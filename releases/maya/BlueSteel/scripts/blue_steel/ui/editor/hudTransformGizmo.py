"""Interactive "free transform" gizmo for the Blue Steel shapes HUD.

The gizmo is a temporary, translucent Qt window laid over the active Maya
viewport. It never draws the HUD itself (the HUD is drawn by Viewport 2.0
through the ``bsShapesHUD`` plugin, so it shows up in playblasts); it only
edits the frame position/dimensions and independent font size of the HUD node:

* drag inside the frame: move
* drag a corner handle: resize the area, anchored on the opposite corner
* mouse wheel: change font size without changing the frame
* arrow keys: nudge (Shift = x10)
* Enter / double-click: commit
* Esc: cancel (revert)
* right-click: Commit / Cancel / Reset
"""

from __future__ import annotations

import math
from typing import Optional, Tuple

from maya import cmds
import maya.api.OpenMayaUI as omui2

from ...api import hudManager
from . import qt
from .qt import QColor, QPainter, QPoint, QRect, Qt, QTimer, QWidget, Signal

HANDLE_SIZE = 10
MIN_SCALE = 0.05
MAX_SCALE = 20.0


def _active_model_panel() -> Optional[str]:
    """Return the focused model panel, or the first visible one."""
    panel = cmds.getPanel(withFocus=True)
    if panel and cmds.getPanel(typeOf=panel) == "modelPanel":
        return panel
    for panel in cmds.getPanel(visiblePanels=True) or []:
        if cmds.getPanel(typeOf=panel) == "modelPanel":
            return panel
    return None


def _viewport_widget(panel: str) -> Optional[QWidget]:
    """Return the viewport QWidget of a model panel."""
    try:
        import maya.api.OpenMayaUI as omui2
        view = omui2.M3dView.getM3dViewFromModelPanel(panel)
        ptr = view.widget()
        if ptr:
            return qt.wrapInstance(int(ptr), QWidget)
    except Exception:
        pass
    import maya.OpenMayaUI as omui
    editor = cmds.modelPanel(panel, query=True, modelEditor=True)
    ptr = omui.MQtUtil.findControl(editor)
    return qt.wrapInstance(int(ptr), QWidget) if ptr else None


