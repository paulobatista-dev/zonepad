from __future__ import annotations

import ast
import json
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _project_config() -> dict[str, object]:
    with (ROOT / "pyproject.toml").open("rb") as project_file:
        return tomllib.load(project_file)["project"]


def test_runtime_dependencies_are_empty_and_gui_is_optional() -> None:
    project = _project_config()
    assert project["dependencies"] == []
    optional = project["optional-dependencies"]
    assert optional["gui"] == ["PySide6>=6.7"]
    assert {"pytest", "pytest-cov", "ruff", "mypy", "virtualenv", "build"} <= {
        requirement.split(">", maxsplit=1)[0].split("=", maxsplit=1)[0]
        for requirement in optional["dev"]
    }


def test_project_version_python_range_and_console_scripts_are_declared() -> None:
    project = _project_config()
    assert project["version"] == "0.1.0"
    assert project["requires-python"] == ">=3.15,<3.16"
    assert project["scripts"] == {
        "zonepad": "zonepad.interface.cli:main",
        "zonepad-gui": "zonepad.interface.gui:run",
    }


def test_isolated_build_backend_has_an_exact_development_constraint() -> None:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    build_requirements = config["build-system"]["requires"]
    assert any(requirement.lower().startswith("setuptools>=") for requirement in build_requirements)
    constraints = (ROOT / "constraints/dev.txt").read_text(encoding="utf-8")
    assert "setuptools==84.2.1" in constraints.splitlines()


def test_every_catalog_json_is_covered_by_package_data() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    patterns = project["tool"]["setuptools"]["package-data"]["zonepad.infrastructure"]
    catalog_files = list((ROOT / "src/zonepad/infrastructure/catalog_data").glob("*.json"))
    assert catalog_files
    assert "catalog_data/*.json" in patterns
    assert all(json.loads(path.read_text(encoding="utf-8")) for path in catalog_files)


def test_runtime_outside_gui_does_not_import_py_side_or_dev_tools() -> None:
    forbidden_roots = {"PySide6", "pytest", "pytest_cov", "ruff", "mypy", "build", "virtualenv"}
    package_root = ROOT / "src/zonepad"
    for source_path in package_root.rglob("*.py"):
        if "interface/gui" in source_path.as_posix():
            continue
        tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".", maxsplit=1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".", maxsplit=1)[0])
        assert imported.isdisjoint(forbidden_roots), source_path
