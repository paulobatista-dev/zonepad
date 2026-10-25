from __future__ import annotations

import fcntl
import os
import struct
import sys
from pathlib import Path

from zonepad.domain.errors import UnsupportedPlatformError
from zonepad.domain.input import CalibratedFrame


class LinuxUinputPublisher:
    """Publisher boundary for a corrected virtual controller.

    Device registration is explicit and follows the Linux uinput ABI. A clear
    filesystem error is raised when the uinput node is unavailable.
    """

    UI_SET_EVBIT = 1_074_025_828
    UI_SET_KEYBIT = 1_074_025_829
    UI_SET_ABSBIT = 1_074_025_831
    UI_DEV_CREATE = 21_761
    UI_DEV_DESTROY = 21_762
    EV_SYN = 0
    EV_KEY = 1
    EV_ABS = 3
    SYN_REPORT = 0
    ABS_CODES = {"lx": 0, "ly": 1, "rx": 3, "ry": 4, "lt": 2, "rt": 5}
    ABS_MINIMUMS = {2: 0, 5: 0}
    BUTTON_CODES = {
        "button_south": 304,
        "button_east": 305,
        "button_north": 307,
        "button_west": 308,
    }
    EVENT_STRUCT = struct.Struct("llHHi")

    def __init__(
        self, path: Path | None = None, device_name: str = "ZonaPad Virtual Controller"
    ) -> None:
        if not sys.platform.startswith("linux"):
            raise UnsupportedPlatformError("uinput backend requires Linux")
        device_path = Path(path) if path is not None else Path("/dev/uinput")
        if not device_path.exists():
            raise FileNotFoundError(device_path)
        self._path = device_path
        self._fd = os.open(device_path, os.O_WRONLY | os.O_NONBLOCK)
        self._closed = False
        try:
            fcntl.ioctl(self._fd, self.UI_SET_EVBIT, self.EV_ABS)
            fcntl.ioctl(self._fd, self.UI_SET_EVBIT, self.EV_KEY)
            for code in self.ABS_CODES.values():
                fcntl.ioctl(self._fd, self.UI_SET_ABSBIT, code)
            for code in self.BUTTON_CODES.values():
                fcntl.ioctl(self._fd, self.UI_SET_KEYBIT, code)
            self._write_device_definition(device_name)
            fcntl.ioctl(self._fd, self.UI_DEV_CREATE)
        except Exception:
            os.close(self._fd)
            raise

    def _write_device_definition(self, device_name: str) -> None:
        name = device_name.encode("utf-8")[:79].ljust(80, b"\0")
        # struct uinput_user_dev: name, bus/vendor/product/version, ff_max,
        # then 64-element absmax/min/fuzz/flat arrays.
        header = struct.pack("<80sHHHHH2x", name, 0x03, 0x1234, 0x0001, 1, 0)
        absmax = [32767] * 64
        absmin = [-32767] * 64
        for code, minimum in self.ABS_MINIMUMS.items():
            absmin[code] = minimum
        absfuzz = [0] * 64
        absflat = [0] * 64
        os.write(
            self._fd,
            header
            + struct.pack("<64i", *absmax)
            + struct.pack("<64i", *absmin)
            + struct.pack("<64i", *absfuzz)
            + struct.pack("<64i", *absflat),
        )

    def publish(self, frame: CalibratedFrame) -> None:
        if self._closed:
            raise RuntimeError("publisher is closed")
        for name, code in self.ABS_CODES.items():
            if name in frame.axes:
                value = int(max(-1.0, min(1.0, frame.axes[name])) * 32767)
            elif name in frame.triggers:
                value = int(max(0.0, min(1.0, frame.triggers[name])) * 32767)
            else:
                continue
            os.write(self._fd, self.EVENT_STRUCT.pack(0, 0, self.EV_ABS, code, value))
        for name, code in self.BUTTON_CODES.items():
            value = int(name in frame.buttons)
            os.write(self._fd, self.EVENT_STRUCT.pack(0, 0, self.EV_KEY, code, value))
        os.write(self._fd, self.EVENT_STRUCT.pack(0, 0, self.EV_SYN, self.SYN_REPORT, 0))

    def close(self) -> None:
        if not self._closed:
            try:
                fcntl.ioctl(self._fd, self.UI_DEV_DESTROY)
            finally:
                os.close(self._fd)
                self._closed = True


UinputPublisher = LinuxUinputPublisher
