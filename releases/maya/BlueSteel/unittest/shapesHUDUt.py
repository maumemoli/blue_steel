"""Maya-side checks for the Blue Steel shapes HUD (``bsShapesHUD`` + hudManager).

Run in a DISPOSABLE Maya scene (tests create new scenes without saving).
A GUI session is required for native HUD and viewport visibility tests::

    python -m unittest blue_steel.unittest.shapesHUDUt

Covered:
    * ``hudManager.sections_overlapping`` mapping onto the 2x5 HUD grid.
    * ``bsShapesHUD.compute_layout`` scaling / offset behaviour.
    * The plugin node is never written to the scene (``doNotWrite``).
    * Toggling the HUD hides only overlapping visible HUDs and restores only
      the HUDs it hid (an already hidden HUD stays hidden).
"""

import os
import sys
import unittest

_RELEASE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_PACKAGE_ROOT = os.path.join(_RELEASE_ROOT, "scripts")
_PLUGIN_PATH = os.path.join(_RELEASE_ROOT, "plug-ins", "bsShapesHUD.py")
if _PACKAGE_ROOT not in sys.path:
    sys.path.insert(0, _PACKAGE_ROOT)
_PLUGIN_DIR = os.path.dirname(_PLUGIN_PATH)
if _PLUGIN_DIR not in sys.path:
    sys.path.insert(0, _PLUGIN_DIR)

from maya import cmds
import maya.api.OpenMaya as om

from blue_steel.api import hudManager

TEST_HUD_VISIBLE = "bsUtHudVisible"
TEST_HUD_HIDDEN = "bsUtHudHidden"
TEST_HUD_FAR = "bsUtHudFar"


def _load_plugin():
    if not cmds.pluginInfo(hudManager.PLUGIN_NAME, query=True, loaded=True):
        cmds.loadPlugin(_PLUGIN_PATH, quiet=True)


def _make_blendshape():
    base = cmds.polyCube(name="hudUtBase")[0]
    target = cmds.polyCube(name="hudUtTarget")[0]
    blend = cmds.blendShape(target, base, name="hudUtBlend")[0]
    cmds.setAttr(f"{blend}.{target}", 0.5)
    return blend


class TestSectionsOverlapping(unittest.TestCase):
    def test_top_left(self):
        self.assertEqual(hudManager.sections_overlapping((0, 0, 100, 100), 1000, 800), {0})

    def test_spans_top_row(self):
        self.assertEqual(hudManager.sections_overlapping((0, 0, 1000, 50), 1000, 800),
                         {0, 1, 2, 3, 4})

    def test_bottom_right(self):
        self.assertEqual(hudManager.sections_overlapping((900, 700, 50, 50), 1000, 800), {9})

    def test_tall_column_covers_both_rows(self):
        self.assertEqual(hudManager.sections_overlapping((10, 10, 50, 780), 1000, 800), {0, 5})

    def test_outside(self):
        self.assertEqual(hudManager.sections_overlapping((2000, 0, 10, 10), 1000, 800), set())


