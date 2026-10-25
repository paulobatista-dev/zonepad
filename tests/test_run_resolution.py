from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field, replace
from pathlib import Path

import pytest
from cli_support import Workspace, workspace
from conftest import IoGuardFactory
from sysfs_builder import XBOX_ONE_ABSINFO, twin_generic_pads, xbox_one_s_usb

from zonepad.domain.device import DeviceInfo
from zonepad.domain.discovery import absinfo_from_kernel
from zonepad.domain.profile import (
    CalibrationProfile,
    DeviceIdentity,
    StickCalibration,
    TriggerCalibration,
)
from zonepad.infrastructure.fake import FakeBackend, FakeSession
from zonepad.infrastructure.json_profile_store import JsonProfileStore
from zonepad.infrastructure.mapping import DeviceMapping, load_device_mapping
from zonepad.infrastructure.sysfs import SysfsInputScanner
from zonepad.interface import cli

XBOX_ID = "usb-045e-02ea-se73b07be4c"


@dataclass
class RecordingBackend:
    mapping: DeviceMapping
    opened: list[str] = field(default_factory=list)
    sessions: list[FakeSession] = field(default_factory=list)

    def list_devices(self) -> tuple[DeviceInfo, ...]:
        raise AssertionError("run never lists devices")

    def open(self, device_id: str) -> FakeSession:
        self.opened.append(device_id)
        session = FakeSession(
            DeviceInfo(device_id, device_id),
            [],
            disconnect_after=True,
            normalization_config=self.mapping,
        )
        self.sessions.append(session)
        return session


@dataclass
class RecordingPublisher:
    closed: bool = False

    def publish(self, frame: object) -> None:
        pass

    def close(self) -> None:
        self.closed = True


@dataclass
class Harness:
    ws: Workspace
    profile_id: str
    backends: list[RecordingBackend] = field(default_factory=list)
    publishers: list[RecordingPublisher] = field(default_factory=list)

    def deps(self, **overrides: object):
        def backend(mapping: DeviceMapping) -> RecordingBackend:
            created = RecordingBackend(mapping)
            self.backends.append(created)
            return created

        def publisher(path: Path | None) -> RecordingPublisher:
            created = RecordingPublisher()
            self.publishers.append(created)
            return created

        return self.ws.deps(backend=backend, publisher=publisher, **overrides)

    def run(self, *extra: str, **overrides: object) -> int:
        argv = [
            "run",
            "--profile",
            self.profile_id,
            "--profiles-dir",
            str(self.ws.root / "profiles"),
            *self.ws.paths(),
            *extra,
        ]
        return cli.main(argv, dependencies=self.deps(**overrides))


def _harness(tmp_path: Path, nodes=None, *, draft: bool = True, no_probe: bool = False) -> Harness:
    ws = workspace(tmp_path, nodes or [xbox_one_s_usb()])
    ws.absinfo["event3"] = XBOX_ONE_ABSINFO
    profile = CalibrationProfile(
        1,
        str(uuid.uuid4()),
        DeviceIdentity("Pad", "0x045e", "0x02ea"),
        {"left": StickCalibration(), "right": StickCalibration()},
        {"left": TriggerCalibration(), "right": TriggerCalibration()},
        "2026-10-25T00:00:00Z",
        "0.1.0",
    )
    JsonProfileStore(tmp_path / "profiles").save(profile)
    if draft:
        args = ["mapping", "draft", "--device", "event3", *ws.paths()]
        assert cli.main([*args, "--no-probe"] if no_probe else args, dependencies=ws.deps()) == 0
    return Harness(ws, profile.profile_id)


def test_run_with_stable_id_uses_the_saved_mapping_like_an_explicit_one(
    tmp_path: Path, forbid_io_outside: IoGuardFactory
) -> None:
    harness = _harness(tmp_path)
    saved_path = harness.ws.devices / XBOX_ID / "mapping.json"
    explicit = tmp_path / "explicit.json"
    explicit.write_text(saved_path.read_text("utf-8"), encoding="utf-8")

    with forbid_io_outside(tmp_path):
        assert harness.run("--device", XBOX_ID) == 0
    assert harness.run("--device", "event3", "--mapping", str(explicit)) == 0

    saved_run, legacy_run = harness.backends
    assert saved_run.opened == legacy_run.opened == ["event3"]
    assert saved_run.mapping == legacy_run.mapping == load_device_mapping(explicit)
    assert harness.publishers[0].closed
    assert saved_run.sessions[0].device_info.device_id == "event3"


def test_run_logs_resolution_and_provisional_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    harness = _harness(tmp_path)

    with caplog.at_level(logging.INFO, logger="zonepad.cli"):
        assert harness.run("--device", "usb-045e-02ea") == 0

    text = caplog.text
    assert f"device resolved stable_id={XBOX_ID} node=event3 reference=base" in text
    assert "mapping resolved source=saved" in text and "provisional=true" in text
    assert "mapping_provisional" in text
    record = next(r for r in caplog.records if r.getMessage().startswith("device resolved"))
    assert record.stable_id == XBOX_ID  # type: ignore[attr-defined]


