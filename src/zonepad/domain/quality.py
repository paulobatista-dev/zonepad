"""Quality findings derived from measured facts (catalog in docs/specs/metrics-v1.md)."""

from __future__ import annotations

import math
from dataclasses import replace

from .findings import Finding, Severity, derive_status, sort_findings
from .metrics import (
    ChannelCoverage,
    MeasurementMetrics,
    MetricsConfig,
    StickMetrics,
    TriggerMetrics,
)

_AXIS_MISSING_WARNING_RATIO = 0.05


def evaluate_quality(metrics: MeasurementMetrics) -> MeasurementMetrics:
    """Return ``metrics`` with sorted ``findings`` and the derived ``status``."""
    findings: list[Finding] = []
    findings.extend(_capture_findings(metrics))
    for side, stick in metrics.sticks.items():
        findings.extend(_stick_findings(side, stick, metrics))
    for side, trigger in metrics.triggers.items():
        findings.extend(_trigger_findings(side, trigger, metrics))
    ordered = sort_findings(findings)
    return replace(metrics, findings=ordered, status=derive_status(ordered))


def _fmt(value: float) -> str:
    return f"{value:.4f}"


def _rest_findings(
    root: str, frames: int, rest_segments: int, config: MetricsConfig
) -> list[Finding]:
    protocol = config.protocol
    if rest_segments == 0:
        return []  # MISSING_REST_SEGMENT is reported once, in the capture findings
    if frames >= protocol.rest_min_frames:
        return []
    severity: Severity = "error" if frames < protocol.rest_hard_min_frames else "warning"
    return [
        Finding(
            "REST_TOO_SHORT",
            severity,
            f"{root}: repouso efetivo com {frames} frames; o mínimo é "
            f"{protocol.rest_min_frames}. Alongue o segmento rest.",
            f"{root}.rest.frames",
            float(frames),
            float(protocol.rest_min_frames),
        )
    ]


def _axis_missing(root: str, coverage: ChannelCoverage) -> list[Finding]:
    if coverage.relevant_frames == 0:
        return []
    missing = coverage.missing_frames
    if (
        coverage.valid_frames == 0
        or missing / coverage.relevant_frames > _AXIS_MISSING_WARNING_RATIO
    ):
        severity: Severity = "error"
    elif missing > 0:
        severity = "warning"
    else:
        return []
    return [
        Finding(
            "AXIS_MISSING",
            severity,
            f"{root}: {missing} de {coverage.relevant_frames} frames dos segmentos não trazem "
            "todos os eixos; confira o mapping e a captura.",
            root,
            float(missing),
        )
    ]


def _raw_findings(root: str, side_raw: dict[str, float | None]) -> list[Finding]:
    return [
        Finding(
            "MAPPING_RANGE_EXCEEDED",
            "warning",
            f"{root}.raw.{channel}: {_fmt(ratio)} dos frames ficam fora do range do mapping; "
            "a normalização clampa e esconde o excesso. Meça o mapping novamente.",
            f"{root}.raw.{channel}.out_of_range_ratio",
            ratio,
        )
        for channel, ratio in side_raw.items()
        if ratio is not None and ratio > 0
    ]


def _stick_findings(side: str, stick: StickMetrics, metrics: MeasurementMetrics) -> list[Finding]:
    config = metrics.config
    limits = config.thresholds
    root = f"sticks.{side}"
    findings = _rest_findings(root, stick.rest.frames, metrics.rest_segments, config)
    findings.extend(_axis_missing(root, stick.coverage))
    findings.extend(
        _raw_findings(
            root, {c: metrics.raw[c].out_of_range_ratio for c in stick.axes if c in metrics.raw}
        )
    )
    if stick.rest_segments > 0 and stick.rest.valid_blocks < 2 and stick.rest.frames > 0:
        findings.append(
            Finding(
                "REST_TOO_SHORT",
                "warning",
                f"{root}: menos de 2 blocos de {_fmt(config.protocol.drift_block_s)} s válidos no "
                "repouso; o drift não pôde ser medido. Alongue o segmento rest.",
                f"{root}.rest.drift",
                float(stick.rest.valid_blocks),
                2.0,
            )
        )
    findings.extend(_circle_findings(root, stick, config))
    if stick.rest.drift is not None and stick.rest.drift >= limits.drift_max:
        findings.append(
            Finding(
                "HIGH_DRIFT",
                "warning",
                f"{root}: drift {_fmt(stick.rest.drift)} no repouso (limite {limits.drift_max}).",
                f"{root}.rest.drift",
                stick.rest.drift,
                limits.drift_max,
            )
        )
    noise = stick.rest.noise
    if noise is not None and noise.rms_xy >= limits.noise_rms_max:
        findings.append(
            Finding(
                "HIGH_NOISE",
                "warning",
                f"{root}: ruído RMS {_fmt(noise.rms_xy)} no repouso (limite "
                f"{limits.noise_rms_max}).",
                f"{root}.rest.noise_rms.xy",
                noise.rms_xy,
                limits.noise_rms_max,
            )
        )
    if stick.center is not None:
        offset = max(abs(stick.center[0]), abs(stick.center[1]))
        if offset > limits.center_offset_info:
            findings.append(
                Finding(
                    "CENTER_FAR_FROM_MAPPING",
                    "info",
                    f"{root}: centro medido a {_fmt(offset)} do centro do mapping; o centro do "
                    "mapping pode estar errado ou o stick desgastado.",
                    f"{root}.center",
                    offset,
                    limits.center_offset_info,
                )
            )
    if stick.deadzone is not None and stick.deadzone.clamped:
        findings.append(_deadzone_clamped(f"{root}.deadzone_suggested", stick.deadzone.basis_p99))
    return findings


