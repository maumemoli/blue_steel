"""Blue Steel editor UI package.

The main window is exposed through :mod:`blue_steel.ui.editor.mainWindow`.
To open the editor, use the top-level ``blue_steel.show()`` entry point.

Example:
    >>> import blue_steel
    >>> win = blue_steel.show()
"""

from blue_steel.ui.editor.mainWindow import MainWindow, show, get_maya_main_window

__all__ = ["MainWindow", "show", "get_maya_main_window"]
