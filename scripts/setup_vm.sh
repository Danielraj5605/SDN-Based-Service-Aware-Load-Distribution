#!/usr/bin/env bash
# One-shot setup for the Ubuntu 20.04 VM: installs everything and verifies it.
#
#   bash scripts/setup_vm.sh
#
# Safe to re-run. Asks for your sudo password once.
set -euo pipefail

cd "$(dirname "$0")/.."
PROJECT_DIR="$(pwd)"
ok()   { printf '  \033[32m[ok]\033[0m %s\n' "$*"; }
fail() { printf '  \033[31m[fail]\033[0m %s\n' "$*"; exit 1; }
step() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }

step "Checking the environment"
. /etc/os-release
[[ "${ID}" == "ubuntu" ]] || fail "this script targets Ubuntu (found ${ID})"
[[ "${VERSION_ID}" == "20.04" ]] && ok "Ubuntu ${VERSION_ID}" \
  || printf '  [warn] Ubuntu %s - 20.04 is recommended (Python 3.8 for Ryu)\n' "${VERSION_ID}"
PYV=$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')
case "${PYV}" in
  3.8|3.9) ok "Python ${PYV}" ;;
  *) fail "Python ${PYV} found - Ryu 4.34 needs Python 3.8 or 3.9 (use Ubuntu 20.04)" ;;
esac
grep -Eqc '(vmx|svm)' /proc/cpuinfo && ok "CPU virtualisation visible" \
  || printf '  [warn] no vmx/svm flag - fine inside a VM, Mininet does not need nested virtualisation\n'

step "Installing system packages (Mininet, Open vSwitch, iperf, Python libs)"
sudo apt-get update -qq
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
  mininet openvswitch-switch iperf iperf3 curl git net-tools tshark \
  python3-pip python3-yaml python3-psutil > /dev/null
sudo systemctl enable --now openvswitch-switch > /dev/null 2>&1 || true
ok "apt packages installed"

step "Installing Python packages for the controller"
python3 -m pip install --user -q --upgrade "pip<24"
python3 -m pip install --user -q "setuptools<58"
python3 -m pip install --user -q -r "${PROJECT_DIR}/requirements.txt"
if ! grep -q 'HOME/.local/bin' "${HOME}/.bashrc"; then
  echo 'export PATH=$HOME/.local/bin:$PATH' >> "${HOME}/.bashrc"
fi
export PATH="${HOME}/.local/bin:${PATH}"
ok "pip packages installed"

step "Verifying"
command -v mn > /dev/null && ok "mininet $(mn --version 2>&1 | head -1)" || fail "mn not found"
ok "$(ovs-vsctl --version | head -1)"
ryu-manager --version > /dev/null 2>&1 && ok "ryu $(ryu-manager --version 2>&1 | awk '{print $2}')" \
  || fail "ryu-manager does not start - try: pip3 install --user eventlet==0.30.2"
python3 -c 'import yaml, psutil, pandas, matplotlib' && ok "python libraries import"
python3 -m unittest discover -s tests > /tmp/sdn_lb_unittest.log 2>&1 \
  && ok "unit tests: $(grep -Eo 'Ran [0-9]+ tests' /tmp/sdn_lb_unittest.log)" \
  || fail "unit tests failed - see /tmp/sdn_lb_unittest.log"
sudo mn -c > /dev/null 2>&1 || true
if sudo mn --test pingall 2>&1 | grep -q 'Results: 0% dropped'; then
  ok "mininet pingall: 0% dropped"
else
  fail "mininet self-test failed - run 'sudo mn --test pingall' to see why"
fi

step "Done. Next:"
cat <<EOF
  terminal 1:  cd ${PROJECT_DIR} && ryu-manager controller/lb_controller.py
  terminal 2:  cd ${PROJECT_DIR} && sudo python3 topology/sdn_topology.py
  browser:     http://127.0.0.1:8080/lb/dashboard
  full check:  sudo python3 tests/functional_test.py      (with the controller running)
EOF
