# Implementation Plan: SDN-Based Service-Aware Load Distribution

**Course area:** Software Defined Networking and Network Management  
**Team:** Arjun, Danielraj, Madankumar  
**Code location:** `sdn-service-lb/` (this folder)  
**Repository:** https://github.com/Danielraj5605/SDN-Based-Service-Aware-Load-Distribution  
**Status (7 Oct 2026):** All code is written and pushed. Nothing has run in the Ubuntu VM yet. See section 0 for exactly what is done and what remains.

---

## 0. Implementation status at a glance

**How each part has been checked so far:**
- **Unit-tested:** covered by `tests/test_logic.py` (26 tests, all passing).
- **Static-checked:** pyflakes found no undefined names, typos or unused imports; every file is valid Python 3.8 syntax.
- **Mock-tested:** run against a fake controller on Windows.
- **Not run yet:** needs the Ubuntu VM (Ryu and Mininet only run on Linux).

### 0.1 Done ✅

| Area | What is implemented | Files | Checked so far |
|---|---|---|---|
| Configuration | VIP, 4 heterogeneous servers, links, service ports, weights, DSCP map, rebalance settings, experiment mix; validation with clear errors | `config.yaml`, `controller/config_loader.py` | Unit-tested |
| Service classification | Port/range-based (TCP/UDP); DSCP marks override ports; ICMP and anything else → default | `controller/classifier.py` | Unit-tested |
| Network monitoring | Bandwidth from OpenFlow port stats (EWMA); RTT and loss from ICMP probes injected at the VIP; down after 3 missed probes | `controller/network_monitor.py`, `controller/packets.py` | Unit-tested (logic); packet I/O not run yet |
| Server monitoring | Per-host agent: CPU/memory of processes in the host's network namespace, TCP sessions, emulated extra load; controller marks stale agents | `agent/server_agent.py`, `controller/server_monitor.py` | Static-checked; not run yet |
| Decision engine | 5-factor weighted score, per-service weights, tie-break, pending-bandwidth reservation, round robin baseline, fallback when nothing is up, rebalance check with hysteresis | `controller/decision_engine.py`, `controller/models.py` | Unit-tested |
| Flow management | Table-miss rule, VIP ARP responder, forward/reverse rewrite rules, idle timeouts, cookie per server, delete-by-server on failure, sticky 5-tuple table, L2 learning for non-VIP traffic | `controller/flow_manager.py`, `controller/lb_controller.py` | Static-checked; not run yet |
| Live UDP rebalancing | Moves running UDP flows (voip/video) to a clearly better server; off by default | `controller/lb_controller.py` (`_rebalance`) | Unit-tested (decision); flow moves not run yet |
| Decision timing | Every decision timed; avg/p95/max reported | `controller/lb_controller.py`, `logs/decisions.csv` | Static-checked; not run yet |
| REST API | `/lb/status`, `/lb/flows`, `/lb/mode`, `/lb/weights`, `/lb/rebalance`, `/lb/dashboard` | `controller/rest_api.py` | Static-checked; not run yet |
| CLI | `status`, `watch`, `flows`, `mode`, `weights`, `rebalance` | `tools/lbctl.py` | Static-checked; not run yet |
| Web dashboard | Server cards, 2-minute latency chart with hover, score table, active flows, mode and rebalance buttons; light/dark; phone layout | `controller/dashboard.html` | Mock-tested (screenshots in light, dark and 390 px phone width) |
| Logging | `logs/decisions.csv` (incl. decision_ms), `logs/metrics.csv` | `controller/csv_logger.py` | Static-checked; not run yet |
| Topology | Single OVS switch, 4 clients, 4 servers with TCLink bw/delay/loss from config; starts agent, iperf, UDP echo and web server on each server | `topology/sdn_topology.py` | Static-checked; not run yet |
| Traffic tools | Paced UDP client (RTT, p95, jitter, loss, throughput, DSCP), UDP echo server | `traffic/` | Static-checked; not run yet |
| Experiments | RR vs SA (optional SA + rebalance), 3 repeats, alternating order, per-flow and per-round CSVs, Jain's fairness | `experiments/run_experiment.py` | Static-checked; not run yet |
| Charts | 7-panel QoS comparison + per-server utilisation and flow count, validated colour palette | `experiments/plot_results.py` | Mock-tested with synthetic data |
| VM setup | One-shot install + verification (Python version, packages, Ryu, unit tests, Mininet pingall) | `scripts/setup_vm.sh` | bash syntax checked; not run yet |
| Functional tests | Automated T1–T10, T12 (DSCP), T13 (rebalancing) with a pass/fail table | `tests/functional_test.py` | Static-checked; not run yet |
| Documentation | README, this plan, requirements, `.gitignore` (secrets), `.gitattributes` (LF endings) | repo root | Done |
| Version control | GitHub repository created; all work pushed to `main` | GitHub | Done |

### 0.2 Remaining ⏳

In order. Each item has an owner (suggested), how to do it, and when it counts as done.

