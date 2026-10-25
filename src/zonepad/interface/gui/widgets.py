"""Small accessible QPainter widgets for normalized controller values."""

from __future__ import annotations

from collections.abc import Mapping

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget


class StickWidget(QWidget):
    def __init__(
        self,
        title: str,
        x_axis: str,
        y_axis: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._title = title
        self._x_axis = x_axis
        self._y_axis = y_axis
        self._x: float | None = None
        self._y: float | None = None
        self.setMinimumSize(190, 220)
        self.setAccessibleName(f"{title}, stick normalizado")
        self.setAccessibleDescription(self._description())

    @property
    def readout_text(self) -> str:
        return (
            f"{self._x_axis} {self._format_value(self._x)} · "
            f"{self._y_axis} {self._format_value(self._y)}"
        )

    @property
    def axes_range_text(self) -> str:
        return f"{self._x_axis} [-1, 1] · {self._y_axis} [-1, 1]"

    @staticmethod
    def _format_value(value: float | None) -> str:
        return "aguardando" if value is None else f"{value:+.3f}"

    def _description(self) -> str:
        return f"{self.axes_range_text}; Y positivo aponta para cima. {self.readout_text}."

    def set_value(self, x: float | None, y: float | None) -> None:
        self._x, self._y = x, y
        value_text = f"{self._title}: {self.readout_text}"
        self.setToolTip(value_text)
        self.setAccessibleDescription(self._description())
        self.update()

    def paintEvent(self, event: object) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        bounds = QRectF(self.rect()).adjusted(20, 34, -20, -62)
        side = min(bounds.width(), bounds.height())
        board = QRectF(bounds.center().x() - side / 2, bounds.center().y() - side / 2, side, side)
        painter.setPen(QPen(QColor("#65758b"), 1))
        painter.setBrush(QColor("#f3f6fa"))
        painter.drawEllipse(board)
        painter.drawLine(
            QPointF(board.center().x(), board.top()), QPointF(board.center().x(), board.bottom())
        )
        painter.drawLine(
            QPointF(board.left(), board.center().y()), QPointF(board.right(), board.center().y())
        )
        radius = side * 0.43
        if self._x is not None and self._y is not None:
            marker = QPointF(
                board.center().x() + self._x * radius,
                board.center().y() - self._y * radius,
            )
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#1769aa"))
            painter.drawEllipse(marker, 7, 7)
        painter.setPen(QPen(QColor("#17212f"), 1))
        painter.drawText(QRectF(0, 2, self.width(), 20), Qt.AlignmentFlag.AlignCenter, self._title)
        painter.drawText(
            QRectF(board.left(), board.top() - 22, board.width(), 18),
            Qt.AlignmentFlag.AlignCenter,
            f"{self._y_axis} +1",
        )
        painter.drawText(
            QRectF(board.left(), board.bottom() + 3, board.width(), 18),
            Qt.AlignmentFlag.AlignCenter,
            f"{self._y_axis} -1",
        )
        painter.drawText(
            QRectF(board.left() - 12, board.center().y() - 9, 24, 18),
            Qt.AlignmentFlag.AlignLeft,
            "-1",
        )
        painter.drawText(
            QRectF(board.right() - 12, board.center().y() - 9, 24, 18),
            Qt.AlignmentFlag.AlignRight,
            "+1",
        )
        painter.drawText(
            QRectF(0, self.height() - 39, self.width(), 18),
            Qt.AlignmentFlag.AlignCenter,
            self.axes_range_text,
        )
        painter.drawText(
            QRectF(0, self.height() - 22, self.width(), 18),
            Qt.AlignmentFlag.AlignCenter,
            self.readout_text,
        )


class TriggerBarWidget(QWidget):
    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._title = title
        self._value: float | None = None
        self._rest_reference: float | None = None
        self._provisional = False
        self.setMinimumHeight(68)
        self.setAccessibleName(f"{title}, gatilho normalizado")
        self.setAccessibleDescription(self.readout_text)

    @property
    def readout_text(self) -> str:
        value = "aguardando" if self._value is None else f"{self._value:.3f}"
        rest = "aguardando" if self._rest_reference is None else f"{self._rest_reference:.3f}"
        provisional = " · mapping provisório" if self._provisional else ""
        return f"{self._title}: {value} · repouso mapping {rest}{provisional}"

    def set_reference(self, rest_reference: float, *, provisional: bool) -> None:
        if not 0.0 <= rest_reference <= 1.0:
            raise ValueError("normalized trigger rest reference must be in [0, 1]")
        self._rest_reference = rest_reference
        self._provisional = provisional
        self.setAccessibleDescription(self.readout_text)
        self.setToolTip(self.readout_text)
        self.update()

    def set_value(self, value: float | None) -> None:
        self._value = value
        value_text = self.readout_text
        self.setToolTip(value_text)
        self.setAccessibleDescription(value_text)
        self.update()

    def paintEvent(self, event: object) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor("#65758b"), 1))
        painter.setBrush(QColor("#edf1f6"))
        bar = QRectF(90, 19, max(20, self.width() - 112), 18)
        painter.drawRoundedRect(bar, 4, 4)
        if self._value is not None:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#16806a"))
            painter.drawRoundedRect(
                QRectF(bar.left(), bar.top(), bar.width() * self._value, bar.height()), 4, 4
            )
        if self._rest_reference is not None:
            marker_x = bar.left() + bar.width() * self._rest_reference
            painter.setPen(QPen(QColor("#a44500"), 2))
            painter.drawLine(QPointF(marker_x, bar.top() - 3), QPointF(marker_x, bar.bottom() + 3))
        painter.setPen(QPen(QColor("#17212f"), 1))
        painter.drawText(QRectF(0, 16, 86, 24), Qt.AlignmentFlag.AlignLeft, self._title)
        painter.drawText(QRectF(bar.left(), 39, bar.width(), 17), Qt.AlignmentFlag.AlignLeft, "0")
        painter.drawText(QRectF(bar.right() - 24, 39, 24, 17), Qt.AlignmentFlag.AlignRight, "1")
        painter.drawText(
            QRectF(bar.right() + 6, 16, 106, 24),
            Qt.AlignmentFlag.AlignLeft,
            "aguardando" if self._value is None else f"{self._value:.3f}",
        )
        rest_text = (
            "repouso mapping: aguardando"
            if self._rest_reference is None
            else f"repouso mapping: {self._rest_reference:.3f}"
        )
        painter.drawText(QRectF(0, 50, self.width(), 17), Qt.AlignmentFlag.AlignCenter, rest_text)


