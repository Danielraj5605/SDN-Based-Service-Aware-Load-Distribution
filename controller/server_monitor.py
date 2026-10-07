"""Server Monitor: reads CPU / memory / session reports written by agent/server_agent.py.

Mininet hosts share the VM's filesystem, so each agent writes <name>.json into a
shared directory. On real hardware this would be a REST or gRPC call instead.
"""
import json
import os


def _clamp(value, lo=0.0, hi=100.0):
    return max(lo, min(hi, float(value)))


class ServerMonitor:
    def __init__(self, cfg, servers, logger):
        self.dir = cfg.monitoring['agent_stats_dir']
        self.stale_after = float(cfg.monitoring['agent_stale_after'])
        self.servers = servers
        self.log = logger

    def refresh(self, now):
        for s in self.servers:
            data = self._read(s.name)
            ok = data is not None and now - float(data.get('ts', 0)) <= self.stale_after
            if ok:
                s.cpu = _clamp(data.get('cpu', 0))
                s.mem = _clamp(data.get('mem', 0))
                s.agent_sessions = max(0, int(data.get('sessions', 0)))
                s.agent_ts = float(data['ts'])
            else:
                s.agent_sessions = 0
            if ok != s.agent_ok:
                s.agent_ok = ok
                if ok:
                    self.log.info("agent on %s is reporting", s.name)
                else:
                    self.log.warning("no fresh agent report from %s - using neutral health", s.name)

    def _read(self, name):
        try:
            with open(os.path.join(self.dir, name + '.json')) as f:
                return json.load(f)
        except (OSError, ValueError):
            return None
