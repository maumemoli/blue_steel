"""Centralized Qt (PySide2/PySide6) imports and shared Qt helpers.

This module is the single place where the Maya-version-specific Qt binding is
chosen. The rest of the editor imports Qt names from here instead of repeating
the ``if env.MAYA_VERSION > 2024`` block in every file.

It also hosts small helpers that remove the PySide2/PySide6 API differences
(``exec`` vs ``exec_``) and tiny geometry/color utilities shared across views
and models.

Example:
    >>> from blue_steel.ui.editor import qt
    >>> parent = qt.get_maya_main_window()
    >>> drag = qt.QDrag(widget)
    >>> qt.start_drag(drag, qt.Qt.CopyAction)
"""

from __future__ import annotations

from typing import List, Optional, Sequence

import maya.OpenMayaUI as omui

from ... import env

if env.MAYA_VERSION > 2024:
    from PySide6.QtCore import (
        QAbstractListModel,
        QEvent,
        QItemSelectionModel,
        QMimeData,
        QModelIndex,
        QObject,
        QPersistentModelIndex,
        QPoint,
        QRect,
        QSize,
        QSortFilterProxyModel,
        Qt,
        QTimer,
        Signal,
    )
    from PySide6.QtGui import (
        QAction,
        QActionGroup,
        QColor,
        QCursor,
        QDoubleValidator,
        QDrag,
        QGuiApplication,
        QIcon,
        QPainter,
        QPalette,
        QPixmap,
        QPolygon,
    )
    from PySide6.QtWidgets import (
        QAbstractItemView,
        QApplication,
        QCheckBox,
        QComboBox,
        QDialog,
        QDialogButtonBox,
        QFileDialog,
        QGroupBox,
        QHBoxLayout,
        QHeaderView,
        QInputDialog,
        QLabel,
        QLayout,
        QLineEdit,
        QListView,
        QListWidget,
        QListWidgetItem,
        QMainWindow,
        QMenu,
        QMenuBar,
        QMessageBox,
        QPushButton,
        QSizePolicy,
        QSplitter,
        QSplitterHandle,
        QStatusBar,
        QStyle,
        QStyledItemDelegate,
        QTabWidget,
        QTreeWidget,
        QTreeWidgetItem,
        QVBoxLayout,
        QWidget,
    )
    from shiboken6 import wrapInstance
else:
    from PySide2.QtCore import (
        QAbstractListModel,
        QEvent,
        QItemSelectionModel,
        QMimeData,
        QModelIndex,
        QObject,
        QPersistentModelIndex,
        QPoint,
        QRect,
        QSize,
        QSortFilterProxyModel,
        Qt,
        QTimer,
        Signal,
    )
    from PySide2.QtGui import (
        QColor,
        QCursor,
        QDoubleValidator,
        QDrag,
        QGuiApplication,
        QIcon,
        QPainter,
        QPalette,
        QPixmap,
        QPolygon,
    )
    from PySide2.QtWidgets import (
        QAbstractItemView,
        QAction,
        QActionGroup,
        QApplication,
        QCheckBox,
        QComboBox,
        QDialog,
        QDialogButtonBox,
        QFileDialog,
        QGroupBox,
        QHBoxLayout,
        QHeaderView,
        QInputDialog,
        QLabel,
        QLayout,
        QLineEdit,
        QListView,
        QListWidget,
        QListWidgetItem,
        QMainWindow,
        QMenu,
        QMenuBar,
        QMessageBox,
        QPushButton,
        QSizePolicy,
        QSplitter,
        QSplitterHandle,
        QStatusBar,
        QStyle,
        QStyledItemDelegate,
        QTabWidget,
        QTreeWidget,
        QTreeWidgetItem,
        QVBoxLayout,
        QWidget,
    )
    from shiboken2 import wrapInstance


class OptionRect:
    """Lightweight stand-in for :class:`QStyleOptionViewItem` in geometry helpers.

    Only ``rect`` and ``fontMetrics`` are used by the delegate layout code, so
    callers can build one cheaply instead of allocating a full Qt option object.

    Attributes:
        rect (QRect): The item rectangle.
        fontMetrics: Optional font metrics, typically from the hosting view.
    """

    def __init__(self, rect: Optional[QRect] = None, font_metrics=None) -> None:
        self.rect = rect
        self.fontMetrics = font_metrics


