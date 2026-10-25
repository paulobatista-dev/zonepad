from __future__ import annotations

import os
import select
import struct
import sys
from pathlib import Path
from typing import BinaryIO

from zonepad.application.ports import DeviceBackend, DeviceSession
from zonepad.domain.device import DeviceInfo
from zonepad.domain.errors import (
    DeviceDisconnectedError,
    DeviceNotFoundError,
    UnsupportedPlatformError,
)
from zonepad.domain.input import RawFrame

EVENT_STRUCT = struct.Struct("llHHI")
EV_KEY = 0x01
EV_ABS = 0x03


class EvdevSession(DeviceSession):
    def __init__(
        self,
        device_info: DeviceInfo,
        path: Path,
        axis_codes: dict[int, str],
        trigger_codes: dict[int, str],
    ) -> None:
        self._device_info = device_info
        self._path = path
        self._axis_codes = axis_codes
        self._trigger_codes = trigger_codes
        self._stream: BinaryIO = os.fdopen(
            os.open(path, os.O_RDONLY | os.O_NONBLOCK), "rb", buffering=0
        )
        self._axes: dict[str, int] = {}
        self._triggers: dict[str, int] = {}
        self._buttons: set[str] = set()

    @property
    def device_info(self) -> DeviceInfo:
        return self._device_info

    def read(self, timeout_s: float) -> RawFrame | None:
        ready, _, _ = select.select([self._stream], [], [], max(0.0, timeout_s))
        if not ready:
            return None
        try:
            payload = self._stream.read(EVENT_STRUCT.size)
        except OSError as exc:
            raise DeviceDisconnectedError(str(self._path)) from exc
        if not payload:
            raise DeviceDisconnectedError(str(self._path))
        if len(payload) != EVENT_STRUCT.size:
            return None
        seconds, micros, event_type, code, value = EVENT_STRUCT.unpack(payload)
        if event_type == EV_ABS:
            name = self._axis_codes.get(code)
            if name:
                self._axes[name] = value
        elif event_type == EV_KEY:
            name = f"button_{code}"
            if value:
                self._buttons.add(name)
            else:
                self._buttons.discard(name)
        trigger = self._trigger_codes.get(code)
        if trigger:
            self._triggers[trigger] = value
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
        axis_codes: dict[int, str] | None = None,
        trigger_codes: dict[int, str] | None = None,
    ) -> None:
        if not sys.platform.startswith("linux"):
            raise UnsupportedPlatformError("evdev backend requires Linux")
        self._directory = (
            Path(device_directory) if device_directory is not None else Path("/dev/input")
        )
        self._axis_codes = axis_codes or {0: "lx", 1: "ly", 2: "rx", 3: "ry"}
        self._trigger_codes = trigger_codes or {4: "lt", 5: "rt"}

    def list_devices(self) -> tuple[DeviceInfo, ...]:
        if not self._directory.exists():
            return ()
        return tuple(
            DeviceInfo(path.name, path.name, capabilities=frozenset({"evdev"}))
            for path in sorted(self._directory.glob("event*"))
        )

    def open(self, device_id: str) -> DeviceSession:
        path = self._directory / device_id
        if not path.exists():
            raise DeviceNotFoundError(device_id)
        return EvdevSession(
            DeviceInfo(device_id, device_id, capabilities=frozenset({"evdev"})),
            path,
            self._axis_codes,
            self._trigger_codes,
        )


EvdevBackend = LinuxEvdevBackend
