"""Maps a new flow to a service class from its protocol and destination port."""

PROTO_NUMBERS = {'tcp': 6, 'udp': 17}


def parse_port_spec(spec):
    """8554 -> (8554, 8554); "16384-32767" -> (16384, 32767)."""
    if isinstance(spec, int):
        return spec, spec
    text = str(spec).strip()
    if '-' in text:
        lo, hi = text.split('-', 1)
        lo, hi = int(lo), int(hi)
    else:
        lo = hi = int(text)
    if not (0 <= lo <= hi <= 65535):
        raise ValueError("bad port spec %r" % spec)
    return lo, hi


class ServiceClassifier:
    def __init__(self, services):
        self.rules = []     # (ip_proto, lo, hi, service)
        for name, svc in services.items():
            for proto_name, specs in (svc.get('ports') or {}).items():
                proto = PROTO_NUMBERS[proto_name.lower()]
                for spec in specs or []:
                    lo, hi = parse_port_spec(spec)
                    self.rules.append((proto, lo, hi, name))
        # Narrowest rule first, so a single port wins over a range that contains it.
        self.rules.sort(key=lambda r: r[2] - r[1])

    def classify(self, ip_proto, dst_port):
        if dst_port is not None:
            for proto, lo, hi, name in self.rules:
                if proto == ip_proto and lo <= dst_port <= hi:
                    return name
        return 'default'
