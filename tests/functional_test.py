#!/usr/bin/env python3
"""Automated functional tests against the live controller in Mininet.

Covers the scenarios from implementation_plan.md section 9.2 (T1-T10) plus
DSCP classification (T12) and live UDP rebalancing (T13).

    ryu-manager controller/lb_controller.py          # terminal 1
    sudo python3 tests/functional_test.py            # terminal 2 (builds its own network)
    sudo python3 tests/functional_test.py --only T4 T6

Exit code 0 = every selected test passed.
"""
import argparse
import json
import os
import sys
import time
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'topology'))
sys.path.insert(0, os.path.join(ROOT, 'experiments'))

from mininet.log import setLogLevel                                     # noqa: E402

from run_experiment import Rest, wait_for_controller                    # noqa: E402
from sdn_topology import (DEFAULT_CONFIG, build_network, link_params,   # noqa: E402
                          load_config, start_agent, start_services, stop_services)

TCP, UDP = 6, 17
UDP_CLIENT = os.path.join(ROOT, 'traffic', 'udp_client.py')


class Ctx:
    def __init__(self, net, cfg, rest):
        self.net, self.cfg, self.rest = net, cfg, rest
        self.vip = cfg['vip']['ip']
        self.vip_mac = cfg['vip']['mac'].lower()
        self.http_port = (cfg.get('server_apps') or {}).get('http_port', 8080)

    def host(self, name):
        return self.net.get(name)

    def status(self):
        return self.rest('GET', '/lb/status')

    def server(self, name):
        return next(s for s in self.status()['servers'] if s['name'] == name)

    def flow(self, client, proto, dport):
        """Most recent active flow for (client, proto, dst_port), or None."""
        ip = self.host(client).IP()
        flows = [f for f in self.rest('GET', '/lb/flows')
                 if f['client'] == ip and f['proto'] == proto and f['dst_port'] == dport]
        return max(flows, key=lambda f: f['since']) if flows else None

    def udp(self, client, port, duration, rate=50, size=160, dscp=0):
        cmd = ['python3', UDP_CLIENT, '--host', self.vip, '--port', str(port),
               '--duration', str(duration), '--rate', str(rate), '--size', str(size)]
        if dscp:
            cmd += ['--dscp', str(dscp)]
        return self.host(client).popen(cmd)

    def iperf(self, client, port, duration):
        return self.host(client).popen(['iperf', '-c', self.vip, '-p', str(port),
                                        '-t', str(duration), '-y', 'C'])

    def curl(self, client):
        out = self.host(client).cmd('curl -s -m 5 http://%s:%d/' % (self.vip, self.http_port))
        assert 'Hello from' in out, 'no web reply via the VIP (got %r)' % out.strip()[:80]
        return out.split('Hello from', 1)[1].split()[0]

    def wait_until(self, predicate, timeout, step=0.5):
        start = time.time()
        while time.time() - start < timeout:
            if predicate():
                return time.time() - start
            time.sleep(step)
        return None


def udp_result(proc):
    out, _ = proc.communicate(timeout=120)
    lines = [l for l in out.decode('utf-8', 'replace').splitlines() if l.strip()]
    assert lines, 'udp_client produced no output'
    return json.loads(lines[-1])


def stop(proc):
    if proc.poll() is None:
        proc.kill()
    proc.communicate()


# ---------------------------------------------------------------- tests

def t1_arp(c):
    h1 = c.host('h1')
    h1.cmd('ip neigh flush all')
    h1.cmd('ping -c 1 -W 2 %s' % c.vip)
    neigh = h1.cmd('ip neigh show %s' % c.vip).lower()
    assert c.vip_mac in neigh, 'VIP MAC not learned (neigh: %r)' % neigh.strip()
    return 'h1 resolved %s -> %s' % (c.vip, c.vip_mac)


def t2_icmp(c):
    out = c.host('h1').cmd('ping -c 3 -W 2 %s' % c.vip)
    assert ' 0% packet loss' in out, 'ping lost packets:\n' + out
    assert 'from %s' % c.vip in out, 'replies do not come from the VIP'
    return 'ping VIP: 0% loss, replies from VIP'


def t3_http(c):
    seen = [c.curl('h2') for _ in range(6)]
    return '6/6 HTTP requests answered (%s)' % ', '.join(seen)


def t10_round_robin(c):
    c.rest('POST', '/lb/mode', {'mode': 'round_robin'})
    try:
        seen = [c.curl('h3') for _ in range(4)]
    finally:
        c.rest('POST', '/lb/mode', {'mode': 'service_aware'})
    assert len(set(seen)) == 4, 'round robin did not visit all 4 servers: %s' % seen
    return 'RR order: ' + ' -> '.join(seen)


