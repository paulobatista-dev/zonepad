from __future__ import annotations

import json
from argparse import Namespace
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path

import pytest
from synthetic_capture import FIXED_PROFILE_ID, Recorder, full_session, mapping_payload

from zonepad.application.calibrate import (
    Continue,
    MeasurementCompleted,
    ReviewDecision,
    WizardPhase,
    WizardState,
    step,
)
from zonepad.domain.device import DeviceInfo
from zonepad.domain.input import RawFrame
from zonepad.domain.metrics import MetricsConfig
from zonepad.domain.protocol import Segment
from zonepad.infrastructure.capture_reader import read_strict_capture
from zonepad.infrastructure.capture_writer import CaptureWriter
from zonepad.infrastructure.json_profile_store import JsonProfileStore
from zonepad.infrastructure.live_capture import LiveCaptureSession
from zonepad.infrastructure.manifest_reader import load_manifest
from zonepad.infrastructure.mapping import load_device_mapping
from zonepad.infrastructure.measure_runner import MeasureRunner
from zonepad.interface import cli
from zonepad.interface.calibration_cli import run_calibrate
from zonepad.interface.terminal_console import CalibrationCancelled


class ScriptedConsole:
    is_interactive = True

    def say(self, message: str) -> None:
        pass

    def ask_choice(self, message: str, choices: Sequence[str]) -> int | None:
        return 0

    def ask_confirm(self, message: str, *, default: bool = False) -> bool:
        return default

    def show_progress(self, message: str, seconds_left: float) -> None:
        pass


class AlwaysYesConsole(ScriptedConsole):
    def __init__(self) -> None:
        self.messages: list[str] = []

    def say(self, message: str) -> None:
        self.messages.append(message)

    def ask_confirm(self, message: str, *, default: bool = False) -> bool:
        return True


class CancelAtRetryConsole(AlwaysYesConsole):
    def __init__(self) -> None:
        super().__init__()
        self.ready_prompts = 0

    def ask_confirm(self, message: str, *, default: bool = False) -> bool:
        if message == "Pressione Enter quando estiver pronto":
            self.ready_prompts += 1
            if self.ready_prompts > 7:
                raise CalibrationCancelled
        return True


class FakeClock:
    def __init__(self) -> None:
        self.value = 0

    def now_ns(self) -> int:
        return self.value

    def sleep(self, seconds: float) -> None:
        self.value += int(seconds * 1_000_000_000)


class FakeDeviceSession:
    def __init__(self, device: DeviceInfo) -> None:
        self._device = device
        self.closed = False

    @property
    def device_info(self) -> DeviceInfo:
        return self._device

    @property
    def normalization_config(self):
        raise NotImplementedError

    def read(self, timeout_s: float) -> None:
        return None

    def close(self) -> None:
        self.closed = True


class FakeBackend:
    def __init__(self, device: DeviceInfo) -> None:
        self.device = device
        self.opened = False
        self.session: FakeDeviceSession | None = None

    def list_devices(self) -> tuple[DeviceInfo, ...]:
        return (self.device,)

    def open(self, device_id: str) -> FakeDeviceSession:
        self.opened = True
        self.session = FakeDeviceSession(self.device)
        return self.session


class FailingCapture:
    def __init__(self, session: FakeDeviceSession, writer: CaptureWriter) -> None:
        self.session = session
        self.writer = writer
        self.aborted = False
        self.closed = False

    @property
    def device_info(self) -> DeviceInfo:
        return self.session.device_info

    def start(self) -> None:
        raise RuntimeError("synthetic start failure")

    def pause(self) -> None:
        pass

    def resume(self) -> None:
        pass

    def wait(self, seconds: float, progress=None) -> None:
        pass

    def record_segment(self, spec, duration_seconds: float, progress):
        raise NotImplementedError

    def flush(self):
        raise NotImplementedError

    def finish(self):
        raise NotImplementedError

    def abort(self):
        self.aborted = True
        return self.writer.abort()

    def close(self) -> None:
        self.closed = True
        self.session.close()


