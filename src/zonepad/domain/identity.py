"""Stable device identity derived from hardware facts (spec RF3, ADR 0006).

The identity never contains the volatile ``eventN`` node, the device name or the
sysfs path.  Raw ``uniq``/serial/``phys`` values only enter the ID through a
truncated SHA-256 (pseudonymisation, not anonymisation).
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import NewType

StableId = NewType("StableId", str)

STABLE_ID_PATTERN = re.compile(
    r"(?:usb|bt|bus[0-9a-f]{4})-[0-9a-f]{4}-[0-9a-f]{4}-"
    r"(?:[usp][0-9a-f]{10}(?:\.(?:[2-9]|[1-9][0-9]))?|n[1-9][0-9]{0,2})",
    re.ASCII,
)
STABLE_ID_BASE_PATTERN = re.compile(r"(?:usb|bt|bus[0-9a-f]{4})-[0-9a-f]{4}-[0-9a-f]{4}", re.ASCII)
MAX_STABLE_ID_LENGTH = 33
QUALIFIER_HASH_LENGTH = 10
MAX_DUPLICATE_SUFFIX = 99
MAX_OCCURRENCE = 999

_EVENT_NODE_PATTERN = re.compile(r"event([0-9]+)", re.ASCII)


class Connection(StrEnum):
    USB = "usb"
    BLUETOOTH = "bluetooth"
    UNKNOWN = "unknown"


class QualifierSource(StrEnum):
    UNIQ = "uniq"
    USB_SERIAL = "usb_serial"
    PHYS = "phys"
    OCCURRENCE = "occurrence"


_QUALIFIER_PREFIX = {
    QualifierSource.UNIQ: "u",
    QualifierSource.USB_SERIAL: "s",
    QualifierSource.PHYS: "p",
}


def parse_stable_id(text: str) -> StableId:
    """Validate ``text`` against the stable ID grammar; raise ``ValueError`` otherwise."""
    if len(text) > MAX_STABLE_ID_LENGTH or STABLE_ID_PATTERN.fullmatch(text) is None:
        raise ValueError(f"invalid stable device id: {text!r}")
    return StableId(text)


def is_stable_id(text: str) -> bool:
    return len(text) <= MAX_STABLE_ID_LENGTH and STABLE_ID_PATTERN.fullmatch(text) is not None


def is_stable_id_base(text: str) -> bool:
    return STABLE_ID_BASE_PATTERN.fullmatch(text) is not None


def stable_id_base(stable_id: StableId) -> str:
    """Return the ``<bus>-<vid>-<pid>`` prefix of a valid stable ID."""
    return stable_id.rsplit("-", 1)[0]


def event_node_number(event_node: str) -> int | None:
    """Numeric part of ``eventN`` (``event10`` -> 10); ``None`` for other names."""
    match = _EVENT_NODE_PATTERN.fullmatch(event_node)
    return int(match.group(1)) if match else None


def event_node_sort_key(event_node: str) -> tuple[int, int, str]:
    """Numeric order for ``eventN`` names (``event2`` < ``event10``)."""
    number = event_node_number(event_node)
    return (0, number, "") if number is not None else (1, 0, event_node)


@dataclass(frozen=True, slots=True)
class HardwareFacts:
    """What a device declares about itself; ``eventN`` is deliberately absent."""

    bustype: int
    vendor_id: int
    product_id: int
    device_version: int | None
    firmware: str | None
    driver: str | None
    name: str | None
    uniq: str | None
    usb_serial: str | None
    phys: str | None

    def __post_init__(self) -> None:
        for label, value in (
            ("bustype", self.bustype),
            ("vendor_id", self.vendor_id),
            ("product_id", self.product_id),
        ):
            if not 0 <= value <= 0xFFFF:
                raise ValueError(f"hardware {label} must be in [0, 0xffff]")
        if self.device_version is not None and not 0 <= self.device_version <= 0xFFFF:
            raise ValueError("hardware device_version must be in [0, 0xffff]")


@dataclass(frozen=True, slots=True)
class IdentityPolicy:
    """Identity rules as data; Linux values come from ``linux_input_policy``.

    ``port_bound_bustypes`` lists the bus types where the USB serial and ``phys``
    may qualify an identity (only USB: in Bluetooth ``phys`` is the adapter MAC).
    """

    bus_tokens: Mapping[int, str]
    bus_connections: Mapping[int, Connection]
    mac_pattern: re.Pattern[str]
    placeholder_pattern: re.Pattern[str]
    port_bound_bustypes: frozenset[int]

    def __post_init__(self) -> None:
        object.__setattr__(self, "bus_tokens", MappingProxyType(dict(self.bus_tokens)))
        object.__setattr__(self, "bus_connections", MappingProxyType(dict(self.bus_connections)))

    def bus_token(self, bustype: int) -> str:
        return self.bus_tokens.get(bustype, f"bus{bustype:04x}")

    def connection(self, bustype: int) -> Connection:
        return self.bus_connections.get(bustype, Connection.UNKNOWN)


@dataclass(frozen=True, slots=True)
class StableIdentity:
    stable_id: StableId
    facts: HardwareFacts
    connection: Connection
    qualifier_source: QualifierSource
    occurrence: int | None
    fragile: bool
    warnings: tuple[str, ...] = ()

    @property
    def base(self) -> str:
        return stable_id_base(self.stable_id)


@dataclass(frozen=True, slots=True)
class MappingKey:
    """Persistence key (D6); never contains ``eventN``, firmware or device version."""

    stable_id: StableId
    connection: Connection


@dataclass(frozen=True, slots=True)
class _Qualified:
    event_node: str
    facts: HardwareFacts
    base: str
    source: QualifierSource
    qualifier: str | None
    warnings: tuple[str, ...] = field(default=())


def derive_stable_ids(
    devices: Sequence[tuple[str, HardwareFacts]],
    policy: IdentityPolicy,
) -> Mapping[str, StableIdentity]:
    """Derive one stable identity per ``event_node``, deterministic for a snapshot.

    Duplicates depend on the whole snapshot, so every gamepad must be passed at once.
    Ties are broken by the numeric ``eventN`` order, which never enters the ID.
    """
    ordered = sorted(devices, key=lambda item: event_node_sort_key(item[0]))
    qualified = [_qualify(event_node, facts, policy) for event_node, facts in ordered]
    groups: dict[tuple[str, str | None], list[_Qualified]] = {}
    for item in qualified:
        groups.setdefault((item.base, item.qualifier), []).append(item)
    result: dict[str, StableIdentity] = {}
    for (base, qualifier), members in groups.items():
        if qualifier is None:
            result.update(_occurrence_identities(base, members, policy))
        else:
            result.update(_hashed_identities(base, qualifier, members, policy))
    return MappingProxyType(result)


def _qualify(event_node: str, facts: HardwareFacts, policy: IdentityPolicy) -> _Qualified:
    base = f"{policy.bus_token(facts.bustype)}-{facts.vendor_id:04x}-{facts.product_id:04x}"
    warnings: list[str] = []
    uniq = _canonical(facts.uniq, policy, warnings)
    if uniq is not None:
        return _hashed(event_node, facts, base, QualifierSource.UNIQ, uniq, warnings)
    if facts.bustype in policy.port_bound_bustypes:
        serial = _canonical(facts.usb_serial, policy, warnings)
        if serial is not None:
            return _hashed(event_node, facts, base, QualifierSource.USB_SERIAL, serial, warnings)
        phys = _canonical(facts.phys, policy, warnings)
        if phys is not None:
            warnings.append("identity_bound_to_port")
            return _hashed(event_node, facts, base, QualifierSource.PHYS, phys, warnings)
    warnings.append("identity_weak")
    return _Qualified(event_node, facts, base, QualifierSource.OCCURRENCE, None, tuple(warnings))


def _hashed(
    event_node: str,
    facts: HardwareFacts,
    base: str,
    source: QualifierSource,
    canonical_value: str,
    warnings: list[str],
) -> _Qualified:
    digest = hashlib.sha256(f"{source.value}\0{canonical_value}".encode()).hexdigest()
    qualifier = _QUALIFIER_PREFIX[source] + digest[:QUALIFIER_HASH_LENGTH]
    return _Qualified(event_node, facts, base, source, qualifier, tuple(warnings))


def _canonical(value: str | None, policy: IdentityPolicy, warnings: list[str]) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    if policy.mac_pattern.fullmatch(stripped):
        canonical = re.sub(r"[:-]", "", stripped).lower()
    else:
        canonical = unicodedata.normalize("NFC", stripped)
    if policy.placeholder_pattern.fullmatch(canonical):
        if "placeholder_serial" not in warnings:
            warnings.append("placeholder_serial")
        return None
    return canonical


def _occurrence_identities(
    base: str, members: list[_Qualified], policy: IdentityPolicy
) -> dict[str, StableIdentity]:
    if len(members) > MAX_OCCURRENCE:
        raise ValueError(f"too many identical devices for {base}")
    duplicate_warning = (f"duplicate_identity:{len(members)}",) if len(members) > 1 else ()
    result: dict[str, StableIdentity] = {}
    for occurrence, item in enumerate(members, start=1):
        result[item.event_node] = StableIdentity(
            stable_id=parse_stable_id(f"{base}-n{occurrence}"),
            facts=item.facts,
            connection=policy.connection(item.facts.bustype),
            qualifier_source=QualifierSource.OCCURRENCE,
            occurrence=occurrence,
            fragile=True,
            warnings=item.warnings + duplicate_warning,
        )
    return result


def _hashed_identities(
    base: str, qualifier: str, members: list[_Qualified], policy: IdentityPolicy
) -> dict[str, StableIdentity]:
    if len(members) > MAX_DUPLICATE_SUFFIX:
        raise ValueError(f"too many devices sharing qualifier {base}-{qualifier}")
    is_duplicate = len(members) > 1
    duplicate_warning = (f"duplicate_identity:{len(members)}",) if is_duplicate else ()
    result: dict[str, StableIdentity] = {}
    for rank, item in enumerate(members, start=1):
        suffix = f".{rank}" if rank > 1 else ""
        result[item.event_node] = StableIdentity(
            stable_id=parse_stable_id(f"{base}-{qualifier}{suffix}"),
            facts=item.facts,
            connection=policy.connection(item.facts.bustype),
            qualifier_source=item.source,
            occurrence=None,
            fragile=is_duplicate,
            warnings=item.warnings + duplicate_warning,
        )
    return result
