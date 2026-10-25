from __future__ import annotations

from dataclasses import replace

import pytest

from zonepad.domain.discovery import (
    AbsInfo,
    AxisCapability,
    ButtonCapability,
    DeviceCapabilities,
    DeviceClass,
    DiscoverySnapshot,
    GamepadKind,
    ObservedInputDevice,
    ReadIssue,
    ReadIssueKind,
    absinfo_from_kernel,
    build_snapshot,
    classify,
    diff_snapshots,
)
from zonepad.infrastructure.linux_input_policy import (
    discovery_policies,
    gamepad_filter_policy,
)

POLICY = gamepad_filter_policy()
POLICIES = discovery_policies()
PAD_BUTTONS = frozenset({0x130, 0x131, 0x133, 0x134, 0x136, 0x137})


def _device(
    *,
    event_node: str = "event3",
    input_token: str | None = "input10",
    ev: frozenset[int] = frozenset({0, 1, 3}),
    axes: frozenset[int] = frozenset({0, 1, 2, 3, 4, 5}),
    buttons: frozenset[int] = PAD_BUTTONS,
    rel: frozenset[int] = frozenset(),
    props: frozenset[int] = frozenset(),
    name: str = "Pad",
    bustype: int = 0x03,
    vendor_id: int = 0x045E,
    product_id: int = 0x02EA,
    usb_serial: str | None = "SYNTH0001",
    is_virtual_path: bool = False,
    issues: tuple[ReadIssue, ...] = (),
) -> ObservedInputDevice:
    return ObservedInputDevice(
        event_node=event_node,
        input_token=input_token,
        sysfs_path="/devices/synthetic/input/" + (input_token or "x"),
        name=name,
        bustype=bustype,
        vendor_id=vendor_id,
        product_id=product_id,
        version=1,
        uniq="",
        phys="",
        usb_serial=usb_serial,
        driver="xpad",
        firmware=None,
        usb_interface_protocol=None,
        is_virtual_path=is_virtual_path,
        capabilities=DeviceCapabilities.from_codes(
            event_types=ev, axes=axes, buttons=buttons, relative_axes=rel, properties=props
        ),
        issues=issues,
    )


@pytest.mark.parametrize(
    ("overrides", "device_class", "kind", "reasons"),
    [
        ({}, DeviceClass.GAMEPAD, GamepadKind.GAMEPAD, ()),
        (
            {"buttons": frozenset({0x120, 0x121, 0x122})},
            DeviceClass.GAMEPAD,
            GamepadKind.JOYSTICK_HID,
            (),
        ),
        (
            {"buttons": frozenset({0x120, 0x110})},
            DeviceClass.UNKNOWN,
            None,
            ("not_a_gamepad:other",),
        ),
        (
            {"rel": frozenset({0, 1}), "ev": frozenset({0, 1, 2, 3})},
            DeviceClass.UNKNOWN,
            None,
            ("ambiguous:gamepad_and_mouse",),
        ),
        (
            {"buttons": PAD_BUTTONS | frozenset(range(1, 32))},
            DeviceClass.UNKNOWN,
            None,
            ("ambiguous:gamepad_and_keyboard",),
        ),
        (
            {"buttons": PAD_BUTTONS | {167, 30, 57}},
            DeviceClass.GAMEPAD,
            GamepadKind.GAMEPAD,
            (),
        ),
        (
            {"props": frozenset({0x06}), "ev": frozenset({0, 3})},
            DeviceClass.MOTION_SENSOR,
            None,
            ("not_a_gamepad:motion_sensor",),
        ),
        (
            {"ev": frozenset({0, 3}), "buttons": frozenset()},
            DeviceClass.MOTION_SENSOR,
            None,
            ("not_a_gamepad:motion_sensor",),
        ),
        (
            {"axes": frozenset({0, 1, 0x35, 0x36}), "props": frozenset({0, 2})},
            DeviceClass.TOUCHPAD,
            None,
            ("not_a_gamepad:touchpad",),
        ),
        (
            {"axes": frozenset({0, 1, 0x35, 0x36}), "props": frozenset({1})},
            DeviceClass.UNKNOWN,
            None,
            ("not_a_gamepad:touchscreen_or_tablet",),
        ),
        (
            {"axes": frozenset(), "ev": frozenset({0, 1}), "buttons": frozenset({30, 57})},
            DeviceClass.KEYBOARD,
            None,
            ("not_a_gamepad:keyboard",),
        ),
        (
            {"axes": frozenset(), "ev": frozenset({0, 1, 2}), "rel": frozenset({0, 1})},
            DeviceClass.MOUSE,
            None,
            ("not_a_gamepad:mouse",),
        ),
        (
            {"axes": frozenset(), "buttons": frozenset({0x110, 0x111})},
            DeviceClass.MOUSE,
            None,
            ("not_a_gamepad:mouse",),
        ),
        (
            {"axes": frozenset({0x28}), "buttons": frozenset({0x2C0})},
            DeviceClass.UNKNOWN,
            None,
            ("not_a_gamepad:no_abs_xy",),
        ),
        (
            {"buttons": frozenset({0x2C0})},
            DeviceClass.UNKNOWN,
            None,
            ("not_a_gamepad:no_gamepad_buttons",),
        ),
    ],
)
def test_classification_rules(
    overrides: dict[str, object],
    device_class: DeviceClass,
    kind: GamepadKind | None,
    reasons: tuple[str, ...],
) -> None:
    verdict = classify(_device(**overrides), POLICY)  # type: ignore[arg-type]

    assert verdict.device_class is device_class
    assert verdict.gamepad_kind is kind
    assert verdict.reasons == reasons


