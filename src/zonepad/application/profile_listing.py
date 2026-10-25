"""Profile catalog use case with isolated validation errors."""

from __future__ import annotations

from dataclasses import dataclass

from zonepad.domain.errors import InvalidProfileError
from zonepad.domain.profile import CalibrationProfile

from .ports import ProfileCatalog, ProfileStore


@dataclass(frozen=True, slots=True)
class ListedProfile:
    profile_id: str
    profile: CalibrationProfile | None
    error: str | None = None


def list_profiles(catalog: ProfileCatalog, store: ProfileStore) -> tuple[ListedProfile, ...]:
    """Load profiles independently; one damaged item leaves the catalog usable."""
    result: list[ListedProfile] = []
    for profile_id in catalog.list_profiles():
        try:
            result.append(ListedProfile(profile_id, store.load(profile_id)))
        except (InvalidProfileError, OSError) as exc:
            detail = (
                f"falha de leitura ({type(exc).__name__})" if isinstance(exc, OSError) else str(exc)
            )
            result.append(ListedProfile(profile_id, None, detail))
    return tuple(result)
