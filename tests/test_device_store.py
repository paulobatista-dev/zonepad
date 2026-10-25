from __future__ import annotations

import json
import logging
import stat
from dataclasses import replace
from pathlib import Path

import pytest
from discovery_fakes import FakeAbsInfoReader
from sysfs_builder import (
    GENERIC_4095_ABSINFO,
    XBOX_ONE_ABSINFO,
    build_sysfs,
    generic_usb_full,
    xbox_one_s_usb,
)

from zonepad.application.discovery import discover_devices, resolve_device_reference
from zonepad.application.mapping_draft import DraftOutcome, build_mapping_record, draft_mapping
from zonepad.application.mapping_resolution import MappingSource, resolve_mapping
from zonepad.application.ports import MappingRecord
from zonepad.domain.errors import InvalidMappingError, MappingConflictError
from zonepad.domain.identity import Connection, MappingKey, StableId
from zonepad.infrastructure.catalog import LayeredDeviceCatalog, load_builtin_catalog
from zonepad.infrastructure.device_store import (
    IDENTITY_FILE,
    INDEX_FILE,
    MAPPING_FILE,
    JsonDeviceMappingStore,
)
from zonepad.infrastructure.files import sha256_bytes, write_text_atomic
from zonepad.infrastructure.linux_input_policy import discovery_policies, draft_rules
from zonepad.infrastructure.mapping import (
    dumps_device_mapping,
    load_device_mapping,
    loads_device_mapping,
)
from zonepad.infrastructure.sysfs import SysfsInputScanner

CREATED_AT = "2026-10-25T12:00:00Z"


def _record(tmp_path: Path, node=None) -> MappingRecord:
    root = tmp_path / "sys"
    build_sysfs(root, [node or xbox_one_s_usb()])
    snapshot = discover_devices(SysfsInputScanner(root), discovery_policies())
    resolved = resolve_device_reference("event3", snapshot)
    outcome = draft_mapping(
        resolved,
        absinfo_reader=FakeAbsInfoReader({"event3": XBOX_ONE_ABSINFO}),
        catalog=LayeredDeviceCatalog(load_builtin_catalog()),
        rules=draft_rules(),
    )
    assert isinstance(outcome, DraftOutcome)
    return build_mapping_record(
        resolved,
        outcome,
        dumps_device_mapping(outcome.draft),
        connection_override=None,
        created_at=CREATED_AT,
        app_version="0.1.0",
    )


def _key(record: MappingRecord, connection: Connection = Connection.USB) -> MappingKey:
    return MappingKey(record.key.stable_id, connection)


def test_draft_text_is_deterministic_and_accepted_by_the_v1_parser(tmp_path: Path) -> None:
    first = _record(tmp_path / "a")
    second = _record(tmp_path / "b")

    assert first.mapping_text == second.mapping_text
    mapping = loads_device_mapping(first.mapping_text)
    assert mapping.axis_codes == {0: "lx", 1: "ly", 3: "rx", 4: "ry"}
    assert mapping.trigger_codes == {2: "lt", 5: "rt"}
    assert mapping.button_codes == {
        304: "button_south",
        305: "button_east",
        307: "button_north",
        308: "button_west",
    }
    payload = json.loads(first.mapping_text)
    assert payload["axes"]["lx"] == {"code": 0, "minimum": -32768, "center": 0, "maximum": 32767}
    assert payload["triggers"]["lt"] == {"code": 2, "rest": 0, "maximum": 1023}
    assert first.mapping_text.endswith("}\n")


def test_save_writes_layout_with_private_directories(tmp_path: Path) -> None:
    record = _record(tmp_path)
    store = JsonDeviceMappingStore(tmp_path / "devices")

    ref = store.save(record, overwrite=False)

    device_dir = tmp_path / "devices" / record.key.stable_id
    assert sorted(path.name for path in device_dir.iterdir()) == [IDENTITY_FILE, MAPPING_FILE]
    assert (tmp_path / "devices" / INDEX_FILE).is_file()
    for directory in (tmp_path / "devices", device_dir):
        assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    assert (device_dir / MAPPING_FILE).read_text(encoding="utf-8") == record.mapping_text
    assert ref.status == "provisional"
    assert ref.mapping_sha256 == ref.recorded_sha256 == sha256_bytes(record.mapping_text.encode())
    assert ref.range_source == "evdev_absinfo"
    assert ref.recorded_device_version == 0x0408
    assert load_device_mapping(Path(ref.mapping_path)) == loads_device_mapping(record.mapping_text)


