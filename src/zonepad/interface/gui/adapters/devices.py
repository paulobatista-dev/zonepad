"""Adapters from the GUI to the discovery and mapping application ports."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from zonepad.application.discovery import ResolvedDevice, discover_devices, resolve_device_reference
from zonepad.application.hotplug import (
    DEFAULT_POLL_INTERVAL_S,
    PollingHotplugWatcher,
    validate_poll_interval,
)
from zonepad.application.mapping_resolution import ResolvedMappingRef, resolve_mapping
from zonepad.application.ports import DeviceMappingStore, DeviceSession
from zonepad.domain.discovery import DiscoverySnapshot
from zonepad.domain.errors import DeviceDisconnectedError, MappingNotFoundError
from zonepad.domain.identity import MappingKey
from zonepad.infrastructure.clock import SystemClock
from zonepad.infrastructure.device_store import JsonDeviceMappingStore
from zonepad.infrastructure.evdev import LinuxEvdevBackend
from zonepad.infrastructure.files import sha256_file
from zonepad.infrastructure.linux_input_policy import discovery_policies
from zonepad.infrastructure.mapping import DeviceMapping, load_device_mapping
from zonepad.infrastructure.sysfs import SysfsInputScanner


@dataclass(frozen=True, slots=True)
class GuiDiscoveredDevice:
    resolved: ResolvedDevice
    mapping_status: str
    mapping_detail: str | None = None


@dataclass(frozen=True, slots=True)
class SessionResolution:
    device: GuiDiscoveredDevice
    mapping: DeviceMapping
    mapping_ref: ResolvedMappingRef
    mapping_path: Path


class DeviceAdapter:
    """Compose existing sysfs discovery, mapping registry and evdev backend."""

    def __init__(
        self,
        *,
        sysfs_root: Path = Path("/sys"),
        devices_dir: Path = Path("~/.config/zonepad/devices"),
        store: DeviceMappingStore | None = None,
    ) -> None:
        self._sysfs_root = sysfs_root.expanduser()
        self._devices_dir = devices_dir.expanduser()
        self._store = store or JsonDeviceMappingStore(self._devices_dir)
        self._watcher: PollingHotplugWatcher | None = None
        self._poll_interval = validate_poll_interval(DEFAULT_POLL_INTERVAL_S * 2)

    def snapshot(self) -> DiscoverySnapshot:
        scanner = SysfsInputScanner(self._sysfs_root)
        return discover_devices(scanner, discovery_policies())

    def list_devices(self) -> tuple[GuiDiscoveredDevice, ...]:
        watcher = self._get_watcher()
        snapshot = watcher.snapshot()
        return self._devices_from_snapshot(snapshot)

    def poll_devices(self) -> tuple[GuiDiscoveredDevice, ...]:
        watcher = self._get_watcher()
        if watcher.has_snapshot:
            watcher.poll()
        else:
            watcher.snapshot()
        return self._devices_from_snapshot(watcher.current_snapshot)

    def _devices_from_snapshot(
        self, snapshot: DiscoverySnapshot
    ) -> tuple[GuiDiscoveredDevice, ...]:
        result: list[GuiDiscoveredDevice] = []
        for candidate in snapshot.gamepads:
            identity = candidate.identity
            if identity is None:
                continue
            ref = self._store.find(MappingKey(identity.stable_id, identity.connection))
            result.append(
                GuiDiscoveredDevice(
                    resolve_device_reference(identity.stable_id, snapshot),
                    ref.status if ref is not None else "absent",
                    ref.detail if ref is not None else None,
                )
            )
        return tuple(result)

    def _get_watcher(self) -> PollingHotplugWatcher:
        if self._watcher is None:
            scanner = SysfsInputScanner(self._sysfs_root)
            self._watcher = PollingHotplugWatcher(
                scanner,
                discovery_policies(),
                SystemClock(),
                self._poll_interval,
            )
        return self._watcher

    def resolve_session(self, stable_id: str) -> SessionResolution:
        snapshot = self.snapshot()
        resolved = resolve_device_reference(stable_id, snapshot)
        gui_device = GuiDiscoveredDevice(resolved, "absent")
        try:
            mapping_ref = resolve_mapping(
                None,
                resolved.identity,
                self._store,
                sha256_of=lambda path: sha256_file(Path(path)),
            )
        except MappingNotFoundError:
            raise
        mapping_path = Path(mapping_ref.path)
        mapping = load_device_mapping(mapping_path)
        return SessionResolution(gui_device, mapping, mapping_ref, mapping_path)

    def open_session(self, resolution: SessionResolution) -> DeviceSession:
        expected = resolution.device.resolved

        def identity_still_matches() -> bool:
            current = resolve_device_reference(str(expected.identity.stable_id), self.snapshot())
            return (
                current.event_node == expected.event_node
                and current.device.tracking_key == expected.device.tracking_key
            )

        if not identity_still_matches():
            raise DeviceDisconnectedError("a conexão mudou depois da seleção do controle")
        backend = LinuxEvdevBackend(mapping=resolution.mapping)
        session = backend.open(expected.event_node)
        try:
            if not identity_still_matches():
                raise DeviceDisconnectedError("a conexão mudou ao abrir o dispositivo")
        except Exception:
            session.close()
            raise
        return session
