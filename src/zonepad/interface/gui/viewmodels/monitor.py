"""Pure monitor snapshots and frame-rate calculation."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from zonepad.domain.input import NormalizedFrame

RATE_WINDOW_NS = 1_000_000_000


@dataclass(frozen=True, slots=True)
class MonitorSnapshot:
    frame: NormalizedFrame
    observed_hz: float | None


class FrameRateWindow:
    """Calculate observed frames per second from distinct monotonic timestamps."""

    def __init__(self, window_ns: int = RATE_WINDOW_NS) -> None:
        if window_ns <= 0:
            raise ValueError("window_ns must be positive")
        self._window_ns = window_ns
        self._timestamps: deque[int] = deque()

    def push(self, timestamp_ns: int) -> float | None:
        if self._timestamps and timestamp_ns < self._timestamps[-1]:
            raise ValueError("frame timestamps must be monotonic")
        if not self._timestamps or timestamp_ns != self._timestamps[-1]:
            self._timestamps.append(timestamp_ns)
        cutoff = timestamp_ns - self._window_ns
        while len(self._timestamps) > 1 and self._timestamps[0] < cutoff:
            self._timestamps.popleft()
        if len(self._timestamps) < 2:
            return None
        elapsed = self._timestamps[-1] - self._timestamps[0]
        return None if elapsed <= 0 else (len(self._timestamps) - 1) * 1_000_000_000 / elapsed
