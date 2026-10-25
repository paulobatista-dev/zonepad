from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from zonepad.infrastructure.evdev import LinuxEvdevBackend
from zonepad.infrastructure.json_profile_store import JsonProfileStore
from zonepad.infrastructure.replay import load_capture


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="zonepad", description="Calibração de controles no Linux")
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("list", help="lista controles evdev disponíveis")
    replay = subcommands.add_parser("replay", help="inspeciona uma captura JSONL")
    replay.add_argument("capture", type=Path)
    profiles = subcommands.add_parser("profiles", help="lista perfis JSON")
    profiles.add_argument("--directory", type=Path, default=Path("~/.config/zonepad/profiles"))
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
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
