from __future__ import annotations

import copy
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest
from synthetic_capture import (
    FIXED_NOW,
    Recorder,
    fixed_now,
    fixed_profile_id,
    full_session,
)

from zonepad.application.calibration import (
    build_profile,
    build_profile_from_metrics,
    derive_calibration,
)
from zonepad.application.measure import MeasureOptions, execute_measure, measure
from zonepad.application.report import (
    dumps_report,
    loads_report,
    render_markdown,
    validate_report,
)
from zonepad.domain.device import DeviceInfo
from zonepad.domain.errors import InvalidReportError, ProfileDerivationError
from zonepad.domain.input import NormalizedFrame
from zonepad.domain.metrics import MeasurementMetrics
from zonepad.domain.profile import validate_profile

DEVICE = DeviceInfo("event3", "Synthetic Pad", 0x045E, 0x0B13, "guid-1", "serial-1")


def metrics_for(rec: Recorder | None = None, **manifest: Any) -> MeasurementMetrics:
    return measure((rec or full_session()).inputs(**manifest)).metrics


def outcome(rec: Recorder | None = None) -> Any:
    return execute_measure(
        (rec or full_session()).inputs(),
        MeasureOptions(save_profile=True),
        app_version="0.1.0",
        now=fixed_now,
        profile_id_factory=fixed_profile_id,
    )


# ------------------------------------------------------------------------------- profile


def build(metrics: MeasurementMetrics, **overrides: Any) -> Any:
    options: dict[str, Any] = {
        "app_version": "0.1.0",
        "now": fixed_now,
        "profile_id_factory": fixed_profile_id,
        **overrides,
    }
    return build_profile_from_metrics(DEVICE, metrics, **options)


def test_perfil_derivado_passa_em_validate_profile_e_mantem_invariantes() -> None:
    profile = build(metrics_for(full_session(rest_values={"lx": 0.1, "ly": -0.1, "lt": 0.02})))

    revalidated = validate_profile(json.loads(json.dumps(profile.to_dict())))
    assert revalidated == profile
    assert profile.schema_version == 1
    for stick in profile.sticks.values():
        for minimum, center, maximum in zip(
            stick.range_min, stick.center, stick.range_max, strict=True
        ):
            assert minimum < center < maximum
        assert 0.0 <= stick.deadzone.value <= 0.95
        assert stick.deadzone.mode == "cut"
        assert stick.curve.type == "linear"
        assert stick.invert == (False, False)
    for trigger in profile.triggers.values():
        assert 0.0 <= trigger.rest < trigger.max <= 1.0
        assert trigger.curve.type == "linear"
        assert trigger.invert is False
    assert profile.sticks["left"].center == pytest.approx((0.1, -0.1), abs=1e-6)
    assert profile.triggers["left"].rest == pytest.approx(0.02, abs=1e-6)


def test_perfil_nao_ganha_campos_novos_alem_do_schema_v1() -> None:
    profile = build(metrics_for())

    assert set(profile.to_dict()) == {
        "schema_version",
        "profile_id",
        "device",
        "sticks",
        "triggers",
        "created_at",
        "app_version",
        "notes",
    }
    with pytest.raises(Exception, match="unknown"):
        validate_profile({**profile.to_dict(), "metrics": {}})


def test_perfil_e_deterministico_com_relogio_e_uuid_injetados() -> None:
    first = build(metrics_for())
    second = build(metrics_for())

    assert first == second
    assert json.dumps(first.to_dict(), sort_keys=True) == json.dumps(
        second.to_dict(), sort_keys=True
    )
    assert first.created_at == "2026-10-24T00:00:00Z"
    assert first.profile_id == fixed_profile_id()


def test_identidade_do_dispositivo_vem_do_device_info_em_hex_minusculo() -> None:
    profile = build(metrics_for())

    assert (profile.device.name, profile.device.vid, profile.device.pid) == (
        "Synthetic Pad",
        "0x045e",
        "0x0b13",
    )
    assert (profile.device.guid, profile.device.serial) == ("guid-1", "serial-1")


def test_notas_registram_origem_status_e_avisos() -> None:
    metrics = metrics_for(full_session(rest_s=3.0))  # REST_TOO_SHORT (warning)

    notes = build(metrics).notes

    assert notes.startswith("zonepad measure; captura=capture.jsonl; sha256=aaaaaaaaaaaa;")
    assert "metrics_schema_version=1" in notes
    assert "status=warn" in notes
    assert notes.endswith("avisos=REST_TOO_SHORT")


def test_notas_sao_truncadas_em_2000_caracteres_com_reticencias() -> None:
    metrics = replace(metrics_for(), source_file="x" * 3000)

    notes = build(metrics).notes

    assert len(notes) == 2000
    assert notes.endswith("…")


def test_perfil_exige_relogio_com_fuso_horario() -> None:
    naive = lambda: datetime(2026, 10, 24)  # noqa: E731

    with pytest.raises(ValueError, match="fuso"):
        build(metrics_for(), now=naive)


