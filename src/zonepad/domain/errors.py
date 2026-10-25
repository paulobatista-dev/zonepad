from __future__ import annotations


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
