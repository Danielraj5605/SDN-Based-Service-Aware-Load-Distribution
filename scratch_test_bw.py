import sys
sys.path.insert(0, '/home/arjun/SDN-Based-Service-Aware-Load-Distribution/controller')
from config_loader import load_config
from decision_engine import DecisionEngine

for file_bw in [20, 50, 70, 80, 90]:
    cfg = load_config('/home/arjun/SDN-Based-Service-Aware-Load-Distribution/config.yaml')
    cfg.services['file']['expected_mbps'] = file_bw
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

    # t=0: file 1 on srv1
    p1, _, _ = engine.select('service_aware', 'file', cfg.servers, 1000.0)
    p1.record_assignment(1000.0, cfg.expected_mbps('file'))
    # t=0.01: file 2 on srv2
    p2, _, _ = engine.select('service_aware', 'file', cfg.servers, 1000.01)
    p2.record_assignment(1000.01, cfg.expected_mbps('file'))

    # t=2.0: video 1
    p3, _, sc3 = engine.select('service_aware', 'video', cfg.servers, 1002.0)
    p3.record_assignment(1002.0, cfg.expected_mbps('video'))
    # t=2.01: video 2
    p4, _, sc4 = engine.select('service_aware', 'video', cfg.servers, 1002.01)

    print(f"file_expected={file_bw} => Video1: {p3.name} (s1={sc3['srv1']:.3f}, s4={sc3['srv4']:.3f}) | Video2: {p4.name} (s1={sc4['srv1']:.3f}, s4={sc4['srv4']:.3f})")
