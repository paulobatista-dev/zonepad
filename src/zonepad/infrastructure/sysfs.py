"""Read-only Linux sysfs scanner for input devices (spec RF1).

``root`` is the sysfs mount point (``/sys``); nodes are enumerated from
``<root>/class/input/event*`` and every resolved path must stay under ``root``.
This is the only module that touches ``/sys``; it never opens ``/dev/input``.
"""

from __future__ import annotations

import logging
import math
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from zonepad.domain.discovery import (
    DeviceCapabilities,
    ObservedInputDevice,
    ReadIssue,
    ReadIssueKind,
)
from zonepad.domain.errors import DeviceNotFoundError
from zonepad.domain.identity import event_node_sort_key

from .linux_input_policy import (
    ABS_MAX,
    BUS_USB,
    DEFAULT_BITMAP_WORD_BITS,
    EV_MAX,
    INPUT_PROP_MAX,
    KEY_MAX,
    REL_MAX,
)

LOGGER = logging.getLogger("zonepad.sysfs")
_EVENT_ENTRY = re.compile(r"event[0-9]+", re.ASCII)
_HEX_WORD = re.compile(r"[0-9a-fA-F]+", re.ASCII)
_HEX_ID = re.compile(r"[0-9a-fA-F]{1,8}", re.ASCII)
_VIRTUAL_INPUT_SEGMENT = "/devices/virtual/input/"
_REPLACEMENT_CHARACTER = "�"

ReadText = Callable[[Path], str]


def read_sysfs_text(path: Path) -> str:
    """Default reader: UTF-8 with replacement (invalid bytes become U+FFFD)."""
    return path.read_text(encoding="utf-8", errors="replace")


class _Vanished(Exception):
    """The node disappeared during the scan; it is omitted from the snapshot."""


class _NodeIssue(Exception):
    def __init__(self, issue: ReadIssue) -> None:
        super().__init__(issue.reason)
        self.issue = issue


class MalformedBitmapError(ValueError):
    pass


def decode_bitmap(text: str, word_bits: int, max_code: int) -> frozenset[int]:
    """Decode an ``input_print_bitmap`` text (most significant word first).

    Raises ``MalformedBitmapError`` for non-hex words, a word ``>= 2**word_bits``,
    more words than ``max_code`` needs or a bit above ``max_code``.
    """
    words = text.strip().split(" ")
    if not words or not all(_HEX_WORD.fullmatch(word) for word in words):
        raise MalformedBitmapError("bitmap words must be hexadecimal")
    if len(words) > math.ceil((max_code + 1) / word_bits):
        raise MalformedBitmapError("bitmap has more words than the code range")
    value = 0
    for index, word in enumerate(reversed(words)):
        number = int(word, 16)
        if number >= 1 << word_bits:
            raise MalformedBitmapError("bitmap word exceeds the word width")
        value |= number << (index * word_bits)
    if value >> (max_code + 1):
        raise MalformedBitmapError("bitmap sets a bit above the maximum code")
    return frozenset(bit for bit in range(value.bit_length()) if value >> bit & 1)


@dataclass(slots=True)
class _NodeReader:
    """Reads the attributes of one node, collecting issues instead of raising."""

    root: Path
    event_dir: Path
    read_text: ReadText
    issues: list[ReadIssue] = field(default_factory=list)

    def confined(self, path: Path) -> Path:
        resolved = path.resolve()
        if not resolved.is_relative_to(self.root):
            raise _NodeIssue(ReadIssue(ReadIssueKind.OUTSIDE_SYSFS_ROOT))
        return resolved

    def text(self, path: Path, attribute: str, *, required: bool) -> str | None:
        try:
            raw = self.read_text(self.confined(path))
        except FileNotFoundError as exc:
            if not self.event_dir.exists():
                raise _Vanished from exc
            if required:
                raise _NodeIssue(ReadIssue(ReadIssueKind.UNREADABLE_ATTRIBUTE, attribute)) from exc
            return None
        except PermissionError as exc:
            raise _NodeIssue(ReadIssue(ReadIssueKind.PERMISSION_DENIED)) from exc
        except OSError as exc:
            if not required:
                return None
            raise _NodeIssue(ReadIssue(ReadIssueKind.UNREADABLE_ATTRIBUTE, attribute)) from exc
        if _REPLACEMENT_CHARACTER in raw:
            self.issues.append(ReadIssue(ReadIssueKind.INVALID_UTF8, attribute))
            LOGGER.warning("invalid UTF-8 in sysfs attribute=%s", attribute)
        return raw.removesuffix("\n")

    def hex_id(self, path: Path, attribute: str) -> int:
        text = self.text(path, attribute, required=True) or ""
        if not _HEX_ID.fullmatch(text.strip()):
            raise _NodeIssue(ReadIssue(ReadIssueKind.UNREADABLE_ATTRIBUTE, attribute))
        return int(text.strip(), 16)

    def bitmap(self, path: Path, attribute: str, word_bits: int, max_code: int) -> frozenset[int]:
        text = self.text(path, attribute, required=True) or ""
        try:
            return decode_bitmap(text, word_bits, max_code)
        except MalformedBitmapError as exc:
            raise _NodeIssue(ReadIssue(ReadIssueKind.MALFORMED_BITMAP, attribute)) from exc

    def link_target(self, path: Path) -> Path | None:
        """Resolve an optional symlink; ``None`` when absent or dangling."""
        if not path.is_symlink() and not path.exists():
            return None
        resolved = self.confined(path)
        return resolved if resolved.exists() else None


