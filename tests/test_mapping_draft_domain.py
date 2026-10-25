from __future__ import annotations

from dataclasses import replace

from sysfs_builder import DUALSENSE_ABSINFO, GENERIC_4095_ABSINFO, XBOX_ONE_ABSINFO

from zonepad.domain.catalog import CatalogMatch
from zonepad.domain.discovery import (
    AbsInfo,
    DeviceCapabilities,
    GamepadKind,
    absinfo_from_kernel,
)
from zonepad.domain.mapping_draft import (
    PROVISIONAL_FIELDS,
    InsufficientCapabilities,
    MappingDraft,
    RangeSource,
    ValueSource,
    build_draft,
)
from zonepad.infrastructure.catalog import load_builtin_catalog
from zonepad.infrastructure.linux_input_policy import draft_rules

RULES = draft_rules()
CATALOG = load_builtin_catalog()
ENTRIES = {entry.entry_id: entry for entry in CATALOG.entries}
FACE = frozenset({0x130, 0x131, 0x133, 0x134})
GENERIC = CatalogMatch(None, 1, "generic")


def _match(entry_id: str) -> CatalogMatch:
    return CatalogMatch(ENTRIES[entry_id], 1, "builtin")


def _caps(
    axes: frozenset[int] = frozenset({0, 1, 2, 3, 4, 5}),
    buttons: frozenset[int] = FACE | {0x136, 0x137},
    absinfo: dict[int, AbsInfo] | None = None,
) -> DeviceCapabilities:
    caps = DeviceCapabilities.from_codes(
        event_types=frozenset({0, 1, 3}), axes=axes, buttons=buttons
    )
    return caps.with_absinfo(absinfo or {})


def _draft(caps: DeviceCapabilities, match: CatalogMatch, driver: str = "xpad") -> MappingDraft:
    result = build_draft(caps, match, RULES, driver=driver, gamepad_kind=GamepadKind.GAMEPAD)
    assert isinstance(result, MappingDraft), result
    return result


def test_xbox_one_draft_with_absinfo_matches_the_fixture_table() -> None:
    draft = _draft(_caps(absinfo=XBOX_ONE_ABSINFO), _match("xpad-xboxone"))

    for name, code in (("lx", 0), ("ly", 1), ("rx", 3), ("ry", 4)):
        axis = draft.axes[name]
        assert (axis.code, axis.minimum, axis.center, axis.maximum) == (code, -32768, 0, 32767)
        assert axis.range_source is RangeSource.EVDEV_ABSINFO
        assert axis.center_source is ValueSource.MIDPOINT
    for name, code in (("lt", 2), ("rt", 5)):
        trigger = draft.triggers[name]
        assert (trigger.code, trigger.rest, trigger.maximum) == (code, 0, 1023)
        assert trigger.rest_source is ValueSource.RANGE_MINIMUM
    assert dict(draft.buttons) == {
        304: "button_south",
        305: "button_east",
        307: "button_north",
        308: "button_west",
    }
    assert draft.provenance.provisional
    assert draft.provenance.provisional_fields == PROVISIONAL_FIELDS
    assert draft.provenance.catalog_entry_id == "xpad-xboxone"
    assert draft.provenance.warnings == ("provisional_center",)
    assert draft.range_source is RangeSource.EVDEV_ABSINFO
    assert draft.axis_candidates == ()


def test_catalog_ranges_are_used_without_absinfo() -> None:
    draft = _draft(_caps(), _match("xpad-xboxone"))

    assert draft.axes["lx"].range_source is RangeSource.CATALOG
    assert (draft.triggers["rt"].rest, draft.triggers["rt"].maximum) == (0, 1023)
    assert draft.range_source is RangeSource.CATALOG


def test_absinfo_wins_over_divergent_catalog_ranges_with_a_warning() -> None:
    absinfo = dict(XBOX_ONE_ABSINFO)
    absinfo[2] = absinfo_from_kernel(0, 0, 255, 0, 0, 0)

    draft = _draft(_caps(absinfo=absinfo), _match("xpad-xboxone"))

    assert draft.triggers["lt"].maximum == 255
    assert "catalog_range_mismatch:2" in draft.provenance.warnings


def test_dualsense_draft_has_centers_at_128() -> None:
    draft = _draft(_caps(absinfo=DUALSENSE_ABSINFO), _match("playstation-dualsense"), "playstation")

    assert {(a.minimum, a.center, a.maximum) for a in draft.axes.values()} == {(0, 128, 255)}
    assert {(t.rest, t.maximum) for t in draft.triggers.values()} == {(0, 255)}


def test_switch_pro_is_unsupported_with_digital_triggers() -> None:
    caps = _caps(axes=frozenset({0, 1, 3, 4, 0x10, 0x11}), buttons=FACE | {0x138, 0x139})

    result = build_draft(
        caps, _match("nintendo-procon"), RULES, driver="nintendo", gamepad_kind=GamepadKind.GAMEPAD
    )

    assert isinstance(result, InsufficientCapabilities)
    assert result.reason == "digital_triggers_only"
    assert result.missing_channels == ("lt", "rt")


def test_generic_range_0_4095_gets_center_2048_and_no_positional_buttons() -> None:
    draft = _draft(
        _caps(axes=frozenset(range(6)), absinfo=GENERIC_4095_ABSINFO), GENERIC, "hid-generic"
    )

    assert (draft.axes["lx"].minimum, draft.axes["lx"].center, draft.axes["lx"].maximum) == (
        0,
        2048,
        4095,
    )
    assert dict(draft.buttons) == {}
    assert "face_buttons_not_positional" in draft.provenance.warnings
    assert draft.provenance.catalog_source == "generic"
    assert draft.provenance.catalog_entry_id is None