| # | Task | Owner | How | Done when |
|---|---|---|---|---|
| R1 | Enable CPU virtualisation | Madankumar | BIOS → Intel Virtualization Technology → Enabled (it currently shows disabled on the laptop) | Task Manager shows "Virtualization: Enabled" |
| R2 | Create the VM | Madankumar | VirtualBox + Ubuntu 20.04 Desktop, 4 GB RAM, 2–4 CPUs, 30 GB disk | Ubuntu desktop boots |
| R3 | Install and self-check | Madankumar | `git clone …`, then `bash scripts/setup_vm.sh` | Every line prints `[ok]`, including Mininet pingall |
| R4 | First controller bring-up | Danielraj | Section 8.2, steps 1–10 | All 4 servers UP with agents reporting; VIP ping, curl, VoIP and iperf work |
| R5 | Fix first-run issues | Danielraj | Paste errors and fix (see 0.3 for likely spots) | No tracebacks in ryu-manager output |
| R6 | Functional tests | Arjun | `sudo python3 tests/functional_test.py` | 11/11 PASS (or failures understood and fixed) |
| R7 | Controller restart test (T11) | Arjun | Manual: stop ryu-manager while traffic runs, check existing flows continue, restart | Behaviour recorded for the report |
| R8 | Dashboard in the real setup | Arjun | Open `http://127.0.0.1:8080/lb/dashboard` in the VM's browser | Live data shows; mode and rebalance buttons work |
| R9 | Main experiment | Madankumar | `sudo python3 experiments/run_experiment.py`, then `python3 experiments/plot_results.py` | `results/plots/*.png` and the summary CSV produced |
| R10 | Rebalancing experiment (optional) | Madankumar | Add `--modes round_robin service_aware service_aware_rebalance` | A third bar in every chart |
| R11 | Tuning, if differences are small | Danielraj | Increase server differences or flow count in `config.yaml`; re-run R9 | Clear, repeatable gap between modes |
| R12 | Wireshark evidence for the report | Arjun | `sudo wireshark` on `lo`, filter `openflow_v4`; capture PacketIn → FlowMod for one flow | Screenshot of the control-plane exchange |
| R13 | Decision-time evidence | Danielraj | Read avg/p95 from `lbctl status` after R9 | Number quoted in the report for NFR-1 |
| R14 | Commit results | Any | `git add results/ && git commit && git push` | Charts and CSVs in the repository |
| R15 | Final report | All | Use sections 1–13 of this plan plus the R9–R13 results | Report submitted |
| R16 | Final slides and demo rehearsal | All | Section 14 demo script, timed at about 5 minutes | Rehearsed once end-to-end in the VM |
| R17 | Keep this plan current | Any | Mark R-items done; record the measured numbers | Status line matches reality |

### 0.3 Not verified yet; watch these on the first VM run

| Item | Why it might need a fix | Quick check |
|---|---|---|
| Ryu install | `pip install ryu` can fail with newer setuptools | The setup script already pins `setuptools<58` and `eventlet==0.30.2` |
| REST port 8080 | Another service may already use it | `ss -ltnp` shows the port; if busy, run `ryu-manager --wsapi-port 8081 …` and change `rest_url` |
| ICMP probes | Servers must answer echo requests from the VIP and resolve the VIP via ARP | `lbctl status` shows an RTT for every server |
| Agent per-namespace CPU | Reads `/proc/<pid>/ns/net` (needs root, which Mininet hosts have) | `cat /tmp/sdn_lb/stats/srv1.json` |
| iperf CSV parsing | `iperf -y C` output can differ between iperf2 versions | `throughput_mbps` is filled in `results/flows_*.csv` |
| Rule replacement on rebalance | Relies on OVS replacing a rule with the same match and priority | T13 passes; `ovs-ofctl -O OpenFlow13 dump-flows s1` shows the new server |
| Link reconfiguration in T13 | Uses Mininet `TCIntf.config` to change delay at runtime | T13 passes |

### 0.4 Deliberately not implemented (out of scope / future work)
Multi-switch topologies and path selection, multiple or clustered controllers, ML/auto-tuned weights, deep packet inspection, live migration of TCP connections, physical testbed (see sections 12–13).

---

## 1. Project summary

### 1.1 Problem
Traditional load balancers such as Round Robin hand each request to the next server in turn. They know nothing about:
- **the traffic type.** Video needs steady bandwidth, VoIP needs low latency and jitter, and file transfer needs reliability but tolerates delay.
- **the server's condition**: CPU, memory, active sessions, whether it is up.
- **the network's condition**: available bandwidth, latency and packet loss on each path.

The result is poor QoS, especially for traffic that is sensitive to delay.

### 1.2 Solution
An SDN controller sees the whole network from one place. For every new flow it:
1. classifies the service type,
2. combines service type, server health and network state into a **suitability score** for each server,
3. sends the flow to the highest-scoring server by installing OpenFlow rules,
4. keeps monitoring and reacts to change: failed servers are removed, and new flows follow the current conditions.

### 1.3 Objectives
| # | Objective | How it is measured |
|---|---|---|
| O1 | Lower latency and jitter for VoIP than Round Robin | Average RTT, p95 RTT and jitter of the VoIP test flows |
| O2 | Higher, steadier throughput for video and file transfer | Throughput (Mbit/s) and loss % |
| O3 | Fairer use of server capacity | Jain's fairness index over per-server link utilisation |
| O4 | Automatic handling of server failure | A failed server is excluded within about 3 s and its flows are removed |
| O5 | Logic is programmable without code changes | Weights, ports and servers live in `config.yaml`; weights can also be changed at runtime through the REST API |

### 1.4 Scope
**In scope:** single-switch Mininet topology, 4 heterogeneous servers, 4 clients, service classes video / voip / file / default, TCP, UDP and ICMP, Round Robin baseline, REST API, CSV logging, automated experiments and charts.

**Out of scope (future work):** multiple switches and multi-hop paths, multiple controllers or high availability, migrating live TCP connections, physical testbed, ML-based weight tuning.

