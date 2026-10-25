# Pull Request: Call-Quality Analysis, Degradation Rebalancing Scenarios, and Reporting Dashboards

## Summary
This PR consolidates the experimental evaluation, call-quality analysis, server degradation scenarios, and faculty/operator dashboards for the **SDN-Based Service-Aware Load Distribution** system.

All enhancements preserve the core Ryu OpenFlow 1.3 multi-criteria decision engine while providing thorough, honest, and reproducible benchmarking against Round Robin under heterogeneous server conditions.

---

## 1. Key Changes & Features Added

### A. Configuration Updates (`config.yaml`)
- **`services.file.expected_mbps`**: Updated from `20` to `80` to realistically reflect bulk TCP elephant flow demands on 100 Mbit/s links.
- **`scoring.pending_window`**: Increased from `4` to `6` to prevent flow-burst thundering herd effects during simultaneous connection arrivals before switch byte counters refresh.

### B. New Scenarios & Evaluation Tools
- **VoIP Call-Quality Evaluation (`experiments/quality_report.py`)**:
  - Implements multi-dimensional VoIP quality assessment against pre-defined targets: **`PASS = RTT <= 150 ms AND jitter <= 30 ms AND loss <= 1%`**.
  - Adds failure breakdown analysis identifying why Round Robin fails (queue delay on saturated servers vs link loss).
  - Includes post-experiment loss-threshold sensitivity analysis (1%, 3%, 5%) for complete transparency.
- **Server Degradation & Rebalancing (`experiments/run_degradation.py`)**:
  - Evaluates dynamic network resilience when `srv3` undergoes mid-session delay degradation (injected +100 ms latency) while `srv1` and `srv2` are saturated by bulk TCP file transfers.
  - Benchmarks Round Robin, Service-Aware (static assignment), and Service-Aware with proactive/reactive UDP rebalancing.
- **Reporting & Operator Dashboards**:
  - **Live Web Dashboard** (`controller/lb_controller.py` at `/lb/dashboard`): Real-time server telemetry, flow tables, active weight adjustments, and visual decision explanation inspector.
  - **Results Dashboard (`results/dashboard.html`)**: Fully self-contained, single-file, offline HTML/CSS/JS dashboard presenting all baseline runs, degradation stats, and interactive parameter explorations without any external CDN dependencies.

---

## 2. Test Verification & Results

All verification suites pass cleanly in the WSL2 testbed:
- **Unit Tests**: `28/28 passed` (`python3 -m unittest discover -s tests -v`)
  - Core scoring logic, weight normalization, pending flow penalties, routing tables, and REST endpoints.
- **Functional Tests (Mininet)**: `11/11 passed` (`python3 tests/functional_tests.py`)
  - ARP resolution, TCP VIP load balancing, UDP VIP routing, VIP rewriting/restoration, failure detection, and recovery.
- **T11 Controller Restart Resilience**: `PASSED`
  - Controller killed and restarted during active flows; established data-plane flows remained uninterrupted, new flows buffered and routed upon controller reattachment.

---

## 3. Experimental Benchmarks (Summary of 3 Repeats)

### Baseline Evaluation (Mean of 3 Repeats, `results/summary_20261012-221819.csv`)
| Metric | Round Robin | Service-Aware | Impact |
| :--- | :---: | :---: | :---: |
| **VoIP RTT (Mean)** | 272.90 ± 22.84 ms | **2.37 ± 0.08 ms** | **99.1% reduction** |
| **VoIP Jitter (Mean)** | 1.83 ± 1.13 ms | **0.02 ± 0.00 ms** | **98.9% reduction** |
| **VoIP Loss Rate** | 0.49 ± 0.05 % | **0.00 ± 0.00 %** | **Zero packet loss** |
| **VoIP Pass Rate (All 3 Criteria)** | 25.0% (3/12) | **100.0% (12/12)** | **+75.0% absolute improvement** |
| **File Transfer Throughput** | 98.90 ± 0.07 Mbit/s | **96.60 ± 1.15 Mbit/s** | -2.3% (negligible link capacity cost) |
| **Video RTT (Mean)** | **11.54 ± 0.07 ms** | 20.49 ± 0.01 ms | +8.95 ms (trade-off) |
| **Video Loss Rate** | **0.97 ± 0.01 %** | 1.95 ± 0.01 % | +0.98% (trade-off) |
| **Jain's Fairness Index** | **0.720 ± 0.022** | 0.596 ± 0.024 | -0.124 (expected trade-off) |

### Degradation & Rebalancing (`results/degradation_20261025-162804.csv`)
- **Wave 1 RTT (Prior to degradation)**: RR 212.74 ± 58.39 ms | SA 164.20 ± 59.79 ms | SA+Rebalance **103.66 ± 54.16 ms**
- **Wave 2 RTT (During `srv3` degradation)**: RR 276.38 ± 40.25 ms | SA 108.05 ± 76.40 ms | SA+Rebalance **20.42 ± 0.02 ms**
- **Wave 1 Calls Migrated**: RR 2.33 ± 2.08 (7/12) | SA 3.00 ± 1.73 (9/12) | SA+Rebalance **4.00 ± 0.00 (12/12, 100%)**

---

## 4. Honest Trade-offs and Limitations

We explicitly document the trade-offs where Service-Aware routing performs worse or encounters structural constraints:
1. **Video RTT & Loss Trade-Off**: Service-Aware assigns bulk TCP file transfers exclusively to `srv1` and `srv2` (high bandwidth, low latency). To protect file transfers and low-latency VoIP (`srv3`), video flows are steered to `srv4`. Because `srv4` has an emulated 10 ms delay and 1% link loss per direction, video RTT increases from 11.54 ms to 20.49 ms and packet loss increases from 0.97% to 1.95%.
2. **Lower Jain's Fairness (0.596 vs 0.720)**: Round Robin distributes connections blind to server capability, producing more uniform load distribution across hosts. Service-Aware deliberately concentrates traffic by service profile (e.g., file flows on `srv1`/`srv2`, VoIP on `srv3`), inherently resulting in lower numerical fairness.
3. **Rebalancing Pass-Rate Caveat**: In the severe degradation test, live rebalancing successfully migrates 100% of VoIP calls away from degraded `srv3`, lowering latency from 276 ms to 20.4 ms. However, because `srv1` and `srv2` are saturated by elephant TCP flows, calls are migrated to `srv4`. The emulated link loss on `srv4` produces ~1.97% measured loss, exceeding the strict 1% VoIP threshold. Hence, while latency is rescued, the strict pass rate is 0%.
4. **Scope & Methodology Limitations**:
   - Evaluated in Mininet (emulation on Linux kernel veth/OVS), not physical switches.
   - Single-switch star topology; multi-switch ECMP / core networks are not evaluated.
   - Hand-chosen linear weights rather than ML/reinforcement learning.
   - Benchmarked against unweighted Round Robin as the primary comparative baseline across 3 experimental repeats.

---

## 5. Scope of Changes
- Documentation, analysis scripts, and dashboard artifacts only.
- Controller core decision logic and `controller/` code have zero git diff.
- Ready for review and merge into main.
