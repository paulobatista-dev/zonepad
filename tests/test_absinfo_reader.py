from __future__ import annotations

import errno
import os
import struct
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from zonepad.domain.discovery import AbsInfo
from zonepad.domain.errors import DeviceAccessDeniedError, DeviceNotFoundError
from zonepad.infrastructure.absinfo import ABSINFO_STRUCT, EvdevAbsInfoReader, eviocgabs

FD = 42


@dataclass
class FakeEvdevNode:
    """Records opener/ioctl/close calls; answers EVIOCGABS from a table."""

    table: dict[int, tuple[int, int, int, int, int, int]]
    open_error: OSError | None = None
    ioctl_errors: dict[int, OSError] = field(default_factory=dict)
    opened: list[tuple[str, int]] = field(default_factory=list)
    requests: list[int] = field(default_factory=list)
    closed: list[int] = field(default_factory=list)

    def opener(self, path: str, flags: int) -> int:
        self.opened.append((path, flags))
        if self.open_error is not None:
            raise self.open_error
        return FD

    def ioctl(self, fd: int, request: int, buffer: bytearray) -> object:
        assert fd == FD
        self.requests.append(request)
        code = request - eviocgabs(0)
        if code in self.ioctl_errors:
            raise self.ioctl_errors[code]
        buffer[:] = struct.pack("=6i", *self.table[code])
        return 0

    def closer(self, fd: int) -> None:
        self.closed.append(fd)

    def reader(self) -> EvdevAbsInfoReader:
        return EvdevAbsInfoReader(
            Path("/dev/input"), opener=self.opener, ioctl=self.ioctl, closer=self.closer
        )


def test_ioctl_number_follows_the_ior_formula() -> None:
    assert ABSINFO_STRUCT.size == 24
    for code in (0, 1, 5, 0x3F):
        assert eviocgabs(code) == 0x80184540 + code
    with pytest.raises(ValueError):
        eviocgabs(0x40)


def test_reads_struct_fields_in_kernel_order_and_closes() -> None:
    node = FakeEvdevNode({0: (12, -32768, 32767, 16, 128, 3), 2: (0, 0, 1023, 0, 0, 0)})

    result = node.reader().read_absinfo("event3", [2, 0, 0])

    assert result[0] == AbsInfo(-32768, 32767, 16, 128, 3, value_at_probe=12)
    assert result[2] == AbsInfo(0, 1023, 0, 0, 0, value_at_probe=0)
    assert node.opened == [("/dev/input/event3", os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)]
    assert node.requests == [0x80184540, 0x80184542]
    assert node.closed == [FD]


def test_opens_exactly_the_requested_node_and_never_reads() -> None:
    node = FakeEvdevNode({0: (0, 0, 255, 0, 0, 0)})
    reader = node.reader()

    reader.read_absinfo("event17", [0])

    assert [path for path, _ in node.opened] == ["/dev/input/event17"]
    assert not hasattr(reader, "read")


def test_permission_denied_on_open_is_access_denied() -> None:
    node = FakeEvdevNode({}, open_error=PermissionError(errno.EACCES, "denied"))

    with pytest.raises(DeviceAccessDeniedError) as raised:
        node.reader().read_absinfo("event3", [0])

    assert raised.value.event_node == "event3"
    assert node.closed == []


def test_missing_node_is_device_not_found() -> None:
    node = FakeEvdevNode({}, open_error=FileNotFoundError(errno.ENOENT, "gone"))

    with pytest.raises(DeviceNotFoundError):
        node.reader().read_absinfo("event3", [0])


def test_close_happens_even_when_the_device_disappears_mid_read() -> None:
    node = FakeEvdevNode({0: (0, 0, 255, 0, 0, 0)}, ioctl_errors={1: OSError(errno.ENODEV, "x")})

    with pytest.raises(DeviceNotFoundError):
        node.reader().read_absinfo("event3", [0, 1])

    assert node.closed == [FD]


def test_unsupported_and_degenerate_codes_are_skipped(caplog: pytest.LogCaptureFixture) -> None:
    node = FakeEvdevNode(
        {0: (0, 0, 255, 0, 0, 0), 1: (0, 0, 0, 0, 0, 0)},
        ioctl_errors={2: OSError(errno.EINVAL, "invalid")},
    )

    result = node.reader().read_absinfo("event3", [0, 1, 2])

    assert set(result) == {0}
    assert "degenerate absinfo" in caplog.text
    assert "EVIOCGABS failed" in caplog.text
    assert node.closed == [FD]


def test_negative_fields_are_discarded() -> None:
    node = FakeEvdevNode({0: (0, 0, 255, -1, -2, -3)})

    info = node.reader().read_absinfo("event3", [0])[0]

    assert (info.fuzz, info.flat, info.resolution) == (None, None, None)


@pytest.mark.parametrize("node_name", ["../event3", "event3/../../x", "js0", ""])
def test_rejects_anything_but_an_event_node(node_name: str) -> None:
    node = FakeEvdevNode({})

    with pytest.raises(DeviceNotFoundError):
        node.reader().read_absinfo(node_name, [0])

    assert node.opened == []
