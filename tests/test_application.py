from __future__ import annotations

import uuid

from zonepad.application.runtime import RuntimeProcessor
from zonepad.domain.device import DeviceInfo
from zonepad.domain.input import RawFrame
from zonepad.domain.normalization import AxisRange, TriggerRange
from zonepad.domain.profile import (
    CalibrationProfile,
    DeviceIdentity,
    StickCalibration,
    TriggerCalibration,
)
from zonepad.infrastructure.fake import FakeSession


class Publisher:
    def __init__(self) -> None:
        self.frames = []
        self.closed = False

    def publish(self, frame) -> None:
        self.frames.append(frame)

    def close(self) -> None:
        self.closed = True


def test_runtime_distinguishes_timeout_and_publishes_calibrated_frame() -> None:
    info = DeviceInfo("pad", "Pad", 1, 2)
    session = FakeSession(
        info,
        [RawFrame("pad", 1, {"lx": 0, "ly": 0, "rx": 0, "ry": 0}, {"lt": 0, "rt": 0}, frozenset())],
    )
    profile = CalibrationProfile(
        1,
        str(uuid.uuid4()),
        DeviceIdentity("Pad", "0x0001", "0x0002"),
        {"left": StickCalibration(), "right": StickCalibration()},
        {"left": TriggerCalibration(), "right": TriggerCalibration()},
        "2026-10-24T00:00:00Z",
        "0.1.0",
    )
    publisher = Publisher()
    runtime = RuntimeProcessor(
        session,
        profile,
        publisher,
        {name: AxisRange(-100, 0, 100) for name in ("lx", "ly", "rx", "ry")},
        {"lt": TriggerRange(0, 100), "rt": TriggerRange(0, 100)},
    )
    assert runtime.process_once() is not None
    assert runtime.process_once() is None
    assert len(publisher.frames) == 1
