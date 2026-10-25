from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from synthetic_capture import (
    FIXED_NOW,
    FIXED_PROFILE_ID,
    Recorder,
    full_session,
    mapping_payload,
)

from zonepad.application.report import loads_report, render_markdown
from zonepad.domain.profile import validate_profile
from zonepad.infrastructure.json_profile_store import JsonProfileStore
from zonepad.interface import cli


class FrozenDatetime(datetime):
    @classmethod
    def now(cls, tz: Any = None) -> FrozenDatetime:  # type: ignore[override]
        return cls.fromtimestamp(FIXED_NOW.timestamp(), tz)


@pytest.fixture(autouse=True)
def deterministic_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "datetime", FrozenDatetime)
    monkeypatch.setattr(uuid, "uuid4", lambda: uuid.UUID(FIXED_PROFILE_ID))

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("measure não pode tocar em evdev nem em uinput")

    monkeypatch.setattr(cli, "LinuxEvdevBackend", forbidden)
    monkeypatch.setattr(cli, "LinuxUinputPublisher", forbidden)


class Files:
    """Writes a synthetic session to ``tmp_path`` and builds the CLI arguments."""

    def __init__(self, tmp_path: Path, rec: Recorder | None = None) -> None:
        self.dir = tmp_path
        self.rec = rec or full_session()
        self.capture = tmp_path / "capture.jsonl"
        self.manifest = tmp_path / "capture.manifest.json"
        self.mapping = tmp_path / "mapping.json"
        self.capture.write_text(self.rec.jsonl(), encoding="utf-8")
        self.manifest.write_text(json.dumps(self.rec.manifest_payload()), encoding="utf-8")
        self.mapping.write_text(json.dumps(mapping_payload()), encoding="utf-8")

    def args(self, *extra: str) -> list[str]:
        return [
            "measure",
            str(self.capture),
            "--manifest",
            str(self.manifest),
            "--mapping",
            str(self.mapping),
            *extra,
        ]


def run_cli(capsys: pytest.CaptureFixture[str], argv: list[str]) -> tuple[int, str, str]:
    code = cli.main(argv)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


# ------------------------------------------------------------------------------- help


def test_help_documenta_argumentos_obrigatorios_e_codigos_de_saida(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["measure", "--help"])

    out = capsys.readouterr().out
    assert exit_info.value.code == 0
    for argument in (
        "capture",
        "--manifest",
        "--mapping",
        "--report",
        "--report-md",
        "--save-profile",
        "--thresholds",
        "--strict",
    ):
        assert argument in out
    assert "(obrigatório)" in out
    for line in ("  0  ", "  1  ", "  2  ", "  4  "):
        assert line in out


def test_manifest_e_mapping_sao_obrigatorios(capsys: pytest.CaptureFixture[str]) -> None:
    for argv in (
        ["measure", "c.jsonl", "--mapping", "m.json"],
        ["measure", "c.jsonl", "--manifest", "m.json"],
    ):
        with pytest.raises(SystemExit) as exit_info:
            cli.main(argv)
        assert exit_info.value.code == 2
        assert "required" in capsys.readouterr().err


def test_subcomandos_existentes_continuam_no_parser() -> None:
    parser = cli.build_parser()

    assert parser.parse_args(["replay", "c.jsonl"]).command == "replay"
    assert parser.parse_args(["profiles"]).command == "profiles"
    assert parser.parse_args(["list"]).command == "list"
    assert parser.parse_args(["run", "--device", "e", "--profile", "p"]).command == "run"


# ----------------------------------------------------------------------------- outputs


