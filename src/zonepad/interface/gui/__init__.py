from __future__ import annotations


def run() -> int:
    """Start the optional Qt GUI, or return a useful message when unavailable."""
    try:
        from PySide6.QtWidgets import QApplication, QLabel, QWidget
    except ImportError:
        raise RuntimeError("GUI opcional: instale o extra 'gui' (PySide6)") from None
    app = QApplication.instance() or QApplication([])
    window = QWidget()
    window.setWindowTitle("ZonaPad")
    window.setLayout(__import__("PySide6.QtWidgets", fromlist=["QVBoxLayout"]).QVBoxLayout())
    window.layout().addWidget(QLabel("ZonaPad — captura e calibração"))
    window.show()
    return app.exec()