---

## 2. Requirements

### 2.1 Functional requirements
| ID | Requirement | Implemented in |
|---|---|---|
| FR-1 | Emulated topology: clients, an OpenFlow switch, a server pool | `topology/sdn_topology.py` |
| FR-2 | Switch connects to a remote Ryu controller over OpenFlow 1.3 | `sdn_topology.py`, `lb_controller.py` |
| FR-3 | Link bandwidth, delay and loss configurable per server | `config.yaml` → `servers[].link` (Mininet TCLink) |
| FR-4 | Clients reach the pool through one virtual IP (VIP) | `config.yaml` → `vip`; ARP responder in `lb_controller.py` |
| FR-5 | First packet of every new flow is sent to the controller | table-miss rule, `flow_manager.install_table_miss` |
| FR-6 | Classify flows into video / voip / file / default by protocol and port | `controller/classifier.py` |
| FR-7 | Classification rules configurable | `config.yaml` → `services[].ports` |
| FR-8 | Poll switch port statistics periodically | `OFPPortStatsRequest` every 2 s |
| FR-9 | Compute used and available bandwidth per server link | `network_monitor.port_stats` |
| FR-10 | Measure latency per server | ICMP probes from the VIP every 1 s (`network_monitor`, `packets.icmp_probe`) |
| FR-11 | Measure packet loss per server | probe loss over the last 20 probes |
| FR-12 | Collect CPU, memory and sessions per server | `agent/server_agent.py` → `controller/server_monitor.py` |
| FR-13 | Mark a server down after N missed probes and exclude it | `network_monitor.update_availability` (N = 3) |
| FR-14 | Compute a suitability score with per-service weights | `controller/decision_engine.py` |
| FR-15 | Pick the best server with a deterministic tie-break | `decision_engine.select` |
| FR-16 | Install forward and reverse rewrite flows | `flow_manager.install_lb_flows` |
| FR-17 | Flows expire when idle | `idle_timeout` = 10 s |
| FR-18 | Remove flows of a failed server | cookie-based delete, `flow_manager.delete_server_flows` |
| FR-19 | Log every decision and periodic metrics | `logs/decisions.csv`, `logs/metrics.csv` |
| FR-20 | Round Robin baseline, switchable at runtime | `mode` in config; `POST /lb/mode` |
| FR-21 | REST API for status, flows, mode and weights | `controller/rest_api.py`, `tools/lbctl.py` |
| FR-22 | Generate test traffic for every service class | `traffic/udp_client.py`, `udp_echo_server.py`, iperf |
| FR-23 | Measure latency, throughput, loss, utilisation and fairness | `experiments/run_experiment.py` |
| FR-24 | Export results and draw comparison charts | `results/*.csv`, `experiments/plot_results.py` |
| FR-25 | Classify by DSCP marking (overrides the port) | `classification.dscp` in config; `classifier.py` |
| FR-26 | Move running UDP flows to a clearly better server (with hysteresis) | `rebalance:` in config; `lb_controller._rebalance`, `decision_engine.better_server` |
| FR-27 | Measure and report decision time | `decision_ms` in `decisions.csv`, `/lb/status`, dashboard |
| FR-28 | Live web dashboard with mode and rebalance controls | `controller/dashboard.html` at `/lb/dashboard` |
| FR-29 | Automated environment setup and end-to-end tests | `scripts/setup_vm.sh`, `tests/functional_test.py` |

### 2.2 Non-functional requirements
| ID | Category | Requirement | How it is met |
|---|---|---|---|
| NFR-1 | Performance | Decision for a new flow in about 10 ms or less | Scoring is O(number of servers); every decision is timed and avg/p95/max reported |
| NFR-2 | Performance | After the first packet, traffic is forwarded by the switch | Exact-match flow rules; the controller sees only first packets |
| NFR-3 | Overhead | Monitoring traffic stays small | 1 small ICMP probe per server per second; port stats every 2 s |
| NFR-4 | Reliability | Failed server excluded within about 3 s | 3 missed probes at 1 s intervals |
| NFR-5 | Reliability | Graceful degradation | No server up → fall back to Round Robin; silent agent → neutral health (0.5) |
| NFR-6 | Consistency | One flow never splits across servers | "Sticky" table maps a 5-tuple to its server until the flow expires |
| NFR-7 | Scalability | Adding a server needs only a config entry | Servers, ports and links all come from `config.yaml` |
| NFR-8 | Maintainability | Modular, tested code | One module per component; logic modules have no Ryu dependency and are unit tested |
| NFR-9 | Usability | One command per component; readable logs | `ryu-manager …`, `sudo python3 …`, `lbctl watch` |
| NFR-10 | Reproducibility | Experiments are scripted and repeatable | `run_experiment.py`; mode order alternates between repeats; results saved with a timestamp |
| NFR-11 | Portability | Runs in a standard Ubuntu 20.04 VM | No special hardware |
| NFR-12 | Security (basic) | Management traffic stays local | Controller and REST API on 127.0.0.1; agents write to a local directory |

---

## 3. Tech stack