def _deadzone_clamped(metric: str, basis: float) -> Finding:
    return Finding(
        "DEADZONE_CLAMPED",
        "warning",
        f"{metric}: a deadzone sugerida passaria de 0.95 (base P99 {_fmt(basis)}) e foi limitada.",
        metric,
        basis,
        0.95,
    )


def _circle_findings(root: str, stick: StickMetrics, config: MetricsConfig) -> list[Finding]:
    protocol = config.protocol
    limits = config.thresholds
    circle = stick.circle
    path = f"{root}.circle"
    if circle.segments == 0:
        return [
            Finding(
                "MISSING_CIRCLE_SEGMENT",
                "error",
                f"{root}: nenhum segmento circle declarado; gire a borda do gate.",
                root,
            )
        ]
    findings: list[Finding] = []
    for direction, segments, valid in (
        ("cw", circle.segments_cw, circle.valid_laps_cw),
        ("ccw", circle.segments_ccw, circle.valid_laps_ccw),
    ):
        if segments == 0:
            findings.append(
                Finding(
                    "MISSING_CIRCLE_SEGMENT",
                    "warning",
                    f"{root}: sem segmento circle na direção {direction}.",
                    f"{path}.valid_laps.{direction}",
                )
            )
        elif circle.valid_laps > 0 and valid < protocol.circle_min_valid_laps_per_direction:
            findings.append(
                Finding(
                    "INSUFFICIENT_CIRCLE_LAPS",
                    "warning",
                    f"{root}: {valid} volta(s) válida(s) na direção {direction}; o mínimo é "
                    f"{protocol.circle_min_valid_laps_per_direction}.",
                    f"{path}.valid_laps.{direction}",
                    float(valid),
                    float(protocol.circle_min_valid_laps_per_direction),
                )
            )
    if circle.valid_laps == 0 and stick.center is not None:
        findings.append(
            Finding(
                "INSUFFICIENT_CIRCLE_LAPS",
                "error",
                f"{root}: nenhuma volta completa válida; dê voltas completas na borda do gate "
                f"com pelo menos {protocol.circle_min_points_per_lap} frames por volta.",
                path,
                0.0,
                float(protocol.circle_min_valid_laps_per_direction),
            )
        )
    if circle.rejected_laps > 0:
        findings.append(
            Finding(
                "INSUFFICIENT_CIRCLE_POINTS",
                "warning",
                f"{root}: {circle.rejected_laps} volta(s) rejeitada(s) por terem menos de "
                f"{protocol.circle_min_points_per_lap} frames ou setores de 15 graus com "
                f"menos de 2 frames.",
                f"{path}.rejected_laps",
                float(circle.rejected_laps),
            )
        )
    if circle.direction_inconsistent:
        findings.append(
            Finding(
                "CIRCLE_DIRECTION_INCONSISTENT",
                "warning",
                f"{root}: o sentido de rotação observado contradiz os rótulos cw/ccw; "
                "confira o manifesto.",
                path,
            )
        )
    if stick.center is not None and stick.axis_range is not None:
        findings.extend(_range_findings(root, stick, protocol.min_half_range))
    if (
        circle.circularity_median is not None
        and circle.circularity_median <= limits.circularity_min
    ):
        findings.append(
            Finding(
                "LOW_CIRCULARITY",
                "warning",
                f"{root}: circularidade {_fmt(circle.circularity_median)} (mínimo "
                f"{limits.circularity_min}); gates quadrados ou octogonais reduzem este valor.",
                f"{path}.circularity.median",
                circle.circularity_median,
                limits.circularity_min,
            )
        )
    if (
        circle.saturation_ratio is not None
        and circle.saturation_ratio >= limits.saturation_ratio_max
    ):
        findings.append(
            Finding(
                "SATURATION_HIGH",
                "warning",
                f"{root}: {_fmt(circle.saturation_ratio)} dos frames do círculo estão no extremo.",
                f"{path}.saturation_ratio",
                circle.saturation_ratio,
                limits.saturation_ratio_max,
            )
        )
    return findings


