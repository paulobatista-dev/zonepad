from __future__ import annotations

import math
import statistics
from collections.abc import Sequence

import pytest
from synthetic_capture import SCALE, Recorder

from zonepad.domain.metrics import (
    ChannelCoverage,
    CircleStickWindow,
    DeadzoneParams,
    MetricsConfig,
    ProtocolParams,
    RestStickWindow,
    RestTriggerWindow,
    StickMetrics,
    StickSamples,
    Thresholds,
    TriggerMetrics,
    TriggerSamples,
    measure_capture,
    measure_stick,
    measure_trigger,
    median,
    percentile,
)

CONFIG = MetricsConfig()
RATE_HZ = 125.0
AXES = ("lx", "ly")


def ns(index: int, rate_hz: float = RATE_HZ) -> int:
    return round(index * 1e9 / rate_hz)


def samples(points: Sequence[tuple[float, float]], rate_hz: float = RATE_HZ) -> StickSamples:
    return StickSamples(
        tuple(ns(i, rate_hz) for i in range(len(points))),
        tuple(p[0] for p in points),
        tuple(p[1] for p in points),
    )


def rest_window(points: Sequence[tuple[float, float]], rate_hz: float = RATE_HZ) -> RestStickWindow:
    return RestStickWindow(0, ns(len(points), rate_hz), samples(points, rate_hz))


def circle_points(
    laps: int,
    per_lap: int,
    radius: tuple[float, float] = (0.9, 0.9),
    turn: int = 1,
    polar: bool = False,
) -> list[tuple[float, float]]:
    """``laps`` complete turns plus two closing steps so floor(total / 2 pi) == laps."""
    points = []
    for step in range(laps * per_lap + 2):
        angle = turn * 2.0 * math.pi * step / per_lap
        if polar:  # radius of the ellipse at the polar angle (uniform in polar angle)
            a, b = radius
            r = a * b / math.hypot(b * math.cos(angle), a * math.sin(angle))
            points.append((r * math.cos(angle), r * math.sin(angle)))
        else:
            points.append((radius[0] * math.cos(angle), radius[1] * math.sin(angle)))
    return points


def stick(
    rest: Sequence[tuple[float, float]] | None = None,
    circles: Sequence[CircleStickWindow] = (),
    config: MetricsConfig = CONFIG,
) -> StickMetrics:
    windows = [rest_window(rest)] if rest is not None else []
    return measure_stick(AXES, windows, circles, ChannelCoverage(), config)


def circle_window(
    direction: str = "cw", laps: int = 3, per_lap: int = 125, **options: object
) -> CircleStickWindow:
    return CircleStickWindow(
        direction,
        samples(circle_points(laps, per_lap, **options)),  # type: ignore[arg-type]
    )


def trigger(rec: Recorder, name: str = "lt", config: MetricsConfig = CONFIG) -> TriggerMetrics:
    frames = rec.frames
    values = TriggerSamples(
        tuple(f["timestamp_ns"] for f in frames), tuple(f["triggers"][name] / SCALE for f in frames)
    )
    rest = RestTriggerWindow(0, 1_000_000_000, TriggerSamples((0, 1), (0.0, 0.0)))
    return measure_trigger([rest], [values], ChannelCoverage(), config)


# ----------------------------------------------------------------------------- statistics


def test_percentil_tipo_7_confere_statistics_quantiles_inclusive() -> None:
    values = [3.0, 9.0, 1.0, 7.0, 5.0, 11.0, 2.0]
    cuts = statistics.quantiles(values, n=100, method="inclusive")
    for q in (0.05, 0.25, 0.5, 0.95, 0.99):
        assert percentile(values, q) == pytest.approx(cuts[round(q * 100) - 1], abs=1e-12)


def test_mediana_de_quantidade_par_media_os_dois_centrais() -> None:
    assert median([4.0, 1.0, 3.0, 2.0]) == pytest.approx(2.5)
    assert median([7.0]) == 7.0


