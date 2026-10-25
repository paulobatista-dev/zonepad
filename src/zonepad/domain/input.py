from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType


def _freeze_values(values: Mapping[str, int | float]) -> Mapping[str, int | float]:
    return MappingProxyType(dict(values))


@dataclass(frozen=True, slots=True)
class RawFrame:
    """Raw integer values as received from a device."""

    device_id: str
    timestamp_ns: int
    axes: Mapping[str, int]
    triggers: Mapping[str, int]
    buttons: frozenset[str]

    def __post_init__(self) -> None:
        if self.timestamp_ns < 0:
            raise ValueError("timestamp_ns must be non-negative")
        object.__setattr__(self, "axes", _freeze_values(self.axes))
        object.__setattr__(self, "triggers", _freeze_values(self.triggers))
        object.__setattr__(self, "buttons", frozenset(self.buttons))


@dataclass(frozen=True, slots=True)
class NormalizedFrame:
    """Device-independent values: sticks in [-1, 1], triggers in [0, 1]."""

    device_id: str
    timestamp_ns: int
    axes: Mapping[str, float]
    triggers: Mapping[str, float]
    buttons: frozenset[str]

    def __post_init__(self) -> None:
        if self.timestamp_ns < 0:
            raise ValueError("timestamp_ns must be non-negative")
        axes = {name: _bounded(value, -1.0, 1.0, name) for name, value in self.axes.items()}
        triggers = {name: _bounded(value, 0.0, 1.0, name) for name, value in self.triggers.items()}
        object.__setattr__(self, "axes", MappingProxyType(axes))
        object.__setattr__(self, "triggers", MappingProxyType(triggers))
        object.__setattr__(self, "buttons", frozenset(self.buttons))


@dataclass(frozen=True, slots=True)
class CalibratedFrame:
    """Normalized values after applying a validated user profile."""

    device_id: str
    timestamp_ns: int
    axes: Mapping[str, float]
    triggers: Mapping[str, float]
    buttons: frozenset[str]
    profile_id: str

    def __post_init__(self) -> None:
        if not self.profile_id:
            raise ValueError("profile_id must not be empty")
        axes = {name: _bounded(value, -1.0, 1.0, name) for name, value in self.axes.items()}
        triggers = {name: _bounded(value, 0.0, 1.0, name) for name, value in self.triggers.items()}
        object.__setattr__(self, "axes", MappingProxyType(axes))
        object.__setattr__(self, "triggers", MappingProxyType(triggers))
        object.__setattr__(self, "buttons", frozenset(self.buttons))


def _finite(value: float) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("frame values must be finite")
    return result


def _bounded(value: float, minimum: float, maximum: float, name: str) -> float:
    result = _finite(value)
    if not minimum <= result <= maximum:
        raise ValueError(f"{name} must be in [{minimum}, {maximum}]")
    return result
