"""Qt application composition root."""

from __future__ import annotations

import logging
import sys

from PySide6.QtWidgets import QApplication

from .main_window import MainWindow

LOGGER = logging.getLogger("zonepad.gui")


def run_app(*, smoke: bool = False) -> int:
    """Compose the window and run the GUI event loop or the offscreen smoke."""
    try:
        app = QApplication.instance() or QApplication(sys.argv[:1])
    except RuntimeError as exc:
        LOGGER.exception("Qt platform initialization failed")
        sys.stderr.write(
            "Falha ao iniciar a plataforma gráfica Qt. Verifique a configuração "
            "de display e os plugins Qt disponíveis.\n"
        )
        LOGGER.debug("Qt startup detail: %s", exc)
        return 2
    app.setApplicationName("ZonaPad")
    window = MainWindow(enable_hotplug=not smoke)
    if smoke:
        window.show()
        app.processEvents()
        window.close()
        app.processEvents()
        return 0
    window.show()
    return app.exec()
