"""Item delegates that paint and edit slider-style value rows.

Extracted from the monolithic editor window module. The delegates own custom
painting, value-drag interaction, and icon hit-testing used by the primaries,
shapes, active-shapes, work-shapes, and split-weight lists.

Example:
    >>> from blue_steel.ui.editor import delegates
    >>> delegate = delegates.SliderItemDelegate(view)
"""

from __future__ import annotations

from typing import Dict, List, Optional

from maya import cmds

from ..common.icons import (
    CONNECTED_MESH_DISABLED_ICON,
    CONNECTED_MESH_ENABLED_ICON,
    EDIT_ICON,
    LOCK_OFF_ICON,
    LOCK_ON_ICON,
    MUTE_OFF_ICON,
    MUTE_ON_ICON,
)
from .models import ShapeItemsModel, WorkShapeItemsModel
from .qt import (
    QAbstractItemView,
    QApplication,
    QColor,
    QCursor,
    QDoubleValidator,
    QEvent,
    QIcon,
    QLineEdit,
    QModelIndex,
    QObject,
    QPainter,
    QPersistentModelIndex,
    QRect,
    QSize,
    QStyle,
    QStyledItemDelegate,
    Qt,
    Signal,
    OptionRect,
)


class _DragEventFilter(QObject):
    """Forward global mouse move/release events to an active slider drag.

    Qt delivers mouse events to the widget under the pointer, which means a
    value drag could otherwise be left in an active state when the user releases
    the button outside the view. Installing this filter for the lifetime of a
    drag guarantees the drag always ends and the undo chunk always closes.
    """

    def __init__(self, delegate: "SliderItemDelegate") -> None:
        super().__init__()
        self._delegate = delegate

    def eventFilter(self, watched, event):  # noqa: N802
        if event.type() == QEvent.MouseMove and self._delegate.is_drag_active():
            self._delegate.external_drag_move(self._delegate.viewport_x_from_global(QCursor.pos()))
            return True
        if event.type() == QEvent.MouseButtonRelease and self._delegate.is_drag_active():
            if event.button() == Qt.LeftButton:
                self._delegate.external_drag_end(self._delegate.viewport_x_from_global(QCursor.pos()))
                return True
        return super().eventFilter(watched, event)



