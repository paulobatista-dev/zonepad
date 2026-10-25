"""Synthetic sysfs trees for discovery tests (no real ``/sys``).

``build_sysfs(root, nodes)`` writes ``<root>/devices/<input_path>/`` with an
``eventN`` child, ``<root>/class/input/eventN -> ../../devices/.../eventN`` and
``eventN/device -> ../../inputM`` as relative symlinks, like the kernel does.

Bitmaps follow ``input_print_bitmap`` and are computed for 64-bit words unless
stated otherwise (values from the ``controller-hardware`` fixture table).
Synthetic data only: MACs use the locally administered bit (``02:...``) and
serials start with ``SYNTH``.
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path

from zonepad.domain.discovery import AbsInfo, absinfo_from_kernel

USB_XBOX_DEVICE = "pci0000:00/0000:00:14.0/usb1/1-2"
USB_XBOX_INPUT = f"{USB_XBOX_DEVICE}/1-2:1.0/input/input10"
BT_HCI = "pci0000:00/0000:00:14.0/usb1/1-9/1-9:1.0/bluetooth/hci0/hci0:256"

XBOX_KEY_W64 = "7cdb000000000000 0 0 0 0"
XBOX_KEY_W32 = "7cdb0000 0 0 0 0 0 0 0 0 0"


@dataclass(frozen=True)
class SysfsNode:
    event: str
    input_path: str
    name: str = ""
    bustype: str = "0003"
    vendor: str = "0000"
    product: str = "0000"
    version: str = "0000"
    uniq: str = ""
    phys: str = ""
    ev: str = "0"
    key: str = "0"
    abs: str = "0"
    rel: str = "0"
    msc: str = "0"
    properties: str = "0"
    has_parent: bool = True
    driver: tuple[str, str] | None = None
    parent_attrs: Mapping[str, str] = field(default_factory=dict)
    usb_device: str | None = None
    usb_attrs: Mapping[str, str] = field(default_factory=dict)


def build_sysfs(root: Path, nodes: Iterable[SysfsNode]) -> Path:
    class_dir = root / "class" / "input"
    class_dir.mkdir(parents=True, exist_ok=True)
    (root / "devices").mkdir(exist_ok=True)
    for node in nodes:
        _build_node(root, class_dir, node)
    return root


def add_broken_device_link(root: Path, event: str, target: str) -> None:
    """``class/input/<event>/`` as a real directory whose ``device`` link dangles."""
    event_dir = root / "class" / "input" / event
    event_dir.mkdir(parents=True)
    (event_dir / "device").symlink_to(target)


def _build_node(root: Path, class_dir: Path, node: SysfsNode) -> None:
    input_dir = root / "devices" / node.input_path
    event_dir = input_dir / node.event
    event_dir.mkdir(parents=True)
    _write(event_dir / "dev", "13:64")
    _write(event_dir / "uevent", f"MAJOR=13\nMINOR=64\nDEVNAME=input/{node.event}")
    (event_dir / "device").symlink_to(f"../../{input_dir.name}")
    _write(input_dir / "name", node.name)
    _write(input_dir / "phys", node.phys)
    _write(input_dir / "uniq", node.uniq)
    _write(input_dir / "properties", node.properties)
    for attribute, value in (
        ("bustype", node.bustype),
        ("vendor", node.vendor),
        ("product", node.product),
        ("version", node.version),
    ):
        _write(input_dir / "id" / attribute, value)
    for attribute, value in (
        ("ev", node.ev),
        ("key", node.key),
        ("abs", node.abs),
        ("rel", node.rel),
        ("msc", node.msc),
        ("sw", "0"),
        ("led", "0"),
        ("snd", "0"),
        ("ff", "0"),
    ):
        _write(input_dir / "capabilities" / attribute, value)
    if node.has_parent:
        parent = input_dir.parent.parent
        (input_dir / "device").symlink_to("../..")
        for attribute, value in node.parent_attrs.items():
            _write(parent / attribute, value)
        if node.driver is not None:
            bus, driver = node.driver
            driver_dir = root / "bus" / bus / "drivers" / driver
            driver_dir.mkdir(parents=True, exist_ok=True)
            _write(driver_dir / "uevent", f"DRIVER={driver}")
            link = parent / "driver"
            if not link.is_symlink():
                link.symlink_to(os.path.relpath(driver_dir, parent))
    if node.usb_device is not None:
        usb_dir = root / "devices" / node.usb_device
        for attribute, value in node.usb_attrs.items():
            _write(usb_dir / attribute, value)
    target = os.path.relpath(event_dir, class_dir)
    (class_dir / node.event).symlink_to(target)


def _write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value + "\n", encoding="utf-8")


# --- Catalogued fixtures (controller-hardware table 8.2) ---------------------


def xbox_one_s_usb(
    event: str = "event3", *, serial: str | None = "SYNTH0001", key: str = XBOX_KEY_W64
) -> SysfsNode:
    usb_attrs = {"idVendor": "045e", "idProduct": "02ea"}
    if serial is not None:
        usb_attrs["serial"] = serial
    return SysfsNode(
        event=event,
        input_path=USB_XBOX_INPUT,
        name="Microsoft X-Box One S pad",
        bustype="0003",
        vendor="045e",
        product="02ea",
        version="0408",
        phys="usb-0000:00:14.0-2/input0",
        ev="20000b",
        key=key,
        abs="3003f",
        driver=("usb", "xpad"),
        parent_attrs={"bInterfaceProtocol": "d0"},
        usb_device=USB_XBOX_DEVICE,
        usb_attrs=usb_attrs,
    )


def dualsense_bt_nodes(uniq: str = "02:00:00:00:00:01") -> tuple[SysfsNode, ...]:
    hid = f"{BT_HCI}/0005:054C:0CE6.0007"
    common = {
        "bustype": "0005",
        "vendor": "054c",
        "product": "0ce6",
        "version": "0100",
        "uniq": uniq,
        "driver": ("hid", "playstation"),
        "parent_attrs": {"firmware_version": "0x00000000"},
    }
    return (
        SysfsNode(
            event="event21",
            input_path=f"{hid}/input/input21",
            name="DualSense Wireless Controller",
            ev="20000b",
            key="7fdb000000000000 0 0 0 0",
            abs="3003f",
            **common,
        ),
        SysfsNode(
            event="event22",
            input_path=f"{hid}/input/input22",
            name="DualSense Wireless Controller Touchpad",
            ev="b",
            key="2420 10000 0 0 0 0",
            abs="260800000000003",
            properties="5",
            **common,
        ),
        SysfsNode(
            event="event23",
            input_path=f"{hid}/input/input23",
            name="DualSense Wireless Controller Motion Sensors",
            ev="19",
            key="0",
            abs="3f",
            msc="20",
            properties="40",
            **common,
        ),
    )


def switch_pro_bt(event: str = "event25") -> SysfsNode:
    return SysfsNode(
        event=event,
        input_path=f"{BT_HCI}/0005:057E:2009.0009/input/input25",
        name="Pro Controller",
        bustype="0005",
        vendor="057e",
        product="2009",
        version="8001",
        uniq="02:00:00:00:00:0A",
        phys="02:00:00:00:00:aa",
        ev="20000b",
        key="7ffb000000000000 0 0 0 0",
        abs="3001b",
        driver=("hid", "nintendo"),
    )


def xbox360w_pads() -> tuple[SysfsNode, ...]:
    device = "pci0000:00/0000:00:14.0/usb1/1-4"
    common = {
        "name": "Xbox 360 Wireless Receiver",
        "bustype": "0003",
        "vendor": "045e",
        "product": "02a1",
        "version": "0100",
        "phys": "usb-0000:00:14.0-4/input0",
        "ev": "20000b",
        "key": "f00000000 0 0 0 7cdb000000000000 0 0 0 0",
        "abs": "3003f",
        "driver": ("usb", "xpad"),
        "parent_attrs": {"bInterfaceProtocol": "81"},
        "usb_device": device,
        "usb_attrs": {"idVendor": "045e", "idProduct": "0719"},
    }
    return (
        SysfsNode(event="event40", input_path=f"{device}/1-4:1.0/input/input40", **common),
        SysfsNode(event="event41", input_path=f"{device}/1-4:1.2/input/input41", **common),
    )


# --- Generic HID and non-gamepad fixtures --------------------------------------


def generic_without_triggers(event: str = "event50") -> SysfsNode:
    device = "pci0000:00/0000:00:14.0/usb1/1-5"
    return SysfsNode(
        event=event,
        input_path=f"{device}/1-5:1.0/0003:1209:0001.0003/input/input50",
        name="Synthetic Generic Pad",
        bustype="0003",
        vendor="1209",
        product="0001",
        version="0100",
        uniq="SYNTH0002",
        phys="usb-0000:00:14.0-5/input0",
        ev="1b",
        key="fdb000000000000 0 0 0 0",
        abs="1b",
        driver=("hid", "hid-generic"),
    )


def generic_usb_full(event: str = "event52") -> SysfsNode:
    """HID generic pad with X/Y/RX/RY and Z/RZ triggers (range 0..4095 via absinfo)."""
    device = "pci0000:00/0000:00:14.0/usb1/1-6"
    return SysfsNode(
        event=event,
        input_path=f"{device}/1-6:1.0/0003:1209:0002.0004/input/input52",
        name="Synthetic Generic Full Pad",
        bustype="0003",
        vendor="1209",
        product="0002",
        version="0100",
        uniq="SYNTH0003",
        phys="usb-0000:00:14.0-6/input0",
        ev="1b",
        key="fdb000000000000 0 0 0 0",
        abs="3f",
        driver=("hid", "hid-generic"),
    )


def generic_bt_z_rz(event: str = "event51") -> SysfsNode:
    return SysfsNode(
        event=event,
        input_path="virtual/misc/uhid/0005:F055:0002.000A/input/input51",
        name="Synthetic BT Pad",
        bustype="0005",
        vendor="f055",
        product="0002",
        version="0001",
        uniq="02:00:00:00:00:02",
        phys="02:00:00:00:00:aa",
        ev="1b",
        key="7cdb000000000000 0 0 0 0",
        abs="30627",
        driver=("hid", "hid-generic"),
    )


def keyboard(event: str = "event1") -> SysfsNode:
    return SysfsNode(
        event=event,
        input_path="platform/i8042/serio0/input/input3",
        name="AT Translated Set 2 keyboard",
        bustype="0011",
        vendor="0001",
        product="0001",
        version="ab83",
        phys="isa0060/serio0/input0",
        ev="120013",
        key="ffffffffffffffff fffffffffffffffe",
        msc="10",
        driver=("serio", "atkbd"),
    )


def mouse(event: str = "event5") -> SysfsNode:
    device = "pci0000:00/0000:00:14.0/usb1/1-3"
    return SysfsNode(
        event=event,
        input_path=f"{device}/1-3:1.0/0003:F055:0001.0002/input/input5",
        name="Synthetic USB Mouse",
        bustype="0003",
        vendor="f055",
        product="0001",
        version="0111",
        phys="usb-0000:00:14.0-3/input0",
        ev="17",
        key="70000 0 0 0 0",
        rel="103",
        msc="10",
        driver=("hid", "hid-generic"),
    )


def touchpad(event: str = "event7") -> SysfsNode:
    return SysfsNode(
        event=event,
        input_path="platform/i8042/serio1/input/input7",
        name="Synthetic Touchpad",
        bustype="0011",
        vendor="0002",
        product="0007",
        version="01b1",
        ev="b",
        key="2420 10000 0 0 0 0",
        abs="260800000000003",
        properties="5",
    )


def zonapad_virtual(event: str = "event30") -> SysfsNode:
    return SysfsNode(
        event=event,
        input_path="virtual/input/input30",
        name="ZonaPad Virtual Controller",
        bustype="0003",
        vendor="1234",
        product="0001",
        version="0001",
        ev="b",
        key="1b000000000000 0 0 0 0",
        abs="3f",
        has_parent=False,
    )


def steam_like_virtual(event: str = "event31") -> SysfsNode:
    return SysfsNode(
        event=event,
        input_path="virtual/input/input31",
        name="Microsoft X-Box 360 pad 0",
        bustype="0003",
        vendor="045e",
        product="028e",
        version="0001",
        ev="20000b",
        key=XBOX_KEY_W64,
        abs="3003f",
        has_parent=False,
    )


def twin_generic_pads() -> tuple[SysfsNode, ...]:
    """Two identical pads without uniq, serial or phys (occurrence identity)."""
    base = SysfsNode(
        event="event2",
        input_path="platform/synthetic-hub/twin1/input/input60",
        name="Synthetic Twin Pad",
        bustype="0003",
        vendor="1209",
        product="0009",
        version="0001",
        ev="1b",
        key="fdb000000000000 0 0 0 0",
        abs="3f",
        driver=("hid", "hid-generic"),
    )
    second = replace(
        base,
        event="event10",
        input_path="platform/synthetic-hub/twin2/input/input61",
    )
    return base, second


# --- Absinfo (struct order: value, minimum, maximum, fuzz, flat, resolution) ---


def _absinfo(table: Mapping[int, tuple[int, int, int, int, int, int]]) -> dict[int, AbsInfo]:
    return {code: absinfo_from_kernel(*values) for code, values in table.items()}


XBOX_ONE_ABSINFO = _absinfo(
    {
        **dict.fromkeys((0, 1, 3, 4), (0, -32768, 32767, 16, 128, 0)),
        **dict.fromkeys((2, 5), (0, 0, 1023, 0, 0, 0)),
    }
)
DUALSENSE_ABSINFO = _absinfo(
    {
        **dict.fromkeys((0, 1, 3, 4), (128, 0, 255, 0, 0, 0)),
        **dict.fromkeys((2, 5), (0, 0, 255, 0, 0, 0)),
    }
)
GENERIC_4095_ABSINFO = _absinfo(
    {
        **dict.fromkeys((0, 1, 3, 4), (2048, 0, 4095, 15, 255, 0)),
        **dict.fromkeys((2, 5), (0, 0, 255, 0, 15, 0)),
    }
)
