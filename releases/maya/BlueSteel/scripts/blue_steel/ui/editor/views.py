"""List and tree views used by the editor panels.

Extracted from the monolithic editor window module. These views own drag and
drop, keyboard navigation, and icon hit-testing; the visual painting lives in
:mod:`blue_steel.ui.editor.delegates`.

Example:
    >>> from blue_steel.ui.editor import views
    >>> view = views.SliderListView()
"""

from __future__ import annotations

import os
from typing import Callable, Dict, List, Optional, Sequence

from ... import env

from .constants import (
    PRIMARY_ORDER_MIME_TYPE,
    PRIMARY_TREE_FOLDER_ROLE,
    PRIMARY_TREE_INDENT,
    PRIMARY_TREE_MIME_TYPE,
    PRIMARY_TREE_NAME_ROLE,
    PRIMARY_TREE_SORT_VALUE_ROLE,
    SHAPE_NAMES_MIME_TYPE,
    WORK_SHAPE_ORDER_MIME_TYPE,
)
from .models import ShapeItemsModel, WorkShapeRoles
from .qt import (
    QAbstractItemView,
    QApplication,
    QColor,
    QCursor,
    QDrag,
    QEvent,
    QIcon,
    QItemSelectionModel,
    QListView,
    QListWidget,
    QMenu,
    QMimeData,
    QPainter,
    QPixmap,
    QSize,
    Qt,
    QTreeWidget,
    QTreeWidgetItem,
    Signal,
    OptionRect,
)


PRIMARY_NAME_ROLE = Qt.UserRole + 1
PRIMARY_TYPE_ROLE = Qt.UserRole + 2
PRIMARY_VALUE_ROLE = Qt.UserRole + 3
PRIMARY_MUTED_ROLE = Qt.UserRole + 4
PRIMARY_LEVEL_ROLE = Qt.UserRole + 5
PRIMARY_PRIMARIES_ROLE = Qt.UserRole + 6
PRIMARY_EDITABLE_ROLE = Qt.UserRole + 7
PRIMARY_IS_HEADER_ROLE = Qt.UserRole + 8
PRIMARY_HEADER_LEVEL_ROLE = Qt.UserRole + 9
PRIMARY_HEADER_COLLAPSED_ROLE = Qt.UserRole + 10
PRIMARY_UPSTREAM_RELATED_ROLE = Qt.UserRole + 11
PRIMARY_DOWNSTREAM_RELATED_ROLE = Qt.UserRole + 12
PRIMARY_LOCKED_ROLE = Qt.UserRole + 13
PRIMARY_LOCK_ICON_VISIBLE_ROLE = Qt.UserRole + 14

PRIMARY_DATA_ROLES = (
    PRIMARY_NAME_ROLE,
    PRIMARY_TYPE_ROLE,
    PRIMARY_VALUE_ROLE,
    PRIMARY_MUTED_ROLE,
    PRIMARY_LEVEL_ROLE,
    PRIMARY_PRIMARIES_ROLE,
    PRIMARY_EDITABLE_ROLE,
    PRIMARY_IS_HEADER_ROLE,
    PRIMARY_HEADER_LEVEL_ROLE,
    PRIMARY_HEADER_COLLAPSED_ROLE,
    PRIMARY_UPSTREAM_RELATED_ROLE,
    PRIMARY_DOWNSTREAM_RELATED_ROLE,
    PRIMARY_LOCKED_ROLE,
    PRIMARY_LOCK_ICON_VISIBLE_ROLE,
    Qt.ToolTipRole,
)


def _is_slider_delegate(delegate) -> bool:
    """Return True when ``delegate`` exposes the slider drag API.

    Uses duck typing instead of ``isinstance`` so that reloading the package
    (which recreates class objects) does not break the checks in the view mouse
    handlers.
    """
    return hasattr(delegate, "external_drag_start") and hasattr(delegate, "is_drag_active")


class SliderDragViewMixin:
    """Shared mouse handling for slider-style item views.

    The delegate owns value painting and the drag math; the view owns the Qt
    event flow. ``mousePressEvent`` resolves icon clicks first and otherwise
    asks the delegate to start a slider drag via ``external_drag_start``.

    Set ``_sliders_read_only = True`` to make the sliders display-only: icon
    clicks and name selection/drag still work, but value scrubbing is disabled.
    """

    _icon_click_active = False
    _sliders_read_only = False

    def _slider_delegate(self):
        if hasattr(self, "itemDelegateForColumn"):
            column_delegate = self.itemDelegateForColumn(0)
            if _is_slider_delegate(column_delegate):
                return column_delegate
        stored_delegate = getattr(self, "_slider_drag_delegate", None)
        if _is_slider_delegate(stored_delegate):
            return stored_delegate
        return self.itemDelegate()

    def _resolve_icon_click(self, event_pos):
        return None

    def _emit_icon_click(self, payload) -> None:
        signal, *args = payload
        signal.emit(*args)

    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.LeftButton:
            payload = self._resolve_icon_click(event.pos())
            if payload is not None:
                self._emit_icon_click(payload)
                self._icon_click_active = True
                event.accept()
                return

            delegate = self._slider_delegate()
            index = self.indexAt(event.pos())
            if (
                not self._sliders_read_only
                and _is_slider_delegate(delegate)
                and index.isValid()
                and not bool(index.data(ShapeItemsModel.IsHeaderRole))
                and bool(index.data(ShapeItemsModel.EditableRole))
                and delegate.external_drag_start(
                    self.model(), index, event.pos(), self.visualRect(index)
                )
            ):
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):  # noqa: N802
        delegate = self._slider_delegate()
        if _is_slider_delegate(delegate) and delegate.is_drag_active():
            if delegate.external_drag_move(event.pos().x()):
                event.accept()
                return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):  # noqa: N802
        if self._icon_click_active and event.button() == Qt.LeftButton:
            self._icon_click_active = False
            event.accept()
            return

        delegate = self._slider_delegate()
        if (
            _is_slider_delegate(delegate)
            and event.button() == Qt.LeftButton
            and delegate.is_drag_active()
        ):
            if delegate.external_drag_end(event.pos().x()):
                event.accept()
                return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):  # noqa: N802
        if event.button() == Qt.LeftButton and self._resolve_icon_click(event.pos()) is not None:
            self._icon_click_active = True
            event.accept()
            return
        if event.button() == Qt.LeftButton:
            delegate = self._slider_delegate()
            value_rect_for = getattr(delegate, "value_rect_for", None)
            index = self.indexAt(event.pos())
            if (
                _is_slider_delegate(delegate)
                and value_rect_for is not None
                and getattr(delegate, "_slider_value_edit_enabled", lambda: False)()
                and index.isValid()
                and not bool(index.data(ShapeItemsModel.IsHeaderRole))
                and bool(index.data(ShapeItemsModel.EditableRole))
            ):
                option = OptionRect(self.visualRect(index), self.fontMetrics())
                if value_rect_for(index, option).contains(event.pos()):
                    # Slider double-click enters "value set mode" and consumes the
                    # event so the view's doubleClicked/itemDoubleClicked pose or
                    # rename handlers do not also fire.
                    self.edit(index)
                    event.accept()
                    return
        super().mouseDoubleClickEvent(event)


