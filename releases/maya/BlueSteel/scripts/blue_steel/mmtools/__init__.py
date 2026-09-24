from maya import  cmds
from . import ui
from ..env import ENVIRONMENT

SHELF_NAME = "mmtools"
_PACKAGE_NAME = ENVIRONMENT.PACKAGE_NAME
COMMANDS = [
        f"MMToolsUI,import {_PACKAGE_NAME}\n{_PACKAGE_NAME}.ui.mmtools.show(),Launch MMTools",
        f"CreatePaintCluster,from {_PACKAGE_NAME}.mmtools.smartCluster import make_paint_cluster\nmake_paint_cluster(),Make/Paint Cluster",
        f"ToggleClusterState,from {_PACKAGE_NAME}.mmtools.smartCluster import toggle_cluster_state\ntoggle_cluster_state(),Toggle Cluster on/off",
        f"SelectCluster,from {_PACKAGE_NAME}.mmtools.smartCluster import cycle_selected_clusters\ncycle_selected_clusters(),Cycle cluster selection",
        f"UpdateClusterList,from {_PACKAGE_NAME}.mmtools.smartCluster import update_clusters_list_with_selection\nupdate_clusters_list_with_selection(),Update cluster selection list",
        f"MirrorCluster,from {_PACKAGE_NAME}.mmtools.smartCluster import mirror_selected_cluster\nmirror_selected_cluster(),Mirror cluster",
        f"SmoothFloodDeformer,from {_PACKAGE_NAME}.mmtools.smartCluster import smooth_flood\nsmooth_flood(),Smooth flood deformer",
        f"LinkMirroredClusters,from {_PACKAGE_NAME}.mmtools.smartCluster import link_mirrored_cluster\nlink_mirrored_cluster(),Link mirrored clusters",
        f"ResetAttributesAndTransformations,from {_PACKAGE_NAME}.mmtools.smartCluster import reset_transformations\nreset_transformations(),Reset attributes and transformations",

          ]


def set_up_runtime_cmds(command_name, command, ann="" ):
    hotkey = None
    if cmds.runTimeCommand (command_name , q=True , exists=True):
        old_command = cmds.runTimeCommand (command_name , q=True , command=True)
        if old_command != command:
            cmds.runTimeCommand (command_name , e=True , command=command)
            print(f"Updated command for '{command_name}'\nfrom: {old_command}\nto: {command}")
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