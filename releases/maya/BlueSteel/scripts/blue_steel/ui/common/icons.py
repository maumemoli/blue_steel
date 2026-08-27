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
RENAME_ICON = colorize_icon(QIcon(":/quickRename.png"))
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
connected_mesh_icon_path = join_icons_path("connected_mesh_icon.png")
CONNECTED_MESH_ENABLED_ICON = QIcon(connected_mesh_icon_path)
CONNECTED_MESH_DISABLED_ICON = desaturate_icon(QIcon(connected_mesh_icon_path))
COMPARE_MESH_ICON = colorize_icon(QIcon(":/meshCompare.png"))
HUD_ICON = colorize_icon(QIcon(":/RS_filter_list.png"))

NORMALIZE_ICON = QIcon(":/normalize.png")
MASK_ICON = QIcon(":/Mask.png")
EDIT_SPLIT_MAP_ICON = QIcon(":/paintSetMembership.png")
SAVE_ICON = colorize_icon(QIcon(":/fileSave.png"))
APPLY_SPLIT_MAP_ICON = QIcon(":/paintAutoSave.png")
copy_weights_icon_path = join_icons_path("copy_weights_icon.svg")
COPY_WEIGHTS_ICON = QIcon(copy_weights_icon_path)
paste_weights_icon_path = join_icons_path("paste_weights_icon.svg")
PASTE_WEIGHTS_ICON = QIcon(paste_weights_icon_path)
paste_add_weights_icon_path = join_icons_path("paste_add_weights_icon.svg")
PASTE_ADD_WEIGHTS_ICON = QIcon(paste_add_weights_icon_path)
paste_minus_weights_icon_path = join_icons_path("paste_minus_weights_icon.svg")
PASTE_MINUS_WEIGHTS_ICON = QIcon(paste_minus_weights_icon_path)
paste_multiply_weights_icon_path = join_icons_path("paste_multiply_weights_icon.svg")
PASTE_MULTIPLY_WEIGHTS_ICON = QIcon(paste_multiply_weights_icon_path)
paste_inverted_weights_icon_path = join_icons_path("paste_inverted_weights_icon.svg")
PASTE_INVERTED_WEIGHTS_ICON = QIcon(paste_inverted_weights_icon_path)
filter_active_values_icon_path = join_icons_path("filter_active_values_icon.svg")
FILTER_ACTIVE_VALUES_ICON = QIcon(filter_active_values_icon_path)
SOFT_MOD_ICON = colorize_icon(QIcon(":/softMod.png"))
SPLIT_ICON = colorize_icon(QIcon(":/split.png"))