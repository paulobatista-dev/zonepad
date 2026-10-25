from __future__ import annotations

import json
from pathlib import Path

import pytest
from cli_support import json_lines, workspace
from conftest import IoGuardFactory
from discovery_fakes import FakeClock, ScriptedScanner
from sysfs_builder import (
    XBOX_ONE_ABSINFO,
    build_sysfs,
    dualsense_bt_nodes,
    keyboard,
    twin_generic_pads,
    xbox_one_s_usb,
    zonapad_virtual,
)

from zonepad.domain.discovery import ObservedInputDevice
from zonepad.infrastructure.sysfs import SysfsInputScanner
from zonepad.interface import cli

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "sysfs"
XBOX_ID = "usb-045e-02ea-se73b07be4c"


def test_default_table_lists_only_gamepads(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], forbid_io_outside: IoGuardFactory
) -> None:
    ws = workspace(
        tmp_path, [xbox_one_s_usb(), keyboard(), *dualsense_bt_nodes(), zonapad_virtual()]
    )

    with forbid_io_outside(tmp_path):
        code = cli.main(["devices", *ws.paths()], dependencies=ws.deps())

    out = capsys.readouterr().out.splitlines()
    assert code == 0
    assert out[0].split() == ["ID", "NOME", "VID:PID", "CONEXÃO", "NÓ", "MAPPING"]
    assert len(out) == 3
    assert out[1].startswith("bt-054c-0ce6-u")
    assert "bluetooth" in out[1] and "event21" in out[1]
    assert out[2].startswith(XBOX_ID) and "045e:02ea" in out[2] and "ausente" in out[2]
    assert not any("ZonaPad" in line or "keyboard" in line for line in out)


