"""Strict reader for the ``manifest_version=1`` capture manifest and the thresholds file."""

from __future__ import annotations

import dataclasses
import json
import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any, NoReturn

from zonepad.domain.errors import MeasurementInputError
from zonepad.domain.metrics import (
    THRESHOLDS_VERSION,
    DeadzoneParams,
    MetricsConfig,
    ProtocolParams,
    Thresholds,
)
from zonepad.domain.protocol import CaptureManifest, ManifestDevice, Segment

MAX_MANIFEST_BYTES = 1 << 20
MAX_THRESHOLDS_BYTES = 64 << 10

_SEGMENT_FIELDS: dict[str, frozenset[str]] = {
    "rest": frozenset({"kind", "start_ns", "end_ns", "warmup_ns"}),
    "circle": frozenset({"kind", "start_ns", "end_ns", "stick", "direction"}),
    "trigger_sweep": frozenset({"kind", "start_ns", "end_ns", "trigger"}),
}
_SEGMENT_REQUIRED: dict[str, frozenset[str]] = {
    "rest": frozenset({"kind", "start_ns", "end_ns"}),
    "circle": frozenset({"kind", "start_ns", "end_ns", "stick", "direction"}),
    "trigger_sweep": frozenset({"kind", "start_ns", "end_ns", "trigger"}),
}


class _Problem(ValueError):
    """Field-level problem; the loader prefixes the file name."""


def _reject_constant(name: str) -> NoReturn:
    raise _Problem(f"constante JSON não permitida: {name}")


def _no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _Problem(f"campo duplicado: {key}")
        result[key] = value
    return result


def _load_json(path: Path, limit: int, code: str, label: str) -> Any:
    name = path.name
    try:
        size = path.expanduser().stat().st_size
        if size > limit:
            raise MeasurementInputError(
                code, f"{name}: {label} com {size} bytes excede o limite de {limit} bytes"
            )
        text = path.expanduser().read_text(encoding="utf-8")
    except OSError as exc:
        raise MeasurementInputError(
            code, f"{name}: não foi possível ler o {label} ({exc.strerror or exc})"
        ) from exc
    except UnicodeDecodeError as exc:
        raise MeasurementInputError(code, f"{name}: o {label} não é UTF-8 válido") from exc
    try:
        return json.loads(text, object_pairs_hook=_no_duplicates, parse_constant=_reject_constant)
    except json.JSONDecodeError as exc:
        raise MeasurementInputError(
            code, f"{name}:{exc.lineno}: JSON inválido ({exc.msg}, coluna {exc.colno})"
        ) from exc
    except ValueError as exc:
        raise MeasurementInputError(code, f"{name}: {exc}") from exc


