from __future__ import annotations

import hashlib
import re

import pytest

from zonepad.domain.identity import (
    MAX_STABLE_ID_LENGTH,
    STABLE_ID_PATTERN,
    Connection,
    HardwareFacts,
    QualifierSource,
    derive_stable_ids,
    event_node_sort_key,
    is_stable_id_base,
    parse_stable_id,
    stable_id_base,
)
from zonepad.infrastructure.linux_input_policy import identity_policy

POLICY = identity_policy()


def _facts(
    *,
    bustype: int = 0x03,
    vendor_id: int = 0x045E,
    product_id: int = 0x02EA,
    uniq: str | None = None,
    usb_serial: str | None = None,
    phys: str | None = None,
    name: str = "Pad",
) -> HardwareFacts:
    return HardwareFacts(
        bustype=bustype,
        vendor_id=vendor_id,
        product_id=product_id,
        device_version=0x0408,
        firmware=None,
        driver="xpad",
        name=name,
        uniq=uniq,
        usb_serial=usb_serial,
        phys=phys,
    )


def _expected_hash(source: str, value: str) -> str:
    return hashlib.sha256(f"{source}\0{value}".encode()).hexdigest()[:10]


def test_usb_serial_qualifier_is_a_hash_of_the_canonical_serial() -> None:
    identities = derive_stable_ids([("event3", _facts(usb_serial="SYNTH0001"))], POLICY)

    identity = identities["event3"]
    assert identity.stable_id == f"usb-045e-02ea-s{_expected_hash('usb_serial', 'SYNTH0001')}"
    assert identity.qualifier_source is QualifierSource.USB_SERIAL
    assert identity.connection is Connection.USB
    assert not identity.fragile
    assert identity.occurrence is None
    assert "SYNTH0001" not in identity.stable_id


def test_uniq_wins_over_serial_and_phys() -> None:
    facts = _facts(uniq="02:00:00:00:00:01", usb_serial="SYNTH0001", phys="usb-1/input0")

    identity = derive_stable_ids([("event3", facts)], POLICY)["event3"]

    assert identity.qualifier_source is QualifierSource.UNIQ
    assert identity.stable_id.endswith("-u" + _expected_hash("uniq", "020000000001"))


def test_mac_in_lower_and_upper_case_yields_the_same_qualifier() -> None:
    lower = _facts(bustype=0x05, uniq="02:00:00:00:00:0a")
    upper = _facts(bustype=0x05, uniq="02-00-00-00-00-0A")

    first = derive_stable_ids([("event1", lower)], POLICY)["event1"]
    second = derive_stable_ids([("event1", upper)], POLICY)["event1"]

    assert first.stable_id == second.stable_id
    assert first.stable_id.startswith("bt-045e-02ea-u")
    assert first.connection is Connection.BLUETOOTH


def test_phys_is_used_only_on_usb_with_a_port_warning() -> None:
    usb = derive_stable_ids([("event3", _facts(phys="usb-0000:00:14.0-2/input0"))], POLICY)
    bluetooth = derive_stable_ids([("event3", _facts(bustype=0x05, phys="02:00:00:aa"))], POLICY)

    assert usb["event3"].qualifier_source is QualifierSource.PHYS
    assert "identity_bound_to_port" in usb["event3"].warnings
    assert bluetooth["event3"].qualifier_source is QualifierSource.OCCURRENCE
    assert bluetooth["event3"].stable_id == "bt-045e-02ea-n1"


def test_serial_is_ignored_outside_usb() -> None:
    identity = derive_stable_ids([("event4", _facts(bustype=0x19, usb_serial="SYNTH9"))], POLICY)

    assert identity["event4"].stable_id == "bus0019-045e-02ea-n1"
    assert identity["event4"].connection is Connection.UNKNOWN


def test_placeholder_serial_counts_as_empty() -> None:
    identity = derive_stable_ids([("event3", _facts(uniq="000000", phys="usb-1/input0"))], POLICY)

    assert identity["event3"].qualifier_source is QualifierSource.PHYS
    assert "placeholder_serial" in identity["event3"].warnings


def test_whitespace_only_values_are_empty() -> None:
    identity = derive_stable_ids([("event3", _facts(uniq="  ", usb_serial=" \t"))], POLICY)

    assert identity["event3"].qualifier_source is QualifierSource.OCCURRENCE
    assert identity["event3"].fragile
    assert "identity_weak" in identity["event3"].warnings


