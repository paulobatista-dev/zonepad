from __future__ import annotations

import uuid

from zonepad.domain.profile import (
    CalibrationProfile,
    DeviceIdentity,
    StickCalibration,
    TriggerCalibration,
)
from zonepad.infrastructure.json_profile_store import JsonProfileStore


def test_json_profile_store_round_trip(tmp_path) -> None:
    profile = CalibrationProfile(
        1,
        str(uuid.uuid4()),
        DeviceIdentity("Pad", "0x0001", "0x0002"),
        {"left": StickCalibration(), "right": StickCalibration()},
        {"left": TriggerCalibration(), "right": TriggerCalibration()},
        "2026-10-24T00:00:00Z",
        "0.1.0",
    )
    store = JsonProfileStore(tmp_path)
    store.save(profile)
    assert store.load(profile.profile_id) == profile
    assert store.list_profiles() == (profile.profile_id,)
