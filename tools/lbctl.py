#!/usr/bin/env python3
"""Command-line client for the controller's REST API.

    python3 tools/lbctl.py status
    python3 tools/lbctl.py flows
    python3 tools/lbctl.py mode rr            (or: sa / service_aware / round_robin)
    python3 tools/lbctl.py weights voip latency=0.6 bandwidth=0.05
    python3 tools/lbctl.py rebalance on       (or: off) live UDP flow rebalancing
    python3 tools/lbctl.py watch              (refresh status every 2 s)

Web dashboard: http://127.0.0.1:8080/lb/dashboard
"""
import argparse
import json
import sys
import time
import urllib.error
import urllib.request

DEFAULT_URL = 'http://127.0.0.1:8080'


def call(base, method, path, body=None):
    data = json.dumps(body).encode('utf-8') if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method,
                                 headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        sys.exit('error %s: %s' % (e.code, e.read().decode('utf-8', 'replace')))
    except urllib.error.URLError as e:
        sys.exit('cannot reach the controller at %s (%s) - is ryu-manager running?' % (base, e.reason))


def fmt(value, spec='%.1f'):
    return '-' if value is None else spec % value


def print_status(st):
    print('mode: %s   VIP: %s   switch: %s   active flows: %d   decisions: %d'
          % (st['mode'], st['vip'], 'connected' if st['switch_connected'] else 'NOT connected',
             st['active_flows'], st['decisions']))
    d, rb = st['decision_ms'], st['rebalance']
    print('decision time: avg %s ms, p95 %s ms, max %s ms   rebalancing: %s (%d moved)'
          % (fmt(d['avg'], '%.3f'), fmt(d['p95'], '%.3f'), fmt(d['max'], '%.3f'),
             'on' if rb['enabled'] else 'off', rb['migrations']))
    services = list(st['weights'])
    head = ('%-6s %-4s %-5s %6s %6s %5s %6s %9s %8s %6s  '
            % ('server', 'up', 'agent', 'cpu%', 'mem%', 'sess', 'used', 'avail/cap', 'rtt ms', 'loss%'))
    print(head + '  '.join('%7s' % s[:7] for s in services))
    for s in st['servers']:
        row = ('%-6s %-4s %-5s %6s %6s %5d %6s %9s %8s %6s  '
               % (s['name'], 'yes' if s['up'] else 'NO', 'ok' if s['agent_ok'] else '-',
                  fmt(s['cpu']), fmt(s['mem']), s['sessions'], fmt(s['used_mbps']),
                  '%s/%d' % (fmt(s['available_mbps'], '%.0f'), s['capacity_mbps']),
                  fmt(s['rtt_ms'], '%.2f'), fmt(s['loss_pct'])))
        print(row + '  '.join('%7.3f' % s['scores'][svc] for svc in services))


def main():
    ap = argparse.ArgumentParser(description='Service-aware LB control')
    ap.add_argument('--url', default=DEFAULT_URL)
    sub = ap.add_subparsers(dest='cmd', required=True)
    sub.add_parser('status')
    sub.add_parser('flows')
    sub.add_parser('watch')
    p_mode = sub.add_parser('mode')
    p_mode.add_argument('mode')
    p_w = sub.add_parser('weights')
    p_w.add_argument('service')
    p_w.add_argument('pairs', nargs='+', help='factor=value, e.g. latency=0.6')
    p_rb = sub.add_parser('rebalance')
    p_rb.add_argument('state', choices=['on', 'off'])
    args = ap.parse_args()

    if args.cmd == 'status':
        print_status(call(args.url, 'GET', '/lb/status'))
    elif args.cmd == 'watch':
        while True:
            st = call(args.url, 'GET', '/lb/status')
            print('\033[2J\033[H' + time.strftime('%H:%M:%S'))
            print_status(st)
            time.sleep(2)
    elif args.cmd == 'flows':
        flows = call(args.url, 'GET', '/lb/flows')
        print('%-10s %-5s %6s %6s %-8s %-6s' % ('client', 'proto', 'sport', 'dport', 'service', 'server'))
        for f in sorted(flows, key=lambda f: (f['server'], f['client'])):
            print('%-10s %-5s %6s %6s %-8s %-6s' % (
                f['client'], {6: 'tcp', 17: 'udp', 1: 'icmp'}.get(f['proto'], f['proto']),
                f['src_port'] or '-', f['dst_port'] or '-', f['service'], f['server']))
    elif args.cmd == 'mode':
        print(call(args.url, 'POST', '/lb/mode', {'mode': args.mode}))
    elif args.cmd == 'rebalance':
        print(call(args.url, 'POST', '/lb/rebalance', {'enabled': args.state == 'on'}))
    elif args.cmd == 'weights':
        weights = {}
        for pair in args.pairs:
            key, _, value = pair.partition('=')
            weights[key] = float(value)
        print(call(args.url, 'POST', '/lb/weights', {'service': args.service, 'weights': weights}))


if __name__ == '__main__':
    main()