class SysfsInputScanner:
    """``InputDeviceScanner`` over a sysfs mount point.

    Observations without issues are cached by ``(event_node, input_token)``:
    attributes are fixed for the lifetime of an input registration.
    """

    def __init__(
        self,
        root: Path,
        bitmap_word_bits: int = DEFAULT_BITMAP_WORD_BITS,
        read_text: ReadText = read_sysfs_text,
    ) -> None:
        if bitmap_word_bits not in (32, 64):
            raise ValueError("bitmap_word_bits must be 32 or 64")
        self._root = root.expanduser().resolve()
        self._word_bits = bitmap_word_bits
        self._read_text = read_text
        self._cache: dict[tuple[str, str], ObservedInputDevice] = {}

    def scan(self) -> tuple[ObservedInputDevice, ...]:
        class_dir = self._root / "class" / "input"
        try:
            names = [entry.name for entry in class_dir.iterdir()]
        except (FileNotFoundError, NotADirectoryError) as exc:
            raise DeviceNotFoundError(f"sysfs input class not found: {class_dir}") from exc
        except PermissionError as exc:
            raise DeviceNotFoundError(f"sysfs input class is not readable: {class_dir}") from exc
        nodes = sorted(
            (name for name in names if _EVENT_ENTRY.fullmatch(name)), key=event_node_sort_key
        )
        observed: list[ObservedInputDevice] = []
        seen: set[tuple[str, str]] = set()
        for event_node in nodes:
            try:
                device = self._observe(class_dir / event_node, event_node)
            except _Vanished:
                LOGGER.info("input node vanished during scan node=%s", event_node)
                continue
            observed.append(device)
            if device.input_token is not None:
                seen.add((event_node, device.input_token))
        self._cache = {key: value for key, value in self._cache.items() if key in seen}
        return tuple(observed)

    def observe(self, event_node: str) -> ObservedInputDevice | None:
        """Re-read one node (post-``open`` verification); ``None`` if it is gone."""
        if not _EVENT_ENTRY.fullmatch(event_node):
            raise ValueError(f"invalid event node: {event_node!r}")
        try:
            return self._observe(self._root / "class" / "input" / event_node, event_node)
        except _Vanished:
            return None

    def _observe(self, entry: Path, event_node: str) -> ObservedInputDevice:
        reader = _NodeReader(self._root, entry, self._read_text)
        input_token: str | None = None
        try:
            event_dir = reader.confined(entry)
            if not event_dir.is_dir():
                if entry.is_symlink():
                    raise _NodeIssue(ReadIssue(ReadIssueKind.BROKEN_DEVICE_LINK))
                raise _Vanished
            reader.event_dir = event_dir
            input_dir = reader.link_target(event_dir / "device")
            if input_dir is None or not input_dir.is_dir():
                raise _NodeIssue(ReadIssue(ReadIssueKind.BROKEN_DEVICE_LINK))
            input_token = input_dir.name
            cached = self._cache.get((event_node, input_token))
            if cached is not None:
                return cached
            device = self._read_input_device(reader, event_node, input_dir)
        except _NodeIssue as problem:
            return _unreadable(event_node, input_token, (*reader.issues, problem.issue))
        if not device.issues:
            self._cache[(event_node, input_token)] = device
        return device

    def _read_input_device(
        self, reader: _NodeReader, event_node: str, input_dir: Path
    ) -> ObservedInputDevice:
        bustype = reader.hex_id(input_dir / "id" / "bustype", "id/bustype")
        vendor_id = reader.hex_id(input_dir / "id" / "vendor", "id/vendor")
        product_id = reader.hex_id(input_dir / "id" / "product", "id/product")
        version = reader.hex_id(input_dir / "id" / "version", "id/version")
        capabilities = self._read_capabilities(reader, input_dir)
        sysfs_path = "/" + input_dir.relative_to(self._root).as_posix()
        parent = reader.link_target(input_dir / "device")
        driver = firmware = interface_protocol = usb_serial = None
        if parent is not None:
            driver_dir = reader.link_target(parent / "driver")
            driver = driver_dir.name if driver_dir is not None else None
            firmware = _stripped(
                reader.text(parent / "firmware_version", "firmware_version", required=False)
            )
            interface_protocol = _stripped(
                reader.text(parent / "bInterfaceProtocol", "bInterfaceProtocol", required=False)
            )
        if bustype == BUS_USB:
            usb_serial = self._read_usb_serial(reader, input_dir, vendor_id, product_id)
        return ObservedInputDevice(
            event_node=event_node,
            input_token=input_dir.name,
            sysfs_path=sysfs_path,
            name=reader.text(input_dir / "name", "name", required=False),
            bustype=bustype,
            vendor_id=vendor_id,
            product_id=product_id,
            version=version,
            uniq=reader.text(input_dir / "uniq", "uniq", required=False),
            phys=reader.text(input_dir / "phys", "phys", required=False),
            usb_serial=usb_serial,
            driver=driver,
            firmware=firmware,
            usb_interface_protocol=interface_protocol,
            is_virtual_path=_VIRTUAL_INPUT_SEGMENT in sysfs_path + "/",
            capabilities=capabilities,
            issues=tuple(reader.issues),
        )

    def _read_capabilities(self, reader: _NodeReader, input_dir: Path) -> DeviceCapabilities:
        caps = input_dir / "capabilities"
        bits = self._word_bits
        return DeviceCapabilities.from_codes(
            event_types=reader.bitmap(caps / "ev", "capabilities/ev", bits, EV_MAX),
            axes=reader.bitmap(caps / "abs", "capabilities/abs", bits, ABS_MAX),
            buttons=reader.bitmap(caps / "key", "capabilities/key", bits, KEY_MAX),
            relative_axes=reader.bitmap(caps / "rel", "capabilities/rel", bits, REL_MAX),
            properties=reader.bitmap(input_dir / "properties", "properties", bits, INPUT_PROP_MAX),
        )

    def _read_usb_serial(
        self, reader: _NodeReader, input_dir: Path, vendor_id: int, product_id: int
    ) -> str | None:
        """Serial of the first USB ancestor with ``idVendor``/``idProduct`` (spec RF3)."""
        stop = self._root / "devices"
        for ancestor in input_dir.parents:
            if ancestor == stop or not ancestor.is_relative_to(stop):
                return None
            if not ((ancestor / "idVendor").is_file() and (ancestor / "idProduct").is_file()):
                continue
            usb_vendor = reader.hex_id(ancestor / "idVendor", "usb/idVendor")
            if usb_vendor != vendor_id:
                return None
            if reader.hex_id(ancestor / "idProduct", "usb/idProduct") != product_id:
                reader.issues.append(ReadIssue(ReadIssueKind.USB_PRODUCT_MISMATCH))
            return reader.text(ancestor / "serial", "usb/serial", required=False)
        return None


def _stripped(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _unreadable(
    event_node: str, input_token: str | None, issues: tuple[ReadIssue, ...]
) -> ObservedInputDevice:
    return ObservedInputDevice(
        event_node=event_node,
        input_token=input_token,
        sysfs_path=None,
        name=None,
        bustype=None,
        vendor_id=None,
        product_id=None,
        version=None,
        uniq=None,
        phys=None,
        usb_serial=None,
        driver=None,
        firmware=None,
        usb_interface_protocol=None,
        is_virtual_path=False,
        capabilities=None,
        issues=issues,
    )
