"""JSONL and manifest writer for guided captures."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from zonepad.application.ports import CaptureArtifacts
from zonepad.domain.device import DeviceInfo
from zonepad.domain.errors import MeasurementInputError
from zonepad.domain.input import RawFrame
from zonepad.domain.protocol import CaptureManifest, ManifestDevice, Segment
from zonepad.infrastructure.files import write_text_atomic

MAX_CAPTURE_BYTES = 32 << 20


class CaptureWriter:
    """Append frames and write a compatible sidecar, rebasing one monotonic timeline."""

    def __init__(self, directory: Path, device: DeviceInfo) -> None:
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=False)
        self.device = device
        self.capture_path = directory / "capture.jsonl"
        self.manifest_path = directory / "capture.manifest.json"
        self._stream = self.capture_path.open("xb")
        self._frames = 0
        self._first_ns: int | None = None
        self._last_ns: int | None = None
        self._segments: dict[tuple[str, ...], Segment] = {}
        self._closed = False

    def append(self, frame: RawFrame) -> None:
        if self._closed:
            raise RuntimeError("capture writer is closed")
        if frame.device_id != self.device.device_id:
            raise MeasurementInputError("INVALID_CAPTURE", "device_id mudou durante a sessão")
        if self._last_ns is not None and frame.timestamp_ns < self._last_ns:
            raise MeasurementInputError("NON_MONOTONIC_TIME", "timestamp do dispositivo decresceu")
        if self._first_ns is None:
            self._first_ns = frame.timestamp_ns
        row = {
            "device_id": frame.device_id,
            "timestamp_ns": frame.timestamp_ns - self._first_ns,
            "axes": dict(frame.axes),
            "triggers": dict(frame.triggers),
            "buttons": sorted(frame.buttons),
        }
        encoded = (
            json.dumps(row, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n"
        ).encode("utf-8")
        if self._stream.tell() + len(encoded) > MAX_CAPTURE_BYTES:
            raise MeasurementInputError(
                "INVALID_CAPTURE", "captura aproximou o limite de 32 MiB; sessão interrompida"
            )
        self._stream.write(encoded)
        self._last_ns = frame.timestamp_ns
        self._frames += 1

    def replace_segment(
        self, target: tuple[str, ...], segment: Segment, start_abs_ns: int, end_abs_ns: int
    ) -> bool:
        """Store a clamped semi-open window; return false when no observed interval exists."""
        self._segments.pop(target, None)
        if self._first_ns is None or self._last_ns is None:
            return False
        start = max(self._first_ns, start_abs_ns)
        end = min(self._last_ns + 1, end_abs_ns)
        if start >= end:
            return False
        rebased_start, rebased_end = start - self._first_ns, end - self._first_ns
        try:
            clamped = Segment(
                segment.kind,
                rebased_start,
                rebased_end,
                segment.warmup_ns,
                segment.stick,
                segment.direction,
                segment.trigger,
            )
        except ValueError:
            return False
        self._segments[target] = clamped
        return True

    def _payload(self) -> bytes:
        if not self._closed:
            self._stream.flush()
        return self.capture_path.read_bytes()

    def _write_manifest(self) -> None:
        payload = self._payload()
        segments = tuple(
            sorted(self._segments.values(), key=lambda item: (item.start_ns, item.end_ns))
        )
        manifest = CaptureManifest(
            ManifestDevice(
                self.device.device_id,
                (self.device.name or self.device.device_id)[:200],
                f"0x{(self.device.vendor_id or 0):04x}",
                f"0x{(self.device.product_id or 0):04x}",
                self.device.guid,
                self.device.serial,
            ),
            self.capture_path.name,
            segments,
            hashlib.sha256(payload).hexdigest(),
        )
        raw = {
            "manifest_version": manifest.manifest_version,
            "device": {
                "device_id": manifest.device.device_id,
                "name": manifest.device.name,
                "vid": manifest.device.vid,
                "pid": manifest.device.pid,
                **({"guid": manifest.device.guid} if manifest.device.guid else {}),
                **({"serial": manifest.device.serial} if manifest.device.serial else {}),
            },
            "capture_file": manifest.capture_file,
            "capture_sha256": manifest.capture_sha256,
            "connection": "unknown",
            "segments": [
                {
                    "kind": s.kind,
                    "start_ns": s.start_ns,
                    "end_ns": s.end_ns,
                    **({"warmup_ns": s.warmup_ns} if s.kind == "rest" else {}),
                    **({"stick": s.stick, "direction": s.direction} if s.kind == "circle" else {}),
                    **({"trigger": s.trigger} if s.kind == "trigger_sweep" else {}),
                }
                for s in manifest.segments
            ],
        }
        write_text_atomic(
            self.manifest_path, json.dumps(raw, ensure_ascii=False, indent=2, sort_keys=True)
        )

    def flush(self) -> CaptureArtifacts:
        self._stream.flush()
        if self._segments:
            self._write_manifest()
        return CaptureArtifacts(
            str(self.directory), str(self.capture_path), str(self.manifest_path)
        )

    def finish(self) -> CaptureArtifacts:
        if not self._closed:
            self._stream.flush()
            self._stream.close()
            self._closed = True
        self._write_manifest()
        return CaptureArtifacts(
            str(self.directory), str(self.capture_path), str(self.manifest_path)
        )

    def abort(self) -> CaptureArtifacts:
        if not self._closed:
            self._stream.flush()
            self._stream.close()
            self._closed = True
        self.manifest_path.unlink(missing_ok=True)
        (self.directory / "report.json").unlink(missing_ok=True)
        (self.directory / "report.md").unlink(missing_ok=True)
        return CaptureArtifacts(
            str(self.directory), str(self.capture_path), str(self.manifest_path)
        )


def create_session_directory(root: Path, device_id: str, utc_stamp: str) -> Path:
    safe_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", device_id).strip("._-") or "device"
    base = root.expanduser() / f"{utc_stamp}-{safe_id}"
    candidate = base
    suffix = 2
    while candidate.exists():
        candidate = Path(f"{base}-{suffix}")
        suffix += 1
    return candidate
