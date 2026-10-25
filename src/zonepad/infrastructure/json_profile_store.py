from __future__ import annotations

import json
import os
from pathlib import Path

from zonepad.domain.errors import InvalidProfileError
from zonepad.domain.profile import CalibrationProfile


class JsonProfileStore:
    """Versioned JSON profiles with atomic writes confined to one directory."""

    def __init__(self, directory: Path) -> None:
        self._directory = directory.expanduser().resolve()
        self._directory.mkdir(parents=True, exist_ok=True)

    def _path(self, profile_id: str) -> Path:
        if (
            profile_id in {"", ".", ".."}
            or Path(profile_id).name != profile_id
            or any(char in profile_id for char in "/\\")
        ):
            raise InvalidProfileError("invalid profile id path")
        return self._directory / f"{profile_id}.json"

    def load(self, profile_id: str) -> CalibrationProfile:
        path = self._path(profile_id)
        try:
            with path.open(encoding="utf-8") as stream:
                data = json.load(stream)
        except FileNotFoundError as exc:
            raise InvalidProfileError(f"profile not found: {profile_id}") from exc
        except json.JSONDecodeError as exc:
            raise InvalidProfileError(f"invalid JSON profile: {profile_id}") from exc
        return CalibrationProfile.from_dict(data)

    def save(self, profile: CalibrationProfile) -> None:
        path = self._path(profile.profile_id)
        temporary = path.with_suffix(".json.tmp")
        payload = json.dumps(profile.to_dict(), ensure_ascii=False, indent=2, sort_keys=True)
        try:
            with temporary.open("w", encoding="utf-8") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(path)
        finally:
            if temporary.exists():
                temporary.unlink()

    def list_profiles(self) -> tuple[str, ...]:
        return tuple(sorted(path.stem for path in self._directory.glob("*.json")))
