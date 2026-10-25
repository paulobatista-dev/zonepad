from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

os.environ["QT_QPA_PLATFORM"] = "offscreen"

import pytest

pytest.importorskip("PySide6")

from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication

from zonepad.application.calibration_plan import calibration_plans
from zonepad.application.hotplug import validate_poll_interval
from zonepad.domain.input import NormalizedFrame
from zonepad.infrastructure.mapping import loads_device_mapping
from zonepad.interface import calibration_cli
from zonepad.interface.gui import app as gui_app
from zonepad.interface.gui import calibration_worker as gui_calibration_worker
from zonepad.interface.gui import main_window as gui_window_module
from zonepad.interface.gui.calibration_worker import format_quality_findings
from zonepad.interface.gui.main_window import MainWindow
from zonepad.interface.gui.viewmodels.monitor import FrameRateWindow
from zonepad.interface.gui.widgets import ButtonIndicators, StickWidget, TriggerBarWidget
from zonepad.interface.gui.workers import FrameMailbox


@pytest.fixture
def app() -> QApplication:
    instance = QApplication.instance()
    return instance or QApplication([])


def _mapping_fixture():
    return loads_device_mapping(
        '{"schema_version":1,'
        '"axes":{'
        '"lx":{"code":0,"minimum":-10,"center":0,"maximum":10},'
        '"ly":{"code":1,"minimum":-10,"center":0,"maximum":10},'
        '"rx":{"code":2,"minimum":-10,"center":0,"maximum":10},'
        '"ry":{"code":3,"minimum":-10,"center":0,"maximum":10}},'
        '"triggers":{'
        '"lt":{"code":4,"rest":32,"maximum":255},'
        '"rt":{"code":5,"rest":64,"maximum":255}},'
        '"buttons":{}}'
    )


def test_gui_usa_os_mesmos_planos_do_cli() -> None:
    assert calibration_cli.calibration_plans is calibration_plans
    assert gui_calibration_worker.calibration_plans is calibration_plans
    assert gui_calibration_worker.retry_targets is calibration_cli.retry_targets
    plans = calibration_plans(2.0, 5.0, 6.0, 25.0)
    assert len(plans) == 7
    assert plans[0].target == ("rest",)
    assert plans[-1].target == ("trigger", "right")


def test_frame_rate_usa_timestamps_distintos_na_janela() -> None:
    rate = FrameRateWindow()
    assert rate.push(0) is None
    assert rate.push(0) is None
    assert rate.push(500_000_000) == pytest.approx(2.0)
    assert rate.push(1_000_000_000) == pytest.approx(2.0)
    assert rate.push(2_000_000_000) == pytest.approx(1.0)


def test_frame_mailbox_preserva_somente_o_snapshot_mais_recente() -> None:
    mailbox = FrameMailbox()
    first = NormalizedFrame("test", 1, {}, {}, frozenset())
    second = NormalizedFrame("test", 2, {}, {}, frozenset())
    mailbox.publish(first, 1.0)
    mailbox.publish(second, 2.0)
    value = mailbox.take()
    assert value is not None
    assert value.frame.timestamp_ns == 2
    assert value.observed_hz == 2.0
    assert mailbox.take() is None


def test_botoes_mapeados_apresentam_subset_e_estado_textual(app: QApplication) -> None:
    del app
    buttons = ButtonIndicators(("button_south", "button_west"))
    buttons.set_pressed(frozenset({"button_south"}))
    assert "Sul pressionado" in buttons.accessibleDescription()
    assert "Oeste solto" in buttons.accessibleDescription()

    empty = ButtonIndicators(())
    empty.set_pressed(frozenset())
    assert empty.accessibleDescription() == "Nenhum botão mapeado"

    stick = StickWidget("Stick esquerdo", "lx", "ly")
    assert stick.readout_text == "lx aguardando · ly aguardando"
    assert stick.axes_range_text == "lx [-1, 1] · ly [-1, 1]"
    assert "aguardando" in stick.accessibleDescription()
    stick.set_value(0.5, -0.25)
    assert stick.readout_text == "lx +0.500 · ly -0.250"
    assert stick.axes_range_text in stick.accessibleDescription()
    trigger = TriggerBarWidget("Gatilho esquerdo")
    assert "aguardando" in trigger.readout_text
    trigger.set_reference(0.0, provisional=True)
    trigger.set_value(0.75)
    assert trigger.readout_text == (
        "Gatilho esquerdo: 0.750 · repouso mapping 0.000 · mapping provisório"
    )
    assert trigger.accessibleDescription() == trigger.readout_text