def test_twins_without_qualifier_get_numeric_occurrences() -> None:
    twins = [("event10", _facts()), ("event2", _facts())]

    identities = derive_stable_ids(twins, POLICY)

    assert identities["event2"].stable_id == "usb-045e-02ea-n1"
    assert identities["event10"].stable_id == "usb-045e-02ea-n2"
    assert identities["event2"].occurrence == 1
    assert all(identity.fragile for identity in identities.values())
    assert all("duplicate_identity:2" in identity.warnings for identity in identities.values())


def test_single_occurrence_still_has_suffix_n1_and_is_fragile() -> None:
    identity = derive_stable_ids([("event7", _facts())], POLICY)["event7"]

    assert identity.stable_id == "usb-045e-02ea-n1"
    assert identity.fragile
    assert not any(warning.startswith("duplicate_identity") for warning in identity.warnings)


def test_shared_qualifier_gets_dot_suffix_for_later_nodes() -> None:
    phys = "usb-0000:00:14.0-4/input0"
    pads = [("event41", _facts(phys=phys)), ("event40", _facts(phys=phys))]

    identities = derive_stable_ids(pads, POLICY)

    first, second = identities["event40"], identities["event41"]
    assert second.stable_id == f"{first.stable_id}.2"
    assert first.fragile and second.fragile
    assert "duplicate_identity:2" in first.warnings


def test_derivation_is_deterministic_and_independent_of_input_order() -> None:
    devices = [
        ("event5", _facts(usb_serial="SYNTH1")),
        ("event3", _facts()),
        ("event9", _facts()),
    ]

    forward = derive_stable_ids(devices, POLICY)
    backward = derive_stable_ids(list(reversed(devices)), POLICY)

    assert dict(forward) == dict(backward)


def test_name_does_not_change_the_identity() -> None:
    first = derive_stable_ids([("event3", _facts(usb_serial="SYNTH1", name="A"))], POLICY)
    second = derive_stable_ids([("event3", _facts(usb_serial="SYNTH1", name="B"))], POLICY)

    assert first["event3"].stable_id == second["event3"].stable_id


@pytest.mark.parametrize(
    "text",
    [
        "usb-045e-02ea-s1a2b3c4d5e",
        "bt-054c-0ce6-u0123456789",
        "bus0019-1209-0001-p0123456789.2",
        "usb-045e-02a1-p0123456789.99",
        "usb-1209-0009-n1",
        "usb-1209-0009-n999",
    ],
)
def test_parse_stable_id_accepts_the_grammar(text: str) -> None:
    assert parse_stable_id(text) == text
    assert len(text) <= MAX_STABLE_ID_LENGTH


@pytest.mark.parametrize(
    "text",
    [
        "",
        "../x",
        "usb-045e-02ea-s1a2b3c4d5e/..",
        "USB-045E-02EA-s1a2b3c4d5e",
        "usb-045e-02ea-s1a2b3c4d5",
        "usb-045e-02ea-x1a2b3c4d5e",
        "usb-045e-02ea-n0",
        "usb-045e-02ea-n1.2",
        "usb-045e-02ea-s1a2b3c4d5e.1",
        "usb-045e-02ea-s1a2b3c4d5e.100",
        "usb-045e-02ea-s1a2b3c4d5e ",
        "event3",
        "virtual-045e-02ea-n1",
    ],
)
def test_parse_stable_id_rejects_everything_else(text: str) -> None:
    with pytest.raises(ValueError):
        parse_stable_id(text)


def test_longest_valid_id_fits_the_length_limit() -> None:
    longest = "bus0019-045e-02ea-s0123456789.99"

    assert STABLE_ID_PATTERN.fullmatch(longest)
    assert len(longest) <= MAX_STABLE_ID_LENGTH


def test_base_helpers() -> None:
    stable_id = parse_stable_id("usb-045e-02ea-p0123456789.2")

    assert stable_id_base(stable_id) == "usb-045e-02ea"
    assert is_stable_id_base("usb-045e-02ea")
    assert not is_stable_id_base("usb-045e")


def test_event_nodes_sort_numerically() -> None:
    nodes = ["event10", "event2", "js0", "event1"]

    assert sorted(nodes, key=event_node_sort_key) == ["event1", "event2", "event10", "js0"]


def test_hardware_facts_reject_out_of_range_ids() -> None:
    with pytest.raises(ValueError):
        _facts(vendor_id=0x10000)


def test_stable_ids_never_contain_path_separators() -> None:
    identities = derive_stable_ids(
        [("event3", _facts(uniq="../../etc/passwd")), ("event4", _facts(phys="a/b c"))], POLICY
    )

    for identity in identities.values():
        assert re.fullmatch(r"[a-z0-9.-]+", identity.stable_id)
