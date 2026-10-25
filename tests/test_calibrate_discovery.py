from __future__ import annotations

import json
from argparse import Namespace
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from cli_support import workspace
from discovery_fakes import FakeAbsInfoReader
from synthetic_capture import FIXED_PROFILE_ID, full_session, mapping_payload
from sysfs_builder import XBOX_ONE_ABSINFO, keyboard, twin_generic_pads, xbox_one_s_usb
from test_calibrate_flow import AlwaysYesConsole, FakeBackend, FakeClock, RecorderCapture

from zonepad.application.discovery import discover_devices, resolve_device_reference
from zonepad.application.mapping_draft import DraftOutcome, build_mapping_record, draft_mapping
from zonepad.domain.device import DeviceInfo
from zonepad.infrastructure.capture_reader import read_strict_capture
from zonepad.infrastructure.catalog import LayeredDeviceCatalog, load_builtin_catalog
from zonepad.infrastructure.device_store import JsonDeviceMappingStore
from zonepad.infrastructure.linux_input_policy import discovery_policies, draft_rules
from zonepad.infrastructure.manifest_reader import load_manifest
from zonepad.infrastructure.sysfs import SysfsInputScanner
from zonepad.interface.calibration_cli import run_calibrate

XBOX_ID = "usb-045e-02ea-se73b07be4c"


class ChoosingConsole(AlwaysYesConsole):
    def __init__(self) -> None:
        super().__init__()
        self.choices: list[tuple[str, ...]] = []

    def ask_choice(self, message: str, choices: Sequence[str]) -> int | None:
        self.choices.append(tuple(choices))
        return 0


def _save_synthetic_mapping(sysfs: Path, devices: Path) -> None:
    """Saved provisional mapping whose ranges match the synthetic recorder."""
    snapshot = discover_devices(SysfsInputScanner(sysfs), discovery_policies())
    resolved = resolve_device_reference("event3", snapshot)
    outcome = draft_mapping(
        resolved,
        absinfo_reader=FakeAbsInfoReader({"event3": XBOX_ONE_ABSINFO}),
        catalog=LayeredDeviceCatalog(load_builtin_catalog()),
        rules=draft_rules(),
    )
    assert isinstance(outcome, DraftOutcome)
    record = build_mapping_record(
        resolved,
        outcome,
        json.dumps(mapping_payload(), indent=2) + "\n",
        connection_override=None,
        created_at="2026-10-25T12:00:00Z",
        app_version="0.1.0",
    )
    JsonDeviceMappingStore(devices).save(record, overwrite=False)


def _args(tmp_path: Path, ws, *, device: str | None, mapping: Path | None = None) -> Namespace:
    return Namespace(
        mapping=mapping,
        thresholds=None,
        warmup_seconds=2.0,
        rest_seconds=5.0,
        circle_seconds=6.0,
        trigger_seconds=25.0,
        device=device,
        capture_dir=tmp_path / "captures",
        profiles_dir=tmp_path / "profiles",
        max_retries=2,
        sysfs_root=ws.sysfs,
        devices_dir=ws.devices,
    )


def _calibrate(tmp_path: Path, ws, console, *, device: str | None, mapping: Path | None = None):
    backend = FakeBackend(DeviceInfo("event3", "Synthetic Pad"))
    built: list[object] = []

    def backend_factory(loaded):
        built.append(loaded)
        return backend

    code = run_calibrate(
        _args(tmp_path, ws, device=device, mapping=mapping),
        console=console,
        clock=FakeClock(),
        backend_factory=backend_factory,
        now=lambda: datetime(2026, 10, 25, tzinfo=UTC),
        profile_id_factory=lambda: FIXED_PROFILE_ID,
        capture_factory=lambda session, writer, timer: RecorderCapture(full_session(), writer),
        dependencies=ws.deps(),
    )
    return code, backend, built


