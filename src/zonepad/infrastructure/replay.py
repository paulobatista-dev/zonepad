from __future__ import annotations

import json
from pathlib import Path

from zonepad.domain.device import DeviceInfo
from zonepad.domain.input import RawFrame

from .fake import FakeBackend


def load_capture(path: Path) -> list[RawFrame]:
    frames: list[RawFrame] = []
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            try:
                data = json.loads(line)
                frames.append(
                    RawFrame(
                        data["device_id"],
                        int(data["timestamp_ns"]),
                        data.get("axes", {}),
                        data.get("triggers", {}),
                        frozenset(data.get("buttons", [])),
                    )
                )
            except (ValueError, KeyError, TypeError) as exc:
                raise ValueError(f"invalid capture line {line_number}") from exc
    return frames


class ReplayBackend(FakeBackend):
    @classmethod
    def from_file(cls, path: Path, device_id: str = "replay") -> ReplayBackend:
        frames = load_capture(path)
        info = DeviceInfo(device_id, "Replay capture")
        return cls([(info, frames)])
