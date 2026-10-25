from __future__ import annotations

import argparse
import json
import logging
import math
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

from zonepad import __version__
from zonepad.application.measure import MeasureInputs, MeasureOptions, execute_measure, save_profile
from zonepad.application.report import dumps_report, render_markdown
from zonepad.application.runtime import build_runtime
from zonepad.domain.errors import (
    DeviceDisconnectedError,
    DeviceNotFoundError,
    InvalidMappingError,
    InvalidProfileError,
    MeasurementInputError,
    UnsupportedPlatformError,
)
from zonepad.infrastructure.capture_reader import read_strict_capture
from zonepad.infrastructure.evdev import LinuxEvdevBackend
from zonepad.infrastructure.files import sha256_file, write_text_atomic
from zonepad.infrastructure.json_profile_store import JsonProfileStore
from zonepad.infrastructure.manifest_reader import load_manifest, load_metrics_config
from zonepad.infrastructure.mapping import load_device_mapping
from zonepad.infrastructure.replay import load_capture
from zonepad.infrastructure.uinput import LinuxUinputPublisher
from zonepad.interface.calibration_cli import run_calibrate


def _positive_float(value: str) -> float:
    try:
        result = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a number") from exc
    if not math.isfinite(result) or result <= 0:
        raise argparse.ArgumentTypeError("must be a finite value greater than zero")
    return result


