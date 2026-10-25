from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from synthetic_capture import full_session

from zonepad.domain.errors import MeasurementInputError
from zonepad.domain.metrics import MetricsConfig
from zonepad.infrastructure.capture_reader import read_strict_capture
from zonepad.infrastructure.manifest_reader import load_manifest, load_metrics_config
from zonepad.infrastructure.replay import load_capture

FRAME = {"device_id": "pad", "timestamp_ns": 1, "axes": {"lx": 5}, "triggers": {"lt": 0}}


def write_lines(path: Path, *lines: str) -> Path:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def frame_line(**changes: Any) -> str:
    return json.dumps({**FRAME, **changes})


# ----------------------------------------------------------------------- capture reader


def test_leitor_estrito_le_a_captura_sintetica_e_calcula_o_hash(tmp_path: Path) -> None:
    rec = full_session()
    path = tmp_path / "capture.jsonl"
    path.write_text(rec.jsonl(), encoding="utf-8")

    loaded = read_strict_capture(path)

    assert len(loaded.frames) == len(rec.frames)
    assert loaded.file_name == "capture.jsonl"
    assert loaded.sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
    assert loaded.frames[0].axes["lx"] == 0
    assert loaded.frames == tuple(rec.raw_frames())


def test_leitor_estrito_nao_altera_o_replay_leniente(tmp_path: Path) -> None:
    path = write_lines(tmp_path / "lenient.jsonl", frame_line(timestamp_ns=1.0))

    assert len(load_capture(path)) == 1  # replay segue aceitando float
    with pytest.raises(MeasurementInputError, match=r"lenient.jsonl:1: timestamp_ns"):
        read_strict_capture(path)


@pytest.mark.parametrize(
    ("lines", "code", "location", "fragment"),
    [
        (
            [frame_line(), '{"device_id": "pad", "timestamp_ns": NaN}'],
            "INVALID_CAPTURE",
            ":2:",
            "NaN",
        ),
        (
            ['{"device_id": "pad", "timestamp_ns": 1, "axes": {"lx": Infinity}}'],
            "INVALID_CAPTURE",
            ":1:",
            "Infinity",
        ),
        (
            ['{"device_id": "pad", "timestamp_ns": 1, "axes": {"lx": -Infinity}}'],
            "INVALID_CAPTURE",
            ":1:",
            "-Infinity",
        ),
        ([frame_line(timestamp_ns=1.5)], "INVALID_CAPTURE", ":1:", "timestamp_ns"),
        ([frame_line(timestamp_ns=True)], "INVALID_CAPTURE", ":1:", "timestamp_ns"),
        ([frame_line(timestamp_ns="7")], "INVALID_CAPTURE", ":1:", "timestamp_ns"),
        ([frame_line(timestamp_ns=-1)], "INVALID_CAPTURE", ":1:", ">= 0"),
        ([frame_line(axes={"lx": 1.5})], "INVALID_CAPTURE", ":1:", "axes.lx"),
        ([frame_line(triggers={"lt": True})], "INVALID_CAPTURE", ":1:", "triggers.lt"),
        ([frame_line(axes=[1, 2])], "INVALID_CAPTURE", ":1:", "axes"),
        ([frame_line(buttons="a")], "INVALID_CAPTURE", ":1:", "buttons"),
        ([frame_line(extra=1)], "INVALID_CAPTURE", ":1:", "campos desconhecidos: extra"),
        ([json.dumps({"timestamp_ns": 1})], "INVALID_CAPTURE", ":1:", "device_id"),
        ([frame_line(device_id="")], "INVALID_CAPTURE", ":1:", "device_id"),
        (
            [frame_line(), frame_line(timestamp_ns=2, device_id="other")],
            "INVALID_CAPTURE",
            ":2:",
            "device_id",
        ),
        (
            [frame_line(timestamp_ns=ts) for ts in (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12)]
            + [frame_line(timestamp_ns=3)],
            "NON_MONOTONIC_TIME",
            ":13:",
            "decresce de 12 para 3",
        ),
        ([frame_line(), "", frame_line(timestamp_ns=2)], "INVALID_CAPTURE", ":2:", "JSON inválido"),
        (["{not json"], "INVALID_CAPTURE", ":1:", "JSON inválido"),
        (["[1, 2]"], "INVALID_CAPTURE", ":1:", "objeto"),
        (
            ['{"device_id": "pad", "device_id": "pad", "timestamp_ns": 1}'],
            "INVALID_CAPTURE",
            ":1:",
            "duplicado",
        ),
    ],
)
def test_leitor_estrito_rejeita_linha_invalida_citando_arquivo_e_linha(
    tmp_path: Path, lines: list[str], code: str, location: str, fragment: str
) -> None:
    path = write_lines(tmp_path / "bad.jsonl", *lines)

    with pytest.raises(MeasurementInputError) as caught:
        read_strict_capture(path)

    message = str(caught.value)
    assert message.startswith(f"[{code}]")
    assert f"bad.jsonl{location}" in message
    assert fragment in message
    assert str(tmp_path) not in message  # nunca expõe o caminho absoluto


