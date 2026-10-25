"""Strict JSONL capture reader for ``zonepad measure``.

``replay.load_capture`` stays lenient for ``zonepad replay``; this reader validates every field
and cites the file and line of each problem.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn

from zonepad.domain.errors import MeasurementInputError
from zonepad.domain.input import RawFrame

from .files import sha256_bytes

MAX_CAPTURE_BYTES = 32 << 20
_ALLOWED_FIELDS = frozenset({"device_id", "timestamp_ns", "axes", "triggers", "buttons"})


@dataclass(frozen=True, slots=True)
class LoadedCapture:
    frames: tuple[RawFrame, ...]
    sha256: str
    file_name: str


class _LineProblem(ValueError):
    """Raised by JSON hooks and field checks; the reader adds file and line."""


def _reject_constant(name: str) -> NoReturn:
    raise _LineProblem(f"constante JSON não permitida: {name}")


def _no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _LineProblem(f"campo duplicado: {key}")
        result[key] = value
    return result


def _integer(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise _LineProblem(f"{field} deve ser um inteiro JSON, recebido {value!r}")
    return value


def _channels(value: Any, field: str) -> dict[str, int]:
    if not isinstance(value, dict):
        raise _LineProblem(f"{field} deve ser um objeto")
    return {name: _integer(raw, f"{field}.{name}") for name, raw in value.items()}


def _parse_line(text: str) -> RawFrame:
    data = json.loads(text, object_pairs_hook=_no_duplicates, parse_constant=_reject_constant)
    if not isinstance(data, dict):
        raise _LineProblem("cada linha deve ser um objeto JSON")
    unknown = sorted(set(data) - _ALLOWED_FIELDS)
    if unknown:
        raise _LineProblem(f"campos desconhecidos: {', '.join(unknown)}")
    for required in ("device_id", "timestamp_ns"):
        if required not in data:
            raise _LineProblem(f"campo obrigatório ausente: {required}")
    device_id = data["device_id"]
    if not isinstance(device_id, str) or not device_id:
        raise _LineProblem("device_id deve ser um texto não vazio")
    timestamp = _integer(data["timestamp_ns"], "timestamp_ns")
    if timestamp < 0:
        raise _LineProblem("timestamp_ns deve ser >= 0")
    buttons = data.get("buttons", [])
    if not isinstance(buttons, list) or any(not isinstance(b, str) for b in buttons):
        raise _LineProblem("buttons deve ser uma lista de textos")
    return RawFrame(
        device_id,
        timestamp,
        _channels(data.get("axes", {}), "axes"),
        _channels(data.get("triggers", {}), "triggers"),
        frozenset(buttons),
    )


def read_strict_capture(path: Path) -> LoadedCapture:
    """Read and validate a capture; raises ``MeasurementInputError`` with file and line."""
    name = path.name
    try:
        size = path.expanduser().stat().st_size
        if size > MAX_CAPTURE_BYTES:
            raise MeasurementInputError(
                "INVALID_CAPTURE",
                f"{name}: a captura tem {size} bytes e excede o limite de {MAX_CAPTURE_BYTES} "
                "bytes; divida a sessão em capturas menores",
            )
        payload = path.expanduser().read_bytes()
    except OSError as exc:
        raise MeasurementInputError(
            "INVALID_CAPTURE", f"{name}: não foi possível ler a captura ({exc.strerror or exc})"
        ) from exc
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise MeasurementInputError(
            "INVALID_CAPTURE", f"{name}: a captura não é UTF-8 válido (byte {exc.start})"
        ) from exc
    lines = text.split("\n")
    if lines[-1] == "":
        lines.pop()
    if not text.strip():
        raise MeasurementInputError(
            "EMPTY_CAPTURE", f"{name}: a captura está vazia; grave frames JSONL antes de medir"
        )
    frames: list[RawFrame] = []
    for number, line in enumerate(lines, 1):
        try:
            frame = _parse_line(line)
        except json.JSONDecodeError as exc:
            raise MeasurementInputError(
                "INVALID_CAPTURE", f"{name}:{number}: JSON inválido ({exc.msg}, coluna {exc.colno})"
            ) from exc
        except ValueError as exc:
            raise MeasurementInputError("INVALID_CAPTURE", f"{name}:{number}: {exc}") from exc
        if frames and frame.device_id != frames[0].device_id:
            raise MeasurementInputError(
                "INVALID_CAPTURE",
                f"{name}:{number}: device_id {frame.device_id!r} difere de "
                f"{frames[0].device_id!r}; uma captura deve ter um único dispositivo",
            )
        if frames and frame.timestamp_ns < frames[-1].timestamp_ns:
            raise MeasurementInputError(
                "NON_MONOTONIC_TIME",
                f"{name}:{number}: timestamp_ns decresce de {frames[-1].timestamp_ns} para "
                f"{frame.timestamp_ns}; regrave a captura com relógio monotônico",
            )
        frames.append(frame)
    return LoadedCapture(tuple(frames), sha256_bytes(payload), name)