_MEASURE_EPILOG = """\
códigos de saída:
  0  relatório gerado (avisos podem existir sem --strict)
  1  falha inesperada, com mensagem acionável
  2  captura, manifesto, mapping, thresholds ou argumentos inválidos
  4  qualidade insuficiente com --strict, ou --save-profile sem perfil derivável
     (o relatório continua sendo escrito e nenhum perfil é gravado)

sem --report e sem --report-md, o relatório JSON vai para stdout.
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="zonepad", description="Calibração de controles no Linux")
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("list", help="lista controles evdev disponíveis")
    replay = subcommands.add_parser("replay", help="inspeciona uma captura JSONL")
    replay.add_argument("capture", type=Path)
    profiles = subcommands.add_parser("profiles", help="lista perfis JSON")
    profiles.add_argument("--directory", type=Path, default=Path("~/.config/zonepad/profiles"))
    run = subcommands.add_parser("run", help="aplica um perfil a um controle virtual uinput")
    run.add_argument("--device", required=True, help="nome do nó evdev, por exemplo event3")
    run.add_argument("--profile", required=True, help="UUID do perfil salvo")
    run.add_argument("--profiles-dir", type=Path, default=Path("~/.config/zonepad/profiles"))
    run.add_argument("--mapping", type=Path, help="JSON v1 com códigos e ranges medidos")
    run.add_argument("--uinput", type=Path, help="nó uinput; padrão: /dev/uinput")
    run.add_argument(
        "--timeout", type=_positive_float, default=0.05, help="timeout de leitura em segundos"
    )
    run.add_argument("--duration", type=_positive_float, help="duração máxima em segundos")
    measure = subcommands.add_parser(
        "measure",
        help="mede métricas de calibração de uma captura JSONL segmentada por manifesto",
        description=(
            "Calcula métricas de sticks e triggers (normalizadas com o mapping), emite um "
            "relatório JSON/Markdown e, com --save-profile, grava um perfil schema_version=1. "
            "Não acessa /dev/input nem /dev/uinput."
        ),
        epilog=_MEASURE_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    measure.add_argument("capture", type=Path, help="captura JSONL (frames raw)")
    measure.add_argument(
        "--manifest", type=Path, required=True, help="manifesto JSON com os segmentos (obrigatório)"
    )
    measure.add_argument(
        "--mapping",
        type=Path,
        required=True,
        help="mapping JSON v1, o mesmo de 'zonepad run' (obrigatório)",
    )
    measure.add_argument("--report", type=Path, help="grava o relatório JSON neste arquivo")
    measure.add_argument("--report-md", type=Path, help="grava o relatório Markdown neste arquivo")
    measure.add_argument(
        "--save-profile", type=Path, metavar="DIR", help="grava o perfil derivado neste diretório"
    )
    measure.add_argument("--thresholds", type=Path, help="JSON com thresholds e parâmetros")
    measure.add_argument(
        "--strict",
        action="store_true",
        help="falha com código 4 diante de achados bloqueantes e não grava perfil",
    )
    calibrate = subcommands.add_parser(
        "calibrate",
        help="conduz a calibração interativa de um controle",
        description=(
            "Grava uma captura segmentada, mede sua qualidade e oferece a criação de perfil v1. "
            "Requer TTY; não descobre mapping automaticamente."
        ),
        epilog=(
            "códigos de saída:\n"
            "  0  perfil salvo ou resultado aceito sem salvar\n"
            "  1  falha inesperada\n"
            "  2  argumentos, TTY, mapping, thresholds ou captura inválidos\n"
            "  3  dispositivo indisponível, desconectado ou sem permissão\n"
            "  4  qualidade bloqueante ou perfil não derivável\n"
            "  130 cancelamento (Ctrl+C, EOF ou opção cancelar)\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    calibrate.add_argument("--device", help="nó evdev; omitido: seleção manual")
    calibrate.add_argument(
        "--mapping", type=Path, required=True, help="mapping JSON v1 com lx, ly, rx, ry, lt e rt"
    )
    calibrate.add_argument(
        "--capture-dir",
        type=Path,
        default=Path("~/.local/share/zonepad/captures"),
        help="diretório base das sessões de captura",
    )
    calibrate.add_argument(
        "--profiles-dir",
        type=Path,
        default=Path("~/.config/zonepad/profiles"),
        help="diretório dos perfis v1",
    )
    calibrate.add_argument("--thresholds", type=Path, help="JSON opcional com thresholds v1")
    calibrate.add_argument(
        "--warmup-seconds",
        type=_positive_float,
        default=2.0,
        help="aquecimento inicial (padrão: 2)",
    )
    calibrate.add_argument(
        "--rest-seconds",
        type=_positive_float,
        default=5.0,
        help="repouso total incluindo 1 s interno (padrão: 5)",
    )
    calibrate.add_argument(
        "--circle-seconds",
        type=_positive_float,
        default=6.0,
        help="duração de cada direção de stick (padrão: 6)",
    )
    calibrate.add_argument(
        "--trigger-seconds",
        type=_positive_float,
        default=25.0,
        help="duração de cada varredura de trigger (padrão: 25)",
    )
    calibrate.add_argument(
        "--max-retries",
        type=int,
        choices=range(0, 7),
        default=2,
        help="retries máximos por alvo; limite global fixo de 6 (padrão: 2)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO)
    args = build_parser().parse_args(argv)
    if args.command == "list":
        for device in LinuxEvdevBackend().list_devices():
            print(
                json.dumps(
                    {
                        "id": device.device_id,
                        "name": device.name,
                        "capabilities": sorted(device.capabilities),
                    }
                )
            )
        return 0
    if args.command == "replay":
        frames = load_capture(args.capture)
        print(
            json.dumps(
                {"frames": len(frames), "device_id": frames[0].device_id if frames else None}
            )
        )
        return 0
    if args.command == "profiles":
        store = JsonProfileStore(args.directory)
        for profile_id in store.list_profiles():
            print(profile_id)
        return 0
    if args.command == "run":
        return _run(args)
    if args.command == "measure":
        return _measure(args)
    if args.command == "calibrate":
        return run_calibrate(args)
    return 2


def _fail(message: str) -> None:
    print(f"erro: {message}", file=sys.stderr)


def _measure(args: argparse.Namespace) -> int:
    """Composition root of ``zonepad measure``: load inputs, run the use case, write outputs."""
    try:
        config = load_metrics_config(args.thresholds)
        manifest = load_manifest(args.manifest)
        mapping = load_device_mapping(args.mapping)
        mapping_sha256 = sha256_file(args.mapping.expanduser())
        capture = read_strict_capture(args.capture)
        inputs = MeasureInputs(
            capture.frames,
            capture.file_name,
            capture.sha256,
            manifest,
            mapping.axes,
            mapping.triggers,
            mapping_sha256,
            config,
        )
        store = JsonProfileStore(args.save_profile) if args.save_profile else None
        outcome = execute_measure(
            inputs,
            MeasureOptions(strict=args.strict, save_profile=store is not None),
            app_version=__version__,
            now=lambda: datetime.now(UTC),
            profile_id_factory=lambda: str(uuid.uuid4()),
        )
        report_json = dumps_report(outcome.report)
        if args.report is not None:
            write_text_atomic(args.report, report_json)
        if args.report_md is not None:
            write_text_atomic(args.report_md, render_markdown(outcome.report))
        if store is not None:
            save_profile(store, outcome)
    except MeasurementInputError as exc:
        _fail(str(exc))
        return 2
    except InvalidMappingError as exc:
        _fail(f"[INVALID_MAPPING] {exc}")
        return 2
    except OSError as exc:
        _fail(f"não foi possível ler ou gravar arquivos: {exc}. Confira caminhos e permissões.")
        return 1
    except Exception as exc:
        logging.getLogger(__name__).debug("measure failed", exc_info=True)
        _fail(
            f"falha inesperada ({type(exc).__name__}): {exc}. Rode novamente com a mesma entrada "
            "e reporte o problema com a captura anonimizada."
        )
        return 1
    json_on_stdout = args.report is None and args.report_md is None
    if json_on_stdout:
        sys.stdout.write(report_json)
    if outcome.profile is not None:
        line = f"profile_id: {outcome.profile.profile_id}"
        print(line, file=sys.stderr if json_on_stdout else sys.stdout)
    if outcome.exit_reason != "ok":
        _fail(outcome.message or "qualidade insuficiente")
        return 4
    return 0


def _run(args: argparse.Namespace) -> int:
    if args.mapping is None:
        print(
            "erro: --mapping é necessário para fornecer ranges medidos de eixos e triggers",
            flush=True,
        )
        return 2
    try:
        mapping = load_device_mapping(args.mapping)
        store = JsonProfileStore(args.profiles_dir)
        # Validar o perfil antes de registrar um controle virtual.
        store.load(args.profile)
        backend = LinuxEvdevBackend(mapping=mapping)
        try:
            publisher = LinuxUinputPublisher(args.uinput)
        except PermissionError:
            print(
                "erro: sem permissão para /dev/uinput; configure uma regra udev "
                "ou o grupo adequado",
                flush=True,
            )
            return 3
        runtime = build_runtime(backend, store, publisher, args.device, args.profile, args.timeout)
        logging.info(
            "runtime started",
            extra={
                "device_id": args.device,
                "profile_id": args.profile,
                "duration_s": args.duration,
            },
        )
        runtime.run(args.timeout, args.duration)
    except KeyboardInterrupt:
        logging.info("runtime interrupted")
        return 0
    except DeviceDisconnectedError:
        print("controle desconectado; encerramento concluído", flush=True)
        return 0
    except PermissionError:
        print(
            "erro: sem permissão para abrir /dev/input ou o diretório de perfis; "
            "confira o grupo adequado",
            flush=True,
        )
        return 3
    except (OSError, RuntimeError) as exc:
        print(f"erro: não foi possível executar o runtime: {exc}", flush=True)
        return 2
    except (
        InvalidProfileError,
        InvalidMappingError,
        DeviceNotFoundError,
        FileNotFoundError,
    ) as exc:
        print(f"erro: {exc}", flush=True)
        return 2
    except UnsupportedPlatformError as exc:
        print(f"erro: {exc}", flush=True)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