class PrimaryDropListView(SliderDragViewMixin, QListView):
    """Drop-enabled list that accepts primaries dragged from the primaries tree."""
    DRAG_MIME_TYPE = SHAPE_NAMES_MIME_TYPE
    PRIMARY_TREE_MIME_TYPE = PRIMARY_TREE_MIME_TYPE
    _panel_icon_slots = 1
    _hides_mute_icon = True

    def __init__(self, drop_callback: Callable[[Sequence[str]], None], remove_callback: Optional[Callable[[Sequence[str]], None]] = None, parent=None) -> None:
        super().__init__(parent)
        self._drop_callback = drop_callback
        self._remove_callback = remove_callback
        self._icon_click_active = False
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DropOnly)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

    def _selected_shape_names(self) -> List[str]:
        model = self.model()
        selection_model = self.selectionModel()
        if model is None or selection_model is None:
            return []
        shape_names: List[str] = []
        for index in selection_model.selectedRows():
            if bool(model.data(index, ShapeItemsModel.IsHeaderRole)):
                continue
            shape_name = str(model.data(index, ShapeItemsModel.NameRole) or "")
            if shape_name:
                shape_names.append(shape_name)
        return shape_names

    def _show_context_menu(self, pos) -> None:
        if self.selectionModel() is not None:
            clicked_index = self.indexAt(pos)
            if clicked_index.isValid() and not self.selectionModel().isSelected(clicked_index):
                self.selectionModel().clearSelection()
                self.selectionModel().select(clicked_index, QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows)
                self.setCurrentIndex(clicked_index)

        selected_names = self._selected_shape_names()
        if not selected_names:
            return

        menu = QMenu(self)
        remove_action = menu.addAction("Remove Selected from Sliders Drop Box")
        if hasattr(menu, "exec"):
            selected_action = menu.exec(self.viewport().mapToGlobal(pos))
        else:
            selected_action = menu.exec_(self.viewport().mapToGlobal(pos))

        if selected_action == remove_action and self._remove_callback is not None:
            self._remove_callback(selected_names)

    def _shape_names_from_mime(self, mime_data: QMimeData) -> List[str]:
        if mime_data is None:
            return []
        raw_names: List[str] = []
        if mime_data.hasFormat(self.DRAG_MIME_TYPE):
            raw_payload = bytes(mime_data.data(self.DRAG_MIME_TYPE)).decode("utf-8", errors="ignore")
            raw_names.extend(raw_payload.splitlines())
        elif mime_data.hasText():
            raw_names.extend(str(mime_data.text() or "").splitlines())
        return [name.strip() for name in raw_names if name and name.strip()]

    def _can_accept_drop(self, mime_data: QMimeData) -> bool:
        if mime_data is None:
            return False
        if self._shape_names_from_mime(mime_data):
            return True
        return mime_data.hasFormat(self.PRIMARY_TREE_MIME_TYPE)

    def _resolve_mute_icon_click(self, event_pos) -> Optional[tuple]:
        delegate = self.itemDelegate()
        if not _is_slider_delegate(delegate):
            return None

        index = self.indexAt(event_pos)
        if not index.isValid():
            return None
        if bool(index.data(ShapeItemsModel.IsHeaderRole)):
            return None


        option = OptionRect()
        option.rect = self.visualRect(index)
        icon_rect = delegate._mute_icon_rect(option, index)
        if not icon_rect.contains(event_pos):
            return None

        shape_name = str(index.data(ShapeItemsModel.NameRole) or "")
        if not shape_name:
            return None

        current_muted = bool(index.data(ShapeItemsModel.MutedRole))
        return shape_name, (not current_muted)

    def _resolve_lock_icon_click(self, event_pos) -> Optional[tuple]:
        delegate = self.itemDelegate()
        if not _is_slider_delegate(delegate):
            return None

        index = self.indexAt(event_pos)
        if not index.isValid():
            return None
        if bool(index.data(ShapeItemsModel.IsHeaderRole)):
            return None


        option = OptionRect()
        option.rect = self.visualRect(index)
        icon_rect = delegate._lock_icon_rect(option, index)
        if icon_rect.isNull() or not icon_rect.contains(event_pos):
            return None

        shape_name = str(index.data(ShapeItemsModel.NameRole) or "")
        if not shape_name:
            return None

        current_locked = bool(index.data(ShapeItemsModel.LockedRole))
        return shape_name, (not current_locked)

    def _resolve_icon_click(self, event_pos):
        mute_payload = self._resolve_mute_icon_click(event_pos)
        if mute_payload is not None:
            shape_name, next_state = mute_payload
            return self.itemDelegate().muteToggleRequested, shape_name, next_state

        lock_payload = self._resolve_lock_icon_click(event_pos)
        if lock_payload is not None:
            shape_name, next_state = lock_payload
            return self.itemDelegate().lockToggleRequested, shape_name, next_state
        return None

    def dragEnterEvent(self, event):  # noqa: N802
        if self._can_accept_drop(event.mimeData()):
            event.acceptProposedAction()
            return
        event.ignore()

    def dragMoveEvent(self, event):  # noqa: N802
        if self._can_accept_drop(event.mimeData()):
            event.acceptProposedAction()
            return
        event.ignore()

    def dropEvent(self, event):  # noqa: N802
        if not self._can_accept_drop(event.mimeData()):
            event.ignore()
            return
        shape_names = self._shape_names_from_mime(event.mimeData())
        self._drop_callback(shape_names)
        event.acceptProposedAction()



class SplitMapWeightsList(SliderDragViewMixin, QListWidget):
    """Selectable edit-blendshape weight sliders."""



class SliderIconClickMixin:
    """Icon hit-testing shared by slider-style list and tree views.

    Resolves clicks on the connected-mesh, mute, lock, and work edit-mode
    icons and returns the delegate signal plus its arguments. Views that do
    not want this behavior override :meth:`_resolve_icon_click`.
    """

    def _resolve_mute_icon_click(self, event_pos) -> Optional[tuple]:
        """Return (shape_name, next_state) if event is on mute icon, else None."""
        delegate = self.itemDelegate()
        if not _is_slider_delegate(delegate):
            return None

        index = self.indexAt(event_pos)
        if not index.isValid():
            return None
        if bool(index.data(ShapeItemsModel.IsHeaderRole)):
            return None


        option = OptionRect()
        option.rect = self.visualRect(index)
        icon_rect = delegate._mute_icon_rect(option, index)
        if not icon_rect.contains(event_pos):
            return None

        shape_name = str(index.data(ShapeItemsModel.NameRole) or "")
        if not shape_name:
            return None

        current_muted = bool(index.data(ShapeItemsModel.MutedRole))
        return shape_name, (not current_muted)

    def _resolve_connected_mesh_icon_click(self, event_pos) -> Optional[str]:
        """Return shape name if event is on enabled connected-mesh icon, else None."""
        delegate = self.itemDelegate()
        if not _is_slider_delegate(delegate):
            return None

        index = self.indexAt(event_pos)
        if not index.isValid():
            return None
        if bool(index.data(ShapeItemsModel.IsHeaderRole)):
            return None


        option = OptionRect()
        option.rect = self.visualRect(index)
        icon_rect = delegate._connected_mesh_icon_rect(option, index)
        if icon_rect.isNull() or not icon_rect.contains(event_pos):
            return None

        if not bool(index.data(WorkShapeRoles.ConnectedRole)):
            return None

        shape_name = str(index.data(ShapeItemsModel.NameRole) or "")
        if not shape_name:
            return None
        return shape_name

    def _resolve_lock_icon_click(self, event_pos) -> Optional[tuple]:
        """Return (shape_name, next_state) if event is on lock icon, else None."""
        delegate = self.itemDelegate()
        if not _is_slider_delegate(delegate):
            return None

        index = self.indexAt(event_pos)
        if not index.isValid():
            return None
        if bool(index.data(ShapeItemsModel.IsHeaderRole)):
            return None


        option = OptionRect()
        option.rect = self.visualRect(index)
        icon_rect = delegate._lock_icon_rect(option, index)
        if icon_rect.isNull() or not icon_rect.contains(event_pos):
            return None

        shape_name = str(index.data(ShapeItemsModel.NameRole) or "")
        if not shape_name:
            return None

        current_locked = bool(index.data(ShapeItemsModel.LockedRole))
        return shape_name, (not current_locked)

    def _resolve_work_edit_mode_icon_click(self, event_pos) -> Optional[tuple]:
        """Return (shape_name, next_state) if event is on the edit-mode icon."""
        delegate = self.itemDelegate()
        if not _is_slider_delegate(delegate):
            return None

        index = self.indexAt(event_pos)
        if not index.isValid():
            return None
        if bool(index.data(ShapeItemsModel.IsHeaderRole)):
            return None


        option = OptionRect()
        option.rect = self.visualRect(index)
        icon_rect = delegate._edit_mode_icon_rect(option, index)
        if icon_rect.isNull() or not icon_rect.contains(event_pos):
            return None

        shape_name = str(index.data(ShapeItemsModel.NameRole) or "")
        if not shape_name:
            return None

        in_edit_mode = bool(index.data(WorkShapeRoles.InEditModeRole))
        return shape_name, (not in_edit_mode)

    def _resolve_icon_click(self, event_pos):
        delegate = self.itemDelegate()
        if not _is_slider_delegate(delegate):
            return None

        connected_shape_name = self._resolve_connected_mesh_icon_click(event_pos)
        if connected_shape_name is not None:
            return delegate.connectedMeshRequested, connected_shape_name

        mute_payload = self._resolve_mute_icon_click(event_pos)
        if mute_payload is not None:
            shape_name, next_state = mute_payload
            return delegate.muteToggleRequested, shape_name, next_state

        lock_payload = self._resolve_lock_icon_click(event_pos)
        if lock_payload is not None:
            shape_name, next_state = lock_payload
            return delegate.lockToggleRequested, shape_name, next_state

        edit_payload = self._resolve_work_edit_mode_icon_click(event_pos)
        if edit_payload is not None:
            shape_name, next_state = edit_payload
            return delegate.workEditModeToggleRequested, shape_name, next_state
        return None