def t4_voip_avoids_loaded_server(c):
    bulk = c.iperf('h1', 2121, 25)
    try:
        time.sleep(6)                               # let port stats see the load
        f = c.flow('h1', TCP, 2121)
        assert f, 'file transfer flow not found'
        loaded = f['server']
        call = c.udp('h2', 5060, 8)
        time.sleep(3)
        v = c.flow('h2', UDP, 5060)
        res = udp_result(call)
    finally:
        stop(bulk)
    assert v, 'VoIP flow not found'
    assert v['server'] != loaded, 'VoIP was placed on the loaded server %s' % loaded
    assert res['rtt_avg_ms'] is not None and res['rtt_avg_ms'] < 30, 'VoIP RTT too high: %s' % res
    return 'file on %s, VoIP on %s, RTT %.2f ms, loss %.1f%%' % (
        loaded, v['server'], res['rtt_avg_ms'], res['loss_pct'])


def t5_video_spread(c):
    a = c.udp('h3', 5004, 8, rate=500, size=1000)
    b = c.udp('h4', 5004, 8, rate=500, size=1000)
    time.sleep(3)
    fa, fb = c.flow('h3', UDP, 5004), c.flow('h4', UDP, 5004)
    ra, rb = udp_result(a), udp_result(b)
    assert fa and fb, 'video flows not found'
    assert 'srv3' not in (fa['server'], fb['server']), 'video placed on the 10 Mbit/s server'
    assert max(ra['loss_pct'], rb['loss_pct']) < 10, 'video loss too high: %s / %s' % (ra, rb)
    return 'videos on %s and %s, loss %.1f%% / %.1f%%' % (
        fa['server'], fb['server'], ra['loss_pct'], rb['loss_pct'])


def t12_dscp(c):
    # Port 5004 is "video", but an EF mark (46) must classify the flow as voip.
    p = c.udp('h4', 5004, 4, dscp=46)
    time.sleep(2)
    f = c.flow('h4', UDP, 5004)
    udp_result(p)
    assert f and f['service'] == 'voip', 'DSCP 46 not classified as voip: %s' % f
    return 'UDP/5004 with DSCP EF classified as %s' % f['service']


def t9_weights(c):
    original = dict(c.status()['weights']['voip'])
    only = {k: 0.0 for k in original}
    try:
        c.rest('POST', '/lb/weights', {'service': 'voip', 'weights': dict(only, bandwidth=1.0)})
        p = c.udp('h1', 5060, 3)
        time.sleep(1.5)
        bw_pick = c.flow('h1', UDP, 5060)['server']
        udp_result(p)

        st = c.status()
        fastest = min((s for s in st['servers'] if s['up']), key=lambda s: s['rtt_ms'])['name']
        c.rest('POST', '/lb/weights', {'service': 'voip', 'weights': dict(only, latency=1.0)})
        p = c.udp('h2', 5060, 3)
        time.sleep(1.5)
        lat_pick = c.flow('h2', UDP, 5060)['server']
        udp_result(p)
    finally:
        c.rest('POST', '/lb/weights', {'service': 'voip', 'weights': original})
    assert bw_pick in ('srv1', 'srv2'), 'bandwidth-only weights picked %s' % bw_pick
    assert lat_pick == fastest, 'latency-only weights picked %s, lowest RTT is %s' % (lat_pick, fastest)
    return 'bandwidth-only -> %s, latency-only -> %s' % (bw_pick, lat_pick)


def t6_t7_failure_and_recovery(c):
    c.net.configLinkStatus('s1', 'srv3', 'down')
    try:
        detect = c.wait_until(lambda: not c.server('srv3')['up'], 10)
        assert detect is not None, 'srv3 was not marked down within 10 s'
        seen = [c.curl('h2') for _ in range(6)]
        assert 'srv3' not in seen, 'traffic still sent to the failed server'
    finally:
        c.net.configLinkStatus('s1', 'srv3', 'up')
    recover = c.wait_until(lambda: c.server('srv3')['up'], 10)
    assert recover is not None, 'srv3 did not come back within 10 s'
    return 'down detected in %.1f s; requests avoided it (%s); back up in %.1f s' % (
        detect, ', '.join(sorted(set(seen))), recover)


def t8_agent_loss(c):
    srv = next(s for s in c.cfg['servers'] if s['name'] == 'srv4')
    os.system("pkill -f 'server_agent.py --name srv4 ' > /dev/null 2>&1")
    try:
        gone = c.wait_until(lambda: not c.server('srv4')['agent_ok'], 15)
        assert gone is not None, 'agent loss not noticed within 15 s'
        s = c.server('srv4')
        assert s['up'], 'server should stay selectable without its agent'
    finally:
        start_agent(c.net, c.cfg, srv)
    back = c.wait_until(lambda: c.server('srv4')['agent_ok'], 10)
    assert back is not None, 'agent did not report again after restart'
    return 'agent silence noticed in %.1f s (server stayed up); reporting again in %.1f s' % (gone, back)


