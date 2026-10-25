from __future__ import annotations

from pathlib import Path

import pytest
from conftest import IoGuardFactory
from sysfs_builder import (
    XBOX_KEY_W32,
    add_broken_device_link,
    build_sysfs,
    dualsense_bt_nodes,
    generic_bt_z_rz,
    keyboard,
    mouse,
    steam_like_virtual,
    switch_pro_bt,
    touchpad,
    xbox360w_pads,
    xbox_one_s_usb,
    zonapad_virtual,
)

from zonepad.application.discovery import discover_devices
from zonepad.domain.discovery import DeviceClass, GamepadKind, ReadIssueKind
from zonepad.domain.errors import DeviceNotFoundError
from zonepad.domain.identity import Connection, QualifierSource
from zonepad.infrastructure.linux_input_policy import discovery_policies
from zonepad.infrastructure.sysfs import MalformedBitmapError, SysfsInputScanner, decode_bitmap

POLICIES = discovery_policies()


def _snapshot(root: Path, **scanner_kwargs: object):
    return discover_devices(SysfsInputScanner(root, **scanner_kwargs), POLICIES)  # type: ignore[arg-type]


def test_xbox_one_s_usb_is_a_gamepad_identified_by_usb_serial(
    tmp_path: Path, forbid_io_outside: IoGuardFactory
) -> None:
    build_sysfs(tmp_path, [xbox_one_s_usb()])

    with forbid_io_outside(tmp_path):
        observed = SysfsInputScanner(tmp_path, bitmap_word_bits=64).scan()
        snapshot = discover_devices(SysfsInputScanner(tmp_path, bitmap_word_bits=64), POLICIES)

    (device,) = observed
    assert device.event_node == "event3"
    assert device.input_token == "input10"
    assert device.sysfs_path == "/devices/pci0000:00/0000:00:14.0/usb1/1-2/1-2:1.0/input/input10"
    assert (device.bustype, device.vendor_id, device.product_id, device.version) == (
        0x03,
        0x045E,
        0x02EA,
        0x0408,
    )
    assert device.name == "Microsoft X-Box One S pad"
    assert device.uniq == ""
    assert device.phys == "usb-0000:00:14.0-2/input0"
    assert device.usb_serial == "SYNTH0001"
    assert device.driver == "xpad"
    assert device.usb_interface_protocol == "d0"
    assert device.firmware is None
    assert not device.is_virtual_path
    assert device.issues == ()
    assert device.capabilities is not None
    assert device.capabilities.axis_codes == frozenset({0, 1, 2, 3, 4, 5, 0x10, 0x11})
    assert {0x130, 0x131, 0x133, 0x134, 0x13C} <= device.capabilities.button_codes
    (gamepad,) = snapshot.gamepads
    assert gamepad.verdict.gamepad_kind is GamepadKind.GAMEPAD
    assert gamepad.identity is not None
    assert gamepad.identity.qualifier_source is QualifierSource.USB_SERIAL
    assert gamepad.identity.connection is Connection.USB
    assert gamepad.stable_id is not None and gamepad.stable_id.startswith("usb-045e-02ea-s")
    assert "event3" not in gamepad.stable_id


def test_xbox_without_serial_falls_back_to_phys(tmp_path: Path) -> None:
    build_sysfs(tmp_path, [xbox_one_s_usb(serial=None)])

    (gamepad,) = _snapshot(tmp_path).gamepads

    assert gamepad.identity is not None
    assert gamepad.identity.qualifier_source is QualifierSource.PHYS
    assert "identity_bound_to_port" in gamepad.identity.warnings
    assert gamepad.stable_id is not None and gamepad.stable_id.startswith("usb-045e-02ea-p")


def test_bitmap_word_width_32_gives_the_same_snapshot_as_64(tmp_path: Path) -> None:
    build_sysfs(tmp_path / "w64", [xbox_one_s_usb()])
    build_sysfs(tmp_path / "w32", [xbox_one_s_usb(key=XBOX_KEY_W32)])

    w64 = SysfsInputScanner(tmp_path / "w64", bitmap_word_bits=64).scan()
    w32 = SysfsInputScanner(tmp_path / "w32", bitmap_word_bits=32).scan()

    assert w64[0].capabilities == w32[0].capabilities
    assert _snapshot(tmp_path / "w64").gamepads[0].stable_id == (
        _snapshot(tmp_path / "w32", bitmap_word_bits=32).gamepads[0].stable_id
    )


def test_dualsense_bt_exposes_one_gamepad_and_hides_auxiliary_nodes(tmp_path: Path) -> None:
    build_sysfs(tmp_path, dualsense_bt_nodes())

    snapshot = _snapshot(tmp_path)

    (gamepad,) = snapshot.gamepads
    assert gamepad.event_node == "event21"
    assert gamepad.identity is not None
    assert gamepad.identity.connection is Connection.BLUETOOTH
    assert gamepad.identity.qualifier_source is QualifierSource.UNIQ
    assert gamepad.observed.firmware == "0x00000000"
    classes = {device.event_node: device.verdict for device in snapshot.devices}
    assert classes["event22"].device_class is DeviceClass.TOUCHPAD
    assert classes["event22"].reasons == ("not_a_gamepad:touchpad",)
    assert classes["event23"].device_class is DeviceClass.MOTION_SENSOR
    assert classes["event23"].reasons == ("not_a_gamepad:motion_sensor",)