def _object(value: Any, field: str, allowed: frozenset[str] | set[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise _Problem(f"{field} deve ser um objeto")
    unknown = sorted(set(value) - set(allowed))
    if unknown:
        raise _Problem(f"{field}: campos desconhecidos ou não permitidos: {', '.join(unknown)}")
    return value


def _require(data: Mapping[str, Any], names: frozenset[str] | set[str], field: str) -> None:
    missing = sorted(set(names) - set(data))
    if missing:
        raise _Problem(f"{field}: campos obrigatórios ausentes: {', '.join(missing)}")


def _integer(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise _Problem(f"{field} deve ser um inteiro JSON, recebido {value!r}")
    return value


def _number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _Problem(f"{field} deve ser um número, recebido {value!r}")
    result = float(value)
    if not math.isfinite(result):
        raise _Problem(f"{field} deve ser finito")
    return result


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise _Problem(f"{field} deve ser um texto, recebido {value!r}")
    return value


def _optional_text(data: Mapping[str, Any], key: str, field: str) -> str | None:
    value = data.get(key)
    return None if value is None else _text(value, f"{field}.{key}")


def _parse_segment(raw: Any, index: int) -> Segment:
    field = f"segments[{index}]"
    if not isinstance(raw, dict):
        raise _Problem(f"{field} deve ser um objeto")
    kind = raw.get("kind")
    if kind not in _SEGMENT_FIELDS:
        raise _Problem(f"{field}.kind desconhecido: {kind!r} (use rest, circle ou trigger_sweep)")
    data = _object(raw, field, _SEGMENT_FIELDS[kind])
    _require(data, _SEGMENT_REQUIRED[kind], field)
    try:
        return Segment(
            kind,
            _integer(data["start_ns"], f"{field}.start_ns"),
            _integer(data["end_ns"], f"{field}.end_ns"),
            _integer(data.get("warmup_ns", 0), f"{field}.warmup_ns"),
            _text(data["stick"], f"{field}.stick") if "stick" in data else None,
            _text(data["direction"], f"{field}.direction") if "direction" in data else None,
            _text(data["trigger"], f"{field}.trigger") if "trigger" in data else None,
        )
    except _Problem:
        raise
    except ValueError as exc:
        raise _Problem(f"{field}: {exc}") from exc


def _parse_device(raw: Any) -> ManifestDevice:
    data = _object(raw, "device", {"device_id", "name", "vid", "pid", "guid", "serial"})
    _require(data, {"device_id", "name", "vid", "pid"}, "device")
    try:
        return ManifestDevice(
            _text(data["device_id"], "device.device_id"),
            _text(data["name"], "device.name"),
            _text(data["vid"], "device.vid"),
            _text(data["pid"], "device.pid"),
            _optional_text(data, "guid", "device"),
            _optional_text(data, "serial", "device"),
        )
    except _Problem:
        raise
    except ValueError as exc:
        raise _Problem(str(exc)) from exc


def _parse_manifest(raw: Any) -> CaptureManifest:
    data = _object(
        raw,
        "manifesto",
        {
            "manifest_version",
            "device",
            "capture_file",
            "capture_sha256",
            "nominal_rate_hz",
            "connection",
            "segments",
        },
    )
    _require(data, {"manifest_version", "device", "capture_file", "segments"}, "manifesto")
    segments = data["segments"]
    if not isinstance(segments, list):
        raise _Problem("segments deve ser uma lista")
    if len(segments) > 256:
        raise _Problem(f"segments tem {len(segments)} itens; o máximo é 256")
    try:
        return CaptureManifest(
            device=_parse_device(data["device"]),
            capture_file=_text(data["capture_file"], "capture_file"),
            segments=tuple(_parse_segment(item, i) for i, item in enumerate(segments)),
            capture_sha256=(
                _text(data["capture_sha256"], "capture_sha256")
                if data.get("capture_sha256") is not None
                else None
            ),
            nominal_rate_hz=(
                _number(data["nominal_rate_hz"], "nominal_rate_hz")
                if data.get("nominal_rate_hz") is not None
                else None
            ),
            connection=_text(data.get("connection", "unknown"), "connection"),
            manifest_version=_integer(data["manifest_version"], "manifest_version"),
        )
    except _Problem:
        raise
    except ValueError as exc:
        raise _Problem(str(exc)) from exc


def load_manifest(path: Path) -> CaptureManifest:
    """Load a capture manifest; every failure is a ``MeasurementInputError`` naming the field."""
    raw = _load_json(path, MAX_MANIFEST_BYTES, "INVALID_MANIFEST", "manifesto")
    try:
        return _parse_manifest(raw)
    except _Problem as exc:
        raise MeasurementInputError("INVALID_MANIFEST", f"{path.name}: {exc}") from exc


# ------------------------------------------------------------------------------ thresholds


def _section(
    data: Mapping[str, Any], cls: type, prefix: str, skip: frozenset[str] = frozenset()
) -> dict[str, Any]:
    """Typed values for the dataclass fields present in ``data`` (others use defaults)."""
    defaults = cls()
    values: dict[str, Any] = {}
    for item in dataclasses.fields(cls):
        if item.name in skip or item.name not in data:
            continue
        field = f"{prefix}{item.name}"
        if isinstance(getattr(defaults, item.name), int):
            values[item.name] = _integer(data[item.name], field)
        else:
            values[item.name] = _number(data[item.name], field)
    return values


def _parse_thresholds(raw: Any) -> MetricsConfig:
    names = {item.name for item in dataclasses.fields(Thresholds)}
    data = _object(raw, "thresholds", names | {"thresholds_version", "deadzone", "protocol"})
    _require(data, {"thresholds_version"}, "thresholds")
    version = _integer(data["thresholds_version"], "thresholds_version")
    if version != THRESHOLDS_VERSION:
        raise _Problem(
            f"thresholds_version {version} não suportada (suportadas: {THRESHOLDS_VERSION})"
        )
    deadzone_names = {item.name for item in dataclasses.fields(DeadzoneParams)}
    protocol_names = {item.name for item in dataclasses.fields(ProtocolParams)}
    deadzone = _object(data.get("deadzone", {}), "deadzone", deadzone_names)
    protocol = _object(data.get("protocol", {}), "protocol", protocol_names)
    try:
        return MetricsConfig(
            Thresholds(**_section(data, Thresholds, "")),
            DeadzoneParams(**_section(deadzone, DeadzoneParams, "deadzone.")),
            ProtocolParams(**_section(protocol, ProtocolParams, "protocol.")),
        )
    except _Problem:
        raise
    except ValueError as exc:
        raise _Problem(str(exc)) from exc


def load_metrics_config(path: Path | None) -> MetricsConfig:
    """Defaults when ``path`` is None; otherwise the strict ``--thresholds`` file."""
    if path is None:
        return MetricsConfig()
    raw = _load_json(path, MAX_THRESHOLDS_BYTES, "INVALID_THRESHOLDS", "arquivo de thresholds")
    try:
        return _parse_thresholds(raw)
    except _Problem as exc:
        raise MeasurementInputError("INVALID_THRESHOLDS", f"{path.name}: {exc}") from exc
