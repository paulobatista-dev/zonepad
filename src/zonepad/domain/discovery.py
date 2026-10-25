"""Observed input devices, gamepad classification and discovery snapshots.

Linux codes reach this module only as data (``GamepadFilterPolicy``); the rules
follow spec RF2 and are evaluated in order, the first match winning.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from .identity import (
    HardwareFacts,
    IdentityPolicy,
    StableId,
    StableIdentity,
    derive_stable_ids,
    event_node_sort_key,
)

MAX_ABS_CODE = 0x3F
MAX_KEY_CODE = 0x2FF


class DeviceClass(StrEnum):
    GAMEPAD = "gamepad"
    KEYBOARD = "keyboard"
    MOUSE = "mouse"
    TOUCHPAD = "touchpad"
    MOTION_SENSOR = "motion_sensor"
    VIRTUAL = "virtual"
    UNKNOWN = "unknown"


class GamepadKind(StrEnum):
    GAMEPAD = "gamepad"
    JOYSTICK_HID = "joystick_hid"


ABSINFO_OPTIONAL_FIELDS = ("fuzz", "flat", "resolution")


@dataclass(frozen=True, slots=True)
class AbsInfo:
    """Kernel ``input_absinfo`` in device counts.

    ``fuzz``, ``flat`` and ``resolution`` are ``None`` when the kernel reported a
    negative value, which is discarded (warning ``absinfo_negative_field:<field>``).
    ``value_at_probe`` is diagnostic only and never becomes a center or a rest.
    """

    minimum: int
    maximum: int
    fuzz: int | None
    flat: int | None
    resolution: int | None
    value_at_probe: int | None = None

    def __post_init__(self) -> None:
        if not self.minimum < self.maximum:
            raise ValueError("absinfo requires minimum < maximum")
        for name in ABSINFO_OPTIONAL_FIELDS:
            value = getattr(self, name)
            if value is not None and value < 0:
                raise ValueError(f"absinfo {name} must be non-negative or None")

    @property
    def discarded_fields(self) -> tuple[str, ...]:
        return tuple(name for name in ABSINFO_OPTIONAL_FIELDS if getattr(self, name) is None)


def absinfo_from_kernel(
    value: int, minimum: int, maximum: int, fuzz: int, flat: int, resolution: int
) -> AbsInfo:
    """Build ``AbsInfo`` from the ``struct input_absinfo`` field order.

    Raises ``ValueError`` when ``minimum >= maximum`` (degenerate axis).
    """
    return AbsInfo(
        minimum=minimum,
        maximum=maximum,
        fuzz=fuzz if fuzz >= 0 else None,
        flat=flat if flat >= 0 else None,
        resolution=resolution if resolution >= 0 else None,
        value_at_probe=value,
    )


@dataclass(frozen=True, slots=True)
class AxisCapability:
    code: int
    absinfo: AbsInfo | None = None

    def __post_init__(self) -> None:
        if not 0 <= self.code <= MAX_ABS_CODE:
            raise ValueError(f"ABS code out of range: {self.code}")


@dataclass(frozen=True, slots=True)
class ButtonCapability:
    code: int

    def __post_init__(self) -> None:
        if not 0 <= self.code <= MAX_KEY_CODE:
            raise ValueError(f"KEY/BTN code out of range: {self.code}")


@dataclass(frozen=True, slots=True)
class DeviceCapabilities:
    event_types: frozenset[int]
    axes: tuple[AxisCapability, ...]
    buttons: tuple[ButtonCapability, ...]
    relative_axes: frozenset[int]
    properties: frozenset[int]

    def __post_init__(self) -> None:
        axis_codes = [axis.code for axis in self.axes]
        button_codes = [button.code for button in self.buttons]
        if len(set(axis_codes)) != len(axis_codes):
            raise ValueError("duplicate ABS codes in capabilities")
        if len(set(button_codes)) != len(button_codes):
            raise ValueError("duplicate KEY/BTN codes in capabilities")
        object.__setattr__(self, "axes", tuple(sorted(self.axes, key=lambda axis: axis.code)))
        object.__setattr__(
            self, "buttons", tuple(sorted(self.buttons, key=lambda button: button.code))
        )

    @classmethod
    def from_codes(
        cls,
        *,
        event_types: frozenset[int],
        axes: frozenset[int],
        buttons: frozenset[int],
        relative_axes: frozenset[int] = frozenset(),
        properties: frozenset[int] = frozenset(),
    ) -> DeviceCapabilities:
        return cls(
            event_types=event_types,
            axes=tuple(AxisCapability(code) for code in axes),
            buttons=tuple(ButtonCapability(code) for code in buttons),
            relative_axes=relative_axes,
            properties=properties,
        )

    @property
    def axis_codes(self) -> frozenset[int]:
        return frozenset(axis.code for axis in self.axes)

    @property
    def button_codes(self) -> frozenset[int]:
        return frozenset(button.code for button in self.buttons)

    def axis(self, code: int) -> AxisCapability | None:
        return next((axis for axis in self.axes if axis.code == code), None)

    def with_absinfo(self, absinfo: Mapping[int, AbsInfo]) -> DeviceCapabilities:
        """Attach absinfo to present axes; codes absent from the bitmap are ignored."""
        return DeviceCapabilities(
            event_types=self.event_types,
            axes=tuple(
                AxisCapability(axis.code, absinfo.get(axis.code, axis.absinfo))
                for axis in self.axes
            ),
            buttons=self.buttons,
            relative_axes=self.relative_axes,
            properties=self.properties,
        )


class ReadIssueKind(StrEnum):
    BROKEN_DEVICE_LINK = "broken_device_link"
    PERMISSION_DENIED = "permission_denied"
    UNREADABLE_ATTRIBUTE = "unreadable_attribute"
    MALFORMED_BITMAP = "malformed_bitmap"
    OUTSIDE_SYSFS_ROOT = "outside_sysfs_root"
    INVALID_UTF8 = "invalid_utf8"
    USB_PRODUCT_MISMATCH = "usb_product_mismatch"


_NON_FATAL_ISSUES = frozenset({ReadIssueKind.INVALID_UTF8, ReadIssueKind.USB_PRODUCT_MISMATCH})


@dataclass(frozen=True, slots=True)
class ReadIssue:
    """A sysfs read problem. Fatal issues make the device ``unknown``."""

    kind: ReadIssueKind
    attribute: str | None = None

    @property
    def is_fatal(self) -> bool:
        return self.kind not in _NON_FATAL_ISSUES

    @property
    def reason(self) -> str:
        """Stable ASCII reason, ``<category>[:<detail>]``."""
        if self.attribute and self.kind in (
            ReadIssueKind.UNREADABLE_ATTRIBUTE,
            ReadIssueKind.MALFORMED_BITMAP,
            ReadIssueKind.INVALID_UTF8,
        ):
            return f"{self.kind.value}:{self.attribute}"
        return self.kind.value


@dataclass(frozen=True, slots=True)
class ObservedInputDevice:
    """Facts read from one ``eventN`` entry; ``eventN`` is volatile, never a key."""

    event_node: str
    input_token: str | None
    sysfs_path: str | None
    name: str | None
    bustype: int | None
    vendor_id: int | None
    product_id: int | None
    version: int | None
    uniq: str | None
    phys: str | None
    usb_serial: str | None
    driver: str | None
    firmware: str | None
    usb_interface_protocol: str | None
    is_virtual_path: bool
    capabilities: DeviceCapabilities | None
    issues: tuple[ReadIssue, ...] = ()

    @property
    def fatal_issues(self) -> tuple[ReadIssue, ...]:
        return tuple(issue for issue in self.issues if issue.is_fatal)

    def hardware_facts(self) -> HardwareFacts | None:
        if self.bustype is None or self.vendor_id is None or self.product_id is None:
            return None
        return HardwareFacts(
            bustype=self.bustype,
            vendor_id=self.vendor_id,
            product_id=self.product_id,
            device_version=self.version,
            firmware=self.firmware,
            driver=self.driver,
            name=self.name,
            uniq=self.uniq,
            usb_serial=self.usb_serial,
            phys=self.phys,
        )


@dataclass(frozen=True, slots=True)
class GamepadFilterPolicy:
    """RF2 criteria as data; values come from ``infrastructure.linux_input_policy``."""

    ev_key: int
    ev_rel: int
    ev_abs: int
    abs_x: int
    abs_y: int
    abs_z: int
    abs_mt_position_x: int
    abs_mt_position_y: int
    rel_x: int
    rel_y: int
    btn_south: int
    btn_tool_finger: int
    btn_tool_pen: int
    joystick_buttons: frozenset[int]
    mouse_buttons: frozenset[int]
    mouse_rule_buttons: frozenset[int]
    keyboard_block: frozenset[int]
    key_a: int
    key_space: int
    prop_pointer: int
    prop_direct: int
    prop_accelerometer: int
    virtual_bustype: int
    zonapad_virtual_name: str
    zonapad_virtual_ids: tuple[int, int]
    steam_vendor_id: int
    steam_name_marker: str


@dataclass(frozen=True, slots=True)
class Verdict:
    device_class: DeviceClass
    gamepad_kind: GamepadKind | None
    reasons: tuple[str, ...]
    warnings: tuple[str, ...] = ()

    @property
    def is_gamepad(self) -> bool:
        return self.device_class is DeviceClass.GAMEPAD


def classify(device: ObservedInputDevice, policy: GamepadFilterPolicy) -> Verdict:
    """Classify one observed node following the ordered rules of spec RF2."""
    warnings = tuple(issue.reason for issue in device.issues if not issue.is_fatal)
    fatal = device.fatal_issues
    if fatal:
        return Verdict(DeviceClass.UNKNOWN, None, tuple(issue.reason for issue in fatal), warnings)
    caps = device.capabilities
    if caps is None or device.hardware_facts() is None:
        return Verdict(DeviceClass.UNKNOWN, None, ("unreadable_attribute:id",), warnings)
    if device.is_virtual_path or device.bustype == policy.virtual_bustype:
        return Verdict(DeviceClass.VIRTUAL, None, (_virtual_reason(device, policy),), warnings)
    verdict = _classify_capabilities(caps, policy)
    return Verdict(
        verdict.device_class, verdict.gamepad_kind, verdict.reasons, verdict.warnings + warnings
    )


def _virtual_reason(device: ObservedInputDevice, policy: GamepadFilterPolicy) -> str:
    ids = (device.vendor_id, device.product_id)
    if device.name == policy.zonapad_virtual_name and ids == policy.zonapad_virtual_ids:
        return "virtual:zonapad"
    if device.vendor_id == policy.steam_vendor_id or policy.steam_name_marker in (
        device.name or ""
    ):
        return "virtual:steam_input"
    return "virtual:uinput" if device.is_virtual_path else "virtual:bus_virtual"


def _classify_capabilities(caps: DeviceCapabilities, policy: GamepadFilterPolicy) -> Verdict:
    axes = caps.axis_codes
    buttons = caps.button_codes
    has_xy = policy.abs_x in axes and policy.abs_y in axes
    has_key_events = policy.ev_key in caps.event_types
    has_abs_events = policy.ev_abs in caps.event_types
    has_rel_xy = policy.rel_x in caps.relative_axes and policy.rel_y in caps.relative_axes
    has_keyboard_block = has_key_events and policy.keyboard_block <= buttons

    if policy.prop_accelerometer in caps.properties or (
        not has_key_events and has_xy and policy.abs_z in axes
    ):
        return Verdict(DeviceClass.MOTION_SENSOR, None, ("not_a_gamepad:motion_sensor",))

    is_pointer = (
        (policy.abs_mt_position_x in axes and policy.abs_mt_position_y in axes)
        or policy.prop_pointer in caps.properties
        or (policy.btn_tool_finger in buttons and policy.prop_direct not in caps.properties)
    )
    if is_pointer:
        if policy.prop_direct in caps.properties or policy.btn_tool_pen in buttons:
            return Verdict(DeviceClass.UNKNOWN, None, ("not_a_gamepad:touchscreen_or_tablet",))
        return Verdict(DeviceClass.TOUCHPAD, None, ("not_a_gamepad:touchpad",))

    gamepad_kind: GamepadKind | None = None
    if has_abs_events and has_xy:
        if has_key_events and policy.btn_south in buttons:
            gamepad_kind = GamepadKind.GAMEPAD
        elif buttons & policy.joystick_buttons and not buttons & policy.mouse_buttons:
            gamepad_kind = GamepadKind.JOYSTICK_HID
    if gamepad_kind is not None:
        if has_rel_xy:
            return Verdict(DeviceClass.UNKNOWN, None, ("ambiguous:gamepad_and_mouse",))
        if has_keyboard_block:
            return Verdict(DeviceClass.UNKNOWN, None, ("ambiguous:gamepad_and_keyboard",))
        warnings = (
            ("face_buttons_not_positional",) if gamepad_kind is GamepadKind.JOYSTICK_HID else ()
        )
        return Verdict(DeviceClass.GAMEPAD, gamepad_kind, (), warnings)

    if has_keyboard_block or (
        policy.key_a in buttons and policy.key_space in buttons and not has_xy
    ):
        return Verdict(DeviceClass.KEYBOARD, None, ("not_a_gamepad:keyboard",))
    if has_rel_xy or (buttons & policy.mouse_rule_buttons and not has_xy):
        return Verdict(DeviceClass.MOUSE, None, ("not_a_gamepad:mouse",))
    if not has_xy:
        return Verdict(DeviceClass.UNKNOWN, None, ("not_a_gamepad:no_abs_xy",))
    if policy.btn_south not in buttons and not buttons & policy.joystick_buttons:
        return Verdict(DeviceClass.UNKNOWN, None, ("not_a_gamepad:no_gamepad_buttons",))
    return Verdict(DeviceClass.UNKNOWN, None, ("not_a_gamepad:other",))


@dataclass(frozen=True, slots=True)
class DiscoveredDevice:
    observed: ObservedInputDevice
    verdict: Verdict
    identity: StableIdentity | None = None

    @property
    def event_node(self) -> str:
        return self.observed.event_node

    @property
    def stable_id(self) -> StableId | None:
        return self.identity.stable_id if self.identity else None

    @property
    def is_selectable(self) -> bool:
        """Only identified gamepads can be chosen; virtual devices never are."""
        return self.verdict.is_gamepad and self.identity is not None

    @property
    def tracking_key(self) -> str:
        """``inputM`` never repeats within a boot; ``eventN`` can be reused."""
        return self.observed.input_token or f"node:{self.observed.event_node}"


@dataclass(frozen=True, slots=True)
class DiscoverySnapshot:
    """Ordered devices: gamepads by stable ID, then the rest by (ID, node number)."""

    devices: tuple[DiscoveredDevice, ...] = field(default=())

    @property
    def gamepads(self) -> tuple[DiscoveredDevice, ...]:
        return tuple(device for device in self.devices if device.is_selectable)

    def by_event_node(self, event_node: str) -> DiscoveredDevice | None:
        return next((d for d in self.devices if d.event_node == event_node), None)


@dataclass(frozen=True, slots=True)
class DiscoveryPolicies:
    filter_policy: GamepadFilterPolicy
    identity_policy: IdentityPolicy


def build_snapshot(
    observed: Sequence[ObservedInputDevice], policies: DiscoveryPolicies
) -> DiscoverySnapshot:
    """Classify every node and derive identities for the gamepads of the snapshot."""
    verdicts = [(device, classify(device, policies.filter_policy)) for device in observed]
    gamepad_facts: list[tuple[str, HardwareFacts]] = []
    for device, verdict in verdicts:
        facts = device.hardware_facts()
        if verdict.is_gamepad and facts is not None:
            gamepad_facts.append((device.event_node, facts))
    identities = derive_stable_ids(gamepad_facts, policies.identity_policy)
    discovered = [
        DiscoveredDevice(device, verdict, identities.get(device.event_node))
        for device, verdict in verdicts
    ]
    return DiscoverySnapshot(tuple(sorted(discovered, key=_snapshot_order)))


def _snapshot_order(device: DiscoveredDevice) -> tuple[int, str, tuple[int, int, str]]:
    group = 0 if device.is_selectable else 1
    return (group, device.stable_id or "", event_node_sort_key(device.event_node))


@dataclass(frozen=True, slots=True)
class HotplugChange:
    added: tuple[DiscoveredDevice, ...]
    removed: tuple[DiscoveredDevice, ...]
    renamed: tuple[tuple[StableId, StableId], ...]
    observed_at_ns: int

    @property
    def is_empty(self) -> bool:
        return not (self.added or self.removed or self.renamed)


def diff_snapshots(
    before: DiscoverySnapshot, after: DiscoverySnapshot, at_ns: int
) -> HotplugChange:
    """Compare snapshots by ``input_token`` (spec RF12).

    A reconnection shows as ``removed`` (old token) plus ``added`` (new token).  A
    node that keeps its token but changes stable ID (renumbering of a fragile
    group) is ``renamed``; a node that changes class is ``removed`` + ``added``.
    """
    old = {device.tracking_key: device for device in before.devices}
    new = {device.tracking_key: device for device in after.devices}
    added: list[DiscoveredDevice] = []
    removed: list[DiscoveredDevice] = []
    renamed: list[tuple[StableId, StableId]] = []
    for key, device in old.items():
        current = new.get(key)
        if current is None or current.verdict.device_class is not device.verdict.device_class:
            removed.append(device)
            if current is not None:
                added.append(current)
        elif device.stable_id and current.stable_id and device.stable_id != current.stable_id:
            renamed.append((device.stable_id, current.stable_id))
    added.extend(device for key, device in new.items() if key not in old)
    return HotplugChange(
        added=tuple(sorted(added, key=_snapshot_order)),
        removed=tuple(sorted(removed, key=_snapshot_order)),
        renamed=tuple(sorted(renamed)),
        observed_at_ns=at_ns,
    )