def t13_rebalance(c):
    rb = c.status()['rebalance']
    srv_cfg = {s['name']: s for s in c.cfg['servers']}
    c.rest('POST', '/lb/rebalance', {'enabled': True})
    call = c.udp('h3', 5060, rb['hold_time'] + rb['interval'] * 3 + 12)
    degraded = None
    try:
        time.sleep(2)
        first = c.flow('h3', UDP, 5060)
        assert first, 'VoIP flow not found'
        degraded = first['server']
        # Make the chosen server's link slow (80 ms each way) so its latency score drops.
        params = link_params(srv_cfg[degraded].get('link') or {})
        params['delay'] = '80ms'
        link = c.net.linksBetween(c.host('s1'), c.host(degraded))[0]
        link.intf1.config(**params)
        link.intf2.config(**params)
        moved = c.wait_until(
            lambda: (c.flow('h3', UDP, 5060) or {}).get('server') not in (None, degraded),
            rb['hold_time'] + rb['interval'] * 3 + 5, step=1)
        assert moved is not None, 'flow was not moved off the degraded server %s' % degraded
        new = c.flow('h3', UDP, 5060)['server']
    finally:
        if degraded:
            orig = link_params(srv_cfg[degraded].get('link') or {})
            link = c.net.linksBetween(c.host('s1'), c.host(degraded))[0]
            link.intf1.config(**orig)
            link.intf2.config(**orig)
        c.rest('POST', '/lb/rebalance', {'enabled': rb['enabled']})
    res = udp_result(call)
    return 'call moved %s -> %s after %.0f s without restarting; loss %.1f%%' % (
        degraded, new, moved, res['loss_pct'])


TESTS = [
    ('T1', 'ARP for the VIP', t1_arp),
    ('T2', 'ICMP through the VIP', t2_icmp),
    ('T3', 'Many TCP connections (HTTP)', t3_http),
    ('T10', 'Round robin mode', t10_round_robin),
    ('T4', 'VoIP avoids the loaded server', t4_voip_avoids_loaded_server),
    ('T5', 'Video streams avoid the small link', t5_video_spread),
    ('T12', 'DSCP classification', t12_dscp),
    ('T9', 'Runtime weight change', t9_weights),
    ('T6/T7', 'Server failure and recovery', t6_t7_failure_and_recovery),
    ('T8', 'Agent stops reporting', t8_agent_loss),
    ('T13', 'Live UDP rebalancing', t13_rebalance),
]


def main():
    ap = argparse.ArgumentParser(description='Functional tests for the service-aware LB')
    ap.add_argument('--config', default=DEFAULT_CONFIG)
    ap.add_argument('--only', nargs='+', help='test ids to run, e.g. T4 T6/T7')
    args = ap.parse_args()
    if os.geteuid() != 0:
        sys.exit('run with sudo (Mininet needs root)')

    cfg = load_config(args.config)
    rest = Rest(cfg['controller'].get('rest_url', 'http://127.0.0.1:8080'))
    selected = [t for t in TESTS if not args.only or t[0] in args.only]

    setLogLevel('warning')
    net = build_network(cfg)
    net.start()
    results = []
    try:
        start_services(net, cfg)
        wait_for_controller(rest, len(cfg['servers']))
        c = Ctx(net, cfg, rest)
        rest('POST', '/lb/mode', {'mode': 'service_aware'})
        for tid, name, fn in selected:
            print('[%s] %-38s ...' % (tid, name), end=' ', flush=True)
            started = time.time()
            try:
                detail, outcome = fn(c), 'PASS'
            except AssertionError as e:
                detail, outcome = str(e), 'FAIL'
            except Exception as e:      # noqa: BLE001 - report and keep going
                detail, outcome = '%s: %s' % (type(e).__name__, e), 'ERROR'
                traceback.print_exc()
            print('%s (%.0f s)' % (outcome, time.time() - started))
            results.append((tid, name, outcome, detail))
            time.sleep(2)
    finally:
        stop_services()
        net.stop()

    print('\n' + '=' * 100)
    for tid, name, outcome, detail in results:
        print('%-6s %-5s %-38s %s' % (tid, outcome, name, detail))
    passed = sum(1 for r in results if r[2] == 'PASS')
    print('=' * 100)
    print('%d/%d passed' % (passed, len(results)))
    sys.exit(0 if passed == len(results) else 1)


if __name__ == '__main__':
    main()
