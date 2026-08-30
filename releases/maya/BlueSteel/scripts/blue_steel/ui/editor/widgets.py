"""Standalone editor widgets: search bar, split-map trees, inline rename editor.

Extracted from the monolithic ``mainWindow`` module.

Example:
    >>> from blue_steel.ui.editor import widgets
    >>> search = widgets.TokenSearchBar("Filter...")
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence

from .constants import SPLIT_MAP_MIME_TYPE
from .qt import (
    QAbstractItemView,
    QColor,
    QCursor,
    QDrag,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMimeData,
    QPainter,
    QPushButton,
    QRect,
    QSizePolicy,
    QStyledItemDelegate,
    Qt,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
    Signal,
)



class TokenSearchBar(QWidget):
    """Search field that commits Enter-separated terms as removable tokens."""

    searchChanged = Signal(object)

    def __init__(self, placeholder: str = "", parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._tokens: List[str] = []
        self._token_widgets: Dict[str, QWidget] = {}
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(2)
        self._editor = QLineEdit(self)
        self._editor.setMinimumWidth(40)
        self._editor.setPlaceholderText(placeholder)
        self._layout.addWidget(self._editor, 1)
        self._token_container = QWidget(self)
        self._token_layout = QHBoxLayout(self._token_container)
        self._token_layout.setContentsMargins(0, 0, 0, 0)
        self._token_layout.setSpacing(2)
        self._token_layout.addStretch(1)
        self._token_container.setVisible(False)
        self._layout.addWidget(self._token_container)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setStyleSheet(
            "TokenSearchBar QLabel { border: 0px; background: transparent; }"
            "TokenSearchBar QPushButton { border: 0px; padding: 0px 1px; font-weight: bold; }"
        )
        self._editor.textChanged.connect(self._emit_search_changed)
        self._editor.returnPressed.connect(self._commit_editor_text)

    def setPlaceholderText(self, text: str) -> None:  # noqa: N802
        self._editor.setPlaceholderText(text)

    def text(self) -> str:
        return self._editor.text()

    def terms(self) -> List[str]:
        terms = list(self._tokens)
        draft = self._editor.text().strip()
        if draft:
            terms.append(draft)
        return terms

    def setText(self, text: str) -> None:  # noqa: N802
        for token in list(self._tokens):
            self._remove_token(token, emit=False)
        was_blocked = self._editor.blockSignals(True)
        try:
            self._editor.setText(text)
        finally:
            self._editor.blockSignals(was_blocked)
        self._emit_search_changed()

    def clear(self) -> None:
        for token in list(self._tokens):
            self._remove_token(token, emit=False)
        was_blocked = self._editor.blockSignals(True)
        try:
            self._editor.clear()
        finally:
            self._editor.blockSignals(was_blocked)
        self._emit_search_changed()

    def _commit_editor_text(self) -> None:
        term = self._editor.text().strip()
        if not term:
            return
        if term.lower() in {token.lower() for token in self._tokens}:
            was_blocked = self._editor.blockSignals(True)
            self._editor.clear()
            self._editor.blockSignals(was_blocked)
            self._emit_search_changed()
            return

        self._tokens.append(term)
        token_widget = QWidget(self._token_container)
        token_widget.setObjectName("searchToken")
        token_widget.setStyleSheet(
            "QWidget#searchToken { border: 1px solid #9a8eaa; border-radius: 6px; background-color: #746b82; }"
            "QWidget#searchToken QLabel { color: #f1edf4; font-weight: bold; }"
            "QWidget#searchToken QPushButton { color: #f1edf4; border-radius: 4px; }"
            "QWidget#searchToken QPushButton:hover { color: #ffffff; background-color: #5d536c; }"
        )
        token_layout = QHBoxLayout(token_widget)
        token_layout.setContentsMargins(2, 0, 1, 0)
        token_layout.setSpacing(1)
        token_layout.addWidget(QLabel(term, token_widget))
        remove_button = QPushButton("x", token_widget)
        remove_button.setFixedSize(16, 16)
        remove_button.setToolTip(f"Remove '{term}' filter")
        remove_button.clicked.connect(lambda _checked=False, token=term: self._remove_token(token))
        token_layout.addWidget(remove_button)
        self._token_widgets[term] = token_widget
        self._token_layout.insertWidget(self._token_layout.count() - 1, token_widget)
        self._token_container.setVisible(True)
        was_blocked = self._editor.blockSignals(True)
        self._editor.clear()
        self._editor.blockSignals(was_blocked)
        self._editor.setFocus()
        self._emit_search_changed()

    def _remove_token(self, token: str, emit: bool = True) -> None:
        if token not in self._tokens:
            return
        self._tokens.remove(token)
        widget = self._token_widgets.pop(token, None)
        if widget is not None:
            widget.deleteLater()
        self._token_container.setVisible(bool(self._tokens))
        if emit:
            self._emit_search_changed()

    def _emit_search_changed(self, *_args) -> None:
        self.searchChanged.emit(self.terms())



class SplitMapsTree(QTreeWidget):
    """Draggable split maps shown with normalization state and areas."""

    MIME_TYPE = SPLIT_MAP_MIME_TYPE
    MAP_NAME_ROLE = Qt.UserRole + 1
    STATUS_COLOR_ROLE = Qt.UserRole + 2
    NORMALIZED_COLOR = QColor("#4ba66d")
    NOT_NORMALIZED_COLOR = QColor("#d9534f")
    NOT_CHECKED_COLOR = QColor("#808080")
    EDITING_COLOR = QColor("#f39c12")

    currentMapChanged = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setColumnCount(3)
        self.setHeaderLabels(["", "Split Map", "Areas"])
        self.setRootIsDecorated(False)
        self.setIndentation(0)
        self.setUniformRowHeights(True)
        self.header().setSectionResizeMode(0, QHeaderView.Fixed)
        self.header().setSectionResizeMode(1, QHeaderView.Stretch)
        self.header().setSectionResizeMode(2, QHeaderView.Stretch)
        self.setColumnWidth(0, 28)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragOnly)
        self.currentItemChanged.connect(self._on_current_item_changed)

    def set_maps(
        self,
        map_weights: Dict[str, Sequence[str]],
        normalized_maps: Optional[Dict[str, bool]] = None,
        selected_map: str = "",
        editing_map: str = "",
    ) -> None:
        normalized_maps = normalized_maps or {}
        self.blockSignals(True)
        try:
            self.clear()
            selected_item = None
            for map_name in sorted(map_weights):
                areas = []
                for raw_weight_name in map_weights[map_name]:
                    area = str(raw_weight_name)
                    prefix = f"{map_name}_"
                    if area.startswith(prefix):
                        area = area[len(prefix):]
                    areas.append(area)
                is_editing = map_name == editing_map
                area_text = "[--EDIT MODE--]" if is_editing else f"[{', '.join(areas)}]"
                map_item = QTreeWidgetItem(["", map_name, area_text])
                map_item.setData(0, self.MAP_NAME_ROLE, map_name)
                map_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsDragEnabled)
                self.addTopLevelItem(map_item)
                if is_editing:
                    status_color = self.EDITING_COLOR
                    status_text = "Currently being edited"
                elif map_name not in normalized_maps:
                    status_color = self.NOT_CHECKED_COLOR
                    status_text = "Normalization not checked"
                elif normalized_maps[map_name]:
                    status_color = self.NORMALIZED_COLOR
                    status_text = "Normalized"
                else:
                    status_color = self.NOT_NORMALIZED_COLOR
                    status_text = "Not normalized"
                map_item.setData(0, self.STATUS_COLOR_ROLE, status_color)
                map_item.setToolTip(0, status_text)
                map_item.setToolTip(1, status_text)
                map_item.setToolTip(2, area_text)
                if map_name == selected_map:
                    selected_item = map_item
            if selected_item is None and self.topLevelItemCount():
                selected_item = self.topLevelItem(0)
            if selected_item is not None:
                self.setCurrentItem(selected_item)
        finally:
            self.blockSignals(False)
        if self.currentItem() is not None:
            self._on_current_item_changed(self.currentItem(), None)

    def map_name(self, item: Optional[QTreeWidgetItem] = None) -> str:
        item = item or self.currentItem()
        if item is None:
            return ""
        return str(item.data(0, self.MAP_NAME_ROLE) or "")

    def map_items(self) -> List[QTreeWidgetItem]:
        return [self.topLevelItem(row) for row in range(self.topLevelItemCount())]

    def find_map(self, map_name: str) -> Optional[QTreeWidgetItem]:
        for item in self.map_items():
            if self.map_name(item) == map_name:
                return item
        return None

    def _on_current_item_changed(self, current, _previous) -> None:
        self.currentMapChanged.emit(self.map_name(current))

    def startDrag(self, supported_actions) -> None:  # noqa: N802
        item = self.currentItem()
        if item is None or item.parent() is not None:
            return
        mime_data = QMimeData()
        mime_data.setData(self.MIME_TYPE, self.map_name(item).encode("utf-8"))
        drag = QDrag(self)
        drag.setMimeData(mime_data)
        if hasattr(drag, "exec"):
            drag.exec(Qt.CopyAction)
        else:
            drag.exec_(Qt.CopyAction)



class SplitMapStatusDelegate(QStyledItemDelegate):
    """Draw the split map normalization state as a colored square."""

    def paint(self, painter, option, index) -> None:  # noqa: N802
        super().paint(painter, option, index)
        if index.column() != 0:
            return
        status_color = index.data(SplitMapsTree.STATUS_COLOR_ROLE)
        if not isinstance(status_color, QColor):
            return
        square_size = min(12, option.rect.height() - 6)
        square_rect = QRect(
            option.rect.center().x() - square_size // 2,
            option.rect.center().y() - square_size // 2,
            square_size,
            square_size,
        )
        painter.save()
        painter.setPen(status_color.darker(150))
        painter.setBrush(status_color)
        painter.drawRect(square_rect)
        painter.restore()



class SplitGroupsTree(QTreeWidget):
    """Split groups with ordered split maps as draggable child items."""

    GROUP_NAME_ROLE = Qt.UserRole + 1
    MAP_NAME_ROLE = Qt.UserRole + 2

    mapSelected = Signal(str)
    mapsChanged = Signal(dict)
    mapDraggedOut = Signal(str, str)
    groupSelected = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setColumnCount(1)
        self.setHeaderHidden(True)
        self.setIndentation(14)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDrop)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setDropIndicatorShown(True)
        self.currentItemChanged.connect(self._on_current_item_changed)

    def set_groups(self, split_groups: Dict[str, Sequence[str]], selected_group: str = "") -> None:
        normalized_groups = {
            str(group_name): [str(split_map_name) for split_map_name in map_names]
            for group_name, map_names in split_groups.items()
        }
        expanded_groups = {
            self._group_name(self.topLevelItem(row))
            for row in range(self.topLevelItemCount())
            if self.topLevelItem(row).isExpanded()
        }
        self.blockSignals(True)
        try:
            self.clear()
            selected_item = None
            for group_name in sorted(normalized_groups):
                group_item = QTreeWidgetItem([group_name])
                group_item.setData(0, self.GROUP_NAME_ROLE, group_name)
                group_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsDropEnabled)
                self.addTopLevelItem(group_item)
                for split_map_name in normalized_groups[group_name]:
                    map_item = QTreeWidgetItem([str(split_map_name)])
                    map_item.setData(0, self.GROUP_NAME_ROLE, group_name)
                    map_item.setData(0, self.MAP_NAME_ROLE, str(split_map_name))
                    map_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsDragEnabled)
                    group_item.addChild(map_item)
                group_item.setExpanded(not expanded_groups or group_name in expanded_groups)
                if group_name == selected_group:
                    selected_item = group_item
            if selected_item is None and self.topLevelItemCount():
                selected_item = self.topLevelItem(0)
            if selected_item is not None:
                self.setCurrentItem(selected_item)
        finally:
            self.blockSignals(False)
        if self.currentItem() is not None:
            self._on_current_item_changed(self.currentItem(), None)

    def selected_group_name(self) -> str:
        return self._group_name(self.currentItem())

    def select_group(self, group_name: str) -> None:
        for row in range(self.topLevelItemCount()):
            item = self.topLevelItem(row)
            if self._group_name(item) == group_name:
                self.setCurrentItem(item)
                return

    def _group_name(self, item: Optional[QTreeWidgetItem]) -> str:
        if item is None:
            return ""
        return str(item.data(0, self.GROUP_NAME_ROLE) or "")

    def _map_names(self, group_item: QTreeWidgetItem) -> List[str]:
        return [
            str(group_item.child(row).data(0, self.MAP_NAME_ROLE) or "")
            for row in range(group_item.childCount())
        ]

    def groups(self) -> Dict[str, List[str]]:
        return {
            self._group_name(self.topLevelItem(row)): self._map_names(self.topLevelItem(row))
            for row in range(self.topLevelItemCount())
        }

    def _on_current_item_changed(self, current, _previous) -> None:
        self.groupSelected.emit(self._group_name(current))
        if current is not None and current.parent() is not None:
            self.mapSelected.emit(str(current.data(0, self.MAP_NAME_ROLE) or ""))

    @staticmethod
    def _event_position(event):
        if hasattr(event, "position"):
            return event.position().toPoint()
        return event.pos()

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.source() is self or event.mimeData().hasFormat(SplitMapsTree.MIME_TYPE):
            event.acceptProposedAction()
            return
        event.ignore()

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if event.source() is self or event.mimeData().hasFormat(SplitMapsTree.MIME_TYPE):
            event.acceptProposedAction()
            return
        event.ignore()

    def dropEvent(self, event) -> None:  # noqa: N802
        if not event.mimeData().hasFormat(SplitMapsTree.MIME_TYPE):
            event.ignore()
            return
        map_name = bytes(event.mimeData().data(SplitMapsTree.MIME_TYPE)).decode("utf-8")
        event_position = self._event_position(event)
        target_item = self.itemAt(event_position)
        target_group = target_item.parent() if target_item is not None and target_item.parent() is not None else target_item
        if not map_name or target_group is None:
            event.ignore()
            return

        source_item = self.currentItem() if event.source() is self else None
        source_group = source_item.parent() if source_item is not None else None
        if source_item is target_item:
            event.ignore()
            return
        if map_name in self._map_names(target_group) and source_group is not target_group:
            event.ignore()
            return

        new_row = target_group.childCount()
        if target_item is not None and target_item.parent() is target_group:
            new_row = target_group.indexOfChild(target_item)
            if event_position.y() >= self.visualItemRect(target_item).center().y():
                new_row += 1
        source_row = source_group.indexOfChild(source_item) if source_group is not None else -1
        if source_group is not None:
            source_group.takeChild(source_row)

        if source_group is target_group and source_row < new_row:
            new_row -= 1
        new_row = min(new_row, target_group.childCount())
        map_item = source_item or QTreeWidgetItem([map_name])
        map_item.setData(0, self.GROUP_NAME_ROLE, self._group_name(target_group))
        map_item.setData(0, self.MAP_NAME_ROLE, map_name)
        map_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsDragEnabled)
        target_group.insertChild(new_row, map_item)
        target_group.setExpanded(True)
        self.setCurrentItem(map_item)
        self.mapsChanged.emit(self.groups())
        event.setDropAction(Qt.MoveAction if source_group is not None else Qt.CopyAction)
        event.accept()
        return

    def startDrag(self, supported_actions) -> None:  # noqa: N802
        item = self.currentItem()
        if item is None or item.parent() is None:
            return
        map_name = str(item.data(0, self.MAP_NAME_ROLE) or "")
        group_name = self._group_name(item)
        mime_data = QMimeData()
        mime_data.setData(SplitMapsTree.MIME_TYPE, map_name.encode("utf-8"))
        drag = QDrag(self)
        drag.setMimeData(mime_data)
        if hasattr(drag, "exec"):
            result = drag.exec(Qt.MoveAction)
        else:
            result = drag.exec_(Qt.MoveAction)
        if result == Qt.IgnoreAction and not self.viewport().rect().contains(
            self.viewport().mapFromGlobal(QCursor.pos())
        ):
            self.mapDraggedOut.emit(group_name, map_name)



class InlineWorkshapeRenameEditor(QLineEdit):
    """Inline editor for workshape rename: Enter submits, Esc/focus-out cancels."""

    submitted = Signal()
    canceled = Signal()

    def keyPressEvent(self, event):  # noqa: N802
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.submitted.emit()
            event.accept()
            return
        if event.key() == Qt.Key_Escape:
            self.canceled.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def focusOutEvent(self, event):  # noqa: N802
        self.canceled.emit()
        super().focusOutEvent(event)



