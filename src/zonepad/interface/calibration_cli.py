from __future__ import annotations

import uuid
from argparse import Namespace
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from zonepad.application.calibrate import (
    Cancel,
    Continue,
    Event,
    MeasurementCompleted,
    RetryDecision,
    ReviewDecision,
    SaveDecision,
    SegmentCompleted,
    SegmentPlan,
    SegmentRejected,
    WizardPhase,
    WizardState,
    step,
)
from zonepad.application.measure import MeasureOutcome, save_profile
from zonepad.application.ports import (
    CaptureArtifacts,
    CaptureSession,
    Clock,
    Console,
    DeviceBackend,
    DeviceSession,
)
from zonepad.application.report import dumps_report, render_markdown
from zonepad.domain.errors import (
    DeviceDisconnectedError,
    DeviceNotFoundError,
    InvalidMappingError,
    MeasurementInputError,
    UnsupportedPlatformError,
)
from zonepad.domain.protocol import Segment
from zonepad.infrastructure.capture_writer import CaptureWriter, create_session_directory
from zonepad.infrastructure.clock import SystemClock
from zonepad.infrastructure.evdev import LinuxEvdevBackend
from zonepad.infrastructure.files import write_text_atomic
from zonepad.infrastructure.json_profile_store import JsonProfileStore
from zonepad.infrastructure.live_capture import LiveCaptureSession
from zonepad.infrastructure.manifest_reader import load_metrics_config
from zonepad.infrastructure.mapping import DeviceMapping, load_device_mapping
from zonepad.infrastructure.measure_runner import MeasureRunner
from zonepad.interface.terminal_console import CalibrationCancelled, TerminalConsole


class _QualityBlocked(Exception):
    pass


def _plans(warmup: float, rest: float, circle: float, trigger: float) -> tuple[SegmentPlan, ...]:
    return (
        SegmentPlan(
            ("rest",),
            "rest",
            rest,
            "Mãos fora do controle; deixe os sticks e gatilhos em repouso.",
            1_000_000_000,
        ),
        SegmentPlan(
            ("circle", "left", "cw"),
            "circle",
            circle,
            "Stick esquerdo na borda: dê 3 voltas horárias e passe do ponto inicial.",
            stick="left",
            direction="cw",
        ),
        SegmentPlan(
            ("circle", "left", "ccw"),
            "circle",
            circle,
            "Stick esquerdo na borda: dê 3 voltas anti-horárias e passe do ponto inicial.",
            stick="left",
            direction="ccw",
        ),
        SegmentPlan(
            ("circle", "right", "cw"),
            "circle",
            circle,
            "Stick direito na borda: dê 3 voltas horárias e passe do ponto inicial.",
            stick="right",
            direction="cw",
        ),
        SegmentPlan(
            ("circle", "right", "ccw"),
            "circle",
            circle,
            "Stick direito na borda: dê 3 voltas anti-horárias e passe do ponto inicial.",
            stick="right",
            direction="ccw",
        ),
        SegmentPlan(
            ("trigger", "left"),
            "trigger_sweep",
            trigger,
            "Gatilho esquerdo: em cada ciclo, fique 0,5 s em repouso, pressione em 2 s, "
            "mantenha no fundo por 0,5 s e solte em 2 s; repita 5 vezes.",
            trigger="left",
        ),
        SegmentPlan(
            ("trigger", "right"),
            "trigger_sweep",
            trigger,
            "Gatilho direito: em cada ciclo, fique 0,5 s em repouso, pressione em 2 s, "
            "mantenha no fundo por 0,5 s e solte em 2 s; repita 5 vezes.",
            trigger="right",
        ),
    )


def _plan_segment(plan: SegmentPlan) -> Segment:
    return Segment(plan.kind, 1, 2, plan.warmup_ns, plan.stick, plan.direction, plan.trigger)