class HudTransformGizmo(QWidget):
    """Translucent overlay for moving/resizing the HUD area and adjusting its font.

    Signals:
        finished(bool): Emitted when the session ends, True if committed.
    """

    finished = Signal(bool)

    def __init__(self, panel: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent or qt.get_maya_main_window())
        # Stay above Maya's native viewport window while the session is active;
        # the overlay hides itself when Maya is not the active application.
        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint
                            | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)

        self._panel = panel
        self._viewport = _viewport_widget(panel)
        self._initial = hudManager.get_transform() or hudManager.load_settings()
        self._initial_frame_size = hudManager.get_frame_size() or hudManager.load_frame_size()
        self._drag_mode: Optional[str] = None
        self._drag_corner: Optional[int] = None
        self._press_pos = QPoint()
        self._press_transform: Tuple[float, float, float] = self._initial
        self._press_rect: Tuple[float, float, float, float] = (0.0, 0.0, 1.0, 1.0)
        self._done = False
        self._missing_ticks = 0
        self._menu = None

        # Keep the overlay glued to the viewport (moves, resizes, panel layout changes).
        self._follow_timer = QTimer(self)
        self._follow_timer.setInterval(200)
        self._follow_timer.timeout.connect(self._sync_geometry)
        self._follow_timer.start()

        app = qt.QApplication.instance()
        if app is not None:
            app.applicationStateChanged.connect(self._on_application_state_changed)

        hudManager.set_show_frame(True)
        self._sync_geometry()

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------
    @classmethod
    def start(cls, parent: Optional[QWidget] = None) -> Optional["HudTransformGizmo"]:
        """Create and show a gizmo over the active model panel.

        Returns:
            HudTransformGizmo | None: The gizmo, or None if no viewport/HUD.
        """
        if not hudManager.plugin_hud_exists():
            return None
        panel = _active_model_panel()
        if panel is None or _viewport_widget(panel) is None:
            return None
        gizmo = cls(panel, parent)
        if gizmo._done:
            return None
        gizmo.show()
        gizmo.raise_()
        gizmo.activateWindow()
        gizmo.setFocus()
        return gizmo

    # ------------------------------------------------------------------
    # Geometry helpers
    # ------------------------------------------------------------------
    # Number of consecutive 200 ms ticks tolerated without viewport / HUD.
    MAX_MISSING_TICKS = 5

    def _sync_geometry(self) -> None:
        if self._done:
            return
        if not qt.is_valid_qt_object(self._viewport):
            # The wrapper can go stale (panel rebuilt): look the widget up again.
            self._viewport = _viewport_widget(self._panel) if cmds.panel(
                self._panel, exists=True) else None
        if self._viewport is None or not hudManager.plugin_hud_exists():
            self._missing_ticks += 1
            if self._missing_ticks >= self.MAX_MISSING_TICKS:
                reason = "viewport closed" if self._viewport is None else "HUD node removed"
                self.cancel(reason=reason)
            return
        self._missing_ticks = 0
        try:
            top_left = self._viewport.mapToGlobal(QPoint(0, 0))
            rect = QRect(top_left, self._viewport.size())
        except RuntimeError:
            self._viewport = None
            return
        if rect != self.geometry():
            self.setGeometry(rect)
        if self.isVisible():
            self.raise_()
        self.update()

    def _on_application_state_changed(self, state) -> None:
        if self._done:
            return
        if state == Qt.ApplicationActive:
            self.show()
            self.raise_()
        else:
            # Do not float above other applications (WindowStaysOnTopHint).
            self.hide()

    def _physical_viewport_size(self) -> Tuple[float, float]:
        """VP2 dimensions can differ from Qt logical dimensions on high-DPI screens."""
        try:
            view = omui2.M3dView.getM3dViewFromModelPanel(self._panel)
            return float(max(1, view.portWidth())), float(max(1, view.portHeight()))
        except RuntimeError:
            ratio = self.devicePixelRatioF()
            return max(1, self.width()) * ratio, max(1, self.height()) * ratio

    def _hud_rect(self) -> Tuple[float, float, float, float]:
        vp_w, vp_h = self._physical_viewport_size()
        rect = hudManager.query_rect(vp_w, vp_h)
        if rect is None:
            return (0.0, 0.0, 1.0, 1.0)
        sx, sy = max(1, self.width()) / vp_w, max(1, self.height()) / vp_h
        return rect[0] * sx, rect[1] * sy, rect[2] * sx, rect[3] * sy

    def _minimum_frame_size(self, scale: float) -> Tuple[float, float]:
        """Minimum logical size, large enough for the overflow cue at this font."""
        vp_w, vp_h = self._physical_viewport_size()
        font = max(6, min(200, round((13.0 / 720.0) * scale * vp_h)))
        return (min(self.width(), max(64.0, 4.0 * font) * self.width() / vp_w),
                min(self.height(), max(48.0, 3.0 * font) * self.height() / vp_h))

    def _corners(self, rect) -> list:
        x, y, w, h = rect
        return [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]

    def _hit_corner(self, pos: QPoint, rect) -> Optional[int]:
        for index, (cx, cy) in enumerate(self._corners(rect)):
            if abs(pos.x() - cx) <= HANDLE_SIZE and abs(pos.y() - cy) <= HANDLE_SIZE:
                return index
        return None

    @staticmethod
    def _inside(pos: QPoint, rect) -> bool:
        x, y, w, h = rect
        return x <= pos.x() <= x + w and y <= pos.y() <= y + h

    def _apply(self, offset_x: float, offset_y: float, scale: float) -> None:
        frame_w, frame_h = hudManager.get_frame_size() or hudManager.load_frame_size()
        offset_x = min(max(0.0, offset_x), max(0.0, 1.0 - frame_w))
        offset_y = min(max(0.0, offset_y), max(0.0, 1.0 - frame_h))
        hudManager.set_transform(offset_x, offset_y, scale, save=False)
        self.update()

    # ------------------------------------------------------------------
    # Session end
    # ------------------------------------------------------------------
    def commit(self, reason: str = "committed") -> None:
        """Keep the current placement and close."""
        if self._done:
            return
        current = hudManager.get_transform()
        if current is not None:
            hudManager.save_settings(*current)
        frame_size = hudManager.get_frame_size()
        if frame_size is not None:
            hudManager.save_frame_size(*frame_size)
        self._finish(True, reason)

    def cancel(self, reason: str = "cancelled") -> None:
        """Revert to the placement at session start and close."""
        if self._done:
            return
        if hudManager.plugin_hud_exists():
            hudManager.set_transform(*self._initial, save=False, refresh=False)
            hudManager.set_frame_size(*self._initial_frame_size, save=False)
        self._finish(False, reason)

    def reset(self) -> None:
        """Reset to the default placement (session stays open)."""
        hudManager.reset_transform(save=False)
        self.update()

    def _finish(self, committed: bool, reason: str) -> None:
        self._done = True
        self._follow_timer.stop()
        app = qt.QApplication.instance()
        if app is not None:
            try:
                app.applicationStateChanged.disconnect(self._on_application_state_changed)
            except (RuntimeError, TypeError):
                pass
        print(f"Blue Steel HUD transform ended: {reason}")
        hudManager.set_show_frame(False)
        if hudManager.plugin_hud_exists():
            hudManager.update_conflicts()
        self.finished.emit(committed)
        self.close()

    # ------------------------------------------------------------------
    # Qt events
    # ------------------------------------------------------------------
    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        # Near-transparent fill so the window receives mouse events everywhere.
        painter.fillRect(self.rect(), QColor(0, 0, 0, 1))
        x, y, w, h = self._hud_rect()
        painter.setPen(QColor(80, 190, 255))
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(QRect(int(x), int(y), int(w), int(h)))
        painter.setBrush(QColor(255, 255, 255))
        for cx, cy in self._corners((x, y, w, h)):
            painter.drawRect(int(cx - HANDLE_SIZE / 2), int(cy - HANDLE_SIZE / 2),
                             HANDLE_SIZE, HANDLE_SIZE)
        painter.setPen(QColor(255, 255, 255, 200))
        painter.drawText(QRect(8, self.height() - 24, self.width() - 16, 20),
                         Qt.AlignLeft | Qt.AlignVCenter,
                         "HUD Transform: drag = move, corners = resize area, wheel = font size, "
                         "Enter = commit, Esc = cancel, right-click = menu")
        painter.end()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        pos = event.pos()
        if event.button() == Qt.RightButton:
            self._show_menu(self.mapToGlobal(pos))
            return
        if event.button() != Qt.LeftButton:
            return
        rect = self._hud_rect()
        transform = hudManager.get_transform()
        if transform is None:
            self.cancel(reason="HUD node missing on mouse press")
            return
        self._press_pos = pos
        self._press_rect = rect
        self._press_transform = transform
        corner = self._hit_corner(pos, rect)
        if corner is not None:
            self._drag_mode = "resize"
            self._drag_corner = corner
        elif self._inside(pos, rect):
            self._drag_mode = "move"
        else:
            self._drag_mode = None

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        pos = event.pos()
        if self._drag_mode is None:
            rect = self._hud_rect()
            corner = self._hit_corner(pos, rect)
            if corner in (0, 2):
                self.setCursor(Qt.SizeFDiagCursor)
            elif corner in (1, 3):
                self.setCursor(Qt.SizeBDiagCursor)
            elif self._inside(pos, rect):
                self.setCursor(Qt.SizeAllCursor)
            else:
                self.unsetCursor()
            return
        width = float(max(1, self.width()))
        height = float(max(1, self.height()))
        ox, oy, _ = self._press_transform
        current = hudManager.get_transform()
        if current is None:
            return
        scale = current[2]
        dx, dy = pos.x() - self._press_pos.x(), pos.y() - self._press_pos.y()
        if self._drag_mode == "move":
            self._apply(ox + dx / width, oy + dy / height, scale)
            return
        # Resize independently in each axis, using the mouse delta so clicking
        # near (rather than exactly on) a handle does not jump the frame.
        corners = self._corners(self._press_rect)
        cx, cy = corners[self._drag_corner]
        ax, ay = corners[(self._drag_corner + 2) % 4]
        ax, ay = min(width, max(0.0, ax)), min(height, max(0.0, ay))
        min_w, min_h = self._minimum_frame_size(scale)
        if self._drag_corner in (0, 3):
            left, right = min(max(0.0, cx + dx), ax - min(min_w, ax)), ax
        else:
            left, right = ax, max(min(width, cx + dx), ax + min(min_w, width - ax))
        if self._drag_corner in (0, 1):
            top, bottom = min(max(0.0, cy + dy), ay - min(min_h, ay)), ay
        else:
            top, bottom = ay, max(min(height, cy + dy), ay + min(min_h, height - ay))
        hudManager.set_frame_size((right - left) / width, (bottom - top) / height,
                                  save=False, refresh=False)
        hudManager.set_transform(left / width, top / height, scale, save=False)
        self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._drag_mode = None
        self._drag_corner = None

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        self.commit(reason="double-click")

    def wheelEvent(self, event) -> None:  # noqa: N802
        transform = hudManager.get_transform()
        if transform is None:
            return
        steps = event.angleDelta().y() / 120.0
        ox, oy, scale = transform
        frame_w, frame_h = hudManager.get_frame_size() or hudManager.load_frame_size()
        vp_w, vp_h = self._physical_viewport_size()
        # Limit the font so an ellipsis still fits. Never resize the area in
        # response to the wheel, and never change the font during a corner drag.
        max_font = max(6, min(200, math.floor(min(frame_w * vp_w / 4.0,
                                                 frame_h * vp_h / 3.0))))
        max_scale = min(MAX_SCALE, (max_font + 0.49) / ((13.0 / 720.0) * vp_h))
        new_scale = min(max_scale, max(MIN_SCALE, scale * (1.1 ** steps)))
        hudManager.set_transform(ox, oy, new_scale, save=False)
        self.update()
        event.accept()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        key = event.key()
        if key in (Qt.Key_Return, Qt.Key_Enter):
            self.commit(reason="Enter key")
            return
        if key == Qt.Key_Escape:
            self.cancel(reason="Esc key")
            return
        nudges = {Qt.Key_Left: (-1, 0), Qt.Key_Right: (1, 0),
                  Qt.Key_Up: (0, -1), Qt.Key_Down: (0, 1)}
        if key in nudges:
            transform = hudManager.get_transform()
            if transform is None:
                return
            step = 10.0 if event.modifiers() & Qt.ShiftModifier else 1.0
            dx, dy = nudges[key]
            ox, oy, scale = transform
            self._apply(ox + dx * step / max(1, self.width()),
                        oy + dy * step / max(1, self.height()), scale)
            return
        super().keyPressEvent(event)

    def closeEvent(self, event) -> None:  # noqa: N802
        if not self._done:
            self.cancel(reason="window closed externally")
        super().closeEvent(event)

    def _show_menu(self, global_pos: QPoint) -> None:
        menu = qt.QMenu(self)
        commit_action = menu.addAction("Commit")
        cancel_action = menu.addAction("Cancel")
        menu.addSeparator()
        reset_action = menu.addAction("Reset Position / Area / Font")
        self._menu = menu  # keep a Python ref while the menu is open
        chosen = qt.exec_menu(menu, global_pos)
        if chosen is commit_action:
            self.commit(reason="menu")
        elif chosen is cancel_action:
            self.cancel(reason="menu")
        elif chosen is reset_action:
            self.reset()
