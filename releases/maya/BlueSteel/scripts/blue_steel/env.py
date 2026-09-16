import os
import sys
from maya import cmds
"""
Here go all the evnvironment variables that are used in the project.
"""


SEPARATOR = "_"
VERSION = "v1.6.5-beta1"
# NOTE: ``env`` is also imported by the drag-and-drop installer *before* the
# ``blue_steel_maya`` module is registered, so ``moduleInfo`` can return
# ``None`` on a fresh install. Guard against that instead of crashing.
try:
    _MODULE_PATH = cmds.moduleInfo(moduleName="blue_steel_maya", path=True)
except Exception:
    _MODULE_PATH = None
ICONS_PATH = os.path.join(_MODULE_PATH, "icons") if _MODULE_PATH else ""
MAYA_VERSION = int(cmds.about(version=True))
# python version
PYTHON_VERSION = sys.version_info.major
DGA_NODES_SUPPORTED = all([node in cmds.allNodeTypes() for node in ["dgaDelta", "dgaVisualizer"]])