def _retry_targets(
    outcome: MeasureOutcome, existing: set[tuple[str, ...]]
) -> tuple[tuple[str, ...], ...] | None:
    blockers = [finding for finding in outcome.metrics.findings if finding.blocks_strict]
    if not blockers:
        return None
    targets: set[tuple[str, ...]] = set()
    for finding in blockers:
        metric = finding.metric or ""
        if finding.code in {"REST_TOO_SHORT", "HIGH_DRIFT", "HIGH_NOISE"}:
            target: tuple[str, ...] = ("rest",)
            if target not in existing:
                return None
        elif finding.code in {
            "INSUFFICIENT_CIRCLE_POINTS",
            "INSUFFICIENT_CIRCLE_LAPS",
            "CIRCLE_DIRECTION_INCONSISTENT",
        }:
            bits = metric.split(".")
            if len(bits) >= 3 and bits[0] == "sticks" and bits[1] in {"left", "right"}:
                directions = (
                    [bits[4]]
                    if len(bits) > 4 and bits[3] == "valid_laps" and bits[4] in {"cw", "ccw"}
                    else ["cw", "ccw"]
                )
                for direction in directions:
                    target = ("circle", bits[1], direction)
                    if target not in existing:
                        return None
                    targets.add(target)
                continue
            return None
        elif finding.code == "INSUFFICIENT_TRIGGER_CYCLES":
            bits = metric.split(".")
            if len(bits) < 2 or bits[0] != "triggers" or bits[1] not in {"left", "right"}:
                return None
            target = ("trigger", bits[1])
            if target not in existing:
                return None
        else:
            return None
        targets.add(target)
    return tuple(sorted(targets)) if targets else None


def _write_reports(directory: Path, outcome: MeasureOutcome) -> tuple[Path, Path]:
    json_path, markdown_path = directory / "report.json", directory / "report.md"
    write_text_atomic(json_path, dumps_report(outcome.report))
    write_text_atomic(markdown_path, render_markdown(outcome.report))
    return json_path, markdown_path


