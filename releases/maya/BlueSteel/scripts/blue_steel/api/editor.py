from __future__ import annotations
print("Success")

from maya import cmds, mel
import traceback
import sys
import json
import re
import itertools

from . import attrUtils
from .mayaUtils import undoable, pause_shape_editor
from .container import Container
from .blendshape import Blendshape, Weight
from .skinCluster import SkinCluster
from ..logic.shape import Shape
from ..logic.shapeList import ShapeList
from ..logic.network import Network
from ..logic.splitMap import SplitMap
from ..logic.splitData import SplitData
from ..logic import utilities
from . import mayaUtils
from . import blendshapeHUD
from contextlib import contextmanager


from .. import env
import os
import time
import numpy as np
import maya.OpenMayaUI as omui
try:
    from PySide2 import QtWidgets
    from shiboken2 import wrapInstance
except ImportError:
    from shiboken6 import wrapInstance
    from PySide6 import QtWidgets



# ENVIRONMENT VARIABLES
VERSION = env.VERSION
ICONS_PATH = env.ICONS_PATH
SEPARATOR = env.SEPARATOR
MAYA_VERSION = env.MAYA_VERSION
DGA_NODES_SUPPORTED = env.DGA_NODES_SUPPORTED
# end globals


# ATTR



VERBOSE = False
TIMED = False


class SplitSession(object):
    """
    Holds the Maya-side state of a split bake session.

    Created by BlueSteelEditor._split_session once per split run. It caches the
    area to weight lookups and tracks the active area of each split map so
    only the split maps that actually changed between two poses are updated.

    Attributes:
        connect_blendshape (Blendshape): The first split map blendshape, used to
            connect the source shape targets into the split map chain.
        connect_weights (list): The weights of connect_blendshape.
        bake_mesh (str): The last mesh of the split map chain, holding the final
            split deformation that gets baked into the destination editor.
        area_weights (dict): {split map name: {area: Weight}} lookup tables.
        active_areas (dict): {split map name: active area} to skip redundant sets.
    """
    UNSET_AREA = "__UNINITIALIZED__"

    def __init__(self, editor: BlueSteelEditor):
        self.editor = editor
        self.connect_blendshape = Blendshape(editor.split_blendshape_to_connect)
        self.connect_weights = self.connect_blendshape.get_weights()
        self.bake_mesh = editor.split_bake_mesh
        # precomputing the area lookups to avoid rescanning the weight lists per pose
        self.area_weights = {
            split_map: {str(weight): weight for weight in weights}
            for split_map, weights in editor.split_map_blendshapes_weights.items()
        }
        self.active_areas = {
            split_map: self.UNSET_AREA
            for split_map in editor.split_map_blendshapes
        }

    def connect_shape(self, shape_name: str) -> None:
        """
        Connects the target of a shape of the source blendshape to every area
        target of the split map chain so the split poses can be evaluated.
        Parameters:
            shape_name (str): The name of the shape to connect.
        Returns:
            None
        Example:
            >>> session.connect_shape("browUp")
        """
        self.editor.connect_shape_to_split_map_blendshapes(shape_name,
                                                           split_blendshape=self.connect_blendshape,
                                                           split_weights=self.connect_weights)

    def apply_pose(self, areas: list) -> None:
        """
        Sets the split map blendshape weights for the given area combination.
        Only the split maps whose area changed since the last pose are updated.
        A split map without an area gets all its weights set to 1.0 so the mask
        lets the delta pass unchanged.
        Parameters:
            areas (list): The area combination of the split pose.
        Returns:
            None
        Example:
            >>> session.apply_pose(["side_L", "topBottom_T"])
        """
        desired_areas = {}
        for area in areas:
            split_map_name, split_map_area = area.rsplit("_", 1)
            desired_areas[split_map_name] = split_map_area

        for split_map_name, split_blendshape in self.editor.split_map_blendshapes.items():
            target_area = desired_areas.get(split_map_name)
            if self.active_areas[split_map_name] == target_area:
                continue
            area_weights = self.area_weights[split_map_name]
            if target_area is None:
                for weight in area_weights.values():
                    split_blendshape.set_weight_value(weight, 1.0)
            else:
                target_weight = area_weights.get(target_area)
                if target_weight is None:
                    raise ValueError(f"Area '{target_area}' is not valid for split map '{split_map_name}'.")
                for area, weight in area_weights.items():
                    split_blendshape.set_weight_value(weight, 1.0 if area == target_area else 0.0)
            self.active_areas[split_map_name] = target_area

    def commit_pose(self, pose_name: str, destination_editor: BlueSteelEditor) -> None:
        """
        Commits the current split pose to the destination editor and bakes the
        split deformation into the committed target.
        Parameters:
            pose_name (str): The name of the split pose to commit.
            destination_editor (BlueSteelEditor): The destination editor instance.
        Returns:
            None
        Example:
            >>> session.commit_pose("browUpL", split_editor)
        """
        destination_blendshape = destination_editor.blendshape
        committed_shape = destination_editor.commit_shape(pose_name, destination_editor.base_mesh)
        if committed_shape is None:
            return
        committed_weight_id = getattr(committed_shape, "weight_id", None)
        if committed_weight_id is None:
            committed_weight = destination_blendshape.get_weight_by_name(committed_shape)
            if not committed_weight:
                raise ValueError(f"Committed shape '{pose_name}' does not have a "
                                 "corresponding weight in the destination editor blendshape.")
            committed_weight_id = committed_weight.id
        # connecting and disconnecting bakes the current split deformation into the target
        destination_blendshape.connect_mesh_to_target(committed_weight_id, self.bake_mesh)
        destination_blendshape.disconnect_mesh_from_target(committed_weight_id)


