from __future__ import annotations

import json
from dataclasses import replace
from importlib import resources
from pathlib import Path

import pytest
from sysfs_builder import (
    build_sysfs,
    dualsense_bt_nodes,
    generic_without_triggers,
    switch_pro_bt,
    xbox360w_pads,
    xbox_one_s_usb,
)

from zonepad.domain.discovery import ObservedInputDevice
from zonepad.domain.errors import InvalidCatalogError
from zonepad.infrastructure.catalog import (
    LayeredDeviceCatalog,
    load_builtin_catalog,
    load_catalog_file,
    loads_catalog,
)
from zonepad.infrastructure.sysfs import SysfsInputScanner

BUILTIN_TEXT = (
    resources.files("zonepad.infrastructure")
    .joinpath("catalog_data", "families.json")
    .read_text(encoding="utf-8")
)


def _observe(tmp_path: Path, *nodes) -> tuple[ObservedInputDevice, ...]:
    build_sysfs(tmp_path, nodes)
    return SysfsInputScanner(tmp_path).scan()


def test_builtin_catalog_is_package_data_and_loads_strictly() -> None:
    catalog = load_builtin_catalog()

    assert catalog.catalog_version == 1
    assert catalog.source == "builtin"
    assert [entry.entry_id for entry in catalog.entries] == [
        "xpad-xbox360",
        "xpad-xbox360w",
        "xpad-xboxone",
        "playstation-ds4",
        "playstation-dualsense",
        "nintendo-procon",
    ]
    assert not any(entry.verified_on_hardware for entry in catalog.entries)


@pytest.mark.parametrize(
    ("nodes", "entry_id"),
    [
        ((xbox_one_s_usb(),), "xpad-xboxone"),
        (dualsense_bt_nodes()[:1], "playstation-dualsense"),
        ((switch_pro_bt(),), "nintendo-procon"),
        (xbox360w_pads()[:1], "xpad-xbox360w"),
    ],
)
def test_builtin_entries_match_by_driver_and_vid_pid(tmp_path: Path, nodes, entry_id: str) -> None:
    (device,) = _observe(tmp_path, *nodes)

    match = LayeredDeviceCatalog(load_builtin_catalog()).match(device)

    assert match.entry is not None and match.entry.entry_id == entry_id
    assert match.source == "builtin"
    assert match.warnings == ()


@pytest.mark.parametrize(
    ("protocol", "entry_id"),
    [("d0", "xpad-xboxone"), ("01", "xpad-xbox360"), ("81", "xpad-xbox360w")],
)
def test_unknown_xpad_pid_matches_by_interface_protocol(
    tmp_path: Path, protocol: str, entry_id: str
) -> None:
    node = replace(xbox_one_s_usb(), product="beef", parent_attrs={"bInterfaceProtocol": protocol})
    (device,) = _observe(tmp_path, node)

    match = LayeredDeviceCatalog(load_builtin_catalog()).match(device)

    assert match.entry is not None and match.entry.entry_id == entry_id


def test_other_driver_falls_back_to_the_generic_heuristic(tmp_path: Path) -> None:
    (device,) = _observe(tmp_path, generic_without_triggers())

    match = LayeredDeviceCatalog(load_builtin_catalog()).match(device)

    assert match.entry is None
    assert match.source == "generic"
    assert match.catalog_version == 1


def test_driver_must_match_even_with_a_known_vid_pid(tmp_path: Path) -> None:
    node = replace(xbox_one_s_usb(), driver=("usb", "xpadneo"))
    (device,) = _observe(tmp_path, node)

    assert LayeredDeviceCatalog(load_builtin_catalog()).match(device).entry is None


def test_missing_required_abs_discards_the_entry_with_a_warning(tmp_path: Path) -> None:
    node = replace(xbox_one_s_usb(), abs="3001b")  # no ABS_Z/RZ (triggers_to_buttons)
    (device,) = _observe(tmp_path, node)

    match = LayeredDeviceCatalog(load_builtin_catalog()).match(device)

    assert match.entry is None
    assert match.warnings == ("catalog_capability_mismatch",)


def test_user_catalog_overrides_the_builtin(tmp_path: Path) -> None:
    data = json.loads(BUILTIN_TEXT)
    data["families"] = [family for family in data["families"] if family["id"] == "xpad-xboxone"]
    data["families"][0]["id"] = "my-xbox"
    data["families"][0]["known_ranges"]["2"]["maximum"] = 255
    user_file = tmp_path / "user.json"
    user_file.write_text(json.dumps(data), encoding="utf-8")
    (device,) = _observe(tmp_path / "sys", xbox_one_s_usb())

    match = LayeredDeviceCatalog(load_builtin_catalog(), load_catalog_file(user_file)).match(device)

    assert match.entry is not None and match.entry.entry_id == "my-xbox"
    assert match.source == "user"
    assert match.entry.known_ranges[2].maximum == 255


def _mutated(change) -> str:
    data = json.loads(BUILTIN_TEXT)
    change(data)
    return json.dumps(data)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda d: d.update(extra=1), "unknown fields: extra"),
        (lambda d: d.update(catalog_version=2), "catalog_version"),
        (lambda d: d["families"][0].update(shiny=True), "unknown fields: shiny"),
        (lambda d: d["families"][0].pop("layout"), "missing fields: layout"),
        (lambda d: d["families"][0]["match"].update(vid_pid=["045E:028E"]), "vid_pid"),
        (lambda d: d["families"][0]["match"].update(bustype=["3"]), "bustype"),
        (
            lambda d: d["families"][0]["match"].update(
                usb_interface_protocol={"in": [], "not_in": []}
            ),
            "exactly one",
        ),
        (lambda d: d["families"][0]["channels"].update(lz={"code": 9}), "unknown channels"),
        (lambda d: d["families"][0]["channels"].pop("rt"), "all mapping channels"),
        (lambda d: d["families"][0]["buttons"].update({"0x130": "button_south"}), "decimal"),
        (lambda d: d["families"][0]["buttons"].update({"309": "button_start"}), "supported button"),
        (
            lambda d: d["families"][0]["known_ranges"]["0"].update(minimum=40000),
            "minimum < maximum",
        ),
        (lambda d: d["families"][0]["known_ranges"]["0"].update(fuzz=True), "integer"),
        (lambda d: d["families"].append(d["families"][0]), "unique"),
        (lambda d: d["families"][0].update(id="Bad Id"), "id must match"),
        (lambda d: d["families"][0]["center_override"].update(lt=3), "non-stick"),
        (lambda d: d["families"][0].update(required_abs=[0, 1, 2, 3, 4]), "outside required_abs"),
    ],
)
def test_loader_rejects_schema_violations(change, message: str) -> None:
    with pytest.raises(InvalidCatalogError, match=message):
        loads_catalog(_mutated(change), source="user")


def test_loader_rejects_duplicate_fields_and_bad_json() -> None:
    with pytest.raises(InvalidCatalogError, match="duplicate field"):
        loads_catalog('{"catalog_version": 1, "catalog_version": 1, "families": []}', source="user")
    with pytest.raises(InvalidCatalogError, match="invalid catalog JSON"):
        loads_catalog("{", source="user")


def test_missing_user_catalog_is_invalid_catalog(tmp_path: Path) -> None:
    with pytest.raises(InvalidCatalogError, match="catalog not found"):
        load_catalog_file(tmp_path / "absent.json")


def test_xbox360_entry_documents_the_original_xbox_quirk() -> None:
    entry = next(e for e in load_builtin_catalog().entries if e.entry_id == "xpad-xbox360")

    assert "also_matches_original_xbox_by_interface_protocol" in entry.quirks
