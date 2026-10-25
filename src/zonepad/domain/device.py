from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class DeviceInfo:
    """Stable identity and capabilities exposed by a device backend."""

    device_id: str
    name: str
    vendor_id: int | None = None
    product_id: int | None = None
    guid: str | None = None
    serial: str | None = None
    capabilities: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        if not self.device_id:
            raise ValueError("device_id must not be empty")
        if not self.name:
            raise ValueError("name must not be empty")
        if self.vendor_id is not None and not 0 <= self.vendor_id <= 0xFFFF:
            raise ValueError("vendor_id must be a 16-bit integer")
        if self.product_id is not None and not 0 <= self.product_id <= 0xFFFF:
            raise ValueError("product_id must be a 16-bit integer")
        object.__setattr__(self, "capabilities", frozenset(self.capabilities))

    @property
    def vid(self) -> int | None:
        return self.vendor_id

    @property
    def pid(self) -> int | None:
        return self.product_id
