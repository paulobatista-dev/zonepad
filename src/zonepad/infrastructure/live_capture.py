from __future__ import annotations

import threading
from collections.abc import Callable

from zonepad.application.calibrate import SegmentPlan
from zonepad.application.ports import CaptureArtifacts, Clock, DeviceSession
from zonepad.domain.errors import DeviceDisconnectedError, MeasurementInputError
from zonepad.domain.protocol import Segment

from .capture_writer import CaptureWriter


class LiveCaptureSession:
    """Read frames continuously while the terminal prompts and records timed windows."""

    def __init__(self, session: DeviceSession, writer: CaptureWriter, clock: Clock) -> None:
        self._session = session
        self._writer = writer
        self._clock = clock
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._failure: BaseException | None = None
        self._closed = False
        self._session_closed = False

    @property
    def device_info(self):
        return self._session.device_info

    def start(self) -> None:
        if self._closed:
            raise RuntimeError("capture session is closed")
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._read_frames, name="zonepad-capture", daemon=True
        )
        self._thread.start()

    def pause(self) -> None:
        self._stop_reader(close_session=False)
        self._raise_failure()

    def resume(self) -> None:
        if self._failure is not None:
            self._raise_failure()
        self.start()

    def _read_frames(self) -> None:
        try:
            while not self._stop.is_set():
                frame = self._session.read(0.05)
                if frame is not None:
                    with self._lock:
                        self._writer.append(frame)
        except BaseException as exc:
            self._failure = exc
            self._stop.set()

    def _raise_failure(self) -> None:
        if isinstance(self._failure, DeviceDisconnectedError):
            raise self._failure
        if isinstance(self._failure, MeasurementInputError):
            raise self._failure
        if self._failure is not None:
            raise RuntimeError(
                f"falha durante leitura do dispositivo: {self._failure}"
            ) from self._failure

    def wait(self, seconds: float, progress: Callable[[float], None] | None = None) -> None:
        start = self._clock.now_ns()
        deadline = start + int(seconds * 1_000_000_000)
        while True:
            self._raise_failure()
            remaining = (deadline - self._clock.now_ns()) / 1_000_000_000
            if remaining <= 0:
                return
            if progress is not None:
                progress(remaining)
            self._clock.sleep(min(1.0, remaining))

    def record_segment(
        self,
        spec: SegmentPlan,
        duration_seconds: float,
        progress: Callable[[float], None],
    ) -> Segment | None:
        start = self._clock.now_ns()
        self.wait(duration_seconds, progress)
        end = self._clock.now_ns()
        segment = Segment(
            spec.kind,
            0,
            spec.warmup_ns + 2 if spec.kind == "rest" else 2,
            spec.warmup_ns,
            spec.stick,
            spec.direction,
            spec.trigger,
        )
        with self._lock:
            self._raise_failure()
            valid = self._writer.replace_segment(spec.target, segment, start, end)
        return segment if valid else None

    def flush(self) -> CaptureArtifacts:
        with self._lock:
            return self._writer.flush()

    def finish(self) -> CaptureArtifacts:
        self.pause()
        with self._lock:
            return self._writer.finish()

    def abort(self) -> CaptureArtifacts:
        stop_error: BaseException | None = None
        try:
            self._stop_reader(close_session=True)
        except BaseException as exc:
            stop_error = exc
        with self._lock:
            artifacts = self._writer.abort()
        if stop_error is not None:
            raise stop_error
        return artifacts

    def close(self) -> None:
        if self._closed:
            return
        self._stop_reader(close_session=True)
        self._closed = True

    def _stop_reader(self, *, close_session: bool) -> None:
        self._stop.set()
        close_error: BaseException | None = None
        if close_session:
            try:
                self._close_session()
            except BaseException as exc:
                close_error = exc
        thread = self._thread
        if thread is not None:
            thread.join()
            if thread.is_alive():
                raise RuntimeError("capture reader thread did not stop")
            self._thread = None
        if close_error is not None:
            raise close_error

    def _close_session(self) -> None:
        if not self._session_closed:
            self._session.close()
            self._session_closed = True
