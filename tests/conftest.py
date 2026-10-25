"""Shared fixtures.

``forbid_io_outside(root)`` activates an audit hook (``sys.addaudithook``) through
a ``ContextVar``: inside the ``with`` block every ``open``/``os.open``/
``Path.read_text``/``os.scandir``/``os.listdir`` must target a path under
``root`` after ``realpath``, and any ``fcntl.ioctl`` is a violation.  Violations
are recorded (not raised inside the code under test) and asserted on exit.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

# The versioned sysfs tree has cyclic directory symlinks (``inputM/device -> ../..``),
# exactly like the real sysfs; collection must not walk into it.
collect_ignore = ["fixtures"]


@dataclass
class IoGuard:
    root: str
    violations: list[str] = field(default_factory=list)
    accessed: list[str] = field(default_factory=list)
    busy: bool = False


_ACTIVE_GUARD: ContextVar[IoGuard | None] = ContextVar("zonepad_io_guard", default=None)
_PATH_EVENTS = frozenset({"open", "os.scandir", "os.listdir"})


def _audit(event: str, args: tuple[Any, ...]) -> None:
    guard = _ACTIVE_GUARD.get()
    if guard is None or guard.busy:
        return
    if event == "fcntl.ioctl":
        guard.violations.append(f"fcntl.ioctl request={args[1]!r}")
        return
    if event not in _PATH_EVENTS:
        return
    target = args[0] if args else "."
    if target is None:
        target = "."
    if isinstance(target, int):
        return
    guard.busy = True
    try:
        resolved = os.path.realpath(os.fsdecode(os.fspath(target)))
        if resolved == guard.root or resolved.startswith(guard.root + os.sep):
            guard.accessed.append(resolved)
        else:
            guard.violations.append(f"{event} {resolved}")
    finally:
        guard.busy = False


sys.addaudithook(_audit)

IoGuardFactory = Callable[[Path], AbstractContextManager[IoGuard]]


@pytest.fixture
def forbid_io_outside() -> IoGuardFactory:
    @contextmanager
    def guard(root: Path) -> Iterator[IoGuard]:
        state = IoGuard(os.path.realpath(root))
        token = _ACTIVE_GUARD.set(state)
        try:
            yield state
        finally:
            _ACTIVE_GUARD.reset(token)
        assert not state.violations, f"I/O outside {state.root}: {state.violations}"

    return guard
