"""Bridge the GUI application port to the existing infrastructure runner."""

from __future__ import annotations

from pathlib import Path
from typing import cast

from zonepad.application.measure import MeasureOutcome
from zonepad.application.ports import NormalizationConfig, WizardMeasureRunner
from zonepad.domain.metrics import MetricsConfig
from zonepad.infrastructure.mapping import DeviceMapping
from zonepad.infrastructure.measure_runner import MeasureRunner


class MeasureRunnerAdapter(WizardMeasureRunner):
    def __init__(self, runner: MeasureRunner) -> None:
        self._runner = runner

    def run(
        self,
        capture_path: Path,
        manifest_path: Path,
        mapping_path: Path,
        mapping: NormalizationConfig,
        config: MetricsConfig,
    ) -> MeasureOutcome:
        # The validated mapping also carries evdev codes; measurement reads its ranges.
        return self._runner.run(
            capture_path,
            manifest_path,
            mapping_path,
            cast(DeviceMapping, mapping),
            config,
        )