class TestLayout(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import bsShapesHUD
        cls.plugin = bsShapesHUD

    def test_offset(self):
        layout = self.plugin.compute_layout("t", ["a: 1"], 1000, 500, 0.5, 0.2, 1.0)
        x, y, _, _ = layout["rect"]
        self.assertAlmostEqual(x, 500.0)
        self.assertAlmostEqual(y, 100.0)

    def test_font_scale_does_not_resize_frame(self):
        small = self.plugin.compute_layout("t", ["a: 1"], 1000, 500, 0, 0, 1.0)
        big = self.plugin.compute_layout("t", ["a: 1"], 1000, 500, 0, 0, 2.0)
        self.assertEqual(big["rect"], small["rect"])
        self.assertGreater(big["font"], small["font"])

    def test_width_does_not_use_pair_kerning(self):
        # VP2 advances glyphs independently; Qt's shaped AV width is shorter.
        width = self.plugin.text_width
        self.assertGreaterEqual(width("AV" * 30, 19),
                                width("A" * 30, 19) + width("V" * 30, 19) - 2)

    def test_draw_sets_complete_font_style_before_text(self):
        from unittest.mock import MagicMock, call
        import maya.api.OpenMayaRender as omr
        manager, context = MagicMock(), MagicMock()
        context.getViewportDimensions.return_value = (0, 0, 1280, 720)
        content = dict(title="HUD", lines=["shape: 0.5"], offset_x=.01, offset_y=.02,
                       scale=1.0, frame_width=.4, frame_height=.5,
                       text_color=om.MColor((1, 1, 1, 1)), title_color=om.MColor((1, 1, 0, 1)),
                       background_opacity=0.0, show_frame=False)
        self.plugin.BsShapesHUDDrawOverride._draw_content(content, manager, context)
        first_text = next(i for i, method in enumerate(manager.method_calls) if method[0] == "text2d")
        for style_call in (call.setFontWeight(omr.MUIDrawManager.kWeightNormal),
                           call.setFontStretch(omr.MUIDrawManager.kStretchUnstretched),
                           call.setFontIncline(omr.MUIDrawManager.kInclineNormal)):
            self.assertIn(style_call, manager.method_calls[:first_text])

    def test_frame_resize_does_not_change_font(self):
        small = self.plugin.compute_layout("t", ["a: 1"], 1000, 500, 0, 0, 1.0, .2, .3)
        big = self.plugin.compute_layout("t", ["a: 1"] * 20, 1000, 500, 0, 0, 1.0, .8, .7)
        self.assertEqual(big["font"], small["font"])
        self.assertEqual(small["rect"], (0, 0, 200, 150))
        self.assertEqual(big["rect"], (0, 0, 800, 350))

    def _fixed_capacity_layout(self, count, columns=1, rows=2):
        p = self.plugin
        font = 13
        title_font = int(round(font * p.TITLE_SCALE))
        column_width = p.text_width("shape: 1", font)
        width = 2 * p.PADDING * font + columns * column_width + (columns - 1) * p.COLUMN_GAP * font
        height = 2 * p.PADDING * font + title_font * p.LINE_SPACING + rows * font * p.LINE_SPACING
        return p.compute_layout("t", ["shape: 1"] * count, 1280, 720, 0, 0, 1.0,
                                width / 1280, height / 720)

    def test_exact_fit_and_one_extra_shape(self):
        exact = self._fixed_capacity_layout(2)
        self.assertFalse(exact["overflow"])
        self.assertEqual(exact["visible_count"], 2)
        self.assertNotEqual(exact["items"][-1][2], "...")
        extra = self._fixed_capacity_layout(3)
        self.assertTrue(extra["overflow"])
        self.assertEqual(extra["visible_count"], 1)
        self.assertEqual(extra["items"][-1][2], "...")
        self.assertEqual(len(extra["items"]), len(exact["items"]))

    def test_columns_and_final_marker(self):
        exact = self._fixed_capacity_layout(4, columns=2)
        self.assertEqual(len({item[0] for item in exact["items"][1:]}), 2)
        self.assertEqual(exact["visible_count"], 4)
        self.assertFalse(exact["overflow"])
        extra = self._fixed_capacity_layout(5, columns=2)
        self.assertEqual(extra["items"][-1][2], "...")
        self.assertEqual(extra["visible_count"], 3)

    def test_empty_content_does_not_change_frame(self):
        empty = self.plugin.compute_layout("t", [], 1280, 720, .1, .1, 1.0)
        full = self.plugin.compute_layout("t", ["x: 1"] * 1000, 1280, 720, .1, .1, 1.0)
        self.assertEqual(empty["rect"], full["rect"])
        self.assertFalse(empty["overflow"])
        self.assertTrue(full["overflow"])
        self.assertEqual(full["items"][-1][2], "...")

    def test_long_labels_and_partial_offscreen_frame_stay_bounded(self):
        p = self.plugin
        layout = p.compute_layout("An extremely long title " * 20,
                                  ["VeryLongShapeName" * 30 + ": 0.5"] * 50,
                                  1280, 720, .85, .8, 1.0, .4, .5)
        x, y, w, h = layout["rect"]
        pad = layout["font"] * p.PADDING
        for ix, iy, text, font in layout["items"]:
            self.assertGreaterEqual(ix, max(0, x + pad))
            self.assertLessEqual(ix + p.text_width(text, font), min(1280, x + w - pad) + 1e-6)
            self.assertLessEqual(iy, min(720, y + h - pad) + 1e-6)
        self.assertEqual(layout["items"][-1][2], "...")
        self.assertTrue(any(item[2].endswith(": 0.5") for item in layout["items"][1:-1]))

    def test_short_frame_shows_only_overflow_marker(self):
        p = self.plugin
        height = 13 * (p.LINE_SPACING + 2 * p.PADDING)
        layout = p.compute_layout("title", ["a: 1"] * 10, 1280, 720, 0, 0, 1.0,
                                  .2, height / 720)
        self.assertEqual([item[2] for item in layout["items"]], ["..."])
        self.assertFalse(layout["title_drawn"])
        self.assertTrue(layout["overflow"])

    def test_impossibly_small_frame_does_not_spill(self):
        layout = self.plugin.compute_layout("t", ["a: 1"], 1000, 500, 0, 0, 20, .001, .001)
        self.assertEqual(layout["items"], [])
        self.assertTrue(layout["overflow"])

    def test_proportional_to_viewport(self):
        a = self.plugin.compute_layout("title", ["x: 1"] * 3, 1000, 500, 0.1, 0.1, 2.0)["rect"]
        b = self.plugin.compute_layout("title", ["x: 1"] * 3, 2000, 1000, 0.1, 0.1, 2.0)["rect"]
        for va, vb in zip(a, b):
            self.assertAlmostEqual(va * 2.0, vb, delta=4.0)

    def test_wraps_into_columns(self):
        lines = ["shape{0}: 1".format(i) for i in range(200)]
        layout = self.plugin.compute_layout("t", lines, 1920, 1080, 0, 0, 1.0)
        self.assertLessEqual(layout["rect"][3], 1080)


class TestPluginHud(unittest.TestCase):
    def setUp(self):
        cmds.file(new=True, force=True)
        _load_plugin()
        self.blend = _make_blendshape()
        self.saved_settings = hudManager.load_settings()
        self.saved_frame_size = hudManager.load_frame_size()
        hudManager.save_settings(0.01, 0.02, 1.0)
        hudManager.save_frame_size(hudManager.DEFAULT_FRAME_WIDTH, hudManager.DEFAULT_FRAME_HEIGHT)
        self.panel = None
        self.panel_settings = None
        if not cmds.about(batch=True):
            panels = cmds.getPanel(type="modelPanel")
            self.panel = next((p for p in panels if p in cmds.getPanel(visiblePanels=True)), panels[0])
            self.panel_settings = {
                "locators": cmds.modelEditor(self.panel, q=True, locators=True),
                "pluginShapes": cmds.modelEditor(self.panel, q=True, pluginShapes=True),
            }
            cmds.modelEditor(self.panel, e=True, locators=True, pluginShapes=True)
            cmds.isolateSelect(self.panel, state=False)
            cmds.setFocus(self.panel)

    def tearDown(self):
        hudManager.hide(restore=True)
        hudManager.save_settings(*self.saved_settings)
        hudManager.save_frame_size(*self.saved_frame_size)
        if self.panel:
            cmds.isolateSelect(self.panel, state=False)
            cmds.modelEditor(self.panel, e=True, **self.panel_settings)
        for name in (TEST_HUD_VISIBLE, TEST_HUD_HIDDEN, TEST_HUD_FAR):
            if cmds.headsUpDisplay(name, query=True, exists=True):
                cmds.headsUpDisplay(name, remove=True)

    def test_node_not_written(self):
        shape = hudManager.create(self.blend)
        self.assertIsNotNone(shape)
        sel = om.MSelectionList()
        sel.add(shape)
        self.assertFalse(om.MFnDependencyNode(sel.getDependNode(0)).canBeWritten())

    def test_frame_size_persists_independently(self):
        hudManager.create(self.blend)
        hudManager.set_frame_size(.25, .35, save=True, refresh=False)
        self.assertAlmostEqual(hudManager.get_transform()[2], 1.0)
        hudManager.set_transform(.1, .2, 1.7, save=True, refresh=False)
        self.assertAlmostEqual(hudManager.get_frame_size()[0], .25)
        hudManager.delete()
        hudManager.create(self.blend)
        self.assertAlmostEqual(hudManager.get_frame_size()[0], .25)
        self.assertAlmostEqual(hudManager.get_frame_size()[1], .35)
        self.assertAlmostEqual(hudManager.get_transform()[2], 1.7)
        rect = hudManager.query_rect(1000, 800)
        for actual, expected in zip(rect, (100, 160, 250, 280)):
            self.assertAlmostEqual(actual, expected, places=4)
        hudManager.reset_transform(save=False)
        self.assertAlmostEqual(hudManager.get_frame_size()[0], hudManager.DEFAULT_FRAME_WIDTH)
        self.assertAlmostEqual(hudManager.get_frame_size()[1], hudManager.DEFAULT_FRAME_HEIGHT)
        self.assertAlmostEqual(hudManager.get_transform()[2], hudManager.DEFAULT_SCALE)

    def test_plugin_filter_registered(self):
        self.assertTrue(cmds.pluginDisplayFilter(hudManager.DISPLAY_FILTER_NAME, exists=True))
        self.assertEqual(cmds.pluginInfo(hudManager.PLUGIN_NAME, q=True, version=True),
                         hudManager.PLUGIN_VERSION)

    def _capture_buffer(self):
        """Read the actual VP2 buffer as an owning QImage."""
        import maya.api.OpenMayaUI as omui
        import tempfile
        if int(cmds.about(version=True)) >= 2025:
            from PySide6.QtGui import QImage
        else:
            from PySide2.QtGui import QImage
        cmds.refresh(force=True)
        view = omui.M3dView.getM3dViewFromModelPanel(self.panel)
        image = om.MImage()
        view.readColorBuffer(image, True)
        # Keep test output inside this checkout, not the user's temp/prefs.
        with tempfile.TemporaryDirectory(dir=os.path.dirname(__file__)) as temp:
            path = os.path.join(temp, "hud.png")
            image.writeToFile(path, "png")
            return QImage(path)

    def _title_pixel_count(self):
        """Count the actual gold HUD glyphs in the VP2 color buffer."""
        capture = self._capture_buffer()
        count = 0
        for y in range(min(capture.height(), 200)):
            for x in range(min(capture.width(), 700)):
                color = capture.pixelColor(x, y)
                if color.red() > 170 and 120 < color.green() < 240 and color.blue() < 115:
                    count += 1
        return count

    @unittest.skipIf(cmds.about(batch=True), "VP2 color buffer requires a GUI")
    def test_rendered_overflow_marker_and_text_stay_inside_frame(self):
        import bsShapesHUD as plugin
        cmds.hide("hudUtBase", "hudUtTarget")
        blend = cmds.createNode("blendShape", name="overflowUtBlend")
        lines = []
        for i in range(80):
            alias = "shape{:02d}".format(i)
            cmds.setAttr(blend + ".weight[{}]".format(i), .5)
            cmds.aliasAttr(alias, blend + ".weight[{}]".format(i))
            lines.append(alias + ": 0.5")
        hudManager.show(blend)
        hudManager.set_transform(.1, .1, 1.0, refresh=False)
        hudManager.set_frame_size(.18, .16, refresh=False)
        # A distinct body color makes actual glyph pixels unambiguous.
        color_plug = hudManager._get_plug(hudManager.get_hud_shape(), "textColor")
        for i, value in enumerate((0.0, 1.0, 0.0)):
            color_plug.child(i).setFloat(value)
        image = self._capture_buffer()
        layout = plugin.compute_layout(blend, lines, image.width(), image.height(),
                                       .1, .1, 1.0, .18, .16)
        self.assertTrue(layout["overflow"])
        self.assertEqual(layout["items"][-1][2], "...")
        fx, fy, fw, fh = layout["rect"]
        mx, my, text, font = layout["items"][-1]
        marker_width = plugin.text_width(text, font)
        body_pixels = outside_pixels = marker_pixels = 0
        for y in range(image.height()):
            for x in range(image.width()):
                color = image.pixelColor(x, y)
                if color.green() > 160 and color.red() < 100 and color.blue() < 100:
                    body_pixels += 1
                    if not (fx - 1 <= x <= fx + fw + 1 and fy - 1 <= y <= fy + fh + 1):
                        outside_pixels += 1
                    if mx - 1 <= x <= mx + marker_width + 1 and my - font * 1.5 <= y <= my + 2:
                        marker_pixels += 1
        self.assertGreater(body_pixels, 20)
        self.assertEqual(outside_pixels, 0)
        self.assertGreater(marker_pixels, 0)

    @unittest.skipIf(cmds.about(batch=True), "VP2 color buffer requires a GUI")
    def test_long_combo_labels_leave_rendered_column_gutters_clear(self):
        """Regression for mixed/long labels from newSplitMaps.mb, without the asset."""
        import math
        import bsShapesHUD as plugin
        cmds.hide("hudUtBase", "hudUtTarget")
        blend = cmds.createNode("blendShape", name="columnUtBlend")
        stems = ["mouthLipCornerPuller", "eyesLidTightener_eyesLookDown_eyesLookRight_eyesUpperLidRaiser",
                 "eyesClosedR_eyesLidTightener_eyesLookDown_eyesLookRight", "AVATARToffeeWWWiii"]
        lines = []
        for i in range(80):
            alias = stems[i % len(stems)] + "{:02d}".format(i)
            cmds.setAttr(blend + ".weight[{}]".format(i), .5)
            cmds.aliasAttr(alias, blend + ".weight[{}]".format(i))
            lines.append(alias + ": 0.5")
        hudManager.show(blend)
        hudManager.set_frame_size(.94, .35, refresh=False)
        color_plug = hudManager._get_plug(hudManager.get_hud_shape(), "textColor")
        for i, value in enumerate((1.0, 0.0, 1.0)):
            color_plug.child(i).setFloat(value)
        for scale in (.65, 1.0, 1.4):
            hudManager.set_transform(.01, .02, scale, refresh=False)
            image = self._capture_buffer()
            layout = plugin.compute_layout(blend, lines, image.width(), image.height(),
                                           .01, .02, scale, .94, .35)
            self.assertGreaterEqual(len(layout["columns"]), 2)
            first = layout["columns"][0]
            body_ink = 0
            for y in range(math.ceil(first[1]), math.ceil(first[1] + layout["font"] * plugin.LINE_SPACING)):
                for x in range(math.ceil(first[0]), math.floor(first[0] + first[2])):
                    color = image.pixelColor(x, y)
                    if (color.red() > 80 and color.blue() > 80
                            and color.red() > 1.5 * color.green() and color.blue() > 1.5 * color.green()):
                        body_ink += 1
            self.assertGreater(body_ink, 10, "The body must actually render for a gutter check")
            for left, right in zip(layout["columns"], layout["columns"][1:]):
                ink = 0
                for y in range(math.ceil(left[1]), math.floor(left[1] + left[3])):
                    for x in range(math.ceil(left[0] + left[2] + 1), math.floor(right[0] - 1)):
                        color = image.pixelColor(x, y)
                        if (color.red() > 80 and color.blue() > 80
                                and color.red() > 1.5 * color.green()
                                and color.blue() > 1.5 * color.green()):
                            ink += 1
                self.assertEqual(ink, 0, "Rendered text spilled into a column gutter")

    @unittest.skipIf(cmds.about(batch=True), "VP2 color buffer requires a GUI")
    def test_visible_with_locators_disabled(self):
        cmds.modelEditor(self.panel, e=True, locators=False)
        hudManager.show(self.blend)
        self.assertFalse(cmds.modelEditor(self.panel, q=True, locators=True))
        self.assertGreater(self._title_pixel_count(), 20)
        # The dedicated HUD filter still lets the user explicitly hide it.
        cmds.modelEditor(self.panel, e=True, pluginObjects=(hudManager.DISPLAY_FILTER_NAME, False))
        self.assertEqual(self._title_pixel_count(), 0)
        cmds.modelEditor(self.panel, e=True, pluginObjects=(hudManager.DISPLAY_FILTER_NAME, True))
        # The dedicated filter also works independently of the generic plugin
        # shape switch (the common "meshes only" viewport configuration).
        cmds.modelEditor(self.panel, e=True, pluginShapes=False)
        hudManager.ensure_panels_show_hud()
        self.assertGreater(self._title_pixel_count(), 20)

    @unittest.skipIf(cmds.about(batch=True), "Isolate Select requires a GUI")
    def test_visible_in_isolation_and_after_retoggle(self):
        cmds.select("hudUtBase", replace=True)
        cmds.isolateSelect(self.panel, state=True)
        cmds.isolateSelect(self.panel, addSelected=True)
        original_selection = cmds.ls(selection=True, long=True)
        for _ in range(2):
            hudManager.show(self.blend)
            self.assertGreater(self._title_pixel_count(), 20)
            self.assertEqual(cmds.ls(selection=True, long=True), original_selection)
            self.assertTrue(cmds.isolateSelect(self.panel, q=True, state=True))
            hudManager.hide()
        self.assertFalse(hudManager._viewport_watch_timer.isActive())

    @unittest.skipIf(cmds.about(batch=True), "Isolate Select requires a GUI")
    def test_isolation_enabled_after_show(self):
        hudManager.show(self.blend)
        cmds.select("hudUtBase", replace=True)
        cmds.isolateSelect(self.panel, state=True)
        cmds.isolateSelect(self.panel, addSelected=True)
        # Exercise the timer callback without sleeping on Maya's UI thread.
        hudManager._watch_viewports()
        self.assertGreater(self._title_pixel_count(), 20)

    @unittest.skipIf(cmds.about(batch=True), "headsUpDisplay needs an interactive session")
    def test_hide_and_restore(self):
        for name, section, visible in ((TEST_HUD_VISIBLE, 0, True),
                                       (TEST_HUD_HIDDEN, 0, False),
                                       (TEST_HUD_FAR, 9, True)):
            block = cmds.headsUpDisplay(nextFreeBlock=section)
            cmds.headsUpDisplay(name, section=section, block=block, label=name)
            cmds.headsUpDisplay(name, edit=True, visible=visible)

        hudManager.show(self.blend)
        self.assertFalse(cmds.headsUpDisplay(TEST_HUD_VISIBLE, query=True, visible=True))
        self.assertIn(TEST_HUD_VISIBLE, hudManager.hidden_huds())
        self.assertNotIn(TEST_HUD_HIDDEN, hudManager.hidden_huds())
        self.assertTrue(cmds.headsUpDisplay(TEST_HUD_FAR, query=True, visible=True))

        hudManager.hide(restore=True)
        self.assertTrue(cmds.headsUpDisplay(TEST_HUD_VISIBLE, query=True, visible=True))
        self.assertFalse(cmds.headsUpDisplay(TEST_HUD_HIDDEN, query=True, visible=True))
        self.assertEqual(hudManager.hidden_huds(), [])
        self.assertFalse(cmds.optionVar(exists=hudManager.OV_HIDDEN_HUDS))


@unittest.skipIf(cmds.about(batch=True), "Interactive HUD resizing requires a GUI")
class TestHudGizmo(unittest.TestCase):
    """Exercise the production gesture handlers with deterministic mouse events."""

    def setUp(self):
        TestPluginHud.setUp(self)
        from blue_steel.ui.editor.hudTransformGizmo import HudTransformGizmo
        from blue_steel.ui.editor import qt
        self.qt = qt
        self.Gizmo = HudTransformGizmo
        self.gizmos = []
        hudManager.show(self.blend)
        hudManager.set_transform(.1, .1, 1.0, refresh=False)
        hudManager.set_frame_size(.4, .5)

    def tearDown(self):
        for gizmo in getattr(self, "gizmos", []):
            if self.qt.is_valid_qt_object(gizmo) and not gizmo._done:
                gizmo.cancel(reason="test cleanup")
        TestPluginHud.tearDown(self)

    def new_gizmo(self):
        gizmo = self.Gizmo(self.panel)
        self.gizmos.append(gizmo)
        gizmo.show()
        return gizmo

    def event_at(self, x, y):
        from types import SimpleNamespace
        point = self.qt.QPoint(int(round(x)), int(round(y)))
        return SimpleNamespace(pos=lambda: point, button=lambda: self.qt.Qt.LeftButton,
                               buttons=lambda: self.qt.Qt.LeftButton, accept=lambda: None)

    def assert_sequence_close(self, actual, expected):
        for a, b in zip(actual, expected):
            self.assertAlmostEqual(a, b, places=5)

    def test_each_corner_resizes_only_area_and_cancel_restores(self):
        initial_transform = hudManager.get_transform()
        initial_size = hudManager.get_frame_size()
        for corner, delta in enumerate(((25, 20), (35, -20), (35, 20), (-25, 20))):
            gizmo = self.new_gizmo()
            rect = gizmo._hud_rect()
            corners = gizmo._corners(rect)
            anchor = corners[(corner + 2) % 4]
            x, y = corners[corner]
            gizmo.mousePressEvent(self.event_at(x, y))
            gizmo.mouseMoveEvent(self.event_at(x + delta[0], y + delta[1]))
            gizmo.mouseReleaseEvent(self.event_at(x + delta[0], y + delta[1]))
            changed = gizmo._hud_rect()
            actual_anchor = gizmo._corners(changed)[(corner + 2) % 4]
            for actual, expected in zip(actual_anchor, anchor):
                self.assertAlmostEqual(actual, expected, delta=1.5)
            self.assertNotAlmostEqual(changed[2], rect[2], delta=5)
            self.assertNotAlmostEqual(changed[3], rect[3], delta=5)
            self.assertAlmostEqual(hudManager.get_transform()[2], initial_transform[2])
            gizmo.cancel(reason="corner cancel test")
            self.assert_sequence_close(hudManager.get_transform(), initial_transform)
            self.assert_sequence_close(hudManager.get_frame_size(), initial_size)

    def test_wheel_changes_only_font_and_commit_persists(self):
        from types import SimpleNamespace
        gizmo = self.new_gizmo()
        initial_rect = gizmo._hud_rect()
        initial_transform = hudManager.get_transform()
        initial_size = hudManager.get_frame_size()
        gizmo.wheelEvent(SimpleNamespace(angleDelta=lambda: self.qt.QPoint(0, 120), accept=lambda: None))
        self.assertGreater(hudManager.get_transform()[2], initial_transform[2])
        self.assert_sequence_close(gizmo._hud_rect(), initial_rect)
        self.assert_sequence_close(hudManager.get_frame_size(), initial_size)
        expected_font = hudManager.get_transform()[2]
        gizmo.commit(reason="wheel commit test")
        self.assertAlmostEqual(hudManager.load_settings()[2], expected_font)
        self.assert_sequence_close(hudManager.load_frame_size(), initial_size)

    def test_move_preserves_size_and_font(self):
        gizmo = self.new_gizmo()
        x, y, w, h = gizmo._hud_rect()
        initial_size = hudManager.get_frame_size()
        initial_scale = hudManager.get_transform()[2]
        gizmo.mousePressEvent(self.event_at(x + w / 2, y + h / 2))
        gizmo.mouseMoveEvent(self.event_at(x + w / 2 + 20, y + h / 2 + 30))
        self.assert_sequence_close(hudManager.get_frame_size(), initial_size)
        self.assertAlmostEqual(hudManager.get_transform()[2], initial_scale)
        self.assertGreater(hudManager.get_transform()[0], .1)
        self.assertGreater(hudManager.get_transform()[1], .1)

    def test_hidpi_queries_physical_size_but_returns_logical_frame(self):
        from unittest.mock import patch
        gizmo = self.new_gizmo()
        logical_w, logical_h = gizmo.width(), gizmo.height()
        with patch.object(gizmo, "_physical_viewport_size", return_value=(2 * logical_w, 2 * logical_h)):
            with patch.object(hudManager, "query_rect", wraps=hudManager.query_rect) as query:
                rect = gizmo._hud_rect()
                query.assert_called_once_with(2 * logical_w, 2 * logical_h)
        for actual, expected in zip(rect, (.1 * logical_w, .1 * logical_h, .4 * logical_w, .5 * logical_h)):
            self.assertAlmostEqual(actual, expected, delta=.001)

    def test_reset_and_cancel_restore_all_settings(self):
        hudManager.set_transform(.2, .15, 1.4, refresh=False)
        hudManager.set_frame_size(.5, .6)
        initial = hudManager.get_transform()
        size = hudManager.get_frame_size()
        gizmo = self.new_gizmo()
        gizmo.reset()
        self.assert_sequence_close(hudManager.get_transform(), (.01, .02, 1.0))
        self.assert_sequence_close(hudManager.get_frame_size(), (.4, .5))
        gizmo.cancel(reason="reset cancel test")
        self.assert_sequence_close(hudManager.get_transform(), initial)
        self.assert_sequence_close(hudManager.get_frame_size(), size)


if __name__ == "__main__":
    unittest.main()
