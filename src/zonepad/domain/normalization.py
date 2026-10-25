from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from .input import NormalizedFrame, RawFrame


@dataclass(frozen=True, slots=True)
class AxisRange:
    minimum: int
    center: int
    maximum: int

    def __post_init__(self) -> None:
        if not self.minimum < self.center < self.maximum:
            raise ValueError("axis range requires minimum < center < maximum")


@dataclass(frozen=True, slots=True)
class TriggerRange:
    rest: int
    maximum: int

    def __post_init__(self) -> None:
        if self.maximum <= self.rest:
            raise ValueError("trigger range requires maximum > rest")


def normalize_axis(value: int | float, axis_range: AxisRange) -> float:
    """Normalize an asymmetric stick axis to [-1, 1]."""
    numeric = float(value)
    if numeric >= axis_range.center:
        normalized = (numeric - axis_range.center) / (axis_range.maximum - axis_range.center)
    else:
        normalized = (numeric - axis_range.center) / (axis_range.center - axis_range.minimum)
    return max(-1.0, min(1.0, normalized))


def normalize_trigger(value: int | float, trigger_range: TriggerRange) -> float:
    """Normalize a trigger using measured rest and maximum values."""
    normalized = (float(value) - trigger_range.rest) / (trigger_range.maximum - trigger_range.rest)
    return max(0.0, min(1.0, normalized))


def normalize_stick(
    x: int | float,
    y: int | float,
    x_range: AxisRange,
    y_range: AxisRange,
) -> tuple[float, float]:
    return normalize_axis(x, x_range), normalize_axis(y, y_range)


def normalize_frame(
    frame: RawFrame,
    axis_ranges: Mapping[str, AxisRange],
    trigger_ranges: Mapping[str, TriggerRange],
) -> NormalizedFrame:
    missing_axes = set(frame.axes) - set(axis_ranges)
    missing_triggers = set(frame.triggers) - set(trigger_ranges)
    if missing_axes or missing_triggers:
        missing = sorted(missing_axes | missing_triggers)
        raise ValueError(f"missing measured ranges for: {', '.join(missing)}")
    return NormalizedFrame(
        device_id=frame.device_id,
        timestamp_ns=frame.timestamp_ns,
        axes={name: normalize_axis(value, axis_ranges[name]) for name, value in frame.axes.items()},
        triggers={
            name: normalize_trigger(value, trigger_ranges[name])
            for name, value in frame.triggers.items()
        },
        buttons=frame.buttons,
    )
