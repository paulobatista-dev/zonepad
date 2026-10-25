"""Calibration metrics for sticks, triggers and capture timing (spec metrics-v1).

Every function is pure and works on values already normalized with the device mapping:
sticks in [-1, 1], triggers in [0, 1]. Only ``RawChannelDiagnostics`` uses the raw layer
(integer counts). Percentiles use linear interpolation (Hyndman-Fan type 7); the center is
always a median.
"""

from __future__ import annotations

import math
from bisect import bisect_left, bisect_right
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from .calibration import calibrate_axis
from .findings import Finding, QualityStatus

NS_PER_S = 1_000_000_000
THRESHOLDS_VERSION = 1
_EPS_SATURATION = 1e-9
_DEADZONE_MAX = 0.95
_LAP_BINS = 24
_LAP_BIN_DEGREES = 360.0 / _LAP_BINS
_MIN_POINTS_PER_BIN = 2
_RANGE_LOW_Q = 0.005
_RANGE_HIGH_Q = 0.995
_SMOOTH_WINDOW = 5
_ANCHOR_LOW = 0.05
_ANCHOR_HIGH = 0.95
_HYSTERESIS_GRID = 100


# --------------------------------------------------------------------------- configuration


def _require(condition: bool, field_name: str, rule: str) -> None:
    if not condition:
        raise ValueError(f"{field_name}: {rule}")


def _positive(value: float, field_name: str) -> None:
    _require(math.isfinite(value) and value > 0, field_name, "deve ser finito e maior que zero")


def _count(value: int, field_name: str) -> None:
    _require(isinstance(value, int) and value >= 1, field_name, "deve ser um inteiro >= 1")


@dataclass(frozen=True, slots=True)
class DeadzoneParams:
    factor: float = 1.5
    stick_floor: float = 0.02
    trigger_floor: float = 0.01

    def __post_init__(self) -> None:
        _require(1.0 <= self.factor <= 10.0, "deadzone.factor", "deve estar em [1, 10]")
        _require(0.0 <= self.stick_floor <= 0.5, "deadzone.stick_floor", "deve estar em [0, 0.5]")
        _require(
            0.0 <= self.trigger_floor <= 0.5, "deadzone.trigger_floor", "deve estar em [0, 0.5]"
        )


@dataclass(frozen=True, slots=True)
class ProtocolParams:
    rest_min_duration_s: float = 3.0
    rest_min_frames: int = 150
    rest_hard_min_duration_s: float = 1.0
    rest_hard_min_frames: int = 10
    drift_block_s: float = 1.0
    drift_block_min_frames: int = 5
    circle_min_radius: float = 0.3
    circle_min_points_per_lap: int = 100
    circle_min_valid_laps_per_direction: int = 2
    min_half_range: float = 0.5
    trigger_arm: float = 0.15
    trigger_exit: float = 0.10
    trigger_peak_min: float = 0.8
    trigger_phase_min_points: int = 50
    trigger_min_valid_cycles: int = 3
    trigger_min_span: float = 0.5
    rate_gap_max_s: float = 0.25
    rate_min_pairs: int = 100

    def __post_init__(self) -> None:
        for name in (
            "rest_min_duration_s",
            "rest_hard_min_duration_s",
            "drift_block_s",
            "circle_min_radius",
            "min_half_range",
            "trigger_arm",
            "trigger_exit",
            "trigger_peak_min",
            "trigger_min_span",
            "rate_gap_max_s",
        ):
            _positive(getattr(self, name), f"protocol.{name}")
        for name in (
            "rest_min_frames",
            "rest_hard_min_frames",
            "drift_block_min_frames",
            "circle_min_points_per_lap",
            "circle_min_valid_laps_per_direction",
            "trigger_phase_min_points",
            "trigger_min_valid_cycles",
            "rate_min_pairs",
        ):
            _count(getattr(self, name), f"protocol.{name}")
        _require(
            round(self.drift_block_s * NS_PER_S) >= 1,
            "protocol.drift_block_s",
            "deve valer pelo menos 1 ns",
        )
        _require(
            self.trigger_exit < self.trigger_arm < self.trigger_peak_min,
            "protocol.trigger_exit",
            "exige trigger_exit < trigger_arm < trigger_peak_min",
        )


