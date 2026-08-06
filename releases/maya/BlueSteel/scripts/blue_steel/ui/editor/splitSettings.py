"""Grouped primary-assignment tree used by the Split Settings tab."""

from __future__ import annotations

from typing import Dict, List, Sequence

from ... import env

if env.MAYA_VERSION > 2024:
	from PySide6.QtCore import QMimeData, Qt, Signal
	from PySide6.QtGui import QDrag
	from PySide6.QtWidgets import QAbstractItemView, QTreeWidget, QTreeWidgetItem
else:
	from PySide2.QtCore import QMimeData, Qt, Signal
	from PySide2.QtGui import QDrag
	from PySide2.QtWidgets import QAbstractItemView, QTreeWidget, QTreeWidgetItem


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


class SplitPrimaryAssignmentsView(QTreeWidget):
	"""Group primaries by split assignment and reassign them with drag and drop."""

	assignmentChanged = Signal(str, object)
	_primary_tree_layout = True
	_primary_slider_layout = False
	_uses_native_branch_indicator = True

	def __init__(self, parent=None) -> None:
		super().__init__(parent)
		self._source_model = None
		self._assignments: Dict[str, str] = {}
		self._search_text = ""
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
		finally:
			self.blockSignals(False)
		self.set_search_text(self._search_text)

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

	def set_search_text(self, text: str) -> None:
		self._search_text = (text or "").strip().lower()
		for row in range(self.topLevelItemCount()):
			group_item = self.topLevelItem(row)
			visible_children = 0
			for child_row in range(group_item.childCount()):
				child = group_item.child(child_row)
				visible = not self._search_text or self._search_text in str(child.data(0, PRIMARY_NAME_ROLE) or "").lower()
				child.setHidden(not visible)
				visible_children += int(visible)
			group_item.setHidden(bool(self._search_text) and visible_children == 0)

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
			index = self.indexAt(event.pos())
			item = self.itemAt(event.pos())
			if item is not None and item.parent() is not None and item.isSelected():
				self._pressed_primary_names = [
					str(selected.data(0, PRIMARY_NAME_ROLE) or "")
					for selected in self.selectedItems()
					if selected.parent() is not None and selected.data(0, PRIMARY_NAME_ROLE)
				]
			delegate = self.itemDelegateForColumn(0)
			if (
				index.isValid()
				and item is not None
				and item.parent() is not None
				and bool(index.data(PRIMARY_EDITABLE_ROLE))
				and getattr(delegate, "external_drag_start", lambda *_args: False)(
					self.model(), index, event.pos(), self.visualRect(index)
				)
			):
				event.accept()
				return
		super().mousePressEvent(event)

	def mouseMoveEvent(self, event):  # noqa: N802
		delegate = self.itemDelegateForColumn(0)
		if getattr(delegate, "is_drag_active", lambda: False)() and delegate.external_drag_move(event.pos().x()):
			event.accept()
			return
		super().mouseMoveEvent(event)

	def mouseReleaseEvent(self, event):  # noqa: N802
		delegate = self.itemDelegateForColumn(0)
		if event.button() == Qt.LeftButton and getattr(delegate, "is_drag_active", lambda: False)() and delegate.external_drag_end(event.pos().x()):
			event.accept()
			return
		super().mouseReleaseEvent(event)