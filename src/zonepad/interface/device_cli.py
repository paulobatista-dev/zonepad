"""Composition and presentation of ``zonepad devices`` and ``zonepad mapping`` (RF9, RF10).

Also hosts the device/mapping resolution shared by ``run`` and ``calibrate``
(RF8, RF11).  Messages are PT-BR; logs keep ``key=value`` fields in the message
and in ``extra`` because the default ``basicConfig`` format hides ``extra``.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from zonepad import __version__
from zonepad.application.discovery import (
    ResolvedDevice,
    discover_devices,
    fragile_group,
    resolve_device_reference,
)
from zonepad.application.hotplug import (
    DEFAULT_POLL_INTERVAL_S,
    MAX_POLL_INTERVAL_S,
    MIN_POLL_INTERVAL_S,
    PollingHotplugWatcher,
    follow,
)
from zonepad.application.mapping_draft import (
    ABSINFO_PERMISSION_DENIED,
    ABSINFO_UNSUPPORTED_PLATFORM,
    DraftOutcome,
    build_mapping_record,
    draft_mapping,
    resolve_connection,
)
from zonepad.application.mapping_resolution import (
    MappingSource,
    ResolvedMappingRef,
    resolve_mapping,
)
from zonepad.application.ports import (
    AbsInfoReader,
    Clock,
    DeviceBackend,
    DeviceMappingStore,
    FramePublisher,
    InputDeviceScanner,
    StoredMappingRef,
)
from zonepad.domain.catalog import Catalog
from zonepad.domain.discovery import (
    DiscoveredDevice,
    DiscoverySnapshot,
    HotplugChange,
    ObservedInputDevice,
)
from zonepad.domain.errors import (
    AmbiguousAxisAssignmentError,
    AmbiguousDeviceError,
    DeviceAccessDeniedError,
    DeviceNotFoundError,
    InvalidCatalogError,
    InvalidMappingError,
    InvalidSavedMappingError,
    MappingConflictError,
    MappingNotFoundError,
    UnsupportedPlatformError,
)
from zonepad.domain.identity import Connection, MappingKey, StableId, is_stable_id
from zonepad.domain.mapping_draft import InsufficientCapabilities
from zonepad.infrastructure.absinfo import EvdevAbsInfoReader
from zonepad.infrastructure.catalog import (
    LayeredDeviceCatalog,
    load_builtin_catalog,
    load_catalog_file,
)
from zonepad.infrastructure.clock import SystemClock
from zonepad.infrastructure.device_store import IDENTITY_FILE, JsonDeviceMappingStore
from zonepad.infrastructure.files import sha256_file, write_text_atomic
from zonepad.infrastructure.linux_input_policy import (
    BTN_TL2,
    BTN_TR2,
    abs_code_name,
    discovery_policies,
    draft_rules,
    key_code_name,
)
from zonepad.infrastructure.mapping import (
    DeviceMapping,
    dumps_device_mapping,
    load_device_mapping,
    loads_device_mapping,
)
from zonepad.infrastructure.sysfs import SysfsInputScanner

LOGGER = logging.getLogger("zonepad.cli")
DEFAULT_SYSFS_ROOT = Path("/sys")
DEFAULT_DEVICES_DIR = Path("~/.config/zonepad/devices")
DEV_INPUT = Path("/dev/input")
EVENT_NODE = re.compile(r"event[0-9]+", re.ASCII)
DEVICES_JSON_SCHEMA_VERSION = 1
_NAME_WIDTH = 32
_STATUS_LABELS = {
    "saved": "salvo",
    "provisional": "provisório",
    "edited": "editado",
    "invalid": "inválido",
}
_CONNECTION_LABELS = {"usb": "usb", "bluetooth": "bluetooth", "unknown": "desconhecida"}
_CONNECTION_CHOICES = {
    "usb": Connection.USB,
    "bluetooth": Connection.BLUETOOTH,
    "desconhecida": Connection.UNKNOWN,
}
_ACCESS_LABELS = {"ok": "ok", "permission_denied": "sem permissão", "missing": "ausente"}
_RAW_IDENTITY_FIELDS = ("uniq", "usb_serial", "phys")


class DiscoveryScanner(InputDeviceScanner, Protocol):
    def observe(self, event_node: str) -> ObservedInputDevice | None: ...


def verify_node_access(event_node: str) -> str:
    """Open ``/dev/input/<node>`` read-only and close it at once; never reads events."""
    try:
        fd = os.open(DEV_INPUT / event_node, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)
    except PermissionError:
        return "permission_denied"
    except FileNotFoundError:
        return "missing"
    os.close(fd)
    return "ok"


def tty_confirm(question: str) -> bool | None:
    """Ask on a TTY; ``None`` when there is no terminal to ask."""
    if not (sys.stdin.isatty() and sys.stderr.isatty()):
        return None
    print(f"{question} [s/N] ", end="", file=sys.stderr, flush=True)
    try:
        answer = sys.stdin.readline()
    except KeyboardInterrupt:
        return False
    return answer.strip().lower() in {"s", "sim", "y", "yes"}


def _default_scanner(root: Path) -> DiscoveryScanner:
    return SysfsInputScanner(root)


def _default_store(directory: Path) -> DeviceMappingStore:
    return JsonDeviceMappingStore(directory)


def _default_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class CliDependencies:
    """Injectable factories of the discovery commands and of ``run``/``calibrate``."""

    scanner: Callable[[Path], DiscoveryScanner] = _default_scanner
    absinfo_reader: Callable[[], AbsInfoReader] = EvdevAbsInfoReader
    verify_access: Callable[[str], str] = verify_node_access
    store: Callable[[Path], DeviceMappingStore] = _default_store
    builtin_catalog: Callable[[], Catalog] = load_builtin_catalog
    clock: Callable[[], Clock] = SystemClock
    now: Callable[[], datetime] = _default_now
    confirm: Callable[[str], bool | None] = tty_confirm
    # ``None`` keeps the evdev backend and the uinput publisher of ``cli.py``.
    backend: Callable[[DeviceMapping], DeviceBackend] | None = None
    publisher: Callable[[Path | None], FramePublisher] | None = None


class CliExit(Exception):
    """A user-facing failure with its exit code; the message is PT-BR."""

    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


# --- argparse -----------------------------------------------------------------


def _interval(value: str) -> float:
    try:
        result = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a number") from exc
    if not MIN_POLL_INTERVAL_S <= result <= MAX_POLL_INTERVAL_S:
        raise argparse.ArgumentTypeError(
            f"must be between {MIN_POLL_INTERVAL_S:g} and {MAX_POLL_INTERVAL_S:g} seconds"
        )
    return result


def add_discovery_paths(parser: argparse.ArgumentParser, *, sysfs: bool = True) -> None:
    if sysfs:
        parser.add_argument(
            "--sysfs-root",
            type=Path,
            default=DEFAULT_SYSFS_ROOT,
            help="ponto de montagem do sysfs (padrão: /sys)",
        )
    parser.add_argument(
        "--devices-dir",
        type=Path,
        default=DEFAULT_DEVICES_DIR,
        help="diretório dos mappings por dispositivo (padrão: ~/.config/zonepad/devices)",
    )


DEVICE_REFERENCE_HELP = (
    "ID estável (zonepad devices), nó evdev (eventN) ou base <bus>-<vid>-<pid> única"
)

_DEVICES_EPILOG = """\
códigos de saída:
  0  ao menos um gamepad encontrado
  2  argumentos inválidos (por exemplo --verify com --watch)
  3  nenhum gamepad, ou sysfs ausente ou inacessível
     (com --watch: só sysfs ausente ou inacessível)
  1  falha inesperada
  130 --watch interrompido (Ctrl+C)