def test_identity_sidecar_records_provenance_and_raw_facts(tmp_path: Path) -> None:
    record = _record(tmp_path)
    store = JsonDeviceMappingStore(tmp_path / "devices")
    store.save(record, overwrite=False)

    identity = json.loads(
        (tmp_path / "devices" / record.key.stable_id / IDENTITY_FILE).read_text(encoding="utf-8")
    )

    assert identity["schema_version"] == 1
    assert identity["stable_id"] == record.key.stable_id
    assert identity["connection"] == "usb"
    assert identity["connection_source"] == "detected"
    assert identity["hardware"] == {
        "bustype": "0x0003",
        "vendor_id": "0x045e",
        "product_id": "0x02ea",
        "device_version": "0x0408",
        "firmware": None,
        "driver": "xpad",
        "name": "Microsoft X-Box One S pad",
        "uniq": None,
        "usb_serial": "SYNTH0001",
        "phys": "usb-0000:00:14.0-2/input0",
    }
    assert identity["identity"] == {
        "qualifier_source": "usb_serial",
        "occurrence": None,
        "fragile": False,
    }
    draft = identity["draft"]
    assert draft["catalog_entry_id"] == "xpad-xboxone"
    assert draft["catalog_source"] == "builtin"
    assert draft["range_source"] == "evdev_absinfo"
    assert draft["provisional"] is True
    assert draft["provisional_fields"][0] == "axes.lx.center"
    assert draft["absinfo"]["0"] == {
        "minimum": -32768,
        "maximum": 32767,
        "fuzz": 16,
        "flat": 128,
        "resolution": 0,
        "value_at_probe": 0,
    }
    assert draft["warnings"] == ["provisional_center"]
    assert identity["mapping_file"] == "mapping.json"
    assert identity["created_at"] == CREATED_AT


def test_saving_twice_produces_identical_bytes(tmp_path: Path) -> None:
    record = _record(tmp_path)
    first = JsonDeviceMappingStore(tmp_path / "one")
    second = JsonDeviceMappingStore(tmp_path / "two")
    first.save(record, overwrite=False)
    second.save(record, overwrite=False)

    for name in (MAPPING_FILE, IDENTITY_FILE):
        left = (tmp_path / "one" / record.key.stable_id / name).read_bytes()
        right = (tmp_path / "two" / record.key.stable_id / name).read_bytes()
        assert left == right
    assert (tmp_path / "one" / INDEX_FILE).read_bytes() == (
        tmp_path / "two" / INDEX_FILE
    ).read_bytes()


def test_existing_mapping_requires_overwrite(tmp_path: Path) -> None:
    record = _record(tmp_path)
    store = JsonDeviceMappingStore(tmp_path / "devices")
    store.save(record, overwrite=False)

    with pytest.raises(MappingConflictError, match="already exists"):
        store.save(record, overwrite=False)
    assert store.save(record, overwrite=True).status == "provisional"


def test_writes_go_mapping_then_identity_then_index(tmp_path: Path) -> None:
    record = _record(tmp_path)
    written: list[str] = []

    def recording_writer(path: Path, text: str) -> None:
        written.append(path.name)
        write_text_atomic(path, text)

    JsonDeviceMappingStore(tmp_path / "devices", write_text=recording_writer).save(
        record, overwrite=False
    )

    assert written == [MAPPING_FILE, IDENTITY_FILE, INDEX_FILE]


def test_invalid_mapping_text_is_rejected_before_writing(tmp_path: Path) -> None:
    record = _record(tmp_path)
    broken = MappingRecord(**{**_fields(record), "mapping_text": '{"schema_version": 2}'})

    with pytest.raises(InvalidMappingError):
        JsonDeviceMappingStore(tmp_path / "devices").save(broken, overwrite=False)
    assert not (tmp_path / "devices").exists()


def _fields(record: MappingRecord) -> dict[str, object]:
    return {name: getattr(record, name) for name in record.__dataclass_fields__}


