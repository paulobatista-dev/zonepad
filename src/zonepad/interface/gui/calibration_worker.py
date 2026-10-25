"""GUI calibration coordinator that reuses the application reducer and policy."""

from __future__ import annotations

import logging
import re
import threading
import uuid
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal, Slot

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
from zonepad.application.calibration_plan import calibration_plans, retry_targets
from zonepad.application.measure import save_profile
from zonepad.application.ports import CaptureSession, Clock, DeviceSession, WizardMeasureRunner
from zonepad.application.report import dumps_report, render_markdown
from zonepad.domain.errors import DeviceDisconnectedError, MeasurementInputError
from zonepad.infrastructure.capture_writer import CaptureWriter, create_session_directory
from zonepad.infrastructure.files import write_text_atomic
from zonepad.infrastructure.json_profile_store import JsonProfileStore
from zonepad.infrastructure.manifest_reader import load_metrics_config

from .adapters.devices import SessionResolution

LOGGER = logging.getLogger("zonepad.gui.calibration")
_SAFE_METRIC = re.compile(r"[A-Za-z0-9_.-]{1,120}\Z", re.ASCII)


def format_quality_findings(findings: Sequence[Mapping[str, object]]) -> str:
    """Present quality context without exposing filesystem paths."""
    if not findings:
        return "Nenhum achado de qualidade."
    formatted: list[str] = []
    for finding in findings:
        severity = str(finding.get("severity", "info"))
        code = str(finding.get("code", "QUALITY_FINDING"))
        metric_value = finding.get("metric")
        metric = (
            str(metric_value)
            if isinstance(metric_value, str) and _SAFE_METRIC.fullmatch(metric_value)
            else "métrica"
        )
        message = str(finding.get("message", "Sem descrição disponível."))
        context: list[str] = []
        value = finding.get("value")
        threshold = finding.get("threshold")
        if value is not None:
            context.append(f"valor={value}")
        if threshold is not None:
            context.append(f"limite={threshold}")
        suffix = f" ({'; '.join(context)})" if context else ""
        formatted.append(f"{severity} {code} · {metric}: {message}{suffix}")
    return "\n".join(formatted)


class UserCancelled(Exception):
    pass


class QualityBlocked(Exception):
    pass