def test_sem_report_o_json_vai_para_stdout(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    files = Files(tmp_path)

    code, out, err = run_cli(capsys, files.args())

    assert code == 0
    report = loads_report(out)
    assert report["quality"]["status"] == "pass"
    assert report["capture"]["file"] == "capture.jsonl"
    assert err == ""
    assert not list(tmp_path.glob("*.tmp"))


def test_report_e_report_md_gravam_arquivos_consistentes_entre_si(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    files = Files(tmp_path)
    report_path, markdown_path = tmp_path / "m.json", tmp_path / "m.md"

    code, out, _ = run_cli(
        capsys, files.args("--report", str(report_path), "--report-md", str(markdown_path))
    )

    assert code == 0
    assert out == ""
    report = loads_report(report_path.read_text(encoding="utf-8"))
    assert markdown_path.read_text(encoding="utf-8") == render_markdown(report)


def test_apenas_report_md_nao_imprime_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    files = Files(tmp_path)

    code, out, _ = run_cli(capsys, files.args("--report-md", str(tmp_path / "m.md")))

    assert code == 0
    assert out == ""
    assert "# Relatório de métricas de calibração" in (tmp_path / "m.md").read_text(
        encoding="utf-8"
    )


def test_execucao_repetida_gera_relatorio_e_perfil_identicos(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    files = Files(tmp_path)
    outputs = []
    for name in ("a", "b"):
        run_cli(
            capsys,
            files.args(
                "--report", str(tmp_path / f"{name}.json"), "--save-profile", str(tmp_path / name)
            ),
        )
        outputs.append(
            (
                (tmp_path / f"{name}.json").read_bytes(),
                (tmp_path / name / f"{FIXED_PROFILE_ID}.json").read_bytes(),
            )
        )

    assert outputs[0] == outputs[1]


# ---------------------------------------------------------------------------- profile


def test_save_profile_grava_perfil_valido_e_imprime_o_id(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    files = Files(tmp_path, full_session(rest_values={"lx": 0.1}))
    profiles = tmp_path / "profiles"
    report_path = tmp_path / "m.json"

    code, out, _ = run_cli(
        capsys, files.args("--report", str(report_path), "--save-profile", str(profiles))
    )

    assert code == 0
    assert f"profile_id: {FIXED_PROFILE_ID}" in out
    store = JsonProfileStore(profiles)
    assert store.list_profiles() == (FIXED_PROFILE_ID,)
    profile = store.load(FIXED_PROFILE_ID)
    validate_profile(profile.to_dict())
    assert profile.sticks["left"].center[0] == pytest.approx(0.1, abs=1e-6)
    report = loads_report(report_path.read_text(encoding="utf-8"))
    assert report["profile_summary"]["profile_id"] == FIXED_PROFILE_ID


def test_json_em_stdout_mantem_o_profile_id_em_stderr(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    files = Files(tmp_path)

    code, out, err = run_cli(capsys, files.args("--save-profile", str(tmp_path / "profiles")))

    assert code == 0
    assert loads_report(out)["profile_summary"]["profile_id"] == FIXED_PROFILE_ID
    assert err.strip() == f"profile_id: {FIXED_PROFILE_ID}"


def test_sem_save_profile_nenhum_perfil_e_criado(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    files = Files(tmp_path)

    code, out, _ = run_cli(capsys, files.args())

    assert code == 0
    assert loads_report(out)["profile_summary"]["profile_id"] is None
    assert not (tmp_path / "profiles").exists()


# ----------------------------------------------------------------------- strict / exit 4


def test_repouso_curto_sem_strict_sai_com_0_e_grava_o_perfil(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    files = Files(tmp_path, full_session(rest_s=3.0))

    code, out, _ = run_cli(capsys, files.args("--save-profile", str(tmp_path / "p")))

    assert code == 0
    assert loads_report(out)["quality"]["status"] == "warn"
    assert JsonProfileStore(tmp_path / "p").list_profiles() == (FIXED_PROFILE_ID,)


def test_repouso_curto_com_strict_sai_com_4_sem_perfil_e_com_relatorio(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    files = Files(tmp_path, full_session(rest_s=3.0))
    report_path = tmp_path / "m.json"

    code, out, err = run_cli(
        capsys,
        files.args("--strict", "--report", str(report_path), "--save-profile", str(tmp_path / "p")),
    )

    assert code == 4
    assert "--strict" in err
    assert "Traceback" not in err
    assert JsonProfileStore(tmp_path / "p").list_profiles() == ()
    codes = {
        f["code"]
        for f in loads_report(report_path.read_text(encoding="utf-8"))["quality"]["findings"]
    }
    assert "REST_TOO_SHORT" in codes
    assert out == ""


def test_strict_sem_achados_bloqueantes_sai_com_0(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    files = Files(tmp_path)

    code, _, _ = run_cli(capsys, files.args("--strict"))

    assert code == 0


def test_save_profile_sem_perfil_derivavel_sai_com_4_mantendo_o_relatorio(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    files = Files(tmp_path, full_session(circles=(("right", "cw", {}), ("right", "ccw", {}))))
    report_path = tmp_path / "m.json"

    code, _, err = run_cli(
        capsys, files.args("--report", str(report_path), "--save-profile", str(tmp_path / "p"))
    )

    assert code == 4
    assert "MISSING_CIRCLE_SEGMENT" in err
    assert loads_report(report_path.read_text(encoding="utf-8"))["quality"]["status"] == "fail"
    assert JsonProfileStore(tmp_path / "p").list_profiles() == ()


# ----------------------------------------------------------------------- exit 2 (inputs)


def test_captura_vazia_sai_com_2_e_mensagem_acionavel(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    files = Files(tmp_path)
    files.capture.write_text("", encoding="utf-8")

    code, out, err = run_cli(capsys, files.args())

    assert code == 2
    assert out == ""
    assert "[EMPTY_CAPTURE]" in err and "capture.jsonl" in err
    assert "Traceback" not in err


def test_nan_na_captura_sai_com_2_e_nunca_emite_nan(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    files = Files(tmp_path)
    lines = files.capture.read_text(encoding="utf-8").splitlines()
    lines[41] = '{"device_id": "event3", "timestamp_ns": 1, "axes": {"lx": NaN}}'
    files.capture.write_text("\n".join(lines) + "\n", encoding="utf-8")

    code, out, err = run_cli(capsys, files.args())

    assert code == 2
    assert "capture.jsonl:42:" in err
    assert "NaN" not in out


def test_timestamp_decrescente_sai_com_2_citando_a_linha(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    files = Files(tmp_path)
    lines = files.capture.read_text(encoding="utf-8").splitlines()
    record = json.loads(lines[11])
    record["timestamp_ns"] = 0
    lines[11] = json.dumps(record)
    files.capture.write_text("\n".join(lines) + "\n", encoding="utf-8")

    code, _, err = run_cli(capsys, files.args())

    assert code == 2
    assert "[NON_MONOTONIC_TIME]" in err
    assert "capture.jsonl:12:" in err


def test_manifesto_invalido_sai_com_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    files = Files(tmp_path)
    payload = files.rec.manifest_payload()
    payload["segments"][0]["bogus"] = 1
    files.manifest.write_text(json.dumps(payload), encoding="utf-8")

    code, _, err = run_cli(capsys, files.args())

    assert code == 2
    assert "[INVALID_MANIFEST]" in err and "bogus" in err


def test_manifesto_para_outra_captura_sai_com_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    files = Files(tmp_path)
    renamed = tmp_path / "outra.jsonl"
    files.capture.rename(renamed)
    files.capture = renamed

    code, _, err = run_cli(capsys, files.args())

    assert code == 2
    assert "capture_file" in err


def test_thresholds_invalidos_saem_com_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    files = Files(tmp_path)
    thresholds = tmp_path / "t.json"
    thresholds.write_text('{"thresholds_version": 1, "drift_max": -1}', encoding="utf-8")

    code, _, err = run_cli(capsys, files.args("--thresholds", str(thresholds)))

    assert code == 2
    assert "[INVALID_THRESHOLDS]" in err and "drift_max" in err


def test_thresholds_do_usuario_entram_no_relatorio_e_nos_achados(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    files = Files(tmp_path, full_session(rest_noise=lambda i: {"lx": 0.01 if i % 2 else -0.01}))
    thresholds = tmp_path / "t.json"
    thresholds.write_text('{"thresholds_version": 1, "noise_rms_max": 0.5}', encoding="utf-8")

    code, out, _ = run_cli(capsys, files.args("--thresholds", str(thresholds)))

    report = loads_report(out)
    assert code == 0
    assert report["thresholds"]["noise_rms_max"] == 0.5
    assert "HIGH_NOISE" not in {f["code"] for f in report["quality"]["findings"]}


def test_mapping_invalido_ou_ausente_sai_com_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    files = Files(tmp_path)
    files.mapping.write_text("{broken", encoding="utf-8")

    code, _, err = run_cli(capsys, files.args())
    assert code == 2
    assert "[INVALID_MAPPING]" in err

    files.mapping.unlink()
    code, _, err = run_cli(capsys, files.args())
    assert code == 2
    assert "mapping" in err


def test_captura_inexistente_sai_com_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    files = Files(tmp_path)
    files.capture.unlink()

    code, _, err = run_cli(capsys, files.args())

    assert code == 2
    assert "não foi possível ler" in err


# ----------------------------------------------------------------------- exit 1


def test_falha_de_escrita_sai_com_1_e_orientacao(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    files = Files(tmp_path)

    code, _, err = run_cli(capsys, files.args("--report", str(tmp_path / "ausente" / "m.json")))

    assert code == 1
    assert "permissões" in err
    assert "Traceback" not in err


def test_falha_inesperada_sai_com_1_sem_stack_trace(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    files = Files(tmp_path)

    def boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("falha simulada")

    monkeypatch.setattr(cli, "execute_measure", boom)

    code, _, err = run_cli(capsys, files.args())

    assert code == 1
    assert "falha inesperada (RuntimeError): falha simulada" in err
    assert "Traceback" not in err


def test_falha_ao_gravar_o_relatorio_nao_deixa_perfil_gravado(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    files = Files(tmp_path)
    bad_report = str(tmp_path / "ausente" / "m.json")

    code, _, _ = run_cli(
        capsys, files.args("--report", bad_report, "--save-profile", str(tmp_path / "p"))
    )

    assert code == 1
    assert JsonProfileStore(tmp_path / "p").list_profiles() == ()


def test_degenerate_range_do_trigger_via_thresholds(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    files = Files(tmp_path, full_session(sweeps=(("left", {"peak": 0.48}), ("right", {}))))
    thresholds = tmp_path / "t.json"
    thresholds.write_text(
        '{"thresholds_version": 1, "protocol": {"trigger_peak_min": 0.45}}', encoding="utf-8"
    )

    code, out, _ = run_cli(capsys, files.args("--thresholds", str(thresholds)))

    findings = loads_report(out)["quality"]["findings"]
    assert code == 0
    assert any(
        f["code"] == "DEGENERATE_RANGE"
        and f["severity"] == "error"
        and f["metric"] == "triggers.left.span"
        for f in findings
    )
