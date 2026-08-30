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




class SplitSettingsUiMixin(MainWindowMixin):
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
        self.split_group_preview_label = QLabel("<i>Select a split group to preview its maps.</i>")
        self.split_group_preview_label.setWordWrap(True)
        self.split_group_preview_label.setMinimumWidth(0)
        self.split_groups_frame_layout.addWidget(self.split_group_preview_label)
        split_groups_splitter.addWidget(split_groups_tree_widget)
        self.split_groups_frame_layout.collapse()

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

        self.create_split_editor_button = QPushButton("Create Split Editor")
        self.create_split_editor_button.setIcon(SPLIT_ICON)
        self.create_split_editor_button.setToolTip("Create a new split editor")
        split_maps_layout.addWidget(self.create_split_editor_button)

        split_settings_splitter.addWidget(right_column)
        split_settings_splitter.setStretchFactor(0, 1)
        split_settings_splitter.setStretchFactor(1, 1)
        split_settings_splitter.setSizes([500, 500])


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


    def _on_split_map_edit_weight_value_changed(self, _shape_id: int, _shape_name: str, _value: float) -> None:
        if self._is_split_tab_active():
            self._sync_split_map_weight_slider_values()


    def _on_split_map_edit_structure_changed(self, *_args) -> None:
        if self._is_split_tab_active():
            self._refresh_split_map_weights()
        else:
            self._split_settings_refresh_pending = True


    def _on_split_map_edit_blendshape_deleted(self, blendshape_name: str) -> None:
        self._clear_split_map_edit_blendshape_tracker()
        self._refresh_split_map_weights()
        self._set_status(f"Split-map edit blendshape '{blendshape_name}' deleted.", warning=True)