class ReorderableTreeWidgetMixin:
    """Internal drag-reorder/group behavior shared by orderable trees.

    Concrete views declare their own ``...MoveRequested`` / ``groupRequested``
    signals and translate the mixin's abstract emitters, so the mixin stays
    independent of any particular tree widget and its signal names.
    """

    ORDER_MIME_TYPE = PRIMARY_ORDER_MIME_TYPE
    _enable_internal_reorder = False

    def _init_internal_reorder(self) -> None:
        """Initialise drop-indicator state and Qt drag/drop flags."""
        self._drop_target_item = None
        self._drop_position = ""
        if self._enable_internal_reorder:
            # Internal reordering is handled by the owning window through the
            # move-requested signal; Qt must not move the items itself.
            self.setDragEnabled(True)
            self.setAcceptDrops(True)
            self.setDragDropMode(QAbstractItemView.DragDrop)
            self.setDropIndicatorShown(True)
            self.setDefaultDropAction(Qt.MoveAction)

    def _emit_move_requested(self, names, target, position) -> None:
        """Emit the view's own move-requested signal."""
        raise NotImplementedError

    def _emit_group_requested(self) -> None:
        """Emit the view's own group-requested signal."""
        raise NotImplementedError

    def _selected_order_names(self) -> List[str]:
        """Return selected leaf/folder names for internal reordering."""
        return [self._item_name(item) for item in self.selectedItems() if self._item_name(item)]

    def startDrag(self, supportedActions):  # noqa: N802
        shape_names = self._selected_draggable_shape_names()
        order_names = self._selected_order_names() if self._enable_internal_reorder else []
        if not shape_names and not order_names:
            return
        mime_data = QMimeData()
        if shape_names:
            payload = "\n".join(shape_names).encode("utf-8")
            mime_data.setData(self.DRAG_MIME_TYPE, payload)
            mime_data.setText("\n".join(shape_names))
        if order_names:
            mime_data.setData(self.ORDER_MIME_TYPE, "\n".join(order_names).encode("utf-8"))
        drag = QDrag(self)
        drag.setMimeData(mime_data)
        drop_action = Qt.CopyAction if (supportedActions & Qt.CopyAction) else Qt.MoveAction
        if hasattr(drag, "exec"):
            drag.exec(drop_action)
        else:
            drag.exec_(drop_action)

    @staticmethod
    def _event_position(event):
        if hasattr(event, "position"):
            return event.position().toPoint()
        return event.pos()

    def _item_name(self, item) -> str:
        if item is None:
            return ""
        name = item.data(0, PRIMARY_TREE_NAME_ROLE)
        if not name:
            name = item.data(0, ShapeItemsModel.NameRole)
        return str(name or item.text(0) or "")

    def dragEnterEvent(self, event):  # noqa: N802
        if self._is_internal_order_event(event):
            event.acceptProposedAction()
            return
        event.ignore()

    def dragMoveEvent(self, event):  # noqa: N802
        if not self._is_internal_order_event(event):
            event.ignore()
            return
        item, position = self._internal_drop_target(self._event_position(event))
        if item is not self._drop_target_item or position != self._drop_position:
            self._drop_target_item = item
            self._drop_position = position
            self.viewport().update()
        event.acceptProposedAction()

    def dragLeaveEvent(self, event):  # noqa: N802
        self._clear_drop_indicator()
        super().dragLeaveEvent(event)

    def _is_internal_order_event(self, event) -> bool:
        return bool(
            self._enable_internal_reorder
            and event.source() is self
            and event.mimeData().hasFormat(self.ORDER_MIME_TYPE)
        )

    def _internal_drop_target(self, pos):
        """Resolve the internal drop target for ``pos``.

        Returns:
            tuple: ``(item, position)`` where ``position`` is ``before``,
                ``after`` or ``inside`` for an item target, or ``(None, "root")``
                when the pointer is over empty viewport space.
        """
        item = self.itemAt(pos)
        if item is None:
            return None, "root"
        rect = self.visualItemRect(item)
        ratio = (pos.y() - rect.top()) / max(1, rect.height())
        if bool(item.data(0, PRIMARY_TREE_FOLDER_ROLE)):
            # Only the middle band nests; the edges reorder as siblings so a
            # nested group can always be pulled back out of its parent.
            if ratio < 0.25:
                return item, "before"
            if ratio > 0.75:
                return item, "after"
            return item, "inside"
        return item, ("before" if ratio < 0.5 else "after")

    def _clear_drop_indicator(self) -> None:
        if self._drop_target_item is not None or self._drop_position:
            self._drop_target_item = None
            self._drop_position = ""
            self.viewport().update()

    def dropEvent(self, event):  # noqa: N802
        if not self._is_internal_order_event(event):
            event.ignore()
            return
        names = [
            name for name in bytes(event.mimeData().data(self.ORDER_MIME_TYPE))
            .decode("utf-8", errors="ignore").split("\n")
            if name.strip()
        ]
        item, position = self._internal_drop_target(self._event_position(event))
        self._clear_drop_indicator()
        if not names:
            event.ignore()
            return
        target = self._item_name(item) if item is not None else ""
        if position != "root" and not target:
            event.ignore()
            return
        self._emit_move_requested(names, target, position)
        event.acceptProposedAction()

    def paintEvent(self, event):  # noqa: N802
        super().paintEvent(event)
        item = self._drop_target_item
        if item is None:
            return
        rect = self.visualItemRect(item)
        if not rect.isValid():
            return
        painter = QPainter(self.viewport())
        try:
            accent = QColor(90, 160, 240)
            if self._drop_position == "inside":
                highlight = QColor(accent)
                highlight.setAlpha(55)
                painter.fillRect(rect, highlight)
                painter.setPen(accent)
                painter.drawRect(rect.adjusted(0, 0, -1, -1))
            else:
                line_top = rect.top() - 1 if self._drop_position == "before" else rect.bottom() - 1
                painter.fillRect(rect.left() + 1, line_top, max(1, rect.width() - 2), 3, accent)
        finally:
            painter.end()

    def _handle_group_shortcut(self, event) -> bool:
        """Handle Ctrl+G and emit the group request when pressed."""
        if event.key() == Qt.Key_G and (event.modifiers() & Qt.ControlModifier):
            self._emit_group_requested()
            event.accept()
            return True
        return False


class SliderListView(SliderIconClickMixin, SliderDragViewMixin, QListView):
    """QListView that forwards global drag move/release to `SliderItemDelegate`.

    Once drag starts in the slider area, updates continue from mouse x-delta even
    when the pointer leaves the original item rectangle.
    """
    DRAG_MIME_TYPE = SHAPE_NAMES_MIME_TYPE
    _panel_icon_slots = 2

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._icon_click_active = False
        self._slider_drag_delegate = None

    def setItemDelegate(self, delegate) -> None:  # noqa: N802
        self._slider_drag_delegate = delegate
        super().setItemDelegate(delegate)

    def _selected_draggable_shape_names(self) -> List[str]:
        model = self.model()
        selection_model = self.selectionModel()
        if model is None or selection_model is None:
            return []
        shape_names: List[str] = []
        for index in selection_model.selectedRows():
            if bool(model.data(index, ShapeItemsModel.IsHeaderRole)):
                continue
            shape_name = str(model.data(index, ShapeItemsModel.NameRole) or "")
            if not shape_name:
                continue
            shape_names.append(shape_name)
        return shape_names

    def startDrag(self, supportedActions):  # noqa: N802
        shape_names = self._selected_draggable_shape_names()
        if not shape_names:
            return
        mime_data = QMimeData()
        payload = "\n".join(shape_names).encode("utf-8")
        mime_data.setData(self.DRAG_MIME_TYPE, payload)
        mime_data.setText("\n".join(shape_names))
        drag = QDrag(self)
        drag.setMimeData(mime_data)
        drop_action = Qt.CopyAction if (supportedActions & Qt.CopyAction) else Qt.MoveAction
        if hasattr(drag, "exec"):
            drag.exec(drop_action)
        else:
            drag.exec_(drop_action)



