from __future__ import annotations

import itertools
import time
from dataclasses import replace
from pathlib import Path

import pytest
from discovery_fakes import FakeClock, ScriptedScanner
from sysfs_builder import build_sysfs, dualsense_bt_nodes, twin_generic_pads, xbox_one_s_usb

from zonepad.application.hotplug import PollingHotplugWatcher, follow
from zonepad.domain.discovery import DeviceClass, ObservedInputDevice
from zonepad.infrastructure.linux_input_policy import discovery_policies
from zonepad.infrastructure.sysfs import SysfsInputScanner

POLICIES = discovery_policies()


def _scan(tmp_path: Path, name: str, nodes) -> tuple[ObservedInputDevice, ...]:
    root = tmp_path / name
    build_sysfs(root, nodes)
    return SysfsInputScanner(root).scan()


def test_poll_reports_added_and_removed_with_ids(tmp_path: Path) -> None:
    empty: tuple[ObservedInputDevice, ...] = ()
    xbox = _scan(tmp_path, "xbox", [xbox_one_s_usb()])
    clock = FakeClock(now=7)
    watcher = PollingHotplugWatcher(ScriptedScanner([empty, xbox, empty]), POLICIES, clock)

    assert watcher.snapshot().devices == ()
    added = watcher.poll()
    removed = watcher.poll()

    assert [device.event_node for device in added.added] == ["event3"]
    assert added.added[0].stable_id is not None
    assert added.observed_at_ns == 7
    assert [device.stable_id for device in removed.removed] == [added.added[0].stable_id]
    assert removed.added == ()


def test_reconnection_with_another_input_token_is_removed_then_added(tmp_path: Path) -> None:
    first = _scan(tmp_path, "a", [xbox_one_s_usb()])
    original = xbox_one_s_usb()
    reconnected_node = replace(original, input_path=original.input_path[:-2] + "77")
    second = _scan(tmp_path, "b", [reconnected_node])
    watcher = PollingHotplugWatcher(ScriptedScanner([first, second]), POLICIES, FakeClock())
    watcher.snapshot()

    change = watcher.poll()

    assert [d.observed.input_token for d in change.removed] == ["input10"]
    assert [d.observed.input_token for d in change.added] == ["input77"]
    assert change.removed[0].stable_id == change.added[0].stable_id


def test_twin_leaving_renames_the_remaining_twin(tmp_path: Path) -> None:
    first, second = twin_generic_pads()
    both = _scan(tmp_path, "both", [first, second])
    only_second = _scan(tmp_path, "one", [second])
    watcher = PollingHotplugWatcher(ScriptedScanner([both, only_second]), POLICIES, FakeClock())
    watcher.snapshot()

    change = watcher.poll()

    assert [d.observed.input_token for d in change.removed] == ["input60"]
    assert change.renamed == (("usb-1209-0009-n2", "usb-1209-0009-n1"),)


def test_auxiliary_nodes_are_tagged_so_the_default_output_can_skip_them(tmp_path: Path) -> None:
    dualsense = _scan(tmp_path, "ds", dualsense_bt_nodes())
    watcher = PollingHotplugWatcher(ScriptedScanner([(), dualsense]), POLICIES, FakeClock())
    watcher.snapshot()

    change = watcher.poll()

    gamepads = [d.event_node for d in change.added if d.verdict.device_class is DeviceClass.GAMEPAD]
    assert gamepads == ["event21"]
    assert len(change.added) == 3


def test_follow_sleeps_through_the_clock_and_yields_only_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    xbox = _scan(tmp_path, "xbox", [xbox_one_s_usb()])
    clock = FakeClock()
    scanner = ScriptedScanner([(), (), xbox, xbox, ()])
    watcher = PollingHotplugWatcher(scanner, POLICIES, clock, interval_s=0.5)
    watcher.snapshot()

    def no_real_sleep(seconds: float) -> None:
        raise AssertionError("follow must not call time.sleep")

    monkeypatch.setattr(time, "sleep", no_real_sleep)
    changes = list(itertools.islice(follow(watcher, clock, 0.5, lambda: scanner.calls >= 5), 5))

    assert [(len(c.added), len(c.removed)) for c in changes] == [(1, 0), (0, 1)]
    assert clock.sleeps == [0.5, 0.5, 0.5, 0.5]
    assert clock.now == 2_000_000_000


def test_follow_stops_before_polling_when_asked() -> None:
    clock = FakeClock()
    scanner = ScriptedScanner([()])
    watcher = PollingHotplugWatcher(scanner, POLICIES, clock)

    assert list(follow(watcher, clock, 1.0, lambda: True)) == []
    assert scanner.calls == 0


@pytest.mark.parametrize("interval", [0.1, 0.249, 5.01])
def test_interval_is_validated(interval: float) -> None:
    with pytest.raises(ValueError):
        PollingHotplugWatcher(ScriptedScanner([()]), POLICIES, FakeClock(), interval_s=interval)