@pytest.mark.parametrize(("values", "q"), [([], 0.5), ([1.0], -0.1), ([1.0], 1.1)])
def test_percentil_rejeita_entrada_invalida(values: list[float], q: float) -> None:
    with pytest.raises(ValueError):
        percentile(values, q)


# ---------------------------------------------------------------------------- stick rest


def test_centro_e_drift_de_repouso_constante() -> None:
    result = stick(rest=[(0.1, -0.1)] * 500)

    assert result.center == pytest.approx((0.1, -0.1), abs=1e-9)
    assert result.rest.drift == pytest.approx(0.0, abs=1e-9)
    assert result.rest.noise is not None
    assert result.rest.noise.rms_xy == pytest.approx(0.0, abs=1e-9)
    assert result.rest.valid_blocks == 4


def test_ruido_alternado_em_x_mede_rms_p2p_e_raio() -> None:
    points = [(0.01 if i % 2 else -0.01, 0.0) for i in range(500)]

    noise = stick(rest=points).rest.noise

    assert noise is not None
    assert noise.rms_xy == pytest.approx(0.01, abs=1e-9)
    assert noise.rms_x == pytest.approx(0.01, abs=1e-9)
    assert noise.rms_y == pytest.approx(0.0, abs=1e-9)
    assert noise.p2p_x == pytest.approx(0.02, abs=1e-9)
    assert noise.radius_max == pytest.approx(0.01, abs=1e-9)
    assert noise.radius_p99 == pytest.approx(0.01, abs=1e-9)


def test_centro_alternado_com_contagem_par_fica_em_zero() -> None:
    points = [(0.01 if i % 2 else -0.01, 0.0) for i in range(500)]
    center = stick(rest=points).center
    assert center is not None
    assert center[0] == pytest.approx(0.0, abs=1e-9)


def test_jitter_mede_passos_entre_amostras_vizinhas() -> None:
    points = [(0.01 if i % 2 else -0.01, 0.0) for i in range(500)]

    jitter = stick(rest=points).rest.jitter

    assert jitter is not None
    assert jitter.mean == pytest.approx(0.02, abs=1e-9)
    assert jitter.max == pytest.approx(0.02, abs=1e-9)


def test_drift_separa_deriva_lenta_do_ruido_rapido() -> None:
    # Rampa de 0.06 em 4 s: mediana dos blocos de 1 s = 0.0075..0.0525 contra c = 0.03.
    # A spec cita rampa de 0.03, mas pela fórmula max||m_k - c|| ela daria só 0.01125.
    points = [(0.06 * i / 499, 0.0) for i in range(500)]

    result = stick(rest=points)

    assert result.rest.drift == pytest.approx(0.0225, abs=1e-3)
    assert result.rest.drift is not None and result.rest.drift >= CONFIG.thresholds.drift_max


def test_drift_nulo_com_menos_de_dois_blocos_validos() -> None:
    result = stick(rest=[(0.0, 0.0)] * 150)  # 1.2 s -> um único bloco de 1 s

    assert result.rest.valid_blocks == 1
    assert result.rest.drift is None


def test_blocos_com_poucos_frames_sao_descartados() -> None:
    # 4 s com 3 frames por bloco: nenhum bloco atinge o mínimo de 5 frames.
    rest = RestStickWindow(
        0,
        4_000_000_000,
        StickSamples(
            tuple(b * 1_000_000_000 + j * 100_000_000 for b in range(4) for j in range(3)),
            (0.0,) * 12,
            (0.0,) * 12,
        ),
    )

    result = measure_stick(AXES, [rest], [], ChannelCoverage(), CONFIG)

    assert result.rest.valid_blocks == 0
    assert result.rest.drift is None


def test_deslocamento_do_centro_entre_segmentos_de_repouso() -> None:
    first = rest_window([(0.0, 0.0)] * 300)
    second = rest_window([(0.04, 0.0)] * 300)

    result = measure_stick(AXES, [first, second], [], ChannelCoverage(), CONFIG)

    assert result.center == pytest.approx((0.02, 0.0), abs=1e-9)
    assert result.center_segment_max_shift == pytest.approx(0.02, abs=1e-9)


