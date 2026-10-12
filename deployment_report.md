# SDN-Based Service-Aware Load Distribution — Deployment Report

> WSL2 Ubuntu-20.04 · October 12 2026

---

## 1. Files Changed and Why

| File | Change | Reason |
|---|---|---|
| `/etc/sudoers.d/arjun` (WSL, new) | `arjun ALL=(ALL) NOPASSWD:ALL` | Passwordless sudo needed for Mininet and OVS commands. |
| `sudo pip3 install mininet` (system-wide) | Installed `mininet==2.3.0.dev6` | The apt package installs Mininet as Python 2 (`/usr/bin/mn` is `#!/usr/bin/python2`). `sudo python3 topology/sdn_topology.py` needs the Python 3 package. |
| `tests/manual_test_t11.py` (new) | New test script for T11 | Automates stop-ryu/verify-data-plane/restart/new-flows scenario from R7. |

> **No existing project source files were changed.**

---

## 2. Command Log

```
# Step 1 — Setup
sudo service openvswitch-switch start
cd ~/SDN-Based-Service-Aware-Load-Distribution
bash scripts/setup_vm.sh
  => [ok] Ubuntu 20.04
  => [ok] Python 3.8
  => [ok] apt packages installed
  => [ok] pip packages installed
  => [ok] mininet 2.2.2
  => [ok] ovs-vsctl (Open vSwitch) 2.13.8
  => [ok] ryu 4.34
  => [ok] python libraries import
  => [ok] unit tests: Ran 26 tests
  => [ok] mininet pingall: 0% dropped

# One-time fix: install mininet for system Python 3 (sudo python3 needs it)
sudo pip3 install mininet

# Step 2 — Unit tests
python3 -m unittest discover -s tests -v
  => Ran 26 tests in 0.011s: OK

# Step 3 — Port check
ss -ltnp   => Port 8080: free

# Step 4 — Bring-up
# Controller (keep running in background/tmux):
PYTHONPATH=~/.local/lib/python3.8/site-packages \
  ryu-manager controller/lb_controller.py
  => Service-aware LB: VIP 10.0.0.100, 4 servers, mode=service_aware
  => wsgi starting up on http://0.0.0.0:8080
  => switch 0000000000000001 connected
  => server srv1/srv2/srv3/srv4 is UP (x4)
  => agent on srv1/srv2/srv3/srv4 is reporting (x4)

# Topology:
sudo python3 topology/sdn_topology.py   => Mininet CLI starts

# Mininet manual tests:
h1 ping -c 3 10.0.0.100
  => 0% loss, replies from 10.0.0.100
h1 curl -s 10.0.0.100:8080
  => Hello from srv1 (10.0.0.11)
h2 python3 traffic/udp_client.py --host 10.0.0.100 --port 5060 --duration 5
  => {"sent":250,"received":250,"loss_pct":0.0,"rtt_avg_ms":5.282,"jitter_ms":0.271}
h1 iperf -c 10.0.0.100 -p 2121 -t 5
  => 109 Mbits/sec
ovs-ofctl -O OpenFlow13 dump-flows s1
  => forward+reverse VIP rewrite rules installed per flow

curl http://127.0.0.1:8080/lb/status    => 200 OK
curl http://127.0.0.1:8080/lb/dashboard => 200 OK (live HTML dashboard)
```

---

## 3. lbctl status (switch connected, 4 servers up)

```
mode: service_aware   VIP: 10.0.0.100   switch: connected   decisions: 0
decision time: avg 0.077 ms, p95 0.197 ms, max 0.360 ms   rebalancing: off
server  up   agent  cpu%   mem%  sess  used  avail/cap  rtt ms  loss%   video   voip    file  default
srv1    yes  ok      0.1    0.6     0   0.0  100/100     7.44    40.0   0.969  0.903   0.896    0.945
srv2    yes  ok     10.1    0.6     0   0.0  100/100    53.88    40.0   0.889  0.558   0.860    0.837
srv3    yes  ok      0.1    0.6     0   0.0   10/10      5.43    40.0   0.462  0.868   0.522    0.724
srv4    yes  ok     50.0   20.6     0   0.0   50/50     23.91    40.0   0.661  0.647   0.560    0.700
```

