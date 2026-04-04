import os
import sys
from maya import cmds
import importlib
"""
Here go all the evnvironment variables that are used in the project.
"""

SEPARATOR = "_"
VERSION = "v1.0.0"
ICONS_PATH = os.path.join(cmds.moduleInfo(moduleName="blue_steel_maya", path=True), "icons")
MAYA_VERSION = int(cmds.about(version=True))
# python version
PYTHON_VERSION = sys.version_info.major