@pytest.mark.parametrize("content", [b"", b"\n"])
def test_captura_vazia_e_rejeitada_com_orientacao(tmp_path: Path, content: bytes) -> None:
    path = tmp_path / "empty.jsonl"
    path.write_bytes(content)

    with pytest.raises(MeasurementInputError, match=r"\[EMPTY_CAPTURE\].*vazia"):
        read_strict_capture(path)


def test_captura_ausente_ou_com_bytes_invalidos_e_erro_acionavel(tmp_path: Path) -> None:
    bad = tmp_path / "bad.jsonl"
    bad.write_bytes(b"\xff\xfe")

    with pytest.raises(MeasurementInputError, match="não foi possível ler"):
        read_strict_capture(tmp_path / "missing.jsonl")
    with pytest.raises(MeasurementInputError, match="UTF-8"):
        read_strict_capture(bad)


def test_timestamps_iguais_sao_aceitos_na_leitura(tmp_path: Path) -> None:
    path = write_lines(tmp_path / "dup.jsonl", frame_line(), frame_line())

    assert len(read_strict_capture(path).frames) == 2


# ---------------------------------------------------------------------------- manifest


def manifest_payload() -> dict[str, Any]:
    return {
        "manifest_version": 1,
        "device": {
            "device_id": "event3",
            "name": "Xbox Wireless Controller",
            "vid": "0x045e",
            "pid": "0x0b13",
            "guid": "g",
            "serial": "s",
        },
        "capture_file": "captura.jsonl",
        "capture_sha256": "ab" * 32,
        "nominal_rate_hz": 125,
        "connection": "bluetooth",
        "segments": [
            {
                "kind": "rest",
                "start_ns": 2_000_000_000,
                "end_ns": 7_000_000_000,
                "warmup_ns": 1_000_000_000,
            },
            {
                "kind": "circle",
                "stick": "left",
                "direction": "cw",
                "start_ns": 8_000_000_000,
                "end_ns": 14_000_000_000,
            },
            {
                "kind": "circle",
                "stick": "left",
                "direction": "ccw",
                "start_ns": 14_000_000_000,
                "end_ns": 20_500_000_000,
            },
            {
                "kind": "trigger_sweep",
                "trigger": "left",
                "start_ns": 22_000_000_000,
                "end_ns": 47_000_000_000,
            },
        ],
    }


def write_json(path: Path, payload: Any) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_manifesto_da_spec_e_aceito(tmp_path: Path) -> None:
    manifest = load_manifest(write_json(tmp_path / "m.json", manifest_payload()))

    assert manifest.device.device_id == "event3"
    assert manifest.device.serial == "s"
    assert manifest.connection == "bluetooth"
    assert manifest.nominal_rate_hz == 125.0
    assert [s.kind for s in manifest.segments] == ["rest", "circle", "circle", "trigger_sweep"]
    assert manifest.segments[0].effective_start_ns == 3_000_000_000


def _mutate(path: str, value: Any) -> dict[str, Any]:
    payload = manifest_payload()
    target: Any = payload
    *parents, last = path.split(".")
    for part in parents:
        target = target[int(part)] if part.isdigit() else target[part]
    if value is _DELETE:
        del target[int(last) if last.isdigit() else last]
    else:
        target[int(last) if last.isdigit() else last] = value
    return payload


_DELETE = object()


