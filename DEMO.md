# SDN Service-Aware Load Distribution — 5-Minute Faculty Demonstration Guide

> **Project Goal:** Demonstrate that an OpenFlow 1.3 SDN controller dynamically scoring server health, link capacity, latency, loss, and service type dramatically outperforms standard Round Robin load balancing by shielding interactive traffic (VoIP, Video) from TCP bufferbloat.

---

## 0. Pre-Flight Preparation (30 seconds before demo)

Open **two WSL2 terminal windows** on Windows 11. Ensure Open vSwitch is running.

```bash
# In Terminal 1: Ensure OVS service is active and clean any stale mininet sessions
sudo service openvswitch-switch start
sudo mn -c
```

---

## Step 1: Launch Controller & Open Live Dashboard (1 minute)

### Terminal 1: Start the Ryu SDN Controller
```bash
cd ~/SDN-Based-Service-Aware-Load-Distribution
export PYTHONPATH=~/.local/lib/python3.8/site-packages:$PYTHONPATH
python3 ~/.local/bin/ryu-manager controller/lb_controller.py
```
*Expected Output:*
```
Service-aware LB: VIP 10.0.0.100, 4 servers, mode=service_aware
(xxxx) wsgi starting up on http://0.0.0.0:8080
```

### Windows Browser: Open the Live Dashboard
Open your Windows browser (Chrome / Edge / Firefox) and navigate to:
👉 **`http://127.0.0.1:8080/lb/dashboard`**

> **What to point at on screen:**
> - Point to the top banner: **VIP 10.0.0.100**, mode is **Service-Aware**, switch status shows `Switch Connecting…`.
> - Point to the 4 server cards: `srv1` (100M general), `srv2` (100M bulk), `srv3` (10M voice), `srv4` (50M video). All initial link loss counters are clean at `0.0%`.

---

## Step 2: Connect the Topology & Observe Real-Time Probing (45 seconds)

### Terminal 2: Start Mininet Network
```bash
cd ~/SDN-Based-Service-Aware-Load-Distribution
sudo python3 topology/sdn_topology.py
```
*Expected Output:* Mininet prompt `mininet>` appears.

> **What to point at on screen:**
> - Point to the dashboard header: Status pill immediately switches to **`Switch Connected`** in green.
> - Point to the 4 server cards: All four switch to **`● UP`** with live agent stats (CPU %, Memory %).
> - Point to the **Real-Time ICMP Latency Chart**: Curves start plotting RTT to each server (srv3 at ~2 ms, srv1 at ~4 ms, srv4 at ~20 ms, srv2 at ~50 ms).

---

## Step 3: Service-Aware Traffic Routing (VoIP + Bulk File) (1.5 minutes)

In Terminal 2 (at the `mininet>` prompt), launch a heavy bulk TCP transfer on client `h1`, followed by a delay-sensitive VoIP stream on client `h2`:

```bash
mininet> h1 iperf -c 10.0.0.100 -p 2121 -t 15 &
mininet> h2 python3 traffic/udp_client.py --host 10.0.0.100 --port 5060 --duration 10
```

> **What to point at on screen:**
> 1. **"Last Decision" Breakdown Banner**:
>    - Shows flow `10.0.0.1:2121 [FILE]` assigned to **`srv1`** (or `srv2`).
>    - Shows flow `10.0.0.2:5060 [VOIP]` assigned to **`srv3`** in **< 0.1 ms**.
>    - Expand/point to the factor matrix: Explain how `srv3` scored highest for voice because of its 1 ms latency factor ($L=0.98$) and designated match ($M=1.0$), while `srv1` was discounted due to bulk bandwidth load.
> 2. **Server Cards**:
>    - Point to `srv1`: Bandwidth meter jumps to **98 Mbit/s** (near 100% saturation).
>    - Point to `srv3`: Carrying VoIP cleanly with **0.0% loss** and **~2.5 ms RTT**.
> 3. **Terminal 2 VoIP Output**:
>    - Show the faculty the final measured stats: `Loss: 0.0%`, `RTT avg: ~2.5 ms`, `Jitter: ~0.17 ms`.

---

## Step 3b: Control-Plane OpenFlow Verification (Evidence Capture) (Optional / Defense)

If a faculty member asks *"How do you prove OpenFlow rules are being dynamically installed and the controller isn't inspecting every single packet in the data path?"*:

### Terminal 3 (or background WSL shell): Run the capture script
```bash
bash scripts/capture_openflow.sh
```
*Run this right as Step 3's traffic starts.* It captures OpenFlow control-plane traffic on port 6653 for 30 seconds and outputs a message breakdown.

> **What to point at on screen:**
> - **OFPT_PACKET_IN (Type 10)**: Show that only the *initial packet* of each stream is punted to Ryu (e.g., 2–4 PacketIn events).
> - **OFPT_FLOW_MOD (Type 14)**: Show that Ryu immediately installs matching bidirectional rewrite rules into OVS table 0.
> - **Wire-Speed Forwarding**: Emphasize that all subsequent megabytes of data flow directly through Open vSwitch without touching the Python controller.
> - **Evidence File**: Point out `results/openflow_capture.pcap` which can be opened in Wireshark for deep packet inspection.

---

## Step 4: Contrast with Round Robin (Bufferbloat Exposure) (1 minute)

Now switch the controller to Round Robin mode to show what happens in conventional load balancers.

### Click the "Round Robin" button on the live dashboard (or in Terminal 2):
```bash
# You can click "Round Robin" directly on the UI, or run:
mininet> sh python3 tools/lbctl.py mode rr
```

Now repeat the exact same traffic mix:
```bash
mininet> h1 iperf -c 10.0.0.100 -p 2121 -t 15 &
mininet> h2 python3 traffic/udp_client.py --host 10.0.0.100 --port 5060 --duration 10
```

> **What to point at on screen:**
> 1. **Dashboard Active Flows**:
>    - Round Robin blindly assigns the VoIP call to the next server in sequence (`srv1` or `srv2`), which is currently saturated by the 100 Mbit/s bulk TCP file transfer!
> 2. **Terminal 2 VoIP Output**:
>    - Point to the catastrophic latency: RTT shoots up from 2.5 ms to **500+ ms (p95 over 950 ms!)** due to switch queue bufferbloat.
> 3. **Key Faculty Takeaway**:
>    - Explain: *"This is the core problem our project solves. Blind round robin causes 200× latency degradation for voice. Service-aware SDN routing keeps VoIP at 2.5 ms."*

---

## Step 5: Fault Tolerance & Server Failure Recovery (45 seconds)

Switch back to Service-Aware mode:
```bash
mininet> sh python3 tools/lbctl.py mode sa
```

Simulate a physical link failure on the voice server (`srv3`):
```bash
mininet> link s1 srv3 down
```

> **What to point at on screen:**
> 1. **Server Cards**:
>    - Within 3.5 seconds (after 3 consecutive missed probes), `srv3` card turns red: **`▲ DOWN`**.
> 2. **Live Suitability Matrix**:
>    - `srv3` is greyed out. The highlight for VoIP dynamically moves to the next best candidate (`srv1`).
> 3. Launch a new call to verify failover:
>    ```bash
>    mininet> h2 curl -s 10.0.0.100:8080
>    ```
>    - Proves requests immediately bypass the dead server and answer from an active server.
> 4. Restore the link:
>    ```bash
>    mininet> link s1 srv3 up
>    ```
>    - Within 2 seconds, `srv3` responds to ICMP probes and returns to **`● UP`** with 0% loss.

---

## Step 6: Review Faculty Results Dashboard (30 seconds)

In your Windows browser, open the standalone results file:
👉 **`file:///c:/Users/mjarj/Desktop/Arjun/TECH%20VOID/SDN-Based-Service-Aware-Load-Distribution/results/dashboard.html`**

> **What to point at on screen:**
> 1. **Empirical Bar Charts with Standard Deviations**:
>    - VoIP RTT: **244.4 ms** (Round Robin) $\rightarrow$ **2.51 ms** (Service-Aware).
>    - VoIP Loss: **0.45%** $\rightarrow$ **0.00%**.
>    - Video RTT: **20.5 ms** steady.
> 2. **Decision Latency (NFR-1)**:
>    - Average decision latency is **0.093 ms**, well within the 5.0 ms threshold.
> 3. **Honest Trade-Offs Section**:
>    - Point to the explanation of the Jain's fairness index (0.60 vs 0.72) and Video RTT (20 ms vs 11 ms). Explain that isolating voice onto `srv3` deliberately sacrifices link utilization fairness to protect real-time quality.

---

## Demo Teardown
In Terminal 2:
```bash
mininet> exit
sudo mn -c
```
In Terminal 1:
Press `Ctrl+C` to stop Ryu.