class SliderItemDelegate(QStyledItemDelegate):
    """Slider-style delegate inspired by the reference slider delegate.

    It paints each item as:
    - Name text area
    - Value area with a horizontal fill bar
    - Editable values for primaries only
    """

    valueDragStarted = Signal()
    valueDragEnded = Signal()
    valueDragDelta = Signal(float)
    valueDragSelectionContext = Signal(bool)
    muteToggleRequested = Signal(str, bool)
    lockToggleRequested = Signal(str, bool)
    connectedMeshRequested = Signal(str)
    workEditModeToggleRequested = Signal(str, bool)

    VALUE_COLUMN_WIDTH = 86
    VALUE_TEXT_PADDING = 8
    FALLBACK_VALUE_TEXT_WIDTH = 48
    LEFT_MARGIN = 6
    RIGHT_MARGIN = 4
    TREE_INDENT = 6
    VALUE_TO_ICON_GAP = 10
    ICON_SIZE = 22
    ICON_GAP = 3
    MIN_TEXT_WIDTH = 20

    def _is_primary_tree_view(self) -> bool:
        parent_view = self.parent()
        return bool(getattr(parent_view, "_primary_tree_layout", False))

    def sizeHint(self, option, index):  # noqa: N802
        if bool(index.model().data(index, ShapeItemsModel.IsHeaderRole)):
            return QSize(option.rect.width(), 28)
        if self._is_primary_tree_view() or bool(getattr(self.parent(), "_primary_slider_layout", False)):
            return QSize(option.rect.width(), 20)
        return QSize(option.rect.width(), 24)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._name_column_width = 0
        self._value_column_width = self.VALUE_COLUMN_WIDTH
        self._drag_active = False
        self._undo_chunk_open = False
        self._drag_index = QPersistentModelIndex()
        self._drag_model = None
        self._drag_start_x = 0
        self._drag_start_value = 0.0
        self._drag_range_px = 1
        self._drag_target_indexes: List[QPersistentModelIndex] = []
        self._drag_target_start_values: Dict[QPersistentModelIndex, float] = {}
        self._drag_event_filter = _DragEventFilter(self)

    def _open_drag_undo_chunk(self) -> None:
        if self._undo_chunk_open:
            return
        try:
            cmds.undoInfo(openChunk=True, chunkName="BlueSteel Slider Drag")
            self._undo_chunk_open = True
        except Exception:
            self._undo_chunk_open = False

    def _close_drag_undo_chunk(self) -> None:
        if not self._undo_chunk_open:
            return
        try:
            cmds.undoInfo(closeChunk=True)
        except Exception:
            pass
        finally:
            self._undo_chunk_open = False

    def set_name_column_width(self, width: int) -> None:
        """Set aligned name column width used to place the value area."""
        self._name_column_width = max(0, int(width))

    def value_column_width(self) -> int:
        """Return fixed value column width used by rows and headers."""
        return self._value_column_width

    def _value_text_width(self, option=None) -> int:
        font_metrics = getattr(option, "fontMetrics", None)
        if font_metrics is None and self.parent() is not None:
            font_metrics = self.parent().fontMetrics()
        return font_metrics.horizontalAdvance("0.000") + self.VALUE_TEXT_PADDING if font_metrics is not None else self.FALLBACK_VALUE_TEXT_WIDTH

    def _area_rects(self, option, index):
        rect = option.rect
        shape_type = str(index.model().data(index, ShapeItemsModel.TypeRole) or "")
        is_work_shape = shape_type == "WorkShape"
        left_margin = self.LEFT_MARGIN + self._tree_row_indent(index)
        if bool(getattr(self.parent(), "_primary_slider_layout", False)):
            value_rect = rect.adjusted(left_margin, 0, -self.RIGHT_MARGIN, 0)
            text_rect = value_rect.adjusted(self.VALUE_TEXT_PADDING, 0, -self.VALUE_TEXT_PADDING, 0)
            return value_rect, text_rect
        value_text_w = self._value_text_width(option)
        available_w = max(1, rect.width() - left_margin - self.RIGHT_MARGIN)
        icon_slots = self._reserved_icon_slots(index)
        icon_area_w = (self.ICON_SIZE * icon_slots) + (self.ICON_GAP * icon_slots)
        reserved_text_w = max(self.MIN_TEXT_WIDTH, min(self._name_column_width, available_w))
        reserved_after_value_w = self.VALUE_TO_ICON_GAP + icon_area_w + reserved_text_w
        value_w = min(self._value_column_width, max(value_text_w, available_w - reserved_after_value_w), available_w)

        value_left = rect.left() + left_margin
        value_rect = QRect(value_left, rect.top(), value_w, rect.height())

        icon_left = value_rect.right() + 1 + self.VALUE_TO_ICON_GAP
        text_left = icon_left + (self.ICON_SIZE * icon_slots) + (self.ICON_GAP * icon_slots)
        right_margin = self.RIGHT_MARGIN + (self.ICON_SIZE + self.ICON_GAP if is_work_shape else 0)
        text_width = max(self.MIN_TEXT_WIDTH, rect.right() - text_left - right_margin)
        text_rect = QRect(text_left, rect.top(), text_width, rect.height())
        return value_rect, text_rect

    def _tree_row_indent(self, index) -> int:
        parent_view = self.parent()
        if not bool(getattr(parent_view, "_tree_view_layout", False)) and not self._is_primary_tree_view():
            return 0
        depth = 0
        parent_index = index.parent()
        while parent_index.isValid():
            depth += 1
            parent_index = parent_index.parent()
        return depth * self.TREE_INDENT

    def _connected_mesh_icon_rect(self, option, index) -> QRect:
        shape_type = str(index.model().data(index, ShapeItemsModel.TypeRole) or "")
        if shape_type != "WorkShape":
            return QRect()
        value_rect, _ = self._area_rects(option, index)
        x = value_rect.right() + 1 + self.VALUE_TO_ICON_GAP
        y = option.rect.top() + (option.rect.height() - self.ICON_SIZE) // 2
        return QRect(x, y, self.ICON_SIZE, self.ICON_SIZE)

    def _is_lock_icon_visible(self, index) -> bool:
        return bool(index.model().data(index, ShapeItemsModel.LockIconVisibleRole))

    def _shows_mute_icon(self, index) -> bool:
        parent_view = self.parent()
        return not self._is_primary_tree_view() and not bool(getattr(parent_view, "_hides_mute_icon", False))

    def _panel_reserved_icon_slots(self) -> int:
        parent_view = self.parent()
        if self._is_primary_tree_view():
            return 0
        return int(getattr(parent_view, "_panel_icon_slots", 1))

    def _is_work_edit_mode_icon_visible(self, index) -> bool:
        shape_type = str(index.model().data(index, ShapeItemsModel.TypeRole) or "")
        return shape_type == "WorkShape"

    def _reserved_icon_slots(self, index) -> int:
        shape_type = str(index.model().data(index, ShapeItemsModel.TypeRole) or "")
        is_work_shape = shape_type == "WorkShape"
        reserved_slots = self._panel_reserved_icon_slots()
        work_shape_slots = 1 if is_work_shape else 0
        actual_slots = (1 if self._shows_mute_icon(index) else 0) + (1 if self._is_lock_icon_visible(index) else 0) + work_shape_slots
        return max(reserved_slots, actual_slots)

    def _mute_icon_rect(self, option, index) -> QRect:
        if not self._shows_mute_icon(index):
            return QRect()
        connected_rect = self._connected_mesh_icon_rect(option, index)
        if not connected_rect.isNull():
            return QRect(connected_rect.right() + 1 + self.ICON_GAP, connected_rect.top(), connected_rect.width(), connected_rect.height())
        value_rect, _ = self._area_rects(option, index)
        x = value_rect.right() + 1 + self.VALUE_TO_ICON_GAP
        y = option.rect.top() + (option.rect.height() - self.ICON_SIZE) // 2
        return QRect(x, y, self.ICON_SIZE, self.ICON_SIZE)

    def _edit_mode_icon_rect(self, option, index) -> QRect:
        if not self._is_work_edit_mode_icon_visible(index):
            return QRect()
        x = option.rect.right() - self.RIGHT_MARGIN - self.ICON_SIZE + 1
        y = option.rect.top() + (option.rect.height() - self.ICON_SIZE) // 2
        return QRect(x, y, self.ICON_SIZE, self.ICON_SIZE)

    def _lock_icon_rect(self, option, index) -> QRect:
        if not self._is_lock_icon_visible(index):
            return QRect()
        mute_rect = self._mute_icon_rect(option, index)
        if not mute_rect.isNull():
            return QRect(mute_rect.right() + 1 + self.ICON_GAP, mute_rect.top(), mute_rect.width(), mute_rect.height())
        connected_rect = self._connected_mesh_icon_rect(option, index)
        if not connected_rect.isNull():
            return QRect(connected_rect.right() + 1 + self.ICON_GAP, connected_rect.top(), connected_rect.width(), connected_rect.height())
        value_rect, _ = self._area_rects(option, index)
        x = value_rect.right() + 1 + self.VALUE_TO_ICON_GAP
        y = option.rect.top() + (option.rect.height() - self.ICON_SIZE) // 2
        return QRect(x, y, self.ICON_SIZE, self.ICON_SIZE)

    def _draw_icon_pixmap(self, painter: QPainter, icon_rect: QRect, icon: QIcon) -> None:
        """Draw icon with smoother scaling and HiDPI-aware rasterization."""
        if icon_rect.isNull() or icon.isNull():
            return

        dpr = 1.0
        device = painter.device()
        if device is not None and hasattr(device, "devicePixelRatioF"):
            try:
                dpr = max(1.0, float(device.devicePixelRatioF()))
            except Exception:
                dpr = 1.0

        pixmap_size = QSize(
            max(1, int(round(icon_rect.width() * dpr))),
            max(1, int(round(icon_rect.height() * dpr))),
        )
        pixmap = icon.pixmap(pixmap_size)
        if pixmap.isNull():
            return

        pixmap.setDevicePixelRatio(dpr)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        painter.drawPixmap(icon_rect, pixmap)

    def paint(self, painter: QPainter, option, index):
        model = index.model()
        if bool(model.data(index, ShapeItemsModel.IsHeaderRole)):
            name = model.data(index, ShapeItemsModel.NameRole) or ""
            rect = option.rect
            parent_view = self.parent()
            is_group_tree = bool(getattr(parent_view, "_tree_view_layout", False)) or self._is_primary_tree_view()
            painter.save()
            header_bg = option.palette.alternateBase().color()
            header_bg.setAlpha(190)
            painter.fillRect(rect, header_bg)
            painter.setPen(option.palette.mid().color())
            painter.drawLine(rect.left() + 2, rect.bottom(), rect.right() - 2, rect.bottom())
            font = painter.font()
            font.setBold(True)
            painter.setFont(font)
            painter.setPen(option.palette.text().color())
            text_rect = rect.adjusted(6, 0, -6, 0)
            if is_group_tree and not bool(getattr(parent_view, "_uses_native_branch_indicator", False)):
                indent = self._tree_row_indent(index)
                icon_size = 14
                icon_rect = QRect(rect.left() + indent + 2, rect.top() + (rect.height() - icon_size) // 2, icon_size, icon_size)
                icon = index.data(Qt.DecorationRole)
                if isinstance(icon, QIcon) and not icon.isNull():
                    self._draw_icon_pixmap(painter, icon_rect, icon)
                else:
                    is_expanded = bool(parent_view.isExpanded(index)) if parent_view is not None else False
                    painter.drawText(icon_rect, Qt.AlignCenter, "v" if is_expanded else ">")
                text_rect = rect.adjusted(indent + icon_size + 6, 0, -6, 0)
            painter.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft, f"{name}")
            painter.restore()
            return

        name = model.data(index, ShapeItemsModel.NameRole) or ""
        value = float(model.data(index, ShapeItemsModel.ValueRole) or 0.0)
        muted = bool(model.data(index, ShapeItemsModel.MutedRole))
        in_edit_mode = bool(model.data(index, WorkShapeItemsModel.InEditModeRole))
        editable = bool(model.data(index, ShapeItemsModel.EditableRole))
        shape_type = str(model.data(index, ShapeItemsModel.TypeRole) or "")
        is_work_shape = shape_type == "WorkShape"
        is_connected_work_shape = bool(model.data(index, WorkShapeItemsModel.ConnectedRole)) if is_work_shape else False
        is_driver_connected_work_shape = bool(model.data(index, WorkShapeItemsModel.DriverConnectedRole)) if is_work_shape else False
        is_upstream_related = bool(model.data(index, ShapeItemsModel.UpstreamRelatedRole))
        is_downstream_related = bool(model.data(index, ShapeItemsModel.DownstreamRelatedRole))

        value_rect, text_rect = self._area_rects(option, index)
        base_color = option.palette.base().color()
        name_text_color = option.palette.text().color()
        value_text_color = option.palette.text().color()
        is_combo_shape = shape_type in {"ComboShape", "ComboInbetweenShape", "InbetweenShape"}

        painter.save()
        painter.fillRect(option.rect, base_color)

        parent_view = self.parent()
        is_shapes_tree = bool(getattr(parent_view, "_shapes_tree_layout", False))
        if is_shapes_tree and not (option.state & QStyle.State_Selected):
            if is_upstream_related or is_downstream_related:
                related_color = QColor(95, 173, 136, 90)
                painter.fillRect(option.rect, related_color)

        if option.state & QStyle.State_Selected:
            sel = option.palette.highlight().color()
            sel.setAlpha(60)
            painter.fillRect(option.rect, sel)

        indicator_rect = QRect(option.rect.left() + self._tree_row_indent(index) + 1, option.rect.top() + 3, 4, max(6, option.rect.height() - 6))
        indicator_color = QColor(0, 0, 0, 0)
        if is_driver_connected_work_shape:
            # Maya-like driven-key cue for linked work shapes.
            indicator_color = QColor(102, 153, 255)
        elif shape_type in {"InbetweenShape", "ComboShape", "ComboInbetweenShape"}:
            # Maya channel-box-like direct-connection cue.
            indicator_color = QColor(220, 190, 76)
        if indicator_color.alpha() > 0:
            painter.fillRect(indicator_rect, indicator_color)

        track_rect = value_rect.adjusted(0, 3, 0, -3)
        progress_width = int(max(0.0, min(1.0, value)) * track_rect.width())

        value_bg = QColor(57, 57, 57)
        track_border = QColor(83, 83, 83)
        fill_color = QColor(109, 109, 109)
        if is_driver_connected_work_shape:
            fill_color = option.palette.highlight().color()

        painter.fillRect(track_rect, value_bg)
        painter.setPen(track_border)
        painter.drawRect(track_rect.adjusted(0, 0, -1, -1))

        if progress_width > 0:
            progress_rect = QRect(track_rect.left(), track_rect.top(), progress_width, track_rect.height())
            painter.fillRect(progress_rect, fill_color)

        custom_color = model.data(index, ShapeItemsModel.ColorRole)
        if isinstance(custom_color, QColor) and custom_color.isValid():
            name_text_color = custom_color
        if muted:
            name_text_color = QColor("gray")
        if in_edit_mode:
            name_text_color = QColor(230, 74, 74)
            bold_font = painter.font()
            bold_font.setBold(True)
            painter.setFont(bold_font)

        painter.setPen(name_text_color)
        painter.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft, name)
        if not bool(getattr(parent_view, "_primary_slider_layout", False)):
            painter.setPen(value_text_color)
            painter.drawText(value_rect.adjusted(0, 0, -6, 0), Qt.AlignVCenter | Qt.AlignRight, f"{value:.3f}")

        icon_rect = self._mute_icon_rect(option, index)
        mute_icon = MUTE_ON_ICON if muted else MUTE_OFF_ICON
        if not icon_rect.isNull() and not mute_icon.isNull():
            self._draw_icon_pixmap(painter, icon_rect, mute_icon)

        connected_icon_rect = self._connected_mesh_icon_rect(option, index)
        if not connected_icon_rect.isNull():
            connected_icon = CONNECTED_MESH_ENABLED_ICON if is_connected_work_shape else CONNECTED_MESH_DISABLED_ICON
            if not connected_icon.isNull():
                self._draw_icon_pixmap(painter, connected_icon_rect, connected_icon)

        edit_mode_rect = self._edit_mode_icon_rect(option, index)
        if not edit_mode_rect.isNull():
            button_color = QColor(198, 65, 65) if in_edit_mode else QColor(82, 82, 82)
            painter.save()
            painter.setRenderHint(QPainter.Antialiasing, True)
            painter.setPen(QColor(35, 35, 35))
            painter.setBrush(button_color)
            painter.drawRoundedRect(edit_mode_rect.adjusted(1, 1, -1, -1), 3, 3)
            painter.restore()
            if not EDIT_ICON.isNull():
                self._draw_icon_pixmap(painter, edit_mode_rect.adjusted(3, 3, -3, -3), EDIT_ICON)

        lock_rect = self._lock_icon_rect(option, index)
        if not lock_rect.isNull():
            is_locked = bool(model.data(index, ShapeItemsModel.LockedRole))
            lock_icon = LOCK_ON_ICON if is_locked else LOCK_OFF_ICON
            if not lock_icon.isNull():
                self._draw_icon_pixmap(painter, lock_rect, lock_icon)

        painter.restore()

    def createEditor(self, parent, option, index):  # noqa: N802
        if bool(index.model().data(index, ShapeItemsModel.IsHeaderRole)):
            return None
        if self._is_primary_tree_view() or bool(getattr(self.parent(), "_primary_slider_layout", False)):
            return None
        if not bool(index.model().data(index, ShapeItemsModel.EditableRole)):
            return None
        editor = QLineEdit(parent)
        editor.setFrame(False)
        editor.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        editor.setValidator(QDoubleValidator(0.0, 1.0, 4, editor))
        return editor

    def setEditorData(self, editor, index):  # noqa: N802
        value = float(index.model().data(index, ShapeItemsModel.ValueRole) or 0.0)
        editor.setText(f"{value:.4f}")

    def setModelData(self, editor, model, index):  # noqa: N802
        try:
            value = float(editor.text())
        except ValueError:
            return

        if not index.isValid():
            return

        parent = self.parent()
        selected_indexes = []
        if isinstance(parent, QAbstractItemView) and parent.selectionModel() is not None:
            selected_indexes = parent.selectionModel().selectedIndexes()

        if index in selected_indexes:
            target_indexes = selected_indexes
        else:
            target_indexes = [index]

        persistent_targets: List[QPersistentModelIndex] = []
        for target in target_indexes:
            if not target.isValid():
                continue
            if bool(target.data(ShapeItemsModel.IsHeaderRole)):
                continue
            if not bool(target.data(ShapeItemsModel.EditableRole)):
                continue
            persistent_targets.append(QPersistentModelIndex(target))

        if not persistent_targets:
            persistent_targets = [QPersistentModelIndex(index)]

        for target in persistent_targets:
            if target.isValid():
                model.setData(target, value, ShapeItemsModel.ValueRole)

    def updateEditorGeometry(self, editor, option, index):  # noqa: N802
        value_rect, _ = self._area_rects(option, index)
        editor.setGeometry(value_rect)

    def _set_drag_value_from_pos(self, model, x_pos: int) -> None:
        """Set value(s) from drag delta using captured drag start state."""
        if not self._drag_target_indexes:
            return
        delta_px = x_pos - self._drag_start_x
        delta_value = float(delta_px) / float(max(1, self._drag_range_px))
        self.valueDragDelta.emit(delta_value)
        for target_index in self._drag_target_indexes:
            if not target_index.isValid():
                continue
            start_value = self._drag_target_start_values.get(target_index, 0.0)
            new_value = max(0.0, min(1.0, start_value + delta_value))
            model.setData(target_index, new_value, ShapeItemsModel.ValueRole)

    def _resolve_drag_targets(self, index) -> None:
        """Resolve drag targets based on current selection rules.

        If drag starts on a selected item, all selected editable items are targets.
        If drag starts on a non-selected item, only that item is targeted.
        """
        self._drag_target_indexes = []
        self._drag_target_start_values = {}

        if not index.isValid():
            return

        parent = self.parent()
        selected = []
        if isinstance(parent, QAbstractItemView) and parent.selectionModel() is not None:
            selected = parent.selectionModel().selectedIndexes()

        if index in selected:
            candidate_indexes = selected
        else:
            candidate_indexes = [index]

        for candidate in candidate_indexes:
            if not candidate.isValid():
                continue
            if bool(candidate.data(ShapeItemsModel.IsHeaderRole)):
                continue
            if not bool(candidate.data(ShapeItemsModel.EditableRole)):
                continue
            persistent = QPersistentModelIndex(candidate)
            self._drag_target_indexes.append(persistent)
            self._drag_target_start_values[persistent] = float(candidate.data(ShapeItemsModel.ValueRole) or 0.0)

    def _start_drag(self, model, index, event_pos, value_rect: QRect) -> None:
        parent = self.parent()
        is_drag_source_selected = False
        if isinstance(parent, QAbstractItemView) and parent.selectionModel() is not None:
            is_drag_source_selected = index in parent.selectionModel().selectedIndexes()
        self.valueDragSelectionContext.emit(is_drag_source_selected)

        self._drag_active = True
        self._drag_index = QPersistentModelIndex(index)
        self._drag_model = model
        self._drag_start_x = event_pos.x()
        self._drag_start_value = float(model.data(index, ShapeItemsModel.ValueRole) or 0.0)
        self._drag_range_px = max(1, value_rect.width() - 1)
        self._resolve_drag_targets(index)
        if not self._drag_target_indexes:
            self._drag_target_indexes = [self._drag_index]
            self._drag_target_start_values[self._drag_index] = self._drag_start_value
        self._install_drag_event_filter()
        self._open_drag_undo_chunk()
        self.valueDragStarted.emit()
        self._set_drag_value_from_pos(model, event_pos.x())

    def _end_drag(self, model, x_pos: int) -> None:
        if self._drag_active:
            self._set_drag_value_from_pos(model, x_pos)
        self._drag_active = False
        self._drag_index = QPersistentModelIndex()
        self._drag_model = None
        self._drag_start_x = 0
        self._drag_start_value = 0.0
        self._drag_range_px = 1
        self._drag_target_indexes = []
        self._drag_target_start_values = {}
        self._remove_drag_event_filter()
        self.valueDragEnded.emit()
        self._close_drag_undo_chunk()

    def _install_drag_event_filter(self) -> None:
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self._drag_event_filter)

    def _remove_drag_event_filter(self) -> None:
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self._drag_event_filter)

    def viewport_x_from_global(self, global_pos) -> int:
        parent = self.parent()
        if isinstance(parent, QAbstractItemView):
            return parent.viewport().mapFromGlobal(global_pos).x()
        return global_pos.x()

    def is_drag_active(self) -> bool:
        return self._drag_active

    def external_drag_move(self, x_pos: int) -> bool:
        """Update drag from list-view mouse move, independent of hovered item."""
        if not self._drag_active or self._drag_model is None:
            return False
        self._set_drag_value_from_pos(self._drag_model, x_pos)
        return True

    def external_drag_end(self, x_pos: int) -> bool:
        """Finish drag from list-view mouse release, independent of hovered item."""
        if not self._drag_active or self._drag_model is None:
            return False
        self._end_drag(self._drag_model, x_pos)
        return True

    def external_drag_start(self, model, index, event_pos, item_rect: QRect) -> bool:
        """Start a drag when a view intercepts a press in this delegate's slider area."""

        option = OptionRect()
        option.rect = item_rect
        value_rect, _ = self._area_rects(option, index)
        if not value_rect.contains(event_pos):
            return False
        self._start_drag(model, index, event_pos, value_rect)
        return True

    def editorEvent(self, event, model, option, index):  # noqa: N802
        if bool(model.data(index, ShapeItemsModel.IsHeaderRole)):
            return super().editorEvent(event, model, option, index)

        if not bool(model.data(index, ShapeItemsModel.EditableRole)):
            return super().editorEvent(event, model, option, index)

        if event.type() == QEvent.MouseButtonDblClick:
            # Open the inline value editor only on the slider area; always consume
            # so Qt does not start its own name-edit on editable rows.
            value_rect, _ = self._area_rects(option, index)
            parent = self.parent()
            if value_rect.contains(event.pos()) and isinstance(parent, QAbstractItemView):
                parent.edit(index)
            return True

        return super().editorEvent(event, model, option, index)



