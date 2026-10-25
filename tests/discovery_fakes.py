"""Fakes for discovery ports (scanner, absinfo reader, clock, mapping store)."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType

from zonepad.application.ports import MappingRecord, StoredMappingRef
from zonepad.domain.discovery import AbsInfo, ObservedInputDevice
from zonepad.domain.errors import DeviceAccessDeniedError, DeviceNotFoundError
from zonepad.domain.identity import MappingKey


@dataclass
class FakeAbsInfoReader:
    tables: Mapping[str, Mapping[int, AbsInfo]] = field(default_factory=dict)
    denied: frozenset[str] = frozenset()
    calls: list[tuple[str, tuple[int, ...]]] = field(default_factory=list)

    def read_absinfo(self, event_node: str, codes: Sequence[int]) -> Mapping[int, AbsInfo]:
        self.calls.append((event_node, tuple(codes)))
        if event_node in self.denied:
            raise DeviceAccessDeniedError(event_node)
        if event_node not in self.tables:
            raise DeviceNotFoundError(event_node)
        table = self.tables[event_node]
        return MappingProxyType({code: table[code] for code in codes if code in table})


class ScriptedScanner:
    """Returns one scripted scan per call; the last one repeats."""

    def __init__(self, scans: Iterable[Sequence[ObservedInputDevice]]) -> None:
        self._scans = [tuple(scan) for scan in scans]
        self.calls = 0

    def scan(self) -> tuple[ObservedInputDevice, ...]:
        index = min(self.calls, len(self._scans) - 1)
        self.calls += 1
        return self._scans[index]


@dataclass
class FakeClock:
    now: int = 0
    sleeps: list[float] = field(default_factory=list)

    def now_ns(self) -> int:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += int(seconds * 1_000_000_000)


@dataclass
class InMemoryMappingStore:
    refs: dict[str, StoredMappingRef] = field(default_factory=dict)
    saved: list[MappingRecord] = field(default_factory=list)

    def find(self, key: MappingKey) -> StoredMappingRef | None:
        return self.refs.get(key.stable_id)

    def save(self, record: MappingRecord, *, overwrite: bool) -> StoredMappingRef:
        raise NotImplementedError

    def entries(self) -> tuple[StoredMappingRef, ...]:
        return tuple(self.refs[key] for key in sorted(self.refs))
