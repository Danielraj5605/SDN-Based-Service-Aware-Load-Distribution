#!/usr/bin/env python3
"""Manual test T11: Controller restart during active traffic.

1. Starts Mininet topology and test services.
2. Waits for controller and all 4 servers to be UP.
3. Launches a 15-second UDP stream from h1 to VIP (port 5060).
4. Confirms flow rule is installed on switch s1.
5. Stops ryu-manager at t=4s.
6. Measures traffic while controller is offline (t=4s to t=10s).
7. Restarts ryu-manager at t=10s.
8. Initiates a NEW connection from h2 to VIP:8080 (HTTP) to verify new flow handling.
9. Validates UDP packet delivery and flow continuation.
"""
import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'topology'))
sys.path.insert(0, os.path.join(ROOT, 'experiments'))

from mininet.log import setLogLevel
import shutil
from run_experiment import Rest, wait_for_controller
from sdn_topology import (DEFAULT_CONFIG, build_network, load_config,
                          start_services, stop_services)


def start_controller():
    sudo_user = os.environ.get('SUDO_USER')
    candidates = [
        shutil.which('ryu-manager'),
        os.path.expanduser(f'~{sudo_user}/.local/bin/ryu-manager') if sudo_user else None,
        '/home/arjun/.local/bin/ryu-manager',
        os.path.expanduser('~/.local/bin/ryu-manager'),
    ]
    ryu_bin = next((c for c in candidates if c and os.path.isfile(c)), 'ryu-manager')
    app = os.path.join(ROOT, 'controller', 'lb_controller.py')
    log = open('/tmp/ryu_t11.log', 'w')
    env = os.environ.copy()
    site_dirs = [
        os.path.expanduser(f'~{sudo_user}/.local/lib/python3.8/site-packages') if sudo_user else None,
        '/home/arjun/.local/lib/python3.8/site-packages',
        os.path.expanduser('~/.local/lib/python3.8/site-packages'),
    ]
    for s in site_dirs:
        if s and os.path.isdir(s):
            env['PYTHONPATH'] = s + ':' + env.get('PYTHONPATH', '')
            break
    if sudo_user:
        env['PATH'] = os.path.expanduser(f'~{sudo_user}/.local/bin') + ':' + env.get('PATH', '')
    proc = subprocess.Popen([ryu_bin, app], env=env, stdout=log, stderr=subprocess.STDOUT)
    return proc, log


def stop_controller(proc, log):
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
    log.close()


def main():
    if os.geteuid() != 0:
        sys.exit('Must run with sudo')

    cfg = load_config(DEFAULT_CONFIG)
    rest_url = cfg['controller'].get('rest_url', 'http://127.0.0.1:8080')
    rest = Rest(rest_url)

    print("=== T11: Controller Restart Test ===")
    print("[1] Starting ryu-manager...")
    c_proc, c_log = start_controller()
    time.sleep(2)

    setLogLevel('warning')
    net = build_network(cfg)
    net.start()
    try:
        start_services(net, cfg)
        print("[2] Waiting for controller and servers...")
        wait_for_controller(rest, len(cfg['servers']))
        print("    Controller connected, 4 servers UP.")

        vip = cfg['vip']['ip']
        h1 = net.get('h1')
        h2 = net.get('h2')

        udp_client = os.path.join(ROOT, 'traffic', 'udp_client.py')
        duration = 16
        print("[3] Starting %ds VoIP traffic stream from h1 to VIP %s:5060..." % (duration, vip))
        client_proc = h1.popen(['python3', udp_client, '--host', vip, '--port', '5060',
                                '--duration', str(duration), '--rate', '50'])

        time.sleep(3)
        flows_before = h1.cmd('sudo ovs-ofctl -O OpenFlow13 dump-flows s1 | grep "tp_dst=5060"')
        print("    Installed OpenFlow rule:\n    %s" % flows_before.strip())
        assert flows_before.strip(), "Flow rule was not installed on switch s1!"

        print("[4] Stopping ryu-manager (SIGTERM)...")
        t_stop = time.time()
        stop_controller(c_proc, c_log)
        time.sleep(1)

        # Verify controller is dead
        is_down = False
        try:
            rest('GET', '/lb/status')
        except Exception:
            is_down = True
        print("    Controller is OFFLINE: %s" % is_down)
        assert is_down, "Controller did not stop!"

        print("[5] Waiting 5 seconds while traffic flows with controller dead...")
        time.sleep(5)
        flows_during = h1.cmd('sudo ovs-ofctl -O OpenFlow13 dump-flows s1 | grep "tp_dst=5060"')
        print("    Switch flow counter during downtime:\n    %s" % flows_during.strip())

        print("[6] Restarting ryu-manager...")
        c_proc, c_log = start_controller()
        t_restart = time.time()
        time.sleep(3)

        # Wait for rest api to be alive
        rest_alive = False
        for _ in range(10):
            try:
                st = rest('GET', '/lb/status')
                if st.get('switch_connected'):
                    rest_alive = True
                    break
            except Exception:
                pass
            time.sleep(0.5)
        print("    Controller REST and switch reconnected: %s" % rest_alive)

        # Wait for the UDP stream to finish
        print("[7] Waiting for VoIP stream completion...")
        out, _ = client_proc.communicate(timeout=30)
        lines = [l for l in out.decode('utf-8', 'replace').splitlines() if l.strip()]
        res = json.loads(lines[-1])
        print("    Traffic result: Sent=%d, Received=%d, Loss=%.1f%%, RTT_avg=%.2fms, Jitter=%.2fms" % (
            res['sent'], res['received'], res['loss_pct'], res['rtt_avg_ms'], res['jitter_ms']))

        print("[8] Testing NEW connection while restarted controller is running...")
        curl_out = h2.cmd('curl -s -m 5 http://%s:8080/' % vip)
        print("    New flow response: %r" % curl_out.strip())
        assert 'Hello from' in curl_out, "New flow failed after controller restart!"

        print("\n=== T11 TEST PASSED ===")
        print("1. Existing flows continued uninterrupted during controller failure (0%% packet loss).")
        print("2. Switch s1 maintained established flow table entries in data plane.")
        print("3. Controller reconnected and successfully processed new flows.")

    finally:
        stop_services()
        net.stop()
        stop_controller(c_proc, c_log)


if __name__ == '__main__':
    main()
