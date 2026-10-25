#!/usr/bin/env python3
"""Mid-run degradation scenario experiment.

Wave 1 at t=0s: 2 file transfers + 2 video streams + 4 VoIP calls (each 20 s).
At t=8s:        degrade srv3 link (add 80 ms delay + 3% loss).
Wave 2 at t=10s: 4 more VoIP calls (15 s each).
Total run ~25 s.

Modes: round_robin, service_aware, service_aware_rebalance  (3 repeats each).
Reports VoIP pass-rate for wave-1, wave-2, overall, and mean RTT during degradation.

Usage:
    sudo python3 experiments/run_degradation.py
    sudo python3 experiments/run_degradation.py --repeats 1   # quick smoke test
    sudo python3 experiments/run_degradation.py --modes round_robin service_aware

Writes results/degradation_<tag>.csv
"""
import argparse
import csv
import json
import os
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'topology'))
sys.path.insert(0, os.path.join(ROOT, 'experiments'))

from mininet.log import setLogLevel                                     # noqa: E402
from run_experiment import Rest, wait_for_controller                    # noqa: E402
from sdn_topology import (DEFAULT_CONFIG, build_network, link_params,  # noqa: E402
                          load_config, start_services, stop_services)

RESULTS_DIR = os.path.join(ROOT, 'results')
UDP_CLIENT = os.path.join(ROOT, 'traffic', 'udp_client.py')

# Thresholds fixed before running (same as quality_report.py)
VOIP_RTT_MS   = 150
VOIP_JIT_MS   = 30
VOIP_LOSS_PCT = 1.0

# Degradation parameters (fixed before running)
DEGRADE_SERVER = 'srv3'
DEGRADE_DELAY  = '80ms'
DEGRADE_LOSS   = 3.0        # percent


def log(msg):
    print('[%s] %s' % (time.strftime('%H:%M:%S'), msg), flush=True)


def parse_udp(out):
    lines = [line for line in out.strip().splitlines() if line.strip()]
    if not lines:
        return {'error': 'no output'}
    try:
        return json.loads(lines[-1])
    except ValueError:
        return {'error': lines[-1][:200]}


def voip_pass(r):
    if r is None:
        return None
    rtt = r.get('rtt_avg_ms')
    jit = r.get('jitter_ms')
    los = r.get('loss_pct')
    if None in (rtt, jit, los):
        return None
    return rtt <= VOIP_RTT_MS and jit <= VOIP_JIT_MS and los <= VOIP_LOSS_PCT


def degrade_link(net, cfg, server_name, delay, loss):
    """Apply tc netem delay+loss to the switch<->server link on both interfaces."""
    srv_cfg = {s['name']: s for s in cfg['servers']}
    params = link_params(srv_cfg[server_name].get('link') or {})
    params['delay'] = delay
    params['loss']  = loss
    link = net.linksBetween(net.get('s1'), net.get(server_name))[0]
    link.intf1.config(**params)
    link.intf2.config(**params)
    log('Degraded %s link: +%s delay, +%.0f%% loss' % (server_name, delay, loss))


def restore_link(net, cfg, server_name):
    """Restore original link parameters."""
    srv_cfg = {s['name']: s for s in cfg['servers']}
    params = link_params(srv_cfg[server_name].get('link') or {})
    link = net.linksBetween(net.get('s1'), net.get(server_name))[0]
    link.intf1.config(**params)
    link.intf2.config(**params)
    log('Restored %s link to original parameters' % server_name)


def placement_map(rest, proto=17):
    """Return dict  (client_ip, proto, dport) -> server_name."""
    return {(f['client'], f['proto'], f['dst_port']): f['server']
            for f in rest('GET', '/lb/flows') if f['proto'] == proto}


