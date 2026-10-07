"""Network Monitor: bandwidth (OpenFlow port stats), latency and packet loss (ICMP probes).

Pure Python - the Ryu app turns OpenFlow messages and packets into the plain
values passed in here, which keeps this logic unit-testable.
"""
from collections import deque


def ewma(old, new, alpha):
    return new if old is None else alpha * new + (1 - alpha) * old


class NetworkMonitor:
    PROBE_ID = 0x5D4E   # ICMP identifier used by our latency probes

    def __init__(self, cfg, servers, logger):
        mon = cfg.monitoring
        self.timeout = float(mon['probe_timeout'])
        self.down_after = int(mon['down_after_missed'])
        self.alpha = float(mon['ewma_alpha'])
        self.servers = servers
        self.by_port = {s.switch_port: s for s in servers}
        self.log = logger
        for s in servers:
            s.probe_window = deque(maxlen=int(mon['loss_window']))
        self._seq = 0
        self._outstanding = {}      # seq -> (server, sent_at)

    # ---------- latency / loss probes ----------
    def next_probe(self, server, now):
        """Register a probe to `server` and return its ICMP sequence number."""
        self._seq = (self._seq + 1) & 0xFFFF
        self._outstanding[self._seq] = (server, now)
        return self._seq

    def probe_reply(self, src_ip, ident, seq, now):
        """Handle an ICMP echo reply. Returns True if it was one of our probes."""
        if ident != self.PROBE_ID:
            return False
        entry = self._outstanding.pop(seq, None)
        if entry is None or entry[0].ip != src_ip:
            return True                 # late or unexpected reply - already counted as lost
        server, sent_at = entry
        server.rtt_ms = ewma(server.rtt_ms, (now - sent_at) * 1000.0, self.alpha)
        server.probe_window.append(True)
        server.consecutive_misses = 0
        return True

    def expire_probes(self, now):
        for seq, (server, sent_at) in list(self._outstanding.items()):
            if now - sent_at > self.timeout:
                del self._outstanding[seq]
                server.probe_window.append(False)
                server.consecutive_misses += 1

    def update_availability(self):
        """Apply up/down rules and return the servers whose state changed."""
        changed = []
        for s in self.servers:
            up_now = s.rtt_ms is not None and s.consecutive_misses < self.down_after
            if up_now != s.up:
                s.up = up_now
                if not up_now:
                    s.rtt_ms = None     # forget stale latency; the next reply brings it back up
                changed.append(s)
        return changed

    # ---------- bandwidth from port counters ----------
    def port_stats(self, samples, now):
        """samples: iterable of (port_no, tx_bytes, rx_bytes) as seen by the switch."""
        for port_no, tx, rx in samples:
            s = self.by_port.get(port_no)
            if s is None:
                continue
            if s.last_port_sample is not None:
                t0, tx0, rx0 = s.last_port_sample
                dt = now - t0
                if dt > 0:
                    # Full duplex: the busier direction is what limits the link.
                    mbps = max(tx - tx0, rx - rx0, 0) * 8 / dt / 1e6
                    s.used_mbps = ewma(s.used_mbps, mbps, self.alpha)
            s.last_port_sample = (now, tx, rx)
            s.tx_bytes, s.rx_bytes = tx, rx
