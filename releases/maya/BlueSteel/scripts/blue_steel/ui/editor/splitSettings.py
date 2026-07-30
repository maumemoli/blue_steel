"""Models and widgets used by the Blue Steel Split Settings tab.

The assignment model layers split-group state over the primary-only proxy from
the shared shape model. The assignment state is intentionally kept separate
from shape rows because it is persisted on the editor's split attribute group.
"""

from __future__ import annotations

from typing import Dict, List, Sequence

from ... import env

if env.MAYA_VERSION > 2024:
	from PySide6.QtCore import QAbstractProxyModel, QModelIndex, QPersistentModelIndex, QItemSelectionModel, Qt, QTimer, Signal
	from PySide6.QtWidgets import QAbstractItemView, QComboBox, QStyledItemDelegate, QTableView
else:
	from PySide2.QtCore import QAbstractProxyModel, QModelIndex, QPersistentModelIndex, QItemSelectionModel, Qt, QTimer, Signal
	from PySide2.QtWidgets import QAbstractItemView, QComboBox, QStyledItemDelegate, QTableView


# This matches ShapeItemsModel.NameRole without importing mainWindow.py.
PRIMARY_NAME_ROLE = Qt.UserRole + 1
PRIMARY_TYPE_ROLE = Qt.UserRole + 2


class SplitPrimaryAssignmentsModel(QAbstractProxyModel):
	"""Expose primary rows with a second column for split-group assignment."""

	GroupRole = Qt.UserRole + 906
	assignmentCommitted = Signal(str, object)

	def __init__(self, parent=None) -> None:
		super().__init__(parent)
		self._group_names: List[str] = ["NoSplit"]
		self._assignments: Dict[str, str] = {}

	def setSourceModel(self, source_model) -> None:  # noqa: N802
		old_model = self.sourceModel()
		if old_model is not None:
			try:
				old_model.modelAboutToBeReset.disconnect(self.beginResetModel)
				old_model.modelReset.disconnect(self.endResetModel)
				old_model.dataChanged.disconnect(self._on_source_data_changed)
			except Exception:
				pass
		self.beginResetModel()
		super().setSourceModel(source_model)
		self.endResetModel()
		if source_model is not None:
			source_model.modelAboutToBeReset.connect(self.beginResetModel)
			source_model.modelReset.connect(self.endResetModel)
			source_model.dataChanged.connect(self._on_source_data_changed)

	def _on_source_data_changed(self, top_left, bottom_right, roles) -> None:
		if self.rowCount() <= 0:
			return
		first_row = max(0, top_left.row())
		last_row = min(self.rowCount() - 1, bottom_right.row())
		self.dataChanged.emit(self.index(first_row, 0), self.index(last_row, 0), roles)

	def set_assignments(self, group_names: Sequence[str], assignments: Dict[str, str]) -> None:
		self.beginResetModel()
		self._group_names = ["NoSplit"] + [str(name) for name in group_names]
		self._assignments = {
			str(name): str(group) if str(group) in self._group_names else "NoSplit"
			for name, group in assignments.items()
		}
		self.endResetModel()

	def set_search_text(self, text: str) -> None:
		if self.sourceModel() is None:
			return
		self.beginResetModel()
		self.sourceModel().set_search_text(text)
		self.endResetModel()

	def primary_names(self) -> List[str]:
		"""Return all primary names, independent of the split-settings filter."""
		primary_proxy = self.sourceModel()
		shape_model = primary_proxy.sourceModel() if primary_proxy is not None else None
		if shape_model is None:
			return []

		return [
			str(shape_model.data(shape_model.index(row, 0), PRIMARY_NAME_ROLE) or "")
			for row in range(shape_model.rowCount())
			if shape_model.data(shape_model.index(row, 0), PRIMARY_TYPE_ROLE) == "PrimaryShape"
		]

	def group_names(self) -> List[str]:
		return list(self._group_names)

	def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
		if parent.isValid() or self.sourceModel() is None:
			return 0
		return self.sourceModel().rowCount()

	def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
		return 0 if parent.isValid() else 2

	def index(self, row: int, column: int, parent: QModelIndex = QModelIndex()) -> QModelIndex:
		if parent.isValid() or not (0 <= row < self.rowCount()) or not (0 <= column < 2):
			return QModelIndex()
		return self.createIndex(row, column)

	def parent(self, _index: QModelIndex = QModelIndex()) -> QModelIndex:
		return QModelIndex()

	def mapToSource(self, proxy_index: QModelIndex) -> QModelIndex:  # noqa: N802
		if not proxy_index.isValid() or self.sourceModel() is None:
			return QModelIndex()
		return self.sourceModel().index(proxy_index.row(), 0)

	def mapFromSource(self, source_index: QModelIndex) -> QModelIndex:  # noqa: N802
		if not source_index.isValid() or source_index.model() is not self.sourceModel():
			return QModelIndex()
		return self.index(source_index.row(), 0)

	def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
		if not index.isValid():
			return None
		source_index = self.mapToSource(index)
		if index.column() == 0:
			return self.sourceModel().data(source_index, role)
		if role == PRIMARY_NAME_ROLE:
			return self.sourceModel().data(source_index, PRIMARY_NAME_ROLE)
		if role in (Qt.DisplayRole, Qt.EditRole, self.GroupRole):
			primary_name = str(self.sourceModel().data(source_index, PRIMARY_NAME_ROLE) or "")
			return self._assignments.get(primary_name, "NoSplit")
		return None

	def setData(self, index: QModelIndex, value, role: int = Qt.EditRole) -> bool:  # noqa: N802
		if not index.isValid():
			return False
		if index.column() == 0:
			return self.sourceModel().setData(self.mapToSource(index), value, role)
		if role != Qt.EditRole:
			return False
		group_name = str(value)
		if group_name not in self._group_names:
			return False
		primary_name = str(self.data(index, PRIMARY_NAME_ROLE) or "")
		return self.set_assignment_targets(group_name, [primary_name])

	def set_assignment_targets(self, group_name: str, primary_names: Sequence[str]) -> bool:
		if group_name not in self._group_names:
			return False
		target_names = list(dict.fromkeys(str(name) for name in primary_names if name))
		changed_names = [
			name for name in target_names
			if self._assignments.get(name, "NoSplit") != group_name
		]
		if not changed_names:
			return False

		changed_name_set = set(changed_names)
		for name in changed_names:
			self._assignments[name] = group_name
		for row in range(self.rowCount()):
			index = self.index(row, 1)
			if str(self.data(index, PRIMARY_NAME_ROLE) or "") in changed_name_set:
				self.dataChanged.emit(index, index, [Qt.DisplayRole, Qt.EditRole, self.GroupRole])
		self.assignmentCommitted.emit(group_name, changed_names)
		return True

	def flags(self, index: QModelIndex):
		if not index.isValid():
			return Qt.NoItemFlags
		if index.column() == 0:
			return self.sourceModel().flags(self.mapToSource(index))
		return Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsEditable

	def headerData(self, section: int, orientation, role: int = Qt.DisplayRole):  # noqa: N802
		if orientation == Qt.Horizontal and role == Qt.DisplayRole:
			return "Primary" if section == 0 else "Split Group"
		return None


