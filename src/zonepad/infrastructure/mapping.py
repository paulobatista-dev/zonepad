from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

from zonepad.domain.errors import InvalidMappingError
from zonepad.domain.mapping_draft import MappingDraft
from zonepad.domain.normalization import AxisRange, TriggerRange

_AXIS_NAMES = frozenset(("lx", "ly", "rx", "ry"))
_TRIGGER_NAMES = frozenset(("lt", "rt"))
_BUTTON_NAMES = frozenset(("button_south", "button_east", "button_north", "button_west"))


@dataclass(frozen=True, slots=True)
class DeviceMapping:
    """Validated v1 mapping from Linux evdev codes to ZonaPad inputs."""

    axes: Mapping[str, AxisRange]
    triggers: Mapping[str, TriggerRange]
    axis_codes: Mapping[int, str]
    trigger_codes: Mapping[int, str]
    button_codes: Mapping[int, str]

    def __post_init__(self) -> None:
        if set(self.axes) != _AXIS_NAMES:
            raise InvalidMappingError("mapping.axes must define lx, ly, rx and ry")
        if set(self.triggers) != _TRIGGER_NAMES:
            raise InvalidMappingError("mapping.triggers must define lt and rt")
        if set(self.axis_codes.values()) != _AXIS_NAMES:
            raise InvalidMappingError("mapping axis codes must be unique and complete")
        if set(self.trigger_codes.values()) != _TRIGGER_NAMES:
            raise InvalidMappingError("mapping trigger codes must be unique and complete")
        if set(self.axis_codes).intersection(self.trigger_codes):
            raise InvalidMappingError("axis and trigger codes must not overlap")
        if len(set(self.button_codes.values())) != len(self.button_codes):
            raise InvalidMappingError("button semantic names must not be repeated")
        if not set(self.button_codes.values()).issubset(_BUTTON_NAMES):
            raise InvalidMappingError("mapping contains an unsupported button semantic name")
        object.__setattr__(self, "axes", MappingProxyType(dict(self.axes)))
        object.__setattr__(self, "triggers", MappingProxyType(dict(self.triggers)))
        object.__setattr__(self, "axis_codes", MappingProxyType(dict(self.axis_codes)))
        object.__setattr__(self, "trigger_codes", MappingProxyType(dict(self.trigger_codes)))
        object.__setattr__(self, "button_codes", MappingProxyType(dict(self.button_codes)))


def load_device_mapping(path: Path) -> DeviceMapping:
    """Load a strict schema-v1 mapping without inferring hardware ranges."""
    try:
        with path.expanduser().open(encoding="utf-8") as stream:
            text = stream.read()
    except FileNotFoundError as exc:
        raise InvalidMappingError(f"mapping not found: {path}") from exc
    except (OSError, UnicodeError, IsADirectoryError) as exc:
        raise InvalidMappingError(f"mapping cannot be read: {path}") from exc
    return _loads(text, str(path))


def loads_device_mapping(text: str) -> DeviceMapping:
    """Parse a strict schema-v1 mapping from JSON text (same rules as the file loader)."""
    return _loads(text, "<text>")


def dumps_device_mapping(draft: MappingDraft) -> str:
    """Serialize a draft as deterministic schema-v1 JSON (button keys in decimal)."""
    payload = {
        "schema_version": 1,
        "axes": {
            name: {
                "code": axis.code,
                "minimum": axis.minimum,
                "center": axis.center,
                "maximum": axis.maximum,
            }
            for name, axis in draft.axes.items()
        },
        "triggers": {
            name: {"code": trigger.code, "rest": trigger.rest, "maximum": trigger.maximum}
            for name, trigger in draft.triggers.items()
        },
        "buttons": {str(code): name for code, name in draft.buttons.items()},
    }
    return json.dumps(payload, ensure_ascii=False, allow_nan=False, indent=2, sort_keys=True) + "\n"


def _loads(text: str, source: str) -> DeviceMapping:
    try:
        raw = json.loads(text, object_pairs_hook=_strict_object)
    except json.JSONDecodeError as exc:
        raise InvalidMappingError(f"invalid mapping JSON: {source}") from exc
    return _parse_mapping(raw)


