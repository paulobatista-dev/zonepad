from __future__ import annotations

import math
from collections.abc import Callable, Iterator
from dataclasses import replace
from typing import Any

import pytest
from synthetic_capture import (
    DEFAULT_CIRCLES,
    Recorder,
    fixed_now,
    fixed_profile_id,
    full_session,
)

from zonepad.application.measure import (
    MeasureInputs,
    MeasureOptions,
    MeasureOutcome,
    execute_measure,
    measure,
    save_profile,
)
from zonepad.application.report import dumps_report, render_markdown
from zonepad.domain.errors import MeasurementInputError
from zonepad.domain.findings import STRICT_BLOCKING, Finding
from zonepad.domain.metrics import MetricsConfig, ProtocolParams, Thresholds
from zonepad.infrastructure.json_profile_store import JsonProfileStore

# Tabela do catálogo da spec: código -> (severidades possíveis, bloqueia em --strict).
SPEC_CATALOG: dict[str, tuple[frozenset[str], bool]] = {
    "MISSING_REST_SEGMENT": (frozenset({"error"}), True),
    "REST_TOO_SHORT": (frozenset({"warning", "error"}), True),
    "MISSING_CIRCLE_SEGMENT": (frozenset({"error", "warning"}), True),
    "INSUFFICIENT_CIRCLE_POINTS": (frozenset({"warning"}), True),
    "INSUFFICIENT_CIRCLE_LAPS": (frozenset({"warning", "error"}), True),
    "CIRCLE_DIRECTION_INCONSISTENT": (frozenset({"warning"}), True),
    "MISSING_TRIGGER_SEGMENT": (frozenset({"error"}), True),
    "INSUFFICIENT_TRIGGER_CYCLES": (frozenset({"warning", "error"}), True),
    "AXIS_MISSING": (frozenset({"warning", "error"}), True),
    "DEGENERATE_RANGE": (frozenset({"error"}), True),
    "CENTER_OUTSIDE_RANGE": (frozenset({"error"}), True),
    "DEADZONE_CLAMPED": (frozenset({"warning"}), True),
    "HIGH_DRIFT": (frozenset({"warning"}), True),
    "HIGH_NOISE": (frozenset({"warning"}), True),
    "MAPPING_RANGE_EXCEEDED": (frozenset({"warning"}), True),
    "DUPLICATE_TIMESTAMP": (frozenset({"warning"}), True),
    "RATE_OUT_OF_TOLERANCE": (frozenset({"warning"}), True),
    "LOW_CIRCULARITY": (frozenset({"warning"}), False),
    "SATURATION_HIGH": (frozenset({"warning"}), False),
    "LOW_TRIGGER_R2": (frozenset({"info"}), False),
    "HIGH_HYSTERESIS": (frozenset({"info"}), False),
    "CENTER_FAR_FROM_MAPPING": (frozenset({"info"}), False),
    "UNMAPPED_CHANNEL_IGNORED": (frozenset({"info"}), False),
    "NOMINAL_RATE_UNKNOWN": (frozenset({"info"}), False),
    "RATE_UNAVAILABLE": (frozenset({"info"}), False),
}


def codes(findings: tuple[Finding, ...]) -> set[str]:
    return {f.code for f in findings}


def find(findings: tuple[Finding, ...], code: str, severity: str | None = None) -> list[Finding]:
    return [f for f in findings if f.code == code and (severity is None or f.severity == severity)]


def run(rec: Recorder, config: MetricsConfig | None = None, **manifest_extra: Any):
    return measure(rec.inputs(config, **manifest_extra)).metrics


def execute(
    rec: Recorder,
    *,
    strict: bool = False,
    save: bool = False,
    store: JsonProfileStore | None = None,
    config: MetricsConfig | None = None,
) -> MeasureOutcome:
    outcome = execute_measure(
        rec.inputs(config),
        MeasureOptions(strict=strict, save_profile=save),
        app_version="0.1.0",
        now=fixed_now,
        profile_id_factory=fixed_profile_id,
    )
    if store is not None:
        save_profile(store, outcome)
    return outcome


