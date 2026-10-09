"""Focused Work Shapes UI tests, runnable without Maya.

Run: python releases/maya/BlueSteel/unittest/workShapesUiUt.py
Requires PySide6 (or PySide2). Real UI modules/Qt widgets are loaded in an
isolated package; only Maya, editor API, and icon dependencies are stubbed.

The Work Shapes panel is an item-based ``QTreeWidget`` (see
``WorkShapesListView``): work shapes are tree items carrying the work-shape
roles, and drivers are painted child rows handled by ``WorkShapeItemDelegate``.
These tests build the tree directly from a fake editor so the view/delegate
behavior can be exercised without the full main-window bootstrap.
"""
from __future__ import annotations

import ast
import importlib.util
import os
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
try:
    from PySide6 import QtCore, QtGui, QtWidgets, QtTest
    MAYA_VERSION = 2025
except ImportError:
    from PySide2 import QtCore, QtGui, QtWidgets, QtTest
    MAYA_VERSION = 2024

UI_PATH = Path(__file__).resolve().parents[1] / "scripts/blue_steel/ui/editor"
APP = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def load_ui_modules():
    """Import production modules without bootstrapping the Maya editor package."""
    root = "_work_shapes_ui_test"
    modules = {}
    for suffix in ("", ".ui", ".ui.editor", ".ui.common", ".api"):
        module = types.ModuleType(root + suffix)
        module.__path__ = []
        modules[module.__name__] = module
    env = types.ModuleType(root + ".env")
    env.ENVIRONMENT = types.SimpleNamespace(
        VERSION="test",
        SEPARATOR="_",
        ICONS_PATH="",
        MAYA_VERSION=MAYA_VERSION,
        PYTHON_VERSION=3,
        DGA_NODES_SUPPORTED=False,
    )
    modules[env.__name__] = env
    api = types.ModuleType(root + ".api.editor")
    api.BlueSteelEditor = object
    modules[api.__name__] = api
    ordering = types.ModuleType(root + ".api.treeViewOrderingManager")
    ordering.TreeViewOrderingManager = object
    modules[ordering.__name__] = ordering
    icons = types.ModuleType(root + ".ui.common.icons")
    for name in ("CONNECTED_MESH_DISABLED_ICON", "CONNECTED_MESH_ENABLED_ICON",
                 "EDIT_ICON", "LOCK_OFF_ICON", "LOCK_ON_ICON", "MUTE_OFF_ICON", "MUTE_ON_ICON"):
        setattr(icons, name, QtGui.QIcon())
    modules[icons.__name__] = icons
    maya = types.ModuleType("maya")
    maya.cmds = Mock()
    maya.OpenMayaUI = types.ModuleType("maya.OpenMayaUI")
    modules.update({"maya": maya, "maya.cmds": maya.cmds, "maya.OpenMayaUI": maya.OpenMayaUI})
    loaded = {}
    with patch.dict(sys.modules, modules):
        for name in ("qt", "constants", "models", "delegates", "views"):
            full_name = root + ".ui.editor." + name
            spec = importlib.util.spec_from_file_location(full_name, UI_PATH / (name + ".py"))
            module = importlib.util.module_from_spec(spec)
            sys.modules[full_name] = module
            spec.loader.exec_module(module)
            loaded[name] = module
    return loaded


UI = load_ui_modules()
Qt = UI["qt"].Qt
Shape = UI["models"].ShapeItemsModel
Roles = UI["models"].WorkShapeRoles
Delegate = UI["delegates"].WorkShapeItemDelegate
View = UI["views"].WorkShapesListView
PRIMARY_TREE_NAME_ROLE = UI["constants"].PRIMARY_TREE_NAME_ROLE
PRIMARY_TREE_FOLDER_ROLE = UI["constants"].PRIMARY_TREE_FOLDER_ROLE


def find_menu_action(menu, path):
    """Return the menu action addressed by a tuple of nested action labels."""
    for action in menu.actions():
        if action.text() != path[0]:
            continue
        if len(path) == 1:
            return action
        submenu = action.menu()
        if submenu is not None:
            found = find_menu_action(submenu, path[1:])
            if found is not None:
                return found
    return None


class ContextMenuProbe(UI["qt"].QMenu):
    """A ``QMenu`` whose ``exec`` returns a preselected action instead of blocking.

    Defined once at module scope so its type object outlives the menu instances
    Qt parents to the view; a throwaway subclass per call crashes on teardown.
    """

    selected_path = ()
    picked_action = None

    def exec(self, *args, **kwargs):
        del args, kwargs
        type(self).picked_action = find_menu_action(self, self.selected_path)
        return type(self).picked_action

    def exec_(self, *args, **kwargs):
        return self.exec(*args, **kwargs)


class Weight(str):
    def __new__(cls, name, target_id):
        result = super().__new__(cls, name)
        result.id = target_id
        return result


class FakeEditor:
    def __init__(self):
        self.drivers = {
            "a_unlinked": [],
            "b_single": ["jawOpen"],
            "mouthFix_workShape": ["lipCornerPuller", "lipCornerFunneler"],
        }
        self.weights = [Weight(name, i) for i, name in enumerate(self.drivers)]
        self.work_blendshape = Mock()
        self.work_blendshape.get_weight_value.return_value = 0.25
        self.work_blendshape.get_weight_value_by_name.return_value = 0.25
        self.work_blendshape.get_sculpt_target_indices.return_value = []
        self.work_blendshape.get_weight_by_id.return_value = self.weights[0]
        self.work_blendshape.get_weight_by_name.side_effect = lambda name: next(
            (w for w in self.weights if w == name), None)

    def get_work_blendshape_weights(self):
        return self.weights

    def get_work_blendshape_connected_targets_weights(self):
        # Extraction-mesh connection is independent of the driver hierarchy.
        return [self.weights[0]]

    def get_work_shape_muted_state(self, name):
        return False

    def get_work_shape_driver_nodes(self, name):
        return ["drivenKey"] if self.drivers[str(name)] else []

    def get_work_shape_driver_shapes(self, name):
        return self.drivers[str(name)]


def feature_handlers():
    """Load the production handlers without the full main-window bootstrap."""
    path = UI_PATH / "workShapesFeatureMixin.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = {"_on_work_shapes_double_clicked", "_on_work_shape_driver_pose_requested",
             "_on_work_shape_driver_removal_requested",
             "_on_work_shape_extract_axis_motion_requested"}
    methods = [node for cls in tree.body if isinstance(cls, ast.ClassDef)
               for node in cls.body if isinstance(node, ast.FunctionDef) and node.name in names]
    namespace = {
        "QModelIndex": QtCore.QModelIndex,
        "ShapeItemsModel": Shape,
        "QGuiApplication": QtGui.QGuiApplication,
        "Qt": Qt,
    }
    exec(compile(ast.Module(body=methods, type_ignores=[]), str(path), "exec"), namespace)
    return namespace


HANDLERS = feature_handlers()


def split_handlers():
    """Load split-settings handlers without the full main-window bootstrap."""
    path = UI_PATH / "splitSettingsUiMixin.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = {"_on_split_primaries_item_double_clicked"}
    methods = [node for cls in tree.body if isinstance(cls, ast.ClassDef)
               for node in cls.body if isinstance(node, ast.FunctionDef) and node.name in names]
    namespace = {"ShapeItemsModel": Shape}
    exec(compile(ast.Module(body=methods, type_ignores=[]), str(path), "exec"), namespace)
    return namespace


SPLIT_HANDLERS = split_handlers()


def build_tree_handler():
    """Load the production Work Shapes tree builder without the full bootstrap."""
    import __future__

    path = UI_PATH / "workShapesFeatureMixin.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = {"_build_work_shapes_tree", "_update_work_shape_folder_icon"}
    methods = [node for cls in tree.body if isinstance(cls, ast.ClassDef)
               for node in cls.body if isinstance(node, ast.FunctionDef) and node.name in names]
    namespace = {
        "QTreeWidgetItem": QtWidgets.QTreeWidgetItem,
        "ShapeItemsModel": Shape,
        "WorkShapeRoles": Roles,
        "PRIMARY_TREE_FOLDER_ROLE": PRIMARY_TREE_FOLDER_ROLE,
        "PRIMARY_TREE_NAME_ROLE": PRIMARY_TREE_NAME_ROLE,
        "Qt": Qt,
    }
    module = ast.Module(body=methods, type_ignores=[])
    exec(compile(module, str(path), "exec", flags=__future__.annotations.compiler_flag), namespace)
    return namespace


BUILD_TREE_HANDLER = build_tree_handler()


