"""Blue Steel Editor (Model/View rewrite).

This module provides a lean editor window that uses one shared source model for
all shapes and two proxy models for filtered views:

- Primaries view (editable slider values)
- Shapes view (same data source, filter-aware)

Example:
	>>> import blue_steel.ui.editor.mainWindowNew as mw
	>>> win = mw.show()
	>>> win.set_current_editor("characterA_blueSteel_container")
"""

from __future__ import annotations

from typing import Callable, Dict, List, Optional, Sequence, Set
import os
import sys
import traceback

import maya.OpenMayaUI as omui
from maya import cmds
from maya.app.general.mayaMixin import MayaQWidgetDockableMixin

from ... import env
from ...api.editor import BlueSteelEditor
from ...api.trackers import BlueSteelEditorsTracker, BlendShapeNodeTracker, ControllerTracker
from ...converters.simplex.ui.dialog import show_simplex_converter_dialog
from ...converters.simplex import commands as simplex_commands
from .controllerLayoutWindow import ControllerLayoutWindow
from .splitSettings import SplitPrimaryAssignmentsView
from ..common.frameLayout import FrameLayout
from ...api.mayaUtils import undoable
from ..common.icons import (
	ADD_ICON,
	COMMIT_ICON,
	DELETE_ICON,
	DOWN_ARROW_ICON,
	DUPLICATE_ICON,
	MMTOOLS_ICON,
	MUTE_ON_ICON,
	REFRESH_ICON,
	RENAME_ICON,
	MUTE_OFF_ICON,
	SELECT_ICON,
	UP_ARROW_ICON,
	ZERO_VALUE_ICON,
	AUTO_POSE_ICON,
	ADD_AT_POSE_ICON,
	ANALYZE_ICON,
	LOCK_ON_ICON,
	LOCK_OFF_ICON,
	HIGHLIGHT_ICON,
	HEAT_MAP_ICON,
	CONTROLLER_LAYOUT_ICON,
	CONNECTED_MESH_ENABLED_ICON,
	CONNECTED_MESH_DISABLED_ICON,
	COMPARE_MESH_ICON,
	HUD_ICON,
	NORMALIZE_ICON,
	MASK_ICON,
	EDIT_ICON,
	EDIT_SPLIT_MAP_ICON,
	COPY_WEIGHTS_ICON,
	PASTE_WEIGHTS_ICON,
	PASTE_INVERTED_WEIGHTS_ICON,
	PASTE_ADD_WEIGHTS_ICON,
	PASTE_MINUS_WEIGHTS_ICON,
	PASTE_MULTIPLY_WEIGHTS_ICON,
	SOFT_MOD_ICON,
	FILTER_ACTIVE_VALUES_ICON,


)
from ...mmtools import ui

WINDOW = None
SHOW_UPDATE_CHECK = True
if env.MAYA_VERSION > 2024:
	from PySide6.QtCore import QAbstractListModel, QModelIndex, QSortFilterProxyModel, Qt, QSize, Signal, QEvent, QRect, QPoint, QPersistentModelIndex, QTimer, QItemSelectionModel, QMimeData
	from PySide6.QtGui import QAction, QActionGroup, QColor, QCursor, QDoubleValidator, QIcon, QPainter, QPixmap, QPolygon, QDrag, QGuiApplication, QPalette
	from PySide6.QtWidgets import (
		QAbstractItemView,
		QCheckBox,
		QDialog,
		QDialogButtonBox,
		QMenu,
		QFileDialog,
		QGroupBox,
		QHBoxLayout,
		QHeaderView,
		QInputDialog,
		QLabel,
		QLayout,
		QLineEdit,
		QListView,
		QMenuBar,
		QMainWindow,
		QMessageBox,
		QPushButton,
		QSlider,
		QSizePolicy,
		QSplitter,
		QStatusBar,
		QStyledItemDelegate,
		QStyle,
		QTreeWidget,
		QTreeWidgetItem,
		QVBoxLayout,
		QWidget,
		QComboBox,
		QListWidget,
		QListWidgetItem,
		QTabWidget,
		QTableView,
	)
	from shiboken6 import wrapInstance
else:
	from PySide2.QtCore import QAbstractListModel, QModelIndex, QSortFilterProxyModel, Qt, QSize, Signal, QEvent, QRect, QPoint, QPersistentModelIndex, QTimer, QItemSelectionModel, QMimeData
	from PySide2.QtGui import QColor, QCursor, QDoubleValidator, QIcon, QPainter, QPixmap, QPolygon, QDrag, QGuiApplication, QPalette
	from PySide2.QtWidgets import (
		QAction,
		QActionGroup,
		QAbstractItemView,
		QCheckBox,
		QDialog,
		QDialogButtonBox,
		QMenu,
		QFileDialog,
		QGroupBox,
		QHBoxLayout,
		QHeaderView,
		QInputDialog,
		QLabel,
		QLayout,
		QLineEdit,
		QListView,
		QMenuBar,
		QMainWindow,
		QMessageBox,
		QPushButton,
		QSlider,
		QSizePolicy,
		QSplitter,
		QStatusBar,
		QStyledItemDelegate,
		QStyle,
		QTreeWidget,
		QTreeWidgetItem,
		QVBoxLayout,
		QWidget,
		QComboBox,
		QListWidget,
		QListWidgetItem,
		QTabWidget,
		QTableView,
	)
	from shiboken2 import wrapInstance


def get_maya_main_window() -> Optional[QWidget]:
	"""Return Maya's main window as QWidget.

	Example:
		>>> parent = get_maya_main_window()
		>>> win = MainWindow(parent=parent)
	"""
	main_window_ptr = omui.MQtUtil.mainWindow()
	if main_window_ptr is None:
		return None
	return wrapInstance(int(main_window_ptr), QWidget)


def _normalized_search_terms(terms) -> List[str]:
	if isinstance(terms, str):
		terms = [terms]
	return [str(term).strip().lower() for term in (terms or []) if str(term).strip()]


SHAPE_CUSTOM_COLORS = {
	"Red": "#e74c3c",
	"Blue": "#4a90d9",
	"Green": "#4ba66d",
	"Yellow": "#f1c40f",
	"Pink": "#e84393",
	"Purple": "#9b59b6",
}


def _color_swatch_icon(color_hex: str, size: int = 14) -> QIcon:
	"""Create a solid color swatch icon for a menu action."""
	pixmap = QPixmap(size, size)
	pixmap.fill(QColor(color_hex))
	return QIcon(pixmap)


def _shape_custom_color_to_qcolor(value) -> Optional[QColor]:
	"""Convert a stored custom color ("#RRGGBB" or legacy [R, G, B]) to a QColor."""
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

	MIME_TYPE = "application/x-blue-steel-split-map"
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


PRIMARY_TREE_SORT_VALUE_ROLE = Qt.UserRole + 905


class ShapeItemsModel(QAbstractListModel):
	"""Shared source model containing all shape rows for the active editor.

	Notes:
	- `PrimaryShape` rows are user-editable.
	- Non-primary rows are read-only in UI.

	Example:
		>>> model = ShapeItemsModel()
		>>> model.rebuild_from_editor(editor)
		>>> model.rowCount()
		124
	"""

	NameRole = Qt.UserRole + 1
	TypeRole = Qt.UserRole + 2
	ValueRole = Qt.UserRole + 3
	MutedRole = Qt.UserRole + 4
	LevelRole = Qt.UserRole + 5
	PrimariesRole = Qt.UserRole + 6
	EditableRole = Qt.UserRole + 7
	IsHeaderRole = Qt.UserRole + 8
	HeaderLevelRole = Qt.UserRole + 9
	HeaderCollapsedRole = Qt.UserRole + 10
	UpstreamRelatedRole = Qt.UserRole + 11
	DownstreamRelatedRole = Qt.UserRole + 12
	LockedRole = Qt.UserRole + 13
	LockIconVisibleRole = Qt.UserRole + 14
	ColorRole = Qt.UserRole + 15

	primaryValueCommitted = Signal(str, float)

	def __init__(self, parent: Optional[QWidget] = None):
		super().__init__(parent)
		self._editor: Optional[BlueSteelEditor] = None
		self._rows: List[dict] = []
		self._row_by_name: Dict[str, int] = {}
		self._upstream_related_names: Set[str] = set()
		self._downstream_related_names: Set[str] = set()

	def set_editor(self, editor: Optional[BlueSteelEditor]) -> None:
		"""Attach editor instance used for write operations."""
		self._editor = editor

	def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
		if parent.isValid():
			return 0
		return len(self._rows)

	def roleNames(self):  # noqa: N802
		return {
			self.NameRole: b"name",
			self.TypeRole: b"type",
			self.ValueRole: b"value",
			self.MutedRole: b"muted",
			self.LevelRole: b"level",
			self.PrimariesRole: b"primaries",
			self.EditableRole: b"editable",
			self.IsHeaderRole: b"isHeader",
			self.HeaderLevelRole: b"headerLevel",
			self.HeaderCollapsedRole: b"headerCollapsed",
			self.UpstreamRelatedRole: b"upstreamRelated",
			self.DownstreamRelatedRole: b"downstreamRelated",
			self.LockedRole: b"locked",
			self.LockIconVisibleRole: b"lockIconVisible",
			self.ColorRole: b"customColor",
		}

	def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
		if not index.isValid() or not (0 <= index.row() < len(self._rows)):
			return None

		row = self._rows[index.row()]
		if role in (Qt.DisplayRole, self.NameRole):
			return row["name"]
		if role == self.TypeRole:
			return row["type"]
		if role == self.ValueRole:
			return row["value"]
		if role == self.MutedRole:
			return row["muted"]
		if role == self.LevelRole:
			return row["level"]
		if role == self.PrimariesRole:
			return row["primaries"]
		if role == self.EditableRole:
			return row["editable"]
		if role == self.IsHeaderRole:
			return bool(row.get("is_header", False))
		if role == self.HeaderLevelRole:
			return int(row.get("header_level", row.get("level", 0)))
		if role == self.UpstreamRelatedRole:
			name = str(row.get("name", ""))
			return name in self._upstream_related_names
		if role == self.DownstreamRelatedRole:
			name = str(row.get("name", ""))
			return name in self._downstream_related_names
		if role == self.LockedRole:
			return bool(row.get("locked", False))
		if role == self.LockIconVisibleRole:
			return bool(row.get("lock_icon_visible", False))
		if role == self.ColorRole:
			return row.get("color", None)
		if role == Qt.ToolTipRole:
			return row.get("tooltip", None)
		return None

	def setData(self, index: QModelIndex, value, role: int = Qt.EditRole) -> bool:  # noqa: N802
		if not index.isValid() or not (0 <= index.row() < len(self._rows)):
			return False

		row = self._rows[index.row()]
		if role == Qt.ToolTipRole:
			row["tooltip"] = value
			self.dataChanged.emit(index, index, [Qt.ToolTipRole])
			return True

		if role not in (Qt.EditRole, self.ValueRole):
			return False
		if not row["editable"] or self._editor is None:
			return False

		try:
			new_value = float(value)
		except (TypeError, ValueError):
			return False

		new_value = max(0.0, min(1.0, round(new_value, 4)))
		if abs(new_value - row["value"]) <= 1e-6:
			return False

		try:
			self._editor.set_primary_shape_value(row["shape"], new_value)
		except Exception as exc:
			cmds.warning(f"Failed setting shape '{row['name']}': {exc}")
			return False

		row["value"] = new_value
		self.dataChanged.emit(index, index, [self.ValueRole, Qt.DisplayRole])
		self.primaryValueCommitted.emit(row["name"], new_value)
		return True

	def flags(self, index: QModelIndex):
		if not index.isValid():
			return Qt.NoItemFlags
		row = self._rows[index.row()]
		if bool(row.get("is_header", False)):
			return Qt.ItemIsEnabled | Qt.ItemIsSelectable
		flags = Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsDragEnabled
		if row["editable"]:
			flags |= Qt.ItemIsEditable
		return flags

	def rebuild_from_editor(self, editor: Optional[BlueSteelEditor]) -> None:
		"""Rebuild full rows from editor network and current blendshape values.

		Example:
			>>> model.rebuild_from_editor(editor)
			>>> names = [model.data(model.index(i, 0), model.NameRole) for i in range(model.rowCount())]
		"""
		self.beginResetModel()
		self._rows = []
		self._row_by_name = {}
		self._upstream_related_names.clear()
		self._downstream_related_names.clear()
		self._editor = editor

		if editor is None:
			self.endResetModel()
			return

		editor.sync_network()
		all_shapes = editor.get_all_shapes().sort_for_display()
		weights = editor.blendshape.get_weights() or set()
		weight_by_name = {str(weight): weight for weight in weights}
		locked_shape_names = {str(name) for name in (getattr(editor, "locked_shapes", set()) or set())}
		custom_colors = editor.read_custom_shapes_colors() or {}

		valid_shapes = [shape for shape in all_shapes if shape.type != "InvalidShape"]
		level_counts: Dict[int, int] = {}
		for shape in valid_shapes:
			level = int(shape.level)
			level_counts[level] = level_counts.get(level, 0) + 1

		current_level = None
		for shape in valid_shapes:
			level = int(shape.level)
			if current_level != level:
				header_name = f"Level {level} ({level_counts.get(level, 0)})"
				self._rows.append(
					{
						"name": header_name,
						"type": "LevelHeader",
						"value": 0.0,
						"muted": False,
						"level": level,
						"primaries": tuple(),
						"editable": False,
						"shape": None,
						"is_header": True,
						"header_level": level,
						"locked": False,
						"lock_icon_visible": False,
					}
				)
				current_level = level

			weight = weight_by_name.get(str(shape))
			value = editor.blendshape.get_weight_value(weight) if weight is not None else 0.0
			primaries = tuple(str(primary) for primary in shape.primaries)
			custom_color = custom_colors.get(str(shape))
			row_data = {
				"name": str(shape),
				"type": shape.type,
				"value": float(value),
				"muted": bool(getattr(shape, "muted", False)),
				"level": level,
				"primaries": primaries,
				"editable": shape.type == "PrimaryShape",
				"shape": shape,
				"is_header": False,
				"header_level": level,
				"locked": str(shape) in locked_shape_names,
				"lock_icon_visible": shape.type != "PrimaryShape",
				"color": _shape_custom_color_to_qcolor(custom_color),
			}
			self._row_by_name[row_data["name"]] = len(self._rows)
			self._rows.append(row_data)

		self.endResetModel()

	def set_related_shape_names(self, upstream_names: Sequence[str], downstream_names: Sequence[str]) -> None:
		"""Update related-shape highlight state and notify changed rows only."""
		new_upstream = {str(name) for name in (upstream_names or []) if name}
		new_downstream = {str(name) for name in (downstream_names or []) if name}

		if new_upstream == self._upstream_related_names and new_downstream == self._downstream_related_names:
			return

		changed_names = (
			self._upstream_related_names
			.union(self._downstream_related_names)
			.union(new_upstream)
			.union(new_downstream)
		)
		self._upstream_related_names = new_upstream
		self._downstream_related_names = new_downstream

		for shape_name in changed_names:
			row_index = self._row_by_name.get(shape_name)
			if row_index is None:
				continue
			model_index = self.index(row_index, 0)
			self.dataChanged.emit(
				model_index,
				model_index,
				[self.UpstreamRelatedRole, self.DownstreamRelatedRole, Qt.DisplayRole],
			)

	def get_name(self, source_row: int) -> Optional[str]:
		if 0 <= source_row < len(self._rows):
			return self._rows[source_row]["name"]
		return None

	def set_shape_value_from_tracker(self, shape_name: str, value: float) -> None:
		"""Fast-path value update from tracker signal without writing back to Maya."""
		row_index = self._row_by_name.get(shape_name)
		if row_index is None:
			return
		clamped_value = max(0.0, min(1.0, float(value)))
		row = self._rows[row_index]
		if abs(row["value"] - clamped_value) <= 1e-6:
			return
		row["value"] = clamped_value
		model_index = self.index(row_index, 0)
		self.dataChanged.emit(model_index, model_index, [self.ValueRole, Qt.DisplayRole])

	def set_shape_muted_state_local(self, shape_name: str, muted: bool) -> None:
		"""Update muted flag in-model without forcing a full rebuild."""
		row_index = self._row_by_name.get(shape_name)
		if row_index is None:
			return
		row = self._rows[row_index]
		target = bool(muted)
		if bool(row.get("muted", False)) == target:
			return
		row["muted"] = target
		model_index = self.index(row_index, 0)
		self.dataChanged.emit(model_index, model_index, [self.MutedRole, Qt.DisplayRole])

	def set_shape_locked_state_local(self, shape_name: str, locked: bool) -> None:
		"""Update locked flag in-model without forcing a full rebuild."""
		row_index = self._row_by_name.get(shape_name)
		if row_index is None:
			return
		row = self._rows[row_index]
		target = bool(locked)
		if bool(row.get("locked", False)) == target:
			return
		row["locked"] = target
		model_index = self.index(row_index, 0)
		self.dataChanged.emit(model_index, model_index, [self.LockedRole, Qt.DisplayRole])

	def set_shape_color_local(self, shape_name: str, color: Optional[QColor]) -> None:
		"""Update the custom text color in-model without forcing a full rebuild."""
		row_index = self._row_by_name.get(shape_name)
		if row_index is None:
			return
		row = self._rows[row_index]
		row["color"] = color
		model_index = self.index(row_index, 0)
		self.dataChanged.emit(model_index, model_index, [self.ColorRole, Qt.DisplayRole])

	def refresh_locked_states_from_editor(self) -> int:
		"""Sync lock flags for all non-header rows from editor lock state."""
		if self._editor is None:
			return 0

		locked_names = {str(name) for name in (getattr(self._editor, "locked_shapes", set()) or set())}
		changed_count = 0
		for row_index, row in enumerate(self._rows):
			if bool(row.get("is_header", False)):
				continue
			shape_name = str(row.get("name", ""))
			target = shape_name in locked_names
			if bool(row.get("locked", False)) == target:
				continue
			row["locked"] = target
			model_index = self.index(row_index, 0)
			self.dataChanged.emit(model_index, model_index, [self.LockedRole, Qt.DisplayRole])
			changed_count += 1

		return changed_count

	def get_shape_value(self, shape_name: str) -> Optional[float]:
		row_index = self._row_by_name.get(shape_name)
		if row_index is None:
			return None
		return float(self._rows[row_index].get("value", 0.0))

	def set_shape_value_by_name(self, shape_name: str, value: float) -> bool:
		row_index = self._row_by_name.get(shape_name)
		if row_index is None:
			return False
		return self.setData(self.index(row_index, 0), value, self.ValueRole)

	def refresh_values_from_editor(self) -> List[tuple]:
		"""Pull current blendshape values and update rows without rebuilding structure.

		Returns a list of changed rows as tuples: (name, value, is_primary).
		"""
		if self._editor is None:
			return []

		weights = self._editor.blendshape.get_weights() or set()
		weight_by_name = {str(weight): weight for weight in weights}
		changed: List[tuple] = []

		for row_index, row in enumerate(self._rows):
			if bool(row.get("is_header", False)):
				continue
			weight = weight_by_name.get(row.get("name", ""))
			new_value = self._editor.blendshape.get_weight_value(weight) if weight is not None else 0.0
			clamped_value = max(0.0, min(1.0, float(new_value)))
			if abs(float(row.get("value", 0.0)) - clamped_value) <= 1e-6:
				continue
			row["value"] = clamped_value
			changed.append((row_index, str(row.get("name", "")), clamped_value, bool(row.get("editable", False))))

		if changed:
			# One range emit so handlers process the whole batch once.
			self.dataChanged.emit(
				self.index(changed[0][0], 0),
				self.index(changed[-1][0], 0),
				[self.ValueRole, Qt.DisplayRole],
			)

		return [(name, value, is_primary) for _row, name, value, is_primary in changed]


class PrimaryShapesProxyModel(QSortFilterProxyModel):
	"""Proxy model for primary-only listing with text filtering."""

	def __init__(self, parent: Optional[QWidget] = None):
		super().__init__(parent)
		self._search_terms: List[str] = []
		self.setDynamicSortFilter(False)

	def set_search_terms(self, terms) -> None:
		self._search_terms = _normalized_search_terms(terms)
		self.invalidateFilter()

	def set_search_text(self, text: str) -> None:
		self.set_search_terms([text])

	def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:  # noqa: N802
		model = self.sourceModel()
		if model is None:
			return False
		index = model.index(source_row, 0, source_parent)
		shape_type = model.data(index, ShapeItemsModel.TypeRole)
		if shape_type != "PrimaryShape":
			return False
		if not self._search_terms:
			return True
		name = (model.data(index, ShapeItemsModel.NameRole) or "").lower()
		return any(term in name for term in self._search_terms)


class ShapesFilterProxyModel(QSortFilterProxyModel):
	"""Proxy model for shapes list with text and selected-primary filtering.

	Example:
		>>> proxy.set_selected_primaries({"jawOpen", "lipCornerPuller"})
		>>> proxy.set_search_text("lip")
	"""

	def __init__(self, parent: Optional[QWidget] = None):
		super().__init__(parent)
		self._search_terms: List[str] = []
		self._selected_primaries: Set[str] = set()
		self._visible_names: Optional[Set[str]] = None
		self._active_only = False
		self._collapsed_levels: Set[int] = set()
		self._color_filter_hexes: Optional[Set[str]] = None
		self._color_filter_include_no_color = False
		self._color_filter_enabled = False
		self._sort_order = Qt.AscendingOrder
		self._level_visible_count_cache: Dict[int, int] = {}
		self._with_value_epsilon = 1e-6
		self._filter_invalidate_timer = QTimer(self)
		self._filter_invalidate_timer.setSingleShot(True)
		self._filter_invalidate_timer.setInterval(33)
		self._filter_invalidate_timer.timeout.connect(self.invalidateFilter)
		self.setDynamicSortFilter(False)

	def setSourceModel(self, sourceModel) -> None:  # noqa: N802
		old_model = self.sourceModel()
		if old_model is not None:
			try:
				old_model.modelReset.disconnect(self._invalidate_level_count_cache)
				old_model.rowsInserted.disconnect(self._invalidate_level_count_cache)
				old_model.rowsRemoved.disconnect(self._invalidate_level_count_cache)
				old_model.layoutChanged.disconnect(self._invalidate_level_count_cache)
				old_model.dataChanged.disconnect(self._on_source_data_changed)
			except Exception:
				pass

		super().setSourceModel(sourceModel)
		self._invalidate_level_count_cache()

		new_model = self.sourceModel()
		if new_model is not None:
			new_model.modelReset.connect(self._invalidate_level_count_cache)
			new_model.rowsInserted.connect(self._invalidate_level_count_cache)
			new_model.rowsRemoved.connect(self._invalidate_level_count_cache)
			new_model.layoutChanged.connect(self._invalidate_level_count_cache)
			new_model.dataChanged.connect(self._on_source_data_changed)

	def _invalidate_level_count_cache(self, *_args) -> None:
		self._level_visible_count_cache.clear()

	def _on_source_data_changed(self, _top_left, _bottom_right, roles) -> None:
		self._invalidate_level_count_cache()
		# Re-filter only for proxies where row visibility depends on values.
		# This is mainly the active-only panel; throttle to keep slider drags smooth.
		if self._color_filter_enabled and (
			(not roles) or (ShapeItemsModel.ColorRole in roles) or (Qt.DisplayRole in roles)
		):
			self._filter_invalidate_timer.start()
			return
		if not self._active_only:
			return
		if (not roles) or (ShapeItemsModel.ValueRole in roles) or (Qt.DisplayRole in roles):
			self._filter_invalidate_timer.start()

	def _is_value_sort_mode(self) -> bool:
		return self.sortRole() == ShapeItemsModel.ValueRole

	def _is_with_value_shape(self, model, index: QModelIndex) -> bool:
		if not index.isValid() or bool(model.data(index, ShapeItemsModel.IsHeaderRole)):
			return False
		value = float(model.data(index, ShapeItemsModel.ValueRole) or 0.0)
		return value > self._with_value_epsilon

	def _with_value_header_source_index(self, model) -> QModelIndex:
		for row in range(model.rowCount()):
			idx = model.index(row, 0)
			if bool(model.data(idx, ShapeItemsModel.IsHeaderRole)):
				return idx
		return QModelIndex()

	def _has_visible_with_value_shapes(self, model) -> bool:
		for row in range(model.rowCount()):
			idx = model.index(row, 0)
			if not self._shape_row_matches_filters(model, idx):
				continue
			if self._is_with_value_shape(model, idx):
				return True
		return False

	def sort(self, column: int, order: Qt.SortOrder = Qt.AscendingOrder) -> None:  # noqa: N802
		"""Track requested sort order while keeping header pinning deterministic."""
		self._sort_order = order
		# Run proxy sort in ascending mode; lessThan applies requested direction.
		super().sort(column, Qt.AscendingOrder)

	def set_search_terms(self, terms) -> None:
		self._search_terms = _normalized_search_terms(terms)
		self._invalidate_level_count_cache()
		self.invalidateFilter()

	def set_search_text(self, text: str) -> None:
		self.set_search_terms([text])

	def set_selected_primaries(self, primary_names: Sequence[str]) -> None:
		self._selected_primaries = set(primary_names)
		self._invalidate_level_count_cache()
		self.invalidateFilter()

	def set_visible_names(self, shape_names: Optional[Sequence[str]]) -> None:
		if shape_names is None:
			self._visible_names = None
		else:
			self._visible_names = set(str(name) for name in shape_names)
		self._invalidate_level_count_cache()
		self.invalidateFilter()

	def set_active_only(self, active_only: bool) -> None:
		self._active_only = bool(active_only)
		self._invalidate_level_count_cache()
		self.invalidateFilter()

	def set_color_filter(self, color_hexes: Optional[Set[str]], include_no_color: bool = False) -> None:
		"""Filter rows by custom shape colors; pass color_hexes=None to disable."""
		if color_hexes is None:
			self._color_filter_enabled = False
			self._color_filter_hexes = None
			self._color_filter_include_no_color = False
		else:
			self._color_filter_enabled = True
			self._color_filter_hexes = {QColor(str(color_hex)).name() for color_hex in color_hexes}
			self._color_filter_include_no_color = bool(include_no_color)
		self._invalidate_level_count_cache()
		self.invalidateFilter()

	def color_filter_active(self) -> bool:
		return self._color_filter_enabled

	def toggle_level_collapsed(self, level: int) -> None:
		level = int(level)
		if level in self._collapsed_levels:
			self._collapsed_levels.remove(level)
		else:
			self._collapsed_levels.add(level)
		self.invalidateFilter()

	def _shape_row_matches_filters(self, model, index: QModelIndex) -> bool:
		"""Return True when a non-header row matches search/primary filters."""
		if not index.isValid():
			return False
		if bool(model.data(index, ShapeItemsModel.IsHeaderRole)):
			return False

		name = model.data(index, ShapeItemsModel.NameRole) or ""
		if self._visible_names is not None and name not in self._visible_names:
			return False
		if self._search_terms and not any(term in name.lower() for term in self._search_terms):
			return False
		if self._active_only:
			value = float(model.data(index, ShapeItemsModel.ValueRole) or 0.0)
			if value <= self._with_value_epsilon:
				return False
		if self._color_filter_enabled:
			row_color = model.data(index, ShapeItemsModel.ColorRole)
			if isinstance(row_color, QColor) and row_color.isValid():
				if row_color.name() not in (self._color_filter_hexes or set()):
					return False
			elif not self._color_filter_include_no_color:
				return False

		if not self._selected_primaries:
			return True

		primaries = model.data(index, ShapeItemsModel.PrimariesRole) or tuple()
		return bool(self._selected_primaries.intersection(set(primaries)))

	def _count_visible_shapes_for_level(self, model, level: int) -> int:
		"""Count rows matching active filters for one level (ignores collapse state)."""
		cache_key = (level, self._is_value_sort_mode())
		cached = self._level_visible_count_cache.get(cache_key)
		if cached is not None:
			return cached

		count = 0
		for row in range(model.rowCount()):
			idx = model.index(row, 0)
			row_level = int(model.data(idx, ShapeItemsModel.LevelRole) or 0)
			if row_level != level:
				continue
			if not self._shape_row_matches_filters(model, idx):
				continue
			# In value-sort mode, rows with active values are moved to the top
			# "With Value" section and should not be counted under level headers.
			if self._is_value_sort_mode() and self._is_with_value_shape(model, idx):
				continue
			count += 1
		self._level_visible_count_cache[cache_key] = count
		return count

	def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:  # noqa: N802
		model = self.sourceModel()
		if model is None:
			return False
		index = model.index(source_row, 0, source_parent)

		is_header = bool(model.data(index, ShapeItemsModel.IsHeaderRole))
		level = int(model.data(index, ShapeItemsModel.LevelRole) or 0)
		is_value_sort = self._is_value_sort_mode()
		if is_header:
			if is_value_sort and index == self._with_value_header_source_index(model):
				return self._has_visible_with_value_shapes(model)
			return self._count_visible_shapes_for_level(model, level) > 0
		if is_value_sort and self._is_with_value_shape(model, index):
			return self._shape_row_matches_filters(model, index)
		if level in self._collapsed_levels:
			return False
		return self._shape_row_matches_filters(model, index)

	def data(self, index: QModelIndex, role: int = Qt.DisplayRole):  # noqa: N802
		if not index.isValid():
			return super().data(index, role)

		source_index = self.mapToSource(index)
		if not source_index.isValid():
			return super().data(index, role)

		if bool(source_index.data(ShapeItemsModel.IsHeaderRole)):
			level = int(source_index.data(ShapeItemsModel.LevelRole) or 0)
			is_with_value_header = (
				self._is_value_sort_mode()
				and source_index == self._with_value_header_source_index(self.sourceModel())
			)
			if role in (Qt.DisplayRole, ShapeItemsModel.NameRole):
				if is_with_value_header:
					count = 0
					for row in range(self.sourceModel().rowCount()):
						idx = self.sourceModel().index(row, 0)
						if self._shape_row_matches_filters(self.sourceModel(), idx) and self._is_with_value_shape(self.sourceModel(), idx):
							count += 1
					return f"With Value ({count})"
				count = self._count_visible_shapes_for_level(self.sourceModel(), level)
				return f"Level {level} ({count})"
			if role == ShapeItemsModel.HeaderCollapsedRole:
				if is_with_value_header:
					return False
				return level in self._collapsed_levels

		if role == ShapeItemsModel.HeaderCollapsedRole and index.isValid():
			source_index = self.mapToSource(index)
			if source_index.isValid() and bool(source_index.data(ShapeItemsModel.IsHeaderRole)):
				level = int(source_index.data(ShapeItemsModel.LevelRole) or 0)
				return level in self._collapsed_levels
		return super().data(index, role)

	def lessThan(self, left: QModelIndex, right: QModelIndex) -> bool:  # noqa: N802
		model = self.sourceModel()
		if model is None:
			return False

		if self._is_value_sort_mode():
			ascending = self._sort_order == Qt.AscendingOrder
			with_value_header = self._with_value_header_source_index(model)

			def value_sort_rank(index: QModelIndex):
				is_header = bool(model.data(index, ShapeItemsModel.IsHeaderRole))
				level = int(model.data(index, ShapeItemsModel.LevelRole) or 0)
				name = (model.data(index, ShapeItemsModel.NameRole) or "").lower()
				value = float(model.data(index, ShapeItemsModel.ValueRole) or 0.0)
				if is_header and index == with_value_header:
					return (0, 0, 0, "")
				if self._is_with_value_shape(model, index):
					# Inside "With Value": level first, then value.
					value_key = value if ascending else -value
					return (1, level, value_key, name)
				if is_header:
					return (2, level, 0, "")
				# Non-valued shapes remain under normal level headers.
				return (3, level, 0, name)

			left_rank = value_sort_rank(left)
			right_rank = value_sort_rank(right)
			if left_rank == right_rank:
				return False
			return left_rank < right_rank

		left_level = int(model.data(left, ShapeItemsModel.LevelRole) or 0)
		right_level = int(model.data(right, ShapeItemsModel.LevelRole) or 0)
		if left_level != right_level:
			return left_level < right_level

		left_is_header = bool(model.data(left, ShapeItemsModel.IsHeaderRole))
		right_is_header = bool(model.data(right, ShapeItemsModel.IsHeaderRole))
		if left_is_header != right_is_header:
			return left_is_header
		if left_is_header and right_is_header:
			return False

		ascending = self._sort_order == Qt.AscendingOrder

		if self.sortRole() == ShapeItemsModel.NameRole:
			left_name = (model.data(left, ShapeItemsModel.NameRole) or "").lower()
			right_name = (model.data(right, ShapeItemsModel.NameRole) or "").lower()
			if left_name == right_name:
				return False
			return left_name < right_name if ascending else left_name > right_name

		if self.sortRole() == ShapeItemsModel.ValueRole:
			left_value = float(model.data(left, ShapeItemsModel.ValueRole) or 0.0)
			right_value = float(model.data(right, ShapeItemsModel.ValueRole) or 0.0)
			if abs(left_value - right_value) > 1e-9:
				return left_value < right_value if ascending else left_value > right_value
			left_name = (model.data(left, ShapeItemsModel.NameRole) or "").lower()
			right_name = (model.data(right, ShapeItemsModel.NameRole) or "").lower()
			if left_name == right_name:
				return False
			return left_name < right_name

		return super().lessThan(left, right)


class PrimarySubsetProxyModel(QSortFilterProxyModel):
	"""Primary-only subset view without headers, driven by an explicit name set."""

	def __init__(self, parent: Optional[QWidget] = None):
		super().__init__(parent)
		self._selected_names: Set[str] = set()
		self.setDynamicSortFilter(False)

	def clear_selected_names(self) -> None:
		self._selected_names.clear()
		self.invalidateFilter()

	def add_selected_names(self, names: Sequence[str]) -> None:
		for name in names:
			if name:
				self._selected_names.add(str(name))
		self.invalidateFilter()

	def selected_names(self) -> List[str]:
		return sorted(self._selected_names)

	def remove_selected_names(self, names: Sequence[str]) -> int:
		remove_names = {str(name) for name in names if name}
		if not remove_names:
			return 0
		removed = len(remove_names.intersection(self._selected_names))
		if removed:
			self._selected_names.difference_update(remove_names)
			self.invalidateFilter()
		return removed

	def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:  # noqa: N802
		model = self.sourceModel()
		if model is None:
			return False
		index = model.index(source_row, 0, source_parent)
		if bool(model.data(index, ShapeItemsModel.IsHeaderRole)):
			return False
		if model.data(index, ShapeItemsModel.TypeRole) != "PrimaryShape":
			return False
		name = str(model.data(index, ShapeItemsModel.NameRole) or "")
		return name in self._selected_names

	def lessThan(self, left: QModelIndex, right: QModelIndex) -> bool:  # noqa: N802
		model = self.sourceModel()
		if model is None:
			return False
		left_name = (model.data(left, ShapeItemsModel.NameRole) or "").lower()
		right_name = (model.data(right, ShapeItemsModel.NameRole) or "").lower()
		if left_name == right_name:
			return False
		return left_name < right_name


class WorkShapeItemsModel(QAbstractListModel):
	"""List model for work blendshape weights rendered with slider delegate style."""

	NameRole = ShapeItemsModel.NameRole
	TypeRole = ShapeItemsModel.TypeRole
	ValueRole = ShapeItemsModel.ValueRole
	MutedRole = ShapeItemsModel.MutedRole
	LevelRole = ShapeItemsModel.LevelRole
	PrimariesRole = ShapeItemsModel.PrimariesRole
	EditableRole = ShapeItemsModel.EditableRole
	IsHeaderRole = ShapeItemsModel.IsHeaderRole
	HeaderLevelRole = ShapeItemsModel.HeaderLevelRole
	HeaderCollapsedRole = ShapeItemsModel.HeaderCollapsedRole
	LockedRole = ShapeItemsModel.LockedRole
	LockIconVisibleRole = ShapeItemsModel.LockIconVisibleRole
	InEditModeRole = Qt.UserRole + 50
	ConnectedRole = Qt.UserRole + 51
	DriverConnectedRole = Qt.UserRole + 52

	valueCommitted = Signal(str, float)

	def __init__(self, parent: Optional[QWidget] = None):
		super().__init__(parent)
		self._editor: Optional[BlueSteelEditor] = None
		self._rows: List[dict] = []
		self._row_by_name: Dict[str, int] = {}
		self._edit_shape_name: Optional[str] = None

	def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
		if parent.isValid():
			return 0
		return len(self._rows)

	def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
		if not index.isValid() or not (0 <= index.row() < len(self._rows)):
			return None
		row = self._rows[index.row()]
		if role in (Qt.DisplayRole, self.NameRole):
			return row["name"]
		if role == self.TypeRole:
			return row["type"]
		if role == self.ValueRole:
			return row["value"]
		if role == self.MutedRole:
			return bool(row.get("muted", False))
		if role == self.LevelRole:
			return 0
		if role == self.PrimariesRole:
			return tuple()
		if role == self.EditableRole:
			return True
		if role == self.IsHeaderRole:
			return False
		if role == self.HeaderLevelRole:
			return 0
		if role == self.HeaderCollapsedRole:
			return False
		if role == self.LockedRole:
			return False
		if role == self.LockIconVisibleRole:
			return False
		if role == self.InEditModeRole:
			return str(row["name"]) == str(self._edit_shape_name)
		if role == self.ConnectedRole:
			return bool(row.get("connected", False))
		if role == self.DriverConnectedRole:
			return bool(row.get("driver_connected", False))
		if role == Qt.ToolTipRole:
			return row.get("tooltip", None)
		return None

	def flags(self, index: QModelIndex):
		if not index.isValid():
			return Qt.NoItemFlags
		return Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsEditable

	def setData(self, index: QModelIndex, value, role: int = Qt.EditRole) -> bool:  # noqa: N802
		if not index.isValid() or not (0 <= index.row() < len(self._rows)):
			return False
		if role == Qt.ToolTipRole:
			row = self._rows[index.row()]
			tooltip_text = str(value).strip() if value else ""
			if row.get("tooltip", "") == tooltip_text:
				return False
			if tooltip_text:
				row["tooltip"] = tooltip_text
			else:
				row.pop("tooltip", None)
			self.dataChanged.emit(index, index, [Qt.ToolTipRole])
			return True
		if role not in (Qt.EditRole, self.ValueRole):
			return False
		if self._editor is None or self._editor.work_blendshape is None:
			return False
		try:
			new_value = max(0.0, min(1.0, float(value)))
		except (TypeError, ValueError):
			return False
		row = self._rows[index.row()]
		if abs(float(row["value"]) - new_value) <= 1e-6:
			return False
		weight = self._editor.work_blendshape.get_weight_by_name(row["name"])
		if weight is None:
			return False
		self._editor.work_blendshape.set_weight_value(weight, new_value)
		row["value"] = new_value
		self.dataChanged.emit(index, index, [self.ValueRole, Qt.DisplayRole])
		self.valueCommitted.emit(str(row["name"]), new_value)
		return True

	def rebuild_from_editor(self, editor: Optional[BlueSteelEditor]) -> None:
		self.beginResetModel()
		self._editor = editor
		self._rows = []
		self._row_by_name = {}
		self._edit_shape_name = None
		if editor is not None and editor.work_blendshape is not None:
			connected_weights = set(editor.get_work_blendshape_connected_targets_weights() or [])
			sculpt_target_indices = set(editor.work_blendshape.get_sculpt_target_indices() or [])
			weights = sorted(editor.get_work_blendshape_weights() or [], key=lambda w: str(w).lower())
			for weight in weights:
				name = str(weight)
				value = float(editor.work_blendshape.get_weight_value(weight))
				muted = bool(editor.get_work_shape_muted_state(name))
				connected = weight in connected_weights
				driver_connected = bool(editor.get_work_shape_driver(weight))
				self._row_by_name[name] = len(self._rows)
				row = {
					"name": name,
					"type": "WorkShape",
					"value": value,
					"muted": muted,
					"connected": connected,
					"driver_connected": driver_connected,
				}
				if connected:
					row["tooltip"] = "Connected extraction mesh"
				self._rows.append(row)
				if self._edit_shape_name is None and int(weight.id) in sculpt_target_indices:
					self._edit_shape_name = name
		self.endResetModel()

	def has_connected_driver_shapes(self) -> bool:
		for row in self._rows:
			if bool(row.get("driver_connected", False)):
				return True
		return False

	def set_value_by_name(self, shape_name: str, value: float) -> None:
		row_index = self._row_by_name.get(shape_name)
		if row_index is None:
			return
		self.setData(self.index(row_index, 0), value, self.ValueRole)

	def get_value(self, shape_name: str) -> Optional[float]:
		row_index = self._row_by_name.get(shape_name)
		if row_index is None:
			return None
		return float(self._rows[row_index]["value"])

	def set_value_local(self, shape_name: str, value: float) -> None:
		"""Update one row value from external tracker callbacks without writing to Maya."""
		row_index = self._row_by_name.get(shape_name)
		if row_index is None:
			return
		clamped_value = max(0.0, min(1.0, float(value)))
		row = self._rows[row_index]
		if abs(float(row.get("value", 0.0)) - clamped_value) <= 1e-6:
			return
		row["value"] = clamped_value
		model_index = self.index(row_index, 0)
		self.dataChanged.emit(model_index, model_index, [self.ValueRole, Qt.DisplayRole])

	def set_muted_state_local(self, shape_name: str, muted: bool) -> None:
		"""Update one row muted state from UI callbacks without forcing rebuild."""
		row_index = self._row_by_name.get(shape_name)
		if row_index is None:
			return
		row = self._rows[row_index]
		target = bool(muted)
		if bool(row.get("muted", False)) == target:
			return
		row["muted"] = target
		model_index = self.index(row_index, 0)
		self.dataChanged.emit(model_index, model_index, [self.MutedRole, Qt.DisplayRole])

	def is_shape_connected(self, shape_name: str) -> bool:
		row_index = self._row_by_name.get(shape_name)
		if row_index is None:
			return False
		return bool(self._rows[row_index].get("connected", False))

	def set_connected_state_local(self, shape_name: str, connected: bool) -> None:
		row_index = self._row_by_name.get(shape_name)
		if row_index is None:
			return
		row = self._rows[row_index]
		target_connected = bool(connected)
		if bool(row.get("connected", False)) == target_connected:
			return
		row["connected"] = target_connected
		if target_connected:
			row["tooltip"] = "Connected extraction mesh"
		else:
			row.pop("tooltip", None)
		model_index = self.index(row_index, 0)
		self.dataChanged.emit(model_index, model_index, [self.ConnectedRole, Qt.ToolTipRole, Qt.DisplayRole])

	def set_driver_connected_state_local(self, shape_name: str, connected: bool) -> None:
		row_index = self._row_by_name.get(shape_name)
		if row_index is None:
			return
		row = self._rows[row_index]
		target_connected = bool(connected)
		if bool(row.get("driver_connected", False)) == target_connected:
			return
		row["driver_connected"] = target_connected
		model_index = self.index(row_index, 0)
		self.dataChanged.emit(model_index, model_index, [self.DriverConnectedRole, Qt.DisplayRole])

	def refresh_values_from_editor(self) -> List[tuple]:
		"""Pull current work-blendshape values and update rows without rebuilding.

		Returns a list of changed rows as tuples: (name, value).
		"""
		if self._editor is None or self._editor.work_blendshape is None:
			return []

		work_blendshape = self._editor.work_blendshape
		changed: List[tuple] = []

		for row_index, row in enumerate(self._rows):
			new_value = work_blendshape.get_weight_value_by_name(str(row.get("name", "")))
			clamped_value = max(0.0, min(1.0, float(new_value or 0.0)))
			if abs(float(row.get("value", 0.0)) - clamped_value) <= 1e-6:
				continue
			row["value"] = clamped_value
			model_index = self.index(row_index, 0)
			self.dataChanged.emit(model_index, model_index, [self.ValueRole, Qt.DisplayRole])
			changed.append((str(row.get("name", "")), clamped_value))

		return changed

	def index_by_name(self, shape_name: str) -> QModelIndex:
		row_index = self._row_by_name.get(shape_name)
		if row_index is None:
			return QModelIndex()
		return self.index(row_index, 0)

	def edit_shape_name(self) -> Optional[str]:
		return self._edit_shape_name

	def set_edit_shape(self, shape_name: Optional[str]) -> None:
		previous = self._edit_shape_name
		next_name = str(shape_name) if shape_name else None
		if next_name and next_name not in self._row_by_name:
			next_name = None
		if previous == next_name:
			return
		self._edit_shape_name = next_name
		for changed_name in (previous, next_name):
			if not changed_name:
				continue
			changed_index = self.index_by_name(changed_name)
			if changed_index.isValid():
				self.dataChanged.emit(changed_index, changed_index, [self.InEditModeRole, Qt.DisplayRole])


class PrimaryDropListView(QListView):
	"""Drop-enabled list that accepts primaries dragged from the primaries tree."""
	DRAG_MIME_TYPE = "application/x-blue-steel-shape-names"
	PRIMARY_TREE_MIME_TYPE = "application/x-qabstractitemmodeldatalist"

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
		if not isinstance(delegate, SliderItemDelegate):
			return None

		index = self.indexAt(event_pos)
		if not index.isValid():
			return None
		if bool(index.data(ShapeItemsModel.IsHeaderRole)):
			return None

		class _OptionRect:
			pass

		option = _OptionRect()
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
		if not isinstance(delegate, SliderItemDelegate):
			return None

		index = self.indexAt(event_pos)
		if not index.isValid():
			return None
		if bool(index.data(ShapeItemsModel.IsHeaderRole)):
			return None

		class _OptionRect:
			pass

		option = _OptionRect()
		option.rect = self.visualRect(index)
		icon_rect = delegate._lock_icon_rect(option, index)
		if icon_rect.isNull() or not icon_rect.contains(event_pos):
			return None

		shape_name = str(index.data(ShapeItemsModel.NameRole) or "")
		if not shape_name:
			return None

		current_locked = bool(index.data(ShapeItemsModel.LockedRole))
		return shape_name, (not current_locked)

	def mousePressEvent(self, event):  # noqa: N802
		if event.button() == Qt.LeftButton:
			mute_payload = self._resolve_mute_icon_click(event.pos())
			if mute_payload is not None:
				delegate = self.itemDelegate()
				if isinstance(delegate, SliderItemDelegate):
					shape_name, next_state = mute_payload
					delegate.muteToggleRequested.emit(shape_name, next_state)
					self._icon_click_active = True
					event.accept()
					return
			lock_payload = self._resolve_lock_icon_click(event.pos())
			if lock_payload is not None:
				delegate = self.itemDelegate()
				if isinstance(delegate, SliderItemDelegate):
					shape_name, next_state = lock_payload
					delegate.lockToggleRequested.emit(shape_name, next_state)
					self._icon_click_active = True
					event.accept()
					return
		super().mousePressEvent(event)

	def mouseMoveEvent(self, event):  # noqa: N802
		delegate = self.itemDelegate()
		if isinstance(delegate, SliderItemDelegate) and delegate.is_drag_active():
			if delegate.external_drag_move(event.pos().x()):
				event.accept()
				return
		super().mouseMoveEvent(event)

	def mouseReleaseEvent(self, event):  # noqa: N802
		if self._icon_click_active and event.button() == Qt.LeftButton:
			self._icon_click_active = False
			event.accept()
			return

		delegate = self.itemDelegate()
		if isinstance(delegate, SliderItemDelegate) and event.button() == Qt.LeftButton and delegate.is_drag_active():
			if delegate.external_drag_end(event.pos().x()):
				event.accept()
				return
		super().mouseReleaseEvent(event)

	def mouseDoubleClickEvent(self, event):  # noqa: N802
		if event.button() == Qt.LeftButton and (
			self._resolve_mute_icon_click(event.pos()) is not None
			or self._resolve_lock_icon_click(event.pos()) is not None
		):
			event.accept()
			return
		super().mouseDoubleClickEvent(event)

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
		return isinstance(parent_view, PrimaryTreeWidget) or bool(getattr(parent_view, "_primary_tree_layout", False))

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
		if not isinstance(parent_view, (PrimaryTreeWidget, ShapeTreeWidget)) and not self._is_primary_tree_view():
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
		return not self._is_primary_tree_view() and not isinstance(parent_view, PrimaryDropListView)

	def _panel_reserved_icon_slots(self) -> int:
		parent_view = self.parent()
		if self._is_primary_tree_view():
			return 0
		if isinstance(parent_view, PrimaryDropListView):
			return 1
		if isinstance(parent_view, WorkShapesListView):
			return 2
		if isinstance(parent_view, (ShapeTreeWidget, SliderListView)):
			return 2
		return 1

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
			is_group_tree = isinstance(parent_view, (PrimaryTreeWidget, ShapeTreeWidget)) or self._is_primary_tree_view()
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
		is_shapes_tree = isinstance(parent_view, ShapeTreeWidget)
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
		self._grab_view_mouse()
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
		self._release_view_mouse()
		self.valueDragEnded.emit()
		self._close_drag_undo_chunk()

	def _grab_view_mouse(self) -> None:
		parent = self.parent()
		if isinstance(parent, QAbstractItemView):
			parent.viewport().grabMouse()

	def _release_view_mouse(self) -> None:
		parent = self.parent()
		if isinstance(parent, QAbstractItemView):
			parent.viewport().releaseMouse()

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
		class _OptionRect:
			pass

		option = _OptionRect()
		option.rect = item_rect
		value_rect, _ = self._area_rects(option, index)
		if not value_rect.contains(event_pos):
			return False
		self._start_drag(model, index, event_pos, value_rect)
		return True

	def editorEvent(self, event, model, option, index):  # noqa: N802
		if bool(model.data(index, ShapeItemsModel.IsHeaderRole)):
			return super().editorEvent(event, model, option, index)

		if event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
			connected_mesh_rect = self._connected_mesh_icon_rect(option, index)
			if not connected_mesh_rect.isNull() and connected_mesh_rect.contains(event.pos()):
				shape_name = str(model.data(index, ShapeItemsModel.NameRole) or "")
				is_connected = bool(model.data(index, WorkShapeItemsModel.ConnectedRole))
				if shape_name and is_connected:
					self.connectedMeshRequested.emit(shape_name)
				return True
			icon_rect = self._mute_icon_rect(option, index)
			if icon_rect.contains(event.pos()):
				shape_name = str(model.data(index, ShapeItemsModel.NameRole) or "")
				if shape_name:
					current_muted = bool(model.data(index, ShapeItemsModel.MutedRole))
					self.muteToggleRequested.emit(shape_name, not current_muted)
				return True
			edit_mode_rect = self._edit_mode_icon_rect(option, index)
			if not edit_mode_rect.isNull() and edit_mode_rect.contains(event.pos()):
				shape_name = str(model.data(index, ShapeItemsModel.NameRole) or "")
				if shape_name:
					in_edit_mode = bool(model.data(index, WorkShapeItemsModel.InEditModeRole))
					self.workEditModeToggleRequested.emit(shape_name, not in_edit_mode)
				return True
			lock_rect = self._lock_icon_rect(option, index)
			if not lock_rect.isNull() and lock_rect.contains(event.pos()):
				shape_name = str(model.data(index, ShapeItemsModel.NameRole) or "")
				if shape_name:
					current_locked = bool(model.data(index, ShapeItemsModel.LockedRole))
					self.lockToggleRequested.emit(shape_name, not current_locked)
				return True

		if not bool(model.data(index, ShapeItemsModel.EditableRole)):
			return super().editorEvent(event, model, option, index)

		value_rect, _ = self._area_rects(option, index)
		drag_button = Qt.LeftButton

		if event.type() == QEvent.MouseButtonPress:
			if event.button() == drag_button and value_rect.contains(event.pos()):
				if not self._drag_active:
					self._start_drag(model, index, event.pos(), value_rect)
				else:
					self._set_drag_value_from_pos(model, event.pos().x())
				return True

		if event.type() == QEvent.MouseMove:
			if self._drag_active and (event.buttons() & drag_button):
				self._set_drag_value_from_pos(model, event.pos().x())
				return True

		if event.type() == QEvent.MouseButtonRelease:
			if self._drag_active and event.button() == drag_button:
				self._end_drag(model, event.pos().x())
				return True

		if event.type() == QEvent.MouseButtonDblClick:
			# Open the inline value editor only on the slider area; always consume so
			# Qt does not start its own name-edit on editable rows.
			parent = self.parent()
			if value_rect.contains(event.pos()) and isinstance(parent, QAbstractItemView):
				parent.edit(index)
			return True

		return super().editorEvent(event, model, option, index)


class SplitMapWeightsList(QListWidget):
	"""Selectable edit-blendshape weight sliders."""

	def mouseMoveEvent(self, event):  # noqa: N802
		delegate = self.itemDelegate()
		if isinstance(delegate, SliderItemDelegate) and delegate.is_drag_active():
			if delegate.external_drag_move(event.pos().x()):
				event.accept()
				return
		super().mouseMoveEvent(event)

	def mouseReleaseEvent(self, event):  # noqa: N802
		delegate = self.itemDelegate()
		if isinstance(delegate, SliderItemDelegate) and event.button() == Qt.LeftButton and delegate.is_drag_active():
			if delegate.external_drag_end(event.pos().x()):
				event.accept()
				return
		super().mouseReleaseEvent(event)


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


class SliderListView(QListView):
	"""QListView that forwards global drag move/release to `SliderItemDelegate`.

	Once drag starts in the slider area, updates continue from mouse x-delta even
	when the pointer leaves the original item rectangle.
	"""
	DRAG_MIME_TYPE = "application/x-blue-steel-shape-names"

	def __init__(self, parent=None) -> None:
		super().__init__(parent)
		self._icon_click_active = False

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

	def _resolve_mute_icon_click(self, event_pos) -> Optional[tuple]:
		"""Return (shape_name, next_state) if event is on mute icon, else None."""
		delegate = self.itemDelegate()
		if not isinstance(delegate, SliderItemDelegate):
			return None

		index = self.indexAt(event_pos)
		if not index.isValid():
			return None
		if bool(index.data(ShapeItemsModel.IsHeaderRole)):
			return None

		class _OptionRect:
			pass

		option = _OptionRect()
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
		if not isinstance(delegate, SliderItemDelegate):
			return None

		index = self.indexAt(event_pos)
		if not index.isValid():
			return None
		if bool(index.data(ShapeItemsModel.IsHeaderRole)):
			return None

		class _OptionRect:
			pass

		option = _OptionRect()
		option.rect = self.visualRect(index)
		icon_rect = delegate._connected_mesh_icon_rect(option, index)
		if icon_rect.isNull() or not icon_rect.contains(event_pos):
			return None

		if not bool(index.data(WorkShapeItemsModel.ConnectedRole)):
			return None

		shape_name = str(index.data(ShapeItemsModel.NameRole) or "")
		if not shape_name:
			return None
		return shape_name

	def _resolve_lock_icon_click(self, event_pos) -> Optional[tuple]:
		"""Return (shape_name, next_state) if event is on lock icon, else None."""
		delegate = self.itemDelegate()
		if not isinstance(delegate, SliderItemDelegate):
			return None

		index = self.indexAt(event_pos)
		if not index.isValid():
			return None
		if bool(index.data(ShapeItemsModel.IsHeaderRole)):
			return None

		class _OptionRect:
			pass

		option = _OptionRect()
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
		if not isinstance(delegate, SliderItemDelegate):
			return None

		index = self.indexAt(event_pos)
		if not index.isValid():
			return None
		if bool(index.data(ShapeItemsModel.IsHeaderRole)):
			return None

		class _OptionRect:
			pass

		option = _OptionRect()
		option.rect = self.visualRect(index)
		icon_rect = delegate._edit_mode_icon_rect(option, index)
		if icon_rect.isNull() or not icon_rect.contains(event_pos):
			return None

		shape_name = str(index.data(ShapeItemsModel.NameRole) or "")
		if not shape_name:
			return None

		in_edit_mode = bool(index.data(WorkShapeItemsModel.InEditModeRole))
		return shape_name, (not in_edit_mode)

	def mousePressEvent(self, event):  # noqa: N802
		if event.button() == Qt.LeftButton:
			connected_shape_name = self._resolve_connected_mesh_icon_click(event.pos())
			if connected_shape_name is not None:
				delegate = self.itemDelegate()
				if isinstance(delegate, SliderItemDelegate):
					delegate.connectedMeshRequested.emit(connected_shape_name)
					self._icon_click_active = True
					event.accept()
					return
			mute_payload = self._resolve_mute_icon_click(event.pos())
			if mute_payload is not None:
				delegate = self.itemDelegate()
				if isinstance(delegate, SliderItemDelegate):
					shape_name, next_state = mute_payload
					delegate.muteToggleRequested.emit(shape_name, next_state)
					self._icon_click_active = True
					event.accept()
					return
			lock_payload = self._resolve_lock_icon_click(event.pos())
			if lock_payload is not None:
				delegate = self.itemDelegate()
				if isinstance(delegate, SliderItemDelegate):
					shape_name, next_state = lock_payload
					delegate.lockToggleRequested.emit(shape_name, next_state)
					self._icon_click_active = True
					event.accept()
					return
			edit_mode_payload = self._resolve_work_edit_mode_icon_click(event.pos())
			if edit_mode_payload is not None:
				delegate = self.itemDelegate()
				if isinstance(delegate, SliderItemDelegate):
					shape_name, next_state = edit_mode_payload
					delegate.workEditModeToggleRequested.emit(shape_name, next_state)
					self._icon_click_active = True
					event.accept()
					return
		super().mousePressEvent(event)

	def mouseMoveEvent(self, event):  # noqa: N802
		delegate = self.itemDelegate()
		if isinstance(delegate, SliderItemDelegate) and delegate.is_drag_active():
			if delegate.external_drag_move(event.pos().x()):
				event.accept()
				return
		super().mouseMoveEvent(event)

	def mouseReleaseEvent(self, event):  # noqa: N802
		if self._icon_click_active and event.button() == Qt.LeftButton:
			self._icon_click_active = False
			event.accept()
			return

		delegate = self.itemDelegate()
		if isinstance(delegate, SliderItemDelegate) and event.button() == Qt.LeftButton and delegate.is_drag_active():
			if delegate.external_drag_end(event.pos().x()):
				event.accept()
				return
		super().mouseReleaseEvent(event)

	def mouseDoubleClickEvent(self, event):  # noqa: N802
		if event.button() == Qt.LeftButton and (
			self._resolve_connected_mesh_icon_click(event.pos()) is not None
			or
			self._resolve_mute_icon_click(event.pos()) is not None
			or self._resolve_lock_icon_click(event.pos()) is not None
			or self._resolve_work_edit_mode_icon_click(event.pos()) is not None
		):
			event.accept()
			return
		super().mouseDoubleClickEvent(event)


class WorkShapesListView(SliderListView):
	"""Work shapes list supporting drops from shape lists and link context actions."""

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
		parent=None,
	) -> None:
		super().__init__(parent)
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
		self.setAcceptDrops(True)
		self.setDragDropMode(QAbstractItemView.DropOnly)
		self.setDefaultDropAction(Qt.CopyAction)
		self.setContextMenuPolicy(Qt.CustomContextMenu)
		self.customContextMenuRequested.connect(self._show_context_menu)

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
		model = self.model()
		if model is None:
			return None
		index = self.indexAt(pos)
		if not index.isValid():
			return None
		if bool(model.data(index, ShapeItemsModel.IsHeaderRole)):
			return None
		receiver = str(model.data(index, ShapeItemsModel.NameRole) or "")
		return receiver or None

	def dragEnterEvent(self, event):  # noqa: N802
		shape_names = self._shape_names_from_mime(event.mimeData())
		if shape_names:
			event.acceptProposedAction()
			return
		event.ignore()

	def dragMoveEvent(self, event):  # noqa: N802
		receiver_name = self._receiver_name_at_pos(event.pos())
		shape_names = self._shape_names_from_mime(event.mimeData())
		if receiver_name and shape_names:
			event.acceptProposedAction()
			return
		event.ignore()

	def dropEvent(self, event):  # noqa: N802
		receiver_name = self._receiver_name_at_pos(event.pos())
		shape_names = self._shape_names_from_mime(event.mimeData())
		if not receiver_name or not shape_names:
			event.ignore()
			return
		self._drop_callback(receiver_name, shape_names[0])
		event.acceptProposedAction()

	def _show_context_menu(self, pos) -> None:
		receiver_name = self._receiver_name_at_pos(pos)
		if not receiver_name:
			return
		selected_shape_names = self._selected_draggable_shape_names()
		normalize_targets = selected_shape_names if receiver_name in selected_shape_names else [receiver_name]
		menu = QMenu(self)
		duplicate_action = menu.addAction(f"Duplicate")
		extract_work_shape_mesh_action = menu.addAction("Extract Mesh")
		can_extract_mesh = self._can_extract_mesh_callback is None or self._can_extract_mesh_callback()
		extract_work_shape_mesh_action.setEnabled(can_extract_mesh)
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
		if selected_action == duplicate_action:
			self.duplicate_callback(receiver_name)
		elif selected_action == extract_work_shape_mesh_action:
			self.extract_work_shape_mesh_callback(receiver_name)
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


class ShapeTreeWidget(QTreeWidget):
	"""Tree view for shapes that supports slider drag forwarding and shape drags."""

	DRAG_MIME_TYPE = "application/x-blue-steel-shape-names"
	toggleUpstreamFilterRequested = Signal()
	pageNavigationPoseRequested = Signal(str)

	def __init__(self, parent=None) -> None:
		super().__init__(parent)
		self._toggle_icon_click_active = False

	def _resolve_toggle_icon_click(self, event_pos) -> Optional[tuple]:
		index = self.indexAt(event_pos)
		delegate = self.itemDelegateForColumn(0)
		if not index.isValid() or not isinstance(delegate, SliderItemDelegate):
			return None
		if bool(index.data(ShapeItemsModel.IsHeaderRole)):
			return None

		class _OptionRect:
			pass

		option = _OptionRect()
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

	def mousePressEvent(self, event):  # noqa: N802
		if event.button() == Qt.LeftButton:
			toggle_payload = self._resolve_toggle_icon_click(event.pos())
			if toggle_payload is not None:
				toggle_signal, shape_name, next_state = toggle_payload
				toggle_signal.emit(shape_name, next_state)
				self._toggle_icon_click_active = True
				event.accept()
				return
		super().mousePressEvent(event)

	def mouseDoubleClickEvent(self, event):  # noqa: N802
		if event.button() == Qt.LeftButton and self._resolve_toggle_icon_click(event.pos()) is not None:
			self._toggle_icon_click_active = True
			event.accept()
			return
		super().mouseDoubleClickEvent(event)

	def mouseMoveEvent(self, event):  # noqa: N802
		delegate = self.itemDelegateForColumn(0)
		if isinstance(delegate, SliderItemDelegate) and delegate.is_drag_active():
			if delegate.external_drag_move(event.pos().x()):
				event.accept()
				return
		super().mouseMoveEvent(event)

	def mouseReleaseEvent(self, event):  # noqa: N802
		if self._toggle_icon_click_active and event.button() == Qt.LeftButton:
			self._toggle_icon_click_active = False
			event.accept()
			return

		delegate = self.itemDelegateForColumn(0)
		if isinstance(delegate, SliderItemDelegate) and event.button() == Qt.LeftButton and delegate.is_drag_active():
			if delegate.external_drag_end(event.pos().x()):
				event.accept()
				return
		super().mouseReleaseEvent(event)


class PrimaryTreeWidget(QTreeWidget):
	"""Primary tree that mirrors the shapes tree: the delegate owns slider value
	drags and Qt owns name drags, so clicks and double-clicks reach the view."""

	DRAG_MIME_TYPE = "application/x-blue-steel-shape-names"
	pageNavigationPoseRequested = Signal(str)

	def __init__(self, parent=None) -> None:
		super().__init__(parent)
		self._toggle_icon_click_active = False

	def _resolve_toggle_icon_click(self, event_pos) -> Optional[tuple]:
		index = self.indexAt(event_pos)
		delegate = self.itemDelegateForColumn(0)
		if not index.isValid() or not isinstance(delegate, SliderItemDelegate):
			return None
		if bool(index.data(ShapeItemsModel.IsHeaderRole)):
			return None

		class _OptionRect:
			pass

		option = _OptionRect()
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

	def mousePressEvent(self, event):  # noqa: N802
		if event.button() == Qt.LeftButton:
			toggle_payload = self._resolve_toggle_icon_click(event.pos())
			if toggle_payload is not None:
				toggle_signal, shape_name, next_state = toggle_payload
				toggle_signal.emit(shape_name, next_state)
				self._toggle_icon_click_active = True
				event.accept()
				return
		super().mousePressEvent(event)

	def mouseDoubleClickEvent(self, event):  # noqa: N802
		if event.button() == Qt.LeftButton and self._resolve_toggle_icon_click(event.pos()) is not None:
			self._toggle_icon_click_active = True
			event.accept()
			return
		super().mouseDoubleClickEvent(event)

	def mouseMoveEvent(self, event):  # noqa: N802
		delegate = self.itemDelegateForColumn(0)
		if isinstance(delegate, SliderItemDelegate) and delegate.is_drag_active():
			if delegate.external_drag_move(event.pos().x()):
				event.accept()
				return
		super().mouseMoveEvent(event)

	def mouseReleaseEvent(self, event):  # noqa: N802
		if self._toggle_icon_click_active and event.button() == Qt.LeftButton:
			self._toggle_icon_click_active = False
			event.accept()
			return

		delegate = self.itemDelegateForColumn(0)
		if isinstance(delegate, SliderItemDelegate) and event.button() == Qt.LeftButton and delegate.is_drag_active():
			if delegate.external_drag_end(event.pos().x()):
				event.accept()
				return
		super().mouseReleaseEvent(event)


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


class MainWindow(MayaQWidgetDockableMixin, QMainWindow):
	"""Main Blue Steel editor window."""

	OBJECT_NAME = "BlueSteelEditor"
	WORKSPACE_CONTROL_NAME = f"{OBJECT_NAME}WorkspaceControl"
	DOCK_TARGET_CONTROL = "Outliner"
	EMPTY_SYSTEM_LABEL = "<Select System>"
	SPLIT_PANELS_MAX_WIDTH = 600
	COMPACT_MARGIN = 2
	COMPACT_SPACING = 2
	PRIMARY_TREE_NAME_ROLE = Qt.UserRole + 200
	PRIMARY_TREE_FOLDER_ROLE = Qt.UserRole + 201

	def __init__(self, parent: Optional[QWidget] = None, version: Optional[str] = None) -> None:
		super().__init__(parent)
		self.setObjectName(self.OBJECT_NAME)
		self.version = version

		self.current_editor: Optional[BlueSteelEditor] = None
		self.scene_editor_tracker: Optional[BlueSteelEditorsTracker] = None
		self.blendshape_tracker: Optional[BlendShapeNodeTracker] = None
		self.work_blendshape_tracker: Optional[BlendShapeNodeTracker] = None
		self.split_map_edit_blendshape_tracker: Optional[BlendShapeNodeTracker] = None
		self.split_attr_grp_tracker: Optional[ControllerTracker] = None
		self._split_attr_refresh_pending = False
		self._split_attr_full_refresh_pending = False
		self._split_settings_refresh_pending = False
		self._split_map_normalization_cache: Dict[str, bool] = {}

		self._shape_model = ShapeItemsModel(self)
		self._work_shape_model = WorkShapeItemsModel(self)
		self._primaries_proxy = PrimaryShapesProxyModel(self)
		self._shapes_proxy = ShapesFilterProxyModel(self)
		self._primary_subset_proxy = PrimarySubsetProxyModel(self)
		self._active_shapes_proxy = ShapesFilterProxyModel(self)
		self._primaries_proxy.setSourceModel(self._shape_model)
		self._shapes_proxy.setSourceModel(self._shape_model)
		self._primary_subset_proxy.setSourceModel(self._shape_model)
		self._active_shapes_proxy.setSourceModel(self._shape_model)
		self._active_shapes_proxy.set_active_only(True)
		self._exclusive_primary_filter = False
		self._primary_tree_sort_by_value = False
		self._primaries_drag_active = False
		self._linked_drag_active = False
		self._linked_primary_start_values: Dict[str, float] = {}
		self._linked_work_start_values: Dict[str, float] = {}
		self._linked_drag_can_propagate = False
		self._linked_drag_ctrl_pressed = False
		self._primary_tree_items: Dict[str, QTreeWidgetItem] = {}
		self._shape_tree_items: Dict[str, QTreeWidgetItem] = {}
		self._syncing_primaries_tree = False
		self._syncing_shapes_tree = False
		self._upstream_shapes_cache: Dict[str, Set[str]] = {}
		self._downstream_shapes_cache: Dict[str, Set[str]] = {}
		self._shapes_tree_expanded_headers: Dict[int, bool] = {}
		self._shapes_tree_expanded_type_groups: Dict[tuple, bool] = {}
		self._primary_tree_folder_open_icon = QIcon()
		self._primary_tree_folder_closed_icon = QIcon()
		self.tool_buttons: List[QPushButton] = []
		self.rename_editor_action: Optional[QAction] = None
		self.explode_container_action: Optional[QAction] = None
		self.fix_invisible_blendshapes_action: Optional[QAction] = None
		self.convert_simplex_action: Optional[QAction] = None
		self.connect_simplex_controllers_action: Optional[QAction] = None
		self.prepare_for_publishing_action: Optional[QAction] = None
		self.blendshape_node_io_actions: List[QAction] = []
		self._workshape_rename_editor: Optional[QLineEdit] = None
		self._workshape_rename_old_name: str = ""
		self._primary_rename_editor: Optional[QLineEdit] = None
		self._primary_rename_old_name: str = ""
		self._controller_layout_window: Optional[ControllerLayoutWindow] = None
		self.heat_map_switch: Optional[QPushButton] = None
		self._main_splitter: Optional[QSplitter] = None
		self._editor_splitter: Optional[QSplitter] = None
		self._third_column_splitter: Optional[QSplitter] = None
		self._third_column_sections: List[QWidget] = []
		self._tools_group: Optional[QGroupBox] = None
		self._tools_panel_buttons: List[QPushButton] = []
		self._tools_panel_button_labels: Dict[QPushButton, str] = {}
		self._tools_panel_sections: List[FrameLayout] = []
		self._tools_panel_section_labels: Dict[FrameLayout, str] = {}
		self._shapes_header_buttons: List[QPushButton] = []
		self._shapes_header_button_labels: Dict[QPushButton, str] = {}
		self._shapes_header_full_width = 0
		self._shapes_header_compact_mode = False
		self._shapes_active_filter_enabled = False
		self._tools_panel_compact_mode = False
		self._tools_panel_compact_threshold = 165
		self._tools_panel_compact_width = 76
		self._tools_panel_expanded_width = 200
		self._tools_panel_compact_icon_size = QSize(24, 24)
		self._tools_panel_expanded_icon_size = QSize(18, 18)
		self._initial_splitter_layout_applied = False
		self._initial_splitter_layout_timer = QTimer(self)
		self._initial_splitter_layout_timer.setSingleShot(True)
		self._initial_splitter_layout_timer.timeout.connect(self._apply_initial_splitter_layout)
		self._active_shapes_filter_refresh_timer = QTimer(self)
		self._active_shapes_filter_refresh_timer.setSingleShot(True)
		self._active_shapes_filter_refresh_timer.setInterval(33)
		self._active_shapes_filter_refresh_timer.timeout.connect(self._refresh_active_shapes_filter)
		self.main_tabs: Optional[QTabWidget] = None
		self.split_primary_search: Optional[TokenSearchBar] = None
		self.split_primaries_tree: Optional[SplitPrimaryAssignmentsView] = None
		self._split_primary_slider_delegate: Optional[SliderItemDelegate] = None
		self.split_groups_tree: Optional[SplitGroupsTree] = None
		self.split_group_preview_label: Optional[QLabel] = None
		self.split_maps_list: Optional[SplitMapsTree] = None
		self.split_map_weights_list: Optional[SplitMapWeightsList] = None
		self.split_map_weight_stats_label: Optional[QLabel] = None
		self._split_map_weight_slider_delegate: Optional[SplitMapWeightSliderDelegate] = None
		self._syncing_split_map_weight_values = False
		self._split_groups_group_widget: Optional[QGroupBox] = None
		self._split_groups_splitter: Optional[QSplitter] = None
		self._split_group_controls_widget: Optional[QWidget] = None
		self._split_group_buttons: List[QPushButton] = []
		self._split_group_button_labels: Dict[QPushButton, str] = {}
		self._split_group_buttons_compact_mode = False
		self._split_group_buttons_expanded_width = 0
		self._split_maps_lists_splitter: Optional[QSplitter] = None
		self._split_map_controls_widget: Optional[QWidget] = None
		self._split_map_weights_column_widget: Optional[QWidget] = None
		self._split_map_editor_group_widget: Optional[QGroupBox] = None
		self._split_map_weights_splitter: Optional[QSplitter] = None
		self._split_map_weight_controls_widget: Optional[QWidget] = None
		self._split_map_buttons: List[QPushButton] = []
		self._split_map_button_labels: Dict[QPushButton, str] = {}
		self._split_map_buttons_compact_mode = False
		self._split_map_buttons_expanded_width = 0
		self._split_map_weight_buttons: List[QPushButton] = []
		self._split_map_weight_button_labels: Dict[QPushButton, str] = {}
		self._split_map_weight_buttons_compact_mode = False
		self._split_map_weight_buttons_expanded_width = 0
		self._split_map_weight_operation_buttons: List[QPushButton] = []
		self._split_map_weight_paste_operation_buttons: List[QPushButton] = []

		self._build_ui()
		self._connect_ui_signals()
		self._setup_scene_editor_tracker()
		self._reload_editor_menu()
		self._select_first_available_editor()
		self._update_window_title()

	def _allow_horizontal_collapse(self, widget: QWidget) -> None:
		widget.setMinimumWidth(0)
		widget.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)

	def _compact_layout(self, layout: QLayout, *, margin: int = 0) -> None:
		layout.setContentsMargins(margin, margin, margin, margin)
		layout.setSpacing(self.COMPACT_SPACING)

	def _prepare_toolbar_button(self, button: QPushButton, *, height: int = 24) -> None:
		button.setStyleSheet("padding: 0px;")
		button.setFixedHeight(height)

	def _create_work_tool_button(self, label: str, icon: QIcon) -> QPushButton:
		button = QPushButton()
		button.setIcon(icon)
		button.setToolTip(label)
		button.setFixedSize(26, 26)
		button.setIconSize(self._tools_panel_expanded_icon_size)
		return button

	def _set_dock_button_state(self, docked: bool) -> None:
		pixmap = QPixmap(14, 14)
		pixmap.fill(Qt.transparent)
		points = (
			[QPoint(11, 7), QPoint(3, 2), QPoint(3, 12)]
			if docked
			else [QPoint(3, 7), QPoint(11, 2), QPoint(11, 12)]
		)
		painter = QPainter(pixmap)
		painter.setRenderHint(QPainter.Antialiasing, True)
		painter.setPen(Qt.NoPen)
		painter.setBrush(self.dock_toggle_button.palette().color(QPalette.ButtonText))
		painter.drawPolygon(QPolygon(points))
		painter.end()
		self.dock_toggle_button.setIcon(QIcon(pixmap))
		self.dock_toggle_button.setToolTip("Undock Blue Steel" if docked else "Dock Blue Steel")
		self.dock_close_button.setVisible(docked)

	def _dock_to_maya_panel(self) -> bool:
		if not cmds.workspaceControl(self.DOCK_TARGET_CONTROL, query=True, exists=True):
			return False
		cmds.workspaceControl(
			self.WORKSPACE_CONTROL_NAME,
			edit=True,
			floating=False,
		)
		cmds.workspaceControl(
			self.WORKSPACE_CONTROL_NAME,
			edit=True,
			dockToControl=(self.DOCK_TARGET_CONTROL, "left"),
		)
		cmds.workspaceControl(
			self.WORKSPACE_CONTROL_NAME,
			edit=True,
			restore=True,
			visible=True,
		)
		self.raise_()
		self.activateWindow()
		self._set_dock_button_state(docked=True)
		return True

	def _toggle_docking(self) -> None:
		if not cmds.workspaceControl(self.WORKSPACE_CONTROL_NAME, query=True, exists=True):
			return
		is_floating = cmds.workspaceControl(
			self.WORKSPACE_CONTROL_NAME,
			query=True,
			floating=True,
		)
		if is_floating:
			self._dock_to_maya_panel()
			return
		cmds.workspaceControl(self.WORKSPACE_CONTROL_NAME, edit=True, floating=True)
		self._set_dock_button_state(docked=False)

	def _build_ui(self) -> None:
		self._create_menu_bar()

		central = QWidget(self)
		self.setCentralWidget(central)
		root_layout = QVBoxLayout(central)
		self._compact_layout(root_layout, margin=self.COMPACT_MARGIN)

		controls_layout = QHBoxLayout()
		self._compact_layout(controls_layout)
		self.refresh_button = QPushButton("Refresh")
		self.refresh_button.setIcon(REFRESH_ICON)
		self._prepare_toolbar_button(self.refresh_button)
		self.create_system_button = QPushButton("New")
		self.create_system_button.setIcon(ADD_ICON)
		self._prepare_toolbar_button(self.create_system_button)
		self.editor_combo = QComboBox()
		self.editor_combo.setSizeAdjustPolicy(QComboBox.AdjustToContents)
		controls_layout.addWidget(self.refresh_button)
		controls_layout.addWidget(self.create_system_button)
		controls_layout.addWidget(QLabel("System:"))
		controls_layout.addWidget(self.editor_combo)
		controls_layout.addStretch()
		self.heat_map_switch = QPushButton("Display Heat Map")
		self.heat_map_switch.setIcon(HEAT_MAP_ICON)
		self.heat_map_switch.setCheckable(True)
		self.heat_map_switch.setChecked(False)
		#self.heat_map_switch.adjustSize()
		self.heat_map_switch.setFixedHeight(24)
		self.heat_map_switch.setFixedWidth(self.heat_map_switch.sizeHint().width() + 2)
		self.heat_map_switch.setToolTip("Toggle heat map visualization for selected shape targets")
		self.heat_map_switch.setVisible(bool(env.DGA_NODES_SUPPORTED))
		self.heat_map_switch.setEnabled(bool(env.DGA_NODES_SUPPORTED))
		self.heat_map_switch.setStyleSheet(
			"""
			QPushButton:checked {
				background-color: #4ba66d;
				border: 1px solid #3f8a5b;
				color: #ffffff;
			}
			QPushButton:!checked {
				background-color: #5a5a5a;
				border: 1px solid #2f2f2f;
			}
			"""
		)
		controls_layout.addWidget(self.heat_map_switch)
		root_layout.addLayout(controls_layout)

		workspace_splitter = QSplitter(Qt.Horizontal)
		workspace_splitter.setChildrenCollapsible(True)
		workspace_splitter.setHandleWidth(2)
		self._allow_horizontal_collapse(workspace_splitter)
		self._main_splitter = workspace_splitter
		root_layout.addWidget(workspace_splitter, 1)
		self._build_tools_panel(workspace_splitter)

		self.main_tabs = QTabWidget(workspace_splitter)
		self._allow_horizontal_collapse(self.main_tabs)
		workspace_splitter.addWidget(self.main_tabs)
		workspace_splitter.setStretchFactor(0, 0)
		workspace_splitter.setStretchFactor(1, 1)
		workspace_splitter.setSizes([self._tools_panel_compact_width, 1220])

		editor_tab = QWidget(self)
		editor_tab_layout = QVBoxLayout(editor_tab)
		editor_tab_layout.setContentsMargins(0, 0, 0, 0)
		editor_tab_layout.setSpacing(0)
		self.main_tabs.addTab(editor_tab, "Editor")

		split_settings_tab = QWidget(self)
		self._build_split_settings_tab(split_settings_tab)
		self.main_tabs.addTab(split_settings_tab, "Split Settings")

		splitter = QSplitter(Qt.Horizontal)
		splitter.setChildrenCollapsible(True)
		splitter.setHandleWidth(2)
		self._allow_horizontal_collapse(splitter)
		self._editor_splitter = splitter
		editor_tab_layout.addWidget(splitter, 1)

		primaries_panel = QWidget()
		self._allow_horizontal_collapse(primaries_panel)
		primaries_layout = QVBoxLayout(primaries_panel)
		self._compact_layout(primaries_layout, margin=self.COMPACT_MARGIN)
		primaries_header_layout = QHBoxLayout()
		self._compact_layout(primaries_header_layout)
		primaries_header_layout.addWidget(QLabel("Primaries"))
		primaries_header_layout.addStretch(1)
		primaries_layout.addLayout(primaries_header_layout)
		self.primaries_search = TokenSearchBar("Filter primaries...")
		primaries_layout.addWidget(self.primaries_search)
		primaries_filter_toolbar = QHBoxLayout()
		self._compact_layout(primaries_filter_toolbar)
		self.primary_filter_button = QPushButton("Filtering: Standard")
		self._prepare_toolbar_button(self.primary_filter_button)
		self.primary_filter_button.setToolTip("Choose how selected primaries filter the Shapes list")
		primary_filter_menu = QMenu(self.primary_filter_button)
		primary_filter_menu.addSection("Filtering")
		self.primary_filter_action_group = QActionGroup(primary_filter_menu)
		self.primary_filter_action_group.setExclusive(True)
		self.standard_filter_action = primary_filter_menu.addAction("Standard (Match Any Primary)")
		self.standard_filter_action.setCheckable(True)
		self.standard_filter_action.setChecked(True)
		self.standard_filter_action.setToolTip(
			"Show shapes that share any selected primary"
		)
		self.exclusive_filter_action = primary_filter_menu.addAction("Exclusive (Exact Relationship)")
		self.exclusive_filter_action.setCheckable(True)
		self.exclusive_filter_action.setToolTip(
			"Show the exact related-shape result for the selected primaries"
		)
		self.primary_filter_action_group.addAction(self.standard_filter_action)
		self.primary_filter_action_group.addAction(self.exclusive_filter_action)
		self.primary_filter_button.setMenu(primary_filter_menu)
		primaries_filter_toolbar.addWidget(self.primary_filter_button)
		primaries_filter_toolbar.addStretch(1)
		primaries_layout.addLayout(primaries_filter_toolbar)
		self.primaries_view = PrimaryTreeWidget()
		self._allow_horizontal_collapse(self.primaries_view)
		self.primaries_view._sort_by_value = False
		self.primaries_view.setColumnCount(1)
		self.primaries_view.setHeaderHidden(True)
		self.primaries_view.setIndentation(0)
		self.primaries_view.setRootIsDecorated(False)
		self._apply_primaries_branch_icons()
		self.primaries_view.setSelectionMode(QAbstractItemView.ExtendedSelection)
		self.primaries_view.setDragEnabled(True)
		self.primaries_view.setDragDropMode(QAbstractItemView.DragOnly)
		self.primaries_view.setToolTip("Drag the value area to adjust; click names to select; drag selected names to drag and drop them")
		self.primaries_view.setContextMenuPolicy(Qt.CustomContextMenu)
		self._primaries_delegate = SliderItemDelegate(self.primaries_view)
		self.primaries_view.setItemDelegateForColumn(0, self._primaries_delegate)

		primaries_layout.addWidget(self.primaries_view, 1)
		primaries_footer_layout = QVBoxLayout()
		primaries_footer_layout.setContentsMargins(0, 0, 0, 0)
		primaries_footer_layout.setSpacing(0)
		self.primaries_info = QLabel("Items: 0")
		primaries_footer_layout.addWidget(self.primaries_info)
		primaries_layout.addLayout(primaries_footer_layout)

		shapes_panel = QWidget()
		self._allow_horizontal_collapse(shapes_panel)
		shapes_layout = QVBoxLayout(shapes_panel)
		self._compact_layout(shapes_layout, margin=self.COMPACT_MARGIN)
		shapes_layout.addWidget(QLabel("Shapes"))
		self.shapes_search = TokenSearchBar("Filter shapes...")
		shapes_layout.addWidget(self.shapes_search)
		self.shapes_view = ShapeTreeWidget()
		self._allow_horizontal_collapse(self.shapes_view)
		self.shapes_view.setColumnCount(1)
		self.shapes_view.setHeaderHidden(True)
		self.shapes_view.setIndentation(0)
		self.shapes_view.setRootIsDecorated(False)
		self.shapes_view.setStyleSheet(
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
		self.shapes_view.setSelectionMode(QAbstractItemView.ExtendedSelection)
		self.shapes_view.setDragEnabled(True)
		self.shapes_view.setDragDropMode(QAbstractItemView.DragOnly)
		self.shapes_view.setContextMenuPolicy(Qt.CustomContextMenu)
		self._shapes_delegate = SliderItemDelegate(self.shapes_view)
		self.shapes_view.setItemDelegateForColumn(0, self._shapes_delegate)

		shapes_header_layout = QHBoxLayout()
		shapes_header_layout.setContentsMargins(0, 0, 0, 0)
		shapes_header_layout.setSpacing(0)
		self.shapes_auto_pose_button = QPushButton("Auto Pose")
		self._prepare_toolbar_button(self.shapes_auto_pose_button)
		self.shapes_auto_pose_button.setIcon(AUTO_POSE_ICON)
		self.shapes_auto_pose_button.setIconSize(QSize(16, 16))
		self.shapes_auto_pose_button.setToolTip("When enabled, selecting a shape sets it to its pose")
		self.shapes_auto_pose_button.setCheckable(True)
		self.shapes_auto_pose_button.setChecked(False)
		shapes_header_layout.addWidget(self.shapes_auto_pose_button, 1)

		self.shapes_list_active_button = QPushButton("List Active")
		self._prepare_toolbar_button(self.shapes_list_active_button)
		self.shapes_list_active_button.setIcon(FILTER_ACTIVE_VALUES_ICON)
		self.shapes_list_active_button.setIconSize(QSize(16, 16))
		self.shapes_list_active_button.setToolTip("List only shapes with an active value")
		self.shapes_list_active_button.setCheckable(True)
		self.shapes_list_active_button.setChecked(False)
		shapes_header_layout.addWidget(self.shapes_list_active_button, 1)

		self.shapes_downstream_button = QPushButton("Downstream")
		self._prepare_toolbar_button(self.shapes_downstream_button)
		self.shapes_downstream_button.setIcon(DOWN_ARROW_ICON)
		self.shapes_downstream_button.setIconSize(QSize(16, 16))
		self.shapes_downstream_button.setToolTip("List Downstream Connections")
		self.shapes_downstream_button.setCheckable(True)
		self.shapes_downstream_button.setChecked(False)
		shapes_header_layout.addWidget(self.shapes_downstream_button, 1)

		self.shapes_upstream_button = QPushButton("Upstream")
		self._prepare_toolbar_button(self.shapes_upstream_button)
		self.shapes_upstream_button.setIcon(UP_ARROW_ICON)
		self.shapes_upstream_button.setIconSize(QSize(16, 16))
		self.shapes_upstream_button.setToolTip("List Upstream Connections")
		self.shapes_upstream_button.setCheckable(True)
		self.shapes_upstream_button.setChecked(False)
		shapes_header_layout.addWidget(self.shapes_upstream_button, 1)

		self._shapes_header_buttons = [
			self.shapes_auto_pose_button,
			self.shapes_list_active_button,
			self.shapes_downstream_button,
			self.shapes_upstream_button,
		]
		self._shapes_header_button_labels = {
			button: button.text() for button in self._shapes_header_buttons
		}
		self._shapes_header_full_width = sum(button.sizeHint().width() for button in self._shapes_header_buttons)
		shapes_layout.addLayout(shapes_header_layout)

		# Color filter swatch row: six colors + a "no color" swatch, all toggleable.
		color_filter_row = QHBoxLayout()
		color_filter_row.setContentsMargins(0, 0, 0, 0)
		color_filter_row.setSpacing(0)
		# Non-interactive label styled like the swatch buttons.
		filter_label = QPushButton("FILTER BY COLOR:")
		filter_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
		filter_label.setFocusPolicy(Qt.NoFocus)
		filter_label.setStyleSheet(
			"QPushButton { border: 1px solid #222; border-radius: 2px; padding: 0 6px; }"
		)
		# Pin the width to the text so the layout can never shrink it below the label.
		filter_label.setFixedSize(
			filter_label.fontMetrics().horizontalAdvance("FILTER BY COLOR:") + 16,
			18,
		)
		color_filter_row.addWidget(filter_label, 0)
		self._color_filter_swatch_buttons: List[QPushButton] = []
		self._color_filter_swatch_colors: Dict[QPushButton, Optional[str]] = {}
		for color_name, color_hex in SHAPE_CUSTOM_COLORS.items():
			swatch = QPushButton()
			swatch.setCheckable(True)
			swatch.setChecked(False)
			swatch.setMinimumWidth(12)
			swatch.setFixedHeight(18)
			swatch.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
			swatch.setToolTip(
				f"Show only shapes colored {color_name}.\n"
				"Toggle on to filter; toggle off to clear.\n"
				"Multiple colors can be combined."
			)
			swatch.setStyleSheet(
				f"QPushButton {{ background-color: {color_hex}; border: 1px solid #222; border-radius: 2px; }}"
				f"QPushButton:checked {{ border: 2px solid #ffffff; }}"
			)
			swatch.toggled.connect(self._on_color_filter_swatch_toggled)
			self._color_filter_swatch_buttons.append(swatch)
			self._color_filter_swatch_colors[swatch] = color_hex
			color_filter_row.addWidget(swatch, 1)
		# No Color swatch (shows an empty/transparent box).
		self._no_color_swatch = QPushButton()
		self._no_color_swatch.setCheckable(True)
		self._no_color_swatch.setChecked(False)
		self._no_color_swatch.setMinimumWidth(12)
		self._no_color_swatch.setFixedHeight(18)
		self._no_color_swatch.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
		self._no_color_swatch.setToolTip(
			"Show only shapes with no custom color assigned.\n"
			"Toggle on to filter; toggle off to clear.\n"
			"Can be combined with color filters."
		)
		# Match the default text color from the application palette.
		default_text_color = QGuiApplication.palette().color(QPalette.WindowText).name()
		self._no_color_swatch.setStyleSheet(
			f"QPushButton {{ background-color: {default_text_color}; border: 1px solid #222; border-radius: 2px; }}"
			"QPushButton:checked { border: 2px solid #4ba66d; }"
		)
		self._no_color_swatch.toggled.connect(self._on_color_filter_swatch_toggled)
		self._color_filter_swatch_buttons.append(self._no_color_swatch)
		self._color_filter_swatch_colors[self._no_color_swatch] = None
		color_filter_row.addWidget(self._no_color_swatch, 1)
		shapes_layout.addLayout(color_filter_row)

		shapes_layout.addWidget(self.shapes_view, 1)
		shapes_footer_layout = QVBoxLayout()
		shapes_footer_layout.setContentsMargins(0, 0, 0, 0)
		shapes_footer_layout.setSpacing(0)
		self.shapes_info = QLabel("Items: 0")
		shapes_footer_layout.addWidget(self.shapes_info)
		shapes_layout.addLayout(shapes_footer_layout)

		third_column_panel = QWidget()
		self._allow_horizontal_collapse(third_column_panel)
		third_column_layout = QVBoxLayout(third_column_panel)
		third_column_layout.setContentsMargins(0, 0, 0, 0)
		third_column_layout.setSpacing(self.COMPACT_SPACING)
		third_column_splitter = QSplitter(Qt.Vertical)
		third_column_splitter.setChildrenCollapsible(True)
		third_column_splitter.setHandleWidth(2)
		third_column_layout.addWidget(third_column_splitter, 1)

		primary_drop_section = QGroupBox("Sliders Drop Box")
		primary_drop_layout = QVBoxLayout(primary_drop_section)
		self._compact_layout(primary_drop_layout, margin=self.COMPACT_MARGIN)
		primary_drop_toolbar = QHBoxLayout()
		self._compact_layout(primary_drop_toolbar)
		self.primary_drop_get_active_button = QPushButton("Get Active")
		self._prepare_toolbar_button(self.primary_drop_get_active_button)
		primary_drop_toolbar.addWidget(self.primary_drop_get_active_button)
		primary_drop_toolbar.addStretch(1)
		primary_drop_layout.addLayout(primary_drop_toolbar)
		self.primary_drop_view = PrimaryDropListView(
			self._on_primary_drop_list_dropped,
			self._on_primary_drop_remove_requested,
		)
		self._allow_horizontal_collapse(self.primary_drop_view)
		self.primary_drop_view.setSelectionMode(QAbstractItemView.ExtendedSelection)
		self.primary_drop_view.setModel(self._primary_subset_proxy)
		self._primary_drop_delegate = SliderItemDelegate(self.primary_drop_view)
		self.primary_drop_view.setItemDelegate(self._primary_drop_delegate)
		primary_drop_layout.addWidget(self.primary_drop_view, 1)

		work_shapes_section = QGroupBox("Work Shapes")
		work_shapes_layout = QVBoxLayout(work_shapes_section)
		self._compact_layout(work_shapes_layout, margin=self.COMPACT_MARGIN)
		work_toolbar = QHBoxLayout()
		self._compact_layout(work_toolbar)
		#work_toolbar.addWidget(QLabel("Tools"))
		self.work_add_button = self._create_work_tool_button("Add", ADD_ICON)
		self.work_add_button.setToolTip("Add a new work blendshape target")
		work_toolbar.addWidget(self.work_add_button)
		self.work_remove_button = self._create_work_tool_button("Remove", DELETE_ICON)
		self.work_remove_button.setToolTip("Remove selected work blendshape targets")
		work_toolbar.addWidget(self.work_remove_button)
		self.work_paint_button = self._create_work_tool_button("Paint Weights", MASK_ICON)
		self.work_paint_button.setToolTip("Paint selected work blendshape target")
		work_toolbar.addWidget(self.work_paint_button)
		self.apply_work_shapes_button = self._create_work_tool_button("Apply All", COMMIT_ICON)
		self.apply_work_shapes_button.setToolTip("Apply changes to all linked work blendshape targets")
		work_toolbar.addWidget(self.apply_work_shapes_button)
		work_toolbar.addStretch(1)
		work_shapes_layout.addLayout(work_toolbar)
		self.work_shapes_view = WorkShapesListView(
			self._on_work_shape_drop_received,
			self._on_work_shape_duplicate_requested,
			self._on_work_shape_extract_requested,
			self._on_work_shape_break_link_requested,
			self._on_work_shape_copy_weights_requested,
			self._on_work_shape_paste_weights_requested,
			self._on_work_shape_paste_inverted_weights_requested,
			self._on_work_shape_add_copied_weights_requested,
			self._on_work_shape_subtract_copied_weights_requested,
			self._on_work_shapes_normalize_weights_requested,
			self._on_work_shape_clear_weights_requested,
			self._has_copied_work_weight_map_values,
			lambda: self.current_editor is not None and self.current_editor.skin_cluster is None,
		)
		self._allow_horizontal_collapse(self.work_shapes_view)
		self.work_shapes_view.setSelectionMode(QAbstractItemView.ExtendedSelection)
		self.work_shapes_view.setModel(self._work_shape_model)
		self._work_shapes_delegate = SliderItemDelegate(self.work_shapes_view)
		self.work_shapes_view.setItemDelegate(self._work_shapes_delegate)
		work_shapes_layout.addWidget(self.work_shapes_view, 1)

		active_shapes_section = QGroupBox("Active Shapes")
		active_shapes_layout = QVBoxLayout(active_shapes_section)
		self._compact_layout(active_shapes_layout, margin=self.COMPACT_MARGIN)
		self.active_shapes_search = TokenSearchBar("Filter active shapes...")
		active_shapes_layout.addWidget(self.active_shapes_search)
		self.active_shapes_view = SliderListView()
		self._allow_horizontal_collapse(self.active_shapes_view)
		self.active_shapes_view.setSelectionMode(QAbstractItemView.ExtendedSelection)
		self.active_shapes_view.setDragEnabled(True)
		self.active_shapes_view.setDragDropMode(QAbstractItemView.DragOnly)
		self.active_shapes_view.setModel(self._active_shapes_proxy)
		self.active_shapes_view.setContextMenuPolicy(Qt.CustomContextMenu)
		self._active_shapes_delegate = SliderItemDelegate(self.active_shapes_view)
		self.active_shapes_view.setItemDelegate(self._active_shapes_delegate)
		active_shapes_layout.addWidget(self.active_shapes_view, 1)
		active_shapes_footer_layout = QVBoxLayout()
		active_shapes_footer_layout.setContentsMargins(0, 0, 0, 0)
		active_shapes_footer_layout.setSpacing(0)
		self.active_shapes_info = QLabel("Items: 0")
		active_shapes_footer_layout.addWidget(self.active_shapes_info)
		active_shapes_layout.addLayout(active_shapes_footer_layout)

		third_column_splitter.addWidget(primary_drop_section)
		third_column_splitter.addWidget(work_shapes_section)
		third_column_splitter.addWidget(active_shapes_section)
		third_column_splitter.setStretchFactor(0, 1)
		third_column_splitter.setStretchFactor(1, 1)
		third_column_splitter.setStretchFactor(2, 1)
		third_column_splitter.setSizes([260, 260, 260])
		self._third_column_splitter = third_column_splitter
		self._third_column_sections = [primary_drop_section, work_shapes_section, active_shapes_section]

		splitter.addWidget(primaries_panel)
		splitter.addWidget(shapes_panel)
		splitter.addWidget(third_column_panel)
		splitter.setStretchFactor(0, 1)
		splitter.setStretchFactor(1, 1)
		splitter.setStretchFactor(2, 2)
		QTimer.singleShot(0, self._update_shapes_header_compact_mode)

		self.status_bar = QStatusBar(self)
		self.setStatusBar(self.status_bar)
		self.status_bar.showMessage("Ready")

	def showEvent(self, event):  # noqa: N802
		super().showEvent(event)
		self._schedule_initial_splitter_layout()

	def _schedule_initial_splitter_layout(self) -> None:
		if not self._initial_splitter_layout_applied:
			self._initial_splitter_layout_timer.start(50)

	def _apply_initial_splitter_layout(self) -> None:
		if (
			self._main_splitter is None
			or self._editor_splitter is None
			or self._third_column_splitter is None
		):
			return
		if (
			self._main_splitter.width() <= 0
			or self._editor_splitter.width() <= 0
			or self._third_column_splitter.height() <= 0
		):
			self._schedule_initial_splitter_layout()
			return

		self._initial_splitter_layout_applied = True
		if self._main_splitter is not None:
			self._main_splitter.setSizes([self._tools_panel_compact_width, 1220])
		if self._editor_splitter is not None:
			self._editor_splitter.setSizes([1, 1, 1])
		if self._third_column_splitter is not None:
			self._third_column_splitter.setSizes([500, 500, 500])
		self._force_tools_panel_startup_compact_mode()
		self._update_third_column_section_minimums()
		self._update_shapes_header_compact_mode()

	def _build_split_settings_tab(self, parent_widget: QWidget) -> None:
		layout = QVBoxLayout(parent_widget)
		self._compact_layout(layout, margin=self.COMPACT_MARGIN)
		split_settings_splitter = QSplitter(Qt.Horizontal)
		split_settings_splitter.setChildrenCollapsible(False)
		split_settings_splitter.setHandleWidth(2)
		layout.addWidget(split_settings_splitter, 1)

		primaries_group = QGroupBox("Primary Split Group Assignments")
		self._allow_horizontal_collapse(primaries_group)
		primaries_layout = QVBoxLayout(primaries_group)
		self._compact_layout(primaries_layout, margin=self.COMPACT_MARGIN)
		self.split_primary_search = TokenSearchBar("Search primaries...")
		primaries_layout.addWidget(self.split_primary_search)
		self.split_primaries_tree = SplitPrimaryAssignmentsView()
		self._allow_horizontal_collapse(self.split_primaries_tree)
		self.split_primaries_tree.set_source_model(self._shape_model)
		self.split_primaries_tree.setAlternatingRowColors(True)
		self.split_primaries_tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
		self.split_primaries_tree.setEditTriggers(QAbstractItemView.NoEditTriggers)
		self.split_primaries_tree.setIndentation(0)
		self.split_primaries_tree.setStyleSheet("QTreeView::item { padding-top: 1px; padding-bottom: 1px; }")
		self._split_primary_slider_delegate = SliderItemDelegate(self.split_primaries_tree)
		self.split_primaries_tree.setItemDelegateForColumn(0, self._split_primary_slider_delegate)
		primaries_layout.addWidget(self.split_primaries_tree, 1)
		split_settings_splitter.addWidget(primaries_group)

		right_column = QWidget(parent_widget)
		self._allow_horizontal_collapse(right_column)
		right_column.setMaximumWidth(self.SPLIT_PANELS_MAX_WIDTH)
		right_layout = QVBoxLayout(right_column)
		right_layout.setContentsMargins(0, 0, 0, 0)
		right_layout.setSpacing(self.COMPACT_SPACING)

		split_groups_maps_splitter = QSplitter(Qt.Horizontal)
		split_groups_maps_splitter.setChildrenCollapsible(False)
		split_groups_maps_splitter.setHandleWidth(2)
		right_layout.addWidget(split_groups_maps_splitter, 1)

		split_groups_group = QGroupBox("Split Groups")
		self._allow_horizontal_collapse(split_groups_group)
		split_groups_layout = QHBoxLayout(split_groups_group)
		self._compact_layout(split_groups_layout, margin=self.COMPACT_MARGIN)
		split_groups_splitter = QSplitter(Qt.Horizontal)
		split_groups_splitter.setChildrenCollapsible(False)
		split_groups_splitter.setHandleWidth(2)
		split_groups_layout.addWidget(split_groups_splitter, 1)
		split_groups_maps_splitter.addWidget(split_groups_group)

		split_group_controls_widget = QWidget()
		self._allow_horizontal_collapse(split_group_controls_widget)
		split_group_controls = QVBoxLayout(split_group_controls_widget)
		self._compact_layout(split_group_controls)
		self.split_group_add_button = QPushButton("Add Group")
		self.split_group_add_button.setIcon(ADD_ICON)
		self.split_group_remove_button = QPushButton("Remove Group")
		self.split_group_remove_button.setIcon(DELETE_ICON)
		self.split_group_rename_button = QPushButton("Rename Group")
		self.split_group_rename_button.setIcon(RENAME_ICON)
		self._split_group_buttons = [
			self.split_group_add_button,
			self.split_group_rename_button,
			self.split_group_remove_button,
		]
		self._split_group_button_labels = {
			button: button.text() for button in self._split_group_buttons
		}
		for button in self._split_group_buttons:
			button.setToolTip(self._split_group_button_labels[button])
			button.setMinimumWidth(0)
			button.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
			button.setStyleSheet("text-align: left; padding-left: 2px;")
			button.setIconSize(self._tools_panel_expanded_icon_size)
			button.setFixedHeight(26)
			split_group_controls.addWidget(button)
		split_group_controls.addStretch(1)
		split_groups_splitter.addWidget(split_group_controls_widget)

		split_groups_tree_widget = QWidget()
		self._allow_horizontal_collapse(split_groups_tree_widget)
		split_groups_tree_layout = QVBoxLayout(split_groups_tree_widget)
		self._compact_layout(split_groups_tree_layout)
		self.split_groups_tree = SplitGroupsTree()
		self._allow_horizontal_collapse(self.split_groups_tree)
		self.split_groups_tree.setToolTip(
			"Select a group or map; drop maps onto groups, drag to reorder, or drag out to remove"
		)
		split_groups_tree_layout.addWidget(self.split_groups_tree, 1)
		self.split_groups_frame_layout = FrameLayout("Split Group Preview")
		split_groups_tree_layout.addWidget(self.split_groups_frame_layout)
		self.split_group_preview_label = QLabel()
		self.split_group_preview_label.setWordWrap(True)
		self.split_group_preview_label.setMinimumWidth(0)
		self.split_groups_frame_layout.addWidget(self.split_group_preview_label)
		split_groups_splitter.addWidget(split_groups_tree_widget)

		split_maps_browser_group = QGroupBox("Split Maps")
		self._allow_horizontal_collapse(split_maps_browser_group)
		split_maps_group_layout = QHBoxLayout(split_maps_browser_group)
		self._compact_layout(split_maps_group_layout, margin=self.COMPACT_MARGIN)
		split_maps_lists_splitter = QSplitter(Qt.Horizontal)
		split_maps_lists_splitter.setChildrenCollapsible(False)
		split_maps_lists_splitter.setHandleWidth(2)
		split_maps_group_layout.addWidget(split_maps_lists_splitter, 1)
		split_groups_maps_splitter.addWidget(split_maps_browser_group)

		split_map_controls_widget = QWidget()
		self._allow_horizontal_collapse(split_map_controls_widget)
		split_map_controls = QVBoxLayout(split_map_controls_widget)
		self._compact_layout(split_map_controls)
		self.split_map_add_button = QPushButton("Add Split Map")
		self.split_map_add_button.setIcon(ADD_ICON)
		self.split_map_rename_button = QPushButton("Rename Split Map")
		self.split_map_rename_button.setIcon(RENAME_ICON)
		self.split_map_remove_button = QPushButton("Remove Split Map")
		self.split_map_remove_button.setIcon(DELETE_ICON)
		self.split_map_check_normalization_button = QPushButton("Check Normalization")
		self.split_map_check_normalization_button.setIcon(NORMALIZE_ICON)
		self.split_map_edit_button = QPushButton("Edit Split Map")
		self.split_map_edit_button.setIcon(EDIT_SPLIT_MAP_ICON)
		self.split_map_weight_add_button = QPushButton("Add Weight")
		self.split_map_weight_add_button.setIcon(ADD_ICON)
		self.split_map_weight_rename_button = QPushButton("Rename Weight")
		self.split_map_weight_rename_button.setIcon(RENAME_ICON)
		self.split_map_weight_remove_button = QPushButton("Remove Weight")
		self.split_map_weight_remove_button.setIcon(DELETE_ICON)
		self.split_map_paint_mask_button = QPushButton("Paint Weight Mask")
		self.split_map_paint_mask_button.setIcon(MASK_ICON)
		self.split_map_weight_normalize_button = QPushButton("Normalize Weights")
		self.split_map_weight_normalize_button.setIcon(NORMALIZE_ICON)
		self.split_map_weight_apply_button = QPushButton("Apply Edits")
		self.split_map_weight_apply_button.setIcon(COMMIT_ICON)
		self.split_map_weight_cancel_button = QPushButton("Cancel Edits")
		self.split_map_weight_cancel_button.setIcon(DELETE_ICON)
		self._split_map_buttons = [
			self.split_map_add_button,
			self.split_map_rename_button,
			self.split_map_remove_button,
			self.split_map_check_normalization_button,
		]
		self._split_map_button_labels = {
			button: button.text() for button in self._split_map_buttons
		}
		for button in self._split_map_buttons:
			button.setToolTip(self._split_map_button_labels[button])
			button.setMinimumWidth(0)
			button.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
			button.setStyleSheet("text-align: left; padding-left: 2px;")
			button.setIconSize(self._tools_panel_expanded_icon_size)
			button.setFixedHeight(26)
			split_map_controls.addWidget(button)
		split_map_controls.addStretch(1)
		split_maps_lists_splitter.addWidget(split_map_controls_widget)

		split_maps_browser_widget = QWidget()
		self._allow_horizontal_collapse(split_maps_browser_widget)
		split_maps_browser_layout = QVBoxLayout(split_maps_browser_widget)
		self._compact_layout(split_maps_browser_layout)
		self.split_maps_list = SplitMapsTree()
		self._allow_horizontal_collapse(self.split_maps_list)
		self.split_maps_list.setSelectionMode(QAbstractItemView.SingleSelection)
		self.split_maps_list.setToolTip("All split maps; drag a map onto a group in the tree")
		self.split_maps_list.setContextMenuPolicy(Qt.CustomContextMenu)
		self.split_maps_list.setItemDelegate(SplitMapStatusDelegate(self.split_maps_list))
		split_maps_browser_layout.addWidget(self.split_maps_list, 1)
		self.split_map_weight_stats_label = QLabel("Press Check Normalization to check split maps.")
		split_maps_browser_layout.addWidget(self.split_map_weight_stats_label)
		split_maps_lists_splitter.addWidget(split_maps_browser_widget)
		split_maps_lists_splitter.setStretchFactor(0, 0)
		split_maps_lists_splitter.setStretchFactor(1, 1)

		split_groups_splitter.setStretchFactor(0, 0)
		split_groups_splitter.setStretchFactor(1, 1)
		split_groups_maps_splitter.setStretchFactor(0, 1)
		split_groups_maps_splitter.setStretchFactor(1, 1)
		self._split_groups_group_widget = split_groups_group
		self._split_groups_splitter = split_groups_splitter
		self._split_group_controls_widget = split_group_controls_widget
		self._split_maps_lists_splitter = split_maps_lists_splitter
		self._split_map_controls_widget = split_map_controls_widget
		self._split_group_buttons_expanded_width = max(
			button.sizeHint().width() for button in self._split_group_buttons
		)
		self._split_map_buttons_expanded_width = max(
			button.sizeHint().width() for button in self._split_map_buttons
		)

		split_maps_group = QGroupBox("Split Map Editor")
		self._allow_horizontal_collapse(split_maps_group)
		self._split_map_editor_group_widget = split_maps_group
		split_maps_group.setEnabled(False)
		split_maps_layout = QVBoxLayout(split_maps_group)
		self._compact_layout(split_maps_layout, margin=self.COMPACT_MARGIN)

		split_map_weights_splitter = QSplitter(Qt.Horizontal)
		split_map_weights_splitter.setChildrenCollapsible(False)
		split_map_weights_splitter.setHandleWidth(2)
		split_map_weight_controls_widget = QWidget()
		self._allow_horizontal_collapse(split_map_weight_controls_widget)
		split_map_weight_controls = QVBoxLayout(split_map_weight_controls_widget)
		self._compact_layout(split_map_weight_controls)
		self._split_map_weight_buttons = [
			self.split_map_edit_button,
			self.split_map_weight_add_button,
			self.split_map_weight_rename_button,
			self.split_map_weight_remove_button,
			self.split_map_paint_mask_button,
			self.split_map_weight_normalize_button,
		]
		self._split_map_weight_button_labels = {
			button: button.text() for button in self._split_map_weight_buttons
		}
		for button in self._split_map_weight_buttons:
			button.setToolTip(self._split_map_weight_button_labels[button])
			button.setMinimumWidth(0)
			button.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
			button.setStyleSheet("text-align: left; padding-left: 2px;")
			button.setIconSize(self._tools_panel_expanded_icon_size)
			button.setFixedHeight(26)
			split_map_weight_controls.addWidget(button)
		split_map_weight_controls.addStretch(1)
		split_map_weights_splitter.addWidget(split_map_weight_controls_widget)

		split_map_weights_column_widget = QWidget()
		self._allow_horizontal_collapse(split_map_weights_column_widget)
		split_map_weights_column = QVBoxLayout()
		split_map_weights_column_widget.setLayout(split_map_weights_column)
		self._compact_layout(split_map_weights_column)
		self.split_map_weights_list = SplitMapWeightsList()
		self._allow_horizontal_collapse(self.split_map_weights_list)
		self.split_map_weights_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
		self.split_map_weights_list.setSelectionMode(QAbstractItemView.SingleSelection)
		self.split_map_weights_list.setToolTip("Select a split-map weight or drag its slider to set the edit blendshape value")
		self.split_map_weights_list.setContextMenuPolicy(Qt.CustomContextMenu)
		self._split_map_weight_slider_delegate = SplitMapWeightSliderDelegate(self.split_map_weights_list)
		self.split_map_weights_list.setItemDelegate(self._split_map_weight_slider_delegate)
		split_map_weight_operations = QHBoxLayout()
		self._compact_layout(split_map_weight_operations)
		operation_specs = [
			(SOFT_MOD_ICON, "Convert Soft Selection to Split Weight Map", "convert_soft_selection_to_edit_split_weight_map", "Converted soft selection to", False),
			(COPY_WEIGHTS_ICON, "Copy Weight Map", "copy_edit_split_weight_map_values", "Copied", False),
			(PASTE_WEIGHTS_ICON, "Paste Weight Map", "paste_edit_split_weight_map_values", "Pasted", True),
			(PASTE_INVERTED_WEIGHTS_ICON, "Paste Inverted", "paste_inverted_edit_split_weight_map_values", "Pasted inverted values to", True),
			(PASTE_ADD_WEIGHTS_ICON, "Add Copied Weights", "add_edit_split_weight_map_values", "Added copied values to", True),
			(PASTE_MINUS_WEIGHTS_ICON, "Subtract Copied Weights", "subtract_edit_split_weight_map_values", "Subtracted copied values from", True),
			(PASTE_MULTIPLY_WEIGHTS_ICON, "Multiply by Copied Weights", "paste_multiplied_edit_split_weight_map_values", "Multiplied", True),
		]
		for icon, tooltip, method_name, status_verb, requires_copy in operation_specs:
			button = QPushButton()
			button.setIcon(icon)
			button.setIconSize(self._tools_panel_expanded_icon_size)
			button.setFixedSize(26, 26)
			button.setToolTip(tooltip)
			button.clicked.connect(
				lambda _checked=False, method_name=method_name, status_verb=status_verb:
				self._run_split_weight_map_operation(method_name, status_verb)
			)
			self._split_map_weight_operation_buttons.append(button)
			if requires_copy:
				self._split_map_weight_paste_operation_buttons.append(button)
			split_map_weight_operations.addWidget(button)
		split_map_weight_operations.addStretch(1)
		split_map_weights_column.addLayout(split_map_weight_operations)
		split_map_weights_column.addWidget(self.split_map_weights_list, 1)
		split_map_edit_actions = QHBoxLayout()
		self._compact_layout(split_map_edit_actions)
		self.split_map_weight_apply_button.setToolTip("Apply split-map weight edits")
		self.split_map_weight_cancel_button.setToolTip("Cancel split-map weight edits")
		split_map_edit_actions.addWidget(self.split_map_weight_apply_button, 1)
		split_map_edit_actions.addWidget(self.split_map_weight_cancel_button, 1)
		split_map_weights_column.addLayout(split_map_edit_actions)
		split_map_weights_splitter.addWidget(split_map_weights_column_widget)
		split_map_weights_splitter.setStretchFactor(0, 0)
		split_map_weights_splitter.setStretchFactor(1, 1)
		split_maps_layout.addWidget(split_map_weights_splitter, 1)
		self._split_map_weights_column_widget = split_map_weights_splitter
		self._split_map_weights_splitter = split_map_weights_splitter
		self._split_map_weight_controls_widget = split_map_weight_controls_widget
		self._split_map_weight_buttons_expanded_width = max(
			button.sizeHint().width() for button in self._split_map_weight_buttons
		)
		shared_controls_width = max(
			self._split_group_buttons_expanded_width,
			self._split_map_buttons_expanded_width,
		)
		self._split_group_buttons_expanded_width = shared_controls_width
		self._split_map_buttons_expanded_width = shared_controls_width
		self._set_split_group_buttons_compact_mode(True)
		self._set_split_map_buttons_compact_mode(True)
		self._set_split_map_weight_buttons_compact_mode(True)
		split_groups_maps_splitter.setSizes([500, 500])
		split_groups_splitter.setSizes([30, 500])
		split_maps_lists_splitter.setSizes([30, 500])
		split_map_weights_splitter.setSizes([30, 500])

		split_map_labels_layout = QHBoxLayout()
		self._compact_layout(split_map_labels_layout)
		self.split_map_weights_label = QLabel("Editing Split Map: None")
		split_map_labels_layout.addWidget(self.split_map_weights_label)
		split_maps_layout.addLayout(split_map_labels_layout)
		right_layout.addWidget(split_maps_group, 1)

		split_settings_splitter.addWidget(right_column)
		split_settings_splitter.setStretchFactor(0, 1)
		split_settings_splitter.setStretchFactor(1, 1)
		split_settings_splitter.setSizes([500, 500])

	def _apply_primaries_branch_icons(self) -> None:
		"""Use fixed-size item icons for folders; hide branch glyphs tied to indentation."""
		closed_icon = os.path.abspath(os.path.join(env.ICONS_PATH, "tree_chevron_right.svg")).replace("\\", "/")
		open_icon = os.path.abspath(os.path.join(env.ICONS_PATH, "tree_chevron_down.svg")).replace("\\", "/")
		if os.path.exists(closed_icon):
			self._primary_tree_folder_closed_icon = QIcon(closed_icon)
		if os.path.exists(open_icon):
			self._primary_tree_folder_open_icon = QIcon(open_icon)
		self.primaries_view.setIconSize(QSize(14, 14))
		self.primaries_view.setStyleSheet(
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

	def _is_primary_tree_folder_item(self, item: Optional[QTreeWidgetItem]) -> bool:
		if item is None:
			return False
		if item.data(0, self.PRIMARY_TREE_NAME_ROLE):
			return False
		return bool(item.childCount())

	def _update_primary_tree_folder_icon(self, item: Optional[QTreeWidgetItem]) -> None:
		if not self._is_primary_tree_folder_item(item):
			return
		if item.isExpanded() and not self._primary_tree_folder_open_icon.isNull():
			item.setIcon(0, self._primary_tree_folder_open_icon)
		elif not self._primary_tree_folder_closed_icon.isNull():
			item.setIcon(0, self._primary_tree_folder_closed_icon)

	def _on_primaries_item_expanded(self, item: QTreeWidgetItem) -> None:
		self._update_primary_tree_folder_icon(item)

	def _on_primaries_item_collapsed(self, item: QTreeWidgetItem) -> None:
		self._update_primary_tree_folder_icon(item)

	def _on_primaries_item_clicked(self, item: QTreeWidgetItem, column: int) -> None:
		"""Toggle folder expansion on single click when branch glyphs are hidden."""
		if column != 0:
			return
		if not self._is_primary_tree_folder_item(item):
			return
		item.setExpanded(not item.isExpanded())

	def _on_primaries_item_double_clicked(self, item: QTreeWidgetItem, column: int) -> None:
		"""Set a double-clicked primary tree leaf to its defined pose."""
		if self.current_editor is None:
			self._set_status("No system selected.", warning=True)
			return
		if item is None or column != 0:
			return
		primary_name = item.data(0, self.PRIMARY_TREE_NAME_ROLE)
		if not primary_name:
			return
		self._set_shape_pose_by_name(str(primary_name))

	def _show_primaries_context_menu(self, pos) -> None:
		if self.current_editor is None:
			return
		item = self.primaries_view.itemAt(pos)
		if item is None:
			return

		primary_name = item.data(0, self.PRIMARY_TREE_NAME_ROLE)
		if not primary_name:
			return
		if not item.isSelected():
			self.primaries_view.clearSelection()
			item.setSelected(True)

		primary_name = str(primary_name)
		menu = QMenu(self.primaries_view)
		rename_action = menu.addAction("Rename")
		menu.addSeparator()
		add_inbetween_action = menu.addAction("Add Inbetween")
		split_selected_action = menu.addAction("Split selected shapes")
		menu.addSeparator()
		delete_action = menu.addAction("Delete")
		if hasattr(menu, "exec"):
			selected_action = menu.exec(self.primaries_view.viewport().mapToGlobal(pos))
		else:
			selected_action = menu.exec_(self.primaries_view.viewport().mapToGlobal(pos))

		if selected_action == rename_action:
			self._begin_inline_primary_rename(item)
		elif selected_action == add_inbetween_action:
			self._on_add_inbetween_requested(primary_name)
		elif selected_action == split_selected_action:
			self._split_selected_shapes(self._selected_primary_tree_names())
		elif selected_action == delete_action:
			self.remove_selected_primaries()

	def _on_add_inbetween_requested(self, primary_name: str) -> None:
		if self.current_editor is None:
			self._set_status("No system selected.", warning=True)
			return

		primary_value = self._get_primary_tree_value(primary_name)
		default_inbetween_value = 50
		if primary_value is not None:
			default_inbetween_value = int(float(primary_value) * 100.0)
		default_inbetween_value = max(0, min(99, default_inbetween_value))

		value, ok = QInputDialog.getInt(
			self,
			"Add Inbetween",
			f"Enter 2-digit inbetween value for '{primary_name}':",
			default_inbetween_value,
			0,
			99,
		)
		if not ok:
			self._set_status("Add inbetween cancelled.")
			return

		inbetween_suffix = f"{int(value):02d}"
		inbetween_name = f"{primary_name}{inbetween_suffix}"

		try:
			self._stop_active_blendshape_trackers()
			self.current_editor.add_new_inbetween_shape(inbetween_name)
		except Exception as exc:
			self._set_status(f"Error adding inbetween shape: {exc}", error=True)
			return
		finally:
			self._start_active_blendshape_trackers()

		self._reload_shapes_from_editor()
		self._set_shape_pose_by_name(inbetween_name)
		selected = self._select_shape_in_shapes_tree(inbetween_name, ensure_visible=True)
		if selected:
			self._set_status(f"Added inbetween shape '{inbetween_name}', selected it, and set its pose.")
		else:
			self._set_status(
				f"Added inbetween shape '{inbetween_name}' and set its pose, but could not select it in Shapes.",
				warning=True,
			)

	def _begin_inline_primary_rename(self, item: QTreeWidgetItem) -> None:
		if self.current_editor is None or item is None:
			return
		shape_name = item.data(0, self.PRIMARY_TREE_NAME_ROLE)
		if not shape_name:
			return
		old_name = str(shape_name)

		if self._primary_rename_editor is not None:
			self._cancel_inline_primary_rename()

		name_index = self.primaries_view.indexFromItem(item, 0)
		item_rect = self.primaries_view.visualRect(name_index)
		if not item_rect.isValid():
			return

		editor = InlineWorkshapeRenameEditor(self.primaries_view.viewport())
		editor.setText(old_name)
		editor.setFrame(False)
		editor.setTextMargins(0, 0, 0, 0)
		editor.setStyleSheet("QLineEdit { border: 0px; padding: 0px; margin: 0px; background: black; color: white; }")
		editor.setGeometry(item_rect)
		editor.selectAll()
		editor.show()
		editor.setFocus(Qt.MouseFocusReason)

		self._primary_rename_editor = editor
		self._primary_rename_old_name = old_name
		editor.submitted.connect(self._commit_inline_primary_rename)
		editor.canceled.connect(self._cancel_inline_primary_rename)

	def _cancel_inline_primary_rename(self) -> None:
		editor = self._primary_rename_editor
		self._primary_rename_editor = None
		self._primary_rename_old_name = ""
		if editor is not None:
			editor.deleteLater()

	def _commit_inline_primary_rename(self) -> None:
		editor = self._primary_rename_editor
		old_name = self._primary_rename_old_name
		self._primary_rename_editor = None
		self._primary_rename_old_name = ""
		if editor is None:
			return

		new_name = (editor.text() or "").strip()
		editor.deleteLater()

		if self.current_editor is None or not old_name:
			return
		if not new_name or new_name == old_name:
			return

		try:
			self._stop_active_blendshape_trackers()
			self.current_editor.rename_primary_shape(old_name, new_name)
		except Exception as exc:
			self._set_status(f"Error renaming primary shape: {exc}", error=True)
			return
		finally:
			self._start_active_blendshape_trackers()

		self._reload_shapes_from_editor()
		renamed_item = self._primary_tree_items.get(new_name)
		if renamed_item is not None:
			self.primaries_view.clearSelection()
			renamed_item.setSelected(True)
			self.primaries_view.setCurrentItem(renamed_item)
			self.primaries_view.scrollToItem(renamed_item)
		self._set_status(f"Renamed primary shape '{old_name}' to '{new_name}'.")

	def _build_tools_panel(self, parent_layout) -> None:
		tools_group = QGroupBox()
		self._tools_group = tools_group
		tools_group.setContentsMargins(0, 0, 0, 0)
		tools_group.setMinimumWidth(self._tools_panel_compact_width)
		tools_group.setMaximumWidth(self._tools_panel_expanded_width)
		tools_group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
		parent_layout.addWidget(tools_group)

		self.tool_buttons = []
		self._tools_panel_buttons = []
		self._tools_panel_button_labels = {}
		self._tools_panel_sections = []
		self._tools_panel_section_labels = {}
		main_tools_layout = QVBoxLayout(tools_group)
		self._compact_layout(main_tools_layout, margin=self.COMPACT_MARGIN)
		main_tools_layout.setSizeConstraint(QLayout.SetMinimumSize)

		self.mmtools_button = self._create_tool_button("MMTools", MMTOOLS_ICON, track_enabled=False)
		main_tools_layout.addWidget(self.mmtools_button)

		editor_frame_layout = FrameLayout("Editor")
		self._tools_panel_sections.append(editor_frame_layout)
		self._tools_panel_section_labels[editor_frame_layout] = "Editor"
		self.select_editor_button = self._create_tool_button("Select Controller", SELECT_ICON)
		self.controller_layout_button = self._create_tool_button("Controller Layout", CONTROLLER_LAYOUT_ICON)
		
		self.zero_all_button = self._create_tool_button("Zero All", ZERO_VALUE_ICON)
		self.rename_button = self._create_tool_button("Rename To Pose", RENAME_ICON)
		self.duplicate_button = self._create_tool_button("Duplicate Rename", DUPLICATE_ICON)
		editor_frame_layout.addWidget(self.select_editor_button)
		editor_frame_layout.addWidget(self.controller_layout_button)
		editor_frame_layout.addWidget(self.zero_all_button)
		editor_frame_layout.addWidget(self.rename_button)
		editor_frame_layout.addWidget(self.duplicate_button)

		edit_shapes_frame_layout = FrameLayout("Shapes Edit")
		self._tools_panel_sections.append(edit_shapes_frame_layout)
		self._tools_panel_section_labels[edit_shapes_frame_layout] = "Shapes Edit"
		self.add_primary_button = self._create_tool_button("Add/Commit New Primary", ADD_ICON)
		self.add_primary_button.setToolTip("Add selected mesh as a new primary shape.\n If there are no selected meshes, creates an empty primary shape that can be filled by copying values from an existing shape.")
		self.add_selected_at_current_pose_button = self._create_tool_button("Add/Commit At Current Pose", ADD_AT_POSE_ICON)
		self.add_selected_at_current_pose_button.setToolTip("Add the selected mesh at the current pose extrapolating the name from the active values in the controller.\nFor example: (lipCornerPuller, 0.5) (jawOpen, 1.0) -> lipCornerPuller50_jawOpen\nIf no mesh is selected an empty shape will be added.")
		self.commit_shapes_button = self._create_tool_button("Commit Selected", COMMIT_ICON)
		self.delete_shapes_button = self._create_tool_button("Delete Shapes", DELETE_ICON)
		self.delete_shapes_button.setFocusPolicy(Qt.NoFocus)
		self.delete_shapes_button.setToolTip("Delete the selected shapes from the focused Primaries or Shapes list")
		edit_shapes_frame_layout.addWidget(self.commit_shapes_button)
		edit_shapes_frame_layout.addWidget(self.add_primary_button)
		edit_shapes_frame_layout.addWidget(self.add_selected_at_current_pose_button)
		edit_shapes_frame_layout.addWidget(self.delete_shapes_button)


		preview_shapes_frame_layout = FrameLayout("Shapes Preview")
		self._tools_panel_sections.append(preview_shapes_frame_layout)
		self._tools_panel_section_labels[preview_shapes_frame_layout] = "Shapes Preview"
		self.unmute_all_shapes_button = self._create_tool_button("Unmute All Shapes", MUTE_OFF_ICON)
		preview_shapes_frame_layout.addWidget(self.unmute_all_shapes_button)
		self.unlock_all_shapes_button = self._create_tool_button("Unlock All Shapes", LOCK_OFF_ICON)
		preview_shapes_frame_layout.addWidget(self.unlock_all_shapes_button)
		self.toggle_hud_button = self._create_tool_button("Toggle HUD", HUD_ICON)
		preview_shapes_frame_layout.addWidget(self.toggle_hud_button)

		debug_shapes_frame_layout = FrameLayout("Debug")
		self._tools_panel_sections.append(debug_shapes_frame_layout)
		self._tools_panel_section_labels[debug_shapes_frame_layout] = "Debug"
		self.compare_shapes_button = self._create_tool_button("Compare Shapes", COMPARE_MESH_ICON)
		self.compare_shapes_button.setToolTip("Compare the shapes in the editor with meshes in the scene with the same name.")
		debug_shapes_frame_layout.addWidget(self.compare_shapes_button)

		main_tools_layout.addWidget(edit_shapes_frame_layout, 0)
		main_tools_layout.addWidget(editor_frame_layout, 0)
		main_tools_layout.addWidget(preview_shapes_frame_layout, 0)
		main_tools_layout.addWidget(debug_shapes_frame_layout, 0)
		for section in self._tools_panel_sections:
			section.layout.setSpacing(0)
			section.content_layout.setContentsMargins(0, 1, 0, 1)
			section.content_layout.setSpacing(1)
		main_tools_layout.addStretch(1)
		self._set_tools_panel_compact_mode(True, force=True)
		tools_group.setMinimumWidth(0)
		main_tools_layout.activate()
		self._tools_panel_compact_width = tools_group.minimumSizeHint().width()
		tools_group.setMinimumWidth(self._tools_panel_compact_width)

	def _create_tool_button(self, label: str, icon: Optional[QIcon] = None, *, track_enabled: bool = True) -> QPushButton:
		button = QPushButton(label)
		button.setStyleSheet("text-align: left; padding-left: 2px;")
		if icon is not None:
			button.setIcon(icon)
			button.setIconSize(self._tools_panel_expanded_icon_size)
		if track_enabled:
			self.tool_buttons.append(button)
		self._tools_panel_buttons.append(button)
		self._tools_panel_button_labels[button] = label
		if not button.toolTip():
			button.setToolTip(label)
		return button

	def _connect_ui_signals(self) -> None:
		self.refresh_button.clicked.connect(self.refresh_ui)
		self.create_system_button.clicked.connect(self._create_new_editor)
		self.dock_toggle_button.clicked.connect(self._toggle_docking)
		self.dock_close_button.clicked.connect(self.close)
		self.editor_combo.currentTextChanged.connect(self._on_editor_selected)
		if self.heat_map_switch is not None:
			self.heat_map_switch.toggled.connect(self._on_display_heat_map_toggled)
		if self.primaries_view.model() is not None:
			self.primaries_view.model().dataChanged.connect(self._on_primaries_tree_data_changed)
		self._primaries_delegate.valueDragStarted.connect(lambda: self._on_value_drag_state_changed(True))
		self._primaries_delegate.valueDragEnded.connect(lambda: self._on_value_drag_state_changed(False))
		if self._split_primary_slider_delegate is not None:
			self._split_primary_slider_delegate.valueDragStarted.connect(lambda: self._on_value_drag_state_changed(True))
			self._split_primary_slider_delegate.valueDragEnded.connect(lambda: self._on_value_drag_state_changed(False))
		self._shapes_delegate.muteToggleRequested.connect(self._on_shapes_mute_toggle_requested)
		self._shapes_delegate.lockToggleRequested.connect(self._on_shapes_lock_toggle_requested)
		self._active_shapes_delegate.muteToggleRequested.connect(self._on_active_shapes_mute_toggle_requested)
		self._active_shapes_delegate.lockToggleRequested.connect(self._on_active_shapes_lock_toggle_requested)
		self._primary_drop_delegate.muteToggleRequested.connect(self._on_primary_drop_mute_toggle_requested)
		self._primary_drop_delegate.lockToggleRequested.connect(self._on_primary_drop_lock_toggle_requested)
		self._work_shapes_delegate.muteToggleRequested.connect(self._on_work_shapes_mute_toggle_requested)
		self._work_shapes_delegate.connectedMeshRequested.connect(self._on_work_shape_connected_mesh_requested)
		self._work_shapes_delegate.workEditModeToggleRequested.connect(self._on_work_shape_edit_mode_toggle_requested)
		self.primaries_search.searchChanged.connect(self._on_primaries_search_changed)
		self.shapes_search.searchChanged.connect(self._on_shapes_search_changed)
		self.active_shapes_search.searchChanged.connect(self._on_active_shapes_search_changed)
		self.shapes_list_active_button.toggled.connect(self._filter_shapes_active)
		self.shapes_downstream_button.toggled.connect(self._filter_shapes_downstream)
		self.shapes_upstream_button.toggled.connect(self._filter_shapes_upstream)
		self.primary_drop_get_active_button.clicked.connect(self._fill_primary_drop_list_from_active)
		self.shapes_view.itemClicked.connect(self._on_shapes_item_clicked)
		self.shapes_view.itemSelectionChanged.connect(self._on_shapes_selection_changed)
		self.shapes_view.toggleUpstreamFilterRequested.connect(self._on_shapes_toggle_upstream_filter_requested)
		self.shapes_view.pageNavigationPoseRequested.connect(self._set_shape_pose_by_name)
		self.shapes_view.itemDoubleClicked.connect(self._on_shapes_double_clicked)
		self.shapes_view.itemExpanded.connect(self._on_shapes_item_expanded)
		self.shapes_view.itemCollapsed.connect(self._on_shapes_item_collapsed)
		self.shapes_view.customContextMenuRequested.connect(self._show_shapes_context_menu)
		if self.shapes_view.model() is not None:
			self.shapes_view.model().dataChanged.connect(self._on_shapes_tree_data_changed)
		self.active_shapes_view.customContextMenuRequested.connect(self._show_shapes_context_menu)
		self.active_shapes_view.clicked.connect(self._on_active_shapes_item_clicked)
		self.active_shapes_view.doubleClicked.connect(self._on_active_shapes_double_clicked)
		self.work_shapes_view.doubleClicked.connect(self._on_work_shapes_double_clicked)
		if self.active_shapes_view.selectionModel() is not None:
			self.active_shapes_view.selectionModel().selectionChanged.connect(self._on_active_shapes_selection_changed)
		self.select_editor_button.clicked.connect(self.select_face_ctrl)
		self.controller_layout_button.clicked.connect(self._show_controller_layout_window)
		self.zero_all_button.clicked.connect(self.zero_all)
		self.rename_button.clicked.connect(self.rename_selected_mesh)
		self.duplicate_button.clicked.connect(self.duplicate_at_value)
		self.add_primary_button.clicked.connect(self._on_add_primary_clicked)
		self.commit_shapes_button.clicked.connect(self.commit_selected)
		self.add_selected_at_current_pose_button.clicked.connect(self.add_selected_at_current_pose)
		self.delete_shapes_button.clicked.connect(self.remove_shapes_from_focused_view)
		self.unmute_all_shapes_button.clicked.connect(self.unmute_all_shapes)
		self.unlock_all_shapes_button.clicked.connect(self.unlock_all_shapes)
		self.compare_shapes_button.clicked.connect(self.compare_shapes_debug)
		self.mmtools_button.clicked.connect(self.launch_mmtools)
		self.toggle_hud_button.clicked.connect(self._on_toggle_hud_clicked)
		self._shape_model.primaryValueCommitted.connect(self._on_primary_value_committed)
		self._work_shape_model.valueCommitted.connect(self._on_work_shape_value_committed)
		self._shape_model.modelReset.connect(self._update_info_labels)
		self._shape_model.dataChanged.connect(self._on_shape_model_data_changed)
		self._shape_model.modelReset.connect(self._update_delegate_name_columns)
		self._primary_drop_delegate.valueDragStarted.connect(self._on_linked_drag_started)
		self._primary_drop_delegate.valueDragEnded.connect(self._on_linked_drag_ended)
		self._work_shapes_delegate.valueDragStarted.connect(self._on_linked_drag_started)
		self._work_shapes_delegate.valueDragEnded.connect(self._on_linked_drag_ended)
		self._primary_drop_delegate.valueDragDelta.connect(self._on_linked_drag_delta)
		self._work_shapes_delegate.valueDragDelta.connect(self._on_linked_drag_delta)
		self._primary_drop_delegate.valueDragSelectionContext.connect(self._on_linked_drag_selection_context)
		self._work_shapes_delegate.valueDragSelectionContext.connect(self._on_linked_drag_selection_context)
		self.work_add_button.clicked.connect(self._on_add_work_shape_clicked)
		self.work_remove_button.clicked.connect(self._on_remove_work_shapes_clicked)
		self.work_paint_button.clicked.connect(self._on_paint_work_shape_clicked)
		self.apply_work_shapes_button.clicked.connect(self._on_apply_work_shapes_clicked)
		if self.work_shapes_view.selectionModel() is not None:
			self.work_shapes_view.selectionModel().selectionChanged.connect(self._on_work_shapes_selection_changed)

		self.primaries_view.itemSelectionChanged.connect(self._on_primaries_selection_changed)
		self.exclusive_filter_action.toggled.connect(self._on_exclusive_filter_toggled)
		self.primaries_view.itemExpanded.connect(self._on_primaries_item_expanded)
		self.primaries_view.itemCollapsed.connect(self._on_primaries_item_collapsed)
		self.primaries_view.itemClicked.connect(self._on_primaries_item_clicked)
		self.primaries_view.pageNavigationPoseRequested.connect(self._set_shape_pose_by_name)
		self.primaries_view.itemDoubleClicked.connect(self._on_primaries_item_double_clicked)
		self.primaries_view.customContextMenuRequested.connect(self._show_primaries_context_menu)
		if self.split_primary_search is not None:
			self.split_primary_search.searchChanged.connect(self._on_split_primary_search_changed)
		if self.split_primaries_tree is not None:
			self.split_primaries_tree.assignmentChanged.connect(self._on_primary_split_group_changed)
			self.split_primaries_tree.model().dataChanged.connect(self._on_split_primaries_tree_data_changed)
			self.split_primaries_tree.setContextMenuPolicy(Qt.CustomContextMenu)
			self.split_primaries_tree.customContextMenuRequested.connect(self._show_split_primaries_context_menu)
		if self.split_groups_tree is not None:
			self.split_groups_tree.mapSelected.connect(self._on_split_group_map_selected)
			self.split_groups_tree.mapsChanged.connect(self._on_split_group_maps_changed)
			self.split_groups_tree.mapDraggedOut.connect(self._on_split_group_map_dragged_out)
			self.split_groups_tree.groupSelected.connect(self._on_split_group_selection_changed)
		if self.split_maps_list is not None:
			self.split_maps_list.currentMapChanged.connect(self._on_split_map_selection_changed)
			self.split_maps_list.customContextMenuRequested.connect(self._show_split_maps_context_menu)
		if self.split_map_weights_list is not None:
			self.split_map_weights_list.customContextMenuRequested.connect(self._show_split_map_weights_context_menu)
			self.split_map_weights_list.currentItemChanged.connect(self._on_split_map_weight_selection_changed)
			self.split_map_weights_list.model().dataChanged.connect(self._on_split_map_weight_value_changed)
		if hasattr(self, "split_group_add_button"):
			self.split_group_add_button.clicked.connect(self._on_create_split_group_clicked)
			self.split_group_remove_button.clicked.connect(self._on_remove_split_group_clicked)
			self.split_group_rename_button.clicked.connect(self._on_rename_split_group_clicked)
			self.split_map_add_button.clicked.connect(self._on_add_split_map_clicked)
			self.split_map_rename_button.clicked.connect(self._on_rename_split_map_clicked)
			self.split_map_remove_button.clicked.connect(self._on_remove_split_map_clicked)
			self.split_map_check_normalization_button.clicked.connect(lambda: self._check_split_maps_normalization(split_map_name=None))
			self.split_map_edit_button.clicked.connect(self._on_edit_split_map_clicked)
			self.split_map_weight_add_button.clicked.connect(self._on_add_split_map_weight_clicked)
			self.split_map_weight_rename_button.clicked.connect(self._on_rename_split_map_weight_clicked)
			self.split_map_weight_remove_button.clicked.connect(self._on_remove_split_map_weight_clicked)
			self.split_map_paint_mask_button.clicked.connect(self._on_paint_split_map_weight_mask_clicked)
			self.split_map_weight_normalize_button.clicked.connect(self._on_normalize_edit_split_map_weights_clicked)
			self.split_map_weight_apply_button.clicked.connect(self._on_apply_edit_split_map_clicked)
			self.split_map_weight_cancel_button.clicked.connect(self._on_cancel_edit_split_map_clicked)

		self._apply_shapes_name_sort()
		self._sort_primaries_tree()
		self._update_tools_button_panel()
		self._update_work_shape_button_panel()
		if self._main_splitter is not None:
			self._main_splitter.splitterMoved.connect(self._on_main_splitter_moved)
		if self._editor_splitter is not None:
			self._editor_splitter.splitterMoved.connect(self._on_editor_splitter_moved)
		if self._third_column_splitter is not None:
			self._third_column_splitter.splitterMoved.connect(self._on_third_column_splitter_moved)
		if self._split_groups_splitter is not None:
			self._split_groups_splitter.splitterMoved.connect(self._on_split_groups_splitter_moved)
		if self._split_maps_lists_splitter is not None:
			self._split_maps_lists_splitter.splitterMoved.connect(self._on_split_maps_splitter_moved)
		if self._split_map_weights_splitter is not None:
			self._split_map_weights_splitter.splitterMoved.connect(self._on_split_map_weights_splitter_moved)
		if self.main_tabs is not None:
			self.main_tabs.currentChanged.connect(self._on_main_tab_changed)

	def _on_main_splitter_moved(self, _pos: int, _index: int) -> None:
		self._sync_tools_panel_compact_mode_from_splitter()
		self._update_shapes_header_compact_mode()
		self._update_delegate_name_columns()

	def _on_editor_splitter_moved(self, _pos: int, _index: int) -> None:
		self._update_shapes_header_compact_mode()
		self._update_delegate_name_columns()

	def resizeEvent(self, event):  # noqa: N802
		super().resizeEvent(event)
		self._schedule_initial_splitter_layout()
		self._update_shapes_header_compact_mode()

	def _update_shapes_header_compact_mode(self) -> None:
		if not self._shapes_header_buttons:
			return
		available_width = self.shapes_view.width()
		compact = available_width < self._shapes_header_full_width
		if compact == self._shapes_header_compact_mode:
			return
		self._shapes_header_compact_mode = compact
		for button in self._shapes_header_buttons:
			button.setText("" if compact else self._shapes_header_button_labels[button])

	def _set_splitter_first_pane_size(self, splitter: QSplitter, target_width: int) -> None:
		sizes = splitter.sizes()
		if len(sizes) < 2:
			return
		current_width = sizes[0]
		target_width = max(1, min(target_width, current_width + sizes[1] - 1))
		first_list_width = sizes[1] - (target_width - current_width)
		new_sizes = [target_width, first_list_width] + sizes[2:]
		was_blocked = splitter.blockSignals(True)
		try:
			splitter.setSizes(new_sizes)
		finally:
			splitter.blockSignals(was_blocked)

	def _on_split_groups_splitter_moved(self, pos: int, index: int) -> None:
		if self._split_groups_splitter is None or index != 1:
			return
		compact_width = 30
		expanded_width = self._split_group_buttons_expanded_width
		compact = pos < (compact_width + expanded_width) // 2
		self._set_split_group_buttons_compact_mode(compact)
		self._set_splitter_first_pane_size(
			self._split_groups_splitter,
			compact_width if compact else expanded_width,
		)

	def _set_split_group_buttons_compact_mode(self, compact: bool) -> None:
		if (
			self._split_groups_group_widget is None
			or self._split_group_controls_widget is None
			or not self._split_group_buttons
		):
			return
		if compact == self._split_group_buttons_compact_mode:
			return
		self._split_group_buttons_compact_mode = compact
		for button in self._split_group_buttons:
			button.setText(
				"" if compact else self._split_group_button_labels[button]
			)
			button.setStyleSheet(
				"text-align: center; padding-left: 0px;"
				if compact
				else "text-align: left; padding-left: 2px;"
			)
			button.setIconSize(
				self._tools_panel_compact_icon_size
				if compact
				else self._tools_panel_expanded_icon_size
			)
			button.updateGeometry()

	def _on_split_maps_splitter_moved(self, pos: int, index: int) -> None:
		if self._split_maps_lists_splitter is None or index != 1:
			return
		compact_width = 30
		expanded_width = self._split_map_buttons_expanded_width
		compact = pos < (compact_width + expanded_width) // 2
		self._set_split_map_buttons_compact_mode(compact)
		self._set_splitter_first_pane_size(
			self._split_maps_lists_splitter,
			compact_width if compact else expanded_width,
		)

	def _set_split_map_buttons_compact_mode(self, compact: bool) -> None:
		if (
			self._split_maps_lists_splitter is None
			or self._split_map_controls_widget is None
			or not self._split_map_buttons
		):
			return
		if compact == self._split_map_buttons_compact_mode:
			return
		self._split_map_buttons_compact_mode = compact
		for button in self._split_map_buttons:
			button.setText(
				"" if compact else self._split_map_button_labels[button]
			)
			button.setStyleSheet(
				"text-align: center; padding-left: 0px;"
				if compact
				else "text-align: left; padding-left: 2px;"
			)
			button.setIconSize(
				self._tools_panel_compact_icon_size
				if compact
				else self._tools_panel_expanded_icon_size
			)
			button.updateGeometry()

	def _on_split_map_weights_splitter_moved(self, _pos: int, index: int) -> None:
		if self._split_map_weights_splitter is None or index != 1:
			return
		sizes = self._split_map_weights_splitter.sizes()
		if len(sizes) < 2:
			return
		compact_width = 30
		expanded_width = self._split_map_weight_buttons_expanded_width
		compact = sizes[0] < (compact_width + expanded_width) // 2
		self._set_split_map_weight_buttons_compact_mode(compact)
		total_width = sum(sizes)
		target_width = compact_width if compact else expanded_width
		self._split_map_weights_splitter.setSizes([
			target_width,
			max(1, total_width - target_width),
		])

	def _set_split_map_weight_buttons_compact_mode(self, compact: bool) -> None:
		if (
			self._split_map_weights_splitter is None
			or self._split_map_weight_controls_widget is None
			or not self._split_map_weight_buttons
		):
			return
		if compact == self._split_map_weight_buttons_compact_mode:
			return
		self._split_map_weight_buttons_compact_mode = compact
		for button in self._split_map_weight_buttons:
			button.setText(
				"" if compact else self._split_map_weight_button_labels[button]
			)
			button.setStyleSheet(
				"text-align: center; padding-left: 0px;"
				if compact
				else "text-align: left; padding-left: 2px;"
			)
			button.setIconSize(
				self._tools_panel_compact_icon_size
				if compact
				else self._tools_panel_expanded_icon_size
			)
			button.updateGeometry()

	def _on_third_column_splitter_moved(self, _pos: int, _index: int) -> None:
		self._update_third_column_section_minimums()
		self._update_delegate_name_columns()

	def _on_main_tab_changed(self, index: int) -> None:
		if self.main_tabs is None:
			return
		tab_name = self.main_tabs.tabText(index)
		is_split_tab = tab_name == "Split Settings"
		self._sync_split_map_edit_mesh_visibility(is_split_tab)
		if is_split_tab and self._split_settings_refresh_pending:
			self._reload_split_settings_from_editor()

	def _is_split_tab_active(self) -> bool:
		return bool(self.main_tabs is not None and self.main_tabs.currentIndex() == 1)

	def _sync_split_map_edit_mesh_visibility(self, visible: bool) -> None:
		if self.current_editor is None:
			return
		try:
			if self.current_editor.get_current_edit_split_map() is None:
				return
			self.current_editor.switch_visibility_to_split_map_edit_mesh(visible)
		except Exception as exc:
			self._set_status(f"Error switching split-map edit mesh visibility: {exc}", error=True)

	def _update_third_column_section_minimums(self) -> None:
		if self._third_column_splitter is None or not self._third_column_sections:
			return
		sizes = self._third_column_splitter.sizes()
		for section, size in zip(self._third_column_sections, sizes):
			section.setMinimumWidth(0)
			if size <= 0:
				section.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
			else:
				section.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
			section.updateGeometry()

	def _force_tools_panel_startup_compact_mode(self) -> None:
		self._set_tools_panel_compact_mode(True, force=True)
		if self._main_splitter is not None:
			sizes = self._main_splitter.sizes()
			if sizes:
				total_width = sum(sizes)
				remainder_width = max(0, total_width - self._tools_panel_compact_width)
				remainder = sizes[1:] if len(sizes) > 1 else []
				remainder_total = sum(remainder)
				if remainder and remainder_total > 0:
					new_remainder = [max(1, int(round(remainder_width * (size / remainder_total)))) for size in remainder]
					delta = remainder_width - sum(new_remainder)
					new_remainder[-1] = max(1, new_remainder[-1] + delta)
				else:
					return
				was_blocked = self._main_splitter.blockSignals(True)
				try:
					self._main_splitter.setSizes([self._tools_panel_compact_width] + new_remainder)
				finally:
					self._main_splitter.blockSignals(was_blocked)
		self._set_tools_panel_compact_mode(True, force=True)

	def _sync_tools_panel_compact_mode_from_splitter(self) -> None:
		if self._main_splitter is None:
			return
		sizes = self._main_splitter.sizes()
		if not sizes:
			return
		self._set_tools_panel_compact_mode(sizes[0] <= self._tools_panel_compact_threshold)

	def _set_tools_panel_compact_mode(self, compact: bool, *, force: bool = False) -> None:
		if compact == self._tools_panel_compact_mode and not force:
			return
		self._tools_panel_compact_mode = compact

		if self._tools_group is not None:
			if compact:
				self._tools_group.setMinimumWidth(self._tools_panel_compact_width)
				self._tools_group.setMaximumWidth(self._tools_panel_expanded_width)
			else:
				self._tools_group.setMinimumWidth(self._tools_panel_compact_width)
				self._tools_group.setMaximumWidth(self._tools_panel_expanded_width)

		for button in self._tools_panel_buttons:
			label = self._tools_panel_button_labels.get(button, "")
			has_icon = not button.icon().isNull()
			button.setVisible(has_icon or not compact)
			if compact:
				button.setText("")
				button.setStyleSheet("text-align: center; padding-left: 0px;")
				button.setIconSize(self._tools_panel_compact_icon_size)
				button.setFixedHeight(26)
			else:
				button.setText(label)
				button.setStyleSheet("text-align: left; padding-left: 2px;")
				button.setIconSize(self._tools_panel_expanded_icon_size)
				button.setMinimumHeight(0)
				button.setMaximumHeight(16777215)

		for section in self._tools_panel_sections:
			title_button = getattr(section, "title", None)
			if title_button is None:
				continue
			label = self._tools_panel_section_labels.get(section, "")
			if compact:
				title_button.setText("")
				title_button.setToolButtonStyle(Qt.ToolButtonIconOnly)
				title_button.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
				section.layout.setContentsMargins(1, 1, 1, 1)
			else:
				title_button.setText(label)
				title_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
				title_button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
				section.layout.setContentsMargins(2, 2, 2, 2)

	def _update_tools_button_panel(self) -> None:
		activate = self.current_editor is not None
		for button in self.tool_buttons:
			button.setEnabled(activate)
		if self.rename_editor_action is not None:
			self.rename_editor_action.setEnabled(activate)
		if self.explode_container_action is not None:
			self.explode_container_action.setEnabled(activate)
		if self.fix_invisible_blendshapes_action is not None:
			self.fix_invisible_blendshapes_action.setEnabled(activate)
		if self.convert_simplex_action is not None:
			self.convert_simplex_action.setEnabled(activate)
		if self.connect_simplex_controllers_action is not None:
			self.connect_simplex_controllers_action.setEnabled(activate)
		if self.prepare_for_publishing_action is not None:
			self.prepare_for_publishing_action.setEnabled(activate)
		for action in self.blendshape_node_io_actions:
			action.setEnabled(activate)
		if self.main_tabs is not None:
			self.main_tabs.setTabEnabled(1, activate)

	def _set_split_settings_enabled(self, enabled: bool) -> None:
		for widget in [
			self.split_primary_search,
			self.split_primaries_tree,
			self.split_groups_tree,
			self.split_maps_list,
			self.split_map_weights_list,
			getattr(self, "split_group_add_button", None),
			getattr(self, "split_group_remove_button", None),
			getattr(self, "split_group_rename_button", None),
			getattr(self, "split_map_add_button", None),
			getattr(self, "split_map_rename_button", None),
			getattr(self, "split_map_remove_button", None),
			getattr(self, "split_map_check_normalization_button", None),
			getattr(self, "split_map_edit_button", None),
			getattr(self, "split_map_weight_add_button", None),
			getattr(self, "split_map_weight_rename_button", None),
			getattr(self, "split_map_weight_remove_button", None),
			getattr(self, "split_map_paint_mask_button", None),
			getattr(self, "split_map_weight_normalize_button", None),
			getattr(self, "split_map_weight_apply_button", None),
			getattr(self, "split_map_weight_cancel_button", None),
		]:
			if widget is not None:
				widget.setEnabled(enabled)

	def _reload_split_settings_from_editor(self) -> None:
		if not self._is_split_tab_active():
			self._split_settings_refresh_pending = True
			return
		self._split_settings_refresh_pending = False
		if self.current_editor is None:
			self._refresh_split_primary_assignments()
			self._refresh_split_groups()
			self._refresh_split_maps()
			self._refresh_split_map_weights()
			if self.split_map_weight_stats_label is not None:
				self.split_map_weight_stats_label.setText("No active system.")
			self._set_split_settings_enabled(False)
			return

		self._set_split_settings_enabled(True)
		self._refresh_split_primary_assignments()
		self._refresh_split_groups()
		self._refresh_split_maps()
		self._refresh_split_map_weights()

	def _refresh_split_primary_assignments(self) -> None:
		if self.split_primaries_tree is None:
			return
		if self.current_editor is None:
			self.split_primaries_tree.set_assignments([], {})
			return

		try:
			split_groups = self.current_editor.read_split_groups_attributes()
		except Exception:
			split_groups = {}

		group_names = sorted(str(name) for name in split_groups.keys())
		assignments = {}
		for primary in self.split_primaries_tree.primary_names():
			try:
				assignments[primary] = self.current_editor.get_primary_split_group(primary)
			except Exception:
				assignments[primary] = "NoSplit"
		self.split_primaries_tree.set_assignments(group_names, assignments)
		self._on_split_primary_search_changed(self.split_primary_search.terms() if self.split_primary_search else [])

	def _refresh_split_groups(self) -> None:
		if self.split_groups_tree is None:
			return
		if self.current_editor is None:
			self.split_groups_tree.set_groups({})
			return

		selected_group = self._selected_split_group_name() or ""
		try:
			split_groups = self.current_editor.read_split_groups_attributes()
		except Exception:
			split_groups = {}
		self.split_groups_tree.set_groups(split_groups, selected_group)

	def _refresh_split_maps(self) -> None:
		if self.split_maps_list is None:
			return
		if self.current_editor is None:
			self.split_maps_list.set_maps({})
			return

		selected_map = self._selected_split_map_name() or ""
		editing_map = self._current_edit_split_map_name() or ""
		map_weights = {}
		for split_map_name in sorted(self.current_editor.get_split_maps()):
			try:
				map_weights[split_map_name] = self.current_editor.get_split_map_areas(split_map_name)
			except Exception:
				map_weights[split_map_name] = []
		normalized_maps = {
			map_name: self._split_map_normalization_cache[map_name]
			for map_name in map_weights
			if map_name in self._split_map_normalization_cache
		}
		self.split_maps_list.set_maps(map_weights, normalized_maps, selected_map, editing_map)

	def _refresh_split_map_weights(self, split_map_name: Optional[str] = None) -> None:
		if self.split_map_weights_list is None:
			return
		self.split_map_weights_list.clear()
		split_map_name = self._current_edit_split_map_name()
		# print(f"Refreshing split map weights for: {split_map_name}")
		editing = bool(split_map_name)

		if self._split_map_editor_group_widget is not None:
			self._split_map_editor_group_widget.setEnabled(self.current_editor is not None)
		self.split_map_weights_list.setEnabled(editing)
		if getattr(self, "split_map_weights_label", None) is not None:
			self.split_map_weights_label.setText(
				f"Editing Split Map: {split_map_name}" if editing else "Editing Split Map: None"
			)
		for button in (
			getattr(self, "split_map_weight_add_button", None),
			getattr(self, "split_map_weight_rename_button", None),
			getattr(self, "split_map_weight_remove_button", None),
			getattr(self, "split_map_paint_mask_button", None),
			getattr(self, "split_map_weight_normalize_button", None),
			getattr(self, "split_map_weight_apply_button", None),
			getattr(self, "split_map_weight_cancel_button", None),
		):
			if button is not None:
				button.setEnabled(editing)
		if not editing:
			self._update_split_map_weight_operation_buttons()
			if self.split_map_weight_stats_label is not None:
				self.split_map_weight_stats_label.setText("Press Check Normalization to check split maps.")
			return
		try:
			areas = self.current_editor.get_edit_split_map_areas()
			weight_values = self.current_editor.get_current_edit_split_map_weight_values()
		except Exception as exc:
			self._set_status(f"Error reading split map weights: {exc}", error=True)
			return
		for raw_area in areas:
			prefix = f"{split_map_name}_"
			weight_name = str(raw_area)
			if not weight_name.startswith(prefix):
				weight_name = f"{prefix}{weight_name}"
			display_area = weight_name
			if display_area.startswith(prefix):
				display_area = display_area[len(prefix):]
			item = QListWidgetItem(display_area)
			item.setData(Qt.UserRole, weight_name)
			item.setData(ShapeItemsModel.NameRole, display_area)
			item.setData(ShapeItemsModel.TypeRole, "SplitMapWeight")
			item.setData(ShapeItemsModel.ValueRole, float(weight_values.get(weight_name, 0.0)))
			item.setData(ShapeItemsModel.MutedRole, False)
			item.setData(ShapeItemsModel.EditableRole, True)
			item.setData(ShapeItemsModel.IsHeaderRole, False)
			item.setData(ShapeItemsModel.LockIconVisibleRole, False)
			item.setFlags(item.flags() | Qt.ItemIsEditable)
			self.split_map_weights_list.addItem(item)
		if self.split_map_weights_list.count():
			self.split_map_weights_list.setCurrentRow(0)
		self._update_split_map_weight_operation_buttons()
		if self.split_map_weight_stats_label is not None:
			self.split_map_weight_stats_label.setText("Press Check Normalization to check split maps.")

	def _sync_split_map_weight_slider_values(self) -> None:
		if self.current_editor is None or self.split_map_weights_list is None:
			return
		try:
			weight_values = self.current_editor.get_current_edit_split_map_weight_values()
		except Exception:
			return
		self._syncing_split_map_weight_values = True
		try:
			for row in range(self.split_map_weights_list.count()):
				item = self.split_map_weights_list.item(row)
				weight_name = str(item.data(Qt.UserRole) or "")
				item.setData(ShapeItemsModel.ValueRole, float(weight_values.get(weight_name, 0.0)))
		finally:
			self._syncing_split_map_weight_values = False

	def _on_split_map_weight_value_changed(self, top_left: QModelIndex, bottom_right: QModelIndex, roles) -> None:
		if self._syncing_split_map_weight_values or self.current_editor is None or self.split_map_weights_list is None:
			return
		if roles and ShapeItemsModel.ValueRole not in roles:
			return
		for row in range(top_left.row(), bottom_right.row() + 1):
			item = self.split_map_weights_list.item(row)
			if item is None:
				continue
			weight_name = str(item.data(Qt.UserRole) or "")
			value = float(item.data(ShapeItemsModel.ValueRole) or 0.0)
			try:
				self.current_editor.set_current_edit_split_map_weight_value(weight_name, value)
			except Exception as exc:
				self._set_status(f"Error setting edit weight '{weight_name}': {exc}", error=True)
				self._sync_split_map_weight_slider_values()
				return
		self._set_status(f"Updated edit blendshape weight '{weight_name}' to {value:.3f}.")

	def _selected_split_group_name(self) -> Optional[str]:
		if self.split_groups_tree is None:
			return None
		return self.split_groups_tree.selected_group_name() or None

	def _selected_split_map_name(self) -> Optional[str]:
		if self.split_maps_list is None:
			return None
		return self.split_maps_list.map_name() or None

	def _current_edit_split_map_name(self) -> Optional[str]:
		if self.current_editor is None:
			return None
		try:
			return self.current_editor.get_current_edit_split_map()
		except Exception as exc:
			self._set_status(f"Error reading current split-map edit mode: {exc}", error=True)
			return None

	def _selected_split_map_weight_area(self) -> Optional[str]:
		if self.split_map_weights_list is None or self.split_map_weights_list.currentItem() is None:
			return None
		item = self.split_map_weights_list.currentItem()
		raw_area = item.data(Qt.UserRole)
		if raw_area:
			return str(raw_area)
		return item.text().strip()

	def _on_split_map_weight_selection_changed(self, current_item, _previous_item) -> None:
		self._update_split_map_weight_operation_buttons()
		if self.current_editor is None or current_item is None:
			return
		split_map_name = self._current_edit_split_map_name()
		if not split_map_name:
			return
		weight_area = str(current_item.data(Qt.UserRole) or current_item.text()).strip()
		if not weight_area:
			return
		prefix = f"{split_map_name}_"
		weight_name = weight_area if weight_area.startswith(prefix) else f"{prefix}{weight_area}"
		try:
			edit_mesh = self.current_editor.split_map_edit_mesh
			edit_mesh_shape = cmds.listRelatives(edit_mesh, shapes=True, fullPath=True) or []
			edit_mesh_shapes = set([edit_mesh] + edit_mesh_shape)
			selected = cmds.ls(selection=True, long=True) or []
			self.current_editor.activate_edit_split_weight(weight_name)
			if any(obj in edit_mesh_shapes for obj in selected):
				current_context = cmds.currentCtx()
				if current_context == "sculptMeshCacheContext":
					self.current_editor.set_current_edit_split_map_weight_paint_mask(weight_name)
				elif current_context == "artAttrBlendShapeContext":
					self.current_editor.set_current_edit_split_map_weight_paint_weight(weight_name)
		except Exception as exc:
			self._set_status(f"Error activating split-map weight: {exc}", error=True)
			return
		self._set_status(f"Selected split-map weight '{weight_name}'.")

	def _update_split_map_weight_operation_buttons(self) -> None:
		editing = self.current_editor is not None and bool(self._current_edit_split_map_name())
		has_weight = self.split_map_weights_list is not None and self.split_map_weights_list.currentItem() is not None
		can_paste = editing and getattr(self.current_editor, "copied_weight_map_values", None) is not None
		for button in self._split_map_weight_operation_buttons:
			button.setEnabled(editing and has_weight)
		for button in self._split_map_weight_paste_operation_buttons:
			button.setEnabled(editing and has_weight and can_paste)

	def _on_split_primary_search_changed(self, terms) -> None:
		if self.split_primaries_tree is not None:
			self.split_primaries_tree.set_search_terms(terms)

	def _on_split_primaries_tree_data_changed(self, top_left: QModelIndex, bottom_right: QModelIndex, roles) -> None:
		if self.current_editor is None or self.split_primaries_tree is None:
			return
		if roles and ShapeItemsModel.ValueRole not in roles:
			return
		for row in range(top_left.row(), bottom_right.row() + 1):
			index = top_left.sibling(row, 0)
			if not index.isValid() or bool(index.data(ShapeItemsModel.IsHeaderRole)):
				continue
			shape_name = str(index.data(ShapeItemsModel.NameRole) or "")
			if not shape_name:
				continue
			value = max(0.0, min(1.0, float(index.data(ShapeItemsModel.ValueRole) or 0.0)))
			self._on_primary_tree_slider_changed(shape_name, value)
			self._sync_primary_tree_slider(shape_name, value)
	
	def _on_primary_split_group_changed(self, group_name: str, primary_names) -> None:
		if self.current_editor is None:
			return
		target_names = [str(name) for name in primary_names]
		try:
			self.current_editor.set_primaries_split_group(target_names, group_name)
		except Exception as exc:
			self._set_status(f"Error updating split group assignment: {exc}", error=True)
			self._reload_split_settings_from_editor()
			return
		if self.split_primaries_tree is not None:
			self._refresh_split_primary_assignments()
		self._set_status(f"Assigned {len(target_names)} primary shape(s) to split group '{group_name}'.")

	def _show_split_primaries_context_menu(self, pos) -> None:
		if self.current_editor is None or self.split_primaries_tree is None:
			return
		item = self.split_primaries_tree.itemAt(pos)
		if item is None or item.parent() is None:
			return
		if not item.isSelected():
			self.split_primaries_tree.clearSelection()
			item.setSelected(True)

		menu = QMenu(self.split_primaries_tree)
		split_selected_action = menu.addAction("Split selected shapes")
		menu.addSeparator()
		assign_menu = menu.addMenu("Assign to:")
		try:
			split_groups = self.current_editor.read_split_groups_attributes()
		except Exception:
			split_groups = {}
		assign_actions = {}
		for group_name in ["NoSplit"] + sorted(str(name) for name in split_groups.keys()):
			assign_actions[assign_menu.addAction(group_name)] = group_name

		selected_action = menu.exec(self.split_primaries_tree.viewport().mapToGlobal(pos)) if hasattr(menu, "exec") else menu.exec_(self.split_primaries_tree.viewport().mapToGlobal(pos))
		if selected_action == split_selected_action:
			self._split_selected_shapes(self._selected_split_primary_names())
		elif selected_action in assign_actions:
			self._on_primary_split_group_changed(assign_actions[selected_action], self._selected_split_primary_names())

	def _split_selected_shapes(self, primary_names: Sequence[str]) -> None:
		if self.current_editor is None:
			self._set_status("No system selected.", warning=True)
			return
		selected_names = list(dict.fromkeys(str(name) for name in primary_names if name))
		if not selected_names:
			self._set_status("No primary shapes selected.", warning=True)
			return
		try:
			self._stop_active_blendshape_trackers()
			self.current_editor.split_shapes(selected_names)
		except Exception as exc:
			self._set_status(f"Error splitting selected shapes: {exc}", error=True)
			return
		finally:
			self._start_active_blendshape_trackers()
			self._reload_shapes_from_editor()
		self._set_status(f"Split {len(selected_names)} selected primary shape(s).")

	def _on_split_group_map_selected(self, split_map_name: str) -> None:
		if self.split_maps_list is None or not split_map_name:
			return
		matching = self.split_maps_list.find_map(split_map_name)
		if matching is not None:
			self.split_maps_list.setCurrentItem(matching)

	def _on_split_group_selection_changed(self, group_name: str) -> None:
		if self.split_group_preview_label is None:
			return
		if self.current_editor is None or not group_name:
			self.split_group_preview_label.setText("")
			return
		try:
			primary_name, split_names = self.current_editor.preview_split_primary_name(group_name)
		except Exception:
			self.split_group_preview_label.setText(
				f"<i>'{group_name}' has no split maps</i>"
			)
			return
		split_lines = "<br>".join(f"{name}" for name in split_names)
		self.split_group_preview_label.setText(
			f"<b>{primary_name}:</b><br>{split_lines}"
		)

	def _on_split_map_selection_changed(self, split_map_name: str) -> None:
		self._refresh_split_map_weights()

	def _check_split_maps_normalization(self, split_map_name = None) -> None:
		if not self._is_split_tab_active():
			return
		if self.split_map_weight_stats_label is None:
			return
		if self.current_editor is None:
			self.split_map_weight_stats_label.setText("No active system.")
			return
		if self.split_maps_list is None or self.split_maps_list.topLevelItemCount() == 0:
			self.split_map_weight_stats_label.setText("No split maps to check.")
			return

		editing_map = self._current_edit_split_map_name() or ""
		for item in self.split_maps_list.map_items():
			map_name = self.split_maps_list.map_name(item)
			if split_map_name is not None and map_name != split_map_name:
				continue
			try:
				is_normalized = self.current_editor.is_split_map_normalized(map_name)
			except Exception:
				is_normalized = False
			self._split_map_normalization_cache[map_name] = is_normalized
			if map_name == editing_map:
				item.setData(0, SplitMapsTree.STATUS_COLOR_ROLE, SplitMapsTree.EDITING_COLOR)
				item.setToolTip(0, "Currently being edited")
			else:
				status_color = SplitMapsTree.NORMALIZED_COLOR if is_normalized else SplitMapsTree.NOT_NORMALIZED_COLOR
				item.setData(0, SplitMapsTree.STATUS_COLOR_ROLE, status_color)
				item.setToolTip(0, "Normalized" if is_normalized else "Not normalized")

		total_count = self.split_maps_list.topLevelItemCount()
		map_names = [self.split_maps_list.map_name(item) for item in self.split_maps_list.map_items()]
		checked_count = sum(map_name in self._split_map_normalization_cache for map_name in map_names)
		normalized_count = sum(
			self._split_map_normalization_cache.get(map_name, False)
			for map_name in map_names
		)
		not_normalized_count = checked_count - normalized_count
		not_checked_count = total_count - checked_count
		self.split_map_weight_stats_label.setText(
			f"Normalized: {normalized_count}/{total_count}; not normalized: {not_normalized_count}; "
			f"not checked: {not_checked_count}."
		)

	def _show_split_maps_context_menu(self, pos) -> None:
		if self.current_editor is None or self.split_maps_list is None:
			return
		item = self.split_maps_list.itemAt(pos)
		if item is None:
			return
		if item.parent() is not None:
			item = item.parent()
		self.split_maps_list.setCurrentItem(item)
		split_map_name = self.split_maps_list.map_name(item)
		menu = QMenu(self.split_maps_list)
		copy_weight_menu = menu.addMenu("Copy Weight")
		copy_weight_actions = {}
		try:
			for weight in self.current_editor.get_split_map_weights(split_map_name):
				weight_name = str(weight)
				copy_weight_actions[copy_weight_menu.addAction(weight_name)] = weight_name
		except Exception as exc:
			self._set_status(f"Error reading weights for split map '{split_map_name}': {exc}", error=True)
			return
		copy_weight_menu.setEnabled(bool(copy_weight_actions))
		menu.addSeparator()
		remove_action = menu.addAction("Remove")
		normalize_action = menu.addAction("Normalize Weights")
		selected_action = menu.exec(self.split_maps_list.viewport().mapToGlobal(pos)) if hasattr(menu, "exec") else menu.exec_(self.split_maps_list.viewport().mapToGlobal(pos))
		weight_name = copy_weight_actions.get(selected_action)
		if weight_name is not None:
			try:
				self.current_editor.copy_split_weight_map_values(weight_name)
			except Exception as exc:
				self._set_status(f"Error copying split-map weight '{weight_name}': {exc}", error=True)
				return
			self._update_split_map_weight_operation_buttons()
			self._set_status(f"Copied weight map '{weight_name}'.")
		elif selected_action == remove_action:
			self._on_remove_split_map_clicked()
		elif selected_action == normalize_action:
			self._on_normalize_split_map_weights_requested()

	def _show_split_map_weights_context_menu(self, pos) -> None:
		if self.current_editor is None or self.split_map_weights_list is None:
			return
		item = self.split_map_weights_list.itemAt(pos)
		if item is None:
			return
		self.split_map_weights_list.setCurrentItem(item)
		menu = QMenu(self.split_map_weights_list)
		convert_soft_selection_action = menu.addAction("Convert Soft Selection to Split Weight Map")
		copy_action = menu.addAction("Copy Weight Map")
		menu.addSeparator()
		paste_action = menu.addAction("Paste Weight Map")
		paste_inverted_action = menu.addAction("Paste Inverted")
		add_action = menu.addAction("Add Copied Weights")
		subtract_action = menu.addAction("Subtract Copied Weights")
		multiply_action = menu.addAction("Multiply by Copied Weights")
		can_paste = self.current_editor.copied_weight_map_values is not None
		for action in [paste_action, paste_inverted_action, add_action, subtract_action, multiply_action]:
			action.setEnabled(can_paste)
		selected_action = menu.exec(self.split_map_weights_list.viewport().mapToGlobal(pos)) if hasattr(menu, "exec") else menu.exec_(self.split_map_weights_list.viewport().mapToGlobal(pos))
		operations = {
			convert_soft_selection_action: ("convert_soft_selection_to_edit_split_weight_map", "Converted soft selection to"),
			copy_action: ("copy_edit_split_weight_map_values", "Copied"),
			paste_action: ("paste_edit_split_weight_map_values", "Pasted"),
			paste_inverted_action: ("paste_inverted_edit_split_weight_map_values", "Pasted inverted values to"),
			add_action: ("add_edit_split_weight_map_values", "Added copied values to"),
			subtract_action: ("subtract_edit_split_weight_map_values", "Subtracted copied values from"),
			multiply_action: ("paste_multiplied_edit_split_weight_map_values", "Multiplied"),
		}
		operation = operations.get(selected_action)
		if operation is not None:
			self._run_split_weight_map_operation(*operation)

	def _run_split_weight_map_operation(self, method_name: str, status_verb: str, weight_name: str = "") -> None:
		if self.current_editor is None:
			return
		split_map_name = self._current_edit_split_map_name()
		if not split_map_name:
			return
		if not weight_name:
			weight_area = self._selected_split_map_weight_area()
			if not weight_area:
				return
			prefix = f"{split_map_name}_"
			weight_name = weight_area if weight_area.startswith(prefix) else f"{split_map_name}_{weight_area}"
		try:
			getattr(self.current_editor, method_name)(weight_name)
		except Exception as exc:
			self._set_status(f"Error updating split-map weight: {exc}", error=True)
			return
		self._sync_split_map_weight_slider_values()
		self._update_split_map_weight_operation_buttons()
		self._set_status(f"{status_verb} weight map '{weight_name}'.")

	def _on_normalize_split_map_weights_requested(self) -> None:
		if self.current_editor is None:
			return
		split_map_name = self._selected_split_map_name()
		if not split_map_name:
			return
		try:
			self.current_editor.normalize_split_map_weights(split_map_name)
		except Exception as exc:
			self._set_status(f"Error normalizing split map: {exc}", error=True)
			return
		if self.split_maps_list is not None:
			item = self.split_maps_list.find_map(split_map_name)
			if item is not None:
				item.setData(0, SplitMapsTree.STATUS_COLOR_ROLE, SplitMapsTree.NORMALIZED_COLOR)
				item.setToolTip(0, "Normalized")
		self._split_map_normalization_cache[split_map_name] = True
		self._set_status(f"Normalized split map '{split_map_name}'.")

	def _on_create_split_group_clicked(self) -> None:
		if self.current_editor is None:
			return
		group_name, ok = QInputDialog.getText(self, "Create Split Group", "Split group name:")
		if not ok:
			return
		group_name = (group_name or "").strip()
		if not group_name:
			return
		try:
			self.current_editor.create_split_group(group_name, [])
		except Exception as exc:
			self._set_status(f"Error creating split group: {exc}", error=True)
			return
		self._refresh_split_primary_assignments()
		self._refresh_split_groups()
		self._set_status(f"Created split group '{group_name}'.")

	def _on_remove_split_group_clicked(self) -> None:
		if self.current_editor is None:
			return
		group_name = self._selected_split_group_name()
		if not group_name:
			return
		try:
			self.current_editor.remove_split_group(group_name)
		except Exception as exc:
			self._set_status(f"Error removing split group: {exc}", error=True)
			return
		self._refresh_split_primary_assignments()
		self._refresh_split_groups()
		self._set_status(f"Removed split group '{group_name}'.")

	def _on_rename_split_group_clicked(self) -> None:
		if self.current_editor is None:
			return
		group_name = self._selected_split_group_name()
		if not group_name:
			return
		new_name, ok = QInputDialog.getText(
			self,
			"Rename Split Group",
			"Split group name:",
			text=group_name,
		)
		if not ok:
			return
		new_name = (new_name or "").strip()
		if not new_name or new_name == group_name:
			return
		try:
			self.current_editor.rename_split_group(group_name, new_name)
		except Exception as exc:
			self._set_status(f"Error renaming split group: {exc}", error=True)
			return
		self._refresh_split_primary_assignments()
		self._refresh_split_groups()
		if self.split_groups_tree is not None:
			self.split_groups_tree.select_group(new_name)
		self._set_status(f"Renamed split group '{group_name}' to '{new_name}'.")

	def _on_split_group_maps_changed(self, split_groups: Dict[str, List[str]]) -> None:
		if self.current_editor is None or self.split_groups_tree is None:
			return
		try:
			self.current_editor.write_split_groups_attributes(split_groups)
			self.current_editor.update_split_map_attributes_from_groups()
		except Exception as exc:
			self._set_status(f"Error updating split group maps: {exc}", error=True)
			self._refresh_split_groups()
			return
		self._set_status("Updated split group maps.")

	def _on_split_group_map_dragged_out(self, group_name: str, map_name: str) -> None:
		if self.current_editor is None or self.split_groups_tree is None:
			return
		if not group_name:
			return
		try:
			split_groups = self.current_editor.read_split_groups_attributes()
		except Exception:
			return

		self.current_editor.remove_split_map_from_split_group(group_name, map_name)
		self._on_split_group_maps_changed(split_groups)
		self._refresh_split_groups()

	def _on_add_split_map_clicked(self) -> None:
		if self.current_editor is None:
			return
		split_map_name, ok = QInputDialog.getText(self, "Add Split Map", "Split map name:")
		if not ok:
			return
		split_map_name = (split_map_name or "").strip()
		if not split_map_name:
			return
		areas_text, ok = QInputDialog.getText(
			self,
			"Add Split Map Weights",
			"Weight areas (comma-separated, optional):",
			text="L,R",
		)
		if not ok:
			return
		areas = [area.strip() for area in str(areas_text).split(",") if area.strip()]
		try:
			self.current_editor.create_split_map(split_map_name, areas)
		except Exception as exc:
			self._set_status(f"Error adding split map: {exc}", error=True)
			return
		self._reload_split_settings_from_editor()
		self._set_status(f"Added split map '{split_map_name}'.")

	def _on_rename_split_map_clicked(self) -> None:
		if self.current_editor is None:
			return
		current_name = self._selected_split_map_name()
		if not current_name:
			return
		new_name, ok = QInputDialog.getText(self, "Rename Split Map", "New split map name:", text=current_name)
		if not ok:
			return
		new_name = (new_name or "").strip()
		if not new_name or new_name == current_name:
			return
		try:
			self.current_editor.rename_split_map(current_name, new_name)
		except Exception as exc:
			self._set_status(f"Error renaming split map: {exc}", error=True)
			return
		self._reload_split_settings_from_editor()
		self._set_status(f"Renamed split map '{current_name}' to '{new_name}'.")

	def _on_remove_split_map_clicked(self) -> None:
		if self.current_editor is None:
			return
		current_name = self._selected_split_map_name()
		if not current_name:
			return
		try:
			self.current_editor.delete_split_map(current_name)
		except Exception as exc:
			self._set_status(f"Error removing split map: {exc}", error=True)
			return
		self._reload_split_settings_from_editor()
		self._set_status(f"Removed split map '{current_name}'.")

	def _on_edit_split_map_clicked(self) -> None:
		if self.current_editor is None:
			return
		split_map_name = self._selected_split_map_name()
		if not split_map_name:
			self._set_status("Select a split map first.", warning=True)
			return
		self._clear_split_map_edit_blendshape_tracker()
		try:
			self.current_editor.create_split_map_edit_blendshape(split_map_name)
		except Exception as exc:
			self._set_status(f"Error entering split-map edit mode: {exc}", error=True)
			return
		finally:
			self._setup_split_map_edit_blendshape_tracker()
		self._refresh_split_maps()
		self._refresh_split_map_weights()
		self._set_status(f"Editing split map '{split_map_name}'.")

	def _on_normalize_edit_split_map_weights_clicked(self) -> None:
		if self.current_editor is None:
			return
		split_map_name = self._current_edit_split_map_name()
		if not split_map_name:
			self._set_status("Enter split-map edit mode first.", warning=True)
			return
		try:
			self.current_editor.normalize_edit_split_map_weights()
		except Exception as exc:
			self._set_status(f"Error normalizing edited split map: {exc}", error=True)
			return
		self._set_status(f"Normalized edited split map '{split_map_name}'.")

	def _on_apply_edit_split_map_clicked(self) -> None:
		if self.current_editor is None:
			return
		split_map_name = self._current_edit_split_map_name()
		if not split_map_name:
			self._set_status("Enter split-map edit mode first.", warning=True)
			return
		self._clear_split_map_edit_blendshape_tracker()
		try:
			self.current_editor.apply_current_edit_split_map()
		except Exception as exc:
			self._set_status(f"Error applying split-map edits: {exc}", error=True)
			return
		finally:
			self._setup_split_map_edit_blendshape_tracker()
		self._split_map_normalization_cache.pop(split_map_name, None)
		self._refresh_split_maps()
		self._refresh_split_map_weights()
		self._set_status(f"Applied edits to split map '{split_map_name}'.")

	def _on_cancel_edit_split_map_clicked(self) -> None:
		if self.current_editor is None:
			return
		split_map_name = self._current_edit_split_map_name()
		if not split_map_name:
			self._set_status("Enter split-map edit mode first.", warning=True)
			return
		self._clear_split_map_edit_blendshape_tracker()
		try:
			self.current_editor.cancel_current_edit_split_map()
		except Exception as exc:
			self._set_status(f"Error cancelling split-map edits: {exc}", error=True)
			return
		finally:
			self._setup_split_map_edit_blendshape_tracker()
		self._refresh_split_maps()
		self._refresh_split_map_weights()
		self._set_status(f"Cancelled edits to split map '{split_map_name}'.")


	def _on_add_split_map_weight_clicked(self) -> None:
		if self.current_editor is None:
			return
		split_map_name = self._current_edit_split_map_name()
		if not split_map_name:
			self._set_status("Enter split-map edit mode first.", warning=True)
			return
		area_name, ok = QInputDialog.getText(self, "Add Split Map Weight", "Weight area name:")
		if not ok:
			return
		area_name = (area_name or "").strip()
		if not area_name:
			return
		if self.split_map_edit_blendshape_tracker is not None:
			self.split_map_edit_blendshape_tracker.stop()
		try:
			self.current_editor.add_weight_to_split_map_edit_blendshape(split_map_name, area_name)
		except Exception as exc:
			self._set_status(f"Error adding split-map weight: {exc}", error=True)
			return
		finally:
			self._setup_split_map_edit_blendshape_tracker()
		self._refresh_split_map_weights(split_map_name)
		self._set_status(f"Added weight '{split_map_name}_{area_name}'.")

	def _on_rename_split_map_weight_clicked(self) -> None:
		if self.current_editor is None:
			return
		split_map_name = self._current_edit_split_map_name()
		old_area = self._selected_split_map_weight_area()
		if not split_map_name or not old_area:
			return
		prefix = f"{split_map_name}_"
		base_old_area = old_area[len(prefix):] if old_area.startswith(prefix) else old_area
		new_area, ok = QInputDialog.getText(self, "Rename Split Map Weight", "New weight area:", text=base_old_area)
		if not ok:
			return
		new_area = (new_area or "").strip()
		if not new_area or new_area == base_old_area:
			return
		if self.split_map_edit_blendshape_tracker is not None:
			self.split_map_edit_blendshape_tracker.stop()
		try:
			self.current_editor.rename_edit_split_map_edit_blendshape_weight(split_map_name, base_old_area, new_area)
		except Exception as exc:
			self._set_status(f"Error renaming split-map weight: {exc}", error=True)
			return
		finally:
			self._setup_split_map_edit_blendshape_tracker()
		self._reload_split_settings_from_editor()
		self._set_status(f"Renamed weight '{split_map_name}_{base_old_area}' to '{split_map_name}_{new_area}'.")

	def _on_paint_split_map_weight_mask_clicked(self) -> None:
		if self.current_editor is None:
			return
		split_map_name = self._current_edit_split_map_name()
		weight_area = self._selected_split_map_weight_area()
		if not split_map_name or not weight_area:
			return
		prefix = f"{split_map_name}_"
		weight_name = weight_area if weight_area.startswith(prefix) else f"{split_map_name}_{weight_area}"
		paint_weight = bool(QGuiApplication.keyboardModifiers() & Qt.AltModifier)
		paint_method = (
			self.current_editor.set_current_edit_split_map_weight_paint_weight
			if paint_weight
			else self.current_editor.set_current_edit_split_map_weight_paint_mask
		)
		paint_mode = "target weight" if paint_weight else "target mask"
		try:
			paint_method(weight_name)
		except Exception as exc:
			self._set_status(f"Error entering {paint_mode} paint mode: {exc}", error=True)
			return
		self._set_status(f"Entered {paint_mode} paint mode for split-map weight '{weight_name}'.")

	def _on_remove_split_map_weight_clicked(self) -> None:
		if self.current_editor is None:
			return
		split_map_name = self._current_edit_split_map_name()
		area_name = self._selected_split_map_weight_area()
		if not split_map_name or not area_name:
			return
		if self.split_map_edit_blendshape_tracker is not None:
			self.split_map_edit_blendshape_tracker.stop()
		try:
			self.current_editor.remove_weight_from_split_map_edit_blendshape(split_map_name, area_name)
		except Exception as exc:
			self._set_status(f"Error removing split-map weight: {exc}", error=True)
			return
		finally:
			self._setup_split_map_edit_blendshape_tracker()
		self._refresh_split_map_weights(split_map_name)
		self._set_status(f"Removed weight '{area_name}'.")

	def _show_controller_layout_window(self) -> None:
		if self._controller_layout_window is None:
			maya_parent = get_maya_main_window() or self
			self._controller_layout_window = ControllerLayoutWindow(
				self._editor_for_controller_layout,
				lambda msg: self._set_status(msg),
				maya_parent,
			)
			self._controller_layout_window.destroyed.connect(lambda *_args: self._clear_controller_layout_window_ref())
		self._controller_layout_window.set_current_editor(self.current_editor)
		self._controller_layout_window.show()
		self._controller_layout_window.raise_()
		self._controller_layout_window.activateWindow()

	def _editor_for_controller_layout(self) -> Optional[BlueSteelEditor]:
		return self.current_editor

	def _clear_controller_layout_window_ref(self) -> None:
		self._controller_layout_window = None

	def _selected_shape_names_from_shapes_view(self) -> List[str]:
		names: List[str] = []
		for item in self.shapes_view.selectedItems():
			if bool(item.data(0, ShapeItemsModel.IsHeaderRole)):
				continue
			shape_name = item.data(0, ShapeItemsModel.NameRole)
			if shape_name:
				names.append(shape_name)
		return names

	def _selected_shape_names_from_active_shapes_view(self) -> List[str]:
		names: List[str] = []
		selected_indexes = self.active_shapes_view.selectedIndexes()
		for index in selected_indexes:
			shape_name = index.data(ShapeItemsModel.NameRole)
			if shape_name:
				names.append(shape_name)
		return names

	def _select_shape_in_shapes_tree(self, shape_name: str, *, ensure_visible: bool = True) -> bool:
		item = self._shape_tree_items.get(shape_name)
		if item is None and ensure_visible:
			# If filters hide the newly added shape, clear filters and try again.
			self._clear_shapes_filters(keep_selection=True)
			item = self._shape_tree_items.get(shape_name)
		if item is None:
			return False

		self.shapes_view.clearSelection()
		item.setSelected(True)
		self.shapes_view.setCurrentItem(item)
		self.shapes_view.scrollToItem(item)
		return True

	@undoable
	def commit_selected(self) -> None:
		if self.current_editor is None:
			self._set_status("No system selected.", warning=True)
			return

		selected = cmds.ls(selection=True, flatten=True)
		if not selected:
			self._set_status("No items selected in the scene.", warning=True)
			return

		selected_components = cmds.filterExpand(selected, selectionMask=(31, 32, 34)) or None
		if selected_components:
			selected_transfom = selected_components[0].split(".")[0]
			if cmds.nodeType(selected_transfom) == "mesh":
				selected_transfom = cmds.listRelatives(selected_transfom, parent=True, fullPath=True)[0] or []
			
			selected_meshes = [selected_transfom] or []
			
		else:
			# we need to check if the selected transforms have shape nodes under them, otherwise we might end up committing the transform instead of the shape
			selected_meshes = []
			for transform in selected:
				shapes = cmds.listRelatives(transform, shapes=True, fullPath=True) or []
				for shape in shapes:
					if cmds.nodeType(shape) == "mesh":
						selected_meshes.append(transform)
						break
		if not selected_meshes:
			self._set_status("No polygon meshes found in selection.", warning=True)
			return

		failed_shapes = []
		try:
			if self.blendshape_tracker is not None:
				self.blendshape_tracker.stop()
			failed_shapes = self.current_editor.commit_shapes(selected_meshes)
		except Exception as exc:
			self._set_status(f"Error committing shapes: {exc}", error=True)
			return
		finally:
			if self.blendshape_tracker is not None:
				self.blendshape_tracker.start()
			self._reload_shapes_from_editor()
			if selected_components:
				cmds.select(selected_components, replace=True)

		committed_count = len(selected_meshes) - len(failed_shapes)
		meshes_label = "poly mesh" if len(selected_meshes) == 1 else "poly meshes"
		self._set_status(f"Committed {committed_count} {meshes_label} to '{self.current_editor.name}'.")

	def add_selected_at_current_pose(self) -> None:
		if self.current_editor is None:
			self._set_status("No system selected.", warning=True)
			return
		
		try:
			if self.blendshape_tracker is not None:
				self.blendshape_tracker.stop()
			committed_shape_name = self.current_editor.add_selected_at_current_pose()
		except Exception as exc:
			self._set_status(f"Error adding shape at current pose: {exc}", error=True)
			return
		finally:
			if self.blendshape_tracker is not None:
				self.blendshape_tracker.start()
			self._reload_shapes_from_editor()

		if committed_shape_name:
			self._set_shape_pose_by_name(committed_shape_name)
			selected = self._select_shape_in_shapes_tree(committed_shape_name, ensure_visible=True)
			if selected:
				self._set_status(f"Added shape '{committed_shape_name}' at current pose, and selected it in Shapes.")
			else:
				self._set_status(
					f"Added shape '{committed_shape_name}' at current pose, but could not select it in Shapes.",
					warning=True,
				)
		else:
			self._set_status("Added shape at current pose, but no active values found to determine the name.", warning=True)

	def _on_add_primary_clicked(self) -> None:
		if self.current_editor is None:
			self._set_status("No system selected.", warning=True)
			return

		shape_name, ok = QInputDialog.getText(
			self,
			"Add Primary",
			"Enter primary shape name:",
		)
		shape_name = (shape_name or "").strip()
		if not ok or not shape_name:
			self._set_status("Add primary cancelled.")
			return

		try:
			self._stop_active_blendshape_trackers()
			self.current_editor.add_new_primary_shape(shape_name)
		except Exception as exc:
			self._set_status(f"Error adding primary shape: {exc}", error=True)
			return
		finally:
			self._start_active_blendshape_trackers()

		self._reload_shapes_from_editor()
		added_item = self._primary_tree_items.get(shape_name)
		if added_item is not None:
			self.primaries_view.clearSelection()
			added_item.setSelected(True)
			self.primaries_view.setCurrentItem(added_item)
			self.primaries_view.scrollToItem(added_item)
		self._set_status(f"Added primary shape '{shape_name}'.")

	def remove_selected_shapes(self, shape_names: Optional[Sequence[str]] = None) -> None:
		if self.current_editor is None:
			self._set_status("No system selected.", warning=True)
			return

		shape_names = list(shape_names) if shape_names else self._selected_shape_names_from_shapes_view()
		if not shape_names:
			self._set_status("No shapes selected.", warning=True)
			return

		try:
			if self.blendshape_tracker is not None:
				self.blendshape_tracker.stop()
			removed_shapes = self.current_editor.remove_shapes(shape_names)
		except Exception as exc:
			self._set_status(f"Error removing shapes: {exc}", error=True)
			return
		finally:
			if self.blendshape_tracker is not None:
				self.blendshape_tracker.start()

		self._reload_shapes_from_editor()
		self._set_status(f"Removed {len(removed_shapes)} shape(s) from '{self.current_editor.name}'.")

	def remove_shapes_from_focused_view(self) -> None:
		if self.primaries_view.hasFocus():
			self.remove_selected_primaries()
			return
		if self.shapes_view.hasFocus():
			self.remove_selected_shapes()
			return
		self._set_status("Focus the Primaries or Shapes list before removing shapes.", warning=True)

	def remove_selected_primaries(self) -> None:
		if self.current_editor is None:
			self._set_status("No system selected.", warning=True)
			return

		primary_names = self._selected_primary_tree_names()
		if not primary_names:
			self._set_status("No primaries selected.", warning=True)
			return

		try:
			self._stop_active_blendshape_trackers()
			removed_shapes = self.current_editor.remove_shapes(primary_names)
		except Exception as exc:
			self._set_status(f"Error removing primaries: {exc}", error=True)
			return
		finally:
			self._start_active_blendshape_trackers()

		self._reload_shapes_from_editor()
		self._set_status(
			f"Removed {len(primary_names)} primary shape(s) and "
			f"{len(removed_shapes) - len(primary_names)} dependent shape(s) from '{self.current_editor.name}'."
		)

	def toggle_mute_selected_shapes(self) -> None:
		if self.current_editor is None:
			self._set_status("No system selected.", warning=True)
			return

		shape_names = self._selected_shape_names_from_shapes_view()
		if not shape_names:
			self._set_status("No shapes selected.", warning=True)
			return

		try:
			for shape_name in shape_names:
				shape = self.current_editor.get_shape(shape_name)
				if shape is not None:
					self.current_editor.set_shape_mute_state(shape, not bool(getattr(shape, "muted", False)))
		except Exception as exc:
			self._set_status(f"Error toggling mute state: {exc}", error=True)
			return

		self._reload_shapes_from_editor()
		self._set_status(f"Toggled mute for {len(shape_names)} shape(s).")

	def unmute_all_shapes(self) -> None:
		if self.current_editor is None:
			self._set_status("No system selected.", warning=True)
			return
		try:
			self.current_editor.unmute_all_shapes()
		except Exception as exc:
			self._set_status(f"Error unmuting all shapes: {exc}", error=True)
			return
		self._reload_shapes_from_editor()
		self._set_status(f"All shapes in '{self.current_editor.name}' are unmuted.")

	def unlock_all_shapes(self) -> None:
		print("Unlocking all shapes...")
		if self.current_editor is None:
			self._set_status("No system selected.", warning=True)
			return
		if getattr(self.current_editor, "locked_shapes", None) is None:
			self.current_editor.locked_shapes = set()

		self.current_editor.unlock_all_shapes()
		self._shape_model.refresh_locked_states_from_editor()
		self._set_status(f"All shapes in '{self.current_editor.name}' are unlocked.")

	def select_face_ctrl(self) -> None:
		if self.current_editor is None:
			self._set_status("No system selected.", warning=True)
			return
		cmds.select(self.current_editor.face_ctrl, replace=True)
		self._set_status(f"Selected controller '{self.current_editor.face_ctrl}'.")

	def zero_all(self) -> None:
		if self.current_editor is None:
			self._set_status("No system selected.", warning=True)
			return
		try:
			if self.blendshape_tracker is not None:
				self.blendshape_tracker.stop()
			self.current_editor.zero_out()
			changed_rows = self._shape_model.refresh_values_from_editor()
			for changed_name, changed_value, is_primary in changed_rows:
				if is_primary:
					self._sync_primary_tree_slider(changed_name, changed_value)
			self._resort_value_sorted_lists_if_needed()
		except Exception as exc:
			self._set_status(f"Error zeroing out shapes: {exc}", error=True)
			return
		finally:
			if self.blendshape_tracker is not None:
				self.blendshape_tracker.start()
		self._set_status(f"All shapes in '{self.current_editor.name}' have been zeroed.")

	def rename_selected_mesh(self) -> None:
		selection = cmds.ls(selection=True)
		if not selection:
			self._set_status("No items selected in the scene.", warning=True)
			return
		if self.current_editor is None:
			self._set_status("No system selected.", warning=True)
			return
		if selection[0] == self.current_editor.base_mesh:
			self._set_status("Cannot rename the base mesh.", warning=True)
			return
		pose_name = self.current_editor.get_active_state_name()
		if not pose_name:
			self._set_status("No active pose found.", warning=True)
			return
		new_name = cmds.rename(selection[0], pose_name)
		self._set_status(f"Renamed mesh to '{new_name}'.")

	def extract_selected(self, selected_shapes) -> None:
		if self.current_editor is None:
			self._set_status("No system selected.", warning=True)
			return

		try:
			extracted = self.current_editor.extract_shapes_to_mesh(selected_shapes)
		except Exception as exc:
			self._set_status(f"Error extracting shape: {exc}", error=True)
			return
		self._reload_shapes_from_editor()
		self._set_status(f"Extracted shape '{extracted}' from current pose.")

	def duplicate_at_value(self) -> None:
		if self.current_editor is None:
			self._set_status("No system selected.", warning=True)
			return
		try:
			extracted = self.current_editor.duplicate_base_mesh_at_current_pose()
		except Exception as exc:
			self._set_status(f"Error duplicating to new pose: {exc}", error=True)
			return
		self._set_status(f"Duplicated current pose to '{extracted}'.")

	def launch_mmtools(self) -> None:
		workspace_control = "MMToolsWorkspaceControl"
		if (
			cmds.workspaceControl(workspace_control, query=True, exists=True)
			and cmds.workspaceControl(workspace_control, query=True, visible=True)
		):
			cmds.workspaceControl(workspace_control, edit=True, close=True)
			cmds.deleteUI(workspace_control, control=True)
			ui.WINDOW = None
			return
		ui.show()

	def _on_toggle_hud_clicked(self) -> None:
		modifiers = QGuiApplication.keyboardModifiers()
		alt_pressed = bool(modifiers & Qt.AltModifier)
		if self.current_editor is None:
			self._set_status("No system selected.", warning=True)
			return
		try:
			self.current_editor.toggle_hud_display(state=not self.current_editor.hud_on, list_combos= not alt_pressed)
		except Exception as exc:
			self._set_status(f"Error toggling HUD: {exc}", error=True)
			return
		self._set_status(f"Toggled HUD for '{self.current_editor.blendshape.name}'.")

	def compare_shapes_debug(self) -> None:
		if self.current_editor is None:
			self._set_status("No system selected.", warning=True)
			return
		unmatched_shapes, max_diff, max_diff_shape = self.current_editor.compare_shapes_debug()
		if unmatched_shapes:
			self._set_status(
				f"Found {len(unmatched_shapes)} unmatched shape(s). Max difference: {max_diff:.6f} on shape '{max_diff_shape}'.",
				warning=True,
			)
		else:
			self._set_status("All shapes match successfully.")

	def _clear_trackers_for_scene_operation(self) -> None:
		"""Temporarily stop trackers before scene-wide operations."""
		self._clear_scene_editor_tracker()
		self._clear_blendshape_tracker()

	def _restart_trackers_after_scene_operation(self) -> None:
		"""Restore trackers after scene-wide operations."""
		self._setup_scene_editor_tracker()
		if self.current_editor is not None:
			self._setup_blendshape_tracker()

	def _create_menu_bar(self) -> None:
		"""Create the top menu bar migrated from the legacy editor window."""
		menu_widget = QWidget(self)
		menu_widget.setFixedHeight(24)
		menu_layout = QHBoxLayout(menu_widget)
		menu_layout.setContentsMargins(0, 0, 2, 0)
		menu_layout.setSpacing(2)
		menu_bar = QMenuBar(menu_widget)
		menu_bar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
		menu_layout.addWidget(menu_bar, 1)
		button_size = 20
		self.dock_toggle_button = QPushButton(menu_widget)
		self.dock_toggle_button.setFixedSize(button_size, button_size)
		self.dock_toggle_button.setIconSize(QSize(14, 14))
		self.dock_toggle_button.setStyleSheet(
			"QPushButton { border: 1px solid palette(mid); border-radius: 5px; padding: 0px; }"
		)
		menu_layout.addWidget(self.dock_toggle_button, 0, Qt.AlignVCenter)
		self.dock_close_button = QPushButton("X", menu_widget)
		self.dock_close_button.setFixedSize(button_size, button_size)
		self.dock_close_button.setToolTip("Close Blue Steel")
		self.dock_close_button.setStyleSheet(
			"QPushButton { border: 1px solid palette(mid); border-radius: 5px; padding: 0px; font-weight: bold; }"
		)
		menu_layout.addWidget(self.dock_close_button, 0, Qt.AlignVCenter)
		self._set_dock_button_state(docked=True)
		self.setMenuWidget(menu_widget)

		file_menu = menu_bar.addMenu("File")
		new_action = QAction("New", self)
		new_action.setShortcut("Ctrl+N")
		new_action.triggered.connect(self._create_new_editor)
		file_menu.addAction(new_action)
		file_menu.addSeparator()

		exit_action = QAction("Exit", self)
		exit_action.setShortcut("Ctrl+Q")
		exit_action.triggered.connect(self.close)
		file_menu.addAction(exit_action)

		import_menu = file_menu.addMenu("Import")
		import_objs_action = QAction("Import Objs", self)
		import_objs_action.triggered.connect(self._import_objs)
		import_menu.addAction(import_objs_action)
		import_blendshape_node_menu = import_menu.addMenu("Import From BlendShape Node")
		import_blendshape_node_action = QAction("Relative Shapes", self)
		import_blendshape_node_action.triggered.connect(lambda _checked=False: self._import_shapes_from_blendshape_node(absolute_delta=False))
		import_blendshape_node_menu.addAction(import_blendshape_node_action)
		import_absolute_blendshape_node_action = QAction("Absolute Shapes", self)
		import_absolute_blendshape_node_action.triggered.connect(lambda _checked=False: self._import_shapes_from_blendshape_node(absolute_delta=True))
		import_blendshape_node_menu.addAction(import_absolute_blendshape_node_action)

		export_menu = file_menu.addMenu("Export")
		export_objs_action = QAction("Export Objs", self)
		export_objs_action.triggered.connect(self._export_objs)
		export_menu.addAction(export_objs_action)
		export_blendshape_node_menu = export_menu.addMenu("Export To BlendShape Node")
		export_blendshape_node_action = QAction("Relative Shapes", self)
		export_blendshape_node_action.triggered.connect(lambda _checked=False: self._export_shapes_as_blendshape_node(absolute_delta=False))
		export_blendshape_node_menu.addAction(export_blendshape_node_action)
		export_absolute_blendshape_node_action = QAction("Absolute Shapes", self)
		export_absolute_blendshape_node_action.triggered.connect(lambda _checked=False: self._export_shapes_as_blendshape_node(absolute_delta=True))
		export_blendshape_node_menu.addAction(export_absolute_blendshape_node_action)
		self.blendshape_node_io_actions = [
			import_blendshape_node_action,
			import_absolute_blendshape_node_action,
			export_blendshape_node_action,
			export_absolute_blendshape_node_action,
		]

		utilities_menu = menu_bar.addMenu("Utilities")
		self.rename_editor_action = QAction("Rename Editor", self)
		self.rename_editor_action.setToolTip("Rename the current Blue Steel Editor system.")
		self.rename_editor_action.triggered.connect(self._rename_current_editor)
		self.rename_editor_action.setEnabled(self.current_editor is not None)
		utilities_menu.addAction(self.rename_editor_action)

		recover_editor_action = QAction("Recover Deleted Editors", self)
		recover_editor_action.setToolTip("Not available yet in the Model/View editor.")
		recover_editor_action.setEnabled(False)
		utilities_menu.addAction(recover_editor_action)

		split_shapes_menu = menu_bar.addMenu("Split Shapes")
		split_shapes_menu.setToolTip("Split shapes into multiple shapes based on the current split settings.")

		import_split_data_action = QAction("Import Split Data", self)
		import_split_data_action.triggered.connect(self._import_split_data)
		split_shapes_menu.addAction(import_split_data_action)

		export_split_data_action = QAction("Export Split Data", self)
		export_split_data_action.triggered.connect(self._export_split_data)
		split_shapes_menu.addAction(export_split_data_action)

		create_split_shapes_editor_action = QAction("Create Split Shapes Editor", self)
		create_split_shapes_editor_action.triggered.connect(self._on_create_split_shapes_editor_requested)
		split_shapes_menu.addAction(create_split_shapes_editor_action)

		collapsed = True
		if cmds.nodeEditor("nodeEditorPanel1NodeEditorEd", exists=True):
			collapsed = bool(cmds.nodeEditor("nodeEditorPanel1NodeEditorEd", q=True, useAssets=True))
		self.explode_container_action = QAction("", self)
		self._toggle_exploded_container_action_state(collapsed)
		self.explode_container_action.triggered.connect(self._toggle_node_editor_container_view)
		self.explode_container_action.setEnabled(self.current_editor is not None)
		utilities_menu.addAction(self.explode_container_action)

		self.fix_invisible_blendshapes_action = QAction("Fix Invisible Blendshapes in the Shape Editor", self)
		self.fix_invisible_blendshapes_action.setToolTip(
			"Fix mid-layer blendshape directory indices that can hide targets in Maya Shape Editor."
		)
		self.fix_invisible_blendshapes_action.triggered.connect(self._on_fix_invisible_blendshapes_requested)
		self.fix_invisible_blendshapes_action.setEnabled(self.current_editor is not None)
		utilities_menu.addAction(self.fix_invisible_blendshapes_action)

		conversion_cleanup_menu = menu_bar.addMenu("Converters/Clean-Up")
		simplex_menu = conversion_cleanup_menu.addMenu("Simplex Facial System")
		self.convert_simplex_action = QAction("Convert Simplex", self)
		self.convert_simplex_action.setToolTip("Convert a Simplex facial system into Blue Steel.")
		self.convert_simplex_action.triggered.connect(self._on_simplex_converter_requested)
		self.convert_simplex_action.setEnabled(self.current_editor is not None)
		simplex_menu.addAction(self.convert_simplex_action)
		self.connect_simplex_controllers_action = QAction("Connect Simplex Controller", self)
		self.connect_simplex_controllers_action.setToolTip("Connect the selected Simplex controller to the Blue Steel controller.")
		self.connect_simplex_controllers_action.triggered.connect(self._on_connect_simplex_controller_requested)
		self.connect_simplex_controllers_action.setEnabled(self.current_editor is not None)
		simplex_menu.addAction(self.connect_simplex_controllers_action)
		conversion_cleanup_menu.addSeparator()
		self.prepare_for_publishing_action = QAction("Prepare For Publishing", self)
		self.prepare_for_publishing_action.setToolTip("Prepare the current editor for publishing and remove editor access.")
		self.prepare_for_publishing_action.triggered.connect(self._on_prepare_for_publishing_requested)
		self.prepare_for_publishing_action.setEnabled(self.current_editor is not None)
		conversion_cleanup_menu	.addAction(self.prepare_for_publishing_action)

		help_menu = menu_bar.addMenu("Help")
		about_action = QAction("About", self)
		about_action.triggered.connect(self.show_about)
		help_menu.addAction(about_action)

	def _create_new_editor(self) -> None:
		selection = cmds.ls(selection=True) or []
		if not selection:
			self._set_status("No mesh selected to create a new system.", error=True)
			return

		name, ok = QInputDialog.getText(self, "New Editor", "Enter a name space for the new editor:")
		name = (name or "").strip()
		if not ok or not name:
			self._set_status("Editor creation cancelled.")
			return

		try:
			new_editor = BlueSteelEditor.create_new(editor_name=name, mesh_name=selection[0]).name
		except Exception as exc:
			self._set_status(f"Error creating editor: {exc}", error=True)
			return

		if isinstance(self.scene_editor_tracker, BlueSteelEditorsTracker):
			self.scene_editor_tracker.register_scene_editor_nodes()
		self.set_current_editor(new_editor)
		self._set_status(f"Created new system with root: {selection[0]}")

	def _import_objs(self) -> None:
		if self.current_editor is None:
			self._set_status("No system selected.", warning=True)
			return

		directory = QFileDialog.getExistingDirectory(self, "Select Import Directory")
		if not directory:
			self._set_status("Import cancelled.")
			return

		self._clear_trackers_for_scene_operation()
		try:
			self.current_editor.import_objs(directory)
		except Exception as exc:
			self._set_status(f"Error importing shapes: {exc}", error=True)
			return
		finally:
			self._restart_trackers_after_scene_operation()

		self._reload_shapes_from_editor()
		self._reload_editor_menu()
		self._set_status(f"Imported all OBJs from '{directory}' as shapes.")

	def _import_shapes_from_blendshape_node(self, absolute_delta: bool = False) -> None:
		if self.current_editor is None:
			self._set_status("No system selected.", warning=True)
			return

		delta_label = "Absolute" if absolute_delta else "Relative"
		import_path, _selected_filter = QFileDialog.getOpenFileName(
			self,
			f"Import {delta_label} Shapes From BlendShape Node",
			"",
			"Maya Files (*.ma *.mb);;Maya ASCII (*.ma);;Maya Binary (*.mb)",
		)
		if not import_path:
			self._set_status("Import cancelled.")
			return

		self._clear_trackers_for_scene_operation()
		try:
			self.current_editor.import_shapes_from_blendshape_node(import_path, absolute_delta=absolute_delta)
		except Exception as exc:
			self._set_status(f"Error importing shapes from blendshape node: {exc}", error=True)
			return
		finally:
			self._restart_trackers_after_scene_operation()

		self._reload_shapes_from_editor()
		self._reload_editor_menu()
		delta_label = "absolute" if absolute_delta else "relative"
		self._set_status(f"Imported shapes from '{import_path}' as {delta_label} deltas.")

	def _import_split_data(self) -> None:
		if self.current_editor is None:
			self._set_status("No system selected.", warning=True)
			return

		directory = QFileDialog.getExistingDirectory(self, "Select Split Data Directory")
		if not directory:
			self._set_status("Import cancelled.")
			return

		choice_dialog = QDialog(self)
		choice_dialog.setWindowTitle("Import Split Data")
		choice_layout = QVBoxLayout(choice_dialog)
		choice_layout.addWidget(QLabel("Choose the split data to import:", choice_dialog))
		split_groups_checkbox = QCheckBox("Split Groups", choice_dialog)
		split_groups_checkbox.setChecked(True)
		choice_layout.addWidget(split_groups_checkbox)
		split_maps_checkbox = QCheckBox("Split Maps", choice_dialog)
		split_maps_checkbox.setChecked(True)
		choice_layout.addWidget(split_maps_checkbox)
		dialog_buttons = QDialogButtonBox(
			QDialogButtonBox.Ok | QDialogButtonBox.Cancel,
			parent=choice_dialog,
		)
		dialog_buttons.button(QDialogButtonBox.Ok).setText("Import")
		dialog_buttons.accepted.connect(choice_dialog.accept)
		dialog_buttons.rejected.connect(choice_dialog.reject)
		choice_layout.addWidget(dialog_buttons)
		if hasattr(choice_dialog, "exec"):
			result = choice_dialog.exec()
		else:
			result = choice_dialog.exec_()
		if result != QDialog.Accepted:
			self._set_status("Import cancelled.")
			return

		import_settings = split_groups_checkbox.isChecked()
		import_weights = split_maps_checkbox.isChecked()
		if not import_settings and not import_weights:
			self._set_status("Select at least one split data type to import.", warning=True)
			return
		if import_settings and import_weights:
			import_label = "split groups and split maps"
		elif import_settings:
			import_label = "split groups"
		else:
			import_label = "split maps"

		self._clear_trackers_for_scene_operation()
		try:
			self.current_editor.import_split_data(
				directory,
				import_weights=import_weights,
				import_settings=import_settings,
			)
		except Exception as exc:
			self._set_status(f"Error importing split data: {exc}", error=True)
			return
		finally:
			self._restart_trackers_after_scene_operation()

		self._reload_shapes_from_editor()
		self._reload_editor_menu()
		self._split_map_normalization_cache.clear()
		self._set_status(f"Imported {import_label} from '{directory}'.")

			
	def _on_create_split_shapes_editor_requested(self) -> None:
		if self.current_editor is None:
			self._set_status("No system selected.", warning=True)
			return
		combine_editor_name = self.current_editor.name
		self._clear_trackers_for_scene_operation()
		try:
			split_editor_name = self.current_editor.create_split_shapes_editor()


		except Exception as exc:
			self._set_status(f"Error splitting shapes: {exc}", error=True)
			return
		finally:
			self._restart_trackers_after_scene_operation()

		self._reload_shapes_from_editor()
		self._set_status(f"Created new split editor '{split_editor_name}' from '{self.current_editor.name}'.")
		self.set_current_editor(split_editor_name)
		delete_reply = QMessageBox.question(
			self,
			"Delete Combined Editor?",
			"Do you want to delete the original editor after splitting shapes?",
			QMessageBox.Yes | QMessageBox.No,
			QMessageBox.No,
		)
		if delete_reply == QMessageBox.Yes:
			cmds.delete(combine_editor_name)
			# we need to refresh the editor drop down menu.
			self._reload_editor_menu()

	def _export_split_data(self) -> None:
		if self.current_editor is None:
			self._set_status("No system selected.", warning=True)
			return

		directory = QFileDialog.getExistingDirectory(self, "Select Export Split Data Directory")
		if not directory:
			self._set_status("Export cancelled.")
			return

		self._clear_trackers_for_scene_operation()
		try:
			self.current_editor.export_split_data(directory)
		except Exception as exc:
			self._set_status(f"Error exporting split data: {exc}", error=True)
			return
		finally:
			self._restart_trackers_after_scene_operation()

		self._set_status(f"Exported split data to '{directory}'.")

	def _export_objs(self) -> None:
		if self.current_editor is None:
			self._set_status("No system selected.", warning=True)
			return

		directory = QFileDialog.getExistingDirectory(self, "Select Export Directory")
		if not directory:
			self._set_status("Export cancelled.")
			return

		self._clear_trackers_for_scene_operation()
		try:
			self.current_editor.export_all_objs(directory)
		except Exception as exc:
			self._set_status(f"Error exporting shapes: {exc}", error=True)
			return
		finally:
			self._restart_trackers_after_scene_operation()

		self._reload_shapes_from_editor()
		self._set_status(f"Exported all shapes as OBJs to '{directory}'.")

	def _export_shapes_as_blendshape_node(self, absolute_delta: bool = False) -> None:
		if self.current_editor is None:
			self._set_status("No system selected.", warning=True)
			return

		delta_label = "Absolute" if absolute_delta else "Relative"
		export_path, _selected_filter = QFileDialog.getSaveFileName(
			self,
			f"Export {delta_label} Shapes To BlendShape Node",
			f"{self.current_editor.name}.mb",
			"Maya Binary (*.mb);;Maya ASCII (*.ma);;Maya Files (*.ma *.mb)",
		)
		if not export_path:
			self._set_status("Export cancelled.")
			return
		if os.path.splitext(export_path)[1].lower() not in (".ma", ".mb"):
			export_path += ".mb"

		self._clear_trackers_for_scene_operation()
		try:
			self.current_editor.export_shapes_as_blendshape_node(export_path, absolute_delta=absolute_delta)
		except Exception as exc:
			self._set_status(f"Error exporting shapes as blendshape node: {exc}", error=True)
			return
		finally:
			self._restart_trackers_after_scene_operation()

		delta_label = "absolute" if absolute_delta else "relative"
		self._set_status(f"Exported {delta_label} shapes as a blendshape node to '{export_path}'.")

	def _rename_current_editor(self) -> None:
		if self.current_editor is None:
			self._set_status("No system selected.", warning=True)
			return

		current_name = self.current_editor.name
		new_name, ok = QInputDialog.getText(
			self,
			"Rename Editor",
			"Enter a name space for the editor:",
			text=current_name,
		)
		new_name = (new_name or "").strip()
		if not ok or not new_name:
			self._set_status("Editor renaming cancelled.")
			return

		try:
			renamed = BlueSteelEditor.rename_editor(current_name, new_name)
		except Exception as exc:
			self._set_status(f"Error renaming editor: {exc}", error=True)
			return

		self.set_current_editor(renamed)
		self._set_status(f"Renamed editor '{current_name}' to '{renamed}'.")

	def _on_fix_invisible_blendshapes_requested(self) -> None:
		"""Fix Shape Editor visibility issues caused by misplaced mid-layer directories."""
		if self.current_editor is None:
			self._set_status("No system selected.", warning=True)
			return

		try:
			self.current_editor.fix_mid_layer_blendshapes_indices_position()
		except Exception as exc:
			self._set_status(f"Error fixing invisible blendshapes: {exc}", error=True)
			return

		self._set_status("Fixed invisible blendshapes in the Shape Editor.")

	def _toggle_exploded_container_action_state(self, collapsed: bool) -> None:
		if self.explode_container_action is None:
			return
		if collapsed:
			self.explode_container_action.setText("Break Containers in Node Editor")
			self.explode_container_action.setToolTip("Expose nodes inside container assets in Node Editor.")
		else:
			self.explode_container_action.setText("Collapse Containers in Node Editor")
			self.explode_container_action.setToolTip("Hide internal container nodes in Node Editor.")

	def _toggle_node_editor_container_view(self) -> None:
		if not cmds.nodeEditor("nodeEditorPanel1NodeEditorEd", exists=True):
			self._set_status("Node Editor panel not found.", warning=True)
			return

		collapsed = bool(cmds.nodeEditor("nodeEditorPanel1NodeEditorEd", q=True, useAssets=True))
		cmds.nodeEditor("nodeEditorPanel1NodeEditorEd", e=True, useAssets=not collapsed)
		self._toggle_exploded_container_action_state(not collapsed)

	def _on_connect_simplex_controller_requested(self) -> None:
		if self.current_editor is None:
			self._set_status("Please select a Blue Steel Editor before connecting Simplex controllers.",
					         warning=True)
			return

		selection = cmds.ls(selection=True, flatten=True) or []
		if not selection:
			self._set_status("No controller selected. Please select a Simplex controller to connect.", 
					warning=True)
			return
		controller = selection[0]
		if cmds.nodeType(controller) != "transform":
			self._set_status("Selected object is not a transform node. Please select a Simplex controller transform.", 
					warning=True)
			return
		if simplex_commands.get_simplex_node_from_controller(controller) is None:
			self._set_status("Selected controller is not part of a Simplex facial system. Please select a valid Simplex controller.", 
					warning=True)
			return
		simplex_commands.connect_blue_steel_ctrl_to_simplex_ctrl(
			blue_steel_ctrl=self.current_editor.face_ctrl,
			simplex_ctrl=controller,)

	def _on_simplex_converter_requested(self) -> None:
		if self.current_editor is None:
			self._set_status("Please select a Blue Steel Editor before converting Simplex systems.",
					          warning=True)
			return

		self._clear_trackers_for_scene_operation()
		try:
			selection = show_simplex_converter_dialog() or {}
			if not selection:
				self._set_status("Simplex conversion cancelled.")
				return

			simplex_commands.add_simplex_shapes_to_editor(
				editor=self.current_editor,
				simplex_node=selection.get("simplex_node"),
				mesh=selection.get("mesh"),
				merge_sides=selection.get("merge_sides"),
				level_range=selection.get("level_range"),
			)
		except Exception as exc:
			self._set_status(f"Error during Simplex conversion: {exc}", error=True)
			return
		finally:
			self._restart_trackers_after_scene_operation()

		self._reload_shapes_from_editor()
		self._reload_editor_menu()
		self._set_status("Simplex conversion completed.")

	def _on_prepare_for_publishing_requested(self) -> None:
		if self.current_editor is None:
			self._set_status("Please select a Blue Steel Editor before preparing for publishing.", warning=True)
			return

		reply = QMessageBox.question(
			self,
			"Prepare For Publishing",
			"This action will prepare the system for publishing and you will no longer have access to the editor controls for this system.\n\nDo you want to continue?",
			QMessageBox.Yes | QMessageBox.No,
			QMessageBox.No,
		)
		if reply != QMessageBox.Yes:
			self._set_status("Prepare for publishing cancelled.")
			return
		try:
			self.current_editor.prepare_for_publishing()
		except Exception as exc:
			self._set_status(f"Error preparing for publishing: {exc}", error=True)
			return

	def _on_value_drag_state_changed(self, active: bool) -> None:
		self._primaries_drag_active = active
		if not active:
			self._resort_value_sorted_lists_if_needed()

	def _resort_value_sorted_lists_if_needed(self) -> None:
		if self._primaries_drag_active:
			return
		if self._primary_tree_sort_by_value:
			self._sort_primaries_tree()

	def _apply_shapes_name_sort(self) -> None:
		self._shapes_proxy.setSortRole(ShapeItemsModel.NameRole)
		self._shapes_proxy.sort(0, Qt.AscendingOrder)
		self._active_shapes_proxy.setSortRole(ShapeItemsModel.NameRole)
		self._active_shapes_proxy.sort(0, Qt.AscendingOrder)

	def _first_selected_shape_name(self) -> Optional[str]:
		selected_names = self._selected_shape_names_from_shapes_view()
		if not selected_names:
			return None
		return selected_names[0]

	def _clear_related_shapes_cache(self) -> None:
		self._upstream_shapes_cache.clear()
		self._downstream_shapes_cache.clear()

	def _get_cached_related_shape_names(self, shape_name: str, *, upstream: bool) -> Set[str]:
		"""Return cached related shape-name set for one source shape and direction."""
		if self.current_editor is None:
			return set()

		cache = self._upstream_shapes_cache if upstream else self._downstream_shapes_cache
		cached_names = cache.get(shape_name)
		if cached_names is not None:
			return set(cached_names)

		if upstream:
			related = self.current_editor.get_related_shapes_upstream(shape_name) or []
		else:
			related = self.current_editor.get_related_shapes_downstream(shape_name) or []

		names = {str(shape) for shape in related}
		cache[shape_name] = names
		return set(names)

	def _set_directional_shapes_filter_state(self, *, downstream_checked: bool, upstream_checked: bool) -> None:
		self.shapes_downstream_button.blockSignals(True)
		self.shapes_upstream_button.blockSignals(True)
		self.shapes_downstream_button.setChecked(downstream_checked)
		self.shapes_upstream_button.setChecked(upstream_checked)
		self.shapes_downstream_button.blockSignals(False)
		self.shapes_upstream_button.blockSignals(False)

	def _set_active_shapes_filter_state(self, checked: bool) -> None:
		self._shapes_active_filter_enabled = bool(checked)
		self._shapes_proxy.set_active_only(checked)

	def _set_shapes_value_filter_button_state(self, checked: bool) -> None:
		was_blocked = self.shapes_list_active_button.blockSignals(True)
		try:
			self.shapes_list_active_button.setChecked(checked)
		finally:
			self.shapes_list_active_button.blockSignals(was_blocked)

	def _filter_shapes_active(self, checked: bool) -> None:
		if not checked:
			self._clear_shapes_filters()
			return
		self._clear_shapes_filters(rebuild_ui=False)
		visible_names = []
		for row in range(self._shape_model.rowCount()):
			index = self._shape_model.index(row, 0)
			if self._shapes_proxy._is_with_value_shape(self._shape_model, index):
				visible_names.append(str(self._shape_model.data(index, ShapeItemsModel.NameRole)))
		self._shapes_proxy.set_visible_names(visible_names)
		self._set_shapes_value_filter_button_state(True)
		self._apply_shapes_name_sort()
		self._rebuild_shapes_tree()
		self._update_delegate_name_columns()
		self._update_info_labels()
		self._set_status("Listed shapes with value at the time of filtering.")

	def _refresh_active_shapes_filter(self) -> None:
		if not self._shapes_active_filter_enabled and not self._shapes_proxy.color_filter_active():
			return
		self._shapes_proxy.invalidateFilter()
		self._rebuild_shapes_tree()
		self._update_delegate_name_columns()
		self._update_info_labels()

	def _filter_shapes_downstream(self, checked: bool) -> None:
		if not checked:
			self._clear_shapes_filters(keep_selection=True)
			self._set_status("Cleared downstream filter.")
			return
		if self.current_editor is None:
			self._set_directional_shapes_filter_state(downstream_checked=False, upstream_checked=False)
			self._set_status("No system selected.", warning=True)
			return
		shape_name = self._first_selected_shape_name()
		if not shape_name:
			self._set_directional_shapes_filter_state(downstream_checked=False, upstream_checked=False)
			self._set_status("Select one shape first.", warning=True)
			return
		self._clear_shapes_filters(keep_selection=True, rebuild_ui=False)
		visible_names = self._get_cached_related_shape_names(shape_name, upstream=False)
		self._shapes_proxy.set_visible_names(tuple(visible_names))
		self._set_directional_shapes_filter_state(downstream_checked=True, upstream_checked=False)
		self._apply_shapes_name_sort()
		self._rebuild_shapes_tree()
		self._update_delegate_name_columns()
		self._update_info_labels()
		self._set_status(f"Filtered downstream shapes from '{shape_name}'.")

	def _filter_shapes_upstream(self, checked: bool) -> None:
		if not checked:
			self._clear_shapes_filters(keep_selection=True)
			self._set_status("Cleared upstream filter.")
			return
		if self.current_editor is None:
			self._set_directional_shapes_filter_state(downstream_checked=False, upstream_checked=False)
			self._set_status("No system selected.", warning=True)
			return
		shape_name = self._first_selected_shape_name()
		if not shape_name:
			self._set_directional_shapes_filter_state(downstream_checked=False, upstream_checked=False)
			self._set_status("Select one shape first.", warning=True)
			return
		self._clear_shapes_filters(keep_selection=True, rebuild_ui=False)
		visible_names = self._get_cached_related_shape_names(shape_name, upstream=True)
		self._shapes_proxy.set_visible_names(tuple(visible_names))
		self._set_directional_shapes_filter_state(downstream_checked=False, upstream_checked=True)
		self._apply_shapes_name_sort()
		self._rebuild_shapes_tree()
		self._update_delegate_name_columns()
		self._update_info_labels()
		self._set_status(f"Filtered upstream shapes from '{shape_name}'.")

	def _on_color_filter_swatch_toggled(self, *_args) -> None:
		"""Apply the color filter based on the checked swatch buttons."""
		selected_hexes = set()
		include_no_color = False
		for swatch, color_hex in self._color_filter_swatch_colors.items():
			try:
				if not swatch.isChecked():
					continue
			except RuntimeError:
				continue
			if color_hex is None:
				include_no_color = True
			else:
				selected_hexes.add(color_hex)
		if not selected_hexes and not include_no_color:
			self._shapes_proxy.set_color_filter(None)
		else:
			self._shapes_proxy.set_color_filter(set(selected_hexes), include_no_color)
		self._apply_shapes_name_sort()
		self._rebuild_shapes_tree()
		self._update_delegate_name_columns()
		self._update_info_labels()

	def _clear_color_filter_actions(self) -> None:
		"""Uncheck all color filter swatches without triggering refiltering per swatch."""
		for swatch in self._color_filter_swatch_buttons:
			try:
				was_blocked = swatch.blockSignals(True)
				try:
					swatch.setChecked(False)
				finally:
					swatch.blockSignals(was_blocked)
			except RuntimeError:
				continue
		self._shapes_proxy.set_color_filter(None)

	def _clear_shapes_filters(self, keep_selection: bool = False, rebuild_ui: bool = True) -> None:
		self._set_shapes_value_filter_button_state(False)
		if not keep_selection:
			self.primaries_view.clearSelection()
		self.shapes_search.blockSignals(True)
		self.shapes_search.setText("")
		self.shapes_search.blockSignals(False)
		self._shapes_proxy.set_search_terms([])
		self._set_active_shapes_filter_state(False)
		self._set_directional_shapes_filter_state(downstream_checked=False, upstream_checked=False)
		self._clear_color_filter_actions()
		selected_names = self._selected_primary_tree_names() if keep_selection else []
		self._apply_primary_selection_shapes_filter(selected_names)
		if rebuild_ui:
			self._apply_shapes_name_sort()
			self._rebuild_shapes_tree()
			self._update_delegate_name_columns()
			self._update_info_labels()
		if not keep_selection:
			self._set_status("Cleared all shapes filters.")

	def _on_primaries_search_changed(self, terms) -> None:
		self._apply_primaries_tree_filter(terms)
		self._update_delegate_name_columns()
		self._update_info_labels()

	def _on_shapes_search_changed(self, terms) -> None:
		self._shapes_proxy.set_search_terms(terms)
		self._rebuild_shapes_tree()
		self._update_delegate_name_columns()
		self._update_info_labels()

	def _on_active_shapes_search_changed(self, terms) -> None:
		self._active_shapes_proxy.set_search_terms(terms)
		self._update_delegate_name_columns()
		self._update_info_labels()

	def _on_shape_model_data_changed(self, _top_left, _bottom_right, roles) -> None:
		"""Run expensive UI refreshes only when non-value data changed."""
		if self._is_split_tab_active() and self.split_primaries_tree is not None:
			self.split_primaries_tree.sync_source_data(_top_left, _bottom_right, roles)
		if self._syncing_shapes_tree:
			return
		self._sync_shapes_tree_items_from_source_rows(_top_left, _bottom_right)
		if self._shapes_active_filter_enabled and (
			not roles or ShapeItemsModel.ValueRole in roles or Qt.DisplayRole in roles
		):
			self._active_shapes_filter_refresh_timer.start()
		elif self._shapes_proxy.color_filter_active() and (
			not roles or ShapeItemsModel.ColorRole in roles or Qt.DisplayRole in roles
		):
			self._active_shapes_filter_refresh_timer.start()
		if roles and all(
			role in (ShapeItemsModel.ValueRole, Qt.DisplayRole, ShapeItemsModel.MutedRole, ShapeItemsModel.LockedRole)
			for role in roles
		):
			# Value changes can move shapes in or out of the Active Shapes list.
			self._update_info_labels()
			return
		self._update_info_labels()
		self._update_delegate_name_columns()

	def _on_shapes_item_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
		"""Toggle group expansion when clicking a shapes-tree header row."""
		if item is None:
			return
		if not bool(item.data(0, ShapeItemsModel.IsHeaderRole)):
			return
		item.setExpanded(not item.isExpanded())
		self._update_delegate_name_columns()
		self._update_info_labels()

	def _on_shapes_selection_changed(self) -> None:
		self._update_info_labels()
		self._update_heat_map_target_from_shapes_selection()
		if self.current_editor is None or not self.shapes_auto_pose_button.isChecked():
			return
		shape_names = self._selected_shape_names_from_shapes_view()
		if not shape_names:
			return
		self._set_shape_pose_by_name(shape_names[0])

	def _on_shapes_toggle_upstream_filter_requested(self) -> None:
		"""Toggle selected-shape upstream filter from Shapes panel G shortcut."""
		if self.current_editor is None:
			self._set_status("No system selected.", warning=True)
			return
		self.shapes_upstream_button.toggle()

	def _on_shapes_double_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
		"""Set clicked shape to its pose from the shapes tree."""
		if item is None or bool(item.data(0, ShapeItemsModel.IsHeaderRole)):
			return
		shape_name = str(item.data(0, ShapeItemsModel.NameRole) or "")
		if not shape_name:
			return
		self._set_shape_pose_by_name(shape_name)

	def _show_shapes_context_menu(self, pos) -> None:
		sender = self.sender()

		if self.current_editor is None:
			return
		if sender == self.shapes_view:
			selected_shapes = self._selected_shape_names_from_shapes_view()
		elif sender == self.active_shapes_view:
			selected_shapes = self._selected_shape_names_from_active_shapes_view()
		else:
			return
		if not selected_shapes:
			return

		menu = QMenu(sender)
		extract_action = menu.addAction("Extract Selected")
		reset_deltas_action = menu.addAction("Reset Deltas")
		set_color_menu = menu.addMenu("Set Color")
		color_actions = {}
		for color_name, color_hex in SHAPE_CUSTOM_COLORS.items():
			color_action = set_color_menu.addAction(_color_swatch_icon(color_hex), color_name)
			color_actions[color_action] = color_hex
		set_color_menu.addSeparator()
		clear_color_action = set_color_menu.addAction("Clear")
		menu.addSeparator()
		delete_action = menu.addAction("Delete")
		if hasattr(menu, "exec"):
			selected_action = menu.exec(sender.mapToGlobal(pos))
		else:
			selected_action = menu.exec_(sender.mapToGlobal(pos))
		if selected_action == delete_action:
			self.remove_selected_shapes(selected_shapes)
		elif selected_action in color_actions:
			self._set_shapes_custom_color(selected_shapes, color_actions[selected_action])
		elif selected_action == clear_color_action:
			self._clear_shapes_custom_color(selected_shapes)
		elif selected_action == extract_action:
			self.extract_selected(selected_shapes)
		elif selected_action == reset_deltas_action:
			try:
				if self.blendshape_tracker is not None:
					self.blendshape_tracker.stop()
				self.current_editor.reset_delta_for_shapes(selected_shapes)
			except Exception as exc:
				self._set_status(f"Error resetting deltas: {exc}", error=True)
				return
			finally:
				if self.blendshape_tracker is not None:
					self.blendshape_tracker.start()
			self._set_status(f"Reset deltas for {len(selected_shapes)} shape(s).")

	def _set_shapes_custom_color(self, shape_names, color_hex: str) -> None:
		if self.current_editor is None:
			return
		try:
			for shape_name in shape_names:
				self.current_editor.set_shape_custom_color(shape_name, color_hex)
		except Exception as exc:
			self._set_status(f"Error setting shape color: {exc}", error=True)
			return
		color = QColor(color_hex)
		for shape_name in shape_names:
			self._apply_shape_color_to_views(shape_name, color)
		self._set_status(f"Set color for {len(shape_names)} shape(s).")

	def _apply_shape_color_to_views(self, shape_name: str, color: Optional[QColor]) -> None:
		"""Push a custom color to every view that renders shape names."""
		self._shape_model.set_shape_color_local(shape_name, color)
		shape_item = self._shape_tree_items.get(shape_name)
		if shape_item is not None:
			shape_item.setData(0, ShapeItemsModel.ColorRole, color)
		primary_item = self._primary_tree_items.get(shape_name)
		if primary_item is not None:
			primary_item.setData(0, ShapeItemsModel.ColorRole, color)

	def _clear_shapes_custom_color(self, shape_names) -> None:
		if self.current_editor is None:
			return
		try:
			for shape_name in shape_names:
				self.current_editor.remove_shape_custom_color(shape_name)
		except Exception as exc:
			self._set_status(f"Error clearing shape color: {exc}", error=True)
			return
		for shape_name in shape_names:
			self._apply_shape_color_to_views(shape_name, None)
		self._set_status(f"Cleared color for {len(shape_names)} shape(s).")

	def _on_shapes_item_expanded(self, item: QTreeWidgetItem) -> None:
		if item is None or not bool(item.data(0, ShapeItemsModel.IsHeaderRole)):
			return
		item.setData(0, ShapeItemsModel.HeaderCollapsedRole, False)
		self._update_shapes_tree_group_icon(item)
		self.shapes_view.viewport().update()

	def _on_shapes_item_collapsed(self, item: QTreeWidgetItem) -> None:
		if item is None or not bool(item.data(0, ShapeItemsModel.IsHeaderRole)):
			return
		item.setData(0, ShapeItemsModel.HeaderCollapsedRole, True)
		self._update_shapes_tree_group_icon(item)
		self.shapes_view.viewport().update()

	def _update_shapes_tree_group_icon(self, item: Optional[QTreeWidgetItem]) -> None:
		if item is None or not bool(item.data(0, ShapeItemsModel.IsHeaderRole)):
			return
		if item.isExpanded() and not self._primary_tree_folder_open_icon.isNull():
			item.setIcon(0, self._primary_tree_folder_open_icon)
		elif not self._primary_tree_folder_closed_icon.isNull():
			item.setIcon(0, self._primary_tree_folder_closed_icon)

	def _on_shapes_tree_data_changed(self, top_left: QModelIndex, bottom_right: QModelIndex, roles) -> None:
		if self._syncing_shapes_tree:
			return
		if self.current_editor is None:
			return
		if roles and ShapeItemsModel.ValueRole not in roles:
			return
		for row in range(top_left.row(), bottom_right.row() + 1):
			index = top_left.sibling(row, 0)
			if not index.isValid() or bool(index.data(ShapeItemsModel.IsHeaderRole)):
				continue
			if not bool(index.data(ShapeItemsModel.EditableRole)):
				continue
			shape_name = str(index.data(ShapeItemsModel.NameRole) or "")
			if not shape_name:
				continue
			value = float(index.data(ShapeItemsModel.ValueRole) or 0.0)
			self._shape_model.set_shape_value_by_name(shape_name, value)

	def _on_active_shapes_item_clicked(self, proxy_index: QModelIndex) -> None:
		if not proxy_index.isValid():
			return
		if not bool(self._active_shapes_proxy.data(proxy_index, ShapeItemsModel.IsHeaderRole)):
			return
		level = int(self._active_shapes_proxy.data(proxy_index, ShapeItemsModel.LevelRole) or 0)
		self._active_shapes_proxy.toggle_level_collapsed(level)
		self._update_delegate_name_columns()
		self._update_info_labels()

	def _on_active_shapes_selection_changed(self, *_args) -> None:
		self._update_info_labels()
		self._update_heat_map_target_from_active_shapes_selection()

	def _on_active_shapes_double_clicked(self, proxy_index: QModelIndex) -> None:
		if not proxy_index.isValid():
			return
		shape_name = str(self._active_shapes_proxy.data(proxy_index, ShapeItemsModel.NameRole) or "")
		if not shape_name:
			return
		self._select_shape_and_primaries(shape_name, focus_shape=True)

	def _select_shape_and_primaries(self, shape_name: str, *, focus_shape: bool = False) -> bool:
		if self.current_editor is None:
			return False
		shape = self.current_editor.get_shape(shape_name)
		if shape is None:
			self._set_status(f"Shape '{shape_name}' not found.", warning=True)
			return False

		first_primary_item = None
		was_blocked = self.primaries_view.blockSignals(True)
		try:
			self.primaries_view.clearSelection()
			for primary in shape.primaries:
				item = self._primary_tree_items.get(str(primary))
				if item is None:
					continue
				item.setSelected(True)
				if first_primary_item is None:
					first_primary_item = item
			if first_primary_item is not None:
				self.primaries_view.setCurrentItem(
					first_primary_item,
					0,
					QItemSelectionModel.NoUpdate,
				)
				self.primaries_view.scrollToItem(first_primary_item, QAbstractItemView.PositionAtCenter)
		finally:
			self.primaries_view.blockSignals(was_blocked)
		self._on_primaries_selection_changed()

		if not self._select_shape_in_shapes_tree(shape_name, ensure_visible=True):
			return False
		item = self._shape_tree_items.get(shape_name)
		if item is not None:
			self.shapes_view.scrollToItem(item, QAbstractItemView.PositionAtCenter)
		if focus_shape:
			self.shapes_view.setFocus(Qt.MouseFocusReason)
		return True

	def _set_shape_pose_from_proxy_index(self, proxy_model: QSortFilterProxyModel, proxy_index: QModelIndex) -> None:
		"""Set a shape to its pose using a row from a shapes proxy model."""
		if self.current_editor is None or not proxy_index.isValid():
			return
		if bool(proxy_model.data(proxy_index, ShapeItemsModel.IsHeaderRole)):
			return

		source_index = proxy_model.mapToSource(proxy_index)
		shape_name = self._shape_model.data(source_index, ShapeItemsModel.NameRole)
		if not shape_name:
			return

		shape = self.current_editor.get_shape(str(shape_name))
		if shape is None:
			self._set_status(f"Shape '{shape_name}' not found.", warning=True)
			return

		try:
			if self.blendshape_tracker is not None:
				self.blendshape_tracker.stop()
			self.current_editor.set_shape_pose(shape)
			changed_rows = self._shape_model.refresh_values_from_editor()
			for changed_name, changed_value, is_primary in changed_rows:
				if is_primary:
					self._sync_primary_tree_slider(changed_name, changed_value)
			self._resort_value_sorted_lists_if_needed()
			self._set_status(f"Set shape '{shape_name}' to its pose.")
		except Exception as exc:
			self._set_status(f"Error setting shape pose: {exc}", error=True)
			return
		finally:
			if self.blendshape_tracker is not None:
				self.blendshape_tracker.start()

	def _set_shape_pose_by_name(self, shape_name: str) -> None:
		if self.current_editor is None:
			return
		shape = self.current_editor.get_shape(str(shape_name))
		if shape is None:
			self._set_status(f"Shape '{shape_name}' not found.", warning=True)
			return

		try:
			if self.blendshape_tracker is not None:
				self.blendshape_tracker.stop()
			self.current_editor.set_shape_pose(shape)
			changed_rows = self._shape_model.refresh_values_from_editor()
			for changed_name, changed_value, is_primary in changed_rows:
				if is_primary:
					self._sync_primary_tree_slider(changed_name, changed_value)
			self._resort_value_sorted_lists_if_needed()
			self._set_status(f"Set shape '{shape_name}' to its pose.")
		except Exception as exc:
			self._set_status(f"Error setting shape pose: {exc}", error=True)
			return
		finally:
			if self.blendshape_tracker is not None:
				self.blendshape_tracker.start()

	def _compute_tree_max_name_width(self, tree: QTreeWidget) -> int:
		fm = tree.fontMetrics()
		max_width = 0

		def visit(item: QTreeWidgetItem) -> None:
			nonlocal max_width
			if item.isHidden():
				return
			if not bool(item.data(0, ShapeItemsModel.IsHeaderRole)):
				name = str(item.data(0, ShapeItemsModel.NameRole) or item.text(0) or "")
				max_width = max(max_width, fm.horizontalAdvance(name))
			for i in range(item.childCount()):
				visit(item.child(i))

		for i in range(tree.topLevelItemCount()):
			visit(tree.topLevelItem(i))
		return max_width

	def _compute_filtered_max_name_width(self, view: QListView, model: QSortFilterProxyModel) -> int:
		"""Return max name width for currently filtered rows in a proxy model."""
		fm = view.fontMetrics()
		max_width = 0
		for row in range(model.rowCount()):
			index = model.index(row, 0)
			name = model.data(index, ShapeItemsModel.NameRole) or ""
			max_width = max(max_width, fm.horizontalAdvance(name))
		return max_width

	def _update_delegate_name_columns(self) -> None:
		"""Align value columns using max name width of the *filtered* data per view."""
		primaries_width = self._compute_tree_max_name_width(self.primaries_view)
		shapes_width = self._compute_tree_max_name_width(self.shapes_view)
		active_shapes_width = self._compute_filtered_max_name_width(self.active_shapes_view, self._active_shapes_proxy)
		primary_drop_width = self._compute_filtered_max_name_width(self.primary_drop_view, self._primary_subset_proxy)
		work_shapes_width = self._compute_filtered_max_name_width(self.work_shapes_view, self._work_shape_model)
		self._primaries_delegate.set_name_column_width(primaries_width)
		self._shapes_delegate.set_name_column_width(shapes_width)
		self._active_shapes_delegate.set_name_column_width(active_shapes_width)
		self._primary_drop_delegate.set_name_column_width(primary_drop_width)
		self._work_shapes_delegate.set_name_column_width(work_shapes_width)
		self.primaries_view.viewport().update()
		self.shapes_view.viewport().update()
		self.active_shapes_view.viewport().update()
		self.primary_drop_view.viewport().update()
		self.work_shapes_view.viewport().update()

	def _rebuild_shapes_tree(self) -> None:
		self._syncing_shapes_tree = True
		try:
			selected_names = set(self._selected_shape_names_from_shapes_view())
			expanded_headers = self._shapes_tree_expanded_headers
			expanded_type_groups = self._shapes_tree_expanded_type_groups
			for i in range(self.shapes_view.topLevelItemCount()):
				header_item = self.shapes_view.topLevelItem(i)
				header_level = int(header_item.data(0, ShapeItemsModel.LevelRole) or -1)
				header_name = str(header_item.data(0, ShapeItemsModel.NameRole) or "")
				if header_name:
					expanded_headers[header_level] = header_item.isExpanded()
				for j in range(header_item.childCount()):
					type_item = header_item.child(j)
					type_name = str(type_item.data(0, ShapeItemsModel.NameRole) or "")
					if type_name:
						expanded_type_groups[(header_level, type_name)] = type_item.isExpanded()

			self.shapes_view.clear()
			self._shape_tree_items.clear()

			type_group_order = {
				"Primaries": 0,
				"Inbetweens": 1,
				"Combos": 2,
				"Combo Inbetweens": 3,
				"Other": 99,
			}

			def _shape_type_group_name(shape_type: str) -> str:
				if shape_type == "PrimaryShape":
					return "Primaries"
				if shape_type == "InbetweenShape":
					return "Inbetweens"
				if shape_type == "ComboShape":
					return "Combos"
				if shape_type == "ComboInbetweenShape":
					return "Combo Inbetweens"
				return "Other"

			current_group_item: Optional[QTreeWidgetItem] = None
			current_level_value: Optional[int] = None
			type_group_items = {}
			for row in range(self._shapes_proxy.rowCount()):
				proxy_index = self._shapes_proxy.index(row, 0)
				if not proxy_index.isValid():
					continue

				is_header = bool(self._shapes_proxy.data(proxy_index, ShapeItemsModel.IsHeaderRole))
				name = str(self._shapes_proxy.data(proxy_index, ShapeItemsModel.NameRole) or "")
				if not name:
					continue

				if is_header:
					level_value = int(self._shapes_proxy.data(proxy_index, ShapeItemsModel.LevelRole) or -1)
					group_item = QTreeWidgetItem([name])
					group_item.setData(0, ShapeItemsModel.IsHeaderRole, True)
					group_item.setData(0, ShapeItemsModel.NameRole, name)
					group_item.setData(0, ShapeItemsModel.LevelRole, level_value)
					group_item.setData(0, ShapeItemsModel.HeaderCollapsedRole, False)
					font = group_item.font(0)
					font.setBold(True)
					group_item.setFont(0, font)
					group_item.setFlags(Qt.ItemIsEnabled)
					self.shapes_view.addTopLevelItem(group_item)
					should_expand = expanded_headers.get(level_value, True)
					group_item.setExpanded(should_expand)
					group_item.setData(0, ShapeItemsModel.HeaderCollapsedRole, not should_expand)
					current_group_item = group_item
					current_level_value = level_value
					type_group_items = {}
					continue

				if current_group_item is None:
					current_group_item = QTreeWidgetItem(["Ungrouped"])
					current_group_item.setData(0, ShapeItemsModel.IsHeaderRole, True)
					current_group_item.setData(0, ShapeItemsModel.NameRole, "Ungrouped")
					current_group_item.setData(0, ShapeItemsModel.LevelRole, 999)
					current_group_item.setData(0, ShapeItemsModel.HeaderCollapsedRole, False)
					font = current_group_item.font(0)
					font.setBold(True)
					current_group_item.setFont(0, font)
					current_group_item.setFlags(Qt.ItemIsEnabled)
					self.shapes_view.addTopLevelItem(current_group_item)
					current_level_value = 999
					type_group_items = {}

				shape_type = str(self._shapes_proxy.data(proxy_index, ShapeItemsModel.TypeRole) or "")
				type_group_name = _shape_type_group_name(shape_type)
				type_group_item = type_group_items.get(type_group_name)
				if type_group_item is None:
					type_group_item = QTreeWidgetItem([type_group_name])
					type_group_item.setData(0, ShapeItemsModel.IsHeaderRole, True)
					type_group_item.setData(0, ShapeItemsModel.NameRole, type_group_name)
					type_group_item.setData(0, ShapeItemsModel.LevelRole, int(current_level_value if current_level_value is not None else 999))
					type_group_item.setData(0, ShapeItemsModel.HeaderCollapsedRole, False)
					type_group_item.setData(0, ShapeItemsModel.HeaderLevelRole, int(type_group_order.get(type_group_name, 999)))
					font = type_group_item.font(0)
					font.setBold(True)
					type_group_item.setFont(0, font)
					type_group_item.setFlags(Qt.ItemIsEnabled)
					current_group_item.addChild(type_group_item)
					should_expand = expanded_type_groups.get((int(current_level_value if current_level_value is not None else 999), type_group_name), True)
					type_group_item.setExpanded(should_expand)
					type_group_item.setData(0, ShapeItemsModel.HeaderCollapsedRole, not should_expand)
					type_group_items[type_group_name] = type_group_item

				leaf = QTreeWidgetItem([name])
				for role in (
					ShapeItemsModel.NameRole,
					ShapeItemsModel.TypeRole,
					ShapeItemsModel.ValueRole,
					ShapeItemsModel.MutedRole,
					ShapeItemsModel.LockedRole,
					ShapeItemsModel.LockIconVisibleRole,
					ShapeItemsModel.LevelRole,
					ShapeItemsModel.PrimariesRole,
					ShapeItemsModel.EditableRole,
					ShapeItemsModel.IsHeaderRole,
					ShapeItemsModel.HeaderLevelRole,
					ShapeItemsModel.HeaderCollapsedRole,
					ShapeItemsModel.UpstreamRelatedRole,
					ShapeItemsModel.DownstreamRelatedRole,
					ShapeItemsModel.ColorRole,
				):
					leaf.setData(0, role, self._shapes_proxy.data(proxy_index, role))
				leaf.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsDragEnabled)
				type_group_item.addChild(leaf)
				self._shape_tree_items[name] = leaf
				if name in selected_names:
					leaf.setSelected(True)

			for i in range(self.shapes_view.topLevelItemCount()):
				stack = [self.shapes_view.topLevelItem(i)]
				while stack:
					item = stack.pop()
					self._update_shapes_tree_group_icon(item)
					for j in range(item.childCount()):
						stack.append(item.child(j))
		finally:
			self._syncing_shapes_tree = False

	def _sync_shapes_tree_items_from_source_rows(self, top_left: QModelIndex, bottom_right: QModelIndex) -> None:
		if not top_left.isValid() or not bottom_right.isValid() or not self._shape_tree_items:
			return
		self._syncing_shapes_tree = True
		try:
			for row in range(top_left.row(), bottom_right.row() + 1):
				source_index = self._shape_model.index(row, 0)
				if not source_index.isValid() or bool(self._shape_model.data(source_index, ShapeItemsModel.IsHeaderRole)):
					continue
				shape_name = str(self._shape_model.data(source_index, ShapeItemsModel.NameRole) or "")
				if not shape_name:
					continue
				item = self._shape_tree_items.get(shape_name)
				if item is None:
					continue
				# Item pointers can become stale while the tree is rebuilt.
				try:
					_ = item.treeWidget()
				except RuntimeError:
					self._shape_tree_items.pop(shape_name, None)
					continue
				for role in (
					ShapeItemsModel.NameRole,
					ShapeItemsModel.TypeRole,
					ShapeItemsModel.ValueRole,
					ShapeItemsModel.MutedRole,
					ShapeItemsModel.LockedRole,
					ShapeItemsModel.LockIconVisibleRole,
					ShapeItemsModel.LevelRole,
					ShapeItemsModel.PrimariesRole,
					ShapeItemsModel.EditableRole,
					ShapeItemsModel.IsHeaderRole,
					ShapeItemsModel.HeaderLevelRole,
					ShapeItemsModel.UpstreamRelatedRole,
					ShapeItemsModel.DownstreamRelatedRole,
				):
					try:
						item.setData(0, role, self._shape_model.data(source_index, role))
					except RuntimeError:
						self._shape_tree_items.pop(shape_name, None)
						break
		finally:
			self._syncing_shapes_tree = False

	def _selected_primary_tree_names(self) -> List[str]:
		names: List[str] = []
		for item in self.primaries_view.selectedItems():
			shape_name = item.data(0, self.PRIMARY_TREE_NAME_ROLE)
			if shape_name:
				names.append(str(shape_name))
		return names

	def _selected_split_primary_names(self) -> List[str]:
		if self.split_primaries_tree is None:
			return []
		return [
			str(item.data(0, ShapeItemsModel.NameRole))
			for item in self.split_primaries_tree.selectedItems()
			if item.parent() is not None and item.data(0, ShapeItemsModel.NameRole)
		]

	def _on_primary_drop_list_dropped(self, dropped_shape_names: Sequence[str]) -> None:
		names: List[str] = []
		if self.current_editor is not None:
			for shape_name in dropped_shape_names:
				shape = self.current_editor.get_shape(str(shape_name))
				if shape is not None:
					primaries = [str(primary) for primary in shape.primaries]
					if primaries:
						names.extend(primaries)
					else:
						names.append(str(shape_name))
				else:
					names.append(str(shape_name))

		# Keep compatibility with primaries-tree drops that may not include expected mime payload.
		if not names:
			names = self._selected_primary_tree_names()

		names = list(dict.fromkeys(name for name in names if name))
		if not names:
			return
		self._primary_subset_proxy.add_selected_names(names)
		self._primary_subset_proxy.sort(0, Qt.AscendingOrder)
		self._update_delegate_name_columns()
		self._update_info_labels()

	def _on_primary_drop_remove_requested(self, shape_names: Sequence[str]) -> None:
		removed = self._primary_subset_proxy.remove_selected_names(shape_names)
		if removed <= 0:
			self._set_status("No slider entries selected in Sliders Drop Box.", warning=True)
			return
		self._primary_subset_proxy.sort(0, Qt.AscendingOrder)
		self._update_delegate_name_columns()
		self._update_info_labels()
		self._set_status(f"Removed {removed} slider(s) from Sliders Drop Box.")

	def _fill_primary_drop_list_from_active(self) -> None:
		if self.current_editor is None:
			self._set_status("No system selected.", warning=True)
			return
		active_primaries = []
		for shape in self.current_editor.get_primary_shapes() or []:
			weight = self.current_editor.blendshape.get_weight_by_name(shape)
			if weight is None:
				continue
			if float(self.current_editor.blendshape.get_weight_value(weight)) > 0.0:
				active_primaries.append(str(shape))
		self._primary_subset_proxy.clear_selected_names()
		self._primary_subset_proxy.add_selected_names(active_primaries)
		self._primary_subset_proxy.sort(0, Qt.AscendingOrder)
		self._update_delegate_name_columns()
		self._update_info_labels()
		self._set_status(f"Loaded {len(active_primaries)} active primaries.")

	def _selected_names_from_list_view(self, view: QListView, model) -> List[str]:
		names: List[str] = []
		if view.selectionModel() is None:
			return names
		for index in view.selectionModel().selectedRows():
			if bool(model.data(index, ShapeItemsModel.IsHeaderRole)):
				continue
			shape_name = model.data(index, ShapeItemsModel.NameRole)
			if shape_name:
				names.append(str(shape_name))
		return names

	def _selected_work_shape_names(self) -> List[str]:
		return self._selected_names_from_list_view(self.work_shapes_view, self._work_shape_model)

	def _selected_active_shape_names(self) -> List[str]:
		return self._selected_names_from_list_view(self.active_shapes_view, self._active_shapes_proxy)

	def _selected_primary_drop_shape_names(self) -> List[str]:
		return self._selected_names_from_list_view(self.primary_drop_view, self._primary_subset_proxy)

	def _first_selected_work_shape_name(self) -> Optional[str]:
		selected_names = self._selected_work_shape_names()
		if not selected_names:
			return None
		return selected_names[0]

	def _select_work_shape(self, shape_name: str) -> None:
		index = self._work_shape_model.index_by_name(shape_name)
		if not index.isValid() or self.work_shapes_view.selectionModel() is None:
			return
		self.work_shapes_view.selectionModel().clearSelection()
		self.work_shapes_view.selectionModel().select(index, QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows)
		self.work_shapes_view.setCurrentIndex(index)

	def _on_work_shapes_selection_changed(self, *_args) -> None:
		self._update_work_shape_button_panel()
		self._update_heat_map_target_from_work_shapes_selection()

	def _on_display_heat_map_toggled(self, checked: bool) -> None:
		if self.current_editor is None or not env.DGA_NODES_SUPPORTED:
			return
		try:
			self.current_editor.display_heat_maps(bool(checked))
			if checked:
				if self._update_heat_map_target_from_shapes_selection():
					return
				if self._update_heat_map_target_from_active_shapes_selection():
					return
				self._update_heat_map_target_from_work_shapes_selection()
			else:
				self.current_editor.clear_heat_map_target()
		except Exception as exc:
			self._set_status(f"Error toggling heat map display: {exc}", error=True)

	def _is_heat_map_switch_active(self) -> bool:
		if self.heat_map_switch is None:
			return False
		if not env.DGA_NODES_SUPPORTED:
			return False
		return bool(self.heat_map_switch.isChecked())

	def _set_heat_map_target_for_editor(self, blendshape_name: str, shape_name: str) -> bool:
		if self.current_editor is None or not self._is_heat_map_switch_active():
			return False
		if not blendshape_name or not shape_name:
			return False
		try:
			self.current_editor.set_heat_map_target(blendshape_name, shape_name)
			return True
		except Exception:
			return False

	def _clear_heat_map_target_for_editor(self) -> None:
		if self.current_editor is None or not self._is_heat_map_switch_active():
			return
		try:
			self.current_editor.clear_heat_map_target()
		except Exception:
			pass

	def _update_heat_map_target_from_shapes_selection(self) -> bool:
		if self.current_editor is None or not self._is_heat_map_switch_active():
			return False
		selected_shape_names = self._selected_shape_names_from_shapes_view()
		if not selected_shape_names:
			self._clear_heat_map_target_for_editor()
			return False
		return self._set_heat_map_target_for_editor(self.current_editor.blendshape.name, selected_shape_names[0])

	def _update_heat_map_target_from_active_shapes_selection(self) -> bool:
		if self.current_editor is None or not self._is_heat_map_switch_active():
			return False
		selected_shape_names = self._selected_active_shape_names()
		if not selected_shape_names:
			return False
		return self._set_heat_map_target_for_editor(self.current_editor.blendshape.name, selected_shape_names[0])

	def _update_heat_map_target_from_work_shapes_selection(self) -> bool:
		if self.current_editor is None or not self._is_heat_map_switch_active():
			return False
		selected_shape_names = self._selected_work_shape_names()
		if not selected_shape_names:
			return False
		if self.current_editor.work_blendshape is None:
			return False
		return self._set_heat_map_target_for_editor(self.current_editor.work_blendshape.name, selected_shape_names[0])

	def _update_work_shape_button_panel(self) -> None:
		has_editor = self.current_editor is not None and self.current_editor.work_blendshape is not None
		selected_shape_name = self._first_selected_work_shape_name()
		has_selection = bool(selected_shape_name)
		self.work_add_button.setEnabled(has_editor)
		self.work_remove_button.setEnabled(has_editor and has_selection)
		self.work_paint_button.setEnabled(has_editor and has_selection)
		self.apply_work_shapes_button.setEnabled(has_editor and bool(self._work_shape_model.has_connected_driver_shapes()))

	def _stop_active_blendshape_trackers(self) -> None:
		for tracker in (
			self.blendshape_tracker,
			self.work_blendshape_tracker,
			self.split_map_edit_blendshape_tracker,
		):
			if tracker is not None:
				# print(f"Stopping active blendshape tracker {tracker.node_name}.")
				tracker.stop()

	def _start_active_blendshape_trackers(self) -> None:
		for tracker in (
			self.blendshape_tracker,
			self.work_blendshape_tracker,
			self.split_map_edit_blendshape_tracker,
		):
			if tracker is not None:
				# print(f"Starting active blendshape tracker {tracker.node_name}.")
				tracker.start()

	def _reload_work_shapes_from_editor(self) -> None:
		if self.current_editor is None:
			self._work_shape_model.rebuild_from_editor(None)
		else:
			self._work_shape_model.rebuild_from_editor(self.current_editor)
		self._update_delegate_name_columns()
		self._update_work_shape_button_panel()

	def _on_add_work_shape_clicked(self) -> None:
		if self.current_editor is None:
			self._set_status("No system selected.", warning=True)
			return
		try:
			self._stop_active_blendshape_trackers()
			work_shape_name = str(self.current_editor.add_work_shape())
		except Exception as exc:
			self._set_status(f"Error creating work shape: {exc}", error=True)
			return
		finally:
			self._start_active_blendshape_trackers()
		self._reload_work_shapes_from_editor()
		self._select_work_shape(work_shape_name)
		self._set_status(f"Created work shape '{work_shape_name}'.")

	def _on_remove_work_shapes_clicked(self) -> None:
		if self.current_editor is None:
			self._set_status("No system selected.", warning=True)
			return
		shape_names = self._selected_work_shape_names()
		if not shape_names:
			self._set_status("No work shapes selected.", warning=True)
			return

		active_edit_shape = self._work_shape_model.edit_shape_name()
		if active_edit_shape in shape_names:
			try:
				cmds.sculptTarget(self.current_editor.work_blendshape.name, e=True, t=-1)
			except Exception:
				pass
			self._work_shape_model.set_edit_shape(None)

		removed_count = 0
		try:
			self._stop_active_blendshape_trackers()
			self.current_editor.delete_work_shapes(shape_names)
			removed_count = len(shape_names)
		except Exception as exc:
			self._set_status(f"Error removing work shape(s): {exc}", error=True)
			return
		finally:
			self._start_active_blendshape_trackers()

		self._reload_work_shapes_from_editor()
		self._set_status(f"Removed {removed_count} work shape(s).")

	def _on_paint_work_shape_clicked(self) -> None:
		if self.current_editor is None:
			self._set_status("No system selected.", warning=True)
			return
		paint_weight = bool(QGuiApplication.keyboardModifiers() & Qt.AltModifier)
		shape_name = self._first_selected_work_shape_name()
		if not shape_name:
			self._set_status("Select one work shape first.", warning=True)
			return
		try:
			if paint_weight:
				target_id = self.current_editor.set_work_target_weight_paint_mode(shape_name)
			else:
				target_id = self.current_editor.set_work_target_mask_paint_mode(shape_name)
		except Exception as exc:
			self._set_status(f"Error entering paint mode: {exc}", error=True)
			return
		self._set_status(f"Paint mode on '{shape_name}' (target id {target_id}).")

	def _on_apply_work_shapes_clicked(self) -> None:
		if self.current_editor is None:
			self._set_status("No system selected.", warning=True)
			return
		try:
			self._stop_active_blendshape_trackers()
			applied_work_shapes = self.current_editor.apply_active_work_shapes()
		except Exception as exc:
			self._set_status(f"Error applying work shapes: {exc}", error=True)
			return
		finally:
			self._start_active_blendshape_trackers()
		self._reload_work_shapes_from_editor()
		self._set_status(f"Committed {len(applied_work_shapes)} linked shape(s). Check the Script Editor for the list.")

	def _on_work_shape_edit_mode_toggle_requested(self, shape_name: str, _state: bool) -> None:
		self._on_toggle_work_shape_edit_mode(shape_name)

	def _on_toggle_work_shape_edit_mode(self, shape_name: Optional[str] = None) -> None:
		if self.current_editor is None:
			self._set_status("No system selected.", warning=True)
			return
		if self.current_editor.work_blendshape is None:
			self._set_status("Work blendshape not found.", warning=True)
			return

		shape_name = shape_name or self._first_selected_work_shape_name()
		active_shape_name = self._work_shape_model.edit_shape_name()
		if not shape_name:
			if active_shape_name:
				try:
					cmds.sculptTarget(self.current_editor.work_blendshape.name, e=True, t=-1)
				except Exception as exc:
					self._set_status(f"Error disabling edit mode: {exc}", error=True)
					return
				self._work_shape_model.set_edit_shape(None)
				self._set_status("Work shape edit mode disabled.")
				self._update_work_shape_button_panel()
				return
			self._set_status("Select one work shape first.", warning=True)
			return

		if active_shape_name == shape_name:
			try:
				cmds.sculptTarget(self.current_editor.work_blendshape.name, e=True, t=-1)
			except Exception as exc:
				self._set_status(f"Error disabling edit mode: {exc}", error=True)
				return
			self._work_shape_model.set_edit_shape(None)
			self._set_status("Work shape edit mode disabled.")
			self._update_work_shape_button_panel()
			return

		if self._work_shape_model.is_shape_connected(shape_name):
			self._set_status(f"Cannot enable edit mode for '{shape_name}' because it has a connected mesh.", warning=True)
			self._update_work_shape_button_panel()
			return

		try:
			self.current_editor.set_work_shape_editable(shape_name)
		except Exception as exc:
			self._set_status(f"Error enabling edit mode: {exc}", error=True)
			return
		self._work_shape_model.set_edit_shape(shape_name)
		self._set_status(f"Edit mode enabled for '{shape_name}'.")

		self._update_work_shape_button_panel()

	def _on_work_shapes_double_clicked(self, model_index: QModelIndex) -> None:
		if self.current_editor is None or not model_index.isValid():
			return
		shape_name = str(self._work_shape_model.data(model_index, ShapeItemsModel.NameRole) or "")
		if not shape_name:
			return
		if QGuiApplication.keyboardModifiers() & Qt.AltModifier:
			if self.shapes_list_active_button.isChecked():
				self.shapes_list_active_button.setChecked(False)
			try:
				connected_shape_name = self.current_editor.get_work_shape_driver(shape_name)
			except Exception as exc:
				self._set_status(f"Error finding connected shape for '{shape_name}': {exc}", error=True)
				return
			if not connected_shape_name:
				self._set_status(f"Work shape '{shape_name}' is not connected to a shape.", warning=True)
				return
			connected_shape_name = str(connected_shape_name)
			self._set_shape_pose_by_name(connected_shape_name)
			self._select_shape_and_primaries(connected_shape_name)
			return
		self._begin_inline_workshape_rename(model_index)

	def _on_work_shape_drop_received(self, work_shape_name: str, source_shape_name: str) -> None:
		if self.current_editor is None:
			self._set_status("No system selected.", warning=True)
			return
		try:
			self._stop_active_blendshape_trackers()
			self.current_editor.connect_work_blendshape_weight_to_blendshape_weight(work_shape_name,
																		   source_shape_name)
		except Exception as exc:
			self._set_status(f"Error connecting work shape '{work_shape_name}': {exc}", error=True)
			return
		finally:
			self._start_active_blendshape_trackers()
		self._reload_work_shapes_from_editor()
		self._work_shape_model.set_driver_connected_state_local(work_shape_name, True)
		self._select_work_shape(work_shape_name)
		self._set_status(f"Connected work shape '{work_shape_name}' to '{source_shape_name}'.")

	def _on_work_shape_break_link_requested(self, work_shape_name: str) -> None:
		if self.current_editor is None:
			self._set_status("No system selected.", warning=True)
			return
		try:
			self._stop_active_blendshape_trackers()
			self.current_editor.disconnect_work_blendshape_weight(work_shape_name)
		except Exception as exc:
			self._set_status(f"Error breaking link for '{work_shape_name}': {exc}", error=True)
			return
		finally:
			self._start_active_blendshape_trackers()
		self._reload_work_shapes_from_editor()
		self._work_shape_model.set_driver_connected_state_local(work_shape_name, False)
		self._select_work_shape(work_shape_name)
		self._set_status(f"Broke link for work shape '{work_shape_name}'.")

	def _has_copied_work_weight_map_values(self) -> bool:
		if self.current_editor is None:
			return False
		return getattr(self.current_editor, "copied_weight_map_values", None) is not None

	def _on_work_shape_duplicate_requested(self, work_shape_name: str) -> None:
		if self.current_editor is None:
			self._set_status("No system selected.", warning=True)
			return
		try:
			self._stop_active_blendshape_trackers()
			new_work_shape_name = str(self.current_editor.duplicate_work_shape(work_shape_name))
		except Exception as exc:
			self._set_status(f"Error duplicating work shape '{work_shape_name}': {exc}", error=True)
			return
		finally:
			self._start_active_blendshape_trackers()
		self._reload_work_shapes_from_editor()
		self._select_work_shape(new_work_shape_name)
		self._set_status(f"Duplicated work shape '{work_shape_name}' to '{new_work_shape_name}'.")	

	def _on_work_shape_extract_requested(self, work_shape_name: str) -> None:
		if self.current_editor is None:
			self._set_status("No system selected.", warning=True)
			return
		try:
			self._stop_active_blendshape_trackers()
			new_shape_name = str(self.current_editor.extract_work_shape(work_shape_name))
		except Exception as exc:
			self._set_status(f"Error extracting shape from work shape '{work_shape_name}': {exc}", error=True)
			return
		finally:
			self._start_active_blendshape_trackers()
		self._reload_work_shapes_from_editor()
		if self.current_editor is not None and self.current_editor.work_blendshape is not None:
			weight = self.current_editor.work_blendshape.get_weight_by_name(work_shape_name)
			if weight is not None:
				self._work_shape_model.set_connected_state_local(work_shape_name, bool(weight in (self.current_editor.get_work_blendshape_connected_targets_weights() or [])))
		self._select_work_shape(work_shape_name)
		self._set_status(f"Extracted shape '{new_shape_name}' from work shape '{work_shape_name}'.")

	def _on_work_shape_connected_mesh_requested(self, work_shape_name: str) -> None:
		if self.current_editor is None or self.current_editor.work_blendshape is None:
			self._set_status("No system selected.", warning=True)
			return
		weight = self.current_editor.work_blendshape.get_weight_by_name(work_shape_name)
		if weight is None:
			self._set_status(f"Work shape '{work_shape_name}' not found.", warning=True)
			return
		try:
			edit_mesh = self.current_editor.get_work_shape_edit_mesh(weight)
		except Exception as exc:
			self._set_status(f"Error finding connected mesh for '{work_shape_name}': {exc}", error=True)
			return
		if not edit_mesh or not cmds.objExists(edit_mesh):
			self._set_status(f"No connected mesh found for '{work_shape_name}'.", warning=True)
			return
		cmds.select(edit_mesh, replace=True)
		self._set_status(f"Selected connected mesh '{edit_mesh}' for '{work_shape_name}'.")

	def _on_work_shape_copy_weights_requested(self, work_shape_name: str) -> None:
		if self.current_editor is None:
			self._set_status("No system selected.", warning=True)
			return
		try:
			self.current_editor.copy_work_weight_map_values(work_shape_name)
		except Exception as exc:
			self._set_status(f"Error copying weight map values from '{work_shape_name}': {exc}", error=True)
			return
		self._set_status(f"Copied weight map values from '{work_shape_name}'.")

	def _on_work_shape_paste_weights_requested(self, work_shape_name: str) -> None:
		if self.current_editor is None:
			self._set_status("No system selected.", warning=True)
			return
		try:
			self.current_editor.paste_work_weight_map_values(work_shape_name)
		except Exception as exc:
			self._set_status(f"Error pasting weight map values to '{work_shape_name}': {exc}", error=True)
			return
		self._set_status(f"Pasted weight map values to '{work_shape_name}'.")

	def _on_work_shape_paste_inverted_weights_requested(self, work_shape_name: str) -> None:
		if self.current_editor is None:
			self._set_status("No system selected.", warning=True)
			return
		try:
			self.current_editor.paste_inverted_work_weight_map_values(work_shape_name)
		except Exception as exc:
			self._set_status(f"Error pasting inverted weight map values to '{work_shape_name}': {exc}", error=True)
			return
		self._set_status(f"Pasted inverted weight map values to '{work_shape_name}'.")

	def _on_work_shape_add_copied_weights_requested(self, work_shape_name: str) -> None:
		if self.current_editor is None:
			self._set_status("No system selected.", warning=True)
			return
		try:
			self.current_editor.add_work_weight_map_values(work_shape_name)
		except Exception as exc:
			self._set_status(f"Error adding copied weight map values to '{work_shape_name}': {exc}", error=True)
			return
		self._set_status(f"Added copied weight map values to '{work_shape_name}'.")

	def _on_work_shape_subtract_copied_weights_requested(self, work_shape_name: str) -> None:
		if self.current_editor is None:
			self._set_status("No system selected.", warning=True)
			return
		try:
			self.current_editor.subtract_work_weight_map_values(work_shape_name)
		except Exception as exc:
			self._set_status(f"Error subtracting copied weight map values from '{work_shape_name}': {exc}", error=True)
			return
		self._set_status(f"Subtracted copied weight map values from '{work_shape_name}'.")

	def _on_work_shapes_normalize_weights_requested(self, work_shape_names: Sequence[str]) -> None:
		if self.current_editor is None:
			self._set_status("No system selected.", warning=True)
			return
		shape_names = [str(name) for name in (work_shape_names or []) if str(name)]
		if not shape_names:
			self._set_status("No work shapes selected.", warning=True)
			return
		if len(shape_names) == 1:
			self._set_status(f"Cannot Normalize Only One Work Shape", warning=True)
			return
		try:
			self.current_editor.normalize_work_weight_map_values(shape_names)
		except Exception as exc:
			self._set_status(f"Error normalizing work-shape weight maps: {exc}", error=True)
			return
		self._set_status(f"Normalized weight maps for {len(shape_names)} work shape(s).")

	def _on_work_shape_clear_weights_requested(self, work_shape_name: str) -> None:
		if self.current_editor is None:
			self._set_status("No system selected.", warning=True)
			return
		try:
			print(f"Clearing weight map values for '{work_shape_name}'...")
			self.current_editor.clear_work_weight_map_values(work_shape_name)
		except Exception as exc:
			self._set_status(f"Error clearing weight map values for '{work_shape_name}': {exc}", error=True)
			return
		self._set_status(f"Cleared weight map values for '{work_shape_name}'.")

	def _begin_inline_workshape_rename(self, model_index: QModelIndex) -> None:
		if self.current_editor is None or not model_index.isValid():
			return
		old_name = str(self._work_shape_model.data(model_index, ShapeItemsModel.NameRole) or "")
		if not old_name:
			return

		if self._workshape_rename_editor is not None:
			self._cancel_inline_workshape_rename()

		class _OptionRect:
			pass

		option = _OptionRect()
		option.rect = self.work_shapes_view.visualRect(model_index)
		_, text_rect = self._work_shapes_delegate._area_rects(option, model_index)

		editor = InlineWorkshapeRenameEditor(self.work_shapes_view.viewport())
		editor.setText(old_name)
		editor.setGeometry(text_rect.adjusted(0, 2, 0, -2))
		editor.selectAll()
		editor.show()
		editor.setFocus(Qt.MouseFocusReason)

		self._workshape_rename_editor = editor
		self._workshape_rename_old_name = old_name
		editor.submitted.connect(self._commit_inline_workshape_rename)
		editor.canceled.connect(self._cancel_inline_workshape_rename)

	def _cancel_inline_workshape_rename(self) -> None:
		editor = self._workshape_rename_editor
		self._workshape_rename_editor = None
		self._workshape_rename_old_name = ""
		if editor is not None:
			editor.deleteLater()

	def _commit_inline_workshape_rename(self) -> None:
		editor = self._workshape_rename_editor
		old_name = self._workshape_rename_old_name
		self._workshape_rename_editor = None
		self._workshape_rename_old_name = ""
		if editor is None:
			return

		new_name = (editor.text() or "").strip()
		editor.deleteLater()

		if self.current_editor is None or not old_name:
			return
		if not new_name or new_name == old_name:
			return

		try:
			self._stop_active_blendshape_trackers()
			self.current_editor.rename_work_shape(old_name, new_name)
		except Exception as exc:
			self._set_status(f"Error renaming work shape: {exc}", error=True)
			return
		finally:
			self._start_active_blendshape_trackers()

		if self._work_shape_model.edit_shape_name() == old_name:
			self._work_shape_model.set_edit_shape(new_name)
		self._reload_work_shapes_from_editor()
		self._select_work_shape(new_name)
		self._set_status(f"Renamed work shape '{old_name}' to '{new_name}'.")

	def _capture_linked_drag_state(self) -> None:
		self._linked_primary_start_values = {}
		self._linked_work_start_values = {}
		for shape_name in self._selected_names_from_list_view(self.primary_drop_view, self._primary_subset_proxy):
			value = self._shape_model.get_shape_value(shape_name)
			if value is None:
				continue
			self._linked_primary_start_values[shape_name] = value
		for shape_name in self._selected_names_from_list_view(self.work_shapes_view, self._work_shape_model):
			value = self._work_shape_model.get_value(shape_name)
			if value is None:
				continue
			self._linked_work_start_values[shape_name] = float(value)

	def _on_linked_drag_started(self) -> None:
		self._linked_drag_active = True
		self._linked_drag_ctrl_pressed = bool(QGuiApplication.keyboardModifiers() & Qt.ControlModifier)
		self._capture_linked_drag_state()

	def _on_linked_drag_selection_context(self, can_propagate: bool) -> None:
		self._linked_drag_can_propagate = bool(can_propagate)

	def _on_linked_drag_ended(self) -> None:
		self._linked_drag_active = False
		self._linked_primary_start_values = {}
		self._linked_work_start_values = {}
		self._linked_drag_can_propagate = False
		self._linked_drag_ctrl_pressed = False

	def _on_linked_drag_delta(self, delta_value: float) -> None:
		if not self._linked_drag_active:
			return
		if not self._linked_drag_can_propagate:
			return
		if not self._linked_drag_ctrl_pressed:
			return
		for shape_name, start_value in self._linked_primary_start_values.items():
			target_value = max(0.0, min(1.0, start_value + float(delta_value)))
			self._shape_model.set_shape_value_by_name(shape_name, target_value)
		for shape_name, start_value in self._linked_work_start_values.items():
			target_value = max(0.0, min(1.0, start_value + float(delta_value)))
			self._work_shape_model.set_value_by_name(shape_name, target_value)

	def _on_work_shape_value_committed(self, shape_name: str, value: float) -> None:
		if self._linked_drag_active:
			return
		self._set_status(f"Set work shape '{shape_name}' to {value:.3f}")

	def _refresh_primary_folder_sort_values(self) -> float:
		"""Update per-item numeric sort value (leaf=slider value, folder=max descendant)."""
		def visit(item: QTreeWidgetItem) -> float:
			shape_name = item.data(0, self.PRIMARY_TREE_NAME_ROLE)
			if shape_name:
				value = float(item.data(0, ShapeItemsModel.ValueRole) or 0.0)
				item.setData(0, PRIMARY_TREE_SORT_VALUE_ROLE, value)
				return value
			max_value = 0.0
			for i in range(item.childCount()):
				max_value = max(max_value, visit(item.child(i)))
			item.setData(0, PRIMARY_TREE_SORT_VALUE_ROLE, max_value)
			return max_value

		max_root = 0.0
		for i in range(self.primaries_view.topLevelItemCount()):
			max_root = max(max_root, visit(self.primaries_view.topLevelItem(i)))
		return max_root

	def _sort_primaries_tree(self) -> None:
		"""Sort primaries tree by current sort mode (name or value)."""
		self._refresh_primary_folder_sort_values()
		# Use ascending sort and let PrimaryTreeItem.__lt__ handle mode-specific ordering.
		self.primaries_view.sortItems(0, Qt.AscendingOrder)

		def sort_descendants(item: QTreeWidgetItem) -> None:
			item.sortChildren(0, Qt.AscendingOrder)
			for i in range(item.childCount()):
				sort_descendants(item.child(i))

		for i in range(self.primaries_view.topLevelItemCount()):
			sort_descendants(self.primaries_view.topLevelItem(i))

	def _set_status(self, message: str, *, warning: bool = False, error: bool = False) -> None:
		self.status_bar.showMessage(message)
		if error:
			if sys.exc_info()[0] is not None:
				traceback.print_exc()
			self.status_bar.setStyleSheet("color: #ff6b6b;")
		elif warning:
			self.status_bar.setStyleSheet("color: #e7b45a;")
		else:
			self.status_bar.setStyleSheet("")

	def _iter_primary_tree_leaves(self):
		"""Yield all primary leaf items in the primaries tree."""
		stack = [self.primaries_view.topLevelItem(i) for i in range(self.primaries_view.topLevelItemCount())]
		while stack:
			item = stack.pop()
			if item is None:
				continue
			if item.data(0, ShapeItemsModel.EditableRole):
				yield item
			for i in range(item.childCount()):
				stack.append(item.child(i))

	def _get_primary_tree_value(self, shape_name: str) -> Optional[float]:
		"""Get the current blendshape value for a primary shape."""
		if self.current_editor is None:
			return None
		try:
			weight = self.current_editor.blendshape.get_weight_by_name(shape_name)
			return float(self.current_editor.blendshape.get_weight_value(weight))
		except Exception:
			return None

	def _on_primary_tree_slider_changed(self, shape_name: str, value: float) -> None:
		"""Commit primary value changes coming from primaries tree sliders."""
		if self.current_editor is None:
			return
		shape = self.current_editor.get_shape(shape_name)
		if shape is None:
			return
		value = max(0.0, min(1.0, float(value)))
		try:
			self.current_editor.set_primary_shape_value(shape, value)
		except Exception as exc:
			self._set_status(f"Failed setting primary '{shape_name}': {exc}", error=True)
		# Keep row positions stable while dragging; re-sort on drag end.
		if self._primary_tree_sort_by_value and not self._primaries_drag_active:
			self._sort_primaries_tree()

	def _on_primaries_tree_data_changed(self, top_left: QModelIndex, bottom_right: QModelIndex, roles) -> None:
		if self._syncing_primaries_tree:
			return
		if self.current_editor is None:
			return
		if roles and ShapeItemsModel.ValueRole not in roles:
			return
		for row in range(top_left.row(), bottom_right.row() + 1):
			index = top_left.sibling(row, 0)
			if not index.isValid() or bool(index.data(ShapeItemsModel.IsHeaderRole)):
				continue
			if not bool(index.data(ShapeItemsModel.EditableRole)):
				continue
			shape_name = str(index.data(ShapeItemsModel.NameRole) or "")
			if not shape_name:
				continue
			value = max(0.0, min(1.0, float(index.data(ShapeItemsModel.ValueRole) or 0.0)))
			item = self.primaries_view.itemFromIndex(index)
			if item is not None:
				self._syncing_primaries_tree = True
				try:
					item.setData(0, PRIMARY_TREE_SORT_VALUE_ROLE, value)
				finally:
					self._syncing_primaries_tree = False
			self._on_primary_tree_slider_changed(shape_name, value)

	def _sync_primary_tree_slider(self, shape_name: str, value: float) -> None:
		"""Sync one primaries tree leaf value from tracker/model updates."""
		item = self._primary_tree_items.get(shape_name)
		if item is None:
			return
		target = max(0.0, min(1.0, float(value)))
		current = float(item.data(0, ShapeItemsModel.ValueRole) or 0.0)
		if abs(current - target) <= 1e-6:
			return
		self._syncing_primaries_tree = True
		try:
			item.setData(0, ShapeItemsModel.ValueRole, target)
			item.setData(0, PRIMARY_TREE_SORT_VALUE_ROLE, target)
			model = self.primaries_view.model()
			if model is not None:
				idx = self.primaries_view.indexFromItem(item, 0)
				if idx.isValid():
					model.dataChanged.emit(idx, idx, [ShapeItemsModel.ValueRole, Qt.DisplayRole])
		finally:
			self._syncing_primaries_tree = False

	def _rebuild_primaries_tree(self) -> None:
		"""Build primaries hierarchy from target directories, skipping shape envelope folders."""
		selected_names = {item.data(0, self.PRIMARY_TREE_NAME_ROLE) for item in self.primaries_view.selectedItems()}
		selected_names.discard(None)
		self._syncing_primaries_tree = True
		try:
			self.primaries_view.clear()
			self._primary_tree_items.clear()

			if self.current_editor is None:
				return

			primary_shapes = self.current_editor.get_primary_shapes().sort_for_display()
			primaries_target_dirs = self.current_editor.get_primaries_target_dirs() or {}
			dirs_by_name = {str(name): list(path or []) for name, path in primaries_target_dirs.items()}
			custom_colors = self.current_editor.read_custom_shapes_colors() or {}

			# Build stable grouped data: path is stored leaf->root from API, so reverse to root->leaf.
			grouped = {}
			for shape in primary_shapes:
				shape_name = str(shape)
				tokens = list(reversed(dirs_by_name.get(shape_name, [])))
				tokens = [token for token in tokens if token != shape_name]
				grouped.setdefault(tuple(tokens), []).append(shape_name)

			nodes_by_path = {}
			for dir_path in sorted(grouped.keys(), key=lambda path: (len(path), path)):
				parent_item = None
				for depth in range(len(dir_path)):
					partial_path = dir_path[: depth + 1]
					node = nodes_by_path.get(partial_path)
					if node is None:
						node = PrimaryTreeItem([dir_path[depth]])
						node.setData(0, self.PRIMARY_TREE_FOLDER_ROLE, True)
						node.setData(0, ShapeItemsModel.NameRole, dir_path[depth])
						node.setData(0, ShapeItemsModel.TypeRole, "PrimaryFolder")
						node.setData(0, ShapeItemsModel.ValueRole, 0.0)
						node.setData(0, ShapeItemsModel.EditableRole, False)
						node.setData(0, ShapeItemsModel.IsHeaderRole, True)
						node.setData(0, ShapeItemsModel.MutedRole, False)
						node.setData(0, ShapeItemsModel.LockedRole, False)
						node.setData(0, ShapeItemsModel.LockIconVisibleRole, False)
						node.setData(0, ShapeItemsModel.PrimariesRole, tuple())
						node.setData(0, PRIMARY_TREE_SORT_VALUE_ROLE, 0.0)
						folder_font = node.font(0)
						folder_font.setBold(True)
						node.setFont(0, folder_font)
						node.setFlags(Qt.ItemIsEnabled)
						if parent_item is None:
							self.primaries_view.addTopLevelItem(node)
						else:
							parent_item.addChild(node)
						nodes_by_path[partial_path] = node
					parent_item = node

				for shape_name in sorted(grouped[dir_path], key=str.lower):
					leaf = PrimaryTreeItem([shape_name])
					leaf.setData(0, self.PRIMARY_TREE_NAME_ROLE, shape_name)
					value = self._get_primary_tree_value(shape_name)
					leaf_value = 0.0 if value is None else float(value)
					leaf.setData(0, ShapeItemsModel.NameRole, shape_name)
					leaf.setData(0, ShapeItemsModel.TypeRole, "PrimaryShape")
					leaf.setData(0, ShapeItemsModel.ValueRole, leaf_value)
					leaf.setData(0, ShapeItemsModel.EditableRole, True)
					leaf.setData(0, ShapeItemsModel.IsHeaderRole, False)
					leaf.setData(0, ShapeItemsModel.MutedRole, False)
					leaf.setData(0, ShapeItemsModel.LockedRole, False)
					leaf.setData(0, ShapeItemsModel.LockIconVisibleRole, False)
					leaf.setData(0, ShapeItemsModel.PrimariesRole, (shape_name,))
					leaf.setData(0, PRIMARY_TREE_SORT_VALUE_ROLE, leaf_value)
					custom_color = custom_colors.get(shape_name)
					leaf.setData(0, ShapeItemsModel.ColorRole, _shape_custom_color_to_qcolor(custom_color))
					leaf.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsEditable | Qt.ItemIsDragEnabled)
					if parent_item is None:
						self.primaries_view.addTopLevelItem(leaf)
					else:
						parent_item.addChild(leaf)
					self._primary_tree_items[shape_name] = leaf
					if shape_name in selected_names:
						leaf.setSelected(True)

			self.primaries_view.expandAll()
			for i in range(self.primaries_view.topLevelItemCount()):
				stack = [self.primaries_view.topLevelItem(i)]
				while stack:
					item = stack.pop()
					self._update_primary_tree_folder_icon(item)
					for j in range(item.childCount()):
						stack.append(item.child(j))
			self._sort_primaries_tree()
		finally:
			self._syncing_primaries_tree = False

	def _apply_primaries_tree_filter(self, terms) -> None:
		"""Filter primaries tree while preserving parent groups for matching children."""
		search_terms = _normalized_search_terms(terms)

		def visit(item: QTreeWidgetItem) -> bool:
			item_text = item.text(0).lower()
			own_match = not search_terms or any(term in item_text for term in search_terms)
			child_match = False
			for i in range(item.childCount()):
				if visit(item.child(i)):
					child_match = True
			visible = own_match or child_match
			item.setHidden(not visible)
			return visible

		for i in range(self.primaries_view.topLevelItemCount()):
			visit(self.primaries_view.topLevelItem(i))

	def _setup_scene_editor_tracker(self) -> None:
		self._clear_scene_editor_tracker()
		self.scene_editor_tracker = BlueSteelEditorsTracker()
		self.scene_editor_tracker.sceneReset.connect(self._on_scene_reset)
		self.scene_editor_tracker.sceneOpened.connect(self._on_scene_opened)
		self.scene_editor_tracker.editorAdded.connect(self._on_editor_added)
		self.scene_editor_tracker.editorRemoved.connect(self._on_editor_removed)
		self.scene_editor_tracker.editorRenamed.connect(self._on_editor_renamed)
		self.scene_editor_tracker.frameChanged.connect(self._on_scene_frame_changed, Qt.QueuedConnection)

	@staticmethod
	def _dispose_tracker(tracker) -> None:
		if tracker is None:
			return
		try:
			tracker.kill()
		except RuntimeError:
			return
		try:
			tracker.deleteLater()
		except RuntimeError:
			pass

	def _clear_scene_editor_tracker(self) -> None:
		tracker = self.scene_editor_tracker
		self.scene_editor_tracker = None
		self._dispose_tracker(tracker)

	def _setup_blendshape_tracker(self) -> None:
		self._clear_blendshape_tracker()
		if self.current_editor is None:
			return
		self.blendshape_tracker = BlendShapeNodeTracker(self.current_editor.blendshape.name)
		self.blendshape_tracker.shapeValueChanged.connect(self._on_shape_value_changed, Qt.QueuedConnection)
		self.blendshape_tracker.shapeAdded.connect(self._on_shape_structure_changed)
		self.blendshape_tracker.shapeRemoved.connect(self._on_shape_structure_changed)
		self.blendshape_tracker.shapeRenamed.connect(self._on_shape_renamed)
		self.blendshape_tracker.nodeDeleted.connect(self._on_blendshape_deleted)
		self.blendshape_tracker.start()

		if self.current_editor.work_blendshape is not None:
			self.work_blendshape_tracker = BlendShapeNodeTracker(self.current_editor.work_blendshape.name)
			self.work_blendshape_tracker.shapeValueChanged.connect(self._on_work_shape_value_changed, Qt.QueuedConnection)
			self.work_blendshape_tracker.shapeAdded.connect(self._on_work_shape_structure_changed)
			self.work_blendshape_tracker.shapeRemoved.connect(self._on_work_shape_structure_changed)
			self.work_blendshape_tracker.shapeRenamed.connect(self._on_work_shape_structure_changed)
			self.work_blendshape_tracker.shapeInputConnected.connect(self._on_work_blendshape_driver_connection_changed)
			self.work_blendshape_tracker.sculptTargetChanged.connect(self._on_work_sculpt_target_changed, Qt.QueuedConnection)
			self.work_blendshape_tracker.nodeDeleted.connect(self._on_work_blendshape_deleted)
			self.work_blendshape_tracker.target_connection_changed.connect(self._on_work_blendshape_target_connection_changed)
			self.work_blendshape_tracker.start()
		else:
			print("No work blendshape found for current editor, skipping work tracker setup.")
		self._setup_split_map_edit_blendshape_tracker()

	def _setup_split_map_edit_blendshape_tracker(self) -> None:
		node_name = None
		if self.current_editor is not None:
			node_name = self.current_editor.split_map_edit_blendshape
		if not node_name or not cmds.objExists(node_name):
			self._clear_split_map_edit_blendshape_tracker()
			return
		if (
			self.split_map_edit_blendshape_tracker is not None
			and self.split_map_edit_blendshape_tracker.node_name == node_name
		):
			self.split_map_edit_blendshape_tracker.start()
			return

		self._clear_split_map_edit_blendshape_tracker()
		tracker = BlendShapeNodeTracker(node_name)
		tracker.shapeValueChanged.connect(self._on_split_map_edit_weight_value_changed, Qt.QueuedConnection)
		tracker.shapeAdded.connect(self._on_split_map_edit_structure_changed)
		tracker.shapeRemoved.connect(self._on_split_map_edit_structure_changed)
		tracker.shapeRenamed.connect(self._on_split_map_edit_structure_changed)
		tracker.nodeDeleted.connect(self._on_split_map_edit_blendshape_deleted)
		tracker.start()
		self.split_map_edit_blendshape_tracker = tracker

	def _clear_split_map_edit_blendshape_tracker(self) -> None:
		tracker = self.split_map_edit_blendshape_tracker
		self.split_map_edit_blendshape_tracker = None
		self._dispose_tracker(tracker)

	def _clear_blendshape_tracker(self) -> None:
		self._clear_split_map_edit_blendshape_tracker()
		blendshape_tracker = self.blendshape_tracker
		self.blendshape_tracker = None
		self._dispose_tracker(blendshape_tracker)
		work_blendshape_tracker = self.work_blendshape_tracker
		self.work_blendshape_tracker = None
		self._dispose_tracker(work_blendshape_tracker)

	def _setup_split_attr_grp_tracker(self) -> None:
		self._clear_split_attr_grp_tracker()
		if self.current_editor is None or not cmds.objExists(self.current_editor.split_attr_grp):
			return
		self.split_attr_grp_tracker = ControllerTracker(self.current_editor.split_attr_grp)
		self.split_attr_grp_tracker.attributeChanged.connect(self._schedule_split_attr_grp_value_refresh)
		self.split_attr_grp_tracker.attributeAdded.connect(self._schedule_split_attr_grp_full_refresh)
		self.split_attr_grp_tracker.attributeRemoved.connect(self._schedule_split_attr_grp_full_refresh)
		self.split_attr_grp_tracker.nodeDeleted.connect(self._on_split_attr_grp_deleted)
		self.split_attr_grp_tracker.start()

	def _clear_split_attr_grp_tracker(self) -> None:
		self._split_attr_refresh_pending = False
		self._split_attr_full_refresh_pending = False
		tracker = self.split_attr_grp_tracker
		self.split_attr_grp_tracker = None
		self._dispose_tracker(tracker)

	def _schedule_split_attr_grp_value_refresh(self, attribute_name: str, _value) -> None:
		"""Refresh only assignment values when a primary enum value changes."""
		if self.current_editor is None:
			return
		try:
			attribute_type = cmds.getAttr(f"{self.current_editor.split_attr_grp}.{attribute_name}", type=True)
		except Exception:
			attribute_type = None
		self._schedule_split_attr_grp_refresh(full=attribute_type != "enum")

	def _schedule_split_attr_grp_full_refresh(self, *_args) -> None:
		self._schedule_split_attr_grp_refresh(full=True)

	def _schedule_split_attr_grp_refresh(self, *, full: bool) -> None:
		if not self._is_split_tab_active():
			self._split_settings_refresh_pending = True
			return
		self._split_attr_full_refresh_pending |= full
		if self._split_attr_refresh_pending:
			return
		self._split_attr_refresh_pending = True
		QTimer.singleShot(60, self._reload_split_settings_from_tracker)

	def _reload_split_settings_from_tracker(self) -> None:
		full_refresh = self._split_attr_full_refresh_pending
		self._split_attr_refresh_pending = False
		self._split_attr_full_refresh_pending = False
		if self.current_editor is not None:
			if full_refresh:
				self._reload_split_settings_from_editor()
			else:
				self._refresh_split_primary_assignments()

	def _on_split_attr_grp_deleted(self, _node_name: str) -> None:
		self._clear_split_attr_grp_tracker()
		self._reload_split_settings_from_editor()

	def _reload_editor_menu(self) -> None:
		current_name = self.current_editor.name if self.current_editor else self.EMPTY_SYSTEM_LABEL
		names = []
		if isinstance(self.scene_editor_tracker, BlueSteelEditorsTracker):
			names = sorted(self.scene_editor_tracker.get_editor_names())

		self.editor_combo.blockSignals(True)
		self.editor_combo.clear()
		self.editor_combo.addItem(self.EMPTY_SYSTEM_LABEL)
		for name in names:
			self.editor_combo.addItem(name)

		idx = self.editor_combo.findText(current_name)
		self.editor_combo.setCurrentIndex(max(0, idx))
		self.editor_combo.blockSignals(False)

	def _select_first_available_editor(self) -> None:
		if self.editor_combo.count() > 1:
			self.editor_combo.setCurrentIndex(1)
		else:
			self.set_current_editor(None)

	def _on_editor_selected(self, name: str) -> None:
		if not name or name == self.EMPTY_SYSTEM_LABEL:
			self.set_current_editor(None)
			return
		self.set_current_editor(name)

	def _on_primaries_selection_changed(self, *_args) -> None:
		self._set_shapes_value_filter_button_state(False)
		selected_names = []
		for item in self.primaries_view.selectedItems():
			shape_name = item.data(0, self.PRIMARY_TREE_NAME_ROLE)
			if shape_name:
				selected_names.append(str(shape_name))
		# Changing primary selection should remove active and directional filters.
		self._active_shapes_proxy.set_visible_names(None)
		self._set_active_shapes_filter_state(False)
		self._set_directional_shapes_filter_state(downstream_checked=False, upstream_checked=False)
		self._apply_primary_selection_shapes_filter(selected_names)
		self._rebuild_shapes_tree()
		self._update_delegate_name_columns()
		self._update_info_labels()

	def _on_exclusive_filter_toggled(self, checked: bool) -> None:
		self._exclusive_primary_filter = bool(checked)
		method_name = "Exclusive" if checked else "Standard"
		self.primary_filter_button.setText(f"Filtering: {method_name}")
		self._on_primaries_selection_changed()

	def _apply_primary_selection_shapes_filter(self, selected_names: Sequence[str]) -> None:
		selected_names = list(dict.fromkeys(str(name) for name in selected_names if name))
		if not selected_names or not getattr(self, "_exclusive_primary_filter", False):
			self._shapes_proxy.set_visible_names(None)
			self._shapes_proxy.set_selected_primaries(selected_names)
			return

		self._shapes_proxy.set_selected_primaries(tuple())
		if self.current_editor is None:
			self._shapes_proxy.set_visible_names(tuple())
			return
		try:
			related_shapes = self.current_editor.get_related_shapes(selected_names) or []
		except Exception as exc:
			self._shapes_proxy.set_visible_names(tuple())
			self._set_status(f"Error filtering strict relationships: {exc}", error=True)
			return
		self._shapes_proxy.set_visible_names(tuple(str(shape) for shape in related_shapes))

	def _on_primary_value_committed(self, shape_name: str, value: float) -> None:
		self._set_status(f"Set '{shape_name}' to {value:.3f}")
		self._resort_value_sorted_lists_if_needed()

	def _on_shape_value_changed(self, shape_id: int, shape_name: str, value: float) -> None:
		del shape_id
		self._shape_model.set_shape_value_from_tracker(shape_name, value)
		self._sync_primary_tree_slider(shape_name, value)
		self._resort_value_sorted_lists_if_needed()

	def _on_shape_structure_changed(self, *_args) -> None:
		self._clear_related_shapes_cache()
		if self.current_editor is not None:
			self.current_editor.blendshape.invalidate_weights_cache()
		self._reload_shapes_from_editor()

	def _on_work_shape_value_changed(self, shape_id: int, shape_name: str, value: float) -> None:
		del shape_id
		self._work_shape_model.set_value_local(shape_name, value)

	def _on_split_map_edit_weight_value_changed(self, _shape_id: int, _shape_name: str, _value: float) -> None:
		if self._is_split_tab_active():
			self._sync_split_map_weight_slider_values()

	def _on_split_map_edit_structure_changed(self, *_args) -> None:
		if self._is_split_tab_active():
			self._refresh_split_map_weights()
		else:
			self._split_settings_refresh_pending = True

	def _on_work_shape_structure_changed(self, *_args) -> None:
		print("Work shape structure changed, reloading work shapes from editor...")
		if self.current_editor is not None and self.current_editor.work_blendshape is not None:
			self.current_editor.work_blendshape.invalidate_weights_cache()
		self._reload_work_shapes_from_editor()

	def _on_work_sculpt_target_changed(self, target_id: int, _shape_name: str) -> None:
		if self.current_editor is None or self.current_editor.work_blendshape is None:
			self._work_shape_model.set_edit_shape(None)
			self._update_work_shape_button_panel()
			return
		if target_id < 0:
			self._work_shape_model.set_edit_shape(None)
			self._update_work_shape_button_panel()
			return
		weight = self.current_editor.work_blendshape.get_weight_by_id(target_id)
		self._work_shape_model.set_edit_shape(str(weight) if weight is not None else None)
		self._update_work_shape_button_panel()

	def _on_shapes_mute_toggle_requested(self, shape_name: str, state: bool) -> None:
		"""Handle delegate mute icon clicks without rebuilding full UI state."""
		if self.current_editor is None:
			return

		selected_shape_names = self._selected_shape_names_from_shapes_view()
		self._apply_shape_mute_toggle(shape_name, state, selected_shape_names)

	def _on_active_shapes_mute_toggle_requested(self, shape_name: str, state: bool) -> None:
		"""Handle active-shapes delegate mute icon clicks with list-selection semantics."""
		if self.current_editor is None:
			return

		selected_shape_names = self._selected_active_shape_names()
		self._apply_shape_mute_toggle(shape_name, state, selected_shape_names)

	def _on_primary_drop_mute_toggle_requested(self, shape_name: str, state: bool) -> None:
		"""Handle primary-drive delegate mute icon clicks with list-selection semantics."""
		if self.current_editor is None:
			return

		selected_shape_names = self._selected_primary_drop_shape_names()
		self._apply_shape_mute_toggle(shape_name, state, selected_shape_names)

	def _apply_shape_mute_toggle(self, shape_name: str, state: bool, selected_shape_names: List[str]) -> None:
		"""Apply shape mute state for one or many names and refresh in-model muted flags."""
		if shape_name in selected_shape_names:
			target_shape_names = list(dict.fromkeys(selected_shape_names))
		else:
			target_shape_names = [shape_name]

		try:
			if self.blendshape_tracker is not None:
				self.blendshape_tracker.stop()
			for target_name in target_shape_names:
				self.current_editor.set_shape_mute_state(target_name, bool(state))
				self._shape_model.set_shape_muted_state_local(target_name, bool(state))
			if len(target_shape_names) == 1:
				self._set_status(f"{'Muted' if state else 'Unmuted'} shape '{target_shape_names[0]}'.")
			else:
				self._set_status(f"{'Muted' if state else 'Unmuted'} {len(target_shape_names)} selected shape(s).")
		except Exception as exc:
			self._set_status(f"Error toggling mute state: {exc}", error=True)
		finally:
			if self.blendshape_tracker is not None:
				self.blendshape_tracker.start()

	def _on_shapes_lock_toggle_requested(self, shape_name: str, state: bool) -> None:
		"""Handle delegate lock icon clicks without rebuilding full UI state."""
		print(f"Lock toggle requested for shape '{shape_name}' with state {state}.")
		if self.current_editor is None:
			return

		selected_shape_names = self._selected_shape_names_from_shapes_view()
		self._apply_shape_lock_toggle(shape_name, state, selected_shape_names)

	def _on_active_shapes_lock_toggle_requested(self, shape_name: str, state: bool) -> None:
		"""Handle active-shapes delegate lock icon clicks with list-selection semantics."""
		if self.current_editor is None:
			return

		selected_shape_names = self._selected_active_shape_names()
		self._apply_shape_lock_toggle(shape_name, state, selected_shape_names)

	def _on_primary_drop_lock_toggle_requested(self, shape_name: str, state: bool) -> None:
		"""Handle primary-drop delegate lock icon clicks with list-selection semantics."""
		if self.current_editor is None:
			return

		selected_shape_names = self._selected_primary_drop_shape_names()
		self._apply_shape_lock_toggle(shape_name, state, selected_shape_names)
		
	def _apply_shape_lock_toggle(self, shape_name: str, state: bool, selected_shape_names: List[str]) -> None:
		"""Apply shape lock state for one or many names and refresh in-model lock flags."""
		if shape_name in selected_shape_names:
			target_shape_names = list(dict.fromkeys(selected_shape_names))
		else:
			target_shape_names = [shape_name]

		if getattr(self.current_editor, "locked_shapes", None) is None:
			self.current_editor.locked_shapes = set()

		updated_target_names: List[str] = []
		for target_name in target_shape_names:
			target_shape = self.current_editor.get_shape(target_name)
			if target_shape is not None and getattr(target_shape, "type", "") == "PrimaryShape":
				continue
			if state:
				self.current_editor.add_shape_to_locked_shapes(target_name)
			else:
				self.current_editor.remove_shape_from_locked_shapes(target_name)
			self._shape_model.set_shape_locked_state_local(target_name, bool(state))
			updated_target_names.append(target_name)

		if not updated_target_names:
			return
		if len(updated_target_names) == 1:
			self._set_status(f"{'Locked' if state else 'Unlocked'} shape '{updated_target_names[0]}'.")
		else:
			self._set_status(f"{'Locked' if state else 'Unlocked'} {len(updated_target_names)} selected shape(s).")

	def _on_work_shapes_mute_toggle_requested(self, shape_name: str, state: bool) -> None:
		"""Handle work-shape delegate mute icon clicks with shapes-panel semantics."""
		if self.current_editor is None:
			return

		selected_shape_names = self._selected_work_shape_names()
		if shape_name in selected_shape_names:
			target_shape_names = list(dict.fromkeys(selected_shape_names))
		else:
			target_shape_names = [shape_name]

		try:
			if self.work_blendshape_tracker is not None:
				self.work_blendshape_tracker.stop()
			for target_name in target_shape_names:
				self.current_editor.set_work_shape_mute_state(target_name, bool(state))
				self._work_shape_model.set_muted_state_local(target_name, bool(state))
			if len(target_shape_names) == 1:
				self._set_status(f"{'Muted' if state else 'Unmuted'} work shape '{target_shape_names[0]}'.")
			else:
				self._set_status(f"{'Muted' if state else 'Unmuted'} {len(target_shape_names)} selected work shape(s).")
		except Exception as exc:
			self._set_status(f"Error toggling work-shape mute state: {exc}", error=True)
		finally:
			if self.work_blendshape_tracker is not None:
				self.work_blendshape_tracker.start()

	def _on_work_blendshape_target_connection_changed(self, _target_id: int, connected: bool) -> None:
		if self.current_editor is None or self.current_editor.work_blendshape is None:
			return
		work_weight = self.current_editor.work_blendshape.get_weight_by_id(_target_id)
		if work_weight is None:
			return
		work_shape_name = str(work_weight)
		self._work_shape_model.set_connected_state_local(work_shape_name, bool(connected))
		if connected and self._work_shape_model.edit_shape_name() == work_shape_name:
			try:
				cmds.sculptTarget(self.current_editor.work_blendshape.name, e=True, t=-1)
			except Exception:
				pass
			self._work_shape_model.set_edit_shape(None)
		self._update_work_shape_button_panel()

	def _on_work_blendshape_driver_connection_changed(self, target_id: int, connected: bool) -> None:
		if self.current_editor is None or self.current_editor.work_blendshape is None:
			return
		work_weight = self.current_editor.work_blendshape.get_weight_by_id(target_id)
		if work_weight is None:
			return
		self._work_shape_model.set_driver_connected_state_local(str(work_weight), bool(connected))
		

	def _on_shape_renamed(self, *_args) -> None:
		self._clear_related_shapes_cache()
		if self.current_editor is not None:
			self.current_editor.blendshape.invalidate_weights_cache()
		self._reload_shapes_from_editor()

	def _on_blendshape_deleted(self, blendshape_name: str) -> None:
		self.set_current_editor(None)
		self._set_status(f"Blendshape '{blendshape_name}' deleted.", warning=True)

	def _on_work_blendshape_deleted(self, blendshape_name: str) -> None:
		self.set_current_editor(None)
		self._set_status(f"Work blendshape '{blendshape_name}' deleted.", warning=True)

	def _on_split_map_edit_blendshape_deleted(self, blendshape_name: str) -> None:
		self._clear_split_map_edit_blendshape_tracker()
		self._refresh_split_map_weights()
		self._set_status(f"Split-map edit blendshape '{blendshape_name}' deleted.", warning=True)

	def _on_scene_reset(self) -> None:
		def deferred():
			self.set_current_editor(None)
			self._reload_editor_menu()
			self._set_status("Scene reset.")

		cmds.evalDeferred(deferred)

	def _on_scene_opened(self) -> None:
		def deferred():
			self._reload_editor_menu()
			self._select_first_available_editor()
			self._set_status("Scene opened.")

		cmds.evalDeferred(deferred)

	def _on_editor_added(self, _name: str) -> None:
		self._reload_editor_menu()

	def _on_editor_removed(self, name: str) -> None:
		if self.current_editor and self.current_editor.name == name:
			self.set_current_editor(None)
		self._reload_editor_menu()

	def _on_editor_renamed(self, new_name: str, old_name: str) -> None:
		if self.current_editor and self.current_editor.name == old_name:
			self.set_current_editor(new_name)
		else:
			self._reload_editor_menu()

	def _on_scene_frame_changed(self, _frame: float) -> None:
		"""Keep slider UIs in sync while keyed values change over time."""
		if self.current_editor is None or not self.isVisible():
			return
		if self._primaries_drag_active or self._linked_drag_active:
			return

		changed_rows = self._shape_model.refresh_values_from_editor()
		for changed_name, changed_value, is_primary in changed_rows:
			if is_primary:
				self._sync_primary_tree_slider(changed_name, changed_value)
		self._work_shape_model.refresh_values_from_editor()
		self._resort_value_sorted_lists_if_needed()

	def _reload_shapes_from_editor(self) -> None:
		self._clear_related_shapes_cache()
		if self.current_editor is None:
			self._shape_model.rebuild_from_editor(None)
			self._work_shape_model.rebuild_from_editor(None)
			self._primary_subset_proxy.clear_selected_names()
			self._rebuild_primaries_tree()
			self._rebuild_shapes_tree()
			self._reload_split_settings_from_editor()
			self._update_delegate_name_columns()
			self._update_info_labels()
			self._update_work_shape_button_panel()
			return
		try:
			self.current_editor.sync_network()
			self._shape_model.rebuild_from_editor(self.current_editor)
			self._work_shape_model.rebuild_from_editor(self.current_editor)
			self._primary_subset_proxy.sort(0, Qt.AscendingOrder)
			self._rebuild_primaries_tree()
			self._rebuild_shapes_tree()
			self._reload_split_settings_from_editor()
			self._update_delegate_name_columns()
			self._update_info_labels()
			self._update_work_shape_button_panel()
		except Exception as exc:
			self._set_status(f"Failed to reload shapes: {exc}", error=True)

	def _update_info_labels(self) -> None:
		total_primaries = sum(1 for _ in self._iter_primary_tree_leaves())
		selected_primaries = sum(
			1
			for item in self.primaries_view.selectedItems()
			if item.data(0, self.PRIMARY_TREE_NAME_ROLE)
		)
		self.primaries_info.setText(f"Items: {selected_primaries}/{total_primaries}")
		selected_shapes = sum(
			1
			for item in self.shapes_view.selectedItems()
			if not bool(item.data(0, ShapeItemsModel.IsHeaderRole))
		)
		total_shapes = len(self._shape_tree_items)
		self.shapes_info.setText(f"Items: {selected_shapes}/{total_shapes}")
		total_active_shapes = sum(
			1
			for row in range(self._active_shapes_proxy.rowCount())
			if not bool(self._active_shapes_proxy.data(self._active_shapes_proxy.index(row, 0), ShapeItemsModel.IsHeaderRole))
		)
		selected_active_shapes = sum(
			1
			for index in self.active_shapes_view.selectedIndexes()
			if not bool(self._active_shapes_proxy.data(index, ShapeItemsModel.IsHeaderRole))
		)
		self.active_shapes_info.setText(f"Items: {selected_active_shapes}/{total_active_shapes}")

	def _update_window_title(self) -> None:
		editor_name = self.current_editor.name if self.current_editor is not None else ""
		title = f"Blue Steel v.{self.version}"
		if editor_name:
			title = f"{title} - {editor_name}"
		self.setWindowTitle(title)

	def set_current_editor(self, name: Optional[str]) -> None:
		"""Set active editor by name.

		Example:
			>>> win.set_current_editor("myCharacter_blueSteel_container")
		"""
		self._clear_blendshape_tracker()
		self._clear_split_attr_grp_tracker()
		self._split_map_normalization_cache.clear()

		if not name or not cmds.objExists(name):
			if self.heat_map_switch is not None:
				self.heat_map_switch.blockSignals(True)
				self.heat_map_switch.setChecked(False)
				self.heat_map_switch.blockSignals(False)
			self.current_editor = None
			self._update_window_title()
			self._shape_model.rebuild_from_editor(None)
			self._rebuild_primaries_tree()
			self._rebuild_shapes_tree()
			self._reload_split_settings_from_editor()
			self._update_delegate_name_columns()
			self._update_tools_button_panel()
			self._reload_editor_menu()
			if self._controller_layout_window is not None:
				self._controller_layout_window.set_current_editor(None)
			self._set_status("No system selected.", warning=True)
			return

		try:
			self.current_editor = BlueSteelEditor(name)
			if self.heat_map_switch is not None:
				self.heat_map_switch.setEnabled(bool(env.DGA_NODES_SUPPORTED))
				if env.DGA_NODES_SUPPORTED:
					if self.current_editor.heat_map_display_state:
						# we need to block signals here to prevent unwanted toggles since set_current_editor can be called during editor initialization when the heat map state is already active
						self.heat_map_switch.blockSignals(True)
						self.heat_map_switch.setChecked(True)
						self.heat_map_switch.blockSignals(False)
				if self._is_heat_map_switch_active():
					try:
						self.current_editor.display_heat_maps(True)
					except Exception:
						pass
			self._update_window_title()
			self._reload_shapes_from_editor()
			self._setup_blendshape_tracker()
			self._setup_split_attr_grp_tracker()
			self._update_tools_button_panel()
			self._reload_editor_menu()
			if self._controller_layout_window is not None:
				self._controller_layout_window.set_current_editor(self.current_editor)
			self._set_status(f"Loaded system: {name}")
		except Exception as exc:
			self.current_editor = None
			self._update_window_title()
			self._shape_model.rebuild_from_editor(None)
			self._rebuild_primaries_tree()
			self._rebuild_shapes_tree()
			self._reload_split_settings_from_editor()
			self._update_delegate_name_columns()
			self._update_tools_button_panel()
			self._reload_editor_menu()
			if self._controller_layout_window is not None:
				self._controller_layout_window.set_current_editor(None)
			self._set_status(f"Failed loading system '{name}': {exc}", error=True)

	def refresh_ui(self) -> None:
		"""Refresh model and editor list while preserving current selection when possible."""
		self._clear_shapes_filters(rebuild_ui=False)
		selected_name = self.current_editor.name if self.current_editor else None
		self._reload_editor_menu()
		if selected_name and cmds.objExists(selected_name):
			self.set_current_editor(selected_name)
		else:
			self.set_current_editor(None)
		self._set_status("Refreshed UI.")

	def show_about(self) -> None:
		QMessageBox.about(
            self, "About",
            "Blues Steel\n\n"
            "A really, really, ridiculously good-looking\n blendshape manager for Maya\n by Maurizio Memoli\n\n"
            f"Version: {self.version}\n"
		)

	def closeEvent(self, event) -> None:  # noqa: N802
		if self.current_editor is not None:
			self.current_editor.toggle_hud_display(False)
		if self._controller_layout_window is not None:
			self._controller_layout_window.close()
			self._controller_layout_window.deleteLater()
			self._controller_layout_window = None
		self._clear_blendshape_tracker()
		self._clear_split_attr_grp_tracker()
		self._clear_scene_editor_tracker()
		super().closeEvent(event)


def show() -> MainWindow:
	"""Show the rewritten Blue Steel editor window.

	Example:
		>>> win = show()
		>>> win.refresh_ui()
	"""
	print("Opening Blue Steel editor...")
	global WINDOW
	global SHOW_UPDATE_CHECK

	try:
		if WINDOW is not None:
			WINDOW.close()
			WINDOW.deleteLater()
			WINDOW = None
	except Exception:
		WINDOW = None
	if cmds.workspaceControl(MainWindow.WORKSPACE_CONTROL_NAME, query=True, exists=True):
		cmds.deleteUI(MainWindow.WORKSPACE_CONTROL_NAME, control=True)

	maya_main_window = get_maya_main_window()
	import blue_steel
	status_label = None
	if blue_steel.__version__  < blue_steel.__latest_version__:
		url = blue_steel.__update_url__
		status_label = QLabel(
			f'Update available: v.{blue_steel.__latest_version__} Download '
			f'<a href="{url}" style="color: #e7b45a;"><strong>Here</strong></a>'
		)
		status_label.setStyleSheet("color: #e7b45a;")
		status_label.setOpenExternalLinks(True)
	WINDOW = MainWindow(parent=maya_main_window, version=blue_steel.__version__)
	WINDOW.resize(1200, max(720, WINDOW.sizeHint().height()))
	WINDOW.show(dockable=True, area="right", floating=False)
	WINDOW._dock_to_maya_panel()
	if status_label is not None:
		WINDOW.status_bar.addPermanentWidget(status_label)

	return WINDOW

