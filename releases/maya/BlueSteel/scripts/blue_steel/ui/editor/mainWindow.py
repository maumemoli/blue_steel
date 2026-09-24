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

from typing import Dict, List, Optional, Set
import sys
import traceback

from maya import cmds
from maya.app.general.mayaMixin import MayaQWidgetDockableMixin

from ...api.editor import BlueSteelEditor
from ...api.trackers import BlueSteelEditorsTracker, BlendShapeNodeTracker, ControllerTracker
from ..common.frameLayout import FrameLayout
from .controllerLayoutWindow import ControllerLayoutWindow
from .delegates import SliderItemDelegate, SplitMapWeightSliderDelegate
from .models import (
    PrimaryShapesProxyModel,
    PrimarySubsetProxyModel,
    ShapeItemsModel,
    ShapesFilterProxyModel,
    WorkShapeItemsModel,
)
from .qt import (
    QAction,
    QGroupBox,
    QHBoxLayout,
    QIcon,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QSize,
    QSplitter,
    QStyle,
    QTabWidget,
    QTimer,
    QTreeWidgetItem,
    QWidget,
    Qt,
    get_maya_main_window,
)
from .views import (
    SplitMapWeightsList,
    SplitPrimaryAssignmentsView,
)
from .widgets import (
    SplitGroupsTree,
    SplitMapsTree,
    TokenSearchBar,
)

from .editorOpsMixin import EditorOpsMixin
from .editorSessionMixin import EditorSessionMixin
from .shapesFeatureMixin import ShapesFeatureMixin
from .splitSettingsUiMixin import SplitSettingsUiMixin
from .editorUiMixin import EditorUiMixin
from .workShapesFeatureMixin import WorkShapesFeatureMixin

WINDOW = None
SHOW_UPDATE_CHECK = True


class MainWindow(
    MayaQWidgetDockableMixin,
    QMainWindow,
    EditorUiMixin,
    SplitSettingsUiMixin,
    EditorSessionMixin,
    ShapesFeatureMixin,
    WorkShapesFeatureMixin,
    EditorOpsMixin,
):
    OBJECT_NAME = "BlueSteelEditor"
    WORKSPACE_CONTROL_NAME = f"{OBJECT_NAME}WorkspaceControl"
    DOCK_TARGET_CONTROL = "Outliner"
    EMPTY_SYSTEM_LABEL = "<Select System>"
    SPLIT_PANELS_MAX_WIDTH = 600
    COMPACT_MARGIN = 2
    COMPACT_SPACING = 2

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
        self._primary_drop_tree_items: Dict[str, QTreeWidgetItem] = {}
        self._shape_tree_items: Dict[str, QTreeWidgetItem] = {}
        self._syncing_primaries_tree = False
        self._syncing_primary_drop_tree = False
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

        self.destroyed.connect(self._on_window_destroyed)

        self._build_ui()
        self._connect_ui_signals()
        self._setup_scene_editor_tracker()
        self._reload_editor_menu()
        self._select_first_available_editor()
        self._update_window_title()


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


    def show(self, *args, **kwargs):
        """Show the window and sync the dock toggle button with the actual state."""
        result = super().show(*args, **kwargs)
        self._refresh_dock_button_state()
        return result


    def dockCloseEventTriggered(self) -> None:  # noqa: N802
        """Handle closing the dockable workspace control.

        Maya invokes this (via
        ``maya.app.general.mayaMixin.workspaceControlClosed``) instead of Qt's
        ``closeEvent`` whenever the Blue Steel workspace control is closed,
        including the dock tab close button, the floating window close button
        and the in-app "X" button. ``MayaQWidgetDockableMixin`` defines an
        empty stub here and precedes the feature mixins in the MRO, so the
        override must live on ``MainWindow`` itself.

        Returns:
            None
        """
        self._shutdown_window()


def _build_dismissible_status_widget(status_label: QLabel) -> QWidget:
    """Wrap a status label with a circular close button.

    The returned widget is a horizontal container holding ``status_label``
    followed by a small black circular button showing the standard Qt close
    cross. Clicking the button hides the notification. The circle is sized 10%
    larger than the label text height so its glyph and the text stay visually
    balanced.

    Args:
        status_label (QLabel): The update notification label to make dismissible.

    Returns:
        QWidget: A container with the label and its close button.

    Example:
        >>> container = _build_dismissible_status_widget(QLabel("Update available"))
    """
    diameter = max(1, round(status_label.fontMetrics().height() * 1.1))

    close_button = QPushButton(status_label)
    close_button.setFixedSize(diameter, diameter)
    close_button.setIconSize(QSize(diameter, diameter))
    close_button.setCursor(Qt.PointingHandCursor)
    close_button.setToolTip("Dismiss")
    close_button.setIcon(status_label.style().standardIcon(QStyle.SP_TitleBarCloseButton))
    close_button.setStyleSheet(
        "QPushButton { background-color: black; border: none;"
        f" border-radius: {diameter // 2}px; padding: 0px; }}"
        "QPushButton:hover { background-color: #333333; }"
    )

    container = QWidget(status_label.parentWidget())
    layout = QHBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(4)
    layout.addWidget(status_label)
    layout.addWidget(close_button, 0, Qt.AlignVCenter)

    close_button.clicked.connect(container.hide)
    return container


def show() -> MainWindow:
    """Show the rewritten Blue Steel editor window.

    Example:
        >>> win = show()
        >>> win.refresh_ui()
    """
    print("Opening Blue Steel editor...")
    global WINDOW
    global SHOW_UPDATE_CHECK

    # Resolve any window that we still need to shut down, including one that
    # survived a module reload (the mayaMixin keeps a reference to every
    # workspace control it created, so it may be alive without ``WINDOW``).
    existing = WINDOW
    if existing is None:
        try:
            from maya.app.general.mayaMixin import mixinWorkspaceControls
            existing = mixinWorkspaceControls.get(MainWindow.WORKSPACE_CONTROL_NAME)
        except Exception:
            existing = None
    if existing is not None:
        try:
            existing._shutdown_window()
        except Exception:
            pass
        try:
            existing.close()
        except Exception:
            pass
        try:
            existing.deleteLater()
        except Exception:
            pass
    WINDOW = None
    if cmds.workspaceControl(MainWindow.WORKSPACE_CONTROL_NAME, query=True, exists=True):
        cmds.deleteUI(MainWindow.WORKSPACE_CONTROL_NAME, control=True)

    maya_main_window = get_maya_main_window()
    from ... import __update_url__, __latest_version__, __version__

    status_label = None
    update_url = __update_url__
    if __latest_version__ is None:
        status_label = QLabel(
            f'Unable to determine the latest version. '
            f'<a href="{update_url}" style="color: #e7b45a;"><strong>Check For Updates</strong></a>'
        )
    elif __version__  < __latest_version__:
        
        status_label = QLabel(
            f'Update available: v.{__latest_version__} Download '
            f'<a href="{update_url}" style="color: #e7b45a;"><strong>Here</strong></a>'
        )
        status_label.setStyleSheet("color: #e7b45a;")
        status_label.setOpenExternalLinks(True)
    else:
        status_label = QLabel(
            f'Blue Steel is up to date.'
        )
    
    WINDOW = MainWindow(parent=maya_main_window, version=__version__)
    WINDOW.resize(1200, max(720, WINDOW.sizeHint().height()))
    WINDOW.show(dockable=True, area="right", floating=True)
    if status_label is not None:
        WINDOW.status_bar.addPermanentWidget(_build_dismissible_status_widget(status_label))

    return WINDOW

