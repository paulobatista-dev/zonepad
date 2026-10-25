"""Discovery use cases: snapshot of input devices and ``--device`` resolution."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from zonepad.domain.discovery import (
    DiscoveredDevice,
    DiscoveryPolicies,
    DiscoverySnapshot,
    build_snapshot,
)
from zonepad.domain.errors import AmbiguousDeviceError, DeviceNotFoundError
from zonepad.domain.identity import StableId, StableIdentity, is_stable_id, is_stable_id_base

from .ports import InputDeviceScanner

ReferenceKind = Literal["stable_id", "event_node", "base"]
_EVENT_NODE = re.compile(r"event[0-9]+", re.ASCII)


@dataclass(frozen=True, slots=True)
class ResolvedDevice:
    device: DiscoveredDevice
    identity: StableIdentity
    reference_kind: ReferenceKind

    @property
    def event_node(self) -> str:
        return self.device.event_node


def discover_devices(scanner: InputDeviceScanner, policies: DiscoveryPolicies) -> DiscoverySnapshot:
    """Scan sysfs once and classify every node; never opens ``/dev/input``."""
    return build_snapshot(scanner.scan(), policies)


def resolve_device_reference(reference: str, snapshot: DiscoverySnapshot) -> ResolvedDevice:
    """Resolve a stable ID, an ``eventN`` or a unique ``<bus>-<vid>-<pid>`` base.

    Raises ``DeviceNotFoundError`` (exit 3) or ``AmbiguousDeviceError`` (exit 2).
    Only selectable gamepads resolve; virtual and auxiliary nodes never do.
    """
    if is_stable_id(reference):
        for device in snapshot.gamepads:
            if device.stable_id == reference:
                return _resolved(device, "stable_id")
        raise DeviceNotFoundError(f"device {reference} not found")
    if _EVENT_NODE.fullmatch(reference):
        node = snapshot.by_event_node(reference)
        if node is None:
            raise DeviceNotFoundError(f"device {reference} not found")
        if not node.is_selectable:
            reasons = ", ".join(node.verdict.reasons) or node.verdict.device_class.value
            raise DeviceNotFoundError(f"device {reference} is not a selectable gamepad: {reasons}")
        return _resolved(node, "event_node")
    if is_stable_id_base(reference):
        matches = [d for d in snapshot.gamepads if d.identity and d.identity.base == reference]
        if not matches:
            raise DeviceNotFoundError(f"device {reference} not found")
        if len(matches) > 1:
            raise AmbiguousDeviceError(reference, tuple(str(d.stable_id) for d in matches))
        return _resolved(matches[0], "base")
    raise DeviceNotFoundError(f"device {reference!r} not found")


def fragile_group(snapshot: DiscoverySnapshot, identity: StableIdentity) -> tuple[StableId, ...]:
    """IDs of gamepads sharing the base of a fragile identity (shown before confirming)."""
    if not identity.fragile:
        return ()
    return tuple(
        device.identity.stable_id
        for device in snapshot.gamepads
        if device.identity is not None
        and device.identity.fragile
        and device.identity.base == identity.base
        and device.identity.qualifier_source is identity.qualifier_source
    )


def _resolved(device: DiscoveredDevice, kind: ReferenceKind) -> ResolvedDevice:
    if device.identity is None:  # guarded by DiscoverySnapshot.gamepads
        raise DeviceNotFoundError(f"device {device.event_node} has no stable identity")
    return ResolvedDevice(device, device.identity, kind)
