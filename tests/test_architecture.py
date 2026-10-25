from __future__ import annotations

import ast
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[1] / "src" / "zonepad"
DOMAIN_FORBIDDEN = frozenset(
    {"os", "pathlib", "time", "evdev", "subprocess", "fcntl", "select", "struct"}
)
DOMAIN_FORBIDDEN_PACKAGES = ("zonepad.infrastructure", "zonepad.interface", "zonepad.application")


def _imports(path: Path, package: str) -> list[str]:
    """Absolute module names imported by ``path`` (relative imports resolved)."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                parts = package.split(".")
                base = ".".join(parts[: len(parts) - node.level + 1])
                module = f"{base}.{node.module}" if node.module else base
            else:
                module = node.module or ""
            names.append(module)
    return names


def _modules(layer: str) -> list[Path]:
    return sorted((SOURCE / layer).glob("*.py"))


@pytest.mark.parametrize("path", _modules("domain"), ids=lambda path: path.name)
def test_domain_imports_no_os_io_or_outer_layers(path: Path) -> None:
    imported = _imports(path, "zonepad.domain")

    forbidden = [
        name
        for name in imported
        if name.split(".")[0] in DOMAIN_FORBIDDEN or name.startswith(DOMAIN_FORBIDDEN_PACKAGES)
    ]
    assert forbidden == []


@pytest.mark.parametrize("path", _modules("application"), ids=lambda path: path.name)
def test_application_does_not_import_infrastructure_or_interface(path: Path) -> None:
    imported = _imports(path, "zonepad.application")

    assert [
        n for n in imported if n.startswith(("zonepad.infrastructure", "zonepad.interface"))
    ] == []


def test_relative_imports_are_resolved() -> None:
    assert "zonepad.domain.identity" in _imports(
        SOURCE / "domain" / "discovery.py", "zonepad.domain"
    )


def test_only_absinfo_and_uinput_adapters_call_ioctl() -> None:
    offenders = []
    for path in sorted(SOURCE.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        if "ioctl(" in text and path.name not in {"absinfo.py", "uinput.py"}:
            offenders.append(path.name)
    assert offenders == []