def run_calibrate(
    args: Namespace,
    *,
    console: Console | None = None,
    clock: Clock | None = None,
    backend_factory: Callable[[DeviceMapping], DeviceBackend] | None = None,
    now: Callable[[], datetime] | None = None,
    profile_id_factory: Callable[[], str] | None = None,
    capture_factory: Callable[[DeviceSession, CaptureWriter, Clock], CaptureSession] | None = None,
) -> int:
    """Interactive CLI workflow; dependencies are injectable for deterministic tests."""
    terminal = console or TerminalConsole()
    timer = clock or SystemClock()
    wall_now = now or (lambda: datetime.now(UTC))
    id_factory = profile_id_factory or (lambda: str(uuid.uuid4()))
    if not terminal.is_interactive:
        terminal.say("erro: calibrate exige um terminal interativo (TTY); --help não exige TTY")
        return 2
    try:
        mapping_path = Path(args.mapping).expanduser()
        mapping = load_device_mapping(mapping_path)
        config = load_metrics_config(
            Path(args.thresholds).expanduser() if args.thresholds else None
        )
        warmup, rest, circle, trigger = (
            args.warmup_seconds,
            args.rest_seconds,
            args.circle_seconds,
            args.trigger_seconds,
        )
        effective_rest = rest - 1.0
        minimum_rest = max(config.protocol.rest_min_duration_s, 2.0 * config.protocol.drift_block_s)
        if effective_rest < minimum_rest:
            terminal.say(
                f"erro: --rest-seconds precisa ser >= {minimum_rest + 1.0:g} para incluir o "
                "warmup interno e repouso efetivo"
            )
            return 2
        plans = _plans(warmup, rest, circle, trigger)
    except (InvalidMappingError, MeasurementInputError, OSError, ValueError) as exc:
        terminal.say(f"erro: configuração inválida: {exc}")
        return 2

    state = WizardState()

    def dispatch(event: Event) -> tuple[str, ...]:
        nonlocal state
        next_state, effects = step(state, event, segment_count=len(plans))
        state = next_state
        return tuple(effect.name for effect in effects)

    backend_builder = backend_factory or (lambda loaded: LinuxEvdevBackend(mapping=loaded))
    opened_session: DeviceSession | None = None
    writer: CaptureWriter | None = None
    capture_session: CaptureSession | None = None

    def cleanup_startup() -> str | None:
        errors: list[str] = []
        if capture_session is not None:
            try:
                capture_session.abort()
            except Exception as exc:
                errors.append(f"abort da captura: {exc}")
            try:
                capture_session.close()
            except Exception as exc:
                errors.append(f"fechamento da captura: {exc}")
        else:
            if writer is not None:
                try:
                    writer.abort()
                except Exception as exc:
                    errors.append(f"abort do writer: {exc}")
            if opened_session is not None:
                try:
                    opened_session.close()
                except Exception as exc:
                    errors.append(f"fechamento do dispositivo: {exc}")
        return "; ".join(errors) or None

    try:
        terminal.say("Bem-vindo ao wizard de calibração ZonaPad.")
        if "select_device" not in dispatch(Continue()):
            raise RuntimeError("state machine não solicitou seleção do dispositivo")
        backend = backend_builder(mapping)
        if args.device:
            devices = tuple(backend.list_devices())
            device = next((item for item in devices if item.device_id == args.device), None)
            if device is None:
                terminal.say(f"erro: dispositivo {args.device!r} não está disponível")
                return 3
        else:
            devices = tuple(backend.list_devices())
            if not devices:
                terminal.say("erro: nenhum dispositivo evdev disponível")
                return 3
            selected = terminal.ask_choice(
                "Escolha o controle", [f"{d.name} ({d.device_id})" for d in devices]
            )
            if selected is None:
                return 130
            device = devices[selected]
        if "validate_mapping" not in dispatch(Continue()):
            raise RuntimeError("state machine não solicitou validação do mapping")
        if "confirm_device" not in dispatch(Continue()):
            raise RuntimeError("state machine não solicitou confirmação do dispositivo")
        mapping_label = str(mapping_path)
        terminal.say(f"Dispositivo: {device.name} ({device.device_id})")
        terminal.say(f"Mapping: {mapping_label}")
        if not terminal.ask_confirm("A identidade e o mapping estão corretos?", default=False):
            return 130
        terminal.say(
            "A calibração leva cerca de 81 s de captura, além das instruções e contagens. "
            "Siga cada gesto; a qualidade depende da cadência do controle."
        )
        capture_effects = dispatch(Continue())
        if "open_capture" not in capture_effects:
            raise RuntimeError("state machine não solicitou abertura da captura")
        opened_session = backend.open(device.device_id)
        stamp = wall_now().astimezone(UTC).strftime("%Y-%m-%dT%H-%M-%SZ")
        directory = create_session_directory(Path(args.capture_dir), device.device_id, stamp)
        writer = CaptureWriter(directory, opened_session.device_info)
        capture_builder = capture_factory or LiveCaptureSession
        capture_session = capture_builder(opened_session, writer, timer)
        capture_session.start()
    except (DeviceNotFoundError, PermissionError, UnsupportedPlatformError, OSError) as exc:
        cleanup_error = cleanup_startup()
        detail = f"; cleanup: {cleanup_error}" if cleanup_error else ""
        if opened_session is None:
            terminal.say(f"erro: dispositivo indisponível ou sem permissão: {exc}{detail}")
            return 3
        terminal.say(f"erro ao preparar captura ou iniciar dispositivo: {exc}{detail}")
        return 2
    except CalibrationCancelled, KeyboardInterrupt:
        cleanup_startup()
        return 130
    except Exception as exc:
        cleanup_error = cleanup_startup()
        detail = f"; cleanup: {cleanup_error}" if cleanup_error else ""
        terminal.say(f"erro ao iniciar captura ({type(exc).__name__}): {exc}{detail}")
        return 1

    if capture_session is None:
        raise RuntimeError("capture factory não retornou uma sessão")
    capture = capture_session

    total_retries = 0
    retries_by_target: dict[tuple[str, ...], int] = defaultdict(int)
    started_ns = timer.now_ns()
    artifacts = None
    review_ready = False

    def record_plan(plan: SegmentPlan) -> None:
        nonlocal total_retries
        while True:
            if state.phase in {WizardPhase.SEGMENT_PROMPT, WizardPhase.RECORD_SEGMENT}:
                effects = dispatch(Continue())
            else:
                raise RuntimeError(f"fase inesperada para segmento: {state.phase.value}")
            if "countdown" not in effects:
                raise RuntimeError("state machine não solicitou contagem regressiva")
            terminal.say(plan.instruction)
            if not terminal.ask_confirm("Pressione Enter quando estiver pronto", default=True):
                raise CalibrationCancelled
            for remaining in (3, 2, 1):
                terminal.show_progress("Começando", float(remaining))
                timer.sleep(1.0)
            if state.phase is WizardPhase.COUNTDOWN and "record_segment" not in dispatch(
                Continue()
            ):
                raise RuntimeError("state machine não solicitou a captura do segmento")
            recorded = capture.record_segment(
                plan,
                plan.duration_seconds,
                lambda left: terminal.show_progress("Captura", left),
            )
            if recorded is not None:
                return
            can_retry = total_retries < 6 and retries_by_target[plan.target] < args.max_retries
            effects = dispatch(SegmentRejected(can_retry))
            if can_retry:
                if "retry_decision" not in effects:
                    raise RuntimeError("state machine não solicitou decisão de retry")
                terminal.say(
                    "Nenhuma janela com frames observados neste segmento; tente novamente o alvo."
                )
                if not terminal.ask_confirm("Repetir este segmento?", default=True):
                    dispatch(RetryDecision(False))
                    raise _QualityBlocked
                if "record_retry" not in dispatch(RetryDecision(True)):
                    raise RuntimeError("state machine não iniciou o retry")
                retries_by_target[plan.target] += 1
                total_retries += 1
                continue
            terminal.say("Limite de retries atingido para o segmento sem intervalo observado.")
            raise _QualityBlocked

    try:
        if "warmup" not in capture_effects:
            raise RuntimeError("state machine não solicitou aquecimento")
        terminal.say("Aquecimento: deixe o controle conectado e sem tocar por 2 s.")
        capture.wait(warmup, lambda left: terminal.show_progress("Aquecimento", left))
        if "prompt_segment" not in dispatch(Continue()):
            raise RuntimeError("state machine não solicitou o primeiro segmento")
        for plan in plans:
            record_plan(plan)
            artifacts = capture.flush()
            effects = dispatch(SegmentCompleted())
            if plan is not plans[-1] and "prompt_segment" not in effects:
                raise RuntimeError("state machine não solicitou o próximo segmento")
            if plan is plans[-1] and "measure" not in effects:
                raise RuntimeError("state machine não solicitou a medição")
        capture.pause()
        artifacts = capture.flush()
        review_ready = True
        runner = MeasureRunner(now=wall_now, profile_id_factory=id_factory)
        existing = {plan.target for plan in plans}
        while True:
            outcome = runner.run(
                Path(artifacts.capture_path),
                Path(artifacts.manifest_path),
                mapping_path,
                mapping,
                config,
            )
            if outcome.profile is not None:
                outcome.report["profile_summary"]["profile_id"] = None
            report_json, report_markdown = _write_reports(Path(artifacts.directory), outcome)
            review_ready = True
            targets = _retry_targets(outcome, existing)
            if "review" not in dispatch(MeasurementCompleted()):
                raise RuntimeError("state machine não entrou em review")
            review_effect = dispatch(
                ReviewDecision(targets is not None, outcome.exit_reason == "ok")
            )
            status = outcome.report["quality"]["status"]
            terminal.say(f"Qualidade: {status}")
            for finding in outcome.report["quality"]["findings"]:
                metric = (
                    f" ({finding['metric']}={finding['value']})"
                    if finding.get("value") is not None
                    else ""
                )
                terminal.say(
                    f"{finding['severity']} {finding['code']}: {finding['message']}{metric}"
                )
            terminal.say(f"Relatório: {report_markdown}")
            if outcome.exit_reason == "ok":
                if "save_decision" not in review_effect:
                    raise RuntimeError("state machine não solicitou confirmação do perfil")
                artifacts = capture.finish()
                save = terminal.ask_confirm("Salvar o perfil de calibração?", default=True)
                save_effect = dispatch(SaveDecision(save))
                if not save:
                    if "summary" not in save_effect:
                        raise RuntimeError("state machine não concluiu o resumo")
                    terminal.say("Artefatos preservados; nenhum perfil foi salvo.")
                    _summary(
                        terminal,
                        device.device_id,
                        started_ns,
                        timer,
                        total_retries,
                        status,
                        artifacts,
                        report_json,
                        report_markdown,
                        None,
                        mapping_path,
                    )
                    return 0
                if "save" not in save_effect:
                    raise RuntimeError("state machine não solicitou persistência do perfil")
                if outcome.profile is None:
                    terminal.say("erro: motor não retornou um perfil; nenhum perfil foi salvo")
                    return 4
                store = JsonProfileStore(Path(args.profiles_dir))
                outcome.report["profile_summary"]["profile_id"] = outcome.profile.profile_id
                report_json, report_markdown = _write_reports(Path(artifacts.directory), outcome)
                save_profile(store, outcome)
                if "summary" not in dispatch(Continue()):
                    raise RuntimeError("state machine não concluiu o resumo")
                profile_id = outcome.profile.profile_id
                _summary(
                    terminal,
                    device.device_id,
                    started_ns,
                    timer,
                    total_retries,
                    status,
                    artifacts,
                    report_json,
                    report_markdown,
                    profile_id,
                    mapping_path,
                )
                return 0
            if outcome.exit_reason == "profile_not_derivable":
                if state.phase is not WizardPhase.FAILED:
                    raise RuntimeError("state machine não bloqueou perfil não derivável")
                artifacts = capture.finish()
                terminal.say(f"erro: perfil não derivável: {outcome.message}")
                _summary(
                    terminal,
                    device.device_id,
                    started_ns,
                    timer,
                    total_retries,
                    status,
                    artifacts,
                    report_json,
                    report_markdown,
                    None,
                    mapping_path,
                )
                return 4
            if targets is None:
                if state.phase is not WizardPhase.FAILED:
                    raise RuntimeError("state machine não bloqueou achados sem retry seguro")
                artifacts = capture.finish()
                terminal.say("erro: qualidade bloqueante sem segmento de retry seguro")
                _summary(
                    terminal,
                    device.device_id,
                    started_ns,
                    timer,
                    total_retries,
                    status,
                    artifacts,
                    report_json,
                    report_markdown,
                    None,
                    mapping_path,
                )
                return 4
            target = targets[0]
            if total_retries >= 6 or retries_by_target[target] >= args.max_retries:
                artifacts = capture.finish()
                terminal.say("erro: limite de retries atingido; nenhum perfil foi salvo")
                _summary(
                    terminal,
                    device.device_id,
                    started_ns,
                    timer,
                    total_retries,
                    status,
                    artifacts,
                    report_json,
                    report_markdown,
                    None,
                    mapping_path,
                )
                return 4
            name = "/".join(target)
            if "retry_decision" not in review_effect:
                raise RuntimeError("state machine não solicitou decisão de retry")
            if not terminal.ask_confirm(f"Repetir o segmento: {name}?", default=True):
                dispatch(RetryDecision(False))
                artifacts = capture.finish()
                _summary(
                    terminal,
                    device.device_id,
                    started_ns,
                    timer,
                    total_retries,
                    status,
                    artifacts,
                    report_json,
                    report_markdown,
                    None,
                    mapping_path,
                )
                return 4
            if "record_retry" not in dispatch(RetryDecision(True)):
                raise RuntimeError("state machine não iniciou o retry")
            review_ready = False
            capture.resume()
            retries_by_target[target] += 1
            total_retries += 1
            plan = next(plan for plan in plans if plan.target == target)
            record_plan(plan)
            capture.flush()
            if "measure" not in dispatch(SegmentCompleted()):
                raise RuntimeError("state machine não solicitou nova medição após retry")
            capture.pause()
            artifacts = capture.flush()
    except CalibrationCancelled, KeyboardInterrupt:
        dispatch(Cancel())
        if review_ready:
            artifacts = capture.finish()
            terminal.say(
                "calibração cancelada após a medição; artefatos preservados em "
                f"{artifacts.directory}"
            )
        else:
            artifacts = capture.abort()
            terminal.say(
                f"calibração cancelada; captura incompleta preservada em {artifacts.capture_path}"
            )
        return 130
    except DeviceDisconnectedError as exc:
        artifacts = capture.abort()
        terminal.say(
            f"erro: controle desconectado ({exc}); captura parcial: {artifacts.capture_path}"
        )
        return 3
    except _QualityBlocked:
        artifacts = capture.abort()
        terminal.say(f"erro: segmento inválido; captura parcial: {artifacts.capture_path}")
        return 4
    except (MeasurementInputError, InvalidMappingError, OSError, ValueError) as exc:
        artifacts = capture.abort()
        terminal.say(f"erro: {exc}; captura parcial: {artifacts.capture_path}")
        return 2
    except Exception as exc:
        artifacts = capture.abort()
        terminal.say(
            f"erro inesperado ({type(exc).__name__}): {exc}; captura: {artifacts.capture_path}"
        )
        return 1
    finally:
        capture.close()
    return 1


def _summary(
    console: Console,
    device_id: str,
    started_ns: int,
    clock: Clock,
    retries: int,
    status: str,
    artifacts: CaptureArtifacts,
    report_json: Path,
    report_markdown: Path,
    profile_id: str | None,
    mapping_path: Path,
) -> None:
    duration = max(0.0, (clock.now_ns() - started_ns) / 1_000_000_000)
    console.say(
        f"Resumo: dispositivo={device_id}; duração={duration:.1f} s; retries={retries}; "
        f"qualidade={status}"
    )
    console.say(f"Captura: {artifacts.capture_path}")
    console.say(f"Manifesto: {artifacts.manifest_path}")
    console.say(f"Relatórios: {report_json} e {report_markdown}")
    if profile_id:
        console.say(f"profile_id: {profile_id}")
        console.say(
            f"Próximo comando: zonepad run --device {device_id} --profile {profile_id} "
            f"--mapping {mapping_path}"
        )
