"""Main Qt window and four application panels."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path

from PySide6.QtCore import QSignalBlocker, Qt, QThread, QTimer
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from zonepad.application.hotplug import validate_poll_interval
from zonepad.application.profile_listing import list_profiles
from zonepad.domain.normalization import normalize_trigger
from zonepad.infrastructure.clock import SystemClock
from zonepad.infrastructure.json_profile_store import JsonProfileStore
from zonepad.infrastructure.measure_runner import MeasureRunner

from .adapters.devices import DeviceAdapter, GuiDiscoveredDevice, SessionResolution
from .adapters.measure import MeasureRunnerAdapter
from .calibration_worker import GuiCalibrationWorker
from .viewmodels.devices import DeviceItem, status_label
from .viewmodels.profiles import profile_item
from .widgets import ButtonIndicators, StickWidget, TriggerBarWidget, mapped_button_names
from .workers import DeviceReadWorker, FrameMailbox

LOGGER = logging.getLogger("zonepad.gui")


def _panel(title: str, description: str) -> tuple[QWidget, QVBoxLayout]:
    widget = QWidget()
    layout = QVBoxLayout(widget)
    heading = QLabel(title)
    heading.setStyleSheet("font-size: 20px; font-weight: 600")
    layout.addWidget(heading)
    text = QLabel(description)
    text.setWordWrap(True)
    layout.addWidget(text)
    return widget, layout


class MainWindow(QMainWindow):
    def __init__(
        self,
        adapter: DeviceAdapter | None = None,
        *,
        enable_hotplug: bool = True,
    ) -> None:
        super().__init__()
        self.setWindowTitle("ZonaPad — calibração guiada")
        self.resize(980, 720)
        self.setAccessibleName("ZonaPad")
        self._adapter = adapter or DeviceAdapter()
        self._devices: dict[str, GuiDiscoveredDevice] = {}
        self._selected: DeviceItem | None = None
        self._mapping_validated_id: str | None = None
        self._thread: QThread | None = None
        self._worker: DeviceReadWorker | None = None
        self._calibration_thread: QThread | None = None
        self._calibration_worker: GuiCalibrationWorker | None = None
        self._close_pending = False
        self._mailbox = FrameMailbox()
        self._monitor_timer = QTimer(self)
        self._monitor_timer.setInterval(34)
        self._monitor_timer.timeout.connect(self._consume_frame)
        self._discovery_timer = QTimer(self)
        poll_interval = validate_poll_interval(2.0)
        self._discovery_timer.setInterval(round(poll_interval * 1_000))
        self._discovery_timer.timeout.connect(self._poll_hotplug)

        root = QWidget()
        root_layout = QVBoxLayout(root)
        nav = QHBoxLayout()
        self._pages = QStackedWidget()
        self._navigation: list[QPushButton] = []
        for index, name in enumerate(("Dispositivos", "Monitor", "Calibração", "Perfis")):
            button = QPushButton(name)
            button.setCheckable(True)
            button.setAccessibleName(f"Abrir painel {name}")
            button.clicked.connect(lambda _checked=False, page=index: self._show_page(page))
            nav.addWidget(button)
            self._navigation.append(button)
        root_layout.addLayout(nav)
        self._shutdown_status = QLabel()
        self._shutdown_status.setWordWrap(True)
        self._shutdown_status.setAccessibleName("Estado de encerramento")
        self._shutdown_status.hide()
        root_layout.addWidget(self._shutdown_status)
        root_layout.addWidget(self._pages, 1)
        self.setCentralWidget(root)
        self._build_devices_page()
        self._build_monitor_page()
        self._build_calibration_page()
        self._build_profiles_page()
        self._show_page(0)
        if enable_hotplug:
            self._discovery_timer.start()

    def _show_page(self, index: int) -> None:
        self._pages.setCurrentIndex(index)
        for position, button in enumerate(self._navigation):
            button.setChecked(position == index)
        if index == 3:
            self.refresh_profiles()

    def _build_devices_page(self) -> None:
        page, layout = _panel(
            "Dispositivos",
            "A seleção usa a identidade estável. eventN é exibido como detalhe da conexão atual.",
        )
        self._device_list = QListWidget()
        self._device_list.setAccessibleName("Gamepads descobertos")
        self._device_list.currentRowChanged.connect(self._select_row)
        layout.addWidget(self._device_list, 1)
        self._device_status = QLabel("Atualize para procurar gamepads.")
        self._device_status.setWordWrap(True)
        layout.addWidget(self._device_status)
        actions = QHBoxLayout()
        refresh = QPushButton("Atualizar (Ctrl+R)")
        refresh.setShortcut("Ctrl+R")
        refresh.clicked.connect(self.refresh_devices)
        actions.addWidget(refresh)
        self._validate_button = QPushButton("Validar mapping")
        self._validate_button.clicked.connect(self._validate_mapping)
        actions.addWidget(self._validate_button)
        layout.addLayout(actions)
        self._pages.addWidget(page)

    def _build_monitor_page(self) -> None:
        page, layout = _panel(
            "Monitor normalizado",
            "Sticks: [-1, 1]. Gatilhos: [0, 1]. Y positivo aponta para cima. "
            "Esta tela é somente leitura.",
        )
        sticks = QHBoxLayout()
        self._sticks = {
            "left": StickWidget("Stick esquerdo", "lx", "ly"),
            "right": StickWidget("Stick direito", "rx", "ry"),
        }
        for widget in self._sticks.values():
            sticks.addWidget(widget)
        layout.addLayout(sticks)
        self._triggers: dict[str, TriggerBarWidget] = {
            name: TriggerBarWidget(title)
            for name, title in (("lt", "Gatilho esquerdo"), ("rt", "Gatilho direito"))
        }
        self._last_axes: dict[str, float | None] = {name: None for name in ("lx", "ly", "rx", "ry")}
        self._last_triggers: dict[str, float | None] = {name: None for name in ("lt", "rt")}
        self._monitor_mapping_status = QLabel("Mapping: aguardando validação")
        self._monitor_mapping_status.setAccessibleName("Estado de referência do mapping")
        layout.addWidget(self._monitor_mapping_status)
        for trigger_widget in self._triggers.values():
            layout.addWidget(trigger_widget)
        self._buttons = ButtonIndicators(())
        layout.addWidget(self._buttons)
        self._monitor_rate = QLabel("Taxa observada: aguardando frames")
        layout.addWidget(self._monitor_rate)
        self._monitor_channels = QLabel("Canais: aguardando leitura inicial")
        self._monitor_channels.setAccessibleName("Estado dos canais lidos")
        layout.addWidget(self._monitor_channels)
        self._monitor_status = QLabel("Selecione um dispositivo com mapping válido.")
        self._monitor_status.setWordWrap(True)
        layout.addWidget(self._monitor_status)
        self._monitor_button = QPushButton("Iniciar monitor")
        self._monitor_button.clicked.connect(self._toggle_monitor)
        layout.addWidget(self._monitor_button)
        self._pages.addWidget(page)

    def _build_calibration_page(self) -> None:
        page, layout = _panel(
            "Calibração guiada",
            "O protocolo mede repouso, os dois sticks e os dois gatilhos. Mantenha o "
            "controle apoiado e siga as instruções de cada etapa.",
        )
        self._wizard_status = QLabel(
            "Selecione um dispositivo e valide o mapping antes de iniciar. "
            "Identidades frágeis pedem confirmação contextual."
        )
        self._wizard_status.setWordWrap(True)
        layout.addWidget(self._wizard_status)
        self._wizard_button = QPushButton("Iniciar calibração")
        self._wizard_button.clicked.connect(self._start_calibration)
        layout.addWidget(self._wizard_button)
        self._cancel_wizard_button = QPushButton("Cancelar calibração (Esc)")
        self._cancel_wizard_button.setShortcut("Esc")
        self._cancel_wizard_button.setEnabled(False)
        self._cancel_wizard_button.clicked.connect(self._cancel_calibration)
        layout.addWidget(self._cancel_wizard_button)
        layout.addStretch(1)
        self._pages.addWidget(page)

    def _build_profiles_page(self) -> None:
        page, layout = _panel("Perfis", "Inspeção somente leitura de perfis locais.")
        self._profile_list = QListWidget()
        self._profile_list.setAccessibleName("Perfis salvos")
        layout.addWidget(self._profile_list, 1)
        self._profile_detail = QLabel("Selecione um perfil para inspecionar.")
        self._profile_detail.setWordWrap(True)
        layout.addWidget(self._profile_detail)
        self._profile_list.currentItemChanged.connect(
            lambda current, _previous: self._profile_detail.setText(
                current.data(Qt.ItemDataRole.UserRole + 1) if current else "Selecione um perfil."
            )
        )
        refresh = QPushButton("Atualizar perfis")
        refresh.clicked.connect(self.refresh_profiles)
        layout.addWidget(refresh)
        self._pages.addWidget(page)

    def refresh_devices(self) -> None:
        try:
            devices = self._adapter.list_devices()
        except (OSError, RuntimeError, ValueError) as exc:
            self._device_status.setText(
                f"Falha ao procurar dispositivos ({type(exc).__name__}). "
                "Verifique o diagnóstico `zonepad devices` e tente atualizar."
            )
            LOGGER.exception("device discovery failed")
            return
        self._render_devices(devices)

    def _poll_hotplug(self) -> None:
        try:
            devices = self._adapter.poll_devices()
        except (OSError, RuntimeError, ValueError) as exc:
            self._device_status.setText(
                f"Falha ao observar conexões: {type(exc).__name__}. Atualize para tentar novamente."
            )
            LOGGER.exception("hotplug polling failed")
            return
        self._render_devices(devices)

    def _render_devices(self, devices: tuple[GuiDiscoveredDevice, ...]) -> None:
        previous_id = self._selected.stable_id if self._selected is not None else None
        previously_validated = self._mapping_validated_id
        active_monitor = self._thread is not None and self._thread.isRunning()
        blocker = QSignalBlocker(self._device_list)
        self._devices.clear()
        self._device_list.clear()
        for discovered in devices:
            resolved = discovered.resolved
            identity = resolved.identity
            facts = identity.facts
            item = DeviceItem(
                str(identity.stable_id),
                facts.name or resolved.device.observed.event_node,
                facts.vendor_id,
                facts.product_id,
                identity.connection.value,
                resolved.event_node,
                status_label(discovered.mapping_status),
                identity.fragile,
                identity.warnings,
            )
            self._devices[item.stable_id] = discovered
            self._device_list.addItem(item.label)
            self._device_list.item(self._device_list.count() - 1).setData(
                Qt.ItemDataRole.UserRole, item.stable_id
            )
        if not devices:
            self._device_status.setText(
                "Nenhum gamepad encontrado. Confira a conexão e consulte "
                "`zonepad devices` para diagnóstico."
            )
        selected_row = next(
            (
                row
                for row in range(self._device_list.count())
                if self._device_list.item(row).data(Qt.ItemDataRole.UserRole) == previous_id
            ),
            -1 if active_monitor else (0 if self._device_list.count() else -1),
        )
        self._device_list.setCurrentRow(selected_row)
        del blocker
        monitor_thread = self._thread
        if active_monitor and selected_row < 0 and monitor_thread is not None:
            monitor_thread.requestInterruption()
            self._monitor_status.setText(
                "O dispositivo foi desconectado. Encerrando leitura; atualize a lista."
            )
        self._select_row(selected_row)
        if previous_id is not None and previous_id == previously_validated:
            try:
                self._adapter.resolve_session(previous_id)
            except Exception:
                self._mapping_validated_id = None
                self._monitor_button.setEnabled(False)
                self._wizard_button.setEnabled(False)
                self._device_status.setText(
                    "Mapping não está válido. Valide novamente ou gere outro com "
                    f"`zonepad mapping draft --device {previous_id}`."
                )
            else:
                self._mapping_validated_id = previous_id
                self._monitor_button.setEnabled(True)
                self._wizard_button.setEnabled(True)

    def _select_row(self, row: int) -> None:
        if self._thread is not None and self._thread.isRunning() and row >= 0:
            candidate_id = self._device_list.item(row).data(Qt.ItemDataRole.UserRole)
            if self._selected is not None and candidate_id != self._selected.stable_id:
                self._device_status.setText("Encerre o monitor antes de trocar de dispositivo.")
                blocker = QSignalBlocker(self._device_list)
                current_row = next(
                    (
                        index
                        for index in range(self._device_list.count())
                        if self._device_list.item(index).data(Qt.ItemDataRole.UserRole)
                        == self._selected.stable_id
                    ),
                    -1,
                )
                self._device_list.setCurrentRow(current_row)
                del blocker
                return
        if row < 0 or row >= self._device_list.count():
            self._selected = None
            self._mapping_validated_id = None
            self._monitor_button.setEnabled(False)
            self._wizard_button.setEnabled(False)
            return
        stable_id = self._device_list.item(row).data(Qt.ItemDataRole.UserRole)
        discovered = self._devices.get(stable_id)
        if discovered is None:
            return
        identity = discovered.resolved.identity
        facts = identity.facts
        self._selected = DeviceItem(
            stable_id,
            facts.name or discovered.resolved.event_node,
            facts.vendor_id,
            facts.product_id,
            identity.connection.value,
            discovered.resolved.event_node,
            status_label(discovered.mapping_status),
            identity.fragile,
            identity.warnings,
        )
        if self._mapping_validated_id != stable_id:
            self._mapping_validated_id = None
        detail = f"{self._selected.label}"
        if identity.warnings:
            detail += "\nAvisos: " + ", ".join(identity.warnings)
        if discovered.mapping_detail:
            detail += f"\nMapping: {discovered.mapping_detail}"
        self._device_status.setText(detail)
        mapping_valid = self._mapping_validated_id == stable_id
        self._monitor_button.setEnabled(mapping_valid)
        self._wizard_button.setEnabled(mapping_valid)

    def _validate_mapping(self) -> None:
        selected = self._selected
        if selected is None:
            return
        try:
            resolution = self._adapter.resolve_session(selected.stable_id)
        except Exception as exc:
            self._device_status.setText(
                f"Mapping não disponível ou inválido ({type(exc).__name__}). Gere ou valide "
                f"com `zonepad mapping draft --device {selected.stable_id}`."
            )
            self._monitor_button.setEnabled(False)
            self._wizard_button.setEnabled(False)
            return
        self._device_status.setText(
            f"Mapping válido: {resolution.mapping_path.name} ({resolution.mapping_ref.status})."
        )
        self._show_monitor_mapping(resolution)
        self._mapping_validated_id = selected.stable_id
        self._monitor_button.setEnabled(True)
        self._wizard_button.setEnabled(True)

    def _toggle_monitor(self) -> None:
        if self._thread is not None:
            self._stop_monitor()
            return
        selected = self._selected
        if selected is None:
            return
        try:
            resolution = self._adapter.resolve_session(selected.stable_id)
            mapped = mapped_button_names(resolution.mapping.button_codes)
        except Exception as exc:
            self._monitor_status.setText(
                f"Mapping inválido ({type(exc).__name__}). Corrija com "
                f"`zonepad mapping draft --device {selected.stable_id}`."
            )
            return
        self._buttons.set_mapped(mapped)
        self._show_monitor_mapping(resolution)
        self._last_axes = {name: None for name in ("lx", "ly", "rx", "ry")}
        self._last_triggers = {name: None for name in ("lt", "rt")}
        self._sticks["left"].set_value(None, None)
        self._sticks["right"].set_value(None, None)
        for widget in self._triggers.values():
            widget.set_value(None)
        self._monitor_rate.setText("Taxa observada: aguardando frames")
        self._monitor_channels.setText("Canais: aguardando leitura inicial")
        self._monitor_status.setText("Conectando ao dispositivo…")
        self._monitor_button.setText("Parar monitor")
        self._thread = QThread(self)
        self._worker = DeviceReadWorker(
            lambda: self._adapter.open_session(resolution), self._mailbox
        )
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.failed.connect(self._monitor_failed)
        self._worker.finished.connect(self._thread.quit)
        self._worker.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._monitor_stopped)
        self._thread.start()
        self._monitor_timer.start()

    def _show_monitor_mapping(self, resolution: SessionResolution) -> None:
        mapping_ref = resolution.mapping_ref
        provisional = mapping_ref.provisional is True
        self._monitor_mapping_status.setText(
            "Mapping provisório: repouso dos gatilhos usa a referência do draft."
            if provisional
            else "Mapping validado: repouso dos gatilhos usa a referência salva."
        )
        for name, widget in self._triggers.items():
            trigger_range = resolution.mapping.triggers[name]
            rest_reference = normalize_trigger(trigger_range.rest, trigger_range)
            widget.set_reference(rest_reference, provisional=provisional)

    def _consume_frame(self) -> None:
        value = self._mailbox.take()
        if value is None:
            return
        frame = value.frame
        axes = frame.axes
        missing: list[str] = []
        for name in self._last_axes:
            if name in axes:
                self._last_axes[name] = axes[name]
            else:
                missing.append(name)
        self._sticks["left"].set_value(self._last_axes["lx"], self._last_axes["ly"])
        self._sticks["right"].set_value(self._last_axes["rx"], self._last_axes["ry"])
        for name, widget in self._triggers.items():
            if name in frame.triggers:
                self._last_triggers[name] = frame.triggers[name]
            else:
                missing.append(name)
            widget.set_value(self._last_triggers[name])
        self._buttons.set_pressed(frame.buttons)
        self._monitor_channels.setText(
            "Canais: aguardando " + ", ".join(missing)
            if missing
            else "Canais: sticks, gatilhos e botões disponíveis"
        )
        hz = "aquecendo" if value.observed_hz is None else f"{value.observed_hz:.1f} Hz"
        self._monitor_rate.setText(f"Taxa observada: {hz}")
        self._monitor_status.setText("Conectado · camada normalizada · aquisição integral")

    def _monitor_failed(self, message: str) -> None:
        if "Permission denied" in message or "PermissionError" in message:
            self._monitor_status.setText(
                "Permissão negada ao ler o controle. Confira a ACL da sessão; "
                "se necessário, consulte a política do grupo input da distribuição."
            )
        else:
            self._monitor_status.setText(
                f"Leitura interrompida: {message}. Atualize a seleção e tente novamente."
            )

    def _monitor_stopped(self) -> None:
        self._monitor_timer.stop()
        self._worker = None
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.deleteLater()
        if self._monitor_button is not None:
            self._monitor_button.setText("Iniciar monitor")
        self._finish_pending_close()

    def _stop_monitor(self) -> None:
        self._monitor_timer.stop()
        if self._thread is not None:
            self._thread.requestInterruption()
            if not self._thread.wait(2_000):
                LOGGER.error("device reader did not stop within 2 seconds")

    def _start_calibration(self) -> None:
        if self._thread is not None:
            self._wizard_status.setText("Encerre o monitor antes de iniciar a calibração.")
            return
        selected = self._selected
        if selected is None:
            return
        try:
            resolution = self._adapter.resolve_session(selected.stable_id)
        except Exception as exc:
            self._wizard_status.setText(
                f"Mapping inválido ({type(exc).__name__}). Gere ou corrija com "
                f"`zonepad mapping draft --device {selected.stable_id}`."
            )
            return
        if selected.fragile:
            answer = QMessageBox.question(
                self,
                "Confirmar identidade",
                f"A identidade deste controle é frágil ({selected.stable_id}).\n\n"
                "Confirma que este é o controle correto?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self._wizard_button.setEnabled(False)
        self._monitor_button.setEnabled(False)
        self._wizard_status.setText("Iniciando sessão de calibração…")
        thread = QThread(self)
        worker = GuiCalibrationWorker(
            resolution,
            lambda: self._adapter.open_session(resolution),
            SystemClock(),
            MeasureRunnerAdapter(
                MeasureRunner(
                    now=lambda: datetime.now(UTC),
                    profile_id_factory=lambda: str(uuid.uuid4()),
                )
            ),
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.question.connect(self._calibration_question)
        worker.progress.connect(self._wizard_status.setText)
        worker.completed.connect(self._calibration_completed)
        worker.failed.connect(self._calibration_failed)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(self._calibration_stopped)
        self._calibration_thread = thread
        self._calibration_worker = worker
        self._cancel_wizard_button.setEnabled(True)
        thread.start()

    def _cancel_calibration(self) -> None:
        if self._calibration_thread is None:
            return
        self._calibration_thread.requestInterruption()
        self._cancel_wizard_button.setEnabled(False)
        self._wizard_status.setText("Cancelando com preservação dos artefatos de captura…")

    def _calibration_question(
        self, question_id: str, title: str, prompt: str, default: bool
    ) -> None:
        buttons = QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        default_button = (
            QMessageBox.StandardButton.Yes if default else QMessageBox.StandardButton.No
        )
        answer = QMessageBox.question(self, title, prompt, buttons, default_button)
        worker = self._calibration_worker
        if worker is not None:
            worker.answer(question_id, answer == QMessageBox.StandardButton.Yes)

    def _calibration_completed(self, message: str) -> None:
        self._wizard_status.setText(message)

    def _calibration_failed(self, message: str) -> None:
        self._wizard_status.setText(message)

    def _calibration_stopped(self) -> None:
        thread, self._calibration_thread = self._calibration_thread, None
        self._calibration_worker = None
        if thread is not None:
            thread.deleteLater()
        if self._selected is not None:
            self._wizard_button.setEnabled(True)
            self._monitor_button.setEnabled(self._mapping_validated_id == self._selected.stable_id)
        self._cancel_wizard_button.setEnabled(False)
        self._finish_pending_close()

    def _finish_pending_close(self) -> None:
        if self._close_pending and self._thread is None and self._calibration_thread is None:
            self._close_pending = False
            QTimer.singleShot(0, self.close)

    def refresh_profiles(self) -> None:
        self._profile_list.clear()
        try:
            store = JsonProfileStore(Path("~/.config/zonepad/profiles"))
            profiles = list_profiles(store, store)
        except OSError as exc:
            self._profile_detail.setText(
                "Não foi possível listar perfis "
                f"({type(exc).__name__}). Verifique as permissões da pasta configurada."
            )
            return
        for listed in profiles:
            item = profile_item(listed)
            self._profile_list.addItem(item.title)
            widget_item = self._profile_list.item(self._profile_list.count() - 1)
            widget_item.setData(Qt.ItemDataRole.UserRole, item.profile_id)
            widget_item.setData(Qt.ItemDataRole.UserRole + 1, item.summary)
            if item.error:
                widget_item.setToolTip(f"{item.profile_id}.json: perfil inválido — {item.error}")
        if not profiles:
            self._profile_detail.setText("Nenhum perfil salvo.")

    def closeEvent(self, event: QCloseEvent) -> None:
        self._discovery_timer.stop()
        self._monitor_timer.stop()
        active_threads = tuple(
            thread
            for thread in (self._thread, self._calibration_thread)
            if thread is not None and thread.isRunning()
        )
        if active_threads:
            self._close_pending = True
            for thread in active_threads:
                thread.requestInterruption()
            self._shutdown_status.setText(
                "Aguardando encerramento cooperativo das operações. "
                "A janela permanecerá aberta até os workers terminarem."
            )
            self._shutdown_status.show()
            event.ignore()
            return
        event.accept()
