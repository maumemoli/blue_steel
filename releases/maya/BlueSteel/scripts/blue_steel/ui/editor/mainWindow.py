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

from ... import env
from ...api.editor import BlueSteelEditor
from ...api.trackers import BlueSteelEditorsTracker, BlendShapeNodeTracker
from ...converters.simplex.ui.dialog import show_simplex_converter_dialog
from ...converters.simplex import commands as simplex_commands
from ..common import frameLayout
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
	LOCK_ON_ICON,
	LOCK_OFF_ICON,

)
from .. import mmtools

WINDOW = None

if env.MAYA_VERSION > 2024:
	from PySide6.QtCore import QAbstractListModel, QModelIndex, QSortFilterProxyModel, Qt, QSize, Signal, QEvent, QRect, QPersistentModelIndex, QTimer, QItemSelectionModel, QMimeData
	from PySide6.QtGui import QAction, QColor, QDoubleValidator, QIcon, QPainter, QDrag, QGuiApplication
	from PySide6.QtWidgets import (
		QAbstractItemView,
		QMenu,
		QFileDialog,
		QGroupBox,
		QHBoxLayout,
		QInputDialog,
		QLabel,
		QLayout,
		QLineEdit,
		QListView,
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
	)
	from shiboken6 import wrapInstance
else:
	from PySide2.QtCore import QAbstractListModel, QModelIndex, QSortFilterProxyModel, Qt, QSize, Signal, QEvent, QRect, QPersistentModelIndex, QTimer, QItemSelectionModel, QMimeData
	from PySide2.QtGui import QColor, QDoubleValidator, QIcon, QPainter, QDrag, QGuiApplication
	from PySide2.QtWidgets import (
		QAction,
		QAbstractItemView,
		QMenu,
		QFileDialog,
		QGroupBox,
		QHBoxLayout,
		QInputDialog,
		QLabel,
		QLayout,
		QLineEdit,
		QListView,
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
			model_index = self.index(row_index, 0)
			self.dataChanged.emit(model_index, model_index, [self.ValueRole, Qt.DisplayRole])
			changed.append((str(row.get("name", "")), clamped_value, bool(row.get("editable", False))))

		return changed


class PrimaryShapesProxyModel(QSortFilterProxyModel):
	"""Proxy model for primary-only listing with text filtering."""

	def __init__(self, parent: Optional[QWidget] = None):
		super().__init__(parent)
		self._search_text = ""
		self.setDynamicSortFilter(False)

	def set_search_text(self, text: str) -> None:
		self._search_text = (text or "").strip().lower()
		self.invalidateFilter()

	def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:  # noqa: N802
		model = self.sourceModel()
		if model is None:
			return False
		index = model.index(source_row, 0, source_parent)
		shape_type = model.data(index, ShapeItemsModel.TypeRole)
		if shape_type != "PrimaryShape":
			return False
		if not self._search_text:
			return True
		name = (model.data(index, ShapeItemsModel.NameRole) or "").lower()
		return self._search_text in name


class ShapesFilterProxyModel(QSortFilterProxyModel):
	"""Proxy model for shapes list with text and selected-primary filtering.

	Example:
		>>> proxy.set_selected_primaries({"jawOpen", "lipCornerPuller"})
		>>> proxy.set_search_text("lip")
	"""

	def __init__(self, parent: Optional[QWidget] = None):
		super().__init__(parent)
		self._search_text = ""
		self._selected_primaries: Set[str] = set()
		self._visible_names: Optional[Set[str]] = None
		self._active_only = False
		self._collapsed_levels: Set[int] = set()
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

	def set_search_text(self, text: str) -> None:
		self._search_text = (text or "").strip().lower()
		self._invalidate_level_count_cache()
		self.invalidateFilter()

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
		if self._search_text and self._search_text not in name.lower():
			return False
		if self._active_only:
			value = float(model.data(index, ShapeItemsModel.ValueRole) or 0.0)
			if value <= self._with_value_epsilon:
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
			sculpt_target_indices = set(editor.work_blendshape.get_sculpt_target_indices() or [])
			weights = sorted(editor.get_work_blendshape_weights() or [], key=lambda w: str(w).lower())
			for weight in weights:
				name = str(weight)
				value = float(editor.work_blendshape.get_weight_value(weight))
				muted = bool(editor.get_work_shape_muted_state(name))
				driver_name = editor.get_work_shape_driver(weight)
				connected = bool(driver_name)
				self._row_by_name[name] = len(self._rows)
				row = {"name": name, "type": "WorkShape", "value": value, "muted": muted, "connected": connected}
				if driver_name:
					row["tooltip"] = f"Driven by {driver_name}"
				self._rows.append(row)
				if self._edit_shape_name is None and int(weight.id) in sculpt_target_indices:
					self._edit_shape_name = name
		self.endResetModel()

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

	def refresh_values_from_editor(self) -> List[tuple]:
		"""Pull current work-blendshape values and update rows without rebuilding.

		Returns a list of changed rows as tuples: (name, value).
		"""
		if self._editor is None or self._editor.work_blendshape is None:
			return []

		weights = self._editor.work_blendshape.get_weights() or set()
		weight_by_name = {str(weight): weight for weight in weights}
		changed: List[tuple] = []

		for row_index, row in enumerate(self._rows):
			weight = weight_by_name.get(str(row.get("name", "")))
			new_value = self._editor.work_blendshape.get_weight_value(weight) if weight is not None else 0.0
			clamped_value = max(0.0, min(1.0, float(new_value)))
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

	def sizeHint(self, option, index):  # noqa: N802
		if bool(index.model().data(index, ShapeItemsModel.IsHeaderRole)):
			return QSize(option.rect.width(), 28)
		return QSize(option.rect.width(), 24)

	def __init__(self, parent=None) -> None:
		super().__init__(parent)
		self._name_column_width = 0
		self._value_column_width = 86
		self._drag_active = False
		self._drag_index = QPersistentModelIndex()
		self._drag_model = None
		self._drag_start_x = 0
		self._drag_start_value = 0.0
		self._drag_range_px = 1
		self._drag_target_indexes: List[QPersistentModelIndex] = []
		self._drag_target_start_values: Dict[QPersistentModelIndex, float] = {}

	def set_name_column_width(self, width: int) -> None:
		"""Set aligned name column width used to place the value area."""
		self._name_column_width = max(0, int(width))

	def value_column_width(self) -> int:
		"""Return fixed value column width used by rows and headers."""
		return self._value_column_width

	def _area_rects(self, option, index):
		rect = option.rect
		value = float(index.model().data(index, ShapeItemsModel.ValueRole) or 0.0)
		left_margin = 6
		column_gap = 12
		icon_size = 22
		icon_gap = 8
		right_margin = 4
		value_w = min(self._value_column_width, max(40, rect.width() - 40))
		icon_slots = 1 + (1 if self._is_lock_icon_visible(index) else 0)

		value_left = rect.left() + left_margin
		value_rect = QRect(value_left, rect.top(), value_w, rect.height())

		icon_left = value_rect.right() + 1 + column_gap
		text_left = icon_left + (icon_size * icon_slots) + (icon_gap * icon_slots)
		text_width = max(20, rect.right() - text_left - right_margin)
		text_rect = QRect(text_left, rect.top(), text_width, rect.height())
		return value_rect, text_rect

	def _is_lock_icon_visible(self, index) -> bool:
		return bool(index.model().data(index, ShapeItemsModel.LockIconVisibleRole))

	def _mute_icon_rect(self, option, index) -> QRect:
		value_rect, _ = self._area_rects(option, index)
		icon_size = 22
		column_gap = 12
		x = value_rect.right() + 1 + column_gap
		y = option.rect.top() + (option.rect.height() - icon_size) // 2
		return QRect(x, y, icon_size, icon_size)

	def _lock_icon_rect(self, option, index) -> QRect:
		if not self._is_lock_icon_visible(index):
			return QRect()
		mute_rect = self._mute_icon_rect(option, index)
		icon_gap = 8
		return QRect(mute_rect.right() + 1 + icon_gap, mute_rect.top(), mute_rect.width(), mute_rect.height())

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
			painter.drawText(rect.adjusted(6, 0, -6, 0), Qt.AlignVCenter | Qt.AlignLeft, f"{name}")
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
				related_color = QColor(196, 196, 196, 90)
				painter.fillRect(option.rect, related_color)

		if option.state & QStyle.State_Selected:
			sel = option.palette.highlight().color()
			sel.setAlpha(60)
			painter.fillRect(option.rect, sel)

		indicator_rect = QRect(option.rect.left() + 1, option.rect.top() + 3, 4, max(6, option.rect.height() - 6))
		indicator_color = QColor(0, 0, 0, 0)
		if is_connected_work_shape:
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
		if is_connected_work_shape:
			fill_color = option.palette.highlight().color()

		painter.fillRect(track_rect, value_bg)
		painter.setPen(track_border)
		painter.drawRect(track_rect.adjusted(0, 0, -1, -1))

		if progress_width > 0:
			progress_rect = QRect(track_rect.left(), track_rect.top(), progress_width, track_rect.height())
			painter.fillRect(progress_rect, fill_color)

		if muted:
			name_text_color = QColor("gray")
		if in_edit_mode:
			name_text_color = QColor(230, 74, 74)
			bold_font = painter.font()
			bold_font.setBold(True)
			painter.setFont(bold_font)

		painter.setPen(name_text_color)
		painter.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft, name)
		painter.setPen(value_text_color)
		painter.drawText(value_rect.adjusted(0, 0, -6, 0), Qt.AlignVCenter | Qt.AlignRight, f"{value:.3f}")

		icon_rect = self._mute_icon_rect(option, index)
		mute_icon = MUTE_ON_ICON if muted else MUTE_OFF_ICON
		if not mute_icon.isNull():
			self._draw_icon_pixmap(painter, icon_rect, mute_icon)

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

	def editorEvent(self, event, model, option, index):  # noqa: N802
		if bool(model.data(index, ShapeItemsModel.IsHeaderRole)):
			return super().editorEvent(event, model, option, index)

		if event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
			icon_rect = self._mute_icon_rect(option, index)
			if icon_rect.contains(event.pos()):
				shape_name = str(model.data(index, ShapeItemsModel.NameRole) or "")
				if shape_name:
					current_muted = bool(model.data(index, ShapeItemsModel.MutedRole))
					self.muteToggleRequested.emit(shape_name, not current_muted)
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

		if event.type() == QEvent.MouseButtonPress:
			if event.button() == Qt.LeftButton and value_rect.contains(event.pos()):
				if not self._drag_active:
					self._start_drag(model, index, event.pos(), value_rect)
				else:
					self._set_drag_value_from_pos(model, event.pos().x())
				return True

		if event.type() == QEvent.MouseMove:
			if self._drag_active and (event.buttons() & Qt.LeftButton):
				self._set_drag_value_from_pos(model, event.pos().x())
				return True

		if event.type() == QEvent.MouseButtonRelease:
			if self._drag_active and event.button() == Qt.LeftButton:
				self._end_drag(model, event.pos().x())
				return True

		if event.type() == QEvent.MouseButtonDblClick:
			if value_rect.contains(event.pos()):
				parent = self.parent()
				if isinstance(parent, QAbstractItemView):
					parent.edit(index)
					return True
			# Prevent default item-edit behavior on non-slider double-clicks.
			return True

		return super().editorEvent(event, model, option, index)


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


