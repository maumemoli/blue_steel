from maya import  cmds
from ..ui import mmtools
SHELF_NAME = "mmtools"
COMMANDS = [
        "MMToolsUI,import blue_steel\nblue_steel.ui.mmtools.show(),Launch MMTools",
        "CreatePaintCluster,from blue_steel.mmtools.smartCluster import make_paint_cluster\nmake_paint_cluster(),Make/Paint Cluster",
        "ToggleClusterState,from blue_steel.mmtools.smartCluster import toggle_cluster_state\ntoggle_cluster_state(),Toggle Cluster on/off",
        "SelectCluster,from blue_steel.mmtools.smartCluster import cycle_selected_clusters\ncycle_selected_clusters(),Cycle cluster selection",
        "UpdateClusterList,from blue_steel.mmtools.smartCluster import update_clusters_list_with_selection\nupdate_clusters_list_with_selection(),Update cluster selection list",
        "MirrorCluster,from blue_steel.mmtools.smartCluster import mirror_selected_cluster\nmirror_selected_cluster(),Mirror cluster",
        "SmoothFloodDeformer,from blue_steel.mmtools.smartCluster import smooth_flood\nsmooth_flood(),Smooth flood deformer",
        "LinkMirroredClusters,from blue_steel.mmtools.smartCluster import link_mirrored_cluster\nlink_mirrored_cluster(),Link mirrored clusters",
        "ResetAttributesAndTransformations,from blue_steel.mmtools.smartCluster import reset_transformations\nreset_transformations(),Reset attributes and transformations",

          ]


def set_up_runtime_cmds(command_name, command, ann="" ):
    hotkey = None
    if cmds.runTimeCommand (command_name , q=True , exists=True):
        print(f"Runtime command '{command_name}' already exists. Skipping creation.")
        return
    cmds.runTimeCommand (
        command_name ,
        ann=ann ,
        category='MMTools' ,
        command=command ,
        commandLanguage='python'
    )


def setup():
    global  COMMANDS
    for full_command in COMMANDS:
        command_name, full_command, annotation = full_command.split(",")
        set_up_runtime_cmds (command_name , full_command, annotation)

setup()