class SplitMapWeightSliderDelegate(SliderItemDelegate):
    """Maya-style split-weight slider with a separate numeric field."""

    MIN_NAME_WIDTH = 24
    MAX_NAME_WIDTH = 120
    MIN_SLIDER_WIDTH = 48
    VALUE_FIELD_WIDTH = 48
    VALUE_FIELD_GAP = 5

    def sizeHint(self, option, index):  # noqa: N802
        return QSize(1, 28)

    def _row_rects(self, option, index):
        rect = option.rect
        left = rect.left() + self.LEFT_MARGIN
        content_right = rect.right() - self.RIGHT_MARGIN
        available_width = max(1, content_right - left)
        font_metrics = getattr(option, "fontMetrics", None)
        name = str(index.data(ShapeItemsModel.NameRole) or "")
        name_hint = font_metrics.horizontalAdvance(name) + 4 if font_metrics is not None else self.MIN_NAME_WIDTH
        maximum_name_width = max(
            self.MIN_NAME_WIDTH,
            available_width - self.MIN_SLIDER_WIDTH - self.VALUE_FIELD_WIDTH - self.VALUE_FIELD_GAP - 4,
        )
        name_width = min(self.MAX_NAME_WIDTH, maximum_name_width, max(self.MIN_NAME_WIDTH, name_hint))
        text_rect = QRect(left, rect.top(), name_width, rect.height())
        slider_left = text_rect.right() + 4
        value_field_right = content_right
        value_field_width = min(self.VALUE_FIELD_WIDTH, max(1, value_field_right - slider_left - self.VALUE_FIELD_GAP))
        value_field_left = value_field_right - value_field_width + 1
        value_field_rect = QRect(
            value_field_left,
            rect.top() + (rect.height() - 18) // 2,
            value_field_width,
            18,
        )
        slider_width = max(1, value_field_left - self.VALUE_FIELD_GAP - slider_left)
        slider_rect = QRect(slider_left, rect.top(), slider_width, rect.height())
        return slider_rect, value_field_rect, text_rect

    def _area_rects(self, option, index):
        slider_rect, _value_field_rect, text_rect = self._row_rects(option, index)
        return slider_rect, text_rect

    def paint(self, painter: QPainter, option, index) -> None:
        value = max(0.0, min(1.0, float(index.data(ShapeItemsModel.ValueRole) or 0.0)))
        name = str(index.data(ShapeItemsModel.NameRole) or "")
        slider_rect, value_field_rect, text_rect = self._row_rects(option, index)

        painter.save()
        painter.fillRect(option.rect, option.palette.base().color())
        if option.state & QStyle.State_Selected:
            selection_color = option.palette.highlight().color()
            selection_color.setAlpha(55)
            painter.fillRect(option.rect, selection_color)

        painter.setPen(option.palette.text().color())
        display_name = option.fontMetrics.elidedText(name, Qt.ElideRight, text_rect.width())
        painter.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft, display_name)

        track_left = min(slider_rect.left() + 6, slider_rect.right())
        track_right = max(track_left, slider_rect.right() - 6)
        track_y = slider_rect.center().y()
        cursor_x = track_left + int(value * max(1, track_right - track_left))
        track_rect = QRect(track_left, track_y - 2, max(1, track_right - track_left + 1), 5)
        painter.fillRect(track_rect, QColor(82, 82, 82))
        progress_rect = QRect(track_left, track_y - 2, max(1, cursor_x - track_left + 1), 5)
        painter.fillRect(progress_rect, option.palette.highlight().color())
        cursor_rect = QRect(cursor_x - 6, track_y - 6, 12, 12)
        painter.setPen(QColor(35, 35, 35))
        painter.setBrush(option.palette.highlight().color())
        painter.drawEllipse(cursor_rect)

        painter.setPen(option.palette.mid().color())
        painter.setBrush(option.palette.base().color())
        painter.drawRect(value_field_rect.adjusted(0, 0, -1, -1))
        painter.setPen(option.palette.text().color())
        painter.drawText(value_field_rect.adjusted(3, 0, -3, 0), Qt.AlignVCenter | Qt.AlignRight, f"{value:.3f}")

        painter.restore()

    def editorEvent(self, event, model, option, index):  # noqa: N802
        if event.type() == QEvent.MouseButtonDblClick:
            _slider_rect, value_field_rect, _text_rect = self._row_rects(option, index)
            if value_field_rect.contains(event.pos()):
                parent = self.parent()
                if isinstance(parent, QAbstractItemView):
                    parent.edit(index)
            return True
        return super().editorEvent(event, model, option, index)

    def updateEditorGeometry(self, editor, option, index):  # noqa: N802
        _slider_rect, value_field_rect, _text_rect = self._row_rects(option, index)
        editor.setGeometry(value_field_rect.adjusted(1, 1, -1, -1))

    def _shows_mute_icon(self, index) -> bool:
        del index
        return False

    def _panel_reserved_icon_slots(self) -> int:
        return 0



