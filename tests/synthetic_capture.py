"""Synthetic captures for the measurement tests: no hardware, no real clock, no sleep.

Raw counts use a +/-1_000_000 mapping so that normalized values are exact to ~1e-6 and
"round" numbers such as 0.1 or 0.01 survive normalization bit for bit.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from zonepad.application.measure import MeasureInputs
from zonepad.domain.input import RawFrame
from zonepad.domain.metrics import MetricsConfig
from zonepad.domain.normalization import AxisRange, TriggerRange
from zonepad.domain.protocol import CaptureManifest, ManifestDevice, Segment

SCALE = 1_000_000
CHANNELS = ("lx", "ly", "rx", "ry", "lt", "rt")
AXIS_RANGES = {name: AxisRange(-SCALE, 0, SCALE) for name in ("lx", "ly", "rx", "ry")}
TRIGGER_RANGES = {name: TriggerRange(0, SCALE) for name in ("lt", "rt")}
FIXED_NOW = datetime(2026, 10, 24, 0, 0, 0, tzinfo=UTC)
FIXED_PROFILE_ID = "550e8400-e29b-41d4-a716-446655440000"
DEVICE_ID = "event3"


def fixed_now() -> datetime:
    return FIXED_NOW


def fixed_profile_id() -> str:
    return FIXED_PROFILE_ID


def mapping_payload() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "axes": {
            name: {"code": code, "minimum": -SCALE, "center": 0, "maximum": SCALE}
            for name, code in (("lx", 0), ("ly", 1), ("rx", 3), ("ry", 4))
        },
        "triggers": {
            name: {"code": code, "rest": 0, "maximum": SCALE}
            for name, code in (("lt", 2), ("rt", 5))
        },
    }


@dataclass
class Recorder:
    """Builds frames on a fixed-rate timeline and records the matching manifest segments."""

    rate_hz: float = 125.0
    start_ns: int = 1_000_000_000
    device_id: str = DEVICE_ID
    drop: frozenset[str] = frozenset()
    extra_axes: dict[str, int] = field(default_factory=dict)
    frames: list[dict[str, Any]] = field(default_factory=list)
    segments: list[dict[str, Any]] = field(default_factory=list)
    state: dict[str, float] = field(default_factory=lambda: dict.fromkeys(CHANNELS, 0.0))
    _tick: int = 0

    @property
    def now_ns(self) -> int:
        return self.start_ns + round(self._tick * 1e9 / self.rate_hz)

    def tick(self, **values: float) -> None:
        self.state.update(values)
        axes = {
            n: round(self.state[n] * SCALE) for n in ("lx", "ly", "rx", "ry") if n not in self.drop
        }
        axes.update(self.extra_axes)
        triggers = {n: round(self.state[n] * SCALE) for n in ("lt", "rt") if n not in self.drop}
        self.frames.append(
            {
                "device_id": self.device_id,
                "timestamp_ns": self.now_ns,
                "axes": axes,
                "triggers": triggers,
                "buttons": [],
            }
        )
        self._tick += 1

    def hold(self, seconds: float, **values: float) -> None:
        for _ in range(round(seconds * self.rate_hz)):
            self.tick(**values)

    def pause(self, seconds: float) -> None:
        """Advance the clock without emitting frames (frames outside every segment)."""
        self._tick += round(seconds * self.rate_hz)

    def segment(self, kind: str, begin_tick: int, **fields: Any) -> None:
        self.segments.append(
            {
                "kind": kind,
                "start_ns": self.start_ns + round(begin_tick * 1e9 / self.rate_hz),
                "end_ns": self.now_ns,
                **fields,
            }
        )

    def rest(
        self,
        seconds: float = 5.0,
        warmup_s: float = 1.0,
        sampler: Callable[[int], dict[str, float]] | None = None,
        **values: float,
    ) -> None:
        begin = self._tick
        for index in range(round(seconds * self.rate_hz)):
            self.tick(**{**values, **(sampler(index) if sampler else {})})
        self.segment("rest", begin, warmup_ns=round(warmup_s * 1e9))

    def circle(
        self,
        stick: str,
        direction: str,
        laps: int = 3,
        points_per_lap: int = 125,
        radius: tuple[float, float] = (0.95, 0.95),
        center: tuple[float, float] = (0.0, 0.0),
        sign: int | None = None,
        label: str | None = None,
    ) -> None:
        names = ("lx", "ly") if stick == "left" else ("rx", "ry")
        turn = sign if sign is not None else (-1 if direction == "cw" else 1)
        begin = self._tick
        for step in range(laps * points_per_lap + 2):
            angle = turn * 2.0 * math.pi * step / points_per_lap
            self.tick(
                **{
                    names[0]: center[0] + radius[0] * math.cos(angle),
                    names[1]: center[1] + radius[1] * math.sin(angle),
                }
            )
        self.segment("circle", begin, stick=stick, direction=label or direction)
        self.tick(**{names[0]: 0.0, names[1]: 0.0})

    def sweep(
        self,
        trigger: str,
        cycles: int = 5,
        peak: float = 1.0,
        up_s: float = 2.0,
        down_s: float = 2.0,
        down_curve: Callable[[float], float] | None = None,
    ) -> None:
        name = "lt" if trigger == "left" else "rt"
        up, down = round(up_s * self.rate_hz), round(down_s * self.rate_hz)
        begin = self._tick
        self.hold(0.5, **{name: 0.0})
        for _ in range(cycles):
            for index in range(up):
                self.tick(**{name: peak * index / up})
            self.hold(0.5, **{name: peak})
            for index in range(down):
                progress = 1.0 - index / down
                shaped = down_curve(progress) if down_curve else progress
                self.tick(**{name: min(peak, max(0.0, peak * shaped))})
            self.hold(0.5, **{name: 0.0})
        self.segment("trigger_sweep", begin, trigger=trigger)

    # ------------------------------------------------------------------ outputs

    def raw_frames(self) -> tuple[RawFrame, ...]:
        return tuple(
            RawFrame(f["device_id"], f["timestamp_ns"], f["axes"], f["triggers"], frozenset())
            for f in self.frames
        )

    def jsonl(self) -> str:
        return "".join(json.dumps(f) + "\n" for f in self.frames)

    def manifest_payload(self, capture_file: str = "capture.jsonl", **extra: Any) -> dict[str, Any]:
        return {
            "manifest_version": 1,
            "device": {
                "device_id": self.device_id,
                "name": "Synthetic Pad",
                "vid": "0x045e",
                "pid": "0x0b13",
            },
            "capture_file": capture_file,
            "segments": [dict(segment) for segment in self.segments],
            **extra,
        }

    def manifest(self, capture_file: str = "capture.jsonl", **extra: Any) -> CaptureManifest:
        segments = tuple(
            Segment(
                s["kind"],
                s["start_ns"],
                s["end_ns"],
                s.get("warmup_ns", 0),
                s.get("stick"),
                s.get("direction"),
                s.get("trigger"),
            )
            for s in self.segments
        )
        return CaptureManifest(
            ManifestDevice(self.device_id, "Synthetic Pad", "0x045e", "0x0b13"),
            capture_file,
            segments,
            **extra,
        )

    def inputs(
        self,
        config: MetricsConfig | None = None,
        capture_file: str = "capture.jsonl",
        **manifest_extra: Any,
    ) -> MeasureInputs:
        return MeasureInputs(
            self.raw_frames(),
            capture_file,
            "a" * 64,
            self.manifest(capture_file, **manifest_extra),
            AXIS_RANGES,
            TRIGGER_RANGES,
            "b" * 64,
            config or MetricsConfig(),
        )


DEFAULT_CIRCLES: tuple[tuple[str, str, dict[str, Any]], ...] = (
    ("left", "cw", {}),
    ("left", "ccw", {}),
    ("right", "cw", {}),
    ("right", "ccw", {}),
)


def full_session(
    *,
    with_rest: bool = True,
    rest_s: float = 5.0,
    warmup_s: float = 1.0,
    rest_noise: Callable[[int], dict[str, float]] | None = None,
    rest_values: dict[str, float] | None = None,
    circles: Sequence[tuple[str, str, dict[str, Any]]] = DEFAULT_CIRCLES,
    sweeps: Sequence[tuple[str, dict[str, Any]]] = (("left", {}), ("right", {})),
    **recorder_options: Any,
) -> Recorder:
    """A well-formed ~85 s session: rest, both circles per stick, five cycles per trigger."""
    rec = Recorder(**recorder_options)
    rec.hold(2.0)  # warm-up outside any segment
    if with_rest:
        rec.rest(rest_s, warmup_s, rest_noise, **(rest_values or {}))
    for stick, direction, options in circles:
        rec.hold(0.5)
        rec.circle(stick, direction, **options)
    for trigger, options in sweeps:
        rec.hold(0.5)
        rec.sweep(trigger, **options)
    rec.hold(0.5)
    return rec