def run_round(net, cfg, rest, mode, round_no):
    vip = cfg['vip']['ip']
    rebalance = mode == 'service_aware_rebalance'
    actual_mode = 'service_aware' if rebalance else mode
    rest('POST', '/lb/mode', {'mode': actual_mode})
    rest('POST', '/lb/rebalance', {'enabled': rebalance})

    settle = int(cfg['experiment'].get('settle_time', 12))
    log('round %d  mode=%s  settling %ds' % (round_no, mode, settle))
    time.sleep(settle)

    WAVE1_DURATION = 20
    DEGRADE_AT     = 8   # seconds after wave 1 starts
    WAVE2_START    = 10  # seconds after wave 1 starts
    WAVE2_DURATION = 15

    # Wave 1 flows
    w1_defs = [
        {'client': 'h1', 'service': 'file',  'tool': 'iperf', 'port': 2121},
        {'client': 'h2', 'service': 'file',  'tool': 'iperf', 'port': 2121},
        {'client': 'h3', 'service': 'video', 'tool': 'udp',   'port': 5004, 'rate': 500, 'size': 1000},
        {'client': 'h4', 'service': 'video', 'tool': 'udp',   'port': 5004, 'rate': 500, 'size': 1000},
        {'client': 'h1', 'service': 'voip',  'tool': 'udp',   'port': 5060, 'rate': 50,  'size': 160},
        {'client': 'h2', 'service': 'voip',  'tool': 'udp',   'port': 5060, 'rate': 50,  'size': 160},
        {'client': 'h3', 'service': 'voip',  'tool': 'udp',   'port': 5060, 'rate': 50,  'size': 160},
        {'client': 'h4', 'service': 'voip',  'tool': 'udp',   'port': 5060, 'rate': 50,  'size': 160},
    ]

    t0 = time.time()
    procs1 = []
    for d in w1_defs:
        host = net.get(d['client'])
        if d['tool'] == 'iperf':
            cmd = ['iperf', '-c', vip, '-p', str(d['port']),
                   '-t', str(WAVE1_DURATION), '-y', 'C']
        else:
            cmd = ['python3', UDP_CLIENT, '--host', vip,
                   '--port', str(d['port']), '--rate', str(d.get('rate', 50)),
                   '--size', str(d.get('size', 160)), '--duration', str(WAVE1_DURATION)]
        procs1.append((d, host.popen(cmd)))

    log('Wave 1 started (%d flows)' % len(procs1))

    # Snapshot placements ~2 s after start
    time.sleep(min(2, DEGRADE_AT / 2))
    pm_pre = placement_map(rest)

    # Wait until degradation moment
    elapsed = time.time() - t0
    wait = max(0, DEGRADE_AT - elapsed)
    if wait > 0:
        time.sleep(wait)

    degrade_link(net, cfg, DEGRADE_SERVER, DEGRADE_DELAY, DEGRADE_LOSS)

    # Wave 2 flows
    elapsed = time.time() - t0
    wait = max(0, WAVE2_START - elapsed)
    if wait > 0:
        time.sleep(wait)

    w2_defs = [
        {'client': 'h1', 'service': 'voip', 'tool': 'udp', 'port': 5060, 'rate': 50, 'size': 160},
        {'client': 'h2', 'service': 'voip', 'tool': 'udp', 'port': 5060, 'rate': 50, 'size': 160},
        {'client': 'h3', 'service': 'voip', 'tool': 'udp', 'port': 5060, 'rate': 50, 'size': 160},
        {'client': 'h4', 'service': 'voip', 'tool': 'udp', 'port': 5060, 'rate': 50, 'size': 160},
    ]
    procs2 = []
    for d in w2_defs:
        host = net.get(d['client'])
        cmd = ['python3', UDP_CLIENT, '--host', vip,
               '--port', str(d['port']), '--rate', str(d.get('rate', 50)),
               '--size', str(d.get('size', 160)), '--duration', str(WAVE2_DURATION)]
        procs2.append((d, host.popen(cmd)))

    log('Wave 2 started (%d new VoIP calls)' % len(procs2))

    # Snapshot placements after degradation
    time.sleep(2)
    pm_post = placement_map(rest)

    # Collect wave 1 results
    rows = []
    for d, proc in procs1:
        try:
            out, err = proc.communicate(timeout=WAVE1_DURATION + 30)
        except Exception:
            proc.kill()
            out, err = proc.communicate()
        out_str = out.decode('utf-8', 'replace')
        if d['tool'] == 'iperf':
            lines = [line for line in out_str.strip().splitlines() if line.strip()]
            try:
                metrics = {'throughput_mbps': round(float(lines[-1].split(',')[-1]) / 1e6, 3)}
            except (ValueError, IndexError):
                metrics = {'error': 'parse failed'}
        else:
            metrics = parse_udp(out_str)
        host = net.get(d['client'])
        key = (host.IP(), 17, d['port'])
        server_pre = pm_pre.get(key, '?')
        server_post = pm_post.get(key, server_pre)
        row = {'round': round_no, 'mode': mode, 'wave': 1,
               'client': d['client'], 'service': d['service'],
               'server_pre': server_pre, 'server_post': server_post,
               'migrated': server_pre != server_post and server_pre != '?'}
        row.update(metrics)
        rows.append(row)

    # Collect wave 2 results
    for d, proc in procs2:
        try:
            out, err = proc.communicate(timeout=WAVE2_DURATION + 30)
        except Exception:
            proc.kill()
            out, err = proc.communicate()
        metrics = parse_udp(out.decode('utf-8', 'replace'))
        host = net.get(d['client'])
        key = (host.IP(), 17, d['port'])
        server_post = pm_post.get(key, '?')
        row = {'round': round_no, 'mode': mode, 'wave': 2,
               'client': d['client'], 'service': d['service'],
               'server_pre': server_post, 'server_post': server_post, 'migrated': False}
        row.update(metrics)
        rows.append(row)

    restore_link(net, cfg, DEGRADE_SERVER)
    return rows


