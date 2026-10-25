"""``mapping draft`` use case: absinfo probe, catalog lookup and provisional draft."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Literal

from zonepad.domain.catalog import CatalogMatch
from zonepad.domain.discovery import AbsInfo
from zonepad.domain.errors import (
    AmbiguousAxisAssignmentError,
    DeviceAccessDeniedError,
    MappingConflictError,
    UnsupportedPlatformError,
)
from zonepad.domain.identity import Connection, MappingKey
from zonepad.domain.mapping_draft import (
    DraftRules,
    InsufficientCapabilities,
    MappingDraft,
    RangeSource,
    build_draft,
)

from .discovery import ResolvedDevice
from .ports import AbsInfoReader, DeviceCatalog, MappingRecord

LOGGER = logging.getLogger("zonepad.mapping_draft")
ABSINFO_PERMISSION_DENIED = "absinfo_permission_denied"
ABSINFO_UNSUPPORTED_PLATFORM = "absinfo_unsupported_platform"


@dataclass(frozen=True, slots=True)
class DraftOutcome:
    draft: MappingDraft
    catalog: CatalogMatch
    absinfo: Mapping[int, AbsInfo]
    probed_node: str | None


def draft_mapping(
    resolved: ResolvedDevice,
    *,
    absinfo_reader: AbsInfoReader | None,
    catalog: DeviceCatalog,
    rules: DraftRules,
    accept_axis_guess: bool = False,
) -> DraftOutcome | InsufficientCapabilities:
    """Build a provisional draft for ``resolved``; nothing is persisted here.

    ``absinfo_reader=None`` is ``--no-probe``: ranges come only from the catalog.
    Without permission on the node the catalog ranges are used; if they are
    missing too, ``DeviceAccessDeniedError`` propagates (exit 3).  Ambiguous
    generic layouts raise ``AmbiguousAxisAssignmentError`` unless accepted.
    """
    observed = resolved.device.observed
    capabilities = observed.capabilities
    if capabilities is None:  # gamepads always carry capabilities
        raise ValueError(f"{observed.event_node} has no capabilities")
    match = catalog.match(observed)
    absinfo: Mapping[int, AbsInfo] = MappingProxyType({})
    access_denied = False
    probe_warning: str | None = None
    probed_node: str | None = None
    if absinfo_reader is not None:
        codes = _probe_codes(match, rules, capabilities.axis_codes)
        probed_node = observed.event_node
        try:
            absinfo = MappingProxyType(dict(absinfo_reader.read_absinfo(probed_node, codes)))
        except UnsupportedPlatformError as exc:
            probe_warning = ABSINFO_UNSUPPORTED_PLATFORM
            LOGGER.warning("absinfo unavailable on this platform: %s", exc)
        except DeviceAccessDeniedError:
            access_denied = True
            probe_warning = ABSINFO_PERMISSION_DENIED
            LOGGER.warning(
                "absinfo permission denied node=%s; using catalog ranges",
                probed_node,
                extra={"node": probed_node},
            )
    result = build_draft(
        capabilities.with_absinfo(absinfo),
        match,
        rules,
        driver=observed.driver,
        gamepad_kind=resolved.device.verdict.gamepad_kind,
    )
    if isinstance(result, InsufficientCapabilities):
        if access_denied and result.reason == "ranges_unavailable":
            raise DeviceAccessDeniedError(observed.event_node)
        return result
    if result.axis_candidates and not accept_axis_guess:
        raise AmbiguousAxisAssignmentError(result.axis_candidates)
    if probe_warning is not None:
        result = _with_warning(result, probe_warning)
    elif absinfo_reader is not None:
        for channel, source in result.range_sources.items():
            if source is RangeSource.CATALOG:
                result = _with_warning(result, f"absinfo_unavailable:{result.codes[channel]}")
    return DraftOutcome(result, match, absinfo, probed_node)


def resolve_connection(
    detected: Connection, override: Connection | None
) -> tuple[Connection, Literal["detected", "override"]]:
    """``--connection`` only replaces a detected ``unknown`` (spec RF7)."""
    if override is None or override is detected:
        return detected, "detected"
    if detected is not Connection.UNKNOWN:
        raise MappingConflictError(
            f"--connection {override.value} conflicts with detected connection {detected.value}"
        )
    return override, "override"


def build_mapping_record(
    resolved: ResolvedDevice,
    outcome: DraftOutcome,
    mapping_text: str,
    *,
    connection_override: Connection | None,
    created_at: str,
    app_version: str,
) -> MappingRecord:
    connection, connection_source = resolve_connection(
        resolved.identity.connection, connection_override
    )
    return MappingRecord(
        key=MappingKey(resolved.identity.stable_id, connection),
        identity=resolved.identity,
        connection_source=connection_source,
        mapping_text=mapping_text,
        provenance=outcome.draft.provenance,
        range_source=outcome.draft.range_source.value,
        range_sources={name: source.value for name, source in outcome.draft.range_sources.items()},
        absinfo=outcome.absinfo,
        created_at=created_at,
        app_version=app_version,
    )


def _probe_codes(match: CatalogMatch, rules: DraftRules, present: frozenset[int]) -> list[int]:
    wanted = set(match.entry.channels.values()) if match.entry else set(rules.probe_codes)
    return sorted(wanted & present)


def _with_warning(draft: MappingDraft, warning: str) -> MappingDraft:
    warnings = tuple(dict.fromkeys((*draft.provenance.warnings, warning)))
    return replace(draft, provenance=replace(draft.provenance, warnings=warnings))