class WorkShapesListView(ReorderableTreeWidgetMixin, SliderIconClickMixin, SliderDragViewMixin, QTreeWidget):
    """Work shapes tree with parent controls and collapsible, pose-activating drivers.

    Work shapes can be grouped and reordered; the order/grouping is persisted
    through the owning window (see ``FaceCtrlSortingStore``). Driver shapes are
    painted child rows of a work-shape leaf, not tree nodes.
    """

    DRAG_MIME_TYPE = SHAPE_NAMES_MIME_TYPE
    ORDER_MIME_TYPE = WORK_SHAPE_ORDER_MIME_TYPE
    driverPoseRequested = Signal(str)
    driverRemovalRequested = Signal(str, str)
    workShapeMoveRequested = Signal(object, str, str)
    groupRequested = Signal()
    renameGroupRequested = Signal(object)
    ungroupRequested = Signal()
    _enable_slider_value_edit = True
    _tree_view_layout = True
    _primary_tree_layout = False
    _shapes_tree_layout = False
    # Match the Primaries tree's per-level group/leaf indentation.
    _tree_indent = PRIMARY_TREE_INDENT
    _panel_icon_slots = 2
    _uses_native_branch_indicator = False
    _enable_internal_reorder = True

    def __init__(
        self,
        drop_callback: Callable[[str, str], None],
        duplicate_callback: Callable[[str], None],
        extract_work_shape_mesh_callback: Callable[[str], None],
        break_link_callback: Callable[[str], None],
        copy_weights_callback: Optional[Callable[[str], None]] = None,
        paste_weights_callback: Optional[Callable[[str], None]] = None,
        paste_inverted_weights_callback: Optional[Callable[[str], None]] = None,
        add_copied_weights_callback: Optional[Callable[[str], None]] = None,
        subtract_copied_weights_callback: Optional[Callable[[str], None]] = None,
        normalize_weights_callback: Optional[Callable[[Sequence[str]], None]] = None,
        clear_weights_callback: Optional[Callable[[str], None]] = None,
        can_paste_weights_callback: Optional[Callable[[], bool]] = None,
        can_extract_mesh_callback: Optional[Callable[[], bool]] = None,
        propagate_to_active_shapes_callback: Optional[Callable[[str], None]] = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._init_internal_reorder()
        # Slider double-clicks are the only path that opens the value editor;
        # name double-clicks keep their rename behavior.
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setColumnCount(1)
        self.setHeaderHidden(True)
        self.setIndentation(0)
        self.setRootIsDecorated(False)
        # Group disclosure is delegate-painted (see SliderItemDelegate.paint).
        # Hide Qt's native branch glyph so it cannot draw a second, barely
        # indented triangle next to the custom one.
        self.setIconSize(QSize(14, 14))
        self.setStyleSheet(
            """
            QTreeView::branch {
                image: none;
                border-image: none;
                width: 0px;
                height: 0px;
            }
            QTreeView::item {
                padding-top: 1px;
                padding-bottom: 1px;
            }
            """
        )
        self._collapsed_driver_names = set()
        self._driver_editor = None
        self._driver_press_active = False
        self._driver_drag_target = None
        self._driver_drag_start = None
        self._driver_drag_active = False
        self._driver_drag_outside = None
        self._driver_trash_cursor = None
        self._drop_callback = drop_callback
        self.duplicate_callback = duplicate_callback
        self.extract_work_shape_mesh_callback = extract_work_shape_mesh_callback
        self._break_link_callback = break_link_callback
        self._copy_weights_callback = copy_weights_callback
        self._paste_weights_callback = paste_weights_callback
        self._paste_inverted_weights_callback = paste_inverted_weights_callback
        self._add_copied_weights_callback = add_copied_weights_callback
        self._subtract_copied_weights_callback = subtract_copied_weights_callback
        self._normalize_weights_callback = normalize_weights_callback
        self._clear_weights_callback = clear_weights_callback
        self._can_paste_weights_callback = can_paste_weights_callback
        self._can_extract_mesh_callback = can_extract_mesh_callback
        self._propagate_to_active_shapes_callback = propagate_to_active_shapes_callback
        self.setToolTip(
            "<b>Work shapes:</b><br>"
            "<b>Double-click</b> a work shape to rename it.<br>"
            "<b>Double-click</b> a driver to set its pose.<br>"
            "<b>Drag</b> a work shape onto the middle of a group to nest it, its top/bottom "
            "edge to reorder, or empty space to move it to the top level.<br>"
            "<b>Drag outside</b> a driver row and release to remove that driver connection.<br>"
            "<b>Alt+left-click</b> a disclosure triangle to expand or collapse all work shapes.<br>"
            "<b>Ctrl+G</b> groups the selected work shapes."
        )
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)
        model = self.model()
        if model is not None:
            model.dataChanged.connect(self._driver_data_changed)
            model.modelAboutToBeReset.connect(self._cancel_driver_drag)

    def _emit_move_requested(self, names, target, position) -> None:
        self.workShapeMoveRequested.emit(names, target, position)

    def _emit_group_requested(self) -> None:
        self.groupRequested.emit()

    def _selected_draggable_shape_names(self) -> List[str]:
        # Work shapes are reordered internally; they are not dragged out as
        # shape names the way primaries are.
        return []

    def _iter_leaf_items(self):
        """Yield every work-shape leaf item depth first."""
        stack = [self.topLevelItem(i) for i in range(self.topLevelItemCount())]
        while stack:
            item = stack.pop()
            if item is None:
                continue
            if not bool(item.data(0, PRIMARY_TREE_FOLDER_ROLE)):
                yield item
            for i in range(item.childCount()):
                stack.append(item.child(i))

    def _sync_driver_expansion(self, editor=None) -> None:
        """Drop collapsed-driver names that no longer exist in the tree."""
        if editor is not None and editor is not self._driver_editor:
            self._collapsed_driver_names.clear()
            self._driver_editor = editor
        surviving_names = set()
        for item in self._iter_leaf_items():
            if item.data(0, WorkShapeRoles.DriverNamesRole):
                surviving_names.add(str(item.data(0, ShapeItemsModel.NameRole) or ""))
        self._collapsed_driver_names.intersection_update(surviving_names)


    def _driver_data_changed(self, first, last, roles=()) -> None:
        self._cancel_driver_drag()
        delegate = self.itemDelegate()
        if delegate is not None and first.isValid():
            delegate.sizeHintChanged.emit(first)
        self.viewport().update()

    def drivers_expanded(self, index) -> bool:
        return str(index.data(ShapeItemsModel.NameRole)) not in self._collapsed_driver_names

    def _toggle_drivers(self, index) -> None:
        name = str(index.data(ShapeItemsModel.NameRole))
        if self.drivers_expanded(index):
            self._collapsed_driver_names.add(name)
        else:
            self._collapsed_driver_names.discard(name)
        self.itemDelegate().sizeHintChanged.emit(index)
        self.viewport().update()

    def _set_all_drivers_expanded(self, expanded: bool) -> None:
        """Apply one driver-expansion state to every work shape with drivers.

        Parameters:
            expanded (bool): ``True`` to expand every driver list, ``False`` to
                collapse every driver list.

        Returns:
            None
        """
        delegate = self.itemDelegate()
        if expanded:
            self._collapsed_driver_names.clear()
        else:
            for item in self._iter_leaf_items():
                if item.data(0, WorkShapeRoles.DriverNamesRole):
                    self._collapsed_driver_names.add(str(item.data(0, ShapeItemsModel.NameRole) or ""))
        for item in self._iter_leaf_items():
            index = self.indexFromItem(item, 0)
            if delegate is not None and index.isValid():
                delegate.sizeHintChanged.emit(index)
        self.viewport().update()

    def keyPressEvent(self, event):  # noqa: N802
        if self._handle_group_shortcut(event):
            return
        super().keyPressEvent(event)


    def _work_shape_hit(self, pos):
        """Return (parent index, part, driver name) using delegate geometry."""
        index = self.indexAt(pos)
        if not index.isValid():
            return index, None, None
        delegate = self.itemDelegate()
        if not hasattr(delegate, "driver_at_pos"):
            return index, "parent", None
        option = OptionRect(self.visualRect(index), self.fontMetrics())
        folder_disclosure = getattr(delegate, "folder_disclosure_rect", None)
        if callable(folder_disclosure) and folder_disclosure(option, index).contains(pos):
            return index, "folder_disclosure", None
        if delegate.disclosure_rect(option, index).contains(pos):
            return index, "disclosure", None
        driver = delegate.driver_at_pos(option, index, pos)
        if driver is not None:
            return index, "driver", driver
        return index, "parent", None

    def _trash_cursor(self) -> QCursor:
        if self._driver_trash_cursor is None:
            # Draw a high-contrast bin rather than depending on a Maya resource
            # or a font glyph; both can be unavailable on some installations.
            dpr = self.devicePixelRatioF()
            pixmap = QPixmap(round(32 * dpr), round(32 * dpr))
            pixmap.setDevicePixelRatio(dpr)
            pixmap.fill(Qt.transparent)
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.Antialiasing, True)
            painter.setPen(QColor("black"))
            painter.setBrush(QColor(245, 245, 245))
            painter.drawRoundedRect(7, 10, 18, 19, 2, 2)
            painter.drawRect(12, 3, 8, 4)
            painter.drawRect(5, 7, 22, 3)
            for x in (12, 16, 20):
                painter.drawLine(x, 14, x, 25)
            painter.end()
            self._driver_trash_cursor = QCursor(pixmap, 16, 16)
        return self._driver_trash_cursor

    def _outside_driver_panel(self, global_pos) -> bool:
        # Include the list frame and scrollbars: these are not removal targets.
        return not self.rect().contains(self.mapFromGlobal(global_pos))

    def _move_driver_drag(self, global_pos) -> None:
        if not self._driver_drag_active:
            if (global_pos - self._driver_drag_start).manhattanLength() < QApplication.startDragDistance():
                return
            self._driver_drag_active = True
            QApplication.setOverrideCursor(Qt.ClosedHandCursor)
        outside = self._outside_driver_panel(global_pos)
        if outside != self._driver_drag_outside:
            cursor = self._trash_cursor() if outside else QCursor(Qt.ClosedHandCursor)
            QApplication.changeOverrideCursor(cursor)
            self._driver_drag_outside = outside

    def _cancel_driver_drag(self) -> None:
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
            if self._driver_drag_active:
                QApplication.restoreOverrideCursor()
        self._driver_drag_target = None
        self._driver_drag_start = None
        self._driver_drag_active = False
        self._driver_drag_outside = None

    def _finish_driver_drag(self, global_pos) -> None:
        target = self._driver_drag_target
        remove = self._driver_drag_active and self._outside_driver_panel(global_pos)
        # Restore the cursor/filter before emitting: the callback can reset the
        # model, raise an error, or close the editor. Never leave a trash cursor.
        self._cancel_driver_drag()
        self._driver_press_active = False
        if remove and target is not None:
            self.driverRemovalRequested.emit(*target)

    def eventFilter(self, watched, event):  # noqa: N802
        if getattr(self, "_driver_drag_target", None) is not None:
            event_type = event.type()
            if event_type == QEvent.MouseMove:
                self._move_driver_drag(event.globalPos())
                return True
            if event_type == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
                self._finish_driver_drag(event.globalPos())
                return True
            if event_type == QEvent.ShortcutOverride and event.key() == Qt.Key_Escape:
                event.accept()  # Keep Maya/global shortcuts from stealing cancellation.
                return True
            if event_type == QEvent.KeyPress and event.key() == Qt.Key_Escape:
                self._cancel_driver_drag()
                return True
            if event_type == QEvent.ApplicationDeactivate or (
                watched in (self, self.window())
                and event_type in (QEvent.Hide, QEvent.Close, QEvent.DeferredDelete, QEvent.WindowDeactivate)
            ):
                self._cancel_driver_drag()
        return super().eventFilter(watched, event)

    def mousePressEvent(self, event):  # noqa: N802
        self._cancel_driver_drag()
        self._driver_press_active = False
        index, part, driver = self._work_shape_hit(event.pos())
        if part == "folder_disclosure":
            # The group chevron is delegate-painted, so Qt's native branch no
            # longer toggles it; a single left-click on the triangle must.
            if event.button() == Qt.LeftButton and index.isValid():
                item = self.itemFromIndex(index)
                if item is not None:
                    item.setExpanded(not item.isExpanded())
            event.accept()
            return
        if part in {"driver", "disclosure"}:
            if (
                part == "disclosure"
                and event.button() == Qt.LeftButton
                and bool(event.modifiers() & Qt.AltModifier)
            ):
                self._set_all_drivers_expanded(not self.drivers_expanded(index))
                event.accept()
                return
            self._driver_press_active = True
            if event.button() == Qt.LeftButton:
                if part == "disclosure":
                    self._toggle_drivers(index)
                else:
                    self._driver_drag_target = (str(index.data(ShapeItemsModel.NameRole)), driver)
                    self._driver_drag_start = event.globalPos()
                    QApplication.instance().installEventFilter(self)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):  # noqa: N802
        # QListView can begin rubber-band selection even after a consumed press.
        if self._driver_press_active:
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):  # noqa: N802
        if self._driver_press_active:
            self._driver_press_active = False
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):  # noqa: N802
        self._cancel_driver_drag()
        _, part, driver = self._work_shape_hit(event.pos())
        if part in {"driver", "disclosure", "folder_disclosure"}:
            self._driver_press_active = True
            if event.button() == Qt.LeftButton and part == "driver":
                self.driverPoseRequested.emit(driver)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def _shape_names_from_mime(self, mime_data: QMimeData) -> List[str]:
        if mime_data is None:
            return []
        raw_names: List[str] = []
        if mime_data.hasFormat(self.DRAG_MIME_TYPE):
            raw_payload = bytes(mime_data.data(self.DRAG_MIME_TYPE)).decode("utf-8", errors="ignore")
            raw_names.extend(raw_payload.splitlines())
        elif mime_data.hasText():
            raw_names.extend(str(mime_data.text() or "").splitlines())
        return [name.strip() for name in raw_names if name and name.strip()]

    def _receiver_name_at_pos(self, pos) -> Optional[str]:
        index, part, _ = self._work_shape_hit(pos)
        if not index.isValid() or part != "parent":
            return None
        if bool(index.data(ShapeItemsModel.IsHeaderRole)):
            return None
        receiver = str(index.data(ShapeItemsModel.NameRole) or "")
        return receiver or None

    def dragEnterEvent(self, event):  # noqa: N802
        if self._is_internal_order_event(event):
            event.acceptProposedAction()
            return
        if self._shape_names_from_mime(event.mimeData()):
            event.acceptProposedAction()
            return
        event.ignore()

    def dragMoveEvent(self, event):  # noqa: N802
        if self._is_internal_order_event(event):
            pos = self._event_position(event)
            item, position = self._internal_drop_target(pos)
            if item is not self._drop_target_item or position != self._drop_position:
                self._drop_target_item = item
                self._drop_position = position
                self.viewport().update()
            event.acceptProposedAction()
            return
        if self._receiver_name_at_pos(self._event_position(event)) and self._shape_names_from_mime(event.mimeData()):
            event.acceptProposedAction()
            return
        event.ignore()

    def dropEvent(self, event):  # noqa: N802
        if self._is_internal_order_event(event):
            super().dropEvent(event)
            return
        receiver_name = self._receiver_name_at_pos(self._event_position(event))
        shape_names = self._shape_names_from_mime(event.mimeData())
        if not receiver_name or not shape_names:
            event.ignore()
            return
        self._drop_callback(receiver_name, shape_names[0])
        event.acceptProposedAction()

    def _show_context_menu(self, pos) -> None:
        item = self.itemAt(pos)
        if item is None:
            return
        if not item.isSelected():
            self.clearSelection()
            item.setSelected(True)
            self.setCurrentItem(item)

        if bool(item.data(0, PRIMARY_TREE_FOLDER_ROLE)):
            menu = QMenu(self)
            rename_group_action = menu.addAction("Rename Group")
            ungroup_action = menu.addAction("Ungroup")
            if hasattr(menu, "exec"):
                selected_action = menu.exec(self.viewport().mapToGlobal(pos))
            else:
                selected_action = menu.exec_(self.viewport().mapToGlobal(pos))
            if selected_action == rename_group_action:
                self.renameGroupRequested.emit(item)
            elif selected_action == ungroup_action:
                self.ungroupRequested.emit()
            return

        receiver_name = self._receiver_name_at_pos(pos)
        if not receiver_name:
            return
        selected_shape_names = [str(it.data(0, ShapeItemsModel.NameRole) or "")
                                for it in self.selectedItems()
                                if not bool(it.data(0, ShapeItemsModel.IsHeaderRole))]
        normalize_targets = selected_shape_names if receiver_name in selected_shape_names else [receiver_name]
        menu = QMenu(self)
        menu.setToolTipsVisible(True)
        group_action = menu.addAction("Group Selected")
        group_action.setShortcut("Ctrl+G")
        group_action.setToolTip("Group the selected work shapes (Ctrl+G)")
        menu.addSeparator()
        duplicate_action = menu.addAction(f"Duplicate")
        duplicate_action.setToolTip("Duplicate the selected shape")
        menu.addSeparator()
        propagate_to_active_shapes_action = menu.addAction("Propagate to Active Shapes")
        propagate_to_active_shapes_action.setToolTip("Propagate the selected shape down to all active shapes")
        propagate_to_active_shapes_action.setEnabled(self._propagate_to_active_shapes_callback is not None)
        extract_work_shape_mesh_action = menu.addAction("Extract Mesh")
        can_extract_mesh = self._can_extract_mesh_callback is None or self._can_extract_mesh_callback()
        extract_work_shape_mesh_action.setEnabled(can_extract_mesh)
        if can_extract_mesh:
            extract_work_shape_mesh_action.setToolTip("Extract the mesh of the selected work shape")
        if not can_extract_mesh:
            extract_work_shape_mesh_action.setToolTip("Extract Mesh is not supported on meshes with a skinCluster")
            menu.setToolTipsVisible(True)
        connections_menu = menu.addMenu("Connections")
        break_link_action = connections_menu.addAction("Break Link")

        weight_maps_menu = menu.addMenu("Weight Maps")
        copy_weights_action = weight_maps_menu.addAction("Copy")
        paste_weights_action = weight_maps_menu.addAction("Paste Weights")
        paste_inverted_weights_action = weight_maps_menu.addAction("Paste Inverted Weights")
        add_copied_weights_action = weight_maps_menu.addAction("Add Copied Weights")
        subtract_copied_weights_action = weight_maps_menu.addAction("Subtract Copied Weights")
        normalize_selected_weights_action = weight_maps_menu.addAction("Normalize Selected Weights")
        weight_maps_menu.addSeparator()
        clear_weights_action = weight_maps_menu.addAction("Clear Weights")

        can_paste_weights = True
        if self._can_paste_weights_callback is not None:
            can_paste_weights = bool(self._can_paste_weights_callback())
        paste_weights_action.setEnabled(can_paste_weights)
        paste_inverted_weights_action.setEnabled(can_paste_weights)
        add_copied_weights_action.setEnabled(can_paste_weights)
        subtract_copied_weights_action.setEnabled(can_paste_weights)
        normalize_selected_weights_action.setEnabled(bool(normalize_targets) and self._normalize_weights_callback is not None)
        clear_weights_action.setEnabled(self._clear_weights_callback is not None)

        if hasattr(menu, "exec"):
            selected_action = menu.exec(self.viewport().mapToGlobal(pos))
        else:
            selected_action = menu.exec_(self.viewport().mapToGlobal(pos))
        if selected_action == group_action:
            self.groupRequested.emit()
        elif selected_action == duplicate_action:
            self.duplicate_callback(receiver_name)
        elif selected_action == extract_work_shape_mesh_action:
            self.extract_work_shape_mesh_callback(receiver_name)
        elif selected_action == propagate_to_active_shapes_action and self._propagate_to_active_shapes_callback is not None:
            self._propagate_to_active_shapes_callback(receiver_name)
        elif selected_action == break_link_action:
            self._break_link_callback(receiver_name)
        elif selected_action == copy_weights_action and self._copy_weights_callback is not None:
            self._copy_weights_callback(receiver_name)
        elif selected_action == paste_weights_action and self._paste_weights_callback is not None:
            self._paste_weights_callback(receiver_name)
        elif selected_action == paste_inverted_weights_action and self._paste_inverted_weights_callback is not None:
            self._paste_inverted_weights_callback(receiver_name)
        elif selected_action == add_copied_weights_action and self._add_copied_weights_callback is not None:
            self._add_copied_weights_callback(receiver_name)
        elif selected_action == subtract_copied_weights_action and self._subtract_copied_weights_callback is not None:
            self._subtract_copied_weights_callback(receiver_name)
        elif selected_action == normalize_selected_weights_action and self._normalize_weights_callback is not None:
            self._normalize_weights_callback(normalize_targets)
        elif selected_action == clear_weights_action and self._clear_weights_callback is not None:
            self._clear_weights_callback(receiver_name)



