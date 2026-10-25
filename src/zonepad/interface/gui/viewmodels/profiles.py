"""Pure profile-list presentation state."""

from __future__ import annotations

from dataclasses import dataclass

from zonepad.application.profile_listing import ListedProfile


@dataclass(frozen=True, slots=True)
class ProfileItem:
    profile_id: str
    title: str
    summary: str
    error: str | None = None


def profile_item(item: ListedProfile) -> ProfileItem:
    profile = item.profile
    if profile is None:
        reason = item.error or "Perfil inválido"
        return ProfileItem(
            item.profile_id,
            item.profile_id,
            f"Arquivo {item.profile_id}.json · Perfil inválido · {reason}",
            reason,
        )
    left = profile.sticks["left"]
    right = profile.sticks["right"]
    left_trigger = profile.triggers["left"]
    right_trigger = profile.triggers["right"]
    summary = (
        f"{profile.device.name} · {profile.device.vid}:{profile.device.pid} · "
        f"criado em {profile.created_at} · "
        f"sticks centro {left.center}/{right.center} · "
        f"ranges L {left.range_min}…{left.range_max}, R {right.range_min}…{right.range_max} · "
        f"deadzone L/R {left.deadzone.value:.3f}/{right.deadzone.value:.3f} · "
        f"gatilhos repouso/máximo L {left_trigger.rest:.3f}/{left_trigger.max:.3f}, "
        f"R {right_trigger.rest:.3f}/{right_trigger.max:.3f}"
    )
    if profile.notes:
        summary = f"{summary} · {profile.notes}"
    return ProfileItem(item.profile_id, profile.profile_id, summary)
