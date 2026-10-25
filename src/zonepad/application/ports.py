from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol

from zonepad.domain.device import DeviceInfo
from zonepad.domain.input import CalibratedFrame, RawFrame
from zonepad.domain.normalization import AxisRange, TriggerRange
from zonepad.domain.profile import CalibrationProfile


class DeviceSession(Protocol):
    @property
    def device_info(self) -> DeviceInfo: ...

    def read(self, timeout_s: float) -> RawFrame | None: ...

    @property
    def normalization_config(self) -> NormalizationConfig: ...

    def close(self) -> None: ...


class DeviceBackend(Protocol):
    def list_devices(self) -> Sequence[DeviceInfo]: ...

    def open(self, device_id: str) -> DeviceSession: ...


class ProfileStore(Protocol):
    def load(self, profile_id: str) -> CalibrationProfile: ...

    def save(self, profile: CalibrationProfile) -> None: ...


class FramePublisher(Protocol):
    def publish(self, frame: CalibratedFrame) -> None: ...

    def close(self) -> None: ...


class NormalizationConfig(Protocol):
    @property
    def axes(self) -> Mapping[str, AxisRange]: ...

    @property
    def triggers(self) -> Mapping[str, TriggerRange]: ...
