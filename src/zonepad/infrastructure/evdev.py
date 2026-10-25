from __future__ import annotations

import os
import re
import select
import struct
import sys
import time
from pathlib import Path
from typing import BinaryIO

from zonepad.application.ports import DeviceBackend, DeviceSession, NormalizationConfig
from zonepad.domain.device import DeviceInfo
from zonepad.domain.errors import (
    DeviceDisconnectedError,
    DeviceNotFoundError,
    InvalidMappingError,
    UnsupportedPlatformError,
)
from zonepad.domain.input import RawFrame

from .mapping import DeviceMapping

EVENT_STRUCT = struct.Struct("@llHHi")
EV_SYN = 0x00
EV_KEY = 0x01
EV_ABS = 0x03
SYN_REPORT = 0x00


class EvdevSession(DeviceSession):
    def __init__(
        self,
        device_info: DeviceInfo,
        path: Path,
        mapping: DeviceMapping,
    ) -> None:
        self._device_info = device_info
        self._path = path
        self._mapping = mapping
        self._stream: BinaryIO = os.fdopen(
            os.open(path, os.O_RDONLY | os.O_NONBLOCK), "rb", buffering=0
        )
        self._axes: dict[str, int] = {}
        self._triggers: dict[str, int] = {}
        self._buttons: set[str] = set()
        # Linux evdev timestamps default to CLOCK_REALTIME.  Use a host
        # monotonic sample at SYN_REPORT until EVIOCSCLOCKID is added.
        self._timestamp_mode = "read_monotonic"

    @property
    def device_info(self) -> DeviceInfo:
        return self._device_info

    @property
    def normalization_config(self) -> NormalizationConfig:
        return self._mapping

    def read(self, timeout_s: float) -> RawFrame | None:
        deadline = time.monotonic() + max(0.0, timeout_s)
        while True:
            remaining = max(0.0, deadline - time.monotonic())
            ready, _, _ = select.select([self._stream], [], [], remaining)
            if not ready:
                return None
            try:
                payload = self._stream.read(EVENT_STRUCT.size)
            except OSError as exc:
                raise DeviceDisconnectedError(str(self._path)) from exc
            if not payload:
                raise DeviceDisconnectedError(str(self._path))
            if len(payload) != EVENT_STRUCT.size:
                raise DeviceDisconnectedError(f"truncated input event from {self._path}")
            seconds, micros, event_type, code, value = EVENT_STRUCT.unpack(payload)
            frame = self._apply_event(seconds, micros, event_type, code, value)
            if frame is not None:
                return frame

    def _apply_event(
        self, seconds: int, micros: int, event_type: int, code: int, value: int
    ) -> RawFrame | None:
        if event_type == EV_ABS:
            axis_name = self._mapping.axis_codes.get(code)
            trigger_name = self._mapping.trigger_codes.get(code)
            if axis_name is not None:
                self._axes[axis_name] = value
            elif trigger_name is not None:
                self._triggers[trigger_name] = value
            return None
        if event_type == EV_KEY:
            button_name = self._mapping.button_codes.get(code)
            if button_name is not None:
                if value:
                    self._buttons.add(button_name)
                else:
                    self._buttons.discard(button_name)
            return None
        if event_type != EV_SYN or code != SYN_REPORT:
            return None
        if getattr(self, "_timestamp_mode", "event_timeval") == "read_monotonic":
            timestamp_ns = time.monotonic_ns()
        else:
            timestamp_ns = int(seconds) * 1_000_000_000 + int(micros) * 1_000
        return RawFrame(
            self._device_info.device_id,
            timestamp_ns,
            self._axes,
            self._triggers,
            frozenset(self._buttons),
        )

    def close(self) -> None:
        self._stream.close()


class LinuxEvdevBackend(DeviceBackend):
    """Minimal Linux evdev adapter; parsing maps are supplied by composition code."""

    def __init__(
        self,
        device_directory: Path | None = None,
        mapping: DeviceMapping | None = None,
    ) -> None:
        if not sys.platform.startswith("linux"):
            raise UnsupportedPlatformError("evdev backend requires Linux")
        self._directory = (
            Path(device_directory) if device_directory is not None else Path("/dev/input")
        )
        self._mapping = mapping

    def list_devices(self) -> tuple[DeviceInfo, ...]:
        if not self._directory.exists():
            return ()
        return tuple(
            DeviceInfo(path.name, path.name, capabilities=frozenset({"evdev"}))
            for path in sorted(self._directory.glob("event*"))
        )

    def open(self, device_id: str) -> DeviceSession:
        if self._mapping is None:
            raise InvalidMappingError("mapping is required to open an evdev device")
        if re.fullmatch(r"event[0-9]+", device_id) is None:
            raise DeviceNotFoundError(device_id)
        path = self._directory / device_id
        if not path.exists():
            raise DeviceNotFoundError(device_id)
        return EvdevSession(
            DeviceInfo(device_id, device_id, capabilities=frozenset({"evdev"})),
            path,
            self._mapping,
        )


EvdevBackend = LinuxEvdevBackend