def test_joystick_hid_warns_that_face_buttons_are_not_positional() -> None:
    verdict = classify(_device(buttons=frozenset({0x120, 0x121})), POLICY)

    assert verdict.warnings == ("face_buttons_not_positional",)


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        (
            {"name": "ZonaPad Virtual Controller", "vendor_id": 0x1234, "product_id": 0x0001},
            "virtual:zonapad",
        ),
        ({"vendor_id": 0x28DE}, "virtual:steam_input"),
        ({"name": "Steam Virtual Gamepad"}, "virtual:steam_input"),
        ({}, "virtual:uinput"),
    ],
)
def test_virtual_path_is_virtual_even_with_bus_usb(
    overrides: dict[str, object], reason: str
) -> None:
    verdict = classify(_device(is_virtual_path=True, **overrides), POLICY)  # type: ignore[arg-type]

    assert verdict.device_class is DeviceClass.VIRTUAL
    assert verdict.reasons == (reason,)


def test_bus_virtual_without_virtual_path_is_virtual() -> None:
    verdict = classify(_device(bustype=0x06), POLICY)

    assert verdict.device_class is DeviceClass.VIRTUAL
    assert verdict.reasons == ("virtual:bus_virtual",)


def test_fatal_read_issue_makes_the_device_unknown() -> None:
    issues = (ReadIssue(ReadIssueKind.MALFORMED_BITMAP, "capabilities/key"),)

    verdict = classify(_device(issues=issues), POLICY)

    assert verdict.device_class is DeviceClass.UNKNOWN
    assert verdict.reasons == ("malformed_bitmap:capabilities/key",)


def test_non_fatal_issue_becomes_a_warning() -> None:
    verdict = classify(_device(issues=(ReadIssue(ReadIssueKind.USB_PRODUCT_MISMATCH),)), POLICY)

    assert verdict.is_gamepad
    assert verdict.warnings == ("usb_product_mismatch",)


def test_absinfo_from_kernel_discards_negative_fields() -> None:
    info = absinfo_from_kernel(7, 0, 255, -1, 15, -3)

    assert info == AbsInfo(0, 255, None, 15, None, value_at_probe=7)
    assert info.discarded_fields == ("fuzz", "resolution")


@pytest.mark.parametrize(("minimum", "maximum"), [(0, 0), (10, -10)])
def test_absinfo_requires_minimum_below_maximum(minimum: int, maximum: int) -> None:
    with pytest.raises(ValueError):
        absinfo_from_kernel(0, minimum, maximum, 0, 0, 0)


def test_capabilities_reject_duplicates_and_out_of_range_codes() -> None:
    with pytest.raises(ValueError):
        DeviceCapabilities(
            frozenset(), (AxisCapability(1), AxisCapability(1)), (), frozenset(), frozenset()
        )
    with pytest.raises(ValueError):
        AxisCapability(0x40)
    with pytest.raises(ValueError):
        ButtonCapability(0x300)


