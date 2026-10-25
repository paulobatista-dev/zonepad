from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .identity import MappingKey


class ZonaPadError(Exception):
    """Base class for expected ZonaPad failures."""


class InvalidProfileError(ZonaPadError, ValueError):
    """Raised when a profile is malformed or outside supported limits."""


class InvalidMappingError(ZonaPadError, ValueError):
    """Raised when a device mapping is malformed or unsupported."""


class DeviceNotFoundError(ZonaPadError):
    """Raised when a requested device is not available."""


class DeviceDisconnectedError(ZonaPadError):
    """Raised when a previously opened device disappears."""


class UnsupportedPlatformError(ZonaPadError):
    """Raised when an infrastructure adapter is not available on this OS."""


class MeasurementInputError(ZonaPadError, ValueError):
    """Raised when a capture, manifest or thresholds file cannot be measured.

    ``code`` is a stable identifier shown as ``[CODE]`` at the start of the message.
    """

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"[{code}] {detail}")
        self.code = code
        self.detail = detail


class ProfileDerivationError(ZonaPadError, ValueError):
    """Raised when measured metrics cannot yield a valid schema-v1 profile."""


class InvalidReportError(ZonaPadError, ValueError):
    """Raised when a metrics report violates its strict schema."""


class AmbiguousDeviceError(ZonaPadError):
    """Raised when a device reference matches more than one discovered gamepad."""

    def __init__(self, reference: str, candidates: tuple[str, ...]) -> None:
        super().__init__(f"device reference {reference!r} is ambiguous: {', '.join(candidates)}")
        self.reference = reference
        self.candidates = candidates


class AmbiguousAxisAssignmentError(ZonaPadError):
    """Raised when the generic heuristic found more than one plausible axis layout."""

    def __init__(self, candidates: tuple[str, ...]) -> None:
        super().__init__(f"ambiguous axis assignment: {'; '.join(candidates)}")
        self.candidates = candidates


class DeviceAccessDeniedError(ZonaPadError):
    """Raised when an input node exists but the process cannot open it."""

    def __init__(self, event_node: str) -> None:
        super().__init__(f"permission denied for input node {event_node}")
        self.event_node = event_node


class MappingNotFoundError(ZonaPadError):
    """Raised when no saved mapping exists for a mapping key."""

    def __init__(self, key: MappingKey) -> None:
        super().__init__(f"no saved mapping for {key.stable_id}")
        self.key = key


class MappingConflictError(ZonaPadError):
    """Raised when saving or resolving a mapping conflicts with existing state."""


class InvalidSavedMappingError(InvalidMappingError):
    """Raised when the saved mapping of a device exists but cannot be used."""

    def __init__(self, stable_id: str, detail: str) -> None:
        super().__init__(f"saved mapping for {stable_id} is invalid: {detail}")
        self.stable_id = stable_id
        self.detail = detail


class InvalidCatalogError(ZonaPadError, ValueError):
    """Raised when a device family catalog violates its strict schema."""