def test_perfil_converte_relogio_para_utc() -> None:
    local = lambda: datetime(2026, 10, 24, 3, 0, 0, tzinfo=timezone(timedelta(hours=3)))  # noqa: E731

    assert build(metrics_for(), now=local).created_at == "2026-10-24T00:00:00Z"


def test_fabrica_de_id_invalido_vira_erro_de_derivacao() -> None:
    with pytest.raises(ProfileDerivationError, match="UUID"):
        build(metrics_for(), profile_id_factory=lambda: "not-a-uuid")


@pytest.mark.parametrize(
    "rec",
    [
        full_session(with_rest=False),
        full_session(circles=()),
        full_session(sweeps=()),
        full_session(
            circles=(
                ("left", "cw", {"radius": (0.4, 0.4)}),
                ("left", "ccw", {"radius": (0.4, 0.4)}),
            )
            + (("right", "cw", {}), ("right", "ccw", {}))
        ),
    ],
    ids=["sem-repouso", "sem-circulos", "sem-triggers", "range-degenerado"],
)
def test_metricas_com_achado_de_erro_nao_geram_perfil_nem_usam_epsilon(rec: Recorder) -> None:
    metrics = metrics_for(rec)

    with pytest.raises(ProfileDerivationError, match="achados de erro"):
        build(metrics)
    with pytest.raises(ProfileDerivationError):
        derive_calibration(metrics)


def test_metrica_ausente_sem_achado_de_erro_ainda_falha_com_mensagem_acionavel() -> None:
    metrics = metrics_for()
    broken_stick = replace(metrics.sticks["left"], center=None)
    broken = replace(metrics, sticks={**metrics.sticks, "left": broken_stick})

    with pytest.raises(ProfileDerivationError, match="stick left: faltam repouso ou círculo"):
        derive_calibration(broken)


def test_build_profile_legado_continua_disponivel_e_valido() -> None:
    frames = [
        NormalizedFrame(
            "pad",
            1,
            {"lx": -0.5, "ly": -0.5, "rx": -0.5, "ry": -0.5},
            {"lt": 0.0, "rt": 0.0},
            frozenset(),
        ),
        NormalizedFrame(
            "pad",
            2,
            {"lx": 0.5, "ly": 0.5, "rx": 0.5, "ry": 0.5},
            {"lt": 1.0, "rt": 1.0},
            frozenset(),
        ),
    ]

    profile = build_profile(DEVICE, frames)

    assert profile.schema_version == 1


# ------------------------------------------------------------------------------- report


def test_relatorio_serializa_valida_e_faz_round_trip() -> None:
    report = outcome().report

    text = dumps_report(report)
    parsed = loads_report(text)

    assert parsed["report_kind"] == "calibration-metrics"
    assert parsed["metrics_schema_version"] == 1
    assert parsed["profile_summary"]["profile_id"] == fixed_profile_id()
    assert dumps_report(parsed) == text
    assert text.endswith("}\n")
    assert "NaN" not in text and "Infinity" not in text


def test_relatorio_registra_thresholds_efetivos_e_hashes() -> None:
    report = outcome().report

    assert report["thresholds"]["drift_max"] == 0.02
    assert report["thresholds"]["deadzone"]["factor"] == 1.5
    assert report["thresholds"]["protocol"]["rest_min_frames"] == 150
    assert report["capture"]["sha256"] == "a" * 64
    assert report["normalization"] == {"source": "mapping", "mapping_sha256": "b" * 64}
    assert report["quality"] == {
        "status": "pass",
        "findings": [
            {
                "code": "NOMINAL_RATE_UNKNOWN",
                "severity": "info",
                "message": report["quality"]["findings"][0]["message"],
                "metric": "capture.nominal_rate_hz",
                "value": None,
                "threshold": None,
                "strict_blocking": False,
            }
        ],
    }


def test_flutuantes_sao_arredondados_e_zero_negativo_vira_zero() -> None:
    report = copy.deepcopy(outcome().report)
    report["capture"]["duration_s"] = 1.23456789
    report["capture"]["effective_rate_hz"] = 124.99999999
    report["sticks"]["left"]["rest"]["drift"] = -0.0

    data = json.loads(dumps_report(report))

    assert data["capture"]["duration_s"] == 1.234568
    assert data["capture"]["effective_rate_hz"] == 125.0
    assert str(data["sticks"]["left"]["rest"]["drift"]) == "0.0"
    assert "-0.0" not in dumps_report(report)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_serializacao_nunca_emite_nao_finitos(bad: float) -> None:
    report = copy.deepcopy(outcome().report)
    report["capture"]["duration_s"] = bad

    with pytest.raises(InvalidReportError, match="não finito"):
        dumps_report(report)


