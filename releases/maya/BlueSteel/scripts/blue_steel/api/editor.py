print("Success")

from maya import cmds, mel
import traceback
import sys

from . import attrUtils
from .mayaUtils import undoable
from .container import Container
from .blendshape import Blendshape, Weight
from ..logic.shape import Shape
from ..logic.shapeList import ShapeList
from ..logic.network import Network
from ..logic.splitMap import SplitMap
from ..logic import utilities
from . import mayaUtils

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
MAIN_BLENDSHAPE_STRING_IDENTIFIER = "mainBlendShape"
SPLIT_BLENDSHAPE_STRING_IDENTIFIER = "splitBlendShape"
WORK_BLENDSHAPE_STRING_IDENTIFIER = "workBlendShape"
HEAT_MAP_BLENDSHAPE_STRING_IDENTIFIER = "heatMapBlendShape"
SPLIT_ATTR_GRP_STRING_IDENTIFIER = "splitAttrGrp"
FACE_CTRL_STRING_IDENTIFIER = "faceCtrl"
NODE_NETWORK_CONTAINER_STRING_IDENTIFIER = "nodeNetwork"
BASE_MESH_STRING_IDENTIFIER = "baseMesh"
HEAT_MAP_MESH_STRING_IDENTIFIER = "heatMapMesh"
DGA_VISUALIZER_STRING_IDENTIFIER = "dgaVisualizer"
DGA_DELTA_STRING_IDENTIFIER = "dgaDelta"
DELTA_MAP_STRING_IDENTIFIER = "deltaMap"
# TARGET GROUP NAMES
PRIMARY_SHAPES_GRP_NAME = "Primaries_GRP"
COMBO_SHAPES_GRP_NAME = "Combos_GRP"
INBETWEEN_SHAPES_GRP_NAME = "Inbetweens_GRP"


VERBOSE = False
TIMED = False

