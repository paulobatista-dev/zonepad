"""Pure device-list state and formatting for the GUI."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DeviceItem:
    stable_id: str
    name: str
    vid: int
    pid: int
    connection: str
    event_node: str
    mapping_status: str
    fragile: bool
    warnings: tuple[str, ...] = ()

    @property
    def label(self) -> str:
        state = f"mapping: {self.mapping_status}"
        fragile = "; identidade frágil" if self.fragile else ""
        return (
            f"{self.name} ({self.stable_id}) · {self.vid:04x}:{self.pid:04x} · "
            f"{self.connection} · {self.event_node} · {state}{fragile}"
        )


@dataclass(frozen=True, slots=True)
class DeviceListState:
    items: tuple[DeviceItem, ...] = ()
    error: str | None = None


def status_label(status: str | None) -> str:
    return {
        None: "ausente",
        "saved": "salvo",
        "provisional": "provisório",
        "edited": "editado",
        "invalid": "inválido",
    }.get(status, status or "ausente")