class GuiCalibrationWorker(QObject):
    """Own one device session and the existing capture reader during calibration."""

    question = Signal(str, str, str, bool)
    progress = Signal(str)
    completed = Signal(str)
    failed = Signal(str)
    finished = Signal()

    def __init__(
        self,
        resolution: SessionResolution,
        session_factory: Callable[[], DeviceSession],
        clock: Clock,
        measure_runner: WizardMeasureRunner,
        *,
        capture_root: Path = Path("~/.local/share/zonepad/captures"),
        profiles_root: Path = Path("~/.config/zonepad/profiles"),
        now: Callable[[], datetime] | None = None,
        capture_factory: Callable[[DeviceSession, CaptureWriter, Clock], CaptureSession]
        | None = None,
    ) -> None:
        super().__init__()
        self._resolution = resolution
        self._session_factory = session_factory
        self._capture_root = capture_root
        self._profiles_root = profiles_root
        self._clock = clock
        self._now = now or (lambda: datetime.now(UTC))
        self._capture_factory = capture_factory or self._make_capture
        self._measure_runner = measure_runner
        self._answer_lock = threading.Lock()
        self._answer_event: threading.Event | None = None
        self._answer_value = False
        self._question_id: str | None = None

    @staticmethod
    def _make_capture(
        session: DeviceSession, writer: CaptureWriter, clock: Clock
    ) -> CaptureSession:
        from zonepad.infrastructure.live_capture import LiveCaptureSession

        return LiveCaptureSession(session, writer, clock)

    def answer(self, question_id: str, value: bool) -> None:
        with self._answer_lock:
            if self._question_id != question_id or self._answer_event is None:
                return
            self._answer_value = value
            self._answer_event.set()

    def _ask(self, title: str, prompt: str, *, default: bool = False) -> bool:
        self._check_cancelled()
        question_id = str(uuid.uuid4())
        event = threading.Event()
        with self._answer_lock:
            self._question_id = question_id
            self._answer_event = event
            self._answer_value = default
        self.question.emit(question_id, title, prompt, default)
        while not event.wait(0.1):
            self._check_cancelled()
        with self._answer_lock:
            answer = self._answer_value
            self._question_id = None
            self._answer_event = None
        return answer

    def _check_cancelled(self) -> None:
        if QThread.currentThread().isInterruptionRequested():
            raise UserCancelled

    def _wait(self, seconds: float, label: str) -> None:
        start = self._clock.now_ns()
        deadline = start + int(seconds * 1_000_000_000)
        while True:
            self._check_cancelled()
            remaining = (deadline - self._clock.now_ns()) / 1_000_000_000
            if remaining <= 0:
                return
            self.progress.emit(f"{label}: {remaining:.0f} s")
            self._clock.sleep(min(0.2, remaining))

    @Slot()
    def run(self) -> None:
        capture: CaptureSession | None = None
        opened_session: DeviceSession | None = None
        writer: CaptureWriter | None = None
        review_ready = False
        plans = calibration_plans(2.0, 5.0, 6.0, 25.0)
        state = WizardState()

        def dispatch(event: Event) -> tuple[str, ...]:
            nonlocal state
            state, effects = step(state, event, segment_count=len(plans))
            return tuple(effect.name for effect in effects)

        try:
            config = load_metrics_config(None)
            dispatch(Continue())  # welcome → selection
            dispatch(Continue())  # selection → mapping validation
            dispatch(Continue())  # mapping → identity confirmation
            if not self._ask(
                "Confirmar controle",
                "Confirme que o dispositivo e o mapping selecionados estão corretos.",
                default=False,
            ):
                raise UserCancelled
            effects = dispatch(Continue())
            if "open_capture" not in effects or "warmup" not in effects:
                raise RuntimeError("reducer não solicitou a abertura da captura")
            session = self._session_factory()
            opened_session = session
            stamp = self._now().astimezone(UTC).strftime("%Y-%m-%dT%H-%M-%SZ")
            directory = create_session_directory(
                self._capture_root, session.device_info.device_id, stamp
            )
            writer = CaptureWriter(directory, session.device_info)
            capture = self._capture_factory(session, writer, self._clock)
            opened_session = None
            capture.start()
            self.progress.emit("Aquecimento: deixe o controle sem tocar por 2 s.")

            def warmup_progress(left: float) -> None:
                self._check_cancelled()
                self.progress.emit(f"Aquecimento: {left:.0f} s")

            capture.wait(2.0, warmup_progress)
            dispatch(Continue())  # warmup → first segment prompt
            retries = 0
            retries_by_target: dict[tuple[str, ...], int] = defaultdict(int)
            existing = {plan.target for plan in plans}

            def record(plan: SegmentPlan) -> None:
                nonlocal retries
                while True:
                    if state.phase not in {WizardPhase.SEGMENT_PROMPT, WizardPhase.RECORD_SEGMENT}:
                        raise RuntimeError(f"fase inesperada: {state.phase.value}")
                    dispatch(Continue())
                    if not self._ask(
                        "Próximo movimento",
                        f"{plan.instruction}\n\nQuando estiver pronto, escolha Continuar.",
                        default=False,
                    ):
                        raise UserCancelled
                    for remaining in (3, 2, 1):
                        self.progress.emit(f"Começando em {remaining}…")
                        self._wait(1.0, "Contagem")
                    dispatch(Continue())

                    def update_progress(left: float) -> None:
                        self._check_cancelled()
                        self.progress.emit(f"Capturando: {left:.0f} s")

                    segment = capture.record_segment(
                        plan,
                        plan.duration_seconds,
                        update_progress,
                    )
                    if segment is not None:
                        return
                    can_retry = retries < 6 and retries_by_target[plan.target] < 2
                    dispatch(SegmentRejected(can_retry))
                    if not can_retry:
                        raise QualityBlocked(
                            "O segmento não produziu intervalo observado e atingiu "
                            "o limite de retries."
                        )
                    if not self._ask(
                        "Segmento sem frames",
                        "Não foram observados frames neste intervalo. Repetir este movimento?",
                        default=True,
                    ):
                        dispatch(RetryDecision(False))
                        raise QualityBlocked("O segmento inválido não foi repetido.")
                    dispatch(RetryDecision(True))
                    retries += 1
                    retries_by_target[plan.target] += 1

            for plan in plans:
                record(plan)
                capture.flush()
                dispatch(SegmentCompleted())
            capture.pause()
            artifacts = capture.flush()
            review_ready = True
            while True:
                outcome = self._measure_runner.run(
                    Path(artifacts.capture_path),
                    Path(artifacts.manifest_path),
                    self._resolution.mapping_path,
                    self._resolution.mapping,
                    config,
                )
                # Measurement adapters may run for a while without entering the
                # worker's polling loop. Honor a close/cancel request as soon as
                # that operation returns, before writing or presenting its result.
                self._check_cancelled()
                if outcome.profile is not None:
                    outcome.report["profile_summary"]["profile_id"] = None
                report_json = Path(artifacts.directory) / "report.json"
                report_md = Path(artifacts.directory) / "report.md"
                write_text_atomic(report_json, dumps_report(outcome.report))
                write_text_atomic(report_md, render_markdown(outcome.report))
                targets = retry_targets(outcome, existing)
                dispatch(MeasurementCompleted())
                effects = dispatch(ReviewDecision(targets is not None, outcome.exit_reason == "ok"))
                status = str(outcome.report["quality"]["status"])
                findings = format_quality_findings(outcome.report["quality"]["findings"])
                if outcome.exit_reason == "ok":
                    if "save_decision" not in effects:
                        raise RuntimeError("reducer não solicitou decisão de salvamento")
                    artifacts = capture.finish()
                    save = self._ask(
                        "Resultado da calibração",
                        f"Qualidade: {status}\n\n{findings}\n\nSalvar o perfil?",
                        default=True,
                    )
                    save_effects = dispatch(SaveDecision(save))
                    profile_id: str | None = None
                    if save:
                        if outcome.profile is None or "save" not in save_effects:
                            raise RuntimeError("perfil não derivável para salvamento")
                        outcome.report["profile_summary"]["profile_id"] = outcome.profile.profile_id
                        write_text_atomic(report_json, dumps_report(outcome.report))
                        write_text_atomic(report_md, render_markdown(outcome.report))
                        save_profile(JsonProfileStore(self._profiles_root), outcome)
                        profile_id = outcome.profile.profile_id
                        dispatch(Continue())
                    self.completed.emit(
                        f"Qualidade: {status}. Relatório: {report_md.name}. "
                        + (
                            f"Perfil salvo: {profile_id}"
                            if profile_id
                            else "Artefatos preservados; perfil não salvo."
                        )
                    )
                    return
                if outcome.exit_reason == "profile_not_derivable" or targets is None:
                    capture.finish()
                    self.failed.emit(
                        f"Qualidade bloqueante ({status}). Artefatos: {report_md.name}. "
                        f"{outcome.message or findings}"
                    )
                    return
                target = targets[0]
                if retries >= 6 or retries_by_target[target] >= 2:
                    capture.finish()
                    self.failed.emit(
                        f"Limite de retries atingido. Qualidade: {status}. "
                        f"Relatório: {report_md.name}."
                    )
                    return
                # The review transition above has already entered RETRY_DECISION.
                if not self._ask(
                    "Qualidade requer nova captura",
                    f"Repetir o segmento {'/'.join(target)}?\n\n{findings}",
                    default=True,
                ):
                    dispatch(RetryDecision(False))
                    capture.finish()
                    self.failed.emit(
                        f"Calibração encerrada sem perfil. Qualidade: {status}. "
                        f"Relatório: {report_md.name}."
                    )
                    return
                dispatch(RetryDecision(True))
                capture.resume()
                retries += 1
                retries_by_target[target] += 1
                retry_plan = next(plan for plan in plans if plan.target == target)
                record(retry_plan)
                capture.flush()
                dispatch(SegmentCompleted())
                capture.pause()
                artifacts = capture.flush()
        except UserCancelled:
            dispatch(Cancel())
            if capture is not None:
                if review_ready:
                    artifacts = capture.finish()
                    self.completed.emit(
                        "Calibração cancelada após medição; artefatos em "
                        f"{Path(artifacts.directory).name}."
                    )
                else:
                    artifacts = capture.abort()
                    self.completed.emit(
                        "Calibração cancelada; captura parcial em "
                        f"{Path(artifacts.directory).name}."
                    )
            else:
                self.completed.emit(
                    "Calibração cancelada antes da captura; nenhum artefato foi criado."
                )
        except QualityBlocked as exc:
            if capture is not None:
                artifacts = capture.abort()
                self.failed.emit(
                    f"Qualidade insuficiente no segmento: {exc} "
                    f"Captura parcial: {Path(artifacts.capture_path).name}."
                )
            else:
                self.failed.emit(f"Qualidade insuficiente no segmento: {exc}")
        except DeviceDisconnectedError as exc:
            self.failed.emit(f"Controle desconectado: {exc}. Atualize a seleção e tente novamente.")
            if capture is not None:
                capture.abort()
        except PermissionError as exc:
            self.failed.emit(
                "Permissão negada ao ler o controle. Confira a ACL da sessão; "
                "se necessário, consulte a política do grupo input da distribuição. "
                f"Detalhe: {exc}"
            )
            if capture is not None:
                capture.abort()
        except (MeasurementInputError, OSError, ValueError) as exc:
            self.failed.emit(
                f"Falha na captura ou medição: {exc}. Artefatos parciais foram preservados."
            )
            if capture is not None:
                capture.abort()
        except Exception as exc:
            LOGGER.exception("GUI calibration failed")
            self.failed.emit(f"Falha inesperada ({type(exc).__name__}): {exc}")
            if capture is not None:
                capture.abort()
        finally:
            if capture is not None:
                try:
                    capture.close()
                except Exception:
                    LOGGER.exception("failed to close GUI calibration session")
            elif writer is not None:
                try:
                    writer.abort()
                except Exception:
                    LOGGER.exception("failed to preserve partial capture writer")
            if opened_session is not None:
                try:
                    opened_session.close()
                except Exception:
                    LOGGER.exception("failed to close device session after startup error")
            self.finished.emit()
