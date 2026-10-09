"""Focused Active Shapes delegate painting tests, runnable without Maya.

Run: python releases/maya/BlueSteel/unittest/activeShapesUiUt.py

The Active Shapes panel is a read-only monitor list. Its delegate must show
only the shape name and numeric value: the slider track/fill and the gold
shape-type indicator bar are suppressed. These tests reuse the isolated
Qt/module harness from ``workShapesUiUt`` so the production delegate code runs
without the full main-window bootstrap.
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from workShapesUiUt import (  # noqa: E402  (path setup must come first)
    APP,
    Qt,
    QtCore,
    QtGui,
    QtWidgets,
    Shape,
    UI,
)

SliderDelegate = UI["delegates"].SliderItemDelegate
ActiveDelegate = UI["delegates"].ActiveShapesItemDelegate

INDICATOR_GOLD = (220, 190, 76)
TRACK_BG = (57, 57, 57)


class ActiveShapesDelegateTests(unittest.TestCase):
    ROW_WIDTH = 520
    ROW_HEIGHT = 24

    def setUp(self):
        self.view = QtWidgets.QListView()
        self.view._panel_icon_slots = 2
        self.model = QtGui.QStandardItemModel()
        item = QtGui.QStandardItem("comboShape")
        item.setData("ComboShape", Shape.TypeRole)
        # Render with zero progress so the whole track stays in its flat
        # background colour, giving a stable pixel to probe.
        item.setData(0.0, Shape.ValueRole)
        item.setData(True, Shape.EditableRole)
        self.model.appendRow(item)
        self.index = self.model.index(0, 0)

    def tearDown(self):
        self.view.deleteLater()
        APP.processEvents()

    def option(self, width=None):
        option = QtWidgets.QStyleOptionViewItem()
        option.rect = QtCore.QRect(0, 0, self.ROW_WIDTH if width is None else width, self.ROW_HEIGHT)
        option.palette = self.view.palette()
        option.font = self.view.font()
        option.fontMetrics = self.view.fontMetrics()
        return option

    def render(self, delegate, option):
        pixmap = QtGui.QPixmap(self.ROW_WIDTH, self.ROW_HEIGHT)
        pixmap.fill(Qt.transparent)
        painter = QtGui.QPainter(pixmap)
        delegate.paint(painter, option, self.index)
        painter.end()
        return pixmap.toImage()

    def rgb(self, image, point):
        color = QtGui.QColor(image.pixel(point.x(), point.y()))
        return color.red(), color.green(), color.blue()

    def test_active_delegate_hides_track_and_indicator(self):
        self.assertTrue(ActiveDelegate._hides_value_track)
        self.assertTrue(ActiveDelegate._hides_type_indicator)

        option = self.option()
        active = ActiveDelegate(self.view)
        base = SliderDelegate(self.view)

        active_image = self.render(active, option)
        base_image = self.render(base, option)

        # The gold indicator lives at the far-left of the row.
        indicator = QtCore.QPoint(option.rect.left() + 2, option.rect.center().y())
        # Sample the empty left side of the value column (value text is right-aligned).
        value_rect = base.value_rect_for(self.index, option)
        track = QtCore.QPoint(value_rect.left() + 2, option.rect.center().y())

        # Sanity: the base delegate paints both elements we are suppressing.
        self.assertEqual(self.rgb(base_image, indicator), INDICATOR_GOLD)
        self.assertEqual(self.rgb(base_image, track), TRACK_BG)

        # The Active Shapes delegate paints neither.
        self.assertNotEqual(self.rgb(active_image, indicator), INDICATOR_GOLD)
        self.assertNotEqual(self.rgb(active_image, track), TRACK_BG)

    def test_plain_shape_also_suppresses_track(self):
        self.index.model().setData(self.index, "PrimaryShape", Shape.TypeRole)
        option = self.option()
        active = ActiveDelegate(self.view)
        base = SliderDelegate(self.view)

        base_image = self.render(base, option)
        active_image = self.render(active, option)

        value_rect = base.value_rect_for(self.index, option)
        track = QtCore.QPoint(value_rect.left() + 2, option.rect.center().y())
        self.assertEqual(self.rgb(base_image, track), TRACK_BG)
        self.assertNotEqual(self.rgb(active_image, track), TRACK_BG)

    def test_active_value_width_is_fixed(self):
        self.assertTrue(ActiveDelegate._uses_fixed_value_width)
        self.assertFalse(SliderDelegate._uses_fixed_value_width)

        active = ActiveDelegate(self.view)
        base = SliderDelegate(self.view)
        wide = self.option(520)
        narrow = self.option(150)

        active_wide = active.value_rect_for(self.index, wide).width()
        active_narrow = active.value_rect_for(self.index, narrow).width()
        # The value area hugs the value text and no longer tracks list width.
        self.assertEqual(active_wide, active_narrow)
        self.assertAlmostEqual(active_wide, active._value_text_width(wide), delta=1)

        base_wide = base.value_rect_for(self.index, wide).width()
        base_narrow = base.value_rect_for(self.index, narrow).width()
        self.assertNotEqual(base_wide, base_narrow)
        self.assertGreater(base_wide, active_wide)

    def test_default_delegate_flags_unchanged(self):
        # Every other view keeps the slider track and indicator.
        self.assertFalse(SliderDelegate._hides_value_track)
        self.assertFalse(SliderDelegate._hides_type_indicator)


if __name__ == "__main__":
    unittest.main()