class ShapeTreeWidget(SliderDragViewMixin, QTreeWidget):
    """Tree view for shapes that supports slider drag forwarding and shape drags."""

    DRAG_MIME_TYPE = SHAPE_NAMES_MIME_TYPE
    toggleUpstreamFilterRequested = Signal()
    pageNavigationPoseRequested = Signal(str)
    _tree_view_layout = True
    _shapes_tree_layout = True
    _panel_icon_slots = 2
    _uses_native_branch_indicator = False
    _enable_slider_value_edit = True

    def __init__(self, parent=None) -> None:
        """Create the shapes tree with slider-only value editing enabled.

        Parameters:
            parent (QWidget, optional): Parent widget.

        Returns:
            None
        """
        super().__init__(parent)
        # Slider double-clicks are the only path that opens the value editor;
        # name double-clicks keep their pose behavior.
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)

    def _resolve_icon_click(self, event_pos) -> Optional[tuple]:
        index = self.indexAt(event_pos)
        delegate = self.itemDelegateForColumn(0)
        if not index.isValid() or not _is_slider_delegate(delegate):
            return None
        if bool(index.data(ShapeItemsModel.IsHeaderRole)):
            return None


        option = OptionRect()
        option.rect = self.visualRect(index)
        mute_rect = delegate._mute_icon_rect(option, index)
        shape_name = str(index.data(ShapeItemsModel.NameRole) or "")
        if not shape_name:
            return None
        if mute_rect.contains(event_pos):
            current_muted = bool(index.data(ShapeItemsModel.MutedRole))
            return delegate.muteToggleRequested, shape_name, (not current_muted)

        lock_rect = delegate._lock_icon_rect(option, index)
        if not lock_rect.isNull() and lock_rect.contains(event_pos):
            current_locked = bool(index.data(ShapeItemsModel.LockedRole))
            return delegate.lockToggleRequested, shape_name, (not current_locked)
        return None

    def _selected_draggable_shape_names(self) -> List[str]:
        shape_names: List[str] = []
        for item in self.selectedItems():
            if bool(item.data(0, ShapeItemsModel.IsHeaderRole)):
                continue
            shape_name = str(item.data(0, ShapeItemsModel.NameRole) or "")
            if shape_name:
                shape_names.append(shape_name)
        return shape_names

    def _next_selectable_item(self, start_item: Optional[QTreeWidgetItem], direction: int) -> Optional[QTreeWidgetItem]:
        if start_item is None:
            return None
        candidate = self.itemBelow(start_item) if direction > 0 else self.itemAbove(start_item)
        while candidate is not None:
            if not bool(candidate.data(0, ShapeItemsModel.IsHeaderRole)):
                return candidate
            candidate = self.itemBelow(candidate) if direction > 0 else self.itemAbove(candidate)
        return None

    def _move_to_next_selectable_item(self, direction: int) -> bool:
        target_item = self._next_selectable_item(self.currentItem(), direction)
        if target_item is None:
            return False
        self.clearSelection()
        self.setCurrentItem(target_item)
        target_item.setSelected(True)
        self.scrollToItem(target_item, QAbstractItemView.EnsureVisible)
        return True

    def startDrag(self, supportedActions):  # noqa: N802
        shape_names = self._selected_draggable_shape_names()
        if not shape_names:
            return
        mime_data = QMimeData()
        payload = "\n".join(shape_names).encode("utf-8")
        mime_data.setData(self.DRAG_MIME_TYPE, payload)
        mime_data.setText("\n".join(shape_names))
        drag = QDrag(self)
        drag.setMimeData(mime_data)
        drop_action = Qt.CopyAction if (supportedActions & Qt.CopyAction) else Qt.MoveAction
        if hasattr(drag, "exec"):
            drag.exec(drop_action)
        else:
            drag.exec_(drop_action)

    def keyPressEvent(self, event):  # noqa: N802
        """Handle shape-row navigation shortcuts in the shapes panel."""
        if event.modifiers() == Qt.NoModifier:
            if event.key() == Qt.Key_Down and self._move_to_next_selectable_item(1):
                event.accept()
                return
            if event.key() == Qt.Key_Up and self._move_to_next_selectable_item(-1):
                event.accept()
                return
            if event.key() == Qt.Key_PageDown and self._move_to_next_selectable_item(1):
                shape_name = str(self.currentItem().data(0, ShapeItemsModel.NameRole) or "")
                if shape_name:
                    self.pageNavigationPoseRequested.emit(shape_name)
                event.accept()
                return
            if event.key() == Qt.Key_PageUp and self._move_to_next_selectable_item(-1):
                shape_name = str(self.currentItem().data(0, ShapeItemsModel.NameRole) or "")
                if shape_name:
                    self.pageNavigationPoseRequested.emit(shape_name)
                event.accept()
                return
        if event.key() == Qt.Key_F and event.modifiers() == Qt.NoModifier:
            target_item = self.currentItem()
            if target_item is None:
                selected_items = self.selectedItems()
                target_item = selected_items[0] if selected_items else None
            if target_item is not None:
                self.scrollToItem(target_item, QAbstractItemView.PositionAtCenter)
                event.accept()
                return
        super().keyPressEvent(event)




