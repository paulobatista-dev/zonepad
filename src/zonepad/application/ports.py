from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from zonepad.domain.device import DeviceInfo
from zonepad.domain.input import CalibratedFrame, RawFrame
from zonepad.domain.normalization import AxisRange, TriggerRange
from zonepad.domain.profile import CalibrationProfile
from zonepad.domain.protocol import Segment

from .calibrate import SegmentPlan


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


class Console(Protocol):
    @property
    def is_interactive(self) -> bool: ...

    def say(self, message: str) -> None: ...

    def ask_choice(self, message: str, choices: Sequence[str]) -> int | None: ...

    def ask_confirm(self, message: str, *, default: bool = False) -> bool: ...

    def show_progress(self, message: str, seconds_left: float) -> None: ...


class Clock(Protocol):
    def now_ns(self) -> int: ...

    def sleep(self, seconds: float) -> None: ...


@dataclass(frozen=True, slots=True)
class CaptureArtifacts:
    directory: str
    capture_path: str
    manifest_path: str


class CaptureSession(Protocol):
    @property
    def device_info(self) -> DeviceInfo: ...

    def start(self) -> None: ...

    def pause(self) -> None: ...

    def resume(self) -> None: ...

    def wait(self, seconds: float, progress: Callable[[float], None] | None = None) -> None: ...

    def record_segment(
        self,
        spec: SegmentPlan,
        duration_seconds: float,
        progress: Callable[[float], None],
    ) -> Segment | None: ...

    def flush(self) -> CaptureArtifacts: ...

    def finish(self) -> CaptureArtifacts: ...

    def abort(self) -> CaptureArtifacts: ...

    def close(self) -> None: ...


class FramePublisher(Protocol):
    def publish(self, frame: CalibratedFrame) -> None: ...

    def close(self) -> None: ...


class NormalizationConfig(Protocol):
    @property
    def axes(self) -> Mapping[str, AxisRange]: ...

    @property
    def triggers(self) -> Mapping[str, TriggerRange]: ...
