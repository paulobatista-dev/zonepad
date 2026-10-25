from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from zonepad.application.runtime import RuntimeProcessor, build_runtime
from zonepad.domain.device import DeviceInfo
from zonepad.domain.errors import DeviceDisconnectedError, DeviceNotFoundError, InvalidMappingError
from zonepad.domain.input import RawFrame
from zonepad.domain.normalization import AxisRange, TriggerRange
from zonepad.domain.profile import (
    CalibrationProfile,
    DeviceIdentity,
    StickCalibration,
    TriggerCalibration,
)
from zonepad.infrastructure.evdev import (
    EV_ABS,
    EV_KEY,
    EV_SYN,
    EVENT_STRUCT,
    SYN_REPORT,
    EvdevSession,
)
from zonepad.infrastructure.fake import FakeBackend, FakeSession
from zonepad.infrastructure.mapping import DeviceMapping, load_device_mapping
from zonepad.infrastructure.uinput import LinuxUinputPublisher
from zonepad.interface import cli


class InMemoryStore:
    def __init__(self, profile: CalibrationProfile) -> None:
        self.profile = profile

    def load(self, profile_id: str) -> CalibrationProfile:
        if profile_id != self.profile.profile_id:
            raise ValueError(f"profile not found: {profile_id}")
        return self.profile

    def save(self, profile: CalibrationProfile) -> None:
        self.profile = profile


class Publisher:
    def __init__(self) -> None:
        self.frames = []
        self.closed = False

    def publish(self, frame: object) -> None:
        self.frames.append(frame)

    def close(self) -> None:
        self.closed = True


def make_profile() -> CalibrationProfile:
    return CalibrationProfile(
        1,
        str(uuid.uuid4()),
        DeviceIdentity("Pad", "0x0001", "0x0002"),
        {"left": StickCalibration(), "right": StickCalibration()},
        {"left": TriggerCalibration(), "right": TriggerCalibration()},
        "2026-10-24T00:00:00Z",
        "0.1.0",
    )


def make_mapping() -> DeviceMapping:
    return DeviceMapping(
        {
            "lx": AxisRange(-100, 0, 100),
            "ly": AxisRange(-100, 0, 100),
            "rx": AxisRange(-100, 0, 100),
            "ry": AxisRange(-100, 0, 100),
        },
        {"lt": TriggerRange(0, 100), "rt": TriggerRange(0, 100)},
        {0: "lx", 1: "ly", 3: "rx", 4: "ry"},
        {2: "lt", 5: "rt"},
        {304: "button_south", 305: "button_east"},
    )


def mapping_payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "axes": {
            name: {"code": code, "minimum": -100, "center": 0, "maximum": 100}
            for name, code in (("lx", 0), ("ly", 1), ("rx", 3), ("ry", 4))
        },
        "triggers": {
            name: {"code": code, "rest": 0, "maximum": 100} for name, code in (("lt", 2), ("rt", 5))
        },
        "buttons": {"304": "button_south", "305": "button_east"},
    }


def test_mapping_loads_ranges_codes_and_buttons(tmp_path: Path) -> None:
    path = tmp_path / "pad.json"
    path.write_text(json.dumps(mapping_payload()), encoding="utf-8")

    mapping = load_device_mapping(path)

    assert mapping.axis_codes == {0: "lx", 1: "ly", 3: "rx", 4: "ry"}
    assert mapping.trigger_codes == {2: "lt", 5: "rt"}
    assert mapping.button_codes == {304: "button_south", 305: "button_east"}
    assert mapping.axes["lx"] == AxisRange(-100, 0, 100)
    assert mapping.triggers["lt"] == TriggerRange(0, 100)


def test_mapping_rejects_unknown_fields_and_duplicate_codes(tmp_path: Path) -> None:
    payload = mapping_payload()
    payload["unexpected"] = True
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(InvalidMappingError, match="unknown fields"):
        load_device_mapping(path)

    payload = mapping_payload()
    axes = payload["axes"]
    assert isinstance(axes, dict)
    axes["ly"]["code"] = 0
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(InvalidMappingError, match="unique"):
        load_device_mapping(path)


def test_build_runtime_processes_mapping_ranges_and_closes_after_duration() -> None:
    info = DeviceInfo("pad", "Pad")
    backend = FakeBackend(
        [
            (
                info,
                [
                    RawFrame(
                        "pad",
                        1,
                        {"lx": -100, "ly": 0, "rx": 100, "ry": 0},
                        {"lt": 50, "rt": 100},
                        frozenset({"button_south"}),
                    )
                ],
            )
        ],
        normalization_config=make_mapping(),
    )
    publisher = Publisher()
    store = InMemoryStore(make_profile())
    runtime = build_runtime(backend, store, publisher, "pad", store.profile.profile_id, 0.05)
    ticks = iter((0.0, 0.0, 1.0))
    runtime.run(0.05, duration_s=0.5, monotonic=lambda: next(ticks))

    assert len(publisher.frames) == 1
    frame = publisher.frames[0]
    assert frame.axes["lx"] == pytest.approx(-1.0)
    assert frame.triggers["lt"] == pytest.approx(0.5)
    assert frame.buttons == frozenset({"button_south"})
    assert publisher.closed