@pytest.mark.parametrize(
    ("payload", "fragment"),
    [
        (_mutate("manifest_version", 2), "manifest_version 2 não suportada (suportadas: 1)"),
        (_mutate("manifest_version", True), "manifest_version"),
        (_mutate("extra", 1), "campos desconhecidos ou não permitidos: extra"),
        (_mutate("device.extra", 1), "device: campos desconhecidos"),
        (_mutate("device.vid", "045e"), "vid"),
        (_mutate("device.device_id", ""), "device_id"),
        (_mutate("device", _DELETE), "campos obrigatórios ausentes: device"),
        (_mutate("capture_file", "../x.jsonl"), "capture_file"),
        (_mutate("capture_file", "/abs/x.jsonl"), "capture_file"),
        (_mutate("capture_sha256", "xyz"), "capture_sha256"),
        (_mutate("nominal_rate_hz", 0), "nominal_rate_hz"),
        (_mutate("nominal_rate_hz", "125"), "nominal_rate_hz"),
        (_mutate("connection", "carrier-pigeon"), "connection"),
        (_mutate("segments", []), "segments"),
        (_mutate("segments", "x"), "segments"),
        (_mutate("segments.1.kind", "spin"), "segments[1].kind desconhecido"),
        (_mutate("segments.1.extra", 1), "segments[1]"),
        (
            _mutate("segments.1.warmup_ns", 5),
            "segments[1]: campos desconhecidos ou não permitidos: warmup_ns",
        ),
        (_mutate("segments.0.stick", "left"), "segments[0]"),
        (_mutate("segments.3.direction", "cw"), "segments[3]"),
        (
            _mutate("segments.1.direction", _DELETE),
            "segments[1]: campos obrigatórios ausentes: direction",
        ),
        (_mutate("segments.1.stick", "middle"), "segments[1]"),
        (_mutate("segments.1.start_ns", 8.5), "segments[1].start_ns"),
        (_mutate("segments.1.start_ns", True), "segments[1].start_ns"),
        (_mutate("segments.1.end_ns", 8_000_000_000), "segments[1]"),
        (_mutate("segments.1.start_ns", 6_000_000_000), "sobrepõe"),
        (_mutate("segments.0.warmup_ns", 6_000_000_000), "segments[0]"),
        (_mutate("segments.0.warmup_ns", -1), "segments[0]"),
    ],
)
def test_manifesto_invalido_e_rejeitado_citando_o_campo(
    tmp_path: Path, payload: dict[str, Any], fragment: str
) -> None:
    with pytest.raises(MeasurementInputError) as caught:
        load_manifest(write_json(tmp_path / "m.json", payload))

    message = str(caught.value)
    assert message.startswith("[INVALID_MANIFEST] m.json:")
    assert fragment in message


def test_manifesto_com_segmentos_fora_de_ordem_e_rejeitado(tmp_path: Path) -> None:
    payload = manifest_payload()
    payload["segments"].reverse()

    with pytest.raises(MeasurementInputError, match="fora de ordem"):
        load_manifest(write_json(tmp_path / "m.json", payload))


def test_manifesto_com_mais_de_256_segmentos_e_rejeitado(tmp_path: Path) -> None:
    payload = manifest_payload()
    payload["segments"] = [
        {"kind": "rest", "start_ns": i * 10, "end_ns": i * 10 + 5} for i in range(257)
    ]

    with pytest.raises(MeasurementInputError, match="máximo é 256"):
        load_manifest(write_json(tmp_path / "m.json", payload))


def test_manifesto_acima_de_1_mib_e_rejeitado(tmp_path: Path) -> None:
    path = tmp_path / "big.json"
    path.write_text(" " * (1 << 20) + "{}", encoding="utf-8")

    with pytest.raises(MeasurementInputError, match="excede o limite"):
        load_manifest(path)


@pytest.mark.parametrize(
    ("text", "fragment"),
    [
        ("{not json", "JSON inválido"),
        ('{"manifest_version": NaN}', "NaN"),
        ('{"manifest_version": 1, "manifest_version": 1}', "duplicado"),
        ("[]", "deve ser um objeto"),
    ],
)
def test_manifesto_com_json_malformado_cita_arquivo_e_linha(
    tmp_path: Path, text: str, fragment: str
) -> None:
    path = tmp_path / "m.json"
    path.write_text(text, encoding="utf-8")

    with pytest.raises(MeasurementInputError, match="m.json") as caught:
        load_manifest(path)

    assert fragment in str(caught.value)