def get_maya_main_window() -> Optional[QWidget]:
    """Return Maya's main window as a ``QWidget``, or ``None`` when unavailable.

    Returns:
        Optional[QWidget]: Maya's main window, wrapped for the active Qt binding.

    Example:
        >>> parent = get_maya_main_window()
        >>> window = MainWindow(parent=parent)
    """
    main_window_ptr = omui.MQtUtil.mainWindow()
    if main_window_ptr is None:
        return None
    return wrapInstance(int(main_window_ptr), QWidget)


def exec_menu(menu: QMenu, global_pos: QPoint):
    """Execute a context menu using the PySide2/6-correct ``exec`` method.

    Parameters:
        menu (QMenu): The menu to show.
        global_pos (QPoint): Global position at which to show the menu.

    Returns:
        QAction: The action chosen by the user, or ``None``.
    """
    if hasattr(menu, "exec"):
        return menu.exec(global_pos)
    return menu.exec_(global_pos)


def exec_dialog(dialog: QDialog):
    """Execute a modal dialog using the PySide2/6-correct ``exec`` method.

    Parameters:
        dialog (QDialog): The dialog to show.

    Returns:
        int: The dialog result code (e.g. ``QDialog.Accepted``).
    """
    if hasattr(dialog, "exec"):
        return dialog.exec()
    return dialog.exec_()


def start_drag(drag: QDrag, action):
    """Start a Qt drag operation using the PySide2/6-correct ``exec`` method.

    Parameters:
        drag (QDrag): The configured drag object.
        action: The drop action(s) to allow.

    Returns:
        Qt.DropAction: The resulting drop action.
    """
    if hasattr(drag, "exec"):
        return drag.exec(action)
    return drag.exec_(action)


def make_shape_name_mime(shape_names: Sequence[str], mime_type: str) -> QMimeData:
    """Build MIME data for dragging one or more shape names.

    Parameters:
        shape_names (Sequence[str]): Names to place in the MIME payload.
        mime_type (str): Custom MIME type under which to store the payload.

    Returns:
        QMimeData: MIME data ready to attach to a :class:`QDrag`.
    """
    names = [str(name) for name in shape_names if str(name)]
    mime_data = QMimeData()
    payload = "\n".join(names).encode("utf-8")
    mime_data.setData(mime_type, payload)
    mime_data.setText("\n".join(names))
    return mime_data


def color_swatch_icon(color_hex: str, size: int = 14) -> QIcon:
    """Create a solid color swatch icon for a menu action.

    Parameters:
        color_hex (str): Color in ``#RRGGBB`` form.
        size (int): Icon size in pixels.

    Returns:
        QIcon: A solid-color icon.
    """
    pixmap = QPixmap(size, size)
    pixmap.fill(QColor(color_hex))
    return QIcon(pixmap)


def shape_custom_color_to_qcolor(value) -> Optional[QColor]:
    """Convert a stored custom shape color to a :class:`QColor`.

    Parameters:
        value: Either a ``#RRGGBB`` string or a legacy ``[R, G, B]`` sequence.

    Returns:
        Optional[QColor]: The color, or ``None`` when the value is invalid.
    """
    if isinstance(value, str):
        color = QColor(value)
    elif isinstance(value, (list, tuple)) and len(value) == 3:
        try:
            color = QColor(*[int(component) for component in value])
        except (TypeError, ValueError):
            return None
    else:
        return None
    return color if color.isValid() else None


class SplitterHandle(QSplitterHandle):
    """Splitter handle that always restores the default cursor on leave.

    Qt sets the resize cursor once on the handle and relies on its normal
    enter/leave delivery to swap the pointer shape back to the arrow. When the
    editor is docked (Maya workspace control) that leave delivery is sometimes
    missed, leaving the resize cursor stuck. Overriding the cursor here makes
    the restore explicit.
    """

    def enterEvent(self, event) -> None:  # noqa: N802
        if self.orientation() == Qt.Horizontal:
            self.setCursor(Qt.SplitHCursor)
        else:
            self.setCursor(Qt.SplitVCursor)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self.unsetCursor()
        super().leaveEvent(event)


class Splitter(QSplitter):
    """QSplitter that uses :class:`SplitterHandle` for its resize handles."""

    def createHandle(self):  # noqa: N802
        return SplitterHandle(self.orientation(), self)
