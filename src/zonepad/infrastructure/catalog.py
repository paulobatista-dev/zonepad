"""Strict loader of the device family catalog (spec RF5, P7).

The builtin catalog ships as package data (``catalog_data/families.json``) and is
read through ``importlib.resources``.  A user catalog (``--catalog PATH``) uses
the same schema and takes precedence.  Unknown fields are rejected; nothing is
evaluated.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from importlib import resources
from pathlib import Path
from typing import Any, Literal

from zonepad.domain.catalog import (
    MAPPING_CHANNELS,
    STICK_CHANNELS,
    Catalog,
    CatalogEntry,
    CatalogEvidence,
    CatalogMatch,
    CatalogMatchRule,
    InterfaceProtocolRule,
    KnownRange,
    match_catalog,
)
from zonepad.domain.discovery import ObservedInputDevice
from zonepad.domain.errors import InvalidCatalogError

from .linux_input_policy import ABS_MAX, KEY_MAX

SUPPORTED_CATALOG_VERSION = 1
_BUILTIN_PACKAGE = "zonepad.infrastructure"
_BUILTIN_RESOURCE = ("catalog_data", "families.json")
_BUTTON_NAMES = frozenset(("button_south", "button_east", "button_north", "button_west"))
_ENTRY_FIELDS = frozenset(
    {
        "id",
        "display_name",
        "match",
        "required_abs",
        "channels",
        "known_ranges",
        "center_override",
        "buttons",
        "layout",
        "unsupported_reason",
        "quirks",
        "evidence",
        "verified_on_hardware",
    }
)
_HEX4 = re.compile(r"[0-9a-f]{4}", re.ASCII)
_HEX2 = re.compile(r"[0-9a-f]{2}", re.ASCII)
_VID_PID = re.compile(r"([0-9a-f]{4}):([0-9a-f]{4})", re.ASCII)
_ENTRY_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,63}", re.ASCII)


def load_builtin_catalog() -> Catalog:
    resource = resources.files(_BUILTIN_PACKAGE).joinpath(*_BUILTIN_RESOURCE)
    return loads_catalog(resource.read_text(encoding="utf-8"), source="builtin")


def load_catalog_file(path: Path) -> Catalog:
    """Load a user catalog; every problem becomes ``InvalidCatalogError``."""
    try:
        text = path.expanduser().read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise InvalidCatalogError(f"catalog not found: {path}") from exc
    except (OSError, UnicodeError) as exc:
        raise InvalidCatalogError(f"catalog cannot be read: {path}") from exc
    return loads_catalog(text, source="user")


def loads_catalog(text: str, *, source: Literal["user", "builtin"]) -> Catalog:
    try:
        raw = json.loads(text, object_pairs_hook=_strict_object)
    except json.JSONDecodeError as exc:
        raise InvalidCatalogError(f"invalid catalog JSON: {exc.msg}") from exc
    data = _object(raw, "catalog")
    _exact_fields(data, {"catalog_version", "families"}, "catalog")
    if data["catalog_version"] != SUPPORTED_CATALOG_VERSION:
        raise InvalidCatalogError(f"catalog.catalog_version must be {SUPPORTED_CATALOG_VERSION}")
    families = _list(data["families"], "catalog.families")
    entries = tuple(
        _entry(item, f"catalog.families[{index}]") for index, item in enumerate(families)
    )
    try:
        return Catalog(SUPPORTED_CATALOG_VERSION, source, entries)
    except ValueError as exc:
        raise InvalidCatalogError(f"catalog: {exc}") from exc


class LayeredDeviceCatalog:
    """``DeviceCatalog``: user catalog > builtin catalog > generic heuristic."""

    def __init__(self, builtin: Catalog, user: Catalog | None = None) -> None:
        self._catalogs = (user, builtin) if user is not None else (builtin,)
        self._generic_version = builtin.catalog_version

    def match(self, observed: ObservedInputDevice) -> CatalogMatch:
        return match_catalog(self._catalogs, observed, generic_version=self._generic_version)


def _entry(raw: Any, field: str) -> CatalogEntry:
    data = _object(raw, field)
    _exact_fields(data, _ENTRY_FIELDS, field)
    entry_id = _string(data["id"], f"{field}.id")
    if not _ENTRY_ID.fullmatch(entry_id):
        raise InvalidCatalogError(f"{field}.id must match {_ENTRY_ID.pattern}")
    field = f"catalog.families[{entry_id}]"
    try:
        return CatalogEntry(
            entry_id=entry_id,
            display_name=_string(data["display_name"], f"{field}.display_name"),
            match=_match(data["match"], f"{field}.match"),
            required_abs=frozenset(
                _code(item, f"{field}.required_abs", ABS_MAX)
                for item in _list(data["required_abs"], f"{field}.required_abs")
            ),
            channels=_channels(data["channels"], f"{field}.channels"),
            known_ranges=_known_ranges(data["known_ranges"], f"{field}.known_ranges"),
            center_override=_center_override(data["center_override"], f"{field}.center_override"),
            buttons=_buttons(data["buttons"], f"{field}.buttons"),
            layout=_string(data["layout"], f"{field}.layout"),
            unsupported_reason=_optional_string(
                data["unsupported_reason"], f"{field}.unsupported_reason"
            ),
            quirks=tuple(
                _string(item, f"{field}.quirks")
                for item in _list(data["quirks"], f"{field}.quirks")
            ),
            evidence=tuple(
                _evidence(item, f"{field}.evidence")
                for item in _list(data["evidence"], f"{field}.evidence")
            ),
            verified_on_hardware=_boolean(
                data["verified_on_hardware"], f"{field}.verified_on_hardware"
            ),
        )
    except ValueError as exc:
        if isinstance(exc, InvalidCatalogError):
            raise
        raise InvalidCatalogError(f"{field}: {exc}") from exc


def _match(raw: Any, field: str) -> CatalogMatchRule:
    data = _object(raw, field)
    _exact_fields(data, {"driver", "bustype", "vid_pid", "usb_interface_protocol"}, field)
    bustypes = frozenset(
        int(_pattern(item, _HEX4, f"{field}.bustype"), 16)
        for item in _list(data["bustype"], f"{field}.bustype")
    )
    if not bustypes:
        raise InvalidCatalogError(f"{field}.bustype must not be empty")
    vid_pids: frozenset[tuple[int, int]] | None = None
    if data["vid_pid"] is not None:
        pairs = []
        for item in _list(data["vid_pid"], f"{field}.vid_pid"):
            match = _VID_PID.fullmatch(_string(item, f"{field}.vid_pid"))
            if match is None:
                raise InvalidCatalogError(f"{field}.vid_pid items must be 'vvvv:pppp' lowercase")
            pairs.append((int(match.group(1), 16), int(match.group(2), 16)))
        vid_pids = frozenset(pairs)
    return CatalogMatchRule(
        driver=_string(data["driver"], f"{field}.driver"),
        bustypes=bustypes,
        vid_pids=vid_pids,
        usb_interface_protocol=_protocol_rule(
            data["usb_interface_protocol"], f"{field}.usb_interface_protocol"
        ),
    )


def _protocol_rule(raw: Any, field: str) -> InterfaceProtocolRule | None:
    if raw is None:
        return None
    data = _object(raw, field)
    if set(data) not in ({"in"}, {"not_in"}):
        raise InvalidCatalogError(f"{field} must have exactly one of 'in' or 'not_in'")
    mode: Literal["in", "not_in"] = "in" if "in" in data else "not_in"
    values = frozenset(
        _pattern(item, _HEX2, f"{field}.{mode}") for item in _list(data[mode], f"{field}.{mode}")
    )
    if not values:
        raise InvalidCatalogError(f"{field}.{mode} must not be empty")
    return InterfaceProtocolRule(mode, values)


def _channels(raw: Any, field: str) -> dict[str, int]:
    data = _object(raw, field)
    unknown = sorted(set(data) - set(MAPPING_CHANNELS))
    if unknown:
        raise InvalidCatalogError(f"{field} has unknown channels: {', '.join(unknown)}")
    result: dict[str, int] = {}
    for name, item in data.items():
        channel = _object(item, f"{field}.{name}")
        _exact_fields(channel, {"code"}, f"{field}.{name}")
        result[name] = _code(channel["code"], f"{field}.{name}.code", ABS_MAX)
    return result


def _known_ranges(raw: Any, field: str) -> dict[int, KnownRange]:
    data = _object(raw, field)
    result: dict[int, KnownRange] = {}
    for key, item in data.items():
        code = _code(_decimal_key(key, field), f"{field}.{key}", ABS_MAX)
        values = _object(item, f"{field}.{key}")
        _exact_fields(values, {"minimum", "maximum", "fuzz", "flat"}, f"{field}.{key}")
        try:
            result[code] = KnownRange(
                **{name: _integer(values[name], f"{field}.{key}.{name}") for name in values}
            )
        except ValueError as exc:
            if isinstance(exc, InvalidCatalogError):
                raise
            raise InvalidCatalogError(f"{field}.{key}: {exc}") from exc
    return result


def _center_override(raw: Any, field: str) -> dict[str, int]:
    data = _object(raw, field)
    unknown = sorted(set(data) - set(STICK_CHANNELS))
    if unknown:
        raise InvalidCatalogError(f"{field} has non-stick channels: {', '.join(unknown)}")
    return {name: _integer(value, f"{field}.{name}") for name, value in data.items()}


def _buttons(raw: Any, field: str) -> dict[int, str]:
    data = _object(raw, field)
    result: dict[int, str] = {}
    for key, name in data.items():
        code = _code(_decimal_key(key, field), f"{field}.{key}", KEY_MAX)
        if not isinstance(name, str) or name not in _BUTTON_NAMES:
            raise InvalidCatalogError(f"{field}.{key} must name a supported button")
        result[code] = name
    if len(set(result.values())) != len(result):
        raise InvalidCatalogError(f"{field} repeats a button name")
    return result


def _evidence(raw: Any, field: str) -> CatalogEvidence:
    data = _object(raw, field)
    _exact_fields(data, {"kind", "ref", "commit"}, field)
    return CatalogEvidence(
        kind=_string(data["kind"], f"{field}.kind"),
        ref=_string(data["ref"], f"{field}.ref"),
        commit=_optional_string(data["commit"], f"{field}.commit"),
    )


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise InvalidCatalogError(f"catalog contains duplicate field: {key}")
        result[key] = value
    return result


def _exact_fields(data: Mapping[str, Any], expected: set[str] | frozenset[str], field: str) -> None:
    unknown = sorted(set(data) - expected)
    if unknown:
        raise InvalidCatalogError(f"{field} has unknown fields: {', '.join(unknown)}")
    missing = sorted(expected - set(data))
    if missing:
        raise InvalidCatalogError(f"{field} is missing fields: {', '.join(missing)}")


def _object(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise InvalidCatalogError(f"{field} must be an object")
    return value


def _list(value: Any, field: str) -> list[Any]:
    if not isinstance(value, list):
        raise InvalidCatalogError(f"{field} must be a list")
    return value


def _string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise InvalidCatalogError(f"{field} must be a non-empty string")
    return value


def _optional_string(value: Any, field: str) -> str | None:
    return None if value is None else _string(value, field)


def _boolean(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        raise InvalidCatalogError(f"{field} must be a boolean")
    return value


def _integer(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise InvalidCatalogError(f"{field} must be an integer")
    return value


def _code(value: Any, field: str, maximum: int) -> int:
    code = _integer(value, field)
    if not 0 <= code <= maximum:
        raise InvalidCatalogError(f"{field} must be in [0, {maximum}]")
    return code


def _decimal_key(key: str, field: str) -> int:
    if not key.isdecimal() or not key.isascii():
        raise InvalidCatalogError(f"{field} keys must be decimal codes")
    return int(key)


def _pattern(value: Any, pattern: re.Pattern[str], field: str) -> str:
    text = _string(value, field)
    if not pattern.fullmatch(text):
        raise InvalidCatalogError(f"{field} items must match {pattern.pattern}")
    return text