# ---------------------------------------------------------------------- range and circle


def test_circularidade_e_raio_medio_de_circulo_perfeito() -> None:
    result = stick(rest=[(0.0, 0.0)] * 500, circles=[circle_window()])

    circle = result.circle
    assert circle.valid_laps_cw == 3
    assert circle.circularity_median == pytest.approx(1.0, abs=1e-9)
    assert circle.mean_radius_median == pytest.approx(0.9, abs=1e-9)
    assert circle.mean_radius_worst == pytest.approx(0.9, abs=1e-9)


def test_gate_eliptico_reduz_circularidade_para_cerca_de_metade() -> None:
    window = circle_window(per_lap=240, radius=(0.9, 0.45), polar=True)

    result = stick(rest=[(0.0, 0.0)] * 500, circles=[window])

    assert result.circle.circularity_median == pytest.approx(0.5, abs=0.02)


def test_voltas_validas_por_direcao_e_consistencia_de_sentido() -> None:
    cw = circle_window("cw", turn=-1)
    ccw = circle_window("ccw", turn=1)

    result = stick(rest=[(0.0, 0.0)] * 500, circles=[cw, ccw])

    assert (result.circle.valid_laps_cw, result.circle.valid_laps_ccw) == (3, 3)
    assert result.circle.direction_inconsistent is False


@pytest.mark.parametrize(
    ("first", "second"),
    [(("cw", -1), ("ccw", -1)), (("cw", -1), ("cw", 1))],
    ids=["mesmo-sentido-com-rotulos-opostos", "mesmo-rotulo-com-sentidos-opostos"],
)
def test_sentido_observado_incoerente_com_rotulos(
    first: tuple[str, int], second: tuple[str, int]
) -> None:
    windows = [circle_window(first[0], turn=first[1]), circle_window(second[0], turn=second[1])]

    result = stick(rest=[(0.0, 0.0)] * 500, circles=windows)

    assert result.circle.direction_inconsistent is True


def test_volta_com_poucos_pontos_e_rejeitada_da_circularidade() -> None:
    result = stick(rest=[(0.0, 0.0)] * 500, circles=[circle_window(per_lap=80)])

    assert result.circle.rejected_laps == 3
    assert result.circle.valid_laps == 0
    assert result.circle.circularity_median is None


def test_volta_com_setor_de_15_graus_sem_frames_e_rejeitada() -> None:
    # 3 voltas de 250 frames (> 100), mas o setor em torno de 0 graus nunca é visitado.
    points = [p for p in circle_points(3, 250) if abs(math.degrees(math.atan2(p[1], p[0]))) > 8.0]
    window = CircleStickWindow("cw", samples(points))

    result = stick(rest=[(0.0, 0.0)] * 500, circles=[window])

    assert result.circle.valid_laps == 0
    assert result.circle.rejected_laps >= 1


def test_range_usa_percentis_e_ignora_frame_espurio_mas_o_reporta_como_pior_caso() -> None:
    points = circle_points(3, 125)
    points.insert(100, (1.0, 0.0))
    window = CircleStickWindow("cw", samples(points))

    result = stick(rest=[(0.0, 0.0)] * 500, circles=[window])

    assert result.axis_range is not None
    assert result.axis_range.max[0] < 0.9001
    assert result.axis_range.observed_max[0] == 1.0
    assert result.axis_range.span[0] == pytest.approx(1.8, abs=2e-3)
    assert result.axis_range.symmetry[0] == pytest.approx(1.0, abs=1e-3)


def test_simetria_nula_quando_centro_fica_fora_do_range() -> None:
    window = circle_window(radius=(0.3, 0.9))
    result = stick(rest=[(-0.5, 0.0)] * 500, circles=[window])

    assert result.axis_range is not None
    assert result.axis_range.symmetry[0] is None


