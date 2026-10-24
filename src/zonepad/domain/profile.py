from __future__ import annotations

import math
import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Any, Literal

from .errors import InvalidProfileError

CurveType = Literal["linear", "exponential", "lut"]
DeadzoneMode = Literal["cut", "rescale"]
_HEX_ID = re.compile(r"^0x[0-9a-fA-F]{4}$")


def _number(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InvalidProfileError(f"{field_name} must be a number")
    result = float(value)
    if not math.isfinite(result):
        raise InvalidProfileError(f"{field_name} must be finite")
    return result


def _pair(value: Any, field_name: str) -> tuple[float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise InvalidProfileError(f"{field_name} must contain two values")
    return (_number(value[0], field_name), _number(value[1], field_name))


@dataclass(frozen=True, slots=True)
class CurveSpec:
    type: CurveType = "linear"
    gamma: float | None = None
    lut: tuple[tuple[float, float], ...] = ()

    def __post_init__(self) -> None:
        if self.type not in ("linear", "exponential", "lut"):
            raise InvalidProfileError(f"unsupported curve type: {self.type}")
        if self.type == "exponential":
            if self.gamma is None or not math.isfinite(self.gamma) or self.gamma <= 0:
                raise InvalidProfileError("exponential curve requires gamma > 0")
        elif self.gamma is not None:
            raise InvalidProfileError("gamma is only valid for exponential curves")
        if self.type == "lut":
            if len(self.lut) < 2:
                raise InvalidProfileError("lut curve requires at least two points")
            previous_x = -math.inf
            previous_y = -math.inf
            for point in self.lut:
                if len(point) != 2:
                    raise InvalidProfileError("lut points must contain two values")
                x, y = map(float, point)
                if not math.isfinite(x) or not math.isfinite(y):
                    raise InvalidProfileError("lut values must be finite")
                if x < previous_x or y < previous_y:
                    raise InvalidProfileError("lut points must be monotonic")
                previous_x, previous_y = x, y
        elif self.lut:
            raise InvalidProfileError("lut is only valid for lut curves")

    @classmethod
    def from_dict(cls, data: Any) -> CurveSpec:
        if not isinstance(data, dict):
            raise InvalidProfileError("curve must be an object")
        allowed = {"type", "gamma", "lut"}
        _reject_unknown(data, allowed, "curve")
        curve_type = data.get("type", "linear")
        lut_raw = data.get("lut", ())
        if lut_raw and not isinstance(lut_raw, list):
            raise InvalidProfileError("curve.lut must be an array")
        lut = tuple(_pair(point, "curve.lut") for point in lut_raw)
        gamma = _number(data["gamma"], "curve.gamma") if "gamma" in data else None
        return cls(type=curve_type, gamma=gamma, lut=lut)  # type: ignore[arg-type]

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"type": self.type}
        if self.gamma is not None:
            result["gamma"] = self.gamma
        if self.lut:
            result["lut"] = [list(point) for point in self.lut]
        return result


@dataclass(frozen=True, slots=True)
class DeadzoneSpec:
    mode: DeadzoneMode = "cut"
    value: float = 0.0

    def __post_init__(self) -> None:
        if self.mode not in ("cut", "rescale") or not 0 <= self.value <= 0.95:
            raise InvalidProfileError("deadzone must use cut/rescale and value in [0, 0.95]")

    @classmethod
    def from_dict(cls, data: Any) -> DeadzoneSpec:
        if not isinstance(data, dict):
            raise InvalidProfileError("deadzone must be an object")
        _reject_unknown(data, {"mode", "value"}, "deadzone")
        return cls(
            mode=data.get("mode", "cut"), value=_number(data.get("value", 0), "deadzone.value")
        )  # type: ignore[arg-type]

    def to_dict(self) -> dict[str, Any]:
        return {"mode": self.mode, "value": self.value}


@dataclass(frozen=True, slots=True)
class StickCalibration:
    center: tuple[float, float] = (0.0, 0.0)
    range_min: tuple[float, float] = (-1.0, -1.0)
    range_max: tuple[float, float] = (1.0, 1.0)
    deadzone: DeadzoneSpec = DeadzoneSpec()
    curve: CurveSpec = CurveSpec()
    invert: tuple[bool, bool] = (False, False)

    def __post_init__(self) -> None:
        for name, pair in (
            ("center", self.center),
            ("range_min", self.range_min),
            ("range_max", self.range_max),
        ):
            if len(pair) != 2 or any(
                not math.isfinite(float(v)) or not -1 <= float(v) <= 1 for v in pair
            ):
                raise InvalidProfileError(f"{name} values must be in [-1, 1]")
        if any(a >= b for a, b in zip(self.range_min, self.range_max, strict=False)):
            raise InvalidProfileError("stick range.min must be lower than range.max")
        if any(
            not (minimum < center < maximum)
            for minimum, center, maximum in zip(
                self.range_min, self.center, self.range_max, strict=False
            )
        ):
            raise InvalidProfileError("stick center must be inside measured range")
        if len(self.invert) != 2 or any(not isinstance(v, bool) for v in self.invert):
            raise InvalidProfileError("stick invert must contain two booleans")

    @classmethod
    def from_dict(cls, data: Any) -> StickCalibration:
        if not isinstance(data, dict):
            raise InvalidProfileError("stick must be an object")
        _reject_unknown(data, {"center", "range", "deadzone", "curve", "invert"}, "stick")
        ranges = data.get("range", {})
        if not isinstance(ranges, dict):
            raise InvalidProfileError("stick.range must be an object")
        _reject_unknown(ranges, {"min", "max"}, "stick.range")
        invert = data.get("invert", (False, False))
        if not isinstance(invert, (list, tuple)):
            raise InvalidProfileError("stick.invert must be an array")
        if (
            not isinstance(invert, (list, tuple))
            or len(invert) != 2
            or any(not isinstance(value, bool) for value in invert)
        ):
            raise InvalidProfileError("stick.invert must contain two booleans")
        return cls(
            center=_pair(data.get("center", (0, 0)), "stick.center"),
            range_min=_pair(ranges.get("min", (-1, -1)), "stick.range.min"),
            range_max=_pair(ranges.get("max", (1, 1)), "stick.range.max"),
            deadzone=DeadzoneSpec.from_dict(data.get("deadzone", {})),
            curve=CurveSpec.from_dict(data.get("curve", {})),
            invert=(invert[0], invert[1]),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "center": list(self.center),
            "range": {"min": list(self.range_min), "max": list(self.range_max)},
            "deadzone": self.deadzone.to_dict(),
            "curve": self.curve.to_dict(),
            "invert": list(self.invert),
        }


@dataclass(frozen=True, slots=True)
class TriggerCalibration:
    rest: float = 0.0
    max: float = 1.0
    deadzone: float = 0.0
    curve: CurveSpec = CurveSpec()
    invert: bool = False

    def __post_init__(self) -> None:
        if not 0 <= self.rest < self.max <= 1:
            raise InvalidProfileError("trigger requires 0 <= rest < max <= 1")
        if not 0 <= self.deadzone <= 0.95:
            raise InvalidProfileError("trigger deadzone must be in [0, 0.95]")
        if not isinstance(self.invert, bool):
            raise InvalidProfileError("trigger invert must be boolean")

    @classmethod
    def from_dict(cls, data: Any) -> TriggerCalibration:
        if not isinstance(data, dict):
            raise InvalidProfileError("trigger must be an object")
        _reject_unknown(data, {"rest", "max", "deadzone", "curve", "invert"}, "trigger")
        invert = data.get("invert", False)
        if not isinstance(invert, bool):
            raise InvalidProfileError("trigger invert must be boolean")
        return cls(
            rest=_number(data.get("rest", 0), "trigger.rest"),
            max=_number(data.get("max", 1), "trigger.max"),
            deadzone=_number(data.get("deadzone", 0), "trigger.deadzone"),
            curve=CurveSpec.from_dict(data.get("curve", {})),
            invert=invert,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "rest": self.rest,
            "max": self.max,
            "deadzone": self.deadzone,
            "curve": self.curve.to_dict(),
            "invert": self.invert,
        }


@dataclass(frozen=True, slots=True)
class DeviceIdentity:
    name: str
    vid: str
    pid: str
    guid: str | None = None
    serial: str | None = None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.name, str)
            or not isinstance(self.vid, str)
            or not isinstance(self.pid, str)
        ):
            raise InvalidProfileError("device name, vid and pid must be strings")
        if (
            not 1 <= len(self.name) <= 200
            or not _HEX_ID.fullmatch(self.vid)
            or not _HEX_ID.fullmatch(self.pid)
        ):
            raise InvalidProfileError("device name, vid and pid are invalid")
        if self.guid is not None and not isinstance(self.guid, str):
            raise InvalidProfileError("device guid must be a string or null")
        if self.serial is not None and not isinstance(self.serial, str):
            raise InvalidProfileError("device serial must be a string or null")

    @classmethod
    def from_dict(cls, data: Any) -> DeviceIdentity:
        if not isinstance(data, dict):
            raise InvalidProfileError("device must be an object")
        _reject_unknown(data, {"name", "vid", "pid", "guid", "serial"}, "device")
        return cls(
            name=data.get("name", ""),
            vid=data.get("vid", ""),
            pid=data.get("pid", ""),
            guid=data.get("guid"),
            serial=data.get("serial"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "vid": self.vid,
            "pid": self.pid,
            "guid": self.guid,
            "serial": self.serial,
        }


@dataclass(frozen=True, slots=True)
class CalibrationProfile:
    schema_version: int
    profile_id: str
    device: DeviceIdentity
    sticks: Mapping[str, StickCalibration]
    triggers: Mapping[str, TriggerCalibration]
    created_at: str
    app_version: str
    notes: str = ""

    CURRENT_SCHEMA_VERSION = 1

    def __post_init__(self) -> None:
        if self.schema_version != self.CURRENT_SCHEMA_VERSION:
            raise InvalidProfileError(f"unsupported schema_version: {self.schema_version}")
        try:
            parsed = uuid.UUID(self.profile_id)
        except (ValueError, AttributeError, TypeError) as exc:
            raise InvalidProfileError("profile_id must be a UUID") from exc
        if parsed.version != 4:
            raise InvalidProfileError("profile_id must be a UUID v4")
        if set(self.sticks) != {"left", "right"} or set(self.triggers) != {"left", "right"}:
            raise InvalidProfileError("profile must contain left and right sticks/triggers")
        try:
            stamp = datetime.fromisoformat(self.created_at.replace("Z", "+00:00"))
        except (ValueError, AttributeError, TypeError) as exc:
            raise InvalidProfileError("created_at must be ISO-8601") from exc
        if stamp.tzinfo is None:
            raise InvalidProfileError("created_at must include timezone")
        offset = stamp.utcoffset()
        if offset is None or offset.total_seconds() != 0:
            raise InvalidProfileError("created_at must be UTC")
        if not isinstance(self.app_version, str) or not self.app_version:
            raise InvalidProfileError("app_version must not be empty")
        if not isinstance(self.notes, str):
            raise InvalidProfileError("notes must be a string")
        if len(self.notes) > 2000:
            raise InvalidProfileError("notes exceed 2000 characters")
        object.__setattr__(self, "sticks", MappingProxyType(dict(self.sticks)))
        object.__setattr__(self, "triggers", MappingProxyType(dict(self.triggers)))

    @classmethod
    def from_dict(cls, data: Any) -> CalibrationProfile:
        if not isinstance(data, dict):
            raise InvalidProfileError("profile must be an object")
        _reject_unknown(
            data,
            {
                "schema_version",
                "profile_id",
                "device",
                "sticks",
                "triggers",
                "created_at",
                "app_version",
                "notes",
            },
            "profile",
        )
        if data.get("schema_version") != cls.CURRENT_SCHEMA_VERSION:
            raise InvalidProfileError(f"unsupported schema_version: {data.get('schema_version')}")
        sticks_raw, triggers_raw = data.get("sticks"), data.get("triggers")
        if not isinstance(sticks_raw, dict) or not isinstance(triggers_raw, dict):
            raise InvalidProfileError("sticks and triggers must be objects")
        try:
            sticks = {
                name: StickCalibration.from_dict(sticks_raw[name]) for name in ("left", "right")
            }
            triggers = {
                name: TriggerCalibration.from_dict(triggers_raw[name]) for name in ("left", "right")
            }
        except KeyError as exc:
            raise InvalidProfileError(
                "profile must contain left and right sticks/triggers"
            ) from exc
        notes = data.get("notes", "")
        if not isinstance(notes, str):
            raise InvalidProfileError("notes must be a string")
        return cls(
            schema_version=1,
            profile_id=data.get("profile_id", ""),
            device=DeviceIdentity.from_dict(data.get("device")),
            sticks=sticks,
            triggers=triggers,
            created_at=data.get("created_at", ""),
            app_version=data.get("app_version", ""),
            notes=notes,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "profile_id": self.profile_id,
            "device": self.device.to_dict(),
            "sticks": {name: value.to_dict() for name, value in self.sticks.items()},
            "triggers": {name: value.to_dict() for name, value in self.triggers.items()},
            "created_at": self.created_at,
            "app_version": self.app_version,
            "notes": self.notes,
        }


def _reject_unknown(data: dict[str, Any], allowed: set[str], context: str) -> None:
    unknown = set(data) - allowed
    if unknown:
        raise InvalidProfileError(f"unknown {context} fields: {', '.join(sorted(unknown))}")


def validate_profile(data: Any) -> CalibrationProfile:
    """Validate untrusted JSON-like data and return an immutable profile."""
    return CalibrationProfile.from_dict(data)