class WorkShapesListView(SliderListView):
	"""Work shapes list supporting drops from shape lists and link context actions."""

	def __init__(
		self,
		drop_callback: Callable[[str, str], None],
		duplicate_callback: Callable[[str], None],
		break_link_callback: Callable[[str], None],
		copy_weights_callback: Optional[Callable[[str], None]] = None,
		paste_weights_callback: Optional[Callable[[str], None]] = None,
		paste_inverted_weights_callback: Optional[Callable[[str], None]] = None,
		add_copied_weights_callback: Optional[Callable[[str], None]] = None,
		subtract_copied_weights_callback: Optional[Callable[[str], None]] = None,
		can_paste_weights_callback: Optional[Callable[[], bool]] = None,
		parent=None,
	) -> None:
		super().__init__(parent)
		self._drop_callback = drop_callback
		self.duplicate_callback = duplicate_callback
		self._break_link_callback = break_link_callback
		self._copy_weights_callback = copy_weights_callback
		self._paste_weights_callback = paste_weights_callback
		self._paste_inverted_weights_callback = paste_inverted_weights_callback
		self._add_copied_weights_callback = add_copied_weights_callback
		self._subtract_copied_weights_callback = subtract_copied_weights_callback
		self._can_paste_weights_callback = can_paste_weights_callback
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
		menu = QMenu(self)
		duplicate_action = menu.addAction(f"Duplicate")
		connections_menu = menu.addMenu("Connections")
		break_link_action = connections_menu.addAction("Break Link")

		weight_maps_menu = menu.addMenu("Weight Maps")
		copy_weights_action = weight_maps_menu.addAction("Copy")
		paste_weights_action = weight_maps_menu.addAction("Paste Weights")
		paste_inverted_weights_action = weight_maps_menu.addAction("Paste Inverted Weights")
		add_copied_weights_action = weight_maps_menu.addAction("Add Copied Weights")
		subtract_copied_weights_action = weight_maps_menu.addAction("Subtract Copied Weights")

		can_paste_weights = True
		if self._can_paste_weights_callback is not None:
			can_paste_weights = bool(self._can_paste_weights_callback())
		paste_weights_action.setEnabled(can_paste_weights)
		paste_inverted_weights_action.setEnabled(can_paste_weights)
		add_copied_weights_action.setEnabled(can_paste_weights)
		subtract_copied_weights_action.setEnabled(can_paste_weights)

		if hasattr(menu, "exec"):
			selected_action = menu.exec(self.viewport().mapToGlobal(pos))
		else:
			selected_action = menu.exec_(self.viewport().mapToGlobal(pos))
		if selected_action == duplicate_action:
			self.duplicate_callback(receiver_name)
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


class ShapeTreeWidget(QTreeWidget):
	"""Tree view for shapes that supports slider drag forwarding and shape drags."""

	DRAG_MIME_TYPE = "application/x-blue-steel-shape-names"
	toggleUpstreamFilterRequested = Signal()

	def _selected_draggable_shape_names(self) -> List[str]:
		shape_names: List[str] = []
		for item in self.selectedItems():
			if bool(item.data(0, ShapeItemsModel.IsHeaderRole)):
				continue
			shape_name = str(item.data(0, ShapeItemsModel.NameRole) or "")
			if shape_name:
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

	def keyPressEvent(self, event):  # noqa: N802
		"""Press F to center the selected/current shape row in the shapes panel."""
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

	def mouseMoveEvent(self, event):  # noqa: N802
		delegate = self.itemDelegateForColumn(0)
		if isinstance(delegate, SliderItemDelegate) and delegate.is_drag_active():
			if delegate.external_drag_move(event.pos().x()):
				event.accept()
				return
		super().mouseMoveEvent(event)

	def mouseReleaseEvent(self, event):  # noqa: N802
		delegate = self.itemDelegateForColumn(0)
		if isinstance(delegate, SliderItemDelegate) and event.button() == Qt.LeftButton and delegate.is_drag_active():
			if delegate.external_drag_end(event.pos().x()):
				event.accept()
				return
		super().mouseReleaseEvent(event)


class PrimaryTreeWidget(QTreeWidget):
	"""QTreeWidget that forwards drag move/release to primaries value delegate."""

	def mouseMoveEvent(self, event):  # noqa: N802
		delegate = self.itemDelegateForColumn(1)
		if isinstance(delegate, PrimaryTreeValueDelegate) and delegate.is_drag_active():
			if delegate.external_drag_move(event.pos().x()):
				event.accept()
				return
		super().mouseMoveEvent(event)

	def mouseReleaseEvent(self, event):  # noqa: N802
		delegate = self.itemDelegateForColumn(1)
		if isinstance(delegate, PrimaryTreeValueDelegate) and event.button() == Qt.LeftButton and delegate.is_drag_active():
			if delegate.external_drag_end(event.pos().x()):
				event.accept()
				return
		super().mouseReleaseEvent(event)


