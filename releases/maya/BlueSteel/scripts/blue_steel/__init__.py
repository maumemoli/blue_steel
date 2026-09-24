
from ._version import __version__ as _version_string
from .version import Version
from maya import cmds
import sys
from .updater import get_latest_version

__maya_version__ = int(cmds.about(version=True))
__python_version__ = sys.version_info.major

if __maya_version__ < 2022 or __python_version__ < 3:
    raise RuntimeError("BlueSteel requires Maya 2022 or higher with Python 3.x")

__url__ = "https://api.github.com/repos/maumemoli/blue_steel/releases/latest"
__update_url__ = "https://github.com/maumemoli/blue_steel/releases/latest"
__version__ = Version(_version_string)
__author__ = "Maurizio Memoli"
__package_name__ = __name__
_latest_version = get_latest_version(__url__)
__latest_version__ = Version(_latest_version) if _latest_version else None






def show():
    """Open the Blue Steel editor window.

    The UI is imported lazily so that ``import blue_steel`` stays lightweight
    and does not initialize Qt/Maya UI classes until the editor is requested.

    Returns:
        MainWindow: The open Blue Steel editor window.

    Example:
        >>> import blue_steel
        >>> win = blue_steel.show()
    """
    from .ui.editor.mainWindow import show as _show
    return _show()
