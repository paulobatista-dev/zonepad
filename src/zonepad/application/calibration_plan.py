"""Shared calibration plans and retry target selection for CLI and GUI."""

from __future__ import annotations

from collections.abc import Collection

from zonepad.domain.protocol import Segment

from .calibrate import SegmentPlan
from .measure import MeasureOutcome


def calibration_plans(
    warmup: float, rest: float, circle: float, trigger: float
) -> tuple[SegmentPlan, ...]:
    """Return the seven wizard plans and their user-facing instructions."""
    return (
        SegmentPlan(
            ("rest",),
            "rest",
            rest,
            "Mãos fora do controle; deixe os sticks e gatilhos em repouso.",
            1_000_000_000,
        ),
        SegmentPlan(
            ("circle", "left", "cw"),
            "circle",
            circle,
            "Stick esquerdo na borda: dê 3 voltas horárias e passe do ponto inicial.",
            stick="left",
            direction="cw",
        ),
        SegmentPlan(
            ("circle", "left", "ccw"),
            "circle",
            circle,
            "Stick esquerdo na borda: dê 3 voltas anti-horárias e passe do ponto inicial.",
            stick="left",
            direction="ccw",
        ),
        SegmentPlan(
            ("circle", "right", "cw"),
            "circle",
            circle,
            "Stick direito na borda: dê 3 voltas horárias e passe do ponto inicial.",
            stick="right",
            direction="cw",
        ),
        SegmentPlan(
            ("circle", "right", "ccw"),
            "circle",
            circle,
            "Stick direito na borda: dê 3 voltas anti-horárias e passe do ponto inicial.",
            stick="right",
            direction="ccw",
        ),
        SegmentPlan(
            ("trigger", "left"),
            "trigger_sweep",
            trigger,
            "Gatilho esquerdo: em cada ciclo, fique 0,5 s em repouso, pressione em 2 s, "
            "mantenha no fundo por 0,5 s e solte em 2 s; repita 5 vezes.",
            trigger="left",
        ),
        SegmentPlan(
            ("trigger", "right"),
            "trigger_sweep",
            trigger,
            "Gatilho direito: em cada ciclo, fique 0,5 s em repouso, pressione em 2 s, "
            "mantenha no fundo por 0,5 s e solte em 2 s; repita 5 vezes.",
            trigger="right",
        ),
    )


def segment_from_plan(plan: SegmentPlan) -> Segment:
    """Create the manifest segment associated with one shared plan."""
    return Segment(plan.kind, 1, 2, plan.warmup_ns, plan.stick, plan.direction, plan.trigger)


def retry_targets(
    outcome: MeasureOutcome, existing: Collection[tuple[str, ...]]
) -> tuple[tuple[str, ...], ...] | None:
    """Resolve all strict-blocking findings to existing wizard targets safely."""
    blockers = [finding for finding in outcome.metrics.findings if finding.blocks_strict]
    if not blockers:
        return None
    targets: set[tuple[str, ...]] = set()
    for finding in blockers:
        metric = finding.metric or ""
        target: tuple[str, ...]
        if finding.code in {"REST_TOO_SHORT", "HIGH_DRIFT", "HIGH_NOISE"}:
            target = ("rest",)
            if target not in existing:
                return None
        elif finding.code in {
            "INSUFFICIENT_CIRCLE_POINTS",
            "INSUFFICIENT_CIRCLE_LAPS",
            "CIRCLE_DIRECTION_INCONSISTENT",
        }:
            bits = metric.split(".")
            if len(bits) >= 3 and bits[0] == "sticks" and bits[1] in {"left", "right"}:
                directions = (
                    [bits[4]]
                    if len(bits) > 4 and bits[3] == "valid_laps" and bits[4] in {"cw", "ccw"}
                    else ["cw", "ccw"]
                )
                for direction in directions:
                    target = ("circle", bits[1], direction)
                    if target not in existing:
                        return None
                    targets.add(target)
                continue
            return None
        elif finding.code == "INSUFFICIENT_TRIGGER_CYCLES":
            bits = metric.split(".")
            if len(bits) < 2 or bits[0] != "triggers" or bits[1] not in {"left", "right"}:
                return None
            target = ("trigger", bits[1])
            if target not in existing:
                return None
        else:
            return None
        targets.add(target)
    return tuple(sorted(targets)) if targets else None
