"""Pure state transitions for the interactive calibration wizard."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum


class WizardPhase(StrEnum):
    WELCOME = "welcome"
    SELECT_DEVICE = "select_device"
    VALIDATE_MAPPING = "validate_mapping"
    CONFIRM_DEVICE = "confirm_device"
    WARMUP = "warmup"
    SEGMENT_PROMPT = "segment_prompt"
    COUNTDOWN = "countdown"
    RECORD_SEGMENT = "record_segment"
    MEASURE = "measure"
    REVIEW = "review"
    RETRY_DECISION = "retry_decision"
    SAVE_DECISION = "save_decision"
    SAVE = "save"
    SUMMARY = "summary"
    ABORTED = "aborted"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class WizardState:
    phase: WizardPhase = WizardPhase.WELCOME
    segment_index: int = 0
    retry_count: int = 0
    error: str | None = None


@dataclass(frozen=True, slots=True)
class SegmentPlan:
    target: tuple[str, ...]
    kind: str
    duration_seconds: float
    instruction: str
    warmup_ns: int = 0
    stick: str | None = None
    direction: str | None = None
    trigger: str | None = None


@dataclass(frozen=True, slots=True)
class Continue:
    pass


@dataclass(frozen=True, slots=True)
class Cancel:
    pass


@dataclass(frozen=True, slots=True)
class SegmentCompleted:
    pass


@dataclass(frozen=True, slots=True)
class SegmentRejected:
    retry_available: bool


@dataclass(frozen=True, slots=True)
class MeasurementCompleted:
    pass


@dataclass(frozen=True, slots=True)
class RetryDecision:
    retry: bool


@dataclass(frozen=True, slots=True)
class SaveDecision:
    save: bool


@dataclass(frozen=True, slots=True)
class ReviewDecision:
    retry_available: bool
    accepted: bool


type Event = (
    Continue
    | Cancel
    | SegmentCompleted
    | SegmentRejected
    | MeasurementCompleted
    | ReviewDecision
    | RetryDecision
    | SaveDecision
)


@dataclass(frozen=True, slots=True)
class Effect:
    name: str
    value: str | int | None = None


def step(
    state: WizardState, event: Event, *, segment_count: int
) -> tuple[WizardState, tuple[Effect, ...]]:
    """Advance one wizard phase without performing I/O."""
    if isinstance(event, Cancel):
        return replace(state, phase=WizardPhase.ABORTED), (Effect("abort_capture"),)

    if state.phase == WizardPhase.WELCOME and isinstance(event, Continue):
        return replace(state, phase=WizardPhase.SELECT_DEVICE), (Effect("select_device"),)
    if state.phase == WizardPhase.SELECT_DEVICE and isinstance(event, Continue):
        return replace(state, phase=WizardPhase.VALIDATE_MAPPING), (Effect("validate_mapping"),)
    if state.phase == WizardPhase.VALIDATE_MAPPING and isinstance(event, Continue):
        return replace(state, phase=WizardPhase.CONFIRM_DEVICE), (Effect("confirm_device"),)
    if state.phase == WizardPhase.CONFIRM_DEVICE and isinstance(event, Continue):
        return replace(state, phase=WizardPhase.WARMUP), (Effect("open_capture"), Effect("warmup"))
    if state.phase == WizardPhase.WARMUP and isinstance(event, Continue):
        phase = WizardPhase.SEGMENT_PROMPT if segment_count else WizardPhase.MEASURE
        return replace(state, phase=phase), (Effect("prompt_segment", state.segment_index),)
    if state.phase == WizardPhase.SEGMENT_PROMPT and isinstance(event, Continue):
        return replace(state, phase=WizardPhase.COUNTDOWN), (Effect("countdown", 3),)
    if state.phase == WizardPhase.COUNTDOWN and isinstance(event, Continue):
        return replace(state, phase=WizardPhase.RECORD_SEGMENT), (
            Effect("record_segment", state.segment_index),
        )
    if state.phase == WizardPhase.RECORD_SEGMENT and isinstance(event, Continue):
        return state, (Effect("countdown", 3),)
    if state.phase == WizardPhase.RECORD_SEGMENT and isinstance(event, SegmentCompleted):
        next_index = state.segment_index + 1
        phase = WizardPhase.SEGMENT_PROMPT if next_index < segment_count else WizardPhase.MEASURE
        return replace(state, phase=phase, segment_index=next_index), (
            Effect("prompt_segment", next_index)
            if phase == WizardPhase.SEGMENT_PROMPT
            else Effect("measure"),
        )
    if state.phase == WizardPhase.RECORD_SEGMENT and isinstance(event, SegmentRejected):
        phase = WizardPhase.RETRY_DECISION if event.retry_available else WizardPhase.FAILED
        return replace(state, phase=phase), (Effect(phase.value),)
    if state.phase == WizardPhase.MEASURE and isinstance(event, MeasurementCompleted):
        return replace(state, phase=WizardPhase.REVIEW), (Effect("review"),)
    if state.phase == WizardPhase.REVIEW and isinstance(event, ReviewDecision):
        phase = (
            WizardPhase.SAVE_DECISION
            if event.accepted
            else (WizardPhase.RETRY_DECISION if event.retry_available else WizardPhase.FAILED)
        )
        return replace(state, phase=phase), (Effect(phase.value),)
    if state.phase == WizardPhase.RETRY_DECISION and isinstance(event, RetryDecision):
        if event.retry:
            return replace(
                state, phase=WizardPhase.RECORD_SEGMENT, retry_count=state.retry_count + 1
            ), (Effect("record_retry"),)
        return replace(state, phase=WizardPhase.FAILED), (Effect("quality_blocked"),)
    if state.phase == WizardPhase.SAVE_DECISION and isinstance(event, SaveDecision):
        phase = WizardPhase.SAVE if event.save else WizardPhase.SUMMARY
        return replace(state, phase=phase), (Effect(phase.value),)
    if state.phase == WizardPhase.SAVE and isinstance(event, Continue):
        return replace(state, phase=WizardPhase.SUMMARY), (Effect("summary"),)
    raise ValueError(f"evento {type(event).__name__} inválido para fase {state.phase.value}")