def _range_findings(root: str, stick: StickMetrics, min_half_range: float) -> list[Finding]:
    assert stick.center is not None and stick.axis_range is not None
    findings: list[Finding] = []
    path = f"{root}.range"
    outside = degenerate = False
    smallest = math.inf
    for axis in range(2):
        center = stick.center[axis]
        for half in (center - stick.axis_range.min[axis], stick.axis_range.max[axis] - center):
            if half <= 0:
                outside = True
            elif half < min_half_range:
                degenerate = True
                smallest = min(smallest, half)
    if outside:
        findings.append(
            Finding(
                "CENTER_OUTSIDE_RANGE",
                "error",
                f"{root}: o centro medido não fica estritamente dentro do range do círculo; "
                "refaça o círculo contornando toda a borda do gate.",
                path,
            )
        )
    if degenerate:
        findings.append(
            Finding(
                "DEGENERATE_RANGE",
                "error",
                f"{root}: semi-range de {_fmt(smallest)} abaixo do mínimo {min_half_range}; "
                "refaça o círculo contornando toda a borda do gate.",
                path,
                smallest,
                min_half_range,
            )
        )
    return findings


def _trigger_findings(
    side: str, trigger: TriggerMetrics, metrics: MeasurementMetrics
) -> list[Finding]:
    config = metrics.config
    limits = config.thresholds
    protocol = config.protocol
    root = f"triggers.{side}"
    findings = _rest_findings(root, trigger.rest_frames, metrics.rest_segments, config)
    findings.extend(_axis_missing(root, trigger.coverage))
    channel = "lt" if side == "left" else "rt"
    if channel in metrics.raw:
        findings.extend(_raw_findings(root, {channel: metrics.raw[channel].out_of_range_ratio}))
    if trigger.sweep_segments == 0:
        findings.append(
            Finding(
                "MISSING_TRIGGER_SEGMENT",
                "error",
                f"{root}: nenhum segmento trigger_sweep declarado; pressione o gatilho até o "
                "fundo e solte em ciclos.",
                root,
            )
        )
        return findings
    findings.extend(_trigger_cycle_findings(root, trigger, config))
    if trigger.noise_rms is not None and trigger.noise_rms >= limits.noise_rms_max:
        findings.append(
            Finding(
                "HIGH_NOISE",
                "warning",
                f"{root}: ruído RMS {_fmt(trigger.noise_rms)} no repouso (limite "
                f"{limits.noise_rms_max}).",
                f"{root}.noise_rms",
                trigger.noise_rms,
                limits.noise_rms_max,
            )
        )
    if trigger.span is not None and trigger.span < protocol.trigger_min_span:
        findings.append(
            Finding(
                "DEGENERATE_RANGE",
                "error",
                f"{root}: curso útil {_fmt(trigger.span)} abaixo do mínimo "
                f"{protocol.trigger_min_span}; pressione o gatilho até o fundo.",
                f"{root}.span",
                trigger.span,
                protocol.trigger_min_span,
            )
        )
    if trigger.deadzone is not None and trigger.deadzone.clamped:
        findings.append(_deadzone_clamped(f"{root}.deadzone_suggested", trigger.deadzone.basis_p99))
    if trigger.linearity_r2 is not None and trigger.linearity_r2.median <= limits.trigger_r2_min:
        findings.append(
            Finding(
                "LOW_TRIGGER_R2",
                "info",
                f"{root}: R² {_fmt(trigger.linearity_r2.median)} (mínimo "
                f"{limits.trigger_r2_min}); a forma usa o tempo como proxy do curso.",
                f"{root}.linearity_r2.median",
                trigger.linearity_r2.median,
                limits.trigger_r2_min,
            )
        )
    if trigger.hysteresis is not None and trigger.hysteresis.median >= limits.hysteresis_max:
        findings.append(
            Finding(
                "HIGH_HYSTERESIS",
                "info",
                f"{root}: histerese {_fmt(trigger.hysteresis.median)} (limite "
                f"{limits.hysteresis_max}); a forma usa o tempo como proxy do curso.",
                f"{root}.hysteresis.median",
                trigger.hysteresis.median,
                limits.hysteresis_max,
            )
        )
    if (
        trigger.saturation_ratio is not None
        and trigger.saturation_ratio >= limits.saturation_ratio_max
    ):
        findings.append(
            Finding(
                "SATURATION_HIGH",
                "warning",
                f"{root}: {_fmt(trigger.saturation_ratio)} dos frames do sweep estão no fundo.",
                f"{root}.saturation_ratio",
                trigger.saturation_ratio,
                limits.saturation_ratio_max,
            )
        )
    return findings