def test_monitor_e_calibracao_exigem_mapping_validado(app: QApplication) -> None:
    del app
    identity = SimpleNamespace(
        stable_id="usb-0001-0002-u1234567890",
        facts=SimpleNamespace(name="Controle de teste", vendor_id=1, product_id=2),
        connection=SimpleNamespace(value="usb"),
        fragile=False,
        warnings=(),
    )
    resolved = SimpleNamespace(
        identity=identity,
        device=SimpleNamespace(observed=SimpleNamespace(event_node="event0")),
        event_node="event0",
    )
    discovered = SimpleNamespace(
        resolved=resolved,
        mapping_status="saved",
        mapping_detail=None,
    )
    session_resolution = SimpleNamespace(
        mapping=_mapping_fixture(),
        mapping_path=Path("mapping.json"),
        mapping_ref=SimpleNamespace(status="saved", provisional=False),
    )

    class Adapter:
        def list_devices(self) -> tuple[object, ...]:
            return (discovered,)

        def resolve_session(self, stable_id: str) -> object:
            assert stable_id == identity.stable_id
            return session_resolution

    window = MainWindow(Adapter(), enable_hotplug=False)  # type: ignore[arg-type]
    window.refresh_devices()
    assert window._device_list.count() == 1
    assert not window._monitor_button.isEnabled()
    assert not window._wizard_button.isEnabled()

    window._validate_mapping()
    assert window._monitor_button.isEnabled()
    assert window._wizard_button.isEnabled()

    nav = window._navigation[1]
    spy = QSignalSpy(nav.clicked)
    nav.click()
    assert spy.count() == 1
    assert window._pages.currentIndex() == 1
    window.close()


def test_monitor_tolera_frames_iniciais_com_canais_parciais(app: QApplication) -> None:
    del app

    class Adapter:
        def list_devices(self) -> tuple[object, ...]:
            return ()

    window = MainWindow(Adapter(), enable_hotplug=False)  # type: ignore[arg-type]
    window._mailbox.publish(NormalizedFrame("test", 1, {"lx": 0.25}, {}, frozenset()), None)
    window._consume_frame()
    assert window._monitor_channels.text() == "Canais: aguardando ly, rx, ry, lt, rt"
    assert window._sticks["left"].readout_text == "lx +0.250 · ly aguardando"
    assert (
        window._triggers["lt"].readout_text
        == "Gatilho esquerdo: aguardando · repouso mapping aguardando"
    )
    window.close()


def test_monitor_mostra_referencia_de_repouso_e_mapping_provisorio(
    app: QApplication,
) -> None:
    del app
    mapping = _mapping_fixture()
    resolution = SimpleNamespace(
        mapping=mapping,
        mapping_ref=SimpleNamespace(provisional=True),
    )

    class Adapter:
        def list_devices(self) -> tuple[object, ...]:
            return ()

    window = MainWindow(Adapter(), enable_hotplug=False)  # type: ignore[arg-type]
    window._show_monitor_mapping(resolution)  # type: ignore[arg-type]
    assert "Mapping provisório" in window._monitor_mapping_status.text()
    for name in ("lt", "rt"):
        assert "repouso mapping 0.000" in window._triggers[name].readout_text
        assert "mapping provisório" in window._triggers[name].readout_text
    window.close()


def test_poll_hotplug_usa_intervalo_validado(app: QApplication) -> None:
    del app

    class Adapter:
        def list_devices(self) -> tuple[object, ...]:
            return ()

    window = MainWindow(Adapter(), enable_hotplug=True)  # type: ignore[arg-type]
    assert window._discovery_timer.isActive()
    assert window._discovery_timer.interval() == round(validate_poll_interval(2.0) * 1_000)
    window.close()


def test_findings_apresentam_metricas_e_redigem_paths() -> None:
    text = format_quality_findings(
        [
            {
                "severity": "warning",
                "code": "HIGH_DRIFT",
                "metric": "sticks.left.drift",
                "message": "Deriva acima do limite.",
                "value": 0.04,
                "threshold": 0.02,
            },
            {
                "severity": "error",
                "code": "BAD",
                "metric": "/home/private/capture.json",
                "message": "Entrada inválida.",
            },
        ]
    )
    assert "sticks.left.drift" in text
    assert "valor=0.04" in text
    assert "limite=0.02" in text
    assert "/home/private" not in text
    assert " · métrica:" in text


def test_smoke_monta_janela_sem_iniciar_discovery(
    app: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    del app

    class InertAdapter:
        def list_devices(self) -> tuple[object, ...]:
            raise AssertionError("smoke não deve descobrir dispositivos")

        def poll_devices(self) -> tuple[object, ...]:
            raise AssertionError("smoke não deve observar hot-plug")

    monkeypatch.setattr(gui_window_module, "DeviceAdapter", lambda: InertAdapter())
    assert gui_app.run_app(smoke=True) == 0


def test_close_waits_cooperatively_for_calibration_worker(app: QApplication) -> None:
    del app
    class Adapter:
        def list_devices(self) -> tuple[object, ...]:
            return ()

    class RunningThread:
        running = True
        interruption_requested = False

        def isRunning(self) -> bool:
            return self.running

        def requestInterruption(self) -> None:
            self.interruption_requested = True

        def deleteLater(self) -> None:
            pass

    window = MainWindow(Adapter(), enable_hotplug=False)  # type: ignore[arg-type]
    thread = RunningThread()
    window._calibration_thread = thread
    window._calibration_worker = object()
    window.show()
    assert not window.close()
    assert window.isVisible()
    assert window._close_pending
    assert thread.interruption_requested
    assert "permanecerá aberta" in window._shutdown_status.text()
    assert window._calibration_thread is thread
    thread.running = False
    window._calibration_stopped()
    for _ in range(5):
        QApplication.processEvents()
    assert not window.isVisible()