class PrimaryTreeValueDelegate(QStyledItemDelegate):
	"""Delegate that draws/edits primaries tree value cells like slider rows."""
	_MIN_ROW_HEIGHT = 24

	valueCommitted = Signal(str, float)
	valueDragStarted = Signal()
	valueDragEnded = Signal()

	def __init__(self, name_role: int, parent=None) -> None:
		super().__init__(parent)
		self._name_role = name_role
		self._drag_active = False
		self._drag_index = QPersistentModelIndex()
		self._drag_model = None
		self._drag_start_x = 0
		self._drag_start_value = 0.0
		self._drag_range_px = 1
		self._drag_target_indexes: List[QPersistentModelIndex] = []
		self._drag_target_start_values: Dict[QPersistentModelIndex, float] = {}

	def _shape_name_from_index(self, index: QModelIndex) -> Optional[str]:
		if not index.isValid():
			return None
		name_index = index.sibling(index.row(), 0)
		shape_name = name_index.data(self._name_role)
		return str(shape_name) if shape_name else None

	def _is_leaf_value_cell(self, index: QModelIndex) -> bool:
		if not index.isValid() or index.column() != 1:
			return False
		return self._shape_name_from_index(index) is not None

	def _value_from_index(self, index: QModelIndex) -> float:
		return max(0.0, min(1.0, float(index.data(Qt.UserRole) or 0.0)))

	def _set_value(self, model, index: QModelIndex, value: float, *, emit: bool = True) -> None:
		if not self._is_leaf_value_cell(index):
			return
		value = max(0.0, min(1.0, float(value)))
		model.setData(index, value, Qt.UserRole)
		if emit:
			shape_name = self._shape_name_from_index(index)
			if shape_name:
				self.valueCommitted.emit(shape_name, value)

	def _slider_rect(self, option) -> QRect:
		return option.rect.adjusted(6, 3, -6, -3)

	def sizeHint(self, option, index):  # noqa: N802
		size = super().sizeHint(option, index)
		if self._is_leaf_value_cell(index):
			size.setHeight(max(size.height(), self._MIN_ROW_HEIGHT))
		return size

	def paint(self, painter: QPainter, option, index):
		if not self._is_leaf_value_cell(index):
			return super().paint(painter, option, index)

		value = self._value_from_index(index)
		rect = option.rect
		track_rect = self._slider_rect(option)

		painter.save()
		painter.fillRect(rect, option.palette.base().color())
		if option.state & QStyle.State_Selected:
			sel = option.palette.highlight().color()
			sel.setAlpha(60)
			painter.fillRect(rect, sel)

		track_bg = QColor(57, 57, 57)
		track_border = QColor(83, 83, 83)
		fill_color = QColor(109, 109, 109)

		painter.fillRect(track_rect, track_bg)
		painter.setPen(track_border)
		painter.drawRect(track_rect.adjusted(0, 0, -1, -1))

		progress_width = int(value * track_rect.width())
		if progress_width > 0:
			painter.fillRect(QRect(track_rect.left(), track_rect.top(), progress_width, track_rect.height()), fill_color)

		painter.setPen(option.palette.text().color())
		painter.drawText(track_rect.adjusted(0, 0, -6, 0), Qt.AlignVCenter | Qt.AlignRight, f"{value:.3f}")
		painter.restore()

	def createEditor(self, parent, option, index):  # noqa: N802
		if not self._is_leaf_value_cell(index):
			return None
		editor = QLineEdit(parent)
		editor.setFrame(False)
		editor.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
		editor.setValidator(QDoubleValidator(0.0, 1.0, 4, editor))
		return editor

	def setEditorData(self, editor, index):  # noqa: N802
		editor.setText(f"{self._value_from_index(index):.4f}")

	def setModelData(self, editor, model, index):  # noqa: N802
		try:
			value = float(editor.text())
		except ValueError:
			value = self._value_from_index(index)
		self._set_value(model, index, value, emit=True)

	def updateEditorGeometry(self, editor, option, index):  # noqa: N802
		editor.setGeometry(self._slider_rect(option))

	def _set_drag_value_from_pos(self, model, x_pos: int) -> None:
		if not self._drag_target_indexes:
			return
		delta_px = x_pos - self._drag_start_x
		delta_value = float(delta_px) / float(max(1, self._drag_range_px))
		for target_index in self._drag_target_indexes:
			if not target_index.isValid():
				continue
			start_value = self._drag_target_start_values.get(target_index, 0.0)
			new_value = start_value + delta_value
			self._set_value(model, target_index, new_value, emit=True)

	def _resolve_drag_targets(self, index: QModelIndex) -> None:
		"""Mirror shapes behavior:
		- dragging selected row -> affect all selected leaf rows
		- dragging non-selected row -> affect only dragged row
		"""
		self._drag_target_indexes = []
		self._drag_target_start_values = {}

		parent = self.parent()
		if not isinstance(parent, QAbstractItemView) or parent.selectionModel() is None:
			persistent = QPersistentModelIndex(index)
			self._drag_target_indexes = [persistent]
			self._drag_target_start_values[persistent] = self._value_from_index(index)
			return

		row0_index = index.sibling(index.row(), 0)
		selected_rows0 = parent.selectionModel().selectedRows(0)
		if row0_index in selected_rows0:
			candidate_indexes = [row_index.sibling(row_index.row(), 1) for row_index in selected_rows0]
		else:
			candidate_indexes = [index]

		for candidate in candidate_indexes:
			if not self._is_leaf_value_cell(candidate):
				continue
			persistent = QPersistentModelIndex(candidate)
			self._drag_target_indexes.append(persistent)
			self._drag_target_start_values[persistent] = self._value_from_index(candidate)

		if not self._drag_target_indexes:
			persistent = QPersistentModelIndex(index)
			self._drag_target_indexes = [persistent]
			self._drag_target_start_values[persistent] = self._value_from_index(index)

	def _start_drag(self, model, index, event_pos, track_rect: QRect) -> None:
		self._drag_active = True
		self._drag_index = QPersistentModelIndex(index)
		self._drag_model = model
		self._drag_start_x = event_pos.x()
		self._drag_start_value = self._value_from_index(index)
		self._drag_range_px = max(1, track_rect.width())
		self._resolve_drag_targets(index)
		self._grab_view_mouse()
		self.valueDragStarted.emit()

	def _end_drag(self) -> None:
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
		if not self._drag_active or self._drag_model is None:
			return False
		self._set_drag_value_from_pos(self._drag_model, x_pos)
		return True

	def external_drag_end(self, x_pos: int) -> bool:
		if not self._drag_active or self._drag_model is None:
			return False
		self._set_drag_value_from_pos(self._drag_model, x_pos)
		self._end_drag()
		return True

	def editorEvent(self, event, model, option, index):  # noqa: N802
		if not self._is_leaf_value_cell(index):
			return super().editorEvent(event, model, option, index)

		track_rect = self._slider_rect(option)

		if event.type() == QEvent.MouseButtonPress:
			if event.button() == Qt.LeftButton and track_rect.contains(event.pos()):
				self._start_drag(model, index, event.pos(), track_rect)
				self._set_drag_value_from_pos(model, event.pos().x())
				return True

		if event.type() == QEvent.MouseMove:
			if self._drag_active and (event.buttons() & Qt.LeftButton):
				self._set_drag_value_from_pos(model, event.pos().x())
				return True

		if event.type() == QEvent.MouseButtonRelease:
			if self._drag_active and event.button() == Qt.LeftButton:
				self._set_drag_value_from_pos(model, event.pos().x())
				self._end_drag()
				return True

		if event.type() == QEvent.MouseButtonDblClick:
			if track_rect.contains(event.pos()):
				parent = self.parent()
				if isinstance(parent, QAbstractItemView):
					parent.edit(index)
					return True

		return super().editorEvent(event, model, option, index)


class PrimaryTreeItem(QTreeWidgetItem):
	"""Tree item with numeric-aware sorting on the Value column."""

	def __lt__(self, other):  # noqa: N802
		tree = self.treeWidget()
		if tree is None:
			return super().__lt__(other)
		column = tree.sortColumn()
		if column == 1:
			left_value = float(self.data(1, Qt.UserRole) or 0.0)
			right_value = float(other.data(1, Qt.UserRole) or 0.0)
			if abs(left_value - right_value) > 1e-9:
				return left_value < right_value
			# stable tie-breaker by name
			return (self.text(0) or "").lower() < (other.text(0) or "").lower()
		return (self.text(column) or "").lower() < (other.text(column) or "").lower()


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


