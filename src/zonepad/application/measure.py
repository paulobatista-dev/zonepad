"""Use case behind ``zonepad measure``: segment, measure, assess, report and derive a profile."""

from __future__ import annotations

import logging
from bisect import bisect_left
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from zonepad.domain.device import DeviceInfo
from zonepad.domain.errors import MeasurementInputError, ProfileDerivationError
from zonepad.domain.input import RawFrame
from zonepad.domain.metrics import (
    ChannelCoverage,
    CircleStickWindow,
    MeasurementMetrics,
    MetricsConfig,
    RawChannelDiagnostics,
    RestStickWindow,
    RestTriggerWindow,
    StickSamples,
    TriggerSamples,
    measure_capture,
    measure_raw_axis,
    measure_raw_trigger,
    measure_stick,
    measure_trigger,
)
from zonepad.domain.normalization import AxisRange, TriggerRange, normalize_axis, normalize_trigger
from zonepad.domain.profile import CalibrationProfile
from zonepad.domain.protocol import CaptureManifest, Segment
from zonepad.domain.quality import evaluate_quality

from .calibration import (
    DerivedCalibration,
    build_profile_from_metrics,
    derive_calibration,
    format_utc,
)
from .ports import ProfileStore
from .report import ReportContext, SegmentSummary, build_report

logger = logging.getLogger(__name__)

STICK_AXES: dict[str, tuple[str, str]] = {"left": ("lx", "ly"), "right": ("rx", "ry")}
TRIGGER_CHANNELS: dict[str, str] = {"left": "lt", "right": "rt"}
_NS_PER_S = 1_000_000_000


@dataclass(frozen=True, slots=True)
class MeasureInputs:
    """Everything already loaded and validated at the boundary."""

    frames: Sequence[RawFrame]
    capture_file: str
    capture_sha256: str
    manifest: CaptureManifest
    axis_ranges: Mapping[str, AxisRange]
    trigger_ranges: Mapping[str, TriggerRange]
    mapping_sha256: str
    config: MetricsConfig = field(default_factory=MetricsConfig)


@dataclass(frozen=True, slots=True)
class MeasurementRun:
    metrics: MeasurementMetrics
    segments: tuple[SegmentSummary, ...]


@dataclass(frozen=True, slots=True)
class MeasureOptions:
    strict: bool = False
    save_profile: bool = False


ExitReason = Literal["ok", "strict_blocked", "profile_not_derivable"]


@dataclass(frozen=True, slots=True)
class MeasureOutcome:
    report: dict[str, Any]
    metrics: MeasurementMetrics
    profile: CalibrationProfile | None
    exit_reason: ExitReason
    message: str | None = None


# ------------------------------------------------------------------------------ validation


def validate_inputs(inputs: MeasureInputs) -> None:
    """Cross-check manifest and capture; every failure is an actionable input error."""
    frames, manifest = inputs.frames, inputs.manifest
    if not frames:
        raise MeasurementInputError(
            "EMPTY_CAPTURE", f"{inputs.capture_file}: a captura não tem frames"
        )
    if manifest.capture_file != inputs.capture_file:
        raise MeasurementInputError(
            "INVALID_MANIFEST",
            f"capture_file {manifest.capture_file!r} difere do arquivo de captura "
            f"{inputs.capture_file!r}; aponte o manifesto para a captura certa",
        )
    if manifest.capture_sha256 is not None and (
        manifest.capture_sha256.lower() != inputs.capture_sha256
    ):
        raise MeasurementInputError(
            "INVALID_MANIFEST",
            "capture_sha256 do manifesto não confere com o hash calculado da captura "
            f"({inputs.capture_sha256}); a captura mudou desde que o manifesto foi escrito",
        )
    for index, frame in enumerate(frames):
        if frame.device_id != manifest.device.device_id:
            raise MeasurementInputError(
                "INVALID_MANIFEST",
                f"device.device_id {manifest.device.device_id!r} difere do device_id "
                f"{frame.device_id!r} do frame {index + 1}",
            )
    first, last = frames[0].timestamp_ns, frames[-1].timestamp_ns
    for index, segment in enumerate(manifest.segments):
        if segment.start_ns < first or segment.end_ns > last + 1:
            raise MeasurementInputError(
                "INVALID_MANIFEST",
                f"segments[{index}] [{segment.start_ns}, {segment.end_ns}) fica fora da captura "
                f"[{first}, {last}]; corrija start_ns/end_ns",
            )


# -------------------------------------------------------------------------- segmentation


def _slice(timestamps: Sequence[int], start_ns: int, end_ns: int) -> range:
    return range(bisect_left(timestamps, start_ns), bisect_left(timestamps, end_ns))


