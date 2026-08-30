"""Blue Steel editor UI package.

The main window is exposed through :mod:`blue_steel.ui.editor.main_window`.
A legacy ``mainWindow`` facade module is kept for backward compatibility.

Example:
    >>> from blue_steel.ui.editor import mainWindow
    >>> win = mainWindow.show()
"""

from blue_steel.ui.editor.main_window import MainWindow, show, get_maya_main_window

__all__ = ["MainWindow", "show", "get_maya_main_window"]