def test_find_returns_none_for_unknown_ids(tmp_path: Path) -> None:
    store = JsonDeviceMappingStore(tmp_path / "devices")

    assert store.find(MappingKey(StableId("usb-045e-02ea-n1"), Connection.USB)) is None
    assert store.entries() == ()


@pytest.mark.parametrize("stable_id", ["../x", "usb-045e-02ea-n1/..", "USB-045E-02EA-N1"])
def test_find_rejects_malicious_ids(tmp_path: Path, stable_id: str) -> None:
    store = JsonDeviceMappingStore(tmp_path / "devices")

    with pytest.raises(ValueError):
        store.find(MappingKey(StableId(stable_id), Connection.USB))


def test_edited_mapping_has_status_edited(tmp_path: Path) -> None:
    record = _record(tmp_path)
    store = JsonDeviceMappingStore(tmp_path / "devices")
    ref = store.save(record, overwrite=False)
    edited = record.mapping_text.replace('"center": 0', '"center": 10', 1)
    Path(ref.mapping_path).write_text(edited, encoding="utf-8")

    found = store.find(_key(record))

    assert found is not None
    assert found.status == "edited"
    assert found.mapping_sha256 == sha256_bytes(edited.encode())
    assert found.recorded_sha256 == ref.recorded_sha256


def test_mapping_failing_the_parser_is_invalid_with_the_field(tmp_path: Path) -> None:
    record = _record(tmp_path)
    store = JsonDeviceMappingStore(tmp_path / "devices")
    ref = store.save(record, overwrite=False)
    payload = json.loads(record.mapping_text)
    payload["axes"]["lx"]["extra"] = 1
    Path(ref.mapping_path).write_text(json.dumps(payload), encoding="utf-8")

    found = store.find(_key(record))

    assert found is not None and found.status == "invalid"
    assert found.detail is not None and "mapping.axes.lx has unknown fields: extra" in found.detail


def test_mapping_without_identity_is_invalid(tmp_path: Path) -> None:
    record = _record(tmp_path)
    store = JsonDeviceMappingStore(tmp_path / "devices")
    store.save(record, overwrite=False)
    (tmp_path / "devices" / record.key.stable_id / IDENTITY_FILE).unlink()

    found = store.find(_key(record))

    assert found is not None
    assert (found.status, found.detail) == ("invalid", "identity_missing")


@pytest.mark.parametrize(
    "mutation",
    [
        lambda d: d.update(stable_id="usb-045e-02ea-n1"),
        lambda d: d.update(mapping_file="../../etc/passwd"),
        lambda d: d.update(unexpected=True),
        lambda d: d["hardware"].update(bustype="3"),
        lambda d: d["draft"].update(range_source="sysfs"),
        lambda d: d.update(mapping_sha256="XYZ"),
    ],
)
def test_strict_identity_validation_marks_entry_invalid(tmp_path: Path, mutation) -> None:
    record = _record(tmp_path)
    store = JsonDeviceMappingStore(tmp_path / "devices")
    store.save(record, overwrite=False)
    path = tmp_path / "devices" / record.key.stable_id / IDENTITY_FILE
    data = json.loads(path.read_text(encoding="utf-8"))
    mutation(data)
    path.write_text(json.dumps(data), encoding="utf-8")

    found = store.find(_key(record))

    assert found is not None and found.status == "invalid"
    assert found.detail is not None and found.detail.startswith("identity.json:")


def test_one_invalid_entry_does_not_hide_the_others(tmp_path: Path) -> None:
    record = _record(tmp_path)
    store = JsonDeviceMappingStore(tmp_path / "devices")
    store.save(record, overwrite=False)
    other = tmp_path / "devices" / "usb-1209-0001-n1"
    other.mkdir()
    (other / MAPPING_FILE).write_text("{", encoding="utf-8")

    entries = store.entries()

    assert [(ref.key.stable_id, ref.status) for ref in entries] == [
        (record.key.stable_id, "provisional"),
        ("usb-1209-0001-n1", "invalid"),
    ]


