import sys
sys.path.insert(0, '/home/arjun/SDN-Based-Service-Aware-Load-Distribution/controller')
from config_loader import load_config
from network_monitor import NetworkMonitor
import logging

cfg = load_config('/home/arjun/SDN-Based-Service-Aware-Load-Distribution/config.yaml')
mon = NetworkMonitor(cfg, cfg.servers, logging.getLogger('test'))
s1 = cfg.servers[0]

# Simulate 2 timed-out probes before server is up:
mon.next_probe(s1, 100.0)
mon.next_probe(s1, 101.0)
# Fix in expire_probes: only append False if server.up
for seq, (server, sent_at) in list(mon._outstanding.items()):
    if 103.0 - sent_at > mon.timeout:
        del mon._outstanding[seq]
        if server.up:
            server.probe_window.append(False)
        server.consecutive_misses += 1

print("Before up - up:", s1.up, "loss_rate:", s1.loss_rate())

# Server answers probe 3:
seq = mon.next_probe(s1, 104.0)
mon.probe_reply(s1.ip, NetworkMonitor.PROBE_ID, seq, 104.004)
# When server comes UP, reset probe window to full True:
changed = []
for s in mon.servers:
    up_now = s.rtt_ms is not None and s.consecutive_misses < mon.down_after
    if up_now != s.up:
        s.up = up_now
        if up_now:
            s.probe_window.clear()
            s.probe_window.extend([True] * s.probe_window.maxlen)
        else:
            s.rtt_ms = None
        changed.append(s)

print("After first reply - up:", s1.up, "loss_rate:", s1.loss_rate())

# Server answers probe 4:
seq = mon.next_probe(s1, 105.0)
mon.probe_reply(s1.ip, NetworkMonitor.PROBE_ID, seq, 105.004)
print("After second reply - up:", s1.up, "loss_rate:", s1.loss_rate())
