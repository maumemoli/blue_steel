"""Widget lifetime regressions for a disposable Maya GUI session (not mayapy).

The mirror options dialog is a long-lived, non-modal tool window: the Split Map
Editor keeps one instance and reopens it. Its widgets must therefore survive
Python garbage collection, otherwise the binding deletes the C++ objects that
only a local variable referenced and every later ``set_settings`` call raises
``RuntimeError: Internal C++ object already deleted``.

Add BlueSteel/scripts to sys.path, then run this file with
runpy.run_path(..., run_name="__main__"). No scene assets are required.

Example:
    >>> runpy.run_path("tests/maya/test_mirror_weights_dialog.py", run_name="__main__")
"""

import gc
import time
import unittest

try:
    from maya import cmds
    GUI_AVAILABLE = not cmds.about(batch=True)
except ImportError:
    GUI_AVAILABLE = False

if GUI_AVAILABLE:
    from blue_steel.api import mayaUtils
    from blue_steel.ui.editor.mirrorWeightsDialog import MirrorWeightsDialog
    from blue_steel.ui.editor.qt import (
        QApplication,
        QEvent,
        QWidget,
        get_maya_main_window,
        is_valid_qt_object,
    )


def settle():
    """Let Maya and Qt finish deferred layout, deletion and docking callbacks."""

    until = time.monotonic() + 0.2
    while time.monotonic() < until:
        QApplication.processEvents()
        time.sleep(0.01)


def flush_deferred_deletes():
    """Process every queued ``deleteLater()`` so destroyed wrappers are final."""

    QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    settle()


@unittest.skipUnless(GUI_AVAILABLE, "Requires an interactive Maya GUI")
class MirrorWeightsDialogLifetimeTests(unittest.TestCase):
    """Check that a cached dialog keeps its C++ widgets across collections."""

    def setUp(self):
        parent = get_maya_main_window() or QWidget()
        self._owns_parent = get_maya_main_window() is None
        self.parent = parent
        self.dialog = MirrorWeightsDialog(parent)
        self.dialog.show()
        settle()

    def tearDown(self):
        self.dialog.close()
        self.dialog.deleteLater()
        flush_deferred_deletes()
        if self._owns_parent:
            self.parent.deleteLater()
            flush_deferred_deletes()

    def collect_garbage(self):
        """Run every collector generation the way an editor switch would."""

        for generation in range(3):
            gc.collect(generation)

    def test_widgets_survive_garbage_collection(self):
        self.collect_garbage()

        self.assertTrue(is_valid_qt_object(self.dialog))
        self.assertTrue(is_valid_qt_object(self.dialog._button_box))
        self.assertTrue(is_valid_qt_object(self.dialog._mirror_button))
        self.assertTrue(is_valid_qt_object(self.dialog._close_button))
        self.assertEqual(self.dialog._mirror_button.text(), "Mirror")
        self.assertEqual(self.dialog._close_button.text(), "Close")

    def test_set_settings_still_refreshes_after_collection(self):
        self.collect_garbage()

        self.dialog.set_settings({"action": mayaUtils.MirrorAction.FLIP})
        self.assertEqual(self.dialog.state()["action"], mayaUtils.MirrorAction.FLIP)
        # Flip forces a hard edge, so the falloff is reported as zero.
        self.assertEqual(self.dialog.settings()["mirror_blend_falloff"], 0.0)
        # Greyed rows of the flip action stay consistent after the refresh.
        self.assertFalse(self.dialog._direction_combo.isEnabled())
        self.assertFalse(self.dialog._falloff_spin.isEnabled())

        self.dialog.set_settings({"action": mayaUtils.MirrorAction.MIRROR})
        self.assertTrue(self.dialog._direction_combo.isEnabled())
        self.assertTrue(self.dialog._falloff_spin.isEnabled())

    def test_helper_detects_a_deleted_dialog(self):
        dialog = MirrorWeightsDialog(self.parent)
        self.assertTrue(is_valid_qt_object(dialog))

        dialog.deleteLater()
        flush_deferred_deletes()

        self.assertFalse(is_valid_qt_object(dialog))
        self.assertFalse(is_valid_qt_object(None))


if __name__ == "__main__":
    unittest.main(argv=[__file__], exit=False)
