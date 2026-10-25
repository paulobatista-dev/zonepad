"""Per-device mapping registry on disk (spec RF7, layout D7).

```text
<directory>/index.json               cache, schema_version 1
<directory>/<stable_id>/mapping.json mapping v1, unchanged schema
<directory>/<stable_id>/identity.json sidecar, schema_version 1
```

Writes go mapping -> identity -> index through ``write_text_atomic``.  The
sidecars are the source of truth; the index is rebuilt in memory (with a
``WARNING``) when missing, invalid or divergent, and only writes rewrite it.
Raw ``uniq``/serial/``phys`` exist only in ``identity.json``; directories are
created with mode ``0o700``.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from zonepad.application.ports import MappingRecord, StoredMappingRef, StoredMappingStatus
from zonepad.domain.discovery import AbsInfo
from zonepad.domain.errors import InvalidMappingError, MappingConflictError
from zonepad.domain.identity import (
    Connection,
    MappingKey,
    QualifierSource,
    StableId,
    is_stable_id,
    parse_stable_id,
)

from .files import sha256_bytes, write_text_atomic
from .mapping import loads_device_mapping

LOGGER = logging.getLogger("zonepad.device_store")
IDENTITY_SCHEMA_VERSION = 1
INDEX_SCHEMA_VERSION = 1
MAPPING_FILE = "mapping.json"
IDENTITY_FILE = "identity.json"
INDEX_FILE = "index.json"
DIRECTORY_MODE = 0o700

_IDENTITY_FIELDS = frozenset(
    {
        "schema_version",
        "stable_id",
        "connection",
        "connection_source",
        "hardware",
        "identity",
        "draft",
        "mapping_file",
        "mapping_sha256",
        "created_at",
        "app_version",
    }
)
_HARDWARE_FIELDS = frozenset(
    {
        "bustype",
        "vendor_id",
        "product_id",
        "device_version",
        "firmware",
        "driver",
        "name",
        "uniq",
        "usb_serial",
        "phys",
    }
)
_DRAFT_FIELDS = frozenset(
    {
        "catalog_entry_id",
        "catalog_version",
        "catalog_source",
        "range_source",
        "range_sources",
        "provisional",
        "provisional_fields",
        "absinfo",
        "warnings",
    }
)
_ABSINFO_FIELDS = frozenset({"minimum", "maximum", "fuzz", "flat", "resolution", "value_at_probe"})
_CHANNELS = frozenset({"lx", "ly", "rx", "ry", "lt", "rt"})
_RANGE_SOURCES = {"evdev_absinfo", "catalog"}
_INDEX_ENTRY_FIELDS = frozenset(
    {"stable_id", "connection", "mapping_sha256", "provisional", "fragile", "updated_at"}
)
_HEX4_FIELD = re.compile(r"0x[0-9a-f]{4}", re.ASCII)
_SHA256_FIELD = re.compile(r"[0-9a-f]{64}", re.ASCII)

WriteText = Callable[[Path, str], None]


class InvalidSidecarError(ValueError):
    """``identity.json`` or ``index.json`` violates its strict schema."""


@dataclass(frozen=True, slots=True)
class _Sidecar:
    stable_id: StableId
    connection: Connection
    mapping_sha256: str
    provisional: bool
    range_source: str
    fragile: bool
    device_version: int | None
    firmware: str | None
    created_at: str


def dumps_identity(record: MappingRecord, mapping_sha256: str) -> str:
    """Serialize the ``identity.json`` sidecar deterministically."""
    facts = record.identity.facts
    provenance = record.provenance
    payload = {
        "schema_version": IDENTITY_SCHEMA_VERSION,
        "stable_id": record.key.stable_id,
        "connection": record.key.connection.value,
        "connection_source": record.connection_source,
        "hardware": {
            "bustype": f"0x{facts.bustype:04x}",
            "vendor_id": f"0x{facts.vendor_id:04x}",
            "product_id": f"0x{facts.product_id:04x}",
            "device_version": _hex4_or_none(facts.device_version),
            "firmware": facts.firmware,
            "driver": facts.driver,
            "name": facts.name,
            "uniq": facts.uniq or None,
            "usb_serial": facts.usb_serial or None,
            "phys": facts.phys or None,
        },
        "identity": {
            "qualifier_source": record.identity.qualifier_source.value,
            "occurrence": record.identity.occurrence,
            "fragile": record.identity.fragile,
        },
        "draft": {
            "catalog_entry_id": provenance.catalog_entry_id,
            "catalog_version": provenance.catalog_version,
            "catalog_source": provenance.catalog_source,
            "range_source": record.range_source,
            "range_sources": dict(record.range_sources),
            "provisional": provenance.provisional,
            "provisional_fields": list(provenance.provisional_fields),
            "absinfo": {
                str(code): _absinfo_payload(info) for code, info in sorted(record.absinfo.items())
            },
            "warnings": list(provenance.warnings),
        },
        "mapping_file": MAPPING_FILE,
        "mapping_sha256": mapping_sha256,
        "created_at": record.created_at,
        "app_version": record.app_version,
    }
    return _dumps(payload)


class JsonDeviceMappingStore:
    """``DeviceMappingStore`` confined to one directory (``--devices-dir``)."""

    def __init__(self, directory: Path, *, write_text: WriteText = write_text_atomic) -> None:
        self._directory = directory.expanduser().resolve()
        self._write_text = write_text

    @property
    def directory(self) -> Path:
        return self._directory

    def find(self, key: MappingKey) -> StoredMappingRef | None:
        stable_id = parse_stable_id(key.stable_id)
        return self._read_entry(stable_id)

    def save(self, record: MappingRecord, *, overwrite: bool) -> StoredMappingRef:
        stable_id = parse_stable_id(record.key.stable_id)
        if record.identity.stable_id != stable_id:
            raise ValueError("mapping record key and identity disagree")
        loads_device_mapping(record.mapping_text)
        device_dir = self._directory / stable_id
        mapping_path = device_dir / MAPPING_FILE
        if mapping_path.exists() and not overwrite:
            raise MappingConflictError(f"a mapping already exists for {stable_id}: {mapping_path}")
        mapping_sha256 = sha256_bytes(record.mapping_text.encode("utf-8"))
        self._make_directory(self._directory)
        self._make_directory(device_dir)
        self._write_text(mapping_path, record.mapping_text)
        self._write_text(device_dir / IDENTITY_FILE, dumps_identity(record, mapping_sha256))
        sidecars = self._scan_sidecars()
        self._write_text(self._directory / INDEX_FILE, _dumps_index(sidecars))
        saved = self._read_entry(stable_id)
        if saved is None:  # pragma: no cover - just written
            raise MappingConflictError(f"mapping for {stable_id} vanished after saving")
        return saved

    def entries(self) -> tuple[StoredMappingRef, ...]:
        """Every saved mapping (including invalid ones), sorted by stable ID.

        Never writes; logs ``WARNING device index rebuilt`` when the index is stale.
        """
        stable_ids = self._candidate_ids()
        self._check_index(self._scan_sidecars())
        refs = (self._read_entry(stable_id) for stable_id in stable_ids)
        return tuple(ref for ref in refs if ref is not None)

    def _candidate_ids(self) -> list[StableId]:
        if not self._directory.is_dir():
            return []
        return sorted(
            StableId(child.name)
            for child in self._directory.iterdir()
            if child.is_dir() and is_stable_id(child.name)
        )

    def _scan_sidecars(self) -> dict[StableId, _Sidecar]:
        result: dict[StableId, _Sidecar] = {}
        for stable_id in self._candidate_ids():
            try:
                result[stable_id] = self._read_sidecar(stable_id)
            except FileNotFoundError, InvalidSidecarError:
                continue
        return result

    def _check_index(self, sidecars: Mapping[StableId, _Sidecar]) -> None:
        expected = json.loads(_dumps_index(sidecars))["entries"]
        path = self._directory / INDEX_FILE
        reason: str | None = None
        try:
            entries = _parse_index(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            reason = "missing" if sidecars else None
        except (OSError, UnicodeError, InvalidSidecarError) as exc:
            reason = f"invalid: {exc}"
        else:
            if entries != expected:
                reason = "divergent"
        if reason is not None:
            LOGGER.warning(
                "device index rebuilt reason=%s path=%s",
                reason,
                path,
                extra={"reason": reason, "path": str(path)},
            )

    def _read_entry(self, stable_id: StableId) -> StoredMappingRef | None:
        device_dir = self._directory / stable_id
        mapping_path = device_dir / MAPPING_FILE
        has_mapping = mapping_path.is_file()
        has_identity = (device_dir / IDENTITY_FILE).is_file()
        if not has_mapping and not has_identity:
            return None
        if not has_identity:
            return _invalid(stable_id, mapping_path, "identity_missing")
        try:
            sidecar = self._read_sidecar(stable_id)
        except (OSError, UnicodeError, InvalidSidecarError) as exc:
            return _invalid(stable_id, mapping_path, f"identity.json: {exc}")
        key = MappingKey(stable_id, sidecar.connection)
        if not has_mapping:
            return _invalid(stable_id, mapping_path, "mapping_missing", key=key, sidecar=sidecar)
        try:
            payload = mapping_path.read_bytes()
        except OSError as exc:
            return _invalid(stable_id, mapping_path, f"mapping.json: {exc.strerror}", key=key)
        current_sha256 = sha256_bytes(payload)
        try:
            loads_device_mapping(payload.decode("utf-8"))
        except (UnicodeDecodeError, InvalidMappingError) as exc:
            return _invalid(
                stable_id, mapping_path, str(exc), key=key, sidecar=sidecar, sha=current_sha256
            )
        status: StoredMappingStatus
        if current_sha256 != sidecar.mapping_sha256:
            status = "edited"
        elif sidecar.provisional:
            status = "provisional"
        else:
            status = "saved"
        return StoredMappingRef(
            key=key,
            mapping_path=str(mapping_path),
            mapping_sha256=current_sha256,
            recorded_sha256=sidecar.mapping_sha256,
            provisional=sidecar.provisional,
            range_source=sidecar.range_source,
            status=status,
            fragile=sidecar.fragile,
            recorded_device_version=sidecar.device_version,
            recorded_firmware=sidecar.firmware,
        )

    def _read_sidecar(self, stable_id: StableId) -> _Sidecar:
        text = (self._directory / stable_id / IDENTITY_FILE).read_text(encoding="utf-8")
        return parse_identity(text, expected_stable_id=stable_id)

    def _make_directory(self, path: Path) -> None:
        path.mkdir(mode=DIRECTORY_MODE, parents=True, exist_ok=True)
        path.chmod(DIRECTORY_MODE)


def parse_identity(text: str, *, expected_stable_id: str) -> _Sidecar:
    """Strictly validate ``identity.json``; ``stable_id`` must equal the directory name."""
    data = _object(_loads(text), "identity")
    _exact(data, _IDENTITY_FIELDS, "identity")
    if data["schema_version"] != IDENTITY_SCHEMA_VERSION:
        raise InvalidSidecarError(f"identity.schema_version must be {IDENTITY_SCHEMA_VERSION}")
    stable_id = _string(data["stable_id"], "identity.stable_id")
    if not is_stable_id(stable_id) or stable_id != expected_stable_id:
        raise InvalidSidecarError("identity.stable_id must match its directory")
    if data["mapping_file"] != MAPPING_FILE:
        raise InvalidSidecarError(f"identity.mapping_file must be {MAPPING_FILE}")
    connection = _connection(data["connection"], "identity.connection")
    _choice(data["connection_source"], {"detected", "override"}, "identity.connection_source")
    hardware = _object(data["hardware"], "identity.hardware")
    _exact(hardware, _HARDWARE_FIELDS, "identity.hardware")
    for name in ("bustype", "vendor_id", "product_id"):
        _hex4(hardware[name], f"identity.hardware.{name}")
    device_version = (
        None
        if hardware["device_version"] is None
        else _hex4(hardware["device_version"], "identity.hardware.device_version")
    )
    for name in ("firmware", "driver", "name", "uniq", "usb_serial", "phys"):
        _optional_string(hardware[name], f"identity.hardware.{name}")
    identity = _object(data["identity"], "identity.identity")
    _exact(identity, {"qualifier_source", "occurrence", "fragile"}, "identity.identity")
    _choice(
        identity["qualifier_source"],
        {source.value for source in QualifierSource},
        "identity.identity.qualifier_source",
    )
    if identity["occurrence"] is not None:
        _integer(identity["occurrence"], "identity.identity.occurrence")
    fragile = _boolean(identity["fragile"], "identity.identity.fragile")
    draft = _object(data["draft"], "identity.draft")
    _exact(draft, _DRAFT_FIELDS, "identity.draft")
    _optional_string(draft["catalog_entry_id"], "identity.draft.catalog_entry_id")
    _integer(draft["catalog_version"], "identity.draft.catalog_version")
    _choice(
        draft["catalog_source"], {"user", "builtin", "generic"}, "identity.draft.catalog_source"
    )
    range_source = _choice(draft["range_source"], _RANGE_SOURCES, "identity.draft.range_source")
    range_sources = _object(draft["range_sources"], "identity.draft.range_sources")
    _exact(range_sources, _CHANNELS, "identity.draft.range_sources")
    for channel, source in range_sources.items():
        _choice(source, _RANGE_SOURCES, f"identity.draft.range_sources.{channel}")
    expected_overall = "catalog" if "catalog" in range_sources.values() else "evdev_absinfo"
    if range_source != expected_overall:
        raise InvalidSidecarError("identity.draft.range_source disagrees with range_sources")
    provisional = _boolean(draft["provisional"], "identity.draft.provisional")
    _string_list(draft["provisional_fields"], "identity.draft.provisional_fields")
    _string_list(draft["warnings"], "identity.draft.warnings")
    absinfo = _object(draft["absinfo"], "identity.draft.absinfo")
    for code, info in absinfo.items():
        if not code.isdecimal():
            raise InvalidSidecarError("identity.draft.absinfo keys must be decimal codes")
        values = _object(info, f"identity.draft.absinfo.{code}")
        _exact(values, _ABSINFO_FIELDS, f"identity.draft.absinfo.{code}")
        for name, value in values.items():
            if value is not None:
                _integer(value, f"identity.draft.absinfo.{code}.{name}")
    mapping_sha256 = _sha256(data["mapping_sha256"], "identity.mapping_sha256")
    _string(data["app_version"], "identity.app_version")
    return _Sidecar(
        stable_id=StableId(stable_id),
        connection=connection,
        mapping_sha256=mapping_sha256,
        provisional=provisional,
        range_source=range_source,
        fragile=fragile,
        device_version=device_version,
        firmware=hardware["firmware"],
        created_at=_string(data["created_at"], "identity.created_at"),
    )


def _parse_index(text: str) -> list[dict[str, Any]]:
    data = _object(_loads(text), "index")
    _exact(data, {"schema_version", "entries"}, "index")
    if data["schema_version"] != INDEX_SCHEMA_VERSION:
        raise InvalidSidecarError(f"index.schema_version must be {INDEX_SCHEMA_VERSION}")
    entries = data["entries"]
    if not isinstance(entries, list):
        raise InvalidSidecarError("index.entries must be a list")
    for position, entry in enumerate(entries):
        field = f"index.entries[{position}]"
        item = _object(entry, field)
        _exact(item, _INDEX_ENTRY_FIELDS, field)
        if not is_stable_id(_string(item["stable_id"], f"{field}.stable_id")):
            raise InvalidSidecarError(f"{field}.stable_id is not a valid stable id")
        _connection(item["connection"], f"{field}.connection")
        _sha256(item["mapping_sha256"], f"{field}.mapping_sha256")
        _boolean(item["provisional"], f"{field}.provisional")
        _boolean(item["fragile"], f"{field}.fragile")
        _string(item["updated_at"], f"{field}.updated_at")
    return entries


def _dumps_index(sidecars: Mapping[StableId, _Sidecar]) -> str:
    entries = [
        {
            "stable_id": sidecar.stable_id,
            "connection": sidecar.connection.value,
            "mapping_sha256": sidecar.mapping_sha256,
            "provisional": sidecar.provisional,
            "fragile": sidecar.fragile,
            "updated_at": sidecar.created_at,
        }
        for _, sidecar in sorted(sidecars.items())
    ]
    return _dumps({"schema_version": INDEX_SCHEMA_VERSION, "entries": entries})


def _invalid(
    stable_id: StableId,
    mapping_path: Path,
    detail: str,
    *,
    key: MappingKey | None = None,
    sidecar: _Sidecar | None = None,
    sha: str | None = None,
) -> StoredMappingRef:
    return StoredMappingRef(
        key=key or MappingKey(stable_id, Connection.UNKNOWN),
        mapping_path=str(mapping_path),
        mapping_sha256=sha,
        recorded_sha256=sidecar.mapping_sha256 if sidecar else None,
        provisional=sidecar.provisional if sidecar else None,
        range_source=sidecar.range_source if sidecar else None,
        status="invalid",
        detail=detail,
        fragile=sidecar.fragile if sidecar else None,
        recorded_device_version=sidecar.device_version if sidecar else None,
        recorded_firmware=sidecar.firmware if sidecar else None,
    )


def _absinfo_payload(info: AbsInfo) -> dict[str, int | None]:
    return {
        "minimum": info.minimum,
        "maximum": info.maximum,
        "fuzz": info.fuzz,
        "flat": info.flat,
        "resolution": info.resolution,
        "value_at_probe": info.value_at_probe,
    }


def _hex4_or_none(value: int | None) -> str | None:
    return None if value is None else f"0x{value:04x}"


def _dumps(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, allow_nan=False, indent=2, sort_keys=True) + "\n"


def _loads(text: str) -> Any:
    def strict(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise InvalidSidecarError(f"duplicate field: {key}")
            result[key] = value
        return result

    try:
        return json.loads(text, object_pairs_hook=strict)
    except json.JSONDecodeError as exc:
        raise InvalidSidecarError(f"invalid JSON: {exc.msg}") from exc


def _exact(data: Mapping[str, Any], expected: frozenset[str] | set[str], field: str) -> None:
    unknown = sorted(set(data) - expected)
    if unknown:
        raise InvalidSidecarError(f"{field} has unknown fields: {', '.join(unknown)}")
    missing = sorted(expected - set(data))
    if missing:
        raise InvalidSidecarError(f"{field} is missing fields: {', '.join(missing)}")


def _object(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise InvalidSidecarError(f"{field} must be an object")
    return value


def _string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise InvalidSidecarError(f"{field} must be a non-empty string")
    return value


def _optional_string(value: Any, field: str) -> str | None:
    return None if value is None else _string(value, field)


def _string_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise InvalidSidecarError(f"{field} must be a list of strings")
    return value


def _boolean(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        raise InvalidSidecarError(f"{field} must be a boolean")
    return value


def _integer(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise InvalidSidecarError(f"{field} must be an integer")
    return value


def _choice(value: Any, allowed: set[str], field: str) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise InvalidSidecarError(f"{field} must be one of {', '.join(sorted(allowed))}")
    return value


def _connection(value: Any, field: str) -> Connection:
    return Connection(_choice(value, {c.value for c in Connection}, field))


def _hex4(value: Any, field: str) -> int:
    text = _string(value, field)
    if not _HEX4_FIELD.fullmatch(text):
        raise InvalidSidecarError(f"{field} must be formatted as 0xNNNN")
    return int(text[2:], 16)


def _sha256(value: Any, field: str) -> str:
    text = _string(value, field)
    if not _SHA256_FIELD.fullmatch(text):
        raise InvalidSidecarError(f"{field} must be a lowercase SHA-256 hex digest")
    return text
