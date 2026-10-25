from __future__ import annotations

from collections.abc import Iterable

from zonepad.domain.input import RawFrame


def collect_frames(session: object, count: int, timeout_s: float = 0.1) -> list[RawFrame]:
    """Collect a deterministic number of samples from a DeviceSession-like object."""
    if count < 1:
        raise ValueError("count must be positive")
    frames: list[RawFrame] = []
    for _ in range(count):
        frame = session.read(timeout_s)  # type: ignore[attr-defined]
        if frame is not None:
            frames.append(frame)
    return frames


def replay_frames(frames: Iterable[RawFrame]) -> Iterable[RawFrame]:
    yield from frames
