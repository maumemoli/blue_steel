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
    env.MAYA_VERSION = MAYA_VERSION
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