class RecorderCapture:
    def __init__(
        self,
        recorder: Recorder,
        writer: CaptureWriter,
        empty_attempts: Mapping[tuple[str, ...], int] | None = None,
    ) -> None:
        self.recorder = recorder
        self.writer = writer
        self.empty_attempts = dict(empty_attempts or {})
        self.attempts: dict[tuple[str, ...], int] = {}
        self.closed = False

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo("event3", "Synthetic Pad")

    def start(self) -> None:
        for frame in self.recorder.raw_frames():
            self.writer.append(frame)

    def pause(self) -> None:
        pass

    def resume(self) -> None:
        pass

    def wait(self, seconds: float, progress=None) -> None:
        pass

    def record_segment(self, spec, duration_seconds: float, progress):
        index = self.attempts.get(spec.target, 0)
        self.attempts[spec.target] = index + 1
        original = next(
            segment
            for segment in self.recorder.segments
            if segment["kind"] == spec.kind
            and (spec.stick is None or segment.get("stick") == spec.stick)
            and (spec.direction is None or segment.get("direction") == spec.direction)
            and (spec.trigger is None or segment.get("trigger") == spec.trigger)
        )
        segment = Segment(
            spec.kind,
            0,
            spec.warmup_ns + 2 if spec.kind == "rest" else 2,
            spec.warmup_ns,
            spec.stick,
            spec.direction,
            spec.trigger,
        )
        if index < self.empty_attempts.get(spec.target, 0):
            self.writer.replace_segment(
                spec.target, segment, original["start_ns"], original["start_ns"]
            )
            return None
        valid = self.writer.replace_segment(
            spec.target, segment, original["start_ns"], original["end_ns"]
        )
        return segment if valid else None

    def flush(self):
        return self.writer.flush()

    def finish(self):
        return self.writer.finish()

    def abort(self):
        return self.writer.abort()

    def close(self) -> None:
        self.closed = True


def test_reducer_moves_without_performing_io() -> None:
    state, effects = step(WizardState(), Continue(), segment_count=7)

    assert state.phase is WizardPhase.SELECT_DEVICE
    assert effects[0].name == "select_device"


def test_reducer_review_and_retry_transitions_are_explicit() -> None:
    state = WizardState(WizardPhase.MEASURE)
    state, effects = step(state, MeasurementCompleted(), segment_count=7)
    assert state.phase is WizardPhase.REVIEW
    assert effects[0].name == "review"

    state, effects = step(
        state, ReviewDecision(retry_available=True, accepted=False), segment_count=7
    )
    assert state.phase is WizardPhase.RETRY_DECISION
    assert effects[0].name == "retry_decision"


def test_writer_outputs_strict_capture_and_manifest_with_sorted_buttons(tmp_path: Path) -> None:
    writer = CaptureWriter(tmp_path / "session", DeviceInfo("event3", "Pad"))
    writer.append(RawFrame("event3", 100, {"lx": 1}, {"lt": 2}, frozenset({"z", "a"})))
    writer.append(RawFrame("event3", 200, {"lx": 3}, {"lt": 4}, frozenset()))
    valid = writer.replace_segment(
        ("circle", "left", "cw"),
        Segment("circle", 0, 2, stick="left", direction="cw"),
        100,
        201,
    )
    assert valid
    artifacts = writer.finish()

    capture = read_strict_capture(Path(artifacts.capture_path))
    manifest = load_manifest(Path(artifacts.manifest_path))
    assert [frame.timestamp_ns for frame in capture.frames] == [0, 100]
    assert manifest.capture_sha256 == capture.sha256
    assert manifest.capture_file == "capture.jsonl"
    assert manifest.segments[0].start_ns == 0
    assert manifest.segments[0].end_ns == 101
    first_row = json.loads(Path(artifacts.capture_path).read_text().splitlines()[0])
    assert set(first_row) == {"device_id", "timestamp_ns", "axes", "triggers", "buttons"}
    assert first_row["buttons"] == ["a", "z"]

    mapping_path = tmp_path / "mapping.json"
    mapping_path.write_text(json.dumps(mapping_payload()), encoding="utf-8")
    mapping = load_device_mapping(mapping_path)
    outcome = MeasureRunner(
        now=lambda: datetime(2026, 10, 25, tzinfo=UTC),
        profile_id_factory=lambda: "550e8400-e29b-41d4-a716-446655440000",
    ).run(
        Path(artifacts.capture_path),
        Path(artifacts.manifest_path),
        mapping_path,
        mapping,
        MetricsConfig(),
    )
    assert outcome.exit_reason == "strict_blocked"
    assert outcome.report["capture"]["file"] == "capture.jsonl"