class MainWindow(QMainWindow):
	"""Main Blue Steel editor window."""

	EMPTY_SYSTEM_LABEL = "<Select System>"
	PRIMARY_TREE_NAME_ROLE = Qt.UserRole + 200
	PRIMARY_TREE_FOLDER_ROLE = Qt.UserRole + 201

	def __init__(self, parent: Optional[QWidget] = None):
		super().__init__(parent)
		
		icon_path = os.path.abspath(os.path.join(env.ICONS_PATH, "blue_steel_icon.svg"))
		if os.path.exists(icon_path):
			self.setWindowIcon(QIcon(icon_path))

		self.current_editor: Optional[BlueSteelEditor] = None
		self.scene_editor_tracker: Optional[BlueSteelEditorsTracker] = None
		self.blendshape_tracker: Optional[BlendShapeNodeTracker] = None
		self.work_blendshape_tracker: Optional[BlendShapeNodeTracker] = None

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
		self._primary_tree_sort_column = 0
		self._primary_tree_sort_order = Qt.AscendingOrder
		self._primaries_drag_active = False
		self._linked_drag_active = False
		self._linked_primary_start_values: Dict[str, float] = {}
		self._linked_work_start_values: Dict[str, float] = {}
		self._linked_drag_can_propagate = False
		self._linked_drag_ctrl_pressed = False
		self._primary_tree_items: Dict[str, QTreeWidgetItem] = {}
		self._shape_tree_items: Dict[str, QTreeWidgetItem] = {}
		self._syncing_shapes_tree = False
		self._upstream_shapes_cache: Dict[str, Set[str]] = {}
		self._downstream_shapes_cache: Dict[str, Set[str]] = {}
		self._primary_tree_folder_open_icon = QIcon()
		self._primary_tree_folder_closed_icon = QIcon()
		self.tool_buttons: List[QPushButton] = []
		self.rename_editor_action: Optional[QAction] = None
		self.explode_container_action: Optional[QAction] = None
		self.fix_invisible_blendshapes_action: Optional[QAction] = None
		self.simplex_action: Optional[QAction] = None
		self.prepare_for_publishing_action: Optional[QAction] = None
		self._workshape_rename_editor: Optional[QLineEdit] = None
		self._workshape_rename_old_name: str = ""
		self._primary_rename_editor: Optional[QLineEdit] = None
		self._primary_rename_old_name: str = ""

		self._build_ui()
		self._connect_ui_signals()
		self._setup_scene_editor_tracker()
		self._reload_editor_menu()
		self._select_first_available_editor()
		self._update_window_title()

	def _build_ui(self) -> None:
		self._create_menu_bar()

		central = QWidget(self)
		self.setCentralWidget(central)
		root_layout = QVBoxLayout(central)
		root_layout.setContentsMargins(6, 6, 6, 6)

		controls_layout = QHBoxLayout()
		self.refresh_button = QPushButton("Refresh")
		self.refresh_button.setIcon(REFRESH_ICON)
		self.create_system_button = QPushButton("New")
		self.create_system_button.setIcon(ADD_ICON)
		self.editor_combo = QComboBox()
		self.editor_combo.setSizeAdjustPolicy(QComboBox.AdjustToContents)
		controls_layout.addWidget(self.refresh_button)
		controls_layout.addWidget(self.create_system_button)
		controls_layout.addWidget(QLabel("System:"))
		controls_layout.addWidget(self.editor_combo)
		controls_layout.addStretch()
		root_layout.addLayout(controls_layout)

		splitter = QSplitter(Qt.Horizontal)
		root_layout.addWidget(splitter, 1)
		self._build_tools_panel(splitter)

		primaries_panel = QWidget()
		primaries_layout = QVBoxLayout(primaries_panel)
		primaries_layout.addWidget(QLabel("Primaries"))
		self.primaries_search = QLineEdit()
		self.primaries_search.setPlaceholderText("Filter primaries...")
		primaries_layout.addWidget(self.primaries_search)
		self.primaries_view = PrimaryTreeWidget()
		self.primaries_view.setColumnCount(2)
		self.primaries_view.setHeaderLabels(["Primary", "Value"])
		# Match indentation to icon+spacing so child text aligns with group label text.
		self.primaries_view.setIndentation(18)
		self._apply_primaries_branch_icons()
		self.primaries_view.setColumnWidth(1, 140)
		self.primaries_view.header().setSectionsClickable(True)
		self.primaries_view.header().setSortIndicatorShown(True)
		self.primaries_view.header().setSortIndicator(self._primary_tree_sort_column, self._primary_tree_sort_order)
		self.primaries_view.setSelectionMode(QAbstractItemView.ExtendedSelection)
		self.primaries_view.setDragEnabled(True)
		self.primaries_view.setContextMenuPolicy(Qt.CustomContextMenu)
		self._primaries_delegate = PrimaryTreeValueDelegate(self.PRIMARY_TREE_NAME_ROLE, self.primaries_view)
		self.primaries_view.setItemDelegateForColumn(1, self._primaries_delegate)

		primaries_layout.addWidget(self.primaries_view, 1)
		self.primaries_info = QLabel("Items: 0")
		primaries_layout.addWidget(self.primaries_info)

		shapes_panel = QWidget()
		shapes_layout = QVBoxLayout(shapes_panel)
		shapes_layout.addWidget(QLabel("Shapes"))
		self.shapes_search = QLineEdit()
		self.shapes_search.setPlaceholderText("Filter shapes...")
		shapes_layout.addWidget(self.shapes_search)
		self.shapes_view = ShapeTreeWidget()
		self.shapes_view.setColumnCount(1)
		self.shapes_view.setHeaderHidden(True)
		self.shapes_view.setIndentation(18)
		self.shapes_view.setRootIsDecorated(True)
		self.shapes_view.setSelectionMode(QAbstractItemView.ExtendedSelection)
		self.shapes_view.setDragEnabled(True)
		self.shapes_view.setDragDropMode(QAbstractItemView.DragOnly)
		self.shapes_view.setContextMenuPolicy(Qt.CustomContextMenu)
		self._shapes_delegate = SliderItemDelegate(self.shapes_view)
		self.shapes_view.setItemDelegateForColumn(0, self._shapes_delegate)

		shapes_header_layout = QHBoxLayout()
		shapes_header_layout.setContentsMargins(6, 0, 4, 0)
		shapes_header_layout.setSpacing(2)
		self.shapes_auto_pose_button = QPushButton("Auto Pose")
		self.shapes_auto_pose_button.setIcon(AUTO_POSE_ICON)
		self.shapes_auto_pose_button.setFixedHeight(26)
		self.shapes_auto_pose_button.setToolTip("When enabled, selecting a shape sets it to its pose")
		self.shapes_auto_pose_button.setCheckable(True)
		self.shapes_auto_pose_button.setChecked(False)
		shapes_header_layout.addWidget(self.shapes_auto_pose_button)

		self.shapes_downstream_button = QPushButton("Downstream")
		self.shapes_downstream_button.setIcon(DOWN_ARROW_ICON)
		self.shapes_downstream_button.setIconSize(QSize(16, 16))
		self.shapes_downstream_button.setFixedHeight(26)
		self.shapes_downstream_button.setToolTip("List Downstream Connections")
		self.shapes_downstream_button.setCheckable(True)
		self.shapes_downstream_button.setChecked(False)
		shapes_header_layout.addWidget(self.shapes_downstream_button)

		self.shapes_upstream_button = QPushButton("Upstream")
		self.shapes_upstream_button.setIcon(UP_ARROW_ICON)
		self.shapes_upstream_button.setIconSize(QSize(16, 16))
		self.shapes_upstream_button.setFixedHeight(26)
		self.shapes_upstream_button.setToolTip("List Upstream Connections")
		self.shapes_upstream_button.setCheckable(True)
		self.shapes_upstream_button.setChecked(False)
		shapes_header_layout.addWidget(self.shapes_upstream_button)
		shapes_header_layout.addStretch(1)
		shapes_layout.addLayout(shapes_header_layout)

		shapes_layout.addWidget(self.shapes_view, 1)
		shapes_footer_layout = QVBoxLayout()
		shapes_footer_layout.setContentsMargins(0, 0, 0, 0)
		shapes_footer_layout.setSpacing(0)
		self.remove_shapes_button = QPushButton("Remove Shapes")
		self.remove_shapes_button.setIcon(DELETE_ICON)
		self.tool_buttons.append(self.remove_shapes_button)
		shapes_footer_layout.addWidget(self.remove_shapes_button)
		self.shapes_info = QLabel("Items: 0")
		shapes_footer_layout.addWidget(self.shapes_info)
		shapes_layout.addLayout(shapes_footer_layout)

		third_column_panel = QWidget()
		third_column_layout = QVBoxLayout(third_column_panel)
		third_column_layout.setContentsMargins(0, 0, 0, 0)
		third_column_layout.setSpacing(8)
		third_column_splitter = QSplitter(Qt.Vertical)
		third_column_layout.addWidget(third_column_splitter, 1)

		primary_drop_section = QGroupBox("Sliders Drop Box")
		primary_drop_layout = QVBoxLayout(primary_drop_section)
		primary_drop_toolbar = QHBoxLayout()
		self.primary_drop_get_active_button = QPushButton("Get Active")
		primary_drop_toolbar.addWidget(self.primary_drop_get_active_button)
		primary_drop_toolbar.addStretch(1)
		primary_drop_layout.addLayout(primary_drop_toolbar)
		self.primary_drop_view = PrimaryDropListView(
			self._on_primary_drop_list_dropped,
			self._on_primary_drop_remove_requested,
		)
		self.primary_drop_view.setSelectionMode(QAbstractItemView.ExtendedSelection)
		self.primary_drop_view.setModel(self._primary_subset_proxy)
		self._primary_drop_delegate = SliderItemDelegate(self.primary_drop_view)
		self.primary_drop_view.setItemDelegate(self._primary_drop_delegate)
		primary_drop_layout.addWidget(self.primary_drop_view, 1)

		work_shapes_section = QGroupBox("Work Shapes")
		work_shapes_layout = QVBoxLayout(work_shapes_section)
		work_toolbar = QHBoxLayout()
		#work_toolbar.addWidget(QLabel("Tools"))
		self.work_add_button = QPushButton("Add")
		self.work_add_button.setToolTip("Add a new work blendshape target")
		work_toolbar.addWidget(self.work_add_button)
		self.work_remove_button = QPushButton("Remove")
		self.work_remove_button.setToolTip("Remove selected work blendshape targets")
		work_toolbar.addWidget(self.work_remove_button)
		self.work_paint_button = QPushButton("Paint Weights")
		self.work_paint_button.setToolTip("Paint selected work blendshape target")
		work_toolbar.addWidget(self.work_paint_button)
		self.work_edit_mode_button = QPushButton("Edit Selected")
		self.work_edit_mode_button.setToolTip("Toggle edit mode on selected work blendshape target")
		work_toolbar.addWidget(self.work_edit_mode_button)
		work_toolbar.addStretch(1)
		work_shapes_layout.addLayout(work_toolbar)
		self.work_shapes_view = WorkShapesListView(
			self._on_work_shape_drop_received,
			self._on_work_shape_duplicate_requested,
			self._on_work_shape_break_link_requested,
			self._on_work_shape_copy_weights_requested,
			self._on_work_shape_paste_weights_requested,
			self._on_work_shape_paste_inverted_weights_requested,
			self._on_work_shape_add_copied_weights_requested,
			self._on_work_shape_subtract_copied_weights_requested,
			self._has_copied_work_weight_map_values,
		)
		self.work_shapes_view.setSelectionMode(QAbstractItemView.ExtendedSelection)
		self.work_shapes_view.setModel(self._work_shape_model)
		self._work_shapes_delegate = SliderItemDelegate(self.work_shapes_view)
		self.work_shapes_view.setItemDelegate(self._work_shapes_delegate)
		work_shapes_layout.addWidget(self.work_shapes_view, 1)

		active_shapes_section = QGroupBox("Active Shapes")
		active_shapes_layout = QVBoxLayout(active_shapes_section)
		self.active_shapes_view = SliderListView()
		self.active_shapes_view.setSelectionMode(QAbstractItemView.ExtendedSelection)
		self.active_shapes_view.setDragEnabled(True)
		self.active_shapes_view.setDragDropMode(QAbstractItemView.DragOnly)
		self.active_shapes_view.setModel(self._active_shapes_proxy)
		self._active_shapes_delegate = SliderItemDelegate(self.active_shapes_view)
		self.active_shapes_view.setItemDelegate(self._active_shapes_delegate)
		active_shapes_layout.addWidget(self.active_shapes_view, 1)

		third_column_splitter.addWidget(primary_drop_section)
		third_column_splitter.addWidget(work_shapes_section)
		third_column_splitter.addWidget(active_shapes_section)
		third_column_splitter.setStretchFactor(0, 1)
		third_column_splitter.setStretchFactor(1, 1)
		third_column_splitter.setStretchFactor(2, 1)
		third_column_splitter.setSizes([260, 260, 260])

		splitter.addWidget(primaries_panel)
		splitter.addWidget(shapes_panel)
		splitter.addWidget(third_column_panel)
		splitter.setStretchFactor(0, 0)
		splitter.setStretchFactor(1, 1)
		splitter.setStretchFactor(2, 2)
		splitter.setSizes([200, 340, 520, 360])

		self.status_bar = QStatusBar(self)
		self.setStatusBar(self.status_bar)
		self.status_bar.showMessage("Ready")

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
				padding-top: 2px;
				padding-bottom: 2px;
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
		"""Start inline rename editing for a primary tree leaf item."""
		if self.current_editor is None:
			self._set_status("No system selected.", warning=True)
			return
		if item is None or column != 0:
			return
		# Defer creation so the tree's own double-click handling finishes first.
		# Without this, focus can bounce back to the tree and immediately cancel edit.
		QTimer.singleShot(0, lambda i=item: self._begin_inline_primary_rename(i))

	def _show_primaries_context_menu(self, pos) -> None:
		if self.current_editor is None:
			return
		item = self.primaries_view.itemAt(pos)
		if item is None:
			return

		primary_name = item.data(0, self.PRIMARY_TREE_NAME_ROLE)
		if not primary_name:
			return

		primary_name = str(primary_name)
		menu = QMenu(self.primaries_view)
		add_inbetween_action = menu.addAction("Add Inbetween")
		if hasattr(menu, "exec"):
			selected_action = menu.exec(self.primaries_view.viewport().mapToGlobal(pos))
		else:
			selected_action = menu.exec_(self.primaries_view.viewport().mapToGlobal(pos))

		if selected_action == add_inbetween_action:
			self._on_add_inbetween_requested(primary_name)

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
		tools_group.setContentsMargins(2, 2, 2, 2)
		tools_group.setFixedWidth(200)
		tools_group.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
		parent_layout.addWidget(tools_group)

		self.tool_buttons = []
		main_tools_layout = QVBoxLayout(tools_group)
		main_tools_layout.setSpacing(10)
		main_tools_layout.setSizeConstraint(QLayout.SetMinimumSize)

		self.mmtools_button = self._create_tool_button("MMTools", MMTOOLS_ICON, track_enabled=False)
		main_tools_layout.addWidget(self.mmtools_button)

		editor_frame_layout = frameLayout.FrameLayout("Editor")
		self.select_editor_button = self._create_tool_button("Select Controller", SELECT_ICON)
		self.zero_all_button = self._create_tool_button("Zero All", ZERO_VALUE_ICON)
		self.rename_button = self._create_tool_button("Rename To Pose", RENAME_ICON)
		self.duplicate_button = self._create_tool_button("Duplicate Rename", DUPLICATE_ICON)
		editor_frame_layout.addWidget(self.select_editor_button)
		editor_frame_layout.addWidget(self.zero_all_button)
		editor_frame_layout.addWidget(self.rename_button)
		editor_frame_layout.addWidget(self.duplicate_button)

		edit_shapes_frame_layout = frameLayout.FrameLayout("Shapes Edit")
		self.add_primary_button = self._create_tool_button("Add/Commit New Primary", ADD_ICON)
		self.add_primary_button.setToolTip("Add selected mesh as a new primary shape.\n If there are no selected meshes, creates an empty primary shape that can be filled by copying values from an existing shape.")
		self.add_selected_at_current_pose_button = self._create_tool_button("Add/Commit At Current Pose", ADD_AT_POSE_ICON)
		self.add_selected_at_current_pose_button.setToolTip("Add the selected mesh at the current pose extrapolating the name from the active values in the controller.\nFor example: (lipCornerPuller, 0.5) (jawOpen, 1.0) -> lipCornerPuller50_jawOpen\nIf no mesh is selected an empty shape will be added.")
		self.commit_shapes_button = self._create_tool_button("Commit Selected", COMMIT_ICON)
		edit_shapes_frame_layout.addWidget(self.commit_shapes_button)
		edit_shapes_frame_layout.addWidget(self.add_primary_button)
		edit_shapes_frame_layout.addWidget(self.add_selected_at_current_pose_button)


		preview_shapes_frame_layout = frameLayout.FrameLayout("Shapes Preview")
		self.unmute_all_shapes_button = self._create_tool_button("Unmute All Shapes", MUTE_OFF_ICON)
		preview_shapes_frame_layout.addWidget(self.unmute_all_shapes_button)
		self.unlock_all_shapes_button = self._create_tool_button("Unlock All Shapes", LOCK_OFF_ICON)
		preview_shapes_frame_layout.addWidget(self.unlock_all_shapes_button)

		debug_shapes_frame_layout = frameLayout.FrameLayout("Debug")
		self.compare_shapes_button = self._create_tool_button("Compare Shapes")
		debug_shapes_frame_layout.addWidget(self.compare_shapes_button)

		main_tools_layout.addWidget(edit_shapes_frame_layout, 0)
		main_tools_layout.addWidget(editor_frame_layout, 0)
		main_tools_layout.addWidget(preview_shapes_frame_layout, 0)
		main_tools_layout.addWidget(debug_shapes_frame_layout, 0)
		main_tools_layout.addStretch(1)

	def _create_tool_button(self, label: str, icon: Optional[QIcon] = None, *, track_enabled: bool = True) -> QPushButton:
		button = QPushButton(label)
		button.setStyleSheet("text-align: left; padding-left: 5px;")
		if icon is not None:
			button.setIcon(icon)
		if track_enabled:
			self.tool_buttons.append(button)
		return button

	def _connect_ui_signals(self) -> None:
		self.refresh_button.clicked.connect(self.refresh_ui)
		self.create_system_button.clicked.connect(self._create_new_editor)
		self.editor_combo.currentTextChanged.connect(self._on_editor_selected)
		self.primaries_view.header().sectionClicked.connect(self._on_primaries_header_clicked)
		self._primaries_delegate.valueCommitted.connect(self._on_primary_tree_slider_changed)
		self._primaries_delegate.valueDragStarted.connect(lambda: self._on_value_drag_state_changed(True))
		self._primaries_delegate.valueDragEnded.connect(lambda: self._on_value_drag_state_changed(False))
		self._shapes_delegate.muteToggleRequested.connect(self._on_shapes_mute_toggle_requested)
		self._shapes_delegate.lockToggleRequested.connect(self._on_shapes_lock_toggle_requested)
		self._active_shapes_delegate.muteToggleRequested.connect(self._on_active_shapes_mute_toggle_requested)
		self._active_shapes_delegate.lockToggleRequested.connect(self._on_active_shapes_lock_toggle_requested)
		self._primary_drop_delegate.muteToggleRequested.connect(self._on_primary_drop_mute_toggle_requested)
		self._primary_drop_delegate.lockToggleRequested.connect(self._on_primary_drop_lock_toggle_requested)
		self._work_shapes_delegate.muteToggleRequested.connect(self._on_work_shapes_mute_toggle_requested)
		self.primaries_search.textChanged.connect(self._on_primaries_search_changed)
		self.shapes_search.textChanged.connect(self._on_shapes_search_changed)
		self.shapes_downstream_button.toggled.connect(self._filter_shapes_downstream)
		self.shapes_upstream_button.toggled.connect(self._filter_shapes_upstream)
		self.primary_drop_get_active_button.clicked.connect(self._fill_primary_drop_list_from_active)
		self.shapes_view.itemClicked.connect(self._on_shapes_item_clicked)
		self.shapes_view.itemSelectionChanged.connect(self._on_shapes_selection_changed)
		self.shapes_view.toggleUpstreamFilterRequested.connect(self._on_shapes_toggle_upstream_filter_requested)
		self.shapes_view.itemDoubleClicked.connect(self._on_shapes_double_clicked)
		self.shapes_view.itemExpanded.connect(self._on_shapes_item_expanded)
		self.shapes_view.itemCollapsed.connect(self._on_shapes_item_collapsed)
		self.shapes_view.customContextMenuRequested.connect(self._show_shapes_context_menu)
		if self.shapes_view.model() is not None:
			self.shapes_view.model().dataChanged.connect(self._on_shapes_tree_data_changed)
		self.active_shapes_view.clicked.connect(self._on_active_shapes_item_clicked)
		self.active_shapes_view.doubleClicked.connect(self._on_active_shapes_double_clicked)
		self.work_shapes_view.doubleClicked.connect(self._on_work_shapes_double_clicked)
		self.select_editor_button.clicked.connect(self.select_face_ctrl)
		self.zero_all_button.clicked.connect(self.zero_all)
		self.rename_button.clicked.connect(self.rename_selected_mesh)
		self.duplicate_button.clicked.connect(self.duplicate_at_value)
		self.add_primary_button.clicked.connect(self._on_add_primary_clicked)
		self.commit_shapes_button.clicked.connect(self.commit_selected)
		self.add_selected_at_current_pose_button.clicked.connect(self.add_selected_at_current_pose)
		self.remove_shapes_button.clicked.connect(self.remove_selected_shapes)
		self.unmute_all_shapes_button.clicked.connect(self.unmute_all_shapes)
		self.unlock_all_shapes_button.clicked.connect(self.unlock_all_shapes)
		self.compare_shapes_button.clicked.connect(self.compare_shapes_debug)
		self.mmtools_button.clicked.connect(self.launch_mmtools)
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
		self.work_edit_mode_button.clicked.connect(self._on_toggle_work_shape_edit_mode)
		if self.work_shapes_view.selectionModel() is not None:
			self.work_shapes_view.selectionModel().selectionChanged.connect(self._on_work_shapes_selection_changed)

		self.primaries_view.itemSelectionChanged.connect(self._on_primaries_selection_changed)
		self.primaries_view.itemExpanded.connect(self._on_primaries_item_expanded)
		self.primaries_view.itemCollapsed.connect(self._on_primaries_item_collapsed)
		self.primaries_view.itemClicked.connect(self._on_primaries_item_clicked)
		self.primaries_view.itemDoubleClicked.connect(self._on_primaries_item_double_clicked)
		self.primaries_view.customContextMenuRequested.connect(self._show_primaries_context_menu)

		self._apply_shapes_name_sort()
		self._sort_primaries_tree()
		self._update_tools_button_panel()
		self._update_work_shape_button_panel()

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
		if self.simplex_action is not None:
			self.simplex_action.setEnabled(activate)
		if self.prepare_for_publishing_action is not None:
			self.prepare_for_publishing_action.setEnabled(activate)

	def _selected_shape_names_from_shapes_view(self) -> List[str]:
		names: List[str] = []
		for item in self.shapes_view.selectedItems():
			if bool(item.data(0, ShapeItemsModel.IsHeaderRole)):
				continue
			shape_name = item.data(0, ShapeItemsModel.NameRole)
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
			poly_meshes = [selected_components[0].split(".")[0]]
		else:
			poly_meshes = cmds.filterExpand(selected, sm=12) or []
		if not poly_meshes:
			self._set_status("No polygon meshes found in selection.", warning=True)
			return

		failed_shapes = []
		try:
			if self.blendshape_tracker is not None:
				self.blendshape_tracker.stop()
			failed_shapes = self.current_editor.commit_shapes(poly_meshes)
		except Exception as exc:
			self._set_status(f"Error committing shapes: {exc}", error=True)
			return
		finally:
			if self.blendshape_tracker is not None:
				self.blendshape_tracker.start()
			self._reload_shapes_from_editor()

		committed_count = len(poly_meshes) - len(failed_shapes)
		meshes_label = "poly mesh" if len(poly_meshes) == 1 else "poly meshes"
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

	def remove_selected_shapes(self) -> None:
		if self.current_editor is None:
			self._set_status("No system selected.", warning=True)
			return

		shape_names = self._selected_shape_names_from_shapes_view()
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

	def extract_selected(self) -> None:
		if self.current_editor is None:
			self._set_status("No system selected.", warning=True)
			return
		# let's get the selected shape names from the shapes view, not the scene selection, since extracting is a shape-level operation
		selected_shapes = self._selected_shape_names_from_shapes_view()
		print(f"Extracting shapes: {selected_shapes}")
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
		mmtools.show()

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
		menu_bar = self.menuBar()

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

		export_menu = file_menu.addMenu("Export")
		export_objs_action = QAction("Export Objs", self)
		export_objs_action.triggered.connect(self._export_objs)
		export_menu.addAction(export_objs_action)

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

		conversion_menu = menu_bar.addMenu("Converters/Clean-Up")
		self.simplex_action = QAction("Convert Simplex", self)
		self.simplex_action.setToolTip("Convert a Simplex facial system into Blue Steel.")
		self.simplex_action.triggered.connect(self._on_simplex_converter_requested)
		self.simplex_action.setEnabled(self.current_editor is not None)
		conversion_menu.addAction(self.simplex_action)
		conversion_menu.addSeparator()
		self.prepare_for_publishing_action = QAction("Prepare For Publishing", self)
		self.prepare_for_publishing_action.setToolTip("Prepare the current editor for publishing and remove editor access.")
		self.prepare_for_publishing_action.triggered.connect(self._on_prepare_for_publishing_requested)
		self.prepare_for_publishing_action.setEnabled(self.current_editor is not None)
		conversion_menu.addAction(self.prepare_for_publishing_action)

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

	def _on_simplex_converter_requested(self) -> None:
		if self.current_editor is None:
			self._set_status("Please select a Blue Steel Editor before converting Simplex systems.", warning=True)
			return

		self._clear_trackers_for_scene_operation()
		try:
			selection = show_simplex_converter_dialog() or {}
			if not selection:
				self._set_status("Simplex conversion cancelled.")
				return

			simplex_commands.add_simplex_shapes_to_editor(
				editor=self.current_editor,
				blendshape_node=selection.get("blendshape_node"),
				controller=selection.get("controller"),
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
		if self._primary_tree_sort_column == 1:
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

	def _clear_shapes_filters(self, keep_selection: bool = False, rebuild_ui: bool = True) -> None:
		if not keep_selection:
			self.primaries_view.clearSelection()
		self.shapes_search.blockSignals(True)
		self.shapes_search.setText("")
		self.shapes_search.blockSignals(False)
		self._shapes_proxy.set_search_text("")
		self._shapes_proxy.set_selected_primaries(tuple())
		self._shapes_proxy.set_visible_names(None)
		self._active_shapes_proxy.set_search_text("")
		self._active_shapes_proxy.set_selected_primaries(tuple())
		self._active_shapes_proxy.set_visible_names(None)
		self._set_directional_shapes_filter_state(downstream_checked=False, upstream_checked=False)
		if rebuild_ui:
			self._apply_shapes_name_sort()
			self._rebuild_shapes_tree()
			self._update_delegate_name_columns()
			self._update_info_labels()
		if not keep_selection:
			self._set_status("Cleared all shapes filters.")

	def _on_primaries_search_changed(self, text: str) -> None:
		self._apply_primaries_tree_filter(text)
		self._update_delegate_name_columns()
		self._update_info_labels()

	def _on_shapes_search_changed(self, text: str) -> None:
		self._shapes_proxy.set_search_text(text)
		self._active_shapes_proxy.set_search_text(text)
		self._rebuild_shapes_tree()
		self._update_delegate_name_columns()
		self._update_info_labels()

	def _on_shape_model_data_changed(self, _top_left, _bottom_right, roles) -> None:
		"""Run expensive UI refreshes only when non-value data changed."""
		if self._syncing_shapes_tree:
			return
		self._sync_shapes_tree_items_from_source_rows(_top_left, _bottom_right)
		if roles and all(
			role in (ShapeItemsModel.ValueRole, Qt.DisplayRole, ShapeItemsModel.MutedRole, ShapeItemsModel.LockedRole)
			for role in roles
		):
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
		self._update_related_shape_highlights_from_selection()
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

	def _update_related_shape_highlights_from_selection(self) -> None:
		"""Highlight upstream/downstream rows related to current shapes selection."""
		if self.current_editor is None:
			self._shape_model.set_related_shape_names(tuple(), tuple())
			self.shapes_view.viewport().update()
			return

		selected_names = {str(name) for name in self._selected_shape_names_from_shapes_view() if name}
		if not selected_names:
			self._shape_model.set_related_shape_names(tuple(), tuple())
			self.shapes_view.viewport().update()
			return

		upstream_related_names: Set[str] = set()
		downstream_related_names: Set[str] = set()
		for shape_name in selected_names:
			try:
				upstream_names = self._get_cached_related_shape_names(shape_name, upstream=True)
				downstream_names = self._get_cached_related_shape_names(shape_name, upstream=False)
			except Exception:
				continue
			upstream_related_names.update(upstream_names)
			downstream_related_names.update(downstream_names)

		upstream_related_names.difference_update(selected_names)
		downstream_related_names.difference_update(selected_names)
		self._shape_model.set_related_shape_names(tuple(upstream_related_names), tuple(downstream_related_names))
		self.shapes_view.viewport().update()

	def _on_shapes_double_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
		"""Set clicked shape to its pose from the shapes tree."""
		if item is None or bool(item.data(0, ShapeItemsModel.IsHeaderRole)):
			return
		shape_name = str(item.data(0, ShapeItemsModel.NameRole) or "")
		if not shape_name:
			return
		self._set_shape_pose_by_name(shape_name)

	def _show_shapes_context_menu(self, pos) -> None:
		if self.current_editor is None:
			return
		selected_shapes = self._selected_shape_names_from_shapes_view()
		if not selected_shapes:
			return

		menu = QMenu(self.shapes_view)
		extract_action = menu.addAction("Extract Selected")
		reset_deltas_action = menu.addAction("Reset Deltas")
		if hasattr(menu, "exec"):
			selected_action = menu.exec(self.shapes_view.viewport().mapToGlobal(pos))
		else:
			selected_action = menu.exec_(self.shapes_view.viewport().mapToGlobal(pos))
		if selected_action == extract_action:
			self.extract_selected()
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
			self._reload_shapes_from_editor()
			self._set_status(f"Reset deltas for {len(selected_shapes)} shape(s).")

	def _on_shapes_item_expanded(self, item: QTreeWidgetItem) -> None:
		if item is None or not bool(item.data(0, ShapeItemsModel.IsHeaderRole)):
			return
		item.setData(0, ShapeItemsModel.HeaderCollapsedRole, False)
		self.shapes_view.viewport().update()

	def _on_shapes_item_collapsed(self, item: QTreeWidgetItem) -> None:
		if item is None or not bool(item.data(0, ShapeItemsModel.IsHeaderRole)):
			return
		item.setData(0, ShapeItemsModel.HeaderCollapsedRole, True)
		self.shapes_view.viewport().update()

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

	def _on_active_shapes_double_clicked(self, proxy_index: QModelIndex) -> None:
		self._set_shape_pose_from_proxy_index(self._active_shapes_proxy, proxy_index)

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
		for shape_name in self._shape_tree_items.keys():
			max_width = max(max_width, fm.horizontalAdvance(str(shape_name)))
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
		shapes_width = self._compute_tree_max_name_width(self.shapes_view)
		active_shapes_width = self._compute_filtered_max_name_width(self.active_shapes_view, self._active_shapes_proxy)
		primary_drop_width = self._compute_filtered_max_name_width(self.primary_drop_view, self._primary_subset_proxy)
		work_shapes_width = self._compute_filtered_max_name_width(self.work_shapes_view, self._work_shape_model)
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
			expanded_headers = {}
			expanded_type_groups = {}
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
					group_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
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
					current_group_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
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
					type_group_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
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
				):
					leaf.setData(0, role, self._shapes_proxy.data(proxy_index, role))
				leaf.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsDragEnabled)
				type_group_item.addChild(leaf)
				self._shape_tree_items[name] = leaf
				if name in selected_names:
					leaf.setSelected(True)
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

	def _update_work_shape_button_panel(self) -> None:
		has_editor = self.current_editor is not None and self.current_editor.work_blendshape is not None
		has_selection = bool(self._selected_work_shape_names())
		has_active_edit = bool(self._work_shape_model.edit_shape_name())
		self.work_add_button.setEnabled(has_editor)
		self.work_remove_button.setEnabled(has_editor and has_selection)
		self.work_paint_button.setEnabled(has_editor and has_selection)
		self.work_edit_mode_button.setEnabled(has_editor and (has_selection or has_active_edit))

	def _stop_active_blendshape_trackers(self) -> None:
		for tracker in (self.blendshape_tracker, self.work_blendshape_tracker):
			if tracker is not None:
				tracker.stop()

	def _start_active_blendshape_trackers(self) -> None:
		for tracker in (self.blendshape_tracker, self.work_blendshape_tracker):
			if tracker is not None:
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
		shape_name = self._first_selected_work_shape_name()
		if not shape_name:
			self._set_status("Select one work shape first.", warning=True)
			return
		try:
			target_id = self.current_editor.paint_work_blendshape_target(shape_name)
		except Exception as exc:
			self._set_status(f"Error entering paint mode: {exc}", error=True)
			return
		# self._work_shape_model.set_edit_shape(shape_name)
		# self._update_work_shape_button_panel()
		self._set_status(f"Paint mode on '{shape_name}' (target id {target_id}).")

	def _on_toggle_work_shape_edit_mode(self) -> None:
		if self.current_editor is None:
			self._set_status("No system selected.", warning=True)
			return
		if self.current_editor.work_blendshape is None:
			self._set_status("Work blendshape not found.", warning=True)
			return

		shape_name = self._first_selected_work_shape_name()
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
		self._begin_inline_workshape_rename(model_index)

	def _on_work_shape_drop_received(self, work_shape_name: str, source_shape_name: str) -> None:
		if self.current_editor is None:
			self._set_status("No system selected.", warning=True)
			return
		try:
			self._stop_active_blendshape_trackers()
			self.current_editor.connect_work_shape_to_shape(work_shape_name, source_shape_name)
		except Exception as exc:
			self._set_status(f"Error connecting work shape '{work_shape_name}': {exc}", error=True)
			return
		finally:
			self._start_active_blendshape_trackers()
		self._reload_work_shapes_from_editor()
		self._select_work_shape(work_shape_name)
		self._set_status(f"Connected work shape '{work_shape_name}' to '{source_shape_name}'.")

	def _on_work_shape_break_link_requested(self, work_shape_name: str) -> None:
		if self.current_editor is None:
			self._set_status("No system selected.", warning=True)
			return
		try:
			self._stop_active_blendshape_trackers()
			self.current_editor.disconnect_work_shape(work_shape_name)
		except Exception as exc:
			self._set_status(f"Error breaking link for '{work_shape_name}': {exc}", error=True)
			return
		finally:
			self._start_active_blendshape_trackers()
		self._reload_work_shapes_from_editor()
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
				value = float(item.data(1, Qt.UserRole) or 0.0)
				item.setData(1, Qt.UserRole, value)
				return value
			max_value = 0.0
			for i in range(item.childCount()):
				max_value = max(max_value, visit(item.child(i)))
			item.setData(1, Qt.UserRole, max_value)
			return max_value

		max_root = 0.0
		for i in range(self.primaries_view.topLevelItemCount()):
			max_root = max(max_root, visit(self.primaries_view.topLevelItem(i)))
		return max_root

	def _sort_primaries_tree(self) -> None:
		"""Sort primaries tree using header sort mode: name column or value column."""
		self._refresh_primary_folder_sort_values()
		column = self._primary_tree_sort_column
		order = self._primary_tree_sort_order
		self.primaries_view.header().setSortIndicator(column, order)

		# Use native sort APIs to keep per-item widgets (sliders) attached.
		self.primaries_view.sortItems(column, order)

		def sort_descendants(item: QTreeWidgetItem) -> None:
			item.sortChildren(column, order)
			for i in range(item.childCount()):
				sort_descendants(item.child(i))

		for i in range(self.primaries_view.topLevelItemCount()):
			sort_descendants(self.primaries_view.topLevelItem(i))

	def _on_primaries_header_clicked(self, section: int) -> None:
		"""Toggle primaries sort mode from tree header clicks.

		section 0: sort by primary/directory name
		section 1: sort by value (active primaries/folders first)
		"""
		if section not in (0, 1):
			return
		if self._primary_tree_sort_column == section:
			self._primary_tree_sort_order = Qt.DescendingOrder if self._primary_tree_sort_order == Qt.AscendingOrder else Qt.AscendingOrder
		else:
			self._primary_tree_sort_column = section
			self._primary_tree_sort_order = Qt.DescendingOrder if section == 1 else Qt.AscendingOrder
		self._sort_primaries_tree()

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
			if item.data(0, self.PRIMARY_TREE_NAME_ROLE):
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
		if self._primary_tree_sort_column == 1 and not self._primaries_drag_active:
			self._sort_primaries_tree()

	def _sync_primary_tree_slider(self, shape_name: str, value: float) -> None:
		"""Sync one primaries tree leaf value from tracker/model updates."""
		item = self._primary_tree_items.get(shape_name)
		if item is None:
			return
		target = max(0.0, min(1.0, float(value)))
		current = float(item.data(1, Qt.UserRole) or 0.0)
		if abs(current - target) <= 1e-6:
			return
		item.setData(1, Qt.UserRole, target)
		model = self.primaries_view.model()
		if model is not None:
			idx = self.primaries_view.indexFromItem(item, 1)
			if idx.isValid():
				model.dataChanged.emit(idx, idx, [Qt.UserRole, Qt.DisplayRole])

	def _rebuild_primaries_tree(self) -> None:
		"""Build primaries hierarchy from target directories, skipping shape envelope folders."""
		selected_names = {item.data(0, self.PRIMARY_TREE_NAME_ROLE) for item in self.primaries_view.selectedItems()}
		selected_names.discard(None)
		self.primaries_view.clear()
		self._primary_tree_items.clear()

		if self.current_editor is None:
			return

		primary_shapes = self.current_editor.get_primary_shapes().sort_for_display()
		primaries_target_dirs = self.current_editor.get_primaries_target_dirs() or {}
		dirs_by_name = {str(name): list(path or []) for name, path in primaries_target_dirs.items()}

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
					node = PrimaryTreeItem([dir_path[depth], ""])
					node.setData(0, self.PRIMARY_TREE_FOLDER_ROLE, True)
					node.setData(1, Qt.UserRole, 0.0)
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
				leaf = PrimaryTreeItem([shape_name, ""])
				leaf.setData(0, self.PRIMARY_TREE_NAME_ROLE, shape_name)
				value = self._get_primary_tree_value(shape_name)
				leaf.setData(1, Qt.UserRole, 0.0 if value is None else value)
				leaf.setFlags(leaf.flags() | Qt.ItemIsEditable | Qt.ItemIsDragEnabled)
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

	def _apply_primaries_tree_filter(self, text: str) -> None:
		"""Filter primaries tree while preserving parent groups for matching children."""
		query = (text or "").strip().lower()

		def visit(item: QTreeWidgetItem) -> bool:
			own_match = not query or query in item.text(0).lower()
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
		self.scene_editor_tracker = BlueSteelEditorsTracker(parent=self)
		self.scene_editor_tracker.sceneReset.connect(self._on_scene_reset)
		self.scene_editor_tracker.sceneOpened.connect(self._on_scene_opened)
		self.scene_editor_tracker.editorAdded.connect(self._on_editor_added)
		self.scene_editor_tracker.editorRemoved.connect(self._on_editor_removed)
		self.scene_editor_tracker.editorRenamed.connect(self._on_editor_renamed)
		self.scene_editor_tracker.frameChanged.connect(self._on_scene_frame_changed, Qt.QueuedConnection)

	def _clear_scene_editor_tracker(self) -> None:
		if isinstance(self.scene_editor_tracker, BlueSteelEditorsTracker):
			self.scene_editor_tracker.kill()
			self.scene_editor_tracker.deleteLater()
		self.scene_editor_tracker = None

	def _setup_blendshape_tracker(self) -> None:
		self._clear_blendshape_tracker()
		if self.current_editor is None:
			return
		self.blendshape_tracker = BlendShapeNodeTracker(self.current_editor.blendshape.name, parent=self)
		self.blendshape_tracker.shapeValueChanged.connect(self._on_shape_value_changed, Qt.QueuedConnection)
		self.blendshape_tracker.shapeAdded.connect(self._on_shape_structure_changed)
		self.blendshape_tracker.shapeRemoved.connect(self._on_shape_structure_changed)
		self.blendshape_tracker.shapeRenamed.connect(self._on_shape_renamed)
		self.blendshape_tracker.nodeDeleted.connect(self._on_blendshape_deleted)
		self.blendshape_tracker.start()

		if self.current_editor.work_blendshape is not None:
			self.work_blendshape_tracker = BlendShapeNodeTracker(self.current_editor.work_blendshape.name, parent=self)
			self.work_blendshape_tracker.shapeValueChanged.connect(self._on_work_shape_value_changed, Qt.QueuedConnection)
			self.work_blendshape_tracker.shapeAdded.connect(self._on_work_shape_structure_changed)
			self.work_blendshape_tracker.shapeRemoved.connect(self._on_work_shape_structure_changed)
			self.work_blendshape_tracker.shapeRenamed.connect(self._on_work_shape_structure_changed)
			self.work_blendshape_tracker.sculptTargetChanged.connect(self._on_work_sculpt_target_changed, Qt.QueuedConnection)
			self.work_blendshape_tracker.nodeDeleted.connect(self._on_work_blendshape_deleted)
			self.work_blendshape_tracker.start()

	def _clear_blendshape_tracker(self) -> None:
		if isinstance(self.blendshape_tracker, BlendShapeNodeTracker):
			self.blendshape_tracker.kill()
			self.blendshape_tracker.deleteLater()
		self.blendshape_tracker = None
		if isinstance(self.work_blendshape_tracker, BlendShapeNodeTracker):
			self.work_blendshape_tracker.kill()
			self.work_blendshape_tracker.deleteLater()
		self.work_blendshape_tracker = None

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
		selected_names = set()
		for item in self.primaries_view.selectedItems():
			shape_name = item.data(0, self.PRIMARY_TREE_NAME_ROLE)
			if shape_name:
				selected_names.add(shape_name)
		# Changing primary selection should remove directional (upstream/downstream) filters.
		self._shapes_proxy.set_visible_names(None)
		self._active_shapes_proxy.set_visible_names(None)
		self._set_directional_shapes_filter_state(downstream_checked=False, upstream_checked=False)
		self._shapes_proxy.set_selected_primaries(selected_names)
		self._rebuild_shapes_tree()
		self._update_delegate_name_columns()
		self._update_info_labels()

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
		self._reload_shapes_from_editor()

	def _on_work_shape_value_changed(self, shape_id: int, shape_name: str, value: float) -> None:
		del shape_id
		self._work_shape_model.set_value_local(shape_name, value)

	def _on_work_shape_structure_changed(self, *_args) -> None:
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

	def _on_shape_renamed(self, *_args) -> None:
		self._clear_related_shapes_cache()
		self._reload_shapes_from_editor()

	def _on_blendshape_deleted(self, blendshape_name: str) -> None:
		self.set_current_editor(None)
		self._set_status(f"Blendshape '{blendshape_name}' deleted.", warning=True)

	def _on_work_blendshape_deleted(self, blendshape_name: str) -> None:
		self.set_current_editor(None)
		self._set_status(f"Work blendshape '{blendshape_name}' deleted.", warning=True)

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
		if self.current_editor is None:
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
			self._update_related_shape_highlights_from_selection()
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

	def _update_window_title(self) -> None:
		editor_name = self.current_editor.name if self.current_editor is not None else ""
		title = f"Blue Steel v. {env.VERSION}"
		if editor_name:
			title = f"{title} - {editor_name}"
		self.setWindowTitle(title)

	def set_current_editor(self, name: Optional[str]) -> None:
		"""Set active editor by name.

		Example:
			>>> win.set_current_editor("myCharacter_blueSteel_container")
		"""
		self._clear_blendshape_tracker()

		if not name or not cmds.objExists(name):
			self.current_editor = None
			self._update_window_title()
			self._shape_model.rebuild_from_editor(None)
			self._rebuild_primaries_tree()
			self._rebuild_shapes_tree()
			self._update_delegate_name_columns()
			self._update_tools_button_panel()
			self._reload_editor_menu()
			self._set_status("No system selected.", warning=True)
			return

		try:
			self.current_editor = BlueSteelEditor(name)
			self._update_window_title()
			self._reload_shapes_from_editor()
			self._setup_blendshape_tracker()
			self._update_tools_button_panel()
			self._reload_editor_menu()
			self._set_status(f"Loaded system: {name}")
		except Exception as exc:
			self.current_editor = None
			self._update_window_title()
			self._shape_model.rebuild_from_editor(None)
			self._rebuild_primaries_tree()
			self._rebuild_shapes_tree()
			self._update_delegate_name_columns()
			self._update_tools_button_panel()
			self._reload_editor_menu()
			self._set_status(f"Failed loading system '{name}': {exc}", error=True)

	def refresh_ui(self) -> None:
		"""Refresh model and editor list while preserving current selection when possible."""
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
            f"Version: {env.VERSION}\n"
		)

	def closeEvent(self, event) -> None:  # noqa: N802
		self._clear_blendshape_tracker()
		self._clear_scene_editor_tracker()
		super().closeEvent(event)


def show() -> MainWindow:
	"""Show the rewritten Blue Steel editor window.

	Example:
		>>> win = show()
		>>> win.refresh_ui()
	"""
	global WINDOW
	try:
		if WINDOW is not None:
			WINDOW.close()
			WINDOW.deleteLater()
			WINDOW = None
	except Exception:
		WINDOW = None

	maya_main_window = get_maya_main_window()
	WINDOW = MainWindow(parent=maya_main_window)
	WINDOW.show()
	return WINDOW

