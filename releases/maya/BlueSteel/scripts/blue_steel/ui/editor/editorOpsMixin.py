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




class EditorOpsMixin(MainWindowMixin):
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
        import_split_data_action = QAction("Import Split Data", self)
        import_split_data_action.triggered.connect(self._import_split_data)
        import_menu.addAction(import_split_data_action)


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
        export_split_data_action = QAction("Export Split Data", self)
        export_split_data_action.triggered.connect(self._export_split_data)
        export_menu.addAction(export_split_data_action)

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
        conversion_cleanup_menu .addAction(self.prepare_for_publishing_action)

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

        if hasattr(self.scene_editor_tracker, "register_scene_editor_nodes"):
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


    def show_about(self) -> None:
        QMessageBox.about(
            self, "About",
            "Blues Steel\n\n"
            "A really, really, ridiculously good-looking\n blendshape manager for Maya\n by Maurizio Memoli\n\n"
            f"Version: {self.version}\n"
        )

