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




class WorkShapesFeatureMixin(MainWindowMixin):
    def _selected_work_shape_names(self) -> List[str]:
        return self._selected_names_from_list_view(self.work_shapes_view, self._work_shape_model)


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


    def _on_work_shape_value_changed(self, shape_id: int, shape_name: str, value: float) -> None:
        del shape_id
        self._work_shape_model.set_value_local(shape_name, value)


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


    def _on_work_shapes_mute_toggle_requested(self, shape_name: str, state: bool) -> None:
        """Handle work-shape delegate mute icon clicks with shapes-panel semantics."""
        if self.current_editor is None:
            return

        target_names = target_shape_names(shape_name, self._selected_work_shape_names())

        try:
            if self.work_blendshape_tracker is not None:
                self.work_blendshape_tracker.stop()
            for target_name in target_names:
                self.current_editor.set_work_shape_mute_state(target_name, bool(state))
                self._work_shape_model.set_muted_state_local(target_name, bool(state))
            if len(target_names) == 1:
                self._set_status(f"{'Muted' if state else 'Unmuted'} work shape '{target_names[0]}'.")
            else:
                self._set_status(f"{'Muted' if state else 'Unmuted'} {len(target_names)} selected work shape(s).")
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
        


    def _on_work_blendshape_deleted(self, blendshape_name: str) -> None:
        self.set_current_editor(None)
        self._set_status(f"Work blendshape '{blendshape_name}' deleted.", warning=True)

