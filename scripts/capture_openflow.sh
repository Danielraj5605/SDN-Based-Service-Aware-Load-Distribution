#!/usr/bin/env bash
# scripts/capture_openflow.sh
# Captures OpenFlow 1.3 control channel packets on loopback (port 6653) for 30 seconds
# and prints PacketIn / FlowMod message counts.
#
# DO NOT run automatically during automated tests. Run manually during demo runs.
# Usage:
#   bash scripts/capture_openflow.sh
#   or: sudo bash scripts/capture_openflow.sh

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RESULTS_DIR="${ROOT}/results"
mkdir -p "${RESULTS_DIR}"
PCAP_FILE="${RESULTS_DIR}/openflow_capture.pcap"

echo "================================================================="
echo " SDN OpenFlow Control Plane Capture (30 seconds on port 6653)"
echo "================================================================="

if ! command -v tshark &> /dev/null; then
    echo "ERROR: tshark is not installed. Install with: sudo apt-get install -y tshark"
    exit 1
fi

echo "[*] Capturing loopback traffic on TCP port 6653 for 30s..."
echo "[*] Run demo traffic flows now (e.g. h1 iperf or h2 udp_client in Mininet)..."

# Capture for 30 seconds
tshark -i lo -f "tcp port 6653" -a duration:30 -w "${PCAP_FILE}" -q 2>/dev/null || true

echo "[+] Capture complete: ${PCAP_FILE}"
echo ""
echo "=== OpenFlow 1.3 Message Summary ==="

TOTAL_OF=$(tshark -r "${PCAP_FILE}" -Y "openflow_v4" 2>/dev/null | wc -l || echo 0)
PACKET_IN=$(tshark -r "${PCAP_FILE}" -Y "openflow_v4.type == 10" 2>/dev/null | wc -l || echo 0)
FLOW_MOD=$(tshark -r "${PCAP_FILE}" -Y "openflow_v4.type == 14" 2>/dev/null | wc -l || echo 0)
ECHO_REQ=$(tshark -r "${PCAP_FILE}" -Y "openflow_v4.type == 2" 2>/dev/null | wc -l || echo 0)
ECHO_REP=$(tshark -r "${PCAP_FILE}" -Y "openflow_v4.type == 3" 2>/dev/null | wc -l || echo 0)
STATS_REQ=$(tshark -r "${PCAP_FILE}" -Y "openflow_v4.type == 18" 2>/dev/null | wc -l || echo 0)
STATS_REP=$(tshark -r "${PCAP_FILE}" -Y "openflow_v4.type == 19" 2>/dev/null | wc -l || echo 0)

echo "  Total OpenFlow 1.3 Packets : ${TOTAL_OF}"
echo "  OFPT_PACKET_IN  (Type 10)  : ${PACKET_IN}  (First packet of new flows punted to Ryu)"
echo "  OFPT_FLOW_MOD   (Type 14)  : ${FLOW_MOD}   (Forward/Reverse VIP rewrite rules installed)"
echo "  OFPT_ECHO_REQ/REP (Type 2/3): $((ECHO_REQ + ECHO_REP))   (Switch keepalives)"
echo "  OFPT_STATS_REQ/REP(18/19)  : $((STATS_REQ + STATS_REP))   (Port & flow telemetry polling)"
echo "================================================================="
echo "PCAP evidence saved to: ${PCAP_FILE}"
