from __future__ import annotations

import math

from .input import CalibratedFrame, NormalizedFrame
from .profile import CalibrationProfile, CurveSpec, StickCalibration, TriggerCalibration


def apply_curve(value: float, curve: CurveSpec) -> float:
    if curve.type == "linear":
        return value
    if curve.type == "exponential":
        assert curve.gamma is not None
        return math.copysign(abs(value) ** curve.gamma, value)
    points = curve.lut
    if value <= points[0][0]:
        return points[0][1]
    if value >= points[-1][0]:
        return points[-1][1]
    for (x0, y0), (x1, y1) in zip(points, points[1:], strict=False):
        if x0 <= value <= x1:
            if x1 == x0:
                return y1
            fraction = (value - x0) / (x1 - x0)
            return y0 + fraction * (y1 - y0)
    return value


def apply_radial_deadzone(
    x: float, y: float, deadzone: float, mode: str = "cut"
) -> tuple[float, float]:
    if not 0.0 <= deadzone < 1.0:
        raise ValueError("deadzone must be in [0, 1)")
    if mode not in ("cut", "rescale"):
        raise ValueError("deadzone mode must be cut or rescale")
    radius = math.hypot(x, y)
    if radius <= deadzone:
        return 0.0, 0.0
    if mode == "cut" or deadzone == 0:
        return x, y
    scale = (radius - deadzone) / (1.0 - deadzone)
    return x / radius * scale, y / radius * scale


def _calibrate_axis(value: float, center: float, minimum: float, maximum: float) -> float:
    shifted = value - center
    denominator = maximum - center if shifted >= 0 else center - minimum
    if denominator <= 0:
        return 0.0
    return max(-1.0, min(1.0, shifted / denominator))


def _apply_stick(values: tuple[float, float], calibration: StickCalibration) -> tuple[float, float]:
    calibrated_x = _calibrate_axis(
        values[0], calibration.center[0], calibration.range_min[0], calibration.range_max[0]
    )
    calibrated_y = _calibrate_axis(
        values[1], calibration.center[1], calibration.range_min[1], calibration.range_max[1]
    )
    x, y = apply_radial_deadzone(
        calibrated_x, calibrated_y, calibration.deadzone.value, calibration.deadzone.mode
    )
    x = apply_curve(x, calibration.curve)
    y = apply_curve(y, calibration.curve)
    if calibration.invert[0]:
        x = -x
    if calibration.invert[1]:
        y = -y
    return max(-1.0, min(1.0, x)), max(-1.0, min(1.0, y))


def _apply_trigger(value: float, calibration: TriggerCalibration) -> float:
    scaled = max(0.0, min(1.0, (value - calibration.rest) / (calibration.max - calibration.rest)))
    if scaled <= calibration.deadzone:
        scaled = 0.0
    elif calibration.deadzone:
        scaled = (scaled - calibration.deadzone) / (1.0 - calibration.deadzone)
    scaled = apply_curve(scaled, calibration.curve)
    if calibration.invert:
        scaled = 1.0 - scaled
    return max(0.0, min(1.0, scaled))


def apply_stick_calibration(
    x: float, y: float, calibration: StickCalibration
) -> tuple[float, float]:
    return _apply_stick((x, y), calibration)


def apply_trigger_calibration(value: float, calibration: TriggerCalibration) -> float:
    return _apply_trigger(value, calibration)


def apply_profile(frame: NormalizedFrame, profile: CalibrationProfile) -> CalibratedFrame:
    """Apply the documented center → range → deadzone → curve → invert pipeline."""
    axes = dict(frame.axes)
    for side, names in (("left", ("lx", "ly")), ("right", ("rx", "ry"))):
        if all(name in axes for name in names):
            axes[names[0]], axes[names[1]] = _apply_stick(
                (axes[names[0]], axes[names[1]]), profile.sticks[side]
            )
    triggers: dict[str, float] = {}
    for name, value in frame.triggers.items():
        if name in ("lt", "left_trigger"):
            triggers[name] = _apply_trigger(value, profile.triggers["left"])
        elif name in ("rt", "right_trigger"):
            triggers[name] = _apply_trigger(value, profile.triggers["right"])
        else:
            triggers[name] = max(0.0, min(1.0, value))
    return CalibratedFrame(
        frame.device_id, frame.timestamp_ns, axes, triggers, frame.buttons, profile.profile_id
    )