def print_summary(all_rows, modes):
    print('\n' + '=' * 78)
    print('Degradation Scenario  (srv3 degraded at t=8s: +80ms delay +3%% loss)')
    print('%-34s' % 'metric' + ''.join('%22s' % m for m in modes))
    print('-' * (34 + 22 * len(modes)))

    def pct_pass(m_rows, wave):
        voip_rows = [r for r in m_rows if r.get('service') == 'voip'
                     and r.get('wave') == wave]
        results = [voip_pass(r) for r in voip_rows]
        results = [r for r in results if r is not None]
        if not results:
            return '-'
        return '%d/%d (%.0f%%)' % (sum(results), len(results),
                                   100.0 * sum(results) / len(results))

    def mean_rtt(m_rows, wave):
        voip_rows = [r for r in m_rows if r.get('service') == 'voip'
                     and r.get('wave') == wave]
        rtts = [r.get('rtt_avg_ms') for r in voip_rows if r.get('rtt_avg_ms') is not None]
        return '-' if not rtts else '%.1f ms' % (sum(rtts) / len(rtts))

    def migrated(m_rows):
        voip_rows = [r for r in m_rows if r.get('service') == 'voip'
                     and r.get('wave') == 1]
        n = len(voip_rows)
        m = sum(1 for r in voip_rows if r.get('migrated'))
        if n == 0:
            return '-'
        return '%d/%d' % (m, n)

    for label, fn in [
        ('VoIP pass (wave 1, pre-degrade)',
            lambda rows: pct_pass(rows, 1)),
        ('VoIP pass (wave 2, post-degrade)',
            lambda rows: pct_pass(rows, 2)),
        ('VoIP mean RTT (wave 1)',
            lambda rows: mean_rtt(rows, 1)),
        ('VoIP mean RTT (wave 2)',
            lambda rows: mean_rtt(rows, 2)),
        ('Calls migrated off srv3 (wave 1)',
            lambda rows: migrated(rows)),
    ]:
        vals = [fn([r for r in all_rows if r['mode'] == m]) for m in modes]
        print('%-34s' % label + ''.join('%22s' % v for v in vals))
    print('=' * 78)


def write_csv(path, rows):
    if not rows:
        return
    fields = ['round', 'mode', 'wave', 'client', 'service',
              'server_pre', 'server_post', 'migrated',
              'throughput_mbps', 'rtt_avg_ms', 'rtt_p95_ms', 'jitter_ms', 'loss_pct', 'error']
    with open(path, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
        w.writeheader()
        w.writerows(rows)


def main():
    ap = argparse.ArgumentParser(description='Mid-run degradation scenario')
    ap.add_argument('--config', default=DEFAULT_CONFIG)
    ap.add_argument('--modes', nargs='+',
                    default=['round_robin', 'service_aware', 'service_aware_rebalance'])
    ap.add_argument('--repeats', type=int, default=3)
    args = ap.parse_args()

    if os.geteuid() != 0:
        sys.exit('run with sudo (Mininet needs root)')

    cfg = load_config(args.config)
    rest = Rest(cfg['controller'].get('rest_url', 'http://127.0.0.1:8080'))

    setLogLevel('warning')
    net = build_network(cfg)
    net.start()
    all_rows = []
    original_mode = original_rebalance = None
    try:
        start_services(net, cfg)
        wait_for_controller(rest, len(cfg['servers']))
        status = rest('GET', '/lb/status')
        original_mode = status['mode']
        original_rebalance = status['rebalance']['enabled']

        round_no = 0
        for rep in range(args.repeats):
            ordered = args.modes if rep % 2 == 0 else list(reversed(args.modes))
            for mode in ordered:
                round_no += 1
                rows = run_round(net, cfg, rest, mode, round_no)
                all_rows.extend(rows)
                for r in rows:
                    if r.get('service') == 'voip':
                        log('  w%d %-3s voip  srv=%s->%s  rtt=%s ms  loss=%s%%  migrated=%s' % (
                            r['wave'], r['client'],
                            r.get('server_pre', '?'), r.get('server_post', '?'),
                            r.get('rtt_avg_ms', '?'), r.get('loss_pct', '?'),
                            r.get('migrated', '-')))
    finally:
        if original_mode:
            try:
                rest('POST', '/lb/mode', {'mode': original_mode})
                rest('POST', '/lb/rebalance', {'enabled': original_rebalance})
            except OSError:
                pass
        stop_services()
        net.stop()

    os.makedirs(RESULTS_DIR, exist_ok=True)
    tag = time.strftime('%Y%m%d-%H%M%S')
    out_path = os.path.join(RESULTS_DIR, 'degradation_%s.csv' % tag)
    write_csv(out_path, all_rows)

    uid, gid = os.environ.get('SUDO_UID'), os.environ.get('SUDO_GID')
    if uid:
        for dirpath, _, files in os.walk(RESULTS_DIR):
            for p in [dirpath] + [os.path.join(dirpath, f) for f in files]:
                try:
                    os.chown(p, int(uid), int(gid))
                except OSError:
                    pass

    print_summary(all_rows, args.modes)
    log('results written to %s' % out_path)


if __name__ == '__main__':
    main()
