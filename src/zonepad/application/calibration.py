from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from zonepad.domain.device import DeviceInfo
from zonepad.domain.input import NormalizedFrame
from zonepad.domain.profile import (
    CalibrationProfile,
    DeviceIdentity,
    StickCalibration,
    TriggerCalibration,
)


def build_profile(
    device: DeviceInfo, samples: Sequence[NormalizedFrame], app_version: str = "0.1.0"
) -> CalibrationProfile:
    """Build a conservative profile from captured normalized samples."""
    if not samples:
        raise ValueError("at least one sample is required")
    axes = {
        name: [frame.axes[name] for frame in samples if name in frame.axes]
        for name in ("lx", "ly", "rx", "ry")
    }
    sticks: dict[str, StickCalibration] = {}
    for side, names in (("left", ("lx", "ly")), ("right", ("rx", "ry"))):
        values = [axes[name] for name in names]
        center = (
            float(sum(values[0]) / len(values[0])) if values[0] else 0.0,
            float(sum(values[1]) / len(values[1])) if values[1] else 0.0,
        )
        minimum = (float(min(values[0], default=-1.0)), float(min(values[1], default=-1.0)))
        maximum = (float(max(values[0], default=1.0)), float(max(values[1], default=1.0)))
        minimum = (
            minimum[0] if minimum[0] < center[0] else max(-1.0, center[0] - 1e-6),
            minimum[1] if minimum[1] < center[1] else max(-1.0, center[1] - 1e-6),
        )
        maximum = (
            maximum[0] if maximum[0] > center[0] else min(1.0, center[0] + 1e-6),
            maximum[1] if maximum[1] > center[1] else min(1.0, center[1] + 1e-6),
        )
        sticks[side] = StickCalibration(center=center, range_min=minimum, range_max=maximum)
    trigger_values = {
        name: [frame.triggers[name] for frame in samples if name in frame.triggers]
        for name in ("lt", "rt", "left_trigger", "right_trigger")
    }

    def trigger_profile(values: list[float]) -> TriggerCalibration:
        rest = min(values or [0.0])
        maximum = max(values or [1.0])
        if maximum <= rest:
            maximum = min(1.0, rest + 1e-6)
        if maximum <= rest:
            rest = max(0.0, maximum - 1e-6)
        return TriggerCalibration(rest=rest, max=maximum)

    triggers = {
        "left": trigger_profile(trigger_values["lt"] or trigger_values["left_trigger"]),
        "right": trigger_profile(trigger_values["rt"] or trigger_values["right_trigger"]),
    }
    vid = f"0x{(device.vendor_id or 0):04x}"
    pid = f"0x{(device.product_id or 0):04x}"
    return CalibrationProfile(
        1,
        str(uuid.uuid4()),
        DeviceIdentity(device.name, vid, pid, device.guid, device.serial),
        sticks,
        triggers,
        datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        app_version,
    )