class PrimaryTreeWidget(ReorderableTreeWidgetMixin, SliderDragViewMixin, QTreeWidget):
    """Primary tree that mirrors the shapes tree: the delegate owns slider value
    drags and Qt owns name drags, so clicks and double-clicks reach the view."""

    DRAG_MIME_TYPE = SHAPE_NAMES_MIME_TYPE
    ORDER_MIME_TYPE = PRIMARY_ORDER_MIME_TYPE
    pageNavigationPoseRequested = Signal(str)
    primaryMoveRequested = Signal(object, str, str)
    groupRequested = Signal()
    _primary_tree_layout = True
    _tree_view_layout = True
    _shapes_tree_layout = False
    _tree_indent = PRIMARY_TREE_INDENT
    _panel_icon_slots = 0
    _uses_native_branch_indicator = False
    _enable_slider_value_edit = True
    _enable_internal_reorder = True

    def __init__(self, parent=None) -> None:
        """Create the primaries tree with slider-only value editing enabled.

        Parameters:
            parent (QWidget, optional): Parent widget.

        Returns:
            None
        """
        super().__init__(parent)
        self._init_internal_reorder()
        # Slider double-clicks are the only path that opens the value editor;
        # name double-clicks keep their pose behavior.
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)

    def _emit_move_requested(self, names, target, position) -> None:
        self.primaryMoveRequested.emit(names, target, position)

    def _emit_group_requested(self) -> None:
        self.groupRequested.emit()

    def _resolve_icon_click(self, event_pos) -> Optional[tuple]:
        index = self.indexAt(event_pos)
        delegate = self.itemDelegateForColumn(0)
        if not index.isValid() or not _is_slider_delegate(delegate):
            return None
        if bool(index.data(ShapeItemsModel.IsHeaderRole)):
            return None


        option = OptionRect()
        option.rect = self.visualRect(index)
        mute_rect = delegate._mute_icon_rect(option, index)
        shape_name = str(index.data(ShapeItemsModel.NameRole) or "")
        if not shape_name:
            return None
        if mute_rect.contains(event_pos):
            current_muted = bool(index.data(ShapeItemsModel.MutedRole))
            return delegate.muteToggleRequested, shape_name, (not current_muted)

        lock_rect = delegate._lock_icon_rect(option, index)
        if not lock_rect.isNull() and lock_rect.contains(event_pos):
            current_locked = bool(index.data(ShapeItemsModel.LockedRole))
            return delegate.lockToggleRequested, shape_name, (not current_locked)
        return None

    def _selected_draggable_shape_names(self) -> List[str]:
        shape_names: List[str] = []
        for item in self.selectedItems():
            if bool(item.data(0, ShapeItemsModel.IsHeaderRole)):
                continue
            shape_name = str(item.data(0, ShapeItemsModel.NameRole) or "")
            if shape_name:
                shape_names.append(shape_name)
        return shape_names

    def _next_selectable_item(self, start_item: Optional[QTreeWidgetItem], direction: int) -> Optional[QTreeWidgetItem]:
        if start_item is None:
            return None
        candidate = self.itemBelow(start_item) if direction > 0 else self.itemAbove(start_item)
        while candidate is not None:
            if not bool(candidate.data(0, ShapeItemsModel.IsHeaderRole)):
                return candidate
            candidate = self.itemBelow(candidate) if direction > 0 else self.itemAbove(candidate)
        return None

    def _move_to_next_selectable_item(self, direction: int) -> bool:
        target_item = self._next_selectable_item(self.currentItem(), direction)
        if target_item is None:
            return False
        self.clearSelection()
        self.setCurrentItem(target_item)
        target_item.setSelected(True)
        self.scrollToItem(target_item, QAbstractItemView.EnsureVisible)
        return True

    def keyPressEvent(self, event):  # noqa: N802
        if self._handle_group_shortcut(event):
            return
        if event.modifiers() == Qt.NoModifier:
            if event.key() == Qt.Key_Down and self._move_to_next_selectable_item(1):
                event.accept()
                return
            if event.key() == Qt.Key_Up and self._move_to_next_selectable_item(-1):
                event.accept()
                return
            if event.key() == Qt.Key_PageDown and self._move_to_next_selectable_item(1):
                shape_name = str(self.currentItem().data(0, ShapeItemsModel.NameRole) or "")
                if shape_name:
                    self.pageNavigationPoseRequested.emit(shape_name)
                event.accept()
                return
            if event.key() == Qt.Key_PageUp and self._move_to_next_selectable_item(-1):
                shape_name = str(self.currentItem().data(0, ShapeItemsModel.NameRole) or "")
                if shape_name:
                    self.pageNavigationPoseRequested.emit(shape_name)
                event.accept()
                return
        super().keyPressEvent(event)




