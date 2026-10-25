from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Protocol

from zonepad.domain.catalog import CatalogMatch
from zonepad.domain.device import DeviceInfo
from zonepad.domain.discovery import (
    AbsInfo,
    DiscoverySnapshot,
    HotplugChange,
    ObservedInputDevice,
)
from zonepad.domain.identity import MappingKey, StableIdentity
from zonepad.domain.input import CalibratedFrame, RawFrame
from zonepad.domain.mapping_draft import DraftProvenance
from zonepad.domain.normalization import AxisRange, TriggerRange
from zonepad.domain.profile import CalibrationProfile
from zonepad.domain.protocol import Segment

from .calibrate import SegmentPlan

if TYPE_CHECKING:
    from zonepad.application.measure import MeasureOutcome

from zonepad.domain.metrics import MetricsConfig


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


class ProfileCatalog(Protocol):
    """Enumerate profile identifiers while preserving per-item load failures."""

    def list_profiles(self) -> Sequence[str]: ...


class WizardMeasureRunner(Protocol):
    """Execute the validated measurement workflow for one finished capture."""

    def run(
        self,
        capture_path: Path,
        manifest_path: Path,
        mapping_path: Path,
        mapping: NormalizationConfig,
        config: MetricsConfig,
    ) -> MeasureOutcome: ...


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


class InputDeviceScanner(Protocol):
    """Read facts of every ``eventN`` without opening device nodes.

    Raises ``DeviceNotFoundError`` when the sysfs root is missing or unreadable;
    a problem in one node becomes a ``ReadIssue`` and never aborts the scan.
    """

    def scan(self) -> Sequence[ObservedInputDevice]: ...


class AbsInfoReader(Protocol):
    """Read ``input_absinfo`` for ``codes`` of one node (``EVIOCGABS``, no event read).

    Raises ``DeviceAccessDeniedError`` or ``DeviceNotFoundError``.  Codes whose
    absinfo is degenerate or unsupported are absent from the result.
    """

    def read_absinfo(self, event_node: str, codes: Sequence[int]) -> Mapping[int, AbsInfo]: ...


class DeviceCatalog(Protocol):
    def match(self, observed: ObservedInputDevice) -> CatalogMatch: ...


StoredMappingStatus = Literal["saved", "provisional", "edited", "invalid"]


@dataclass(frozen=True, slots=True)
class StoredMappingRef:
    """A saved mapping as found on disk; hashes are recomputed on every read.

    ``key.connection`` is the recorded connection.  ``detail`` explains an
    ``invalid`` status.  ``recorded_*`` fields feed the change warnings of D6.
    """

    key: MappingKey
    mapping_path: str
    mapping_sha256: str | None
    recorded_sha256: str | None
    provisional: bool | None
    range_source: str | None
    status: StoredMappingStatus
    detail: str | None = None
    fragile: bool | None = None
    recorded_device_version: int | None = None
    recorded_firmware: str | None = None


@dataclass(frozen=True, slots=True)
class MappingRecord:
    key: MappingKey
    identity: StableIdentity
    connection_source: Literal["detected", "override"]
    mapping_text: str
    provenance: DraftProvenance
    range_source: str
    range_sources: Mapping[str, str]
    absinfo: Mapping[int, AbsInfo]
    created_at: str
    app_version: str


class DeviceMappingStore(Protocol):
    def find(self, key: MappingKey) -> StoredMappingRef | None:
        """Look up by ``key.stable_id``; connection checks belong to the caller."""
        ...

    def save(self, record: MappingRecord, *, overwrite: bool) -> StoredMappingRef:
        """Raise ``MappingConflictError`` when a mapping exists and ``overwrite`` is false."""
        ...

    def entries(self) -> Sequence[StoredMappingRef]: ...


class HotplugWatcher(Protocol):
    def snapshot(self) -> DiscoverySnapshot: ...

    def poll(self) -> HotplugChange: ...
