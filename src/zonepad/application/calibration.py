from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from types import MappingProxyType

from zonepad.domain.device import DeviceInfo
from zonepad.domain.errors import InvalidProfileError, ProfileDerivationError
from zonepad.domain.input import NormalizedFrame
from zonepad.domain.metrics import MeasurementMetrics
from zonepad.domain.profile import (
    CalibrationProfile,
    DeadzoneSpec,
    DeviceIdentity,
    StickCalibration,
    TriggerCalibration,
)

_NOTES_LIMIT = 2000


def build_profile(
    device: DeviceInfo, samples: Sequence[NormalizedFrame], app_version: str = "0.1.0"
) -> CalibrationProfile:
    """Build a conservative profile from captured normalized samples.

    Legado: usa média, ``min``/``max`` crus e epsilon silencioso, sem medir ruído ou deadzone.
    Para perfis derivados de métricas medidas, use ``build_profile_from_metrics``.
    """
    if not samples:
        raise ValueError("at least one sample is required")
    axes = {
        name: [frame.axes[name] for frame in samples if name in frame.axes]
        for name in ("lx", "ly", "rx", "ry")
    }
    sticks: dict[str, StickCalibration] = {}
    for side, names in (("left", ("lx", "ly")), ("right", ("rx", "ry"))):
        values = [axes[name] for name in names]
        center = (
            float(sum(values[0]) / len(values[0])) if values[0] else 0.0,
            float(sum(values[1]) / len(values[1])) if values[1] else 0.0,
        )
        minimum = (float(min(values[0], default=-1.0)), float(min(values[1], default=-1.0)))
        maximum = (float(max(values[0], default=1.0)), float(max(values[1], default=1.0)))
        minimum = (
            minimum[0] if minimum[0] < center[0] else max(-1.0, center[0] - 1e-6),
            minimum[1] if minimum[1] < center[1] else max(-1.0, center[1] - 1e-6),
        )
        maximum = (
            maximum[0] if maximum[0] > center[0] else min(1.0, center[0] + 1e-6),
            maximum[1] if maximum[1] > center[1] else min(1.0, center[1] + 1e-6),
        )
        sticks[side] = StickCalibration(center=center, range_min=minimum, range_max=maximum)
    trigger_values = {
        name: [frame.triggers[name] for frame in samples if name in frame.triggers]
        for name in ("lt", "rt", "left_trigger", "right_trigger")
    }

    def trigger_profile(values: list[float]) -> TriggerCalibration:
        rest = min(values or [0.0])
        maximum = max(values or [1.0])
        if maximum <= rest:
            maximum = min(1.0, rest + 1e-6)
        if maximum <= rest:
            rest = max(0.0, maximum - 1e-6)
        return TriggerCalibration(rest=rest, max=maximum)

    triggers = {
        "left": trigger_profile(trigger_values["lt"] or trigger_values["left_trigger"]),
        "right": trigger_profile(trigger_values["rt"] or trigger_values["right_trigger"]),
    }
    vid = f"0x{(device.vendor_id or 0):04x}"
    pid = f"0x{(device.product_id or 0):04x}"
    return CalibrationProfile(
        1,
        str(uuid.uuid4()),
        DeviceIdentity(device.name, vid, pid, device.guid, device.serial),
        sticks,
        triggers,
        datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        app_version,
    )


@dataclass(frozen=True, slots=True)
class DerivedCalibration:
    """Stick/trigger calibrations derived from measured metrics (schema-v1 fields only)."""

    sticks: Mapping[str, StickCalibration]
    triggers: Mapping[str, TriggerCalibration]

    def __post_init__(self) -> None:
        object.__setattr__(self, "sticks", MappingProxyType(dict(self.sticks)))
        object.__setattr__(self, "triggers", MappingProxyType(dict(self.triggers)))


def _round6(value: float) -> float:
    return round(value, 6) + 0.0  # "+ 0.0" turns -0.0 into 0.0


