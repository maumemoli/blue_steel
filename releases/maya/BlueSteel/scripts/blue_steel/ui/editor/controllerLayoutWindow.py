from __future__ import annotations

from typing import Callable, Dict, List, Optional, Sequence, Set
import json

from maya import cmds

from ... import env

if env.MAYA_VERSION > 2024:
    from PySide6.QtCore import QMimeData, QPoint, QRect, Qt, QTimer, Signal
    from PySide6.QtGui import QColor, QDrag, QFontMetrics, QPainter
    from PySide6.QtWidgets import (
        QCheckBox,
        QFileDialog,
        QFormLayout,
        QFrame,
        QGridLayout,
        QGroupBox,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QMenu,
        QPushButton,
        QComboBox,
        QVBoxLayout,
        QWidget,
    )
else:
    from PySide2.QtCore import QMimeData, QPoint, QRect, Qt, QTimer, Signal
    from PySide2.QtGui import QColor, QDrag, QFontMetrics, QPainter
    from PySide2.QtWidgets import (
        QCheckBox,
        QFileDialog,
        QFormLayout,
        QFrame,
        QGridLayout,
        QGroupBox,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QMenu,
        QPushButton,
        QComboBox,
        QVBoxLayout,
        QWidget,
    )


LAYOUT_ATTR_NAME = "controllerLayoutJson"
PALETTE_MIME_TYPE = "application/x-blue-steel-controller-type"


class DraggablePaletteButton(QPushButton):
    def __init__(self, label: str, controller_type: str, parent=None) -> None:
        super().__init__(label, parent)
        self._controller_type = controller_type
        self.setCursor(Qt.OpenHandCursor)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if not (event.buttons() & Qt.LeftButton):
            return super().mouseMoveEvent(event)
        mime = QMimeData()
        mime.setData(PALETTE_MIME_TYPE, self._controller_type.encode("utf-8"))
        drag = QDrag(self)
        drag.setMimeData(mime)
        if hasattr(drag, "exec"):
            drag.exec(Qt.CopyAction)
        else:
            drag.exec_(Qt.CopyAction)


class AttributePopupButton(QPushButton):
    currentTextChanged = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._items: List[str] = []
        self._current_text = ""
        self.setText("(None)")
        self.clicked.connect(self._show_popup)

    def set_options(self, items: Sequence[str]) -> None:
        self._items = [str(item) for item in items]
        if self._current_text and self._current_text not in self._items:
            self._current_text = ""
        self._refresh_button_text()

    def currentText(self) -> str:  # noqa: N802
        return self._current_text

    def setCurrentText(self, text: str) -> None:  # noqa: N802
        normalized = str(text or "")
        changed = normalized != self._current_text
        self._current_text = normalized
        self._refresh_button_text()
        if changed and not self.signalsBlocked():
            self.currentTextChanged.emit(self._current_text)

    def _refresh_button_text(self) -> None:
        self.setText(self._current_text or "(None)")

    def _show_popup(self) -> None:
        menu = QMenu(self)
        none_action = menu.addAction("(None)")
        if not self._current_text:
            none_action.setCheckable(True)
            none_action.setChecked(True)
        menu.addSeparator()
        for item in self._items:
            action = menu.addAction(item)
            action.setCheckable(True)
            action.setChecked(item == self._current_text)

        if hasattr(menu, "exec"):
            chosen = menu.exec(self.mapToGlobal(self.rect().bottomLeft()))
        else:
            chosen = menu.exec_(self.mapToGlobal(self.rect().bottomLeft()))
        if chosen is None:
            return
        if chosen == none_action:
            self.setCurrentText("")
            return
        self.setCurrentText(chosen.text())