@pytest.mark.parametrize("problem", ["missing", "corrupted", "orphan", "divergent_sha"])
def test_stale_index_is_rebuilt_in_memory_without_rewriting(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, problem: str
) -> None:
    record = _record(tmp_path)
    directory = tmp_path / "devices"
    store = JsonDeviceMappingStore(directory)
    store.save(record, overwrite=False)
    index = directory / INDEX_FILE
    if problem == "missing":
        index.unlink()
    elif problem == "corrupted":
        index.write_text("not json", encoding="utf-8")
    elif problem == "orphan":
        data = json.loads(index.read_text(encoding="utf-8"))
        data["entries"].append({**data["entries"][0], "stable_id": "usb-1209-0001-n1"})
        index.write_text(json.dumps(data), encoding="utf-8")
    else:
        data = json.loads(index.read_text(encoding="utf-8"))
        data["entries"][0]["mapping_sha256"] = "0" * 64
        index.write_text(json.dumps(data), encoding="utf-8")
    before = index.read_bytes() if index.exists() else None

    with caplog.at_level(logging.WARNING, logger="zonepad.device_store"):
        entries = store.entries()

    assert [ref.key.stable_id for ref in entries] == [record.key.stable_id]
    assert "device index rebuilt" in caplog.text
    assert (index.read_bytes() if index.exists() else None) == before


def test_consistent_index_logs_nothing(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    record = _record(tmp_path)
    store = JsonDeviceMappingStore(tmp_path / "devices")
    store.save(record, overwrite=False)

    with caplog.at_level(logging.WARNING, logger="zonepad.device_store"):
        store.entries()

    assert "device index rebuilt" not in caplog.text


def test_rebuild_ignores_directories_outside_the_id_grammar(tmp_path: Path) -> None:
    record = _record(tmp_path)
    store = JsonDeviceMappingStore(tmp_path / "devices")
    store.save(record, overwrite=False)
    (tmp_path / "devices" / "not-an-id").mkdir()
    (tmp_path / "devices" / "not-an-id" / MAPPING_FILE).write_text("{}", encoding="utf-8")

    assert [ref.key.stable_id for ref in store.entries()] == [record.key.stable_id]


def test_index_lists_entries_sorted_by_stable_id(tmp_path: Path) -> None:
    record = _record(tmp_path)
    store = JsonDeviceMappingStore(tmp_path / "devices")
    store.save(record, overwrite=False)

    index = json.loads((tmp_path / "devices" / INDEX_FILE).read_text(encoding="utf-8"))

    assert index == {
        "schema_version": 1,
        "entries": [
            {
                "stable_id": record.key.stable_id,
                "connection": "usb",
                "mapping_sha256": sha256_bytes(record.mapping_text.encode()),
                "provisional": True,
                "fragile": False,
                "updated_at": CREATED_AT,
            }
        ],
    }


def test_connection_override_on_unknown_bus_is_found_by_resolution(tmp_path: Path) -> None:
    root = tmp_path / "sys"
    build_sysfs(root, [replace(generic_usb_full("event3"), bustype="0019")])
    snapshot = discover_devices(SysfsInputScanner(root), discovery_policies())
    resolved = resolve_device_reference("event3", snapshot)
    assert resolved.identity.connection is Connection.UNKNOWN
    outcome = draft_mapping(
        resolved,
        absinfo_reader=FakeAbsInfoReader({"event3": GENERIC_4095_ABSINFO}),
        catalog=LayeredDeviceCatalog(load_builtin_catalog()),
        rules=draft_rules(),
    )
    assert isinstance(outcome, DraftOutcome)
    record = build_mapping_record(
        resolved,
        outcome,
        dumps_device_mapping(outcome.draft),
        connection_override=Connection.USB,
        created_at=CREATED_AT,
        app_version="0.1.0",
    )
    store = JsonDeviceMappingStore(tmp_path / "devices")
    store.save(record, overwrite=False)

    identity_path = tmp_path / "devices" / resolved.identity.stable_id / IDENTITY_FILE
    sidecar = json.loads(identity_path.read_text(encoding="utf-8"))
    ref = resolve_mapping(None, resolved.identity, store, sha256_of=lambda path: "")

    assert resolved.identity.stable_id.startswith("bus0019-1209-0002-")
    assert (sidecar["connection"], sidecar["connection_source"]) == ("usb", "override")
    assert ref.source is MappingSource.SAVED