class ButtonIndicators(QWidget):
    ORDER = ("button_south", "button_east", "button_north", "button_west")
    LABELS = {
        "button_south": "Sul",
        "button_east": "Leste",
        "button_north": "Norte",
        "button_west": "Oeste",
    }

    def __init__(self, mapped: tuple[str, ...], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._mapped = tuple(name for name in self.ORDER if name in mapped)
        self._pressed: frozenset[str] = frozenset()
        self.setMinimumHeight(70)
        self.setAccessibleName("Botões mapeados")

    def set_pressed(self, pressed: frozenset[str]) -> None:
        self._pressed = pressed
        if self._mapped:
            states = ", ".join(
                f"{self.LABELS[name]} {'pressionado' if name in pressed else 'solto'}"
                for name in self._mapped
            )
            self.setAccessibleDescription(states)
            self.setToolTip(states)
        else:
            self.setAccessibleDescription("Nenhum botão mapeado")
            self.setToolTip("Nenhum botão mapeado")
        self.update()

    def set_mapped(self, mapped: tuple[str, ...]) -> None:
        self._mapped = tuple(name for name in self.ORDER if name in mapped)
        self.set_pressed(self._pressed)

    def paintEvent(self, event: object) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self._mapped:
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Nenhum botão mapeado")
            return
        width = self.width() / len(self._mapped)
        for index, name in enumerate(self._mapped):
            area = QRectF(index * width + 3, 12, width - 6, 42)
            painter.setPen(QPen(QColor("#1769aa"), 1))
            painter.setBrush(QColor("#cdebdc") if name in self._pressed else QColor("#f3f6fa"))
            painter.drawRoundedRect(area, 6, 6)
            painter.setPen(QPen(QColor("#17212f"), 1))
            text = self.LABELS[name] + (" · pressionado" if name in self._pressed else " · solto")
            painter.drawText(area, Qt.AlignmentFlag.AlignCenter, text)


def mapped_button_names(button_codes: Mapping[int, str]) -> tuple[str, ...]:
    return tuple(name for name in ButtonIndicators.ORDER if name in button_codes.values())