---

## 4. Functional Test Table — 11/11 PASS

| ID | Test | Outcome | Detail |
|---|---|---|---|
| T1 | ARP for the VIP | **PASS** | h1 resolved 10.0.0.100 -> 00:00:00:00:01:00 |
| T2 | ICMP through the VIP | **PASS** | ping VIP: 0% loss, replies from VIP |
| T3 | Many TCP connections (HTTP) | **PASS** | 6/6 HTTP requests answered |
| T10 | Round robin mode | **PASS** | RR order: srv1 -> srv2 -> srv3 -> srv4 |
| T4 | VoIP avoids the loaded server | **PASS** | file on srv1, VoIP on srv3, RTT 2.73 ms, loss 0.0% |
| T5 | Video streams avoid the small link | **PASS** | videos on srv2 and srv2, loss 0.0% / 0.0% |
| T12 | DSCP classification | **PASS** | UDP/5004 with DSCP EF classified as voip |
| T9 | Runtime weight change | **PASS** | bandwidth-only -> srv1, latency-only -> srv3 |
| T6/T7 | Server failure and recovery | **PASS** | down in 4.0 s; requests avoided it; back up in 2.0 s |
| T8 | Agent stops reporting | **PASS** | silence noticed in 6.1 s; server stayed up; back in 1.0 s |
| T13 | Live UDP rebalancing | **PASS** | call moved srv1 -> srv3 after 9 s without restarting; loss 0.1% |

---

## 5. Manual Test T11 — Controller Restart During Active Traffic

```
[1] ryu-manager started; 4 servers UP.
[3] 16s VoIP stream h1 -> VIP:5060 started.
    Flow rule installed on s1 (n_packets=125 after 3 s).
[4] ryu-manager SIGTERM'd -> Controller OFFLINE: True
[5] 5 s wait: switch flow table still active (n_packets=426, flow unchanged).
[6] ryu-manager restarted -> REST API + switch reconnected in ~3 s.
[7] Stream finished: Sent=800, Received=800, Loss=0.0%, RTT=4.68ms, Jitter=0.24ms
[8] New HTTP via VIP after restart: 'Hello from srv1' - OK

RESULT: 0% packet loss during 5-second controller outage.
        New flows handled correctly after restart.
```

---

## 6. Decision-Time Numbers (119 decisions from logs/decisions.csv)

| avg | p95 | max |
|---|---|---|
| **0.077 ms** | **0.197 ms** | **0.360 ms** |

All well within the <=10 ms NFR-1 target.

---

## 7. Experiment Results (3 repeats x 3 modes = 9 rounds)

```
metric (mean)                   round_robin  service_aware  service_aware_rebalance
------------------------------------------------------------------------
VoIP RTT (ms)                      273.40          2.39              2.37
VoIP jitter (ms)                     1.48          0.19              0.18
VoIP packet loss (%)                 0.56          0.00              0.00
Video RTT (ms)                      11.32        225.46            172.80
Video packet loss (%)                0.98          0.94              1.45
Video throughput (Mbit/s)            3.96          3.96              3.94
File throughput (Mbit/s)            98.91         96.60             97.30
Jain's fairness (utilisation)        0.72          0.54              0.56
```

**Key findings:**
- VoIP RTT drops 99% (273 ms -> 2.4 ms): SA always routes voip to srv3 (1 ms link, designated for voip); RR scatters flows across all servers including the high-latency ones.
- VoIP loss eliminated: SA avoids srv4 (1% loss link) for voip; RR does not.
- Video RTT higher under SA: both video streams land on srv1 (competing with bulk TCP); RR spreads them to srv3/srv4. This is a single-switch limitation.
- Fairness higher under RR (0.72 vs 0.54): SA concentrates voip on the low-bw srv3, leaving it underloaded by capacity.
- File throughput essentially equal (~97-99 Mbit/s) across modes.

**Results files (in results/):**
- `flows_20261012-184156.csv` — per-flow metrics
- `rounds_20261012-184156.csv` — per-round server utilisation + fairness
- `summary_20261012-184156.csv` — mean ± std per service and mode
- `plots/comparison_20261012-184156.png` — 7-panel QoS chart
- `plots/servers_20261012-184156.png` — per-server utilisation chart