def build_work_shape_items(editor, view):
    """Populate ``view`` with the same item roles the production build uses."""
    view.clear()
    items = {}
    if editor is None or editor.work_blendshape is None:
        view._sync_driver_expansion(editor)
        return items
    weights = sorted(editor.get_work_blendshape_weights() or [], key=lambda w: str(w).lower())
    connected = set(editor.get_work_blendshape_connected_targets_weights() or [])
    for weight in weights:
        name = str(weight)
        driver_connected = bool(editor.get_work_shape_driver_nodes(weight))
        drivers = ()
        if driver_connected:
            try:
                drivers = tuple(dict.fromkeys(
                    str(driver) for driver in (editor.get_work_shape_driver_shapes(name) or []) if driver
                ))
            except (RuntimeError, ValueError):
                drivers = ()
        item = QtWidgets.QTreeWidgetItem([name])
        item.setData(0, PRIMARY_TREE_NAME_ROLE, name)
        item.setData(0, Shape.NameRole, name)
        item.setData(0, Shape.TypeRole, "WorkShape")
        item.setData(0, Shape.ValueRole, float(editor.work_blendshape.get_weight_value(weight)))
        item.setData(0, Shape.MutedRole, bool(editor.get_work_shape_muted_state(name)))
        item.setData(0, Shape.EditableRole, True)
        item.setData(0, Shape.IsHeaderRole, False)
        item.setData(0, Shape.LockedRole, False)
        item.setData(0, Shape.LockIconVisibleRole, False)
        item.setData(0, Roles.InEditModeRole, False)
        item.setData(0, Roles.ConnectedRole, weight in connected)
        item.setData(0, Roles.DriverConnectedRole, driver_connected)
        item.setData(0, Roles.DriverNamesRole, drivers)
        item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsEditable | Qt.ItemIsDragEnabled)
        view.addTopLevelItem(item)
        items[name] = item
    view._sync_driver_expansion(editor)
    return items


def add_work_shape_folder(view, name, parent=None):
    """Add a folder item the way the production tree builder does."""
    folder = QtWidgets.QTreeWidgetItem([name])
    folder.setData(0, PRIMARY_TREE_FOLDER_ROLE, True)
    folder.setData(0, PRIMARY_TREE_NAME_ROLE, name)
    folder.setData(0, Shape.NameRole, name)
    folder.setData(0, Shape.TypeRole, "WorkShapeFolder")
    folder.setData(0, Shape.IsHeaderRole, True)
    folder.setData(0, Shape.EditableRole, False)
    folder.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsDragEnabled | Qt.ItemIsDropEnabled)
    if parent is None:
        view.addTopLevelItem(folder)
    else:
        parent.addChild(folder)
    return folder


def add_primary_leaf(view, name, parent=None):
    """Add a primary leaf item the way the production tree builder does."""
    leaf = QtWidgets.QTreeWidgetItem([name])
    leaf.setData(0, PRIMARY_TREE_NAME_ROLE, name)
    leaf.setData(0, Shape.NameRole, name)
    leaf.setData(0, Shape.TypeRole, "PrimaryShape")
    leaf.setData(0, Shape.IsHeaderRole, False)
    leaf.setData(0, Shape.EditableRole, True)
    leaf.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsEditable | Qt.ItemIsDragEnabled)
    if parent is None:
        view.addTopLevelItem(leaf)
    else:
        parent.addChild(leaf)
    return leaf


def add_shape_header(view, name, parent=None, level=0):
    """Add a shapes-tree group row (level header or nested type group)."""
    header = QtWidgets.QTreeWidgetItem([name])
    header.setData(0, Shape.IsHeaderRole, True)
    header.setData(0, Shape.NameRole, name)
    header.setData(0, Shape.LevelRole, int(level))
    header.setData(0, Shape.HeaderCollapsedRole, False)
    font = header.font(0)
    font.setBold(True)
    header.setFont(0, font)
    header.setFlags(Qt.ItemIsEnabled)
    if parent is None:
        view.addTopLevelItem(header)
    else:
        parent.addChild(header)
    return header


class FakeTreeItem:
    """Minimal QTreeWidgetItem stand-in for role-keyed double-click tests."""

    def __init__(self, name, is_header=False, parent=None):
        self._name = name
        self._is_header = is_header
        self._parent = parent

    def parent(self):
        return self._parent

    def data(self, column, role):
        del column
        if role == Shape.IsHeaderRole:
            return self._is_header
        if role == Shape.NameRole:
            return self._name
        return None


