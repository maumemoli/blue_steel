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




class EditorUiMixin(MainWindowMixin):
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
        if item.data(0, PRIMARY_TREE_NAME_ROLE):
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
        primary_name = item.data(0, PRIMARY_TREE_NAME_ROLE)
        if not primary_name:
            return
        self._set_shape_pose_by_name(str(primary_name))


    def _show_primaries_context_menu(self, pos) -> None:
        if self.current_editor is None:
            return
        item = self.primaries_view.itemAt(pos)
        if item is None:
            return

        primary_name = item.data(0, PRIMARY_TREE_NAME_ROLE)
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
        shape_name = item.data(0, PRIMARY_TREE_NAME_ROLE)
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
            self.create_split_editor_button.clicked.connect(self._on_create_split_shapes_editor_requested)
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
        # tab_name = self.main_tabs.tabText(index)
        is_split_tab = self._is_split_tab_active()
        self._sync_split_map_edit_mesh_visibility(is_split_tab)
        if is_split_tab:
            # we need to update the split primaries values
            self._refresh_split_primary_assignments()
            if self._split_settings_refresh_pending:
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