| Layer | Technology | Version | Purpose |
|---|---|---|---|
| Host OS | Windows 11 + VirtualBox | 7.x | Runs the Linux VM |
| Guest OS | Ubuntu Desktop | 20.04 LTS | Mininet needs Linux; ships Python 3.8 |
| Network emulator | Mininet | 2.2.x / 2.3.x | Virtual hosts, links (TCLink) |
| Virtual switch | Open vSwitch | 2.13+ | OpenFlow 1.3 switch |
| SDN controller | Ryu | 4.34 | Controller framework (Python) |
| Southbound API | OpenFlow | 1.3 | Controller ↔ switch |
| Language | Python | 3.8 | Everything |
| Python libraries | eventlet 0.30.2, PyYAML, psutil, pandas, matplotlib, webob (from Ryu) | — | Ryu runtime, config, agent metrics, analysis, REST |
| Traffic tools | iperf (v2), custom UDP client/echo, ping, curl | — | Traffic generation and measurement |
| Packet analysis | Wireshark / tshark, `ovs-ofctl` | — | Inspect packets and installed flows |

**VM sizing:** 4 GB RAM, 2–4 vCPUs, 30 GB disk. **CPU virtualisation (VT-x) must be enabled in BIOS**; it currently shows as disabled on the laptop.

---

## 4. System architecture

```
                         ┌──────────────────────── Ryu controller ────────────────────────┐
                         │                                                                 │
  PacketIn (1st pkt) ───►│  Classifier ──► Decision Engine ◄── Network Monitor             │
                         │  (port→svc)     (score, select)  ◄── Server Monitor             │
                         │                      │                                          │
                         │                      ▼                                          │
                         │                Flow Manager ──► FlowMod / PacketOut ────────────┼──► switch
                         │                                                                 │
                         │  REST API (:8080)  /lb/status /lb/flows /lb/mode /lb/weights    │
                         └─────────────────────────────────────────────────────────────────┘
                                    ▲                          ▲
                   port stats + ICMP probe replies     agent JSON reports
                                    │                          │
 clients h1..h4 ──── s1 (OVS, OpenFlow 1.3) ────┬── srv1  100 Mbit/s  2 ms   [video voip file default]
   10.0.0.1-4        dpid 1                     ├── srv2  100 Mbit/s 25 ms   [video file default]
                                                ├── srv3   10 Mbit/s  1 ms   [voip default]
                     VIP 10.0.0.100             └── srv4   50 Mbit/s 10 ms 1% loss, +50% CPU [video default]
```

