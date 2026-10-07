"""Runtime state the controller keeps for every backend server."""
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, List, Optional, Tuple


@dataclass
class Server:
    index: int                  # 1-based; also the high 32 bits of this server's flow cookies
    name: str
    ip: str
    mac: str
    switch_port: int
    capacity_mbps: float
    services: List[str]

    # --- filled by the network monitor ---
    up: bool = False
    rtt_ms: Optional[float] = None
    consecutive_misses: int = 0
    probe_window: Deque[bool] = field(default_factory=lambda: deque(maxlen=20))
    used_mbps: float = 0.0
    tx_bytes: int = 0           # switch -> server, cumulative
    rx_bytes: int = 0           # server -> switch, cumulative
    last_port_sample: Optional[Tuple[float, int, int]] = None
    pending: List[Tuple[float, float]] = field(default_factory=list)   # (assigned_at, mbps)

    # --- filled by the server monitor (agent reports) ---
    agent_ok: bool = False
    agent_ts: float = 0.0
    cpu: float = 0.0
    mem: float = 0.0
    agent_sessions: int = 0

    # --- controller bookkeeping ---
    active_flows: int = 0
    assigned_total: int = 0

    def loss_rate(self) -> float:
        if not self.probe_window:
            return 0.0
        return 1.0 - sum(self.probe_window) / len(self.probe_window)

    def pending_mbps(self, now: float, window: float) -> float:
        """Bandwidth reserved by flows assigned too recently to show up in port stats."""
        self.pending = [(t, m) for t, m in self.pending if now - t < window]
        return sum(m for _, m in self.pending)

    def available_mbps(self, now: float, window: float) -> float:
        return max(0.0, self.capacity_mbps - self.used_mbps - self.pending_mbps(now, window))

    def sessions(self) -> int:
        # The agent sees TCP connections; the controller sees every flow it installed.
        return max(self.agent_sessions, self.active_flows)

    def record_assignment(self, now: float, expected_mbps: float) -> None:
        self.pending.append((now, expected_mbps))
        self.active_flows += 1
        self.assigned_total += 1
