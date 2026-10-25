import sys
sys.path.insert(0, '/home/arjun/SDN-Based-Service-Aware-Load-Distribution/controller')
from config_loader import load_config
from decision_engine import DecisionEngine

cfg = load_config('/home/arjun/SDN-Based-Service-Aware-Load-Distribution/config.yaml')
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

# Decision 1: file
pick1, _, scores1 = engine.select('service_aware', 'file', cfg.servers, 1000.0)
print("Decision 1 (file):", pick1.name, scores1)
pick1.record_assignment(1000.0, 80.0)

# Decision 2: file
pick2, _, scores2 = engine.select('service_aware', 'file', cfg.servers, 1000.01)
print("Decision 2 (file):", pick2.name, scores2)
pick2.record_assignment(1000.01, 80.0)

# Decision 3: video
pick3, _, scores3 = engine.select('service_aware', 'video', cfg.servers, 1002.0)
print("Decision 3 (video):", pick3.name, scores3)
pick3.record_assignment(1002.0, 8.0)

# Decision 4: video
pick4, _, scores4 = engine.select('service_aware', 'video', cfg.servers, 1002.01)
print("Decision 4 (video):", pick4.name, scores4)
pick4.record_assignment(1002.01, 8.0)

# Decision 5: voip
pick5, _, scores5 = engine.select('service_aware', 'voip', cfg.servers, 1004.0)
print("Decision 5 (voip):", pick5.name, scores5)