class CanvasControllerWidget(QFrame):
    selected = Signal(object, bool)
    changed = Signal()

    _HANDLE_SIZE = 7

    def __init__(self, canvas: "ControllerCanvas", controller_type: str, parent=None) -> None:
        super().__init__(parent)
        self.canvas = canvas
        self.controller_type = controller_type
        self.controller_id = f"{controller_type}_{id(self)}"
        self._selected = False
        self._edit_mode = False
        self._drag_origin = QPoint()
        self._start_geometry = QRect()
        self._drag_mode: Optional[str] = None
        self._resize_handle: Optional[str] = None
        self._interaction_active = False
        self.label_text = ""
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.ClickFocus)

    def is_interacting(self) -> bool:
        return self._interaction_active

    def set_selected(self, state: bool) -> None:
        self._selected = bool(state)
        self.update()

    def set_edit_mode(self, state: bool) -> None:
        self._edit_mode = bool(state)
        self.update()

    def to_dict(self) -> Dict:
        geom = self.geometry()
        return {
            "id": self.controller_id,
            "type": self.controller_type,
            "x": geom.x(),
            "y": geom.y(),
            "w": geom.width(),
            "h": geom.height(),
            "label_text": self.label_text,
        }

    def load_dict(self, data: Dict) -> None:
        self.controller_id = str(data.get("id") or self.controller_id)
        self.label_text = str(data.get("label_text") or "")
        self.setGeometry(
            int(data.get("x", 0)),
            int(data.get("y", 0)),
            max(40, int(data.get("w", 100))),
            max(40, int(data.get("h", 70))),
        )

    def _corner_rect(self, corner: str) -> QRect:
        hs = self._HANDLE_SIZE
        if corner == "tl":
            return QRect(0, 0, hs, hs)
        if corner == "tr":
            return QRect(self.width() - hs, 0, hs, hs)
        if corner == "bl":
            return QRect(0, self.height() - hs, hs, hs)
        return QRect(self.width() - hs, self.height() - hs, hs, hs)

    def _resolve_handle(self, pos: QPoint) -> Optional[str]:
        for corner in ("tl", "tr", "bl", "br"):
            if self._corner_rect(corner).contains(pos):
                return corner
        return None

    def _clamp_to_canvas(self, rect: QRect) -> QRect:
        parent = self.parentWidget()
        if parent is None:
            return rect
        bounds = parent.rect()
        if rect.width() < 40:
            rect.setWidth(40)
        if rect.height() < 40:
            rect.setHeight(40)
        if rect.left() < 0:
            rect.moveLeft(0)
        if rect.top() < 0:
            rect.moveTop(0)
        if rect.right() > bounds.right():
            rect.moveRight(bounds.right())
        if rect.bottom() > bounds.bottom():
            rect.moveBottom(bounds.bottom())
        return rect

    def _paint_overlay(self, painter: QPainter) -> None:
        if not self._selected and not self._edit_mode:
            return
        painter.save()
        border_color = QColor(255, 166, 72) if self._selected else QColor(125, 125, 125)
        painter.setPen(border_color)
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(self.rect().adjusted(0, 0, -1, -1))
        show_handles = (
            self._selected
            and self._edit_mode
            and self.canvas.selected_controller() is self
            and len(self.canvas.selected_controllers()) == 1
        )
        if show_handles:
            painter.setBrush(QColor(255, 166, 72))
            painter.setPen(Qt.NoPen)
            for corner in ("tl", "tr", "bl", "br"):
                painter.drawRect(self._corner_rect(corner))
        painter.restore()

    def _label_text(self) -> str:
        if self.label_text:
            return self.label_text
        return self.controller_type.replace("_", " ").title()

    def _draw_fitted_text(self, painter: QPainter, rect: QRect, text: str, *, vertical: bool = False) -> None:
        if not text:
            return
        font = painter.font()
        base_size = font.pointSize()
        if base_size <= 0:
            base_size = 10

        max_w = max(8, rect.width())
        max_h = max(8, rect.height())
        if vertical:
            max_w, max_h = max_h, max_w

        chosen = font
        for size in range(base_size, 6, -1):
            test_font = painter.font()
            test_font.setPointSize(size)
            metrics = QFontMetrics(test_font)
            if metrics.horizontalAdvance(text) <= max_w and metrics.height() <= max_h:
                chosen = test_font
                break
            chosen = test_font

        painter.save()
        painter.setFont(chosen)
        metrics = QFontMetrics(chosen)
        elided = metrics.elidedText(text, Qt.ElideRight, max_w)

        if vertical:
            painter.translate(rect.center())
            painter.rotate(-90)
            draw_rect = QRect(-rect.height() // 2, -rect.width() // 2, rect.height(), rect.width())
            painter.drawText(draw_rect, Qt.AlignCenter, elided)
        else:
            painter.drawText(rect, Qt.AlignCenter, elided)
        painter.restore()

    def _paint_label(self, painter: QPainter, *, rect: Optional[QRect] = None, vertical: bool = False) -> None:
        painter.save()
        label_rect = rect if rect is not None else QRect(6, 4, max(10, self.width() - 12), 16)
        painter.setPen(QColor(212, 212, 212))
        self._draw_fitted_text(painter, label_rect, self._label_text(), vertical=vertical)
        painter.restore()

    def _interaction_press(self, _pos: QPoint) -> None:
        self._interaction_active = True

    def _interaction_move(self, _pos: QPoint) -> None:
        pass

    def _interaction_release(self, _pos: QPoint) -> None:
        self._interaction_active = False

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.LeftButton:
            return super().mousePressEvent(event)
        was_selected = self._selected
        additive = bool(event.modifiers() & (Qt.ControlModifier | Qt.ShiftModifier))

        if additive:
            # Ctrl/Shift+click toggles membership; never starts value drag.
            self.selected.emit(self, True)
            self.setFocus(Qt.MouseFocusReason)
            event.accept()
            return

        # Plain click.
        if not was_selected:
            # Selecting for the first time – no interaction yet.
            self.selected.emit(self, False)
            self.setFocus(Qt.MouseFocusReason)
            event.accept()
            return

        # Already selected – keep current selection set and start interaction.
        self.setFocus(Qt.MouseFocusReason)

        if self._edit_mode:
            self._drag_origin = event.globalPos()
            self._start_geometry = self.geometry()
            self._resize_handle = self._resolve_handle(event.pos())
            self._drag_mode = "resize" if self._resize_handle else "move"
            self._interaction_active = True
            # Store start geometries for all selected (multi-move in edit mode).
            self.canvas._store_edit_start_geometries(self)
            event.accept()
            return

        # Value interaction: start immediately, snapshot for multi-drag.
        self.canvas._store_interaction_snapshots()
        self._interaction_press(event.pos())
        self._interaction_move(event.pos())
        event.accept()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if self._edit_mode and event.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            if self.canvas.remove_selected_controllers():
                event.accept()
                return
        super().keyPressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._edit_mode and self._interaction_active and (event.buttons() & Qt.LeftButton):
            delta = event.globalPos() - self._drag_origin
            if self._drag_mode == "move":
                self.canvas._apply_edit_move_delta(self, delta)
            elif self._drag_mode == "resize":
                rect = QRect(self._start_geometry)
                if self._resize_handle in ("tr", "br"):
                    rect.setRight(self._start_geometry.right() + delta.x())
                if self._resize_handle in ("tl", "bl"):
                    rect.setLeft(self._start_geometry.left() + delta.x())
                if self._resize_handle in ("bl", "br"):
                    rect.setBottom(self._start_geometry.bottom() + delta.y())
                if self._resize_handle in ("tl", "tr"):
                    rect.setTop(self._start_geometry.top() + delta.y())
                rect = self._clamp_to_canvas(rect.normalized())
                rect = self.canvas.snap_rect(rect)
                self.setGeometry(rect)
            self.changed.emit()
            event.accept()
            return

        if not self._edit_mode and self._interaction_active and (event.buttons() & Qt.LeftButton):
            self._interaction_move(event.pos())
            self.canvas._propagate_interaction_delta(self)
            event.accept()
            return

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton and self._interaction_active:
            if self._edit_mode:
                self._interaction_active = False
                self._drag_mode = None
                self._resize_handle = None
                self.changed.emit()
                event.accept()
                return
            self._interaction_release(event.pos())
            self.changed.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)


