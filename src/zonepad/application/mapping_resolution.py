"""Mapping precedence for ``run``/``calibrate`` (spec RF8, D8).

``--mapping`` explicit > saved mapping of the current key > actionable error.
This module chooses *which file*; the composition root loads it with
``load_device_mapping`` so the strict v1 validation stays in one place, and it
must parse an explicit mapping before calling ``resolve_mapping`` (row 2: an
invalid explicit mapping never falls back to the saved one).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from zonepad.domain.errors import (
    InvalidSavedMappingError,
    MappingConflictError,
    MappingNotFoundError,
)
from zonepad.domain.identity import Connection, MappingKey, StableIdentity

from .ports import DeviceMappingStore, StoredMappingRef


class MappingSource(StrEnum):
    EXPLICIT = "explicit"
    SAVED = "saved"


@dataclass(frozen=True, slots=True)
class ResolvedMappingRef:
    source: MappingSource
    path: str
    sha256: str | None
    provisional: bool | None
    overridden_saved: StoredMappingRef | None = None
    status: str | None = None
    range_source: str | None = None
    warnings: tuple[str, ...] = ()


def resolve_mapping(
    explicit_path: str | None,
    identity: StableIdentity | None,
    store: DeviceMappingStore | None,
    *,
    sha256_of: Callable[[str], str],
) -> ResolvedMappingRef:
    """Pick the mapping file for a device.

    ``identity=None`` is the legacy path (``eventN`` + ``--mapping``): neither the
    store nor the file hash is consulted.  Raises ``MappingNotFoundError`` and
    ``InvalidSavedMappingError`` (exit 2), and ``MappingConflictError`` when the
    recorded connection differs from a known detected connection (exit 2).
    """
    if identity is None:
        if explicit_path is None:
            raise ValueError("the legacy path requires an explicit mapping")
        return ResolvedMappingRef(MappingSource.EXPLICIT, explicit_path, None, None)
    if store is None:
        raise ValueError("a mapping store is required to resolve a stable identity")
    key = MappingKey(identity.stable_id, identity.connection)
    saved = store.find(key)
    if explicit_path is not None:
        comparable = saved if saved is not None and _same_connection(saved, key) else None
        return ResolvedMappingRef(
            MappingSource.EXPLICIT,
            explicit_path,
            sha256_of(explicit_path),
            None,
            overridden_saved=comparable,
        )
    if saved is None:
        raise MappingNotFoundError(key)
    if saved.status == "invalid":
        raise InvalidSavedMappingError(key.stable_id, saved.detail or "invalid")
    if not _same_connection(saved, key):
        raise MappingConflictError(
            f"saved mapping for {key.stable_id} was recorded for connection "
            f"{saved.key.connection.value}, detected {key.connection.value}"
        )
    return ResolvedMappingRef(
        MappingSource.SAVED,
        saved.mapping_path,
        saved.mapping_sha256,
        saved.provisional,
        status=saved.status,
        range_source=saved.range_source,
        warnings=_change_warnings(saved, identity),
    )


def _same_connection(saved: StoredMappingRef, key: MappingKey) -> bool:
    """The recorded connection only matters when the detected one is known (RF7)."""
    return key.connection is Connection.UNKNOWN or saved.key.connection is key.connection


def _change_warnings(saved: StoredMappingRef, identity: StableIdentity) -> tuple[str, ...]:
    warnings: list[str] = []
    if saved.status == "provisional":
        warnings.append("mapping_provisional")
    if saved.status == "edited":
        warnings.append("mapping_edited")
    if saved.recorded_device_version != identity.facts.device_version:
        warnings.append("device_version_changed")
    if saved.recorded_firmware != identity.facts.firmware:
        warnings.append("firmware_changed")
    return tuple(warnings)