@dataclass(frozen=True, slots=True)
class Thresholds:
    drift_max: float = 0.02
    noise_rms_max: float = 0.005
    circularity_min: float = 0.90
    trigger_r2_min: float = 0.98
    hysteresis_max: float = 0.03
    rate_tolerance: float = 0.10
    saturation_ratio_max: float = 0.30
    center_offset_info: float = 0.10

    def __post_init__(self) -> None:
        for name in (
            "drift_max",
            "noise_rms_max",
            "circularity_min",
            "trigger_r2_min",
            "hysteresis_max",
            "saturation_ratio_max",
            "center_offset_info",
        ):
            _positive(getattr(self, name), name)
        _require(0.0 < self.rate_tolerance < 1.0, "rate_tolerance", "deve estar em (0, 1)")


@dataclass(frozen=True, slots=True)
class MetricsConfig:
    """Effective thresholds and protocol parameters; defaults are *default a validar*."""

    thresholds: Thresholds = field(default_factory=Thresholds)
    deadzone: DeadzoneParams = field(default_factory=DeadzoneParams)
    protocol: ProtocolParams = field(default_factory=ProtocolParams)

    def to_dict(self) -> dict[str, Any]:
        thresholds = {name: getattr(self.thresholds, name) for name in self.thresholds.__slots__}
        deadzone = {name: getattr(self.deadzone, name) for name in self.deadzone.__slots__}
        protocol = {name: getattr(self.protocol, name) for name in self.protocol.__slots__}
        return {
            "thresholds_version": THRESHOLDS_VERSION,
            **thresholds,
            "deadzone": deadzone,
            "protocol": protocol,
        }


# ------------------------------------------------------------------------------ statistics


