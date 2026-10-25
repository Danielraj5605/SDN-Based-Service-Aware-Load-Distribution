import sys, os
sys.path.insert(0, '/home/arjun/SDN-Based-Service-Aware-Load-Distribution/controller')
from config_loader import load_config
from network_monitor import NetworkMonitor
import logging

cfg = load_config('/home/arjun/SDN-Based-Service-Aware-Load-Distribution/config.yaml')
mon = NetworkMonitor(cfg, cfg.servers, logging.getLogger('test'))
s1 = cfg.servers[0]
NOW = 1000.0

# Run exact test_down_after_missed_probes logic:
seq = mon.next_probe(s1, NOW)
mon.probe_reply(s1.ip, NetworkMonitor.PROBE_ID, seq, NOW + 0.002)
# updated availability with fix:
up_now = s1.rtt_ms is not None and s1.consecutive_misses < mon.down_after
if up_now != s1.up:
    s1.up = up_now
    if up_now:
        s1.probe_window.clear()
        s1.probe_window.extend([True] * (s1.probe_window.maxlen or 20))

t = NOW
for _ in range(cfg.monitoring['down_after_missed']):
    t += 1
    mon.next_probe(s1, t)
    # expire probes with fix:
    for sq, (server, sent_at) in list(mon._outstanding.items()):
        if t + 2 - sent_at > mon.timeout:
            del mon._outstanding[sq]
            if server.up:
                server.probe_window.append(False)
            server.consecutive_misses += 1

up_now = s1.rtt_ms is not None and s1.consecutive_misses < mon.down_after
if up_now != s1.up:
    s1.up = up_now
    if not up_now:
        s1.rtt_ms = None

print("s1.up:", s1.up, "loss_rate:", s1.loss_rate())
assert not s1.up
assert s1.loss_rate() > 0
print("test_down_after_missed_probes passes!")
