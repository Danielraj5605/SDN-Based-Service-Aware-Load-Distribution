#!/usr/bin/env python3
"""Mininet topology for the service-aware load balancer.

    clients h1..h4 ---+                +--- srv1  100 Mbit/s,  2 ms
                      |                +--- srv2  100 Mbit/s, 25 ms
                      +---- s1 (OVS) --+--- srv3   10 Mbit/s,  1 ms
                      |   OpenFlow 1.3 +--- srv4   50 Mbit/s, 10 ms, 1% loss
                 Ryu controller (127.0.0.1:6653)

Everything (addresses, link parameters, ports) comes from config.yaml.

Start the controller first, then:
    sudo python3 topology/sdn_topology.py
"""
import argparse
import os
import time

import yaml
from mininet.cli import CLI
from mininet.link import TCLink
from mininet.log import info, setLogLevel
from mininet.net import Mininet
from mininet.node import OVSSwitch, RemoteController

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_CONFIG = os.path.join(ROOT, 'config.yaml')
RUN_DIR = '/tmp/sdn_lb'

# Process patterns started by start_services(); used to clean them up.
_SERVICE_PATTERNS = ['server_agent.py', 'udp_echo_server.py', 'iperf -s', 'http.server']


def load_config(path=DEFAULT_CONFIG):
    with open(path) as f:
        return yaml.safe_load(f)


def _link_params(link):
    params = {}
    if link.get('bw'):
        params['bw'] = float(link['bw'])
    if link.get('delay'):
        params['delay'] = str(link['delay'])
    if link.get('loss'):
        params['loss'] = float(link['loss'])
    return params


def build_network(cfg):
    net = Mininet(controller=None, switch=OVSSwitch, link=TCLink,
                  autoSetMacs=False, build=False)
    ctrl = cfg['controller']
    net.addController('c0', controller=RemoteController, ip=ctrl['ip'], port=int(ctrl['port']))
    s1 = net.addSwitch('s1', dpid='0000000000000001', protocols='OpenFlow13')

    for srv in cfg['servers']:
        host = net.addHost(srv['name'], ip=srv['ip'] + '/24', mac=srv['mac'])
        net.addLink(host, s1, port2=int(srv['switch_port']), **_link_params(srv.get('link') or {}))
    for cl in cfg['clients']:
        host = net.addHost(cl['name'], ip=cl['ip'] + '/24', mac=cl['mac'])
        net.addLink(host, s1, port2=int(cl['switch_port']))

    net.build()
    return net


def start_services(net, cfg):
    """Start the telemetry agent and the test applications on every server."""
    stats_dir = cfg['monitoring']['agent_stats_dir']
    apps = cfg.get('server_apps') or {}
    os.makedirs(stats_dir, exist_ok=True)
    os.makedirs(os.path.join(RUN_DIR, 'logs'), exist_ok=True)
    for f in os.listdir(stats_dir):             # stale reports from an earlier run
        os.remove(os.path.join(stats_dir, f))

    for srv in cfg['servers']:
        name = srv['name']
        host = net.get(name)
        sim = srv.get('simulate') or {}
        log = os.path.join(RUN_DIR, 'logs', name)

        host.cmd('python3 %s/agent/server_agent.py --name %s --dir %s --extra-cpu %s --extra-mem %s'
                 ' > %s-agent.log 2>&1 &'
                 % (ROOT, name, stats_dir, sim.get('extra_cpu', 0), sim.get('extra_mem', 0), log))
        for port in apps.get('iperf_tcp_ports', []):
            host.cmd('iperf -s -p %d > /dev/null 2>&1 &' % port)
        if apps.get('udp_echo_ports'):
            host.cmd('python3 %s/traffic/udp_echo_server.py --ports %s > %s-udp.log 2>&1 &'
                     % (ROOT, ' '.join(str(p) for p in apps['udp_echo_ports']), log))
        if apps.get('http_port'):
            www = os.path.join(RUN_DIR, 'www', name)
            os.makedirs(www, exist_ok=True)
            with open(os.path.join(www, 'index.html'), 'w') as f:
                f.write('Hello from %s (%s)\n' % (name, srv['ip']))
            host.cmd('python3 -m http.server %d --directory %s > /dev/null 2>&1 &'
                     % (apps['http_port'], www))
    time.sleep(1)


def stop_services():
    # Mininet hosts share one process table, so these patterns find every host's copy.
    for pattern in _SERVICE_PATTERNS:
        os.system("pkill -f '%s' > /dev/null 2>&1" % pattern)


def main():
    ap = argparse.ArgumentParser(description='Service-aware LB topology')
    ap.add_argument('--config', default=DEFAULT_CONFIG)
    ap.add_argument('--no-services', action='store_true', help="don't start agents/test servers")
    args = ap.parse_args()

    setLogLevel('info')
    cfg = load_config(args.config)
    net = build_network(cfg)
    net.start()
    try:
        if not args.no_services:
            info('*** Starting agents and test services on the servers\n')
            start_services(net, cfg)
        vip = cfg['vip']['ip']
        info('\n*** VIP is %s. Try:\n' % vip)
        info('    h1 ping -c 3 %s\n' % vip)
        info('    h1 curl -s %s:%s        (shows which server answered)\n'
             % (vip, (cfg.get('server_apps') or {}).get('http_port', 8080)))
        info('    h1 iperf -c %s -p 2121 -t 10                   (file transfer)\n' % vip)
        info('    h2 python3 %s/traffic/udp_client.py --host %s --port 5060 --duration 10   (VoIP)\n'
             % (ROOT, vip))
        info('    Controller state: python3 %s/tools/lbctl.py status\n\n' % ROOT)
        CLI(net)
    finally:
        stop_services()
        net.stop()


if __name__ == '__main__':
    main()