só lê o sysfs; nenhum nó de /dev/input é aberto, exceto com --verify.
"""

_DRAFT_EPILOG = """\
códigos de saída:
  0  mapping provisório gerado
  2  referência ambígua, identidade frágil ou eixos ambíguos sem confirmação,
     mapping existente sem --force, --connection conflitante, --catalog inválido
     ou argumentos inválidos
  3  dispositivo ausente, ou sem permissão no nó e sem ranges de catálogo
  4  canais insuficientes, família sem suporte (por exemplo triggers digitais),
     ranges indisponíveis ou range inválido; nada é gravado
  1  falha inesperada

o draft abre só o nó resolvido (O_RDONLY) para EVIOCGABS, sem ler eventos;
--no-probe usa apenas o catálogo. Centro e repouso são provisórios até o calibrate.
"""

_SHOW_EPILOG = """\
códigos de saída:
  0  mapping salvo exibido
  2  referência ambígua, mapping não salvo ou salvo inválido
  3  dispositivo não descoberto
  1  falha inesperada
"""

_VALIDATE_EPILOG = """\
códigos de saída:
  0  mapping v1 válido
  2  mapping inválido (o primeiro erro com o campo)
  1  falha inesperada
"""


def add_device_commands(subcommands: Any) -> None:
    formatter = argparse.RawDescriptionHelpFormatter
    devices = subcommands.add_parser(
        "devices",
        help="lista gamepads com ID estável, a partir do sysfs",
        description=(
            "Lista os gamepads detectados no sysfs com ID estável, VID:PID, conexão, nó "
            "evdev e estado do mapping salvo. Recomendado em vez de 'zonepad list'."
        ),
        epilog=_DEVICES_EPILOG,
        formatter_class=formatter,
    )
    devices.add_argument("--json", action="store_true", help="uma linha JSON por dispositivo")
    devices.add_argument("--all", action="store_true", help="inclui não gamepads com o motivo")
    devices.add_argument(
        "--verify", action="store_true", help="abre e fecha cada gamepad para conferir acesso"
    )
    devices.add_argument(
        "--watch", action="store_true", help="acompanha conexões e remoções até Ctrl+C"
    )
    devices.add_argument(
        "--interval",
        type=_interval,
        default=DEFAULT_POLL_INTERVAL_S,
        help="intervalo do --watch em segundos, entre 0,25 e 5 (padrão: 1)",
    )
    add_discovery_paths(devices)

    mapping = subcommands.add_parser(
        "mapping",
        help="gera, mostra e valida mappings v1 por dispositivo",
        description="Gera um mapping v1 provisório por família, mostra o salvo e valida arquivos.",
        formatter_class=formatter,
    )
    actions = mapping.add_subparsers(dest="mapping_command", required=True)
    draft = actions.add_parser(
        "draft",
        help="gera um mapping v1 provisório para um dispositivo",
        description=(
            "Gera um mapping v1 a partir das capabilities, do absinfo do driver e do catálogo "
            "por família, e o grava em --devices-dir/<id>/mapping.json."
        ),
        epilog=_DRAFT_EPILOG,
        formatter_class=formatter,
    )
    draft.add_argument("--device", required=True, help=DEVICE_REFERENCE_HELP)
    draft.add_argument(
        "--connection",
        choices=tuple(_CONNECTION_CHOICES),
        help="substitui só uma conexão detectada como desconhecida",
    )
    target = draft.add_mutually_exclusive_group()
    target.add_argument("--out", type=Path, help="grava só o mapping neste caminho, sem sidecar")
    target.add_argument("--print", action="store_true", help="escreve o mapping em stdout")
    draft.add_argument("--force", action="store_true", help="sobrescreve um mapping salvo")
    draft.add_argument("--no-probe", action="store_true", help="não abre o nó; usa o catálogo")
    draft.add_argument(
        "--accept-fragile-id",
        action="store_true",
        help="aceita identidade por ocorrência ou duplicada (gêmeos)",
    )
    draft.add_argument(
        "--accept-axis-guess",
        action="store_true",
        help="aceita a atribuição sugerida quando os eixos são ambíguos",
    )
    draft.add_argument("--catalog", type=Path, help="catálogo do usuário (mesmo schema)")
    add_discovery_paths(draft)

    show = actions.add_parser(
        "show",
        help="mostra o mapping salvo de um dispositivo",
        description="Mostra chave, status, proveniência, caminho e o mapping salvo.",
        epilog=_SHOW_EPILOG,
        formatter_class=formatter,
    )
    show.add_argument("--device", required=True, help=DEVICE_REFERENCE_HELP)
    show.add_argument(
        "--json", action="store_true", help="objeto JSON com identity, mapping e status"
    )
    add_discovery_paths(show)

    validate = actions.add_parser(
        "validate",
        help="valida um arquivo de mapping v1",
        epilog=_VALIDATE_EPILOG,
        formatter_class=formatter,
    )
    validate.add_argument("path", type=Path, help="arquivo JSON de mapping v1")


# --- shared resolution (devices, mapping, run, calibrate) -----------------------


def discover(scanner: InputDeviceScanner, sysfs_root: Path) -> DiscoverySnapshot:
    try:
        return discover_devices(scanner, discovery_policies())
    except DeviceNotFoundError as exc:
        raise CliExit(
            3, f"erro: sysfs indisponível em {sysfs_root}: {exc}. Confira --sysfs-root."
        ) from exc


def resolve_reference(reference: str, snapshot: DiscoverySnapshot) -> ResolvedDevice:
    try:
        resolved = resolve_device_reference(reference, snapshot)
    except AmbiguousDeviceError as exc:
        raise CliExit(
            2,
            f"erro: a referência {reference} é ambígua; candidatos: {', '.join(exc.candidates)}. "
            "Use o ID estável completo.",
        ) from exc
    except DeviceNotFoundError as exc:
        node = snapshot.by_event_node(reference)
        detail = ""
        if node is not None:
            detail = f" ({node.verdict.device_class.value}: {', '.join(node.verdict.reasons)})"
        raise CliExit(
            3,
            f"erro: dispositivo {reference} não encontrado{detail}; rode `zonepad devices`.",
        ) from exc
    _log(
        logging.INFO,
        "device resolved",
        stable_id=resolved.identity.stable_id,
        node=resolved.event_node,
        reference=resolved.reference_kind,
    )
    return resolved


def resolve_session_mapping(
    resolved: ResolvedDevice,
    explicit_path: Path | None,
    store: DeviceMappingStore,
) -> tuple[DeviceMapping, Path, ResolvedMappingRef]:
    """RF8 rows 3-7 for an already validated explicit mapping (or none)."""
    stable_id = resolved.identity.stable_id
    try:
        ref = resolve_mapping(
            str(explicit_path) if explicit_path is not None else None,
            resolved.identity,
            store,
            sha256_of=lambda path: sha256_file(Path(path)),
        )
    except MappingNotFoundError as exc:
        raise CliExit(
            2,
            f"erro: nenhum mapping para {stable_id}; crie com "
            f"`zonepad mapping draft --device {stable_id}` ou passe --mapping.",
        ) from exc
    except InvalidSavedMappingError as exc:
        raise CliExit(
            2,
            f"erro: mapping salvo inválido: {exc.detail}; rode `zonepad mapping validate` ou "
            f"`zonepad mapping draft --device {stable_id} --force`.",
        ) from exc
    except MappingConflictError as exc:
        raise CliExit(2, f"erro: {exc}; gere outro draft ou passe --mapping.") from exc
    path = Path(ref.path)
    try:
        mapping = load_device_mapping(path)
    except InvalidMappingError as exc:
        raise CliExit(2, f"erro: [INVALID_MAPPING] {exc}") from exc
    _log(
        logging.INFO,
        "mapping resolved",
        source=ref.source.value,
        path=str(path),
        sha256=ref.sha256 or "-",
        provisional=_flag(ref.provisional),
    )
    saved = ref.overridden_saved
    if saved is not None:
        _log(
            logging.INFO,
            "explicit mapping overrides saved mapping",
            stable_id=stable_id,
            explicit_sha256=ref.sha256 or "-",
            saved_sha256=saved.mapping_sha256 or "-",
            same=_flag(ref.sha256 == saved.mapping_sha256),
        )
    for warning in ref.warnings:
        _log(logging.WARNING, warning, stable_id=stable_id, path=str(path))
    return mapping, path, ref


def check_catalog_ranges(
    resolved: ResolvedDevice,
    ref: ResolvedMappingRef,
    mapping: DeviceMapping,
    reader: AbsInfoReader,
) -> tuple[str, ...]:
    """RF8/P9: re-read absinfo only when the saved ranges came from the catalog."""
    if ref.source is not MappingSource.SAVED or ref.range_source != "catalog":
        return ()
    channels = {code: name for code, name in mapping.axis_codes.items()}
    channels.update(mapping.trigger_codes)
    try:
        absinfo = reader.read_absinfo(resolved.event_node, sorted(channels))
    except (DeviceAccessDeniedError, DeviceNotFoundError, UnsupportedPlatformError) as exc:
        # The session open right after reports access problems with its own message.
        LOGGER.debug("absinfo re-check skipped node=%s: %s", resolved.event_node, exc)
        return ()
    mismatches: list[str] = []
    for code, name in sorted(channels.items(), key=lambda item: item[1]):
        info = absinfo.get(code)
        if info is None:
            continue
        if name in mapping.axes:
            expected = (mapping.axes[name].minimum, mapping.axes[name].maximum)
        else:
            expected = (mapping.triggers[name].rest, mapping.triggers[name].maximum)
        if expected != (info.minimum, info.maximum):
            mismatches.append(f"absinfo_mismatch:{name}")
            _log(
                logging.WARNING,
                f"absinfo_mismatch:{name}",
                stable_id=resolved.identity.stable_id,
                expected=f"{expected[0]}..{expected[1]}",
                actual=f"{info.minimum}..{info.maximum}",
            )
    return tuple(mismatches)


def verify_after_open(scanner: DiscoveryScanner, resolved: ResolvedDevice) -> None:
    """Compare the ``inputM`` token of the opened node with the discovered one."""
    expected = resolved.device.observed.input_token
    current = scanner.observe(resolved.event_node)
    token = current.input_token if current is not None else None
    if token != expected:
        raise CliExit(
            3,
            f"erro: o nó {resolved.event_node} mudou entre a descoberta e a abertura "
            f"(esperado {expected}, atual {token or 'ausente'}); rode `zonepad devices` "
            "e tente de novo.",
        )


def gamepad_label(device: DiscoveredDevice) -> str:
    return f"{device.observed.name or device.event_node} ({device.stable_id}, {device.event_node})"


def mapping_origin_label(ref: ResolvedMappingRef) -> str:
    if ref.source is MappingSource.EXPLICIT:
        return f"--mapping {ref.path}"
    state = _STATUS_LABELS.get(ref.status or "", ref.status or "")
    return f"mapping salvo ({state}) {ref.path}"


def connection_label(connection: Connection) -> str:
    return _CONNECTION_LABELS[connection.value]


def permission_message(event_node: str, stable_id: str) -> str:
    node = DEV_INPUT / event_node
    return (
        f"Sem permissão de leitura em {node} (controle `{stable_id}`).\n"
        f"1. Verifique com `ls -l {node}` e `getfacl {node}`. Numa sessão gráfica local, "
        "o acesso costuma vir por ACL (uaccess).\n"
        '2. Alternativa: `sudo usermod -aG input "$USER"` e reiniciar a sessão. Impacto: o '
        "grupo `input` dá leitura de todos os dispositivos de entrada, inclusive o teclado. "
        'Para desfazer: `sudo gpasswd -d "$USER" input` e reiniciar a sessão.\n'
        "Enquanto isso, `zonepad mapping draft --no-probe` usa só o catálogo (famílias "
        "conhecidas)."
    )


def _log(level: int, event: str, **fields: str) -> None:
    text = " ".join(f"{key}={value}" for key, value in fields.items())
    LOGGER.log(level, f"{event} {text}".rstrip(), extra=dict(fields))


def _flag(value: bool | None) -> str:
    return "unknown" if value is None else str(value).lower()


def _err(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


# --- zonepad devices ------------------------------------------------------------


def run_devices(args: argparse.Namespace, deps: CliDependencies) -> int:
    if args.verify and args.watch:
        _err("erro: --verify não pode ser combinado com --watch")
        return 2
    scanner = deps.scanner(args.sysfs_root)
    store = deps.store(args.devices_dir)
    try:
        snapshot = discover(scanner, args.sysfs_root)
        if args.watch:
            return _watch(args, deps, scanner, store, snapshot)
        _print_devices(args, deps, store, snapshot)
    except CliExit as exc:
        _err(exc.message)
        return exc.code
    if not snapshot.gamepads:
        _err("erro: nenhum gamepad encontrado; conecte o controle ou rode com --all.")
        return 3
    return 0


def _print_devices(
    args: argparse.Namespace,
    deps: CliDependencies,
    store: DeviceMappingStore,
    snapshot: DiscoverySnapshot,
) -> None:
    devices = snapshot.devices if args.all else snapshot.gamepads
    rows = [_device_row(device, store, deps if args.verify else None) for device in devices]
    if args.json:
        for row in rows:
            print(json.dumps(row, ensure_ascii=False, sort_keys=True))
        return
    _print_table(rows, show_reason=args.all, show_access=args.verify)
    for device in devices:
        for line in _identity_warnings(device):
            print(line)


def _device_row(
    device: DiscoveredDevice, store: DeviceMappingStore, deps: CliDependencies | None
) -> dict[str, Any]:
    observed = device.observed
    identity = device.identity
    policy = discovery_policies().identity_policy
    bus = connection = None
    if identity is not None:
        bus = identity.base.split("-")[0]
        connection = identity.connection.value
    elif observed.bustype is not None:
        bus = policy.bus_token(observed.bustype)
        connection = policy.connection(observed.bustype).value
    warnings = list(device.verdict.warnings)
    if identity is not None:
        warnings.extend(w for w in identity.warnings if w not in warnings)
    row: dict[str, Any] = {
        "schema_version": DEVICES_JSON_SCHEMA_VERSION,
        "id": identity.stable_id if identity else None,
        "kind": device.verdict.device_class.value,
        "gamepad_kind": device.verdict.gamepad_kind.value if device.verdict.gamepad_kind else None,
        "name": observed.name,
        "vid": _hex4(observed.vendor_id),
        "pid": _hex4(observed.product_id),
        "version": _hex4(observed.version),
        "bus": bus,
        "connection": connection,
        "node": observed.event_node,
        "mapping": _mapping_status(store, identity.stable_id) if identity else None,
        "fragile_id": identity.fragile if identity else False,
        "reasons": list(device.verdict.reasons),
        "warnings": warnings,
    }
    if deps is not None:
        row["access"] = deps.verify_access(observed.event_node) if device.is_selectable else None
    return row


def _mapping_status(store: DeviceMappingStore, stable_id: StableId) -> str:
    ref = store.find(MappingKey(stable_id, Connection.UNKNOWN))
    return ref.status if ref is not None else "absent"


def _print_table(rows: Sequence[dict[str, Any]], *, show_reason: bool, show_access: bool) -> None:
    header = ["ID", "NOME", "VID:PID", "CONEXÃO", "NÓ", "MAPPING"]
    if show_access:
        header.append("ACESSO")
    if show_reason:
        header.append("MOTIVO")
    table = [header]
    for row in rows:
        vid_pid = f"{row['vid'][2:]}:{row['pid'][2:]}" if row["vid"] and row["pid"] else "-"
        status = row["mapping"]
        line = [
            row["id"] or "-",
            _truncate(row["name"] or "-"),
            vid_pid,
            _CONNECTION_LABELS.get(row["connection"] or "", "-"),
            row["node"],
            _STATUS_LABELS.get(status, "ausente") if status else "-",
        ]
        if show_access:
            line.append(_ACCESS_LABELS.get(row.get("access") or "", "-"))
        if show_reason:
            line.append(", ".join(row["reasons"]) or "-")
        table.append(line)
    widths = [max(len(line[index]) for line in table) for index in range(len(header))]
    for line in table:
        print(
            "  ".join(cell.ljust(width) for cell, width in zip(line, widths, strict=True)).rstrip()
        )


def _identity_warnings(device: DiscoveredDevice) -> list[str]:
    identity = device.identity
    if identity is None:
        return []
    lines = []
    if identity.fragile:
        lines.append(
            f"aviso: {identity.stable_id}: identidade frágil ({', '.join(identity.warnings)}); "
            "pode trocar entre controles idênticos; gravar mapping exige --accept-fragile-id."
        )
    elif "identity_bound_to_port" in identity.warnings:
        lines.append(
            f"aviso: {identity.stable_id}: identidade presa à porta USB; muda se trocar de porta."
        )
    return lines


def _watch(
    args: argparse.Namespace,
    deps: CliDependencies,
    scanner: DiscoveryScanner,
    store: DeviceMappingStore,
    snapshot: DiscoverySnapshot,
) -> int:
    clock = deps.clock()
    watcher = PollingHotplugWatcher(scanner, discovery_policies(), clock, args.interval)
    try:
        current = watcher.snapshot()
        _print_devices(args, deps, store, current)
        sys.stdout.flush()
        for change in follow(watcher, clock, args.interval, lambda: False):
            _print_change(args, store, change)
            sys.stdout.flush()
    except KeyboardInterrupt:
        return 130
    except DeviceNotFoundError as exc:
        _err(f"erro: sysfs indisponível em {args.sysfs_root}: {exc}")
        return 3
    return 0


def _print_change(
    args: argparse.Namespace, store: DeviceMappingStore, change: HotplugChange
) -> None:
    for kind, devices in (("removed", change.removed), ("added", change.added)):
        for device in devices:
            if not args.all and not device.is_selectable:
                continue
            row = _device_row(device, store, None)
            if args.json:
                print(json.dumps({"event": kind, **row}, ensure_ascii=False, sort_keys=True))
            else:
                label = "conectado" if kind == "added" else "removido"
                print(f"{label}: {row['id'] or '-'}  {row['name'] or '-'}  ({row['node']})")
    for old_id, new_id in change.renamed:
        if args.json:
            print(
                json.dumps({"event": "renamed", "old_id": old_id, "new_id": new_id}, sort_keys=True)
            )
        else:
            print(f"renomeado: {old_id} -> {new_id}")


def _hex4(value: int | None) -> str | None:
    return None if value is None else f"0x{value:04x}"


def _truncate(text: str) -> str:
    return text if len(text) <= _NAME_WIDTH else text[: _NAME_WIDTH - 1] + "…"


# --- zonepad mapping ------------------------------------------------------------


def run_mapping(args: argparse.Namespace, deps: CliDependencies) -> int:
    try:
        if args.mapping_command == "draft":
            return _draft(args, deps)
        if args.mapping_command == "show":
            return _show(args, deps)
        return _validate(args)
    except CliExit as exc:
        _err(exc.message)
        return exc.code


def _draft(args: argparse.Namespace, deps: CliDependencies) -> int:
    try:
        user_catalog = load_catalog_file(args.catalog) if args.catalog else None
        catalog = LayeredDeviceCatalog(deps.builtin_catalog(), user_catalog)
    except InvalidCatalogError as exc:
        raise CliExit(2, f"erro: [INVALID_CATALOG] catálogo inválido: {exc}") from exc
    scanner = deps.scanner(args.sysfs_root)
    snapshot = discover(scanner, args.sysfs_root)
    resolved = resolve_reference(args.device, snapshot)
    stable_id = resolved.identity.stable_id
    override = _CONNECTION_CHOICES[args.connection] if args.connection else None
    try:
        resolve_connection(resolved.identity.connection, override)
    except MappingConflictError as exc:
        raise CliExit(
            2,
            f"erro: --connection {args.connection} conflita com a conexão detectada "
            f"{connection_label(resolved.identity.connection)}.",
        ) from exc
    if resolved.identity.fragile and not args.accept_fragile_id:
        _confirm_fragile(deps, snapshot, resolved)
    store = None if args.print or args.out else deps.store(args.devices_dir)
    if store is not None and not args.force:
        existing = store.find(MappingKey(stable_id, Connection.UNKNOWN))
        if existing is not None:
            raise CliExit(
                2,
                f"erro: já existe um mapping para {stable_id} em {existing.mapping_path}; "
                "use --force para sobrescrever.",
            )
    reader = None if args.no_probe else deps.absinfo_reader()
    try:
        result = draft_mapping(
            resolved,
            absinfo_reader=reader,
            catalog=catalog,
            rules=draft_rules(),
            accept_axis_guess=args.accept_axis_guess,
        )
    except AmbiguousAxisAssignmentError as exc:
        raise CliExit(2, _ambiguous_axes_message(exc.candidates)) from exc
    except DeviceAccessDeniedError as exc:
        raise CliExit(3, "erro: " + permission_message(exc.event_node, stable_id)) from exc
    except DeviceNotFoundError as exc:
        raise CliExit(3, f"erro: dispositivo {args.device} não encontrado: {exc}") from exc
    if isinstance(result, InsufficientCapabilities):
        raise CliExit(4, _insufficient_message(result, no_probe=args.no_probe))
    text = dumps_device_mapping(result.draft)
    loads_device_mapping(text)
    _print_draft_warnings(result, resolved)
    if args.print:
        sys.stdout.write(text)
        _print_provenance(result, resolved)
        return 0
    if args.out is not None:
        write_text_atomic(args.out, text)
        _err(
            "aviso: --out grava só o mapping, sem identidade; `zonepad run` não vai resolvê-lo "
            "sozinho. Use --mapping com esse arquivo."
        )
        print(f"mapping provisório gravado em {args.out}")
        return 0
    if store is None:  # pragma: no cover - guarded above
        raise CliExit(1, "erro: store indisponível")
    record = build_mapping_record(
        resolved,
        result,
        text,
        connection_override=override,
        created_at=deps.now().astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        app_version=__version__,
    )
    try:
        saved = store.save(record, overwrite=args.force)
    except MappingConflictError as exc:
        raise CliExit(2, f"erro: {exc}; use --force para sobrescrever.") from exc
    print(
        f"mapping provisório gravado em {saved.mapping_path}; próximo passo: "
        f"zonepad calibrate --device {stable_id}"
    )
    return 0


def _confirm_fragile(
    deps: CliDependencies, snapshot: DiscoverySnapshot, resolved: ResolvedDevice
) -> None:
    twins = fragile_group(snapshot, resolved.identity) or (resolved.identity.stable_id,)
    question = (
        f"A identidade {resolved.identity.stable_id} é frágil (gêmeos: {', '.join(twins)}); "
        "ela pode trocar entre controles idênticos. Gravar mesmo assim?"
    )
    answer = deps.confirm(question)
    if answer:
        return
    raise CliExit(
        2,
        f"erro: identidade frágil {resolved.identity.stable_id}; gêmeos: {', '.join(twins)}. "
        "Confirme com --accept-fragile-id.",
    )


def _ambiguous_axes_message(candidates: Sequence[str]) -> str:
    lines = ["erro: atribuição de eixos ambígua; candidatos:"]
    lines.extend(f"  {_human_candidate(candidate)}" for candidate in candidates)
    lines.append(
        "confira com o controle e repita com --accept-axis-guess para gravar a atribuição "
        "sugerida (primeira opção de cada canal)."
    )
    return "\n".join(lines)


def _human_candidate(candidate: str) -> str:
    parts = []
    for item in candidate.split(","):
        channel, _, code = item.partition("=")
        parts.append(f"{channel}={abs_code_name(int(code))}({code})" if code.isdecimal() else item)
    return ", ".join(parts)


def _insufficient_message(result: InsufficientCapabilities, *, no_probe: bool) -> str:
    axes = ", ".join(f"{abs_code_name(code)}({code})" for code in result.detected_axes) or "nenhum"
    digital = [
        key_code_name(code) for code in (BTN_TL2, BTN_TR2) if code in result.detected_buttons
    ]
    lines = [
        f"erro: capabilities insuficientes para um mapping v1 ({result.code}).",
        f"  canais ausentes: {', '.join(result.missing_channels) or '-'}",
        f"  eixos ABS detectados: {axes}",
    ]
    if digital:
        lines.append(f"  gatilhos digitais detectados: {', '.join(digital)}")
    if result.reason == "digital_triggers_only":
        lines.append(
            "os gatilhos deste controle são digitais; o mapping v1 exige gatilhos analógicos."
        )
    elif result.reason == "ranges_unavailable":
        hint = (
            "rode sem --no-probe para ler o absinfo do nó"
            if no_probe
            else ("o absinfo do nó não estava disponível")
        )
        lines.append(f"sem ranges para esses canais: {hint}, ou passe --catalog com known_ranges.")
    lines.append("nada foi gravado.")
    return "\n".join(lines)


def _print_draft_warnings(outcome: DraftOutcome, resolved: ResolvedDevice) -> None:
    warnings = outcome.draft.provenance.warnings
    _err(
        "aviso: mapping provisório: centro e repouso são declarados, não medidos; "
        f"rode `zonepad calibrate --device {resolved.identity.stable_id}`."
    )
    if ABSINFO_PERMISSION_DENIED in warnings:
        _err(
            f"aviso: sem permissão em {DEV_INPUT / resolved.event_node}; ranges vieram do "
            "catálogo da família."
        )
    if ABSINFO_UNSUPPORTED_PLATFORM in warnings:
        _err(
            "aviso: leitura de absinfo (EVIOCGABS) não suportada nesta arquitetura; ranges "
            "vieram do catálogo da família."
        )
    for warning in warnings:
        if warning not in {
            "provisional_center",
            ABSINFO_PERMISSION_DENIED,
            ABSINFO_UNSUPPORTED_PLATFORM,
        }:
            _err(f"aviso: {warning}")


def _print_provenance(outcome: DraftOutcome, resolved: ResolvedDevice) -> None:
    provenance = outcome.draft.provenance
    _err(f"id: {resolved.identity.stable_id}")
    _err(
        f"catálogo: {provenance.catalog_entry_id or 'heurística genérica'} "
        f"({provenance.catalog_source}, v{provenance.catalog_version})"
    )
    sources = ", ".join(f"{name}={src.value}" for name, src in outcome.draft.range_sources.items())
    _err(f"ranges: {sources}")


def _show(args: argparse.Namespace, deps: CliDependencies) -> int:
    reference = args.device
    store = deps.store(args.devices_dir)
    if is_stable_id(reference):
        stable_id = StableId(reference)
    else:
        scanner = deps.scanner(args.sysfs_root)
        stable_id = resolve_reference(
            reference, discover(scanner, args.sysfs_root)
        ).identity.stable_id
    ref = store.find(MappingKey(stable_id, Connection.UNKNOWN))
    if ref is None:
        raise CliExit(
            2,
            f"erro: nenhum mapping salvo para {stable_id}; crie com "
            f"`zonepad mapping draft --device {stable_id}`.",
        )
    identity = _identity_document(ref)
    mapping_text = _read_optional(Path(ref.mapping_path))
    if args.json:
        payload = {
            "identity": identity,
            "mapping": _json_or_none(mapping_text),
            "status": ref.status,
        }
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        _print_show(ref, identity, mapping_text)
    if ref.status == "invalid":
        _err(
            f"erro: mapping salvo inválido: {ref.detail}; rode `zonepad mapping validate "
            f"{ref.mapping_path}` ou `zonepad mapping draft --device {stable_id} --force`."
        )
        return 2
    if ref.status == "edited":
        _err("aviso: mapping.json foi editado depois do draft (sha256 diverge do sidecar).")
    return 0


def _identity_document(ref: StoredMappingRef) -> dict[str, Any] | None:
    """``identity.json`` without the raw uniq/serial/phys (never shown or exported)."""
    document = _json_or_none(_read_optional(Path(ref.mapping_path).parent / IDENTITY_FILE))
    if not isinstance(document, dict):
        return None
    hardware = document.get("hardware")
    if isinstance(hardware, dict):
        for name in _RAW_IDENTITY_FIELDS:
            hardware.pop(name, None)
    return document


def _print_show(ref: StoredMappingRef, identity: dict[str, Any] | None, text: str | None) -> None:
    print(f"ID: {ref.key.stable_id}")
    connection = connection_label(ref.key.connection)
    source = identity.get("connection_source") if identity else None
    print(f"Conexão: {connection}" + (f" ({source})" if source else ""))
    print(f"Status: {_STATUS_LABELS.get(ref.status, ref.status)}")
    print(f"Caminho: {ref.mapping_path}")
    draft = identity.get("draft") if identity else None
    if isinstance(draft, dict):
        print(
            f"Catálogo: {draft.get('catalog_entry_id') or 'heurística genérica'} "
            f"({draft.get('catalog_source')}, v{draft.get('catalog_version')})"
        )
        sources = draft.get("range_sources")
        if isinstance(sources, dict):
            print("Ranges: " + ", ".join(f"{k}={v}" for k, v in sources.items()))
        warnings = draft.get("warnings")
        if warnings:
            print("Avisos: " + ", ".join(str(w) for w in warnings))
    if ref.detail:
        print(f"Detalhe: {ref.detail}")
    if text is not None:
        print("--- mapping.json ---")
        sys.stdout.write(text if text.endswith("\n") else text + "\n")


def _validate(args: argparse.Namespace) -> int:
    try:
        mapping = load_device_mapping(args.path)
    except InvalidMappingError as exc:
        raise CliExit(2, f"erro: [INVALID_MAPPING] {exc}") from exc
    channels = ", ".join([*sorted(mapping.axes, key=_channel_order), *sorted(mapping.triggers)])
    print(f"mapping válido: {channels}; {len(mapping.button_codes)} botões")
    return 0


def _channel_order(name: str) -> int:
    return ("lx", "ly", "rx", "ry").index(name)


def _read_optional(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except OSError, UnicodeError:
        return None


def _json_or_none(text: str | None) -> Any:
    if text is None:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None
