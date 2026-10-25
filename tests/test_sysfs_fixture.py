"""Smoke over the versioned tree ``tests/fixtures/sysfs`` (mount point ``/sys``)."""

from __future__ import annotations

import json
from pathlib import Path

from conftest import IoGuardFactory
from sysfs_builder import build_sysfs, keyboard, xbox_one_s_usb

from zonepad.application.discovery import discover_devices
from zonepad.domain.discovery import DeviceClass
from zonepad.domain.identity import QualifierSource
from zonepad.infrastructure.linux_input_policy import discovery_policies
from zonepad.infrastructure.sysfs import SysfsInputScanner

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "sysfs"


def _word_bits() -> int:
    manifest = json.loads((FIXTURE_ROOT / "zonepad-fixture.json").read_text(encoding="utf-8"))
    return int(manifest["bitmap_word_bits"])


def test_versioned_tree_uses_relative_symlinks() -> None:
    links = [path for path in FIXTURE_ROOT.rglob("*") if path.is_symlink()]

    assert links
    assert all(not path.readlink().is_absolute() for path in links)
    assert all(path.resolve().is_relative_to(FIXTURE_ROOT.resolve()) for path in links)


def test_versioned_tree_discovers_one_xbox_and_hides_the_keyboard(
    forbid_io_outside: IoGuardFactory,
) -> None:
    with forbid_io_outside(FIXTURE_ROOT):
        snapshot = discover_devices(
            SysfsInputScanner(FIXTURE_ROOT, bitmap_word_bits=_word_bits()), discovery_policies()
        )

    (gamepad,) = snapshot.gamepads
    assert gamepad.event_node == "event3"
    assert gamepad.observed.name == "Microsoft X-Box One S pad"
    assert gamepad.identity is not None
    assert gamepad.identity.qualifier_source is QualifierSource.USB_SERIAL
    assert gamepad.stable_id == "usb-045e-02ea-se73b07be4c"
    keyboard_node = snapshot.by_event_node("event1")
    assert keyboard_node is not None
    assert keyboard_node.verdict.device_class is DeviceClass.KEYBOARD


def test_versioned_tree_matches_the_builder(tmp_path: Path) -> None:
    build_sysfs(tmp_path, [xbox_one_s_usb(), keyboard()])

    from_fixture = SysfsInputScanner(FIXTURE_ROOT, bitmap_word_bits=_word_bits()).scan()
    from_builder = SysfsInputScanner(tmp_path, bitmap_word_bits=64).scan()

    assert from_fixture == from_builder
