#!/usr/bin/env python3
"""Runs the same traffic mix under Round Robin and Service-Aware modes and records the results.

The Ryu controller must already be running (ryu-manager controller/lb_controller.py).
This script builds its own Mininet network, so close any other Mininet first.

    sudo python3 experiments/run_experiment.py
    sudo python3 experiments/run_experiment.py --repeats 1 --duration 10     (quick check)

Writes results/flows_<tag>.csv (one row per flow) and results/rounds_<tag>.csv
(one row per round: utilisation per server, fairness, assignments).
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

from mininet.log import setLogLevel                                     # noqa: E402

from sdn_topology import (DEFAULT_CONFIG, build_network, load_config,   # noqa: E402
                          start_services, stop_services)

RESULTS_DIR = os.path.join(ROOT, 'results')
PROTO = {'iperf': 6, 'udp': 17}
FLOW_FIELDS = ['round', 'mode', 'client', 'service', 'tool', 'dst_port', 'server',
               'throughput_mbps', 'rtt_avg_ms', 'rtt_p95_ms', 'jitter_ms', 'loss_pct', 'error']


def log(msg):
    print('[%s] %s' % (time.strftime('%H:%M:%S'), msg), flush=True)


class Rest:
    def __init__(self, base):
        self.base = base.rstrip('/')

    def __call__(self, method, path, body=None):
        data = json.dumps(body).encode('utf-8') if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method,
                                     headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode('utf-8'))


def wait_for_controller(rest, n_servers, timeout=60):
    log('waiting for the controller to see the switch and all servers ...')
    deadline = time.time() + timeout
    st = None
    while time.time() < deadline:
        try:
            st = rest('GET', '/lb/status')
            up = sum(1 for s in st['servers'] if s['up'])
            agents = sum(1 for s in st['servers'] if s['agent_ok'])
            if st['switch_connected'] and up == n_servers and agents == n_servers:
                log('controller ready: %d servers up, %d agents reporting' % (up, agents))
                return
        except OSError:
            pass
        time.sleep(2)
    if st is None:
        sys.exit('controller REST API not reachable - start ryu-manager first')
    log('WARNING: not every server/agent is ready; continuing anyway')


def jain(values):
    values = [v for v in values if v is not None]
    if not values or sum(v * v for v in values) == 0:
        return None
    return sum(values) ** 2 / (len(values) * sum(v * v for v in values))


def flow_command(item, vip, duration):
    if item['tool'] == 'iperf':
        return ['iperf', '-c', vip, '-p', str(item['port']), '-t', str(duration), '-y', 'C']
    return ['python3', os.path.join(ROOT, 'traffic', 'udp_client.py'), '--host', vip,
            '--port', str(item['port']), '--rate', str(item.get('rate', 50)),
            '--size', str(item.get('size', 160)), '--duration', str(duration)]


def parse_output(tool, out):
    """Return a dict of metrics, or {'error': ...}."""
    lines = [l for l in out.strip().splitlines() if l.strip()]
    if not lines:
        return {'error': 'no output'}
    try:
        if tool == 'iperf':
            # CSV: time,src,sport,dst,dport,id,interval,bytes,bits_per_second
            return {'throughput_mbps': round(float(lines[-1].split(',')[-1]) / 1e6, 3)}
        res = json.loads(lines[-1])
        return {k: res.get(k) for k in ('throughput_mbps', 'rtt_avg_ms', 'rtt_p95_ms',
                                        'jitter_ms', 'loss_pct')}
    except (ValueError, IndexError):
        return {'error': lines[-1][:200]}


def run_round(net, cfg, rest, mode, round_no, duration, settle):
    vip = cfg['vip']['ip']
    mix = cfg['experiment']['mix']
    rest('POST', '/lb/mode', {'mode': mode})
    log('round %d: mode=%s - letting old flows expire (%ds)' % (round_no, mode, settle))
    time.sleep(settle)

    before = rest('GET', '/lb/status')
    t0 = time.time()
    procs = []
    for item in sorted(mix, key=lambda m: m.get('start', 0)):
        wait = t0 + float(item.get('start', 0)) - time.time()
        if wait > 0:
            time.sleep(wait)
        host = net.get(item['client'])
        procs.append((item, host, host.popen(flow_command(item, vip, duration))))
    log('round %d: %d flows running' % (round_no, len(procs)))

    time.sleep(min(3, duration / 2.0))
    placement = {(f['client'], f['proto'], f['dst_port']): f['server']
                 for f in rest('GET', '/lb/flows')}

    rows = []
    for item, host, proc in procs:
        try:
            out, err = proc.communicate(timeout=duration + 60)
        except Exception:
            proc.kill()
            out, err = proc.communicate()
        metrics = parse_output(item['tool'], out.decode('utf-8', 'replace'))
        if 'error' in metrics and err:
            metrics['error'] += ' | ' + err.decode('utf-8', 'replace').strip()[:200]
        row = {'round': round_no, 'mode': mode, 'client': item['client'],
               'service': item['service'], 'tool': item['tool'], 'dst_port': item['port'],
               'server': placement.get((host.IP(), PROTO[item['tool']], item['port']), '?')}
        row.update(metrics)
        rows.append(row)

    after = rest('GET', '/lb/status')
    round_row = {'round': round_no, 'mode': mode}
    utils = []
    for b, a in zip(before['servers'], after['servers']):
        dt = (a['port_sample_time'] or 0) - (b['port_sample_time'] or 0)
        moved = max(a['tx_bytes'] - b['tx_bytes'], a['rx_bytes'] - b['rx_bytes'])
        mbps = moved * 8 / dt / 1e6 if dt > 0 else 0.0
        util = mbps / a['capacity_mbps']
        utils.append(util)
        round_row['util_%s' % a['name']] = round(util, 4)
        round_row['flows_%s' % a['name']] = a['assigned_total'] - b['assigned_total']
    fairness = jain(utils)
    round_row['fairness'] = None if fairness is None else round(fairness, 4)
    return rows, round_row


def mean(values):
    values = [float(v) for v in values if v not in (None, '')]
    return sum(values) / len(values) if values else None


def print_summary(flow_rows, round_rows, modes):
    print('\n' + '=' * 78)
    print('%-34s' % 'metric (mean)' + ''.join('%20s' % m for m in modes))
    print('-' * 78)
    metrics = [('voip', 'rtt_avg_ms', 'VoIP RTT (ms)'), ('voip', 'jitter_ms', 'VoIP jitter (ms)'),
               ('voip', 'loss_pct', 'VoIP loss (%)'), ('video', 'rtt_avg_ms', 'Video RTT (ms)'),
               ('video', 'loss_pct', 'Video loss (%)'),
               ('video', 'throughput_mbps', 'Video throughput (Mbit/s)'),
               ('file', 'throughput_mbps', 'File throughput (Mbit/s)')]
    for service, key, label in metrics:
        vals = [mean(r.get(key) for r in flow_rows if r['mode'] == m and r['service'] == service)
                for m in modes]
        print('%-34s' % label + ''.join('%20s' % ('-' if v is None else '%.3f' % v) for v in vals))
    vals = [mean(r['fairness'] for r in round_rows if r['mode'] == m) for m in modes]
    print('%-34s' % "Jain's fairness (utilisation)"
          + ''.join('%20s' % ('-' if v is None else '%.3f' % v) for v in vals))
    print('=' * 78)


def write_csv(path, rows, fields):
    with open(path, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
        w.writeheader()
        w.writerows(rows)


def give_back_to_sudo_user(path):
    """We run under sudo; hand results/ back to the real user so plotting works without sudo."""
    uid, gid = os.environ.get('SUDO_UID'), os.environ.get('SUDO_GID')
    if not uid:
        return
    for dirpath, _, files in os.walk(path):
        for p in [dirpath] + [os.path.join(dirpath, f) for f in files]:
            os.chown(p, int(uid), int(gid))


def main():
    ap = argparse.ArgumentParser(description='Round Robin vs Service-Aware comparison')
    ap.add_argument('--config', default=DEFAULT_CONFIG)
    ap.add_argument('--modes', nargs='+', default=['round_robin', 'service_aware'])
    ap.add_argument('--repeats', type=int)
    ap.add_argument('--duration', type=int)
    args = ap.parse_args()

    if os.geteuid() != 0:
        sys.exit('run with sudo (Mininet needs root)')
    cfg = load_config(args.config)
    exp = cfg['experiment']
    repeats = args.repeats or int(exp.get('repeats', 3))
    duration = args.duration or int(exp.get('duration', 20))
    settle = int(exp.get('settle_time', 12))
    rest = Rest(cfg['controller'].get('rest_url', 'http://127.0.0.1:8080'))

    setLogLevel('warning')
    net = build_network(cfg)
    net.start()
    flow_rows, round_rows = [], []
    original_mode = None
    try:
        start_services(net, cfg)
        wait_for_controller(rest, len(cfg['servers']))
        original_mode = rest('GET', '/lb/status')['mode']
        round_no = 0
        for rep in range(repeats):
            # Alternate the order so neither mode always runs first.
            for mode in (args.modes if rep % 2 == 0 else list(reversed(args.modes))):
                round_no += 1
                rows, rr = run_round(net, cfg, rest, mode, round_no, duration, settle)
                flow_rows.extend(rows)
                round_rows.append(rr)
                for r in rows:
                    log('  %-3s %-6s -> %-5s %s' % (r['client'], r['service'], r['server'],
                        ' '.join('%s=%s' % (k, r[k]) for k in FLOW_FIELDS[7:] if r.get(k) is not None)))
    finally:
        if original_mode:
            try:
                rest('POST', '/lb/mode', {'mode': original_mode})
            except OSError:
                pass
        stop_services()
        net.stop()

    os.makedirs(RESULTS_DIR, exist_ok=True)
    tag = time.strftime('%Y%m%d-%H%M%S')
    write_csv(os.path.join(RESULTS_DIR, 'flows_%s.csv' % tag), flow_rows, FLOW_FIELDS)
    round_fields = ['round', 'mode', 'fairness'] + sorted(
        k for k in round_rows[0] if k.startswith(('util_', 'flows_'))) if round_rows else []
    write_csv(os.path.join(RESULTS_DIR, 'rounds_%s.csv' % tag), round_rows, round_fields)
    give_back_to_sudo_user(RESULTS_DIR)
    print_summary(flow_rows, round_rows, args.modes)
    log('results written to results/flows_%s.csv and results/rounds_%s.csv' % (tag, tag))
    log('plot them with: python3 experiments/plot_results.py')


if __name__ == '__main__':
    main()
