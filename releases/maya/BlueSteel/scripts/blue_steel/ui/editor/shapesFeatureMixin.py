"""Blue Steel editor main window.

This module contains the :class:`MainWindow` dockable editor and the ``show``
entry point. Models, delegates, views, and standalone widgets have been moved
to the sibling modules in this package.

Example:
    >>> from blue_steel.ui.editor import mainWindow
    >>> win = mainWindow.show()
    >>> win.set_current_editor("characterA_blueSteel_container")
"""

from __future__ import annotations

from typing import Callable, Dict, List, Optional, Sequence, Set
import os
import sys
import traceback

from maya import cmds
from maya.app.general.mayaMixin import MayaQWidgetDockableMixin

from ... import env
from ...api.editor import BlueSteelEditor
from ...api.mayaUtils import undoable
from ...api.trackers import BlueSteelEditorsTracker, BlendShapeNodeTracker, ControllerTracker
from ...converters.simplex.ui.dialog import show_simplex_converter_dialog
from ...converters.simplex import commands as simplex_commands
from ...mmtools import ui
from ..common.frameLayout import FrameLayout
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
    SPLIT_ICON,
)
from .constants import (
    PRIMARY_TREE_FOLDER_ROLE,
    PRIMARY_TREE_NAME_ROLE,
    PRIMARY_TREE_SORT_VALUE_ROLE,
    SHAPE_CUSTOM_COLORS,
    TYPE_GROUP_ORDER,
    shape_type_group_name,
)
from .mainWindowMixin import MainWindowMixin, target_shape_names
from .controllerLayoutWindow import ControllerLayoutWindow
from .delegates import SliderItemDelegate, SplitMapWeightSliderDelegate
from .models import (
    PrimaryShapesProxyModel,
    PrimarySubsetProxyModel,
    ShapeItemsModel,
    ShapesFilterProxyModel,
    WorkShapeItemsModel,
    normalized_search_terms,
)
from .qt import (
    QAbstractItemView,
    QAction,
    QActionGroup,
    QAbstractListModel,
    QCheckBox,
    QColor,
    QComboBox,
    QCursor,
    QDialog,
    QDialogButtonBox,
    QDoubleValidator,
    QDrag,
    QEvent,
    QFileDialog,
    QGroupBox,
    QGuiApplication,
    QHBoxLayout,
    QHeaderView,
    QIcon,
    QInputDialog,
    QItemSelectionModel,
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
    QMimeData,
    QModelIndex,
    QPainter,
    QPalette,
    QPersistentModelIndex,
    QPixmap,
    QPoint,
    QPolygon,
    QPushButton,
    QRect,
    QSize,
    QSizePolicy,
    QSortFilterProxyModel,
    QSplitter,
    QStatusBar,
    QStyle,
    QStyledItemDelegate,
    QTabWidget,
    QTimer,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
    Qt,
    Signal,
    color_swatch_icon,
    get_maya_main_window,
    shape_custom_color_to_qcolor,
)
from .views import (
    PrimaryDropListView,
    PrimaryTreeItem,
    PrimaryTreeWidget,
    ShapeTreeWidget,
    SliderListView,
    SplitMapWeightsList,
    SplitPrimaryAssignmentsView,
    WorkShapesListView,
)
from .widgets import (
    InlineWorkshapeRenameEditor,
    SplitGroupsTree,
    SplitMapStatusDelegate,
    SplitMapsTree,
    TokenSearchBar,
)




class ShapesFeatureMixin(MainWindowMixin):
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
            if self._shapes_proxy.is_with_value_shape(self._shape_model, index):
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
        
        set_color_menu = menu.addMenu("Set Color")
        color_actions = {}
        for color_name, color_hex in SHAPE_CUSTOM_COLORS.items():
            color_action = set_color_menu.addAction(color_swatch_icon(color_hex), color_name)
            color_actions[color_action] = color_hex
        set_color_menu.addSeparator()
        clear_color_action = set_color_menu.addAction("Clear")
        menu.addSeparator()
        reset_deltas_action = menu.addAction("Reset Deltas")
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

            type_group_order = TYPE_GROUP_ORDER

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
                type_group_name = shape_type_group_name(shape_type)
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
            shape_name = item.data(0, PRIMARY_TREE_NAME_ROLE)
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


    def _selected_active_shape_names(self) -> List[str]:
        return self._selected_names_from_list_view(self.active_shapes_view, self._active_shapes_proxy)


    def _selected_primary_drop_shape_names(self) -> List[str]:
        return self._selected_names_from_list_view(self.primary_drop_view, self._primary_subset_proxy)


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


    def _refresh_primary_folder_sort_values(self) -> float:
        """Update per-item numeric sort value (leaf=slider value, folder=max descendant)."""
        def visit(item: QTreeWidgetItem) -> float:
            shape_name = item.data(0, PRIMARY_TREE_NAME_ROLE)
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
        selected_names = {item.data(0, PRIMARY_TREE_NAME_ROLE) for item in self.primaries_view.selectedItems()}
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
                        node.setData(0, PRIMARY_TREE_FOLDER_ROLE, True)
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
                    leaf.setData(0, PRIMARY_TREE_NAME_ROLE, shape_name)
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
                    leaf.setData(0, ShapeItemsModel.ColorRole, shape_custom_color_to_qcolor(custom_color))
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
        search_terms = normalized_search_terms(terms)

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


    def _on_primaries_selection_changed(self, *_args) -> None:
        self._set_shapes_value_filter_button_state(False)
        selected_names = []
        for item in self.primaries_view.selectedItems():
            shape_name = item.data(0, PRIMARY_TREE_NAME_ROLE)
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
        target_names = target_shape_names(shape_name, selected_shape_names)

        try:
            if self.blendshape_tracker is not None:
                self.blendshape_tracker.stop()
            for target_name in target_names:
                self.current_editor.set_shape_mute_state(target_name, bool(state))
                self._shape_model.set_shape_muted_state_local(target_name, bool(state))
            if len(target_names) == 1:
                self._set_status(f"{'Muted' if state else 'Unmuted'} shape '{target_names[0]}'.")
            else:
                self._set_status(f"{'Muted' if state else 'Unmuted'} {len(target_names)} selected shape(s).")
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
        target_names = target_shape_names(shape_name, selected_shape_names)

        if getattr(self.current_editor, "locked_shapes", None) is None:
            self.current_editor.locked_shapes = set()

        updated_target_names: List[str] = []
        for target_name in target_names:
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


    def _on_shape_renamed(self, *_args) -> None:
        self._clear_related_shapes_cache()
        if self.current_editor is not None:
            self.current_editor.blendshape.invalidate_weights_cache()
        self._reload_shapes_from_editor()


    def _on_blendshape_deleted(self, blendshape_name: str) -> None:
        self.set_current_editor(None)
        self._set_status(f"Blendshape '{blendshape_name}' deleted.", warning=True)


    def _update_info_labels(self) -> None:
        total_primaries = sum(1 for _ in self._iter_primary_tree_leaves())
        selected_primaries = sum(
            1
            for item in self.primaries_view.selectedItems()
            if item.data(0, PRIMARY_TREE_NAME_ROLE)
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