def test_writer_abort_preserves_partial_capture_without_manifest(tmp_path: Path) -> None:
    writer = CaptureWriter(tmp_path / "partial", DeviceInfo("event3", "Pad"))
    writer.append(RawFrame("event3", 10, {}, {}, frozenset()))

    artifacts = writer.abort()

    assert Path(artifacts.capture_path).exists()
    assert not Path(artifacts.manifest_path).exists()


def test_calibrate_help_documents_interactive_mode_and_exit_codes(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as result:
        cli.main(["calibrate", "--help"])

    output = capsys.readouterr().out
    assert result.value.code == 0
    assert "--mapping" in output
    assert "--trigger-seconds" in output
    assert "TTY" in output
    for code in ("  0  ", "  1  ", "  2  ", "  3  ", "  4  ", "  130"):
        assert code in output


def test_invalid_mapping_fails_before_backend_or_device_open(tmp_path: Path) -> None:
    called = False

    def backend_factory(mapping: object) -> object:
        nonlocal called
        called = True
        raise AssertionError("backend must not be constructed")

    args = Namespace(
        mapping=tmp_path / "missing.json",
        thresholds=None,
        warmup_seconds=2,
        rest_seconds=5,
        circle_seconds=6,
        trigger_seconds=25,
        device="event3",
        capture_dir=tmp_path,
        profiles_dir=tmp_path,
        max_retries=2,
    )

    code = run_calibrate(args, console=ScriptedConsole(), backend_factory=backend_factory)  # type: ignore[arg-type]

    assert code == 2
    assert not called


def test_capture_factory_failure_aborts_writer_and_closes_device(tmp_path: Path) -> None:
    mapping_path = _mapping_file(tmp_path / "mapping.json")
    backend = FakeBackend(DeviceInfo("event3", "Synthetic Pad"))
    console = AlwaysYesConsole()

    def fail_factory(session, writer, timer):
        raise RuntimeError("synthetic factory failure")

    code = run_calibrate(
        _calibrate_args(tmp_path, mapping_path),
        console=console,
        backend_factory=lambda mapping: backend,
        capture_factory=fail_factory,
    )

    session_dir = next((tmp_path / "captures").iterdir())
    assert code == 1
    assert backend.session is not None and backend.session.closed
    assert (session_dir / "capture.jsonl").exists()
    assert not (session_dir / "capture.manifest.json").exists()
    assert any("erro ao iniciar captura (RuntimeError)" in message for message in console.messages)


def test_capture_path_failure_has_actionable_exit_and_closes_device(tmp_path: Path) -> None:
    mapping_path = _mapping_file(tmp_path / "mapping.json")
    capture_root = tmp_path / "captures"
    capture_root.write_text("not a directory", encoding="utf-8")
    backend = FakeBackend(DeviceInfo("event3", "Synthetic Pad"))
    console = AlwaysYesConsole()
    args = _calibrate_args(tmp_path, mapping_path)
    args.capture_dir = capture_root

    code = run_calibrate(
        args,
        console=console,
        backend_factory=lambda mapping: backend,
    )

    assert code == 2
    assert backend.session is not None and backend.session.closed
    assert any("erro ao preparar captura" in message for message in console.messages)


def test_capture_start_failure_aborts_capture_and_closes_device(tmp_path: Path) -> None:
    mapping_path = _mapping_file(tmp_path / "mapping.json")
    backend = FakeBackend(DeviceInfo("event3", "Synthetic Pad"))
    captures: list[FailingCapture] = []

    def make_capture(session, writer, timer):
        capture = FailingCapture(session, writer)
        captures.append(capture)
        return capture

    code = run_calibrate(
        _calibrate_args(tmp_path, mapping_path),
        console=AlwaysYesConsole(),
        backend_factory=lambda mapping: backend,
        capture_factory=make_capture,
    )

    assert code == 1
    assert captures[0].aborted and captures[0].closed
    assert backend.session is not None and backend.session.closed


def test_live_capture_waits_for_reader_before_abort_and_writer_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    threads = []

    class ControlledThread:
        def __init__(self, target, *, name: str, daemon: bool) -> None:
            self.alive = False
            self.join_args: tuple[object, ...] = ()
            self.join_kwargs: dict[str, object] = {}
            threads.append(self)

        def start(self) -> None:
            self.alive = True

        def join(self, *args: object, **kwargs: object) -> None:
            self.join_args, self.join_kwargs = args, kwargs
            if not args and not kwargs:
                self.alive = False

        def is_alive(self) -> bool:
            return self.alive

    monkeypatch.setattr("zonepad.infrastructure.live_capture.threading.Thread", ControlledThread)
    session = FakeDeviceSession(DeviceInfo("event3", "Synthetic Pad"))
    writer = CaptureWriter(tmp_path / "session", session.device_info)
    capture = LiveCaptureSession(session, writer, FakeClock())

    capture.start()
    capture.pause()
    assert threads[0].join_args == ()
    assert threads[0].join_kwargs == {}
    assert not threads[0].alive

    capture.resume()
    capture.abort()
    assert session.closed
    assert threads[1].join_args == ()
    assert not threads[1].alive
    assert capture._thread is None
    with pytest.raises(RuntimeError, match="closed"):
        writer.append(RawFrame("event3", 1, {}, {}, frozenset()))


def _calibrate_args(tmp_path: Path, mapping_path: Path, *, max_retries: int = 2) -> Namespace:
    return Namespace(
        mapping=mapping_path,
        thresholds=None,
        warmup_seconds=2.0,
        rest_seconds=5.0,
        circle_seconds=6.0,
        trigger_seconds=25.0,
        device="event3",
        capture_dir=tmp_path / "captures",
        profiles_dir=tmp_path / "profiles",
        max_retries=max_retries,
    )


def _mapping_file(path: Path) -> Path:
    path.write_text(json.dumps(mapping_payload()), encoding="utf-8")
    return path


def test_calibrate_full_happy_path_saves_profile_and_compatible_artifacts(
    tmp_path: Path,
) -> None:
    recorder = full_session()
    mapping_path = _mapping_file(tmp_path / "mapping.json")
    device = DeviceInfo("event3", "Synthetic Pad")
    backend = FakeBackend(device)
    console = AlwaysYesConsole()
    clock = FakeClock()
    capture_instances: list[RecorderCapture] = []

    def make_capture(session, writer, timer):
        capture = RecorderCapture(recorder, writer)
        capture_instances.append(capture)
        return capture

    code = run_calibrate(
        _calibrate_args(tmp_path, mapping_path),
        console=console,
        clock=clock,
        backend_factory=lambda mapping: backend,
        now=lambda: datetime(2026, 10, 25, tzinfo=UTC),
        profile_id_factory=lambda: FIXED_PROFILE_ID,
        capture_factory=make_capture,
    )

    session_dirs = tuple((tmp_path / "captures").iterdir())
    assert code == 0
    assert backend.opened
    assert len(session_dirs) == 1
    session_dir = session_dirs[0]
    loaded = read_strict_capture(session_dir / "capture.jsonl")
    manifest = load_manifest(session_dir / "capture.manifest.json")
    assert manifest.capture_sha256 == loaded.sha256
    assert len(manifest.segments) == 7
    assert (session_dir / "report.json").exists()
    assert (session_dir / "report.md").exists()
    store = JsonProfileStore(tmp_path / "profiles")
    assert store.load(FIXED_PROFILE_ID).profile_id == FIXED_PROFILE_ID
    assert capture_instances[0].closed
    assert any("Próximo comando: zonepad run" in message for message in console.messages)


def test_sparse_rest_retries_and_saves_after_observed_interval(tmp_path: Path) -> None:
    recorder = full_session()
    mapping_path = _mapping_file(tmp_path / "mapping.json")
    backend = FakeBackend(DeviceInfo("event3", "Synthetic Pad"))
    console = AlwaysYesConsole()
    capture_instances: list[RecorderCapture] = []

    def make_capture(session, writer, timer):
        capture = RecorderCapture(recorder, writer, {("rest",): 1})
        capture_instances.append(capture)
        return capture

    code = run_calibrate(
        _calibrate_args(tmp_path, mapping_path),
        console=console,
        clock=FakeClock(),
        backend_factory=lambda mapping: backend,
        now=lambda: datetime(2026, 10, 25, tzinfo=UTC),
        profile_id_factory=lambda: FIXED_PROFILE_ID,
        capture_factory=make_capture,
    )

    session_dir = next((tmp_path / "captures").iterdir())
    manifest = load_manifest(session_dir / "capture.manifest.json")
    assert code == 0
    assert len(manifest.segments) == 7
    assert capture_instances[0].attempts[("rest",)] == 2
    assert any("retries=1" in message for message in console.messages)
    assert (
        JsonProfileStore(tmp_path / "profiles").load(FIXED_PROFILE_ID).profile_id
        == FIXED_PROFILE_ID
    )


def test_sparse_rest_retry_exhaustion_keeps_only_partial_capture(tmp_path: Path) -> None:
    recorder = full_session()
    mapping_path = _mapping_file(tmp_path / "mapping.json")
    backend = FakeBackend(DeviceInfo("event3", "Synthetic Pad"))
    capture_instances: list[RecorderCapture] = []

    def make_capture(session, writer, timer):
        capture = RecorderCapture(recorder, writer, {("rest",): 2})
        capture_instances.append(capture)
        return capture

    code = run_calibrate(
        _calibrate_args(tmp_path, mapping_path, max_retries=1),
        console=AlwaysYesConsole(),
        clock=FakeClock(),
        backend_factory=lambda mapping: backend,
        now=lambda: datetime(2026, 10, 25, tzinfo=UTC),
        profile_id_factory=lambda: FIXED_PROFILE_ID,
        capture_factory=make_capture,
    )

    session_dir = next((tmp_path / "captures").iterdir())
    assert code == 4
    assert capture_instances[0].attempts[("rest",)] == 2
    assert (session_dir / "capture.jsonl").exists()
    assert not (session_dir / "capture.manifest.json").exists()
    assert not (session_dir / "report.json").exists()
    assert not (session_dir / "report.md").exists()
    assert JsonProfileStore(tmp_path / "profiles").list_profiles() == ()


def test_cancel_during_measurement_retry_removes_stale_report_and_manifest(
    tmp_path: Path,
) -> None:
    recorder = full_session(rest_s=2.0)
    mapping_path = _mapping_file(tmp_path / "mapping.json")
    backend = FakeBackend(DeviceInfo("event3", "Synthetic Pad"))
    console = CancelAtRetryConsole()

    code = run_calibrate(
        _calibrate_args(tmp_path, mapping_path),
        console=console,
        clock=FakeClock(),
        backend_factory=lambda mapping: backend,
        now=lambda: datetime(2026, 10, 25, tzinfo=UTC),
        profile_id_factory=lambda: FIXED_PROFILE_ID,
        capture_factory=lambda session, writer, timer: RecorderCapture(recorder, writer),
    )

    session_dir = next((tmp_path / "captures").iterdir())
    assert code == 130
    assert console.ready_prompts > 7
    assert (session_dir / "capture.jsonl").exists()
    assert not (session_dir / "capture.manifest.json").exists()
    assert not (session_dir / "report.json").exists()
    assert not (session_dir / "report.md").exists()
    assert JsonProfileStore(tmp_path / "profiles").list_profiles() == ()