def test_generic_non_hid_driver_keeps_positional_buttons() -> None:
    draft = _draft(_caps(absinfo=GENERIC_4095_ABSINFO), GENERIC, "xpadneo")

    assert set(draft.buttons) == {304, 305, 307, 308}


def test_generic_without_trigger_pair_reports_digital_triggers() -> None:
    caps = _caps(
        axes=frozenset({0, 1, 3, 4}), buttons=FACE | {0x138, 0x139}, absinfo=GENERIC_4095_ABSINFO
    )

    result = build_draft(
        caps, GENERIC, RULES, driver="hid-generic", gamepad_kind=GamepadKind.GAMEPAD
    )

    assert isinstance(result, InsufficientCapabilities)
    assert result.missing_channels == ("lt", "rt")
    assert result.reason == "digital_triggers_only"
    assert result.detected_axes == (0, 1, 3, 4)
    assert 0x138 in result.detected_buttons


def test_generic_without_trigger_and_without_digital_buttons_is_missing_channels() -> None:
    caps = _caps(axes=frozenset({0, 1, 3, 4}), buttons=FACE, absinfo=GENERIC_4095_ABSINFO)

    result = build_draft(
        caps, GENERIC, RULES, driver="hid-generic", gamepad_kind=GamepadKind.GAMEPAD
    )

    assert isinstance(result, InsufficientCapabilities)
    assert result.reason == "missing_channels"


def test_case_b_uses_z_rz_as_right_stick_and_lists_candidates() -> None:
    axes = frozenset({0, 1, 2, 5, 9, 10})
    absinfo = {code: absinfo_from_kernel(0, 0, 255, 0, 0, 0) for code in axes}

    draft = _draft(_caps(axes=axes, absinfo=absinfo), GENERIC, "hid-generic")

    assert (draft.axes["rx"].code, draft.axes["ry"].code) == (2, 5)
    assert (draft.triggers["lt"].code, draft.triggers["rt"].code) == (10, 9)
    assert draft.axis_candidates == ("rx=2,ry=5", "lt=10,rt=9")
    assert "ambiguous_axis_assignment" in draft.provenance.warnings


def test_more_than_one_trigger_pair_is_ambiguous() -> None:
    axes = frozenset({0, 1, 2, 3, 4, 5, 9, 10})
    absinfo = {code: absinfo_from_kernel(0, 0, 255, 0, 0, 0) for code in axes}

    draft = _draft(_caps(axes=axes, absinfo=absinfo), GENERIC, "hid-generic")

    assert (draft.triggers["lt"].code, draft.triggers["rt"].code) == (2, 5)
    assert draft.axis_candidates == ("lt=2,rt=5", "lt=10,rt=9")


def test_generic_without_absinfo_is_ranges_unavailable() -> None:
    result = build_draft(
        _caps(), GENERIC, RULES, driver="hid-generic", gamepad_kind=GamepadKind.GAMEPAD
    )

    assert isinstance(result, InsufficientCapabilities)
    assert result.reason == "ranges_unavailable"
    assert result.code == "ranges_unavailable:lx,ly,rx,ry,lt,rt"


def test_tiny_stick_range_is_invalid() -> None:
    absinfo = dict(GENERIC_4095_ABSINFO)
    absinfo[0] = absinfo_from_kernel(0, 0, 1, 0, 0, 0)

    result = build_draft(
        _caps(absinfo=absinfo),
        GENERIC,
        RULES,
        driver="hid-generic",
        gamepad_kind=GamepadKind.GAMEPAD,
    )

    assert isinstance(result, InsufficientCapabilities)
    assert result.code == "invalid_range:lx"


def test_signed_trigger_range_warns() -> None:
    absinfo = dict(GENERIC_4095_ABSINFO)
    absinfo[2] = absinfo_from_kernel(0, -128, 127, 0, 0, 0)

    draft = _draft(_caps(absinfo=absinfo), GENERIC, "hid-generic")

    assert draft.triggers["lt"].rest == -128
    assert "trigger_signed_range" in draft.provenance.warnings


def test_negative_absinfo_field_is_discarded_with_a_warning() -> None:
    absinfo = dict(XBOX_ONE_ABSINFO)
    absinfo[0] = absinfo_from_kernel(0, -32768, 32767, -1, 128, 0)

    draft = _draft(_caps(absinfo=absinfo), _match("xpad-xboxone"))

    assert "absinfo_negative_field:fuzz" in draft.provenance.warnings


def test_center_override_inside_the_range_wins() -> None:
    entry = ENTRIES["xpad-xboxone"]
    match = CatalogMatch(replace(entry, center_override={"lx": 100}), 1, "user")

    draft = _draft(_caps(absinfo=XBOX_ONE_ABSINFO), match)

    assert draft.axes["lx"].center == 100
    assert draft.axes["lx"].center_source is ValueSource.CATALOG_OVERRIDE
    assert draft.axes["ly"].center == 0


def test_same_input_gives_equal_drafts() -> None:
    first = _draft(_caps(absinfo=XBOX_ONE_ABSINFO), _match("xpad-xboxone"))
    second = _draft(_caps(absinfo=XBOX_ONE_ABSINFO), _match("xpad-xboxone"))

    assert first == second
