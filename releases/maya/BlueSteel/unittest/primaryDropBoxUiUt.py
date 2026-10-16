"""Focused Sliders Drop Box drag-out removal tests, runnable without Maya.

Run: python releases/maya/BlueSteel/unittest/primaryDropBoxUiUt.py

The Sliders Drop Box is a ``PrimaryDropTreeWidget`` (an item-based
``QTreeWidget``). Dragging a primary row outside the view and releasing should
remove every selected entry, mirroring the Work Shapes driver-removal gesture.
These tests reuse the isolated Qt/module harness from ``workShapesUiUt`` so the
production view/delegate code runs without the full main-window bootstrap.
"""
from __future__ import annotations

import ast
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from workShapesUiUt import (  # noqa: E402  (path setup must come first)
    APP,
    Qt,
    QtCore,
    QtGui,
    QtWidgets,
    QtTest,
    Shape,
    UI,
    UI_PATH,
    PRIMARY_TREE_NAME_ROLE,
)

DropView = UI["views"].PrimaryDropTreeWidget
SliderDelegate = UI["delegates"].SliderItemDelegate
SubsetProxy = UI["models"].PrimarySubsetProxyModel
OptionRect = UI["qt"].OptionRect


def drop_tree_handlers():
    """Load the production drop-tree order methods without the full bootstrap."""
    path = UI_PATH / "shapesFeatureMixin.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = {
        "_apply_primary_drop_tree_filter",
        "_reorder_primary_drop_tree_items",
        "_selected_primary_drop_shape_names",
        "_on_primary_drop_move_requested",
    }
    methods = [
        node
        for cls in tree.body
        if isinstance(cls, ast.ClassDef)
        for node in cls.body
        if isinstance(node, ast.FunctionDef) and node.name in names
    ]
    namespace = {"PRIMARY_TREE_NAME_ROLE": PRIMARY_TREE_NAME_ROLE}
    exec(compile(ast.Module(body=methods, type_ignores=[]), str(path), "exec"), namespace)
    return namespace


DROP_HANDLERS = {
    name: value for name, value in drop_tree_handlers().items() if callable(value)
}


class DropTreeHost:
    """Minimal host exposing the production drop-tree order methods."""

    def __init__(self, view, proxy):
        self.primary_drop_view = view
        self._primary_subset_proxy = proxy
        self._primary_drop_tree_items = {}
        self.status = []

    def _update_info_labels(self):
        pass

    def _set_status(self, *args, **kwargs):
        self.status.append((args, kwargs))


for _name, _function in DROP_HANDLERS.items():
    setattr(DropTreeHost, _name, _function)