### 4.1 Components
| Component | File | Responsibility |
|---|---|---|
| Main app | `controller/lb_controller.py` | Ryu event handlers, monitoring loop, sticky/active flow tables, REST hooks |
| Config loader | `controller/config_loader.py` | Loads and validates `config.yaml`; builds `Server` objects; mode aliases |
| Server model | `controller/models.py` | Runtime state per server (up, RTT, loss window, used Mbit/s, pending reservations, CPU/mem, sessions) |
| Classifier | `controller/classifier.py` | `(ip_proto, dst_port) → service`; narrowest port range wins |
| Network Monitor | `controller/network_monitor.py` | Probe bookkeeping, RTT EWMA, loss window, up/down state, bandwidth from port counters |
| Server Monitor | `controller/server_monitor.py` | Reads `/tmp/sdn_lb/stats/<server>.json`; marks agents fresh or stale |
| Decision Engine | `controller/decision_engine.py` | Factor calculation, weighted score, selection, Round Robin, fallback |
| Flow Manager | `controller/flow_manager.py` | Table-miss, LB forward/reverse flows, PacketOut, delete by cookie, stats requests |
| Packet builder | `controller/packets.py` | ARP replies for the VIP, ICMP probe packets |
| CSV logger | `controller/csv_logger.py` | `logs/decisions.csv`, `logs/metrics.csv` |
| REST API | `controller/rest_api.py` | JSON endpoints served by ryu-manager's WSGI server |
| Dashboard | `controller/dashboard.html` | Live server cards, latency chart, score table, flows, mode/rebalance buttons |
| Server agent | `agent/server_agent.py` | Per-host CPU and memory (processes in the host's network namespace), TCP sessions; optional emulated extra load |
| Traffic tools | `traffic/udp_client.py`, `udp_echo_server.py` | Paced UDP streams; RTT, jitter, loss and throughput |
| Topology | `topology/sdn_topology.py` | Builds the network from config; starts agents, iperf, UDP echo and a web server on each server |
| Experiment runner | `experiments/run_experiment.py` | Runs the traffic mix in each mode, collects metrics, writes CSVs |
| Plotter | `experiments/plot_results.py` | Comparison charts and summary CSV |
| CLI | `tools/lbctl.py` | `status`, `watch`, `flows`, `mode`, `weights` |

### 4.2 Request walkthrough
1. Client h1 sends `ARP who-has 10.0.0.100`. The controller replies with the VIP MAC `00:00:00:00:01:00`.
2. h1 sends its first packet to the VIP. There is no matching rule, so it goes to the controller as a **PacketIn**.
3. The controller extracts the 5-tuple and classifies it, e.g. UDP to port 5060 → `voip`.
4. The decision engine scores every server that is up with the `voip` weights and picks the best, e.g. srv3.
5. The flow manager installs:
   - **reverse rule**: `in_port=srv3, ipv4_src=srv3, ipv4_dst=h1, udp 5060→sport` → set `eth_src=VIP_MAC, ipv4_src=VIP, eth_dst=h1_MAC`, output to h1's port
   - **forward rule**: `in_port=h1, ipv4_src=h1, ipv4_dst=VIP, udp sport→5060` → set `eth_dst=srv3_MAC, ipv4_dst=srv3`, output to srv3's port (flag `SEND_FLOW_REM`)
6. The first packet is sent with the forward actions (PacketOut). Every later packet is switched in the data plane.
7. When the flow is idle for 10 s both rules expire. A **FlowRemoved** message updates the server's active-flow count.

---

## 5. Decision logic

### 5.1 Factors (all normalised to 0–1, higher is better)
| Factor | Formula | Data source |
|---|---|---|
| **H** health | `1 − (0.5·CPU% + 0.2·Mem% + 0.3·min(1, sessions/20))`. If the agent is silent: `0.5·(1 − sessions/20)` | agent JSON + controller flow count |
| **B** bandwidth | `min(1, available_Mbps / reference_Mbps)`, where `available = capacity − used (EWMA) − pending reservations` and reference = largest link (100) | port stats |
| **L** latency | `max(0, 1 − RTT_ms / 100)` | ICMP probes (EWMA, α = 0.5) |
| **P** reliability | `1 − loss rate of the last 20 probes` | ICMP probes |
| **M** service match | `1` if the server is designated for the service, else `0.3` | `servers[].services` |

`Score = wH·H + wB·B + wL·L + wP·P + wM·M`. The weights are normalised so they sum to 1.

### 5.2 Weight profiles (`config.yaml`)
| Service | Ports | Health | Bandwidth | Latency | Loss | Match | Expected Mbit/s |
|---|---|---|---|---|---|---|---|
| video | TCP 554, 1935, 8554; UDP 5004–5005 | 0.20 | **0.45** | 0.15 | 0.05 | 0.15 | 8 |
| voip | TCP 5060; UDP 5060, 16384–32767 | 0.15 | 0.05 | **0.50** | 0.15 | 0.15 | 0.1 |
| file | TCP 20, 21, 22, 2121 | **0.25** | **0.30** | 0.05 | **0.25** | 0.15 | 20 |
| default | everything else (web, ICMP) | 0.30 | 0.25 | 0.20 | 0.10 | 0.15 | 1 |

### 5.3 Selection rules
1. Candidates are the servers that are **up** (answered a recent probe).
2. If no server is up, fall back to **Round Robin** over all servers (`fallback_round_robin`).
3. In `round_robin` mode, cycle through the servers that are up.
4. In `service_aware` mode, take the highest score. Ties go to fewer sessions, then the lower server index.
5. **Pending reservation:** a new assignment reserves the service's `expected_mbps` on that server for 4 s, until port stats catch up. This keeps a burst of simultaneous flows from all landing on one server.
6. **Sticky table:** repeat PacketIns for the same 5-tuple, sent before the rule is installed, reuse the same server.
7. **DSCP first:** if the packet carries a DSCP mark listed in `classification.dscp` (46 → voip, 34 → video, 10 → file), that decides the service; otherwise the port does.
8. **Live rebalancing (optional, UDP only):** every 5 s, a UDP flow of a listed service moves if another server scores ≥ 0.15 higher and the flow has stayed put ≥ 10 s. The new forward rule replaces the old one in place (same match and priority), so the client never notices. TCP is never moved, because that would break the connection.

### 5.4 Worked example (VoIP flow, srv1 congested by a file transfer)
| Server | H | B | L (RTT) | P | M | Score (voip weights) |
|---|---|---|---|---|---|---|
| srv1 | 0.90 | 0.05 | 0.20 (80 ms, queueing) | 1.0 | 1.0 | 0.15·0.90 + 0.05·0.05 + 0.5·0.20 + 0.15·1 + 0.15·1 = **0.54** |
| srv2 | 0.90 | 1.00 | 0.50 (50 ms) | 1.0 | 0.3 | 0.135 + 0.05 + 0.25 + 0.15 + 0.045 = **0.63** |
| srv3 | 0.95 | 0.10 | 0.98 (2 ms) | 1.0 | 1.0 | 0.1425 + 0.005 + 0.49 + 0.15 + 0.15 = **0.94** ✅ |
| srv4 | 0.60 | 0.50 | 0.80 (20 ms) | 0.98 | 0.3 | 0.09 + 0.025 + 0.40 + 0.147 + 0.045 = **0.71** |

Round Robin would send this call to whichever server is next, possibly congested srv1 or far-away srv2.

---

## 6. OpenFlow design

| Priority | Match | Actions | Timeouts | Purpose |
|---|---|---|---|---|
| 0 | any | output CONTROLLER (no buffer) | none | table-miss |
| 1 | in_port, eth_src, eth_dst | output learned port | idle 60 s | plain L2 forwarding (ARP between hosts, direct traffic) |
| 100 | client → VIP 5-tuple | set eth_dst, ipv4_dst = server; output server port | idle 10 s | forward LB rule |
| 100 | server → client 5-tuple | set eth_src, ipv4_src = VIP; set eth_dst = client; output client port | idle 10 s | reverse LB rule |

- **Cookie:** `(server_index << 32) | flow_seq`. Deleting with mask `0xFFFFFFFF00000000` removes every flow of one server.
- **Controller-generated packets:** ARP replies for the VIP; ICMP echo requests from the VIP to each server, identified by ICMP id `0x5D4E`. Their replies are addressed to the VIP and match no rule, so they come back as PacketIns.
- **Messages used:** FeaturesReply, FlowMod (ADD/DELETE), PacketIn, PacketOut, PortStatsRequest/Reply, FlowRemoved.

---

## 7. Interfaces

### 7.1 REST API (`http://127.0.0.1:8080`)
| Method | Path | Body | Returns |
|---|---|---|---|
| GET | `/lb/status` | — | mode, switch state, per-server metrics and current score per service, weights |
| GET | `/lb/flows` | — | active LB flows: client, proto, ports, service, server |
| POST | `/lb/mode` | `{"mode": "round_robin"}` | new mode (aliases: `rr`, `sa`) |
| POST | `/lb/weights` | `{"service": "voip", "weights": {"latency": 0.6}}` | updated weights |
| POST | `/lb/rebalance` | `{"enabled": true}` | new rebalancing state |
| GET | `/lb/dashboard` | — | the web dashboard (HTML) |

### 7.2 Agent report (`/tmp/sdn_lb/stats/<server>.json`, every 1 s)
```json
{"name": "srv1", "ts": 1791370000.12, "cpu": 12.5, "mem": 3.1, "sessions": 2}
```
A report older than 5 s counts as stale, and that server's health becomes neutral.

### 7.3 Log files
- `logs/decisions.csv`: time, mode, client, proto, ports, service, chosen server, reason, all scores
- `logs/metrics.csv`: every 2 s per server: up, agent_ok, cpu, mem, sessions, flows, used/available Mbit/s, RTT, loss

---

## 8. Implementation phases

Overall progress: the code for phases 0–6b is written but not yet verified in the VM; phases 7–9 are still to do (see 0.2).

| Phase | Work | Deliverable | Owner (suggested) | Status |
|---|---|---|---|---|
| **0. Design** | Problem, use case, architecture, scoring model | Review 1 and 2 slides | All | ✅ Done |
| **0b. Repository** | GitHub repo, `.gitignore` for secrets, LF line endings | Shared code base | Danielraj | ✅ Done |
| **1. Environment** | Enable VT-x in BIOS → VirtualBox → Ubuntu 20.04 VM → `bash scripts/setup_vm.sh` (installs and self-checks) | Working VM | Madankumar | ✅ Script written, ⏳ run in VM |
| **2. Core controller** | Config loader, classifier, flow manager, ARP for VIP, LB flows, L2 forwarding | VIP works with round robin | Danielraj | ✅ Code written, ⏳ verify in VM |
| **3. Monitoring** | Port-stats bandwidth, ICMP probes (RTT/loss), up/down, server agent, server monitor | `lbctl status` shows live metrics | Arjun | ✅ Code written, ⏳ verify in VM |
| **4. Decision engine** | Factors, weights, selection, pending reservation, sticky table, fallback | Service-aware placement | Danielraj | ✅ Code written, unit tests pass |
| **5. Management** | REST API, `lbctl`, CSV logs, web dashboard, decision timing | Runtime control + demo UI | Arjun | ✅ Code written; dashboard checked against a fake controller, ⏳ verify in VM |
| **5b. Extensions** | DSCP classification, live UDP rebalancing | Future-work items done early | Danielraj | ✅ Code written + unit tests, ⏳ verify in VM |
| **6. Topology & traffic** | Mininet topology from config, test services, UDP client/echo | `sdn_topology.py` CLI demo | Madankumar | ✅ Code written, ⏳ verify in VM |
| **6b. Functional tests** | `sudo python3 tests/functional_test.py` (T1–T13) | Pass/fail report | Arjun | ✅ Script written, ⏳ run in VM |
| **7. Evaluation** | Run experiments (3 repeats × 2–3 modes), plot, analyse | `results/` CSVs + charts | Madankumar + Arjun | ⏳ To do |
| **8. Tuning** | Adjust weights/topology if the results are unclear; re-run | Final numbers | Danielraj | ⏳ To do |
| **9. Documentation** | README and implementation plan (done); report, final slides, demo rehearsal (to do) | Final review package | All | 🟡 Partly done |

### 8.1 Phase 1 checklist (environment)
Short version: steps 1–2 by hand, then `bash scripts/setup_vm.sh` does steps 3–5 and prints ok/fail for each check.

1. BIOS: Intel Virtualization Technology → **Enabled**. Task Manager → CPU should then show "Virtualization: Enabled".
2. Install VirtualBox. Create a VM with 4 GB RAM, 2–4 CPUs and a 30 GB disk, and install Ubuntu 20.04 Desktop. Add Guest Additions.
3. Install the packages:
   ```bash
   sudo apt update && sudo apt install -y mininet openvswitch-switch iperf python3-pip python3-yaml python3-psutil wireshark
   pip3 install -r requirements.txt        # ryu 4.34, eventlet 0.30.2, pyyaml, psutil, pandas, matplotlib
   echo 'export PATH=$HOME/.local/bin:$PATH' >> ~/.bashrc && source ~/.bashrc
   ```
4. Verify: `sudo mn --test pingall`, then `ryu-manager ryu.app.simple_switch_13` together with `sudo mn --controller=remote --switch ovsk,protocols=OpenFlow13 --topo single,3` and `pingall`.
5. Copy `sdn-service-lb/` into the VM and run `python3 -m unittest discover -s tests -v`.

### 8.2 Phases 2–6 bring-up order in the VM
| Step | Command | Pass criteria |
|---|---|---|
| 1 | `ryu-manager controller/lb_controller.py` | Prints "Service-aware LB: VIP 10.0.0.100, 4 servers" with no traceback |
| 2 | `sudo python3 topology/sdn_topology.py` | Controller logs "switch 0000000000000001 connected", then "server srvN is UP" ×4 and "agent on srvN is reporting" ×4 |
| 3 | `python3 tools/lbctl.py status` | All 4 servers `up=yes`, `agent=ok`; RTT about 4 / 50 / 2 / 20 ms |
| 4 | `mininet> h1 ping -c 3 10.0.0.100` | 0% loss; a decision line in the controller log |
| 5 | `mininet> h1 curl -s 10.0.0.100:8080` | "Hello from srvN" |
| 6 | `mininet> h2 python3 traffic/udp_client.py --host 10.0.0.100 --port 5060 --duration 10` | JSON output, loss ≈ 0, service = voip in `lbctl flows` |
| 7 | `mininet> h1 iperf -c 10.0.0.100 -p 2121 -t 10` | Throughput close to the chosen server's link speed |
| 8 | `sudo ovs-ofctl -O OpenFlow13 dump-flows s1` | Priority-100 rules with set_field actions |
| 9 | `mininet> link s1 srv3 down`, wait 4 s, `lbctl status` | srv3 `up=NO`; new VoIP flows avoid it. `link s1 srv3 up` brings it back |
| 10 | `lbctl mode rr`, repeat step 4 several times | Servers chosen in turn (srv1 → srv2 → srv3 → srv4) |

---

## 9. Testing plan

### 9.1 Unit tests (`tests/test_logic.py`, run anywhere)
| Area | Tests |
|---|---|
| Config | Loads the project config; mode aliases; rejects unknown weights and unknown services |
| Classifier | Port → service mapping, port ranges, protocol must match, port-spec parsing |
| Decision engine | VoIP avoids high latency; video prefers bandwidth; file avoids a full link; pending reservation spreads a burst and then expires; down servers skipped; Round Robin order; fallback; neutral health; scores stay in [0, 1] |
| Network monitor | Probe reply → RTT and up; foreign ICMP ignored; down after 3 misses; bandwidth from counters; unknown port ignored |

### 9.2 Integration / functional tests (in the VM)
Automated by `sudo python3 tests/functional_test.py`, which prints a pass/fail table; T11 is manual.
| ID | Scenario | Expected result |
|---|---|---|
| T1 | ARP for the VIP | Client gets the VIP MAC; `arp -n` on the host shows `00:00:00:00:01:00` |
| T2 | ICMP to the VIP | Reply comes from 10.0.0.100 (rewrite works both ways) |
| T3 | Same client, many TCP connections | Each connection is decided separately; none breaks mid-stream |
| T4 | VoIP while a file transfer saturates srv1 | VoIP placed on srv3 (low RTT) |
| T5 | Two simultaneous video streams | Spread across the high-bandwidth servers, not both on srv3 |
| T6 | Server failure (`link s1 srvX down`) | DOWN within about 3 s; its flows deleted; new flows avoid it |
| T7 | Server recovery | UP after the first probe reply |
| T8 | Agent stopped (`pkill -f "server_agent.py --name srv1"`) | `agent_ok` false after 5 s; health 0.5; still selectable |
| T9 | Runtime weight change (`lbctl weights voip latency=0`) | VoIP placement changes accordingly |
| T10 | Mode switch | `rr` cycles servers; `sa` returns to scoring |
| T11 | Controller restart (manual) | Existing flows keep working until they time out; new flows decided after reconnect |
| T12 | DSCP-marked flow (`udp_client.py --dscp 46` to the video port) | Classified as voip |
| T13 | Live rebalancing: the call's server link turns slow (80 ms) | The UDP call moves to another server without restarting |

---

## 10. Evaluation plan

### 10.1 Experiment design
- **Independent variable:** mode, Round Robin vs Service-Aware (optional third: Service-Aware + live rebalancing, `--modes round_robin service_aware service_aware_rebalance`).
- **Fixed:** topology, server heterogeneity and traffic mix, all from `config.yaml`.
- **Repeats:** 3 per mode. The order alternates (RR→SA, SA→RR, RR→SA) to avoid order bias.
- **Per round:** set the mode → wait 12 s for old flows to expire → start the traffic mix → run 20 s → collect.

| Start | Flows | Tool | Purpose |
|---|---|---|---|
| t = 0 s | 2 × file transfer (h1, h2 → TCP 2121) | iperf | Bulk background load |
| t = 2 s | 2 × video (h3, h4 → UDP 5004, 500 pkt/s × 1000 B ≈ 4 Mbit/s) | `udp_client.py` | Bandwidth-sensitive |
| t = 4 s | 4 × VoIP (h1–h4 → UDP 5060, 50 pkt/s × 160 B) | `udp_client.py` | Latency-sensitive |

### 10.2 Metrics
| Metric | Definition | Better |
|---|---|---|
| VoIP / video RTT | Average and p95 round-trip time per packet | lower |
| Jitter | Mean absolute change in RTT between consecutive packets | lower |
| Packet loss | 1 − received / sent | lower |
| Throughput | iperf bits/s (file); received bytes / duration (video) | higher |
| Server utilisation | per-server Mbit/s ÷ link capacity, from port counters | balanced |
| Fairness | Jain's index `(Σx)² / (n·Σx²)` over utilisation | closer to 1 |

### 10.3 Commands and outputs
```bash
sudo python3 experiments/run_experiment.py          # ~5 minutes
python3 experiments/plot_results.py
```
- `results/flows_<tag>.csv`: one row per flow (server chosen, metrics)
- `results/rounds_<tag>.csv`: utilisation and flow count per server, fairness
- `results/plots/comparison_<tag>.png`: 7 panels (VoIP RTT, jitter, loss; video throughput, loss; file throughput; fairness)
- `results/plots/servers_<tag>.png`: utilisation and flow count per server
- `results/summary_<tag>.csv`: mean and std per metric per mode

### 10.4 Expected outcome
- VoIP RTT and jitter clearly lower with Service-Aware, because calls avoid srv2 (25 ms) and congested links.
- Video loss lower, because streams avoid the 10 Mbit/s and lossy links.
- File throughput higher, because bulk transfers go to the 100 Mbit/s servers.
- If the differences are small, follow Phase 8: increase server differences in `config.yaml` (e.g. srv2 delay 40 ms) or add more concurrent flows, then re-run.

---

## 11. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| VT-x disabled / VM won't start | Blocks everything | Enable in BIOS first (Phase 1, step 1) |
| Ryu incompatible with newer Python | Controller won't start | Use Ubuntu 20.04 (Python 3.8); pin `eventlet==0.30.2`; `pip3 install "setuptools<58"` if install fails |
| `sudo mn -c` kills ryu-manager | Confusing failures | Restart the controller after any `mn -c` |
| Controller is a single point of failure | Outage at scale | Documented limitation; installed flows keep working until timeout; future work: clustered controllers (ONOS/ODL) |
| Per-flow scoring overhead | Slower setup than RR | O(n) scoring, decisions only on first packets; measure decision time from logs |
| Weight profiles need manual tuning | Sub-optimal choices | Weights live in config and can be changed at runtime via REST; future work: ML/auto-tuning |
| Stale monitoring data when flows start in bursts | Herding onto one server | Pending-bandwidth reservation and controller-side session count |
| Mininet hosts share one kernel | System-wide CPU identical for all servers | Agent counts only processes in the host's network namespace; `extra_cpu` emulates load |
| VM performance limits (8 GB laptop) | Noisy results | Moderate rates (≤ 100 Mbit/s links), 3 repeats, mean ± std |
| Results not clearly different | Weak evaluation | Phase 8 tuning; more heterogeneity in the topology |

---

## 12. Limitations (to state in the report)
1. Single switch only; the VIP rewrite happens at the access switch.
2. Live TCP connections are never moved between servers. Only new flows follow updated scores.
3. Agent telemetry uses a shared directory, which works because Mininet hosts share a filesystem. Real hardware would use REST or gRPC.
4. Emulated environment (Mininet) only, with no physical testbed.
5. Static, manually chosen weight profiles.
6. Related work each covers one part of the problem: Hedera (flow scheduling), DevoFlow (controller load), ElasticTree (energy), DIFANE (rule scalability). This project combines service, server and network state in one decision, which adds complexity.

## 13. Future work
- Multi-switch topologies with path selection (combined with Hedera-style rerouting).
- Distributed or clustered controllers for high availability.
- Learned or adaptive weights (reinforcement learning on observed QoS).
- Deep packet inspection (DPI) for traffic that is unmarked and uses non-standard ports. DSCP is already supported.
- Live migration for TCP, e.g. via connection proxies. UDP migration is already supported.
- Deployment on a physical OpenFlow testbed.

---

## 14. Demo script for the final review (about 5 minutes)
1. Show `config.yaml`: servers, services, weights.
2. Terminal 1: start `ryu-manager controller/lb_controller.py`. Terminal 2: start the topology. Point out "server UP" and "agent reporting" in the logs.
3. Browser: `http://127.0.0.1:8080/lb/dashboard` (or terminal 3: `lbctl watch`), showing the live RTT, bandwidth and scores per service.
4. `h1 iperf -c 10.0.0.100 -p 2121 -t 60 &`: watch the chosen server's bandwidth fill up.
5. `h2 python3 traffic/udp_client.py --host 10.0.0.100 --port 5060 --duration 10`: the call avoids the congested server. Show the decision line with all scores.
6. `link s1 srv3 down`: the server goes DOWN and new calls go elsewhere. Then `link s1 srv3 up`.
7. `lbctl mode rr` and repeat step 5 to show the worse result.
8. Turn on "Rebalance" in the dashboard, start a long call, then slow its server's link in Mininet: the call moves to another server without restarting.
9. Show the experiment charts from `results/plots/` and the decision time on the dashboard (well under 1 ms).

## 15. Viva preparation (key questions)
| Question | Answer |
|---|---|
| How is the service type detected? | Protocol and destination port of the first packet (PacketIn), using the configurable map in `config.yaml` |
| Why not decide every packet at the controller? | Too slow. Only the first packet goes up; exact-match rules forward the rest at line rate |
| How is latency measured? | The controller injects ICMP echo requests from the VIP to each server every second; the RTT is smoothed with an EWMA |
| How is bandwidth measured? | OpenFlow port-stats counters every 2 s; the byte delta gives Mbit/s; available = capacity − used |
| What if the controller fails? | Installed flows keep forwarding until their timeout; new flows can't be placed. Fix: multiple controllers |
| What if all servers look down? | Fallback to round robin, so traffic is never dropped by the decision logic |
| How do you stop many new flows all going to one server? | Each new assignment reserves its expected bandwidth for 4 s, and the controller counts active flows as sessions |
| How do you prove it is better? | Same topology and traffic, both modes, 3 repeats, comparing RTT, jitter, loss, throughput and Jain's fairness |
| What does it cost per flow? | Every decision is timed; avg/p95/max are on the dashboard and in `decisions.csv` |
| Can a running flow change server? | UDP flows can (stateless), with a 0.15 score gap and 10 s hold time so they don't bounce between servers. TCP flows stay put |
| What if apps mark their traffic? | DSCP marks (EF, AF41, AF11) override port-based classification |
