"""Focused Sliders Drop Box drag-out removal tests, runnable without Maya.

Run: python releases/maya/BlueSteel/unittest/primaryDropBoxUiUt.py

The Sliders Drop Box is a ``PrimaryDropTreeWidget`` (an item-based
``QTreeWidget``). Dragging a primary row outside the view and releasing should
remove every selected entry, mirroring the Work Shapes driver-removal gesture.
These tests reuse the isolated Qt/module harness from ``workShapesUiUt`` so the
production view/delegate code runs without the full main-window bootstrap.
"""
from __future__ import annotations

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
)

DropView = UI["views"].PrimaryDropTreeWidget
SliderDelegate = UI["delegates"].SliderItemDelegate
OptionRect = UI["qt"].OptionRect


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


if __name__ == "__main__":
    unittest.main()