class PrimaryDropBoxTests(unittest.TestCase):
    def setUp(self):
        self.drop = mock.Mock()
        self.remove = mock.Mock()
        self.view = DropView(self.drop, self.remove)
        self.view.resize(320, 260)
        self.delegate = SliderDelegate(self.view)
        self.view.setItemDelegateForColumn(0, self.delegate)

        self.names = ["alpha", "beta", "gamma"]
        for index, name in enumerate(self.names):
            item = QtWidgets.QTreeWidgetItem([name])
            item.setData(0, Shape.NameRole, name)
            item.setData(0, Shape.TypeRole, "PrimaryShape")
            item.setData(0, Shape.ValueRole, float(index) / 2.0)
            item.setData(0, Shape.EditableRole, True)
            self.view.addTopLevelItem(item)

        self.view.show()
        APP.processEvents()

    def tearDown(self):
        while APP.overrideCursor() is not None:
            APP.restoreOverrideCursor()
        self.view.close()
        self.view.deleteLater()
        APP.processEvents()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def index_for(self, name):
        for row in range(self.view.topLevelItemCount()):
            item = self.view.topLevelItem(row)
            if item.data(0, Shape.NameRole) == name:
                return self.view.indexFromItem(item, 0)
        return QtCore.QModelIndex()

    def option_for(self, index):
        return OptionRect(self.view.visualRect(index), self.view.fontMetrics())

    def name_pos(self, name="beta"):
        index = self.index_for(name)
        _, text_rect = self.delegate._area_rects(self.option_for(index), index)
        return text_rect.center()

    def value_pos(self, name="beta"):
        index = self.index_for(name)
        return self.delegate.value_rect_for(index, self.option_for(index)).center()

    def item_pos(self, name, ratio=0.5):
        """Return a viewport point inside ``name``'s row at ``ratio`` of its height."""
        rect = self.view.visualRect(self.index_for(name))
        return QtCore.QPoint(rect.center().x(), int(rect.top() + rect.height() * ratio))

    def blank_pos(self):
        """Return a viewport point below every row (empty drop space)."""
        viewport = self.view.viewport()
        return QtCore.QPoint(viewport.width() // 2, viewport.height() - 2)

    def outside_pos(self):
        return QtCore.QPoint(self.view.width() + 40, self.name_pos().y())

    def select_all(self):
        for row in range(self.view.topLevelItemCount()):
            self.view.topLevelItem(row).setSelected(True)
        APP.processEvents()

    def move_mouse(self, pos, receiver=None):
        receiver = self.view.viewport() if receiver is None else receiver
        global_pos = receiver.mapToGlobal(pos)
        window_pos = receiver.window().mapFromGlobal(global_pos)
        event = QtGui.QMouseEvent(
            QtCore.QEvent.MouseMove,
            QtCore.QPointF(pos),
            QtCore.QPointF(window_pos),
            QtCore.QPointF(global_pos),
            Qt.NoButton,
            Qt.LeftButton,
            Qt.NoModifier,
        )
        APP.sendEvent(receiver, event)
        APP.processEvents()

    def press(self, pos=None):
        pos = self.name_pos() if pos is None else pos
        QtTest.QTest.mousePress(self.view.viewport(), Qt.LeftButton, Qt.NoModifier, pos)
        APP.processEvents()
        return pos

    def release(self, pos):
        QtTest.QTest.mouseRelease(self.view.viewport(), Qt.LeftButton, Qt.NoModifier, pos)
        APP.processEvents()

    # ------------------------------------------------------------------
    # Drag-out removal
    # ------------------------------------------------------------------
    def test_drag_outside_removes_every_selected_entry(self):
        self.select_all()
        pos = self.press()
        self.move_mouse(self.outside_pos())
        self.assertTrue(self.view._removal_drag_active)
        self.assertTrue(self.view._removal_drag_outside)
        self.assertIsNotNone(APP.overrideCursor())
        self.assertFalse(APP.overrideCursor().pixmap().isNull())
        self.remove.assert_not_called()

        self.release(self.outside_pos())
        self.remove.assert_called_once()
        self.assertCountEqual(self.remove.call_args[0][0], self.names)
        self.assertIsNone(APP.overrideCursor())
        self.assertIsNone(self.view._removal_drag_target)
        self.assertFalse(self.view._removal_drag_active)
        self.drop.assert_not_called()

    def test_drag_back_inside_cancels_removal_and_restores_cursor(self):
        pos = self.press()
        self.move_mouse(self.outside_pos())
        self.move_mouse(pos)
        self.assertFalse(self.view._removal_drag_outside)
        self.assertIsNotNone(APP.overrideCursor())
        self.assertEqual(APP.overrideCursor().shape(), Qt.ClosedHandCursor)

        self.release(pos)
        self.remove.assert_not_called()
        self.assertIsNone(APP.overrideCursor())

    def test_press_without_drag_threshold_cannot_remove(self):
        pos = self.press()
        self.move_mouse(pos + QtCore.QPoint(1, 0))
        self.assertFalse(self.view._removal_drag_active)
        self.assertIsNone(APP.overrideCursor())

        self.release(self.outside_pos())
        self.remove.assert_not_called()

    def test_escape_cancels_and_restores_existing_cursor(self):
        APP.setOverrideCursor(Qt.WaitCursor)
        try:
            self.press()
            self.move_mouse(self.outside_pos())
            QtTest.QTest.keyClick(self.view, Qt.Key_Escape)
            self.assertEqual(APP.overrideCursor().shape(), Qt.WaitCursor)

            self.release(self.outside_pos())
            self.remove.assert_not_called()
        finally:
            APP.restoreOverrideCursor()

    def test_value_area_press_does_not_arm_removal(self):
        pos = self.press(self.value_pos())
        self.assertIsNone(self.view._removal_drag_target)
        self.assertTrue(self.delegate.is_drag_active())

        self.release(pos)
        self.assertIsNone(APP.overrideCursor())
        self.remove.assert_not_called()

    def test_lock_icon_press_does_not_arm_removal(self):
        index = self.index_for("beta")
        item = self.view.itemFromIndex(index)
        item.setData(0, Shape.LockIconVisibleRole, True)
        item.setData(0, Shape.LockedRole, False)
        APP.processEvents()
        lock_rect = self.delegate._lock_icon_rect(self.option_for(index), index)
        self.assertFalse(lock_rect.isNull())

        self.press(lock_rect.center())
        self.assertIsNone(self.view._removal_drag_target)
        self.move_mouse(self.outside_pos())

        self.release(self.outside_pos())
        self.remove.assert_not_called()

    # ------------------------------------------------------------------
    # Driver drops (release over a Work Shape receiver)
    # ------------------------------------------------------------------
    def test_release_over_driver_connects_and_keeps_entry(self):
        callback = mock.Mock()
        self.view.set_driver_drop_resolver(lambda _pos: "mouthFix_workShape")
        self.view.set_driver_drop_callback(callback)

        self.press(self.name_pos("beta"))
        outside = self.outside_pos()
        self.move_mouse(outside)
        self.assertTrue(self.view._removal_drag_active)
        self.assertTrue(self.view._removal_drag_over_driver)
        self.assertEqual(APP.overrideCursor().shape(), Qt.DragCopyCursor)

        self.release(outside)
        self.remove.assert_not_called()
        self.drop.assert_not_called()
        callback.assert_called_once()
        receiver, names = callback.call_args[0]
        self.assertEqual(receiver, "mouthFix_workShape")
        self.assertEqual(list(names), ["beta"])
        # Copy semantics: the slider stays in the drop box.
        self.assertIsNotNone(self.index_for("beta"))
        self.assertIsNone(self.view._removal_drag_target)
        self.assertIsNone(APP.overrideCursor())

    def test_multi_select_driver_drop_connects_every_selected(self):
        callback = mock.Mock()
        self.view.set_driver_drop_resolver(lambda _pos: "target_work_shape")
        self.view.set_driver_drop_callback(callback)

        self.select_all()
        self.press(self.name_pos("beta"))
        outside = self.outside_pos()
        self.move_mouse(outside)
        self.release(outside)

        self.remove.assert_not_called()
        callback.assert_called_once()
        receiver, names = callback.call_args[0]
        self.assertEqual(receiver, "target_work_shape")
        self.assertCountEqual(list(names), self.names)
        for name in self.names:
            self.assertIsNotNone(self.index_for(name))

    def test_release_outside_without_driver_target_still_removes(self):
        callback = mock.Mock()
        self.view.set_driver_drop_resolver(lambda _pos: None)
        self.view.set_driver_drop_callback(callback)

        self.press(self.name_pos("beta"))
        outside = self.outside_pos()
        self.move_mouse(outside)
        self.assertFalse(self.view._removal_drag_over_driver)
        self.assertFalse(APP.overrideCursor().pixmap().isNull())

        self.release(outside)
        self.remove.assert_called_once()
        callback.assert_not_called()

    def test_driver_hover_clears_when_reentering_box(self):
        self.view.set_driver_drop_resolver(lambda _pos: "target_work_shape")
        self.view.set_driver_drop_callback(mock.Mock())

        inside = self.press(self.name_pos("beta"))
        self.move_mouse(self.outside_pos())
        self.assertTrue(self.view._removal_drag_over_driver)

        self.move_mouse(inside)
        self.assertFalse(self.view._removal_drag_over_driver)
        self.assertEqual(APP.overrideCursor().shape(), Qt.ClosedHandCursor)
        self.release(inside)
        self.remove.assert_not_called()

    def test_resolver_only_without_callback_still_removes(self):
        self.view.set_driver_drop_resolver(lambda _pos: "target_work_shape")

        self.press(self.name_pos("beta"))
        outside = self.outside_pos()
        self.move_mouse(outside)
        self.assertFalse(self.view._removal_drag_over_driver)

        self.release(outside)
        self.remove.assert_called_once()

    # ------------------------------------------------------------------
    # Drag-to-reorder (inside release)
    # ------------------------------------------------------------------
    def test_drag_inside_emits_reorder_request(self):
        emitted = []
        self.view.primaryMoveRequested.connect(lambda *args: emitted.append(args))

        pos = self.press(self.name_pos("beta"))
        target = self.item_pos("alpha", 0.25)  # before alpha
        self.move_mouse(target)
        self.assertTrue(self.view._removal_drag_active)
        self.assertIsNotNone(self.view._drop_target_item)
        self.assertEqual(self.view._drop_position, "before")

        self.release(target)
        self.remove.assert_not_called()
        self.drop.assert_not_called()
        self.assertEqual(len(emitted), 1)
        names, target_name, position = emitted[0]
        self.assertEqual(list(names), ["beta"])
        self.assertEqual(target_name, "alpha")
        self.assertEqual(position, "before")
        self.assertIsNone(self.view._drop_target_item)
        self.assertIsNone(APP.overrideCursor())

    def test_drag_inside_blank_space_appends(self):
        emitted = []
        self.view.primaryMoveRequested.connect(lambda *args: emitted.append(args))

        pos = self.press(self.name_pos("beta"))
        blank = self.blank_pos()
        self.move_mouse(blank)
        self.assertIsNone(self.view._drop_target_item)

        self.release(blank)
        self.remove.assert_not_called()
        self.assertEqual(len(emitted), 1)
        names, target_name, position = emitted[0]
        self.assertEqual(list(names), ["beta"])
        self.assertEqual(target_name, "")
        self.assertEqual(position, "root")

    def test_multi_select_drag_moves_every_selected_entry(self):
        emitted = []
        self.view.primaryMoveRequested.connect(lambda *args: emitted.append(args))

        self.select_all()
        pos = self.press(self.name_pos("beta"))
        target = self.item_pos("gamma", 0.75)  # after gamma
        self.move_mouse(target)
        self.release(target)
        self.remove.assert_not_called()
        self.assertEqual(len(emitted), 1)
        names, target_name, position = emitted[0]
        self.assertCountEqual(list(names), self.names)
        self.assertEqual(target_name, "gamma")
        self.assertEqual(position, "after")

    def test_escape_clears_reorder_indicator(self):
        pos = self.press(self.name_pos("beta"))
        target = self.item_pos("alpha", 0.25)
        self.move_mouse(target)
        self.assertIsNotNone(self.view._drop_target_item)

        QtTest.QTest.keyClick(self.view, Qt.Key_Escape)
        self.assertIsNone(self.view._drop_target_item)
        self.assertIsNone(self.view._removal_drag_target)

        self.release(target)
        self.remove.assert_not_called()

    # ------------------------------------------------------------------
    # Cancellation paths
    # ------------------------------------------------------------------
    def test_model_reset_cancels_active_drag(self):
        self.press()
        outside = self.outside_pos()
        self.move_mouse(outside)
        self.assertTrue(self.view._removal_drag_active)

        self.view.clear()
        self.assertIsNone(APP.overrideCursor())
        self.assertIsNone(self.view._removal_drag_target)

        self.release(outside)
        self.remove.assert_not_called()

    def test_hide_and_application_deactivate_cancel_active_drag(self):
        self.press()
        self.move_mouse(self.outside_pos())
        self.view.hide()
        self.assertIsNone(APP.overrideCursor())
        self.assertIsNone(self.view._removal_drag_target)

        self.view.show()
        APP.processEvents()
        self.press()
        self.move_mouse(self.outside_pos())
        QtWidgets.QApplication.sendEvent(APP, QtCore.QEvent(QtCore.QEvent.ApplicationDeactivate))
        self.assertIsNone(APP.overrideCursor())
        self.assertIsNone(self.view._removal_drag_target)

        self.release(self.outside_pos())
        self.remove.assert_not_called()


class PrimarySubsetProxyModelTests(unittest.TestCase):
    """Ordered-name-set behavior of the Sliders Drop Box backing model."""

    def setUp(self):
        self.proxy = SubsetProxy()

    def test_selected_names_preserve_insertion_order(self):
        self.proxy.add_selected_names(["gamma", "alpha", "beta"])
        self.assertEqual(self.proxy.selected_names(), ["gamma", "alpha", "beta"])

    def test_add_does_not_duplicate(self):
        self.proxy.add_selected_names(["alpha", "beta"])
        self.proxy.add_selected_names(["beta", "gamma"])
        self.assertEqual(self.proxy.selected_names(), ["alpha", "beta", "gamma"])

    def test_remove_keeps_remaining_order(self):
        self.proxy.add_selected_names(["gamma", "alpha", "beta"])
        self.assertEqual(self.proxy.remove_selected_names(["alpha"]), 1)
        self.assertEqual(self.proxy.selected_names(), ["gamma", "beta"])

    def test_reorder_before_target(self):
        self.proxy.add_selected_names(["alpha", "beta", "gamma"])
        self.assertTrue(self.proxy.reorder_selected_names(["gamma"], "alpha", "before"))
        self.assertEqual(self.proxy.selected_names(), ["gamma", "alpha", "beta"])

    def test_reorder_after_target_keeps_relative_order(self):
        self.proxy.add_selected_names(["alpha", "beta", "gamma", "delta"])
        self.assertTrue(
            self.proxy.reorder_selected_names(["gamma", "alpha"], "delta", "after")
        )
        self.assertEqual(self.proxy.selected_names(), ["beta", "delta", "alpha", "gamma"])

    def test_reorder_root_appends(self):
        self.proxy.add_selected_names(["alpha", "beta", "gamma"])
        self.assertTrue(self.proxy.reorder_selected_names(["alpha"], "", "root"))
        self.assertEqual(self.proxy.selected_names(), ["beta", "gamma", "alpha"])

    def test_reorder_unknown_target_is_a_no_op(self):
        self.proxy.add_selected_names(["alpha", "beta"])
        self.assertFalse(self.proxy.reorder_selected_names(["alpha"], "missing", "before"))
        self.assertEqual(self.proxy.selected_names(), ["alpha", "beta"])

    def test_reorder_that_does_not_change_order_returns_false(self):
        self.proxy.add_selected_names(["alpha", "beta"])
        self.assertFalse(self.proxy.reorder_selected_names(["alpha"], "beta", "before"))
        self.assertEqual(self.proxy.selected_names(), ["alpha", "beta"])


class DropTreeOrderTests(unittest.TestCase):
    """Order enforcement shared by the production drop-tree handlers."""

    def setUp(self):
        self.proxy = SubsetProxy()
        self.view = QtWidgets.QTreeWidget()
        self.view.setColumnCount(1)
        self.view.setHeaderHidden(True)
        self.host = DropTreeHost(self.view, self.proxy)

    def tearDown(self):
        self.view.close()
        self.view.deleteLater()
        APP.processEvents()

    def add_item(self, name):
        item = QtWidgets.QTreeWidgetItem([name])
        item.setData(0, PRIMARY_TREE_NAME_ROLE, name)
        self.view.addTopLevelItem(item)
        self.host._primary_drop_tree_items[name] = item
        return item

    def visible_names(self):
        return [
            str(self.view.topLevelItem(i).data(0, PRIMARY_TREE_NAME_ROLE) or "")
            for i in range(self.view.topLevelItemCount())
            if not self.view.topLevelItem(i).isHidden()
        ]

    def test_filter_shows_visible_entries_in_stored_order(self):
        for name in ("alpha", "beta", "gamma"):
            self.add_item(name)
        self.proxy.add_selected_names(["gamma", "alpha"])

        self.host._apply_primary_drop_tree_filter()

        self.assertEqual(self.visible_names(), ["gamma", "alpha"])
        self.assertTrue(self.host._primary_drop_tree_items["beta"].isHidden())

    def test_move_handler_updates_store_and_view_order(self):
        for name in ("alpha", "beta", "gamma"):
            self.add_item(name)
        self.proxy.add_selected_names(["alpha", "beta", "gamma"])

        self.host._on_primary_drop_move_requested(["gamma"], "alpha", "before")

        self.assertEqual(self.proxy.selected_names(), ["gamma", "alpha", "beta"])
        self.assertEqual(self.visible_names(), ["gamma", "alpha", "beta"])

    def test_order_survives_items_being_reinserted(self):
        for name in ("alpha", "beta", "gamma"):
            self.add_item(name)
        self.proxy.add_selected_names(["alpha", "beta", "gamma"])
        self.host._apply_primary_drop_tree_filter()
        self.host._on_primary_drop_move_requested(["gamma"], "alpha", "before")
        self.assertEqual(self.visible_names(), ["gamma", "alpha", "beta"])

        # Simulate a rebuild that re-creates the rows alphabetically.
        self.view.clear()
        self.host._primary_drop_tree_items.clear()
        for name in ("alpha", "beta", "gamma"):
            self.add_item(name)
        self.host._apply_primary_drop_tree_filter()

        self.assertEqual(self.visible_names(), ["gamma", "alpha", "beta"])

    def test_reorder_preserves_selection(self):
        for name in ("alpha", "beta", "gamma"):
            self.add_item(name)
        self.proxy.add_selected_names(["alpha", "beta", "gamma"])

        self.host._apply_primary_drop_tree_filter()
        self.host._primary_drop_tree_items["alpha"].setSelected(True)
        self.host._on_primary_drop_move_requested(["alpha"], "gamma", "after")

        self.assertEqual(self.visible_names(), ["beta", "gamma", "alpha"])
        self.assertEqual(
            [
                str(item.data(0, PRIMARY_TREE_NAME_ROLE) or "")
                for item in self.view.selectedItems()
            ],
            ["alpha"],
        )


class DropTreeGestureTests(unittest.TestCase):
    """End-to-end drag-to-reorder through the real view and its handler."""

    def setUp(self):
        self.proxy = SubsetProxy()
        self.view = DropView(lambda names: None, lambda names: None)
        self.view.resize(320, 260)
        self.delegate = SliderDelegate(self.view)
        self.view.setItemDelegateForColumn(0, self.delegate)
        self.host = DropTreeHost(self.view, self.proxy)
        self.view.primaryMoveRequested.connect(self.host._on_primary_drop_move_requested)
        for name in ("alpha", "beta", "gamma"):
            item = QtWidgets.QTreeWidgetItem([name])
            item.setData(0, PRIMARY_TREE_NAME_ROLE, name)
            item.setData(0, Shape.NameRole, name)
            item.setData(0, Shape.TypeRole, "PrimaryShape")
            item.setData(0, Shape.ValueRole, 0.0)
            item.setData(0, Shape.EditableRole, True)
            self.view.addTopLevelItem(item)
            self.host._primary_drop_tree_items[name] = item
        self.proxy.add_selected_names(["alpha", "beta", "gamma"])
        self.view.show()
        APP.processEvents()

    def tearDown(self):
        while APP.overrideCursor() is not None:
            APP.restoreOverrideCursor()
        self.view.close()
        self.view.deleteLater()
        APP.processEvents()

    def index_for(self, name):
        for row in range(self.view.topLevelItemCount()):
            item = self.view.topLevelItem(row)
            if item.data(0, PRIMARY_TREE_NAME_ROLE) == name:
                return self.view.indexFromItem(item, 0)
        return QtCore.QModelIndex()

    def visible_names(self):
        return [
            str(self.view.topLevelItem(i).data(0, PRIMARY_TREE_NAME_ROLE) or "")
            for i in range(self.view.topLevelItemCount())
            if not self.view.topLevelItem(i).isHidden()
        ]

    def move_mouse(self, pos):
        receiver = self.view.viewport()
        global_pos = receiver.mapToGlobal(pos)
        window_pos = receiver.window().mapFromGlobal(global_pos)
        event = QtGui.QMouseEvent(
            QtCore.QEvent.MouseMove,
            QtCore.QPointF(pos),
            QtCore.QPointF(window_pos),
            QtCore.QPointF(global_pos),
            Qt.NoButton,
            Qt.LeftButton,
            Qt.NoModifier,
        )
        APP.sendEvent(receiver, event)
        APP.processEvents()

    def test_gesture_reorders_view_and_store(self):
        beta_index = self.index_for("beta")
        _, text_rect = self.delegate._area_rects(
            OptionRect(self.view.visualRect(beta_index), self.view.fontMetrics()), beta_index
        )
        press_pos = text_rect.center()
        alpha_rect = self.view.visualRect(self.index_for("alpha"))
        target_pos = QtCore.QPoint(
            alpha_rect.center().x(), int(alpha_rect.top() + alpha_rect.height() * 0.25)
        )

        QtTest.QTest.mousePress(self.view.viewport(), Qt.LeftButton, Qt.NoModifier, press_pos)
        APP.processEvents()
        self.move_mouse(target_pos)
        QtTest.QTest.mouseRelease(self.view.viewport(), Qt.LeftButton, Qt.NoModifier, target_pos)
        APP.processEvents()

        self.assertEqual(self.proxy.selected_names(), ["beta", "alpha", "gamma"])
        self.assertEqual(self.visible_names(), ["beta", "alpha", "gamma"])
        self.assertEqual(
            [
                str(item.data(0, PRIMARY_TREE_NAME_ROLE) or "")
                for item in self.view.selectedItems()
            ],
            ["beta"],
        )


if __name__ == "__main__":
    unittest.main()