@pytest.mark.parametrize(
    ("node", "device_class", "reason"),
    [
        (keyboard(), DeviceClass.KEYBOARD, "not_a_gamepad:keyboard"),
        (mouse(), DeviceClass.MOUSE, "not_a_gamepad:mouse"),
        (touchpad(), DeviceClass.TOUCHPAD, "not_a_gamepad:touchpad"),
        (zonapad_virtual(), DeviceClass.VIRTUAL, "virtual:zonapad"),
        (steam_like_virtual(), DeviceClass.VIRTUAL, "virtual:uinput"),
    ],
)
def test_non_gamepads_are_classified_with_a_stable_reason(
    tmp_path: Path, node, device_class: DeviceClass, reason: str
) -> None:
    build_sysfs(tmp_path, [node])

    snapshot = _snapshot(tmp_path)

    assert snapshot.gamepads == ()
    (device,) = snapshot.devices
    assert device.verdict.device_class is device_class
    assert device.verdict.reasons == (reason,)
    assert device.identity is None
    assert not device.is_selectable


def test_zonapad_virtual_path_is_detected_without_a_parent_device(tmp_path: Path) -> None:
    build_sysfs(tmp_path, [zonapad_virtual()])

    (device,) = SysfsInputScanner(tmp_path).scan()

    assert device.is_virtual_path
    assert device.sysfs_path == "/devices/virtual/input/input30"
    assert device.driver is None


def test_bluetooth_through_uhid_is_not_virtual(tmp_path: Path) -> None:
    build_sysfs(tmp_path, [generic_bt_z_rz()])

    (device,) = _snapshot(tmp_path).devices

    assert not device.observed.is_virtual_path
    assert device.verdict.device_class is DeviceClass.GAMEPAD
    assert device.identity is not None
    assert device.identity.qualifier_source is QualifierSource.UNIQ


def test_switch_pro_bluetooth_never_uses_phys(tmp_path: Path) -> None:
    build_sysfs(tmp_path, [switch_pro_bt()])

    (gamepad,) = _snapshot(tmp_path).gamepads

    assert gamepad.identity is not None
    assert gamepad.identity.qualifier_source is QualifierSource.UNIQ
    assert gamepad.observed.driver == "nintendo"


def test_broken_device_link_is_unknown_and_the_scan_continues(
    tmp_path: Path, forbid_io_outside: IoGuardFactory
) -> None:
    build_sysfs(tmp_path, [xbox_one_s_usb()])
    add_broken_device_link(tmp_path, "event60", "../../devices/nao-existe/input60")

    with forbid_io_outside(tmp_path):
        snapshot = _snapshot(tmp_path)

    assert [device.event_node for device in snapshot.gamepads] == ["event3"]
    broken = snapshot.by_event_node("event60")
    assert broken is not None
    assert broken.verdict.device_class is DeviceClass.UNKNOWN
    assert broken.verdict.reasons == ("broken_device_link",)


def test_permission_denied_attribute_marks_only_that_node(tmp_path: Path) -> None:
    build_sysfs(tmp_path, [xbox_one_s_usb(), keyboard()])

    def read_text(path: Path) -> str:
        if "serio0" in str(path) and path.name == "name":
            raise PermissionError(path)
        return path.read_text(encoding="utf-8", errors="replace")

    snapshot = _snapshot(tmp_path, read_text=read_text)

    assert [device.event_node for device in snapshot.gamepads] == ["event3"]
    denied = snapshot.by_event_node("event1")
    assert denied is not None
    assert denied.verdict.device_class is DeviceClass.UNKNOWN
    assert denied.verdict.reasons == ("permission_denied",)
    assert denied.observed.input_token == "input3"


def test_permission_denied_on_the_only_gamepad_leaves_no_gamepad(tmp_path: Path) -> None:
    build_sysfs(tmp_path, [xbox_one_s_usb()])

    def read_text(path: Path) -> str:
        raise PermissionError(path)

    snapshot = _snapshot(tmp_path, read_text=read_text)

    assert snapshot.gamepads == ()
    assert snapshot.devices[0].verdict.reasons == ("permission_denied",)


def test_malformed_bitmap_is_reported_with_the_attribute(tmp_path: Path) -> None:
    node = xbox_one_s_usb()
    build_sysfs(tmp_path, [node])
    (tmp_path / "devices" / node.input_path / "capabilities" / "abs").write_text("xyz\n")

    (device,) = _snapshot(tmp_path).devices

    assert device.verdict.reasons == ("malformed_bitmap:capabilities/abs",)


