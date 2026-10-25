from __future__ import annotations

import time


class SystemClock:
    def now_ns(self) -> int:
        return time.monotonic_ns()

    def sleep(self, seconds: float) -> None:
        time.sleep(max(0.0, seconds))
