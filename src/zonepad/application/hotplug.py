"""Hot-plug by sysfs polling with an injected clock (spec RF12, D11)."""

from __future__ import annotations

from collections.abc import Callable, Iterator

from zonepad.domain.discovery import (
    DiscoveryPolicies,
    DiscoverySnapshot,
    HotplugChange,
    diff_snapshots,
)

from .discovery import discover_devices
from .ports import Clock, HotplugWatcher, InputDeviceScanner

DEFAULT_POLL_INTERVAL_S = 1.0
MIN_POLL_INTERVAL_S = 0.25
MAX_POLL_INTERVAL_S = 5.0


def validate_poll_interval(interval_s: float) -> float:
    if not MIN_POLL_INTERVAL_S <= interval_s <= MAX_POLL_INTERVAL_S:
        raise ValueError(
            f"poll interval must be in [{MIN_POLL_INTERVAL_S}, {MAX_POLL_INTERVAL_S}] seconds"
        )
    return interval_s


class PollingHotplugWatcher:
    """Compare consecutive discovery snapshots by ``input_token``.

    ``poll`` before any ``snapshot`` compares against an empty snapshot, so every
    present node is reported as ``added``.
    """

    def __init__(
        self,
        scanner: InputDeviceScanner,
        policies: DiscoveryPolicies,
        clock: Clock,
        interval_s: float = DEFAULT_POLL_INTERVAL_S,
    ) -> None:
        self._scanner = scanner
        self._policies = policies
        self._clock = clock
        self._interval_s = validate_poll_interval(interval_s)
        self._current = DiscoverySnapshot()

    @property
    def interval_s(self) -> float:
        return self._interval_s

    def snapshot(self) -> DiscoverySnapshot:
        self._current = discover_devices(self._scanner, self._policies)
        return self._current

    def poll(self) -> HotplugChange:
        before = self._current
        after = discover_devices(self._scanner, self._policies)
        self._current = after
        return diff_snapshots(before, after, self._clock.now_ns())


def follow(
    watcher: HotplugWatcher,
    clock: Clock,
    interval_s: float,
    should_stop: Callable[[], bool],
) -> Iterator[HotplugChange]:
    """Yield non-empty changes, sleeping ``interval_s`` through ``clock`` between polls."""
    validate_poll_interval(interval_s)
    while not should_stop():
        clock.sleep(interval_s)
        if should_stop():
            return
        change = watcher.poll()
        if not change.is_empty:
            yield change
