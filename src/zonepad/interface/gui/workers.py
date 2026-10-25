"""Qt worker for live reads, with a latest-frame mailbox for coalescing."""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QObject, QThread, Signal, Slot

from zonepad.application.monitor import normalize_monitor_frame
from zonepad.application.ports import DeviceSession
from zonepad.domain.input import NormalizedFrame

from .viewmodels.monitor import FrameRateWindow


@dataclass(frozen=True, slots=True)
class MailboxValue:
    frame: NormalizedFrame
    observed_hz: float | None


class FrameMailbox:
    """Thread-safe single-slot mailbox; UI timers consume only the newest frame."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._value: MailboxValue | None = None

    def publish(self, frame: NormalizedFrame, observed_hz: float | None) -> None:
        with self._lock:
            self._value = MailboxValue(frame, observed_hz)

    def take(self) -> MailboxValue | None:
        with self._lock:
            value, self._value = self._value, None
            return value


class DeviceReadWorker(QObject):
    failed = Signal(str)
    finished = Signal()

    def __init__(self, session_factory: Callable[[], DeviceSession], mailbox: FrameMailbox) -> None:
        super().__init__()
        self._session_factory = session_factory
        self._mailbox = mailbox

    @Slot()
    def run(self) -> None:
        session: DeviceSession | None = None
        try:
            session = self._session_factory()
            ranges = session.normalization_config
            rate = FrameRateWindow()
            while not QThread.currentThread().isInterruptionRequested():
                raw = session.read(0.05)
                if raw is None:
                    continue
                normalized = normalize_monitor_frame(raw, ranges)
                self._mailbox.publish(normalized, rate.push(normalized.timestamp_ns))
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            if session is not None:
                try:
                    session.close()
                except Exception as exc:
                    self.failed.emit(f"falha ao fechar a sessão: {exc}")
            self.finished.emit()