def test_calibrate_with_stable_id_uses_saved_mapping_and_keeps_event_node_artifacts(
    tmp_path: Path,
) -> None:
    ws = workspace(tmp_path, [xbox_one_s_usb(), keyboard()])
    _save_synthetic_mapping(ws.sysfs, ws.devices)
    console = AlwaysYesConsole()

    code, backend, built = _calibrate(tmp_path, ws, console, device=XBOX_ID)

    assert code == 0
    assert backend.opened and len(built) == 1
    messages = console.messages
    assert f"Dispositivo: Microsoft X-Box One S pad ({XBOX_ID}, event3)" in messages
    assert "Conexão: usb" in messages
    assert any(m.startswith("Mapping: mapping salvo (provisório)") for m in messages)
    assert any(
        m == f"Próximo comando: zonepad run --device {XBOX_ID} --profile {FIXED_PROFILE_ID}"
        for m in messages
    )
    (session_dir,) = (tmp_path / "captures").iterdir()
    assert "event3" in session_dir.name
    manifest = load_manifest(session_dir / "capture.manifest.json")
    assert manifest.device.device_id == "event3"
    frames = read_strict_capture(session_dir / "capture.jsonl").frames
    assert {frame.device_id for frame in frames} == {"event3"}
    assert XBOX_ID not in (session_dir / "capture.manifest.json").read_text("utf-8")


def test_calibrate_without_device_lists_only_gamepads(tmp_path: Path) -> None:
    ws = workspace(tmp_path, [keyboard(), xbox_one_s_usb()])
    _save_synthetic_mapping(ws.sysfs, ws.devices)
    console = ChoosingConsole()

    code, _, _ = _calibrate(tmp_path, ws, console, device=None)

    assert code == 0
    assert console.choices == [(f"Microsoft X-Box One S pad ({XBOX_ID}, event3)",)]


def test_calibrate_without_saved_mapping_fails_before_building_the_backend(
    tmp_path: Path,
) -> None:
    ws = workspace(tmp_path, [xbox_one_s_usb()])
    console = AlwaysYesConsole()

    code, backend, built = _calibrate(tmp_path, ws, console, device=XBOX_ID)

    assert code == 2
    assert built == [] and not backend.opened
    assert any(f"zonepad mapping draft --device {XBOX_ID}" in m for m in console.messages)


def test_calibrate_unknown_device_exits_3(tmp_path: Path) -> None:
    ws = workspace(tmp_path, [xbox_one_s_usb()])

    code, _, built = _calibrate(tmp_path, ws, AlwaysYesConsole(), device="usb-045e-02ea-n1")

    assert code == 3 and built == []


def test_calibrate_ambiguous_base_exits_2(tmp_path: Path) -> None:
    ws = workspace(tmp_path, twin_generic_pads())

    code, _, built = _calibrate(tmp_path, ws, AlwaysYesConsole(), device="usb-1209-0009")

    assert code == 2 and built == []


def test_calibrate_without_gamepads_exits_3(tmp_path: Path) -> None:
    ws = workspace(tmp_path, [keyboard()])

    code, _, _ = _calibrate(tmp_path, ws, ChoosingConsole(), device=None)

    assert code == 3


def test_explicit_mapping_with_stable_id_wins_and_is_shown(tmp_path: Path) -> None:
    ws = workspace(tmp_path, [xbox_one_s_usb()])
    explicit = tmp_path / "explicit.json"
    explicit.write_text(json.dumps(mapping_payload()), encoding="utf-8")
    console = AlwaysYesConsole()

    code, _, _ = _calibrate(tmp_path, ws, console, device=XBOX_ID, mapping=explicit)

    assert code == 0
    assert f"Mapping: --mapping {explicit}" in console.messages
    assert any(
        m.endswith(f"--profile {FIXED_PROFILE_ID} --mapping {explicit}")
        and f"--device {XBOX_ID}" in m
        for m in console.messages
    )


def test_node_reassigned_after_open_exits_3(tmp_path: Path) -> None:
    ws = workspace(tmp_path, [xbox_one_s_usb()])
    _save_synthetic_mapping(ws.sysfs, ws.devices)

    class Reassigned(SysfsInputScanner):
        def observe(self, event_node: str):
            device = super().observe(event_node)
            assert device is not None
            return replace(device, input_token="input99")

    console = AlwaysYesConsole()
    backend = FakeBackend(DeviceInfo("event3", "Synthetic Pad"))
    code = run_calibrate(
        _args(tmp_path, ws, device=XBOX_ID),
        console=console,
        clock=FakeClock(),
        backend_factory=lambda mapping: backend,
        dependencies=ws.deps(scanner=lambda root: Reassigned(root)),
    )

    assert code == 3
    assert backend.session is not None and backend.session.closed