def test_explicit_mapping_overrides_saved_and_logs_divergence(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    harness = _harness(tmp_path)
    payload = json.loads((harness.ws.devices / XBOX_ID / "mapping.json").read_text("utf-8"))
    payload["axes"]["lx"]["center"] = 5
    explicit = tmp_path / "explicit.json"
    explicit.write_text(json.dumps(payload), encoding="utf-8")

    with caplog.at_level(logging.INFO, logger="zonepad.cli"):
        assert harness.run("--device", XBOX_ID, "--mapping", str(explicit)) == 0

    assert harness.backends[0].mapping.axes["lx"].center == 5
    assert "explicit mapping overrides saved mapping" in caplog.text
    assert "same=false" in caplog.text


def test_invalid_explicit_mapping_never_falls_back(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    harness = _harness(tmp_path)
    broken = tmp_path / "broken.json"
    broken.write_text("{", encoding="utf-8")

    assert harness.run("--device", XBOX_ID, "--mapping", str(broken)) == 2
    assert harness.backends == []
    assert "invalid mapping JSON" in capsys.readouterr().out


def test_missing_saved_mapping_exits_2_with_draft_hint(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    harness = _harness(tmp_path, draft=False)

    assert harness.run("--device", XBOX_ID) == 2
    assert f"zonepad mapping draft --device {XBOX_ID}" in capsys.readouterr().out
    assert harness.backends == []


def test_invalid_saved_mapping_exits_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    harness = _harness(tmp_path)
    (harness.ws.devices / XBOX_ID / "mapping.json").write_text("{}", encoding="utf-8")

    assert harness.run("--device", XBOX_ID) == 2
    assert "mapping salvo inválido" in capsys.readouterr().out


def test_unknown_device_exits_3(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    harness = _harness(tmp_path)

    assert harness.run("--device", "usb-045e-02ea-n1") == 3
    assert "zonepad devices" in capsys.readouterr().out


def test_legacy_missing_node_now_exits_3(tmp_path: Path) -> None:
    harness = _harness(tmp_path, draft=False)
    explicit = tmp_path / "explicit.json"
    explicit.write_text(json.dumps(_mapping_payload()), encoding="utf-8")

    def missing_backend(mapping: DeviceMapping) -> FakeBackend:
        return FakeBackend([], mapping)

    code = cli.main(
        [
            "run",
            "--device",
            "event9",
            "--profile",
            harness.profile_id,
            "--profiles-dir",
            str(tmp_path / "profiles"),
            "--mapping",
            str(explicit),
        ],
        dependencies=harness.ws.deps(
            backend=missing_backend, publisher=lambda p: RecordingPublisher()
        ),
    )

    assert code == 3


def _mapping_payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "axes": {
            name: {"code": code, "minimum": -100, "center": 0, "maximum": 100}
            for name, code in (("lx", 0), ("ly", 1), ("rx", 3), ("ry", 4))
        },
        "triggers": {
            name: {"code": code, "rest": 0, "maximum": 100} for name, code in (("lt", 2), ("rt", 5))
        },
    }


def test_legacy_path_never_touches_sysfs_or_store(tmp_path: Path) -> None:
    harness = _harness(tmp_path, draft=False)
    explicit = tmp_path / "explicit.json"
    explicit.write_text(json.dumps(_mapping_payload()), encoding="utf-8")

    def no_scanner(root: Path):
        raise AssertionError("legacy run must not scan sysfs")

    def no_store(directory: Path):
        raise AssertionError("legacy run must not open the store")

    code = harness.run(
        "--device", "event3", "--mapping", str(explicit), scanner=no_scanner, store=no_store
    )

    assert code == 0
    assert harness.backends[0].opened == ["event3"]


def test_node_reassigned_after_open_exits_3_and_closes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    harness = _harness(tmp_path)

    class ReassignedScanner(SysfsInputScanner):
        def observe(self, event_node: str):
            device = super().observe(event_node)
            assert device is not None
            return replace(device, input_token="input99")

    assert harness.run("--device", XBOX_ID, scanner=lambda root: ReassignedScanner(root)) == 3
    assert "mudou entre a descoberta e a abertura" in capsys.readouterr().out
    assert harness.backends[0].sessions[0].closed
    assert harness.publishers[0].closed


def test_catalog_ranges_are_rechecked_and_mismatch_only_warns(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    harness = _harness(tmp_path, no_probe=True)
    divergent = dict(XBOX_ONE_ABSINFO)
    divergent[2] = absinfo_from_kernel(0, 0, 255, 0, 0, 0)
    harness.ws.absinfo["event3"] = divergent

    with caplog.at_level(logging.WARNING, logger="zonepad.cli"):
        assert harness.run("--device", XBOX_ID) == 0

    assert "absinfo_mismatch:lt" in caplog.text
    assert "absinfo_mismatch:rt" not in caplog.text
    assert harness.ws.reader is not None
    assert harness.ws.reader.calls[0][0] == "event3"


def test_absinfo_ranges_are_not_rechecked(tmp_path: Path) -> None:
    harness = _harness(tmp_path)

    assert harness.run("--device", XBOX_ID) == 0
    assert harness.ws.reader is not None and harness.ws.reader.calls == []


def test_recheck_with_denied_access_is_silent(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    harness = _harness(tmp_path, no_probe=True)
    harness.ws.denied.add("event3")

    with caplog.at_level(logging.WARNING, logger="zonepad.cli"):
        assert harness.run("--device", XBOX_ID) == 0
    assert "absinfo_mismatch" not in caplog.text


def test_ambiguous_base_exits_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    harness = _harness(tmp_path, twin_generic_pads(), draft=False)

    assert harness.run("--device", "usb-1209-0009") == 2
    assert "usb-1209-0009-n1, usb-1209-0009-n2" in capsys.readouterr().out