# ------------------------------------------------------------------ happy path and layers


def test_sessao_completa_passa_sem_achados_bloqueantes() -> None:
    metrics = run(full_session(), nominal_rate_hz=125.0)

    assert metrics.status == "pass"
    assert not [f for f in metrics.findings if f.severity != "info"]
    assert metrics.capture.effective_rate_hz == pytest.approx(125.0)
    assert metrics.sticks["left"].circle.valid_laps == 6
    assert metrics.triggers["right"].cycles_valid == 5


def test_metricas_usam_a_camada_normalizada_e_o_raw_fica_em_diagnostico() -> None:
    metrics = run(full_session(rest_values={"lx": 0.1, "ly": -0.1}))

    assert metrics.sticks["left"].center == pytest.approx((0.1, -0.1), abs=1e-9)
    raw = metrics.raw["lx"]
    assert raw.mapping == {"minimum": -1_000_000, "center": 0, "maximum": 1_000_000}
    assert raw.rest_median == 100_000
    assert raw.out_of_range_ratio == 0.0
    assert raw.lsb_normalized == pytest.approx(1e-6)


def test_frames_fora_de_segmentos_e_aquecimento_nao_entram_nas_metricas() -> None:
    rec = Recorder()
    rec.hold(1.0, lx=0.9)  # fora de qualquer segmento
    rec.rest(5.0, 1.0, lx=0.0)
    rec.pause(0)
    rec.circle("left", "cw")
    rec.circle("left", "ccw")
    # warmup do repouso com valor diferente: não deve alterar o centro
    for frame in rec.frames[125 : 125 + 125]:
        frame["axes"]["lx"] = 500_000

    metrics = run(rec)

    assert metrics.sticks["left"].center == pytest.approx((0.0, 0.0), abs=1e-9)
    assert metrics.capture.frames_outside_segments == 125 + 1 + 1  # 1 s + 2 frames de fechamento


def test_segmento_nao_declarado_nao_e_inferido() -> None:
    rec = full_session(circles=(), sweeps=())

    metrics = run(rec)

    assert codes(metrics.findings) >= {"MISSING_CIRCLE_SEGMENT", "MISSING_TRIGGER_SEGMENT"}


# -------------------------------------------------------------------- findings catalog


def _scenario_missing_rest() -> Recorder:
    return full_session(with_rest=False)


def _scenario_rest_warning() -> Recorder:
    return full_session(rest_s=3.0)  # efetivo 2 s


def _scenario_rest_error() -> Recorder:
    return full_session(rest_s=1.5)  # efetivo 0,5 s


def _scenario_missing_circle_error() -> Recorder:
    return full_session(circles=(("left", "cw", {}), ("left", "ccw", {})))


def _scenario_missing_circle_warning() -> Recorder:
    return full_session(circles=(("left", "cw", {}), ("right", "cw", {}), ("right", "ccw", {})))


def _scenario_few_points() -> Recorder:
    circles = (("left", "cw", {}), ("left", "ccw", {"points_per_lap": 80})) + DEFAULT_CIRCLES[2:]
    return full_session(circles=circles)


def _scenario_laps_warning() -> Recorder:
    circles = (("left", "cw", {}), ("left", "ccw", {"laps": 1})) + DEFAULT_CIRCLES[2:]
    return full_session(circles=circles)


def _scenario_laps_error() -> Recorder:
    circles = (
        ("left", "cw", {"points_per_lap": 80}),
        ("left", "ccw", {"points_per_lap": 80}),
    ) + DEFAULT_CIRCLES[2:]
    return full_session(circles=circles)


def _scenario_direction() -> Recorder:
    circles = (("left", "cw", {}), ("left", "ccw", {"sign": -1})) + DEFAULT_CIRCLES[2:]
    return full_session(circles=circles)


def _scenario_missing_trigger() -> Recorder:
    return full_session(sweeps=(("left", {}),))


def _scenario_cycles_warning() -> Recorder:
    return full_session(sweeps=(("left", {"cycles": 2}), ("right", {})))