class _Normalizer:
    def __init__(self, inputs: MeasureInputs) -> None:
        self._frames = inputs.frames
        self._axes = inputs.axis_ranges
        self._triggers = inputs.trigger_ranges

    def stick(self, indices: range, names: tuple[str, str]) -> StickSamples:
        ts: list[int] = []
        xs: list[float] = []
        ys: list[float] = []
        for i in indices:
            frame = self._frames[i]
            if all(n in frame.axes and n in self._axes for n in names):
                ts.append(frame.timestamp_ns)
                xs.append(normalize_axis(frame.axes[names[0]], self._axes[names[0]]))
                ys.append(normalize_axis(frame.axes[names[1]], self._axes[names[1]]))
        return StickSamples(tuple(ts), tuple(xs), tuple(ys))

    def trigger(self, indices: range, name: str) -> TriggerSamples:
        ts: list[int] = []
        values: list[float] = []
        if name in self._triggers:
            for i in indices:
                frame = self._frames[i]
                if name in frame.triggers:
                    ts.append(frame.timestamp_ns)
                    values.append(normalize_trigger(frame.triggers[name], self._triggers[name]))
        return TriggerSamples(tuple(ts), tuple(values))

    def raw_values(self, indices: Sequence[int], name: str) -> list[int]:
        found: list[int] = []
        for i in indices:
            frame = self._frames[i]
            source = frame.axes if name in self._axes else frame.triggers
            if name in source:
                found.append(int(source[name]))
        return found


def _unmapped_channels(inputs: MeasureInputs) -> tuple[str, ...]:
    names: set[str] = set()
    for frame in inputs.frames:
        names.update(n for n in frame.axes if n not in inputs.axis_ranges)
        names.update(n for n in frame.triggers if n not in inputs.trigger_ranges)
    return tuple(sorted(names))


def measure(inputs: MeasureInputs) -> MeasurementRun:
    """Segment the capture, compute every metric and attach the quality assessment."""
    validate_inputs(inputs)
    frames, manifest, config = inputs.frames, inputs.manifest, inputs.config
    timestamps = [frame.timestamp_ns for frame in frames]
    for position, (a, b) in enumerate(zip(timestamps, timestamps[1:], strict=False), 2):
        if b < a:
            raise MeasurementInputError(
                "NON_MONOTONIC_TIME", f"frame {position}: timestamp_ns decresce de {a} para {b}"
            )
    normalizer = _Normalizer(inputs)
    windows: list[tuple[Segment, range, range]] = []  # (segment, full indices, effective indices)
    for segment in manifest.segments:
        full = _slice(timestamps, segment.start_ns, segment.end_ns)
        effective = _slice(timestamps, segment.effective_start_ns, segment.end_ns)
        windows.append((segment, full, effective))

    summaries = tuple(
        SegmentSummary(
            index,
            segment,
            len(full),
            (segment.end_ns - segment.effective_start_ns) / _NS_PER_S,
        )
        for index, (segment, full, _) in enumerate(windows)
    )
    in_segments = sorted({i for _, full, _ in windows for i in full})
    rest_windows = [(seg, eff) for seg, _, eff in windows if seg.kind == "rest"]
    rest_indices = sorted({i for _, eff in rest_windows for i in eff})

    sticks = {}
    for side, names in STICK_AXES.items():
        rest = [
            RestStickWindow(seg.effective_start_ns, seg.end_ns, normalizer.stick(eff, names))
            for seg, eff in rest_windows
        ]
        circles = [
            (seg, full) for seg, full, _ in windows if seg.kind == "circle" and seg.stick == side
        ]
        circle_windows = [
            CircleStickWindow(seg.direction or "", normalizer.stick(full, names))
            for seg, full in circles
        ]
        relevant = sum(len(eff) for _, eff in rest_windows) + sum(len(f) for _, f in circles)
        valid = sum(len(w.samples.x) for w in rest) + sum(len(w.samples.x) for w in circle_windows)
        sticks[side] = measure_stick(
            names, rest, circle_windows, ChannelCoverage(relevant, valid), config
        )

    triggers = {}
    for side, channel in TRIGGER_CHANNELS.items():
        rest_t = [
            RestTriggerWindow(seg.effective_start_ns, seg.end_ns, normalizer.trigger(eff, channel))
            for seg, eff in rest_windows
        ]
        sweeps = [
            (seg, full)
            for seg, full, _ in windows
            if seg.kind == "trigger_sweep" and seg.trigger == side
        ]
        sweep_samples = [normalizer.trigger(full, channel) for _, full in sweeps]
        relevant = sum(len(eff) for _, eff in rest_windows) + sum(len(f) for _, f in sweeps)
        valid = sum(len(w.samples.values) for w in rest_t) + sum(
            len(s.values) for s in sweep_samples
        )
        triggers[side] = measure_trigger(
            rest_t, sweep_samples, ChannelCoverage(relevant, valid), config
        )

    raw: dict[str, RawChannelDiagnostics] = {}
    for name, axis_range in inputs.axis_ranges.items():
        raw[name] = measure_raw_axis(
            axis_range.minimum,
            axis_range.center,
            axis_range.maximum,
            normalizer.raw_values(rest_indices, name),
            normalizer.raw_values(in_segments, name),
        )
    for name, trigger_range in inputs.trigger_ranges.items():
        raw[name] = measure_raw_trigger(
            trigger_range.rest,
            trigger_range.maximum,
            normalizer.raw_values(rest_indices, name),
            normalizer.raw_values(in_segments, name),
        )

    circle_spans = [(seg.start_ns, seg.end_ns) for seg in manifest.segments if seg.kind == "circle"]
    capture = measure_capture(timestamps, circle_spans, len(frames) - len(in_segments), config)
    metrics = MeasurementMetrics(
        source_file=inputs.capture_file,
        source_sha256=inputs.capture_sha256,
        capture=capture,
        nominal_rate_hz=manifest.nominal_rate_hz,
        rest_segments=len(rest_windows),
        rest_effective_duration_s=sum(
            (seg.end_ns - seg.effective_start_ns) / _NS_PER_S for seg, _ in rest_windows
        ),
        sticks=sticks,
        triggers=triggers,
        raw={name: raw[name] for name in sorted(raw)},
        unmapped_channels=_unmapped_channels(inputs),
        config=config,
    )
    return MeasurementRun(evaluate_quality(metrics), summaries)


