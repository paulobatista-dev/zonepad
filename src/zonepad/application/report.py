"""Metrics report (``metrics_schema_version=1``): JSON building, strict validation, Markdown.

The JSON document is the source of truth. The Markdown renderer reads only the validated JSON
and never recomputes a metric.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from zonepad.domain.errors import InvalidReportError
from zonepad.domain.findings import STRICT_BLOCKING
from zonepad.domain.metrics import (
    DeadzoneSuggestion,
    MeasurementMetrics,
    MetricsConfig,
    RawChannelDiagnostics,
    Spread,
    StickMetrics,
    TriggerMetrics,
)
from zonepad.domain.protocol import Segment

from .calibration import DerivedCalibration

REPORT_KIND = "calibration-metrics"
METRICS_SCHEMA_VERSION = 1
_NO_VALUE = "n/d"


@dataclass(frozen=True, slots=True)
class SegmentSummary:
    """A declared segment plus what the capture holds inside it."""

    index: int
    segment: Segment
    frames: int
    effective_duration_s: float


@dataclass(frozen=True, slots=True)
class ReportContext:
    """Identity and provenance that complete the metrics in the report."""

    device_name: str
    vid: str
    pid: str
    connection: str
    mapping_sha256: str
    segments: Sequence[SegmentSummary]
    created_at: str
    app_version: str


# ------------------------------------------------------------------------------ building


def _pair(values: tuple[float, float] | None) -> list[float] | None:
    return None if values is None else [values[0], values[1]]


def _spread(spread: Spread | None) -> dict[str, float | None]:
    return {
        "median": None if spread is None else spread.median,
        "worst": None if spread is None else spread.worst,
    }


def _raw(diagnostics: RawChannelDiagnostics) -> dict[str, Any]:
    return {
        "mapping": dict(diagnostics.mapping),
        "rest_median": diagnostics.rest_median,
        "observed_min": diagnostics.observed_min,
        "observed_max": diagnostics.observed_max,
        "out_of_range_ratio": diagnostics.out_of_range_ratio,
        "lsb_normalized": diagnostics.lsb_normalized,
    }


def _stick_dict(stick: StickMetrics, raw: Mapping[str, RawChannelDiagnostics]) -> dict[str, Any]:
    noise = stick.rest.noise
    jitter = stick.rest.jitter
    axis_range = stick.axis_range
    circle = stick.circle
    deadzone: DeadzoneSuggestion | None = stick.deadzone
    return {
        "axes": list(stick.axes),
        "center": _pair(stick.center),
        "center_segment_max_shift": stick.center_segment_max_shift,
        "rest": {
            "frames": stick.rest.frames,
            "duration_s": stick.rest.duration_s,
            "valid_blocks": stick.rest.valid_blocks,
            "drift": stick.rest.drift,
            "noise_rms": {
                "x": None if noise is None else noise.rms_x,
                "y": None if noise is None else noise.rms_y,
                "xy": None if noise is None else noise.rms_xy,
            },
            "noise_p2p": {
                "x": None if noise is None else noise.p2p_x,
                "y": None if noise is None else noise.p2p_y,
            },
            "noise_radius": {
                "max": None if noise is None else noise.radius_max,
                "p99": None if noise is None else noise.radius_p99,
            },
            "jitter": {
                "mean": None if jitter is None else jitter.mean,
                "p99": None if jitter is None else jitter.p99,
                "max": None if jitter is None else jitter.max,
            },
        },
        "range": {
            "min": _pair(None if axis_range is None else axis_range.min),
            "max": _pair(None if axis_range is None else axis_range.max),
            "span": _pair(None if axis_range is None else axis_range.span),
            "observed_min": _pair(None if axis_range is None else axis_range.observed_min),
            "observed_max": _pair(None if axis_range is None else axis_range.observed_max),
            "symmetry": [None, None] if axis_range is None else list(axis_range.symmetry),
        },
        "circle": {
            "valid_laps": {"cw": circle.valid_laps_cw, "ccw": circle.valid_laps_ccw},
            "rejected_laps": circle.rejected_laps,
            "circularity": {
                "median": circle.circularity_median,
                "worst": circle.circularity_worst,
            },
            "mean_radius": {
                "median": circle.mean_radius_median,
                "worst": circle.mean_radius_worst,
            },
            "saturation_ratio": circle.saturation_ratio,
        },
        "deadzone_suggested": {
            "mode": "cut",
            "value": None if deadzone is None else deadzone.value,
            "basis_p99_calibrated": None if deadzone is None else deadzone.basis_p99,
        },
        "raw": {name: _raw(raw[name]) for name in stick.axes if name in raw},
    }


def _trigger_dict(
    channel: str, trigger: TriggerMetrics, raw: Mapping[str, RawChannelDiagnostics]
) -> dict[str, Any]:
    return {
        "input": channel,
        "rest": trigger.rest,
        "noise_rms": trigger.noise_rms,
        "noise_p2p": trigger.noise_p2p,
        "noise_p99": trigger.noise_p99,
        "max": trigger.max,
        "span": trigger.span,
        "max_values": list(trigger.max_values),
        "max_dispersion": trigger.max_dispersion,
        "cycles": {"detected": trigger.cycles_detected, "valid": trigger.cycles_valid},
        "shape_basis": "time_normalized",
        "linearity_r2": _spread(trigger.linearity_r2),
        "linearity_max_error": _spread(trigger.linearity_max_error),
        "hysteresis": _spread(trigger.hysteresis),
        "saturation_ratio": trigger.saturation_ratio,
        "deadzone_suggested": {
            "value": None if trigger.deadzone is None else trigger.deadzone.value
        },
        "raw": {channel: _raw(raw[channel])} if channel in raw else {},
    }


def _segment_dict(summary: SegmentSummary) -> dict[str, Any]:
    segment = summary.segment
    return {
        "kind": segment.kind,
        "index": summary.index,
        "start_ns": segment.start_ns,
        "end_ns": segment.end_ns,
        "effective_start_ns": segment.effective_start_ns,
        "frames": summary.frames,
        "effective_duration_s": summary.effective_duration_s,
        "stick": segment.stick,
        "direction": segment.direction,
        "trigger": segment.trigger,
    }


def _profile_summary(derived: DerivedCalibration | None, profile_id: str | None) -> dict[str, Any]:
    if derived is None:
        return {"derived": False, "profile_id": None, "sticks": {}, "triggers": {}}
    return {
        "derived": True,
        "profile_id": profile_id,
        "sticks": {
            side: {
                "center": list(stick.center),
                "range_min": list(stick.range_min),
                "range_max": list(stick.range_max),
                "deadzone": stick.deadzone.value,
            }
            for side, stick in derived.sticks.items()
        },
        "triggers": {
            side: {"rest": trigger.rest, "max": trigger.max, "deadzone": trigger.deadzone}
            for side, trigger in derived.triggers.items()
        },
    }


def build_report(
    metrics: MeasurementMetrics,
    context: ReportContext,
    derived: DerivedCalibration | None,
    profile_id: str | None,
) -> dict[str, Any]:
    """Build the JSON-ready report (plain dict) from evaluated metrics."""
    capture = metrics.capture
    config: MetricsConfig = metrics.config
    return {
        "report_kind": REPORT_KIND,
        "metrics_schema_version": METRICS_SCHEMA_VERSION,
        "app_version": context.app_version,
        "created_at": context.created_at,
        "device": {"name": context.device_name, "vid": context.vid, "pid": context.pid},
        "capture": {
            "file": metrics.source_file,
            "sha256": metrics.source_sha256,
            "frames": capture.frames,
            "frames_outside_segments": capture.frames_outside_segments,
            "duration_s": capture.duration_s,
            "connection": context.connection,
            "nominal_rate_hz": metrics.nominal_rate_hz,
            "effective_rate_hz": capture.effective_rate_hz,
            "rate_p5_hz": capture.rate_p5_hz,
            "rate_p95_hz": capture.rate_p95_hz,
            "rate_pairs": capture.rate_pairs,
        },
        "normalization": {"source": "mapping", "mapping_sha256": context.mapping_sha256},
        "protocol": {"segments": [_segment_dict(s) for s in context.segments]},
        "sticks": {side: _stick_dict(stick, metrics.raw) for side, stick in metrics.sticks.items()},
        "triggers": {
            side: _trigger_dict("lt" if side == "left" else "rt", trigger, metrics.raw)
            for side, trigger in metrics.triggers.items()
        },
        "profile_summary": _profile_summary(derived, profile_id),
        "quality": {
            "status": metrics.status,
            "findings": [
                {
                    "code": f.code,
                    "severity": f.severity,
                    "message": f.message,
                    "metric": f.metric,
                    "value": f.value,
                    "threshold": f.threshold,
                    "strict_blocking": f.strict_blocking,
                }
                for f in metrics.findings
            ],
        },
        "thresholds": config.to_dict(),
        "notes": "",
    }


# ------------------------------------------------------------------------------ schema

_N = "num"
_NN = ("opt", "num")
_I = "int"
_S = "str"
_SN = ("opt", "str")
_B = "bool"


def _obj(**fields: Any) -> dict[str, Any]:
    return dict(fields)


def _pair_node(item: Any = _N) -> Any:
    return ("tuple", 2, item)


_SPREAD = _obj(median=_NN, worst=_NN)
_RAW = (
    "map",
    _obj(
        mapping=("map", _I),
        rest_median=_NN,
        observed_min=_NN,
        observed_max=_NN,
        out_of_range_ratio=_NN,
        lsb_normalized=_N,
    ),
)
_STICK = _obj(
    axes=("tuple", 2, _S),
    center=("opt", _pair_node()),
    center_segment_max_shift=_NN,
    rest=_obj(
        frames=_I,
        duration_s=_N,
        valid_blocks=_I,
        drift=_NN,
        noise_rms=_obj(x=_NN, y=_NN, xy=_NN),
        noise_p2p=_obj(x=_NN, y=_NN),
        noise_radius=_obj(max=_NN, p99=_NN),
        jitter=_obj(mean=_NN, p99=_NN, max=_NN),
    ),
    range=_obj(
        min=("opt", _pair_node()),
        max=("opt", _pair_node()),
        span=("opt", _pair_node()),
        observed_min=("opt", _pair_node()),
        observed_max=("opt", _pair_node()),
        symmetry=_pair_node(_NN),
    ),
    circle=_obj(
        valid_laps=_obj(cw=_I, ccw=_I),
        rejected_laps=_I,
        circularity=_SPREAD,
        mean_radius=_SPREAD,
        saturation_ratio=_NN,
    ),
    deadzone_suggested=_obj(mode=("enum", "cut"), value=_NN, basis_p99_calibrated=_NN),
    raw=_RAW,
)
_TRIGGER = _obj(
    input=("enum", "lt", "rt"),
    rest=_NN,
    noise_rms=_NN,
    noise_p2p=_NN,
    noise_p99=_NN,
    max=_NN,
    span=_NN,
    max_values=("list", _N),
    max_dispersion=_NN,
    cycles=_obj(detected=_I, valid=_I),
    shape_basis=("enum", "time_normalized"),
    linearity_r2=_SPREAD,
    linearity_max_error=_SPREAD,
    hysteresis=_SPREAD,
    saturation_ratio=_NN,
    deadzone_suggested=_obj(value=_NN),
    raw=_RAW,
)
_FINDING = _obj(
    code=("enum", *STRICT_BLOCKING),
    severity=("enum", "error", "warning", "info"),
    message=_S,
    metric=_SN,
    value=_NN,
    threshold=_NN,
    strict_blocking=_B,
)


def _config_node() -> dict[str, Any]:
    def node(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: node(item) for key, item in value.items()}
        return _I if isinstance(value, int) else _N

    result = node(MetricsConfig().to_dict())
    assert isinstance(result, dict)
    return result


_SCHEMA = _obj(
    report_kind=("enum", REPORT_KIND),
    metrics_schema_version=("enum", METRICS_SCHEMA_VERSION),
    app_version=_S,
    created_at=_S,
    device=_obj(name=_S, vid=_S, pid=_S),
    capture=_obj(
        file=_S,
        sha256=_S,
        frames=_I,
        frames_outside_segments=_I,
        duration_s=_N,
        connection=_S,
        nominal_rate_hz=_NN,
        effective_rate_hz=_NN,
        rate_p5_hz=_NN,
        rate_p95_hz=_NN,
        rate_pairs=_I,
    ),
    normalization=_obj(source=("enum", "mapping"), mapping_sha256=_S),
    protocol=_obj(
        segments=(
            "list",
            _obj(
                kind=("enum", "rest", "circle", "trigger_sweep"),
                index=_I,
                start_ns=_I,
                end_ns=_I,
                effective_start_ns=_I,
                frames=_I,
                effective_duration_s=_N,
                stick=_SN,
                direction=_SN,
                trigger=_SN,
            ),
        )
    ),
    sticks=_obj(left=_STICK, right=_STICK),
    triggers=_obj(left=_TRIGGER, right=_TRIGGER),
    profile_summary=_obj(
        derived=_B,
        profile_id=_SN,
        sticks=(
            "map",
            _obj(
                center=_pair_node(),
                range_min=_pair_node(),
                range_max=_pair_node(),
                deadzone=_N,
            ),
        ),
        triggers=("map", _obj(rest=_N, max=_N, deadzone=_N)),
    ),
    quality=_obj(status=("enum", "pass", "warn", "fail"), findings=("list", _FINDING)),
    thresholds=_config_node(),
    notes=_S,
)


def _fail(path: str, problem: str) -> InvalidReportError:
    return InvalidReportError(f"relatório inválido em {path or '<raiz>'}: {problem}")


def _check(value: Any, node: Any, path: str) -> None:
    if isinstance(node, dict):
        if not isinstance(value, dict):
            raise _fail(path, "esperado objeto")
        unknown = sorted(set(value) - set(node))
        missing = sorted(set(node) - set(value))
        if unknown:
            raise _fail(path, f"campos desconhecidos: {', '.join(unknown)}")
        if missing:
            raise _fail(path, f"campos ausentes: {', '.join(missing)}")
        for key, child in node.items():
            _check(value[key], child, f"{path}.{key}" if path else key)
        return
    if isinstance(node, str):
        _check_leaf(value, node, path)
        return
    kind = node[0]
    if kind == "opt":
        if value is not None:
            _check(value, node[1], path)
    elif kind == "list":
        if not isinstance(value, list):
            raise _fail(path, "esperado lista")
        for index, item in enumerate(value):
            _check(item, node[1], f"{path}[{index}]")
    elif kind == "tuple":
        if not isinstance(value, list) or len(value) != node[1]:
            raise _fail(path, f"esperada lista com {node[1]} itens")
        for index, item in enumerate(value):
            _check(item, node[2], f"{path}[{index}]")
    elif kind == "map":
        if not isinstance(value, dict) or not all(isinstance(k, str) and k for k in value):
            raise _fail(path, "esperado objeto com chaves de texto")
        for key, item in value.items():
            _check(item, node[1], f"{path}.{key}")
    elif kind == "enum":
        if isinstance(value, bool) or value not in node[1:]:
            raise _fail(path, f"valor fora do conjunto permitido: {value!r}")
    else:  # pragma: no cover - schema bug
        raise AssertionError(f"unknown schema node {kind}")


def _check_leaf(value: Any, tag: str, path: str) -> None:
    if tag == _S:
        ok = isinstance(value, str)
    elif tag == _B:
        ok = isinstance(value, bool)
    elif tag == _I:
        ok = isinstance(value, int) and not isinstance(value, bool)
    elif tag == _N:
        ok = isinstance(value, (int, float)) and not isinstance(value, bool)
        if ok and isinstance(value, float) and not math.isfinite(value):
            raise _fail(path, "número não finito")
    else:  # pragma: no cover - schema bug
        raise AssertionError(f"unknown leaf {tag}")
    if not ok:
        raise _fail(path, f"tipo inválido (esperado {tag}): {value!r}")


def validate_report(report: Any) -> dict[str, Any]:
    """Validate a report strictly: exact keys, types, finite numbers and a coherent status."""
    _check(report, _SCHEMA, "")
    findings = report["quality"]["findings"]
    severities = {finding["severity"] for finding in findings}
    expected = "fail" if "error" in severities else "warn" if "warning" in severities else "pass"
    if report["quality"]["status"] != expected:
        raise _fail("quality.status", f"deveria ser {expected!r} para os achados presentes")
    assert isinstance(report, dict)
    return report


# ------------------------------------------------------------------------ serialization


def _clean(value: Any, key: str = "") -> Any:
    if isinstance(value, dict):
        return {name: _clean(item, name) for name, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(item, key) for item in value]
    if isinstance(value, float):
        if not math.isfinite(value):
            raise InvalidReportError(f"relatório inválido: número não finito em {key or '<raiz>'}")
        return round(value, 3 if key.endswith("_hz") else 6) + 0.0
    return value


def dumps_report(report: Mapping[str, Any]) -> str:
    """Round, validate and serialize deterministically (``allow_nan=False``, sorted keys)."""
    cleaned = validate_report(_clean(dict(report)))
    return json.dumps(cleaned, allow_nan=False, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def _reject_constant(name: str) -> Any:
    raise InvalidReportError(f"relatório inválido: constante não permitida {name}")


def loads_report(text: str) -> dict[str, Any]:
    """Parse and strictly validate a serialized report."""
    try:
        data = json.loads(text, parse_constant=_reject_constant)
    except json.JSONDecodeError as exc:
        raise InvalidReportError(f"relatório inválido: JSON malformado ({exc})") from exc
    return validate_report(data)


# -------------------------------------------------------------------------------- markdown


def _num(value: float | None, digits: int = 4) -> str:
    return _NO_VALUE if value is None else f"{value:.{digits}f}"


def _vec(values: Sequence[float | None] | None) -> str:
    if values is None:
        return _NO_VALUE
    return "(" + ", ".join(_num(v) for v in values) + ")"


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def render_markdown(report: Mapping[str, Any]) -> str:
    """Render the validated JSON report as Markdown without recomputing anything."""
    data = validate_report(dict(report))
    device, capture = data["device"], data["capture"]
    lines = [
        "# Relatório de métricas de calibração",
        "",
        f"Gerado em {data['created_at']} por ZonaPad {data['app_version']} "
        f"(metrics_schema_version={data['metrics_schema_version']}).",
        "",
        "## Dispositivo",
        f"- Nome/VID/PID: {device['name']} / {device['vid']} / {device['pid']}",
        f"- Conexão: {capture['connection']}",
        f"- Normalização: mapping (sha256 {data['normalization']['mapping_sha256']})",
        "",
        "## Captura",
        f"- Arquivo: {capture['file']} (sha256 {capture['sha256']})",
        f"- Frames: {capture['frames']} ({capture['frames_outside_segments']} fora de segmentos)",
        f"- Duração: {_num(capture['duration_s'], 3)} s",
        f"- Taxa efetiva: {_num(capture['effective_rate_hz'], 1)} Hz "
        f"(p5 {_num(capture['rate_p5_hz'], 1)} / p95 {_num(capture['rate_p95_hz'], 1)}; "
        f"nominal {_num(capture['nominal_rate_hz'], 1)}; {capture['rate_pairs']} pares)",
        "- Protocolo:",
    ]
    for segment in data["protocol"]["segments"]:
        target = segment["stick"] or segment["trigger"] or ""
        label = " ".join(p for p in (segment["kind"], target, segment["direction"] or "") if p)
        lines.append(
            f"  - [{segment['index']}] {label}: {segment['frames']} frames, "
            f"{_num(segment['effective_duration_s'], 3)} s efetivos"
        )
    lines += [
        "",
        "## Sticks",
        "| Stick | Centro | Drift | Ruído RMS | Range | Circularidade | Deadzone sugerida |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for side, label in (("left", "Esquerdo"), ("right", "Direito")):
        stick = data["sticks"][side]
        rng = stick["range"]
        lines.append(
            f"| {label} | {_vec(stick['center'])} | {_num(stick['rest']['drift'])} "
            f"| {_num(stick['rest']['noise_rms']['xy'])} "
            f"| min {_vec(rng['min'])} / max {_vec(rng['max'])} "
            f"| {_num(stick['circle']['circularity']['median'])} "
            f"(pior {_num(stick['circle']['circularity']['worst'])}) "
            f"| {_num(stick['deadzone_suggested']['value'])} |"
        )
    lines += [
        "",
        "## Triggers",
        "| Trigger | Repouso | Fundo | R² | Erro máx. | Histerese | Deadzone sugerida |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for side, label in (("left", "L2"), ("right", "R2")):
        trigger = data["triggers"][side]
        lines.append(
            f"| {label} | {_num(trigger['rest'])} | {_num(trigger['max'])} "
            f"| {_num(trigger['linearity_r2']['median'])} "
            f"(pior {_num(trigger['linearity_r2']['worst'])}) "
            f"| {_num(trigger['linearity_max_error']['median'])} "
            f"(pior {_num(trigger['linearity_max_error']['worst'])}) "
            f"| {_num(trigger['hysteresis']['median'])} "
            f"(pior {_num(trigger['hysteresis']['worst'])}) "
            f"| {_num(trigger['deadzone_suggested']['value'])} |"
        )
    lines += [
        "",
        "Linearidade e histerese usam o tempo normalizado como proxy do curso "
        "(`shape_basis: time_normalized`).",
        "",
        "## Riscos e observações",
        f"- Status de qualidade: **{data['quality']['status']}**",
    ]
    findings = data["quality"]["findings"]
    if not findings:
        lines.append("- Nenhum achado.")
    for finding in findings:
        lines.append(
            f"- **{finding['severity']}** `{finding['code']}`: {_cell(finding['message'])}"
        )
    summary = data["profile_summary"]
    lines += ["", "## Perfil derivado"]
    if not summary["derived"]:
        lines.append(
            "- Não derivado: há achados de erro, métricas ausentes ou bloqueio por --strict."
        )
    else:
        lines.append(f"- Perfil: {summary['profile_id'] or 'não gravado (use --save-profile)'}")
    lines += ["", "## Thresholds efetivos", "```json"]
    lines.append(json.dumps(data["thresholds"], sort_keys=True, indent=2))
    lines += ["```", ""]
    return "\n".join(lines)
