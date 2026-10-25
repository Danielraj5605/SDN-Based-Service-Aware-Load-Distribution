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
mon.expire_probes(103.0)
print("Before up - up:", s1.up, "loss_rate:", s1.loss_rate())

# Server answers probe 3:
seq = mon.next_probe(s1, 104.0)
mon.probe_reply(s1.ip, NetworkMonitor.PROBE_ID, seq, 104.004)
mon.update_availability()
print("After first reply - up:", s1.up, "loss_rate:", s1.loss_rate())

# Server answers probe 4:
seq = mon.next_probe(s1, 105.0)
mon.probe_reply(s1.ip, NetworkMonitor.PROBE_ID, seq, 105.004)
print("After second reply - up:", s1.up, "loss_rate:", s1.loss_rate())
