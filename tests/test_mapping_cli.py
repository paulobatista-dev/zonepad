from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from cli_support import files_under, workspace
from conftest import IoGuardFactory
from sysfs_builder import (
    GENERIC_4095_ABSINFO,
    XBOX_ONE_ABSINFO,
    build_sysfs,
    generic_bt_z_rz,
    generic_usb_full,
    generic_without_triggers,
    switch_pro_bt,
    twin_generic_pads,
    xbox_one_s_usb,
)

from zonepad.domain.discovery import absinfo_from_kernel
from zonepad.infrastructure.mapping import load_device_mapping
from zonepad.interface import cli

XBOX_ID = "usb-045e-02ea-se73b07be4c"


def _xbox(tmp_path: Path, **node_changes: object):
    ws = workspace(tmp_path, [replace(xbox_one_s_usb(), **node_changes)])  # type: ignore[arg-type]
    ws.absinfo["event3"] = XBOX_ONE_ABSINFO
    return ws


def _draft(ws, *extra: str) -> int:
    return cli.main(["mapping", "draft", *extra, *ws.paths()], dependencies=ws.deps())


def test_draft_saves_a_provisional_mapping_and_points_to_calibrate(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], forbid_io_outside: IoGuardFactory
) -> None:
    ws = _xbox(tmp_path)

    with forbid_io_outside(tmp_path):
        code = _draft(ws, "--device", "event3")

    captured = capsys.readouterr()
    mapping_path = ws.devices / XBOX_ID / "mapping.json"
    assert code == 0
    assert captured.out == (
        f"mapping provisório gravado em {mapping_path}; próximo passo: "
        f"zonepad calibrate --device {XBOX_ID}\n"
    )
    assert "provisório" in captured.err
    assert files_under(ws.devices) == [
        "index.json",
        f"{XBOX_ID}/identity.json",
        f"{XBOX_ID}/mapping.json",
    ]
    mapping = load_device_mapping(mapping_path)
    assert mapping.axes["lx"].minimum == -32768 and mapping.axes["lx"].center == 0
    assert mapping.triggers["lt"].maximum == 1023
    assert set(mapping.button_codes) == {304, 305, 307, 308}
    identity = json.loads((ws.devices / XBOX_ID / "identity.json").read_text("utf-8"))
    assert identity["draft"]["provisional"] is True
    assert identity["draft"]["range_sources"]["lx"] == "evdev_absinfo"
    assert identity["created_at"] == "2026-10-25T12:00:00Z"


def test_probe_opens_only_the_resolved_node(tmp_path: Path) -> None:
    ws = workspace(tmp_path, [xbox_one_s_usb(), generic_usb_full()])
    ws.absinfo["event3"] = XBOX_ONE_ABSINFO

    assert _draft(ws, "--device", XBOX_ID) == 0
    assert ws.reader is not None
    assert [node for node, _ in ws.reader.calls] == ["event3"]


def test_draft_is_byte_identical_across_runs(tmp_path: Path) -> None:
    first = _xbox(tmp_path / "a")
    second = _xbox(tmp_path / "b")

    assert _draft(first, "--device", "event3") == 0
    assert _draft(second, "--device", "event3") == 0

    for name in ("mapping.json", "identity.json"):
        left = (first.devices / XBOX_ID / name).read_bytes()
        right = (second.devices / XBOX_ID / name).read_bytes()
        assert left == right


