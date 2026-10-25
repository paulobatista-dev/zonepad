"""Helpers for CLI tests over synthetic sysfs trees (no /sys, /dev/input or /dev/uinput)."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path

from discovery_fakes import FakeAbsInfoReader, FakeClock
from sysfs_builder import SysfsNode, build_sysfs

from zonepad.domain.discovery import AbsInfo
from zonepad.infrastructure.catalog import load_builtin_catalog
from zonepad.infrastructure.sysfs import SysfsInputScanner
from zonepad.interface.device_cli import CliDependencies

BUILTIN_CATALOG = load_builtin_catalog()
FIXED_NOW = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)


@dataclass
class Workspace:
    """A synthetic sysfs tree plus devices/profiles directories under ``tmp_path``."""

    root: Path
    sysfs: Path
    devices: Path
    absinfo: dict[str, Mapping[int, AbsInfo]] = field(default_factory=dict)
    denied: set[str] = field(default_factory=set)
    access: dict[str, str] = field(default_factory=dict)
    answers: list[bool | None] = field(default_factory=list)
    reader: FakeAbsInfoReader | None = None
    clock: FakeClock = field(default_factory=FakeClock)

    def paths(self) -> list[str]:
        return ["--sysfs-root", str(self.sysfs), "--devices-dir", str(self.devices)]

    def deps(self, **overrides: object) -> CliDependencies:
        self.reader = FakeAbsInfoReader(dict(self.absinfo), frozenset(self.denied))
        reader = self.reader

        def confirm(question: str) -> bool | None:
            return self.answers.pop(0) if self.answers else None

        base = CliDependencies(
            scanner=lambda root: SysfsInputScanner(root),
            absinfo_reader=lambda: reader,
            verify_access=lambda node: self.access.get(node, "ok"),
            builtin_catalog=lambda: BUILTIN_CATALOG,
            clock=lambda: self.clock,
            now=lambda: FIXED_NOW,
            confirm=confirm,
        )
        return replace(base, **overrides)  # type: ignore[arg-type]


def workspace(tmp_path: Path, nodes: Iterable[SysfsNode]) -> Workspace:
    sysfs = build_sysfs(tmp_path / "sys", list(nodes))
    return Workspace(tmp_path, sysfs, tmp_path / "devices")


def json_lines(text: str) -> list[dict[str, object]]:
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def files_under(path: Path) -> list[str]:
    if not path.exists():
        return []
    return sorted(str(item.relative_to(path)) for item in path.rglob("*") if item.is_file())
