# Faculty Viva Voce: Anticipated Questions & Answers

This document provides plain-language, technically rigorous answers to 10 likely faculty examination questions for the **SDN-Based Service-Aware Load Distribution** project. All figures and claims strictly match the measured experimental results and system limits.

---

### Q1: Why did you use a linear multi-criteria scoring algorithm instead of Machine Learning or Deep Reinforcement Learning?
**Answer:**  
In carrier-grade and enterprise SDN load balancing, routing decisions must execute within sub-millisecond budgets. In our Ryu implementation, the controller computes the composite score across all four candidate servers and installs OpenFlow rules in **0.07 to 0.13 milliseconds**.  
Machine learning and reinforcement learning models introduce non-deterministic inference latencies, require extensive training datasets that rarely generalize across topologies, and act as "black boxes." Our multi-criteria algorithm is deterministic, fully explainable (inspectable per-metric scores in real time), transparent to operators, and can be dynamically tuned at runtime via REST APIs without retraining.

---

### Q2: Why not just use Weighted Round Robin (WRR) or Least-Connections?
**Answer:**  
- **Weighted Round Robin (WRR)** statically allocates flows based purely on pre-configured server capacity ratios. It is flow-agnostic: it treats a 50 kbit/s UDP voice call identical to an 80 Mbit/s TCP elephant file transfer, blindly dumping elephant flows onto latency-sensitive servers.  
- **Least-Connections** counts open transport connections, but ignore link quality entirely. A server with 2 idle connections across a lossy, high-delay link will be chosen over a server with 3 connections on a pristine, zero-loss link.  
Our Service-Aware approach inspects flow headers (L4 ports and protocol) to classify traffic into services, dynamically tracking server health, real-time bandwidth utilization, RTT, and link packet loss to assign each flow to the server best suited for its specific SLA.

---