class BlueSteelEditor(object):
    MAIN_BLENDSHAPE_STRING_IDENTIFIER = "mainBlendShape"
    SPLIT_BLENDSHAPE_STRING_IDENTIFIER = "splitBlendShape"
    WORK_BLENDSHAPE_STRING_IDENTIFIER = "workBlendShape"
    HEAT_MAP_BLENDSHAPE_STRING_IDENTIFIER = "heatMapBlendShape"
    SPLIT_ATTR_GRP_STRING_IDENTIFIER = "splitAttrGrp"
    SPLIT_GRP_ATTR_STRING_IDENTIFIER = "splitGroups"
    SPLIT_MAPS_AREA_ORDER_ATTR_STRING_IDENTIFIER = "splitMapsOrder"
    SPLIT_MAP_EDIT_MESH_ATTR_STRING_IDENTIFIER = "splitMapEditMesh"
    SPLIT_MAP_EDIT_BLENDSHAPE_ATTR_STRING_IDENTIFIER = "splitMapEditBlendshape"
    SPLIT_MAP_EDIT_CURRENT_ATTR_STRING_IDENTIFIER = "splitMapEditCurrent"
    FACE_CTRL_STRING_IDENTIFIER = "faceCtrl"
    NODE_NETWORK_CONTAINER_STRING_IDENTIFIER = "nodeNetwork"
    BASE_MESH_STRING_IDENTIFIER = "baseMesh"
    HEAT_MAP_MESH_STRING_IDENTIFIER = "heatMapMesh"
    DGA_VISUALIZER_STRING_IDENTIFIER = "dgaVisualizer"
    DGA_DELTA_STRING_IDENTIFIER = "dgaDelta"
    DELTA_MAP_STRING_IDENTIFIER = "deltaMap"
    SHAPE_NAME_STR = "<<SHAPE_NAME>>"
    # TARGET GROUP NAMES
    PRIMARY_SHAPES_GRP_NAME = "Primaries_GRP"
    COMBO_SHAPES_GRP_NAME = "Combos_GRP"
    INBETWEEN_SHAPES_GRP_NAME = "Inbetweens_GRP"
    CUSTOM_SHAPES_COLOR_ATTR_STRING_IDENTIFIER = "customShapesColor"
    
    def __init__(self, container, separator=SEPARATOR):
        if not cmds.objExists(container):
            raise ValueError(f"Container '{container}' does not exist.")
        self.network = None
        # debug network
        self.network_rebuild_count = 0
        self.dga_nodes_supported = DGA_NODES_SUPPORTED
        self.container = Container(container)
        
        if self.dga_nodes_supported == False:
            self._delete_dga_heat_maps_node_network()
            self._delete_heat_map_blendshape()
            print("DGA nodes are not supported in this Maya version. Heat map visualization will be disabled.")


        # we need to check if inverShape plugin is loaded
        if cmds.pluginInfo("invertShape", query=True, loaded=True) is False:
            cmds.loadPlugin("invertShape")
        self.skin_cluster = None

        self.separator = separator
        self.blendshape = None
        self.split_blendshape = None
        self.work_blendshape = None
        self.heat_map_blendshape = None
        self.split_maps_mesh = None
        self.deformers_node_states = {}

        # these are used to store information when the creatte_split_maps function is called.
        self.split_blendshape_to_connect = None
        self.split_bake_mesh = None
        self.split_maps_group = None
        self.split_map_blendshapes = {}
        self.split_map_blendshapes_weights = {}
        # getting the blendshape nodes
        if self.main_blendshape_name:
            self.blendshape = Blendshape(self.main_blendshape_name)
        else:
            raise ValueError(f"Editor '{container}' does not have a main blendshape linked.")
        
        if self.split_blendshape_name:
            self.split_blendshape = Blendshape(self.split_blendshape_name)
        else:
            raise ValueError(f"Editor '{container}' does not have a split blendshape linked.")
        if self.work_blendshape_name:
            self.work_blendshape = Blendshape(self.work_blendshape_name)
        else:
            raise ValueError(f"Editor '{container}' does not have a work blendshape linked.")
        if self.node_network_container is None:
            raise ValueError(f"Editor '{container}' does not have a node network container linked.")
        if self.split_attr_grp is None:
            raise ValueError(f"Editor '{container}' does not have a split attribute group linked.")
        # we need to check if the blendshape nodes have still a parent directory in the shapeEditorManager
        self.shape_editor_manager = "shapeEditorManager"
        if not cmds.objExists(self.shape_editor_manager):
            raise ValueError(f"shapeEditorManager node does not exist in the scene.")
        self.copied_weight_map_values = None
        # Clean up in case the scene was saved with display heat maps.
        if not self._are_blendshapes_ordered():
            # we need to prompt if the user wants to reorder the blendshapes in the deformation history to fix the heat map visualization. This is necessary because the heat map setup relies on the main blendshape being above the work blendshape in the deformation history.
            result = cmds.confirmDialog(title="Reorder Blendshapes",
                                        message="The blendshapes are not ordered correctly. Do you want to reorder them?",
                                        button=["Yes", "No"],
                                        defaultButton="Yes",
                                        cancelButton="No",
                                        dismissString="No")
            if result == "Yes":
                self.reorder_blendshapes_deformation_history()
        # setting up the network
        self.build_network()
        self.sync_up_muted_shapes()
        self.hud_on = blendshapeHUD.hud_exists(self.blendshape.name)
        self._sync_up_split_maps_attributes()
        # custom coloring for the shapes
        self._add_custom_shapes_color_attribute()
        # make sure the split map edit mesh is hidden when the editor is initialized
        self.switch_visibility_to_split_map_edit_mesh(False)
        self._get_skin_cluster()
        self._ensure_split_shape_name_item_in_groups()
        self.zero_out()

    #-----------------------------
    # SkinCluster Setup
    #-----------------------------
    def _get_skin_cluster(self):
        """
        Get the skinCluster node connected to the base mesh.
        Returns:
            str: The name of the skinCluster node, or None if not found
        """
        base_mesh = self.base_mesh
        if not base_mesh:
            raise ValueError("Base mesh not found in the editor.")
        try:
            skin_cluster = SkinCluster.from_mesh(base_mesh)
        except RuntimeError as e:
            self.skin_cluster = None
            print(f"Warning: {e}")
        else:
            self.skin_cluster = skin_cluster
    #-----------------------------
    # HUD SETUP
    #-----------------------------
    def toggle_hud_display(self, state: bool, list_combos: bool = True):
        """
        Setup the HUD for the Blue Steel rig.
        """
        if state:
            if self.blendshape is None:
                return
            blendshapeHUD.create_master_hud(self.blendshape.name, list_combos=list_combos)
            self.hud_on = True

        else:
            blendshapeHUD.clear_huds()
            self.hud_on = False

    #-----------------------------
    # Heat map setup creation
    #-----------------------------
    
    def display_heat_maps(self, display: bool):
        """
        Display or hide the heat map visualization by connecting or disconnecting the heat map blendshape to the dga node network.
        Parameters:
            display (bool): Whether to display the heat map visualization or not
        """
        if not self.dga_nodes_supported:
            print("DGA nodes not supported in this Maya version. Heat map visualization is not available.")
            return
        if display:
            self._create_heat_map_blendshape()
            self._create_dga_heat_maps_node_network()

        else:
            self._delete_dga_heat_maps_node_network()
            self._delete_heat_map_blendshape()
            base_shape = self.blendshape.get_base()
            if base_shape:
                cmds.setAttr(f"{base_shape[0]}.displayColors", 0)
                cmds.setAttr(f"{base_shape[0]}.materialBlend", 0)

    def set_heat_map_target(self, blendshape_name: str, target_name: str):
        """
        Sets the heat map visualization for a specific target by connecting it to the heat map blendshape.
        Parameters:
            blendshape_name (str): The name of the blendshape that contains the target to visualize
            target_name (str): The name of the target to visualize in the heat map
        """
        if not self.dga_nodes_supported:
            return
        self._connect_target_to_heat_map_blendshape(blendshape_name, target_name)

    def clear_heat_map_target(self):
        """
        Clear the heat map visualization by disconnecting the current target from the heat map blendshape.
        """
        if not self.dga_nodes_supported:
            return
        if self.heat_map_blendshape is None:
            return
        self._disconnect_heat_map_blendshape_target()

    def _delete_heat_map_blendshape(self):
        blend_name = self.heat_map_blendshape_name
        heat_mesh_name = self.heat_map_mesh
        if blend_name and cmds.objExists(blend_name):
            #print(f"Deleting heat map blendshape '{self.heat_map_blendshape_name}' and mesh '{heat_mesh_name}'.")
            cmds.delete(blend_name)
            self.heat_map_blendshape = None
        if self.heat_map_mesh:
            if cmds.objExists(heat_mesh_name):
                #print(f"Deleting heat map mesh '{heat_mesh_name}'.")
                cmds.delete(heat_mesh_name)

    def _disconnect_heat_map_blendshape_target(self):
        if self.heat_map_blendshape is None:
            return
        weight = self.heat_map_blendshape.get_weight_by_name("heatMapTarget")
        if weight is None:
            return
        self.heat_map_blendshape.disconnect_mesh_from_target(weight.id)
        self.heat_map_blendshape.disconnect_target_from_blendshape_target(weight.id)
        self.heat_map_blendshape.reset_target(weight.id)

    def _connect_target_to_heat_map_blendshape(self,
                                            blendshape_name: str,
                                            target_name: str):
        """
        Connect a target in self.blendshape to the heatMapTarget in the heat map blendshape so that 
        it drives the heat map visualization when the target weight is changed.
        parameters:
            blendshape_name (str): The name of the blendshape in self.blendshapes to connect to the heat map blendshape
            target_name (str): The name of the target in self.blendshape to connect to the heat map blendshape
        """
        blendshape = self.blendshapes.get(blendshape_name)
        if blendshape is None:
            raise ValueError(f"Blendshape '{blendshape_name}' not found.")
        if self.heat_map_blendshape is None:
            raise ValueError("Heat map blendshape not found.")
        target_weight = blendshape.get_weight_by_name(target_name)
        if target_weight is None:
            raise ValueError(f"Target '{target_name}' not found in main blendshape.")
        # making  sure there is no mesh connected to the heat map target weight
        # before connecting it to the target weight  
        heat_map_target_weight = self.heat_map_blendshape.get_weight_by_name("heatMapTarget")
        if heat_map_target_weight is None:
            heat_map_target_weight = self.heat_map_blendshape.add_target("heatMapTarget")
        # disconnecting any connected geometry to the heat map target group.
        self.heat_map_blendshape.disconnect_mesh_from_target(heat_map_target_weight.id)
        # we need to connect the target weight to the heat map target weight
        input_weight_id = target_weight.id
        output_weight_id = heat_map_target_weight.id
        output_blendshape_name = self.heat_map_blendshape.name
        blendshape.connect_target_to_blendshape_target(input_target_index=input_weight_id,
                                                        output_blendshape_name=output_blendshape_name,
                                                        output_target_index=output_weight_id)

    def reorder_blendshapes_deformation_history(self):
        """
        Reorder the blendshapes in the deformers history of the base mesh so that the main blendshape is above the work blendshape.
        This is necessary for the heat map visualization to work correctly since it relies on the main blendshape to drive the heat map target weight.
        """
        if self._are_blendshapes_ordered():
            return
        shape = cmds.listRelatives(self.base_mesh, shapes=True, fullPath=True)[0]
        deformers = self.get_deformers()
        if self.work_blendshape_name not in deformers or self.main_blendshape_name not in deformers:
            raise ValueError("Work blendshape or main blendshape not found in the deformers history.")
        cmds.reorderDeformers(self.main_blendshape_name, self.work_blendshape_name, shape)

    def _are_blendshapes_ordered(self):
        """Check if the blendshapes are in the correct order in the deformers history."""
        deformers = self.get_deformers()
        if self.work_blendshape_name not in deformers or self.main_blendshape_name not in deformers:
            raise ValueError("Work blendshape or main blendshape not found in the deformers history.")
        work_blendshape_index = deformers.index(self.work_blendshape_name)
        main_blendshape_index = deformers.index(self.main_blendshape_name)
        if main_blendshape_index > work_blendshape_index:
            return False
        return True
    
    def get_deformers(self):
        """Get the deformers in the history of the base mesh in the order they are applied."""
        shapes = cmds.listRelatives(self.base_mesh, shapes=True, fullPath=True) or None
        if shapes is None:
            raise ValueError(f"Base mesh '{self.base_mesh}' does not have any shapes.")
        shape = shapes[0]
        history = cmds.listHistory(shape, pruneDagObjects=True) or []
        deformers = []
        scene_deformers = cmds.listNodeTypes('deformer')
        for node in history:
            if cmds.nodeType(node) in scene_deformers:
                deformers.append(node)
        
        return deformers

    def _delete_dga_heat_maps_node_network(self):
        """
        Delete the nodes for the heat map setup.
        """
        if self.dga_delta:
            if cmds.objExists(self.dga_delta):
                node = self.dga_delta
                mayaUtils.disconnect_node(node)
                cmds.delete(node)

        if self.dga_visualizer:
            input_connection = cmds.listConnections(f"{self.dga_visualizer}.ig", source=True, destination=False, plugs=True) or []
            output_connection = cmds.listConnections(f"{self.dga_visualizer}.og", source=False, destination=True, plugs=True) or []
                # we need to disconnect the dga visualizer from the heat map blendshape and mesh before deleting it
            if input_connection and output_connection:
                cmds.disconnectAttr(input_connection[0], f"{self.dga_visualizer}.ig")
                cmds.disconnectAttr(f"{self.dga_visualizer}.og", output_connection[0])
                cmds.connectAttr(input_connection[0], output_connection[0], force=True)
            cmds.delete(self.dga_visualizer)

    def _create_dga_heat_maps_node_network(self):
        """
        Create the nodes for the heat map setup.
        """
        # let's check if the heat_mesh exists before creating the dga nodes since we need to connect them to it
        if not self.heat_map_mesh:
            raise ValueError("Heat map mesh not found. Cannot create DGA heat map node network.")
        if not self.heat_map_blendshape:
            raise ValueError("Heat map blendshape not found. Cannot create DGA heat map node network.")
        # deleting the existing nodes if they exist to avoid duplicates
        self._delete_dga_heat_maps_node_network()
        # creating the dga delta node
        delta_node_name = f"{self.editor_base_name}_{self.DGA_DELTA_STRING_IDENTIFIER}"
        delta_node = cmds.createNode("dgaDelta", name=delta_node_name)
        # link to the message attribute for easy access
        attrUtils.add_message_attr(self.container.name, self.DGA_DELTA_STRING_IDENTIFIER, delta_node)
        self.container.add_member(delta_node)
        # now we neeed to connect the delta node to the heat map blendshape and mesh
        heat_map_shape = self.heat_map_blendshape.get_base()[0]
        heat_original_mesh = self.heat_map_blendshape.get_original_geometry()
        cmds.connectAttr(f"{heat_map_shape}.outMesh", f"{delta_node}.inputGeometry", force=True)
        cmds.connectAttr(f"{heat_original_mesh}.outMesh", f"{delta_node}.originalGeometry", force=True)
        # now let's create the dga visualizer node
        visualizer_node_name = f"{self.editor_base_name}_{self.DGA_VISUALIZER_STRING_IDENTIFIER}"
        visualizer_node = cmds.createNode("dgaVisualizer", name=visualizer_node_name)
        # link to the message attribute for easy access
        attrUtils.add_message_attr(self.container.name, self.DGA_VISUALIZER_STRING_IDENTIFIER, visualizer_node)
        self.container.add_member(visualizer_node)
        # connecting the visualizer node to the delta node and to the heat map mesh
        base_shape = self.blendshape.get_base()
        if not base_shape:
            raise ValueError("Base shape not found in main blendshape. Cannot connect DGA visualizer node.")
        base_shape_input = cmds.listConnections(f"{base_shape[0]}.inMesh",
                                                     source=True,
                                                     destination=False,
                                                     plugs=True)
        if not base_shape_input:
            raise ValueError("Base shape does not have an input mesh connection. Cannot connect DGA visualizer node.")
        cmds.connectAttr(base_shape_input[0], f"{visualizer_node}.inputGeometry", force=True)
        cmds.connectAttr(f"{visualizer_node}.outputGeometry", f"{base_shape[0]}.inMesh", force=True)
        # now let's connect the dgaDelta attribute node to the dgaVisualizer
        cmds.connectAttr(f"{delta_node}.outputAttributes[0]", f"{visualizer_node}.inputAttributes[0]", force=True)
        # finally we need to set normalization mode to 0 static 1 dynamic 
        cmds.setAttr(f"{visualizer_node}.normalizationMode", 1)
        cmds.setAttr(f"{base_shape[0]}.displayColors", 1)
        cmds.setAttr(f"{base_shape[0]}.materialBlend", 3)

    def _create_delta_heat_map_node(self):
        """
        Create a single delta heat map node.
        """
        # make sure the plugin is loaded
        if cmds.pluginInfo("deltaMap", query=True, loaded=True) is False:
            cmds.loadPlugin("deltaMap")
        # check if the node exists first
        if self.delta_map:
            return
        delta_node_name = f"{self.editor_base_name}_{self.DELTA_MAP_STRING_IDENTIFIER}"
        delta_node = cmds.deformer(self.base_mesh, type="deltaMap", name=delta_node_name)[0]
        attrUtils.add_message_attr(self.container.name, self.DELTA_MAP_STRING_IDENTIFIER, delta_node)
        self.container.add_member(delta_node)
        heat_base_shapes = cmds.listRelatives(self.heat_map_mesh, shapes=True, fullPath=True) or None
        if heat_base_shapes is None:
            raise ValueError(f"Heat map mesh '{self.heat_map_mesh}' does not have any shapes.")
        heat_map_base_shape = None
        for shape in heat_base_shapes:
            if cmds.getAttr(f"{shape}.intermediateObject"):
                heat_map_base_shape = shape
                break
        cmds.connectAttr(f"{self.heat_map_mesh}.outMesh", f"{delta_node}.deformedMesh", force=True)
        cmds.connectAttr(f"{heat_map_base_shape}.outMesh", f"{delta_node}.baseMesh", force=True)

    def _create_heat_map_blendshape(self):
        """
        Create the blendshape node with an empty target.
        The blendshape out mesh will be connected into the heat map node network.
        """
        if self.heat_map_blendshape and self.heat_map_mesh:
            heat_weight = self.heat_map_blendshape.get_weight_by_name("heatMapTarget")
            self.heat_map_blendshape.set_weight_value(heat_weight, 1.0)
            return
        # we need to create a mesh node to connect to.
        heat_map_geo_name = f"{self.editor_base_name}_{self.HEAT_MAP_MESH_STRING_IDENTIFIER}"
        heat_map_geo = self.duplicate_base_mesh_neutral_state(heat_map_geo_name)
        cmds.setAttr(f"{heat_map_geo}.v", 0)
        attrUtils.add_message_attr(self.container.name,
                                   self.HEAT_MAP_MESH_STRING_IDENTIFIER,
                                   heat_map_geo)
        self.container.add_mesh_as_member(heat_map_geo)

        heat_blendshape_name = f"{self.editor_base_name}_{self.HEAT_MAP_BLENDSHAPE_STRING_IDENTIFIER}"
        heat_blendshape =self.add_new_blendshape_to_container(blendshape_name=heat_blendshape_name,
                                                              mesh_name=heat_map_geo,
                                                              container=self.container,
                                                              message_attr=self.HEAT_MAP_BLENDSHAPE_STRING_IDENTIFIER,
                                                              parent_directory_index=0)

        parent_dir_id = self.blendshape.mid_layer_parent
        self.heat_map_blendshape = Blendshape(heat_blendshape)
        self.heat_map_blendshape.set_mid_layer_parent(parent_dir_id)

        heat_weight = self.heat_map_blendshape.add_target("heatMapTarget")
        self.heat_map_blendshape.set_weight_value(heat_weight, 1.0)

    @property
    def locked_shapes(self):
        if not cmds.attributeQuery("lockedShapes", node=self.container.name, exists=True):
            attrUtils.add_tag(self.container.name, "lockedShapes", "")
        shapes_list_str = attrUtils.get_tag(self.container.name, "lockedShapes")
        locked_shapes_names = shapes_list_str.split(",") if shapes_list_str else []
        locked_shapes = set()
        for shape_name in locked_shapes_names:
            shape = self.network.get_shape(shape_name)
            locked_shapes.add(shape)

        return locked_shapes

    @locked_shapes.setter
    def locked_shapes(self, shapes: set):
        if not cmds.attributeQuery("lockedShapes", node=self.container.name, exists=True):
            attrUtils.add_tag(self.container.name, "lockedShapes", "")
        shapes_list_str = ",".join(sorted(shapes)) if shapes else ""

        cmds.setAttr(f"{self.container.name}.lockedShapes", shapes_list_str, type="string") 

    @property
    def heat_map_display_state(self):
        if self.dga_visualizer:
            return True
        return False

    @property
    def uuid(self):
        """Return the UUID of the Blue Steel rig container."""
        return self.container_view.uuid

    @property
    def name(self):
        if self.container:
            return self.container.name
        else:
            return None
    @property
    def split_map_edit_mesh(self):
        return attrUtils.get_message_attr(self.container.name, self.SPLIT_MAP_EDIT_MESH_ATTR_STRING_IDENTIFIER)

    @property
    def split_map_edit_blendshape(self):
        return attrUtils.get_message_attr(self.container.name, self.SPLIT_MAP_EDIT_BLENDSHAPE_ATTR_STRING_IDENTIFIER)
        
    @property
    def main_blendshape_name(self):
        return attrUtils.get_message_attr(self.container.name, self.MAIN_BLENDSHAPE_STRING_IDENTIFIER)
    @property
    def split_blendshape_name(self):
        return attrUtils.get_message_attr(self.container.name, self.SPLIT_BLENDSHAPE_STRING_IDENTIFIER)
    @property
    def work_blendshape_name(self):
        return attrUtils.get_message_attr(self.container.name, self.WORK_BLENDSHAPE_STRING_IDENTIFIER)
    @property
    def heat_map_blendshape_name(self):
        return attrUtils.get_message_attr(self.container.name, self.HEAT_MAP_BLENDSHAPE_STRING_IDENTIFIER)
    @property
    def split_attr_grp(self):
        return attrUtils.get_message_attr(self.container.name, self.SPLIT_ATTR_GRP_STRING_IDENTIFIER)

    @property
    def dga_visualizer(self):
        return attrUtils.get_message_attr(self.container.name, self.DGA_VISUALIZER_STRING_IDENTIFIER)
    
    @property
    def dga_delta(self):
        return attrUtils.get_message_attr(self.container.name, self.DGA_DELTA_STRING_IDENTIFIER)
    
    @property
    def delta_map(self):
        return attrUtils.get_message_attr(self.container.name, self.DELTA_MAP_STRING_IDENTIFIER)

    @property
    def face_ctrl(self):
        return attrUtils.get_message_attr(self.container.name, self.FACE_CTRL_STRING_IDENTIFIER)

    @property
    def heat_map_mesh(self):
        return attrUtils.get_message_attr(self.container.name, self.HEAT_MAP_MESH_STRING_IDENTIFIER)

    @property
    def node_network_container(self):
        node_network_name = attrUtils.get_message_attr(self.container.name, self.NODE_NETWORK_CONTAINER_STRING_IDENTIFIER)
        if node_network_name:
            return Container(node_network_name)
        return None

    @property
    def current_heat_map_target(self):
        if self.heat_map_blendshape is None:
            return None
        heat_map_target_weight = self.heat_map_blendshape.get_weight_by_name("heatMapTarget")
        if heat_map_target_weight is None:
            return None
        self.heat_map_blendshape.get_target_in
        return None

    @property
    def base_mesh(self):
        """
        Returns the base mesh for the Blue Steel rig.
        Returns:
            str: The name of the base mesh.
        """
        return attrUtils.get_message_attr(self.container.name, self.BASE_MESH_STRING_IDENTIFIER)

    @property
    def editor_base_name(self):
        name_tokens = self.container.name.split("_")[:-1]
        return "_".join(name_tokens)

    @property
    def blendshapes(self):
        blendshapes = {}
        for blendshape in [self.blendshape,
                           self.split_blendshape,
                           self.work_blendshape,
                           self.heat_map_blendshape]:
            if blendshape is not None:
                blendshapes[blendshape.name] = blendshape
        return blendshapes
    
    def exists(self):
        """
        Check if the Blue Steel rig still exists in the scene.
        Returns:
            bool: True if the rig exists, False otherwise.
        """
        return cmds.objExists(self.container.name)

    def unlock_all_shapes(self):
        """
        Unlock all shapes in the Blue Steel rig.
        Returns:
            None
        """
        self.locked_shapes = set()

    def fix_mid_layer_blendshapes_indices_position(self):
        """
        Fix the position of the blendshape indices for the mid layer blendshapes.
        Sometimes the blendshapes disappear because the midLayers are not in the correct position in the shapeEditor Manager"""
        # get the shapeEditorManager.blendShapeDirectory available indices
        blendshape_parent_directory_indices = []
        available_indices = cmds.getAttr(f"{self.shape_editor_manager}.blendShapeDirectory", multiIndices=True) or []
        
        for blendshape in [self.blendshape, self.split_blendshape, self.work_blendshape]:
            if blendshape is None:
                continue
            base_directory_indices = cmds.getAttr(f"{self.shape_editor_manager}.blendShapeDirectory[0].childIndices") or []
            mid_layer_index = blendshape.mid_layer_id
            directory_index = None
            for i in available_indices:
                directory_indices = cmds.getAttr(f"{self.shape_editor_manager}.blendShapeDirectory[{i}].childIndices") or []
                if mid_layer_index in directory_indices:
                    # we found in which directory the mid layer blendshape is
                    directory_index = i
                    break
            if directory_index is None or directory_index == 0:
                # we need to add this blendshape to the base directory
                if mid_layer_index not in base_directory_indices:
                    base_directory_indices.append(mid_layer_index)
                    cmds.setAttr(f"{self.shape_editor_manager}.blendShapeDirectory[0].childIndices",
                                 base_directory_indices, type="Int32Array")
            else:
                if -directory_index not in base_directory_indices:
                    base_directory_indices.append(-directory_index)
                    cmds.setAttr(f"{self.shape_editor_manager}.blendShapeDirectory[0].childIndices",
                                 base_directory_indices, type="Int32Array")
            



        # we need to check if the indices of the mid layer blendshapes are in the available indices


    # def get_base_mesh_shape(self):
    #     base_meshes = self.blendshape.get_base()
    #     if len(base_meshes) == 1:
    #         return base_meshes[0]
    #     else:
    #         for mesh in base_meshes:
    #             if cmds.nodeType(mesh) == "mesh":
    #                 return mesh
    

    # def get_base_mesh(self):
    #     shape = self.get_base_mesh_shape()
    #     if shape:
    #         return cmds.listRelatives(shape, parent=True, fullPath=True)[0]
    #     return None
    
    
    #############################################################################################
    def build_network(self):
        """
        Build the network from scratch based on the blendshape weights.
        This will remove all the existing shapes in the network and rebuild it.
        """
        #TODO: THIS NEEDS TO BE UPDATED WITH THE set_blendshape LOGIC FROM THE NETWORK CLASS
        start = time.time()
        if VERBOSE:
            print("Building network...")
        self.network = Network(separator=self.separator)
        blend_weights = self.blendshape.get_weights() or []
        sorted_weights = utilities.sort_for_insertion(blend_weights, self.separator)
        for shape_weight in sorted_weights:
            shape = self.network.create_shape(shape_weight) # recreating the shape instance
            shape.weight_id = shape_weight.id
            shape.muted = self.blendshape.get_target_mute_state(shape_weight)
            if shape.muted:
                self.network.muted_shapes.add(shape)
            self.network.add_shape(shape)
        # if self.network._shapes.invalid_shapes:
        #     shape_list_str = "    \n".join([str(s) for s in self.network._shapes.invalid_shapes])
        #     print(f"Warning: The following shapes are invalid and were added as InvalidShape:\n{shape_list_str}")
        if TIMED:
            print(f"Finished building network in {time.time() - start:.2f} seconds.")
        self.network_rebuild_count += 1

    def sync_network(self):
        """
       Sync up the network with self.blendshape
        """
        if self.network == self.blendshape.get_weights():
            if VERBOSE:
                print("Network is already in sync")
            return
        if VERBOSE:
            print("Syncing network...")
        self.build_network()

    def zero_out(self):
        """
        Zero out all the primary shapes in the Blue Steel rig.
        Returns:
            None
        """
        if self.face_ctrl is None:
            raise ValueError("Face control not found in the editor.")
        for shape in self.network.get_primary_shapes():
            #self.set_primary_shape_value(shape, 0.0)
            cmds.setAttr(f"{self.face_ctrl}.{shape}", 0.0)

    def set_primary_shape_value(self, shape: Shape, value: float):
        """
        Set the value of a primary shape in the Blue Steel rig.
        Parameters:
            shape (Shape): The shape to set the value for
            value (float): The value to set the shape to
        """
        value = round(value, 2)
        # print(f"Setting primary shape '{shape}' to value {value}.")
        if shape.type != "PrimaryShape":
            raise ValueError(f"Shape '{shape}' is not a primary shape.")
        w = self.blendshape.get_weight_by_name(shape)
        if w is None:
            raise ValueError(f"Shape '{shape}' not found in the blendshape.")
        controller_attr = f"{self.face_ctrl}.{shape}"
        blend_attr = f"{self.blendshape.name}.{shape}"
        if not cmds.objExists(controller_attr):
            raise ValueError(f"Controller attribute '{controller_attr}' does not exist.")
        cmds.setAttr(controller_attr, value)
        shape_value = round(cmds.getAttr(blend_attr), 2)
        if shape_value != value:
            raise ValueError(f"Failed to set shape '{shape}' to value {value}. Current value is {shape_value}.")

    @undoable
    def delete_work_shapes(self, work_shape_names: list):
        """
        Delete multiple work shapes from the blendshape and remove their connections.
        Parameters:
            work_shape_names (list): A list of work shape names to delete
        """
        for work_shape_name in work_shape_names:
            self.delete_work_shape(work_shape_name)

    def get_work_blendshape_connected_targets_weights(self):
        """
        Get the weights of the targets connected to the work blendshape.
        Returns:             
        list: A list of weights of the targets connected to the work blendshape
        """
        connected_weights = []
        if self.work_blendshape is None:
            return connected_weights
        connected_targets = self.work_blendshape.get_connected_targets()
        for connected_target in connected_targets:
            weight = self.work_blendshape.get_weight_by_id(connected_target)
            if weight is not None and weight not in connected_weights:
                connected_weights.append(weight)
        return connected_weights

    def get_work_shape_edit_mesh(self, weight:Weight)->str:
        """
        Get the name of the shape connected to a work blendshape weight.
        Parameters:
            weight (Weight): The weight to get the connected shape for
        Returns:
            str: The name of the connected shape, or None if no shape is connected
        """
        if self.work_blendshape is None:
            raise ValueError("Work blendshape not found.")
        return self.work_blendshape.get_mesh_connected_to_target(weight.id)

    def add_shape_to_locked_shapes(self, shape_name: str):
        """
        Add a shape to the locked shapes set. Locked shapes cannot be deleted or have their connections removed.
        Parameters:
            shape_name (str): The name of the shape to lock
        """
        shape = self.network.get_shape(shape_name)
        if shape is None:
            raise ValueError(f"Shape '{shape_name}' not found in the network.")
        locked = self.locked_shapes
        locked.add(shape)
        self.locked_shapes = locked

    @undoable
    def extract_work_shape(self, work_shape_name: str):
        """
        Extract the work shape to a geometry retaining the current pose.
        that pose will be used as a negative shape to extract the delta.
        """
        current_sculpt_target = self.work_blendshape.get_sculpt_target_indices()[0]
        work_weight = self.work_blendshape.get_weight_by_name(work_shape_name)
        if work_weight is None:
            raise ValueError(f"Work shape '{work_shape_name}' not found in blendshape.")
        # let's get the value of the weight of the work shape to extract the current pose
        work_value = self.work_blendshape.get_weight_value(work_weight)
        if work_value != 1.0:
            raise ValueError(f"Work shape '{work_shape_name}' weight value is {work_value}. Please set it to 1.0 before extracting.")
        # we need to disable the work shape.
        current_mute_state = self.get_work_shape_muted_state(work_weight)
        edit_mesh = cmds.duplicate(self.base_mesh, name=f"{work_shape_name}_editMesh")[0]
        edit_mesh_shape = cmds.listRelatives(edit_mesh, shapes=True, fullPath=True)[0]
        self.set_work_shape_mute_state(work_weight, True)
        # we need to create an extraction mesh
        negative_mesh = cmds.duplicate(self.base_mesh, name=f"{work_shape_name}_negativeMesh")[0]
        extracted_mesh = self.duplicate_base_mesh_neutral_state(f"{work_shape_name}_extractionMesh")
        # we need to create a blendshape to extract the delta between the current pose and the neutral pose
        extraction_blendshape = cmds.blendShape(edit_mesh_shape,
                                                negative_mesh,
                                                extracted_mesh,
                                                name=f"{work_shape_name}_extractionBlendshape",
                                                weight =[(0, 1.0),(1, -1.0)])[0]
        # we need to set the edit mesh as sculpt target
        
        if current_sculpt_target == work_weight.id:
            # if the current sculpt target is the same as the work shape we are extracting, we need to set it to another target to avoid issues with the extraction blendshape
            cmds.sculptTarget(self.work_blendshape.name, e=True, t=-1)
        # we need to connect the extracted mesh to the work blendshape target
        self.work_blendshape.connect_mesh_to_target(work_weight.id, extracted_mesh)
        # we can delete the negative mesh and the extracted mesh empty transform.
        cmds.delete(negative_mesh)
        self.set_work_shape_mute_state(work_weight, current_mute_state)
        # we can translate the group to the side for better visibility
        move_offset = mayaUtils.calculate_mesh_bounding_box_offset(self.base_mesh)
        cmds.move(move_offset[0], 0, 0, edit_mesh, relative=True, worldSpace=True)
        cmds.setAttr(f"{extracted_mesh}.visibility", 0)
        # we create a group to hold the edit mesh and the extracted mesh
        group_name = f"{work_shape_name}_extractionGroup"
        group  = cmds.createNode("transform", name=group_name)
        #print(f"Created extraction group '{group_name}' for work shape '{work_shape_name}'.")
        cmds.parent(edit_mesh, group)
        cmds.parent(extracted_mesh, group)

    def remove_shape_from_locked_shapes(self, shape_name: str):
        """
        Remove a shape from the locked shapes set.
        Parameters:
            shape_name (str): The name of the shape to unlock
        """
        #print(f"Removing shape '{shape_name}' from locked shapes.")
        shape = self.network.get_shape(shape_name)
        if shape is None:
            raise ValueError(f"Shape '{shape_name}' not found in the network.")
        locked = self.locked_shapes
        if shape in locked:
            locked.discard(shape)
        self.locked_shapes = locked

    def delete_work_shape(self, work_shape_name: str):
        """
        Delete a work shape from the blendshape and remove its connections.
        Parameters:
            work_shape_name (str): The name of the work shape to delete
        """
        w = self.work_blendshape.get_weight_by_name(work_shape_name)
        if w is None:
            raise ValueError(f"Work shape '{work_shape_name}' not found in blendshape.")
        parent_dir = self.work_blendshape.get_weight_parent_directory(w)
        if parent_dir.index != 0: # we cannot remove the root directory
            self.work_blendshape.remove_target_dir(parent_dir)
        else:
            print(f"Warning: Work shape '{work_shape_name}' does not have a parent directory. Skipping parent directory removal.")
        driver = self.work_blendshape.get_weight_driver(w)
        if driver:
            cmds.delete(driver)
        self.work_blendshape.remove_target(w)

    @undoable
    def disconnect_work_blendshape_weight(self, work_shape_name: str):
        """
        Disconnect a work shape from the face control.
        Parameters:
            work_shape_name (str): The name of the work shape to disconnect
        """
        w = self.work_blendshape.get_weight_by_name(work_shape_name)
        if w is None:
            raise ValueError(f"Work shape '{work_shape_name}' not found in blendshape.")
        driver = self.work_blendshape.get_weight_driver(w)
        if driver is not None and cmds.nodeType(driver) in ["animCurveUL", "animCurveUA", "animCurveUT", "animCurveUU"]:
            cmds.delete(driver)

    def get_work_shape_driver(self, weight: str):
        """
        Get the driver of a work shape.
        Parameters:
            work_shape_weight (Weight): The weight object of the work shape
        Returns:
            str: The name of the driver node, or None if not found
        """
        if not isinstance(weight, Weight):
            weight = self.work_blendshape.get_weight_by_name(weight)
            if weight is None:
                raise ValueError(f"Weight for work shape '{weight}' not found in blendshape.") 
        driver = self.work_blendshape.get_weight_driver(weight)
        if driver and cmds.nodeType(driver) in ["animCurveUL", "animCurveUA", "animCurveUT", "animCurveUU"]:
            connections = cmds.listConnections(f"{driver}.input", plugs=True) or []
            for conn in connections:
                if conn.startswith(f"{self.blendshape.name}."):
                    primary_shape_name = conn.split(".")[-1]
                    return primary_shape_name
        return None

    def get_shapes_with_connected_work_shapes(self):
        """
        Create a dictionary with the primary shapes that have work shapes connected to them
        where the key is the primary shape name and the value is a list of work shape names that are connected to it.
        """
        shapes_with_connected_work_shapes = {}
        work_weights = self.work_blendshape.get_weights() or []
        for work_weight in work_weights:
            primary_shape_name = self.get_work_shape_driver(work_weight)
            if primary_shape_name:
                if primary_shape_name not in shapes_with_connected_work_shapes:
                    shapes_with_connected_work_shapes[primary_shape_name] = []
                shapes_with_connected_work_shapes[primary_shape_name].append(work_weight)
        return shapes_with_connected_work_shapes

    
    def get_connected_work_shapes(self):
        """
        Create a dictionary with the work shapes that are connected to the main blendshape
        where the key is the work shape name and the value is the primary shape name that is driving it.
        """
        connected_work_shapes = {}
        work_weights = self.work_blendshape.get_weights() or []
        for work_weight in work_weights:
            primary_shape_name = self.get_work_shape_driver(work_weight)
            if primary_shape_name:
                connected_work_shapes[work_weight] = primary_shape_name
        return connected_work_shapes

    @undoable
    def apply_active_work_shapes(self):
        """
        Apply the active work shapes to their linked primary shapes.
        """
        connected_shapes = self.get_shapes_with_connected_work_shapes()
        # we need to get all the work shapes values
        work_shapes_values= {}
        committed_connected_shapes = set()
        for work_shape_weight in self.work_blendshape.get_weights() or []:
            work_shapes_values[work_shape_weight] = self.work_blendshape.get_weight_value(work_shape_weight)
        for connected_shape in utilities.sort_for_insertion(connected_shapes.keys(), self.separator):
            work_shapes = self.work_blendshape.get_weights() or []
            # we need to set the pose to the shape
            current_shape = self.get_shape(connected_shape)
            self.set_shape_pose(current_shape)
            linked_work_shapes = connected_shapes[connected_shape]
            # we need to set the value of all the other shapes to 1
            for work_shape in work_shapes:
                if work_shape not in linked_work_shapes:
                    self.work_blendshape.set_weight_value(work_shape, 0.0)
            # we can duplicate the base mesh and commit the shape.
            dup = cmds.duplicate(self.base_mesh, name=connected_shape)[0]
            committed_connected_shapes.add(connected_shape)
            try:
                self.disable_all_deformers()
                self.commit_shape(connected_shape, dup)
            finally:
                self.enable_all_deformers()
                cmds.delete(dup)
            for linked_work_shape in linked_work_shapes:
                self.delete_work_shape(linked_work_shape)
        # restore the work shapes values
        for work_shape in self.work_blendshape.get_weights() or []:
            if work_shape in work_shapes_values:
                self.work_blendshape.set_weight_value(work_shape, work_shapes_values[work_shape])
        formatted_committed_shapes ='\n      '.join(committed_connected_shapes)
        print(f"================================================================")
        print(f"Applied active work shapes to their linked primary shapes:\n      {formatted_committed_shapes}")
        print(f"================================================================")
        return committed_connected_shapes
    @undoable
    def connect_work_blendshape_weight_to_blendshape_weight(self,work_shape_name: str, shape_name: str):
        """
        Connect a work shape to the face control for direct manipulation.
        Parameters:
            work_shape_name (str): The name of the work shape to connect
            shape_name (str): The name of the primary shape to connect to
        """
        #print(f"Connecting work shape '{work_shape_name}' to primary shape '{shape_name}' for direct manipulation.")
        work_shape_weight = self.work_blendshape.get_weight_by_name(work_shape_name)
        if work_shape_weight is None:
            raise ValueError(f"Work shape '{work_shape_name}' not found in blendshape.")
        shape_weight  = self.blendshape.get_weight_by_name(shape_name)
        if shape_weight is None:
            raise ValueError(f"Shape '{shape_name}' not found in blendshape.")
        # let's check if there is a driven key already. If there is we need to remove it before creating a new one
        driver = self.work_blendshape.get_weight_driver(work_shape_weight)
        #print(f"Existing driver for work shape '{work_shape_name}': {driver}")
        if driver and cmds.nodeType(driver) in ["animCurveUL", "animCurveUA", "animCurveUT", "animCurveUU"]:
            cmds.delete(driver)
            # else:
            #     print(f"No existing driven key found for work shape '{work_shape_name}'. Creating new driven key connection.")
        # if the drive still exists that means that some manual connections were made
        # and we need to disconnect them before creating the driven key connection
        input_connection = cmds.listConnections(f"{self.work_blendshape.name}.{work_shape_name}", source=True, destination=False, plugs=True) or []
        for conn in input_connection:
            cmds.disconnectAttr(conn, f"{self.work_blendshape.name}.{work_shape_name}")

        # we need to create a set driven key connection between the work shape and the primary shape
        # print(f"Creating driven key from '{self.work_blendshape.name}.{work_shape_name}' to '{self.blendshape.name}.{shape_name}'")
        cmds.setDrivenKeyframe(f"{self.work_blendshape.name}.{work_shape_name}",
                        currentDriver=f"{self.blendshape.name}.{shape_name}",
                        driverValue=0, value=0)
        cmds.setDrivenKeyframe(f"{self.work_blendshape.name}.{work_shape_name}",
                        currentDriver=f"{self.blendshape.name}.{shape_name}",
                        driverValue=1, value=1)
        # let's get the driving node
        driver = self.work_blendshape.get_weight_driver(work_shape_weight)

        cmds.keyTangent(driver, index =(0, 0), inTangentType="linear", outTangentType="linear")
        cmds.keyTangent(driver, index =(1, 1), inTangentType="linear", outTangentType="linear")
        # print("Driven key connection created successfully.")
        work_shape_name_base = f"{shape_name}_WS_"
        if work_shape_name.startswith(work_shape_name_base):
            return # we don't need to rename this.

        work_weights = self.work_blendshape.get_weights() or []
        index = 1
        while True:
            new_work_shape_name = f"{work_shape_name_base}{str(index).zfill(3)}"
            if new_work_shape_name not in work_weights:
                break
            index += 1

        self.rename_work_shape(work_shape_name, new_work_shape_name)

    def copy_blendshape_weight_map_values(self, blendshape: Blendshape, shape_name: str):
        """
        Copy the weight values of a shape from a given blendshape to be pasted later.
        Parameters:
            blendshape (Blendshape): The blendshape to copy the weight values from
            shape_name (str): The name of the shape to copy the weight values from
        """
        weight = blendshape.get_weight_by_name(shape_name)
        if weight is None:
            raise ValueError(f"Shape '{shape_name}' not found in {blendshape.name}.")
        self.copied_weight_map_values = blendshape.get_weight_map_values(weight.id)

    def paste_blendshape_weight_map_values_to_shape(self,
                                                    blendshape: Blendshape,
                                                    shape_name: str,
                                                    invert: bool = False,
                                                    add: bool = False,
                                                    subtract: bool = False,
                                                    multiply: bool = False
                                                    ):
        """
        Paste the copied weight values to a shape in a given blendshape.
        Parameters:
            blendshape (Blendshape): The blendshape to paste the weight values to
            shape_name (str): The name of the shape to paste the weight values to
        """
        if self.copied_weight_map_values is None:
            raise ValueError("No weight map values have been copied.")
        weight = blendshape.get_weight_by_name(shape_name)
        if weight is None:
            raise ValueError(f"Shape '{shape_name}' not found in {blendshape.name}.")
        if invert:
            inverted_values = 1 - np.array(self.copied_weight_map_values)
            blendshape.set_weight_map_values(weight.id, inverted_values.tolist())
        elif add:
            existing_values = blendshape.get_weight_map_values(weight.id)
            new_values = np.array(existing_values) + np.array(self.copied_weight_map_values)
            blendshape.set_weight_map_values(weight.id, new_values.tolist())
        elif subtract:
            existing_values = blendshape.get_weight_map_values(weight.id)
            new_values = np.array(existing_values) - np.array(self.copied_weight_map_values)
            blendshape.set_weight_map_values(weight.id, new_values.tolist())
        elif multiply:
            existing_values = blendshape.get_weight_map_values(weight.id)
            new_values = np.array(existing_values) * np.array(self.copied_weight_map_values)
            blendshape.set_weight_map_values(weight.id, new_values.tolist())
        else:
            blendshape.set_weight_map_values(weight.id, self.copied_weight_map_values)

    def convert_soft_selection_to_weight_map(self,
                                             blendshape: Blendshape,
                                             shape_name: str):
        """
        Convert the current soft selection to a weight map for a given shape in a blendshape.
        Parameters:
            blendshape (Blendshape): The blendshape containing the shape
            shape_name (str): The name of the shape to convert the soft selection to a weight map for
        """
        # let's make sure that the shape exists in the blendshape
        weights = mayaUtils.get_softselection_values()
        if weights is None:
            raise ValueError("No soft selection found.")
        weight = blendshape.get_weight_by_name(shape_name)
        if weight is None:
            raise ValueError(f"Shape '{shape_name}' not found in {blendshape.name}.")
        blendshape.set_weight_map_values(weight.id, weights)

    def copy_work_weight_map_values(self, shape_name: str):
        """
        Copy the weight values of a shape to be pasted later.
        Parameters:
            shape_name (str): The name of the shape to copy the weight values from
        """
        self.copy_blendshape_weight_map_values(self.work_blendshape, shape_name)


    def paste_work_weight_map_values_to_shape(self, shape_name: str):
        """
        Paste the copied weight values to a shape.
        Parameters:
            shape_name (str): The name of the shape to paste the weight values to
        """
        self.paste_blendshape_weight_map_values_to_shape(self.work_blendshape, shape_name)

    def paste_inverted_work_weight_map_values(self, shape_name: str):
        """
        Paste the copied weight values to a shape with inverted values.
        Parameters:
            shape_name (str): The name of the shape to paste the weight values to
        """
        self.paste_blendshape_weight_map_values_to_shape(self.work_blendshape, shape_name, invert=True)

    def add_work_weight_map_values(self, shape_name: str):
        """
        Paste the copied weight values to a shape by adding them to the existing values.
        Parameters:
            shape_name (str): The name of the shape to paste the weight values to
        """
        self.paste_blendshape_weight_map_values_to_shape(self.work_blendshape, shape_name, add=True)
    
    def subtract_work_weight_map_values(self, shape_name: str):
        """
        Paste the copied weight values to a shape by subtracting them from the existing values.
        Parameters:
            shape_name (str): The name of the shape to paste the weight values to
        """
        self.paste_blendshape_weight_map_values_to_shape(self.work_blendshape, shape_name, subtract=True)

    def convert_soft_selection_to_work_weight_map(self, shape_name: str):
        """
        Convert the current soft selection to a weight map for a given shape in the work blendshape.
        Parameters:
            shape_name (str): The name of the shape to convert the soft selection to a weight map for
        """
        self.convert_soft_selection_to_weight_map(self.work_blendshape, shape_name)

    def clear_work_weight_map_values(self, shape_name: str):
        """
        Clear the weight map values to 1.0 of a shape by setting them all to 0.
        Parameters:
            shape_name (str): The name of the shape to clear the weight values for
        """
        weight = self.work_blendshape.get_weight_by_name(shape_name)
        if weight is None:
            raise ValueError(f"Shape '{shape_name}' not found in {self.work_blendshape.name}.")
        num_vertices = len(self.work_blendshape.get_weight_map_values(weight.id))
        zero_values = [1.0] * num_vertices
        self.work_blendshape.set_weight_map_values(weight.id, zero_values)

    def normalize_shapes_weight_map_values(self, blendshape: Blendshape, shape_names: list):
        """
        Normalize the given shapes so each nonzero per-vertex weight sum is 1.0.
        Parameters:
            blendshape (Blendshape): The blendshape to normalize the weight values for
            shape_names (list): A list of shape names to normalize the weight values for
        """
        if not shape_names:
            return

        if blendshape is None:
            raise ValueError("Blendshape not found.")
        unique_shape_names = []
        seen = set()
        for shape_name in shape_names:
            key = str(shape_name)
            if not key or key in seen:
                continue
            seen.add(key)
            unique_shape_names.append(key)

        if not unique_shape_names:
            return

        weights = []
        maps = []
        for shape_name in unique_shape_names:
            weight = blendshape.get_weight_by_name(shape_name)
            if weight is None:
                raise ValueError(f"Shape '{shape_name}' not found in {blendshape.name}.")
            weights.append(weight)
            maps.append(np.asarray(blendshape.get_weight_map_values(weight.id), dtype=np.float64))

        stacked_maps = np.vstack(maps)
        per_vertex_sum = stacked_maps.sum(axis=0)
        scale = np.divide(
            1.0,
            per_vertex_sum,
            out=np.ones_like(per_vertex_sum),
            where=per_vertex_sum != 0.0,
        )
        normalized_maps = stacked_maps * scale

        for weight, normalized_values in zip(weights, normalized_maps):
            blendshape.set_weight_map_values(weight.id, normalized_values.tolist())

    def normalize_work_weight_map_values(self, shape_names: list):
        """
        Normalize the weight values of the given shapes so that the maximum value of the sum of all weight value for each vertex is always 1.0.
        Parameters:
            shape_names (list): A list of shape names to normalize the weight values for
        """
        self.normalize_shapes_weight_map_values(self.work_blendshape, shape_names)

    def paste_work_weight_map_values(self, shape_name: str):
        """
        Paste the copied weight values to a shape.
        Parameters:
            shape_name (str): The name of the shape to paste the weight values to
        """
        if self.copied_weight_map_values is None:
            raise ValueError("No weight map values have been copied.")
        weight = self.work_blendshape.get_weight_by_name(shape_name)
        if weight is None:
            raise ValueError(f"Shape '{shape_name}' not found in {self.work_blendshape.name}.")
        self.work_blendshape.set_weight_map_values(weight.id, self.copied_weight_map_values)

    def set_shape_pose(self, shape: Shape):
        """
        Set the pose of the rig based on the Shape.values.
        Parameters:
            shape (Shape): The shape to set the pose for
        """
        self.zero_out()
        #print(f"Setting pose for shape {shape}")
        
        for parent, value in zip(shape.parents, shape.values):
            # print(f"    Setting {parent} to {value}")
            primary = parent.primaries[0]
            cmds.setAttr(f"{self.face_ctrl}.{primary}", value)

    @undoable
    def remove_shapes(self, shape_names: list):
        """
        Remove the selected shapes from the Blue Steel rig.
        Parameters:
            shape_names (list): A list of shape names to remove
        """
        self.sync_network()
        shapes_to_remove = ShapeList([], self.separator)
        for shape_name in shape_names:
            shape = self.network.get_shape(shape_name)
            if shape is None:
                continue
            # we need to check if this shape is a primary or an inbetween shape
            if shape.type in ["PrimaryShape", "InbetweenShape"]:
                descendants = self.get_related_shapes_downstream(shape)
                if descendants:
                    shapes_to_remove.extend(descendants)
            shapes_to_remove.append(shape)
        print(f"Removing shapes: {shapes_to_remove}")
        
        # we also need to remove the shapes from the locked shapes set if they are in it to avoid issues with the connections removal
        for shape in shapes_to_remove:
            if shape in self.locked_shapes:
                self.remove_shape_from_locked_shapes(shape)
        # we need to sort by insertion and reverse it so we remove the children first
        shapes_to_remove = shapes_to_remove.sort_for_insertion()[::-1]
        # Now we can remove the shapes
        primaries_to_value_update = ShapeList([], self.separator)
        for shape in shapes_to_remove:
            w = self.blendshape.get_weight_by_name(shape)
            if w is None:
                continue
            self.network.remove_shape(shape)
            if shape.type == "PrimaryShape":
                # we need to remove the binding to the primary shape
                if cmds.objExists(self.face_ctrl):
                    ctrl_attr = f"{self.face_ctrl}.{shape}"
                    self.container.unbind_attribute(ctrl_attr)
                    attrUtils.remove_attribute(self.face_ctrl, shape)
                    
                else:
                    raise ValueError(f"Cannot remove primary shape '{shape}' because control group is missing.")
                if cmds.objExists(self.split_attr_grp):
                    attrUtils.remove_attribute(self.split_attr_grp, shape)
                else:
                    raise ValueError(f"Cannot remove primary shape '{shape}' because split attribute group is missing.")
            else:
                # we need to remove the input connections to the remapValue or combinationShape nodes
                # of the inbetween combo and combo inbetween shapes
                driver = self.blendshape.get_weight_driver(w)
                if driver:
                    cmds.delete(driver)
                # if this is an inbetween we need to store the primary to update the remap nodes later
                if shape.type == "InbetweenShape":
                    primary = self.network.get_shape(shape.primaries[0])
                    if primary not in shapes_to_remove:
                        primaries_to_value_update.append(primary)
            # we need to remove the parent directory.
            parent_dir = self.blendshape.get_weight_parent_directory(w)
            # print("Parent dir:", parent_dir)
            self.blendshape.remove_target(w)
            if parent_dir.index !=0: # we cannot remove the root directory
                # print("Removing parent dir:", parent_dir)
                self.blendshape.remove_target_dir(parent_dir)
            if VERBOSE:
                print(f"Removed {shape.type} shape {shape}")
        # now we need to update the remapValue nodes for the primaries that had inbetweens removed
        for primary in primaries_to_value_update:
            self.update_remap_nodes_values(primary)
        return shapes_to_remove


    @undoable
    def rename_primary_shape(self, old_name: str, new_name: str):
        """
        Rename a primary shape in the Blue Steel rig.
        Parameters:
            old_name (str): The old name of the primary shape
            new_name (str): The new name of the primary shape
        """
        self.sync_network()
        shape = self.network.get_shape(old_name)
        if shape is None:
            raise ValueError(f"Shape '{old_name}' not found in the network.")
        if shape.type != "PrimaryShape":
            raise ValueError(f"Shape '{old_name}' is not a primary shape.")
        # we need to get all the descendants of this primary shape
        descendants = self.get_related_shapes_downstream(shape).sort_for_insertion()
        # renaming the primary shape
        for child_shape in descendants:
            weight = self.blendshape.get_weight_by_name(child_shape)
            # we need to get the parent group of the shape
            if weight is None:
                raise ValueError(f"Weight for shape '{child_shape}' not found in blendshape.")
            parent_dir = self.blendshape.get_weight_parent_directory(weight)
            # we need to get the driver node too
            driver_node = self.blendshape.get_weight_driver(weight)
            # we need to go through each sub shape and check if it or its primary matches the shape name
            shape_parts = child_shape.parents
            renamed_tokens = []
            for i in range(len(shape_parts)):
                token = shape_parts[i]
                primary = token.primaries[0]
                if primary == old_name:
                    # we need to rename this parent
                    new_token = token.replace(old_name, new_name, 1)
                    renamed_tokens.append(new_token)
                else:
                    renamed_tokens.append(token)
            # the new name is the combination of all the parents
            new_name_full = self.separator.join(sorted(renamed_tokens))

            self.blendshape.rename_weight(child_shape, new_name_full)
            self.blendshape.rename_target_dir(parent_dir, new_name_full)
            if driver_node:
                if cmds.nodeType(driver_node) in ["remapValue", "combinationShape"]:
                    new_driver_node_name = driver_node.replace(old_name, new_name, 1)
                    cmds.rename(driver_node, new_driver_node_name)
            # let's add the shape to the network with the new name
            # print(f"Creating new shape in network: {new_name_full}")
            new_shape = self.network.create_shape(new_name_full)
            new_shape.muted = child_shape.muted
            self.network.add_shape(new_shape)
        # now  we need to remove all the old shapes from the network in inverse order
        for child_shape in reversed(descendants):
            self.network.remove_shape(child_shape)
            
        # we need to rename the attribute on the control
        if cmds.objExists(self.face_ctrl):
            self.container.unbind_attribute(f"{self.face_ctrl}.{old_name}")
            attrUtils.rename_attribute(self.face_ctrl, old_name, new_name)
            self.container.bind_attribute(f"{self.face_ctrl}.{new_name}")
        # finally we need to update the shape in the network
        self.sync_network()


    def commit_shape(self, shape_name: str, mesh: str, invert_shape: bool = True):
        """
        Commit a single shape to the Blue Steel rig.
        Parameters:
            shape_name (str): The name of the shape to commit
            mesh (str): The mesh to commit the shape from
        Returns:
            None
        """
        if not cmds.objExists(mesh):
            mesh = self.base_mesh
        shape = self.network.create_shape(shape_name)
        # check if the shape is valid
        if shape.type == "InvalidShape":
            return None
        # next_shape_type = sorted_shapes[i+1].type if i < len(sorted_shapes)-1 else None
        # we need to check what kind of shape it is and if it needs to be extracted
        if shape.type == "PrimaryShape":
            self.add_primary_shape(mesh=mesh, shape=shape, invert_shape=invert_shape)
        elif shape.type == "InbetweenShape":
            # setting the pose of the rig to the inbetween shape
            self.add_inbetween_shape(mesh=mesh, shape=shape, invert_shape=invert_shape)
        elif shape.type in ["ComboShape", "ComboInbetweenShape"]:
            self.add_combo_shape(mesh=mesh, shape=shape, invert_shape=invert_shape)
        return shape

    def add_selected_at_current_pose(self):
        """
        Define the current pose from the control and commit the selected shape to the Blue Steel rig."""
        selection = cmds.ls(selection=True, long=True) or []
        # let's try to find a valid mesh in the selection
        mesh = self.base_mesh
        for sel in selection:
            if sel == self.base_mesh:
                continue
            shapes = cmds.listRelatives(sel, shapes=True, fullPath=True) or []
            for shape in shapes:
                if cmds.nodeType(shape) == "mesh":
                    mesh = sel
                    break
            if mesh:
                break
        empty_delta = False
        if mesh == self.base_mesh:
            empty_delta = True
        pose_name = self.get_active_state_name()
        if not pose_name:
            raise ValueError("No active state found on the control to commit the shape to.")
        shape = self.network.get_shape(pose_name)
        if shape is not None and empty_delta:
            # we are stopping here because if the shape already exists and there is no mesh to commit we might end up with a shape with no delta that can cause issues with the remap nodes and the shape editor manager
            raise ValueError(f"Operation cancelled: Shape '{pose_name}' already exists and there is no selected mesh to commit.")
        elif empty_delta:
            # adding empty delta this is not going to affect the locked shapes anyway.
            self._commit_batch_shapes_with_progress_bar({pose_name: mesh})
            self.reset_delta_for_shapes([pose_name])
            return pose_name
        else:
            locked_related_shapes = self.get_related_shapes_downstream(pose_name)
            locked_related_shapes = set(locked_related_shapes).intersection(self.locked_shapes)
            extraction_group, extracted_locked_meshes = self.extract_shapes_to_mesh(locked_related_shapes)

            self._commit_batch_shapes_with_progress_bar({pose_name: mesh})
            if extracted_locked_meshes:
                self._commit_batch_shapes_with_progress_bar(extracted_locked_meshes,
                                                            progress_bar_message="Restoring locked {0} shapes...")
            cmds.delete(extraction_group)
            return pose_name


    def add_new_primary_shape(self, shape_name: str)->Shape:
        """
        Add a new primary shape to the rig.
        If there is a mesh selected it will be used as the source for the primary shape,
        otherwise the base mesh will be used.
        Parameters:
            shape_name (str): The name of the shape to add
        Returns:
            Shape: The added primary shape
        """
        selection = cmds.ls(selection=True, long=True) or []
        # let's try to find a valid mesh in the selection
        mesh = self.base_mesh
        for sel in selection:
            if sel == self.base_mesh:
                continue
            shapes = cmds.listRelatives(sel, shapes=True, fullPath=True) or []
            for shape in shapes:
                if cmds.nodeType(shape) == "mesh":
                    mesh = sel
                    break
            if mesh:
                break
        if self.blendshape is None:
            raise ValueError("Main blendshape not found.")
        if shape_name not in self.network._shapes:
            shape = self.network.create_shape(shape_name)
            if shape.type != "PrimaryShape":
                raise ValueError(f"Shape Name '{shape_name}' is not a valid primary shape name.")
            self.add_primary_shape(mesh, shape)
            if mesh == self.base_mesh:
                # if the mesh is the base mesh that means that we are adding a shape with no delta, we need to reset the delta of this shape to avoid any issues with the remap nodes
                self.reset_delta_for_shapes([shape_name])
        else:
            raise ValueError(f"Shape '{shape_name}' already exists in the network.")
        return shape
    
    def add_new_inbetween_shape(self, shape_name: str)->Shape:
        """
        Add an empty inbetween shape to the Blue Steel rig. An empty inbetween shape is a shape with no delta, it will be used as a placeholder for the inbetween shapes that will be added later.
        Parameters:
            shape_name (str): The name of the inbetween shape to add
        Returns:
            Shape: The added inbetween shape
        """
        shape = self.network.create_shape(shape_name)
        if shape.type != "InbetweenShape":
            raise ValueError(f"Shape Name '{shape_name}' is not a valid inbetween shape name.")
        self.add_inbetween_shape(None, shape)
        return shape

    def _commit_batch_shapes_with_progress_bar(self,
                                               shapes_dict: dict, 
                                               progress_bar_message: str = "Committing {0} shapes..."):
        """
        Internal method to commit a batch of shapes with a progress bar.
        Parameters:
            shapes_dict (dict): A dictionary of shape names and their corresponding meshes
        Returns:
            None
        """
         # --- Start the progress bar ---
        gMainProgressBar = mel.eval('$tmp = $gMainProgressBar')
        sorted_shapes = utilities.sort_for_insertion(list(shapes_dict.keys()), self.separator)
        total_shapes = len(sorted_shapes)

        cmds.progressBar(gMainProgressBar, edit=True,
                        beginProgress=True,
                        isInterruptable=True,
                        status=progress_bar_message.format(total_shapes),
                        maxValue=total_shapes)
        try:
            for shape_name in sorted_shapes:
                mesh = shapes_dict[shape_name]
                self.commit_shape(shape_name, mesh)
                cmds.progressBar(gMainProgressBar,
                        edit=True,
                        step=1,
                        status=f'Adding shape: {shape_name}...')
        except Exception as e:
            cmds.warning(f"An error occurred while committing shapes: {e}")
        finally:
            cmds.progressBar(gMainProgressBar, edit=True, endProgress=True)
            return True

    def get_shape_editor_panel(self):
        """
        Get the shape editor panel if it exists.
        Returns:
            str: The name of the shape editor panel, or None if it doesn't exist
        """
        controls = cmds.lsUI(type="workspaceControl")
        for c in controls:
            if "shapePanel" in c:
                return c
        return None

    @pause_shape_editor
    @undoable
    def commit_shapes(self, selected: list):
        """
        Commit the selected shapes to the Blue Steel rig.
        Parameters:
            selected (list): A list of selected meshes to commit
        Returns:
            None
        """
        start = time.time()
        # we need to sync the network first
        self.sync_network()
        # let's check if there is any muted shape.
        if self.get_muted_shapes():
            result = cmds.confirmDialog(title='Muted Shapes Detected',
                                            message=f'The network contains muted shapes. Do you want to continue? Muted shapes can affect the newly committed shapes.',
                                            button = ['Unmute All','Continue','Cancel'],
                                            defaultButton='Unmute All',
                                            cancelButton='Cancel',
                                            dismissString='Cancel')
            if result == 'Cancel':
                raise ValueError(f"Operation cancelled by the user. No shapes have been committed.")
            elif result == 'Unmute All':
                self.unmute_all_shapes()


        # let's create the shapes instances
        valid_meshes = {}
        invalid_shapes = []
        skip_all_locked = False
        related_downstream_shapes = set()
        self.disable_all_deformers()
        try:
            for mesh in selected:
                shape_name = mesh.split("|")[-1]
                if utilities.is_valid(shape_name, self.separator):
                    related_downstream_shapes.update(self.get_related_shapes_downstream(shape_name))
                    if shape_name in self.locked_shapes:
                        # we need a prompt to ask the user if they want to unlock the shape and continue or skip this shape
                        if skip_all_locked == True:
                            continue
                        result = cmds.confirmDialog(title='Locked Shape Detected',
                                                message=f'Shape "{shape_name}" is locked. Do you want to unlock it and continue?',
                                                button=['Unlock', 'Skip', 'Unlock All', 'Skip All', 'Cancel'],
                                                defaultButton='Unlock',
                                                cancelButton='Cancel',
                                                dismissString='Cancel')
                        if result == 'Unlock':
                            self.unlock_shape(shape_name)
                        elif result == 'Cancel':
                            raise ValueError(f"Operation cancelled by the user. No shapes have been committed.")
                        elif result == 'Unlock All':
                            self.unlock_all_shapes()
                        elif result == 'Skip All':
                            skip_all_locked = True
                        else:
                            continue
                    valid_meshes[shape_name] = mesh
                else:
                    print(f"Invalid shape name: {shape_name}. Skipping mesh: {mesh}")
                    invalid_shapes.append(mesh)

            related_downstream_locked_shapes = related_downstream_shapes.intersection(self.locked_shapes)
            extracted_locked_meshes = None
            extraction_group = None
            if related_downstream_locked_shapes:
                extraction_group, extracted_locked_meshes = self.extract_shapes_to_mesh(related_downstream_locked_shapes)

            # we need to get the downstream shapes for the selected shapes.
            # close the shape editor if it's open
            if not valid_meshes:
                raise ValueError("No valid shapes to commit. Please check the selected meshes and ensure they have valid names.")

            self._commit_batch_shapes_with_progress_bar(valid_meshes, progress_bar_message="Committing {0} shapes...")
            # after all shapes have been added we need to update the remap nodes for the primaries that had new inbetweens added
            # now we need to commit the locked
            if extracted_locked_meshes:
                self._commit_batch_shapes_with_progress_bar(extracted_locked_meshes, progress_bar_message="Restoring locked {0} shapes...")
                if extraction_group:
                    cmds.delete(extraction_group)
            if TIMED:
                print(f"Finished committing {len(valid_meshes)} shapes on {len(selected)} Restored: {len(extracted_locked_meshes) if extracted_locked_meshes else 0} locked shapes in {time.time() - start:.2f} seconds.")
            cmds.select(clear=True)
            cmds.select(self.container.name, replace=True)
        except Exception as e:
            print("="*60)
            print(f"Error committing shape selected meshes:")
            traceback.print_exc()
            print("="*60)
        finally:
            if invalid_shapes:
                cmds.warning(f"Could not commit the following shapes because the naming was invalid: {', '.join(set(invalid_shapes))}")
            self.enable_all_deformers()
            return invalid_shapes

    @undoable
    def rename_work_shape(self, old_name: str, new_name: str):
        """
        Rename a work shape in the Blue Steel rig.
        Parameters:
            old_name (str): The old name of the work shape
            new_name (str): The new name of the work shape
        """
        if self.work_blendshape is None:
            raise ValueError("Work blendshape not found.")
        if old_name == new_name:
            return
        if new_name in self.work_blendshape.get_weights():
            raise ValueError(f"Work shape '{new_name}' already exists in blendshape.")       
        weight = self.work_blendshape.get_weight_by_name(old_name)
        if weight is None:
            raise ValueError(f"Work shape '{old_name}' not found in blendshape.")
        parent_dir = self.work_blendshape.get_weight_parent_directory(weight)
        if parent_dir is None:
            raise ValueError(f"Parent directory for work shape '{old_name}' not found.")
        self.work_blendshape.rename_weight(old_name, new_name)
        self.work_blendshape.rename_target_dir(parent_dir, new_name)

    def set_work_shape_editable(self, shape_name: str):
        """
        Set the editability of a work shape by muting or unmuting its parent directory.
        Parameters:
            shape_name (str): The name of the work shape
            editable (bool): Whether the work shape should be editable
        """
        weight = self.work_blendshape.get_weight_by_name(shape_name)
        if weight is None:
            raise ValueError(f"Work shape '{shape_name}' not found in blendshape.")
        self.work_blendshape.set_sculpt_target_index(weight.id)

    @undoable
    def add_work_shape(self, name = "WorkShape")->str:
        """
        Will create a new work shape in the work blendshape node.
        Returns:
            str: The name of the new work shape
        """
        if self.work_blendshape is None:
            raise ValueError("Work blendshape not found.")
        work_shape_name = self.work_blendshape.generate_unique_weight_name(name)
        # we need to add a target directory for the work shape
        parent__dir = self.work_blendshape.add_target_dir(work_shape_name)
        weight = self.work_blendshape.add_target(work_shape_name)
        self.work_blendshape.set_weight_parent_directory(weight, parent__dir)
        self.work_blendshape.set_weight_value(weight, 1.0)
        self.set_work_shape_editable(work_shape_name)
        return weight

    @undoable
    def duplicate_work_shape(self, shape_name: str)->str:
        """
        Duplicate a work shape in the work blendshape node.
        Parameters:
            shape_name (str): The name of the work shape to duplicate
        Returns:
            str: The name of the new duplicated work shape
        """
        if self.work_blendshape is None:
            raise ValueError("Work blendshape not found.")
        weight = self.work_blendshape.get_weight_by_name(shape_name)
        if weight is None:
            raise ValueError(f"Work shape '{shape_name}' not found in blendshape.")
        new_shape_name = f"{shape_name}_copy"
        duplicated_weight = self.add_work_shape(new_shape_name)
        # we need to copy the delta from the original shape to the duplicated shape
        self.work_blendshape.transfer_weight_map(weight.id, duplicated_weight.id)
        deltas = self.work_blendshape.get_target_delta(weight.id)
        self.work_blendshape.set_target_delta(duplicated_weight.id, deltas)
        return duplicated_weight

    def set_work_target_weight_paint_mode(self, weight_name: str) -> int:
        """Enter paint mode for one work blendshape target and return its target id."""
        print(f"Setting work target weight paint mode for '{weight_name}'...")
        if self.work_blendshape is None:
            raise ValueError("Work blendshape not found.")
        sculpt_weight = self.work_blendshape.get_weight_by_name(weight_name)
        if sculpt_weight is None:
            raise ValueError(f"Work shape '{weight_name}' not found in work blendshape.")
        self.work_blendshape.set_target_weight_paint_mode(sculpt_weight)
        return int(sculpt_weight.id)

    def set_work_target_mask_paint_mode(self, weight_name: str) -> int:
        """Enter paint mode for one work blendshape target and return its target id."""
        print(f"Setting work target mask paint mode for weight: {weight_name}")
        if self.work_blendshape is None:
            raise ValueError("Work blendshape not found.")
        sculpt_weight = self.work_blendshape.get_weight_by_name(weight_name)
        if sculpt_weight is None:
            raise ValueError(f"Work shape '{weight_name}' not found in work blendshape.")
        self.work_blendshape.set_target_mask_paint_mode(sculpt_weight.id)
        return int(sculpt_weight.id)

    def get_work_shape_muted_state(self, shape_name: str)->bool:
        """
        Get the muted state of a work shape.
        Parameters:
            shape_name (str): The name of the work shape
        Returns:
            bool: The muted state of the work shape
        """
        if self.work_blendshape is None:
            return False
            raise ValueError("Work blendshape not found.")
        weight = self.work_blendshape.get_weight_by_name(shape_name)
        if weight is None:
            return False
            raise ValueError(f"Work shape '{shape_name}' not found in work blendshape.")
        parent_dir = self.work_blendshape.get_weight_parent_directory(weight)
        parent_dir_value = self.work_blendshape.get_target_dir_weight_value(parent_dir)
        return bool(parent_dir_value == 0)

    def disable_all_deformers(self):
        """
        Disable all deformers that can affect the shape extraction 
        or commit of shapes excluding the main blendshape.
        Returns:
            dict: A dictionary of deformer names and their original envelope or nodeState values
        """
        deformers = self.get_deformers()
        deformers_node_states = dict()
        for deformer in deformers:
            # we need to check if there is a nodeState attribute on the deformer and if it's not 0 we need to set it to 0 and store the original value to restore it later
            if cmds.attributeQuery("nodeState", node=deformer, exists=True):
                if deformer == self.blendshape.name:
                    continue
                if self.skin_cluster is not None and deformer == self.skin_cluster.name:
                    continue
                node_state_value = cmds.getAttr(f"{deformer}.nodeState")
                try:
                    cmds.setAttr(f"{deformer}.nodeState", 1)
                    deformers_node_states[deformer] = node_state_value
                except Exception as e:
                    print(f"Warning: Could not set nodeState for deformer '{deformer}'. Error: {e}")
        self.deformers_node_states = deformers_node_states

    def enable_all_deformers(self):
        """
        Restore the original envelope or nodeState values of the deformers that were disabled for shape extraction or commit.
        """
        for deformer, node_state in self.deformers_node_states.items():
            #print(f"Restoring nodeState for deformer '{deformer}' to {node_state}.")
            try:
                cmds.setAttr(f"{deformer}.nodeState", node_state)
            except Exception as e:
                print(f"Warning: Could not restore nodeState for deformer '{deformer}'. Error: {e}")
        self.deformers_node_states = {}

    @undoable
    def extract_shapes_to_mesh(self, shape_names: list):
        """
        Create an extration mesh, set the pose for each shape and duplicate the extraction mesh with the
        shape name.
        Parameters:
            shape_names (list): A list of shapes to extract
        Returns:
             dict: A dictionary of shape names and their corresponding extracted mesh names
        """
        self.disable_all_deformers()
        extracted_meshes = {}
        extraction_mesh = self.base_mesh
        extraction_group = cmds.createNode("transform", name=f"{self.editor_base_name}_extractedShapes_GRP")
        for shape_name in shape_names:
            shape = self.network.get_shape(shape_name)
            if shape is None:
                print(f"Warning: Shape '{shape_name}' not found in the network. Skipping extraction.")
                continue
            self.set_shape_pose(shape)
            # we need to duplicate the extraction mesh with the shape name
            extracted_shape_mesh = cmds.duplicate(extraction_mesh, name=shape_name)[0]
            # we need to unlock the transform attributes of the extracted shape mesh to avoid issues with the parent constraint
            for axis in "XYZ":
                for attr in ["translate", "rotate", "scale"]:
                    attr_name = f"{attr}{axis}"
                    if cmds.attributeQuery(attr_name, node=extracted_shape_mesh, exists=True):
                        if cmds.getAttr(f"{extracted_shape_mesh}.{attr_name}", lock=True):
                            cmds.setAttr(f"{extracted_shape_mesh}.{attr_name}", lock=False)
            parented = cmds.parent(extracted_shape_mesh, extraction_group)[0] #making sure name does not change
            if parented.split("|")[-1] != shape_name:
                extracted_shape_mesh = cmds.rename(parented, shape_name)
            extracted_meshes[shape_name] = extracted_shape_mesh
        # restore the original envelope values
        self.enable_all_deformers()
        return extraction_group, extracted_meshes
    
    #############################################################################################
    # Export Import
    #############################################################################################
    @staticmethod
    def import_obj(import_path:str):
        """
        Import a shape from an OBJ file into the Blue Steel rig.
        Parameters:
            import_path (str): The path to the OBJ file to import
        Returns:
            str: The name of the imported shape
        """
        if not os.path.isfile(import_path):
            raise ValueError(f"Import path '{import_path}' is not a valid file.")
        # Get a set of all top-level nodes (assemblies) currently in the scene
        before_import = set(cmds.ls(assemblies=True))
        # Store original stdout and stderr
        original_stdout = sys.stdout
        original_stderr = sys.stderr
        # importing the OBJ file
        try:
            with open(os.devnull, 'w') as f:
                sys.stdout = f
                sys.stderr = f
            cmds.file(import_path,
                    i=True,
                    type="OBJ",
                    options="mo=0;lo=1;ptgroups=0;materials=0;smoothing=0;normals=1",
                    pr=True,
                    loadReferenceDepth="all")
        except Exception as e:
            return []
        finally:
            # Restore original stdout and stderr
            sys.stdout = original_stdout
            sys.stderr = original_stderr
        # Get a set of all top-level nodes after the import
        after_import = set(cmds.ls(assemblies=True))

        # The difference between the 'after' and 'before' sets is the new objects
        imported_objects = after_import.difference(before_import)
        # filter all the transforms that have mesh shapes
        imported_meshes = []
        for obj in imported_objects:
            shapes = cmds.listRelatives(obj, shapes=True, fullPath=True) or []
            for shape in shapes:
                if cmds.nodeType(shape) == "mesh":
                    imported_meshes.append(obj)
                    break
        if len(imported_meshes) != 1:
            raise ValueError(f"Expected one mesh to be imported from '{import_path}', but found {len(imported_meshes)}.")    
        
        return imported_meshes[0]

    @pause_shape_editor
    @undoable
    def import_objs(self, import_directory: str,):
        """
        Import shapes from OBJ files into the Blue Steel rig.
        Parameters:
            import_directory (str): The directory containing OBJ files to import
        Returns:
            list: A list of invalid file paths that could not be imported
        """
        invalid_files = []
        # getting all the OBJ files in the directory
        obj_files = [f for f in os.listdir(import_directory) if f.endswith(".obj")]

        # getting the shape names from the file names
        sorted_obj_files = dict()
        for obj_file in obj_files:
            shape_name = obj_file.split(".")[0]
            if utilities.is_valid(shape_name, self.separator):
                # print(f"Importing shape from file: {obj_file} as shape: {shape_name}")
                sorted_obj_files[shape_name] = os.path.join(import_directory, obj_file)
            else:
                print(f"Warning: File '{obj_file}' has an invalid shape name '{shape_name}'. Skipping import.")
                invalid_files.append(os.path.join(import_directory, obj_file))
        sorted_shape_names = utilities.sort_for_insertion(list(sorted_obj_files.keys()), self.separator)
        # we need to import the neutral shape first
        neutral_path = sorted_obj_files.get("neutral", None)
        if neutral_path is None:
            raise ValueError("Neutral shape not found in the import directory.")
        # importing the neutral shape
        neutral_mesh = self.import_obj(neutral_path)
        if neutral_mesh != "neutral":
            neutral_mesh = cmds.rename(neutral_mesh, "neutral")
        delta = None

        base_mesh = self.base_mesh
        if base_mesh is None:
            raise ValueError("Base mesh not found in the editor.")
        # compare the points of the neutral shape with the base mesh
        neutral_points = mayaUtils.get_mesh_raw_points(neutral_mesh)
        base_points = self.blendshape.get_base_points()
        # check first if the vert counts are the same
        if neutral_points.shape[0] != base_points.shape[0]:
            raise ValueError("Neutral shape vertex count does not match base mesh vertex count.")
        if not np.allclose(neutral_points, base_points, rtol=1e-05, atol=1e-08):
            # we need to find the difference and apply that to the imported shapes
            delta = neutral_points - base_points
        # we don't need the neutral mesh anymore
        cmds.delete(neutral_mesh)
        # Get the main progress bar control name
        gMainProgressBar = mel.eval('$tmp = $gMainProgressBar')
        total_shapes = len(sorted_shape_names)
        # --- Start the progress bar ---
        cmds.progressBar(gMainProgressBar, edit=True,
                        beginProgress=True,
                        isInterruptable=True,
                        status=f'Processing {total_shapes} shapes...',
                        maxValue=total_shapes)
        try:
            for shape in sorted_shape_names:
                cmds.progressBar(gMainProgressBar,
                                 edit=True,
                                 step=1,
                                 status=f'Importing shape: {shape}...')
                if shape == "neutral":
                    continue
                import_path = sorted_obj_files[shape]
                
                imported_mesh = self.import_obj(import_path)
                if imported_mesh != shape:
                    # print(f"Renaming imported mesh '{imported_mesh}' to '{shape}'")
                    imported_mesh = cmds.rename(imported_mesh, shape)
                # adding the delta if it exists
                if delta is not None:
                    # apply the delta to the imported mesh
                    imported_points = mayaUtils.get_mesh_raw_points(imported_mesh)
                    if imported_points.shape[0] != delta.shape[0]:
                        raise ValueError(f"Imported shape '{shape}' vertex count does not match base mesh vertex count.")
                    new_points = imported_points - delta
                    mayaUtils.set_mesh_raw_points(imported_mesh, new_points)
                self.commit_shape(shape, imported_mesh)

                cmds.delete(imported_mesh)            
        except Exception as e:
            print("="*60)
            print(f"Error importing shape '{shape}':")
            traceback.print_exc()
            print("="*60)
        # --- End the progress bar ---
        finally:
            cmds.progressBar(gMainProgressBar, edit=True, endProgress=True)
            # refreshing the viewport to remove the progress bar artifacts
            cmds.refresh(force=True)

    def ingest_shapes_from_blendshape_node(self, blendshape_node: str, absolute_delta: bool = False):
        """
        Ingest shapes from a blendshape node into the Blue Steel rig.
        Parameters:
            blendshape_node (str): The name of the blendshape node to ingest
            absolute_delta (bool): Whether to treat the blendshape node as an absolute delta
        Returns:
            None
        """
        # we need to create a commit mesh and link it to the blendshape node.
        commit_mesh = self.duplicate_base_mesh_neutral_state(mesh_name=f"{self.editor_base_name}_commitMesh")
        
        temp_blendshape = cmds.blendShape(commit_mesh, name=f"{self.editor_base_name}_tempBlendshape")[0]
        cmds.delete(temp_blendshape)
        commit_mesh_shape, commit_mesh_origin = cmds.listRelatives(commit_mesh, shapes=True, fullPath=True) or []
        cmds.connectAttr(f"{blendshape_node}.outputGeometry[0]", f"{commit_mesh_shape}.inMesh", force=True)
        cmds.connectAttr(f"{commit_mesh_origin}.worldMesh[0]", f"{blendshape_node}.input[0].inputGeometry", force=True)
        # CaesarSkin_commitMeshShapeOrig.outMesh to CaesarSkin_tempBlendshape.originalGeometry
        cmds.connectAttr(f"{commit_mesh_origin}.outMesh", f"{blendshape_node}.originalGeometry[0]", force=True)
        delta_blendshape = Blendshape(blendshape_node)
        # let's get the weights from the blendshape node and build a network to see if there are invalid shapes.
        network = Network()
        shapes_names = utilities.sort_for_insertion(delta_blendshape.get_weights(), self.separator)
        for weight in shapes_names:
            # we also make sure the weights are all at 0
            delta_blendshape.set_weight_value(weight, 0.0)
            shape = network.create_shape(weight)
            network.add_shape(shape)
        if network.get_invalid_shapes():
            raise ValueError(f"Blendshape node '{blendshape_node}' contains invalid shape names: {network.get_invalid_shapes()}")
        gMainProgressBar = mel.eval('$tmp = $gMainProgressBar')
        total_shapes = len(shapes_names)
        try:
            # --- Start the progress bar ---
            cmds.progressBar(gMainProgressBar, edit=True,
                            beginProgress=True,
                            isInterruptable=True,
                            status=f'Processing {total_shapes} shapes...',
                            maxValue=total_shapes)


            for weight in shapes_names:
                # we need to advance the progress bar for each shape
                cmds.progressBar(gMainProgressBar,
                                 edit=True,
                                 step=1,
                                 status=f'Committing shape: {weight}...')
                delta_blendshape.set_weight_value(weight, 1.0)
                self.commit_shape(weight, commit_mesh, invert_shape=absolute_delta)
                delta_blendshape.set_weight_value(weight, 0.0)
        except Exception as e:
            print("="*60)
            print(f"Error committing shape selected meshes:")
            traceback.print_exc()
            print("="*60)
        finally:
            cmds.progressBar(gMainProgressBar, edit=True, endProgress=True)
            cmds.disconnectAttr(f"{delta_blendshape.name}.outputGeometry[0]", f"{commit_mesh_shape}.inMesh")
            cmds.disconnectAttr(f"{commit_mesh_origin}.worldMesh[0]", f"{blendshape_node}.input[0].inputGeometry")
            cmds.disconnectAttr(f"{commit_mesh_origin}.outMesh", f"{blendshape_node}.originalGeometry[0]")
            cmds.delete(commit_mesh)
            
        
    def import_blendshape_node(self, import_path: str):
        """
        Import a blendshape node from a mb or ma file into the Blue Steel rig.
        Parameters:
            import_path (str): The path to the mb or ma file to import
        Returns:
            The name of the imported blendshape node
        """
        if not os.path.isfile(import_path):
            raise ValueError(f"Import path '{import_path}' is not a valid file.")
        extension = os.path.splitext(import_path)[1].lower()
        file_types = {".ma": "mayaAscii", ".mb": "mayaBinary"}
        if extension not in file_types:
            raise ValueError("Import path must end with '.ma' or '.mb'.")
        # importing the blendshape node
        imported_nodes = cmds.file(
            import_path,
            i=True,
            type=file_types[extension],
            options="v=0",
            returnNewNodes=True,
            namespace="imported_blendshape",
        )
        # filtering the imported nodes to find the blendshape node
        imported_blendshapes = [node for node in imported_nodes if cmds.nodeType(node) == "blendShape"]
        if not imported_blendshapes:
            raise ValueError(f"No blendshape node found in '{import_path}'.")
        if len(imported_blendshapes) > 1:
            raise ValueError(f"Multiple blendshape nodes found in '{import_path}'. Expected only one.")
        return imported_blendshapes[0]

    def import_shapes_from_blendshape_node(self, import_path: str, absolute_delta: bool = False):
        """
        Import shapes from a blendshape node in a mb or ma file into the Blue Steel rig.
        Parameters:
            import_path (str): The path to the mb or ma file to import
            absolute_delta (bool): Whether to treat the blendshape node as an absolute delta
        """
        blendshape_node = self.import_blendshape_node(import_path)
        self.ingest_shapes_from_blendshape_node(blendshape_node, absolute_delta=absolute_delta)
        # we can delete the imported blendshape node now
        cmds.delete(blendshape_node)

    def export_shapes_as_blendshape_node(self, export_path: str, absolute_delta: bool = False):
        """
        Export the Blue Steel rig's shapes as a blendshape node in a mb or ma file.
        Parameters:
            export_path (str): The path to export the mb or ma file to
            absolute_delta (bool): Whether to export the blendshape node as an absolute delta
        """
        if self.blendshape is None:
            raise ValueError("Main blendshape not found.")

        # we need to make sure that the folders of the export path exist
        os.makedirs(os.path.dirname(export_path), exist_ok=True)
        if absolute_delta:
            absolute_blendshape = self.create_absolute_delta_blendshape()
            self.export_blendshape_node(absolute_blendshape, export_path)
            cmds.delete(absolute_blendshape)
        else:
            blendshape_name = self.blendshape.name
            self.export_blendshape_node(blendshape_name, export_path)



    def create_absolute_delta_blendshape(self):
        """
        Create a new blendshape node that contains the absolute delta of the main blendshape.
        Parameters:
        Returns:
            str: The name of the new blendshape node
        """
        # we need to duplicate the base mesh in neutral state.
        neutral_mesh = self.duplicate_base_mesh_neutral_state(mesh_name=f"{self.editor_base_name}_neutralMesh")
        blendshape_name = f"{self.editor_base_name}_absoluteDelta"
        delta_blenshape = cmds.blendShape(neutral_mesh, name=blendshape_name)[0]
        delta_blenshape = Blendshape(delta_blenshape)
        # we need the shape names from the main blendshape
        shapes = self.get_all_shapes()
        # we need to create a progress bar for the shape insertion
        gMainProgressBar = mel.eval('$tmp = $gMainProgressBar')
        total_shapes = len(shapes)
        try:
                # --- Start the progress bar ---
                cmds.progressBar(gMainProgressBar, edit=True,
                                beginProgress=True,
                                isInterruptable=True,
                                status=f'Processing {total_shapes} shapes...',
                                maxValue=total_shapes)
                for i, shape in enumerate(shapes.sort_for_insertion(), start=1):
                    self.set_shape_pose(shape)
                    delta_blenshape.add_target(weight_name=shape, target_object=self.base_mesh, disconnect_target=True)
                    cmds.progressBar(gMainProgressBar, edit=True, step=1, status=f'Processing {i}/{total_shapes} shapes...')
        except Exception as e:
            print("="*60)
            print(f"Error committing shape selected meshes:")
            traceback.print_exc()
            print("="*60)
        # we can disconnect the neutral mesh and get rid of it.
        finally:
            cmds.progressBar(gMainProgressBar, edit=True, endProgress=True)
            cmds.disconnectAttr(f"{delta_blenshape.name}.outputGeometry[0]", f"{neutral_mesh}.inMesh")
            cmds.delete(neutral_mesh)
        return delta_blenshape.name
    
    def export_blendshape_node(self, blendshape_name: str, export_path: str):
        """
        Export the Blue Steel rig's blendshape node as a mb or ma file.
        Parameters:
            blendshape_name (str): The name of the blendshape node to export
            export_path (str): The path to export the mb or ma file to
        Returns:
            None
        """
        if self.blendshape is None:
            raise ValueError("Main blendshape not found.")

        extension = os.path.splitext(export_path)[1].lower()
        file_types = {".ma": "mayaAscii", ".mb": "mayaBinary"}
        if extension not in file_types:
            raise ValueError("Export path must end with '.ma' or '.mb'.")

        original_selection = cmds.ls(selection=True, long=True) or []
        was_container_member = blendshape_name in self.container.members
        disconnected = []
        try:
            if was_container_member:
                self.container.remove_member(blendshape_name)

            incoming = cmds.listConnections(
                blendshape_name,
                source=True,
                destination=False,
                connections=True,
                plugs=True,
            ) or []
            outgoing = cmds.listConnections(
                blendshape_name,
                source=False,
                destination=True,
                connections=True,
                plugs=True,
            ) or []

            connections = []
            connections.extend((incoming[i + 1], incoming[i]) for i in range(0, len(incoming), 2))
            connections.extend((outgoing[i], outgoing[i + 1]) for i in range(0, len(outgoing), 2))
            connections = list(dict.fromkeys(connections))

            for source, destination in connections:
                if not cmds.isConnected(source, destination):
                    continue
                cmds.disconnectAttr(source, destination)
                disconnected.append((source, destination))
            current_mid_layer_parent = self.blendshape.mid_layer_parent
            self.blendshape.set_mid_layer_parent(0)
            cmds.select(blendshape_name, replace=True)
            print(f"Exporting blendshape node '{blendshape_name}' to '{export_path}'...")
            cmds.file(
                export_path,
                force=True,
                options="v=0",
                type=file_types[extension],
                exportSelected=True,
            )
        finally:
            for source, destination in disconnected:
                try:
                    cmds.connectAttr(source, destination, force=True)
                except Exception as e:
                    print(f"Warning: Could not reconnect '{source}' to '{destination}'. Error: {e}")

            if was_container_member:
                self.container.add_member(blendshape_name)

            if original_selection:
                cmds.select(original_selection, replace=True)
            else:
                cmds.select(clear=True)
            self.blendshape.set_mid_layer_parent(current_mid_layer_parent)


    @undoable
    def export_all_objs(self, export_directory: str, custom_mesh_name: str = None):
        """
        Export all shapes from the Blue Steel rig to OBJ files.
        Parameters:
            export_directory (str): The directory to export the OBJ files to
        Returns:
            list: A list of file paths to the exported OBJ files
        """
        shape_names = [str(shape) for shape in self.network._shapes]
        return self.export_objs(shape_names, export_directory, custom_mesh_name)
    
    def export_objs(self, shape_names: list, export_directory: str, custom_mesh_name: str = None):
        """
        Export shapes from the Blue Steel rig to OBJ files.
        Parameters:
            shape_names (list): A list of shape names to export
            export_directory (str): The directory to export the OBJ files to
        Returns:
            list: A list of file paths to the exported OBJ files
        """
        exported_files = []
        base_mesh = self.base_mesh
        if custom_mesh_name is not None and cmds.objExists(custom_mesh_name):
            base_mesh = custom_mesh_name
        # exporting the neutral shape
        # check if there is a mesh named "neutral" in the scene already
        old_neutral = None
        if cmds.objExists("neutral"):
            old_neutral = cmds.rename("neutral", "neutral_temp_bsExport")
        neutral = cmds.duplicate(base_mesh, name="neutral")[0]
        neutral_export_path = os.path.join(export_directory, "neutral.obj")

        base_points = self.blendshape.get_base_points()
        mayaUtils.set_mesh_raw_points(neutral, base_points)
        

        cmds.select(neutral, replace=True)
        cmds.file(neutral_export_path,
                    force=True,
                    options="groups=0;ptgroups=0;materials=0;smoothing=1;normals=1",
                    type="OBJexport", exportSelected=True)
        cmds.delete(neutral)
        if old_neutral is not None:
            cmds.rename(old_neutral, "neutral")
        # Get the main progress bar control name
        gMainProgressBar = mel.eval('$tmp = $gMainProgressBar')
        total_shapes = len(shape_names)
        # --- Start the progress bar ---
        cmds.progressBar(gMainProgressBar, edit=True,
                        beginProgress=True,
                        isInterruptable=True,
                        status=f'Processing {total_shapes} shapes...',
                        maxValue=total_shapes)
        try:
            for shape_name in shape_names:
                cmds.progressBar(gMainProgressBar, edit=True,
                                step=1,
                                status=f'Exporting shape: {shape_name}...')
                shape = self.network.get_shape(shape_name)
                if shape is None:
                    print(f"Warning: Shape '{shape_name}' not found in the network. Skipping export.")
                    continue
                self.set_shape_pose(shape)
                # duplicate the base mesh and rename it to the shape name
                renamed_temp = None
                if cmds.objExists(shape_name):
                    renamed_temp = cmds.rename(shape_name, f"{shape_name}_temp_bsExport")
                duplicated_mesh = cmds.duplicate(base_mesh, name=shape_name)[0]

                export_path = os.path.join(export_directory, f"{shape_name}.obj")
                cmds.select(duplicated_mesh, replace=True)
                cmds.file(export_path,
                        force=True,
                        options="groups=0;ptgroups=0;materials=0;smoothing=0;normals=1",
                        type="OBJexport", exportSelected=True)
                cmds.delete(duplicated_mesh)
                if renamed_temp is not None:
                    cmds.rename(renamed_temp, shape_name)
                exported_files.append(export_path)
        except Exception as e:
            print(f"An error occurred during export: {e}")
        # --- End the progress bar ---
        finally:
            cmds.progressBar(gMainProgressBar, edit=True, endProgress=True)
            # refreshing the viewport to remove the progress bar artifacts
            cmds.refresh(force=True)
        return exported_files

    #############################################################################################
    # Shapes management
    #############################################################################################
    def get_related_shapes_downstream(self, shape: Shape):
        """
        Get all the descendants of a shape in the Blue Steel rig.
        Parameters:
            shape (Shape): The shape to get the descendants for
        Returns:
            list: A list of Shape instances that are descendants of the given shape.    
        """
        descendants = self.network._shapes.get_related_shapes_downstream(shape)
        return descendants

    def get_related_shapes_upstream(self, shape: Shape):
        """
        Get all the ancestors of a shape in the Blue Steel rig.
        Parameters:
            shape (Shape): The shape to get the ancestors for
        Returns:
            list: A list of Shape instances that are ancestors of the given shape.
        """
        ancestors = self.network._shapes.get_related_shapes_upstream(shape)
        return ancestors

    def get_primary_shapes(self):
        """
        Get the primary shapes from the blendshape.
        Returns:
            list: A list of primary Shape instances.
        """
        self.sync_network() # just rebuilding the network to make sure it's up to date
        primary_shapes = self.network.get_primary_shapes()
        return primary_shapes

    def get_primary_weights(self):
        """
        Get the primary weights from the blendshape.
        Returns:
            list: A list of primary weight names.
        """
        self.sync_network() # just rebuilding the network to make sure it's up to date
        primary_shapes = self.network.get_primary_shapes()
        weights = self.blendshape.get_weights()
        primary_weights = [w for w in weights if w in primary_shapes]
        return primary_weights

    def get_all_shapes(self):
        """
        Get all the shapes from the blendshape.
        Returns:
            list: A list of all Shape instances.
        """
        self.sync_network() # just rebuilding the network to make sure it's up to date
        return self.network._shapes

    def get_related_shapes(self, shape_names: list):
        """
        Get all the related shapes (parents and children) of the given shapes.
        Parameters:
            shape_names (list): A list of shape names to get the related shapes for
        Returns:
            ShapeList: A list of Shape instances that are related to the given shapes.
        """
        self.sync_network() # just rebuilding the network to make sure it's up to date
        return self.network.get_related_shapes(shape_names)

    def get_work_blendshape_weights(self):
        """
        Get all the work shape names from the work blendshape.
        Returns:
            list: A list of work shape names.
        """
        if self.work_blendshape is None:
            raise ValueError("Work blendshape not found.")
        work_weights = self.work_blendshape.get_weights()
        return work_weights

    def get_primaries_target_dirs(self):
        """
        It will traverse the PrimaryShapes and build the hierarchy of the target directories for the primary shapes.
        Returns:
            dict: A dictionary where the keys are the primary shape names and the values are lists of target directory names that are parents of the primary shape weight.
        """
        start_time = time.time()
        primary_shapes = self.network.get_primary_shapes()
        primaries_target_dirs = {}
        if not primary_shapes:
            if TIMED:
                print(f"get_primaries_target_dirs took {time.time() - start_time} seconds")
            return primaries_target_dirs

        # Build weight lookup once instead of calling get_weight_by_name per primary.
        weights = self.blendshape.get_weights() or set()
        weight_by_name = {str(weight): weight for weight in weights}

        blendshape_name = self.blendshape.name

        # Build weight -> parent directory index map once.
        parent_dir_indices = cmds.getAttr(f"{blendshape_name}.parentDirectory", mi=True) or []
        weight_parent_dir = {
            weight_id: cmds.getAttr(f"{blendshape_name}.parentDirectory[{weight_id}]")
            for weight_id in parent_dir_indices
        }

        # Cache all target directory names and parent links once.
        target_dir_indices = cmds.getAttr(f"{blendshape_name}.targetDirectory", mi=True) or []
        target_dir_name = {}
        target_dir_parent = {}
        for dir_index in target_dir_indices:
            target_dir_name[dir_index] = cmds.getAttr(
                f"{blendshape_name}.targetDirectory[{dir_index}].directoryName"
            )
            target_dir_parent[dir_index] = cmds.getAttr(
                f"{blendshape_name}.targetDirectory[{dir_index}].parentIndex"
            )

        for primary in primary_shapes:
            weight = weight_by_name.get(str(primary))
            if weight is None:
                continue

            parent_dirs = []
            current_dir_index = weight_parent_dir.get(weight.id)
            while current_dir_index not in (None, 0):
                current_dir_name = target_dir_name.get(current_dir_index)
                if current_dir_name is None or current_dir_name == self.PRIMARY_SHAPES_GRP_NAME:
                    break
                parent_dirs.append(current_dir_name)
                current_dir_index = target_dir_parent.get(current_dir_index)

            primaries_target_dirs[primary] = parent_dirs
        end_time = time.time()
        if TIMED:
            print(f"get_primaries_target_dirs took {end_time - start_time} seconds")
        return primaries_target_dirs
    
    def get_active_primary_weights(self):
        """
        Get all the active primary weights from the blendshape.
        Returns:
            list: A list of active primary weight names.
        """
        primary_shapes = self.network.get_primary_shapes()
        # print("Primary shapes:", primary_shapes)
        active_weights = []
        for w in self.blendshape.get_weights():
            value = self.blendshape.get_weight_value(w)
            if value != 0 and w in primary_shapes:
                # print(f"Active weight: {w} with value {value}")
                active_weights.append(w)

        # active_weights = [w for w in self.blendshape.get_weights() if self.blendshape.get_weight_value(w) != 0 and w in primary_shapes]
        return active_weights

    def get_active_state_name(self):
        """
        Generate the name based on all the weights on self.blendshape that are not zero.
        Returns:
            str: The generated name for the active state.
        """
        active_weights = self.get_active_primary_weights()
        if not active_weights:
            return None
        weight_names = list()
        for w in active_weights:
            weight_value = self.blendshape.get_weight_value(w)
            if weight_value < 0:
                raise ValueError(f"Weight {w} has a negative value {weight_value}. "
                                 "Active state name cannot be generated with negative weights.")
            if weight_value > 1:
                raise ValueError(f"Weight {w} has a value greater than 1 ({weight_value}). "
                                 "Active state name cannot be generated with weights greater than 1.")
            weight_str_value = int(round(weight_value * 100)) if weight_value < 1 else ""
            weight_names.append(f"{w}{weight_str_value}")

        return self.separator.join(sorted(weight_names))

    def get_shape(self, shape_name: str):
        """
        Get a shape from the Blue Steel network.
        Parameters:
            shape_name (str): The name of the shape to get
        Returns:
            Shape: The shape instance if found, None otherwise.
        Example:
            >>> shape = blue_steel.get_shape("myShape")
            >>> print(shape)
            Shape: myShape
        """
        return self.network.get_shape(shape_name)

    def add_primary_shape(self, mesh: str, shape: Shape, invert_shape: bool = True):
        """
        Add a primary shape to the Blue Steel rig.
        Parameters:
            mesh (str): The name of the mesh to add the shape to
            shape (Shape): The shape instance to add
            invert_shape (bool): Whether to invert the shape
        Returns:
            Either if the shape was ADDED or UPDATED.
        """
        return_value = None
        # setting the pose of the rig to the primary shape
        if mesh is None or not cmds.objExists(mesh):
            mesh = self.base_mesh
            #raise ValueError(f"Shape {shape} does not exist")
        
        # check if the shape already exists in the blendshape
        if shape not in self.blendshape.get_weights(): # this is a new primary shape
            ctrl_attr =  None
            # we need to add the primary weight to the control group
            if cmds.objExists(self.face_ctrl):
                ctrl_attr = attrUtils.add_float_attr(self.face_ctrl, shape)
            if ctrl_attr is None:
                raise ValueError(f"Could not add control attribute for primary shape '{shape}' to face cibtrik group.")
            w = self.blendshape.add_target(weight_name=shape)
            # we need to connect the the blendshape weight to the face control attribute
            cmds.connectAttr(ctrl_attr,f"{self.blendshape.name}.{shape}", force=True)
            self.container.bind_attribute(ctrl_attr)
            if VERBOSE:
                print(f"Adding new {shape.type} shape {shape}")
            return_value = "ADDED"
            # let's create a shape target directory under the primary shapes group
            primary_dir = self.blendshape.get_target_dirs_by_name(self.PRIMARY_SHAPES_GRP_NAME)
            if primary_dir == []: # we need to create the primary shapes group
                primary_dir = self.blendshape.add_target_dir(self.PRIMARY_SHAPES_GRP_NAME)
            else:
                primary_dir = primary_dir[0]
            primary_shape_dir = self.blendshape.add_target_dir(name=shape,
                                                               parent_index=primary_dir.index)
            # let's parent the weight to the primary shape dir
            self.blendshape.set_weight_parent_directory(w, primary_shape_dir)
            # will add a split attribute to the shape to store the split maps
            self.add_primary_split_map_attribute(shape)
            self.set_shape_pose(shape)
        else:
            w = self.blendshape.get_weight_by_name(shape)
                    # we need to reset the delta of the shape before extracting the combo shape
            self.blendshape.reset_target(weight=w)
            self.set_shape_pose(shape)
            if VERBOSE:
                print(f"Updating existing {shape.type} shape {shape}")
            return_value = "UPDATED"
        if invert_shape:
            # extracting the combo shape
            inverted_shape = cmds.invertShape(self.base_mesh, mesh)
            self.blendshape.connect_mesh_to_target(w.id, inverted_shape)
            cmds.delete(inverted_shape)
        else:
            self.blendshape.connect_mesh_to_target(w.id, mesh)
            self.blendshape.disconnect_mesh_from_target(w.id)
        shape.weight_id = w.id
        self.network.add_shape(shape)
        # we will set the shape now
        
        return return_value

    @undoable
    def duplicate_base_mesh_neutral_state(self, mesh_name: str)->str:
        """
        Duplicate the base mesh in its neutral state.
        Parameters:
            mesh_name (str): The name of the duplicated mesh.
        Returns:
            str: The name of the duplicated mesh.
        """
        base_mesh = self.base_mesh
        if base_mesh is None:
            raise ValueError("Base mesh not found.")
        duplicated = cmds.duplicate(base_mesh, name=mesh_name)[0]
        # we need to unlock all the transform attributes of the duplicated mesh
        for axis in ["X", "Y", "Z"]:
            for attr in ["translate", "rotate", "scale"]:
                cmds.setAttr(f"{duplicated}.{attr}{axis}", lock=False)
        # we need to remove all the intermediate objects.
        shapes = cmds.listRelatives(duplicated, shapes=True, fullPath=True) or []
        for shape in shapes:
            if cmds.getAttr(f"{shape}.intermediateObject"):
                cmds.delete(shape)
        # we need to get the base mesh points and set them to the duplicated mesh to make sure it's in the neutral state without any deformations
        base_points = self.blendshape.get_base_points()
        mayaUtils.set_points_from_numpy(duplicated, base_points)
        return duplicated


    def duplicate_base_mesh_at_current_pose(self)->str: 
        """
        Duplicate the base mesh at the current pose.
        Returns:
            str: The name of the duplicated mesh.
        """
        pose_name = self.get_active_state_name()
        if pose_name is None:
            raise ValueError("Cannot duplicate base mesh at current pose because no primary shapes are active.")
        base_mesh = self.base_mesh
        if base_mesh is None:
            raise ValueError("Base mesh not found.")
        extracted = cmds.duplicate(base_mesh, name=pose_name)
        # we need to unlock all the transform attributes of the duplicated mesh
        for axis in ["X", "Y", "Z"]:
            for attr in ["translate", "rotate", "scale"]:
                cmds.setAttr(f"{extracted[0]}.{attr}{axis}", lock=False)
        if extracted[0] != pose_name:
            extract_group = cmds.createNode("transform", name=f"{pose_name}_extracted_GRP")
            extracted = cmds.parent(extracted[0], extract_group)[0]
            extracted = cmds.rename(extracted, pose_name)
        # we need to move the mesh to the side
        bbox = mayaUtils.get_mesh_bounding_box(base_mesh)
        offset = (bbox[1][0] - bbox[0][0]) * 1.1
        cmds.move(offset, 0, 0, extracted, relative=True, worldSpace=True)
        return extracted

    def set_work_shape_mute_state(self, shape_name: str, state: bool):
        """
        Mute or unmute a shape in the work blendshape.
        Parameters:
            shape_name (str): The name of the shape to mute or unmute
            state (bool): True to mute, False to unmute
        Returns:
            None
        """
        if self.work_blendshape is None:
            raise ValueError("Work blendshape not found.")
        w = self.work_blendshape.get_weight_by_name(shape_name)
        if w is None:
            raise ValueError(f"Shape {shape_name} does not exist in the work blendshape")
        parent_dir = self.work_blendshape.get_weight_parent_directory(w)
        self.work_blendshape.set_target_dir_weight_value(parent_dir, 0.0 if state else 1.0)
        # self.work_blendshape.set_target_mute_state(w, state)

    def sync_up_muted_shapes(self):
        """
        Sync up the muted shapes in the blendshape with the network.
        This is useful when the mute state of the shapes is changed outside of the API.
        Returns:
            None
        """
        self.sync_network() # just rebuilding the network to make sure it's up to date
        muted_shapes = self.get_muted_shapes()
        for shape in self.network._shapes:
            shape.muted = True if shape in muted_shapes else False

    def set_shape_mute_state(self, shape_name: str, state: bool):
        """
        Mute or unmute a shape in the blendshape.
        Parameters:
            shape_name (str): The name of the shape to mute or unmute
            state (bool): True to mute, False to unmute
        Returns:
            None
        """
        self.sync_network() # just rebuilding the network to make sure it's up to date
        w = self.blendshape.get_weight_by_name(shape_name)
        if w is None:
            raise ValueError(f"Shape {shape_name} does not exist in the blendshape")
        # we need to mute the group above the shape only.
        parent_dir = self.blendshape.get_weight_parent_directory(w)
        self.blendshape.set_target_dir_weight_value(parent_dir, 0.0 if state else 1.0)
        shape = self.network.get_shape(shape_name)
        if state:
            self.network.muted_shapes.add(shape)
        else:
            self.network.muted_shapes.discard(shape)

    def unmute_all_shapes(self):
        """
        Unmute all the shapes in the blendshape.
        Returns:
            None
        """
        self.sync_network() # just rebuilding the network to make sure it's up to date
        for w in self.blendshape.get_weights():
            self.blendshape.set_target_mute_state(w, False)
            parent_dir = self.blendshape.get_weight_parent_directory(w)
            self.blendshape.set_target_dir_weight_value(parent_dir, 1.0)
        for shape in self.network._shapes:
            shape.muted = False

    def get_muted_shapes(self):
        """
        Get all the muted shapes from the blendshape.
        Returns:
            list: A list of muted Shape instances.
        """
        self.sync_network() # just rebuilding the network to make sure it's up to date
        muted_shapes = ShapeList([], self.separator)
        weights = self.blendshape.get_weights()
        for w in weights:
            parent_dir = self.blendshape.get_weight_parent_directory(w)
            target_muted = not bool(self.blendshape.get_target_dir_weight_value(parent_dir))
            if target_muted:
                shape = self.network.get_shape(w)
                if shape:
                    muted_shapes.append(shape)
        return muted_shapes
    
    @undoable
    def reset_delta_for_shapes(self, shape_names: list):
        """
        Reset the delta for multiple shapes in the blendshape.
        Parameters:
            shape_names (list): The names of the shapes to reset the delta for
        Returns:
            None
        """
        self.sync_network() # just rebuilding the network to make sure it's up to date
        for shape_name in shape_names:
            w = self.blendshape.get_weight_by_name(shape_name)
            if w is None:
                raise ValueError(f"Shape {shape_name} does not exist in the blendshape")
            self.blendshape.reset_target(weight=w, use_api=False)  


    def add_inbetween_shape(self, mesh: str, shape: Shape, invert_shape: bool = True):
        """
        Add an inbetween shape to the Blue Steel rig.
        Parameters:
            mesh (str): The name of the mesh to add the shape to
            shape (Shape): The shape to add
            invert_shape (bool): Whether to invert the shape
        Returns:
            str: Either "ADDED" if the shape was added or "UPDATED" if the shape was updated.
        """
        if mesh is None or not cmds.objExists(mesh):
            mesh = self.base_mesh
            #raise ValueError(f"Shape {mesh} does not exist")
        # to avoid interference when extracting the delta from the mesh
        return_value = None
        if shape not in self.blendshape.get_weights(): # this is a new inbetween shape
            # setting the pose of the rig to the inbetween shape
            w = self.blendshape.add_target(shape)
            shape.weight_id = w.id
            self.network.add_shape(shape)
            # reset the delta of the shape before setting it
            self.blendshape.reset_target(weight=w)
            if VERBOSE:
                print(f"Adding new {shape.type} shape {shape}")
            return_value = "ADDED"
            # we need to create the remapValue node for the inbetween shape
            self.create_remap_value_node(shape)
            self.update_remap_nodes_values(shape.primaries[0])
            # let's create a shape target directory under the inbetween shapes group
            inbetween_dir = self.blendshape.get_target_dirs_by_name(self.INBETWEEN_SHAPES_GRP_NAME)
            if inbetween_dir == []: # we need to create the inbetween shapes group
                inbetween_dir = self.blendshape.add_target_dir(self.INBETWEEN_SHAPES_GRP_NAME)
            else:
                inbetween_dir = inbetween_dir[0]
            inbetween_shape_dir = self.blendshape.add_target_dir(name=shape,
                                                                 parent_index=inbetween_dir.index)
            # let's parent the weight to the inbetween shape dir
            self.blendshape.set_weight_parent_directory(w, inbetween_shape_dir)
        else:
            # we need to mute the shape before getting the delta from the mesh
            w = self.blendshape.get_weight_by_name(shape)
            if VERBOSE:
                print(f"Updating existing {shape.type} shape {shape}")
            return_value = "UPDATED"
            shape.weight_id = w.id
            self.network.add_shape(shape)
        # erasing the delta
        self.blendshape.reset_target(weight=w)
        # setting the pose of the rig to the inbetween shape
        self.set_shape_pose(shape)
        # extracting the inbetween shape
        if invert_shape:
            inverted_shape = cmds.invertShape(self.base_mesh, mesh)
            self.blendshape.connect_mesh_to_target(w.id, inverted_shape)
            cmds.delete(inverted_shape)
        else:
            self.blendshape.connect_mesh_to_target(w.id, mesh)
            self.blendshape.disconnect_mesh_from_target(w.id)
        return return_value

    def add_combo_shape(self, mesh: str, shape: Shape, invert_shape: bool = True):
        """
        Add a combo shape to the Blue Steel rig.
        Parameters:
            shape (Shape): The shape to add
        Returns:
            Either if the shape was ADDED or UPDATED.
        """
        return_value = None
        # setting the pose of the rig to the combo shape
        self.set_shape_pose(shape)
        if not cmds.objExists(mesh):
            mesh = self.blendshape.get_base()
            #raise ValueError(f"Shape {mesh} does not exist")
        # check if the shape already exists in the blendshape
        if shape not in self.blendshape.get_weights(): # this is a new combo shape
            if VERBOSE:
                print(f"Adding new {shape.type} shape {shape}")
            return_value = "ADDED"
            w = self.blendshape.add_target(shape)
            # we need to create a target directory under the combo shapes group
            combo_dir = self.blendshape.get_target_dirs_by_name(self.COMBO_SHAPES_GRP_NAME)
            if combo_dir == []: # we need to create the combo shapes group
                combo_dir = self.blendshape.add_target_dir(self.COMBO_SHAPES_GRP_NAME)
            else:
                combo_dir = combo_dir[0]
            combo_shape_dir = self.blendshape.add_target_dir(name=shape,
                                                             parent_index=combo_dir.index)
            # let's parent the weight to the combo shape dir
            self.blendshape.set_weight_parent_directory(w, combo_shape_dir)

            # we need to create a combo node for the combo shape
            self.create_combo_node(shape)
            
        else:
            w = self.blendshape.get_weight_by_name(shape)
            if VERBOSE:
                print(f"Updating existing {shape.type} shape {shape}")
            return_value = "UPDATED"
        shape.weight_id = w.id
        self.network.add_shape(shape)
        # we need to reset the delta of the shape before extracting the combo shape
        self.blendshape.reset_target(weight=w)
        if invert_shape:
            # extracting the combo shape
            inverted_shape = cmds.invertShape(self.base_mesh, mesh)
            self.blendshape.connect_mesh_to_target(w.id, inverted_shape)
            cmds.delete(inverted_shape)
        else:
            self.blendshape.connect_mesh_to_target(w.id, mesh)
            self.blendshape.disconnect_mesh_from_target(w.id)
        return return_value

    def add_split_map_attribute_group(self, group_name: str):
        """
        Add a split map attribute group to the Blue Steel rig
        Parameters:
            group_name (str): The name of the group to add
        Returns:
            str: The name of the group
        Example:
            >>> blue_steel = BlueSteelEditor.create_new("myMesh")
            >>> split_map_grp = blue_steel.add_split_map_attribute_group("mySplitMapGroup")

        """
        if cmds.objExists(group_name):
            raise ValueError(f"Group {group_name} already exist")
        split_attr_grp = attrUtils.create_attribute_grp(group_name)
        cmds.parent(split_attr_grp, self.split_attr_grp)
        self.container.add_member(split_attr_grp)
        return split_attr_grp

    def get_shapes_with_zero_delta(self):
        """
        Get all the shapes with zero delta from the blendshape.
        Returns:
            list: A list of Shape instances with zero delta.
        """
        self.sync_network() # just rebuilding the network to make sure it's up to date
        zero_delta_shapes = ShapeList([], self.separator)
        for w in self.blendshape.get_weights():
            delta = self.blendshape.get_target_delta(w.id)
            if np.allclose(delta, 0.0, rtol=1e-03, atol=1e-05):
                print(f"Shape '{w}' has zero delta.")
                shape = self.network.get_shape(w)
                if shape and shape.type != "PrimaryShape":
                    zero_delta_shapes.append(shape)
        return zero_delta_shapes


    @staticmethod
    def get_editors():
        """
        Get all the Blue Steel rigs in the scene
        Returns:
            list: A list of BlueSteelEditor containers names
        Example:
            >>> blue_steel_editors = BlueSteelEditor.get_editors()

        """
        return attrUtils.get_nodes_by_tag("BlueSteelEditorMain")


    @staticmethod
    def add_new_blendshape_to_container(blendshape_name:str,
                                        mesh_name: str,
                                        container: Container,
                                        message_attr: str,
                                        parent_directory_index: int = 0) -> str:
        """
        Add a blendshape to an existing Blue Steel rig
        Parameters:
            mesh_name (str): The name of the mesh to add as a blendshape
            container (Container): The BlueSteelEditor container
            message_attr (str): The message attribute of the blendshape
        Returns:
            str: The Blendshape instance
        Example:
            >>> container = Container("myMesh_BlueSteelEditor")
            >>> blendshape = BlueSteelEditor.add_new_blendshape_to_container("myBlendshape", container)

        """
        if cmds.objExists(blendshape_name):
            raise ValueError(f"Blendshape {blendshape_name} already exists")
        blendshape_node = cmds.blendShape(mesh_name, name=blendshape_name, foc=True)[0]
        # getting the layer id of the blendshape
        # this is the identifier of the blendshape in the shape editor
        layer_id = cmds.getAttr(f"{blendshape_node}.midLayerId")
        # getting the children of the current layer id
        root_children = cmds.getAttr("shapeEditorManager.blendShapeDirectory[0].childIndices") or []
        if layer_id in root_children:
            root_children.remove(layer_id)
        cmds.setAttr("shapeEditorManager.blendShapeDirectory[0].childIndices",
                     root_children,
                     type="Int32Array")
        parent_child_attr = f"shapeEditorManager.blendShapeDirectory[{parent_directory_index}].childIndices"
        parent_dir_children = cmds.getAttr(parent_child_attr) or []
        if layer_id not in parent_dir_children:
            parent_dir_children.append(layer_id)
        cmds.setAttr(parent_child_attr,
                     parent_dir_children,
                     type="Int32Array")
        cmds.setAttr(f"{blendshape_node}.midLayerParent", parent_directory_index)
        attrUtils.add_message_attr(container.name, message_attr, blendshape_node)
        container.add_member(blendshape_node)
        return blendshape_node

    @classmethod
    @undoable
    def create_new(cls, editor_name: str,mesh_name: str, separator: str = SEPARATOR):
        """
        Create a new Blue Steel rig
        Parameters:
            mesh_name (str): The name of the mesh to rig
        Returns:
            BlueSteelEditor: The BlueSteelEditor instance
        Example:
            >>> blue_steel = BlueSteelEditor.create_new("myMesh")

        """
        stored_selection = cmds.ls(selection=True)
        if not cmds.objExists(mesh_name):
            raise ValueError(f"Mesh {mesh_name} does not exist")

        container_name = f"{editor_name}_blueSteelEditor"
        container = Container.create(container_name)
        container_name = container.name
        # node network container
        node_network_container_name = f"{editor_name}_nodeNetwork"
        if cmds.objExists(node_network_container_name):
            raise ValueError(f"Node network container {node_network_container_name} already exists")
        network_container = Container.create(node_network_container_name)
        network_container.set_icon("node_network_icon.svg")
        # add a message attribute to link the base mesh to the container
        attrUtils.add_message_attr(container.name, cls.BASE_MESH_STRING_IDENTIFIER, mesh_name)
        attrUtils.add_message_attr(container.name, cls.NODE_NETWORK_CONTAINER_STRING_IDENTIFIER, network_container.name)
        attrUtils.add_tag(container.name, "lockedShapes", "")
        container.add_member(network_container.name)
        # create the split map edit mesh attribute
        attrUtils.add_message_attr(container.name, cls.SPLIT_MAP_EDIT_MESH_ATTR_STRING_IDENTIFIER)

        editor_group_name = f"{editor_name}_Blendshapes_GRP"
        editor_grp_id = cls.add_shape_editor_directory(editor_group_name)

        blendshape_names_suffixes = ["mainBlendshape","splitBlendshape", "workBlendshape"]
        message_attributes = [cls.MAIN_BLENDSHAPE_STRING_IDENTIFIER,
                               cls.SPLIT_BLENDSHAPE_STRING_IDENTIFIER,
                               cls.WORK_BLENDSHAPE_STRING_IDENTIFIER]
        # create the blendshape node blendshape.
        for suffix, message_attr in zip(blendshape_names_suffixes, message_attributes):
            blendshape_name = f"{editor_name}_{suffix}"
            cls.add_new_blendshape_to_container(blendshape_name=blendshape_name,
                                                mesh_name=mesh_name,
                                                container=container,
                                                message_attr=message_attr,
                                                parent_directory_index=editor_grp_id)
            if suffix == "mainBlendshape":
                # adding the target groups to the blendshape editor
                blendshape = Blendshape(blendshape_name)
                blendshape.add_target_dir(cls.PRIMARY_SHAPES_GRP_NAME)
                blendshape.add_target_dir(cls.INBETWEEN_SHAPES_GRP_NAME)
                blendshape.add_target_dir(cls.COMBO_SHAPES_GRP_NAME)
                
        # create the controls group node
        face_ctrl_name = f"{editor_name}_face_CTRL"
        if cmds.objExists(face_ctrl_name):
            raise ValueError(f"Face control {face_ctrl_name} already exists")
        face_ctrl = attrUtils.create_attribute_grp(face_ctrl_name, lock_transforms=False)
        # let's show the display handles
        cmds.setAttr(f"{face_ctrl}.displayHandle", 1)
        # let's get the bounding box of the mesh to position the control
        bbox = mayaUtils.get_mesh_bounding_box(mesh_name)
        width = bbox[1][0] - bbox[0][0]
        offset = width * 0.1
        x = bbox[1][0] + offset
        y = (bbox[0][1] + bbox[1][1]) / 2
        z = (bbox[0][2] + bbox[1][2]) / 2
        cmds.setAttr(f"{face_ctrl}.translateX", x)
        cmds.setAttr(f"{face_ctrl}.translateY", y)
        cmds.setAttr(f"{face_ctrl}.translateZ", z)
        container.add_member(face_ctrl)
        attrUtils.add_message_attr(container.name, cls.FACE_CTRL_STRING_IDENTIFIER, face_ctrl)
        # create the split attribute group node
        split_settings_grp_name = f"{editor_name}_splitSettings_GRP"
        split_settings_grp = attrUtils.create_attribute_grp(split_settings_grp_name)
        container.add_member(split_settings_grp)
        attrUtils.add_message_attr(container.name, cls.SPLIT_ATTR_GRP_STRING_IDENTIFIER, split_settings_grp)
        # set the icon of the container
        container.set_icon("blue_steel_icon.svg")

        # adding the version and the tag to recognize the container as a Blue Steel rig
        attrUtils.add_tag(container.name, "BlueSteelEditorMain", env.VERSION)
        # restoring the selection
        if stored_selection:
            cmds.select(stored_selection, replace=True)
        else:
            cmds.select(clear=True)
        editor = BlueSteelEditor(container.name, separator=separator)
        return editor

    @classmethod
    def add_shape_editor_directory(cls, group_name: str):
        """
        Add a directory to the shape editor for Blue Steel blendshapes
        Parameters:
            group_name (str): The name of the group to add
        Returns:
            int: The index of the new directory
        Example:
            >>> dir_index = BlueSteelEditor.add_shape_editor_directory("myBlueSteelShapes_GRP")

        """
        dir_id = attrUtils.get_next_available_index("shapeEditorManager.blendShapeDirectory")
        # adding dir to the shape editor main group children
        root_children = cmds.getAttr("shapeEditorManager.blendShapeDirectory[0].childIndices") or []
        root_children.append(-dir_id)
        cmds.setAttr("shapeEditorManager.blendShapeDirectory[0].childIndices",
                     root_children,
                     type="Int32Array")
        # renaming the group
        cmds.setAttr(f"shapeEditorManager.blendShapeDirectory[{dir_id}].directoryName",
                     group_name, type="string")
        return dir_id

    @classmethod
    def get_shape_editor_directory_index(cls, container_name: str) -> list:
        """
        Get the index of a directory in the shape editor
        Parameters:
            group_name (str): The name of the group to get the index for
        Returns:
            int: The index of the directory
        Example:
            >>> dir_index = BlueSteelEditor.get_shape_group_index("myBlueSteelShapes_GRP")
        """
        if container_name.endswith("_blueSteelEditor"):
            container_name = "_".join(container_name.split("_")[:-1])
        directory_name = f"{container_name}_Blendshapes_GRP"
        # print(f"Searching for directory name: {directory_name}")
        indices = []
        dir_count = cmds.getAttr("shapeEditorManager.blendShapeDirectory", size=True)
        for i in range(dir_count):
            dir_name = cmds.getAttr(f"shapeEditorManager.blendShapeDirectory[{i}].directoryName")
            if dir_name == directory_name:
                indices.append(i)
        return indices



    @classmethod
    def remove_shape_editor_directory(cls, dir_index: int):
        """
        Remove a directory from the shape editor
        Parameters:
            dir_index (int): The index of the directory to remove
        Returns:
            None
        Example:
            >>> BlueSteelEditor.remove_shape_editor_directory(3)
        """
        if dir_index == 0 or dir_index is None:
            return  # cannot remove the root directory
        # moving the children of the directory we are about to remove to the root directory
        parent_dir_index = cmds.getAttr(f"shapeEditorManager.blendShapeDirectory[{dir_index}].parentIndex")
        parent_children = cmds.getAttr(f"shapeEditorManager.blendShapeDirectory[{parent_dir_index}].childIndices") or []
        if -dir_index in parent_children:
            parent_children.remove(-dir_index)
        # reparenting the children of the directory to be removed to the root directory
        dir_children = cmds.getAttr(f"shapeEditorManager.blendShapeDirectory[{dir_index}].childIndices") or []
        parent_children.extend(dir_children)
        cmds.setAttr(f"shapeEditorManager.blendShapeDirectory[{parent_dir_index}].childIndices",
                     parent_children,
                     type="Int32Array")
        # deleting the directory
        cmds.removeMultiInstance(f"shapeEditorManager.blendShapeDirectory[{dir_index}]")


    @classmethod
    def rename_editor(cls, old_name: str, new_name: str)-> str:
        """
        Rename the editor and all its associated nodes.
        Parameters:
            old_name (str): The current name of the editor
            new_name (str): The new name for the editor
        Returns:
            str: The new name of the editor
        """
        if not cmds.objExists(old_name):
            raise ValueError(f"Editor '{old_name}' does not exist.")
        old_editor = BlueSteelEditor(old_name)
        # let's rename all the blendshape driver nodes
        weights = old_editor.blendshape.get_weights()
        for w in weights:
            driver = old_editor.blendshape.get_weight_driver(w)
            # check if this node is in the node network container
            if driver and cmds.objExists(driver) and driver in old_editor.node_network_container.members:
                driver_type = cmds.nodeType(driver)  # just to make sure the node exists
                new_driver_name = f"{new_name}_{w}_{driver_type}"
                cmds.rename(driver, new_driver_name)
        # renaming the linked nodes
        for link in [cls.MAIN_BLENDSHAPE_STRING_IDENTIFIER,
                     cls.SPLIT_BLENDSHAPE_STRING_IDENTIFIER,
                     cls.WORK_BLENDSHAPE_STRING_IDENTIFIER,
                     cls.SPLIT_ATTR_GRP_STRING_IDENTIFIER,
                     cls.NODE_NETWORK_CONTAINER_STRING_IDENTIFIER]:
            node_name = attrUtils.get_message_attr(old_editor.container.name, link)
            if node_name:
                new_node_name = f"{new_name}_{link}"
                cmds.rename(node_name, new_node_name)
        # renaming the container
        new_container_name = cmds.rename(old_editor.container.name, f"{new_name}_blueSteelEditor")
        return new_container_name
            
            
        

    #############################################################################################
    # Nodes management this could be refactored into a set of functions or a separate class
    #############################################################################################
    # remapValue node for inbetween shapes

    def create_combo_node(self, shape: Shape):
        """Create a combo node for the given combo shape.
        Parameters:
            shape (Shape): The combo shape to create the combo node for
        """
        if shape.type not in ["ComboShape", "ComboInbetweenShape"]:
            raise ValueError(f"Shape {shape} is not a ComboShape or ComboInbetweenShape")
        # first we need to check if the combo node already exists
        combo_node_name = f"{self.editor_base_name}_{shape}_combinationShape"
        combo_node = cmds.createNode("combinationShape", name=combo_node_name)
        for i, parent in enumerate(shape.parents):
            cmds.connectAttr(f"{self.blendshape.name}.{parent}", f"{combo_node}.inputWeight[{i}]", force=True)
        cmds.connectAttr(f"{combo_node}.outputWeight", f"{self.blendshape.name}.{shape}", force=True)
        # add the combo node to the node network container
        self.node_network_container.add_member(combo_node)
        return combo_node

    def create_remap_value_node(self, shape: Shape):
        """Create a remapValue node for the given inbetween shape.
        This function will also check if there are sibling inbetween shapes and adjust
        the remapValue nodes accordingly.
        Parameters:
            shape (Shape): The inbetween shape to create the remapValue node for
        """
        if shape.type != "InbetweenShape":
            raise ValueError(f"Shape {shape} is not an InbetweenShape")
        # we also need to check if there is a blendshape target for this shape
        w = self.blendshape.get_weight_by_name(shape)
        if w is None:
            raise ValueError(f"Shape {shape} does not have a blendshape target")
        # first we need to check if the remapValue node already exists
        remap_node_name = f"{self.editor_base_name}_{shape}_remapValue"
        remap_node = cmds.createNode("remapValue", name=remap_node_name)
        # setting the default values this will be adjusted later.
        cmds.setAttr(f"{remap_node}.value[0].value_Position", 0.0)
        cmds.setAttr(f"{remap_node}.value[0].value_FloatValue", 0.0)

        cmds.setAttr(f"{remap_node}.value[1].value_Position", 0.5)
        cmds.setAttr(f"{remap_node}.value[1].value_FloatValue", 1.0)

        cmds.setAttr(f"{remap_node}.value[2].value_Position", 1.0)
        cmds.setAttr(f"{remap_node}.value[2].value_FloatValue", 0.0)
        # now we need to connect the remapValue node to the blendshape node
        primary = shape.primaries[0]
        cmds.connectAttr(f"{self.blendshape.name}.{primary}", f"{remap_node}.inputValue", force=True)
        cmds.connectAttr(f"{remap_node}.outValue", f"{self.blendshape.name}.{w}", force=True)
        # add the node to the node network container
        self.node_network_container.add_member(remap_node)
        return remap_node

    def update_remap_nodes_values(self, shape: Shape):
        """Set the remapValue node values for the given inbetween shape.
        This function will also check if there are sibling inbetween shapes and adjust
        the remapValue nodes accordingly.
        Parameters:
            shape (Shape): The inbetween shape to set the remapValue node values for
        """
        if shape.type != "PrimaryShape":
            raise ValueError(f"Shape {shape} is not a PrimaryShape")
        # we need to find all the inbetween shapes for this primary shape
        inbetweens = self.network.get_inbetween_shapes_for_primary(shape)
        # we need to get the first inbetween
        for i in range(len(inbetweens)):
            previous = inbetweens[i-1] if i > 0 else None
            current = inbetweens[i]
            next = inbetweens[i+1] if i < len(inbetweens)-1 else None
            w = self.blendshape.get_weight_by_name(current)
            if w is None:
                raise ValueError(f"Shape {current} does not have a blendshape target")
            driver = self.blendshape.get_weight_driver(w)
            remap_node = driver if driver and cmds.nodeType(driver) == "remapValue" else None
            if remap_node is None:
                raise ValueError(f"Shape {current} does not have a remapValue node")
            previous_position = previous.values[0] if previous else 0.0
            current_position = current.values[0]
            next_position = next.values[0] if next else 1.0
            # setting the remapPosition based on the shapes values
            cmds.setAttr(f"{remap_node}.value[0].value_Position", previous_position)
            cmds.setAttr(f"{remap_node}.value[1].value_Position", current_position)
            cmds.setAttr(f"{remap_node}.value[2].value_Position", next_position)


    @undoable
    def prepare_for_publishing(self):
        """Prepare the rig for publishing by:
         - Unmuting all the shapes.
         - Zero out all the shapes.
         - Remove the main blendshape node and the face control from the container.
         - Remove all the nodes in the node network container from the container.
         - Set the blendshape midlayer parent to 0 to unparent it from the shape editor directory.
         - Delete the container and all the members left in it."""
        self.unmute_all_shapes()
        self.zero_out()
        # we need to parentthe blendshape node mid parent layer to the group 0 in the shape editor to unparent it from the shape editor directory
        self.blendshape.set_mid_layer_parent(0)
        # we need to remove all the nodes in the node network container from the container
        self.container.remove_member(self.node_network_container.name)
        for member in self.node_network_container.members:
            self.node_network_container.remove_member(member)
        # we need to remove the blendshape node from the container
        self.container.remove_member(self.blendshape.name)
        self.container.remove_member(self.face_ctrl)
        cmds.delete(self.node_network_container.name)
        cmds.delete(self.container.name)
        
        # we need to pull out the 

    # CUSTOM SHAPES COLORING
    def _add_custom_shapes_color_attribute(self):
        """Add a custom attribute to the container to store the custom shapes color.
        The attribute is a JSON string mapping shape names to colors in the format "#RRGGBB".
        """
        if not cmds.attributeQuery(self.CUSTOM_SHAPES_COLOR_ATTR_STRING_IDENTIFIER, node=self.container.name, exists=True):
            cmds.addAttr(self.container.name, longName=self.CUSTOM_SHAPES_COLOR_ATTR_STRING_IDENTIFIER, dataType="string")
            cmds.setAttr(f"{self.container.name}.{self.CUSTOM_SHAPES_COLOR_ATTR_STRING_IDENTIFIER}", "", type="string")

    def read_custom_shapes_colors(self) -> dict:
        """ Reads the custom shapes color attribute string and returns adictionary
        with the name of the shape as key and the color as value in the format "#RRGGBB"
        Returns:
            dict: A dictionary with the name of the shape as key and the color as value in the format "#RRGGBB"
        """
        color_attr = self.CUSTOM_SHAPES_COLOR_ATTR_STRING_IDENTIFIER
        if not cmds.attributeQuery(color_attr, node=self.container.name, exists=True):
            return {}
        color_dict = attrUtils.read_json_attr(self.container.name, color_attr) or {}
        return color_dict

    def write_custom_shapes_colors(self, color_dict: dict):
        """ Writes the custom shapes color attribute string from a dictionary
        with the name of the shape as key and the color as value in the format "#RRGGBB"
        Parameters:
            color_dict (dict): A dictionary with the name of the shape as key and the color as value in the format "#RRGGBB"
        """
        color_attr = self.CUSTOM_SHAPES_COLOR_ATTR_STRING_IDENTIFIER
        if not cmds.attributeQuery(color_attr, node=self.container.name, exists=True):
            self._add_custom_shapes_color_attribute()
        attrUtils.write_json_attr(self.container.name, color_attr, color_dict)

    def clear_custom_shapes_colors(self):
        """ Clear the custom shapes color attribute string
        """
        self.write_custom_shapes_colors({})

    def set_shape_custom_color(self, shape_name: str, color: str):
        """Set a custom color for a shape.
        Parameters:
            shape_name (str): The name of the shape to set the color for.
            color (str): A string with the color in the format "#RRGGBB".
        """
        if not isinstance(color, str) or not color.startswith("#") or len(color) != 7:
            raise ValueError("Color must be a string in the format '#RRGGBB'")
        color_dict = self.read_custom_shapes_colors()
        color_dict[shape_name] = color
        self.write_custom_shapes_colors(color_dict)

    def remove_shape_custom_color(self, shape_name: str):
        """Remove a custom color for a shape.
        Parameters:
            shape_name (str): The name of the shape to remove the color for.
        """
        color_dict = self.read_custom_shapes_colors()
        if shape_name in color_dict:
            del color_dict[shape_name]
            self.write_custom_shapes_colors(color_dict)

    # SPLIT MAPS
    def _sync_up_split_maps_attributes(self):
        """ Sync up the split groups assignments attributes in the
        split settings node with the current primaries
        """
        self._add_split_group_attribute()
        self._add_split_maps_order_attribute()
        self.sync_network() # just rebuilding the network to make sure it's up to date
        if self.split_attr_grp is None or not cmds.objExists(self.split_attr_grp):
            raise ValueError("Split attribute group does not exist")
        # get only user-defined enum attributes in the split attribute group
        attrs = [
            attr for attr in (cmds.listAttr(self.split_attr_grp, userDefined=True) or [])
            if cmds.getAttr(f"{self.split_attr_grp}.{attr}", type=True) == "enum"
        ]
        # get the primaries in the network
        primaries = self.network.get_primary_shapes()
        # remove any attributes that are not in the primaries
        for attr in attrs:
            if attr not in primaries:
                cmds.deleteAttr(f"{self.split_attr_grp}.{attr}")
        # add any primaries that are not in the attributes
        for primary in primaries:
            if primary not in attrs:
                self.add_primary_split_map_attribute(primary)
        self.update_split_map_attributes_from_groups()

    def get_primary_split_group(self, primary: str) -> str:
        """Get the split group assigned to a primary shape.
        Parameters:
            primary (str): The name of the primary shape to get the split group for.
        Returns:
            str: The name of the split group assigned to the primary shape.
        """
        if self.split_attr_grp is None or not cmds.objExists(self.split_attr_grp):
            raise ValueError("Split attribute group does not exist")
        if not cmds.attributeQuery(primary, node=self.split_attr_grp, exists=True):
            raise ValueError(f"Primary {primary} does not have an attribute in the split settings node")
        enum_index = int(cmds.getAttr(f"{self.split_attr_grp}.{primary}"))
        enum_values = cmds.attributeQuery(primary, node=self.split_attr_grp, listEnum=True) or [""]
        enum_labels = enum_values[0].split(":") if enum_values[0] else []
        return enum_labels[enum_index] if enum_index < len(enum_labels) else "NoSplit"

    @undoable
    def set_primaries_split_group(self, primaries: list, group: str):
        """Set the split group assigned to a primary shape.
        Parameters:
            primaries (list): The names of the primary shapes to set the split group for.
            group (str): The name of the split group to assign to the primary shape.
        """
        if group is None or group == "":
            group = "NoSplit"
        if self.split_attr_grp is None or not cmds.objExists(self.split_attr_grp):
            raise ValueError("Split attribute group does not exist")
        for primary in primaries:
            if not cmds.attributeQuery(primary, node=self.split_attr_grp, exists=True):
                raise ValueError(f"Primary {primary} does not have an attribute in the split settings node")
            enum_values = cmds.attributeQuery(primary, node=self.split_attr_grp, listEnum=True) or [""]
            enum_labels = enum_values[0].split(":") if enum_values[0] else []
            if group not in enum_labels:
                raise ValueError(f"Group {group} is not a valid split group for primary {primary}")
            enum_index = enum_labels.index(group)
            cmds.setAttr(f"{self.split_attr_grp}.{primary}", enum_index)

    def update_split_map_attributes_from_groups(self):
        """Update all primary split-map enum attributes from split groups.

        The currently selected enum label is preserved when still available.
        If a selected label no longer exists, it falls back to ``NoSplit``.
        """
        if self.split_attr_grp is None or not cmds.objExists(self.split_attr_grp):
            raise ValueError("Split attribute group does not exist")

        split_groups = self.read_split_groups_attributes()
        enum_labels = ["NoSplit"] + [str(name) for name in split_groups.keys()]
        enum_labels = [label.replace(":", "_") for label in enum_labels]
        enum_name = ":".join(enum_labels)

        attrs = cmds.listAttr(self.split_attr_grp, userDefined=True) or []
        for attr in attrs:
            if attr == self.SPLIT_GRP_ATTR_STRING_IDENTIFIER:
                continue

            attr_full = f"{self.split_attr_grp}.{attr}"
            if cmds.getAttr(attr_full, type=True) != "enum":
                continue

            current_index = int(cmds.getAttr(attr_full))
            old_enum_values = cmds.attributeQuery(attr, node=self.split_attr_grp, listEnum=True) or [""]
            old_labels = old_enum_values[0].split(":") if old_enum_values[0] else []
            current_label = old_labels[current_index] if current_index < len(old_labels) else "NoSplit"

            cmds.addAttr(attr_full, edit=True, enumName=enum_name)
            new_index = enum_labels.index(current_label) if current_label in enum_labels else 0
            cmds.setAttr(attr_full, new_index)
            cmds.setAttr(attr_full, cb=True)

    def add_primary_split_map_attribute(self, primary: str):
        """Add an enum attribute for a primary shape on the split settings node.

        Index ``0`` is reserved for ``NoSplit`` and the following enum entries map
        to the current split group names.
        Parameters:
            primary (str): The name of the primary shape to add the attribute for.
        """
        if self.split_attr_grp is None or not cmds.objExists(self.split_attr_grp):
            raise ValueError("Split attribute group does not exist")
        if cmds.attributeQuery(primary, node=self.split_attr_grp, exists=True):
            #print(f"Primary {primary} already has an attribute in the split settings node")
            return

        split_groups = self.read_split_groups_attributes()
        enum_labels = ["NoSplit"] + list(split_groups.keys())
        enum_name = ":".join(str(label).replace(":", "_") for label in enum_labels)

        cmds.addAttr(self.split_attr_grp,
                     longName=primary,
                     attributeType="enum",
                     enumName=enum_name,
                     defaultValue=0)
        cmds.setAttr(f"{self.split_attr_grp}.{primary}", cb=True)

    def _add_split_maps_order_attribute(self):
        """ add a string attribute that contains a json format list with the order of the split groups.
        The attribute will be added to the split settings node.
        """
        #print("Adding split groups order attribute to the split settings node")
        # check if the split group attriute node exists
        if self.split_attr_grp is None or not cmds.objExists(self.split_attr_grp):
            raise ValueError("Split attribute group does not exist")
        # check if the attribute already exists
        group_attribute = attrUtils.add_string_attr(self.split_attr_grp,
                                                    self.SPLIT_MAPS_AREA_ORDER_ATTR_STRING_IDENTIFIER,
                                                    "[]")

    def _add_split_group_attribute(self):
        """ add a string attribute that contains a json format dictionary with the name of the group
        and the list of split maps assigned to that group. The attribute will be added to the split settings node.
        """
        # print("Adding split groups attribute to the split settings node")
        # check if the split group attriute node exists
        if self.split_attr_grp is None or not cmds.objExists(self.split_attr_grp):
            raise ValueError("Split attribute group does not exist")
        # check if the attribute already exists
        group_attribute = attrUtils.add_string_attr(self.split_attr_grp,
                                                    self.SPLIT_GRP_ATTR_STRING_IDENTIFIER,
                                                    "{}")

    def _ensure_split_shape_name_item_in_groups(self):
        """
        Just a quick sanity check to ensure that the split shape name item is in the split groups.
        """
        fixed_attributes = self.read_split_groups_attributes()
        for group, split_maps in fixed_attributes.items():
            if self.SHAPE_NAME_STR not in split_maps:
                split_maps.insert(0, self.SHAPE_NAME_STR)
                fixed_attributes[group] = split_maps
        self.write_split_groups_attributes(fixed_attributes)

    def read_split_groups_attributes(self) -> dict:
        """ read the split groups attribute and return a dictionary with the name of the group
        and the list of split maps assigned to that group.
        Returns:
            dict: A dictionary with the name of the group and the list of split maps assigned to that group.
        """
        if self.split_attr_grp is None or not cmds.objExists(self.split_attr_grp):
            raise ValueError("Split attribute group does not exist")
        if not cmds.attributeQuery(self.SPLIT_GRP_ATTR_STRING_IDENTIFIER, node=self.split_attr_grp, exists=True):
            raise ValueError("Split groups attribute does not exist")
        return attrUtils.read_json_attr(self.split_attr_grp, self.SPLIT_GRP_ATTR_STRING_IDENTIFIER) or {}

    def read_split_maps_order_attribute(self) -> list:
        """ read the split groups order attribute and return a list with the names of the groups in the order they should be displayed.
        Returns:
            list: A list with the names of the groups in the order they should be displayed.
        """
        if self.split_attr_grp is None or not cmds.objExists(self.split_attr_grp):
            raise ValueError("Split attribute group does not exist")
        if not cmds.attributeQuery(self.SPLIT_MAPS_AREA_ORDER_ATTR_STRING_IDENTIFIER, node=self.split_attr_grp, exists=True):
            raise ValueError("Split groups order attribute does not exist")
        return attrUtils.read_json_attr(self.split_attr_grp, self.SPLIT_MAPS_AREA_ORDER_ATTR_STRING_IDENTIFIER) or []

    def get_edit_split_map_weights(self) -> list:
        """ get the weights of a split map in the edit_blendshape.
        Parameters:
            split_map_name (str): The name of the split map.
        Returns:
            list: A list of weights for the split map.
        """
        if self.split_map_edit_blendshape is None or not cmds.objExists(self.split_map_edit_blendshape):
            raise ValueError("Split map edit blendshape does not exist")
        split_map_edit_blendshape = Blendshape(self.split_map_edit_blendshape)
        return split_map_edit_blendshape.get_weights()

    def get_edit_split_map_areas(self) -> list:
        """ get the areas of a split map in the edit_blendshape.
        Parameters:
            split_map_name (str): The name of the split map.
        Returns:
            list: A list of areas for the split map.
        """
        edit_weights = self.get_edit_split_map_weights()
        areas = [w.split("_")[-1] for w in edit_weights]
        return areas

    def get_split_map_areas(self, split_map_name: str) -> list:
        """ get the areas of a split map in the split_blendshape.
        Parameters:
            split_map_name (str): The name of the split map.
        Returns:
            list: A list of areas for the split map.
        """
        areas = []
        split_map_dir = self.split_blendshape.get_target_dirs_by_name(split_map_name)
        if not split_map_dir:
            raise ValueError(f"Split map {split_map_name} does not have a target directory")
        if len(split_map_dir) > 1:
            raise ValueError(f"Split map has multiple target directories named {split_map_name}.")
        child_target_dirs = self.split_blendshape.get_target_dir_child_target_dirs(split_map_dir[0])
        for child_dir in child_target_dirs:
            areas.append(child_dir.name)
        return areas

    def normalize_split_map_weights(self, split_map_name: str):
        """ normalize the weights of a split map in the split_blendshape.
        Parameters:
            split_map_name (str): The name of the split map.
        """
        split_map_dir = self.split_blendshape.get_target_dirs_by_name(split_map_name)
        if not split_map_dir:
            raise ValueError(f"Split map {split_map_name} does not have a target directory")
        if len(split_map_dir) > 1:
            raise ValueError(f"Split map has multiple target directories named {split_map_name}.")
        split_map_weights = self.get_split_map_weights(split_map_name)
        print(f"Normalizing weights for split map {split_map_name} with weights: {split_map_weights}")
        self.normalize_shapes_weight_map_values(self.split_blendshape, split_map_weights)

    def normalize_edit_split_map_weights(self):
        """ normalize the weights of a split map in the edit_blendshape.
        Parameters:
            split_map_name (str): The name of the split map.
        """
        if self.split_map_edit_blendshape is None or not cmds.objExists(self.split_map_edit_blendshape):
            raise ValueError("Split map edit blendshape does not exist")
        split_map_edit_blendshape = Blendshape(self.split_map_edit_blendshape)

        spit_map_weights = split_map_edit_blendshape.get_weights()
        self.normalize_shapes_weight_map_values(split_map_edit_blendshape, spit_map_weights)

    def is_split_map_normalized(self, split_map_name: str, tolerance: float = 1e-5) -> bool:
        """Return whether the split-map weights sum to 1.0 at every vertex."""
        split_map_weights = self.get_split_map_weights(split_map_name)
        if not split_map_weights:
            return False

        weight_map_values = [
            self.split_blendshape.get_weight_map_values(weight.id)
            for weight in split_map_weights
        ]
        if not weight_map_values or len(weight_map_values[0]) == 0:
            return False
        vertex_count = len(weight_map_values[0])
        if any(len(values) != vertex_count for values in weight_map_values):
            return False

        weight_sums = np.sum(np.asarray(weight_map_values, dtype=float), axis=0)
        return bool(np.allclose(weight_sums, 1.0, rtol=0.0, atol=tolerance))

    def get_split_map_weights(self, split_map_name: str) -> list:
        """ get the weights of a split map in the split_blendshape.
        Parameters:
            split_map_name (str): The name of the split map.
        Returns:
            list: A list of weights for the split map.
        """
        weights = []
        split_map_dir = self.split_blendshape.get_target_dirs_by_name(split_map_name)
        if not split_map_dir:
            raise ValueError(f"Split map {split_map_name} does not have a target directory")
        if len(split_map_dir) > 1:
            raise ValueError(f"Split map has multiple target directories named {split_map_name}.")
        child_target_dirs = self.split_blendshape.get_target_dir_child_target_dirs(split_map_dir[0])
        for child_dir in child_target_dirs:
            child_weights = self.split_blendshape.get_target_dir_child_weights(child_dir)
            weights.extend(child_weights)
        return weights

    def rename_edit_split_map_edit_blendshape_weight(self, split_map_name: str, old_name: str, new_name: str):
        """ rename the weights of a split map in the split_blendshape and in the edit_blendshape.
        Parameters:
            split_map_name (str): The name of the split map.
            old_name (str): The old name of the weight.
            new_name (str): The new name of the weight.
        """
        if split_map_name != self.get_current_edit_split_map():
            return
        # we need to rename the weight in the edit_blendshape
        old_weight_name = f"{split_map_name}_{old_name}"
        new_weight_name = f"{split_map_name}_{new_name}"
        split_map_edit_blendshape = Blendshape(self.split_map_edit_blendshape)
        old_weight = split_map_edit_blendshape.get_weight_by_name(old_weight_name)
        if old_weight is None:
            raise ValueError(f"Weight {old_weight_name} does not exist in edit blendshape")
        if split_map_edit_blendshape.get_weight_by_name(new_weight_name) is not None:
            raise ValueError(f"Weight {new_weight_name} already exists in edit blendshape")
        split_map_edit_blendshape.rename_weight(old_weight_name, new_weight_name)

    def rename_split_map_weight(self, split_map_name: str, old_name: str, new_name: str):
        """ rename the weights of a split map in the split_blendshape.
        Parameters:
            split_map_name (str): The name of the split map.
            old_name (str): The old name of the weight.
            new_name (str): The new name of the weight.
        """
        old_weight_name = f"{split_map_name}_{old_name}"
        new_weight_name = f"{split_map_name}_{new_name}"
        split_maps_weights = self.get_split_map_weights(split_map_name)
        old_weight = next((w for w in split_maps_weights if w == old_weight_name), None)
        if old_weight is None:
            raise ValueError(f"Weight {old_weight_name} does not exist in split map {split_map_name}")
        if new_weight_name in split_maps_weights:
            raise ValueError(f"Weight {new_weight_name} already exists in split map {split_map_name}")
        # we need to get the target directory for the split map
        split_map_dir = self.split_blendshape.get_weight_parent_directory(old_weight)
        if not split_map_dir:
            raise ValueError(f"Weight {old_weight_name} does not have a target directory")
        self.split_blendshape.rename_target_dir(split_map_dir, new_name)
        self.split_blendshape.rename_weight(old_weight_name, new_weight_name)
  
    def rename_split_map(self, old_name: str, new_name: str):
        """ rename a split map in the split_blendshape and in the split groups attribute.
        Parameters:
            old_name (str): The name of the split map to rename.
            new_name (str): The new name of the split map.
        """
        if old_name not in self.get_split_maps():
            raise ValueError(f"Split map {old_name} does not exist")
        if new_name in self.get_split_maps():
            raise ValueError(f"Split map {new_name} already exists")
        # we need to rename the target directory for the split map
        split_map_dir = self.split_blendshape.get_target_dirs_by_name(old_name)
        if not split_map_dir:
            raise ValueError(f"Split map {old_name} does not have a target directory")
        if len(split_map_dir) > 1:
            raise ValueError(f"Split map has multiple target directories named {old_name}.")
        self.split_blendshape.rename_target_dir(split_map_dir[0], new_name)
        # we need to rename the weights under the split map directory
        child_target_dirs = self.split_blendshape.get_target_dir_child_target_dirs(split_map_dir[0])
        for child_dir in child_target_dirs:
            child_weights = self.split_blendshape.get_target_dir_child_weights(child_dir)
            for child in child_weights:
                new_weight_name = child.replace(old_name, new_name)
                self.split_blendshape.rename_weight(child, new_weight_name)
        # we need to update the split groups attribute
        split_groups = self.read_split_groups_attributes()
        for group, maps in split_groups.items():
            if old_name in maps:
                maps[maps.index(old_name)] = new_name
                split_groups[group] = maps
        self.write_split_groups_attributes(split_groups)
        # we need to update the split maps order attribute
        split_maps_order = self.read_split_maps_order_attribute()
        if old_name in split_maps_order:
            split_maps_order[split_maps_order.index(old_name)] = new_name
        self.write_split_maps_order_attribute(split_maps_order)

    @undoable
    def delete_split_map(self, split_map_name: str):
        """ delete a split map in the split_blendshape and in the split groups attribute.
        Parameters:
            split_map_name (str): The name of the split map to delete.
        """
        if split_map_name not in self.get_split_maps():
            raise ValueError(f"Split map {split_map_name} does not exist")
        # we need to delete the target directory for the split map
        split_map_dir = self.split_blendshape.get_target_dirs_by_name(split_map_name)
        if not split_map_dir:
            raise ValueError(f"Split map {split_map_name} does not have a target directory")
        if len(split_map_dir) > 1:
            raise ValueError(f"Split map has multiple target directories named {split_map_name}.")
        # we need to remove all the targets under the split map directory before deleting it
        child_target_dirs = self.split_blendshape.get_target_dir_child_target_dirs(split_map_dir[0])
        for child_dir in child_target_dirs:
            child_weights = self.split_blendshape.get_target_dir_child_weights(child_dir)
            for child in child_weights:
                self.split_blendshape.remove_target(child)
            self.split_blendshape.remove_target_dir(child_dir)
        self.split_blendshape.remove_target_dir(split_map_dir[0])
        # we need to update the split groups attribute
        split_groups = self.read_split_groups_attributes()
        # empty_groups = []
        for group, maps in split_groups.items():
            if split_map_name in maps:
                maps.remove(split_map_name)
                split_groups[group] = maps
        # we need to update the split maps order attribute
        split_maps_order = self.read_split_maps_order_attribute()
        if split_map_name in split_maps_order:
            split_maps_order.remove(split_map_name)
        self.write_split_maps_order_attribute(split_maps_order)
        self.write_split_groups_attributes(split_groups)
        self.update_split_map_attributes_from_groups()

    def write_split_maps_order_attribute(self, split_maps_order: list):
        """ write the split groups order attribute with a list of the names of the groups in the order they should be displayed.
        Parameters:
            split_maps_order (list): A list of the names of the groups in the order they should be displayed.
        """
        if self.split_attr_grp is None or not cmds.objExists(self.split_attr_grp):
            raise ValueError("Split attribute group does not exist")
        attrUtils.write_json_attr(self.split_attr_grp,
                                  self.SPLIT_MAPS_AREA_ORDER_ATTR_STRING_IDENTIFIER,
                                  split_maps_order)

    def write_split_groups_attributes(self, split_groups: dict):
        """ write the split groups attribute with a dictionary with the name of the group
        and the list of split maps assigned to that group.
        Parameters:
            split_groups (dict): A dictionary with the name of the group and the list of split maps assigned to that group.
        """
        if self.split_attr_grp is None or not cmds.objExists(self.split_attr_grp):
            raise ValueError("Split attribute group does not exist")
        attrUtils.write_json_attr(self.split_attr_grp,
                                  self.SPLIT_GRP_ATTR_STRING_IDENTIFIER,
                                  split_groups)

    def get_split_maps(self,) -> list:
        """
        Reads the split_blendshape directories.
        Returns:
            list: A list of split_blendshape directories.
        """
        result = []
        split_maps_target_dirs = self.split_blendshape.get_target_dirs() or []
        for d in split_maps_target_dirs:
            if d.index == 0:
                continue
            if self.split_blendshape.get_target_dir_parent(d) == 0:
                result.append(d.name)
        return result

    def create_split_map(self, split_map_name: str, areas: list = []):
        """
        Create a new split map in the split_blendshape.
        Parameters:
            split_map_name (str): The name of the split map to create.
            areas (list): A list of areas to add to the split map. Default is [].
        Returns:
            str: The name of the created split map.
        """
        if split_map_name in self.get_split_maps():
            raise ValueError(f"Split map {split_map_name} already exists")
        # we need to create a target directory for the split map
        existing_weights = self.split_blendshape.get_weights()
        weight_names = [f"{split_map_name}_{area}" for area in areas]
        for weight in weight_names:
            if weight in existing_weights:
                raise ValueError(f"Weight {weight} already exists in the split_blendshape")
        split_map_dir = self.split_blendshape.add_target_dir(name=split_map_name)
        parent_index = split_map_dir.index
        # we need to add the weights to the split map
        for weight, area in zip(weight_names, areas):
            weight_name_dir = self.split_blendshape.add_target_dir(name=area, parent_index=parent_index)
            self.split_blendshape.add_target(weight, parent_directory=weight_name_dir)
        # we need to update the split maps order attribute
        split_maps_order = self.read_split_maps_order_attribute()
        split_maps_order.append(split_map_name)
        self.write_split_maps_order_attribute(split_maps_order)
        return split_map_dir.name

    def add_weight_to_split_map_edit_blendshape(self, split_map_name: str, area: str)-> str:
        """
        Add a weight to a split map in the split_blendshape edit blendshape.
        Parameters:
            split_map_name (str): The name of the split map to add the weights to.
            area (str): The name of the weight to add to the split map.
        Returns:
            the newly created weight name in the edit blendshape.
        """
        if self.get_current_edit_split_map() != split_map_name:
            return
        weight_name = f"{split_map_name}_{area}"
        edit_split_blend = Blendshape(self.split_map_edit_blendshape)
        existing_weights = edit_split_blend.get_weights()
        if weight_name not in existing_weights:
            weight =edit_split_blend.add_target(weight_name=weight_name)
            # we need to connect the target to the base mesh
            edit_split_blend.connect_mesh_to_target(weight_id=weight.id, mesh=self.base_mesh)
        return weight

    def preview_split_primary_name(self, split_group_name):
        """
        Preview the split shape names generated for a split group.
        Parameters:
            split_group_name (str): The name of the split group.
        Returns:
            tuple: (primary_name, [split_shape_names]) with one name per area combination.
        """
        primaries = self.network.get_primary_shapes()
        primary_name = primaries[0] if primaries else "shapeName"
        for primary in primaries:
            if self.get_primary_split_group(primary) == split_group_name:
                primary_name = primary
                break

        split_groups = self.read_split_groups_attributes()
        split_maps = split_groups.get(split_group_name)
        if not split_maps or len(split_maps) <= 1:
            raise ValueError(f"Split group {split_group_name} has no split maps")

        # each ordered entry contributes the options that are combined into the final names
        area_options = []
        for i, split_map in enumerate(split_maps):
            if split_map == self.SHAPE_NAME_STR:
                # the shape name is capitalized when it is used as a suffix
                shape_token = primary_name if i == 0 else primary_name[0].upper() + primary_name[1:]
                area_options.append([shape_token])
            else:
                areas = self.get_split_map_areas(split_map)
                area_options.append(areas if areas else [""])

        split_names = ["".join(combination) for combination in itertools.product(*area_options)]
        return (primary_name, split_names)

    @undoable
    def add_weight_to_split_map(self, split_map_name: str, area: str)-> Weight:
        """
        Add a weight to a split map in the split_blendshape.
        Parameters:
            split_map_name (str): The name of the split map to add the weights to.
            area (str): The name of the weight to add to the split map.
        Returns:
            Weight: The newly added weight.
        """
        if not re.match(r'^[a-zA-Z]+$', area):
            raise ValueError(f"Area {area} contains invalid characters. "
                             "Only alphabetic characters are allowed.")
        # we need to capitalize the first letter of the area
        split_map_dir = self.split_blendshape.get_target_dirs_by_name(split_map_name)
        if not split_map_dir:
            raise ValueError(f"Split map {split_map_name} does not have a target directory")
        if len(split_map_dir) > 1:
            raise ValueError(f"Split map has multiple target directories named {split_map_name}.")
        parent_index = split_map_dir[0].index
        existing_weights = self.split_blendshape.get_weights()
        weight_name = f"{split_map_name}_{area}"
        if weight_name in existing_weights:
            raise Warning(f"Weight {weight_name} already exists in the split_blendshape")
        # we need to add the weight to the split map
        weight_name_dir = self.split_blendshape.add_target_dir(name=area, parent_index=parent_index)
        weight = self.split_blendshape.add_target(weight_name, parent_directory=weight_name_dir)
        return weight
    @undoable
    def rename_split_group(self, old_name: str, new_name: str):
        """
        Rename a split group in the split_blendshape.
        Parameters:
            old_name (str): The name of the split group to rename.
            new_name (str): The new name of the split group.
        Returns:
            None
        """
        split_groups = self.read_split_groups_attributes()
        split_groups_association = self.get_primaries_split_groups_association()
        if old_name not in split_groups:
            raise ValueError(f"Split group {old_name} does not exist")
        if new_name in split_groups:
            raise ValueError(f"Split group {new_name} already exists")
        # we need to store the primaries with the old split group name and update them to the new split group name

        # we need to rename the split group
        split_groups[new_name] = split_groups.pop(old_name)
        self.write_split_groups_attributes(split_groups)
        self.update_split_map_attributes_from_groups()
        for primary, group in split_groups_association.items():
            if group == old_name:
                self.set_primaries_split_group([primary], new_name)


    @undoable
    def create_split_group(self, split_group_name: str, split_maps_list: list = []):
        """
        Create a new split group in the split_blendshape.
        Parameters:
            split_group_name (str): The name of the split group to create.
            split_maps_list (list): A list of split maps to add to the split group. Default is None.
        Returns:
            str: The name of the created split group.
        """
        # we need to add shape name as a place holder to understand where the split areas are going
        # the assumption is that all the split maps are suffixes
        if self.SHAPE_NAME_STR not in split_maps_list:
            split_maps_list = [self.SHAPE_NAME_STR] + split_maps_list

        split_groups = self.read_split_groups_attributes()
        # we need to create a target directory for the split group
        split_groups[split_group_name] = split_maps_list
        self.write_split_groups_attributes(split_groups)
        self.update_split_map_attributes_from_groups()
        return split_group_name

    @undoable
    def add_split_map_to_split_group(self, split_group_name: str, split_map_name: str):
        """
        Add a split map to a split group in the split_blendshape.
        Parameters:
            split_group_name (str): The name of the split group to add the split maps to.
            split_map_name (str): The name of the split map to add to the split group.
        Returns:
            None
        """
        if split_map_name not in self.get_split_maps():
            raise ValueError(f"Split map {split_map_name} does not exist")
        split_groups = self.read_split_groups_attributes()
        if split_group_name not in split_groups:
            raise ValueError(f"Split group {split_group_name} does not exist")
        # we need to add the split map to the split group
        existing_split_maps = split_groups[split_group_name]
        if split_map_name in existing_split_maps:
            raise ValueError(f"Split map {split_map_name} already exists in split group {split_group_name}")
        existing_split_maps.append(split_map_name)
        split_groups[split_group_name] = existing_split_maps
        self.write_split_groups_attributes(split_groups)
        self.update_split_map_attributes_from_groups()

    @undoable
    def remove_split_map_from_split_group(self, split_group_name: str, split_map_name: str):
        """
        Remove a split map from a split group in the split_blendshape.
        Parameters:
            split_group_name (str): The name of the split group to remove the split maps from.
            split_map_name (str): The name of the split map to remove from the split group.
        Returns:
            None
        """
        # if the split_map_name is the shape name we need to return.
        if split_map_name == self.SHAPE_NAME_STR:
            return
        if split_map_name not in self.get_split_maps():
            raise ValueError(f"Split map {split_map_name} does not exist")
        split_groups = self.read_split_groups_attributes()
        if split_group_name not in split_groups:
            raise ValueError(f"Split group {split_group_name} does not exist")
        # we need to remove the split maps from the split group
        existing_split_maps = split_groups[split_group_name]
        if split_map_name not in existing_split_maps:
            raise ValueError(f"Split map {split_map_name} does not exist in split group {split_group_name}")
        existing_split_maps.remove(split_map_name)
        split_groups[split_group_name] = existing_split_maps
        self.write_split_groups_attributes(split_groups)

    def remove_weight_from_split_map_edit_blendshape(self, split_map_name: str, weight_name: str):
        """
        Remove a target from a split map in the split_blendshape edit blendshape.
        Parameters:
            split_map_name (str): The name of the split map to remove the target from.
            weight_name (str): The name of the weight to remove from the split map.
        Returns:
            None
        """
        if self.get_current_edit_split_map() != split_map_name:
            return
        if self.split_map_edit_blendshape is None or not cmds.objExists(self.split_map_edit_blendshape):
            raise ValueError("Split map edit blendshape does not exist")
        edit_split_blend = Blendshape(self.split_map_edit_blendshape)
        weight_to_remove = edit_split_blend.get_weight_by_name(weight_name)
        if weight_to_remove is None:
            raise ValueError(f"Weight {weight_name} does not exist in edit blendshape")
        edit_split_blend.remove_target(weight_to_remove)

    @pause_shape_editor
    @undoable
    def remove_weight_from_split_map(self, split_map_name: str, weight_name: str):
        """
        Remove a target from a split map in the split_blendshape.
        Parameters:
            split_map_name (str): The name of the split map to remove the target from.
            weight_name (str): The name of the weight to remove from the split map.
        Returns:
            None
        """
        if split_map_name not in self.get_split_maps():
            raise ValueError(f"Split map {split_map_name} does not exist")
        split_weights = self.get_split_map_weights(split_map_name)
        weight_to_remove = None
        for weight in split_weights:
            if weight == weight_name:
                weight_to_remove = weight
                break
        if weight_to_remove is None:
            raise ValueError(f"Weight {weight_name} does not exist in split map {split_map_name}")
        # we need to remove the weight from the split map
        parent_dir = self.split_blendshape.get_weight_parent_directory(weight_to_remove)
        if parent_dir is None:
            raise ValueError(f"Weight {weight_name} does not have a parent directory")
        
        self.split_blendshape.remove_target(weight_to_remove)
        self.split_blendshape.remove_target_dir(parent_dir)

    @undoable
    def remove_split_group(self, split_group_name: str):
        """
        Remove a split group from the split_blendshape.
        Parameters:
            split_group_name (str): The name of the split group to remove.
        Returns:
            None
        """
        split_groups = self.read_split_groups_attributes()
        if split_group_name not in split_groups:
            raise ValueError(f"Split group {split_group_name} does not exist")
        # we need to remove the split group
        del split_groups[split_group_name]
        self.write_split_groups_attributes(split_groups)
        self.update_split_map_attributes_from_groups()

    def create_split_maps_meshes(self):
        """
        Create a duplicate of the mesh with a blendshape for each mesh.
        Returns:
            None
        """
        split_maps = self.get_split_maps()
        if not split_maps:
            raise ValueError("No split maps found to create a split maps mesh")
        # duplicate the mesh
        split_mesh_base_name = f"{self.base_mesh.split('|')[-1]}_split_maps"
        mesh_to_connect = None
        # we need to create a group where we will move the split maps meshes
        split_maps_group = f"{self.base_mesh.split('|')[-1]}_split_maps_grp"
        if not cmds.objExists(split_maps_group):
            split_maps_group = cmds.group(name=split_maps_group, empty=True)

        for split_map in split_maps:
            split_map_area_weights = list()
            blendshape_name = f"{split_map}_blendShape"
            split_mesh_name = f"{split_mesh_base_name}_{split_map}"
            split_mesh = self.duplicate_base_mesh_neutral_state(split_mesh_name)
            split_mesh = cmds.parent(split_mesh, split_maps_group)[0]
            split_map_blendshape = cmds.blendShape(split_mesh, name=blendshape_name)
            split_map_blendshape = Blendshape(split_map_blendshape[0])
            self.split_map_blendshapes[split_map] = split_map_blendshape
            split_map_areas = self.get_split_map_areas(split_map)
            split_map_weights = self.get_split_map_weights(split_map)
            for area, weight in zip(split_map_areas, split_map_weights):
                area_weight = split_map_blendshape.add_target(area)
                split_map_area_weights.append(area_weight)
                # we need to connect the weight maps to the split map blendshape
                self.split_blendshape.transfer_weight_map(source_weight_id = weight.id,
                                                          target_blendshape=split_map_blendshape.name,
                                                          target_weight_id=area_weight.id)
                if mesh_to_connect is None:
                    self.split_blendshape_to_connect = split_map_blendshape.name
                    mesh_to_connect = split_mesh
                    continue
                # we need to connect the ,esh_to connect to the target
                split_map_blendshape.connect_mesh_to_target(area_weight.id, mesh_to_connect)
            self.split_map_blendshapes_weights[split_map] = split_map_area_weights
            mesh_to_connect = split_mesh
        self.split_bake_mesh = split_mesh
        return split_maps_group

    @undoable
    @pause_shape_editor
    def split_shapes(self,  primary_list: list):
        """
        Split the shapes in the blendshape into separate shapes in the split_blendshape.
        Parameters:
            primary_list (list): A list of primary shapes to split.
        Returns:
            None
        """
        if self.get_current_edit_split_map() is not None:
            raise ValueError("Cannot split shapes while editing a split map. Please exit the edit mode first.")
        # let's check if all the split maps are normalized
        for split_map in self.get_split_maps():
            if not self.is_split_map_normalized(split_map):
                raise ValueError(f"Split map {split_map} is not normalized. Please normalize it before splitting shapes.")
        shapes_to_split = set()
        primaries_to_delete = list()
        # we need to store 
        for primary in primary_list:
            split_group = self.get_primary_split_group(primary)
            if split_group is None or split_group == "NoSplit":
                continue
            primaries_to_delete.append(primary)
            primary_shape = self.network.get_shape(primary)
            discendent_shapes = self.network.get_related_shapes_downstream(primary_shape)
            shapes_to_split.update(discendent_shapes)
        # we only want to split the primaries in the list so the other primaries are set to NoSplit
        primary_split_groups = {
            primary: self.get_primary_split_group(primary) if primary in primary_list else "NoSplit"
            for primary in self.get_primary_shapes()
        }
        if len(shapes_to_split) == 0:
            raise ValueError("No shapes to split. Please make sure the primary shapes have a split group assigned.")
        split_data = self.build_split_data(primary_split_groups=primary_split_groups)
        self.split_and_commit_split_shapes(shapes_to_split, self, split_data=split_data)
        # we need to remove the primaries we just split
        self.remove_shapes(primaries_to_delete)
    
    @contextmanager
    def _split_session(self) -> SplitSession:
        """
        Context manager handling the setup and teardown of a split bake.

        Creates the split map meshes, turns the evaluation manager and cycle
        checks off for speed, and restores everything (deleting the temporary
        meshes) when the block exits, even on error.
        Returns:
            SplitSession: The session holding the split bake state.
        Example:
            >>> with blue_steel._split_session() as session:
            ...     session.connect_shape("browUp")
        """
        evaluation_mode = cmds.evaluationManager(query=True, mode=True)[0]
        split_meshes_group = self.create_split_maps_meshes()
        try:
            cmds.evaluationManager(mode="off")
            cmds.cycleCheck(e=False)
            yield SplitSession(self)
        finally:
            cmds.evaluationManager(mode=evaluation_mode)
            cmds.cycleCheck(e=True)
            cmds.refresh(suspend=False)
            self.zero_out()
            if split_meshes_group and cmds.objExists(split_meshes_group):
                cmds.delete(split_meshes_group)
            self.split_bake_mesh = None
            self.split_blendshape_to_connect = None
            self.split_map_blendshapes = {}
            self.split_map_blendshapes_weights = {}

    def split_and_commit_split_shapes(self,
                                      shapes: list,
                                      destination_editor: BlueSteelEditor,
                                      split_data: SplitData = None) -> None:
        """
        Split and commit a list of shapes to a destination editor.

        For every shape, every split pose generated from the split data is
        evaluated on the split map meshes and committed to the destination
        editor, baking the split deformation into the new target.
        Parameters:
            shapes (list): The list of shapes to split and commit.
            destination_editor (BlueSteelEditor): The destination editor instance.
            split_data (SplitData): The split configuration to use. When None the
                current editor configuration is collected with build_split_data.
        Returns:
            None
        Example:
            >>> blue_steel = BlueSteelEditor.create_new("myEditor", "pCube1")
            >>> blue_steel.split_and_commit_split_shapes(["browUp"], blue_steel)
        """
        if split_data is None:
            split_data = self.build_split_data()
        self.zero_out()
        sorted_shapes = utilities.sort_for_insertion(shapes, self.separator)
        total_shapes = len(sorted_shapes)
        # --- Start the progress bar ---
        gMainProgressBar = mel.eval('$tmp = $gMainProgressBar')
        cmds.progressBar(gMainProgressBar, edit=True,
                         beginProgress=True,
                         isInterruptable=True,
                         status=f"Splitting 0/{total_shapes} shapes...",
                         maxValue=total_shapes)
        try:
            with self._split_session() as session:
                for shape_name in sorted_shapes:
                    if cmds.progressBar(gMainProgressBar, query=True, isCancelled=True):
                        break
                    cmds.progressBar(gMainProgressBar,
                                     edit=True,
                                     step=1,
                                     status=f"Splitting shape: {shape_name}...")
                    shape = self.get_shape(shape_name)
                    if shape is None:
                        print(f"Warning: Shape '{shape_name}' not found in the network. Skipping split.")
                        continue
                    session.connect_shape(shape)
                    for pose_name, areas in split_data.get_split_shape_poses(shape).items():
                        session.apply_pose(areas)
                        session.commit_pose(pose_name, destination_editor)
        except Exception as e:
            print(f"Error while splitting shapes: {e}")
            traceback.print_exc()
            raise e
        finally:
            cmds.progressBar(gMainProgressBar, edit=True, endProgress=True)
            destination_editor.zero_out()

    @pause_shape_editor
    @undoable
    def create_split_shapes_editor(self)-> str:
        """
        Create a new editor and add all the split shapes to it.
        Returns:
            str: The name of the new editor.
        """
        if self.get_current_edit_split_map() is not None:
            raise ValueError("Cannot split shapes while editing a split map. Please exit the edit mode first.")
        # let's check if all the split maps are normalized
        for split_map in self.get_split_maps():
            if not self.is_split_map_normalized(split_map):
                raise ValueError(f"Split map {split_map} is not normalized. Please normalize it before splitting shapes.")
        # let's time it
        start_time = time.time()
        editor_name = f"{self.name.replace('_blueSteelEditor', '')}_split"
        count = ""
        while cmds.objExists(f"{editor_name}{count}"):
            if count == "":
                count = 1
            else:
                count += 1
        editor_name = f"{editor_name}{count}"

        mesh = self.base_mesh
        sorted_shapes = utilities.sort_for_insertion(list(self.blendshape.get_weights()), self.separator)
        split_editor = self.create_new(editor_name=editor_name, mesh_name=mesh)
        self.split_and_commit_split_shapes(shapes=sorted_shapes,
                                           destination_editor=split_editor)

        end_time = time.time()
        print(f"Splitting shapes took {end_time - start_time} seconds")

        if split_editor:
            return split_editor.name 
                
    def export_split_data(self, export_path: str):
        """
        Export the split data to a directory.
        Parameters:
            export_path (str): The path to export the split data to.
        Returns:
            None
        """
        self.export_split_settings(export_path)
        self.export_split_maps_weights(export_path)

    @pause_shape_editor
    @undoable
    def import_split_data(self, import_path: str, import_weights: bool = True, import_settings: bool = True):
        """
        Import the split data from a directory.
        Parameters:
            import_path (str): The path to import the split data from.
        Returns:
            None
        """
        if import_weights:
            self.import_split_maps_weights(import_path)
        if import_settings:
            self.import_split_settings(import_path)
            self._ensure_split_shape_name_item_in_groups()

    def get_primaries_split_groups_association(self):
        """
        Creates a dictionary with all the primaries and their associated split groups.
        """
        split_map_associations = dict()
        for primary in self.get_primary_shapes():
            group = self.get_primary_split_group(primary)
            split_map_associations[primary] = group
        return split_map_associations

    def build_split_data(self, primary_split_groups: dict = None) -> SplitData:
        """
        Collect the split configuration of this editor into a SplitData object.
        Parameters:
            primary_split_groups (dict): Optional {primary: split group} override.
                When None the current associations of the editor are used.
        Returns:
            SplitData: The split configuration used to generate the split poses.
        Example:
            >>> blue_steel = BlueSteelEditor.create_new("myEditor", "pCube1")
            >>> blue_steel.create_split_map("side", ["L", "R"])
            >>> split_data = blue_steel.build_split_data()
            >>> print(split_data.split_maps_order)
            ['side']
        """
        if primary_split_groups is None:
            primary_split_groups = self.get_primaries_split_groups_association()
        split_map_areas = {
            split_map: [str(weight) for weight in self.get_split_map_weights(split_map)]
            for split_map in self.get_split_maps()
        }
        return SplitData(split_groups=self.read_split_groups_attributes(),
                         primary_split_groups=primary_split_groups,
                         split_map_areas=split_map_areas,
                         split_maps_order=self.read_split_maps_order_attribute(),
                         shape_name_area=self.SHAPE_NAME_STR,
                         separator=self.separator)
    
    @pause_shape_editor
    @undoable
    def export_split_settings(self, export_path: str):
        """
        Export the split settings to a directory.
        Parameters:
            export_path (str): The path to export the split settings to.
        Returns:
            None
        """
        if not os.path.exists(export_path):
            os.makedirs(export_path)
        split_groups = self.read_split_groups_attributes()
        split_maps_order = self.read_split_maps_order_attribute()
        # we need to get the split group associations for each primary shape
        split_map_associations = self.get_primaries_split_groups_association()
        split_settings = {
            "split_groups": split_groups,
            "split_maps_order": split_maps_order,
            "split_map_associations": split_map_associations
        }
        # we need to write the split settings to a json file
        export_file = os.path.join(export_path, "split_settings.json")
        with open(export_file, "w") as f:
            json.dump(split_settings, f, indent=4)

    def switch_visibility_to_split_map_edit_mesh(self, state):
        """
        Switch the visibility of the split map edit mesh.
        Parameters:
            state (bool): The state to switch the visibility to. Default is True.
        Returns:
            None
        """
        if self.split_map_edit_mesh is None or not cmds.objExists(self.split_map_edit_mesh):
            cmds.setAttr(f"{self.base_mesh}.visibility", True)
            return
        # we need to check if we are in a sculpt or weight painting mode and switch to object mode if we are
        current_context = cmds.currentCtx()
        if current_context in ["sculptMeshCacheContext", "artAttrBlendShapeContext"]:
            cmds.setToolTo("selectSuperContext")
        cmds.setAttr(f"{self.split_map_edit_mesh}.visibility", state)
        cmds.setAttr(f"{self.base_mesh}.visibility", not state)


    def create_split_map_edit_mesh(self):
        """
        Create a duplicate of the mesh with a blendshape for each split map.
        The input mesh for each target is the base mesh.
        """
        # check if the attribute exists.
        split_mesh_attr = self.SPLIT_MAP_EDIT_MESH_ATTR_STRING_IDENTIFIER
        attrUtils.add_message_attr(self.name, split_mesh_attr)
        split_map_edit_mesh_name = f"{self.base_mesh.split('|')[-1]}_{split_mesh_attr}"
        split_map_edit_mesh = self.duplicate_base_mesh_neutral_state(split_map_edit_mesh_name)
        mayaUtils.assign_default_material(split_map_edit_mesh)
        # let's connect the split map edit mesh to the attribute
        cmds.connectAttr(f"{split_map_edit_mesh}.message",f"{self.name}.{split_mesh_attr}", force=True)
         #we need to add all the split maps
        self.switch_visibility_to_split_map_edit_mesh(True)
        return split_map_edit_mesh

    def get_current_edit_split_map(self):
        """
        Get the current split map edit mesh.
        Returns:
            str: The name of the current split map edit mesh.
        """
        if self.split_map_edit_blendshape is None or not cmds.objExists(self.split_map_edit_blendshape):
            #print("Split map edit blendshape does not exist")
            return None
        string_attr = self.SPLIT_MAP_EDIT_CURRENT_ATTR_STRING_IDENTIFIER
        if not cmds.attributeQuery(string_attr, node=self.split_map_edit_blendshape, exists=True):
            #print("Split map edit current attribute does not exist")
            return None
        attr_name = f"{self.split_map_edit_blendshape}.{string_attr}"
        attr = cmds.getAttr(attr_name) or None
        return attr
    
    def cancel_current_edit_split_map(self):
        """
        Cancel the current split map edit mesh.
        This will delete the split map edit mesh and switch the visibility back to the base mesh.
        """
        if self.split_map_edit_mesh is None or not cmds.objExists(self.split_map_edit_mesh):
            raise ValueError("Split map edit mesh does not exist")
        self.switch_visibility_to_split_map_edit_mesh(False)
        cmds.delete(self.split_map_edit_mesh)

    def sync_split_map_weights_to_split_map_edit_weights(self):
        """
        Sync the weights from the split_blendshape to the split_map_edit_blendshape.
        This will transfer the weight maps from the split_blendshape to the split_map_edit_blendshape.
        """
        current_edit_split_map = self.get_current_edit_split_map()
        if current_edit_split_map is None:
            raise ValueError("No current split map edit mesh found")
        if self.split_map_edit_blendshape is None or not cmds.objExists(self.split_map_edit_blendshape):
            raise ValueError("Split map edit blendshape does not exist")
        edit_split_blend = Blendshape(self.split_map_edit_blendshape)
        # we need to clear up all the weights in the split_blendshape weight map.
        weights_to_delete = self.get_split_map_weights(current_edit_split_map)
        for weight in weights_to_delete:
            self.remove_weight_from_split_map(current_edit_split_map, weight)
        for edit_weight in edit_split_blend.get_weights():
            print(f"Syncing weight {edit_weight} to split map {current_edit_split_map}")
            area = edit_weight.split(f"{current_edit_split_map}_")[-1]
            self.add_weight_to_split_map(current_edit_split_map, area)
            split_weight = self.split_blendshape.get_weight_by_name(edit_weight)
            if split_weight is None:
                raise ValueError(f"Weight {area} does not exist in split map edit blendshape")
            print(f"Transferring weight map from {edit_weight} to {split_weight}")
            edit_split_blend.transfer_weight_map(source_weight_id=edit_weight.id,
                                                 target_weight_id=split_weight.id,
                                                 target_blendshape=self.split_blendshape.name)

    def apply_current_edit_split_map(self):
        """
        Apply the current split map edit mesh to the split_blendshape.
        This will transfer the weight maps from the split map edit mesh to the split_blendshape.
        """
        self.sync_split_map_weights_to_split_map_edit_weights()
        self.switch_visibility_to_split_map_edit_mesh(False)
        cmds.delete(self.split_map_edit_mesh)

    def activate_edit_split_weight(self, weight_name: str):
        current_edit_split_map = self.get_current_edit_split_map()
        if current_edit_split_map is None:
            raise ValueError("No current split map edit mesh found")
        if self.split_map_edit_blendshape is None or not cmds.objExists(self.split_map_edit_blendshape):
            raise ValueError("Split map edit blendshape does not exist")
        edit_split_blend = Blendshape(self.split_map_edit_blendshape)
        weight = edit_split_blend.get_weight_by_name(weight_name)
        if weight is None:
            raise ValueError(f"Weight {weight_name} does not exist in split map edit blendshape")
        for w in edit_split_blend.get_weights():
            edit_split_blend.set_weight_value(w, 1.0 if w == weight else 0.0)

    def set_current_edit_split_map_weight_paint_mask(self, weight_name: str):
        current_edit_split_map = self.get_current_edit_split_map()
        if current_edit_split_map is None:
            raise ValueError("No current split map edit mesh found")
        if self.split_map_edit_blendshape is None or not cmds.objExists(self.split_map_edit_blendshape):
            raise ValueError("Split map edit blendshape does not exist")
        edit_split_blend = Blendshape(self.split_map_edit_blendshape)
        weight = edit_split_blend.get_weight_by_name(weight_name)
        if weight is None:
            raise ValueError(f"Weight {weight_name} does not exist in split map edit blendshape")
        edit_split_blend.set_target_mask_paint_mode(weight.id)

    def set_current_edit_split_map_weight_paint_weight(self, weight_name: str):
        if self.get_current_edit_split_map() is None:
            raise ValueError("No current split map edit mesh found")
        if self.split_map_edit_blendshape is None or not cmds.objExists(self.split_map_edit_blendshape):
            raise ValueError("Split map edit blendshape does not exist")
        edit_split_blend = Blendshape(self.split_map_edit_blendshape)
        weight = edit_split_blend.get_weight_by_name(weight_name)
        if weight is None:
            raise ValueError(f"Weight {weight_name} does not exist in split map edit blendshape")
        edit_split_blend.set_target_weight_paint_mode(weight)

    def set_current_edit_split_map_weight_active(self, weight_name: str):
        if self.get_current_edit_split_map() is None:
            raise ValueError("No current split map edit mesh found")
        if self.split_map_edit_blendshape is None or not cmds.objExists(self.split_map_edit_blendshape):
            raise ValueError("Split map edit blendshape does not exist")

        edit_split_blend = Blendshape(self.split_map_edit_blendshape)
        selected_weight = edit_split_blend.get_weight_by_name(weight_name)
        if selected_weight is None:
            raise ValueError(f"Weight {weight_name} does not exist in split map edit blendshape")
        for weight in edit_split_blend.get_weights():
            edit_split_blend.set_weight_value(weight, 1.0 if weight == selected_weight else 0.0)

    def get_current_edit_split_map_weight_values(self) -> dict:
        if self.get_current_edit_split_map() is None:
            return {}
        if self.split_map_edit_blendshape is None or not cmds.objExists(self.split_map_edit_blendshape):
            return {}

        edit_split_blend = Blendshape(self.split_map_edit_blendshape)
        return {
            str(weight): float(edit_split_blend.get_weight_value(weight))
            for weight in edit_split_blend.get_weights()
        }

    def set_current_edit_split_map_weight_value(self, weight_name: str, value: float):
        if self.get_current_edit_split_map() is None:
            raise ValueError("No current split map edit mesh found")
        if self.split_map_edit_blendshape is None or not cmds.objExists(self.split_map_edit_blendshape):
            raise ValueError("Split map edit blendshape does not exist")

        edit_split_blend = Blendshape(self.split_map_edit_blendshape)
        weight = edit_split_blend.get_weight_by_name(weight_name)
        if weight is None:
            raise ValueError(f"Weight {weight_name} does not exist in split map edit blendshape")
        edit_split_blend.set_weight_value(weight, max(0.0, min(1.0, float(value))))

    def create_split_map_edit_blendshape(self, split_map_name: str):
        """
        Create a blendshape node for the split map edit mesh. This is useful when importing split maps from another file.
        """
        current_edit_split_map = self.get_current_edit_split_map()
        if current_edit_split_map is not None and current_edit_split_map != split_map_name:
            # we need to create a prompt to ask the user if they want to switch to the new split map edit mesh
            result = cmds.confirmDialog(title='Switch Split Map Edit Mesh',
                                        message=f'You are currently editing the split map "{current_edit_split_map}".\nDo you want to apply the edits to the split map before switching to "{split_map_name}"?',
                                        button=['Yes', 'No', 'Cancel'],
                                        defaultButton='Yes',
                                        cancelButton='Cancel',
                                        dismissString='Cancel')
            if result == 'Yes':
                self.apply_current_edit_split_map()
            elif result == 'Cancel':
                return
        if current_edit_split_map == split_map_name:
            raise ValueError(f"Split map {split_map_name} is already being edited")
        if split_map_name not in self.get_split_maps():
            raise ValueError(f"Split map {split_map_name} does not exist")
        if self.split_map_edit_mesh is None or not cmds.objExists(self.split_map_edit_mesh):
            self.create_split_map_edit_mesh()
        # we need to clear any existing blendshape nodes from the split map edit mesh
        if self.split_map_edit_blendshape is not None and cmds.objExists(self.split_map_edit_blendshape):
            cmds.delete(self.split_map_edit_blendshape)
        # let's create a blendshape node for the split map edit mesh
        split_map_edit_blendshape_name = f"{self.split_map_edit_mesh.split('|')[-1]}_blendShape"
        split_map_edit_blendshape = cmds.blendShape(self.split_map_edit_mesh,
                                                    name=split_map_edit_blendshape_name)[0]
        # let's connect the split map edit blendshape to the attribute
        split_map_edit_blend_attr = self.SPLIT_MAP_EDIT_BLENDSHAPE_ATTR_STRING_IDENTIFIER
        attrUtils.add_message_attr(self.name, split_map_edit_blend_attr)
        cmds.connectAttr(f"{split_map_edit_blendshape}.message",f"{self.name}.{split_map_edit_blend_attr}",
                         force=True)
        split_map_edit_blendshape = Blendshape(split_map_edit_blendshape)
        # we need to add a string attribute where to store the current split map.
        split_map_edit_current_attr = self.SPLIT_MAP_EDIT_CURRENT_ATTR_STRING_IDENTIFIER
        attrUtils.add_string_attr(split_map_edit_blendshape, split_map_edit_current_attr, split_map_name)
        for weight in self.get_split_map_weights(split_map_name):
            new_target_weight = split_map_edit_blendshape.add_target(weight)
            # we need to transfer the weight maps from the split weight to the newly created weight.
            self.split_blendshape.transfer_weight_map(source_weight_id = weight.id,
                                                      target_weight_id = new_target_weight.id,
                                                      target_blendshape = split_map_edit_blendshape.name,)
            split_map_edit_blendshape.connect_mesh_to_target(new_target_weight.id, self.base_mesh)
            split_map_edit_blendshape.set_weight_value(new_target_weight, 1.0)

    def import_split_settings(self, import_path: str):
        """
        Import the split settings from a directory.
        Parameters:
            import_path (str): The path to import the split settings from.
        Returns:
            None
        """
        valid_split_maps = self.get_split_maps()
        import_file = os.path.join(import_path, "split_settings.json")
        if os.path.exists(import_file):
            with open(import_file, "r") as f:
                split_settings = json.load(f)
            split_groups = split_settings.get("split_groups", {})
            for group, split_maps in split_groups.items():
                split_groups[group] = [split_map for split_map in split_maps if split_map in valid_split_maps]
            split_maps_order = split_settings.get("split_maps_order", [])
            split_map_associations = split_settings.get("split_map_associations", {})
            self.write_split_groups_attributes(split_groups)
            self.write_split_maps_order_attribute(split_maps_order)
            self.update_split_map_attributes_from_groups()
            primary_shapes = self.get_primary_shapes()
            for primary, group in split_map_associations.items():
                if primary not in primary_shapes:
                    #print(f"Primary shape {primary} does not exist in the blendshape. Skipping association.")
                    continue
                self.set_primaries_split_group([primary], group)
            # we need to check if the split maps in the split_groups are valid. If not, we need to remove them from the split_groups.
            

            
    def export_split_maps_weights(self, export_path: str):
        """
        Export the split maps to a directory.
        Parameters:
            export_path (str): The path to export the split maps to.
        Returns:
            None
        """
        if not os.path.exists(export_path):
            os.makedirs(export_path)
        split_maps_weights = {}
        for split_map in self.get_split_maps():
            split_map_weights = self.get_split_map_weights(split_map)
            split_map_data = {}
            for weight in split_map_weights:
                weight_map_values = self.split_blendshape.get_weight_map_values(weight.id)
                split_map_data[weight] = weight_map_values
            split_maps_weights[split_map] = split_map_data
        # we need to write the split maps weights to a json file
        export_file = os.path.join(export_path, "split_maps_weights.json")
        with open(export_file, "w") as f:
            json.dump(split_maps_weights, f, indent=4)

    def import_split_maps_weights(self, import_path: str):
        """
        Import the split maps from a directory.
        Parameters:
            import_path (str): The path to import the split maps from.
        Returns:
            None    
        """
        self.clear_all_split_maps()
        import_file = os.path.join(import_path, "split_maps_weights.json")
        base_mesh_vertex_count = cmds.polyEvaluate(self.base_mesh, vertex=True)
        if os.path.exists(import_file):
            with open(import_file, "r") as f:
                split_maps_weights = json.load(f)
            for split_map, split_map_data in split_maps_weights.items():
                split_map_areas = [x.split("_")[-1] for x in split_map_data.keys()]
                self.create_split_map(split_map, split_map_areas)
                for weight, weight_map_values in split_map_data.items():
                    weight = self.split_blendshape.get_weight_by_name(weight)
                    if weight is None:
                        raise ValueError(f"Weight {weight} does not exist in the split_blendshape")
                    # we need to check if the length of the weight_map_values matches the base_mesh_vertex_count
                    if len(weight_map_values) != base_mesh_vertex_count:
                        print(f"Warning: Weight map values for weight {weight} in split map {split_map} does not match the base mesh vertex count. Skipping this weight.")
                        continue
                    self.split_blendshape.set_weight_map_values(weight.id, weight_map_values)

    def clear_all_split_maps(self):
        """
        Clear all the split maps in the split_blendshape.
        Returns:
            None
        """
        for split_map in self.get_split_maps():
            self.delete_split_map(split_map)

    def connect_shape_to_split_map_blendshapes(self,
                                               shape_name: str,
                                               split_blendshape: Blendshape = None,
                                               split_weights: list = None):
        """
        Connect a shape to the split_maps_blendshape.
        Parameters:
            shape_name (str): The name of the shape to connect to the split_maps_blendshape.
        """
        # check if the shape exists in the blendshape
        shape_weight = self.blendshape.get_weight_by_name(shape_name)
        if not shape_weight:
            raise ValueError(f"Shape {shape_name} does not exist")
        if not self.split_blendshape_to_connect:
            raise ValueError("No split map blendshape to connect to")
        # we need to connect the shape to all the split map blendshape targets
        split_blendshape = split_blendshape or Blendshape(self.split_blendshape_to_connect)
        split_weights = split_weights or split_blendshape.get_weights()
        for weight in split_weights:
            self.blendshape.connect_target_to_blendshape_target(input_target_index=shape_weight.id,
                                                                output_blendshape_name=split_blendshape.name,
                                                                output_target_index=weight.id)
        

    def copy_edit_split_weight_map_values(self, shape_name: str):
        """
        Copy a weight from the split_blendshape to the split_maps_blendshape.
        Parameters:
            shape_name (str): The name of the shape to copy the weight map from."""
        split_map_edit_blendshape = self.split_map_edit_blendshape
        if not split_map_edit_blendshape or not cmds.objExists(split_map_edit_blendshape):
            raise ValueError("Split map edit blendshape does not exist")
        split_map_edit_blendshape = Blendshape(split_map_edit_blendshape)
        self.copy_blendshape_weight_map_values(split_map_edit_blendshape,
                                               shape_name)

    def copy_split_weight_map_values(self, shape_name: str):
        """Copy a weight map from the source split blendshape."""
        self.copy_blendshape_weight_map_values(self.split_blendshape, shape_name)

    def paste_edit_split_weight_map_values(self, shape_name: str):
        """
        Paste a weight from the split_blendshape to the split_maps_blendshape.
        Parameters:
            shape_name (str): The name of the shape to paste the weight map to."""
        split_map_edit_blendshape = self.split_map_edit_blendshape
        if not split_map_edit_blendshape or not cmds.objExists(split_map_edit_blendshape):
            raise ValueError("Split map edit blendshape does not exist")
        split_map_edit_blendshape = Blendshape(split_map_edit_blendshape)
        self.paste_blendshape_weight_map_values_to_shape(split_map_edit_blendshape, shape_name)

    def paste_inverted_edit_split_weight_map_values(self, shape_name: str):
        """
        Paste an inverted weight from the split_blendshape to the split_maps_blendshape.
        Parameters:
            shape_name (str): The name of the shape to paste the weight map to."""
        split_map_edit_blendshape = self.split_map_edit_blendshape
        if not split_map_edit_blendshape or not cmds.objExists(split_map_edit_blendshape):
            raise ValueError("Split map edit blendshape does not exist")
        split_map_edit_blendshape = Blendshape(split_map_edit_blendshape)
        self.paste_blendshape_weight_map_values_to_shape(split_map_edit_blendshape, shape_name, invert=True)

    def paste_multiplied_edit_split_weight_map_values(self, shape_name: str):
        """
        Paste a multiplied weight from the split_blendshape to the split_maps_blendshape.
        Parameters:
            shape_name (str): The name of the shape to paste the weight map to."""
        split_map_edit_blendshape = self.split_map_edit_blendshape
        if not split_map_edit_blendshape or not cmds.objExists(split_map_edit_blendshape):
            raise ValueError("Split map edit blendshape does not exist")
        split_map_edit_blendshape = Blendshape(split_map_edit_blendshape)
        self.paste_blendshape_weight_map_values_to_shape(split_map_edit_blendshape, shape_name, multiply=True)

    def add_edit_split_weight_map_values(self, shape_name: str):
        """
        Add a weight from the split_blendshape to the split_maps_blendshape.
        Parameters:
            shape_name (str): The name of the shape to add the weight map to."""
        split_map_edit_blendshape = self.split_map_edit_blendshape
        if not split_map_edit_blendshape or not cmds.objExists(split_map_edit_blendshape):
            raise ValueError("Split map edit blendshape does not exist")
        split_map_edit_blendshape = Blendshape(split_map_edit_blendshape)
        self.paste_blendshape_weight_map_values_to_shape(split_map_edit_blendshape, shape_name, add=True)

    def subtract_edit_split_weight_map_values(self, shape_name: str):
        """
        Subtract a weight from the split_blendshape to the split_maps_blendshape.
        Parameters:
            shape_name (str): The name of the shape to subtract the weight map from."""
        split_map_edit_blendshape = self.split_map_edit_blendshape
        if not split_map_edit_blendshape or not cmds.objExists(split_map_edit_blendshape):
            raise ValueError("Split map edit blendshape does not exist")
        split_map_edit_blendshape = Blendshape(split_map_edit_blendshape)
        self.paste_blendshape_weight_map_values_to_shape(split_map_edit_blendshape, shape_name, subtract=True)

    def convert_soft_selection_to_edit_split_weight_map(self, shape_name: str):
        split_map_edit_blendshape = self.split_map_edit_blendshape
        if not split_map_edit_blendshape or not cmds.objExists(split_map_edit_blendshape):
            raise ValueError("Split map edit blendshape does not exist")
        split_map_edit_blendshape = Blendshape(split_map_edit_blendshape)
        self.convert_soft_selection_to_weight_map(split_map_edit_blendshape, shape_name)

    # debug function to compare shapes. This will be removed on release
    def compare_shapes_debug(self):
        """DEBUG FUNCTION TO COMPARE SHAPES"""
        shapes = self.get_all_shapes()
        # let's make sure all shapes are unmuted
        self.unmute_all_shapes()
        unmmatched_shapes = []
        max_difference = 0.0
        max_diff_shape = None
        
        for shape in shapes:
            self.set_shape_pose(shape)
            # let's get the deformed vertices
            deformed_points = self.blendshape.get_base_deformed_points()
            # see if we can find a mesh with the same name of the pose
            if cmds.objExists(shape):
                # let's get the shape points
                shape_points = mayaUtils.get_points_as_numpy(shape)
                if shape_points.shape[1] == 4:
                    shape_points = shape_points[:, :3]
                # let's compare the two arrays
                are_close = np.allclose(shape_points, deformed_points)
                if not are_close:
                    # Calculate per-vertex vector differences
                    diff = shape_points - deformed_points
                    # Calculate the length (magnitude) of each difference vector
                    vector_lengths = np.linalg.norm(diff, axis=1)
                    # Get the maximum vector length
                    shape_max_diff = np.max(vector_lengths)
                    
                    # Track overall maximum
                    if shape_max_diff > max_difference:
                        max_difference = shape_max_diff
                        max_diff_shape = str(shape)
                    
                    unmmatched_shapes.append(shape)
                    print(f"Shape '{shape}': max difference = {shape_max_diff:.6f}")
        return unmmatched_shapes, max_difference, max_diff_shape