def test_saturacao_conta_frames_no_extremo() -> None:
    points = [(1.0, 0.0)] * 25 + [(0.0, 0.5)] * 75
    window = CircleStickWindow("cw", samples(points))

    result = stick(rest=[(0.0, 0.0)] * 500, circles=[window])

    assert result.circle.saturation_ratio == pytest.approx(0.25)


# ------------------------------------------------------------------------- stick deadzone


def _noisy_rest(radius: float) -> list[tuple[float, float]]:
    return [(radius if i % 2 else -radius, 0.0) for i in range(500)]


def test_deadzone_sugerida_e_fator_vezes_p99_do_ruido_calibrado() -> None:
    result = stick(rest=_noisy_rest(0.04), circles=[circle_window()])

    assert result.deadzone is not None
    assert result.axis_range is not None
    half_range = result.axis_range.max[0]  # centro em 0, círculo centrado
    expected = max(1.5 * 0.04 / half_range, 0.02)
    assert result.deadzone.value == pytest.approx(expected, rel=1e-3)
    assert result.deadzone.mode == "cut"
    assert result.deadzone.clamped is False


def test_deadzone_sem_ruido_usa_o_piso() -> None:
    result = stick(rest=[(0.0, 0.0)] * 500, circles=[circle_window()])

    assert result.deadzone is not None
    assert result.deadzone.value == pytest.approx(0.02)


def test_deadzone_cresce_quando_o_semi_range_e_curto() -> None:
    full = stick(rest=_noisy_rest(0.04), circles=[circle_window(radius=(1.0, 1.0))])
    short = stick(rest=_noisy_rest(0.04), circles=[circle_window(radius=(0.8, 0.8))])

    assert full.deadzone is not None and short.deadzone is not None
    assert short.deadzone.basis_p99 == pytest.approx(0.04 / 0.8, rel=2e-3)
    assert short.deadzone.value > full.deadzone.value


def test_deadzone_e_limitada_a_095_e_sinalizada() -> None:
    result = stick(rest=_noisy_rest(0.8), circles=[circle_window()])

    assert result.deadzone is not None
    assert result.deadzone.value == 0.95
    assert result.deadzone.clamped is True


# --------------------------------------------------------------------------- triggers


def test_rampa_linear_tem_r2_um_e_erro_nulo() -> None:
    rec = Recorder()
    rec.sweep("left")

    result = trigger(rec)

    assert result.cycles_valid == 5
    assert result.linearity_r2 is not None
    assert result.linearity_r2.worst == pytest.approx(1.0, abs=1e-9)
    assert result.linearity_max_error is not None
    assert result.linearity_max_error.worst == pytest.approx(0.0, abs=1e-9)
    assert result.max == pytest.approx(1.0)
    assert result.span == pytest.approx(1.0)
    assert result.max_dispersion == pytest.approx(0.0, abs=1e-9)


def test_histerese_mede_diferenca_entre_subida_e_descida() -> None:
    rec = Recorder()
    rec.sweep("left", down_curve=lambda x: x + 0.05 * math.sin(math.pi * x))

    result = trigger(rec)

    assert result.hysteresis is not None
    assert result.hysteresis.median == pytest.approx(0.042, abs=0.002)


def test_offset_vertical_puro_nao_gera_histerese_por_causa_das_ancoras() -> None:
    # Limitação de princípio (D11): âncoras 0,05/0,95 absorvem deslocamentos verticais puros.
    rec = Recorder()
    rec.sweep("left", down_curve=lambda x: x - 0.05)

    result = trigger(rec)

    assert result.hysteresis is not None
    assert result.hysteresis.median == pytest.approx(0.0, abs=0.01)


def test_pico_abaixo_do_minimo_invalida_o_ciclo() -> None:
    rec = Recorder()
    rec.sweep("left", peak=0.7)

    result = trigger(rec)

    assert result.cycles_detected == 5
    assert result.cycles_valid == 0
    assert result.max is None