### Q3: Is your comparison against Round Robin fair, or was Round Robin disadvantaged?
**Answer:**  
The baseline comparison is completely fair:
1. **Identical Test Conditions**: Both Round Robin and Service-Aware modes were evaluated using identical Mininet topologies, identical traffic arrival scripts, identical packet sizes, and identical background loads across 3 independent randomized runs.
2. **Transparent Protocol Implementation**: Round Robin rotated strictly through all active, healthy servers $(srv1 \to srv2 \to srv3 \to srv4)$ without artificial handicaps.
3. **No Hidden Metrics**: We openly report all metrics where Round Robin outperforms Service-Aware (e.g., Round Robin achieved lower video delay: 11.5 ms vs 20.5 ms, and higher Jain's fairness: 0.720 vs 0.596).

---

### Q4: Why are the servers in your topology deliberately configured with such different link properties?
**Answer:**  
In real enterprise data centers and hybrid edge networks, infrastructure is heterogeneous: servers have different hardware specs, varying uplink capacities, and different edge latencies.  
To test whether the controller can actually distinguish service requirements, we modeled four distinct server profiles:
- `srv1` & `srv2`: High capacity (100 Mbit/s, 2 ms delay) for high-throughput bulk transfers.
- `srv3`: Ultra-low latency (1 ms delay, 10 Mbit/s) designed for interactive voice/SIP traffic.
- `srv4`: High-latency, lossy link (10 ms delay, 1% link loss per direction, 50 Mbit/s).  
If all servers were identical, service-aware classification would be unnecessary. Heterogeneity is required to demonstrate service-aware affinity.

---

### Q5: Why is Jain's Fairness Index lower for Service-Aware (0.596) than for Round Robin (0.720)?
**Answer:**  
Jain's Fairness Index mathematically measures whether all nodes receive equal load.  
- Round Robin distributes connections blind to application needs, spreading connections evenly across all four servers, which results in higher numerical fairness (0.720).
- Service-Aware intentionally directs bulk TCP elephant flows to `srv1`/`srv2` and low-bandwidth VoIP flows to `srv3`. As a result, `srv1` and `srv2` handle significantly more bytes and bandwidth than `srv3`.  
The lower fairness score (0.596) is an expected, deliberate design trade-off resulting from service specialization rather than a failure of load distribution.

---

### Q6: Why is video latency higher (20.5 ms vs 11.5 ms) and video packet loss higher (1.95% vs 0.97%) under Service-Aware?
**Answer:**  
This is an explicit architectural trade-off.  
Service-Aware prioritizes reserving `srv1` and `srv2` for high-bandwidth file transfers to prevent queue drops, and `srv3` for ultra-sensitive VoIP calls. As a consequence, video streaming flows are routed to `srv4`.  
Because `srv4` has an emulated link delay of 10 ms (20 ms round trip) and 1% drop rate each way (~1.8–2.0% measured round-trip loss), video flows on `srv4` reflect those link constraints. In Round Robin, 3 out of every 4 video flows happen to land on pristine servers (`srv1`, `srv2`, or `srv3`), giving an artificially lower average loss. Service-Aware sacrifices video link optimality to guarantee 100% SLA compliance for voice calls and maximize file throughput.

---

### Q7: Is this Mininet emulation realistic compared to a physical hardware network?
**Answer:**  
Mininet provides high structural and functional realism because it executes the **real Linux kernel network stack**, real Open vSwitch (OVS) kernel modules, real OpenFlow 1.3 protocol exchanges, and real user-space sockets (`iperf`, `ping`, Python UDP sockets).  
However, it has recognized emulation limits:
- All hosts and the switch share the host machine's CPU cores, memory bus, and OS scheduler.
- Physical characteristics such as optical transceivers, ASIC buffer architectures, hardware TCAM lookups, and physical line noise are abstracted using Linux `tc-netem` queueing disciplines.

---

### Q8: What happens if the SDN controller crashes during operation?
**Answer:**  
Our system relies on OpenFlow 1.3 reactive flow table installation with an idle timeout (15 seconds).
1. **Active Data Plane Survival**: Once flow rules (`ip_proto`, `ipv4_src`, `ipv4_dst`, `tcp/udp_port`) are installed in the OVS kernel datapath, existing TCP and UDP flows continue switching at full line rate even if the controller process terminates completely.
2. **Controller Recovery**: In functional test `T11`, we killed the Ryu controller during active traffic and restarted it. Upon reconnecting, the controller completed the OpenFlow handshake, re-queried switch port statistics, and seamlessly handled newly arriving flows without dropping existing traffic.
In a production deployment, this would be backed by a clustered high-availability controller architecture (e.g., active-standby Ryu instances using Raft or etcd).

---

### Q9: What does dynamic rebalancing do during server degradation, and why was the Wave 2 VoIP pass rate 0%?
**Answer:**  
When `srv3` suffers severe latency degradation (+100 ms injected delay), existing VoIP calls on `srv3` begin experiencing packet delays exceeding 270 ms.  
The rebalancing engine detects this degradation, removes the existing OpenFlow flow rules for active UDP streams, and installs new rules redirecting packets to the next best server.  
- **Delay was successfully rescued**: Average latency dropped from **276.4 ms** down to **20.4 ms** (100% of calls successfully migrated).
- **Why pass rate was 0%**: Because `srv1` and `srv2` were saturated with bulk elephant TCP flows, the only available alternative server was `srv4`. Srv4's link has an inherent 1% emulated packet loss per direction (~1.97% round-trip loss). Because our pre-defined VoIP pass rule strictly requires `loss <= 1%`, all calls on `srv4` failed the loss criterion despite passing the delay criterion. The system made the best available trade-off under severe network saturation.

---

### Q10: What would be required to deploy this system on real enterprise or data center hardware?
**Answer:**  
To transition from Mininet to production:
1. **Hardware OpenFlow Switches**: Replace software OVS with physical OpenFlow 1.3 or P4-enabled whitebox switches (e.g., Edgecore or Cisco switches running Stratum or Open Network Linux) with TCAM support for L4 flow matching.
2. **Out-of-Band Control Network**: Establish an isolated, redundant control network connecting physical switch management ports to the Ryu controller cluster over secure OpenFlow (TLS on port 6653).
3. **Distributed Controller State**: Deploy multiple controller nodes behind a virtual IP with state synchronization (e.g., Redis or etcd) to handle switch handoffs and eliminate single points of failure.
4. **Production Server Telemetry**: Replace simulated background ping/iperf monitors with lightweight eBPF agents or Prometheus node-exporters streaming real server metrics (CPU, queue depth, memory) to the controller via gRPC or REST.
