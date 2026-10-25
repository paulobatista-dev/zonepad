from __future__ import annotations

import contextlib
import fcntl
import os
from pathlib import Path

import pytest
from conftest import IoGuardFactory


def test_guard_allows_io_under_the_root(tmp_path: Path, forbid_io_outside: IoGuardFactory) -> None:
    (tmp_path / "inside.txt").write_text("ok\n")

    with forbid_io_outside(tmp_path) as guard:
        assert (tmp_path / "inside.txt").read_text() == "ok\n"
        assert [entry.name for entry in tmp_path.iterdir()] == ["inside.txt"]

    assert guard.accessed


@pytest.mark.parametrize("via", ["open", "os.open", "read_text", "scandir"])
def test_guard_records_io_outside_the_root(
    tmp_path: Path, forbid_io_outside: IoGuardFactory, via: str
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret\n")

    with pytest.raises(AssertionError, match="I/O outside"), forbid_io_outside(root):
        if via == "open":
            with open(outside, encoding="utf-8") as stream:
                stream.read()
        elif via == "os.open":
            os.close(os.open(outside, os.O_RDONLY))
        elif via == "read_text":
            outside.read_text()
        else:
            list(os.scandir(tmp_path))


def test_guard_records_any_ioctl(tmp_path: Path, forbid_io_outside: IoGuardFactory) -> None:
    target = tmp_path / "file"
    target.write_text("x")
    fd = os.open(target, os.O_RDONLY)
    try:
        with (
            pytest.raises(AssertionError, match="fcntl.ioctl"),
            forbid_io_outside(tmp_path),
            contextlib.suppress(OSError),  # TCGETS on a regular file fails
        ):
            fcntl.ioctl(fd, 0x5401, bytearray(64))
    finally:
        os.close(fd)
