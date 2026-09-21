"""Single source of truth for the Blue Steel environment variables and constants.

The :class:`Environment` dataclass groups every value that used to live as a
module-level global in this file or in the former ``api.constants`` module. A
frozen instance named :data:`ENVIRONMENT` is shared across the package::

    >>> from blue_steel import env
    >>> env.ENVIRONMENT.VERSION

``DGA_NODES_SUPPORTED`` is exposed as a property because the
``dynamicGeometryAttributes`` plugin can be registered after import, so its
value has to be queried on every access.
"""

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from maya import cmds
from . import __version__, __url__, __update_url__, __latest_version__, __maya_version__, __python_version__

def dynamic_geometry_attributes_exists():
    """Return whether the dynamicGeometryAttributes plugin is registered."""
    return cmds.pluginInfo("dynamicGeometryAttributes", q=True, registered=True)


def _get_module_path():
    # NOTE: ``env`` is also imported by the drag-and-drop installer *before* the
    # ``blue_steel_maya`` module is registered, so ``moduleInfo`` can return
    # ``None`` on a fresh install. Guard against that instead of crashing.
    if "blue_steel_maya" in cmds.moduleInfo(lm=True):
        return cmds.moduleInfo(moduleName="blue_steel_maya", path=True)
    return None


def _get_icons_path():
    module_path = _get_module_path()
    if module_path is None:
        file_path = Path(__file__).resolve()
        if len(file_path.parents) >= 2:
            module_path = file_path.parents[2]
    icons_path = os.path.join(module_path, "icons")
    return os.path.join(module_path, "icons") if os.path.exists(icons_path) else ""


@dataclass(frozen=True)
class Environment:
    """All the environment variables and shared constants of the project."""

    # ENVIRONMENT VARIABLES
    SEPARATOR: str = "_"
    VERSION: str = __version__
    EDITOR_NAME_SUFFIX: str = "blueSteelEditor"
    ICONS_PATH: str = field(default_factory=_get_icons_path)
    MAYA_VERSION: int = __maya_version__
    PYTHON_VERSION: int = __python_version__

    # ATTR
    MAIN_BLENDSHAPE_STRING_IDENTIFIER: str = "mainBlendShape"
    SPLIT_BLENDSHAPE_STRING_IDENTIFIER: str = "splitBlendShape"
    WORK_BLENDSHAPE_STRING_IDENTIFIER: str = "workBlendShape"
    HEAT_MAP_BLENDSHAPE_STRING_IDENTIFIER: str = "heatMapBlendShape"
    SPLIT_ATTR_GRP_STRING_IDENTIFIER: str = "splitAttrGrp"
    SPLIT_GRP_ATTR_STRING_IDENTIFIER: str = "splitGroups"
    SPLIT_MAPS_AREA_ORDER_ATTR_STRING_IDENTIFIER: str = "splitMapsOrder"
    SPLIT_MAP_EDIT_MESH_ATTR_STRING_IDENTIFIER: str = "splitMapEditMesh"
    SPLIT_MAP_EDIT_BLENDSHAPE_ATTR_STRING_IDENTIFIER: str = "splitMapEditBlendshape"
    SPLIT_MAP_EDIT_CURRENT_ATTR_STRING_IDENTIFIER: str = "splitMapEditCurrent"
    FACE_CTRL_STRING_IDENTIFIER: str = "faceCtrl"
    NODE_NETWORK_CONTAINER_STRING_IDENTIFIER: str = "nodeNetwork"
    BASE_MESH_STRING_IDENTIFIER: str = "baseMesh"
    HEAT_MAP_MESH_STRING_IDENTIFIER: str = "heatMapMesh"
    DGA_VISUALIZER_STRING_IDENTIFIER: str = "dgaVisualizer"
    DGA_DELTA_STRING_IDENTIFIER: str = "dgaDelta"
    SHAPE_NAME_STR: str = "<<SHAPE_NAME>>"
    CUSTOM_SHAPES_COLOR_ATTR_STRING_IDENTIFIER: str = "customShapesColor"

    # TARGET GROUP NAMES
    PRIMARY_SHAPES_GRP_NAME: str = "Primaries_GRP"
    COMBO_SHAPES_GRP_NAME: str = "Combos_GRP"
    INBETWEEN_SHAPES_GRP_NAME: str = "Inbetweens_GRP"

    @property
    def DGA_NODES_SUPPORTED(self) -> bool:
        """Whether dynamic geometry attribute nodes are available (queried live)."""
        return dynamic_geometry_attributes_exists()


ENVIRONMENT = Environment()
