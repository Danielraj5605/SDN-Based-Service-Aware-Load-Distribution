# SDN-Based Service-Aware Load Distribution

A Ryu (OpenFlow 1.3) controller that sends each new flow to the **best server for that
type of traffic**. It does not just pick the next server in turn. It combines the
service type, server health and network conditions into one suitability score.

```
 clients h1..h4 ──► s1 (Open vSwitch) ──► srv1  100 Mbit/s,  2 ms   general purpose
                          │               srv2  100 Mbit/s, 25 ms   far away (bulk)
                          │               srv3   10 Mbit/s,  1 ms   voice
                          ▼               srv4   50 Mbit/s, 10 ms, 1 % loss, busy
                   Ryu controller
       ┌──────────────┬───────────────┬────────────────┐
  Classifier   Network Monitor   Server Monitor   Decision Engine ──► Flow Manager
  (port→svc)   (port stats,      (agent: CPU,     (per-service       (OpenFlow rules
               ICMP probes)       mem, sessions)   weighted score)     VIP ⇄ server)
```

Clients only know the virtual IP **10.0.0.100**.

## How a request is handled

1. The first packet of a new flow reaches the controller (table miss).
2. **Classifier** reads the protocol and destination port and picks a service: video, voip, file or default.
3. **Decision engine** scores every server that is up:
   `Score = w_health·H + w_bandwidth·B + w_latency·L + w_loss·P + w_match·M`. The weights come from that service's profile in `config.yaml`.
4. **Flow manager** installs a forward rule (VIP→server rewrite) and a reverse rule (server→VIP rewrite), then sends the first packet on.
5. Monitoring never stops. Servers that fail 3 probes in a row are marked down, their flows are deleted, and new flows go elsewhere.

| Factor | Source | Meaning |
|---|---|---|
| H health | agent on each server | 1 − weighted (CPU %, memory %, sessions) |
| B bandwidth | OpenFlow port stats every 2 s | available Mbit/s ÷ largest link capacity |
| L latency | ICMP probe from the VIP every 1 s | 1 − RTT ÷ 100 ms |
| P reliability | the same probes | 1 − loss rate over the last 20 probes |
| M match | `services:` list per server | 1 if designated for the service, else 0.3 |

## Project layout

```
config.yaml                    all settings: VIP, servers, links, service ports, weights
controller/lb_controller.py    Ryu app (entry point)
controller/classifier.py       service classification
controller/network_monitor.py  bandwidth / latency / loss
controller/server_monitor.py   reads agent reports
controller/decision_engine.py  suitability score + round robin baseline
controller/flow_manager.py     OpenFlow messages
controller/rest_api.py         REST API (/lb/status, /lb/flows, /lb/mode, /lb/weights)
agent/server_agent.py          runs on each server, reports CPU / memory / sessions
traffic/udp_echo_server.py     UDP echo (VoIP + video tests)
traffic/udp_client.py          paced UDP client: RTT, jitter, loss, throughput
topology/sdn_topology.py       Mininet topology + test services, opens the CLI
experiments/run_experiment.py  Round Robin vs Service-Aware comparison
experiments/plot_results.py    charts from the experiment CSVs
tools/lbctl.py                 command-line client for the REST API
tests/test_logic.py            unit tests (no Mininet/Ryu needed)
```

## Setup (Ubuntu 20.04 VM)

```bash
sudo apt update
sudo apt install -y mininet openvswitch-switch iperf python3-pip python3-yaml python3-psutil
pip3 install -r requirements.txt
echo 'export PATH=$HOME/.local/bin:$PATH' >> ~/.bashrc && source ~/.bashrc
```

Copy this folder into the VM, e.g. `~/sdn-service-lb`, and run every command from inside it.

## Run it

**Terminal 1: controller**
```bash
ryu-manager controller/lb_controller.py
```

**Terminal 2: network**
```bash
sudo python3 topology/sdn_topology.py
```
Then, at the `mininet>` prompt:
```
h1 ping -c 3 10.0.0.100
h1 curl -s 10.0.0.100:8080                       # prints which server answered
h1 iperf -c 10.0.0.100 -p 2121 -t 10              # file transfer
h2 python3 traffic/udp_client.py --host 10.0.0.100 --port 5060 --duration 10   # VoIP call
```

**Terminal 3: watch the controller**
```bash
python3 tools/lbctl.py watch          # live table: health, bandwidth, RTT, loss, score per service
python3 tools/lbctl.py flows          # which flow went to which server
python3 tools/lbctl.py mode rr        # switch to Round Robin (mode sa to switch back)
python3 tools/lbctl.py weights voip latency=0.7
```

Every decision is logged to `logs/decisions.csv`, and per-server metrics to `logs/metrics.csv`.

## Experiment: Round Robin vs Service-Aware

Keep the controller running and exit any open Mininet first (`exit`, then `sudo mn -c`). Then run:

```bash
sudo python3 experiments/run_experiment.py                         # 3 repeats × 2 modes, ~5 min
sudo python3 experiments/run_experiment.py --repeats 1 --duration 10   # quick check
python3 experiments/plot_results.py
```

Each round runs the same mix: 2 file transfers (TCP), 2 video streams (UDP, 4 Mbit/s) and
4 VoIP calls (UDP, 50 pkt/s). The script records VoIP and video RTT, jitter and loss, video and
file throughput, link utilisation per server and Jain's fairness index. It writes:

- `results/flows_<tag>.csv` and `results/rounds_<tag>.csv`: raw data
- `results/plots/comparison_<tag>.png` and `servers_<tag>.png`: charts
- `results/summary_<tag>.csv`: the numbers behind the charts

## Tests

```bash
python3 -m unittest discover -s tests -v
```

## Troubleshooting

| Problem | Fix |
|---|---|
| `ImportError: cannot import name 'ALREADY_HANDLED'` | `pip3 install eventlet==0.30.2` |
| `pip3 install ryu` fails with a setuptools error | `pip3 install "setuptools<58"` then retry |
| Mininet: "file exists" / controller errors | `sudo mn -c` (note: this also kills ryu-manager; restart it) |
| `lbctl` says controller unreachable | is ryu-manager running? REST is on port 8080 |
| Servers stay `up = NO` | the controller must be running before the topology; check `ryu-manager` output |
| `agent = -` in lbctl | the agent logs are in `/tmp/sdn_lb/logs/srvN-agent.log` |

## Limitations

- Drives a single switch. The VIP rewrite happens at that switch.
- In-flight TCP connections are never moved. Only new flows are rebalanced, and flows on a failed server are cleared.
- Agent reports travel through a shared directory, which works because Mininet hosts share one filesystem. On real hardware you would use REST/gRPC instead.
- Tested in Mininet (emulated), not on a physical testbed.