def test_ciclo_sem_fim_no_segmento_e_descartado() -> None:
    rec = Recorder()
    rec.hold(0.5, lt=0.0)
    for index in range(250):
        rec.tick(lt=index / 250)
    rec.hold(1.0, lt=1.0)  # termina pressionado

    result = trigger(rec)

    assert result.cycles_detected == 0
    assert result.cycles_valid == 0


def test_ruido_e_deadzone_do_trigger_usam_o_repouso() -> None:
    rec = Recorder()
    rec.sweep("left")
    sweep = TriggerSamples(
        tuple(f["timestamp_ns"] for f in rec.frames),
        tuple(f["triggers"]["lt"] / SCALE for f in rec.frames),
    )
    noisy = tuple(0.004 if i % 2 else 0.0 for i in range(500))
    rest = RestTriggerWindow(
        0, 4_000_000_000, TriggerSamples(tuple(ns(i) for i in range(500)), noisy)
    )

    result = measure_trigger([rest], [sweep], ChannelCoverage(), CONFIG)

    assert result.rest == pytest.approx(0.002)
    assert result.noise_p2p == pytest.approx(0.004)
    assert result.noise_rms == pytest.approx(0.002)
    assert result.noise_p99 == pytest.approx(0.002)
    assert result.deadzone is not None
    assert result.deadzone.value == pytest.approx(max(1.5 * 0.002, 0.01) / result.span)  # type: ignore[operator]


def test_trigger_sem_repouso_nao_calcula_forma() -> None:
    rec = Recorder()
    rec.sweep("left")
    sweep = TriggerSamples(
        tuple(f["timestamp_ns"] for f in rec.frames),
        tuple(f["triggers"]["lt"] / SCALE for f in rec.frames),
    )

    result = measure_trigger([], [sweep], ChannelCoverage(), CONFIG)

    assert result.rest is None
    assert result.cycles_valid == 0
    assert result.deadzone is None


# ------------------------------------------------------------------------------ capture


def test_taxa_efetiva_a_1_khz_dentro_de_circulos() -> None:
    timestamps = [i * 1_000_000 for i in range(2001)]

    result = measure_capture(timestamps, [(0, 2_001_000_000)], 0, CONFIG)

    assert result.effective_rate_hz == pytest.approx(1000.0)
    assert result.rate_p5_hz == pytest.approx(1000.0)
    assert result.rate_p95_hz == pytest.approx(1000.0)
    assert result.rate_pairs == 2000
    assert result.duration_s == pytest.approx(2.0)


def test_pausa_longa_e_pares_fora_do_circulo_ficam_fora_da_taxa() -> None:
    timestamps = [i * 1_000_000 for i in range(300)] + [300_000_000 + 500_000_000]
    timestamps += [timestamps[-1] + (i + 1) * 1_000_000 for i in range(300)]

    result = measure_capture(timestamps, [(0, 2_000_000_000)], 0, CONFIG)

    assert result.rate_pairs == 599  # 299 + 1 + 299; o par de 0,5 s sai da população
    assert result.effective_rate_hz == pytest.approx(1000.0)


def test_taxa_indisponivel_com_poucos_pares() -> None:
    timestamps = [i * 8_000_000 for i in range(50)]

    result = measure_capture(timestamps, [(0, 1_000_000_000)], 0, CONFIG)

    assert result.effective_rate_hz is None
    assert result.rate_p5_hz is None
    assert result.rate_pairs == 49


def test_timestamp_duplicado_e_contado_e_fica_fora_da_taxa() -> None:
    timestamps = [0, 8_000_000, 8_000_000, 16_000_000]

    result = measure_capture(
        timestamps,
        [(0, 1_000_000_000)],
        0,
        MetricsConfig(protocol=ProtocolParams(rate_min_pairs=1)),
    )

    assert result.duplicate_pairs == 1
    assert result.rate_pairs == 2


def test_timestamp_decrescente_e_rejeitado_no_dominio() -> None:
    with pytest.raises(ValueError, match="non-decreasing"):
        measure_capture([0, 10, 5], [], 0, CONFIG)


