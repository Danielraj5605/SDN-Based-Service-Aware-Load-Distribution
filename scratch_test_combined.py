import sys
sys.path.insert(0, '/home/arjun/SDN-Based-Service-Aware-Load-Distribution/controller')
from config_loader import load_config
from decision_engine import DecisionEngine

cfg = load_config('/home/arjun/SDN-Based-Service-Aware-Load-Distribution/config.yaml')
cfg.services['file']['expected_mbps'] = 80
cfg.services['video']['weights'] = {'health': 0.20, 'bandwidth': 0.35, 'latency': 0.25, 'loss': 0.05, 'match': 0.15}
engine = DecisionEngine(cfg)
s1, s2, s3, s4 = cfg.servers
s1.rtt_ms = 4.0
s2.rtt_ms = 50.0
s3.rtt_ms = 2.0
s4.rtt_ms = 20.0
s4.cpu = 50.0
s4.mem = 20.0
for s in cfg.servers:
    s.up = True
    s.agent_ok = True
    s.probe_window.extend([True]*20)

# Idle state: who gets video when idle?
idle_pick, _, idle_scores = engine.select('service_aware', 'video', cfg.servers, 1000.0)
print(f"When IDLE: Video goes to {idle_pick.name}: {idle_scores}")

# During experiment:
p1, _, _ = engine.select('service_aware', 'file', cfg.servers, 1000.0)
p1.record_assignment(1000.0, cfg.expected_mbps('file'))

p2, _, _ = engine.select('service_aware', 'file', cfg.servers, 1000.01)
p2.record_assignment(1000.01, cfg.expected_mbps('file'))

p3, _, sc3 = engine.select('service_aware', 'video', cfg.servers, 1002.0)
p3.record_assignment(1002.0, cfg.expected_mbps('video'))

p4, _, sc4 = engine.select('service_aware', 'video', cfg.servers, 1002.01)

print(f"During FILE: Video 1 goes to {p3.name}: {sc3}")
print(f"During FILE: Video 2 goes to {p4.name}: {sc4}")
