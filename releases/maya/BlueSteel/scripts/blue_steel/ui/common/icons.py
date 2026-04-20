import sys
import os
import traceback
from ... import env
from .iconTools import desaturate_icon, make_toggle, colorize_icon

if env.MAYA_VERSION > 2024:
    from PySide6.QtGui import QIcon

else:
    from PySide2.QtGui import QIcon
custom_icons_path = os.path.abspath(os.path.join(env.ICONS_PATH))

def join_icons_path(icon_name):
    return os.path.join(custom_icons_path, icon_name)

INFO_STYLE = "color: white; font-size: 15px;"
PRIMARY_ICON = QIcon(":/ts-head3.png")
MUTE_OFF_ICON = QIcon(":/ts-head3.png")
MUTE_ON_ICON = QIcon(":/ts-head4.png")
REFRESH_ICON = colorize_icon(QIcon(":/refresh.png"))
DELETE_ICON = colorize_icon(QIcon(":/trash.png"))
EXTRACT_ICON = colorize_icon(QIcon(":/animateSweep.png"))
COMMIT_ICON = colorize_icon(QIcon(":/insert.png"))
DUPLICATE_ICON = colorize_icon(QIcon(":/duplicateCurve.png"))
MUTE_TOGGLE_ICON = make_toggle(QIcon(":/ts-head3.png"))
SELECT_ICON = colorize_icon(QIcon(":/selectObject.png"))
ZERO_VALUE_ICON = colorize_icon(QIcon(":/zeroDepth.png"))
RENAME_ICON = colorize_icon(QIcon(":/renamePreset.png"))
ANALYZE_ICON = colorize_icon(QIcon(":/searchDown.png"))
DOWN_ARROW_ICON = colorize_icon(QIcon(":/play_regular.png"), rotation=90)
UP_ARROW_ICON = colorize_icon(QIcon(":/play_regular.png"), rotation=-90)
REMOVE_FILTER_ICON = colorize_icon(QIcon(":/closeIcon.svg"))
ADD_ICON = colorize_icon(QIcon(":/addCreateGeneric.png"))
EDIT_ICON = colorize_icon(QIcon(":/edit.png"))
LOCK_ICON = colorize_icon(QIcon(":/lock.png"))
LINK_ICON = colorize_icon(QIcon(":/out_genericConstraint.png"))
AUTO_POSE_ICON = colorize_icon(QIcon(":/tePoseOffset.png"))
ADD_AT_POSE_ICON = colorize_icon(QIcon(":/teCreatePose.png"))
VISIBLE_ICON = colorize_icon(QIcon(":/visible.png"))
HIDDEN_ICON = QIcon(":/hidden.png")
mmtoolicon_path = join_icons_path("mmTools_icon.png")
MMTOOLS_ICON = QIcon(mmtoolicon_path)
LOCK_ON_ICON = QIcon(":/nodeGrapherLocked.png")
LOCK_OFF_ICON = colorize_icon(QIcon(":/nodeGrapherUnlocked.png"))
HIGHLIGHT_ICON = QIcon(":/UVTkPivotCenter.png")
HEAT_MAP_ICON = QIcon(":/rampShader.svg")
CONTROLLER_LAYOUT_ICON = colorize_icon(QIcon(":/polyLayoutUVLarge.png"))