def _scenario_cycles_error() -> Recorder:
    return full_session(sweeps=(("left", {"peak": 0.7}), ("right", {})))


def _scenario_axis_error() -> Recorder:
    return full_session(drop=frozenset({"ry"}))


def _scenario_axis_warning() -> Recorder:
    rec = full_session()
    for frame in rec.frames[400:410]:  # 10 frames no repouso efetivo
        del frame["axes"]["ly"]
    return rec


def _scenario_degenerate() -> Recorder:
    circles = (("left", "cw", {"radius": (0.4, 0.4)}), ("left", "ccw", {"radius": (0.4, 0.4)}))
    return full_session(circles=circles + DEFAULT_CIRCLES[2:])


def _scenario_center_outside() -> Recorder:
    circles = (
        ("left", "cw", {"center": (0.6, 0.0), "radius": (0.5, 0.5)}),
        ("left", "ccw", {"center": (0.6, 0.0), "radius": (0.5, 0.5)}),
    )
    return full_session(circles=circles + DEFAULT_CIRCLES[2:])


def _alternating(amplitude: float) -> Callable[[int], dict[str, float]]:
    return lambda i: {"lx": amplitude if i % 2 else -amplitude}


def _scenario_clamped() -> Recorder:
    return full_session(rest_noise=_alternating(0.8))


def _scenario_drift() -> Recorder:
    return full_session(rest_noise=lambda i: {"lx": 0.09 * i / 624})


def _scenario_noise() -> Recorder:
    return full_session(rest_noise=_alternating(0.01))


def _scenario_range_exceeded() -> Recorder:
    rec = full_session()
    rec.frames[2000]["axes"]["lx"] = 1_100_000
    return rec


def _scenario_duplicate() -> Recorder:
    rec = full_session()
    rec.frames[2000]["timestamp_ns"] = rec.frames[1999]["timestamp_ns"]
    return rec


def _scenario_low_circularity() -> Recorder:
    circles = (
        ("left", "cw", {"radius": (0.95, 0.6)}),
        ("left", "ccw", {"radius": (0.95, 0.6)}),
    )
    return full_session(circles=circles + DEFAULT_CIRCLES[2:])


def _scenario_saturation() -> Recorder:
    circles = (
        ("left", "cw", {"radius": (1.5, 1.5)}),
        ("left", "ccw", {"radius": (1.5, 1.5)}),
    )
    return full_session(circles=circles + DEFAULT_CIRCLES[2:])


def _scenario_hysteresis() -> Recorder:
    shaped = {"down_curve": lambda x: x + 0.1 * math.sin(math.pi * x)}
    return full_session(sweeps=(("left", shaped), ("right", {})))


def _scenario_center_far() -> Recorder:
    return full_session(rest_values={"rx": 0.2})


def _scenario_unmapped() -> Recorder:
    return full_session(extra_axes={"hat": 1})


