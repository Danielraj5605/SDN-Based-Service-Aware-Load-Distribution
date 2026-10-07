"""Unit tests for the pure-Python parts of the controller (no Ryu or Mininet needed).

    python3 -m unittest discover -s tests -v
"""
import copy
import logging
import os
import sys
import unittest

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'controller'))

from classifier import ServiceClassifier, parse_port_spec         # noqa: E402
from config_loader import ROUND_ROBIN, SERVICE_AWARE, Config, ConfigError, normalise_mode  # noqa: E402
from decision_engine import DecisionEngine                        # noqa: E402
from network_monitor import NetworkMonitor                        # noqa: E402

with open(os.path.join(ROOT, 'config.yaml')) as f:
    RAW = yaml.safe_load(f)

LOG = logging.getLogger('test')
NOW = 1000.0


def make_cfg(mutate=None):
    raw = copy.deepcopy(RAW)
    if mutate:
        mutate(raw)
    return Config(raw)


def healthy(server, rtt, cpu=10.0, mem=10.0, used=0.0):
    server.up, server.agent_ok = True, True
    server.rtt_ms, server.cpu, server.mem, server.used_mbps = rtt, cpu, mem, used
    server.probe_window.extend([True] * 10)
    return server


class ConfigTests(unittest.TestCase):
    def test_loads_project_config(self):
        cfg = make_cfg()
        self.assertEqual([s.name for s in cfg.servers], ['srv1', 'srv2', 'srv3', 'srv4'])
        self.assertEqual(cfg.servers[2].capacity_mbps, 10.0)
        self.assertEqual(cfg.servers[0].index, 1)

    def test_mode_aliases(self):
        self.assertEqual(normalise_mode('rr'), ROUND_ROBIN)
        self.assertEqual(normalise_mode('Service-Aware'), SERVICE_AWARE)
        with self.assertRaises(ConfigError):
            normalise_mode('random')

    def test_rejects_bad_weights(self):
        def bad(raw):
            raw['services']['voip']['weights']['speed'] = 1
        with self.assertRaises(ConfigError):
            make_cfg(bad)

    def test_rejects_unknown_service_on_server(self):
        def bad(raw):
            raw['servers'][0]['services'] = ['gaming']
        with self.assertRaises(ConfigError):
            make_cfg(bad)


class ClassifierTests(unittest.TestCase):
    def setUp(self):
        self.c = ServiceClassifier(make_cfg().services)

    def test_ports(self):
        self.assertEqual(self.c.classify(17, 5060), 'voip')
        self.assertEqual(self.c.classify(17, 20000), 'voip')       # RTP range
        self.assertEqual(self.c.classify(17, 5004), 'video')
        self.assertEqual(self.c.classify(6, 8554), 'video')
        self.assertEqual(self.c.classify(6, 2121), 'file')
        self.assertEqual(self.c.classify(6, 8080), 'default')
        self.assertEqual(self.c.classify(1, None), 'default')      # ICMP

    def test_protocol_matters(self):
        self.assertEqual(self.c.classify(6, 5004), 'default')      # 5004 is only video over UDP

    def test_port_spec(self):
        self.assertEqual(parse_port_spec('100-200'), (100, 200))
        self.assertEqual(parse_port_spec(80), (80, 80))
        with self.assertRaises(ValueError):
            parse_port_spec('9-1')