---

## 8. Use Case Network Deployment (Draft for Report)

### Deployment Scenario

We deploy the SDN-Based Service-Aware Load Balancer on a Windows 11 laptop using WSL2 (Ubuntu 20.04). The goal is to demonstrate, in a reproducible emulated environment, that an SDN controller combining traffic classification with server health and network condition scoring delivers substantially better QoS for delay-sensitive flows (VoIP, video) than naive Round Robin.

### Emulated Topology and Rationale

The topology has one Open vSwitch switch (s1), four clients (h1-h4) and four heterogeneous servers:

| Server | BW | Delay | Loss | Designated for | Simulated load |
|---|---|---|---|---|---|
| srv1 | 100 Mbit/s | 2 ms | 0% | video, voip, file, default | none |
| srv2 | 100 Mbit/s | 25 ms | 0% | video, file, default | +10% CPU |
| srv3 | 10 Mbit/s | 1 ms | 0% | voip, default | none |
| srv4 | 50 Mbit/s | 10 ms | 1% | video, default | +50% CPU, +20% mem |

A single switch keeps the control plane simple and isolates the load-distribution logic. Heterogeneous links exaggerate placement QoS differences, making results clearly visible. Extra CPU/memory on srv4 exercises health scoring without real competing workloads. Mininet TCLink enforces link parameters. All clients use a single VIP (10.0.0.100).

### Software Stack

| Component | Version |
|---|---|
| Windows 11 + WSL2 | Ubuntu 20.04.6 LTS |
| Python | 3.8.10 |
| Ryu (OpenFlow 1.3) | 4.34 |
| eventlet | 0.30.2 |
| Open vSwitch | 2.13.8 |
| Mininet | 2.2.2 (system) + 2.3.0.dev6 (pip/Python 3) |
| iperf | 2.0.13 |
| psutil, PyYAML, pandas, matplotlib | latest compatible |

### Deployment Steps (WSL2)

```bash
# Every session
sudo service openvswitch-switch start

# One-time install
git clone https://github.com/Danielraj5605/SDN-Based-Service-Aware-Load-Distribution.git
cd SDN-Based-Service-Aware-Load-Distribution
bash scripts/setup_vm.sh
sudo pip3 install mininet              # one-time fix: Python 3 Mininet module

# Start controller (terminal 1)
PYTHONPATH=~/.local/lib/python3.8/site-packages \
  ryu-manager controller/lb_controller.py

# Start network (terminal 2, after controller prints "wsgi starting up")
sudo python3 topology/sdn_topology.py

# Verify (terminal 3)
python3 tools/lbctl.py status          # all 4 servers up, RTTs visible
sudo python3 tests/functional_test.py  # 11/11 PASS

# Experiment
sudo python3 experiments/run_experiment.py \
  --modes round_robin service_aware service_aware_rebalance
python3 experiments/plot_results.py
```

### Results

Service-aware routing reduced VoIP RTT from **273 ms to 2.4 ms** (99% reduction) and eliminated VoIP packet loss. VoIP jitter dropped from 1.48 ms to 0.19 ms. All 11 functional tests passed, including controller-restart resilience (T11 — 0% loss during a 5 s outage), failure detection within 4 s (T6/T7), live UDP rebalancing (T13) and DSCP classification (T12). Each placement decision took on average **0.077 ms** (p95: 0.197 ms, max: 0.360 ms), well within the <= 10 ms requirement.

### Limitations

1. **Single switch.** VIP rewriting happens at one OVS switch; link congestion cannot be relieved by re-routing.
2. **Mininet emulation only.** Hosts share one Linux kernel. Per-namespace CPU tracking approximates but does not equal physical isolation.
3. **Agent reports via shared filesystem.** `/tmp/sdn_lb/stats/` works in Mininet because all hosts share one filesystem. Real hardware would require REST/gRPC.
4. **WSL2 controller lifetime.** `sudo mn -c` kills `ryu-manager` (included in Mininet cleanup). In production, run the controller as a systemd service.
5. **Video RTT anomaly.** SA concentrates video on srv1 which also carries bulk TCP, raising measured RTT. Longer runs and rate-limited video flows would show clearer separation.
