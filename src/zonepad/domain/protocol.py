from __future__ import annotations

import math
import re
from dataclasses import dataclass

SEGMENT_KINDS: tuple[str, ...] = ("rest", "circle", "trigger_sweep")
SIDES: tuple[str, ...] = ("left", "right")
DIRECTIONS: tuple[str, ...] = ("cw", "ccw")
CONNECTIONS: tuple[str, ...] = ("usb", "bluetooth", "wireless_dongle", "unknown")
MAX_SEGMENTS = 256

_HEX_ID = re.compile(r"^0x[0-9a-fA-F]{4}$")
_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")


@dataclass(frozen=True, slots=True)
class Segment:
    """Declared capture window ``[start_ns, end_ns)`` with the user action it contains."""

    kind: str
    start_ns: int
    end_ns: int
    warmup_ns: int = 0
    stick: str | None = None
    direction: str | None = None
    trigger: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in SEGMENT_KINDS:
            raise ValueError(f"kind desconhecido: {self.kind!r}")
        if self.start_ns < 0 or self.end_ns < 0:
            raise ValueError("start_ns e end_ns devem ser >= 0")
        if self.start_ns >= self.end_ns:
            raise ValueError("start_ns deve ser menor que end_ns")
        if self.kind == "rest":
            if not 0 <= self.warmup_ns < self.end_ns - self.start_ns:
                raise ValueError("warmup_ns deve estar em [0, end_ns - start_ns)")
            if self.stick is not None or self.direction is not None or self.trigger is not None:
                raise ValueError("segmento rest aceita apenas warmup_ns")
        elif self.kind == "circle":
            if self.stick not in SIDES or self.direction not in DIRECTIONS:
                raise ValueError("segmento circle exige stick (left/right) e direction (cw/ccw)")
            if self.warmup_ns != 0 or self.trigger is not None:
                raise ValueError("segmento circle aceita apenas stick e direction")
        else:
            if self.trigger not in SIDES:
                raise ValueError("segmento trigger_sweep exige trigger (left/right)")
            if self.warmup_ns != 0 or self.stick is not None or self.direction is not None:
                raise ValueError("segmento trigger_sweep aceita apenas trigger")

    @property
    def effective_start_ns(self) -> int:
        return self.start_ns + self.warmup_ns


@dataclass(frozen=True, slots=True)
class ManifestDevice:
    device_id: str
    name: str
    vid: str
    pid: str
    guid: str | None = None
    serial: str | None = None

    def __post_init__(self) -> None:
        if not self.device_id:
            raise ValueError("device.device_id não pode ser vazio")
        if not 1 <= len(self.name) <= 200:
            raise ValueError("device.name deve ter entre 1 e 200 caracteres")
        if not _HEX_ID.fullmatch(self.vid) or not _HEX_ID.fullmatch(self.pid):
            raise ValueError("device.vid e device.pid devem seguir o formato 0x0000")


@dataclass(frozen=True, slots=True)
class CaptureManifest:
    """Sidecar describing the capture protocol; ``segments`` are ordered and disjoint."""

    device: ManifestDevice
    capture_file: str
    segments: tuple[Segment, ...]
    capture_sha256: str | None = None
    nominal_rate_hz: float | None = None
    connection: str = "unknown"
    manifest_version: int = 1

    SUPPORTED_VERSIONS = (1,)

    def __post_init__(self) -> None:
        if self.manifest_version not in self.SUPPORTED_VERSIONS:
            supported = ", ".join(map(str, self.SUPPORTED_VERSIONS))
            raise ValueError(
                f"manifest_version {self.manifest_version} não suportada (suportadas: {supported})"
            )
        if not 1 <= len(self.segments) <= MAX_SEGMENTS:
            raise ValueError(f"segments deve ter entre 1 e {MAX_SEGMENTS} itens")
        name = self.capture_file
        if not name or name in {".", ".."} or "/" in name or "\\" in name:
            raise ValueError("capture_file deve ser um nome de arquivo sem diretórios")
        if self.capture_sha256 is not None and not _SHA256.fullmatch(self.capture_sha256):
            raise ValueError("capture_sha256 deve ter 64 dígitos hexadecimais")
        if self.nominal_rate_hz is not None and (
            not math.isfinite(self.nominal_rate_hz) or self.nominal_rate_hz <= 0
        ):
            raise ValueError("nominal_rate_hz deve ser finito e maior que zero")
        if self.connection not in CONNECTIONS:
            raise ValueError(f"connection deve ser um de: {', '.join(CONNECTIONS)}")
        for index, (previous, current) in enumerate(
            zip(self.segments, self.segments[1:], strict=False), 1
        ):
            if current.start_ns < previous.start_ns:
                raise ValueError(f"segments[{index}] está fora de ordem (start_ns decrescente)")
            if previous.end_ns > current.start_ns:
                raise ValueError(f"segments[{index}] sobrepõe segments[{index - 1}]")
