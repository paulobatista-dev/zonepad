from __future__ import annotations

from pathlib import Path

import pytest
from discovery_fakes import InMemoryMappingStore

from zonepad.application.mapping_resolution import MappingSource, resolve_mapping
from zonepad.application.ports import StoredMappingRef
from zonepad.domain.errors import (
    InvalidSavedMappingError,
    MappingConflictError,
    MappingNotFoundError,
)
from zonepad.domain.identity import (
    Connection,
    HardwareFacts,
    MappingKey,
    QualifierSource,
    StableId,
    StableIdentity,
)

STABLE_ID = StableId("usb-045e-02ea-s0123456789")


def _identity(
    connection: Connection = Connection.USB, *, device_version: int = 0x0408
) -> StableIdentity:
    facts = HardwareFacts(
        0x03, 0x045E, 0x02EA, device_version, None, "xpad", "Pad", None, "S", None
    )
    return StableIdentity(STABLE_ID, facts, connection, QualifierSource.USB_SERIAL, None, False)


def _saved(
    status: str = "provisional",
    *,
    connection: Connection = Connection.USB,
    detail: str | None = None,
    device_version: int | None = 0x0408,
) -> StoredMappingRef:
    return StoredMappingRef(
        key=MappingKey(STABLE_ID, connection),
        mapping_path="/devices/saved/mapping.json",
        mapping_sha256="b" * 64,
        recorded_sha256="b" * 64 if status != "edited" else "c" * 64,
        provisional=True,
        range_source="evdev_absinfo",
        status=status,  # type: ignore[arg-type]
        detail=detail,
        fragile=False,
        recorded_device_version=device_version,
        recorded_firmware=None,
    )


def _sha(path: str) -> str:
    return "a" * 64 if path.endswith("explicit.json") else "z" * 64


def _store(*refs: StoredMappingRef) -> InMemoryMappingStore:
    return InMemoryMappingStore({ref.key.stable_id: ref for ref in refs})


class _ExplodingStore(InMemoryMappingStore):
    def find(self, key: MappingKey) -> StoredMappingRef | None:
        raise AssertionError("the legacy path must not consult the store")


def test_row1_legacy_event_node_with_explicit_mapping_skips_store_and_hash() -> None:
    def no_hash(path: str) -> str:
        raise AssertionError("legacy path must not hash")

    ref = resolve_mapping("explicit.json", None, _ExplodingStore(), sha256_of=no_hash)

    assert (ref.source, ref.path, ref.sha256, ref.overridden_saved) == (
        MappingSource.EXPLICIT,
        "explicit.json",
        None,
        None,
    )


def test_row3_explicit_without_saved_mapping() -> None:
    ref = resolve_mapping("explicit.json", _identity(), _store(), sha256_of=_sha)

    assert ref.source is MappingSource.EXPLICIT
    assert ref.sha256 == "a" * 64
    assert ref.overridden_saved is None


def test_row4_explicit_wins_over_saved_and_exposes_it_for_logging() -> None:
    saved = _saved()

    ref = resolve_mapping("explicit.json", _identity(), _store(saved), sha256_of=_sha)

    assert ref.source is MappingSource.EXPLICIT
    assert ref.path == "explicit.json"
    assert ref.overridden_saved == saved
    assert ref.sha256 != saved.mapping_sha256


def test_row4_explicit_still_wins_when_saved_is_invalid() -> None:
    ref = resolve_mapping(
        "explicit.json", _identity(), _store(_saved("invalid", detail="x")), sha256_of=_sha
    )

    assert ref.source is MappingSource.EXPLICIT


@pytest.mark.parametrize(
    ("status", "warning"),
    [("provisional", "mapping_provisional"), ("edited", "mapping_edited"), ("saved", None)],
)
def test_row5_saved_mapping_is_used_with_status_warnings(status: str, warning: str | None) -> None:
    ref = resolve_mapping(None, _identity(), _store(_saved(status)), sha256_of=_sha)

    assert ref.source is MappingSource.SAVED
    assert ref.path == "/devices/saved/mapping.json"
    assert ref.sha256 == "b" * 64
    assert ref.status == status
    assert ref.range_source == "evdev_absinfo"
    expected = (warning,) if warning else ()
    assert ref.warnings == expected


def test_row6_invalid_saved_mapping_is_an_error_with_the_field() -> None:
    saved = _saved("invalid", detail="mapping.axes.lx has unknown fields: extra")

    with pytest.raises(InvalidSavedMappingError) as raised:
        resolve_mapping(None, _identity(), _store(saved), sha256_of=_sha)

    assert raised.value.detail == "mapping.axes.lx has unknown fields: extra"


def test_row7_absent_saved_mapping_is_not_found() -> None:
    with pytest.raises(MappingNotFoundError) as raised:
        resolve_mapping(None, _identity(), _store(), sha256_of=_sha)

    assert raised.value.key == MappingKey(STABLE_ID, Connection.USB)


def test_known_connection_mismatch_is_a_conflict() -> None:
    saved = _saved(connection=Connection.BLUETOOTH)

    with pytest.raises(MappingConflictError, match="connection"):
        resolve_mapping(None, _identity(Connection.USB), _store(saved), sha256_of=_sha)


def test_unknown_detected_connection_finds_mapping_recorded_with_override() -> None:
    saved = _saved(connection=Connection.USB)

    ref = resolve_mapping(None, _identity(Connection.UNKNOWN), _store(saved), sha256_of=_sha)

    assert ref.source is MappingSource.SAVED


def test_device_version_change_warns_but_keeps_the_mapping() -> None:
    ref = resolve_mapping(
        None, _identity(device_version=0x0500), _store(_saved("saved")), sha256_of=_sha
    )

    assert ref.source is MappingSource.SAVED
    assert ref.warnings == ("device_version_changed",)


def test_programming_errors_are_rejected() -> None:
    with pytest.raises(ValueError):
        resolve_mapping(None, None, _store(), sha256_of=_sha)
    with pytest.raises(ValueError):
        resolve_mapping(None, _identity(), None, sha256_of=_sha)


def test_explicit_hash_uses_the_injected_function(tmp_path: Path) -> None:
    calls: list[str] = []

    def sha(path: str) -> str:
        calls.append(path)
        return "a" * 64

    resolve_mapping(str(tmp_path / "explicit.json"), _identity(), _store(), sha256_of=sha)

    assert calls == [str(tmp_path / "explicit.json")]