CATALOG_SCENARIOS: list[tuple[str, str, Callable[[], Recorder], dict[str, Any]]] = [
    ("MISSING_REST_SEGMENT", "error", _scenario_missing_rest, {}),
    ("REST_TOO_SHORT", "warning", _scenario_rest_warning, {}),
    ("REST_TOO_SHORT", "error", _scenario_rest_error, {}),
    ("MISSING_CIRCLE_SEGMENT", "error", _scenario_missing_circle_error, {}),
    ("MISSING_CIRCLE_SEGMENT", "warning", _scenario_missing_circle_warning, {}),
    ("INSUFFICIENT_CIRCLE_POINTS", "warning", _scenario_few_points, {}),
    ("INSUFFICIENT_CIRCLE_LAPS", "warning", _scenario_laps_warning, {}),
    ("INSUFFICIENT_CIRCLE_LAPS", "error", _scenario_laps_error, {}),
    ("CIRCLE_DIRECTION_INCONSISTENT", "warning", _scenario_direction, {}),
    ("MISSING_TRIGGER_SEGMENT", "error", _scenario_missing_trigger, {}),
    ("INSUFFICIENT_TRIGGER_CYCLES", "warning", _scenario_cycles_warning, {}),
    ("INSUFFICIENT_TRIGGER_CYCLES", "error", _scenario_cycles_error, {}),
    ("AXIS_MISSING", "error", _scenario_axis_error, {}),
    ("AXIS_MISSING", "warning", _scenario_axis_warning, {}),
    ("DEGENERATE_RANGE", "error", _scenario_degenerate, {}),
    ("CENTER_OUTSIDE_RANGE", "error", _scenario_center_outside, {}),
    ("DEADZONE_CLAMPED", "warning", _scenario_clamped, {}),
    ("HIGH_DRIFT", "warning", _scenario_drift, {}),
    ("HIGH_NOISE", "warning", _scenario_noise, {}),
    ("MAPPING_RANGE_EXCEEDED", "warning", _scenario_range_exceeded, {}),
    ("DUPLICATE_TIMESTAMP", "warning", _scenario_duplicate, {}),
    ("RATE_OUT_OF_TOLERANCE", "warning", full_session, {"nominal_rate_hz": 1000.0}),
    ("LOW_CIRCULARITY", "warning", _scenario_low_circularity, {}),
    ("SATURATION_HIGH", "warning", _scenario_saturation, {}),
    ("HIGH_HYSTERESIS", "info", _scenario_hysteresis, {}),
    ("CENTER_FAR_FROM_MAPPING", "info", _scenario_center_far, {}),
    ("UNMAPPED_CHANNEL_IGNORED", "info", _scenario_unmapped, {}),
    ("NOMINAL_RATE_UNKNOWN", "info", full_session, {}),
]


@pytest.mark.parametrize(
    ("code", "severity", "scenario", "extra"),
    CATALOG_SCENARIOS,
    ids=[f"{c}-{s}-{i}" for i, (c, s, _, _) in enumerate(CATALOG_SCENARIOS)],
)
def test_cada_codigo_do_catalogo_e_produzido_com_severidade_da_spec(
    code: str, severity: str, scenario: Callable[[], Recorder], extra: dict[str, Any]
) -> None:
    metrics = run(scenario(), **extra)

    produced = find(metrics.findings, code, severity)
    assert produced, [(f.code, f.severity) for f in metrics.findings]
    assert severity in SPEC_CATALOG[code][0]
    assert all(f.strict_blocking is SPEC_CATALOG[code][1] for f in produced)


def test_codigos_com_configuracao_especifica() -> None:
    low_r2 = run(
        full_session(sweeps=(("left", {"down_curve": lambda x: x * x}), ("right", {}))),
        MetricsConfig(thresholds=Thresholds(trigger_r2_min=0.9999)),
    )
    unavailable = run(
        full_session(), MetricsConfig(protocol=ProtocolParams(rate_min_pairs=100_000))
    )
    trigger_span = run(
        full_session(sweeps=(("left", {"peak": 0.9}), ("right", {}))),
        MetricsConfig(protocol=ProtocolParams(trigger_min_span=0.95)),
    )

    assert find(low_r2.findings, "LOW_TRIGGER_R2", "info")
    assert find(unavailable.findings, "RATE_UNAVAILABLE", "info")
    assert find(trigger_span.findings, "DEGENERATE_RANGE", "error")


def test_catalogo_do_codigo_coincide_com_a_tabela_da_spec() -> None:
    assert {code: blocking for code, (_, blocking) in SPEC_CATALOG.items()} == STRICT_BLOCKING


def test_todo_codigo_do_catalogo_tem_cenario() -> None:
    covered = {code for code, _, _, _ in CATALOG_SCENARIOS} | {"LOW_TRIGGER_R2", "RATE_UNAVAILABLE"}
    assert covered == set(STRICT_BLOCKING)


def test_achados_seguem_ordem_estavel_de_severidade_codigo_e_metrica() -> None:
    metrics = run(_scenario_missing_rest())

    keys = [
        ({"error": 0, "warning": 1, "info": 2}[f.severity], f.code, f.metric or "")
        for f in metrics.findings
    ]
    assert keys == sorted(keys)


