from __future__ import annotations

import argparse
import json
import logging
import math
from pathlib import Path

from zonepad.application.runtime import build_runtime
from zonepad.domain.errors import (
    DeviceDisconnectedError,
    DeviceNotFoundError,
    InvalidMappingError,
    InvalidProfileError,
    UnsupportedPlatformError,
)
from zonepad.infrastructure.evdev import LinuxEvdevBackend
from zonepad.infrastructure.json_profile_store import JsonProfileStore
from zonepad.infrastructure.mapping import load_device_mapping
from zonepad.infrastructure.replay import load_capture
from zonepad.infrastructure.uinput import LinuxUinputPublisher


def _positive_float(value: str) -> float:
    try:
        result = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a number") from exc
    if not math.isfinite(result) or result <= 0:
        raise argparse.ArgumentTypeError("must be a finite value greater than zero")
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="zonepad", description="Calibração de controles no Linux")
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("list", help="lista controles evdev disponíveis")
    replay = subcommands.add_parser("replay", help="inspeciona uma captura JSONL")
    replay.add_argument("capture", type=Path)
    profiles = subcommands.add_parser("profiles", help="lista perfis JSON")
    profiles.add_argument("--directory", type=Path, default=Path("~/.config/zonepad/profiles"))
    run = subcommands.add_parser("run", help="aplica um perfil a um controle virtual uinput")
    run.add_argument("--device", required=True, help="nome do nó evdev, por exemplo event3")
    run.add_argument("--profile", required=True, help="UUID do perfil salvo")
    run.add_argument("--profiles-dir", type=Path, default=Path("~/.config/zonepad/profiles"))
    run.add_argument("--mapping", type=Path, help="JSON v1 com códigos e ranges medidos")
    run.add_argument("--uinput", type=Path, help="nó uinput; padrão: /dev/uinput")
    run.add_argument(
        "--timeout", type=_positive_float, default=0.05, help="timeout de leitura em segundos"
    )
    run.add_argument("--duration", type=_positive_float, help="duração máxima em segundos")
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO)
    args = build_parser().parse_args(argv)
    if args.command == "list":
        for device in LinuxEvdevBackend().list_devices():
            print(
                json.dumps(
                    {
                        "id": device.device_id,
                        "name": device.name,
                        "capabilities": sorted(device.capabilities),
                    }
                )
            )
        return 0
    if args.command == "replay":
        frames = load_capture(args.capture)
        print(
            json.dumps(
                {"frames": len(frames), "device_id": frames[0].device_id if frames else None}
            )
        )
        return 0
    if args.command == "profiles":
        store = JsonProfileStore(args.directory)
        for profile_id in store.list_profiles():
            print(profile_id)
        return 0
    if args.command == "run":
        return _run(args)
    return 2


def _run(args: argparse.Namespace) -> int:
    if args.mapping is None:
        print(
            "erro: --mapping é necessário para fornecer ranges medidos de eixos e triggers",
            flush=True,
        )
        return 2
    try:
        mapping = load_device_mapping(args.mapping)
        store = JsonProfileStore(args.profiles_dir)
        # Validar o perfil antes de registrar um controle virtual.
        store.load(args.profile)
        backend = LinuxEvdevBackend(mapping=mapping)
        try:
            publisher = LinuxUinputPublisher(args.uinput)
        except PermissionError:
            print(
                "erro: sem permissão para /dev/uinput; configure uma regra udev "
                "ou o grupo adequado",
                flush=True,
            )
            return 3
        runtime = build_runtime(backend, store, publisher, args.device, args.profile, args.timeout)
        logging.info(
            "runtime started",
            extra={
                "device_id": args.device,
                "profile_id": args.profile,
                "duration_s": args.duration,
            },
        )
        runtime.run(args.timeout, args.duration)
    except KeyboardInterrupt:
        logging.info("runtime interrupted")
        return 0
    except DeviceDisconnectedError:
        print("controle desconectado; encerramento concluído", flush=True)
        return 0
    except PermissionError:
        print(
            "erro: sem permissão para abrir /dev/input ou o diretório de perfis; "
            "confira o grupo adequado",
            flush=True,
        )
        return 3
    except (OSError, RuntimeError) as exc:
        print(f"erro: não foi possível executar o runtime: {exc}", flush=True)
        return 2
    except (
        InvalidProfileError,
        InvalidMappingError,
        DeviceNotFoundError,
        FileNotFoundError,
    ) as exc:
        print(f"erro: {exc}", flush=True)
        return 2
    except UnsupportedPlatformError as exc:
        print(f"erro: {exc}", flush=True)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