class SliderControllerWidget(CanvasControllerWidget):
    def __init__(self, canvas: "ControllerCanvas", orientation: str, parent=None) -> None:
        super().__init__(canvas, f"{orientation}_slider", parent)
        self.orientation = orientation
        self.primary_attr = ""
        self.secondary_attr = ""
        self.two_way = False
        self.inverted = False
        self.value = 0.0

    def to_dict(self) -> Dict:
        data = super().to_dict()
        data.update(
            {
                "orientation": self.orientation,
                "primary_attr": self.primary_attr,
                "secondary_attr": self.secondary_attr,
                "two_way": self.two_way,
                "inverted": self.inverted,
                "value": self.value,
            }
        )
        return data

    def load_dict(self, data: Dict) -> None:
        super().load_dict(data)
        self.orientation = str(data.get("orientation") or self.orientation)
        self.primary_attr = str(data.get("primary_attr") or "")
        self.secondary_attr = str(data.get("secondary_attr") or "")
        self.two_way = bool(data.get("two_way"))
        self.inverted = bool(data.get("inverted"))
        self.set_value(float(data.get("value", 0.0)), emit=False)

    def set_value(self, value: float, *, emit: bool = True) -> None:
        if self.two_way:
            self.value = max(-1.0, min(1.0, float(value)))
        else:
            self.value = max(0.0, min(1.0, float(value)))
        self.update()
        if emit:
            self.changed.emit()

    def _label_text(self) -> str:
        primary = self.primary_attr or "Unbound"
        if self.two_way and self.secondary_attr:
            return f"{primary} / {self.secondary_attr}"
        return primary

    def _interaction_press(self, pos: QPoint) -> None:
        super()._interaction_press(pos)

    def _interaction_move(self, pos: QPoint) -> None:
        if self.orientation == "horizontal":
            knob_half = max(8, min(40, int(self.height() * 0.35))) // 2
            margin = knob_half + 2
            span = max(1, self.width() - margin * 2)
            t = (float(pos.x() - margin) / float(span))
        else:
            knob_half = max(8, min(40, int(self.width() * 0.35))) // 2
            margin = knob_half + 2
            span = max(1, self.height() - margin * 2)
            t = 1.0 - (float(pos.y() - margin) / float(span))
        t = max(0.0, min(1.0, t))
        if self.inverted:
            t = 1.0 - t
        if self.two_way:
            self.set_value((t * 2.0) - 1.0, emit=True)
        else:
            self.set_value(t, emit=True)

    def _interaction_release(self, pos: QPoint) -> None:
        super()._interaction_release(pos)

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)
        bg = QColor(40, 40, 40)
        track = QColor(68, 68, 68)
        active = QColor(95, 154, 230)
        painter.fillRect(self.rect(), bg)

        t = ((self.value + 1.0) * 0.5) if self.two_way else self.value
        t = max(0.0, min(1.0, t))
        if self.inverted:
            t = 1.0 - t

        if self.orientation == "horizontal":
            knob_diameter = max(8, min(40, int(self.height() * 0.35)))
            half = knob_diameter // 2
            margin = half + 2  # keep knob fully inside the widget
            track_h = max(4, knob_diameter // 3)
            track_rect = QRect(margin, self.height() // 2 - track_h // 2, max(8, self.width() - margin * 2), track_h)
            painter.fillRect(track_rect, track)
            if self.two_way:
                center = track_rect.center().x()
                x = track_rect.left() + int(t * track_rect.width())
                if x >= center:
                    painter.fillRect(QRect(center, track_rect.top(), x - center, track_rect.height()), active)
                else:
                    painter.fillRect(QRect(x, track_rect.top(), center - x, track_rect.height()), active)
                knob_x = x
            else:
                width = int(self.value * track_rect.width())
                if self.inverted:
                    start_x = track_rect.right() - width
                    painter.fillRect(QRect(start_x, track_rect.top(), width, track_rect.height()), active)
                    knob_x = track_rect.right() - width
                else:
                    painter.fillRect(QRect(track_rect.left(), track_rect.top(), width, track_rect.height()), active)
                    knob_x = track_rect.left() + width
            knob = QRect(knob_x - half, track_rect.center().y() - half, knob_diameter, knob_diameter)
            self._paint_label(painter, rect=QRect(6, 4, max(10, self.width() - 12), 16), vertical=False)
        else:
            knob_diameter = max(8, min(40, int(self.width() * 0.35)))
            half = knob_diameter // 2
            margin = half + 2  # keep knob fully inside the widget
            track_w = max(4, knob_diameter // 3)
            track_rect = QRect(self.width() // 2 - track_w // 2, margin, track_w, max(8, self.height() - margin * 2))
            painter.fillRect(track_rect, track)
            if self.two_way:
                center = track_rect.center().y()
                y = track_rect.bottom() - int(t * track_rect.height())
                if y <= center:
                    painter.fillRect(QRect(track_rect.left(), y, track_rect.width(), center - y), active)
                else:
                    painter.fillRect(QRect(track_rect.left(), center, track_rect.width(), y - center), active)
                knob_y = y
            else:
                height = int(self.value * track_rect.height())
                if self.inverted:
                    painter.fillRect(QRect(track_rect.left(), track_rect.top(), track_rect.width(), height), active)
                    knob_y = track_rect.top() + height
                else:
                    y = track_rect.bottom() - height
                    painter.fillRect(QRect(track_rect.left(), y, track_rect.width(), height), active)
                    knob_y = y
            knob = QRect(track_rect.center().x() - half, knob_y - half, knob_diameter, knob_diameter)
            self._paint_label(painter, rect=QRect(4, 6, 16, max(10, self.height() - 12)), vertical=True)

        painter.setPen(QColor(20, 20, 20))
        painter.setBrush(QColor(226, 226, 226))
        painter.drawEllipse(knob)
        self._paint_overlay(painter)


class QuadControllerWidget(CanvasControllerWidget):
    def __init__(self, canvas: "ControllerCanvas", parent=None) -> None:
        super().__init__(canvas, "quad_controller", parent)
        self.attr_up = ""
        self.attr_down = ""
        self.attr_left = ""
        self.attr_right = ""
        self.x = 0.0
        self.y = 0.0

    def to_dict(self) -> Dict:
        data = super().to_dict()
        data.update(
            {
                "x_value": self.x,
                "y_value": self.y,
                "attr_up": self.attr_up,
                "attr_down": self.attr_down,
                "attr_left": self.attr_left,
                "attr_right": self.attr_right,
            }
        )
        return data

    def load_dict(self, data: Dict) -> None:
        super().load_dict(data)
        self.attr_up = str(data.get("attr_up") or "")
        self.attr_down = str(data.get("attr_down") or "")
        self.attr_left = str(data.get("attr_left") or "")
        self.attr_right = str(data.get("attr_right") or "")
        self.set_xy(float(data.get("x_value", 0.0)), float(data.get("y_value", 0.0)), emit=False)

    def set_xy(self, x_value: float, y_value: float, *, emit: bool = True) -> None:
        self.x = max(-1.0, min(1.0, float(x_value)))
        self.y = max(-1.0, min(1.0, float(y_value)))
        self.update()
        if emit:
            self.changed.emit()

    def _label_text(self) -> str:
        return self.label_text or "Quad"

    def _interaction_press(self, pos: QPoint) -> None:
        super()._interaction_press(pos)

    def _interaction_move(self, pos: QPoint) -> None:
        margin = 10
        rect = self.rect().adjusted(margin, margin, -margin, -margin)
        x = ((float(pos.x() - rect.left()) / float(max(1, rect.width()))) * 2.0) - 1.0
        y = 1.0 - ((float(pos.y() - rect.top()) / float(max(1, rect.height()))) * 2.0)
        self.set_xy(x, y, emit=True)

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)
        painter.fillRect(self.rect(), QColor(40, 40, 40))

        margin = 10
        area = self.rect().adjusted(margin, margin, -margin, -margin)
        painter.setPen(QColor(125, 125, 125))
        painter.setBrush(QColor(60, 60, 60))
        painter.drawRect(area)

        dot_diameter = max(8, min(40, int(min(area.width(), area.height()) * 0.15)))
        dot_half = dot_diameter // 2

        # Inset the travel range so the dot circle stays inside the area
        travel = area.adjusted(dot_half, dot_half, -dot_half, -dot_half)
        cx = travel.left() + int((self.x + 1.0) * 0.5 * max(1, travel.width()))
        cy = travel.bottom() - int((self.y + 1.0) * 0.5 * max(1, travel.height()))

        painter.setPen(QColor(95, 95, 95))
        painter.drawLine(area.center().x(), area.top(), area.center().x(), area.bottom())
        painter.drawLine(area.left(), area.center().y(), area.right(), area.center().y())

        painter.setPen(QColor(20, 20, 20))
        painter.setBrush(QColor(95, 154, 230))
        painter.drawEllipse(QRect(cx - dot_half, cy - dot_half, dot_diameter, dot_diameter))

        n_text = self.attr_up or "N"
        s_text = self.attr_down or "S"
        w_text = self.attr_left or "W"
        e_text = self.attr_right or "E"
        self._paint_label(painter, rect=QRect(6, 4, max(10, self.width() - 12), 14), vertical=False)
        self._draw_fitted_text(painter, QRect(area.center().x() - 48, area.top() + 4, 96, 14), n_text)
        self._draw_fitted_text(painter, QRect(area.center().x() - 48, area.bottom() - 18, 96, 14), s_text)
        self._draw_fitted_text(painter, QRect(area.left() + 4, area.center().y() - 8, 56, 16), w_text)
        self._draw_fitted_text(painter, QRect(area.right() - 60, area.center().y() - 8, 56, 16), e_text)
        self._paint_overlay(painter)


class ControllerCanvas(QWidget):
    controllerSelected = Signal(object)
    controllerChanged = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._controllers: List[CanvasControllerWidget] = []
        self._selected: List[CanvasControllerWidget] = []
        self._last_changed_controller: Optional[CanvasControllerWidget] = None
        self._edit_mode = False
        self._snap_enabled = True
        self._grid_step = 20
        self.setMinimumSize(420, 320)
        self.setAcceptDrops(True)
        self.setFocusPolicy(Qt.StrongFocus)

    def set_snap_enabled(self, state: bool) -> None:
        self._snap_enabled = bool(state)

    def snap_rect(self, rect: QRect) -> QRect:
        if not self._snap_enabled:
            return rect
        step = max(1, int(self._grid_step))
        snapped = QRect(rect)
        snapped.setX(int(round(float(snapped.x()) / float(step)) * step))
        snapped.setY(int(round(float(snapped.y()) / float(step)) * step))
        snapped.setWidth(max(40, int(round(float(snapped.width()) / float(step)) * step)))
        snapped.setHeight(max(40, int(round(float(snapped.height()) / float(step)) * step)))
        return snapped

    def set_edit_mode(self, state: bool) -> None:
        self._edit_mode = bool(state)
        for controller in self._controllers:
            controller.set_edit_mode(self._edit_mode)
        self.update()

    def selected_controller(self) -> Optional[CanvasControllerWidget]:
        return self._selected[-1] if self._selected else None

    def selected_controllers(self) -> Sequence[CanvasControllerWidget]:
        return tuple(self._selected)

    def last_changed_controller(self) -> Optional[CanvasControllerWidget]:
        return self._last_changed_controller

    def controllers(self) -> Sequence[CanvasControllerWidget]:
        return tuple(self._controllers)

    def frame_all_controllers(self, padding: int = 20) -> None:
        """Ensure all controllers are visible by translating into view and sizing canvas."""
        if not self._controllers:
            self.setMinimumSize(420, 320)
            return

        padding = max(0, int(padding))
        bounds = QRect(self._controllers[0].geometry())
        for controller in self._controllers[1:]:
            bounds = bounds.united(controller.geometry())

        offset_x = 0
        offset_y = 0
        if bounds.left() < padding:
            offset_x = padding - bounds.left()
        if bounds.top() < padding:
            offset_y = padding - bounds.top()

        if offset_x or offset_y:
            for controller in self._controllers:
                shifted = QRect(controller.geometry())
                shifted.translate(offset_x, offset_y)
                controller.setGeometry(shifted)
            bounds.translate(offset_x, offset_y)

        required_width = max(420, bounds.right() + padding + 1)
        required_height = max(320, bounds.bottom() + padding + 1)
        self.setMinimumSize(required_width, required_height)
        self.resize(required_width, required_height)

    def clear_controllers(self) -> None:
        for controller in self._controllers:
            controller.deleteLater()
        self._controllers = []
        self._set_selected(None)
        self.controllerChanged.emit()

    def remove_selected_controllers(self) -> bool:
        if not self._edit_mode or not self._selected:
            return False
        selected_set = set(self._selected)
        remaining: List[CanvasControllerWidget] = []
        for controller in self._controllers:
            if controller in selected_set:
                controller.deleteLater()
            else:
                remaining.append(controller)
        self._controllers = remaining
        self._last_changed_controller = None
        self._set_selected(None)
        self.controllerChanged.emit()
        return True

    def _set_selected(self, controller: Optional[CanvasControllerWidget], *, additive: bool = False) -> None:
        if controller is None:
            self._selected = []
        elif additive:
            if controller in self._selected:
                self._selected = [item for item in self._selected if item is not controller]
            else:
                self._selected.append(controller)
        else:
            self._selected = [controller]

        for item in self._controllers:
            item.set_selected(item in self._selected)
        self.controllerSelected.emit(self.selected_controller())

    def _store_edit_start_geometries(self, initiator: CanvasControllerWidget) -> None:
        """Snapshot geometries of all selected controllers for multi-move in edit mode."""
        self._edit_start_geoms: Dict[CanvasControllerWidget, QRect] = {}
        for ctrl in self._selected:
            self._edit_start_geoms[ctrl] = QRect(ctrl.geometry())

    def _apply_edit_move_delta(self, initiator: CanvasControllerWidget, delta: QPoint) -> None:
        """Apply the same pixel delta to all selected controllers during edit-mode drag."""
        for ctrl, start_geom in self._edit_start_geoms.items():
            rect = QRect(start_geom)
            rect.moveTopLeft(start_geom.topLeft() + delta)
            rect = ctrl._clamp_to_canvas(rect)
            rect = self.snap_rect(rect)
            ctrl.setGeometry(rect)

    def _store_interaction_snapshots(self) -> None:
        """Snapshot current values of all selected controllers before value drag."""
        self._interaction_snapshots: Dict[CanvasControllerWidget, Dict] = {}
        for ctrl in self._selected:
            if isinstance(ctrl, SliderControllerWidget):
                self._interaction_snapshots[ctrl] = {"value": ctrl.value}
            elif isinstance(ctrl, QuadControllerWidget):
                self._interaction_snapshots[ctrl] = {"x": ctrl.x, "y": ctrl.y}

    def _propagate_interaction_delta(self, initiator: CanvasControllerWidget) -> None:
        """Apply value delta from the dragged controller to other selected controllers."""
        if initiator not in self._interaction_snapshots:
            return
        snap = self._interaction_snapshots[initiator]
        if isinstance(initiator, SliderControllerWidget):
            delta = initiator.value - snap["value"]
            for ctrl, ctrl_snap in self._interaction_snapshots.items():
                if ctrl is initiator or not isinstance(ctrl, SliderControllerWidget):
                    continue
                ctrl.set_value(ctrl_snap["value"] + delta, emit=True)
        elif isinstance(initiator, QuadControllerWidget):
            dx = initiator.x - snap["x"]
            dy = initiator.y - snap["y"]
            for ctrl, ctrl_snap in self._interaction_snapshots.items():
                if ctrl is initiator or not isinstance(ctrl, QuadControllerWidget):
                    continue
                ctrl.set_xy(ctrl_snap["x"] + dx, ctrl_snap["y"] + dy, emit=True)

    def _on_controller_selected(self, controller: CanvasControllerWidget, additive: bool) -> None:
        if additive:
            self._set_selected(controller, additive=True)
        else:
            self._set_selected(controller, additive=False)
        self.setFocus(Qt.MouseFocusReason)

    def _on_controller_changed(self) -> None:
        sender = self.sender()
        if isinstance(sender, CanvasControllerWidget):
            self._last_changed_controller = sender
        self.controllerChanged.emit()

    def add_controller(self, controller_type: str, pos: Optional[QPoint] = None) -> Optional[CanvasControllerWidget]:
        if controller_type == "horizontal_slider":
            controller = SliderControllerWidget(self, "horizontal", parent=self)
            controller.setGeometry(40, 40, 220, 70)
        elif controller_type == "vertical_slider":
            controller = SliderControllerWidget(self, "vertical", parent=self)
            controller.setGeometry(40, 40, 70, 220)
        elif controller_type == "quad_controller":
            controller = QuadControllerWidget(self, parent=self)
            controller.setGeometry(40, 40, 180, 180)
        else:
            return None

        if pos is not None:
            geom = controller.geometry()
            geom.moveCenter(pos)
            geom = controller._clamp_to_canvas(geom)
            geom = self.snap_rect(geom)
            controller.setGeometry(geom)

        controller.selected.connect(self._on_controller_selected)
        controller.changed.connect(self._on_controller_changed)
        controller.set_edit_mode(self._edit_mode)
        controller.show()
        self._controllers.append(controller)
        self._set_selected(controller)
        self.controllerChanged.emit()
        return controller

    def serialize(self) -> List[Dict]:
        return [controller.to_dict() for controller in self._controllers]

    def deserialize(self, items: Sequence[Dict]) -> None:
        self.clear_controllers()
        for item in items:
            ctrl_type = str(item.get("type") or "")
            if ctrl_type == "horizontal_slider":
                controller = self.add_controller("horizontal_slider")
            elif ctrl_type == "vertical_slider":
                controller = self.add_controller("vertical_slider")
            elif ctrl_type == "quad_controller":
                controller = self.add_controller("quad_controller")
            else:
                continue
            if controller is not None:
                controller.load_dict(item)
        self.controllerChanged.emit()

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasFormat(PALETTE_MIME_TYPE):
            event.acceptProposedAction()
            return
        event.ignore()

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasFormat(PALETTE_MIME_TYPE):
            event.acceptProposedAction()
            return
        event.ignore()

    def dropEvent(self, event) -> None:  # noqa: N802
        if not event.mimeData().hasFormat(PALETTE_MIME_TYPE):
            event.ignore()
            return
        payload = bytes(event.mimeData().data(PALETTE_MIME_TYPE)).decode("utf-8", errors="ignore")
        controller_type = payload.strip()
        if not controller_type:
            event.ignore()
            return
        self.add_controller(controller_type, event.pos())
        event.acceptProposedAction()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton and self.childAt(event.pos()) is None:
            self._set_selected(None)
        if event.button() == Qt.LeftButton:
            self.setFocus(Qt.MouseFocusReason)
        super().mousePressEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if self._edit_mode and event.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            if self.remove_selected_controllers():
                event.accept()
                return
        super().keyPressEvent(event)

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)
        painter.fillRect(self.rect(), QColor(32, 32, 32))

        step = 20
        grid = QColor(49, 49, 49)
        painter.setPen(grid)
        for x in range(0, self.width(), step):
            painter.drawLine(x, 0, x, self.height())
        for y in range(0, self.height(), step):
            painter.drawLine(0, y, self.width(), y)


class ControllerLayoutWindow(QWidget):
    def __init__(
        self,
        editor_getter: Callable[[], Optional[object]],
        status_callback: Optional[Callable[[str], None]] = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Controller Layout")
        self.setWindowFlag(Qt.Tool, True)
        self.setWindowFlag(Qt.Window, True)

        self._editor_getter = editor_getter
        self._status_callback = status_callback
        self._script_jobs: List[int] = []

        self._edit_mode = False
        self._cancel_edit_requested = False
        self._edit_snapshot: List[Dict] = []
        self._edit_session_active = False
        self._selected_controller: Optional[CanvasControllerWidget] = None

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(8, 8, 8, 8)
        root_layout.setSpacing(8)

        top_bar = QHBoxLayout()
        top_bar.addWidget(QLabel("Custom Controllers"))
        top_bar.addStretch(1)
        self.edit_button = QPushButton("Edit")
        self.edit_button.setCheckable(True)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setEnabled(False)
        self.snap_button = QPushButton("Snap")
        self.snap_button.setCheckable(True)
        self.snap_button.setChecked(True)
        top_bar.addWidget(self.edit_button)
        top_bar.addWidget(self.cancel_button)
        top_bar.addWidget(self.snap_button)
        root_layout.addLayout(top_bar)

        body = QHBoxLayout()
        body.setSpacing(8)
        root_layout.addLayout(body, 1)

        self.canvas = ControllerCanvas(self)
        body.addWidget(self.canvas, 1)

        self.sidebar = QWidget(self)
        self.sidebar.setFixedWidth(290)
        sidebar_layout = QVBoxLayout(self.sidebar)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(8)
        body.addWidget(self.sidebar)

        palette_group = QGroupBox("Controllers")
        palette_layout = QVBoxLayout(palette_group)
        palette_layout.addWidget(DraggablePaletteButton("Horizontal Slider", "horizontal_slider"))
        palette_layout.addWidget(DraggablePaletteButton("Vertical Slider", "vertical_slider"))
        palette_layout.addWidget(DraggablePaletteButton("Quad Controller", "quad_controller"))
        sidebar_layout.addWidget(palette_group)

        self.slider_group = QGroupBox("Slider Settings")
        slider_form = QFormLayout(self.slider_group)
        self.slider_label_edit = QLineEdit()
        self.slider_primary_combo = QComboBox()
        self.slider_two_way_check = QCheckBox("Two way")
        self.slider_invert_check = QCheckBox("Invert")
        self.slider_secondary_combo = QComboBox()
        slider_form.addRow("Label", self.slider_label_edit)
        slider_form.addRow("Primary", self.slider_primary_combo)
        slider_form.addRow("", self.slider_two_way_check)
        slider_form.addRow("", self.slider_invert_check)
        slider_form.addRow("Secondary", self.slider_secondary_combo)
        sidebar_layout.addWidget(self.slider_group)

        self.quad_group = QGroupBox("Quad Settings")
        quad_layout = QVBoxLayout(self.quad_group)
        quad_label_form = QFormLayout()
        self.quad_label_edit = QLineEdit()
        self.quad_up_combo = AttributePopupButton()
        self.quad_down_combo = AttributePopupButton()
        self.quad_left_combo = AttributePopupButton()
        self.quad_right_combo = AttributePopupButton()
        quad_label_form.addRow("Label", self.quad_label_edit)
        quad_layout.addLayout(quad_label_form)

        quad_cross_widget = QFrame(self.quad_group)
        quad_cross_widget.setFixedSize(250, 250)
        quad_cross_widget.setStyleSheet(
            "QFrame { background-color: #3a3a3a; border: 1px solid #707070; border-radius: 2px; }"
        )
        quad_cross = QGridLayout(quad_cross_widget)
        quad_cross.setContentsMargins(10, 10, 10, 10)
        quad_cross.setHorizontalSpacing(8)
        quad_cross.setVerticalSpacing(8)

        for popup in (self.quad_up_combo, self.quad_down_combo, self.quad_left_combo, self.quad_right_combo):
            popup.setMinimumWidth(100)
            popup.setMaximumWidth(120)

        quad_cross.addWidget(self.quad_up_combo, 0, 1, Qt.AlignCenter)
        quad_cross.addWidget(self.quad_left_combo, 1, 0, Qt.AlignCenter)
        quad_cross.addWidget(self.quad_right_combo, 1, 2, Qt.AlignCenter)
        quad_cross.addWidget(self.quad_down_combo, 2, 1, Qt.AlignCenter)

        quad_cross.setRowStretch(1, 1)
        quad_cross.setColumnStretch(1, 1)
        quad_layout.addWidget(quad_cross_widget, 0, Qt.AlignCenter)
        sidebar_layout.addWidget(self.quad_group)

        io_group = QGroupBox("Layout")
        io_layout = QVBoxLayout(io_group)
        self.save_file_button = QPushButton("Save JSON")
        self.load_file_button = QPushButton("Load JSON")
        io_layout.addWidget(self.save_file_button)
        io_layout.addWidget(self.load_file_button)
        sidebar_layout.addWidget(io_group)
        sidebar_layout.addStretch(1)

        self.edit_button.toggled.connect(self._on_edit_toggled)
        self.cancel_button.clicked.connect(self._on_cancel_edit)
        self.snap_button.toggled.connect(self.canvas.set_snap_enabled)
        self.canvas.controllerSelected.connect(self._on_controller_selected)
        self.canvas.controllerChanged.connect(self._on_canvas_changed)

        self.slider_label_edit.textChanged.connect(self._on_slider_ui_changed)
        self.slider_primary_combo.currentTextChanged.connect(self._on_slider_ui_changed)
        self.slider_secondary_combo.currentTextChanged.connect(self._on_slider_ui_changed)
        self.slider_two_way_check.toggled.connect(self._on_slider_ui_changed)
        self.slider_invert_check.toggled.connect(self._on_slider_ui_changed)
        self.quad_label_edit.textChanged.connect(self._on_quad_ui_changed)
        self.quad_up_combo.currentTextChanged.connect(self._on_quad_ui_changed)
        self.quad_down_combo.currentTextChanged.connect(self._on_quad_ui_changed)
        self.quad_left_combo.currentTextChanged.connect(self._on_quad_ui_changed)
        self.quad_right_combo.currentTextChanged.connect(self._on_quad_ui_changed)

        self.save_file_button.clicked.connect(self._save_layout_to_file)
        self.load_file_button.clicked.connect(self._load_layout_from_file)

        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(250)
        self._poll_timer.timeout.connect(self._refresh_controller_values_from_attrs)
        self._poll_timer.start()

        self._populate_attr_combos()
        self.sidebar.setVisible(False)
        self.cancel_button.setEnabled(False)
        self.canvas.set_edit_mode(False)

    def _set_status(self, text: str) -> None:
        if self._status_callback is not None:
            self._status_callback(text)

    def _current_editor(self):
        return self._editor_getter()

    def set_current_editor(self, _editor: Optional[object]) -> None:
        self._populate_attr_combos()
        self._load_layout_from_editor()
        self._rebuild_attr_script_jobs()
        self._refresh_controller_values_from_attrs()

    def _controller_attr_names(self) -> List[str]:
        editor = self._current_editor()
        if editor is None:
            return []
        ctrl = getattr(editor, "face_ctrl", None)
        if not ctrl or not cmds.objExists(ctrl):
            return []
        attrs = cmds.listAttr(ctrl, keyable=True, scalar=True) or []
        return sorted({str(attr) for attr in attrs})

    def _populate_combo_with_attrs(self, combo: QComboBox, attrs: Sequence[str]) -> None:
        current = combo.currentText()
        combo.blockSignals(True)
        if isinstance(combo, AttributePopupButton):
            combo.set_options(attrs)
            combo.setCurrentText(current if current in attrs else "")
        else:
            combo.clear()
            combo.addItem("")
            for attr in attrs:
                combo.addItem(attr)
            idx = combo.findText(current)
            combo.setCurrentIndex(0 if idx < 0 else idx)
        combo.blockSignals(False)

    def _populate_attr_combos(self) -> None:
        attrs = self._controller_attr_names()
        for combo in (
            self.slider_primary_combo,
            self.slider_secondary_combo,
            self.quad_up_combo,
            self.quad_down_combo,
            self.quad_left_combo,
            self.quad_right_combo,
        ):
            self._populate_combo_with_attrs(combo, attrs)

    def _on_edit_toggled(self, checked: bool) -> None:
        self._edit_mode = bool(checked)
        if self._edit_mode:
            self._edit_snapshot = json.loads(json.dumps(self.canvas.serialize()))
            self._edit_session_active = True
        self.sidebar.setVisible(self._edit_mode)
        self.cancel_button.setEnabled(self._edit_mode)
        self.canvas.set_edit_mode(self._edit_mode)
        if not self._edit_mode:
            if self._cancel_edit_requested:
                self._cancel_edit_requested = False
            elif self._edit_session_active:
                self._persist_layout_to_container()
                self._set_status("Controller layout saved on editor container.")
            self._edit_session_active = False
            self._rebuild_attr_script_jobs()

    def _on_controller_selected(self, controller: Optional[CanvasControllerWidget]) -> None:
        self._selected_controller = controller
        self._refresh_settings_panel_from_selected()

    def _refresh_settings_panel_from_selected(self) -> None:
        controller = self._selected_controller
        is_slider = isinstance(controller, SliderControllerWidget)
        is_quad = isinstance(controller, QuadControllerWidget)
        self.slider_group.setVisible(is_slider)
        self.quad_group.setVisible(is_quad)

        if is_slider:
            slider = controller
            self.slider_label_edit.blockSignals(True)
            self.slider_primary_combo.blockSignals(True)
            self.slider_secondary_combo.blockSignals(True)
            self.slider_two_way_check.blockSignals(True)
            self.slider_invert_check.blockSignals(True)
            self.slider_label_edit.setText(slider.label_text)
            self.slider_primary_combo.setCurrentText(slider.primary_attr)
            self.slider_secondary_combo.setCurrentText(slider.secondary_attr)
            self.slider_two_way_check.setChecked(slider.two_way)
            self.slider_invert_check.setChecked(slider.inverted)
            self.slider_secondary_combo.setEnabled(slider.two_way)
            self.slider_label_edit.blockSignals(False)
            self.slider_primary_combo.blockSignals(False)
            self.slider_secondary_combo.blockSignals(False)
            self.slider_two_way_check.blockSignals(False)
            self.slider_invert_check.blockSignals(False)

        if is_quad:
            quad = controller
            self.quad_label_edit.blockSignals(True)
            self.quad_label_edit.setText(quad.label_text)
            self.quad_label_edit.blockSignals(False)
            for combo, value in (
                (self.quad_up_combo, quad.attr_up),
                (self.quad_down_combo, quad.attr_down),
                (self.quad_left_combo, quad.attr_left),
                (self.quad_right_combo, quad.attr_right),
            ):
                combo.blockSignals(True)
                combo.setCurrentText(value)
                combo.blockSignals(False)

    def _on_slider_ui_changed(self, _value) -> None:
        controller = self._selected_controller
        if not isinstance(controller, SliderControllerWidget):
            return
        controller.label_text = self.slider_label_edit.text().strip()
        controller.primary_attr = self.slider_primary_combo.currentText().strip()
        controller.secondary_attr = self.slider_secondary_combo.currentText().strip()
        controller.two_way = self.slider_two_way_check.isChecked()
        controller.inverted = self.slider_invert_check.isChecked()
        if not controller.two_way:
            controller.secondary_attr = ""
        self.slider_secondary_combo.setEnabled(controller.two_way)
        controller.update()
        self._apply_controller_to_attrs(controller)
        self._rebuild_attr_script_jobs()

    def _on_quad_ui_changed(self, _value) -> None:
        controller = self._selected_controller
        if not isinstance(controller, QuadControllerWidget):
            return
        controller.label_text = self.quad_label_edit.text().strip()
        controller.attr_up = self.quad_up_combo.currentText().strip()
        controller.attr_down = self.quad_down_combo.currentText().strip()
        controller.attr_left = self.quad_left_combo.currentText().strip()
        controller.attr_right = self.quad_right_combo.currentText().strip()
        self._apply_controller_to_attrs(controller)
        self._rebuild_attr_script_jobs()

    def _plug_for_attr(self, attr_name: str) -> Optional[str]:
        editor = self._current_editor()
        if editor is None:
            return None
        ctrl = getattr(editor, "face_ctrl", None)
        if not ctrl or not attr_name:
            return None
        plug = f"{ctrl}.{attr_name}"
        if not cmds.objExists(plug):
            return None
        return plug

    def _set_attr_value(self, attr_name: str, value: float) -> None:
        plug = self._plug_for_attr(attr_name)
        if plug is None:
            return
        try:
            cmds.setAttr(plug, float(max(0.0, min(1.0, value))))
        except Exception:
            return

    def _get_attr_value(self, attr_name: str) -> Optional[float]:
        plug = self._plug_for_attr(attr_name)
        if plug is None:
            return None
        try:
            return float(cmds.getAttr(plug))
        except Exception:
            return None

    def _apply_controller_to_attrs(self, controller: CanvasControllerWidget) -> None:
        if isinstance(controller, SliderControllerWidget):
            if controller.two_way:
                self._set_attr_value(controller.primary_attr, max(0.0, controller.value))
                self._set_attr_value(controller.secondary_attr, max(0.0, -controller.value))
            else:
                self._set_attr_value(controller.primary_attr, controller.value)
            return

        if isinstance(controller, QuadControllerWidget):
            self._set_attr_value(controller.attr_right, max(0.0, controller.x))
            self._set_attr_value(controller.attr_left, max(0.0, -controller.x))
            self._set_attr_value(controller.attr_up, max(0.0, controller.y))
            self._set_attr_value(controller.attr_down, max(0.0, -controller.y))

    def _refresh_controller_values_from_attrs(self) -> None:
        for controller in self.canvas.controllers():
            if controller.is_interacting():
                continue
            if isinstance(controller, SliderControllerWidget):
                if controller.two_way:
                    p = self._get_attr_value(controller.primary_attr) or 0.0
                    s = self._get_attr_value(controller.secondary_attr) or 0.0
                    controller.set_value(p - s, emit=False)
                else:
                    p = self._get_attr_value(controller.primary_attr)
                    if p is not None:
                        controller.set_value(p, emit=False)
            elif isinstance(controller, QuadControllerWidget):
                right = self._get_attr_value(controller.attr_right) or 0.0
                left = self._get_attr_value(controller.attr_left) or 0.0
                up = self._get_attr_value(controller.attr_up) or 0.0
                down = self._get_attr_value(controller.attr_down) or 0.0
                controller.set_xy(right - left, up - down, emit=False)

    def _bound_attr_names(self) -> Set[str]:
        attrs: Set[str] = set()
        for controller in self.canvas.controllers():
            if isinstance(controller, SliderControllerWidget):
                if controller.primary_attr:
                    attrs.add(controller.primary_attr)
                if controller.two_way and controller.secondary_attr:
                    attrs.add(controller.secondary_attr)
            elif isinstance(controller, QuadControllerWidget):
                for attr in (
                    controller.attr_up,
                    controller.attr_down,
                    controller.attr_left,
                    controller.attr_right,
                ):
                    if attr:
                        attrs.add(attr)
        return attrs

    def _kill_script_jobs(self) -> None:
        for job in self._script_jobs:
            try:
                if cmds.scriptJob(exists=job):
                    cmds.scriptJob(kill=job, force=True)
            except Exception:
                pass
        self._script_jobs = []

    def _on_external_attr_changed(self) -> None:
        self._refresh_controller_values_from_attrs()

    def _rebuild_attr_script_jobs(self) -> None:
        self._kill_script_jobs()
        for attr_name in sorted(self._bound_attr_names()):
            plug = self._plug_for_attr(attr_name)
            if plug is None:
                continue
            try:
                job = cmds.scriptJob(attributeChange=[plug, self._on_external_attr_changed], protected=True)
                self._script_jobs.append(int(job))
            except Exception:
                continue

    def _serialized_layout(self) -> str:
        return json.dumps(self.canvas.serialize(), ensure_ascii=True, indent=2)

    def _persist_layout_to_container(self) -> None:
        editor = self._current_editor()
        if editor is None:
            return
        container_name = getattr(editor, "name", None)
        if not container_name or not cmds.objExists(container_name):
            return

        try:
            if not cmds.attributeQuery(LAYOUT_ATTR_NAME, node=container_name, exists=True):
                cmds.addAttr(container_name, longName=LAYOUT_ATTR_NAME, dataType="string")
            cmds.setAttr(f"{container_name}.{LAYOUT_ATTR_NAME}", self._serialized_layout(), type="string")
        except Exception as exc:
            self._set_status(f"Failed storing controller layout: {exc}")

    def _load_layout_from_editor(self) -> None:
        editor = self._current_editor()
        if editor is None:
            self.canvas.clear_controllers()
            self._rebuild_attr_script_jobs()
            return

        container_name = getattr(editor, "name", None)
        if not container_name or not cmds.objExists(container_name):
            return
        if not cmds.attributeQuery(LAYOUT_ATTR_NAME, node=container_name, exists=True):
            return

        try:
            payload = cmds.getAttr(f"{container_name}.{LAYOUT_ATTR_NAME}") or ""
            payload = str(payload).strip()
            if not payload:
                return
            data = json.loads(payload)
            if isinstance(data, list):
                self.canvas.deserialize(data)
                self._refresh_controller_values_from_attrs()
                self._rebuild_attr_script_jobs()
                self._set_status("Loaded controller layout from editor container.")
        except Exception as exc:
            self._set_status(f"Failed loading controller layout from editor: {exc}")

    def _save_layout_to_file(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Save Controller Layout", "", "JSON Files (*.json)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(self._serialized_layout())
            self._set_status(f"Saved controller layout to '{path}'.")
        except Exception as exc:
            self._set_status(f"Failed saving controller layout: {exc}")

    def _load_layout_from_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Load Controller Layout", "", "JSON Files (*.json)")
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            if not isinstance(data, list):
                raise ValueError("JSON root must be a list.")
            self.canvas.deserialize(data)
            self._refresh_controller_values_from_attrs()
            self._rebuild_attr_script_jobs()
            self._set_status(f"Loaded controller layout from '{path}'. Toggle Edit off to store it.")
        except Exception as exc:
            self._set_status(f"Failed loading controller layout: {exc}")

    def _on_cancel_edit(self) -> None:
        if not self._edit_mode:
            return
        self.canvas.deserialize(self._edit_snapshot)
        self._refresh_settings_panel_from_selected()
        self._refresh_controller_values_from_attrs()
        self._rebuild_attr_script_jobs()
        self._cancel_edit_requested = True
        self.edit_button.setChecked(False)
        self._set_status("Edit cancelled. Restored previous controller layout.")

    def _on_canvas_changed(self) -> None:
        controller = self.canvas.last_changed_controller() or self.canvas.selected_controller()
        if controller is not None and not self._edit_mode:
            selected = self.canvas.selected_controllers()
            if isinstance(controller, SliderControllerWidget):
                for target in selected:
                    if isinstance(target, SliderControllerWidget) and target is not controller:
                        target.set_value(controller.value, emit=False)
                for target in selected:
                    if isinstance(target, SliderControllerWidget):
                        self._apply_controller_to_attrs(target)
            elif isinstance(controller, QuadControllerWidget):
                for target in selected:
                    if isinstance(target, QuadControllerWidget) and target is not controller:
                        target.set_xy(controller.x, controller.y, emit=False)
                for target in selected:
                    if isinstance(target, QuadControllerWidget):
                        self._apply_controller_to_attrs(target)
            else:
                self._apply_controller_to_attrs(controller)
        self._refresh_settings_panel_from_selected()

    def _frame_all_controllers_on_open(self) -> None:
        self.canvas.frame_all_controllers(padding=20)
        self.adjustSize()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._populate_attr_combos()
        self._load_layout_from_editor()
        self._rebuild_attr_script_jobs()
        self._refresh_controller_values_from_attrs()
        QTimer.singleShot(0, self._frame_all_controllers_on_open)

    def closeEvent(self, event) -> None:  # noqa: N802
        self._kill_script_jobs()
        if self._poll_timer.isActive():
            self._poll_timer.stop()
        super().closeEvent(event)
