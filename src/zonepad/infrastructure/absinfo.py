"""``EVIOCGABS`` reader: ranges of one evdev node without reading events (spec RF4, P1).

The node is opened ``O_RDONLY | O_NONBLOCK | O_CLOEXEC`` only for the ioctls and
always closed in ``finally``; ``read()`` is never called.  Opening the node may
trigger the driver ``open`` briefly (INFERENCE, not verified on hardware).
"""

from __future__ import annotations

import errno
import fcntl
import logging
import os
import platform
import re
import struct
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from types import MappingProxyType

from zonepad.domain.discovery import AbsInfo, absinfo_from_kernel
from zonepad.domain.errors import (
    DeviceAccessDeniedError,
    DeviceNotFoundError,
    UnsupportedPlatformError,
)

from .linux_input_policy import ABS_MAX

LOGGER = logging.getLogger("zonepad.absinfo")

# struct input_absinfo { __s32 value, minimum, maximum, fuzz, flat, resolution; }
# (include/uapi/linux/input.h:93-100)
ABSINFO_STRUCT = struct.Struct("=6i")

# asm-generic/ioctl.h layout (x86_64, aarch64).  powerpc, mips and sparc encode
# ioctls differently; the number is computed, never hard-coded.
_IOC_NRSHIFT = 0
_IOC_TYPESHIFT = 8
_IOC_SIZESHIFT = 16
_IOC_DIRSHIFT = 30
_IOC_READ = 2
_EVDEV_IOC_TYPE = ord("E")
_EVIOCGABS_BASE_NR = 0x40

# Machines whose ioctl encoding follows asm-generic/ioctl.h (platform.machine()).
ASM_GENERIC_IOCTL_MACHINES = frozenset(
    {"x86_64", "amd64", "i386", "i486", "i586", "i686", "aarch64", "arm64", "riscv64"}
)
_EVENT_NODE = re.compile(r"event[0-9]+", re.ASCII)
_DENIED_ERRNOS = frozenset({errno.EACCES, errno.EPERM})
_GONE_ERRNOS = frozenset({errno.ENODEV, errno.ENOENT, errno.ENXIO})

Opener = Callable[[str, int], int]
Ioctl = Callable[[int, int, bytearray], object]
Closer = Callable[[int], None]


def _ior(ioc_type: int, number: int, size: int) -> int:
    return (
        (_IOC_READ << _IOC_DIRSHIFT)
        | (size << _IOC_SIZESHIFT)
        | (ioc_type << _IOC_TYPESHIFT)
        | (number << _IOC_NRSHIFT)
    )


def eviocgabs(code: int) -> int:
    """``EVIOCGABS(code) = _IOR('E', 0x40 + code, struct input_absinfo)``."""
    if not 0 <= code <= ABS_MAX:
        raise ValueError(f"ABS code out of range: {code}")
    return _ior(_EVDEV_IOC_TYPE, _EVIOCGABS_BASE_NR + code, ABSINFO_STRUCT.size)


def is_asm_generic_machine(machine: str) -> bool:
    """32-bit ARM reports ``armv6l``/``armv7l``/``armv8l``; all use asm-generic."""
    normalized = machine.lower()
    return normalized in ASM_GENERIC_IOCTL_MACHINES or normalized.startswith("armv")


def _ioctl(fd: int, request: int, buffer: bytearray) -> object:
    return fcntl.ioctl(fd, request, buffer, True)


class EvdevAbsInfoReader:
    """``AbsInfoReader`` backed by ``/dev/input/eventN`` (opener and ioctl injectable)."""

    def __init__(
        self,
        dev_root: Path = Path("/dev/input"),
        *,
        opener: Opener = os.open,
        ioctl: Ioctl = _ioctl,
        closer: Closer = os.close,
        machine: Callable[[], str] = platform.machine,
    ) -> None:
        self._dev_root = dev_root
        self._opener = opener
        self._ioctl = ioctl
        self._closer = closer
        self._machine = machine

    def read_absinfo(self, event_node: str, codes: Sequence[int]) -> Mapping[int, AbsInfo]:
        if not _EVENT_NODE.fullmatch(event_node):
            raise DeviceNotFoundError(f"invalid input node: {event_node!r}")
        machine = self._machine()
        if not is_asm_generic_machine(machine):
            raise UnsupportedPlatformError(
                f"EVIOCGABS encoding is only verified for asm-generic ioctls, not {machine!r}"
            )
        path = self._dev_root / event_node
        flags = os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC
        try:
            fd = self._opener(str(path), flags)
        except PermissionError as exc:
            raise DeviceAccessDeniedError(event_node) from exc
        except FileNotFoundError as exc:
            raise DeviceNotFoundError(f"input node not found: {path}") from exc
        try:
            result: dict[int, AbsInfo] = {}
            for code in sorted(set(codes)):
                absinfo = self._read_one(fd, event_node, code)
                if absinfo is not None:
                    result[code] = absinfo
            return MappingProxyType(result)
        finally:
            self._closer(fd)

    def _read_one(self, fd: int, event_node: str, code: int) -> AbsInfo | None:
        buffer = bytearray(ABSINFO_STRUCT.size)
        try:
            self._ioctl(fd, eviocgabs(code), buffer)
        except OSError as exc:
            if exc.errno in _DENIED_ERRNOS:
                raise DeviceAccessDeniedError(event_node) from exc
            if exc.errno in _GONE_ERRNOS:
                raise DeviceNotFoundError(f"input node disappeared: {event_node}") from exc
            LOGGER.warning("EVIOCGABS failed node=%s code=%d errno=%s", event_node, code, exc.errno)
            return None
        try:
            return absinfo_from_kernel(*ABSINFO_STRUCT.unpack(buffer))
        except ValueError:
            LOGGER.warning("degenerate absinfo ignored node=%s code=%d", event_node, code)
            return None
