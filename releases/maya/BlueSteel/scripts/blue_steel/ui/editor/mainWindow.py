"""Backward-compatible facade for the Blue Steel editor window.

The implementation now lives in :mod:`blue_steel.ui.editor.main_window`. This
module is kept so existing entry points (``from blue_steel.ui.editor import
mainWindow``) continue to work unchanged.

Example:
    >>> from blue_steel.ui.editor import mainWindow
    >>> win = mainWindow.show()
"""

from blue_steel.ui.editor import main_window as _impl

MainWindow = _impl.MainWindow
show = _impl.show
get_maya_main_window = _impl.get_maya_main_window


def __getattr__(name):
    """Forward module-level attributes (e.g. ``WINDOW``) to the implementation."""
    return getattr(_impl, name)


__all__ = ["MainWindow", "show", "get_maya_main_window"]
