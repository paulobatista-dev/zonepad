from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

Severity = Literal["error", "warning", "info"]
QualityStatus = Literal["pass", "warn", "fail"]

_SEVERITY_ORDER: dict[str, int] = {"error": 0, "warning": 1, "info": 2}

# Código -> bloqueia em --strict (quando severidade é error/warning). Fonte: spec metrics-v1.
STRICT_BLOCKING: dict[str, bool] = {
    "MISSING_REST_SEGMENT": True,
    "REST_TOO_SHORT": True,
    "MISSING_CIRCLE_SEGMENT": True,
    "INSUFFICIENT_CIRCLE_POINTS": True,
    "INSUFFICIENT_CIRCLE_LAPS": True,
    "CIRCLE_DIRECTION_INCONSISTENT": True,
    "MISSING_TRIGGER_SEGMENT": True,
    "INSUFFICIENT_TRIGGER_CYCLES": True,
    "AXIS_MISSING": True,
    "DEGENERATE_RANGE": True,
    "CENTER_OUTSIDE_RANGE": True,
    "DEADZONE_CLAMPED": True,
    "HIGH_DRIFT": True,
    "HIGH_NOISE": True,
    "MAPPING_RANGE_EXCEEDED": True,
    "DUPLICATE_TIMESTAMP": True,
    "RATE_OUT_OF_TOLERANCE": True,
    "LOW_CIRCULARITY": False,
    "SATURATION_HIGH": False,
    "LOW_TRIGGER_R2": False,
    "HIGH_HYSTERESIS": False,
    "CENTER_FAR_FROM_MAPPING": False,
    "UNMAPPED_CHANNEL_IGNORED": False,
    "NOMINAL_RATE_UNKNOWN": False,
    "RATE_UNAVAILABLE": False,
}


@dataclass(frozen=True, slots=True)
class Finding:
    """Quality finding with a stable code; ``metric`` is a dotted path into the report."""

    code: str
    severity: Severity
    message: str
    metric: str | None = None
    value: float | None = None
    threshold: float | None = None

    def __post_init__(self) -> None:
        if self.code not in STRICT_BLOCKING:
            raise ValueError(f"unknown finding code: {self.code}")
        if self.severity not in _SEVERITY_ORDER:
            raise ValueError(f"unknown severity: {self.severity}")

    @property
    def strict_blocking(self) -> bool:
        return STRICT_BLOCKING[self.code]

    @property
    def blocks_strict(self) -> bool:
        """True when ``--strict`` must fail because of this finding."""
        return self.severity == "error" or (self.severity == "warning" and self.strict_blocking)


def sort_findings(findings: Iterable[Finding]) -> tuple[Finding, ...]:
    """Stable order: severity (error, warning, info), then code, then metric."""
    return tuple(
        sorted(findings, key=lambda f: (_SEVERITY_ORDER[f.severity], f.code, f.metric or ""))
    )


def derive_status(findings: Iterable[Finding]) -> QualityStatus:
    severities = {finding.severity for finding in findings}
    if "error" in severities:
        return "fail"
    if "warning" in severities:
        return "warn"
    return "pass"