# --------------------------------------------------------------------------- use case


def _device_info(manifest: CaptureManifest) -> DeviceInfo:
    device = manifest.device
    return DeviceInfo(
        device.device_id,
        device.name,
        int(device.vid, 16),
        int(device.pid, 16),
        device.guid,
        device.serial,
    )


def execute_measure(
    inputs: MeasureInputs,
    options: MeasureOptions,
    *,
    app_version: str,
    now: Callable[[], datetime],
    profile_id_factory: Callable[[], str],
) -> MeasureOutcome:
    """Measure, build the report and, when requested and allowed, derive the profile.

    The caller persists ``outcome.profile`` with ``save_profile`` once the report is written, so
    a failing report never leaves a stray profile. ``--strict`` blocks the profile on any
    blocking finding (the report then states ``derived: false``). Asking for a profile that
    cannot be derived keeps the report but yields ``profile_not_derivable``.
    """
    run = measure(inputs)
    metrics = run.metrics
    blocked = options.strict and any(f.blocks_strict for f in metrics.findings)
    derived: DerivedCalibration | None
    derive_error: str | None = None
    try:
        derived = derive_calibration(metrics)
    except ProfileDerivationError as exc:
        derived, derive_error = None, str(exc)
    if blocked:
        derived = None
    profile: CalibrationProfile | None = None
    if options.save_profile and not blocked and derived is not None:
        try:
            profile = build_profile_from_metrics(
                _device_info(inputs.manifest),
                metrics,
                app_version=app_version,
                now=now,
                profile_id_factory=profile_id_factory,
            )
        except ProfileDerivationError as exc:
            derived, derive_error = None, str(exc)
    manifest_device = inputs.manifest.device
    context = ReportContext(
        device_name=manifest_device.name,
        vid=manifest_device.vid,
        pid=manifest_device.pid,
        connection=inputs.manifest.connection,
        mapping_sha256=inputs.mapping_sha256,
        segments=run.segments,
        created_at=format_utc(now()),
        app_version=app_version,
    )
    report = build_report(
        metrics,
        context,
        derived,
        profile.profile_id if profile is not None else None,
    )
    if blocked:
        return MeasureOutcome(
            report,
            metrics,
            None,
            "strict_blocked",
            "--strict: há achados bloqueantes; nenhum perfil foi gravado",
        )
    if options.save_profile and profile is None:
        return MeasureOutcome(
            report,
            metrics,
            None,
            "profile_not_derivable",
            derive_error or "o perfil não pôde ser derivado das métricas",
        )
    return MeasureOutcome(report, metrics, profile, "ok")


def save_profile(store: ProfileStore, outcome: MeasureOutcome) -> None:
    """Persist the derived profile of ``outcome``; no-op when none was derived."""
    if outcome.profile is not None:
        store.save(outcome.profile)
        logger.debug("profile saved", extra={"profile_id": outcome.profile.profile_id})
