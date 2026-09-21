"""Focused Work Shapes UI tests, runnable without Maya.

Run: python releases/maya/BlueSteel/unittest/workShapesUiUt.py
Requires PySide6 (or PySide2). Real UI modules/Qt widgets are loaded in an
isolated package; only Maya, editor API, and icon dependencies are stubbed.
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
Model = UI["models"].WorkShapeItemsModel
Delegate = UI["delegates"].WorkShapeItemDelegate
View = UI["views"].WorkShapesListView


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
             "_on_work_shape_driver_removal_requested"}
    methods = [node for cls in tree.body if isinstance(cls, ast.ClassDef)
               for node in cls.body if isinstance(node, ast.FunctionDef) and node.name in names]
    namespace = {
        "QModelIndex": QtCore.QModelIndex,
        "ShapeItemsModel": UI["models"].ShapeItemsModel,
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
    namespace = {"ShapeItemsModel": UI["models"].ShapeItemsModel}
    exec(compile(ast.Module(body=methods, type_ignores=[]), str(path), "exec"), namespace)
    return namespace


SPLIT_HANDLERS = split_handlers()


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
        if role == Model.IsHeaderRole:
            return self._is_header
        if role == Model.NameRole:
            return self._name
        return None


class WorkShapesUiTests(unittest.TestCase):
    def setUp(self):
        self.editor = FakeEditor()
        self.model = Model()
        self.model.rebuild_from_editor(self.editor)
        self.drop = Mock()
        self.view = View(self.drop, Mock(), Mock(), Mock())
        self.view.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.view.setModel(self.model)
        self.delegate = Delegate(self.view)
        self.view.setItemDelegate(self.delegate)
        self.view.resize(520, 300)
        self.view.show()
        APP.processEvents()
        self.index = self.model.index_by_name("mouthFix_workShape")

    def tearDown(self):
        self.view.close()
        self.view.deleteLater()
        APP.processEvents()

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

    def test_flat_model_and_zero_one_multiple_drivers(self):
        self.assertEqual(self.model.rowCount(), 3)
        expected = [(), ("jawOpen",), ("lipCornerPuller", "lipCornerFunneler")]
        for row, drivers in enumerate(expected):
            index = self.model.index(row, 0)
            self.assertEqual(index.data(Model.DriverNamesRole), drivers)
            self.assertFalse(index.parent().isValid())
            self.assertEqual(self.model.rowCount(index), 0)
            self.assertEqual(self.view.visualRect(index).height(), 24 + len(drivers) * 20)
        self.assertTrue(self.model.index(0, 0).data(Model.ConnectedRole))
        self.assertFalse(self.index.data(Model.ConnectedRole))
        self.assertTrue(self.index.data(Model.DriverConnectedRole))

    def test_zero_driver_parent_paint_and_geometry_unchanged(self):
        index = self.model.index(0, 0)
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
            self.model, self.index, child_in_slider_column, option.rect))
        editor.deleteLater()

    def test_disclosure_changes_height_without_selection_or_parent_actions(self):
        pose, double = [], []
        self.view.driverPoseRequested.connect(pose.append)
        self.view.doubleClicked.connect(double.append)
        self.view.setCurrentIndex(self.model.index(0, 0))
        selected = self.view.selectionModel().selectedIndexes()
        control = self.delegate.disclosure_rect(self.option(), self.index).center()
        self.click(control, double=True)
        self.assertFalse(self.view.drivers_expanded(self.index))
        self.assertEqual(self.view.visualRect(self.index).height(), 24)
        self.assertEqual(self.view.selectionModel().selectedIndexes(), selected)
        self.assertFalse(pose)
        self.assertFalse(double)
        self.assertIsNone(self.delegate.driver_at_pos(self.option(), self.index, self.child_pos()))
        self.click(control)
        self.assertEqual(self.view.visualRect(self.index).height(), 64)

    def test_each_child_double_click_requests_exact_driver_only(self):
        pose, double, mute, edit, mesh = [], [], [], [], []
        self.view.driverPoseRequested.connect(pose.append)
        self.view.doubleClicked.connect(double.append)
        self.delegate.muteToggleRequested.connect(lambda *args: mute.append(args))
        self.delegate.workEditModeToggleRequested.connect(lambda *args: edit.append(args))
        self.delegate.connectedMeshRequested.connect(mesh.append)
        self.view.setCurrentIndex(self.model.index(0, 0))
        selected = self.view.selectionModel().selectedIndexes()
        for child, name in enumerate(self.editor.drivers["mouthFix_workShape"]):
            pos = self.child_pos(child)
            self.assertEqual(self.delegate.driver_at_pos(self.option(), self.index, pos), name)
            self.click(pos, double=True)
        self.assertEqual(pose, ["lipCornerPuller", "lipCornerFunneler"])
        self.assertEqual(self.view.selectionModel().selectedIndexes(), selected)
        self.assertFalse(double or mute or edit or mesh)
        self.assertFalse(self.delegate.is_drag_active())
        self.editor.work_blendshape.set_weight_value.assert_not_called()

    def test_dragging_from_child_does_not_rubber_band_select_parents(self):
        self.view.setCurrentIndex(self.model.index(0, 0))
        selected = self.view.selectionModel().selectedIndexes()
        QtTest.QTest.mousePress(self.view.viewport(), Qt.LeftButton, Qt.NoModifier, self.child_pos())
        QtTest.QTest.mouseMove(self.view.viewport(), self.view.visualRect(self.model.index(1, 0)).center())
        QtTest.QTest.mouseRelease(self.view.viewport(), Qt.LeftButton, Qt.NoModifier, self.child_pos())
        self.assertEqual(self.view.selectionModel().selectedIndexes(), selected)
        self.assertFalse(self.delegate.is_drag_active())
        self.assertFalse(self.view._driver_press_active)

    def test_children_and_disclosure_are_not_context_or_drop_targets(self):
        self.assertIsNone(self.view._receiver_name_at_pos(self.child_pos()))
        disclosure = self.delegate.disclosure_rect(self.option(), self.index).center()
        self.assertIsNone(self.view._receiver_name_at_pos(disclosure))
        _, name = self.delegate._area_rects(self.option(), self.index)
        self.assertEqual(self.view._receiver_name_at_pos(name.center()), "mouthFix_workShape")

    def test_parent_controls_remain_clickable_in_narrow_panel(self):
        self.view.resize(180, 300)
        APP.processEvents()
        self.model.set_connected_state_local("mouthFix_workShape", True)
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
        self.view.scrollTo(self.index, QtWidgets.QAbstractItemView.PositionAtBottom)
        APP.processEvents()
        pose = []
        self.view.driverPoseRequested.connect(pose.append)
        self.click(self.child_pos(1), double=True)
        self.assertEqual(pose, ["lipCornerFunneler"])

    def test_connection_notifications_refresh_names_and_layout_even_when_still_connected(self):
        changes = []
        self.model.dataChanged.connect(lambda first, last, roles: changes.append(roles))
        self.editor.drivers["mouthFix_workShape"].append("jawOpen")
        self.model.set_driver_connected_state_local("mouthFix_workShape", True)
        APP.processEvents()
        self.assertEqual(self.index.data(Model.DriverNamesRole)[-1], "jawOpen")
        self.assertIn(Model.DriverNamesRole, changes[-1])
        self.assertEqual(self.view.visualRect(self.index).height(), 84)
        self.assertEqual(self.model.index_by_name("mouthFix_workShape"), self.index)
        self.model.set_driver_connected_state_local("mouthFix_workShape", False)
        APP.processEvents()
        self.assertEqual(self.index.data(Model.DriverNamesRole), ())
        self.assertEqual(self.view.visualRect(self.index).height(), 24)
        self.assertTrue(self.delegate.disclosure_rect(self.option(), self.index).isNull())
        self.assertEqual(self.model.rowCount(), 3)

    def test_unresolvable_driver_graph_keeps_parent_usable(self):
        self.editor.get_work_shape_driver_shapes = Mock(side_effect=RuntimeError("Missing input1D"))
        self.model.rebuild_from_editor(self.editor)
        self.index = self.model.index_by_name("mouthFix_workShape")
        self.assertTrue(self.index.isValid())
        self.assertTrue(self.index.data(Model.DriverConnectedRole))
        self.assertEqual(self.index.data(Model.DriverNamesRole), ())
        self.assertEqual(self.delegate.sizeHint(self.option(), self.index).height(), 24)
        self.model.set_value_by_name("mouthFix_workShape", 0.5)
        self.assertEqual(self.model.get_value("mouthFix_workShape"), 0.5)

    def test_expansion_survives_refresh_but_not_editor_change_or_removal(self):
        self.view._toggle_drivers(self.index)
        self.model.rebuild_from_editor(self.editor)
        self.index = self.model.index_by_name("mouthFix_workShape")
        self.assertFalse(self.view.drivers_expanded(self.index))
        self.model.rebuild_from_editor(FakeEditor())
        self.index = self.model.index_by_name("mouthFix_workShape")
        self.assertTrue(self.view.drivers_expanded(self.index))
        self.view._toggle_drivers(self.index)
        self.model.rebuild_from_editor(None)
        self.assertFalse(self.view._collapsed_driver_names)

    def test_pose_handler_and_parent_alt_double_click(self):
        host = Mock()
        host.current_editor = self.editor
        host._work_shape_model = self.model
        host.shapes_list_active_button.isChecked.return_value = True
        self.view.driverPoseRequested.connect(
            lambda name: HANDLERS["_on_work_shape_driver_pose_requested"](host, name))
        self.view.doubleClicked.connect(
            lambda index: HANDLERS["_on_work_shapes_double_clicked"](host, index))
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
        host._begin_inline_workshape_rename.assert_called_once_with(self.index)

    def test_value_area_double_click_starts_numeric_edit_without_rename(self):
        """Double-clicking the slider bar opens the numeric value editor."""
        host = Mock()
        host.current_editor = self.editor
        host._work_shape_model = self.model
        self.view.doubleClicked.connect(
            lambda index: HANDLERS["_on_work_shapes_double_clicked"](host, index))
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
        host._work_shape_model = self.model
        self.view.doubleClicked.connect(
            lambda index: HANDLERS["_on_work_shapes_double_clicked"](host, index))
        _, name_rect = self.delegate._area_rects(self.option(), self.index)
        self.click(name_rect.center(), double=True)
        host._begin_inline_workshape_rename.assert_called_once_with(self.index)
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

    def test_slider_delegate_only_edits_when_view_opts_in(self):
        """Views without the opt-in flag never create a value editor."""
        option = self.option()
        self.assertIsInstance(
            self.delegate.createEditor(self.view.viewport(), option, self.index),
            QtWidgets.QLineEdit,
        )
        plain_view = UI["views"].SliderListView()
        try:
            plain_view.setModel(self.model)
            plain_delegate = UI["delegates"].SliderItemDelegate(plain_view)
            plain_view.setItemDelegate(plain_delegate)
            self.assertFalse(bool(plain_delegate._slider_value_edit_enabled()))
            self.assertIsNone(
                plain_delegate.createEditor(plain_view.viewport(), option, self.index)
            )
        finally:
            plain_view.deleteLater()
            APP.processEvents()

    def test_opt_in_tree_views_disable_default_edit_triggers(self):
        """Opted-in trees only allow the slider double-click to open an editor."""
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
            item.setData(0, Model.NameRole, "name")
            item.setData(0, Model.TypeRole, "PrimaryShape")
            item.setData(0, Model.ValueRole, 0.5)
            item.setData(0, Model.EditableRole, True)
            item.setData(0, Model.IsHeaderRole, False)
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
        """Build a standalone SliderListView with the work-shape model."""
        view = UI["views"].SliderListView()
        view.setModel(self.model)
        delegate = UI["delegates"].SliderItemDelegate(view)
        view.setItemDelegate(delegate)
        view.resize(520, 200)
        view.show()
        APP.processEvents()
        return view, delegate

    def test_read_only_slider_view_blocks_drag(self):
        """A read-only slider view does not start a value scrub on press."""
        view, delegate = self.plain_slider_view()
        try:
            option = QtWidgets.QStyleOptionViewItem()
            option.rect = view.visualRect(self.index)
            option.fontMetrics = view.fontMetrics()
            value_rect, _ = delegate._area_rects(option, self.index)

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
        view, delegate = self.plain_slider_view()
        try:
            view._enable_slider_value_edit = True
            view._sliders_read_only = True
            self.assertFalse(delegate._slider_value_edit_enabled())
            self.assertIsNone(
                delegate.createEditor(view.viewport(), self.option(), self.index))
        finally:
            view.close()
            view.deleteLater()
            APP.processEvents()

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

    def move_mouse(self, pos, receiver=None):
        # Qt 5's offscreen QTest.mouseMove does not deliver moves outside the
        # widget (there is no native mouse grab). Supply the real event's
        # local/window/global coordinates and held-button state explicitly.
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
        self.assertTrue(self.view._driver_drag_active)
        self.assertEqual(APP.overrideCursor().shape(), Qt.ClosedHandCursor)
        self.move_mouse(self.outside_pos())
        self.assertTrue(self.view._driver_drag_outside)
        self.assertFalse(APP.overrideCursor().pixmap().isNull())
        self.assertEqual(removed, [])
        QtTest.QTest.mouseRelease(self.view.viewport(), Qt.LeftButton, Qt.NoModifier, self.outside_pos())
        self.assertEqual(removed, [("mouthFix_workShape", "lipCornerFunneler")])
        self.assertIsNone(APP.overrideCursor())
        self.assertIsNone(self.view._driver_drag_target)
        self.assertFalse(self.view._driver_press_active)
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
            self.assertTrue(self.view._driver_drag_outside)
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
        self.assertFalse(self.view._driver_drag_outside)
        QtTest.QTest.mouseRelease(self.view.viewport(), Qt.LeftButton, Qt.NoModifier, pos)
        removed.assert_not_called()
        self.assertIsNone(APP.overrideCursor())

    def test_press_without_drag_threshold_cannot_remove(self):
        removed = Mock()
        self.view.driverRemovalRequested.connect(removed)
        pos = self.child_pos()
        QtTest.QTest.mousePress(self.view.viewport(), Qt.LeftButton, Qt.NoModifier, pos)
        self.move_mouse(pos + QtCore.QPoint(1, 0))
        self.assertFalse(self.view._driver_drag_active)
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
        self.model.rebuild_from_editor(FakeEditor())
        self.assertIsNone(APP.overrideCursor())
        self.assertIsNone(self.view._driver_drag_target)
        QtTest.QTest.mouseRelease(self.view.viewport(), Qt.LeftButton, Qt.NoModifier, self.outside_pos())
        self.index = self.model.index_by_name("mouthFix_workShape")
        self.start_removal_drag()
        QApplication = QtWidgets.QApplication
        QApplication.sendEvent(APP, QtCore.QEvent(QtCore.QEvent.ApplicationDeactivate))
        self.assertIsNone(APP.overrideCursor())
        self.assertIsNone(self.view._driver_drag_target)
        QtTest.QTest.mouseRelease(self.view.viewport(), Qt.LeftButton, Qt.NoModifier, self.outside_pos())
        self.start_removal_drag()
        self.view.hide()
        self.assertIsNone(APP.overrideCursor())
        self.assertIsNone(self.view._driver_drag_target)
        removed.assert_not_called()

    def test_removal_handler_preserves_other_drivers_and_parent(self):
        host = Mock()
        host.current_editor = self.editor
        def disconnect(work_shape, names):
            self.assertIsNone(APP.overrideCursor())
            self.editor.drivers[work_shape] = [
                name for name in self.editor.drivers[work_shape] if name not in names]
        self.editor.disconnect_work_shape_drivers = Mock(side_effect=disconnect)
        host._reload_work_shapes_from_editor.side_effect = lambda: self.model.rebuild_from_editor(self.editor)
        self.view.driverRemovalRequested.connect(lambda work, driver:
            HANDLERS["_on_work_shape_driver_removal_requested"](host, work, driver))
        self.start_removal_drag(1)
        self.move_mouse(self.outside_pos())
        QtTest.QTest.mouseRelease(self.view.viewport(), Qt.LeftButton, Qt.NoModifier, self.outside_pos())
        self.editor.disconnect_work_shape_drivers.assert_called_once_with(
            "mouthFix_workShape", ["lipCornerFunneler"])
        self.index = self.model.index_by_name("mouthFix_workShape")
        self.assertEqual(self.index.data(Model.DriverNamesRole), ("lipCornerPuller",))
        host._stop_active_blendshape_trackers.assert_called_once()
        host._start_active_blendshape_trackers.assert_called_once()
        APP.processEvents()
        self.start_removal_drag()
        self.move_mouse(self.outside_pos())
        QtTest.QTest.mouseRelease(self.view.viewport(), Qt.LeftButton, Qt.NoModifier, self.outside_pos())
        self.index = self.model.index_by_name("mouthFix_workShape")
        self.assertTrue(self.index.isValid())
        self.assertEqual(self.index.data(Model.DriverNamesRole), ())
        self.assertEqual(self.model.rowCount(), 3)
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
        self.assertEqual(len(self.index.data(Model.DriverNamesRole)), 2)

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
