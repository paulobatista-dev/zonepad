"""Use cases for the live normalized monitor."""

from __future__ import annotations

from zonepad.domain.input import NormalizedFrame, RawFrame
from zonepad.domain.normalization import normalize_frame

from .ports import NormalizationConfig


def normalize_monitor_frame(frame: RawFrame, ranges: NormalizationConfig) -> NormalizedFrame:
    """Convert one raw session frame into the device-independent monitor layer."""
    return normalize_frame(frame, ranges.axes, ranges.triggers)