class SplitPrimaryAssignmentsView(QTableView):
	"""Primary slider table with one persistent split-group chooser per row."""

	_primary_slider_layout = True

	def assignment_targets(self, clicked_index: QModelIndex) -> List[str]:
		clicked_name = str(clicked_index.data(PRIMARY_NAME_ROLE) or "")
		selection_model = self.selectionModel()
		if selection_model is None:
			return [clicked_name] if clicked_name else []
		selected_names = [
			str(index.data(PRIMARY_NAME_ROLE) or "")
			for index in selection_model.selectedRows(0)
		]
		selected_names = [name for name in selected_names if name]
		if clicked_name in selected_names:
			return selected_names
		return [clicked_name] if clicked_name else []

	def restore_assignment_selection(self, primary_names: Sequence[str]) -> None:
		selection_model = self.selectionModel()
		if selection_model is None:
			return
		target_names = {str(name) for name in primary_names}
		selection_model.clearSelection()
		for row in range(self.model().rowCount()):
			index = self.model().index(row, 0)
			if str(index.data(PRIMARY_NAME_ROLE) or "") in target_names:
				selection_model.select(index, QItemSelectionModel.Select | QItemSelectionModel.Rows)

	def mouseMoveEvent(self, event):  # noqa: N802
		delegate = self.itemDelegateForColumn(0)
		if getattr(delegate, "is_drag_active", lambda: False)() and delegate.external_drag_move(event.pos().x()):
			event.accept()
			return
		super().mouseMoveEvent(event)

	def mouseReleaseEvent(self, event):  # noqa: N802
		delegate = self.itemDelegateForColumn(0)
		if event.button() == Qt.MiddleButton and getattr(delegate, "is_drag_active", lambda: False)() and delegate.external_drag_end(event.pos().x()):
			event.accept()
			return
		super().mouseReleaseEvent(event)


class SplitPrimaryGroupCombo(QComboBox):
	"""Compact persistent combo that keeps the table's batch selection intact."""

	def __init__(self, view: SplitPrimaryAssignmentsView, model_index: QModelIndex, parent=None) -> None:
		super().__init__(parent)
		self._view = view
		self._model_index = QPersistentModelIndex(model_index)
		self.assignment_targets: List[str] = []
		self.setFocusPolicy(Qt.NoFocus)
		self.setFixedHeight(18)
		self.setContentsMargins(0, 0, 0, 0)
		self.setStyleSheet("QComboBox { margin: 0px; padding: 0px 4px; }")

	def _capture_assignment_targets(self) -> None:
		if self._model_index.isValid():
			self.assignment_targets = self._view.assignment_targets(self._model_index)

	def _restore_assignment_targets(self) -> None:
		if self.assignment_targets:
			self._view.restore_assignment_selection(self.assignment_targets)

	def enterEvent(self, event) -> None:  # noqa: N802
		self._capture_assignment_targets()
		super().enterEvent(event)

	def mousePressEvent(self, event) -> None:  # noqa: N802
		if not self.assignment_targets:
			self._capture_assignment_targets()
		super().mousePressEvent(event)

	def hidePopup(self) -> None:  # noqa: N802
		super().hidePopup()
		QTimer.singleShot(0, self._restore_assignment_targets)


class SplitPrimaryGroupDelegate(QStyledItemDelegate):
	"""Persistent split-group combo editor for assignment rows."""

	def createEditor(self, parent, option, index):  # noqa: N802
		if index.column() != 1:
			return None
		editor = SplitPrimaryGroupCombo(self.parent(), index, parent)
		editor.addItems(index.model().group_names())
		editor.activated.connect(lambda _index, combo=editor: self.commitData.emit(combo))
		return editor

	def setEditorData(self, editor, index) -> None:  # noqa: N802
		editor.setCurrentText(str(index.data(Qt.EditRole) or "NoSplit"))

	def setModelData(self, editor, model, index) -> None:  # noqa: N802
		targets = editor.assignment_targets or [str(index.data(PRIMARY_NAME_ROLE) or "")]
		model.set_assignment_targets(editor.currentText(), targets)