def _round_pair(pair: tuple[float, float]) -> tuple[float, float]:
    return (_round6(pair[0]), _round6(pair[1]))


def derive_calibration(metrics: MeasurementMetrics) -> DerivedCalibration:
    """Derive centers, ranges, deadzones and trigger rest/max without any epsilon.

    Raises ``ProfileDerivationError`` naming the metric and the action when the measurement
    cannot yield a valid profile (any ``error`` finding, missing metric or broken invariant).
    """
    errors = sorted({f.code for f in metrics.findings if f.severity == "error"})
    if errors:
        raise ProfileDerivationError(
            f"não é possível derivar o perfil: achados de erro pendentes ({', '.join(errors)})"
        )
    sticks: dict[str, StickCalibration] = {}
    for side, stick in metrics.sticks.items():
        if stick.center is None or stick.axis_range is None or stick.deadzone is None:
            raise ProfileDerivationError(
                f"stick {side}: faltam repouso ou círculo medidos; refaça a captura"
            )
        try:
            sticks[side] = StickCalibration(
                center=_round_pair(stick.center),
                range_min=_round_pair(stick.axis_range.min),
                range_max=_round_pair(stick.axis_range.max),
                deadzone=DeadzoneSpec("cut", _round6(stick.deadzone.value)),
            )
        except InvalidProfileError as exc:
            raise ProfileDerivationError(
                f"stick {side}: {exc}; refaça o círculo contornando toda a borda do gate"
            ) from exc
    triggers: dict[str, TriggerCalibration] = {}
    for side, trigger in metrics.triggers.items():
        if trigger.rest is None or trigger.max is None or trigger.deadzone is None:
            raise ProfileDerivationError(
                f"trigger {side}: faltam repouso ou ciclos válidos medidos; refaça a captura"
            )
        try:
            triggers[side] = TriggerCalibration(
                rest=_round6(trigger.rest),
                max=_round6(trigger.max),
                deadzone=_round6(trigger.deadzone.value),
            )
        except InvalidProfileError as exc:
            raise ProfileDerivationError(
                f"trigger {side}: {exc}; pressione o gatilho até o fundo e refaça o sweep"
            ) from exc
    return DerivedCalibration(sticks, triggers)


def format_utc(moment: datetime) -> str:
    """``YYYY-MM-DDTHH:MM:SSZ`` from an aware datetime; naive values are rejected."""
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise ValueError("now() deve devolver um datetime com fuso horário")
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _measurement_notes(metrics: MeasurementMetrics) -> str:
    warnings = sorted({f.code for f in metrics.findings if f.severity in ("warning", "error")})
    notes = (
        f"zonepad measure; captura={metrics.source_file}; sha256={metrics.source_sha256[:12]}; "
        f"metrics_schema_version=1; status={metrics.status}; avisos={','.join(warnings)}"
    )
    return notes if len(notes) <= _NOTES_LIMIT else notes[: _NOTES_LIMIT - 1] + "…"


def build_profile_from_metrics(
    device: DeviceInfo,
    metrics: MeasurementMetrics,
    *,
    app_version: str,
    now: Callable[[], datetime],
    profile_id_factory: Callable[[], str],
) -> CalibrationProfile:
    """Build a schema-v1 profile from measured metrics; deterministic given ``now``/the factory.

    The curve is ``linear`` and ``invert`` is false (D10). Raises ``ProfileDerivationError``
    when the metrics cannot yield a valid profile.
    """
    derived = derive_calibration(metrics)
    vid = f"0x{(device.vendor_id or 0):04x}"
    pid = f"0x{(device.product_id or 0):04x}"
    try:
        return CalibrationProfile(
            1,
            profile_id_factory(),
            DeviceIdentity(device.name, vid, pid, device.guid, device.serial),
            derived.sticks,
            derived.triggers,
            format_utc(now()),
            app_version,
            _measurement_notes(metrics),
        )
    except InvalidProfileError as exc:
        raise ProfileDerivationError(f"perfil derivado inválido: {exc}") from exc
