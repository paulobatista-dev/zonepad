from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from zonepad import __version__
from zonepad.application.measure import (
    MeasureInputs,
    MeasureOptions,
    MeasureOutcome,
    execute_measure,
)
from zonepad.domain.metrics import MetricsConfig
from zonepad.infrastructure.capture_reader import read_strict_capture
from zonepad.infrastructure.files import sha256_file
from zonepad.infrastructure.manifest_reader import load_manifest
from zonepad.infrastructure.mapping import DeviceMapping


class MeasureRunner:
    def __init__(
        self,
        *,
        now: Callable[[], datetime],
        profile_id_factory: Callable[[], str],
    ) -> None:
        self._now = now
        self._profile_id_factory = profile_id_factory

    def run(
        self,
        capture_path: Path,
        manifest_path: Path,
        mapping_path: Path,
        mapping: DeviceMapping,
        config: MetricsConfig,
    ) -> MeasureOutcome:
        capture = read_strict_capture(capture_path)
        manifest = load_manifest(manifest_path)
        return execute_measure(
            MeasureInputs(
                capture.frames,
                capture.file_name,
                capture.sha256,
                manifest,
                mapping.axes,
                mapping.triggers,
                sha256_file(mapping_path.expanduser()),
                config,
            ),
            MeasureOptions(strict=True, save_profile=True),
            app_version=__version__,
            now=self._now,
            profile_id_factory=self._profile_id_factory,
        )