def percentile(values: Sequence[float], q: float) -> float:
    """Percentile ``q`` in [0, 1] by linear interpolation (Hyndman-Fan type 7)."""
    if not values:
        raise ValueError("percentile requires at least one value")
    if not 0.0 <= q <= 1.0:
        raise ValueError("q must be in [0, 1]")
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    lower = math.floor(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (position - lower) * (ordered[upper] - ordered[lower])


def median(values: Sequence[float]) -> float:
    return percentile(values, 0.5)


def _mean(values: Sequence[float]) -> float:
    return math.fsum(values) / len(values)


def _rms(values: Sequence[float]) -> float:
    return math.sqrt(math.fsum(v * v for v in values) / len(values))


def _median_or_none(values: Sequence[float]) -> float | None:
    return median(values) if values else None


def _min_or_none[T: (int, float)](values: Sequence[T]) -> T | None:
    return min(values) if values else None


def _max_or_none[T: (int, float)](values: Sequence[T]) -> T | None:
    return max(values) if values else None


# ------------------------------------------------------------------------------ input types


@dataclass(frozen=True, slots=True)
class StickSamples:
    """Normalized samples of one stick; frames lacking either axis are excluded upstream."""

    timestamps_ns: tuple[int, ...]
    x: tuple[float, ...]
    y: tuple[float, ...]

    def __post_init__(self) -> None:
        if not len(self.timestamps_ns) == len(self.x) == len(self.y):
            raise ValueError("timestamps_ns, x e y devem ter o mesmo tamanho")


@dataclass(frozen=True, slots=True)
class RestStickWindow:
    """Effective rest window ``[effective_start_ns, end_ns)`` (warmup already discarded)."""

    effective_start_ns: int
    end_ns: int
    samples: StickSamples


@dataclass(frozen=True, slots=True)
class CircleStickWindow:
    direction: str
    samples: StickSamples


@dataclass(frozen=True, slots=True)
class TriggerSamples:
    timestamps_ns: tuple[int, ...]
    values: tuple[float, ...]

    def __post_init__(self) -> None:
        if len(self.timestamps_ns) != len(self.values):
            raise ValueError("timestamps_ns e values devem ter o mesmo tamanho")


@dataclass(frozen=True, slots=True)
class RestTriggerWindow:
    effective_start_ns: int
    end_ns: int
    samples: TriggerSamples


@dataclass(frozen=True, slots=True)
class ChannelCoverage:
    """Frames of the channel's relevant segments, and how many carry every needed channel."""

    relevant_frames: int = 0
    valid_frames: int = 0

    @property
    def missing_frames(self) -> int:
        return self.relevant_frames - self.valid_frames


# ----------------------------------------------------------------------------- stick result


@dataclass(frozen=True, slots=True)
class NoiseMetrics:
    rms_x: float
    rms_y: float
    rms_xy: float
    p2p_x: float
    p2p_y: float
    radius_max: float
    radius_p99: float


@dataclass(frozen=True, slots=True)
class JitterMetrics:
    mean: float
    p99: float
    max: float


@dataclass(frozen=True, slots=True)
class StickRestMetrics:
    frames: int
    duration_s: float
    valid_blocks: int
    drift: float | None
    noise: NoiseMetrics | None
    jitter: JitterMetrics | None


@dataclass(frozen=True, slots=True)
class StickRangeMetrics:
    min: tuple[float, float]
    max: tuple[float, float]
    span: tuple[float, float]
    observed_min: tuple[float, float]
    observed_max: tuple[float, float]
    symmetry: tuple[float | None, float | None]


@dataclass(frozen=True, slots=True)
class CircleMetrics:
    segments_cw: int
    segments_ccw: int
    frames: int
    valid_laps_cw: int
    valid_laps_ccw: int
    rejected_laps: int
    direction_inconsistent: bool
    circularity_median: float | None
    circularity_worst: float | None
    mean_radius_median: float | None
    mean_radius_worst: float | None
    saturation_ratio: float | None

    @property
    def segments(self) -> int:
        return self.segments_cw + self.segments_ccw

    @property
    def valid_laps(self) -> int:
        return self.valid_laps_cw + self.valid_laps_ccw


@dataclass(frozen=True, slots=True)
class DeadzoneSuggestion:
    """Suggested radial ``cut`` deadzone (stick, calibrated space) or span fraction (trigger)."""

    value: float
    basis_p99: float
    clamped: bool
    mode: str = "cut"


@dataclass(frozen=True, slots=True)
class StickMetrics:
    axes: tuple[str, str]
    coverage: ChannelCoverage
    rest_segments: int
    rest: StickRestMetrics
    center: tuple[float, float] | None
    center_segment_max_shift: float | None
    axis_range: StickRangeMetrics | None
    circle: CircleMetrics
    deadzone: DeadzoneSuggestion | None


# ------------------------------------------------------------------------------ stick math


def _pool(windows: Sequence[RestStickWindow]) -> tuple[list[float], list[float]]:
    xs = [value for window in windows for value in window.samples.x]
    ys = [value for window in windows for value in window.samples.y]
    return xs, ys


def _noise(xs: Sequence[float], ys: Sequence[float], center: tuple[float, float]) -> NoiseMetrics:
    ex = [value - center[0] for value in xs]
    ey = [value - center[1] for value in ys]
    radii = [math.hypot(a, b) for a, b in zip(ex, ey, strict=True)]
    return NoiseMetrics(
        rms_x=_rms(ex),
        rms_y=_rms(ey),
        rms_xy=_rms(radii),
        p2p_x=max(xs) - min(xs),
        p2p_y=max(ys) - min(ys),
        radius_max=max(radii),
        radius_p99=percentile(radii, 0.99),
    )


def _jitter(windows: Sequence[RestStickWindow]) -> JitterMetrics | None:
    steps: list[float] = []
    for window in windows:
        x, y = window.samples.x, window.samples.y
        steps.extend(math.hypot(x[i + 1] - x[i], y[i + 1] - y[i]) for i in range(len(x) - 1))
    if not steps:
        return None
    return JitterMetrics(mean=_mean(steps), p99=percentile(steps, 0.99), max=max(steps))


def _drift_blocks(
    windows: Sequence[RestStickWindow], protocol: ProtocolParams
) -> list[tuple[float, float]]:
    """Medians of the consecutive 1 s blocks (from the effective start) with enough frames."""
    block_ns = round(protocol.drift_block_s * NS_PER_S)
    medians: list[tuple[float, float]] = []
    for window in windows:
        timestamps = window.samples.timestamps_ns
        for index in range((window.end_ns - window.effective_start_ns) // block_ns):
            start = window.effective_start_ns + index * block_ns
            lo = bisect_left(timestamps, start)
            hi = bisect_left(timestamps, start + block_ns)
            if hi - lo >= protocol.drift_block_min_frames:
                medians.append((median(window.samples.x[lo:hi]), median(window.samples.y[lo:hi])))
    return medians


def _wrap_angle(delta: float) -> float:
    return math.remainder(delta, 2.0 * math.pi)


@dataclass(frozen=True, slots=True)
class _Lap:
    valid: bool
    circularity: float | None = None
    mean_radius: float | None = None


def _analyze_circle(
    samples: StickSamples, center: tuple[float, float], protocol: ProtocolParams
) -> tuple[list[_Lap], int]:
    """Return the complete laps of a circle segment and the observed rotation sign."""
    radii: list[float] = []
    angles: list[float] = []
    for px, py in zip(samples.x, samples.y, strict=True):
        vx, vy = px - center[0], py - center[1]
        radius = math.hypot(vx, vy)
        if radius >= protocol.circle_min_radius:
            radii.append(radius)
            angles.append(math.atan2(vy, vx))
    if len(angles) < 2:
        return [], 0
    unwrapped = [angles[0]]
    for previous, current in zip(angles, angles[1:], strict=False):
        unwrapped.append(unwrapped[-1] + _wrap_angle(current - previous))
    total = unwrapped[-1] - unwrapped[0]
    sign = (total > 0) - (total < 0)
    if sign == 0:
        return [], 0
    complete = math.floor(abs(total) / (2.0 * math.pi))
    lap_radii: list[list[float]] = [[] for _ in range(complete)]
    lap_bins: list[list[list[float]]] = [[[] for _ in range(_LAP_BINS)] for _ in range(complete)]
    for radius, angle, theta in zip(radii, angles, unwrapped, strict=True):
        lap = math.floor(sign * (theta - unwrapped[0]) / (2.0 * math.pi))
        if 0 <= lap < complete:
            lap_radii[lap].append(radius)
            bin_index = math.floor((math.degrees(angle) + _LAP_BIN_DEGREES / 2) / _LAP_BIN_DEGREES)
            lap_bins[lap][bin_index % _LAP_BINS].append(radius)
    laps: list[_Lap] = []
    for frames, bins in zip(lap_radii, lap_bins, strict=True):
        enough = len(frames) >= protocol.circle_min_points_per_lap and all(
            len(b) >= _MIN_POINTS_PER_BIN for b in bins
        )
        if not enough:
            laps.append(_Lap(valid=False))
            continue
        bin_radii = [median(b) for b in bins]
        laps.append(_Lap(True, min(bin_radii) / max(bin_radii), _mean(frames)))
    return laps, sign


def _direction_inconsistent(signs: Mapping[str, set[int]]) -> bool:
    cw, ccw = signs["cw"], signs["ccw"]
    return len(cw) > 1 or len(ccw) > 1 or (bool(cw) and bool(ccw) and cw == ccw)


def _circle_metrics(
    circles: Sequence[CircleStickWindow],
    center: tuple[float, float] | None,
    protocol: ProtocolParams,
) -> CircleMetrics:
    segments = {"cw": 0, "ccw": 0}
    valid = {"cw": 0, "ccw": 0}
    signs: dict[str, set[int]] = {"cw": set(), "ccw": set()}
    rejected = 0
    circularity: list[float] = []
    mean_radius: list[float] = []
    frames = saturated = 0
    for window in circles:
        segments[window.direction] += 1
        frames += len(window.samples.x)
        saturated += sum(
            1
            for px, py in zip(window.samples.x, window.samples.y, strict=True)
            if max(abs(px), abs(py)) >= 1.0 - _EPS_SATURATION
        )
        if center is None:
            continue
        laps, sign = _analyze_circle(window.samples, center, protocol)
        if sign:
            signs[window.direction].add(sign)
        for lap in laps:
            if lap.valid and lap.circularity is not None and lap.mean_radius is not None:
                valid[window.direction] += 1
                circularity.append(lap.circularity)
                mean_radius.append(lap.mean_radius)
            else:
                rejected += 1
    return CircleMetrics(
        segments_cw=segments["cw"],
        segments_ccw=segments["ccw"],
        frames=frames,
        valid_laps_cw=valid["cw"],
        valid_laps_ccw=valid["ccw"],
        rejected_laps=rejected,
        direction_inconsistent=_direction_inconsistent(signs),
        circularity_median=_median_or_none(circularity),
        circularity_worst=_min_or_none(circularity),
        mean_radius_median=_median_or_none(mean_radius),
        mean_radius_worst=_min_or_none(mean_radius),
        saturation_ratio=saturated / frames if frames else None,
    )


def _range_metrics(
    circles: Sequence[CircleStickWindow], center: tuple[float, float] | None
) -> StickRangeMetrics | None:
    xs = [value for window in circles for value in window.samples.x]
    ys = [value for window in circles for value in window.samples.y]
    if not xs:
        return None
    low = (percentile(xs, _RANGE_LOW_Q), percentile(ys, _RANGE_LOW_Q))
    high = (percentile(xs, _RANGE_HIGH_Q), percentile(ys, _RANGE_HIGH_Q))

    def symmetry(axis: int) -> float | None:
        if center is None or center[axis] - low[axis] <= 0 or high[axis] - center[axis] <= 0:
            return None
        return (high[axis] - center[axis]) / (center[axis] - low[axis])

    return StickRangeMetrics(
        min=low,
        max=high,
        span=(high[0] - low[0], high[1] - low[1]),
        observed_min=(min(xs), min(ys)),
        observed_max=(max(xs), max(ys)),
        symmetry=(symmetry(0), symmetry(1)),
    )


def _stick_deadzone(
    xs: Sequence[float],
    ys: Sequence[float],
    center: tuple[float, float],
    axis_range: StickRangeMetrics,
    params: DeadzoneParams,
) -> DeadzoneSuggestion:
    """Radial deadzone in the calibrated space, where ``apply_radial_deadzone`` acts."""
    radii = [
        math.hypot(
            calibrate_axis(px, center[0], axis_range.min[0], axis_range.max[0]),
            calibrate_axis(py, center[1], axis_range.min[1], axis_range.max[1]),
        )
        for px, py in zip(xs, ys, strict=True)
    ]
    basis = percentile(radii, 0.99)
    wanted = max(params.factor * basis, params.stick_floor)
    return DeadzoneSuggestion(min(wanted, _DEADZONE_MAX), basis, wanted > _DEADZONE_MAX)


def measure_stick(
    axes: tuple[str, str],
    rest: Sequence[RestStickWindow],
    circles: Sequence[CircleStickWindow],
    coverage: ChannelCoverage,
    config: MetricsConfig,
) -> StickMetrics:
    xs, ys = _pool(rest)
    center = (median(xs), median(ys)) if xs else None
    noise = _noise(xs, ys, center) if center is not None else None
    blocks = _drift_blocks(rest, config.protocol)
    drift = None
    if center is not None and len(blocks) >= 2:
        drift = max(math.hypot(bx - center[0], by - center[1]) for bx, by in blocks)
    shift = None
    if center is not None:
        shift = max(
            math.hypot(median(w.samples.x) - center[0], median(w.samples.y) - center[1])
            for w in rest
            if w.samples.x
        )
    axis_range = _range_metrics(circles, center)
    deadzone = None
    if center is not None and axis_range is not None:
        deadzone = _stick_deadzone(xs, ys, center, axis_range, config.deadzone)
    return StickMetrics(
        axes=axes,
        coverage=coverage,
        rest_segments=len(rest),
        rest=StickRestMetrics(
            frames=len(xs),
            duration_s=math.fsum((w.end_ns - w.effective_start_ns) / NS_PER_S for w in rest),
            valid_blocks=len(blocks),
            drift=drift,
            noise=noise,
            jitter=_jitter(rest),
        ),
        center=center,
        center_segment_max_shift=shift,
        axis_range=axis_range,
        circle=_circle_metrics(circles, center, config.protocol),
        deadzone=deadzone,
    )


# --------------------------------------------------------------------------- trigger result


@dataclass(frozen=True, slots=True)
class Spread:
    """Typical value (median) and worst case across cycles/laps/phases."""

    median: float
    worst: float


@dataclass(frozen=True, slots=True)
class TriggerMetrics:
    coverage: ChannelCoverage
    rest_segments: int
    sweep_segments: int
    rest_frames: int
    rest_duration_s: float
    rest: float | None
    noise_rms: float | None
    noise_p2p: float | None
    noise_p99: float | None
    max: float | None
    span: float | None
    max_values: tuple[float, ...]
    max_dispersion: float | None
    cycles_detected: int
    cycles_valid: int
    linearity_r2: Spread | None
    linearity_max_error: Spread | None
    hysteresis: Spread | None
    saturation_ratio: float | None
    deadzone: DeadzoneSuggestion | None


def _smooth(values: Sequence[float]) -> list[float]:
    """Moving median with window 5; the window shrinks at the segment borders."""
    half = _SMOOTH_WINDOW // 2
    return [median(values[max(0, i - half) : i + half + 1]) for i in range(len(values))]


def _detect_cycles(
    smoothed: Sequence[float], rest: float, protocol: ProtocolParams
) -> list[tuple[int, int]]:
    """Arm at ``s > rest + trigger_arm``; close at the next ``s <= rest + trigger_exit``.

    An unfinished cycle is reported with exit index -1.
    """
    cycles: list[tuple[int, int]] = []
    index = 0
    while index < len(smoothed):
        if smoothed[index] > rest + protocol.trigger_arm:
            end = next(
                (
                    j
                    for j in range(index + 1, len(smoothed))
                    if smoothed[j] <= rest + protocol.trigger_exit
                ),
                -1,
            )
            cycles.append((index, end))
            if end < 0:
                break
            index = end
        index += 1
    return cycles


def _crossings(
    times: Sequence[float], levels: Sequence[float], level: float, rising: bool
) -> list[float]:
    found: list[float] = []
    for i in range(len(times) - 1):
        a, b = levels[i], levels[i + 1]
        if (rising and a < level <= b) or (not rising and a > level >= b):
            found.append(times[i] + (level - a) / (b - a) * (times[i + 1] - times[i]))
    return found


def _phase(
    times: Sequence[float],
    levels: Sequence[float],
    anchors: tuple[tuple[float, float], tuple[float, float]],
) -> list[tuple[float, float]]:
    """Frames strictly between two anchors, plus the interpolated anchor points themselves."""
    (start, start_level), (end, end_level) = anchors
    inside = [(t, y) for t, y in zip(times, levels, strict=True) if start < t < end]
    return [(start, start_level), *inside, (end, end_level)]


def _interpolate(xs: Sequence[float], ys: Sequence[float], x: float) -> float:
    index = bisect_right(xs, x)
    if index <= 0:
        return ys[0]
    if index >= len(xs):
        return ys[-1]
    x0, x1 = xs[index - 1], xs[index]
    if x1 == x0:
        return ys[index]
    return ys[index - 1] + (x - x0) / (x1 - x0) * (ys[index] - ys[index - 1])


@dataclass(frozen=True, slots=True)
class _Cycle:
    peak: float
    r2: tuple[float, float]
    max_error: tuple[float, float]
    hysteresis: float


def _linearity(points: Sequence[tuple[float, float]]) -> tuple[float, float] | None:
    """R² and max |y - ŷ| of one phase against the line through the 0.05/0.95 anchors."""
    mean_y = _mean([y for _, y in points])
    total = math.fsum((y - mean_y) ** 2 for _, y in points)
    if total <= 0:
        return None
    errors = [y - (_ANCHOR_LOW + (_ANCHOR_HIGH - _ANCHOR_LOW) * tau) for tau, y in points]
    return 1.0 - math.fsum(e * e for e in errors) / total, max(abs(e) for e in errors)


def _analyze_cycle(
    times: Sequence[float],
    smoothed: Sequence[float],
    bounds: tuple[int, int, int, int],
    rest: float,
    protocol: ProtocolParams,
) -> _Cycle | None:
    """Shape metrics of one cycle; ``bounds`` = (context start, arm, exit, context end).

    The context spans from the previous cycle's exit to the next cycle's arm, because the 0.05
    anchors lie outside the arm/exit hysteresis band.
    """
    context_start, arm, exit_index, context_end = bounds
    peak = max(smoothed[arm : exit_index + 1])
    if peak < protocol.trigger_peak_min or peak <= rest:
        return None
    t = list(times[context_start:context_end])
    y = [(s - rest) / (peak - rest) for s in smoothed[context_start:context_end]]
    rises_high = _crossings(t, y, _ANCHOR_HIGH, rising=True)
    falls_high = _crossings(t, y, _ANCHOR_HIGH, rising=False)
    if not rises_high or not falls_high:
        return None
    t_b, t_c = rises_high[0], falls_high[-1]
    rises_low = [c for c in _crossings(t, y, _ANCHOR_LOW, rising=True) if c < t_b]
    falls_low = [c for c in _crossings(t, y, _ANCHOR_LOW, rising=False) if c > t_c]
    if not rises_low or not falls_low or t_c <= t_b:
        return None
    t_a, t_d = rises_low[-1], falls_low[0]
    rise = [
        ((time - t_a) / (t_b - t_a), level)
        for time, level in _phase(t, y, ((t_a, _ANCHOR_LOW), (t_b, _ANCHOR_HIGH)))
    ]
    fall = [
        ((t_d - time) / (t_d - t_c), level)
        for time, level in reversed(_phase(t, y, ((t_c, _ANCHOR_HIGH), (t_d, _ANCHOR_LOW))))
    ]
    minimum = protocol.trigger_phase_min_points
    if len(rise) - 2 < minimum or len(fall) - 2 < minimum:  # only measured frames count
        return None
    rise_fit, fall_fit = _linearity(rise), _linearity(fall)
    if rise_fit is None or fall_fit is None:
        return None
    up_x, up_y = [p[0] for p in rise], [p[1] for p in rise]
    down_x, down_y = [p[0] for p in fall], [p[1] for p in fall]
    gap = max(
        abs(
            _interpolate(up_x, up_y, j / _HYSTERESIS_GRID)
            - _interpolate(down_x, down_y, j / _HYSTERESIS_GRID)
        )
        for j in range(_HYSTERESIS_GRID + 1)
    )
    scale = peak - rest
    return _Cycle(
        peak=peak,
        r2=(rise_fit[0], fall_fit[0]),
        max_error=(scale * rise_fit[1], scale * fall_fit[1]),
        hysteresis=scale * gap,
    )


def _sweep_cycles(
    sweep: TriggerSamples, rest: float, protocol: ProtocolParams
) -> tuple[int, list[_Cycle]]:
    """Return (detected cycles, valid cycles) of one ``trigger_sweep`` segment."""
    smoothed = _smooth(sweep.values)
    times = [ts / NS_PER_S for ts in sweep.timestamps_ns]
    detected = _detect_cycles(smoothed, rest, protocol)
    valid: list[_Cycle] = []
    for position, (arm, exit_index) in enumerate(detected):
        if exit_index < 0:
            continue
        context_start = detected[position - 1][1] + 1 if position > 0 else 0
        context_end = detected[position + 1][0] if position + 1 < len(detected) else len(smoothed)
        cycle = _analyze_cycle(
            times, smoothed, (context_start, arm, exit_index, context_end), rest, protocol
        )
        if cycle is not None:
            valid.append(cycle)
    return sum(1 for _, end in detected if end >= 0), valid


def _spread(values: Sequence[float], *, worst_is_min: bool) -> Spread | None:
    if not values:
        return None
    return Spread(median(values), min(values) if worst_is_min else max(values))


def measure_trigger(
    rest: Sequence[RestTriggerWindow],
    sweeps: Sequence[TriggerSamples],
    coverage: ChannelCoverage,
    config: MetricsConfig,
) -> TriggerMetrics:
    values = [value for window in rest for value in window.samples.values]
    rest_value = median(values) if values else None
    deviations = [abs(v - rest_value) for v in values] if rest_value is not None else []
    detected = 0
    cycles: list[_Cycle] = []
    if rest_value is not None:
        for sweep in sweeps:
            found, valid = _sweep_cycles(sweep, rest_value, config.protocol)
            detected += found
            cycles.extend(valid)
    peaks = tuple(cycle.peak for cycle in cycles)
    peak = median(peaks) if peaks else None
    span = peak - rest_value if peak is not None and rest_value is not None else None
    sweep_frames = [value for sweep in sweeps for value in sweep.values]
    noise_p99 = percentile(deviations, 0.99) if deviations else None
    deadzone = None
    if span is not None and span > 0 and noise_p99 is not None:
        wanted = max(config.deadzone.factor * noise_p99, config.deadzone.trigger_floor) / span
        deadzone = DeadzoneSuggestion(min(wanted, _DEADZONE_MAX), noise_p99, wanted > _DEADZONE_MAX)
    return TriggerMetrics(
        coverage=coverage,
        rest_segments=len(rest),
        sweep_segments=len(sweeps),
        rest_frames=len(values),
        rest_duration_s=math.fsum((w.end_ns - w.effective_start_ns) / NS_PER_S for w in rest),
        rest=rest_value,
        noise_rms=_rms([v - rest_value for v in values]) if rest_value is not None else None,
        noise_p2p=max(values) - min(values) if values else None,
        noise_p99=noise_p99,
        max=peak,
        span=span,
        max_values=peaks,
        max_dispersion=max(peaks) - min(peaks) if peaks else None,
        cycles_detected=detected,
        cycles_valid=len(cycles),
        linearity_r2=_spread([r for c in cycles for r in c.r2], worst_is_min=True),
        linearity_max_error=_spread([e for c in cycles for e in c.max_error], worst_is_min=False),
        hysteresis=_spread([c.hysteresis for c in cycles], worst_is_min=False),
        saturation_ratio=(
            sum(1 for v in sweep_frames if v >= 1.0 - _EPS_SATURATION) / len(sweep_frames)
            if sweep_frames
            else None
        ),
        deadzone=deadzone,
    )


# ------------------------------------------------------------------------- capture timing


@dataclass(frozen=True, slots=True)
class CaptureMetrics:
    frames: int
    frames_outside_segments: int
    duration_s: float
    duplicate_pairs: int
    rate_pairs: int
    effective_rate_hz: float | None
    rate_p5_hz: float | None
    rate_p95_hz: float | None


def measure_capture(
    timestamps_ns: Sequence[int],
    circle_windows: Sequence[tuple[int, int]],
    frames_outside_segments: int,
    config: MetricsConfig,
) -> CaptureMetrics:
    """Capture timing. The rate population is the consecutive pairs inside one circle segment.

    ``circle_windows`` are ``[start_ns, end_ns)`` intervals sorted and disjoint.
    """
    starts = [start for start, _ in circle_windows]

    def window_of(ts: int) -> int:
        index = bisect_right(starts, ts) - 1
        return index if index >= 0 and ts < circle_windows[index][1] else -1

    gap_max = config.protocol.rate_gap_max_s
    deltas: list[float] = []
    duplicates = 0
    for current, following in zip(timestamps_ns, timestamps_ns[1:], strict=False):
        if following < current:
            raise ValueError("timestamps_ns must be non-decreasing")
        if following == current:
            duplicates += 1
            continue
        delta = (following - current) / NS_PER_S
        if (
            delta <= gap_max
            and (window := window_of(current)) >= 0
            and window == window_of(following)
        ):
            deltas.append(delta)
    rates = [1.0 / delta for delta in deltas]
    has_rate = len(deltas) >= config.protocol.rate_min_pairs
    duration = (timestamps_ns[-1] - timestamps_ns[0]) / NS_PER_S if timestamps_ns else 0.0
    return CaptureMetrics(
        frames=len(timestamps_ns),
        frames_outside_segments=frames_outside_segments,
        duration_s=duration,
        duplicate_pairs=duplicates,
        rate_pairs=len(deltas),
        effective_rate_hz=1.0 / _mean(deltas) if has_rate else None,
        rate_p5_hz=percentile(rates, 0.05) if has_rate else None,
        rate_p95_hz=percentile(rates, 0.95) if has_rate else None,
    )


# ------------------------------------------------------------------------ raw diagnostics


@dataclass(frozen=True, slots=True)
class RawChannelDiagnostics:
    """Raw-layer diagnostic in integer counts for one mapped channel."""

    mapping: Mapping[str, int]
    rest_median: float | None
    observed_min: int | None
    observed_max: int | None
    out_of_range_ratio: float | None
    lsb_normalized: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "mapping", MappingProxyType(dict(self.mapping)))


def measure_raw_axis(
    minimum: int,
    center: int,
    maximum: int,
    rest_values: Sequence[int],
    segment_values: Sequence[int],
) -> RawChannelDiagnostics:
    outside = sum(1 for v in segment_values if v < minimum or v > maximum)
    return RawChannelDiagnostics(
        mapping={"minimum": minimum, "center": center, "maximum": maximum},
        rest_median=_median_or_none(rest_values),
        observed_min=_min_or_none(segment_values),
        observed_max=_max_or_none(segment_values),
        out_of_range_ratio=outside / len(segment_values) if segment_values else None,
        lsb_normalized=1.0 / min(maximum - center, center - minimum),
    )


def measure_raw_trigger(
    rest: int, maximum: int, rest_values: Sequence[int], segment_values: Sequence[int]
) -> RawChannelDiagnostics:
    outside = sum(1 for v in segment_values if v < rest or v > maximum)
    return RawChannelDiagnostics(
        mapping={"rest": rest, "maximum": maximum},
        rest_median=_median_or_none(rest_values),
        observed_min=_min_or_none(segment_values),
        observed_max=_max_or_none(segment_values),
        out_of_range_ratio=outside / len(segment_values) if segment_values else None,
        lsb_normalized=1.0 / (maximum - rest),
    )


# -------------------------------------------------------------------------------- aggregate


@dataclass(frozen=True, slots=True)
class MeasurementMetrics:
    """Immutable aggregate consumed by the report and by ``build_profile_from_metrics``.

    ``findings`` and ``status`` are filled by ``evaluate_quality`` (``dataclasses.replace``).
    """

    source_file: str
    source_sha256: str
    capture: CaptureMetrics
    nominal_rate_hz: float | None
    rest_segments: int
    rest_effective_duration_s: float
    sticks: Mapping[str, StickMetrics]
    triggers: Mapping[str, TriggerMetrics]
    raw: Mapping[str, RawChannelDiagnostics]
    unmapped_channels: tuple[str, ...] = ()
    findings: tuple[Finding, ...] = ()
    status: QualityStatus = "pass"
    config: MetricsConfig = field(default_factory=MetricsConfig)

    def __post_init__(self) -> None:
        object.__setattr__(self, "sticks", MappingProxyType(dict(self.sticks)))
        object.__setattr__(self, "triggers", MappingProxyType(dict(self.triggers)))
        object.__setattr__(self, "raw", MappingProxyType(dict(self.raw)))