def _break(path: tuple[str | int, ...], value: Any) -> dict[str, Any]:
    report = copy.deepcopy(outcome().report)
    target: Any = report
    for key in path[:-1]:
        target = target[key]
    if value is _MISSING:
        del target[path[-1]]
    else:
        target[path[-1]] = value
    return report


_MISSING = object()


@pytest.mark.parametrize(
    ("report", "fragment"),
    [
        (_break(("extra",), 1), "campos desconhecidos: extra"),
        (_break(("capture", "extra"), 1), "capture: campos desconhecidos"),
        (_break(("sticks", "left", "extra"), 1), "sticks.left"),
        (_break(("capture", "frames"), _MISSING), "campos ausentes: frames"),
        (_break(("report_kind",), "other"), "report_kind"),
        (_break(("metrics_schema_version",), 2), "metrics_schema_version"),
        (_break(("capture", "frames"), "10"), "capture.frames"),
        (_break(("capture", "frames"), True), "capture.frames"),
        (_break(("capture", "duration_s"), "x"), "capture.duration_s"),
        (_break(("sticks", "left", "center"), [0.0]), "sticks.left.center"),
        (_break(("quality", "status"), "fail"), "quality.status"),
        (_break(("quality", "findings"), [{"code": "NOPE"}]), "quality.findings[0]"),
        (_break(("triggers", "left", "shape_basis"), "x"), "shape_basis"),
    ],
)
def test_validacao_estrita_rejeita_campos_tipos_e_status_incoerentes(
    report: dict[str, Any], fragment: str
) -> None:
    with pytest.raises(InvalidReportError) as caught:
        validate_report(report)

    assert fragment in str(caught.value)


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_leitura_rejeita_constantes_nao_finitas(constant: str) -> None:
    text = dumps_report(outcome().report).replace(
        '"duration_s": 73.472', f'"duration_s": {constant}'
    )

    with pytest.raises(InvalidReportError, match=constant):
        loads_report(text)


def test_leitura_rejeita_json_malformado() -> None:
    with pytest.raises(InvalidReportError, match="malformado"):
        loads_report("{")


def test_relatorio_nao_contem_serial_guid_nem_caminho_absoluto() -> None:
    rec = full_session()
    inputs = rec.inputs()
    device = replace(inputs.manifest.device, guid="guid-secreto", serial="serial-secreto")
    inputs = replace(inputs, manifest=replace(inputs.manifest, device=device))

    report = execute_measure(
        inputs,
        MeasureOptions(save_profile=True),
        app_version="0.1.0",
        now=fixed_now,
        profile_id_factory=fixed_profile_id,
    )

    text = dumps_report(report.report) + render_markdown(report.report)
    assert "guid-secreto" not in text
    assert "serial-secreto" not in text
    assert report.profile is not None
    assert report.profile.device.serial == "serial-secreto"  # só o perfil local leva a identidade
    assert "/home" not in text and "/tmp" not in text
    assert report.report["capture"]["file"] == "capture.jsonl"


# ------------------------------------------------------------------------------ markdown


def test_markdown_segue_a_estrutura_da_skill_e_deriva_do_json() -> None:
    report = outcome(full_session(rest_values={"lx": 0.1, "ly": -0.1})).report

    markdown = render_markdown(report)

    for heading in (
        "## Dispositivo",
        "## Captura",
        "## Sticks",
        "## Triggers",
        "## Riscos e observações",
    ):
        assert heading in markdown
    assert "Synthetic Pad / 0x045e / 0x0b13" in markdown
    assert "| Esquerdo | (0.1000, -0.1000) |" in markdown
    assert "capture.jsonl" in markdown
    assert "`NOMINAL_RATE_UNKNOWN`" in markdown
    assert f"Perfil: {fixed_profile_id()}" in markdown


def test_markdown_nao_recalcula_nada_e_acompanha_o_json() -> None:
    report = copy.deepcopy(outcome().report)
    report["sticks"]["left"]["rest"]["drift"] = 0.0123
    report["triggers"]["right"]["max"] = 0.9876

    markdown = render_markdown(report)

    assert "0.0123" in markdown
    assert "0.9876" in markdown


def test_markdown_mostra_nd_para_metricas_nulas_e_lista_achados() -> None:
    report = execute_measure(
        full_session(with_rest=False).inputs(),
        MeasureOptions(),
        app_version="0.1.0",
        now=fixed_now,
        profile_id_factory=fixed_profile_id,
    ).report

    markdown = render_markdown(report)

    assert "n/d" in markdown
    assert "`MISSING_REST_SEGMENT`" in markdown
    assert "**fail**" in markdown
    assert "Não derivado" in markdown


def test_validate_report_exige_relatorio_valido_para_renderizar() -> None:
    with pytest.raises(InvalidReportError):
        render_markdown({"report_kind": "calibration-metrics"})


def test_relogio_fixo_alimenta_created_at_do_relatorio() -> None:
    assert outcome().report["created_at"] == FIXED_NOW.astimezone(UTC).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