def test_existing_mapping_needs_force(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ws = _xbox(tmp_path)
    assert _draft(ws, "--device", "event3") == 0
    capsys.readouterr()

    assert _draft(ws, "--device", "event3") == 2
    assert "--force" in capsys.readouterr().err
    assert _draft(ws, "--device", "event3", "--force") == 0


def test_print_writes_nothing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ws = _xbox(tmp_path)

    assert _draft(ws, "--device", "event3", "--print") == 0

    captured = capsys.readouterr()
    assert json.loads(captured.out)["schema_version"] == 1
    assert f"id: {XBOX_ID}" in captured.err
    assert "catálogo: xpad-xboxone" in captured.err
    assert not ws.devices.exists()


def test_out_writes_only_the_mapping(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ws = _xbox(tmp_path)
    target = tmp_path / "pad.json"

    assert _draft(ws, "--device", "event3", "--out", str(target)) == 0

    assert load_device_mapping(target).axes["lx"].center == 0
    assert not ws.devices.exists()
    assert "não vai resolvê-lo" in capsys.readouterr().err


def test_print_and_out_are_mutually_exclusive(tmp_path: Path) -> None:
    ws = _xbox(tmp_path)

    with pytest.raises(SystemExit) as raised:
        _draft(ws, "--device", "event3", "--print", "--out", "x.json")
    assert raised.value.code == 2


def test_fragile_identity_requires_confirmation(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ws = workspace(tmp_path, twin_generic_pads())
    ws.absinfo["event2"] = GENERIC_4095_ABSINFO

    assert _draft(ws, "--device", "usb-1209-0009-n1") == 2
    err = capsys.readouterr().err
    assert "usb-1209-0009-n1, usb-1209-0009-n2" in err
    assert "--accept-fragile-id" in err
    assert not ws.devices.exists()
    ws.answers.append(False)
    assert _draft(ws, "--device", "usb-1209-0009-n1") == 2
    ws.answers.append(True)
    assert _draft(ws, "--device", "usb-1209-0009-n1") == 0
    assert _draft(ws, "--device", "event2", "--accept-fragile-id", "--force") == 0


def test_switch_pro_exits_4_without_writing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ws = workspace(tmp_path, [switch_pro_bt()])
    ws.absinfo["event25"] = {}

    assert _draft(ws, "--device", "event25") == 4

    err = capsys.readouterr().err
    assert "digital_triggers_only" in err and "canais ausentes: lt, rt" in err
    assert "nada foi gravado" in err
    assert files_under(ws.devices) == []


def test_generic_without_triggers_lists_missing_and_detected(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ws = workspace(tmp_path, [generic_without_triggers()])
    ws.absinfo["event50"] = GENERIC_4095_ABSINFO

    assert _draft(ws, "--device", "event50") == 4

    err = capsys.readouterr().err
    assert "canais ausentes: lt, rt" in err
    assert "ABS_X(0), ABS_Y(1), ABS_RX(3), ABS_RY(4)" in err
    assert "BTN_TL2, BTN_TR2" in err
    assert not ws.devices.exists()


def test_ambiguous_axes_need_accept_axis_guess(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ws = workspace(tmp_path, [generic_bt_z_rz()])
    ws.absinfo["event51"] = {
        code: absinfo_from_kernel(0, 0, 255, 0, 0, 0) for code in (0, 1, 2, 5, 9, 10)
    }

    assert _draft(ws, "--device", "event51") == 2
    err = capsys.readouterr().err
    assert "rx=ABS_Z(2), ry=ABS_RZ(5)" in err
    assert "lt=ABS_BRAKE(10), rt=ABS_GAS(9)" in err
    assert _draft(ws, "--device", "event51", "--accept-axis-guess") == 0


def test_no_probe_uses_the_catalog_and_never_calls_the_reader(tmp_path: Path) -> None:
    ws = _xbox(tmp_path)

    assert _draft(ws, "--device", "event3", "--no-probe") == 0

    assert ws.reader is not None and ws.reader.calls == []
    identity = json.loads((ws.devices / XBOX_ID / "identity.json").read_text("utf-8"))
    assert identity["draft"]["range_source"] == "catalog"


def test_no_probe_on_generic_exits_4(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ws = workspace(tmp_path, [generic_usb_full()])

    assert _draft(ws, "--device", "event52", "--no-probe") == 4
    assert "ranges_unavailable" in capsys.readouterr().err


def test_permission_denied_uses_catalog_for_known_family(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ws = _xbox(tmp_path)
    ws.denied.add("event3")

    assert _draft(ws, "--device", "event3") == 0
    assert "sem permissão" in capsys.readouterr().err


def test_permission_denied_on_generic_exits_3_with_impact_and_reversal(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ws = workspace(tmp_path, [generic_usb_full()])
    ws.denied.add("event52")

    assert _draft(ws, "--device", "event52") == 3

    err = capsys.readouterr().err
    assert "Sem permissão de leitura em /dev/input/event52" in err
    assert "getfacl /dev/input/event52" in err
    assert "inclusive o teclado" in err
    assert 'sudo gpasswd -d "$USER" input' in err
    assert "--no-probe" in err
    assert "chmod" not in err


def test_connection_override_only_for_unknown_bus(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ws = workspace(tmp_path, [replace(generic_usb_full("event3"), bustype="0019")])
    ws.absinfo["event3"] = GENERIC_4095_ABSINFO

    assert _draft(ws, "--device", "event3", "--connection", "usb") == 0
    (identity_file,) = ws.devices.glob("*/identity.json")
    identity = json.loads(identity_file.read_text("utf-8"))
    assert (identity["connection"], identity["connection_source"]) == ("usb", "override")

    usb = _xbox(tmp_path / "usb")
    assert _draft(usb, "--device", "event3", "--connection", "bluetooth") == 2
    assert "conflita" in capsys.readouterr().err


def test_invalid_user_catalog_exits_2_with_the_field(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ws = _xbox(tmp_path)
    catalog = tmp_path / "catalog.json"
    catalog.write_text('{"catalog_version": 1, "families": [], "extra": 1}', encoding="utf-8")

    assert _draft(ws, "--device", "event3", "--catalog", str(catalog)) == 2
    assert "[INVALID_CATALOG]" in capsys.readouterr().err


def test_reference_errors(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ws = workspace(tmp_path, twin_generic_pads())

    assert _draft(ws, "--device", "usb-1209-0009") == 2
    assert "ambígua" in capsys.readouterr().err
    assert _draft(ws, "--device", "usb-045e-02ea-n1") == 3
    assert "zonepad devices" in capsys.readouterr().err


def _saved(tmp_path: Path):
    ws = _xbox(tmp_path)
    assert _draft(ws, "--device", "event3") == 0
    return ws


def test_show_offline_by_id_via_node_and_json_agree(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ws = _saved(tmp_path)
    capsys.readouterr()
    offline = ["--sysfs-root", str(tmp_path / "absent"), "--devices-dir", str(ws.devices)]

    assert cli.main(["mapping", "show", "--device", XBOX_ID, *offline], dependencies=ws.deps()) == 0
    by_id = capsys.readouterr().out
    assert (
        cli.main(["mapping", "show", "--device", "event3", *ws.paths()], dependencies=ws.deps())
        == 0
    )
    by_node = capsys.readouterr().out
    assert (
        cli.main(
            ["mapping", "show", "--device", XBOX_ID, "--json", *offline], dependencies=ws.deps()
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)

    assert by_id == by_node
    assert f"ID: {XBOX_ID}" in by_id and "Status: provisório" in by_id
    assert "--- mapping.json ---" in by_id
    assert set(payload) == {"identity", "mapping", "status"}
    assert payload["status"] == "provisional"
    assert payload["identity"]["stable_id"] == XBOX_ID
    assert payload["mapping"]["schema_version"] == 1
    assert "usb_serial" not in payload["identity"]["hardware"]
    assert "SYNTH0001" not in json.dumps(payload)


def test_show_without_saved_mapping_exits_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ws = _xbox(tmp_path)

    assert (
        cli.main(["mapping", "show", "--device", XBOX_ID, *ws.paths()], dependencies=ws.deps()) == 2
    )
    assert "mapping draft" in capsys.readouterr().err


def test_show_unknown_device_exits_3(tmp_path: Path) -> None:
    ws = _xbox(tmp_path)

    assert (
        cli.main(["mapping", "show", "--device", "event9", *ws.paths()], dependencies=ws.deps())
        == 3
    )


def test_show_invalid_saved_mapping_exits_2_with_the_field(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ws = _saved(tmp_path)
    path = ws.devices / XBOX_ID / "mapping.json"
    payload = json.loads(path.read_text("utf-8"))
    payload["axes"]["lx"]["bogus"] = 1
    path.write_text(json.dumps(payload), encoding="utf-8")
    capsys.readouterr()

    assert (
        cli.main(["mapping", "show", "--device", XBOX_ID, *ws.paths()], dependencies=ws.deps()) == 2
    )
    assert "mapping.axes.lx has unknown fields: bogus" in capsys.readouterr().err


def test_validate_accepts_and_rejects(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ws = _saved(tmp_path)
    capsys.readouterr()
    good = ws.devices / XBOX_ID / "mapping.json"
    bad = tmp_path / "bad.json"
    payload = json.loads(good.read_text("utf-8"))
    payload["triggers"]["lt"]["extra"] = True
    bad.write_text(json.dumps(payload), encoding="utf-8")

    assert cli.main(["mapping", "validate", str(good)]) == 0
    assert capsys.readouterr().out == "mapping válido: lx, ly, rx, ry, lt, rt; 4 botões\n"
    assert cli.main(["mapping", "validate", str(bad)]) == 2
    err = capsys.readouterr().err
    assert err.startswith("erro: [INVALID_MAPPING] mapping.triggers.lt has unknown fields: extra")
    assert "Traceback" not in err


def test_draft_on_the_versioned_fixture_with_no_probe(capsys: pytest.CaptureFixture[str]) -> None:
    root = Path(__file__).parent / "fixtures" / "sysfs"

    code = cli.main(
        [
            "mapping",
            "draft",
            "--device",
            XBOX_ID,
            "--sysfs-root",
            str(root),
            "--print",
            "--no-probe",
        ]
    )

    assert code == 0
    assert json.loads(capsys.readouterr().out)["triggers"]["rt"]["maximum"] == 1023


def test_empty_sysfs_reports_missing_device(tmp_path: Path) -> None:
    ws = workspace(tmp_path, [])
    build_sysfs(ws.sysfs, [])

    assert _draft(ws, "--device", XBOX_ID) == 3