def _trigger_cycle_findings(
    root: str, trigger: TriggerMetrics, config: MetricsConfig
) -> list[Finding]:
    minimum = config.protocol.trigger_min_valid_cycles
    if trigger.cycles_valid >= minimum or trigger.rest is None:
        return []
    severity: Severity = "error" if trigger.cycles_valid == 0 else "warning"
    return [
        Finding(
            "INSUFFICIENT_TRIGGER_CYCLES",
            severity,
            f"{root}: {trigger.cycles_valid} ciclo(s) válido(s) de {trigger.cycles_detected} "
            f"detectado(s); o mínimo é {minimum} (pico >= {config.protocol.trigger_peak_min} e "
            f"{config.protocol.trigger_phase_min_points} frames por fase).",
            root,
            float(trigger.cycles_valid),
            float(minimum),
        )
    ]


def _capture_findings(metrics: MeasurementMetrics) -> list[Finding]:
    capture = metrics.capture
    limits = metrics.config.thresholds
    findings: list[Finding] = []
    if metrics.rest_segments == 0:
        findings.append(
            Finding(
                "MISSING_REST_SEGMENT",
                "error",
                "protocol: nenhum segmento rest declarado; grave 5 s sem tocar no controle.",
                "protocol.segments",
            )
        )
    if metrics.rest_segments > 0 and (
        metrics.rest_effective_duration_s < metrics.config.protocol.rest_min_duration_s
    ):
        findings.append(
            Finding(
                "REST_TOO_SHORT",
                "error"
                if metrics.rest_effective_duration_s
                < metrics.config.protocol.rest_hard_min_duration_s
                else "warning",
                f"protocol.rest: duração efetiva {_fmt(metrics.rest_effective_duration_s)} s; "
                f"o mínimo é {_fmt(metrics.config.protocol.rest_min_duration_s)} s.",
                "protocol.rest.effective_duration_s",
                metrics.rest_effective_duration_s,
                metrics.config.protocol.rest_min_duration_s,
            )
        )
    if capture.duplicate_pairs > 0:
        findings.append(
            Finding(
                "DUPLICATE_TIMESTAMP",
                "warning",
                f"capture: {capture.duplicate_pairs} par(es) de frames com o mesmo timestamp; "
                "esses pares ficam fora da taxa.",
                "capture.duplicate_pairs",
                float(capture.duplicate_pairs),
            )
        )
    nominal = metrics.nominal_rate_hz
    if nominal is None:
        findings.append(
            Finding(
                "NOMINAL_RATE_UNKNOWN",
                "info",
                "capture: o manifesto não informa nominal_rate_hz; a taxa não foi comparada.",
                "capture.nominal_rate_hz",
            )
        )
    if capture.effective_rate_hz is None:
        findings.append(
            Finding(
                "RATE_UNAVAILABLE",
                "info",
                f"capture: {capture.rate_pairs} pares de frames em círculos; o mínimo para medir "
                f"a taxa é {metrics.config.protocol.rate_min_pairs}.",
                "capture",
                float(capture.rate_pairs),
                float(metrics.config.protocol.rate_min_pairs),
            )
        )
    elif (
        nominal is not None
        and abs(capture.effective_rate_hz - nominal) > limits.rate_tolerance * nominal
    ):
        findings.append(
            Finding(
                "RATE_OUT_OF_TOLERANCE",
                "warning",
                f"capture: taxa efetiva {capture.effective_rate_hz:.1f} Hz fora de "
                f"{nominal:g} Hz +/- {limits.rate_tolerance * 100:g}%.",
                "capture.effective_rate_hz",
                capture.effective_rate_hz,
                nominal,
            )
        )
    findings.extend(
        Finding(
            "UNMAPPED_CHANNEL_IGNORED",
            "info",
            f"capture: o canal {channel!r} da captura não existe no mapping e foi ignorado.",
            f"capture.channels.{channel}",
        )
        for channel in metrics.unmapped_channels
    )
    return findings
