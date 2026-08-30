"""Blue Steel editor main window.

This module contains the :class:`MainWindow` dockable editor and the ``show``
entry point. Models, delegates, views, and standalone widgets have been moved
to the sibling modules in this package.

Example:
    >>> from blue_steel.ui.editor import main_window
    >>> win = main_window.show()
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
from .main_window_helpers import MainWindowMixin, target_shape_names
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




class EditorSessionMixin(MainWindowMixin):
    def _clear_trackers_for_scene_operation(self) -> None:
        """Temporarily stop trackers before scene-wide operations."""
        self._clear_scene_editor_tracker()
        self._clear_blendshape_tracker()


    def _restart_trackers_after_scene_operation(self) -> None:
        """Restore trackers after scene-wide operations."""
        self._setup_scene_editor_tracker()
        if self.current_editor is not None:
            self._setup_blendshape_tracker()


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
        if hasattr(self.scene_editor_tracker, "get_editor_names"):
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


