"""Provisional mapping draft from capabilities, absinfo and catalog (spec RF5/RF6).

Every draft is provisional: ranges come from the driver (absinfo) or the
catalog, while stick centers and trigger rests are declared, not measured.
A draft is either complete for the six mapping channels or not produced at all.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType

from .catalog import (
    MAPPING_CHANNELS,
    STICK_CHANNELS,
    TRIGGER_CHANNELS,
    CatalogMatch,
    CatalogSource,
    KnownRange,
)
from .discovery import AbsInfo, DeviceCapabilities, GamepadKind


class RangeSource(StrEnum):
    EVDEV_ABSINFO = "evdev_absinfo"
    CATALOG = "catalog"


class ValueSource(StrEnum):
    MIDPOINT = "midpoint"
    CATALOG_OVERRIDE = "catalog_override"
    RANGE_MINIMUM = "range_minimum"


PROVISIONAL_FIELDS = (
    "axes.lx.center",
    "axes.ly.center",
    "axes.rx.center",
    "axes.ry.center",
    "triggers.lt.rest",
    "triggers.rt.rest",
)


@dataclass(frozen=True, slots=True)
class DraftRules:
    """D9/D10 heuristics as data; Linux codes come from ``linux_input_policy``.

    ``trigger_candidates`` are ``(lt, rt)`` pairs tested in order.
    """

    left_stick: tuple[int, int]
    right_stick: tuple[int, int]
    right_stick_fallback: tuple[int, int]
    trigger_candidates: tuple[tuple[int, int], ...]
    digital_trigger_buttons: tuple[int, int]
    positional_buttons: Mapping[int, str]
    non_positional_drivers: frozenset[str]
    min_stick_span: int

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "positional_buttons", MappingProxyType(dict(self.positional_buttons))
        )

    @property
    def probe_codes(self) -> frozenset[int]:
        """Every ABS code the generic heuristic may assign to a channel."""
        codes = {*self.left_stick, *self.right_stick, *self.right_stick_fallback}
        for pair in self.trigger_candidates:
            codes.update(pair)
        return frozenset(codes)


@dataclass(frozen=True, slots=True)
class AxisDraft:
    code: int
    minimum: int
    center: int
    maximum: int
    range_source: RangeSource
    center_source: ValueSource


@dataclass(frozen=True, slots=True)
class TriggerDraft:
    code: int
    rest: int
    maximum: int
    range_source: RangeSource
    rest_source: ValueSource


@dataclass(frozen=True, slots=True)
class DraftProvenance:
    catalog_entry_id: str | None
    catalog_version: int
    catalog_source: CatalogSource
    provisional: bool
    provisional_fields: tuple[str, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MappingDraft:
    axes: Mapping[str, AxisDraft]
    triggers: Mapping[str, TriggerDraft]
    buttons: Mapping[int, str]
    provenance: DraftProvenance
    axis_candidates: tuple[str, ...] = field(default=())

    def __post_init__(self) -> None:
        if set(self.axes) != set(STICK_CHANNELS) or set(self.triggers) != set(TRIGGER_CHANNELS):
            raise ValueError("a mapping draft must define every stick and trigger channel")
        object.__setattr__(self, "axes", MappingProxyType(dict(self.axes)))
        object.__setattr__(self, "triggers", MappingProxyType(dict(self.triggers)))
        object.__setattr__(self, "buttons", MappingProxyType(dict(self.buttons)))

    @property
    def range_source(self) -> RangeSource:
        """``catalog`` when any channel range came from the catalog (RF8 re-check)."""
        sources = {axis.range_source for axis in self.axes.values()}
        sources.update(trigger.range_source for trigger in self.triggers.values())
        if RangeSource.CATALOG in sources:
            return RangeSource.CATALOG
        return RangeSource.EVDEV_ABSINFO

    @property
    def codes(self) -> Mapping[str, int]:
        result = {name: axis.code for name, axis in self.axes.items()}
        result.update({name: trigger.code for name, trigger in self.triggers.items()})
        return MappingProxyType(result)


@dataclass(frozen=True, slots=True)
class InsufficientCapabilities:
    """Why no draft was produced; nothing is written in this case (exit 4).

    ``reason`` is one of ``missing_channels``, ``digital_triggers_only``,
    ``ranges_unavailable``, ``invalid_range`` or a catalog ``unsupported_reason``.
    """

    missing_channels: tuple[str, ...]
    detected_axes: tuple[int, ...]
    detected_buttons: tuple[int, ...]
    reason: str

    @property
    def code(self) -> str:
        """Stable ``<reason>[:<channels>]`` string for messages and logs."""
        if self.missing_channels and self.reason in ("ranges_unavailable", "invalid_range"):
            return f"{self.reason}:{','.join(self.missing_channels)}"
        return self.reason


@dataclass(frozen=True, slots=True)
class _ChannelPlan:
    codes: Mapping[str, int]
    buttons: Mapping[int, str]
    axis_candidates: tuple[str, ...]
    warnings: tuple[str, ...]


def build_draft(
    capabilities: DeviceCapabilities,
    catalog: CatalogMatch,
    rules: DraftRules,
    *,
    driver: str | None,
    gamepad_kind: GamepadKind | None,
) -> MappingDraft | InsufficientCapabilities:
    """Build a provisional draft; absinfo must already be attached to ``capabilities``."""
    plan = _plan_channels(capabilities, catalog, rules, driver=driver, gamepad_kind=gamepad_kind)
    if isinstance(plan, InsufficientCapabilities):
        return plan
    known_ranges = catalog.entry.known_ranges if catalog.entry else {}
    warnings: list[str] = ["provisional_center", *catalog.warnings, *plan.warnings]
    ranges: dict[str, tuple[int, int, RangeSource]] = {}
    unavailable: list[str] = []
    for channel in MAPPING_CHANNELS:
        code = plan.codes[channel]
        resolved = _resolve_range(code, capabilities, known_ranges, warnings)
        if resolved is None:
            unavailable.append(channel)
        else:
            ranges[channel] = resolved
    if unavailable:
        return _insufficient(capabilities, tuple(unavailable), "ranges_unavailable")
    center_override = catalog.entry.center_override if catalog.entry else {}
    axes: dict[str, AxisDraft] = {}
    triggers: dict[str, TriggerDraft] = {}
    invalid: list[str] = []
    for channel in STICK_CHANNELS:
        minimum, maximum, source = ranges[channel]
        if maximum - minimum < rules.min_stick_span:
            invalid.append(channel)
            continue
        center, center_source = _center(minimum, maximum, center_override.get(channel))
        axes[channel] = AxisDraft(
            plan.codes[channel], minimum, center, maximum, source, center_source
        )
    for channel in TRIGGER_CHANNELS:
        minimum, maximum, source = ranges[channel]
        if maximum <= minimum:
            invalid.append(channel)
            continue
        if minimum < 0:
            _add_unique(warnings, "trigger_signed_range")
        triggers[channel] = TriggerDraft(
            plan.codes[channel], minimum, maximum, source, ValueSource.RANGE_MINIMUM
        )
    if invalid:
        return _insufficient(capabilities, tuple(invalid), "invalid_range")
    provenance = DraftProvenance(
        catalog_entry_id=catalog.entry.entry_id if catalog.entry else None,
        catalog_version=catalog.catalog_version,
        catalog_source=catalog.source,
        provisional=True,
        provisional_fields=PROVISIONAL_FIELDS,
        warnings=tuple(dict.fromkeys(warnings)),
    )
    return MappingDraft(axes, triggers, plan.buttons, provenance, plan.axis_candidates)


def _plan_channels(
    capabilities: DeviceCapabilities,
    catalog: CatalogMatch,
    rules: DraftRules,
    *,
    driver: str | None,
    gamepad_kind: GamepadKind | None,
) -> _ChannelPlan | InsufficientCapabilities:
    entry = catalog.entry
    if entry is None:
        return _plan_generic(capabilities, rules, driver=driver, gamepad_kind=gamepad_kind)
    if entry.unsupported_reason is not None:
        missing = tuple(channel for channel in MAPPING_CHANNELS if channel not in entry.channels)
        return _insufficient(capabilities, missing, entry.unsupported_reason)
    present = capabilities.button_codes
    buttons = {code: name for code, name in entry.buttons.items() if code in present}
    return _ChannelPlan(entry.channels, buttons, (), ())


def _plan_generic(
    capabilities: DeviceCapabilities,
    rules: DraftRules,
    *,
    driver: str | None,
    gamepad_kind: GamepadKind | None,
) -> _ChannelPlan | InsufficientCapabilities:
    axes = capabilities.axis_codes
    codes: dict[str, int] = {}
    warnings: list[str] = []
    candidates: list[str] = []
    if set(rules.left_stick) <= axes:
        codes["lx"], codes["ly"] = rules.left_stick
    if set(rules.right_stick) <= axes:
        codes["rx"], codes["ry"] = rules.right_stick
    elif set(rules.right_stick_fallback) <= axes:
        codes["rx"], codes["ry"] = rules.right_stick_fallback
        warnings.append("ambiguous_axis_assignment")
        candidates.append("rx={},ry={}".format(*rules.right_stick_fallback))
    used = set(codes.values())
    trigger_pairs = [
        pair
        for pair in rules.trigger_candidates
        if set(pair) <= axes and not set(pair) & used and pair[0] != pair[1]
    ]
    if trigger_pairs:
        codes["lt"], codes["rt"] = trigger_pairs[0]
        if len(trigger_pairs) > 1:
            _add_unique(warnings, "ambiguous_axis_assignment")
            candidates.extend("lt={},rt={}".format(*pair) for pair in trigger_pairs)
        elif candidates:
            candidates.append("lt={},rt={}".format(*trigger_pairs[0]))
    missing = tuple(channel for channel in MAPPING_CHANNELS if channel not in codes)
    if missing:
        triggers_missing = set(TRIGGER_CHANNELS) & set(missing)
        has_digital = set(rules.digital_trigger_buttons) <= capabilities.button_codes
        reason = "digital_triggers_only" if triggers_missing and has_digital else "missing_channels"
        return _insufficient(capabilities, missing, reason)
    if gamepad_kind is GamepadKind.GAMEPAD and driver not in rules.non_positional_drivers:
        present = capabilities.button_codes
        buttons = {code: name for code, name in rules.positional_buttons.items() if code in present}
    else:
        buttons = {}
        warnings.append("face_buttons_not_positional")
    return _ChannelPlan(codes, buttons, tuple(candidates), tuple(warnings))


def _resolve_range(
    code: int,
    capabilities: DeviceCapabilities,
    known_ranges: Mapping[int, KnownRange],
    warnings: list[str],
) -> tuple[int, int, RangeSource] | None:
    axis = capabilities.axis(code)
    absinfo: AbsInfo | None = axis.absinfo if axis else None
    known = known_ranges.get(code)
    if absinfo is not None:
        for name in absinfo.discarded_fields:
            _add_unique(warnings, f"absinfo_negative_field:{name}")
        if known is not None and (known.minimum, known.maximum) != (
            absinfo.minimum,
            absinfo.maximum,
        ):
            _add_unique(warnings, f"catalog_range_mismatch:{code}")
        return absinfo.minimum, absinfo.maximum, RangeSource.EVDEV_ABSINFO
    if known is not None:
        return known.minimum, known.maximum, RangeSource.CATALOG
    return None


def _center(minimum: int, maximum: int, override: int | None) -> tuple[int, ValueSource]:
    if override is not None and minimum < override < maximum:
        return override, ValueSource.CATALOG_OVERRIDE
    return (minimum + maximum + 1) // 2, ValueSource.MIDPOINT


def _insufficient(
    capabilities: DeviceCapabilities, missing: tuple[str, ...], reason: str
) -> InsufficientCapabilities:
    return InsufficientCapabilities(
        missing_channels=missing,
        detected_axes=tuple(sorted(capabilities.axis_codes)),
        detected_buttons=tuple(sorted(capabilities.button_codes)),
        reason=reason,
    )


def _add_unique(warnings: list[str], warning: str) -> None:
    if warning not in warnings:
        warnings.append(warning)
