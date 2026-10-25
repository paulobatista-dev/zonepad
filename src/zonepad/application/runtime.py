from __future__ import annotations

import logging
import math
import time
from collections.abc import Callable, Mapping

from zonepad.domain.calibration import apply_profile
from zonepad.domain.errors import DeviceDisconnectedError
from zonepad.domain.input import CalibratedFrame
from zonepad.domain.normalization import AxisRange, TriggerRange, normalize_frame
from zonepad.domain.profile import CalibrationProfile

from .ports import DeviceBackend, DeviceSession, FramePublisher, ProfileStore

logger = logging.getLogger(__name__)


class RuntimeProcessor:
    """Processes one raw sample at a time; callers decide threading/backpressure."""

    def __init__(
        self,
        session: DeviceSession,
        profile: CalibrationProfile,
        publisher: FramePublisher,
        axis_ranges: Mapping[str, AxisRange],
        trigger_ranges: Mapping[str, TriggerRange],
    ) -> None:
        self._session = session
        self._profile = profile
        self._publisher = publisher
        self._axis_ranges = axis_ranges
        self._trigger_ranges = trigger_ranges
        self._closed = False

    def process_once(self, timeout_s: float = 0.05) -> CalibratedFrame | None:
        raw = self._session.read(timeout_s)
        if raw is None:
            return None
        normalized = normalize_frame(raw, self._axis_ranges, self._trigger_ranges)
        calibrated = apply_profile(normalized, self._profile)
        self._publisher.publish(calibrated)
        return calibrated

    def run(
        self,
        timeout_s: float = 0.05,
        duration_s: float | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if duration_s is not None and (not math.isfinite(duration_s) or duration_s <= 0):
            raise ValueError("duration_s must be a finite positive value")
        deadline = monotonic() + duration_s if duration_s is not None else None
        try:
            while True:
                if deadline is None:
                    self.process_once(timeout_s)
                    continue
                remaining_s = deadline - monotonic()
                if remaining_s <= 0:
                    break
                self.process_once(min(timeout_s, remaining_s))
        except DeviceDisconnectedError:
            logger.info(
                "device disconnected", extra={"device_id": self._session.device_info.device_id}
            )
            raise
        finally:
            self.close()

    def close(self) -> None:
        """Release session and publisher after a runtime terminates."""
        if self._closed:
            return
        self._closed = True
        try:
            self._session.close()
        finally:
            self._publisher.close()


def build_runtime(
    backend: DeviceBackend,
    store: ProfileStore,
    publisher: FramePublisher,
    device_id: str,
    profile_id: str,
    timeout_s: float,
) -> RuntimeProcessor:
    """Compose a runtime from ports after validating its public timeout."""
    if not math.isfinite(timeout_s) or timeout_s <= 0:
        raise ValueError("timeout_s must be a finite positive value")
    session: DeviceSession | None = None
    try:
        profile = store.load(profile_id)
        session = backend.open(device_id)
        config = session.normalization_config
        return RuntimeProcessor(session, profile, publisher, config.axes, config.triggers)
    except Exception:
        try:
            if session is not None:
                session.close()
        except Exception:
            logger.warning("failed to close device after composition error", exc_info=True)
        try:
            publisher.close()
        except Exception:
            logger.warning("failed to close publisher after composition error", exc_info=True)
        raise


def run_saved_profile(
    backend: DeviceBackend,
    profile_store: ProfileStore,
    publisher: FramePublisher,
    device_id: str,
    profile_id: str,
    axis_ranges: dict[str, AxisRange],
    trigger_ranges: dict[str, TriggerRange],
    timeout_s: float = 0.05,
) -> None:
    """Open a physical device, apply a stored profile and publish corrected frames."""
    profile = profile_store.load(profile_id)
    session = backend.open(device_id)
    RuntimeProcessor(session, profile, publisher, axis_ranges, trigger_ranges).run(timeout_s)
