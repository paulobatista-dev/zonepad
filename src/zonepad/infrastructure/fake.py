from __future__ import annotations

from collections.abc import Iterable, Sequence

from zonepad.application.ports import DeviceBackend, DeviceSession, NormalizationConfig
from zonepad.domain.device import DeviceInfo
from zonepad.domain.errors import DeviceDisconnectedError, DeviceNotFoundError, InvalidMappingError
from zonepad.domain.input import RawFrame


class FakeSession(DeviceSession):
    def __init__(
        self,
        device_info: DeviceInfo,
        frames: Iterable[RawFrame],
        disconnect_after: bool = False,
        normalization_config: NormalizationConfig | None = None,
    ) -> None:
        self._device_info = device_info
        self._frames = iter(frames)
        self._disconnect_after = disconnect_after
        self._normalization_config = normalization_config
        self.closed = False

    @property
    def device_info(self) -> DeviceInfo:
        return self._device_info

    @property
    def normalization_config(self) -> NormalizationConfig:
        if self._normalization_config is None:
            raise InvalidMappingError("fake session requires a normalization config")
        return self._normalization_config

    def read(self, timeout_s: float) -> RawFrame | None:
        del timeout_s
        if self.closed:
            raise DeviceDisconnectedError(self._device_info.device_id)
        try:
            return next(self._frames)
        except StopIteration:
            if self._disconnect_after:
                raise DeviceDisconnectedError(self._device_info.device_id) from None
            return None

    def close(self) -> None:
        self.closed = True


class FakeBackend(DeviceBackend):
    def __init__(
        self,
        devices: Sequence[tuple[DeviceInfo, Iterable[RawFrame]]],
        normalization_config: NormalizationConfig | None = None,
    ) -> None:
        self._sessions = {
            info.device_id: FakeSession(info, frames, normalization_config=normalization_config)
            for info, frames in devices
        }

    def list_devices(self) -> Sequence[DeviceInfo]:
        return tuple(session.device_info for session in self._sessions.values())

    def open(self, device_id: str) -> DeviceSession:
        try:
            return self._sessions[device_id]
        except KeyError as exc:
            raise DeviceNotFoundError(device_id) from exc
