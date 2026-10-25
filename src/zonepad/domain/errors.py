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
