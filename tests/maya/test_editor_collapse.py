"""Geometry regressions for a disposable Maya GUI session (not mayapy/batch).

Add BlueSteel/scripts to sys.path, then run this file with runpy.run_path(...,
run_name="__main__"). These tests create their own editor/workspace control and
move it into Maya's docking layout. Use a separate Maya instance/temporary
preferences, not a production scene. No scene assets or plugins are required.
"""

import time
import unittest

try:
    from maya import cmds
    GUI_AVAILABLE = not cmds.about(batch=True)
except ImportError:
    GUI_AVAILABLE = False

if GUI_AVAILABLE:
    from blue_steel.ui.editor.mainWindow import MainWindow
    from blue_steel.ui.editor.qt import QApplication, QPoint, QSize, QWidget, get_maya_main_window

    class CollapseTestWindow(MainWindow):
        OBJECT_NAME = "BlueSteelCollapseRegression"
        WORKSPACE_CONTROL_NAME = OBJECT_NAME + "WorkspaceControl"


def settle():
    """Let Maya and Qt finish deferred layout and docking callbacks."""
    until = time.monotonic() + 0.2
    while time.monotonic() < until:
        QApplication.processEvents()
        time.sleep(0.01)


@unittest.skipUnless(GUI_AVAILABLE, "Requires an interactive Maya GUI")
class EditorCollapseTests(unittest.TestCase):
    def setUp(self):
        self.maya_size = get_maya_main_window().size()
        self.window = CollapseTestWindow(parent=get_maya_main_window())
        self.window.resize(1200, 800)
        self.window.show(dockable=True, floating=True, retain=False)
        # Maya can restore an earlier docking state even with floating=True
        # on creation; explicitly switch mode before measuring the baseline.
        cmds.workspaceControl(self.window.WORKSPACE_CONTROL_NAME, edit=True, floating=True)
        settle()
        self.window._floating_shell_window().resize(1204, 804)
        settle()

    def tearDown(self):
        self.window._collapse_layout_timer.stop()
        self.window._shutdown_window()
        if cmds.workspaceControl(self.window.WORKSPACE_CONTROL_NAME, query=True, exists=True):
            cmds.deleteUI(self.window.WORKSPACE_CONTROL_NAME, control=True)
        settle()
        self.assertEqual(get_maya_main_window().size(), self.maya_size)

    def dock(self):
        # Exercise the editor's normal Outliner-adjacent layout when available.
        if not self.window._dock_to_maya_panel():
            cmds.workspaceControl(
                self.window.WORKSPACE_CONTROL_NAME, edit=True,
                dockToMainWindow=("right", False),
            )
        settle()
        self.assertFalse(self.window._is_workspace_floating())

    def assert_expand_button_reachable(self, pane):
        button = self.window.collapse_toggle_button
        self.assertTrue(button.isVisible())
        position = button.mapTo(pane, QPoint(0, 0))
        self.assertGreaterEqual(position.x(), 0)
        self.assertGreaterEqual(position.y(), 0)
        self.assertLessEqual(position.x() + button.width(), pane.width())
        self.assertLessEqual(position.y() + button.height(), pane.height())

    def test_floating_shell_shrinks_and_restores_exact_size(self):
        win = self.window
        shell = win._floating_shell_window()
        before = shell.size()
        content_before = win.size()
        chrome_height = shell.height() - win.height()
        win._set_collapsed(True)
        settle()
        self.assertEqual(shell.height(), win.menuWidget().sizeHint().height() + chrome_height)
        self.assertLess(shell.height(), before.height())
        self.assertEqual(shell.width(), before.width())
        self.assert_expand_button_reachable(shell)
        win._set_collapsed(False)
        settle()
        self.assertEqual(shell.size(), before)
        self.assertEqual(win.size(), content_before)
        resized = before + QSize(17, 13)
        shell.resize(resized)
        settle()
        self.assertEqual(shell.size(), resized)

    def test_docked_splitter_shrinks_and_restores_exact_sizes(self):
        self.dock()
        win = self.window
        splitter, pane = win._dock_splitter_pane()
        before = splitter.sizes()
        content_before = win.size()
        chrome_width = pane.width() - win.width()
        win._set_collapsed(True)
        settle()
        self.assertEqual(pane.width(), win.collapse_toggle_button.width() + 4 + chrome_width)
        self.assert_expand_button_reachable(pane)
        self.assertFalse(win.dock_close_button.isVisible())
        win._refresh_dock_button_state()
        self.assertFalse(win.dock_close_button.isVisible())
        win._set_collapsed(False)
        settle()
        self.assertEqual(splitter.sizes(), before)
        self.assertEqual(win.size(), content_before)
        win._resize_dock_pane(splitter, pane, pane.width() + 20)
        settle()
        # A neighbor's minimum may limit the requested delta; it must not be
        # locked at the old width by a leftover collapse constraint.
        self.assertGreater(pane.width(), before[splitter.indexOf(pane)])

    def test_docked_collapse_gives_space_to_viewport_not_toolbox(self):
        self.dock()
        win = self.window
        splitter, pane = win._dock_splitter_pane()
        panes = [splitter.widget(i) for i in range(splitter.count())]
        viewport = next(
            (i for i, widget in enumerate(panes)
             if widget.objectName() == "MainPane"
             or widget.findChild(QWidget, "MainPane") is not None),
            None,
        )
        self.assertIsNotNone(viewport, "Test needs Maya's standard viewport docking layout")
        index = splitter.indexOf(pane)
        before = splitter.sizes()
        viewport_x = panes[viewport].x()
        strip_x = pane.x()
        win._set_collapsed(True)
        settle()
        after = splitter.sizes()
        released_width = before[index] - after[index]
        self.assertGreater(released_width, 0)
        self.assertEqual(after[viewport], before[viewport] + released_width)
        for i in range(len(panes)):
            if i not in (index, viewport):
                self.assertEqual(after[i], before[i], "Unrelated pane was resized")
        if viewport > index:
            self.assertEqual(pane.x(), strip_x)
            self.assertEqual(panes[viewport].x(), viewport_x - released_width)
        win._set_collapsed(False)
        settle()
        self.assertEqual(splitter.sizes(), before)

    def test_rapid_toggle_does_not_run_stale_geometry_callbacks(self):
        for docked in (False, True):
            if docked:
                self.dock()
            win = self.window
            before = win.size()
            for _ in range(3):
                win._set_collapsed(True)
                win._set_collapsed(False)
            settle()
            self.assertFalse(win._collapsed)
            self.assertEqual(win.size(), before)
            self.assertGreater(win.maximumWidth(), win.width())
            self.assertGreater(win.maximumHeight(), win.height())

    def test_native_docking_updates_collapsed_orientation(self):
        win = self.window
        before = win._floating_shell_window().size()
        win._set_collapsed(True)
        self.dock()  # Native reparent callback, not the custom dock button.
        self.assertTrue(win._collapsed)
        self.assertEqual(win.width(), win.collapse_toggle_button.width() + 4)
        self.assertGreater(win.maximumHeight(), win.height())
        cmds.workspaceControl(win.WORKSPACE_CONTROL_NAME, edit=True, floating=True)
        settle()
        self.assertTrue(win._collapsed)
        self.assertEqual(win.height(), win.menuWidget().sizeHint().height())
        self.assertGreater(win.maximumWidth(), win.width())
        win._set_collapsed(False)
        settle()
        self.assertTrue(win.centralWidget().isVisible())
        self.assertEqual(win._floating_shell_window().size(), before)

    def test_docked_round_trip_replaces_stale_splitter_snapshot(self):
        self.dock()
        win = self.window
        width_before = win.width()
        win._set_collapsed(True)
        cmds.workspaceControl(win.WORKSPACE_CONTROL_NAME, edit=True, floating=True)
        settle()
        self.dock()
        win._set_collapsed(False)
        settle()
        self.assertEqual(win.width(), width_before)
        self.assertTrue(win.centralWidget().isVisible())


if __name__ == "__main__":
    unittest.main(argv=[__file__], exit=False)
