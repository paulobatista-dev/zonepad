from __future__ import annotations

from pathlib import Path

import pytest
from conftest import IoGuardFactory
from discovery_fakes import FakeAbsInfoReader
from sysfs_builder import (
    GENERIC_4095_ABSINFO,
    XBOX_ONE_ABSINFO,
    build_sysfs,
    generic_bt_z_rz,
    generic_usb_full,
    generic_without_triggers,
    keyboard,
    switch_pro_bt,
    twin_generic_pads,
    xbox_one_s_usb,
)

from zonepad.application.discovery import (
    ResolvedDevice,
    discover_devices,
    fragile_group,
    resolve_device_reference,
)
from zonepad.application.mapping_draft import (
    ABSINFO_PERMISSION_DENIED,
    DraftOutcome,
    build_mapping_record,
    draft_mapping,
    resolve_connection,
)
from zonepad.domain.discovery import absinfo_from_kernel
from zonepad.domain.errors import (
    AmbiguousAxisAssignmentError,
    AmbiguousDeviceError,
    DeviceAccessDeniedError,
    DeviceNotFoundError,
    MappingConflictError,
)
from zonepad.domain.identity import Connection
from zonepad.domain.mapping_draft import InsufficientCapabilities, RangeSource
from zonepad.infrastructure.catalog import LayeredDeviceCatalog, load_builtin_catalog
from zonepad.infrastructure.linux_input_policy import discovery_policies, draft_rules
from zonepad.infrastructure.mapping import dumps_device_mapping, loads_device_mapping
from zonepad.infrastructure.sysfs import SysfsInputScanner

CATALOG = LayeredDeviceCatalog(load_builtin_catalog())
RULES = draft_rules()


def _resolve(root: Path, nodes, reference: str) -> ResolvedDevice:
    build_sysfs(root, nodes)
    snapshot = discover_devices(SysfsInputScanner(root), discovery_policies())
    return resolve_device_reference(reference, snapshot)


def _draft(resolved: ResolvedDevice, reader: FakeAbsInfoReader | None, **kwargs: bool):
    return draft_mapping(resolved, absinfo_reader=reader, catalog=CATALOG, rules=RULES, **kwargs)


def test_xbox_draft_probes_only_the_resolved_node_and_catalog_channels(
    tmp_path: Path, forbid_io_outside: IoGuardFactory
) -> None:
    resolved = _resolve(tmp_path, [xbox_one_s_usb(), keyboard()], "usb-045e-02ea")
    reader = FakeAbsInfoReader({"event3": XBOX_ONE_ABSINFO})

    with forbid_io_outside(tmp_path):
        outcome = _draft(resolved, reader)

    assert isinstance(outcome, DraftOutcome)
    assert reader.calls == [("event3", (0, 1, 2, 3, 4, 5))]
    assert outcome.probed_node == "event3"
    assert outcome.draft.range_source is RangeSource.EVDEV_ABSINFO
    assert outcome.catalog.entry is not None and outcome.catalog.entry.entry_id == "xpad-xboxone"
    assert set(outcome.absinfo) == {0, 1, 2, 3, 4, 5}
    assert resolved.reference_kind == "base"


def test_no_probe_uses_catalog_ranges_without_touching_the_reader(tmp_path: Path) -> None:
    resolved = _resolve(tmp_path, [xbox_one_s_usb()], "event3")

    outcome = _draft(resolved, None)

    assert isinstance(outcome, DraftOutcome)
    assert outcome.probed_node is None
    assert outcome.draft.range_source is RangeSource.CATALOG
    assert outcome.absinfo == {}


def test_no_probe_on_a_generic_device_is_ranges_unavailable(tmp_path: Path) -> None:
    resolved = _resolve(tmp_path, [generic_usb_full()], "event52")

    result = _draft(resolved, None)

    assert isinstance(result, InsufficientCapabilities)
    assert result.reason == "ranges_unavailable"


def test_access_denied_falls_back_to_catalog_ranges_with_a_warning(tmp_path: Path) -> None:
    resolved = _resolve(tmp_path, [xbox_one_s_usb()], "event3")

    outcome = _draft(resolved, FakeAbsInfoReader(denied=frozenset({"event3"})))

    assert isinstance(outcome, DraftOutcome)
    assert outcome.draft.range_source is RangeSource.CATALOG
    assert ABSINFO_PERMISSION_DENIED in outcome.draft.provenance.warnings


def test_access_denied_on_a_generic_device_propagates(tmp_path: Path) -> None:
    resolved = _resolve(tmp_path, [generic_usb_full()], "event52")

    with pytest.raises(DeviceAccessDeniedError):
        _draft(resolved, FakeAbsInfoReader(denied=frozenset({"event52"})))


