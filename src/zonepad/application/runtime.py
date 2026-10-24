from __future__ import annotations

import logging

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
        axis_ranges: dict[str, AxisRange],
        trigger_ranges: dict[str, TriggerRange],
    ) -> None:
        self._session = session
        self._profile = profile
        self._publisher = publisher
        self._axis_ranges = axis_ranges
        self._trigger_ranges = trigger_ranges

    def process_once(self, timeout_s: float = 0.05) -> CalibratedFrame | None:
        raw = self._session.read(timeout_s)
        if raw is None:
            return None
        normalized = normalize_frame(raw, self._axis_ranges, self._trigger_ranges)
        calibrated = apply_profile(normalized, self._profile)
        self._publisher.publish(calibrated)
        return calibrated

    def run(self, timeout_s: float = 0.05) -> None:
        try:
            while True:
                self.process_once(timeout_s)
        except DeviceDisconnectedError:
            logger.info(
                "device disconnected", extra={"device_id": self._session.device_info.device_id}
            )
            raise
        finally:
            self._session.close()
            self._publisher.close()


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
