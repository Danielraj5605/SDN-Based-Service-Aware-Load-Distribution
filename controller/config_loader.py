"""Loads and validates config.yaml for the controller."""
import copy

import yaml

from models import Server

SERVICE_AWARE = 'service_aware'
ROUND_ROBIN = 'round_robin'
WEIGHT_KEYS = ('health', 'bandwidth', 'latency', 'loss', 'match')

_MODE_ALIASES = {
    'service_aware': SERVICE_AWARE, 'service-aware': SERVICE_AWARE, 'sa': SERVICE_AWARE,
    'round_robin': ROUND_ROBIN, 'round-robin': ROUND_ROBIN, 'rr': ROUND_ROBIN,
}

_DEFAULTS = {
    'monitoring': {
        'port_stats_interval': 2, 'probe_interval': 1, 'probe_timeout': 1.0,
        'loss_window': 20, 'down_after_missed': 3, 'ewma_alpha': 0.5,
        'agent_stats_dir': '/tmp/sdn_lb/stats', 'agent_stale_after': 5,
        'metrics_log_interval': 2,
    },
    'flows': {'priority': 100, 'idle_timeout': 10, 'hard_timeout': 0},
    'scoring': {
        'max_latency_ms': 100, 'bandwidth_ref_mbps': 0, 'service_mismatch': 0.3,
        'unknown_health': 0.5, 'max_sessions': 20,
        'health_mix': {'cpu': 0.5, 'mem': 0.2, 'sessions': 0.3},
        'pending_window': 4,
    },
    'rebalance': {
        'enabled': False, 'interval': 5, 'min_gain': 0.15, 'hold_time': 10,
        'services': ['voip', 'video'],
    },
}


class ConfigError(ValueError):
    pass


def normalise_mode(mode):
    key = str(mode).strip().lower()
    if key not in _MODE_ALIASES:
        raise ConfigError("unknown mode %r (use service_aware or round_robin)" % mode)
    return _MODE_ALIASES[key]


def validate_weights(weights, where):
    unknown = set(weights) - set(WEIGHT_KEYS)
    if unknown:
        raise ConfigError("%s: unknown weight(s) %s; allowed: %s"
                          % (where, sorted(unknown), ', '.join(WEIGHT_KEYS)))
    for key, value in weights.items():
        if not isinstance(value, (int, float)) or value < 0:
            raise ConfigError("%s: weight %s must be a number >= 0" % (where, key))
    if sum(weights.get(k, 0) for k in WEIGHT_KEYS) <= 0:
        raise ConfigError("%s: weights must not all be zero" % where)


def _merged(raw, section):
    out = copy.deepcopy(_DEFAULTS[section])
    out.update(raw.get(section) or {})
    return out


class Config:
    def __init__(self, raw):
        self.raw = raw
        self.mode = normalise_mode(raw.get('mode', SERVICE_AWARE))
        self.vip_ip = raw['vip']['ip']
        self.vip_mac = str(raw['vip']['mac']).lower()
        self.monitoring = _merged(raw, 'monitoring')
        self.flows = _merged(raw, 'flows')
        self.scoring = _merged(raw, 'scoring')
        self.rebalance = _merged(raw, 'rebalance')
        self.dscp_map = ((raw.get('classification') or {}).get('dscp')) or {}

        self.services = raw.get('services') or {}
        if 'default' not in self.services:
            raise ConfigError("services: a 'default' service class is required")
        for name, svc in self.services.items():
            svc.setdefault('ports', {})
            svc.setdefault('expected_mbps', 1)
            weights = svc.setdefault('weights', {})
            validate_weights(weights, 'services.%s.weights' % name)
            for key in WEIGHT_KEYS:
                weights.setdefault(key, 0.0)

        for code, svc in self.dscp_map.items():
            if not 0 < int(code) < 64 or svc not in self.services:
                raise ConfigError("classification.dscp: bad entry %r: %r" % (code, svc))
        for svc in self.rebalance['services']:
            if svc not in self.services:
                raise ConfigError("rebalance.services: unknown service %r" % svc)

        self.servers = []
        seen_ports, seen_ips = set(), set()
        for i, srv in enumerate(raw.get('servers') or [], start=1):
            port, ip = int(srv['switch_port']), srv['ip']
            if port in seen_ports or ip in seen_ips:
                raise ConfigError("servers: duplicate switch_port or ip for %s" % srv['name'])
            seen_ports.add(port)
            seen_ips.add(ip)
            services = list(srv.get('services') or ['default'])
            for svc in services:
                if svc not in self.services:
                    raise ConfigError("servers.%s: unknown service %r" % (srv['name'], svc))
            self.servers.append(Server(
                index=i, name=srv['name'], ip=ip, mac=str(srv['mac']).lower(),
                switch_port=port,
                capacity_mbps=float((srv.get('link') or {}).get('bw', 1000)),
                services=services,
            ))
        if not self.servers:
            raise ConfigError("servers: at least one server is required")

    def expected_mbps(self, service):
        return float(self.services.get(service, self.services['default'])['expected_mbps'])


def load_config(path):
    with open(path) as f:
        return Config(yaml.safe_load(f))