class BlueSteelEditor(object):
    SHAPE_EDITOR_PANEL = "shapePanel1Window"
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


        self.separator = separator
        self.blendshape = None
        self.split_blendshape = None
        self.work_blendshape = None
        self.heat_map_blendshape = None
        # Signals
        self.signals_connected = False
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
        # if self.heat_map_blendshape_name:
        #     self.heat_map_blendshape = Blendshape(self.heat_map_blendshape_name)
        # else:
        #     print(f"Warning: Editor '{container}' does not have a heat map blendshape linked.")
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

        # setting up the network
        self.build_network()
        self.sync_up_muted_shapes()

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
            print(f"Deleting heat map blendshape '{self.heat_map_blendshape_name}' and mesh '{heat_mesh_name}'.")
            cmds.delete(blend_name)
            self.heat_map_blendshape = None
        if self.heat_map_mesh:
            if cmds.objExists(heat_mesh_name):
                print(f"Deleting heat map mesh '{heat_mesh_name}'.")
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

    # def _create_heat_map_blendshape(self):
    #     """
    #     Check if the heat map blendshape and mesh exist, and create them if they don't.
    #     """
    #     if self.heat_map_blendshape or self.heat_map_mesh:
    #         # cleaning up existing nodes if they exist before creating new ones to avoid duplicates
    #         if self.heat_map_blendshape:
    #             cmds.delete(self.heat_map_blendshape_name)
    #         if self.heat_map_mesh:
    #             cmds.delete(self.heat_map_mesh)
    #         self._create_heat_map_blendshape()
    #     # just making sure the heat map target weight exists.
    #     heat_weight = self.heat_map_blendshape.get_weight_by_name("heatMapTarget")
    #     if heat_weight is None:
    #         heat_weight = self.heat_map_blendshape.add_target("heatMapTarget")
    #         self.heat_map_blendshape.set_weight_value(heat_weight, 1.0)

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
        delta_node_name = f"{self.editor_base_name}_{DGA_DELTA_STRING_IDENTIFIER}"
        delta_node = cmds.createNode("dgaDelta", name=delta_node_name)
        # link to the message attribute for easy access
        attrUtils.add_message_attr(self.container.name, DGA_DELTA_STRING_IDENTIFIER, delta_node)
        self.container.add_member(delta_node)
        # now we neeed to connect the delta node to the heat map blendshape and mesh
        heat_map_shape = self.heat_map_blendshape.get_base()[0]
        heat_original_mesh = self.heat_map_blendshape.get_original_geometry()
        cmds.connectAttr(f"{heat_map_shape}.outMesh", f"{delta_node}.inputGeometry", force=True)
        cmds.connectAttr(f"{heat_original_mesh}.outMesh", f"{delta_node}.originalGeometry", force=True)
        # now let's create the dga visualizer node
        visualizer_node_name = f"{self.editor_base_name}_{DGA_VISUALIZER_STRING_IDENTIFIER}"
        visualizer_node = cmds.createNode("dgaVisualizer", name=visualizer_node_name)
        # link to the message attribute for easy access
        attrUtils.add_message_attr(self.container.name, DGA_VISUALIZER_STRING_IDENTIFIER, visualizer_node)
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
        # out_shape = cmds.listRelatives(self.base_mesh, shapes=True, fullPath=True) or None
        # if out_shape is None:
        #     raise ValueError(f"Base mesh '{self.base_mesh}' does not have any shapes.")
        # out_shape = out_shape[0]
        # previous_connection = cmds.listConnections(f"{out_shape}.inMesh", source=True, destination=False, plugs=True) or []
        # if not previous_connection:
        #     raise ValueError(f"Base mesh '{self.base_mesh}' does not have a connection to its shape node. Cannot connect heat map delta node.")
        delta_node_name = f"{self.editor_base_name}_{DELTA_MAP_STRING_IDENTIFIER}"
        delta_node = cmds.deformer(self.base_mesh, type="deltaMap", name=delta_node_name)[0]
        attrUtils.add_message_attr(self.container.name, DELTA_MAP_STRING_IDENTIFIER, delta_node)
        self.container.add_member(delta_node)
        # # we need to find the orig shape for the heat map mesh and connect it to the delta node orig input,
        # cmds.connectAttr(f"{previous_connection[0]}", f"{delta_node}.inMesh", force=True)
        # cmds.connectAttr(f"{delta_node}.outMesh", f"{out_shape}.inMesh", force=True)
        # we need to get the heat mesh intermediate shape and connect it to the delta node deformed input
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
        heat_map_geo_name = f"{self.editor_base_name}_{HEAT_MAP_MESH_STRING_IDENTIFIER}"
        heat_map_geo = self.duplicate_base_mesh_neutral_state(heat_map_geo_name)
        cmds.setAttr(f"{heat_map_geo}.v", 0)
        attrUtils.add_message_attr(self.container.name,
                                   HEAT_MAP_MESH_STRING_IDENTIFIER,
                                   heat_map_geo)
        self.container.add_mesh_as_member(heat_map_geo)

        heat_blendshape_name = f"{self.editor_base_name}_{HEAT_MAP_BLENDSHAPE_STRING_IDENTIFIER}"
        heat_blendshape =self.add_new_blendshape_to_container(blendshape_name=heat_blendshape_name,
                                                              mesh_name=heat_map_geo,
                                                              container=self.container,
                                                              message_attr=HEAT_MAP_BLENDSHAPE_STRING_IDENTIFIER,
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
    def main_blendshape_name(self):
        return attrUtils.get_message_attr(self.container.name, MAIN_BLENDSHAPE_STRING_IDENTIFIER)
    @property
    def split_blendshape_name(self):
        return attrUtils.get_message_attr(self.container.name, SPLIT_BLENDSHAPE_STRING_IDENTIFIER)
    @property
    def work_blendshape_name(self):
        return attrUtils.get_message_attr(self.container.name, WORK_BLENDSHAPE_STRING_IDENTIFIER)
    @property
    def heat_map_blendshape_name(self):
        return attrUtils.get_message_attr(self.container.name, HEAT_MAP_BLENDSHAPE_STRING_IDENTIFIER)
    @property
    def split_attr_grp(self):
        return attrUtils.get_message_attr(self.container.name, SPLIT_ATTR_GRP_STRING_IDENTIFIER)

    @property
    def dga_visualizer(self):
        return attrUtils.get_message_attr(self.container.name, DGA_VISUALIZER_STRING_IDENTIFIER)
    
    @property
    def dga_delta(self):
        return attrUtils.get_message_attr(self.container.name, DGA_DELTA_STRING_IDENTIFIER)
    
    @property
    def delta_map(self):
        return attrUtils.get_message_attr(self.container.name, DELTA_MAP_STRING_IDENTIFIER)

    @property
    def face_ctrl(self):
        return attrUtils.get_message_attr(self.container.name, FACE_CTRL_STRING_IDENTIFIER)

    @property
    def heat_map_mesh(self):
        return attrUtils.get_message_attr(self.container.name, HEAT_MAP_MESH_STRING_IDENTIFIER)

    @property
    def node_network_container(self):
        node_network_name = attrUtils.get_message_attr(self.container.name, NODE_NETWORK_CONTAINER_STRING_IDENTIFIER)
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
        return attrUtils.get_message_attr(self.container.name, BASE_MESH_STRING_IDENTIFIER)

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
        if self.network._shapes.invalid_shapes:
            shape_list_str = "    \n".join([str(s) for s in self.network._shapes.invalid_shapes])
            print(f"Warning: The following shapes are invalid and were added as InvalidShape:\n{shape_list_str}")
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
        # we need to temporarily disconnect the driver if it's connected to the face ctrl
        
        driver = self.blendshape.get_weight_driver(w)
        blend_attr = f"{self.blendshape.name}.{shape}"
        if driver == self.face_ctrl:
            driving_attribute = cmds.listConnections(blend_attr,
                                                     source=True,
                                                     destination=False,
                                                     plugs=True) or []
            if not driving_attribute:
                raise ValueError(f"Failed to get driving attribute for shape '{shape}'.")
            # cmds.disconnectAttr(driving_attribute[0], blend_attr)
            cmds.setAttr(driving_attribute[0], value)
            # reconnecting the driver
            # cmds.connectAttr(driving_attribute[0],blend_attr, force=True)
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


    def remove_shape_from_locked_shapes(self, shape_name: str):
        """
        Remove a shape from the locked shapes set.
        Parameters:
            shape_name (str): The name of the shape to unlock
        """
        print(f"Removing shape '{shape_name}' from locked shapes.")
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
    def disconnect_work_shape(self, work_shape_name: str):
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
    def connect_work_shape_to_shape(self,work_shape_name: str, shape_name: str):
        """
        Connect a work shape to the face control for direct manipulation.
        Parameters:
            work_shape_name (str): The name of the work shape to connect
            shape_name (str): The name of the primary shape to connect to
        """
        print(f"Connecting work shape '{work_shape_name}' to primary shape '{shape_name}' for direct manipulation.")
        work_shape_weight = self.work_blendshape.get_weight_by_name(work_shape_name)
        if work_shape_weight is None:
            raise ValueError(f"Work shape '{work_shape_name}' not found in blendshape.")
        shape_weight  = self.blendshape.get_weight_by_name(shape_name)
        if shape_weight is None:
            raise ValueError(f"Shape '{shape_name}' not found in blendshape.")
        # let's check if there is a driven key already. If there is we need to remove it before creating a new one
        driver = self.work_blendshape.get_weight_driver(work_shape_weight)
        print(f"Existing driver for work shape '{work_shape_name}': {driver}")
        if driver and cmds.nodeType(driver) in ["animCurveUL", "animCurveUA", "animCurveUT", "animCurveUU"]:
            cmds.delete(driver)
        else:
            print(f"No existing driven key found for work shape '{work_shape_name}'. Creating new driven key connection.")
        # if the drive still exists that means that some manual connections were made
        # and we need to disconnect them before creating the driven key connection
        input_connection = cmds.listConnections(f"{self.work_blendshape.name}.{work_shape_name}", source=True, destination=False, plugs=True) or []
        for conn in input_connection:
            cmds.disconnectAttr(conn, f"{self.work_blendshape.name}.{work_shape_name}")

        # we need to create a set driven key connection between the work shape and the primary shape
        print(f"Creating driven key from '{self.work_blendshape.name}.{work_shape_name}' to '{self.blendshape.name}.{shape_name}'")
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
        print("Driven key connection created successfully.")

    def copy_work_weight_map_values(self, shape_name: str):
        """
        Copy the weight values of a shape to be pasted later.
        Parameters:
            shape_name (str): The name of the shape to copy the weight values from
        """
        weight = self.work_blendshape.get_weight_by_name(shape_name)
        if weight is None:
            raise ValueError(f"Shape '{shape_name}' not found in {self.work_blendshape.name}.")

        self.copied_weight_map_values = self.work_blendshape.get_weight_map_values(weight)

    def paste_work_weight_map_values_to_shape(self, shape_name: str):
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
        self.work_blendshape.set_weight_map_values(weight, self.copied_weight_map_values)

    def paste_inverted_work_weight_map_values(self, shape_name: str):
        """
        Paste the copied weight values to a shape with inverted values.
        Parameters:
            shape_name (str): The name of the shape to paste the weight values to
        """
        if self.copied_weight_map_values is None:
            raise ValueError("No weight map values have been copied.")
        weight = self.work_blendshape.get_weight_by_name(shape_name)
        if weight is None:
            raise ValueError(f"Shape '{shape_name}' not found in {self.work_blendshape.name}.")
        inverted_values = 1 -np.array(self.copied_weight_map_values) 
        self.work_blendshape.set_weight_map_values(weight, inverted_values.tolist())

    def add_work_weight_map_values(self, shape_name: str):
        """
        Paste the copied weight values to a shape by adding them to the existing values.
        Parameters:
            shape_name (str): The name of the shape to paste the weight values to
        """
        if self.copied_weight_map_values is None:
            raise ValueError("No weight map values have been copied.")
        weight = self.work_blendshape.get_weight_by_name(shape_name)
        if weight is None:
            raise ValueError(f"Shape '{shape_name}' not found in {self.work_blendshape.name}.")
        existing_values = self.work_blendshape.get_weight_map_values(weight)
        new_values = np.array(existing_values) + np.array(self.copied_weight_map_values)
        self.work_blendshape.set_weight_map_values(weight, new_values.tolist())
    
    def subtract_work_weight_map_values(self, shape_name: str):
        """
        Paste the copied weight values to a shape by subtracting them from the existing values.
        Parameters:
            shape_name (str): The name of the shape to paste the weight values to
        """
        if self.copied_weight_map_values is None:
            raise ValueError("No weight map values have been copied.")
        weight = self.work_blendshape.get_weight_by_name(shape_name)
        if weight is None:
            raise ValueError(f"Shape '{shape_name}' not found in {self.work_blendshape.name}.")
        existing_values = self.work_blendshape.get_weight_map_values(weight)
        new_values = np.array(existing_values) - np.array(self.copied_weight_map_values)
        self.work_blendshape.set_weight_map_values(weight, new_values.tolist()) 

    def normalize_work_weight_map_values(self, shape_names: list):
        """
        Normalize the weight values of the given shapes so that the maximum value of the sum of all weight value for each vertex is always 1.0.
        Parameters:
            shape_names (list): A list of shape names to normalize the weight values for
        """
        if not shape_names:
            return

        if self.work_blendshape is None:
            raise ValueError("Work blendshape not found.")

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
            weight = self.work_blendshape.get_weight_by_name(shape_name)
            if weight is None:
                raise ValueError(f"Shape '{shape_name}' not found in {self.work_blendshape.name}.")
            weights.append(weight)
            maps.append(np.asarray(self.work_blendshape.get_weight_map_values(weight), dtype=np.float64))

        stacked_maps = np.vstack(maps)
        per_vertex_sum = stacked_maps.sum(axis=0)
        # Vertices with totals <= 1.0 remain unchanged.
        scale = np.where(per_vertex_sum > 1.0, 1.0 / per_vertex_sum, 1.0)
        normalized_maps = stacked_maps * scale

        for weight, normalized_values in zip(weights, normalized_maps):
            self.work_blendshape.set_weight_map_values(weight, normalized_values.tolist())

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
        self.work_blendshape.set_weight_map_values(weight, self.copied_weight_map_values)

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


    def commit_shape(self, shape_name: str, mesh: str):
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
            self.add_primary_shape(mesh, shape)
        elif shape.type == "InbetweenShape":
            # setting the pose of the rig to the inbetween shape
            self.add_inbetween_shape(mesh, shape)
        elif shape.type in ["ComboShape", "ComboInbetweenShape"]:
            self.add_combo_shape(mesh, shape)
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


    @undoable
    def commit_shapes(self, selected: list, close_shape_editor: bool = True):
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
                invalid_shapes.append(mesh)

        related_downstream_locked_shapes = related_downstream_shapes.intersection(self.locked_shapes)
        extracted_locked_meshes = None
        extraction_group = None
        if related_downstream_locked_shapes:
            extraction_group, extracted_locked_meshes = self.extract_shapes_to_mesh(related_downstream_locked_shapes)

        # we need to get the downstream shapes for the selected shapes.
        # close the shape editor if it's open
        shape_editor_exists = cmds.window(self.SHAPE_EDITOR_PANEL, exists=True)
        if shape_editor_exists and close_shape_editor:
            cmds.deleteUI(self.SHAPE_EDITOR_PANEL)
        self._commit_batch_shapes_with_progress_bar(valid_meshes, progress_bar_message="Committing {0} shapes...")
        # after all shapes have been added we need to update the remap nodes for the primaries that had new inbetweens added
        # now we need to commit the locked
        if extracted_locked_meshes:
            self._commit_batch_shapes_with_progress_bar(extracted_locked_meshes, progress_bar_message="Restoring locked {0} shapes...")
            if extraction_group:
                cmds.delete(extraction_group)
        if shape_editor_exists and close_shape_editor:
            cmds.ShapeEditor()
        if TIMED:
            print(f"Finished committing {len(valid_meshes)} shapes on {len(selected)} Restored: {len(extracted_locked_meshes) if extracted_locked_meshes else 0} locked shapes in {time.time() - start:.2f} seconds.")
        cmds.select(clear=True)
        cmds.select(self.container.name, replace=True)
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
        weight_map_values = self.work_blendshape.get_weight_map_values(weight)
        self.work_blendshape.set_weight_map_values(duplicated_weight, weight_map_values)
        deltas = self.work_blendshape.get_target_delta(weight)
        self.work_blendshape.set_target_delta(duplicated_weight, deltas)
        return duplicated_weight

    def paint_work_blendshape_target(self, weight_name: str) -> int:
        """Enter paint mode for one work blendshape target and return its target id."""
        if self.work_blendshape is None:
            raise ValueError("Work blendshape not found.")
        sculpt_weight = self.work_blendshape.get_weight_by_name(weight_name)
        if sculpt_weight is None:
            raise ValueError(f"Work shape '{weight_name}' not found in work blendshape.")
        self.work_blendshape.set_target_weight_paint_mode(sculpt_weight)
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
            raise ValueError("Work blendshape not found.")
        weight = self.work_blendshape.get_weight_by_name(shape_name)
        if weight is None:
            raise ValueError(f"Work shape '{shape_name}' not found in work blendshape.")
        parent_dir = self.work_blendshape.get_weight_parent_directory(weight)
        parent_dir_value = self.work_blendshape.get_target_dir_weight_value(parent_dir)
        return bool(parent_dir_value == 0)

    def create_extraction_mesh(self):
        """
        Create an extraction mesh by duplicating the base mesh. and connecting it to self.blendshape.
        This will allow to extract pure shape deltas without any influence from other deformers.
        """
        base_mesh = self.base_mesh
        if base_mesh is None:
            raise ValueError("Base mesh not found.")
        extraction_mesh_name = f"{self.editor_base_name}_extractionMesh"
        extraction_group_name = f"{self.editor_base_name}_extractedShapes_GRP"
        if not cmds.objExists(extraction_group_name):
            cmds.createNode("transform", name=extraction_group_name)
        
        extraction_mesh = cmds.duplicate(base_mesh, name=extraction_mesh_name)[0]
        extraction_mesh = cmds.parent(extraction_mesh, extraction_group_name)[0] #making sure name does not change
        # we need to connect the extraction mesh to the blendshape
        cmds.connectAttr(f"{self.blendshape.name}.outputGeometry[0]", f"{extraction_mesh}.inMesh", force=True)
        return extraction_mesh

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
        extracted_meshes = {}
        extraction_mesh = self.create_extraction_mesh()
        extraction_group = cmds.listRelatives(extraction_mesh, parent=True, fullPath=True)[0]
        for shape_name in shape_names:
            shape = self.network.get_shape(shape_name)
            if shape is None:
                print(f"Warning: Shape '{shape_name}' not found in the network. Skipping extraction.")
                continue
            self.set_shape_pose(shape)
            # we need to duplicate the extraction mesh with the shape name
            extracted_shape_mesh = cmds.duplicate(extraction_mesh, name=shape_name)[0]
            if extracted_shape_mesh[0].split("|")[-1] != shape_name:
                extracted_shape_mesh = cmds.rename(extracted_shape_mesh, shape_name)
            extracted_meshes[shape_name] = extracted_shape_mesh
        cmds.delete(extraction_mesh)
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
        # we need to close the shape editor if it's open
        shape_editor_exists = cmds.window(self.SHAPE_EDITOR_PANEL, exists=True)
        if shape_editor_exists:
            cmds.deleteUI(self.SHAPE_EDITOR_PANEL)
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
                if current_dir_name is None or current_dir_name == PRIMARY_SHAPES_GRP_NAME:
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

    def add_primary_shape(self, mesh: str, shape: Shape):
        """
        Add a primary shape to the Blue Steel rig.
        Parameters:
            shape_name (str): The name of the shape to add
            split_maps (list): A list of SplitMap instances to use for the shape
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
            w = self.blendshape.add_target(weight_name=shape, target_object=mesh)
            # we need to connect the the blendshape weight to the face control attribute
            cmds.connectAttr(ctrl_attr,f"{self.blendshape.name}.{shape}", force=True)
            self.container.bind_attribute(ctrl_attr)
            if VERBOSE:
                print(f"Adding new {shape.type} shape {shape}")
            return_value = "ADDED"
            # let's create a shape target directory under the primary shapes group
            primary_dir = self.blendshape.get_target_dirs_by_name(PRIMARY_SHAPES_GRP_NAME)
            if primary_dir == []: # we need to create the primary shapes group
                primary_dir = self.blendshape.add_target_dir(PRIMARY_SHAPES_GRP_NAME)
            else:
                primary_dir = primary_dir[0]
            primary_shape_dir = self.blendshape.add_target_dir(name=shape,
                                                               parent_index=primary_dir.index)
            # let's parent the weight to the primary shape dir
            self.blendshape.set_weight_parent_directory(w, primary_shape_dir)

        else:
            w = self.blendshape.get_weight_by_name(shape)
            self.blendshape.update_target(weight=w, new_mesh=mesh)
            if VERBOSE:
                print(f"Updating existing {shape.type} shape {shape}")
            return_value = "UPDATED"
        shape.weight_id = w.id
        self.network.add_shape(shape)
        # we will set the shape now
        self.set_shape_pose(shape)
        return return_value

    @undoable
    def duplicate_base_mesh_neutral_state(self, mesh_name: str):
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
        # we need to remove all the intermediate objects.
        shapes = cmds.listRelatives(duplicated, shapes=True, fullPath=True) or []
        for shape in shapes:
            if cmds.getAttr(f"{shape}.intermediateObject"):
                cmds.delete(shape)
        # we need to get the base mesh points and set them to the duplicated mesh to make sure it's in the neutral state without any deformations
        base_points = self.blendshape.get_base_points()
        mayaUtils.set_points_from_numpy(duplicated, base_points)
        return duplicated

    def duplicate_base_mesh_at_current_pose(self): 
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


    def add_inbetween_shape(self, mesh: str, shape: Shape):
        """
        Add an inbetween shape to the Blue Steel rig.
        Parameters:
            shape_name (str): The name of the shape to add
        Returns:
            Either if the shape was ADDED or UPDATED.
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
            inbetween_dir = self.blendshape.get_target_dirs_by_name(INBETWEEN_SHAPES_GRP_NAME)
            if inbetween_dir == []: # we need to create the inbetween shapes group
                inbetween_dir = self.blendshape.add_target_dir(INBETWEEN_SHAPES_GRP_NAME)
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
        delta = self.blendshape.get_delta_from_mesh(mesh)

        self.blendshape.set_target_delta(weight=w, delta=delta)
        return return_value

    def add_combo_shape(self, mesh: str, shape: Shape):
        """
        Add a combo shape to the Blue Steel rig.
        Parameters:
            shape_name (str): The name of the shape to add
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
            combo_dir = self.blendshape.get_target_dirs_by_name(COMBO_SHAPES_GRP_NAME)
            if combo_dir == []: # we need to create the combo shapes group
                combo_dir = self.blendshape.add_target_dir(COMBO_SHAPES_GRP_NAME)
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
        # extracting the combo shape
        delta = self.blendshape.get_delta_from_mesh(mesh)
        self.blendshape.set_target_delta(weight=w, delta=delta)
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
            delta = self.blendshape.get_target_delta(w)
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
        attrUtils.add_message_attr(container.name, BASE_MESH_STRING_IDENTIFIER, mesh_name)
        attrUtils.add_message_attr(container.name, NODE_NETWORK_CONTAINER_STRING_IDENTIFIER, network_container.name)
        attrUtils.add_tag(container.name, "lockedShapes", "")
        container.add_member(network_container.name)

        editor_group_name = f"{editor_name}_Blendshapes_GRP"
        editor_grp_id = cls.add_shape_editor_directory(editor_group_name)

        blendshape_names_suffices = ["splitBlendshape", "workBlendshape", "mainBlendshape"]
        message_attributeds = [SPLIT_BLENDSHAPE_STRING_IDENTIFIER,
                               WORK_BLENDSHAPE_STRING_IDENTIFIER,
                               MAIN_BLENDSHAPE_STRING_IDENTIFIER]
        # create the blendshape node blendshape.
        for suffix, message_attr in zip(blendshape_names_suffices, message_attributeds):
            blendshape_name = f"{editor_name}_{suffix}"
            cls.add_new_blendshape_to_container(blendshape_name=blendshape_name,
                                                mesh_name=mesh_name,
                                                container=container,
                                                message_attr=message_attr,
                                                parent_directory_index=editor_grp_id)
            if suffix == "mainBlendshape":
                # adding the target groups to the blendshape editor
                blendshape = Blendshape(blendshape_name)
                blendshape.add_target_dir(PRIMARY_SHAPES_GRP_NAME)
                blendshape.add_target_dir(INBETWEEN_SHAPES_GRP_NAME)
                blendshape.add_target_dir(COMBO_SHAPES_GRP_NAME)
                
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
        attrUtils.add_message_attr(container.name, FACE_CTRL_STRING_IDENTIFIER, face_ctrl)
        # create the split attribute group node
        split_settings_grp_name = f"{editor_name}_splitSettings_GRP"
        split_settings_grp = attrUtils.create_attribute_grp(split_settings_grp_name)
        container.add_member(split_settings_grp)
        attrUtils.add_message_attr(container.name, SPLIT_ATTR_GRP_STRING_IDENTIFIER, split_settings_grp)
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
        for link in [MAIN_BLENDSHAPE_STRING_IDENTIFIER,
                     SPLIT_BLENDSHAPE_STRING_IDENTIFIER,
                     WORK_BLENDSHAPE_STRING_IDENTIFIER,
                     SPLIT_ATTR_GRP_STRING_IDENTIFIER,
                     NODE_NETWORK_CONTAINER_STRING_IDENTIFIER]:
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

    def unfreeze_shape_editor(self):
        """Unfreeze the shape editor panel to allow it to refresh after being frozen.
        This is useful when committing multiple shapes to the rig.
        """
        widget = self._get_shape_editor_widget()
        if widget:
            widget.setVisible(True)
            widget.blockSignals(False)
            widget.setUpdatesEnabled(True)

    def _get_shape_editor_widget(self):
        """Get the shape editor widget.
        Returns:
            QtWidgets.QWidget: The shape editor widget.
        """
        shape_editor_panel = self.SHAPE_EDITOR_PANEL
        if not cmds.window(shape_editor_panel, exists=True):
            return None
        shape_editor_widget = omui.MQtUtil.findControl(shape_editor_panel)
        if not shape_editor_widget:
            return None
        shape_editor_widget = wrapInstance(int(shape_editor_widget), QtWidgets.QWidget)
        return shape_editor_widget


    def freeze_shape_editor(self):
        """Freeze the shape editor panel to avoid it from refreshing while we are making changes.
        This is useful when committing multiple shapes to the rig.
        """
        widget = self._get_shape_editor_widget()
        if widget:
            widget.setVisible(False)
            widget.blockSignals(True)
            widget.setUpdatesEnabled(False)

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