def test_build_runtime_reports_missing_device_without_hardware() -> None:
    publisher = Publisher()
    store = InMemoryStore(make_profile())
    with pytest.raises(DeviceNotFoundError):
        build_runtime(
            FakeBackend([], make_mapping()),
            store,
            publisher,
            "missing",
            store.profile.profile_id,
            0.05,
        )
    assert publisher.closed


def test_runtime_closes_ports_on_disconnect() -> None:
    info = DeviceInfo("pad", "Pad")
    session = FakeSession(info, [], disconnect_after=True, normalization_config=make_mapping())
    publisher = Publisher()
    runtime = RuntimeProcessor(
        session,
        make_profile(),
        publisher,
        make_mapping().axes,
        make_mapping().triggers,
    )

    with pytest.raises(DeviceDisconnectedError, match="pad"):
        runtime.run()

    assert session.closed
    assert publisher.closed


def test_evdev_mapping_emits_a_single_frame_on_syn_report() -> None:
    session = object.__new__(EvdevSession)
    session._device_info = DeviceInfo("pad", "Pad")
    session._mapping = make_mapping()
    session._axes = {}
    session._triggers = {}
    session._buttons = set()

    assert session._apply_event(1, 1, EV_ABS, 0, -20) is None
    assert session._apply_event(1, 2, EV_KEY, 304, 1) is None
    frame = session._apply_event(1, 3, EV_SYN, SYN_REPORT, 0)

    assert frame is not None
    assert frame.axes == {"lx": -20}
    assert frame.buttons == frozenset({"button_south"})
    assert frame.timestamp_ns == 1_000_003_000
    assert EVENT_STRUCT.unpack(EVENT_STRUCT.pack(0, 0, EV_ABS, 0, -1))[-1] == -1
    assert session._apply_event(1, 4, EV_KEY, 999, 1) is None
    assert session._apply_event(1, 5, EV_SYN, SYN_REPORT, 0).buttons == frozenset({"button_south"})


def test_run_parser_validates_positive_values_and_requires_mapping_at_execution(
    capsys: pytest.CaptureFixture[str],
) -> None:
    parser = cli.build_parser()
    parsed = parser.parse_args(["run", "--device", "event3", "--profile", "id"])
    assert parsed.profiles_dir == Path("~/.config/zonepad/profiles")
    assert parsed.duration is None
    with pytest.raises(SystemExit):
        parser.parse_args(["run", "--device", "event3", "--profile", "id", "--timeout", "0"])
    assert cli.main(["run", "--device", "event3", "--profile", "id"]) == 2
    assert "--mapping" in capsys.readouterr().out


def test_run_mapping_error_returns_exit_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    mapping_path = tmp_path / "mapping.json"
    mapping_path.write_text("{", encoding="utf-8")
    assert (
        cli.main(["run", "--device", "event3", "--profile", "id", "--mapping", str(mapping_path)])
        == 2
    )
    assert "invalid mapping JSON" in capsys.readouterr().out


def test_run_missing_profile_returns_exit_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    mapping_path = tmp_path / "mapping.json"
    mapping_path.write_text(json.dumps(mapping_payload()), encoding="utf-8")
    assert (
        cli.main(
            [
                "run",
                "--device",
                "event3",
                "--profile",
                str(uuid.uuid4()),
                "--mapping",
                str(mapping_path),
                "--profiles-dir",
                str(tmp_path / "profiles"),
            ]
        )
        == 2
    )
    assert "profile not found" in capsys.readouterr().out


def test_run_uinput_permission_returns_exit_3(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    mapping_path = tmp_path / "mapping.json"
    mapping_path.write_text(json.dumps(mapping_payload()), encoding="utf-8")
    profile = make_profile()
    from zonepad.infrastructure.json_profile_store import JsonProfileStore

    JsonProfileStore(tmp_path / "profiles").save(profile)

    def unavailable(path: Path | None) -> None:
        del path
        raise PermissionError("/dev/uinput")

    monkeypatch.setattr(cli, "LinuxUinputPublisher", unavailable)
    assert (
        cli.main(
            [
                "run",
                "--device",
                "event3",
                "--profile",
                profile.profile_id,
                "--mapping",
                str(mapping_path),
                "--profiles-dir",
                str(tmp_path / "profiles"),
            ]
        )
        == 3
    )
    assert "udev" in capsys.readouterr().out


def test_uinput_declares_unsigned_trigger_ranges() -> None:
    assert LinuxUinputPublisher.ABS_MINIMUMS[LinuxUinputPublisher.ABS_CODES["lt"]] == 0
    assert LinuxUinputPublisher.ABS_MINIMUMS[LinuxUinputPublisher.ABS_CODES["rt"]] == 0