@pytest.mark.parametrize(
    ("scenario", "status"),
    [
        (full_session, "pass"),
        (_scenario_noise, "warn"),
        (_scenario_missing_rest, "fail"),
        (_scenario_hysteresis, "pass"),  # só achados info
    ],
)
def test_status_deriva_dos_achados_e_info_nao_o_altera(
    scenario: Callable[[], Recorder], status: str
) -> None:
    assert run(scenario()).status == status


def test_mensagens_dos_achados_estao_em_pt_br_e_indicam_a_acao() -> None:
    metrics = run(_scenario_missing_rest())

    messages = " ".join(f.message for f in metrics.findings)
    assert "nenhum segmento rest" in messages
    assert "grave 5 s" in messages


# --------------------------------------------------------------------- null coverage


def _null_paths(value: Any, prefix: str = "") -> Iterator[str]:
    if isinstance(value, dict):
        for key, item in value.items():
            yield from _null_paths(item, f"{prefix}.{key}" if prefix else key)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _null_paths(item, f"{prefix}[{index}]")
    elif value is None:
        yield prefix


@pytest.mark.parametrize(
    "scenario",
    [
        full_session,
        _scenario_missing_rest,
        _scenario_rest_warning,
        _scenario_rest_error,
        _scenario_missing_circle_error,
        _scenario_laps_error,
        _scenario_missing_trigger,
        _scenario_cycles_error,
        _scenario_axis_error,
        _scenario_center_outside,
    ],
)
def test_nenhuma_metrica_nula_fica_sem_achado_que_a_nomeie(
    scenario: Callable[[], Recorder],
) -> None:
    outcome = execute(scenario())
    report = outcome.report
    named = [f["metric"] for f in report["quality"]["findings"] if f["metric"]]
    if "protocol.segments" in named:  # MISSING_REST_SEGMENT cobre tudo que depende do repouso
        named += ["sticks", "triggers"]
    measured = {k: report[k] for k in ("sticks", "triggers", "capture")}

    uncovered = [
        path
        for path in _null_paths(measured)
        if not any(path == m or path.startswith(m + ".") or path.startswith(m + "[") for m in named)
        and not path.endswith("profile_id")
        and path != "capture.connection"
    ]

    assert uncovered == []


# ------------------------------------------------------------------- input validation


def test_captura_vazia_e_rejeitada_antes_de_medir() -> None:
    rec = full_session()
    inputs = rec.inputs()
    empty = MeasureInputs(
        (),
        inputs.capture_file,
        inputs.capture_sha256,
        inputs.manifest,
        inputs.axis_ranges,
        inputs.trigger_ranges,
        inputs.mapping_sha256,
    )

    with pytest.raises(MeasurementInputError, match=r"\[EMPTY_CAPTURE\]"):
        measure(empty)


@pytest.mark.parametrize(
    ("change", "fragment"),
    [
        ({"capture_file": "outra.jsonl"}, "capture_file"),
        ({"capture_sha256": "0" * 64}, "capture_sha256"),
    ],
)
def test_manifesto_incoerente_com_a_captura_e_rejeitado(
    change: dict[str, Any], fragment: str
) -> None:
    rec = full_session()
    base = rec.inputs()
    if "capture_file" in change:
        inputs = replace(base, capture_file="outra.jsonl")
    else:
        inputs = replace(base, manifest=rec.manifest(capture_sha256="0" * 64))

    with pytest.raises(MeasurementInputError, match=fragment):
        measure(inputs)


def test_device_id_divergente_do_manifesto_e_rejeitado() -> None:
    rec = full_session()
    for frame in rec.frames:
        frame["device_id"] = "event9"

    with pytest.raises(MeasurementInputError, match="device_id"):
        measure(rec.inputs())


def test_segmento_fora_da_captura_e_rejeitado() -> None:
    rec = full_session()
    rec.segments[-1]["end_ns"] = rec.frames[-1]["timestamp_ns"] + 2

    with pytest.raises(MeasurementInputError, match=r"segments\[\d+\].*fora da captura"):
        measure(rec.inputs())


