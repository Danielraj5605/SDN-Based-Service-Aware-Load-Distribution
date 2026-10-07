"""Decision Engine: per-service suitability score and server selection.

    Score = w_health*H + w_bandwidth*B + w_latency*L + w_loss*P + w_match*M

    H  server health      1 - weighted(CPU, memory, sessions)
    B  bandwidth          available Mbit/s on the server link / reference capacity
    L  latency            1 - RTT / max_latency_ms
    P  reliability        1 - probe loss rate
    M  service match      1 if the server is designated for the service, else service_mismatch

All factors are in [0, 1]; the weights come from the service's profile in config.yaml.
"""
from config_loader import ROUND_ROBIN, WEIGHT_KEYS


def _clamp01(x):
    return max(0.0, min(1.0, x))


class DecisionEngine:
    def __init__(self, cfg):
        self.cfg = cfg
        self._rr_next = 0

    def bandwidth_ref(self, servers):
        ref = float(self.cfg.scoring['bandwidth_ref_mbps'] or 0)
        return ref if ref > 0 else max(s.capacity_mbps for s in servers)

    def weights(self, service):
        svc = self.cfg.services.get(service, self.cfg.services['default'])
        w = svc['weights']
        total = sum(w[k] for k in WEIGHT_KEYS)
        return {k: w[k] / total for k in WEIGHT_KEYS}

    def factors(self, server, service, now, bw_ref):
        sc = self.cfg.scoring
        sessions = _clamp01(server.sessions() / float(sc['max_sessions']))
        if server.agent_ok:
            mix = sc['health_mix']
            total = float(sum(mix.values())) or 1.0
            load = (mix.get('cpu', 0) * server.cpu / 100.0
                    + mix.get('mem', 0) * server.mem / 100.0
                    + mix.get('sessions', 0) * sessions) / total
            health = 1.0 - load
        else:
            health = float(sc['unknown_health']) * (1.0 - sessions)

        max_lat = float(sc['max_latency_ms'])
        rtt = server.rtt_ms if server.rtt_ms is not None else max_lat
        return {
            'health': _clamp01(health),
            'bandwidth': _clamp01(server.available_mbps(now, sc['pending_window']) / bw_ref),
            'latency': _clamp01(1.0 - rtt / max_lat),
            'loss': _clamp01(1.0 - server.loss_rate()),
            'match': 1.0 if service in server.services else float(sc['service_mismatch']),
        }

    def score(self, server, service, now, bw_ref):
        f = self.factors(server, service, now, bw_ref)
        w = self.weights(service)
        return sum(w[k] * f[k] for k in WEIGHT_KEYS), f

    def select(self, mode, service, servers, now):
        """Return (server, reason, {server_name: score})."""
        candidates = [s for s in servers if s.up]
        if not candidates:
            # Nothing has answered a probe yet (or everything is down): degrade to round robin.
            return self._round_robin(servers), 'fallback_round_robin', {}
        if mode == ROUND_ROBIN:
            return self._round_robin(candidates), 'round_robin', {}

        bw_ref = self.bandwidth_ref(servers)
        scores = {s.name: round(self.score(s, service, now, bw_ref)[0], 4) for s in candidates}
        # Highest score wins; ties go to the server with fewer sessions, then the lower index.
        best = max(candidates, key=lambda s: (scores[s.name], -s.sessions(), -s.index))
        return best, 'service_aware', scores

    def better_server(self, current, service, servers, now, min_gain):
        """For live rebalancing: a server scoring at least `min_gain` above `current`, else None.

        The flow's own traffic is part of `current`'s measured load, so the
        threshold acts as hysteresis against flows bouncing between servers.
        """
        candidates = [s for s in servers if s.up and s is not current]
        if not candidates:
            return None
        bw_ref = self.bandwidth_ref(servers)
        current_score = self.score(current, service, now, bw_ref)[0] if current.up else 0.0
        best = max(candidates, key=lambda s: (self.score(s, service, now, bw_ref)[0], -s.index))
        if self.score(best, service, now, bw_ref)[0] - current_score >= min_gain:
            return best
        return None

    def _round_robin(self, candidates):
        ordered = sorted(candidates, key=lambda s: s.index)
        choice = ordered[self._rr_next % len(ordered)]
        self._rr_next += 1
        return choice