def test_all_shows_every_class_with_reason(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ws = workspace(tmp_path, [xbox_one_s_usb(), keyboard(), zonapad_virtual()])

    code = cli.main(["devices", "--all", "--json", *ws.paths()], dependencies=ws.deps())

    rows = json_lines(capsys.readouterr().out)
    assert code == 0
    assert [(row["node"], row["kind"], row["reasons"]) for row in rows] == [
        ("event3", "gamepad", []),
        ("event1", "keyboard", ["not_a_gamepad:keyboard"]),
        ("event30", "virtual", ["virtual:zonapad"]),
    ]
    assert rows[1]["id"] is None and rows[1]["mapping"] is None


def test_all_table_has_reason_column_and_dash_ids(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ws = workspace(tmp_path, [xbox_one_s_usb(), zonapad_virtual()])

    cli.main(["devices", "--all", *ws.paths()], dependencies=ws.deps())

    lines = capsys.readouterr().out.splitlines()
    assert lines[0].split()[-1] == "MOTIVO"
    assert lines[2].startswith("-") and lines[2].endswith("virtual:zonapad")


def test_golden_json_line_for_the_versioned_fixture(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], forbid_io_outside: IoGuardFactory
) -> None:
    ws = workspace(tmp_path, [])

    with forbid_io_outside(FIXTURE_ROOT):
        code = cli.main(
            ["devices", "--json", "--sysfs-root", str(FIXTURE_ROOT), "--devices-dir", "absent"],
            dependencies=ws.deps(store=lambda directory: _EmptyStore()),
        )

    assert code == 0
    assert capsys.readouterr().out == (
        '{"bus": "usb", "connection": "usb", "fragile_id": false, "gamepad_kind": "gamepad", '
        f'"id": "{XBOX_ID}", "kind": "gamepad", "mapping": "absent", '
        '"name": "Microsoft X-Box One S pad", "node": "event3", "pid": "0x02ea", '
        '"reasons": [], "schema_version": 1, "version": "0x0408", "vid": "0x045e", '
        '"warnings": []}\n'
    )


class _EmptyStore:
    def find(self, key):
        return None

    def save(self, record, *, overwrite):
        raise AssertionError("devices never writes")

    def entries(self):
        return ()


def test_json_never_contains_raw_serial_or_mac(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ws = workspace(tmp_path, [xbox_one_s_usb(), *dualsense_bt_nodes()])

    cli.main(["devices", "--json", "--all", *ws.paths()], dependencies=ws.deps())

    out = capsys.readouterr().out
    assert "SYNTH0001" not in out
    assert "02:00:00:00:00:01" not in out
    assert "usb-0000:00:14.0" not in out


def test_mapping_column_reflects_the_saved_draft(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ws = workspace(tmp_path, [xbox_one_s_usb()])
    ws.absinfo["event3"] = XBOX_ONE_ABSINFO
    assert (
        cli.main(["mapping", "draft", "--device", "event3", *ws.paths()], dependencies=ws.deps())
        == 0
    )
    capsys.readouterr()

    cli.main(["devices", *ws.paths()], dependencies=ws.deps())
    table = capsys.readouterr().out
    cli.main(["devices", "--json", *ws.paths()], dependencies=ws.deps())

    assert "provisório" in table
    assert json_lines(capsys.readouterr().out)[0]["mapping"] == "provisional"


def test_fragile_twins_are_listed_with_a_warning(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ws = workspace(tmp_path, twin_generic_pads())

    cli.main(["devices", *ws.paths()], dependencies=ws.deps())

    out = capsys.readouterr().out
    assert "usb-1209-0009-n1" in out and "usb-1209-0009-n2" in out
    assert "aviso: usb-1209-0009-n1: identidade frágil" in out


def test_no_gamepad_exits_3_even_with_other_nodes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ws = workspace(tmp_path, [keyboard()])

    assert cli.main(["devices", "--all", *ws.paths()], dependencies=ws.deps()) == 3
    captured = capsys.readouterr()
    assert "keyboard" in captured.out
    assert "nenhum gamepad" in captured.err


def test_missing_sysfs_exits_3(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ws = workspace(tmp_path, [])

    code = cli.main(
        ["devices", "--sysfs-root", str(tmp_path / "nowhere"), "--devices-dir", str(ws.devices)],
        dependencies=ws.deps(),
    )

    assert code == 3
    assert "sysfs indisponível" in capsys.readouterr().err


def test_verify_reports_access_per_gamepad(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ws = workspace(tmp_path, [xbox_one_s_usb(), *dualsense_bt_nodes()])
    ws.access["event21"] = "permission_denied"

    cli.main(["devices", "--verify", *ws.paths()], dependencies=ws.deps())
    table = capsys.readouterr().out.splitlines()
    cli.main(["devices", "--verify", "--json", *ws.paths()], dependencies=ws.deps())
    rows = json_lines(capsys.readouterr().out)

    assert table[0].split()[-1] == "ACESSO"
    assert table[1].endswith("sem permissão") and table[2].endswith("ok")
    assert {row["node"]: row["access"] for row in rows} == {
        "event21": "permission_denied",
        "event3": "ok",
    }


def test_access_is_absent_without_verify(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ws = workspace(tmp_path, [xbox_one_s_usb()])

    cli.main(["devices", "--json", *ws.paths()], dependencies=ws.deps())

    assert "access" not in json_lines(capsys.readouterr().out)[0]


def test_verify_with_watch_is_an_argument_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ws = workspace(tmp_path, [xbox_one_s_usb()])

    assert cli.main(["devices", "--verify", "--watch", *ws.paths()], dependencies=ws.deps()) == 2
    assert "--verify" in capsys.readouterr().err


@pytest.mark.parametrize("interval", ["0.1", "6", "x"])
def test_invalid_interval_is_rejected(interval: str) -> None:
    with pytest.raises(SystemExit) as raised:
        cli.main(["devices", "--watch", "--interval", interval])
    assert raised.value.code == 2


class _InterruptingClock(FakeClock):
    def __init__(self, sleeps_before_interrupt: int) -> None:
        super().__init__()
        self.remaining = sleeps_before_interrupt

    def sleep(self, seconds: float) -> None:
        if self.remaining == 0:
            raise KeyboardInterrupt
        self.remaining -= 1
        super().sleep(seconds)


def _scans(tmp_path: Path, *groups) -> list[tuple[ObservedInputDevice, ...]]:
    scans = []
    for index, nodes in enumerate(groups):
        root = build_sysfs(tmp_path / f"scan{index}", list(nodes))
        scans.append(SysfsInputScanner(root).scan())
    return scans


def test_watch_waits_on_empty_list_and_reports_gamepad_events_until_ctrl_c(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    empty, with_pads, after = _scans(
        tmp_path, [], [xbox_one_s_usb(), *dualsense_bt_nodes()], [*dualsense_bt_nodes()]
    )
    scanner = ScriptedScanner([empty, empty, with_pads, after])
    ws = workspace(tmp_path, [])
    clock = _InterruptingClock(3)

    code = cli.main(
        ["devices", "--watch", "--interval", "0.5", *ws.paths()],
        dependencies=ws.deps(scanner=lambda root: scanner, clock=lambda: clock),
    )

    out = capsys.readouterr().out.splitlines()
    assert code == 130
    assert clock.sleeps == [0.5, 0.5, 0.5]
    events = [line for line in out if line.startswith(("conectado", "removido"))]
    assert len(events) == 3
    assert events[0].startswith("conectado: bt-054c-0ce6-u")
    assert events[1].startswith(f"conectado: {XBOX_ID}")
    assert events[2].startswith(f"removido: {XBOX_ID}")
    assert not any("Touchpad" in line or "Motion" in line for line in out)


def test_watch_json_emits_event_objects(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    empty, with_pad = _scans(tmp_path, [], [xbox_one_s_usb()])
    scanner = ScriptedScanner([empty, empty, with_pad])
    ws = workspace(tmp_path, [])

    code = cli.main(
        ["devices", "--watch", "--json", *ws.paths()],
        dependencies=ws.deps(scanner=lambda root: scanner, clock=lambda: _InterruptingClock(1)),
    )

    rows = json_lines(capsys.readouterr().out)
    assert code == 130
    assert rows == [{**rows[0], "event": "added", "id": XBOX_ID}]


def test_watch_with_missing_sysfs_exits_3(tmp_path: Path) -> None:
    ws = workspace(tmp_path, [])

    code = cli.main(
        ["devices", "--watch", "--sysfs-root", str(tmp_path / "x"), "--devices-dir", "d"],
        dependencies=ws.deps(),
    )

    assert code == 3


def test_devices_json_is_valid_json_per_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ws = workspace(tmp_path, [xbox_one_s_usb(), *twin_generic_pads()])

    cli.main(["devices", "--json", *ws.paths()], dependencies=ws.deps())

    for line in capsys.readouterr().out.splitlines():
        assert json.loads(line)["schema_version"] == 1