def _parse_mapping(raw: Any) -> DeviceMapping:
    data = _object(raw, "mapping")
    _reject_unknown(data, {"schema_version", "axes", "triggers", "buttons"}, "mapping")
    if data.get("schema_version") != 1:
        raise InvalidMappingError("mapping.schema_version must be 1")
    axes, axis_codes = _parse_axes(_object(data.get("axes"), "mapping.axes"))
    triggers, trigger_codes = _parse_triggers(_object(data.get("triggers"), "mapping.triggers"))
    button_codes = _parse_buttons(_object(data.get("buttons", {}), "mapping.buttons"))
    return DeviceMapping(axes, triggers, axis_codes, trigger_codes, button_codes)


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise InvalidMappingError(f"mapping contains duplicate field: {key}")
        result[key] = value
    return result


def _parse_axes(data: Mapping[str, Any]) -> tuple[dict[str, AxisRange], dict[int, str]]:
    if set(data) != _AXIS_NAMES:
        raise InvalidMappingError("mapping.axes must contain exactly lx, ly, rx and ry")
    ranges: dict[str, AxisRange] = {}
    codes: dict[int, str] = {}
    for name in _AXIS_NAMES:
        item = _object(data[name], f"mapping.axes.{name}")
        _reject_unknown(item, {"code", "minimum", "center", "maximum"}, f"mapping.axes.{name}")
        code = _code(item.get("code"), f"mapping.axes.{name}.code")
        if code in codes:
            raise InvalidMappingError("mapping axis codes must be unique")
        try:
            ranges[name] = AxisRange(
                _integer(item.get("minimum"), f"mapping.axes.{name}.minimum"),
                _integer(item.get("center"), f"mapping.axes.{name}.center"),
                _integer(item.get("maximum"), f"mapping.axes.{name}.maximum"),
            )
        except ValueError as exc:
            raise InvalidMappingError(str(exc)) from exc
        codes[code] = name
    return ranges, codes


def _parse_triggers(data: Mapping[str, Any]) -> tuple[dict[str, TriggerRange], dict[int, str]]:
    if set(data) != _TRIGGER_NAMES:
        raise InvalidMappingError("mapping.triggers must contain exactly lt and rt")
    ranges: dict[str, TriggerRange] = {}
    codes: dict[int, str] = {}
    for name in _TRIGGER_NAMES:
        item = _object(data[name], f"mapping.triggers.{name}")
        _reject_unknown(item, {"code", "rest", "maximum"}, f"mapping.triggers.{name}")
        code = _code(item.get("code"), f"mapping.triggers.{name}.code")
        if code in codes:
            raise InvalidMappingError("mapping trigger codes must be unique")
        try:
            ranges[name] = TriggerRange(
                _integer(item.get("rest"), f"mapping.triggers.{name}.rest"),
                _integer(item.get("maximum"), f"mapping.triggers.{name}.maximum"),
            )
        except ValueError as exc:
            raise InvalidMappingError(str(exc)) from exc
        codes[code] = name
    return ranges, codes


def _parse_buttons(data: Mapping[str, Any]) -> dict[int, str]:
    result: dict[int, str] = {}
    for raw_code, semantic_name in data.items():
        if not isinstance(raw_code, str) or not raw_code.isdecimal():
            raise InvalidMappingError("mapping button codes must be decimal string keys")
        code = _button_code(int(raw_code), f"mapping.buttons.{raw_code}")
        if not isinstance(semantic_name, str) or semantic_name not in _BUTTON_NAMES:
            raise InvalidMappingError(f"mapping.buttons.{raw_code} must name a supported button")
        if code in result:
            raise InvalidMappingError("mapping button codes must be unique")
        result[code] = semantic_name
    return result


def _object(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise InvalidMappingError(f"{field} must be an object")
    return value


def _integer(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise InvalidMappingError(f"{field} must be an integer")
    return value


def _code(value: Any, field: str) -> int:
    code = _integer(value, field)
    if not 0 <= code <= 0xFFFF:
        raise InvalidMappingError(f"{field} must be in [0, 65535]")
    return code


def _button_code(value: Any, field: str) -> int:
    code = _integer(value, field)
    if not 0 <= code <= 0x2FF:  # Linux KEY_MAX
        raise InvalidMappingError(f"{field} must be in [0, 767]")
    return code


def _reject_unknown(data: Mapping[str, Any], allowed: set[str], field: str) -> None:
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise InvalidMappingError(f"{field} has unknown fields: {', '.join(unknown)}")
