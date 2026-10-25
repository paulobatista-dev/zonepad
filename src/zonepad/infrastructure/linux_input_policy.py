"""Linux input constants and the policies built from them (spec RF2, RF3, RF6).

This is the single source of these numbers; the domain receives them as data.
Values come from ``include/uapi/linux/input-event-codes.h`` and
``include/uapi/linux/input.h`` (kernel ``330517c63aa9``), reviewed by
``controller-hardware``.
"""

from __future__ import annotations

import ctypes
import re

from zonepad.domain.discovery import DiscoveryPolicies, GamepadFilterPolicy
from zonepad.domain.identity import Connection, IdentityPolicy
from zonepad.domain.mapping_draft import DraftRules

# Bitmap upper bounds (input-event-codes.h / input.h).
EV_MAX = 0x1F
KEY_MAX = 0x2FF
ABS_MAX = 0x3F
REL_MAX = 0x0F
INPUT_PROP_MAX = 0x1F

# Width of one ``unsigned long`` word in sysfs bitmaps for *this* process
# (``input-compat.c:100-120``: a 32-bit reader sees 32-bit words).
DEFAULT_BITMAP_WORD_BITS = 8 * ctypes.sizeof(ctypes.c_ulong)

# Event types.
EV_KEY = 0x01
EV_REL = 0x02
EV_ABS = 0x03

# Absolute axes.
ABS_X = 0x00
ABS_Y = 0x01
ABS_Z = 0x02
ABS_RX = 0x03
ABS_RY = 0x04
ABS_RZ = 0x05
ABS_GAS = 0x09
ABS_BRAKE = 0x0A
ABS_HAT2X = 0x14
ABS_HAT2Y = 0x15
ABS_MT_POSITION_X = 0x35
ABS_MT_POSITION_Y = 0x36

# Relative axes.
REL_X = 0x00
REL_Y = 0x01

# Keys and buttons.
KEY_A = 30
KEY_SPACE = 57
BTN_MOUSE = 0x110
BTN_JOYSTICK = 0x120
BTN_SOUTH = 0x130
BTN_EAST = 0x131
BTN_NORTH = 0x133
BTN_WEST = 0x134
BTN_TL2 = 0x138
BTN_TR2 = 0x139
BTN_TOOL_PEN = 0x140
BTN_TOOL_FINGER = 0x145
BTN_STYLUS = 0x14B

# Input properties.
INPUT_PROP_POINTER = 0x00
INPUT_PROP_DIRECT = 0x01
INPUT_PROP_ACCELEROMETER = 0x06

# Bus types.
BUS_USB = 0x03
BUS_BLUETOOTH = 0x05
BUS_VIRTUAL = 0x06

# Virtual devices (``infrastructure/uinput.py``; Valve VID in ``hid-ids.h``).
ZONAPAD_VIRTUAL_NAME = "ZonaPad Virtual Controller"
ZONAPAD_VIRTUAL_IDS = (0x1234, 0x0001)
STEAM_VENDOR_ID = 0x28DE
STEAM_NAME_MARKER = "Steam"

MAC_PATTERN = re.compile(r"(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}", re.ASCII)
PLACEHOLDER_PATTERN = re.compile(r"0+", re.ASCII)

# HID generic numbers buttons sequentially, not by position (hid-input.c:807-812).
NON_POSITIONAL_DRIVERS = frozenset({"hid-generic"})
POSITIONAL_BUTTONS = {
    BTN_SOUTH: "button_south",
    BTN_EAST: "button_east",
    BTN_NORTH: "button_north",
    BTN_WEST: "button_west",
}


def gamepad_filter_policy() -> GamepadFilterPolicy:
    return GamepadFilterPolicy(
        ev_key=EV_KEY,
        ev_rel=EV_REL,
        ev_abs=EV_ABS,
        abs_x=ABS_X,
        abs_y=ABS_Y,
        abs_z=ABS_Z,
        abs_mt_position_x=ABS_MT_POSITION_X,
        abs_mt_position_y=ABS_MT_POSITION_Y,
        rel_x=REL_X,
        rel_y=REL_Y,
        btn_south=BTN_SOUTH,
        btn_tool_finger=BTN_TOOL_FINGER,
        btn_tool_pen=BTN_TOOL_PEN,
        btn_stylus=BTN_STYLUS,
        joystick_buttons=frozenset(range(BTN_JOYSTICK, BTN_JOYSTICK + 0x10)),
        mouse_buttons=frozenset(range(BTN_MOUSE, BTN_MOUSE + 0x10)),
        mouse_rule_buttons=frozenset(range(BTN_MOUSE, BTN_MOUSE + 0x08)),
        keyboard_block=frozenset(range(1, 32)),
        key_a=KEY_A,
        key_space=KEY_SPACE,
        prop_pointer=INPUT_PROP_POINTER,
        prop_direct=INPUT_PROP_DIRECT,
        prop_accelerometer=INPUT_PROP_ACCELEROMETER,
        virtual_bustype=BUS_VIRTUAL,
        zonapad_virtual_name=ZONAPAD_VIRTUAL_NAME,
        zonapad_virtual_ids=ZONAPAD_VIRTUAL_IDS,
        steam_vendor_id=STEAM_VENDOR_ID,
        steam_name_marker=STEAM_NAME_MARKER,
    )


def identity_policy() -> IdentityPolicy:
    return IdentityPolicy(
        bus_tokens={BUS_USB: "usb", BUS_BLUETOOTH: "bt"},
        bus_connections={BUS_USB: Connection.USB, BUS_BLUETOOTH: Connection.BLUETOOTH},
        mac_pattern=MAC_PATTERN,
        placeholder_pattern=PLACEHOLDER_PATTERN,
        port_bound_bustypes=frozenset({BUS_USB}),
    )


def discovery_policies() -> DiscoveryPolicies:
    return DiscoveryPolicies(gamepad_filter_policy(), identity_policy())


def draft_rules() -> DraftRules:
    return DraftRules(
        left_stick=(ABS_X, ABS_Y),
        right_stick=(ABS_RX, ABS_RY),
        right_stick_fallback=(ABS_Z, ABS_RZ),
        trigger_candidates=((ABS_Z, ABS_RZ), (ABS_BRAKE, ABS_GAS), (ABS_HAT2Y, ABS_HAT2X)),
        digital_trigger_buttons=(BTN_TL2, BTN_TR2),
        positional_buttons=POSITIONAL_BUTTONS,
        non_positional_drivers=NON_POSITIONAL_DRIVERS,
        min_stick_span=2,
    )