def test_manifesto_ausente_e_erro_acionavel(tmp_path: Path) -> None:
    with pytest.raises(MeasurementInputError, match="não foi possível ler"):
        load_manifest(tmp_path / "nope.json")


# --------------------------------------------------------------------------- thresholds


def test_sem_arquivo_usa_defaults() -> None:
    assert load_metrics_config(None) == MetricsConfig()


def test_thresholds_parciais_sobrescrevem_so_o_informado(tmp_path: Path) -> None:
    path = write_json(
        tmp_path / "t.json",
        {
            "thresholds_version": 1,
            "drift_max": 0.05,
            "deadzone": {"factor": 2},
            "protocol": {"rest_min_frames": 10, "trigger_arm": 0.2},
        },
    )

    config = load_metrics_config(path)

    assert config.thresholds.drift_max == 0.05
    assert config.thresholds.noise_rms_max == 0.005
    assert config.deadzone.factor == 2.0
    assert config.deadzone.stick_floor == 0.02
    assert config.protocol.rest_min_frames == 10
    assert config.protocol.trigger_arm == 0.2


@pytest.mark.parametrize(
    ("payload", "fragment"),
    [
        ({"drift_max": 0.1}, "thresholds_version"),
        ({"thresholds_version": 2}, "não suportada"),
        ({"thresholds_version": 1, "bogus": 1}, "bogus"),
        ({"thresholds_version": 1, "deadzone": {"bogus": 1}}, "bogus"),
        ({"thresholds_version": 1, "protocol": {"bogus": 1}}, "bogus"),
        ({"thresholds_version": 1, "drift_max": "0.1"}, "drift_max"),
        ({"thresholds_version": 1, "drift_max": True}, "drift_max"),
        ({"thresholds_version": 1, "drift_max": 0}, "drift_max"),
        ({"thresholds_version": 1, "drift_max": -1}, "drift_max"),
        ({"thresholds_version": 1, "rate_tolerance": 1}, "rate_tolerance"),
        ({"thresholds_version": 1, "deadzone": {"factor": 0.5}}, "deadzone.factor"),
        ({"thresholds_version": 1, "deadzone": {"stick_floor": 0.9}}, "deadzone.stick_floor"),
        (
            {"thresholds_version": 1, "protocol": {"rest_min_frames": 1.5}},
            "protocol.rest_min_frames",
        ),
        ({"thresholds_version": 1, "protocol": {"rest_min_frames": 0}}, "protocol.rest_min_frames"),
        ({"thresholds_version": 1, "protocol": {"trigger_exit": 0.5}}, "trigger_exit"),
        ({"thresholds_version": 1, "deadzone": []}, "deadzone"),
    ],
)
def test_thresholds_invalidos_sao_rejeitados_citando_o_campo(
    tmp_path: Path, payload: dict[str, Any], fragment: str
) -> None:
    with pytest.raises(MeasurementInputError) as caught:
        load_metrics_config(write_json(tmp_path / "t.json", payload))

    assert str(caught.value).startswith("[INVALID_THRESHOLDS] t.json")
    assert fragment in str(caught.value)


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_thresholds_nao_finitos_sao_rejeitados(tmp_path: Path, constant: str) -> None:
    path = tmp_path / "t.json"
    path.write_text(f'{{"thresholds_version": 1, "drift_max": {constant}}}', encoding="utf-8")

    with pytest.raises(MeasurementInputError, match=constant):
        load_metrics_config(path)


def test_thresholds_acima_de_64_kib_sao_rejeitados(tmp_path: Path) -> None:
    path = tmp_path / "t.json"
    path.write_text(" " * (64 << 10) + "{}", encoding="utf-8")

    with pytest.raises(MeasurementInputError, match="excede o limite"):
        load_metrics_config(path)


def test_captura_acima_do_teto_e_rejeitada_sem_ser_lida(tmp_path: Path) -> None:
    path = tmp_path / "huge.jsonl"
    with path.open("wb") as stream:
        stream.truncate((32 << 20) + 1)  # arquivo esparso

    with pytest.raises(
        MeasurementInputError, match=r"\[INVALID_CAPTURE\] huge.jsonl.*excede o limite"
    ):
        read_strict_capture(path)