def test_generic_device_with_absinfo_0_4095(tmp_path: Path) -> None:
    resolved = _resolve(tmp_path, [generic_usb_full()], "event52")

    outcome = _draft(resolved, FakeAbsInfoReader({"event52": GENERIC_4095_ABSINFO}))

    assert isinstance(outcome, DraftOutcome)
    assert outcome.draft.axes["lx"].center == 2048
    assert outcome.draft.buttons == {}
    loads_device_mapping(dumps_device_mapping(outcome.draft))


def test_generic_without_triggers_is_insufficient(tmp_path: Path) -> None:
    resolved = _resolve(tmp_path, [generic_without_triggers()], "event50")

    result = _draft(resolved, FakeAbsInfoReader({"event50": GENERIC_4095_ABSINFO}))

    assert isinstance(result, InsufficientCapabilities)
    assert result.missing_channels == ("lt", "rt")
    assert result.reason == "digital_triggers_only"


def test_switch_pro_is_unsupported(tmp_path: Path) -> None:
    resolved = _resolve(tmp_path, [switch_pro_bt()], "event25")

    result = _draft(resolved, FakeAbsInfoReader({"event25": {}}))

    assert isinstance(result, InsufficientCapabilities)
    assert result.reason == "digital_triggers_only"


def test_case_b_requires_accept_axis_guess(tmp_path: Path) -> None:
    resolved = _resolve(tmp_path, [generic_bt_z_rz()], "event51")
    absinfo = {code: absinfo_from_kernel(0, 0, 255, 0, 0, 0) for code in (0, 1, 2, 5, 9, 10)}
    reader = FakeAbsInfoReader({"event51": absinfo})

    with pytest.raises(AmbiguousAxisAssignmentError) as raised:
        _draft(resolved, reader)
    outcome = _draft(resolved, reader, accept_axis_guess=True)

    assert raised.value.candidates == ("rx=2,ry=5", "lt=10,rt=9")
    assert isinstance(outcome, DraftOutcome)
    assert (outcome.draft.axes["rx"].code, outcome.draft.triggers["lt"].code) == (2, 10)


def test_catalog_range_mismatch_uses_absinfo(tmp_path: Path) -> None:
    resolved = _resolve(tmp_path, [xbox_one_s_usb()], "event3")
    absinfo = dict(XBOX_ONE_ABSINFO)
    absinfo[5] = absinfo_from_kernel(0, 0, 255, 0, 0, 0)

    outcome = _draft(resolved, FakeAbsInfoReader({"event3": absinfo}))

    assert isinstance(outcome, DraftOutcome)
    assert outcome.draft.triggers["rt"].maximum == 255
    assert "catalog_range_mismatch:5" in outcome.draft.provenance.warnings


def test_reference_resolution_errors(tmp_path: Path) -> None:
    build_sysfs(tmp_path, [*twin_generic_pads(), keyboard()])
    snapshot = discover_devices(SysfsInputScanner(tmp_path), discovery_policies())

    with pytest.raises(AmbiguousDeviceError) as raised:
        resolve_device_reference("usb-1209-0009", snapshot)
    assert raised.value.candidates == ("usb-1209-0009-n1", "usb-1209-0009-n2")
    with pytest.raises(DeviceNotFoundError, match="not a selectable gamepad"):
        resolve_device_reference("event1", snapshot)
    for missing in ("event99", "usb-045e-02ea-n1", "usb-ffff-ffff", "../etc"):
        with pytest.raises(DeviceNotFoundError):
            resolve_device_reference(missing, snapshot)
    resolved = resolve_device_reference("usb-1209-0009-n2", snapshot)
    assert resolved.event_node == "event10"
    assert fragile_group(snapshot, resolved.identity) == ("usb-1209-0009-n1", "usb-1209-0009-n2")


def test_connection_override_only_replaces_unknown() -> None:
    assert resolve_connection(Connection.UNKNOWN, Connection.USB) == (Connection.USB, "override")
    assert resolve_connection(Connection.USB, None) == (Connection.USB, "detected")
    assert resolve_connection(Connection.USB, Connection.USB) == (Connection.USB, "detected")
    with pytest.raises(MappingConflictError):
        resolve_connection(Connection.USB, Connection.BLUETOOTH)


def test_mapping_record_carries_override_and_provenance(tmp_path: Path) -> None:
    resolved = _resolve(tmp_path, [xbox_one_s_usb()], "event3")
    outcome = _draft(resolved, FakeAbsInfoReader({"event3": XBOX_ONE_ABSINFO}))
    assert isinstance(outcome, DraftOutcome)

    record = build_mapping_record(
        resolved,
        outcome,
        dumps_device_mapping(outcome.draft),
        connection_override=None,
        created_at="2026-10-25T12:00:00Z",
        app_version="0.1.0",
    )

    assert record.key.stable_id == resolved.identity.stable_id
    assert record.key.connection is Connection.USB
    assert record.connection_source == "detected"
    assert record.range_source == "evdev_absinfo"