def test_invalid_utf8_name_is_replaced_and_warned(tmp_path: Path) -> None:
    node = xbox_one_s_usb()
    build_sysfs(tmp_path, [node])
    (tmp_path / "devices" / node.input_path / "name").write_bytes(b"Pad \xff\n")

    (device,) = _snapshot(tmp_path).devices

    assert device.observed.name == "Pad �"
    assert device.verdict.is_gamepad
    assert "invalid_utf8:name" in device.verdict.warnings


def test_symlink_leaving_the_root_is_reported(tmp_path: Path) -> None:
    root = tmp_path / "sys"
    build_sysfs(root, [xbox_one_s_usb()])
    outside = tmp_path / "outside" / "input99"
    outside.mkdir(parents=True)
    add_broken_device_link(root, "event99", str(outside))

    snapshot = _snapshot(root)

    escaped = snapshot.by_event_node("event99")
    assert escaped is not None
    assert escaped.verdict.reasons == (ReadIssueKind.OUTSIDE_SYSFS_ROOT.value,)


def test_usb_product_mismatch_keeps_the_vendor_match_and_warns(tmp_path: Path) -> None:
    build_sysfs(tmp_path, xbox360w_pads())

    snapshot = _snapshot(tmp_path)

    assert len(snapshot.gamepads) == 2
    for gamepad in snapshot.gamepads:
        assert "usb_product_mismatch" in gamepad.verdict.warnings
        assert gamepad.observed.usb_serial is None
        assert gamepad.identity is not None
        assert gamepad.identity.qualifier_source is QualifierSource.PHYS


def test_missing_sysfs_root_raises_device_not_found(tmp_path: Path) -> None:
    with pytest.raises(DeviceNotFoundError, match="sysfs input class not found"):
        SysfsInputScanner(tmp_path / "absent").scan()


def test_nodes_are_scanned_in_numeric_event_order(tmp_path: Path) -> None:
    build_sysfs(tmp_path, [xbox_one_s_usb("event10"), keyboard("event2")])

    nodes = [device.event_node for device in SysfsInputScanner(tmp_path).scan()]

    assert nodes == ["event2", "event10"]


def test_unchanged_nodes_are_served_from_the_cache(tmp_path: Path) -> None:
    build_sysfs(tmp_path, [xbox_one_s_usb()])
    reads: list[Path] = []

    def read_text(path: Path) -> str:
        reads.append(path)
        return path.read_text(encoding="utf-8")

    scanner = SysfsInputScanner(tmp_path, read_text=read_text)
    first = scanner.scan()
    count_after_first = len(reads)
    second = scanner.scan()

    assert first == second
    assert count_after_first > 0
    assert len(reads) == count_after_first


def test_observe_rereads_one_node_for_post_open_verification(tmp_path: Path) -> None:
    build_sysfs(tmp_path, [xbox_one_s_usb()])
    scanner = SysfsInputScanner(tmp_path)

    device = scanner.observe("event3")

    assert device is not None and device.input_token == "input10"
    assert scanner.observe("event9") is None
    with pytest.raises(ValueError):
        scanner.observe("../event3")


@pytest.mark.parametrize(
    ("text", "word_bits", "max_code", "expected"),
    [
        ("0", 64, 0x3F, frozenset()),
        ("3003f\n", 64, 0x3F, frozenset({0, 1, 2, 3, 4, 5, 16, 17})),
        ("10000 0", 64, 0x7F, frozenset({80})),
        ("1 0", 32, 0x3F, frozenset({32})),
        ("FF", 64, 0x3F, frozenset(range(8))),
    ],
)
def test_decode_bitmap(text: str, word_bits: int, max_code: int, expected: frozenset[int]) -> None:
    assert decode_bitmap(text, word_bits, max_code) == expected


@pytest.mark.parametrize(
    ("text", "word_bits", "max_code"),
    [
        ("", 64, 0x3F),
        ("0x3f", 64, 0x3F),
        ("1  0", 64, 0x3F),
        ("100000000", 32, 0x3F),
        ("1 0", 64, 0x3F),
        ("80", 64, 0x06),
    ],
)
def test_decode_bitmap_rejects_malformed_text(text: str, word_bits: int, max_code: int) -> None:
    with pytest.raises(MalformedBitmapError):
        decode_bitmap(text, word_bits, max_code)


def test_scanner_rejects_unsupported_word_width(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        SysfsInputScanner(tmp_path, bitmap_word_bits=16)


def test_xbox360w_pads_sharing_phys_get_dot_suffix_and_are_fragile(tmp_path: Path) -> None:
    build_sysfs(tmp_path, xbox360w_pads())

    first, second = (_snapshot(tmp_path).by_event_node(n) for n in ("event40", "event41"))

    assert first is not None and second is not None
    assert first.identity is not None and second.identity is not None
    assert first.identity.stable_id.startswith("usb-045e-02a1-p")
    assert second.identity.stable_id == f"{first.identity.stable_id}.2"
    assert first.identity.fragile and second.identity.fragile
    assert "duplicate_identity:2" in second.identity.warnings