class PrimaryDropTreeWidget(PrimaryTreeWidget):
    """Flat, drop-enabled primaries tree used by the Sliders Drop Box.

    Mirrors the primaries tree (so slider drags, selection, and keyboard
    navigation behave identically) but only ever shows top-level primary
    leaves. The owning window filters item visibility based on the current
    drop set, so this widget itself only owns the drop plumbing.
    """

    PRIMARY_TREE_MIME_TYPE = PRIMARY_TREE_MIME_TYPE
    _flat_mode = True
    _enable_internal_reorder = False

    def __init__(
        self,
        drop_callback: Callable[[Sequence[str]], None],
        remove_callback: Optional[Callable[[Sequence[str]], None]] = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._drop_callback = drop_callback
        self._remove_callback = remove_callback
        self._icon_click_active = False

        self.setColumnCount(1)
        self.setHeaderHidden(True)
        self.setIndentation(0)
        self.setRootIsDecorated(False)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setDragEnabled(False)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DropOnly)
        self.setDefaultDropAction(Qt.CopyAction)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

    def _selected_shape_names(self) -> List[str]:
        shape_names: List[str] = []
        for item in self.selectedItems():
            shape_name = str(item.data(0, ShapeItemsModel.NameRole) or "")
            if shape_name:
                shape_names.append(shape_name)
        return shape_names

    def _shape_names_from_mime(self, mime_data: QMimeData) -> List[str]:
        if mime_data is None:
            return []
        raw_names: List[str] = []
        if mime_data.hasFormat(self.DRAG_MIME_TYPE):
            raw_payload = bytes(mime_data.data(self.DRAG_MIME_TYPE)).decode("utf-8", errors="ignore")
            raw_names.extend(raw_payload.splitlines())
        elif mime_data.hasText():
            raw_names.extend(str(mime_data.text() or "").splitlines())
        return [name.strip() for name in raw_names if name and name.strip()]

    def _can_accept_drop(self, mime_data: QMimeData) -> bool:
        if mime_data is None:
            return False
        if self._shape_names_from_mime(mime_data):
            return True
        return mime_data.hasFormat(self.PRIMARY_TREE_MIME_TYPE)

    def _show_context_menu(self, pos) -> None:
        item = self.itemAt(pos)
        if item is not None and not item.isSelected():
            self.clearSelection()
            item.setSelected(True)
            self.setCurrentItem(item)

        selected_names = self._selected_shape_names()
        if not selected_names:
            return

        menu = QMenu(self)
        remove_action = menu.addAction("Remove Selected from Sliders Drop Box")
        if hasattr(menu, "exec"):
            selected_action = menu.exec(self.viewport().mapToGlobal(pos))
        else:
            selected_action = menu.exec_(self.viewport().mapToGlobal(pos))

        if selected_action == remove_action and self._remove_callback is not None:
            self._remove_callback(selected_names)

    def dragEnterEvent(self, event):  # noqa: N802
        if self._can_accept_drop(event.mimeData()):
            event.acceptProposedAction()
            return
        event.ignore()

    def dragMoveEvent(self, event):  # noqa: N802
        if self._can_accept_drop(event.mimeData()):
            event.acceptProposedAction()
            return
        event.ignore()

    def dropEvent(self, event):  # noqa: N802
        if not self._can_accept_drop(event.mimeData()):
            event.ignore()
            return
        shape_names = self._shape_names_from_mime(event.mimeData())
        self._drop_callback(shape_names)
        event.acceptProposedAction()



class PrimaryTreeItem(QTreeWidgetItem):
    """Tree item with name/value-aware sorting controlled by tree mode."""

    def __lt__(self, other):  # noqa: N802
        tree = self.treeWidget()
        if tree is None:
            return super().__lt__(other)
        sort_by_value = bool(getattr(tree, "_sort_by_value", False))
        if sort_by_value:
            left_value = float(self.data(0, PRIMARY_TREE_SORT_VALUE_ROLE) or 0.0)
            right_value = float(other.data(0, PRIMARY_TREE_SORT_VALUE_ROLE) or 0.0)
            if abs(left_value - right_value) > 1e-9:
                return left_value > right_value
            # stable tie-breaker by name
            return (self.text(0) or "").lower() < (other.text(0) or "").lower()
        return (self.text(0) or "").lower() < (other.text(0) or "").lower()