class WorkShapesUiTests(unittest.TestCase):
    def setUp(self):
        self.editor = FakeEditor()
        self.drop = Mock()
        self.view = View(self.drop, Mock(), Mock(), Mock())
        self.view.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.delegate = Delegate(self.view)
        self.view.setItemDelegate(self.delegate)
        self.items = build_work_shape_items(self.editor, self.view)
        self.view.resize(520, 300)
        self.view.show()
        APP.processEvents()
        self.index = self.item_index("mouthFix_workShape")

    def tearDown(self):
        self.view.close()
        self.view.deleteLater()
        APP.processEvents()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def item_index(self, name):
        item = self.items.get(name)
        return self.view.indexFromItem(item, 0) if item is not None else QtCore.QModelIndex()

    def reload_items(self):
        """Rebuild the tree from the fake editor and refresh the item cache."""
        self.items = build_work_shape_items(self.editor, self.view)
        return self.items

    def item(self, name):
        return self.items[name]

    def option(self, index=None):
        index = self.index if index is None else index
        option = QtWidgets.QStyleOptionViewItem()
        option.rect = self.view.visualRect(index)
        option.palette = self.view.palette()
        option.font = self.view.font()
        option.fontMetrics = self.view.fontMetrics()
        return option

    def child_pos(self, child=0):
        option = self.option()
        parent = self.delegate.parent_rect(option, self.index)
        _, name = self.delegate._area_rects(option, self.index)
        return QtCore.QPoint(name.left() + 30,
                             parent.bottom() + 1 + child * self.delegate.DRIVER_HEIGHT + 10)

    def click(self, pos, double=False, modifiers=Qt.NoModifier):
        QtTest.QTest.mouseClick(self.view.viewport(), Qt.LeftButton, modifiers, pos)
        if double:
            QtTest.QTest.mouseDClick(self.view.viewport(), Qt.LeftButton, modifiers, pos)
            QtTest.QTest.mouseRelease(self.view.viewport(), Qt.LeftButton, modifiers, pos)
        APP.processEvents()

    def move_mouse(self, pos, receiver=None):
        receiver = self.view.viewport() if receiver is None else receiver
        global_pos = receiver.mapToGlobal(pos)
        window_pos = receiver.window().mapFromGlobal(global_pos)
        event = QtGui.QMouseEvent(QtCore.QEvent.MouseMove, QtCore.QPointF(pos),
                                  QtCore.QPointF(window_pos), QtCore.QPointF(global_pos),
                                  Qt.NoButton, Qt.LeftButton, Qt.NoModifier)
        APP.sendEvent(receiver, event)
        APP.processEvents()

    def start_removal_drag(self, child=0):
        pos = self.child_pos(child)
        QtTest.QTest.mousePress(self.view.viewport(), Qt.LeftButton, Qt.NoModifier, pos)
        self.move_mouse(pos + QtCore.QPoint(40, 0))
        return pos

    def outside_pos(self):
        return QtCore.QPoint(self.view.width() + 30, self.child_pos().y())

    # ------------------------------------------------------------------
    # Tree structure and roles
    # ------------------------------------------------------------------
    def test_flat_tree_and_zero_one_multiple_drivers(self):
        self.assertEqual(self.view.topLevelItemCount(), 3)
        expected = [(), ("jawOpen",), ("lipCornerPuller", "lipCornerFunneler")]
        for row, drivers in enumerate(expected):
            item = self.view.topLevelItem(row)
            self.assertEqual(item.data(0, Roles.DriverNamesRole), drivers)
            self.assertEqual(item.parent(), None)
            self.assertEqual(item.childCount(), 0)
            index = self.view.indexFromItem(item, 0)
            self.assertEqual(self.view.visualRect(index).height(), 24 + len(drivers) * 20)
        first = self.view.indexFromItem(self.view.topLevelItem(0), 0)
        self.assertTrue(first.data(Roles.ConnectedRole))
        self.assertFalse(self.index.data(Roles.ConnectedRole))
        self.assertTrue(self.index.data(Roles.DriverConnectedRole))

    def test_zero_driver_parent_paint_and_geometry_unchanged(self):
        index = self.view.indexFromItem(self.view.topLevelItem(0), 0)
        option = self.option(index)
        original = UI["delegates"].SliderItemDelegate(self.view)
        self.assertEqual(self.delegate.sizeHint(option, index), original.sizeHint(option, index))
        self.assertEqual(self.delegate._area_rects(option, index), original._area_rects(option, index))
        self.assertTrue(self.delegate.disclosure_rect(option, index).isNull())
        images = []
        for delegate in (original, self.delegate):
            pixmap = QtGui.QPixmap(520, 24)
            pixmap.fill(Qt.transparent)
            painter = QtGui.QPainter(pixmap)
            delegate.paint(painter, option, index)
            painter.end()
            images.append(pixmap.toImage())
        self.assertEqual(images[0], images[1])

    def test_expanded_controls_and_editors_stay_in_parent_band(self):
        option = self.option()
        parent = self.delegate.parent_rect(option, self.index)
        value, name = self.delegate._area_rects(option, self.index)
        self.assertEqual(parent.height(), 24)
        for rect in (value, name, self.delegate._connected_mesh_icon_rect(option, self.index),
                     self.delegate._mute_icon_rect(option, self.index),
                     self.delegate._edit_mode_icon_rect(option, self.index)):
            self.assertGreaterEqual(rect.top(), parent.top())
            self.assertLessEqual(rect.bottom(), parent.bottom())
        editor = self.delegate.createEditor(self.view, option, self.index)
        self.delegate.updateEditorGeometry(editor, option, self.index)
        self.assertEqual(editor.geometry(), value)
        child_in_slider_column = QtCore.QPoint(value.center().x(), self.child_pos().y())
        self.assertFalse(self.delegate.external_drag_start(
            self.view.model(), self.index, child_in_slider_column, option.rect))
        editor.deleteLater()

    # ------------------------------------------------------------------
    # Drivers: disclosure, expansion, pose, drag removal
    # ------------------------------------------------------------------
    def test_disclosure_changes_height_without_selection_or_parent_actions(self):
        pose, double = [], []
        self.view.driverPoseRequested.connect(pose.append)
        self.view.itemDoubleClicked.connect(lambda item, col: double.append(item))
        self.view.setCurrentItem(self.item("a_unlinked"))
        selected = self.view.selectedItems()
        control = self.delegate.disclosure_rect(self.option(), self.index).center()
        self.click(control, double=True)
        self.assertFalse(self.view.drivers_expanded(self.index))
        self.assertEqual(self.view.visualRect(self.index).height(), 24)
        self.assertEqual(self.view.selectedItems(), selected)
        self.assertFalse(pose)
        self.assertFalse(double)
        self.assertIsNone(self.delegate.driver_at_pos(self.option(), self.index, self.child_pos()))
        self.click(control)
        self.assertEqual(self.view.visualRect(self.index).height(), 64)

    def test_alt_left_click_disclosure_sets_expansion_for_every_work_shape(self):
        driver_items = [item for item in self.items.values()
                        if item.data(0, Roles.DriverNamesRole)]
        self.assertTrue(driver_items)
        self.assertTrue(all(self.view.drivers_expanded(self.view.indexFromItem(item, 0))
                            for item in driver_items))

        for expected_expanded in (False, True):
            control = self.delegate.disclosure_rect(self.option(), self.index).center()
            QtTest.QTest.mouseClick(self.view.viewport(), Qt.LeftButton, Qt.AltModifier, control)
            APP.processEvents()
            for item in driver_items:
                self.assertEqual(
                    self.view.drivers_expanded(self.view.indexFromItem(item, 0)),
                    expected_expanded,
                )

    def test_plain_right_click_disclosure_leaves_expansion_unchanged(self):
        control = self.delegate.disclosure_rect(self.option(), self.index).center()
        QtTest.QTest.mouseClick(self.view.viewport(), Qt.RightButton, Qt.NoModifier, control)
        APP.processEvents()
        self.assertTrue(self.view.drivers_expanded(self.index))

    def test_each_child_double_click_requests_exact_driver_only(self):
        pose, double, mute, edit, mesh = [], [], [], [], []
        self.view.driverPoseRequested.connect(pose.append)
        self.view.itemDoubleClicked.connect(lambda item, col: double.append(item))
        self.delegate.muteToggleRequested.connect(lambda *args: mute.append(args))
        self.delegate.workEditModeToggleRequested.connect(lambda *args: edit.append(args))
        self.delegate.connectedMeshRequested.connect(mesh.append)
        self.view.setCurrentItem(self.item("a_unlinked"))
        selected = self.view.selectedItems()
        for child, name in enumerate(self.editor.drivers["mouthFix_workShape"]):
            pos = self.child_pos(child)
            self.assertEqual(self.delegate.driver_at_pos(self.option(), self.index, pos), name)
            self.click(pos, double=True)
        self.assertEqual(pose, ["lipCornerPuller", "lipCornerFunneler"])
        self.assertEqual(self.view.selectedItems(), selected)
        self.assertFalse(double or mute or edit or mesh)
        self.assertFalse(self.delegate.is_drag_active())
        self.editor.work_blendshape.set_weight_value.assert_not_called()

    def test_dragging_from_child_does_not_rubber_band_select_parents(self):
        self.view.setCurrentItem(self.item("a_unlinked"))
        selected = self.view.selectedItems()
        QtTest.QTest.mousePress(self.view.viewport(), Qt.LeftButton, Qt.NoModifier, self.child_pos())
        self.move_mouse(self.view.visualRect(self.item_index("b_single")).center())
        QtTest.QTest.mouseRelease(self.view.viewport(), Qt.LeftButton, Qt.NoModifier, self.child_pos())
        self.assertEqual(self.view.selectedItems(), selected)
        self.assertFalse(self.delegate.is_drag_active())
        self.assertFalse(self.view._removal_press_active)

    def test_children_and_disclosure_are_not_context_or_drop_targets(self):
        self.assertIsNone(self.view._receiver_name_at_pos(self.child_pos()))
        disclosure = self.delegate.disclosure_rect(self.option(), self.index).center()
        self.assertIsNone(self.view._receiver_name_at_pos(disclosure))
        _, name = self.delegate._area_rects(self.option(), self.index)
        self.assertEqual(self.view._receiver_name_at_pos(name.center()), "mouthFix_workShape")

    def test_parent_controls_remain_clickable_in_narrow_panel(self):
        self.view.resize(180, 300)
        APP.processEvents()
        self.item("mouthFix_workShape").setData(0, Roles.ConnectedRole, True)
        self.view.viewport().update()
        mesh, mute, edit = [], [], []
        self.delegate.connectedMeshRequested.connect(mesh.append)
        self.delegate.muteToggleRequested.connect(lambda *args: mute.append(args))
        self.delegate.workEditModeToggleRequested.connect(lambda *args: edit.append(args))
        for helper in (self.delegate._connected_mesh_icon_rect,
                       self.delegate._mute_icon_rect, self.delegate._edit_mode_icon_rect):
            self.click(helper(self.option(), self.index).center())
        self.assertEqual(mesh, ["mouthFix_workShape"])
        self.assertEqual(mute, [("mouthFix_workShape", True)])
        self.assertEqual(edit, [("mouthFix_workShape", True)])
        self.assertTrue(self.view.drivers_expanded(self.index))

    def test_edit_button_stays_right_aligned_when_view_resizes(self):
        for width in (180, 520):
            self.view.resize(width, 300)
            APP.processEvents()
            edit_rect = self.delegate._edit_mode_icon_rect(self.option(), self.index)
            viewport_width = self.view.viewport().width()
            self.assertLess(edit_rect.right(), viewport_width)
            self.assertGreaterEqual(edit_rect.right(), viewport_width - 8)

    def test_scrolled_children_use_viewport_coordinates(self):
        self.view.resize(520, 85)
        APP.processEvents()
        self.view.scrollToItem(self.item("mouthFix_workShape"), QtWidgets.QAbstractItemView.PositionAtBottom)
        APP.processEvents()
        pose = []
        self.view.driverPoseRequested.connect(pose.append)
        self.click(self.child_pos(1), double=True)
        self.assertEqual(pose, ["lipCornerFunneler"])

    def test_connection_notifications_refresh_names_and_layout_even_when_still_connected(self):
        self.editor.drivers["mouthFix_workShape"].append("jawOpen")
        item = self.item("mouthFix_workShape")
        item.setData(0, Roles.DriverNamesRole, tuple(self.editor.drivers["mouthFix_workShape"]))
        self.delegate.sizeHintChanged.emit(self.index)
        APP.processEvents()
        self.assertEqual(self.index.data(Roles.DriverNamesRole)[-1], "jawOpen")
        self.assertEqual(self.view.visualRect(self.index).height(), 84)
        item.setData(0, Roles.DriverConnectedRole, False)
        item.setData(0, Roles.DriverNamesRole, ())
        self.delegate.sizeHintChanged.emit(self.index)
        APP.processEvents()
        self.assertEqual(self.index.data(Roles.DriverNamesRole), ())
        self.assertEqual(self.view.visualRect(self.index).height(), 24)
        self.assertTrue(self.delegate.disclosure_rect(self.option(), self.index).isNull())
        self.assertEqual(self.view.topLevelItemCount(), 3)

    def test_unresolvable_driver_graph_keeps_parent_usable(self):
        self.editor.get_work_shape_driver_shapes = Mock(side_effect=RuntimeError("Missing input1D"))
        self.items = build_work_shape_items(self.editor, self.view)
        self.index = self.item_index("mouthFix_workShape")
        self.assertTrue(self.index.isValid())
        self.assertTrue(self.index.data(Roles.DriverConnectedRole))
        self.assertEqual(self.index.data(Roles.DriverNamesRole), ())
        self.assertEqual(self.delegate.sizeHint(self.option(), self.index).height(), 24)

    def test_expansion_survives_refresh_but_not_editor_change_or_removal(self):
        self.view._toggle_drivers(self.index)
        self.items = build_work_shape_items(self.editor, self.view)
        self.index = self.item_index("mouthFix_workShape")
        self.assertFalse(self.view.drivers_expanded(self.index))
        self.items = build_work_shape_items(FakeEditor(), self.view)
        self.index = self.item_index("mouthFix_workShape")
        self.assertTrue(self.view.drivers_expanded(self.index))
        self.view._toggle_drivers(self.index)
        self.items = build_work_shape_items(None, self.view)
        self.assertFalse(self.view._collapsed_driver_names)

    def test_pose_handler_and_parent_alt_double_click(self):
        host = Mock()
        host.current_editor = self.editor
        host.shapes_list_active_button.isChecked.return_value = True
        self.view.driverPoseRequested.connect(
            lambda name: HANDLERS["_on_work_shape_driver_pose_requested"](host, name))
        self.view.itemDoubleClicked.connect(
            lambda item, col: HANDLERS["_on_work_shapes_double_clicked"](host, item, col))
        self.click(self.child_pos(1), double=True)
        host.shapes_list_active_button.setChecked.assert_called_once_with(False)
        host._set_shape_pose_by_name.assert_called_once_with("lipCornerFunneler")
        host._select_shape_and_primaries.assert_called_once_with("lipCornerFunneler")
        host._begin_inline_workshape_rename.assert_not_called()
        host.reset_mock()
        _, name = self.delegate._area_rects(self.option(), self.index)
        self.click(name.center(), double=True, modifiers=Qt.AltModifier)
        host._set_shape_pose_by_name.assert_not_called()
        host._select_shape_and_primaries.assert_not_called()
        host._begin_inline_workshape_rename.assert_called_once()

    def test_value_area_double_click_starts_numeric_edit_without_rename(self):
        """Double-clicking the slider bar opens the numeric value editor."""
        host = Mock()
        host.current_editor = self.editor
        self.view.itemDoubleClicked.connect(
            lambda item, col: HANDLERS["_on_work_shapes_double_clicked"](host, item, col))
        value_rect, _ = self.delegate._area_rects(self.option(), self.index)
        self.double_click(value_rect.center())
        self.assertEqual(self.view.state(), QtWidgets.QAbstractItemView.EditingState)
        host._begin_inline_workshape_rename.assert_not_called()
        editor = self.view.findChild(QtWidgets.QLineEdit)
        self.assertIsNotNone(editor)
        self.assertEqual(editor.text(), "0.2500")

    def test_name_area_double_click_still_renames_without_value_editor(self):
        """Name-area double-clicks keep the rename action and open no editor."""
        host = Mock()
        host.current_editor = self.editor
        self.view.itemDoubleClicked.connect(
            lambda item, col: HANDLERS["_on_work_shapes_double_clicked"](host, item, col))
        _, name_rect = self.delegate._area_rects(self.option(), self.index)
        self.click(name_rect.center(), double=True)
        host._begin_inline_workshape_rename.assert_called_once()
        self.assertNotEqual(self.view.state(), QtWidgets.QAbstractItemView.EditingState)

    def double_click(self, pos):
        """Deliver a raw double-click event (no drag side effects offscreen)."""
        global_pos = self.view.viewport().mapToGlobal(pos)
        window_pos = self.view.viewport().window().mapFromGlobal(global_pos)
        event = QtGui.QMouseEvent(
            QtCore.QEvent.MouseButtonDblClick,
            QtCore.QPointF(pos),
            QtCore.QPointF(window_pos),
            QtCore.QPointF(global_pos),
            Qt.LeftButton,
            Qt.LeftButton,
            Qt.NoModifier,
        )
        APP.sendEvent(self.view.viewport(), event)
        APP.processEvents()

    # ------------------------------------------------------------------
    # Tree grouping / ordering shortcuts
    # ------------------------------------------------------------------
    def test_production_builder_creates_folders_and_leaves(self):
        """The mixin's tree builder stores folder/leaf roles and nesting."""
        class BuilderHost:
            def __init__(self, view):
                self.work_shapes_view = view
                self._work_shape_tree_items = {}

        host = BuilderHost(self.view)
        host._primary_tree_folder_open_icon = QtGui.QIcon(QtGui.QPixmap(4, 4))
        host._primary_tree_folder_closed_icon = QtGui.QIcon(QtGui.QPixmap(4, 4))
        host._build_work_shapes_tree = types.MethodType(BUILD_TREE_HANDLER["_build_work_shapes_tree"], host)
        host._update_work_shape_folder_icon = types.MethodType(
            BUILD_TREE_HANDLER["_update_work_shape_folder_icon"], host)
        self.view.clear()
        host._work_shape_tree_items.clear()
        info = {
            "a_unlinked": {"value": 0.25, "muted": False, "connected": False,
                           "driver_connected": False, "driver_names": (), "tooltip": None},
            "b_single": {"value": 0.5, "muted": False, "connected": True,
                         "driver_connected": True, "driver_names": ("jawOpen",),
                         "tooltip": "Connected extraction mesh"},
        }
        nodes = [
            {"name": "Mouth", "type": "group", "children": [
                {"name": "a_unlinked", "type": "primary"},
                {"name": "b_single", "type": "primary"},
            ]},
        ]
        host._build_work_shapes_tree(nodes, None, info, "b_single", {"a_unlinked"}, set())
        self.assertEqual(self.view.topLevelItemCount(), 1)
        folder = self.view.topLevelItem(0)
        self.assertTrue(folder.data(0, PRIMARY_TREE_FOLDER_ROLE))
        self.assertEqual(folder.data(0, Shape.IsHeaderRole), True)
        self.assertEqual(folder.childCount(), 2)
        leaf = folder.child(0)
        self.assertEqual(leaf.data(0, PRIMARY_TREE_NAME_ROLE), "a_unlinked")
        self.assertEqual(leaf.data(0, Shape.TypeRole), "WorkShape")
        self.assertTrue(leaf.isSelected())
        self.assertFalse(leaf.data(0, Roles.InEditModeRole))
        other = folder.child(1)
        self.assertTrue(other.data(0, Roles.ConnectedRole))
        self.assertTrue(other.data(0, Roles.InEditModeRole))
        self.assertEqual(other.data(0, Roles.DriverNamesRole), ("jawOpen",))
        self.assertEqual(host._work_shape_tree_items["b_single"], other)
        self.assertTrue(folder.isExpanded())
        self.assertFalse(folder.icon(0).isNull())

    def test_ctrl_g_emits_group_requested(self):
        groups = []
        self.view.groupRequested.connect(lambda: groups.append(True))
        QtTest.QTest.keyClick(self.view, Qt.Key_G, Qt.ControlModifier)
        APP.processEvents()
        self.assertTrue(groups)

    # ------------------------------------------------------------------
    # Primaries tree: Alt+left-click toggles every group at once
    # ------------------------------------------------------------------
    def build_primary_tree(self):
        """Build a shown Primaries tree with nested groups and a leaf."""
        view = UI["views"].PrimaryTreeWidget()
        view.resize(320, 320)
        view.show()
        APP.processEvents()
        group_a = add_work_shape_folder(view, "GroupA")
        group_b = add_work_shape_folder(view, "GroupB")
        nested = add_work_shape_folder(view, "Nested", parent=group_a)
        leaf = add_primary_leaf(view, "jawOpen", parent=group_a)
        for group in (group_a, group_b, nested):
            group.setExpanded(True)
        APP.processEvents()
        self.addCleanup(self.close_view, view)
        return view, (group_a, group_b, nested), leaf

    @staticmethod
    def close_view(view):
        view.close()
        view.deleteLater()
        APP.processEvents()

    def test_alt_left_click_group_collapses_every_group(self):
        view, groups, _ = self.build_primary_tree()
        self.assertTrue(all(group.isExpanded() for group in groups))
        QtTest.QTest.mouseClick(
            view.viewport(), Qt.LeftButton, Qt.AltModifier,
            view.visualItemRect(groups[0]).center(),
        )
        APP.processEvents()
        self.assertTrue(all(not group.isExpanded() for group in groups))

    def test_alt_left_click_group_expands_every_group(self):
        view, groups, _ = self.build_primary_tree()
        for group in groups:
            group.setExpanded(False)
        APP.processEvents()
        QtTest.QTest.mouseClick(
            view.viewport(), Qt.LeftButton, Qt.AltModifier,
            view.visualItemRect(groups[0]).center(),
        )
        APP.processEvents()
        self.assertTrue(all(group.isExpanded() for group in groups))

    def test_alt_left_click_group_does_not_emit_item_clicked(self):
        view, groups, _ = self.build_primary_tree()
        clicks = []
        view.itemClicked.connect(lambda item, column: clicks.append(item))
        QtTest.QTest.mouseClick(
            view.viewport(), Qt.LeftButton, Qt.AltModifier,
            view.visualItemRect(groups[0]).center(),
        )
        APP.processEvents()
        self.assertEqual(clicks, [])

    def test_alt_left_click_leaf_leaves_group_expansion_unchanged(self):
        view, groups, leaf = self.build_primary_tree()
        self.assertFalse(bool(leaf.data(0, PRIMARY_TREE_FOLDER_ROLE)))
        QtTest.QTest.mouseClick(
            view.viewport(), Qt.LeftButton, Qt.AltModifier,
            view.visualItemRect(leaf).center(),
        )
        APP.processEvents()
        self.assertTrue(all(group.isExpanded() for group in groups))

    def test_plain_left_click_group_still_emits_item_clicked(self):
        view, groups, _ = self.build_primary_tree()
        clicks = []
        view.itemClicked.connect(lambda item, column: clicks.append(item))
        QtTest.QTest.mouseClick(
            view.viewport(), Qt.LeftButton, Qt.NoModifier,
            view.visualItemRect(groups[0]).center(),
        )
        APP.processEvents()
        self.assertEqual(clicks, [groups[0]])

    # ------------------------------------------------------------------
    # Shapes tree: Alt+left-click toggles every group at once
    # ------------------------------------------------------------------
    def build_shapes_tree(self):
        """Build a shown Shapes tree with level headers and type groups."""
        view = UI["views"].ShapeTreeWidget()
        view.resize(320, 320)
        view.show()
        APP.processEvents()
        header_a = add_shape_header(view, "Level 1", level=0)
        header_b = add_shape_header(view, "Level 2", level=1)
        type_group = add_shape_header(view, "Type A", parent=header_a, level=0)
        add_primary_leaf(view, "jawOpen", parent=type_group)
        groups = (header_a, header_b, type_group)
        for group in groups:
            group.setExpanded(True)
        APP.processEvents()
        self.addCleanup(self.close_view, view)
        return view, groups

    def test_alt_left_click_shape_group_collapses_every_group(self):
        view, groups = self.build_shapes_tree()
        self.assertTrue(all(group.isExpanded() for group in groups))
        QtTest.QTest.mouseClick(
            view.viewport(), Qt.LeftButton, Qt.AltModifier,
            view.visualItemRect(groups[0]).center(),
        )
        APP.processEvents()
        self.assertTrue(all(not group.isExpanded() for group in groups))

    def test_alt_left_click_shape_group_expands_every_group(self):
        view, groups = self.build_shapes_tree()
        for group in groups:
            group.setExpanded(False)
        APP.processEvents()
        QtTest.QTest.mouseClick(
            view.viewport(), Qt.LeftButton, Qt.AltModifier,
            view.visualItemRect(groups[0]).center(),
        )
        APP.processEvents()
        self.assertTrue(all(group.isExpanded() for group in groups))

    def test_alt_left_click_shape_group_does_not_emit_item_clicked(self):
        view, groups = self.build_shapes_tree()
        clicks = []
        view.itemClicked.connect(lambda item, column: clicks.append(item))
        QtTest.QTest.mouseClick(
            view.viewport(), Qt.LeftButton, Qt.AltModifier,
            view.visualItemRect(groups[0]).center(),
        )
        APP.processEvents()
        self.assertEqual(clicks, [])

    def test_alt_left_click_shape_leaf_leaves_group_expansion_unchanged(self):
        view, groups = self.build_shapes_tree()
        leaf = groups[2].child(0)
        self.assertFalse(bool(leaf.data(0, Shape.IsHeaderRole)))
        QtTest.QTest.mouseClick(
            view.viewport(), Qt.LeftButton, Qt.AltModifier,
            view.visualItemRect(leaf).center(),
        )
        APP.processEvents()
        self.assertTrue(all(group.isExpanded() for group in groups))

    def test_plain_left_click_shape_group_still_emits_item_clicked(self):
        view, groups = self.build_shapes_tree()
        clicks = []
        view.itemClicked.connect(lambda item, column: clicks.append(item))
        QtTest.QTest.mouseClick(
            view.viewport(), Qt.LeftButton, Qt.NoModifier,
            view.visualItemRect(groups[0]).center(),
        )
        APP.processEvents()
        self.assertEqual(clicks, [groups[0]])

    # ------------------------------------------------------------------
    # Active Shapes list: Alt+left-click toggles every level group
    # ------------------------------------------------------------------
    def active_shapes_model(self, with_value_header=False):
        model = QtGui.QStandardItemModel()

        def add_row(name, is_header, level, value=0.0, collapsed=False):
            item = QtGui.QStandardItem(name)
            item.setData(bool(is_header), Shape.IsHeaderRole)
            item.setData(level, Shape.LevelRole)
            item.setData(value, Shape.ValueRole)
            if is_header:
                item.setData(collapsed, Shape.HeaderCollapsedRole)
            model.appendRow(item)
            return item

        if with_value_header:
            add_row("With Value (1)", True, -1)
        header = add_row("Level 0 (1)", True, 0)
        add_row("shape0", False, 0, value=1.0)
        add_row("Level 1 (0)", True, 1)
        add_row("shape1", False, 1, value=0.0)
        return model, header

    def active_shapes_list(self):
        view = UI["views"].ActiveShapesListView()
        view.resize(320, 240)
        view.show()
        APP.processEvents()
        self.addCleanup(self.close_view, view)
        return view

    def test_active_shapes_proxy_set_all_levels_collapsed(self):
        model, _ = self.active_shapes_model()
        proxy = UI["models"].ShapesFilterProxyModel()
        proxy.setSourceModel(model)
        proxy.set_all_levels_collapsed(True)
        self.assertEqual(proxy._collapsed_levels, {0, 1})
        proxy.set_all_levels_collapsed(False)
        self.assertEqual(proxy._collapsed_levels, set())

    def test_active_shapes_proxy_skips_with_value_header(self):
        model, _ = self.active_shapes_model(with_value_header=True)
        proxy = UI["models"].ShapesFilterProxyModel()
        proxy.setSourceModel(model)
        proxy.setSortRole(Shape.ValueRole)
        self.assertTrue(proxy._is_value_sort_mode())
        proxy.set_all_levels_collapsed(True)
        self.assertEqual(proxy._collapsed_levels, {0, 1})

    def test_active_shapes_list_alt_click_header_requests_all_groups_toggle(self):
        view = self.active_shapes_list()
        model, header = self.active_shapes_model()
        view.setModel(model)
        APP.processEvents()
        requests = []
        view.allGroupsToggleRequested.connect(requests.append)
        QtTest.QTest.mouseClick(
            view.viewport(), Qt.LeftButton, Qt.AltModifier,
            view.visualRect(model.index(0, 0)).center(),
        )
        APP.processEvents()
        self.assertEqual(requests, [False])

        header.setData(True, Shape.HeaderCollapsedRole)
        QtTest.QTest.mouseClick(
            view.viewport(), Qt.LeftButton, Qt.AltModifier,
            view.visualRect(model.index(0, 0)).center(),
        )
        APP.processEvents()
        self.assertEqual(requests, [False, True])

    def test_active_shapes_list_alt_click_leaf_and_plain_click_emit_nothing(self):
        view = self.active_shapes_list()
        model, _ = self.active_shapes_model()
        view.setModel(model)
        APP.processEvents()
        requests = []
        clicks = []
        view.allGroupsToggleRequested.connect(requests.append)
        view.clicked.connect(lambda index: clicks.append(index))
        leaf_index = model.index(1, 0)
        QtTest.QTest.mouseClick(
            view.viewport(), Qt.LeftButton, Qt.AltModifier,
            view.visualRect(leaf_index).center(),
        )
        APP.processEvents()
        self.assertEqual(requests, [])
        QtTest.QTest.mouseClick(
            view.viewport(), Qt.LeftButton, Qt.NoModifier,
            view.visualRect(model.index(0, 0)).center(),
        )
        APP.processEvents()
        self.assertEqual(requests, [])
        self.assertTrue(clicks)
        self.assertEqual(clicks[-1], model.index(0, 0))

    # ------------------------------------------------------------------
    # Split assignment tree: Alt+left-click toggles every group
    # ------------------------------------------------------------------
    def build_split_assignments(self):
        view = UI["views"].SplitPrimaryAssignmentsView()
        view.resize(300, 300)
        view.show()
        APP.processEvents()
        group_a = QtWidgets.QTreeWidgetItem(["NoSplit"])
        group_b = QtWidgets.QTreeWidgetItem(["GroupA"])
        view.addTopLevelItem(group_a)
        view.addTopLevelItem(group_b)
        group_a.addChild(QtWidgets.QTreeWidgetItem(["jawOpen"]))
        group_b.addChild(QtWidgets.QTreeWidgetItem(["smile"]))
        for group in (group_a, group_b):
            group.setExpanded(True)
        APP.processEvents()
        self.addCleanup(self.close_view, view)
        return view, (group_a, group_b)

    def test_split_assignments_alt_click_group_toggles_all_groups(self):
        view, groups = self.build_split_assignments()
        QtTest.QTest.mouseClick(
            view.viewport(), Qt.LeftButton, Qt.AltModifier,
            view.visualItemRect(groups[0]).center(),
        )
        APP.processEvents()
        self.assertTrue(all(not group.isExpanded() for group in groups))
        QtTest.QTest.mouseClick(
            view.viewport(), Qt.LeftButton, Qt.AltModifier,
            view.visualItemRect(groups[0]).center(),
        )
        APP.processEvents()
        self.assertTrue(all(group.isExpanded() for group in groups))

    def test_split_assignments_plain_click_group_toggles_only_clicked(self):
        view, groups = self.build_split_assignments()
        QtTest.QTest.mouseClick(
            view.viewport(), Qt.LeftButton, Qt.NoModifier,
            view.visualItemRect(groups[0]).center(),
        )
        APP.processEvents()
        self.assertFalse(groups[0].isExpanded())
        self.assertTrue(groups[1].isExpanded())

    def test_split_assignments_alt_click_leaf_leaves_groups_unchanged(self):
        view, groups = self.build_split_assignments()
        leaf = groups[0].child(0)
        QtTest.QTest.mouseClick(
            view.viewport(), Qt.LeftButton, Qt.AltModifier,
            view.visualItemRect(leaf).center(),
        )
        APP.processEvents()
        self.assertTrue(all(group.isExpanded() for group in groups))

    def test_work_shape_tree_enables_internal_reorder(self):
        self.assertTrue(self.view._enable_internal_reorder)
        self.assertEqual(self.view.ORDER_MIME_TYPE, UI["constants"].WORK_SHAPE_ORDER_MIME_TYPE)
        self.assertTrue(self.view.acceptDrops())

    def test_folder_item_is_not_a_driver_drop_target(self):
        folder = add_work_shape_folder(self.view, "GroupA")
        APP.processEvents()
        folder_pos = self.view.visualItemRect(folder).center()
        self.assertIsNone(self.view._receiver_name_at_pos(folder_pos))

    def folder_disclosure_rect(self, folder):
        """Return the delegate-painted group triangle rect for ``folder``."""
        index = self.view.indexFromItem(folder, 0)
        return self.delegate.folder_disclosure_rect(self.option(index), index)

    def test_work_shape_tree_hides_native_branch_indicator(self):
        stylesheet = self.view.styleSheet()
        self.assertIn("QTreeView::branch", stylesheet)
        self.assertIn("image: none", stylesheet)
        self.assertFalse(self.view._uses_native_branch_indicator)

    def test_group_triangle_single_click_toggles_expansion(self):
        folder = add_work_shape_folder(self.view, "GroupA")
        add_work_shape_folder(self.view, "Nested", parent=folder)
        folder.setExpanded(False)
        APP.processEvents()
        rect = self.folder_disclosure_rect(folder)
        self.assertFalse(rect.isNull())
        self.click(rect.center())
        self.assertTrue(folder.isExpanded())
        self.click(rect.center())
        self.assertFalse(folder.isExpanded())

    def test_group_triangle_double_click_does_not_double_toggle(self):
        folder = add_work_shape_folder(self.view, "GroupA")
        add_work_shape_folder(self.view, "Nested", parent=folder)
        folder.setExpanded(False)
        APP.processEvents()
        self.click(self.folder_disclosure_rect(folder).center(), double=True)
        self.assertTrue(folder.isExpanded())

    def test_group_name_click_does_not_toggle_expansion(self):
        folder = add_work_shape_folder(self.view, "GroupA")
        add_work_shape_folder(self.view, "Nested", parent=folder)
        folder.setExpanded(False)
        APP.processEvents()
        rect = self.view.visualItemRect(folder)
        self.click(QtCore.QPoint(rect.right() - 6, rect.center().y()))
        self.assertFalse(folder.isExpanded())

    def test_nested_folder_disclosure_indents_like_primaries(self):
        outer = add_work_shape_folder(self.view, "Outer")
        inner = add_work_shape_folder(self.view, "Inner", parent=outer)
        outer.setExpanded(True)
        APP.processEvents()
        outer_left = self.folder_disclosure_rect(outer).left()
        inner_left = self.folder_disclosure_rect(inner).left()
        self.assertEqual(inner_left - outer_left, UI["constants"].PRIMARY_TREE_INDENT)

    def test_internal_drop_target_resolves_before_inside_after(self):
        folder = add_work_shape_folder(self.view, "GroupA")
        APP.processEvents()
        rect = self.view.visualItemRect(folder)
        self.assertEqual(self.view._internal_drop_target(QtCore.QPoint(rect.center().x(), rect.top() + 1))[1], "before")
        self.assertEqual(self.view._internal_drop_target(QtCore.QPoint(rect.center().x(), rect.center().y()))[1], "inside")
        self.assertEqual(self.view._internal_drop_target(QtCore.QPoint(rect.center().x(), rect.bottom() - 1))[1], "after")

    # ------------------------------------------------------------------
    # Extract Motion Axis context menu
    # ------------------------------------------------------------------
    def invoke_work_shape_menu(self, pos, path):
        """Run the work-shape context menu and pick the action at ``path``."""
        with patch.object(UI["views"], "QMenu", ContextMenuProbe):
            ContextMenuProbe.selected_path = path
            ContextMenuProbe.picked_action = None
            self.view._show_context_menu(pos)
        return ContextMenuProbe.picked_action

    def work_shape_parent_pos(self, name):
        """Return the viewport position over a work shape's parent/name band."""
        index = self.item_index(name)
        _, name_rect = self.delegate._area_rects(self.option(index), index)
        return name_rect.center()

    def test_extract_motion_axis_context_menu_actions(self):
        """The Extract Motion Axis submenu dispatches the combined axis/value."""
        calls = []
        self.view._extract_axis_motion_callback = lambda name, axis: calls.append((name, axis))
        pos = self.work_shape_parent_pos("mouthFix_workShape")
        actions = [
            (("Extract Motion Axis", "X"), "x"),
            (("Extract Motion Axis", "Y"), "y"),
            (("Extract Motion Axis", "Z"), "z"),
            (("Extract Motion Axis", "Positive", "X+"), "x+"),
            (("Extract Motion Axis", "Positive", "Y+"), "y+"),
            (("Extract Motion Axis", "Positive", "Z+"), "z+"),
            (("Extract Motion Axis", "Negative", "X-"), "x-"),
            (("Extract Motion Axis", "Negative", "Y-"), "y-"),
            (("Extract Motion Axis", "Negative", "Z-"), "z-"),
        ]
        for path, axis in actions:
            calls.clear()
            action = self.invoke_work_shape_menu(pos, path)
            self.assertIsNotNone(action, "Missing menu action: %s" % (path,))
            self.assertTrue(action.isEnabled(), "Disabled menu action: %s" % (path,))
            self.assertEqual(calls, [("mouthFix_workShape", axis)], path)

    def test_extract_motion_axis_actions_disabled_without_callback(self):
        """Axis actions are disabled when no extract-axis callback is wired."""
        self.view._extract_axis_motion_callback = None
        pos = self.work_shape_parent_pos("mouthFix_workShape")
        action = self.invoke_work_shape_menu(pos, ("Extract Motion Axis", "X"))
        self.assertIsNotNone(action)
        self.assertFalse(action.isEnabled())

    def test_extract_axis_motion_handler_calls_editor(self):
        """The feature handler forwards the shape name and axis to the editor."""
        host = Mock()
        host.current_editor = Mock()
        host.current_editor.extract_axis_motion_from_work_shape.return_value = "mouthFix_workShape_x+_extracted"
        HANDLERS["_on_work_shape_extract_axis_motion_requested"](host, "mouthFix_workShape", "x+")
        host.current_editor.extract_axis_motion_from_work_shape.assert_called_once_with(
            "mouthFix_workShape", "x+")
        host._reload_work_shapes_from_editor.assert_called_once()
        host._select_work_shape.assert_called_once_with("mouthFix_workShape")
        host._set_status.assert_called_once()

    # ------------------------------------------------------------------
    # Delegate opt-in behavior
    # ------------------------------------------------------------------
    def test_slider_delegate_only_edits_when_view_opts_in(self):
        option = self.option()
        self.assertIsInstance(
            self.delegate.createEditor(self.view.viewport(), option, self.index),
            QtWidgets.QLineEdit,
        )
        plain_view = UI["views"].SliderListView()
        model = self.single_row_model()
        try:
            plain_view.setModel(model)
            plain_delegate = UI["delegates"].SliderItemDelegate(plain_view)
            plain_view.setItemDelegate(plain_delegate)
            self.assertFalse(bool(plain_delegate._slider_value_edit_enabled()))
            self.assertIsNone(
                plain_delegate.createEditor(plain_view.viewport(), option, model.index(0, 0))
            )
        finally:
            plain_view.deleteLater()
            APP.processEvents()

    def single_row_model(self):
        model = QtGui.QStandardItemModel()
        item = QtGui.QStandardItem("shape")
        item.setData("WorkShape", Shape.TypeRole)
        item.setData(0.25, Shape.ValueRole)
        item.setData(True, Shape.EditableRole)
        item.setData(False, Shape.IsHeaderRole)
        model.appendRow(item)
        return model

    def test_opt_in_tree_views_disable_default_edit_triggers(self):
        for view_cls in (UI["views"].ShapeTreeWidget, UI["views"].PrimaryTreeWidget):
            view = view_cls()
            try:
                self.assertTrue(bool(view._enable_slider_value_edit))
                self.assertEqual(
                    view.editTriggers(), QtWidgets.QAbstractItemView.NoEditTriggers
                )
            finally:
                view.deleteLater()
                APP.processEvents()

    def test_tree_view_explicit_edit_opens_value_editor(self):
        """Explicit edit() works on a NoEditTriggers tree with an editable row."""
        view = UI["views"].ShapeTreeWidget()
        try:
            delegate = UI["delegates"].SliderItemDelegate(view)
            view.setItemDelegateForColumn(0, delegate)
            item = QtWidgets.QTreeWidgetItem(["name"])
            item.setData(0, Shape.NameRole, "name")
            item.setData(0, Shape.TypeRole, "PrimaryShape")
            item.setData(0, Shape.ValueRole, 0.5)
            item.setData(0, Shape.EditableRole, True)
            item.setData(0, Shape.IsHeaderRole, False)
            item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsEditable)
            view.addTopLevelItem(item)
            view.resize(300, 100)
            view.show()
            APP.processEvents()
            view.edit(view.indexFromItem(item, 0))
            APP.processEvents()
            self.assertEqual(view.state(), QtWidgets.QAbstractItemView.EditingState)
            editor = view.findChild(QtWidgets.QLineEdit)
            self.assertIsNotNone(editor)
            self.assertEqual(editor.text(), "0.5000")
        finally:
            view.close()
            view.deleteLater()
            APP.processEvents()

    def plain_slider_view(self):
        """Build a standalone SliderListView over a single work-shape row."""
        view = UI["views"].SliderListView()
        model = self.single_row_model()
        view.setModel(model)
        delegate = UI["delegates"].SliderItemDelegate(view)
        view.setItemDelegate(delegate)
        view.resize(520, 200)
        view.show()
        APP.processEvents()
        return view, delegate, model.index(0, 0)

    def test_read_only_slider_view_blocks_drag(self):
        """A read-only slider view does not start a value scrub on press."""
        view, delegate, index = self.plain_slider_view()
        try:
            option = QtWidgets.QStyleOptionViewItem()
            option.rect = view.visualRect(index)
            option.fontMetrics = view.fontMetrics()
            value_rect, _ = delegate._area_rects(option, index)

            view._sliders_read_only = True
            QtTest.QTest.mousePress(
                view.viewport(), Qt.LeftButton, Qt.NoModifier, value_rect.center())
            APP.processEvents()
            self.assertFalse(delegate.is_drag_active())
            QtTest.QTest.mouseRelease(
                view.viewport(), Qt.LeftButton, Qt.NoModifier, value_rect.center())
            APP.processEvents()

            # The same press starts a scrub once the view is interactive again.
            view._sliders_read_only = False
            QtTest.QTest.mousePress(
                view.viewport(), Qt.LeftButton, Qt.NoModifier, value_rect.center())
            APP.processEvents()
            self.assertTrue(delegate.is_drag_active())
            delegate.external_drag_end(value_rect.center().x())
            APP.processEvents()
        finally:
            view.close()
            view.deleteLater()
            APP.processEvents()

    def test_read_only_view_disables_value_edit(self):
        """Read-only wins over the value-edit opt-in and createEditor returns None."""
        view, delegate, index = self.plain_slider_view()
        try:
            view._enable_slider_value_edit = True
            view._sliders_read_only = True
            option = QtWidgets.QStyleOptionViewItem()
            option.rect = view.visualRect(index)
            option.fontMetrics = view.fontMetrics()
            self.assertFalse(delegate._slider_value_edit_enabled())
            self.assertIsNone(
                delegate.createEditor(view.viewport(), option, index))
        finally:
            view.close()
            view.deleteLater()
            APP.processEvents()

    # ------------------------------------------------------------------
    # Split assignment double-click handlers (unchanged behavior)
    # ------------------------------------------------------------------
    def test_split_assignment_name_double_click_sets_pose(self):
        """Double-clicking a child primary name sets that shape to its pose."""
        host = Mock()
        host.current_editor = self.editor
        handler = SPLIT_HANDLERS["_on_split_primaries_item_double_clicked"]
        handler(host, FakeTreeItem("jawOpen", parent=object()), 0)
        host._set_shape_pose_by_name.assert_called_once_with("jawOpen")

    def test_split_assignment_group_and_header_are_ignored(self):
        """Group rows and header-flagged rows do not trigger a pose."""
        host = Mock()
        host.current_editor = self.editor
        handler = SPLIT_HANDLERS["_on_split_primaries_item_double_clicked"]
        handler(host, FakeTreeItem("GroupA", is_header=True, parent=None), 0)
        handler(host, FakeTreeItem("GroupA", is_header=True, parent=object()), 0)
        host._set_shape_pose_by_name.assert_not_called()

    def test_split_assignment_double_click_guards(self):
        """Missing editor, non-zero column, None item, and empty name are ignored."""
        host = Mock()
        handler = SPLIT_HANDLERS["_on_split_primaries_item_double_clicked"]
        item = FakeTreeItem("jawOpen", parent=object())
        host.current_editor = None
        handler(host, item, 0)
        host.current_editor = self.editor
        handler(host, item, 1)
        handler(host, None, 0)
        handler(host, FakeTreeItem("", parent=object()), 0)
        host._set_shape_pose_by_name.assert_not_called()

    # ------------------------------------------------------------------
    # Driver painting and drag removal (unchanged behavior)
    # ------------------------------------------------------------------
    def test_disclosure_is_a_large_filled_triangle(self):
        for expanded in (True, False):
            pixmap = QtGui.QPixmap(self.view.size())
            painter = QtGui.QPainter(pixmap)
            spy = Mock(wraps=painter)
            self.delegate.paint(spy, self.option(), self.index)
            painter.end()
            spy.drawPolygon.assert_called_once()
            polygon = spy.drawPolygon.call_args[0][0]
            self.assertEqual(polygon.count(), 3)
            self.assertGreaterEqual(max(polygon.boundingRect().width(), polygon.boundingRect().height()), 14)
            if expanded:
                self.assertGreater(polygon[2].y(), polygon[0].y())
            else:
                self.assertGreater(polygon[2].x(), polygon[0].x())
            self.assertIn(unittest.mock.call(Qt.NoPen), spy.setPen.call_args_list)
            self.assertIn(unittest.mock.call(self.view.palette().text().color()), spy.setBrush.call_args_list)
            self.view._toggle_drivers(self.index)
            APP.processEvents()

    def test_driver_drag_removes_only_on_outside_release_and_restores_cursor(self):
        removed = []
        self.view.driverRemovalRequested.connect(lambda *args: removed.append(args))
        self.start_removal_drag(1)
        self.assertTrue(self.view._removal_drag_active)
        self.assertEqual(APP.overrideCursor().shape(), Qt.ClosedHandCursor)
        self.move_mouse(self.outside_pos())
        self.assertTrue(self.view._removal_drag_outside)
        self.assertFalse(APP.overrideCursor().pixmap().isNull())
        self.assertEqual(removed, [])
        QtTest.QTest.mouseRelease(self.view.viewport(), Qt.LeftButton, Qt.NoModifier, self.outside_pos())
        self.assertEqual(removed, [("mouthFix_workShape", "lipCornerFunneler")])
        self.assertIsNone(APP.overrideCursor())
        self.assertIsNone(self.view._removal_drag_target)
        self.assertFalse(self.view._removal_press_active)
        self.drop.assert_not_called()

    def test_drag_events_over_another_widget_remove_only_the_source_driver(self):
        other = QtWidgets.QWidget()
        other.move(self.view.pos() + QtCore.QPoint(self.view.width() + 80, 0))
        other.show()
        APP.processEvents()
        removed = []
        self.view.driverRemovalRequested.connect(lambda *args: removed.append(args))
        try:
            self.start_removal_drag()
            self.move_mouse(QtCore.QPoint(10, 10), other)
            self.assertTrue(self.view._removal_drag_outside)
            QtTest.QTest.mouseRelease(other, Qt.LeftButton, Qt.NoModifier, QtCore.QPoint(10, 10))
            self.assertEqual(removed, [("mouthFix_workShape", "lipCornerPuller")])
            self.assertIsNone(APP.overrideCursor())
            self.drop.assert_not_called()
        finally:
            other.close()
            other.deleteLater()

    def test_driver_drag_back_inside_cancels_and_changes_cursor_back(self):
        removed = Mock()
        self.view.driverRemovalRequested.connect(removed)
        pos = self.start_removal_drag()
        self.move_mouse(self.outside_pos())
        self.move_mouse(pos)
        self.assertEqual(APP.overrideCursor().shape(), Qt.ClosedHandCursor)
        self.assertFalse(self.view._removal_drag_outside)
        QtTest.QTest.mouseRelease(self.view.viewport(), Qt.LeftButton, Qt.NoModifier, pos)
        removed.assert_not_called()
        self.assertIsNone(APP.overrideCursor())

    def test_press_without_drag_threshold_cannot_remove(self):
        removed = Mock()
        self.view.driverRemovalRequested.connect(removed)
        pos = self.child_pos()
        QtTest.QTest.mousePress(self.view.viewport(), Qt.LeftButton, Qt.NoModifier, pos)
        self.move_mouse(pos + QtCore.QPoint(1, 0))
        self.assertFalse(self.view._removal_drag_active)
        self.assertIsNone(APP.overrideCursor())
        # Even a far-away release without a drag move must not delete anything.
        QtTest.QTest.mouseRelease(self.view.viewport(), Qt.LeftButton, Qt.NoModifier, self.outside_pos())
        removed.assert_not_called()

    def test_escape_cancels_removal_and_restores_existing_cursor(self):
        removed = Mock()
        self.view.driverRemovalRequested.connect(removed)
        APP.setOverrideCursor(Qt.WaitCursor)
        try:
            self.start_removal_drag()
            self.move_mouse(self.outside_pos())
            QtTest.QTest.keyClick(self.view, Qt.Key_Escape)
            self.assertEqual(APP.overrideCursor().shape(), Qt.WaitCursor)
            QtTest.QTest.mouseRelease(self.view.viewport(), Qt.LeftButton, Qt.NoModifier, self.outside_pos())
            removed.assert_not_called()
        finally:
            APP.restoreOverrideCursor()

    def test_reset_hide_and_deactivation_cancel_driver_drag(self):
        removed = Mock()
        self.view.driverRemovalRequested.connect(removed)
        self.start_removal_drag()
        self.items = build_work_shape_items(FakeEditor(), self.view)
        self.assertIsNone(APP.overrideCursor())
        self.assertIsNone(self.view._removal_drag_target)
        QtTest.QTest.mouseRelease(self.view.viewport(), Qt.LeftButton, Qt.NoModifier, self.outside_pos())
        self.index = self.item_index("mouthFix_workShape")
        self.start_removal_drag()
        QtWidgets.QApplication.sendEvent(APP, QtCore.QEvent(QtCore.QEvent.ApplicationDeactivate))
        self.assertIsNone(APP.overrideCursor())
        self.assertIsNone(self.view._removal_drag_target)
        QtTest.QTest.mouseRelease(self.view.viewport(), Qt.LeftButton, Qt.NoModifier, self.outside_pos())
        self.start_removal_drag()
        self.view.hide()
        self.assertIsNone(APP.overrideCursor())
        self.assertIsNone(self.view._removal_drag_target)
        removed.assert_not_called()

    def test_removal_handler_preserves_other_drivers_and_parent(self):
        host = Mock()
        host.current_editor = self.editor

        def disconnect(work_shape, names):
            self.assertIsNone(APP.overrideCursor())
            self.editor.drivers[work_shape] = [
                name for name in self.editor.drivers[work_shape] if name not in names]

        self.editor.disconnect_work_shape_drivers = Mock(side_effect=disconnect)
        host._reload_work_shapes_from_editor.side_effect = self.reload_items
        self.reload_items()
        self.index = self.item_index("mouthFix_workShape")
        self.view.driverRemovalRequested.connect(lambda work, driver:
            HANDLERS["_on_work_shape_driver_removal_requested"](host, work, driver))
        self.start_removal_drag(1)
        self.move_mouse(self.outside_pos())
        QtTest.QTest.mouseRelease(self.view.viewport(), Qt.LeftButton, Qt.NoModifier, self.outside_pos())
        self.editor.disconnect_work_shape_drivers.assert_called_once_with(
            "mouthFix_workShape", ["lipCornerFunneler"])
        self.index = self.item_index("mouthFix_workShape")
        self.assertEqual(self.index.data(Roles.DriverNamesRole), ("lipCornerPuller",))
        host._stop_active_blendshape_trackers.assert_called_once()
        host._start_active_blendshape_trackers.assert_called_once()
        APP.processEvents()
        self.start_removal_drag()
        self.move_mouse(self.outside_pos())
        QtTest.QTest.mouseRelease(self.view.viewport(), Qt.LeftButton, Qt.NoModifier, self.outside_pos())
        self.index = self.item_index("mouthFix_workShape")
        self.assertTrue(self.index.isValid())
        self.assertEqual(self.index.data(Roles.DriverNamesRole), ())
        self.assertEqual(self.view.topLevelItemCount(), 3)
        self.assertEqual(self.delegate.sizeHint(self.option(), self.index).height(), 24)

    def test_removal_error_restores_cursor_and_restarts_trackers(self):
        host = Mock()
        host.current_editor.disconnect_work_shape_drivers.side_effect = RuntimeError("Locked")
        self.view.driverRemovalRequested.connect(lambda work, driver:
            HANDLERS["_on_work_shape_driver_removal_requested"](host, work, driver))
        self.start_removal_drag()
        self.move_mouse(self.outside_pos())
        QtTest.QTest.mouseRelease(self.view.viewport(), Qt.LeftButton, Qt.NoModifier, self.outside_pos())
        self.assertIsNone(APP.overrideCursor())
        host._start_active_blendshape_trackers.assert_called_once()
        host._reload_work_shapes_from_editor.assert_not_called()
        self.assertTrue(host._set_status.call_args[1]["error"])
        self.assertEqual(len(self.index.data(Roles.DriverNamesRole)), 2)

    def test_paint_and_hit_testing_do_not_query_editor(self):
        self.editor.get_work_shape_driver_shapes = Mock(side_effect=AssertionError("uncached query"))
        option = self.option()
        original_rect = QtCore.QRect(option.rect)
        pixmap = QtGui.QPixmap(self.view.size())
        painter = QtGui.QPainter(pixmap)
        self.delegate.paint(painter, option, self.index)
        painter.end()
        self.assertEqual(option.rect, original_rect)
        self.assertEqual(self.delegate.driver_at_pos(option, self.index, self.child_pos(1)),
                         "lipCornerFunneler")
        self.editor.get_work_shape_driver_shapes.assert_not_called()


if __name__ == "__main__":
    unittest.main()