# ---------------------------------------------------------------------------- config


def test_config_padrao_expoe_o_conjunto_efetivo_completo() -> None:
    data = CONFIG.to_dict()

    assert data["thresholds_version"] == 1
    assert data["drift_max"] == 0.02
    assert data["deadzone"] == {"factor": 1.5, "stick_floor": 0.02, "trigger_floor": 0.01}
    assert data["protocol"]["rest_min_frames"] == 150


@pytest.mark.parametrize(
    ("factory", "field"),
    [
        (lambda: Thresholds(drift_max=0.0), "drift_max"),
        (lambda: Thresholds(rate_tolerance=1.0), "rate_tolerance"),
        (lambda: Thresholds(noise_rms_max=math.nan), "noise_rms_max"),
        (lambda: DeadzoneParams(factor=0.5), "deadzone.factor"),
        (lambda: DeadzoneParams(stick_floor=0.6), "deadzone.stick_floor"),
        (lambda: ProtocolParams(rest_min_frames=0), "protocol.rest_min_frames"),
        (lambda: ProtocolParams(trigger_exit=0.2), "protocol.trigger_exit"),
        (lambda: ProtocolParams(trigger_peak_min=0.1), "protocol.trigger_exit"),
    ],
)
def test_config_rejeita_valores_fora_da_faixa_citando_o_campo(factory: object, field: str) -> None:
    with pytest.raises(ValueError, match=field):
        factory()  # type: ignore[operator]


def test_arm_e_exit_do_trigger_sao_relativos_ao_repouso_medido() -> None:
    values: list[float] = []
    for _ in range(3):
        values += [0.2] * 60
        values += [0.2 + 0.8 * i / 250 for i in range(250)]
        values += [1.0] * 60
        values += [1.0 - 0.8 * i / 250 for i in range(250)]
        values += [0.2] * 60
    sweep = TriggerSamples(tuple(ns(i) for i in range(len(values))), tuple(values))
    rest = RestTriggerWindow(
        0, 4_000_000_000, TriggerSamples(tuple(ns(i) for i in range(500)), (0.2,) * 500)
    )

    result = measure_trigger([rest], [sweep], ChannelCoverage(), CONFIG)

    assert result.rest == pytest.approx(0.2)
    assert result.cycles_detected == 3
    assert result.cycles_valid == 3
    assert result.span == pytest.approx(0.8)


def test_fase_conta_so_frames_medidos_sem_as_ancoras_interpoladas() -> None:
    rec = Recorder()
    rec.sweep("left", cycles=3)
    # A rampa de 2 s a 125 Hz tem 225 frames medidos entre 0,05 e 0,95 (+2 ancoras).
    enough = trigger(
        rec, config=MetricsConfig(protocol=ProtocolParams(trigger_phase_min_points=225))
    )
    short = trigger(
        rec, config=MetricsConfig(protocol=ProtocolParams(trigger_phase_min_points=227))
    )

    assert enough.cycles_valid == 3
    assert short.cycles_valid == 0


def test_simetria_nula_quando_o_centro_fica_acima_do_maximo() -> None:
    window = circle_window(radius=(0.3, 0.9))
    result = stick(rest=[(0.5, 0.0)] * 500, circles=[window])

    assert result.axis_range is not None
    assert result.axis_range.symmetry[0] is None


def test_volta_sem_passos_de_fechamento_conta_zero_voltas() -> None:
    # Uma volta em [0, 2*pi) nunca alcanca Theta >= 2*pi: nenhuma volta completa.
    window = CircleStickWindow("cw", samples(circle_points(1, 125)[:125]))

    result = stick(rest=[(0.0, 0.0)] * 500, circles=[window])

    assert result.circle.valid_laps == 0
    assert result.circle.rejected_laps == 0


def test_drift_block_s_subnanossegundo_e_rejeitado() -> None:
    with pytest.raises(ValueError, match="protocol.drift_block_s"):
        ProtocolParams(drift_block_s=1e-10)
