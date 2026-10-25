"""Device family catalog as pure data plus the matching rules of spec RF5.

Matching tiers, first hit wins and every tier requires the same driver and bus:

1. exact ``vid_pid`` listed by the entry;
2. driver-level entries: ``vid_pid`` is ``null`` or the entry declares a
   ``usb_interface_protocol`` rule (xpad deduces the pad type from the USB
   interface protocol when the PID is not in its table, ``xpad.c:2103-2112``);
3. no entry: generic heuristic (``CatalogMatch.entry is None``).

An entry whose ``required_abs`` is not in the ABS bitmap is discarded with the
warning ``catalog_capability_mismatch`` and the search continues.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal

from .discovery import ObservedInputDevice

CatalogSource = Literal["user", "builtin", "generic"]
STICK_CHANNELS = ("lx", "ly", "rx", "ry")
TRIGGER_CHANNELS = ("lt", "rt")
MAPPING_CHANNELS = STICK_CHANNELS + TRIGGER_CHANNELS


@dataclass(frozen=True, slots=True)
class InterfaceProtocolRule:
    mode: Literal["in", "not_in"]
    values: frozenset[str]

    def matches(self, protocol: str | None) -> bool:
        """An unknown interface protocol never matches (conservative: generic path)."""
        if protocol is None:
            return False
        normalized = protocol.strip().lower()
        return (normalized in self.values) == (self.mode == "in")


@dataclass(frozen=True, slots=True)
class CatalogMatchRule:
    driver: str
    bustypes: frozenset[int]
    vid_pids: frozenset[tuple[int, int]] | None
    usb_interface_protocol: InterfaceProtocolRule | None

    @property
    def is_driver_level(self) -> bool:
        return self.vid_pids is None or self.usb_interface_protocol is not None


@dataclass(frozen=True, slots=True)
class KnownRange:
    minimum: int
    maximum: int
    fuzz: int
    flat: int

    def __post_init__(self) -> None:
        if not self.minimum < self.maximum:
            raise ValueError("known range requires minimum < maximum")
        if self.fuzz < 0 or self.flat < 0:
            raise ValueError("known range fuzz and flat must be non-negative")


@dataclass(frozen=True, slots=True)
class CatalogEvidence:
    kind: str
    ref: str
    commit: str | None


@dataclass(frozen=True, slots=True)
class CatalogEntry:
    entry_id: str
    display_name: str
    match: CatalogMatchRule
    required_abs: frozenset[int]
    channels: Mapping[str, int]
    known_ranges: Mapping[int, KnownRange]
    center_override: Mapping[str, int]
    buttons: Mapping[int, str]
    layout: str
    unsupported_reason: str | None
    quirks: tuple[str, ...]
    evidence: tuple[CatalogEvidence, ...]
    verified_on_hardware: bool

    def __post_init__(self) -> None:
        unknown = set(self.channels) - set(MAPPING_CHANNELS)
        if unknown:
            raise ValueError(f"catalog entry {self.entry_id} has unknown channels")
        if self.unsupported_reason is None and set(self.channels) != set(MAPPING_CHANNELS):
            raise ValueError(f"catalog entry {self.entry_id} must define all mapping channels")
        if len(set(self.channels.values())) != len(self.channels):
            raise ValueError(f"catalog entry {self.entry_id} repeats channel codes")
        if not set(self.channels.values()) <= self.required_abs:
            raise ValueError(f"catalog entry {self.entry_id} maps codes outside required_abs")
        if set(self.center_override) - set(STICK_CHANNELS):
            raise ValueError(f"catalog entry {self.entry_id} overrides a non-stick center")
        for name in ("channels", "known_ranges", "center_override", "buttons"):
            object.__setattr__(self, name, MappingProxyType(dict(getattr(self, name))))


@dataclass(frozen=True, slots=True)
class Catalog:
    catalog_version: int
    source: Literal["user", "builtin"]
    entries: tuple[CatalogEntry, ...]

    def __post_init__(self) -> None:
        ids = [entry.entry_id for entry in self.entries]
        if len(set(ids)) != len(ids):
            raise ValueError("catalog entry ids must be unique")
        seen: set[tuple[str, int, int]] = set()
        for entry in self.entries:
            for vid_pid in entry.match.vid_pids or ():
                key = (entry.match.driver, *vid_pid)
                if key in seen:
                    raise ValueError(f"catalog lists {vid_pid} twice for one driver")
                seen.add(key)


@dataclass(frozen=True, slots=True)
class CatalogMatch:
    entry: CatalogEntry | None
    catalog_version: int
    source: CatalogSource
    warnings: tuple[str, ...] = ()


def match_catalog(
    catalogs: Sequence[Catalog], device: ObservedInputDevice, *, generic_version: int
) -> CatalogMatch:
    """Search ``catalogs`` in precedence order (user before builtin)."""
    warnings: list[str] = []
    for catalog in catalogs:
        entry = _search(catalog, device, warnings)
        if entry is not None:
            return CatalogMatch(entry, catalog.catalog_version, catalog.source, tuple(warnings))
    return CatalogMatch(None, generic_version, "generic", tuple(warnings))


def _search(
    catalog: Catalog, device: ObservedInputDevice, warnings: list[str]
) -> CatalogEntry | None:
    if device.driver is None or device.bustype is None:
        return None
    candidates = [
        entry
        for entry in catalog.entries
        if entry.match.driver == device.driver and device.bustype in entry.match.bustypes
    ]
    vid_pid = (device.vendor_id, device.product_id)
    exact = [e for e in candidates if e.match.vid_pids is not None and vid_pid in e.match.vid_pids]
    driver_level = [
        e
        for e in candidates
        if e.match.is_driver_level
        and (
            e.match.usb_interface_protocol is None
            or e.match.usb_interface_protocol.matches(device.usb_interface_protocol)
        )
    ]
    axes = device.capabilities.axis_codes if device.capabilities else frozenset()
    for entry in exact + driver_level:
        if entry.required_abs <= axes:
            return entry
        if "catalog_capability_mismatch" not in warnings:
            warnings.append("catalog_capability_mismatch")
    return None
