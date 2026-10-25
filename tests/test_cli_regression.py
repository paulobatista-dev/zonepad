"""Regression of the CLI surface touched by device discovery v1."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from synthetic_capture import full_session, mapping_payload

from zonepad.infrastructure.evdev import LinuxEvdevBackend
from zonepad.interface import cli


def test_list_output_is_byte_identical(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    dev = tmp_path / "dev"
    dev.mkdir()
    for name in ("event10", "event3", "mouse0"):
        (dev / name).write_text("", encoding="utf-8")
    monkeypatch.setattr(cli, "LinuxEvdevBackend", lambda: LinuxEvdevBackend(dev))

    assert cli.main(["list"]) == 0

    assert capsys.readouterr().out == (
        '{"id": "event10", "name": "event10", "capabilities": ["evdev"]}\n'
        '{"id": "event3", "name": "event3", "capabilities": ["evdev"]}\n'
    )


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (["devices"], ["--watch", "--verify", "--sysfs-root", "códigos de saída", "130"]),
        (["mapping"], ["draft", "show", "validate"]),
        (
            ["mapping", "draft"],
            ["--accept-fragile-id", "--accept-axis-guess", "--no-probe", "--catalog", "  4  "],
        ),
        (["mapping", "show"], ["--json", "códigos de saída"]),
        (["mapping", "validate"], ["códigos de saída"]),
        (["run"], ["ID estável", "--devices-dir", "códigos de saída", "legado"]),
        (["calibrate"], ["ID estável", "--sysfs-root", "códigos de saída", "não descoberto"]),
        (["list"], []),
        (["replay"], []),
        (["profiles"], []),
        (["measure"], ["códigos de saída"]),
    ],
)
def test_help_is_complete_and_needs_no_tty(
    argv: list[str], expected: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as raised:
        cli.main([*argv, "--help"])

    out = capsys.readouterr().out
    assert raised.value.code == 0
    for text in expected:
        assert text in out


def test_replay_profiles_and_measure_still_work(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    recorder = full_session()
    capture = tmp_path / "capture.jsonl"
    capture.write_text(recorder.jsonl(), encoding="utf-8")
    manifest = tmp_path / "capture.manifest.json"
    manifest.write_text(json.dumps(recorder.manifest_payload()), encoding="utf-8")
    mapping = tmp_path / "mapping.json"
    mapping.write_text(json.dumps(mapping_payload()), encoding="utf-8")

    assert cli.main(["replay", str(capture)]) == 0
    assert json.loads(capsys.readouterr().out)["frames"] == len(recorder.raw_frames())
    assert cli.main(["profiles", "--directory", str(tmp_path / "profiles")]) == 0
    assert capsys.readouterr().out == ""
    report = tmp_path / "report.json"
    code = cli.main(
        [
            "measure",
            str(capture),
            "--manifest",
            str(manifest),
            "--mapping",
            str(mapping),
            "--report",
            str(report),
        ]
    )
    assert code == 0
    assert json.loads(report.read_text("utf-8"))["quality"]["status"]
