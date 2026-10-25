from __future__ import annotations

import email
import sys
import tarfile
import zipfile
from pathlib import Path


def _check_wheel(wheel_path: Path) -> None:
    with zipfile.ZipFile(wheel_path) as archive:
        names = set(archive.namelist())
        metadata_path = next(name for name in names if name.endswith(".dist-info/METADATA"))
        wheel_metadata = email.message_from_bytes(archive.read(metadata_path))
        assert wheel_metadata["Name"] == "zonepad"
        assert wheel_metadata["Version"] == "0.1.0"
        assert set(wheel_metadata["Requires-Python"].split(",")) == {"<3.16", ">=3.15"}
        assert wheel_metadata["Description-Content-Type"].startswith("text/markdown")
        assert "# ZonaPad" in wheel_metadata.get_payload()
        assert "Requires-Dist: PySide6>=6.7; extra == \"gui\"" in archive.read(
            metadata_path
        ).decode("utf-8")
        assert "zonepad/interface/cli.py" in names
        assert "zonepad/interface/gui/__init__.py" in names
        assert "zonepad/infrastructure/catalog_data/families.json" in names
        assert "zonepad-0.1.0.dist-info/entry_points.txt" in names
        entries = archive.read("zonepad-0.1.0.dist-info/entry_points.txt").decode("utf-8")
        assert "zonepad = zonepad.interface.cli:main" in entries
        assert "zonepad-gui = zonepad.interface.gui:run" in entries
        license_files = [value for value in wheel_metadata.get_all("License-File", [])]
        assert license_files
        assert all(f"zonepad-0.1.0.dist-info/licenses/{name}" in names for name in license_files)


def _check_sdist(sdist_path: Path) -> None:
    with tarfile.open(sdist_path, "r:gz") as archive:
        names = set(archive.getnames())
        root = "zonepad-0.1.0/"
        required = {
            "pyproject.toml",
            "README.md",
            "LICENSE",
            "constraints/dev.txt",
            "src/zonepad/interface/cli.py",
            "src/zonepad/infrastructure/catalog_data/families.json",
        }
        missing = [name for name in required if root + name not in names]
        assert not missing, f"sdist omits required files: {missing}"


def main() -> int:
    dist = Path(sys.argv[1] if len(sys.argv) > 1 else "dist")
    wheels = list(dist.glob("zonepad-0.1.0-*.whl"))
    sdists = list(dist.glob("zonepad-0.1.0.tar.gz"))
    assert len(wheels) == 1, f"expected one wheel in {dist}, found {wheels}"
    assert len(sdists) == 1, f"expected one sdist in {dist}, found {sdists}"
    _check_wheel(wheels[0])
    _check_sdist(sdists[0])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