def test_with_absinfo_attaches_only_present_axes() -> None:
    caps = _device(axes=frozenset({0, 1})).capabilities
    assert caps is not None
    info = absinfo_from_kernel(0, -1, 1, 0, 0, 0)

    updated = caps.with_absinfo({0: info, 9: info})

    assert updated.axis(0) == AxisCapability(0, info)
    assert updated.axis(1) == AxisCapability(1, None)
    assert updated.axis(9) is None


def test_snapshot_orders_gamepads_by_id_then_others_by_node() -> None:
    observed = [
        _device(event_node="event10", input_token="input20", usb_serial="SYNTH-B"),
        _device(
            event_node="event2",
            input_token="input21",
            axes=frozenset(),
            buttons=frozenset({30, 57}),
            ev=frozenset({1}),
        ),
        _device(event_node="event4", input_token="input22", usb_serial="SYNTH-A"),
        _device(
            event_node="event1",
            input_token="input23",
            axes=frozenset(),
            buttons=frozenset({30, 57}),
            ev=frozenset({1}),
        ),
    ]

    snapshot = build_snapshot(observed, POLICIES)

    gamepad_ids = [device.stable_id for device in snapshot.gamepads]
    assert gamepad_ids == sorted(gamepad_ids)
    assert [device.event_node for device in snapshot.devices[2:]] == ["event1", "event2"]
    assert all(device.identity is None for device in snapshot.devices[2:])


def _snapshot(*devices: ObservedInputDevice) -> DiscoverySnapshot:
    return build_snapshot(devices, POLICIES)


def test_diff_reports_added_and_removed_by_input_token() -> None:
    pad = _device()
    other = _device(event_node="event4", input_token="input11", usb_serial="SYNTH0002")

    change = diff_snapshots(_snapshot(pad), _snapshot(other), at_ns=5)

    assert [device.observed.input_token for device in change.added] == ["input11"]
    assert [device.observed.input_token for device in change.removed] == ["input10"]
    assert change.renamed == ()
    assert change.observed_at_ns == 5


def test_reconnection_with_a_new_token_is_removed_plus_added() -> None:
    before = _snapshot(_device(input_token="input10"))
    after = _snapshot(_device(input_token="input12"))

    change = diff_snapshots(before, after, at_ns=1)

    assert change.removed[0].stable_id == change.added[0].stable_id
    assert change.removed[0].observed.input_token == "input10"
    assert change.added[0].observed.input_token == "input12"


def test_same_event_node_reused_by_a_new_registration_is_detected() -> None:
    before = _snapshot(_device(event_node="event3", input_token="input10"))
    after = _snapshot(_device(event_node="event3", input_token="input15", usb_serial="SYNTH9"))

    change = diff_snapshots(before, after, at_ns=1)

    assert len(change.added) == 1 and len(change.removed) == 1


def test_twin_renumbering_is_reported_as_renamed() -> None:
    first = _device(event_node="event2", input_token="input30", usb_serial=None)
    second = _device(event_node="event10", input_token="input31", usb_serial=None)
    before = _snapshot(first, second)
    after = _snapshot(second)

    change = diff_snapshots(before, after, at_ns=1)

    assert [device.observed.input_token for device in change.removed] == ["input30"]
    assert change.renamed == (("usb-045e-02ea-n2", "usb-045e-02ea-n1"),)
    assert change.added == ()


def test_unchanged_snapshot_is_empty() -> None:
    snapshot = _snapshot(_device())

    assert diff_snapshots(snapshot, snapshot, at_ns=0).is_empty


def test_class_change_with_the_same_token_is_removed_plus_added() -> None:
    denied = replace(
        _device(), capabilities=None, issues=(ReadIssue(ReadIssueKind.PERMISSION_DENIED),)
    )

    change = diff_snapshots(_snapshot(denied), _snapshot(_device()), at_ns=0)

    assert change.removed[0].verdict.device_class is DeviceClass.UNKNOWN
    assert change.added[0].verdict.device_class is DeviceClass.GAMEPAD
