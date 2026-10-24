from __future__ import annotations

import uuid

import pytest

from zonepad.domain.calibration import apply_profile, apply_radial_deadzone
from zonepad.domain.errors import InvalidProfileError
from zonepad.domain.input import NormalizedFrame
from zonepad.domain.normalization import AxisRange, TriggerRange, normalize_axis, normalize_trigger
from zonepad.domain.profile import (
    CalibrationProfile,
    DeviceIdentity,
    StickCalibration,
    TriggerCalibration,
)


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


def test_normalization_supports_asymmetric_ranges() -> None:
    axis = AxisRange(-100, 10, 90)
    assert normalize_axis(-100, axis) == pytest.approx(-1)
    assert normalize_axis(10, axis) == pytest.approx(0)
    assert normalize_axis(90, axis) == pytest.approx(1)
    assert normalize_trigger(50, TriggerRange(10, 110)) == pytest.approx(0.4)


def test_deadzone_rescale_and_profile_pipeline() -> None:
    assert apply_radial_deadzone(0.05, 0, 0.1) == (0, 0)
    frame = NormalizedFrame(
        "pad", 1, {"lx": 0.5, "ly": 0, "rx": 0, "ry": 0}, {"lt": 0.5, "rt": 0}, frozenset()
    )
    calibrated = apply_profile(frame, make_profile())
    assert calibrated.axes["lx"] == pytest.approx(0.5)
    assert calibrated.triggers["lt"] == pytest.approx(0.5)


def test_profile_rejects_unknown_fields_and_invalid_version() -> None:
    profile = make_profile().to_dict()
    profile["unexpected"] = True
    with pytest.raises(InvalidProfileError):
        CalibrationProfile.from_dict(profile)
    profile = make_profile().to_dict()
    profile["schema_version"] = 99
    with pytest.raises(InvalidProfileError):
        CalibrationProfile.from_dict(profile)