class SplitPrimaryAssignmentsView(SliderDragViewMixin, QTreeWidget):
    """Group primaries by split assignment and reassign them with drag and drop."""

    assignmentChanged = Signal(str, object)
    _primary_tree_layout = True
    _primary_slider_layout = False
    _uses_native_branch_indicator = False
    _enable_slider_value_edit = True

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        # Slider double-clicks are the only path that opens the value editor.
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._source_model = None
        self._assignments: Dict[str, str] = {}
        self._search_terms: List[str] = []
        self._drag_primary_names: List[str] = []
        self._pressed_primary_names: List[str] = []
        self.setColumnCount(1)
        self.setHeaderHidden(True)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDrop)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setDropIndicatorShown(True)
        self.setIndentation(0)
        self.setRootIsDecorated(False)
        self.setIconSize(QSize(14, 14))
        self.setStyleSheet(
            "QTreeView::branch { image: none; border-image: none; width: 0px; height: 0px; }"
            "QTreeView::item { padding-top: 2px; padding-bottom: 2px; }"
        )
        closed_icon = os.path.join(env.ENVIRONMENT.ICONS_PATH, "tree_chevron_right.svg")
        open_icon = os.path.join(env.ENVIRONMENT.ICONS_PATH, "tree_chevron_down.svg")
        self._closed_group_icon = QIcon(closed_icon) if os.path.exists(closed_icon) else QIcon()
        self._open_group_icon = QIcon(open_icon) if os.path.exists(open_icon) else QIcon()
        self.itemExpanded.connect(self._update_group_icon)
        self.itemCollapsed.connect(self._update_group_icon)

    def _update_group_icon(self, item: QTreeWidgetItem) -> None:
        item.setIcon(0, self._open_group_icon if item.isExpanded() else self._closed_group_icon)

    def set_source_model(self, source_model) -> None:
        self._source_model = source_model

    def primary_names(self) -> List[str]:
        if self._source_model is None:
            return []
        return [
            str(self._source_model.index(row, 0).data(PRIMARY_NAME_ROLE) or "")
            for row in range(self._source_model.rowCount())
            if self._source_model.index(row, 0).data(PRIMARY_TYPE_ROLE) == "PrimaryShape"
        ]

    def set_assignments(self, group_names: Sequence[str], assignments: Dict[str, str]) -> None:
        expanded_groups = {
            str(self.topLevelItem(row).data(0, Qt.UserRole) or "")
            for row in range(self.topLevelItemCount())
            if self.topLevelItem(row).isExpanded()
        }
        selected_names = {
            str(item.data(0, PRIMARY_NAME_ROLE) or "")
            for item in self.selectedItems()
            if item.parent() is not None
        }
        valid_groups = ["NoSplit"] + [str(name) for name in group_names]
        self._assignments = {
            str(name): str(group) if str(group) in valid_groups else "NoSplit"
            for name, group in assignments.items()
        }

        self.blockSignals(True)
        try:
            self.clear()
            groups = {}
            for group_name in valid_groups:
                group_item = QTreeWidgetItem([group_name])
                group_item.setData(0, Qt.UserRole, group_name)
                group_item.setData(0, PRIMARY_NAME_ROLE, group_name)
                group_item.setData(0, PRIMARY_TYPE_ROLE, "PrimaryFolder")
                group_item.setData(0, PRIMARY_VALUE_ROLE, 0.0)
                group_item.setData(0, PRIMARY_EDITABLE_ROLE, False)
                group_item.setData(0, PRIMARY_IS_HEADER_ROLE, True)
                group_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsDropEnabled)
                self.addTopLevelItem(group_item)
                groups[group_name] = group_item

            if self._source_model is not None:
                for row in range(self._source_model.rowCount()):
                    source_index = self._source_model.index(row, 0)
                    if source_index.data(PRIMARY_TYPE_ROLE) != "PrimaryShape":
                        continue
                    primary_name = str(source_index.data(PRIMARY_NAME_ROLE) or "")
                    if not primary_name:
                        continue
                    group_name = self._assignments.get(primary_name, "NoSplit")
                    item = QTreeWidgetItem([primary_name])
                    for role in PRIMARY_DATA_ROLES:
                        item.setData(0, role, source_index.data(role))
                    item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsDragEnabled | Qt.ItemIsEditable)
                    groups[group_name].addChild(item)
                    item.setSelected(primary_name in selected_names)

            for group_name, group_item in groups.items():
                group_item.sortChildren(0, Qt.AscendingOrder)
                group_item.setExpanded(not expanded_groups or group_name in expanded_groups)
                self._update_group_icon(group_item)
        finally:
            self.blockSignals(False)
        self.set_search_terms(self._search_terms)

    def sync_source_data(self, top_left, bottom_right, roles) -> None:
        if self._source_model is None:
            return
        roles_to_copy = list(roles or PRIMARY_DATA_ROLES)
        for source_row in range(top_left.row(), bottom_right.row() + 1):
            source_index = self._source_model.index(source_row, 0)
            primary_name = str(source_index.data(PRIMARY_NAME_ROLE) or "")
            if not primary_name:
                continue
            for group_row in range(self.topLevelItemCount()):
                group_item = self.topLevelItem(group_row)
                for child_row in range(group_item.childCount()):
                    item = group_item.child(child_row)
                    if str(item.data(0, PRIMARY_NAME_ROLE) or "") != primary_name:
                        continue
                    self.blockSignals(True)
                    try:
                        for role in roles_to_copy:
                            item.setData(0, role, source_index.data(role))
                    finally:
                        self.blockSignals(False)
                    break

    def set_search_terms(self, terms) -> None:
        if isinstance(terms, str):
            terms = [terms]
        self._search_terms = [
            str(term).strip().lower()
            for term in (terms or [])
            if str(term).strip()
        ]
        for row in range(self.topLevelItemCount()):
            group_item = self.topLevelItem(row)
            group_item.setHidden(False)
            for child_row in range(group_item.childCount()):
                child = group_item.child(child_row)
                name = str(child.data(0, PRIMARY_NAME_ROLE) or "").lower()
                visible = not self._search_terms or any(term in name for term in self._search_terms)
                child.setHidden(not visible)

    def set_search_text(self, text: str) -> None:
        self.set_search_terms([text])

    def startDrag(self, supported_actions) -> None:  # noqa: N802
        selected_names = list(dict.fromkeys(
            str(item.data(0, PRIMARY_NAME_ROLE) or "")
            for item in self.selectedItems()
            if item.parent() is not None and item.data(0, PRIMARY_NAME_ROLE)
        ))
        self._drag_primary_names = list(self._pressed_primary_names or selected_names)
        self._pressed_primary_names = []
        if not self._drag_primary_names:
            return
        mime_data = QMimeData()
        mime_data.setText("\n".join(self._drag_primary_names))
        drag = QDrag(self)
        drag.setMimeData(mime_data)
        if hasattr(drag, "exec"):
            drag.exec(Qt.MoveAction)
        else:
            drag.exec_(Qt.MoveAction)

    def _drop_group_name(self, pos) -> str:
        item = self.itemAt(pos)
        if item is None:
            return ""
        group_item = item if item.parent() is None else item.parent()
        return str(group_item.data(0, Qt.UserRole) or "")

    def dragEnterEvent(self, event):  # noqa: N802
        if self._drag_primary_names:
            event.acceptProposedAction()
            return
        event.ignore()

    def dragMoveEvent(self, event):  # noqa: N802
        if self._drag_primary_names and self._drop_group_name(event.pos()):
            event.acceptProposedAction()
            return
        event.ignore()

    def dropEvent(self, event):  # noqa: N802
        group_name = self._drop_group_name(event.pos())
        primary_names = list(self._drag_primary_names)
        self._drag_primary_names = []
        if not group_name or not primary_names:
            event.ignore()
            return
        self.assignmentChanged.emit(group_name, primary_names)
        event.acceptProposedAction()

    def mousePressEvent(self, event):  # noqa: N802
        self._pressed_primary_names = []
        if event.button() == Qt.LeftButton:
            item = self.itemAt(event.pos())
            if item is not None and item.parent() is None:
                item.setExpanded(not item.isExpanded())
                event.accept()
                return
            if item is not None and item.parent() is not None and item.isSelected():
                self._pressed_primary_names = [
                    str(selected.data(0, PRIMARY_NAME_ROLE) or "")
                    for selected in self.selectedItems()
                    if selected.parent() is not None and selected.data(0, PRIMARY_NAME_ROLE)
                ]
        super().mousePressEvent(event)