class DecisionTests(unittest.TestCase):
    def setUp(self):
        self.cfg = make_cfg()
        self.s1, self.s2, self.s3, self.s4 = self.cfg.servers
        NetworkMonitor(self.cfg, self.cfg.servers, LOG)            # sizes the probe windows
        self.engine = DecisionEngine(self.cfg)

    def all_healthy(self):
        healthy(self.s1, 4)
        healthy(self.s2, 50)
        healthy(self.s3, 2)
        healthy(self.s4, 20, cpu=60)

    def test_voip_avoids_high_latency(self):
        self.all_healthy()
        self.s1.rtt_ms = 80                     # srv1 congested -> queueing delay
        server, reason, scores = self.engine.select(SERVICE_AWARE, 'voip', self.cfg.servers, NOW)
        self.assertEqual(server.name, 'srv3')
        self.assertEqual(reason, 'service_aware')
        self.assertLess(scores['srv2'], scores['srv3'])

    def test_video_prefers_bandwidth(self):
        self.all_healthy()
        server, _, scores = self.engine.select(SERVICE_AWARE, 'video', self.cfg.servers, NOW)
        self.assertIn(server.name, ('srv1', 'srv2'))
        self.assertLess(scores['srv3'], scores[server.name])     # 10 Mbit/s link loses

    def test_file_goes_to_far_server_when_near_one_is_full(self):
        self.all_healthy()
        self.s1.used_mbps = 95
        server, _, _ = self.engine.select(SERVICE_AWARE, 'file', self.cfg.servers, NOW)
        self.assertEqual(server.name, 'srv2')

    def test_pending_reservation_spreads_burst(self):
        self.all_healthy()
        first, _, _ = self.engine.select(SERVICE_AWARE, 'file', self.cfg.servers, NOW)
        for _ in range(4):
            first.record_assignment(NOW, self.cfg.expected_mbps('file'))
        second, _, _ = self.engine.select(SERVICE_AWARE, 'file', self.cfg.servers, NOW + 0.1)
        self.assertNotEqual(first.name, second.name)

    def test_pending_reservation_expires(self):
        self.s1.record_assignment(NOW, 50)
        self.assertEqual(self.s1.available_mbps(NOW + 1, 4), 50)
        self.assertEqual(self.s1.available_mbps(NOW + 5, 4), 100)

    def test_down_servers_are_skipped(self):
        self.all_healthy()
        self.s3.up = False
        for _ in range(8):
            server, _, _ = self.engine.select(SERVICE_AWARE, 'voip', self.cfg.servers, NOW)
            self.assertNotEqual(server.name, 'srv3')

    def test_round_robin_cycles_over_up_servers(self):
        self.all_healthy()
        self.s2.up = False
        picks = [self.engine.select(ROUND_ROBIN, 'voip', self.cfg.servers, NOW)[0].name
                 for _ in range(6)]
        self.assertEqual(picks, ['srv1', 'srv3', 'srv4'] * 2)

    def test_fallback_when_nothing_is_up(self):
        server, reason, _ = self.engine.select(SERVICE_AWARE, 'voip', self.cfg.servers, NOW)
        self.assertEqual(reason, 'fallback_round_robin')
        self.assertIsNotNone(server)

    def test_silent_agent_gets_neutral_health(self):
        healthy(self.s1, 4).agent_ok = False
        f = self.engine.factors(self.s1, 'voip', NOW, 100)
        self.assertAlmostEqual(f['health'], self.cfg.scoring['unknown_health'])

    def test_scores_stay_in_range(self):
        self.all_healthy()
        self.s4.cpu, self.s4.mem, self.s4.active_flows = 100, 100, 500
        for svc in self.cfg.services:
            for s in self.cfg.servers:
                score, factors = self.engine.score(s, svc, NOW, 100)
                self.assertTrue(0 <= score <= 1)
                self.assertTrue(all(0 <= v <= 1 for v in factors.values()))


class NetworkMonitorTests(unittest.TestCase):
    def setUp(self):
        self.cfg = make_cfg()
        self.mon = NetworkMonitor(self.cfg, self.cfg.servers, LOG)
        self.s1 = self.cfg.servers[0]

    def test_probe_reply_sets_rtt_and_up(self):
        seq = self.mon.next_probe(self.s1, NOW)
        self.assertTrue(self.mon.probe_reply(self.s1.ip, NetworkMonitor.PROBE_ID, seq, NOW + 0.004))
        self.assertAlmostEqual(self.s1.rtt_ms, 4.0, places=3)
        self.assertIn(self.s1, self.mon.update_availability())
        self.assertTrue(self.s1.up)

    def test_foreign_icmp_ignored(self):
        self.assertFalse(self.mon.probe_reply(self.s1.ip, 1234, 1, NOW))

    def test_down_after_missed_probes(self):
        seq = self.mon.next_probe(self.s1, NOW)
        self.mon.probe_reply(self.s1.ip, NetworkMonitor.PROBE_ID, seq, NOW + 0.002)
        self.mon.update_availability()
        t = NOW
        for _ in range(self.cfg.monitoring['down_after_missed']):
            t += 1
            self.mon.next_probe(self.s1, t)
            self.mon.expire_probes(t + 2)
        self.mon.update_availability()
        self.assertFalse(self.s1.up)
        self.assertGreater(self.s1.loss_rate(), 0)

    def test_port_stats_bandwidth(self):
        self.mon.port_stats([(1, 0, 0)], NOW)
        self.mon.port_stats([(1, 25_000_000, 1_000_000)], NOW + 2)    # 100 Mbit/s over 2 s
        self.assertAlmostEqual(self.s1.used_mbps, 100 * self.cfg.monitoring['ewma_alpha'])
        self.mon.port_stats([(99, 5, 5)], NOW + 3)                     # unknown port ignored


if __name__ == '__main__':
    unittest.main()