def test_timestamp_decrescente_no_dominio_de_aplicacao_e_rejeitado() -> None:
    rec = full_session()
    rec.frames[100]["timestamp_ns"] = 0

    with pytest.raises(MeasurementInputError, match=r"\[NON_MONOTONIC_TIME\] frame 101"):
        measure(rec.inputs())


# -------------------------------------------------------------- use case and strict


def test_repouso_curto_gera_perfil_sem_strict_e_bloqueia_com_strict(tmp_path: Any) -> None:
    store = JsonProfileStore(tmp_path / "profiles")

    relaxed = execute(_scenario_rest_warning(), save=True, store=store)
    strict = execute(_scenario_rest_warning(), strict=True, save=True, store=store)

    assert relaxed.exit_reason == "ok"
    assert relaxed.profile is not None
    assert store.list_profiles() == (relaxed.profile.profile_id,)
    assert strict.exit_reason == "strict_blocked"
    assert strict.profile is None
    assert strict.report["profile_summary"]["profile_id"] is None
    assert len(store.list_profiles()) == 1  # o strict não gravou outro perfil


def test_strict_ignora_achados_nao_bloqueantes() -> None:
    outcome = execute(_scenario_low_circularity(), strict=True)

    assert find(outcome.metrics.findings, "LOW_CIRCULARITY")
    assert outcome.exit_reason == "ok"


def test_sem_strict_status_fail_ainda_sai_com_ok_mas_save_profile_nao_deriva(tmp_path: Any) -> None:
    store = JsonProfileStore(tmp_path / "profiles")

    plain = execute(_scenario_missing_circle_error())
    saving = execute(_scenario_missing_circle_error(), save=True, store=store)

    assert plain.exit_reason == "ok"
    assert plain.report["quality"]["status"] == "fail"
    assert plain.report["profile_summary"]["derived"] is False
    assert saving.exit_reason == "profile_not_derivable"
    assert saving.profile is None
    assert store.list_profiles() == ()
    assert "MISSING_CIRCLE_SEGMENT" in (saving.message or "")


def test_perfil_salvo_carrega_no_store_e_reflete_as_metricas(tmp_path: Any) -> None:
    store = JsonProfileStore(tmp_path / "profiles")
    rec = full_session(rest_values={"lx": 0.1})

    outcome = execute(rec, save=True, store=store)

    assert outcome.profile is not None
    loaded = store.load(outcome.profile.profile_id)
    assert loaded == outcome.profile
    assert loaded.sticks["left"].center[0] == pytest.approx(0.1, abs=1e-6)
    assert loaded.schema_version == 1


def test_relatorio_e_perfil_sao_deterministicos_com_relogio_e_uuid_injetados(tmp_path: Any) -> None:
    first = execute(full_session(), save=True, store=JsonProfileStore(tmp_path / "a"))
    second = execute(full_session(), save=True, store=JsonProfileStore(tmp_path / "b"))

    assert dumps_report(first.report) == dumps_report(second.report)
    assert (tmp_path / "a" / f"{fixed_profile_id()}.json").read_bytes() == (
        tmp_path / "b" / f"{fixed_profile_id()}.json"
    ).read_bytes()


def test_strict_bloqueado_nao_declara_perfil_derivado_e_o_markdown_explica() -> None:
    blocked = execute(_scenario_rest_warning(), strict=True, save=True)
    unsaved = execute(full_session())

    assert blocked.report["profile_summary"]["derived"] is False
    assert "bloqueio por --strict" in render_markdown(blocked.report)
    assert unsaved.report["profile_summary"]["derived"] is True
    assert "use --save-profile" in render_markdown(unsaved.report)


def test_sem_repouso_emite_um_unico_achado_e_sem_cascata_de_voltas_ou_ciclos() -> None:
    metrics = run(_scenario_missing_rest())

    rest = find(metrics.findings, "MISSING_REST_SEGMENT")
    assert [f.metric for f in rest] == ["protocol.segments"]
    assert not find(metrics.findings, "INSUFFICIENT_CIRCLE_LAPS", "error")
    assert not find(metrics.findings, "INSUFFICIENT_TRIGGER_CYCLES")
