from maya import cmds, mel
import numpy as np
from dataclasses import dataclass, field
import re
from . import mayaUtils
from .targetDirectory import TargetDirectory
from maya import OpenMaya as om
from maya.api import OpenMaya as om2
import os
import time
        
class Weight(str):
    """
    A class to represent a weight with a name and an ID.

    Attributes:
        name (str): The name of the weight.
        id (int): The unique identifier for the weight.
        target_items (list): List of target item logical indices associated with this weight.
        blend_shape (str): The name of the blend shape node this weight belongs to.

    Example:
        >>> w = Weight(name="Spine", id=3, target_items=[6000], blend_shape="blendShape1")
        >>> print(w)
        Spine
        >>> print(w.id)
        3
    """
    def __new__( cls, name: str, id: int, target_items=None, blend_shape=None):
        obj = str.__new__(cls, name)
        obj.id = id
        obj.target_items = target_items if target_items is not None else []
        obj.blend_shape = blend_shape
        return obj

    def __str__(self) -> str:
        """
        Returns the name of the weight as its string representation.

        Returns:
            str: The name of the weight.
        """
        return super().__str__()

    def __repr__(self) -> str:
        """
        Returns a string representation of the Weight object.
        This includes the name and ID of the weight.
        Returns:
            str: A string representation of the Weight object.
        Example:
        >>> w = Weight(name="Spine", id=3)
        """
        target_items = " ,".join([str(item) for item in self.target_items])
        return f"Weight: (name: {super().__repr__()} id: {self.id} target_items: [{target_items}])"


    
class Blendshape(object):
    """
    Blendshape class to handle blendshape nodes in Maya.
    """
    INPUT_TARGET = "{0}.inputTarget[0].inputTargetGroup[{1}].inputTargetItem[{2}]"
    

    def __init__(self, name: str):
        self.name = name
        if not cmds.objExists(self.name):
            raise ValueError(f"Blendshape node '{self.name}' does not exist.")
        self.base = self.get_base()
        if self.base is None:
            raise ValueError(f"Blendshape node '{self.name}' has no base mesh connected.")
        else:
            self.base = self.base[0]
        # sourcing the artAttrBlendShapeToolScript.mel to make sure set_target_weight_paint_mode will work without errors
        mel.eval('source "artAttrBlendShapeToolScript.mel"')
        mel.eval('source "artAttrBlendShapeCallback.mel"')
    def __str__(self):
        return self.name

    def __repr__(self):
        return f"Blendshape: {self.name}"

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def weights(self):
        return self.get_weights()
    
    @property
    def mid_layer_id(self):
        return cmds.getAttr(f"{self.name}.midLayerId")
    
    @property
    def mid_layer_parent(self):
        return cmds.getAttr(f"{self.name}.midLayerParent")

    #-------------------------------------------------------------------
    # Mid layer functions
    #-------------------------------------------------------------------
    def set_mid_layer_parent(self, mid_layer_parent_id: int):
        """
        Sets the mid layer ID for the blendshape node.
        Parameters:
            mid_layer_parent_id (int): The mid layer parent ID to set.
        """
        current_parent_id = self.mid_layer_parent
        layer_id = self.mid_layer_id
        # we need to check if the directory that hosts this mid layer id exists or not
        current_parent_dir_name = cmds.getAttr(f"shapeEditorManager.blendShapeDirectory[{current_parent_id}].directoryName")
        current_parent_dir_indices = cmds.getAttr(f"shapeEditorManager.blendShapeDirectory[{current_parent_id}].childIndices") or []
        print(f"Current mid layer parent directory: {current_parent_dir_name} with child indices: {current_parent_dir_indices}")
        if layer_id in current_parent_dir_indices:
            # we need to remove it from the current parent directory first
            current_parent_dir_indices.remove(layer_id)
            cmds.setAttr(f"shapeEditorManager.blendShapeDirectory[{current_parent_id}].childIndices", current_parent_dir_indices, type="Int32Array")
        # then we can set the new mid layer id
        new_mid_layer_parent_dir_indices = cmds.getAttr(f"shapeEditorManager.blendShapeDirectory[{mid_layer_parent_id}].childIndices") or []
        if layer_id not in new_mid_layer_parent_dir_indices:
            new_mid_layer_parent_dir_indices.append(layer_id)
            cmds.setAttr(f"shapeEditorManager.blendShapeDirectory[{mid_layer_parent_id}].childIndices", new_mid_layer_parent_dir_indices, type="Int32Array")
        cmds.setAttr(f"{self.name}.midLayerParent", mid_layer_parent_id)

    

    # ------------------------------------------------------------------
    # Creation methods
    # ------------------------------------------------------------------
    @classmethod
    def create(cls, name:str, base_mesh:str)->'Blendshape':
        """
        Creates a new blendshape node with the specified name and base mesh.
        Parameters:
            name (str): The name of the blendshape node to create.
            base_mesh (str): The name of the base mesh to which the blendshape
            will be applied.

        Returns:
            Blendshape: An instance of the Blendshape class representing the
                created blendshape node.
        Example:
            >>> blendshape = Blendshape.create("myBlendshape", "pCube1")
            >>> print(blendshape.name)
            myBlendshape
        """
        if not cmds.objExists(base_mesh):
            raise ValueError(f"Base mesh '{base_mesh}' does not exist.")
        blendshape_node = cmds.blendShape(base_mesh, name=name, foc=True)[0]
        return cls(blendshape_node)
    
    # ------------------------------------------------------------------
    # Base geometry methods
    # ------------------------------------------------------------------
    def get_base(self)-> str:
        """
        Returns the input transformation node of the blendShape at the index 0.
        Returns:
            str: The name of the base mesh connected to the blendshape node,
                or None if not found.
        Example:
            >>> blendshape = Blendshape.create("myBlendshape", "pCube1")
            >>> base_mesh = blendshape.get_base()
            >>> print(base_mesh)
            pCube1
        """
        base = cmds.blendShape(self.name, q=True, g=True) or None
        return base if base else None

    def get_base_vertex_count(self)-> int:
        """
        Returns the number of vertices in the base mesh of the blendShape node.
        Returns:
            int: The number of vertices in the base mesh.
        Example:
            >>> blendshape = Blendshape.create("myBlendshape", "pCube1")
            >>> vertex_count = blendshape.get_base_vertex_count()
            >>> print(vertex_count)
            8
        """
        if not self.base:
            raise ValueError(f"Blendshape node '{self.name}'"
                             " has no base mesh connected.")
        return cmds.polyEvaluate(self.base, vertex=True)

    def get_base_deformed_points(self)-> np.ndarray:
        """
        Returns the points of the deformed base mesh of the blendShape node as
            a numpy array.
        Returns:
            numpy.ndarray: A (N, 3) array of doubles where each row is [x, y, z].
            Example:
            >>> blendshape = Blendshape.create("myBlendshape", "pCube1")
            >>> points = blendshape.get_base_deformed_points()
            >>> print(points)
            [(1.0, 2.0, 3.0), (4.0, 5.0, 6.0), ...]
        """
        if not self.base:
            raise ValueError(f"Blendshape node '{self.name}'"
                             " has no base mesh connected.")
        # np_array = mayaUtils.get_points_as_numpy(self.base)
        # np_array = np_array[:, :3]  # remove the 4th row which is always 1.0
        np_array = mayaUtils.get_mesh_raw_points(self.base)
        return np_array

    def set_sculpt_target_index(self, weight_index: int):
        """
        Sets the sculpt target index for the specified weight.
        Parameters:
            weight_index (int): The index of the weight to set the sculpt target for.
        Example:
            >>> blendshape = Blendshape.create("myBlendshape", "pCube1")
            >>> weight = blendshape.get_weight_by_name("Smile")
            >>> blendshape.set_sculpt_target_index(.id)
        """
        cmds.sculptTarget(self.name, e=True, t=int(weight_index))

    def get_sculpt_target_indices(self)->list:
        """
        Returns a list of sculpt target IDs in the blendShape node.
        Returns:
            list: A list of sculpt target IDs.
        Example:
            >>> blendshape = Blendshape.create("myBlendshape", "pCube1")
            >>> sculpt_ids = blendshape.get_sculpt_target_indices()
            >>> print(sculpt_ids)
            [1, -1, 2]
        """
        sculpt_ids = []
        sculpt_target_group = mayaUtils.get_plug(self.name,"inputTarget")
        for i in range(sculpt_target_group.numElements()):
            target_item_plug = sculpt_target_group.elementByPhysicalIndex(i)
            for j in range(target_item_plug.numChildren()):
                child_plug = target_item_plug.child(j)
                if child_plug.name().endswith("sculptTargetIndex"):
                    sculpt_ids.append(child_plug.asInt())
        return sculpt_ids

    #TODO: move to mayaUtils
    def print_numpy_array(self, array: np.ndarray, name: str = "Array"):
        """
        Prints the numpy array in a formatted way.
        Parameters:
            array (numpy.ndarray): The numpy array to print.
        """
        if array is None:
            print("Array is None")
            return
        if not isinstance(array, np.ndarray):
            print("Array is not a numpy array")
            return
        print(f"Numpy Array: {name} Shape: {array.shape}")
        for row in array:
            # round each value to 4 decimal places
            row = np.round(row, 4)
            row_line = ", ".join([f"{val:8.4f}" for val in row])
            print(f"    {row_line}")
        print("================ End of Array ====================")

    def get_base_points(self)-> np.ndarray:
        """
        Returns the points of the base mesh of the blendShape node as a numpy array.
        Returns:
            numpy.ndarray: A (N, 3) array of doubles where each row is [x, y, z].
        Example:
            >>> blendshape = Blendshape.create("myBlendshape", "pCube1")
            >>> points = blendshape.get_base_points()
            >>> print(points)
            [(1.0, 2.0, 3.0), (4.0, 5.0, 6.0), ...]
        """
        if not self.base:
            raise ValueError(f"Blendshape node '{self.name}'"
                             " has no base mesh connected.")
        # Get the intermediate shape of the base mesh
        parent = cmds.listRelatives(self.base, parent=True)[0]
        shapes = cmds.listRelatives(parent, shapes=True, fullPath=True) or []
        intermediate = None
        # we need to clear up the dead intermediate shapes first
        for shape in shapes:
            if cmds.getAttr(f"{shape}.intermediateObject"): 
                out_mesh_connections = cmds.listConnections(f"{shape}.outMesh",
                                                            source=False,
                                                            destination=True,
                                                            plugs=True) or []
                if not out_mesh_connections:
                    cmds.delete(shape)
                else:
                    intermediate = shape
        if intermediate is None:
            raise ValueError(f"Base mesh '{self.base}'"
                             " has no intermediate shape.")
        # checking the vertex count of the intermediate shape
        # we need to create a temp mesh and plug the intermediate shape to it
        np_array = mayaUtils.get_mesh_raw_points(intermediate)
        return np_array

    def duplicate_base(self, name = None)-> str:
        """
        Duplicates the base mesh of the blendShape node.
        Parameters:
            name: The name of the new mesh.
                If None,it will use the base mesh name.
        Returns:
            str: The name of the duplicated mesh.
        Example:
            >>> blendshape = Blendshape.create("myBlendshape", "pCube1")
            >>> new_mesh = blendshape.duplicate_base("pCube1_copy")
            >>> print(new_mesh)
            pCube1_copy
        """
        points = self.get_base_points()
        if name is None:
            name = self.base.split('|')[-1]
        new_mesh = cmds.duplicate(self.base, name =name)
        # making sure this new mesh is equal to the base mesh
        mayaUtils.set_mesh_raw_points(new_mesh[0], points)

        return new_mesh[0]


    # ------------------------------------------------------------------
    # Target mute methods
    # ------------------------------------------------------------------

    def set_target_mute_state(self, weight: Weight, state: bool, target_value: int = 6000):
        """
        Sets the mute state of the target.
        At the moment blendshape inbetween are not supported.
        We do not need that because blueSteel will handle
        targets at 6000 only.
        Parameters:
            weight (Weight): The weight object representing the target to mute.
            target_value (int): The value to set the target weight to (default is 6000).
        """
        cmds.setAttr(f"{self.name}.targetVisibility[{weight.id}]", not state)

    def unmute_all_targets(self):
        """
        Unmutes all targets in the blendShape node.
        """
        all_weights = self.get_weights()
        for weight in all_weights:
            self.set_target_mute_state(weight, False)


    def get_target_mute_state(self, weight: Weight)-> bool:
        """
        Returns the mute state of the target.
        Parameters:
            weight (Weight): The weight object representing the target to check.
        Returns:
            bool: True if the target is muted, False otherwise.
        Example:
            >>> blendshape = Blendshape("myBlendshape")
            >>> weight = blendshape.get_weight_by_name("Smile")
            >>> is_muted = blendshape.get_target_mute_state(weight)
            >>> print(is_muted)
            False
        """
        visibility = cmds.getAttr(f"{self.name}.targetVisibility[{weight.id}]")
        return visibility == 0

    def get_muted_targets(self)->list:
        """
        Returns a list of muted targets in the blendShape node.
        Each target is represented as a Weight object with a name and an ID.
        :Returns: A list of Weight objects that are muted.
        :Example:
            >>> blendshape = Blendshape("myBlendshape")
            >>> muted_targets = blendshape.get_muted_targets()
            >>> for target in muted_targets:
            ...     print(f"Muted Target Name: {target.name}, Target ID: {target.id}")
            Muted Target Name: Smile, Target ID: 0
            Muted Target Name: Frown, Target ID: 2
        """
        all_weights = self.get_weights()
        muted_weights = []
        for weight in all_weights:
            visibility = cmds.getAttr(f"{self.name}.targetVisibility[{weight.id}]")
            if visibility == 0:
                muted_weights.append(weight)
        return muted_weights

    # ------------------------------------------------------------------
    # MAYA API plug methods
    # ------------------------------------------------------------------

    def get_dependency_node(self)->om.MObject:
        """
        Get the MObject of the blendshape node.
        Returns:
            MObject: The MObject of the blendshape node.
        Example:
            >>> blendshape = Blendshape.create("myBlendshape", "pCube1")
            >>> m_obj = blendshape.get_dependency_node()
            >>> print(m_obj)
            <maya.api.OpenMaya.MObject object at 0x...>
        """
        return mayaUtils.get_dependency_node(self.name)

    def get_inbetween_info_group_plug(self, weight_id: int, target_item_id:int)->om.MPlug:
        """
        Returns the MPlug for the specified inbetween info group
        and item in the blendshape node.
        Parameters:
            weight_id (int): The ID of the target group.
            target_item_id (int): The ID of the target item.
        Returns:
            om.MPlug or None: The MPlug for the specified inbetween info
                group and item, or None if not found.
        Example:
            >>> blendshape = Blendshape("myBlendshape")
            >>> plug = blendshape.get_inbetween_info_group_plug(0, 5500)
            >>> print(plug.name())
        """

        # setAttr blendShape2.inbetweenInfoGroup[0].inbetweenInfo[5250].inbetweenTargetName
        input_inbetween_plug = mayaUtils.get_plug(self.name,"inbetweenInfoGroup")
        if input_inbetween_plug.isNull():
            raise RuntimeError("Could not find inputInbetween"
                               f" plug on blendshape node '{self.name}'")
        # Getting this plug
        # Inbetween group plug name:
        # <blendShape>.inbetweenInfoGroup[weight_id].inbetweenInfo
        ib_group_plug = input_inbetween_plug.elementByLogicalIndex(weight_id)
        inbetween_group_plug = ib_group_plug.child(0)
        # going through all the elements in this plug
        # <blendShape>.inbetweenInfoGroup[weight_id].inbetweenInfo[5500] [5250]...
        for i in range(inbetween_group_plug.numElements()):
            element_plug = inbetween_group_plug.elementByPhysicalIndex(i)
            if element_plug.logicalIndex() == target_item_id:
                # found the plug
                return element_plug

        return None

    def get_inbetween_info_child_plugs(self, weight_id: int, target_item_id:int)->list:
        """
        Returns the MPlug for the specified child of the inbetween
        info group and item in the blendshape node.
        Parameters:
            weight_id (int): The ID of the target group.
            
            target_item_id (int): The ID of the target item.
            
            child_name (str): The name of the child plug to retrieve.
        Returns:
            om.MPlug or None: The MPlug for the specified child of
            the inbetween info group and item, or None if not found.
        Example:
            >>> blendshape = Blendshape("myBlendshape")
            >>> plug = blendshape.get_inbetween_info_child_plugs(0,
                                                                 5500,
                                                                 "ibwtName")
            >>> print(plug.name())
            myBlendshape.inbetweenInfoGroup[0].inbetweenInfo[5500].ibwtName
        """
        child_plugs = list()
        ib_info_plug = self.get_inbetween_info_group_plug(weight_id, target_item_id)
        for i in range(ib_info_plug.numChildren()):
            child_plug = ib_info_plug.child(i)
            child_plugs.append(child_plug.name())
        return child_plugs

    def get_inbetween_target_name_plug(self, weight_id: int, target_item_id:int)->om.MPlug:
        """

        Returns the MPlug for the inbetween target name of the specified
        weight and target item in the blendshape node.
        Parameters:
            weight_id (int): The ID of the target group.
            
            target_item_id (int): The ID of the target item.

        Returns:
            om.MPlug or None: The MPlug for the inbetween target name,
            or None if not found.

        Example:
            >>> blendshape = Blendshape("myBlendshape")
            >>> plug = blendshape.get_inbetween_target_name_plug(0, 5500)
            >>> print(plug.name())
            myBlendshape.inbetweenInfoGroup[0].inbetweenInfo[5500].inbetweenTargetName
        """
        inbetween_info_plug = self.get_inbetween_info_group_plug(weight_id, target_item_id)
        for i in range(inbetween_info_plug.numChildren()):
            child_plug = inbetween_info_plug.child(i)
            if child_plug.name().endswith("inbetweenTargetName"):
                return child_plug
        return None

    def get_target_input_geom_plug(self, weight_id: int, target_item_id:int = 6000)->om.MPlug:
        """
        Returns the MPlug for the input geometry of the specified target group
        and item in the blendshape node.
        Parameters:
            weight_id (int): The ID of the target group.
            target_item_id (int): The ID of the target item. Default is 6000.
        Returns:
            om.MPlug: The MPlug for the input geometry of the specified target group and item.
        Example:
            >>> blendshape = Blendshape("myBlendshape")
            >>> plug = blendshape.get_target_input_geom_plug(0, 6000)
            >>> print(plug.name())
            myBlendshape.inputTarget[0].inputTargetGroup[0].inputTargetItem[6000].inputGeom
        """
        input_target_plug = mayaUtils.get_plug(self.name,"inputTarget")
        target_plug = input_target_plug.elementByLogicalIndex(0)
        target_group_plug = target_plug.child(0).elementByLogicalIndex(weight_id)
        target_item_plug = target_group_plug.child(0).elementByLogicalIndex(target_item_id)
        for i in range(target_item_plug.numChildren()):
            child_plug = target_item_plug.child(i)
            if child_plug.name().endswith("inputGeomTarget"):
                return child_plug
        raise RuntimeError(f"Could not find inputGeom plug for weight ID {weight_id} "
                           f"and target item ID {target_item_id}")


    def get_target_group_plug(self, weight_id: int, target_item_id:int = 6000):
        """
        Returns the MPlug for the specified target group and item in the blendshape node.
        Parameters:
            weight_id (int): The ID of the target group.
            target_item_id (int): The ID of the target item. Default is 6000.
        Returns:
            om.MPlug: The MPlug for the specified target group and item.
        Example:
            >>> blendshape = Blendshape("myBlendshape")
            >>> plug = blendshape.get_target_group_plug(0, 6000)
            >>> print(plug.name())
            myBlendshape.inputTarget[0].inputTargetGroup[0].inputTargetItem[6000]
        """
        input_target_plug = mayaUtils.get_plug(self.name,"inputTarget")
        target_plug = input_target_plug.elementByLogicalIndex(0)
        target_group_plug = target_plug.child(0).elementByLogicalIndex(weight_id)
        target_item_plug = target_group_plug.child(0).elementByLogicalIndex(target_item_id)
        return target_item_plug



    def get_target_group_logical_indices(self, weight_id: int)->list:
        """
        Returns a list of logical indices for the target items in the specified target group.
        Parameters:
            weight_id (int): The ID of the target group.
        Returns:
            list: A list of logical indices for the target items in the specified target group.
        Example:
            >>> blendshape = Blendshape("myBlendshape")
            >>> indices = blendshape.get_target_group_logical_indices(0)
            >>> print(indices)
            [5500, 6000]
        """
        input_target_plug = mayaUtils.get_plug(self.name,"inputTarget")
        target_plug = input_target_plug.elementByLogicalIndex(0)
        target_group_plug = target_plug.child(0).elementByLogicalIndex(weight_id)
        target_item_plug = target_group_plug.child(0)
        logical_indices = list()
        for i in range(target_item_plug.numElements()):
            logical_indices.append(target_item_plug.elementByPhysicalIndex(i).logicalIndex())
        return logical_indices[::-1]  # reversing the list to have 6000 first

    #----------------------------------------------------------------
    #Target Directories methods
    #------------------------------------------------------------------
    def get_target_dirs(self)->list:
        """
        Returns a list of TargetDirectory objects in the blendShape node.
        Returns:
            list: A list of TargetDirectory objects.
        Example:
            >>> blendshape = Blendshape("myBlendshape")
            >>> target_dirs = blendshape.get_target_dirs()
            >>> print(target_dirs)
            [2] # list of target directory IDs with the name "MyGroup"
        """
        target_dirs = []
        target_dir_plug = mayaUtils.get_plug(self.name, "targetDirectory")
        for i in range(target_dir_plug.numElements()):
            element_plug = target_dir_plug.elementByPhysicalIndex(i)
            target_dir = TargetDirectory(index=element_plug.logicalIndex(), blendshape=self.name)
            target_dirs.append(target_dir)
        return target_dirs

    def get_target_dir_visibility(self, target_dir: TargetDirectory)-> bool:
        """
        Returns the visibility state of the specified target directory.
        Parameters:
            target_dir (TargetDirectory): The TargetDirectory object to get the visibility for.
        Returns:
            bool: True if the target directory is visible, False otherwise.
        Example:
            >>> blendshape = Blendshape("myBlendshape")
            >>> target_dir = blendshape.get_target_dirs()[0]
            >>> is_visible = blendshape.get_target_dir_visibility(target_dir)
            >>> print(is_visible)
            True
        """
        visibility = cmds.getAttr(f"{self.name}.targetDirectory[{target_dir.index}].directoryVisibility")
        return visibility
    
    def set_target_dir_visibility(self, target_dir: TargetDirectory, visibility: bool):
        """
        Sets the visibility state of the specified target directory.
        Parameters:
            target_dir (TargetDirectory): The TargetDirectory object to set the visibility for.
            visibility (bool): True to make the target directory visible, False to hide it.
        Example:
            >>> blendshape = Blendshape("myBlendshape")
            >>> target_dir = blendshape.get_target_dirs()[0]
            >>> blendshape.set_target_dir_visibility(target_dir, False)
        """
        cmds.setAttr(f"{self.name}.targetDirectory[{target_dir.index}].directoryVisibility", visibility)

    def get_target_dirs_by_name(self, name: str)-> list: # type: ignore
        """
        Returns a list with TargetDirectory objects with the specified name.
        """
        matched_dirs = []
        target_dirs = self.get_target_dirs()
        for target_dir in target_dirs:
            if target_dir.name == name:
                matched_dirs.append(target_dir)
        return matched_dirs
    
    def set_target_weight_paint_mode(self, weight: Weight):
        #artSetToolAndSelectAttr( "artAttrCtx", "blendShape.MetaHuman_mainBlendshape.baseWeights" );
        #artAttrInitPaintableAttr;
        #artBlendShapeSelectTarget artAttrCtx "browDownL";
        base_mesh = self.get_base()
        cmds.select(base_mesh)
    
        mel.eval(f'artSetToolAndSelectAttr("artAttrCtx", "blendShape.{self.name}.baseWeights")')
        mel.eval(f'artAttrInitPaintableAttr')
        # thiss needs to be deferred because it will throw an error if artAttrBlendShapeToolScript.mel is
        # sourced for the first time.
        def deferred():
            mel.eval(f'artBlendShapeSelectTarget("artAttrCtx", "{weight}");')
        cmds.evalDeferred(deferred)

    def get_target_dir_by_index(self, index: int)-> TargetDirectory or None: # type: ignore
        """
        Returns the TargetDirectory object with the specified index.
        """
        target_dirs = self.get_target_dirs()
        for target_dir in target_dirs:
            if target_dir.index == index:
                return target_dir
        return None

    def rename_target_dir(self, target_dir: TargetDirectory, new_name: str):
        """
        Renames the specified target directory.
        Parameters:
            target_dir (TargetDirectory): The TargetDirectory object to rename.
            new_name (str): The new name for the target directory.
        Example:
            >>> blendshape = Blendshape("myBlendshape")
            >>> target_dir = blendshape.get_target_dirs()[0]
            >>> blendshape.rename_target_dir(target_dir, "NewGroupName")
        """
        cmds.setAttr(f"{self.name}.targetDirectory[{target_dir.index}].directoryName",
                     new_name,
                     type="string")

    def add_target_dir(self, name: str, parent_index: int = 0)->TargetDirectory:
        """
        Adds a new target directory to the blendShape node.
        Parameters:
            name (str): The name of the new target directory.
            parent_index (int): The index of the parent directory. Default is -1 (no parent).
        Returns:
            TargetDirectory: The newly created TargetDirectory object.
        Example:
            >>> blendshape = Blendshape("myBlendshape")
            >>> new_dir = blendshape.add_target_dir("MyGroup", 0)
            >>> print(new_dir)
            TargetDirectory: (name: MyGroup id: 2 blendshape: myBlendshape)
        """
        # find the highest target directory index
        target_dirs = self.get_target_dirs()
        if target_dirs:
            highest_id = max(dir.index for dir in target_dirs)
            new_id = highest_id + 1
        else:
            new_id = 1
        # set the attributes for the new target directory
        cmds.setAttr(f"{self.name}.targetDirectory[{new_id}].directoryName", name, type="string")
        cmds.setAttr(f"{self.name}.targetDirectory[{new_id}].parentIndex", parent_index)
        parent_child_indices = cmds.getAttr(f"{self.name}.targetDirectory[{parent_index}].childIndices") or []
        if new_id not in parent_child_indices:
            parent_child_indices.append(-new_id)
            cmds.setAttr(f"{self.name}.targetDirectory[{parent_index}].childIndices",
                         parent_child_indices,
                         type="Int32Array")
        return TargetDirectory(index=new_id, blendshape=self.name)

    def remove_target_dir(self, target_dir: TargetDirectory):
        """
        Removes a target directory from the blendShape node.
        Parameters:
            target_dir (TargetDirectory): The TargetDirectory object to remove.
        Example:
            >>> blendshape = Blendshape("myBlendshape")
            >>> target_dir = blendshape.get_target_dirs()[0]
            >>> blendshape.remove_target_dir(target_dir)
        """
        parent_target_dir = self.get_target_dir_parent(target_dir)
        child_weights = self.get_target_dir_child_weights(target_dir)
        child_target_dirs = self.get_target_dir_child_target_dirs(target_dir)
        # we need to reallocate the child indices of the parent directory
        for weight in child_weights:
            self.set_weight_parent_directory(weight, parent_target_dir)
        for child_target_dir in child_target_dirs:
            self.set_target_dir_parent(child_target_dir, parent_target_dir)
        # we need to remove the target directory negative index from the parent directory
        parent_child_indices = self.get_target_dir_child_indices(parent_target_dir)
        if -target_dir.index in parent_child_indices:
            parent_child_indices.remove(-target_dir.index)
            self.set_target_dir_child_indices(parent_target_dir, parent_child_indices)
        # remove the target directory
        cmds.removeMultiInstance(f"{self.name}.targetDirectory[{target_dir.index}]", b=True)

    def get_target_dir_mute_state(self, target_dir: TargetDirectory)-> bool:
        """
        Returns the mute state of the specified target directory.
        Parameters:
            target_dir (TargetDirectory): The TargetDirectory object to get the mute state for.
        Returns:
            bool: True if the target directory is muted, False otherwise.
        Example:
            >>> blendshape = Blendshape("myBlendshape")
            >>> target_dir = blendshape.get_target_dirs()[0]
            >>> is_muted = blendshape.get_target_dir_mute_state(target_dir)
            >>> print(is_muted)
            False
        """
        mute_state = cmds.getAttr(f"{self.name}.targetDirectory[{target_dir.index}].directoryVisibility")
        return mute_state

    def generate_unique_weight_name(self, name):
        """
        Check if the weight name exists in the blendshape, and add a suffix if needed
        """
        existing_weight_names = self.get_weights()
        if name not in existing_weight_names:
            return name
        suffix = 1
        new_name = f"{name}_{suffix}"
        while new_name in existing_weight_names:
            suffix += 1
            new_name = f"{name}_{suffix}"
        return new_name

    def get_target_dir_weight_value(self, target_dir: TargetDirectory)-> float:
        """
        Returns the weight value of the specified target directory.
        Parameters:
            target_dir (TargetDirectory): The TargetDirectory object to get the weight value for.
        Returns:
            float: The weight value of the target directory.
        Example:
            >>> blendshape = Blendshape("myBlendshape")
            >>> target_dir = blendshape.get_target_dirs()[0]
            >>> envelope_value = blendshape.get_target_dir_envelope_value(target_dir)
            >>> print(envelope_value)
            1.0
        """
        envelope_value = cmds.getAttr(f"{self.name}.targetDirectory[{target_dir.index}].directoryWeight")
        return envelope_value

    def set_target_dir_weight_value(self, target_dir: TargetDirectory, value: float):
        """
        Sets the weight value of the specified target directory.
        Parameters:
            target_dir (TargetDirectory): The TargetDirectory object to set the weight value for.
            value (float): The weight value to set.
        Example:
            >>> blendshape = Blendshape("myBlendshape")
            >>> target_dir = blendshape.get_target_dirs()[0]
            >>> blendshape.set_target_dir_envelope_value(target_dir, 0.5)
        """
        cmds.setAttr(f"{self.name}.targetDirectory[{target_dir.index}].directoryWeight", value)

    def get_target_dir_parent(self, target_dir: TargetDirectory)-> TargetDirectory or None: # type: ignore
        """
        Returns the parent TargetDirectory of the specified target directory.
        Parameters:
            target_dir (TargetDirectory): The TargetDirectory object to get the parent for.
        Returns:
            TargetDirectory: The parent TargetDirectory object, or None if no parent.
        Example:
            >>> blendshape = Blendshape("myBlendshape")
            >>> target_dir = blendshape.get_target_dirs()[0]
            >>> parent_dir = blendshape.get_target_dir_parent(target_dir)
            >>> print(parent_dir)
            TargetDirectory: (name: Root id: 0 blendshape: myBlendshape)
        """
        parent_index = cmds.getAttr(f"{self.name}.targetDirectory[{target_dir.index}].parentIndex")
        return self.get_target_dir_by_index(parent_index)

    def set_target_dir_parent(self, target_dir: TargetDirectory, parent_dir: TargetDirectory):
        """
        Sets the parent TargetDirectory of the specified target directory.
        Parameters:
            target_dir (TargetDirectory): The TargetDirectory object to set the parent for.
            parent_dir (TargetDirectory): The TargetDirectory object to set as the parent.
        Example:
            >>> blendshape = Blendshape("myBlendshape")
            >>> target_dir = blendshape.get_target_dirs()[0]
            >>> parent_dir = blendshape.get_target_dirs()[1]
            >>> blendshape.set_target_dir_parent(target_dir, parent_dir)
        """
        old_parent_index = cmds.getAttr(f"{self.name}.targetDirectory[{target_dir.index}].parentIndex")
        # remove from old parent
        old_parent_child_indices = cmds.getAttr(f"{self.name}.targetDirectory[{old_parent_index}].childIndices") or []
        if -target_dir.index in old_parent_child_indices:
            old_parent_child_indices.remove(-target_dir.index)
            cmds.setAttr(f"{self.name}.targetDirectory[{old_parent_index}].childIndices",
                         old_parent_child_indices,
                         type="Int32Array")
        # set new parent index
        cmds.setAttr(f"{self.name}.targetDirectory[{target_dir.index}].parentIndex", parent_dir.index)
        # add to new parent
        new_parent_child_indices = cmds.getAttr(f"{self.name}.targetDirectory[{parent_dir.index}].childIndices") or []
        if -target_dir.index not in new_parent_child_indices:
            new_parent_child_indices.append(-target_dir.index)
            cmds.setAttr(f"{self.name}.targetDirectory[{parent_dir.index}].childIndices",
                         new_parent_child_indices,
                         type="Int32Array")

    def get_target_dir_child_indices(self, target_dir: TargetDirectory)-> list:
        """
        Returns the list of child indices of the specified target directory.
        Parameters:
            target_dir (TargetDirectory): The TargetDirectory object to get the child indices for.
        Returns:
            list: A list of child indices.
        Example:
            >>> blendshape = Blendshape("myBlendshape")
            >>> target_dir = blendshape.get_target_dirs()[0]
            >>> child_indices = blendshape.get_target_dir_child_indices(target_dir)
            >>> print(child_indices)
            [1, -2, 3]
        """
        child_indices = cmds.getAttr(f"{self.name}.targetDirectory[{target_dir.index}].childIndices") or []
        return child_indices
    
    def set_target_dir_child_indices(self, target_dir: TargetDirectory, child_indices: list):
        """
        Sets the list of child indices of the specified target directory.
        Parameters:
            target_dir (TargetDirectory): The TargetDirectory object to set the child indices for.
            child_indices (list): A list of child indices to set.
        Example:
            >>> blendshape = Blendshape("myBlendshape")
            >>> target_dir = blendshape.get_target_dirs()[0]
            >>> blendshape.set_target_dir_child_indices(target_dir, [1, -2, 3])
        """
        cmds.setAttr(f"{self.name}.targetDirectory[{target_dir.index}].childIndices",
                     child_indices,
                     type="Int32Array")
        
    def get_target_dir_full_path(self, target_dir: TargetDirectory)-> str:
        """
        Returns the full path of the specified target directory.
        Parameters:
            target_dir (TargetDirectory): The TargetDirectory object to get the full path for.
        Returns:
            str: The full path of the target directory.
        Example:
            >>> blendshape = Blendshape("myBlendshape")
            >>> target_dir = blendshape.get_target_dir_by_index(2)
            >>> full_path = blendshape.get_target_dir_full_path(target_dir)
            >>> print(full_path)
            Root|MyGroup|SubGroup
        """
        path_parts = []
        current_dir = target_dir
        while current_dir is not None:
            path_parts.append(current_dir.name)
            current_dir = self.get_target_dir_parent(current_dir)
        path_parts.reverse()
        full_path = "|".join(path_parts)
        return full_path

    def get_target_dir_hierarchy_level(self, target_dir: TargetDirectory)-> int:
        """
        Returns the hierarchy level of the specified target directory.
        Parameters:
            target_dir (TargetDirectory): The TargetDirectory object to get the hierarchy level for.
        Returns:
            int: The hierarchy level of the target directory.
        Example:
            >>> blendshape = Blendshape("myBlendshape")
            >>> target_dir = blendshape.get_target_dir_by_index(2)
            >>> level = blendshape.get_target_dir_hierarchy_level(target_dir)
            >>> print(level)
            2
        """
        level = 0
        current_dir = target_dir
        while current_dir is not None:
            level += 1
            current_dir = self.get_target_dir_parent(current_dir)
        return level - 1  # subtracting 1 to get the correct level
    
    def get_target_dir_child_weights(self, target_dir: TargetDirectory)-> list:
        """
        Returns a list of Weight objects representing the child weights
        of the specified target directory.
        Parameters:
            target_dir (TargetDirectory): The TargetDirectory object to get the child weights for.
        Returns:
            list: A list of Weight objects representing the child weights.
        Example:
            >>> blendshape = Blendshape("myBlendshape")
            >>> target_dir = blendshape.get_target_dir_by_index(2)
            >>> child_weights = blendshape.get_target_dir_child_weights(target_dir)
            >>> for weight in child_weights:
            ...     print(f"Child Weight Name: {weight.name}, Weight ID: {weight.id}")
            Child Weight Name: Smile, Weight ID: 0
            Child Weight Name: Frown, Weight ID: 1
        """
        child_weights = []
        child_indices = self.get_target_dir_child_indices(target_dir)
        for child_index in child_indices:
            if child_index >= 0:
                weight = self.get_weight_by_id(child_index)
                if weight is not None:
                    child_weights.append(weight)
        return child_weights
    
    def get_target_dir_child_target_dirs(self, target_dir: TargetDirectory)-> list:
        """
        Returns a list of TargetDirectory objects representing the child
        target directories of the specified target directory.
        Parameters:
            target_dir (TargetDirectory): The TargetDirectory object to get the child target directories for.
        Returns:
            list: A list of TargetDirectory objects representing the child target directories.
        Example:
            >>> blendshape = Blendshape("myBlendshape")
            >>> target_dir = blendshape.get_target_dir_by_index(2)
            >>> child_target_dirs = blendshape.get_target_dir_child_target_dirs(target_dir)
            >>> for dir in child_target_dirs:
            ...     print(f"Child Target Directory Name: {dir.name}, Directory ID: {dir.index}")
            Child Target Directory Name: SubGroup, Directory ID: 3
        """
        child_target_dirs = []
        child_indices = self.get_target_dir_child_indices(target_dir)
        for child_index in child_indices:
            if child_index < 0:
                dir_index = -child_index
                target_directory = self.get_target_dir_by_index(dir_index)
                if target_directory is not None:
                    child_target_dirs.append(target_directory)
        return child_target_dirs
    
    # ----------------------------------------------------------------
    # Weights methods
    # ------------------------------------------------------------------

    def get_weights(self):
        """
        Returns a list of weights in the blendShape node.
        Each weight is represented as a Weight object with a name and an ID.
        :Returns: A list of Weight objects.
        :Example:
            >>> blendshape = Blendshape.("myBlendshape")
            >>> weights = blendshape.get_weights()
            >>> for weight in weights:
            ...     print(f"Weight Name: {weight.name}, Weight ID: {weight.id}")
            Weight Name: Smile, Weight ID: 0
            Weight Name: Frown, Weight ID: 1
            Weight Name: Blink, Weight ID: 2
        """
        aliases = cmds.aliasAttr(self.name, q=True) or []
        if not aliases:
            return set()

        # Parse all alias pairs into {weight_id: name} in one pass
        id_to_name = {}
        for i in range(0, len(aliases), 2):
            name = aliases[i]
            weight_id = int(re.search(r'\d+', aliases[i + 1]).group())
            id_to_name[weight_id] = name

        # Resolve the inputTarget[0].inputTargetGroup plug ONCE via the API,
        # then collect all target-item logical indices per weight in a single
        # traversal instead of re-resolving the plug chain per weight.
        input_target_plug = mayaUtils.get_plug(self.name, "inputTarget")
        target_plug = input_target_plug.elementByLogicalIndex(0)
        target_group_plug = target_plug.child(0)  # .inputTargetGroup

        # Build a map of weight_id -> [target_item logical indices]
        target_items_map = {}
        for i in range(target_group_plug.numElements()):
            group_element = target_group_plug.elementByPhysicalIndex(i)
            wid = group_element.logicalIndex()
            if wid not in id_to_name:
                continue  # skip groups that have no alias (shouldn't happen normally)
            target_item_plug = group_element.child(0)  # .inputTargetItem
            indices = []
            for j in range(target_item_plug.numElements()):
                indices.append(target_item_plug.elementByPhysicalIndex(j).logicalIndex())
            target_items_map[wid] = indices[::-1]  # reversed to have 6000 first

        # Assemble Weight objects
        weights = set()
        for weight_id, name in id_to_name.items():
            weights.add(Weight(name=name,
                               id=weight_id,
                               target_items=target_items_map.get(weight_id, []),
                               blend_shape=self.name))
        return weights

    def get_highest_weight_id(self) -> int:
        """
        Returns the highest weight ID in the blendshape node.
        Returns:
            int: The highest weight ID, or None if there are no weights.
        Example:
            >>> blendshape = Blendshape("myBlendshape")
            >>> highest_id = blendshape.get_highest_weight_id()
            >>> print(highest_id)
            2
        """
        weights = self.get_weights()
        if not weights:
            return -1
        return max(weight.id for weight in weights)

    def get_weight_by_id(self, weight_id:int)-> Weight or None: # type: ignore
        """
        Returns the Weight object for the given weight ID.
        Parameters:
            weight_id (int): The ID of the weight.
        Returns:
            Weight: The Weight object with the specified ID, or None if not found.
        Example:
            >>> blendshape = Blendshape("myBlendshape")
            >>> weight = blendshape.get_weight_by_id(0)
            >>> print(weight)
            Weight: (name: 'Smile' id: 0)
        """
        weights = self.get_weights()
        if weights:
            for weight in weights:
                if weight.id == weight_id:
                    return weight
        return None

    def get_weight_by_name(self, name):
        """
        Returns the Weight object for the given weight name.
        Parameters:
            name (str): The name of the weight.
        Returns:
            Weight: The Weight object with the specified name,
            or None if not found.
        Example:
            >>> blendshape = Blendshape("myBlendshape")
            >>> weight = blendshape.get_weight_by_name("Smile")
            >>> print(weight)
            Weight: (name: 'Smile' id: 0)
        """
        weights = self.get_weights()
        if weights:
            for weight in weights:
                if weight == name:
                    return weight
        return None

    def rename_weight(self , old_name: str , new_name: str):
        """
        Rename weight in the blendshape node.
        Parameters:
            old_name (str): The current name of the weight.
            new_name (str): The new name for the weight.
        Example:
            >>> blendshape = Blendshape("myBlendshape")
            >>> blendshape.rename_weight("Smile", "Happy")
        """
        if new_name in self.get_weights():
            # print(f"Weight name '{new_name}' already exists in blendshape '{self.name}'.")
            return
        weight = self.get_weight_by_name(old_name)
        if weight is not None:
            cmds.aliasAttr(new_name, "{0}.w[{1}]".format(self.name, weight.id))


    def get_weight_driver(self, weight: Weight)-> str or None: # type: ignore
        """
        Returns the driver of the specified weight.
        Parameters:
            weight (Weight): The weight to get the driver for.
        Returns:
            str or None: The name of the driver node, or None if not connected.
        Example:
            >>> blendshape = Blendshape("myBlendshape")
            >>> weight = blendshape.get_weight_by_name("Smile")
            >>> driver = blendshape.get_weight_driver(weight)
            >>> print(driver)
            controller1.rotateX
        """
        connections = cmds.listConnections(f"{self.name}.w[{weight.id}]",
                                           source=True,
                                           destination=False) or []
        if connections:
            return connections[0]
        else:
            return None

    def get_weight_value(self, weight: Weight)-> float:
        """
        Returns the current value of the specified weight.
        Parameters:
            weight (Weight): The weight to get the value for.
        Returns:
            float: The current value of the weight.
        Example:
            >>> blendshape = Blendshape("myBlendshape")
            >>> weight = blendshape.get_weight_by_name("Smile")
            >>> value = blendshape.get_weight_value(weight)
            >>> print(value)
            0.5
        """
        return cmds.getAttr(f"{self.name}.w[{weight.id}]")

    def set_weight_value(self, weight: Weight, value: float):
        """
        Sets the value of the specified weight.
        Parameters:
            weight (Weight): The weight to set the value for.
            value (float): The value to set the weight to.
        Example:
            >>> blendshape = Blendshape("myBlendshape")
            >>> weight = blendshape.get_weight_by_name("Smile")
            >>> blendshape.set_weight_value(weight, 0.5)
        """
        cmds.setAttr(f"{self.name}.w[{weight.id}]", value)

    def get_weight_parent_directory(self, weight: Weight)-> TargetDirectory or None: # type: ignore
        """
        Returns the parent TargetDirectory of the specified weight.
        Parameters:
            weight (Weight): The weight to get the parent directory for.
        Returns:
            TargetDirectory or None: The parent TargetDirectory object,
            or None if not found.
        Example:
            >>> blendshape = Blendshape("myBlendshape")
            >>> weight = blendshape.get_weight_by_name("Smile")
            >>> parent_dir = blendshape.get_weight_parent_directory(weight)
            >>> print(parent_dir)
            TargetDirectory: (name: MyGroup id: 2 blendshape: myBlendshape)
        """
        parent_dir_indices = cmds.getAttr(f"{self.name}.parentDirectory", mi=True) or []
        weight_id = weight.id
        if weight_id in parent_dir_indices:
            parent_index = cmds.getAttr(f"{self}.parentDirectory[{weight_id}]")
            return self.get_target_dir_by_index(parent_index)
        return None
    
    def set_weight_parent_directory(self, weight: Weight, target_dir: TargetDirectory):
        """
        Sets the parent TargetDirectory of the specified weight.
        Parameters:
            weight (Weight): The weight to set the parent directory for.
            target_dir (TargetDirectory): The TargetDirectory to set as the parent.
        Example:
            >>> blendshape = Blendshape("myBlendshape")
            >>> weight = blendshape.get_weight_by_name("Smile")
            >>> target_dir = blendshape.get_target_dirs()[0]
            >>> blendshape.set_weight_parent_directory(weight, target_dir)
        """
        # first, we need to remove the weight from its current parent directory
        current_parent = self.get_weight_parent_directory(weight)
        if current_parent is not None:
            current_parent_child_indices = self.get_target_dir_child_indices(current_parent)
            if weight.id in current_parent_child_indices:
                current_parent_child_indices.remove(weight.id)
                self.set_target_dir_child_indices(current_parent, current_parent_child_indices)
        # now, we can add the weight to the new parent directory
        new_parent_child_indices = self.get_target_dir_child_indices(target_dir)
        # print("New parent indices before adding:", new_parent_child_indices)
        if weight.id not in new_parent_child_indices:
            new_parent_child_indices.append(weight.id)
            self.set_target_dir_child_indices(target_dir, new_parent_child_indices)
        # finally, we set the parent directory attribute on the weight
        cmds.setAttr(f"{self.name}.parentDirectory[{weight.id}]", target_dir.index)

    # ------------------------------------------------------------------
    # Target methods
    # ------------------------------------------------------------------
    def get_delta_at_weight_value(self, weight: Weight, target_value: int)-> np.ndarray:
        """
        Returns the delta values for the specified weight and target value as a numpy array.
        This includes inbetween targets, e.g., getting the delta
        if there is an inbetween target at 5500 and you request the delta at 5750.
        It will linearly interpolate the delta values between 5500 and 6000.
        Parameters:
            weight (Weight): The weight to get the delta values for.
            target_value (int): The target value for which to retrieve the delta values.
        Returns:
            numpy.ndarray: A (N, 3) array of doubles where each row is [dx, dy, dz].
        Example:
            >>> blendshape = Blendshape("myBlendshape")
            >>> weight = blendshape.get_weight_by_name("Smile")
            >>> delta = blendshape.get_delta_at_weight_value(weight, 6000)
            >>> print(delta)
            [[0.1, 0.0, 0.0],
             [0.1, 0.0, 0.0],
             [0.1, 0.0, 0.0],
             ...]
        """
        # let's find the two closest target items to the requested target value
        if target_value not in weight.target_items:
            # find the two closest target items
            # we need to add 5000 to the list to avoid errors
            all_target_items = weight.target_items + [target_value, 5000] 
            all_target_items = sorted(all_target_items)
            target_index = all_target_items.index(target_value)
            if target_index == 0 or target_index == len(all_target_items) - 1:
                raise ValueError(f"Target value {target_value} is out of range for weight '{weight}' "
                                 f"with target items {weight.target_items}.")
            lower_target = all_target_items[target_index - 1]
            upper_target = all_target_items[target_index + 1]
            # linear interpolation factor
            t = (target_value - lower_target) / (upper_target - lower_target)
            if lower_target == 5000:
                lower_delta = np.zeros((self.get_base_vertex_count(), 3), dtype=np.float64)
            else:
                lower_delta = self.get_target_delta(weight, lower_target)
            if upper_target == 5000:
                upper_delta = np.zeros((self.get_base_vertex_count(), 3), dtype=np.float64)
            else:
                upper_delta = self.get_target_delta(weight, upper_target)
            return lower_delta + (upper_delta - lower_delta) * t
        else:
            return self.get_target_delta(weight, target_value)

    def add_target(self,
                   weight_name: str,
                   target_object: str = None,
                   disconnect_target: bool = True,
                   parent_directory: TargetDirectory =None)-> Weight:
        """""
        Adds a new target to the blendShape node.
        Parameters:
        weight_name (str): The name of the target to be added.
        target_object (str): The mesh object to be used as the target. If None, the target
        will be the base mesh.
        disconnect_target (bool): Whether to disconnect the target mesh from the blendshape.
        parent_directory (TargetDirectory): The parent target directory.
        Returns:
        Weight: The Weight object of the added target.
        Example:
        >>> blendshape = Blendshape("myBlendshape")
        >>> new_target_weight = blendshape.add_target("NewTarget", "pSphere1")
        >>> print(new_target_weight)
        Weight: (name: 'NewTarget' id: 3)
        """
        target_id = None
        reset_target = False
        if parent_directory is None:
            # getting the default directory
            parent_directory = self.get_target_dir_by_index(0)
        if target_object is None: # this means we are adding an empty target
            target_object = self.base
            reset_target = True
            disconnect_target = True # we need to disconnect the base mesh from the target
        if weight_name in self.get_weights():
            raise ValueError(f"Weight '{weight_name}' already exists in blendshape '{self.name}'.")
        target_id = self.get_highest_weight_id() +1
        cmds.blendShape(self.name ,
                        edit=True,
                        t=(self.base, target_id, target_object, 1.0),
                        tc=False,
                        ts=False)
        # making sure the weight_name is the same as the weight name
        current_weight_name = self.get_weight_by_id(target_id)
        if weight_name != current_weight_name:
                self.rename_weight(current_weight_name, weight_name)

        if disconnect_target:
            target_geom_plug = self.get_target_input_geom_plug(target_id).name()
            if cmds.isConnected(f"{target_object}.worldMesh[0]", target_geom_plug):
                cmds.disconnectAttr(f"{target_object}.worldMesh[0]", target_geom_plug)
        w = self.get_weight_by_id(target_id)
        if parent_directory != 0: # this is the default directory
            self.set_weight_parent_directory(w, parent_directory)
        if reset_target:
            self.reset_target(w)
        return w

    def add_inbetween_target(self,
                             weight: Weight,
                             target_item_index: int,
                             target_name: str = None,
                             target_object: str = None,
                             disconnect_target: bool = True):
        """
        Adds an inbetween target to the specified weight in the blendshape node.
        Parameters:
            weight (Weight): The weight to which the inbetween target
                will be added.
            target_item_index (int): The index of the inbetween target
                (e.g., 5500 for halfway between 5000 and 6000).
            target_object (str): The mesh object to be used as the inbetween
                target. If None, the target will be the base mesh.
            disconnect_target (bool): Whether to disconnect the target mesh
                from the blendshape.
        Returns:
            Weight: The Weight object of the weight with the added inbetween target.
        Example:
            >>> blendshape = Blendshape("myBlendshape")
            >>> weight = blendshape.get_weight_by_name("Smile")
            >>> updated_weight = blendshape.add_inbetween_target(weight, 5500, "pSphere1")
            >>> print(updated_weight)
            Weight: (name: 'Smile' id: 0 target_items: [5500, 6000])
        """
        if weight not in self.get_weights():
            raise ValueError(f"Weight '{weight}' does not exist in blendshape '{self.name}'.")
        if target_item_index in weight.target_items:
            raise ValueError(f"Target item index {target_item_index} "
                             f"already exists for weight '{weight}'.")
        if target_item_index < 5000 or target_item_index > 6000:
            raise ValueError(f"Target item index {target_item_index} must be between 5000 and 6000.")
        target_id = weight.id
        interpolated_delta = None
        inbetween_value = float(target_item_index-5000)/1000.0
        if target_object is None: 
            target_object = self.base
            disconnect_target = True # we need to disconnect the base mesh from the target
            interpolated_delta = self.get_delta_at_weight_value(self.get_weight_by_id(target_id),
                                                                target_item_index)
        if target_name is None:
            target_value = int((target_item_index-5000)/10)
            target_name = f"{weight}{target_value}"
        # if the target is the base mesh we need to calculate and set the interpolated
        # delta from the two closest target items
        #blendShape -e -ib -tc on -ibt relative -t |pSphere2|pSphereShape2 0 pSphere3 0.75  blendShape2;
        cmds.blendShape(self.name,
                        edit=True,
                        ib=True,
                        tc=True,
                        ibt='relative',
                        t=(self.base, target_id, target_object, inbetween_value))

        if disconnect_target:
            target_geom_plug = self.get_target_input_geom_plug(target_id, target_item_index).name()
            if cmds.isConnected(f"{target_object}.worldMesh[0]", target_geom_plug):
                cmds.disconnectAttr(f"{target_object}.worldMesh[0]", target_geom_plug)
            if interpolated_delta is not None:
                w = self.get_weight_by_id(target_id)
                self.set_target_delta(weight=w,
                                      target_value=target_item_index,
                                      delta=interpolated_delta,
                                      use_api=False
                                      )
        # renaming the inbetween target
        inbetween_name_plug = self.get_inbetween_target_name_plug(target_id, target_item_index)
        if inbetween_name_plug is not None:
            cmds.setAttr(inbetween_name_plug.name(), target_name, type="string")
        return self.get_weight_by_id(target_id)
    
    def update_target(self,
                      weight: Weight,
                      new_mesh: str,
                      target_value: int = None):
        """
        Updates the target mesh for the specified weight and target value.
        """
        if target_value is None:
            target_value = weight.target_items[0] if weight.target_items else 6000
        weight_id = weight.id
        target_item_plug = f"{self.get_target_group_plug(weight_id, target_value).name()}.inputGeomTarget"  
        if target_item_plug is not None:
            cmds.connectAttr(f"{new_mesh}.worldMesh[0]", target_item_plug, f=True)
            cmds.disconnectAttr(f"{new_mesh}.worldMesh[0]", target_item_plug)

    def connect_target(self, weight: Weight, mesh:str, target_value:int = None):
        """
        Connects a target mesh to the blendshape node for the specified weight
        and target value.
        Parameters:
            weight (Weight): The weight to connect the target mesh to.
            
            mesh (str): The mesh object to connect as a target.
            
            target_value (int): The target value for the blendshape.
                Default is 6000.
        Returns:
            True if the target was successfully connected, False otherwise.
        """
        if target_value is None:
            target_value = weight.target_items[0] if weight.target_items else 6000
        weight_id = weight.id
        if target_value not in weight.target_items:
            return False
        mesh_shape = cmds.listRelatives(mesh, s=True)
        mesh_output = "{}.worldMesh[0]".format(mesh_shape[0])
        blend_input = self.get_target_group_plug(weight_id, target_value).name
        if not cmds.isConnected (mesh_output, blend_input):
            cmds.connectAttr (mesh_output, blend_input , f=True)
            return True
        return False

    def remove_target(self, weight: Weight, target_value = 6000):
        """
        Removes the specified target from the blendshape node.
        Parameters:
            weight (Weight): The weight to remove the target from.
            target_value (int): The target value for the blendshape.
            Default is 6000.
        """
        weight_id = weight.id
        # remove the alias if the target values is 6000
        if target_value == 6000:
            cmds.aliasAttr(f"{self.name}.{weight}", remove=True)
            target_group_plug = self.get_target_group_plug(weight_id, target_value)
            # print("THE TARGET PLUG NAME IS:")
            # print(target_group_plug.name())
            array_plug = target_group_plug.array()   # → inputTargetItem (the whole array)
            parent_plug = array_plug.parent()
            # print("THE PARENT PLUG NAME IS:")
            # print(parent_plug.name())
            cmds.removeMultiInstance(parent_plug.name(), b=True)  # b=True means break connections
            cmds.removeMultiInstance('{0}.weight[{1}]'.format(self.name, weight_id), b=True)
        else:
            target_item_plug = self.get_target_group_plug(weight_id, target_value)
            cmds.removeMultiInstance(target_item_plug.name(), b=True)  # b=True means break connections
            # we need to remove the inbetween info as well

        
        return False

    def get_target_components(self, weight: Weight, target_value: int = 6000):
        """
        Returns the list of component indices for the specified target value
        of the given weight.
        Parameters:
            weight (Weight): The weight to get the target components for.
            
            target_value (int): The target value for which to retrieve
                the component indices. Default is 6000.
        Returns:
            numpy.ndarray: A list of component indices associated with
                the specified target value of the given weight.
        Example:
            >>> blendshape = Blendshape("myBlendshape")
            >>> weight = blendshape.get_weight_by_name("Smile")
            >>> component_indices = blendshape.get_target_components(weight, 6000)
            >>> print(component_indices)
            [0, 1, 2, 3, 4, ...]
        """
        target_item_plug = self.get_target_group_plug(weight.id, target_value).name()
        # maybe there is a better way to get the plug from its name
        sel_list = om2.MSelectionList()
        sel_list.add(target_item_plug)
        target_item_plug = sel_list.getPlug(0)
        # Find inputComponentsTarget
        input_components_plug = None
        for i in range(target_item_plug.numChildren()):
            child = target_item_plug.child(i)
            if child.name().endswith("inputComponentsTarget"):
                input_components_plug = child
                break

        if input_components_plug is None:
            raise RuntimeError("Could not find inputComponentsTarget plug")
        # Collect component indices from array elements
        component_indices = [0]
        component_list = om2.MFnComponentListData(input_components_plug.asMObject())
        if component_list.length() > 0:
            fn_comp = om2.MFnSingleIndexedComponent(component_list.get(0))
            component_indices = fn_comp.getElements()
        np_array = np.array(component_indices, dtype=np.int32)
        return np_array

    def get_target_points(self, weight: Weight, target_value: int = 6000):
        """
        Returns the list of points for the specified target value
        of the given weight.
        Parameters:
            weight (Weight): The weight to get the target points for.
        
            target_value (int): The target value for which to retrieve
                the points. Default is 6000.
        Returns:
            numpy.ndarray: A list of points associated with the specified target
                value of the given weight.
        Example:
            >>> blendshape = Blendshape("myBlendshape")
            >>> weight = blendshape.get_weight_by_name("Smile")
            >>> points = blendshape.get_target_points(weight, 6000)
            >>> print(points)
            [(1.0, 2.0, 3.0), (4.0, 5.0, 6.0), ...]
        """
        target_item_plug_name = self.get_target_group_plug(weight.id, target_value).name()
        # maybe there is a better way to get the plug from its name
                # Convert OpenMaya 2 plug to OpenMaya 1 plug using MSelectionList
        #plug_name = input_points_plug.name()
        sel_list = om.MSelectionList()
        sel_list.add(target_item_plug_name)
        target_item_plug = om.MPlug()
        sel_list.getPlug(0, target_item_plug)
        # we need to get the plug from its name and convert it into a Maya API 1 plug
        # Find inputPointsTarget
        input_points_plug = None
        for i in range(target_item_plug.numChildren()):
            child = target_item_plug.child(i)
            if child.name().endswith("inputPointsTarget"):
                input_points_plug = child
                break
        # points = cmds.getAttr(input_points_plug.name()) or []
        # get the mobject of this plug
        if input_points_plug is None:
            raise RuntimeError("Could not find inputPointsTarget plug")

        # Get the MObject value from the plug, not the plug itself
        points_obj = input_points_plug.asMObject()
        points_data = om.MFnPointArrayData(points_obj)
        points_marray = points_data.array()
        np_array = mayaUtils.m_points_to_numpy(points_marray)
        # we need to remove the 4th row because it is always 1.0
        np_array = np_array[:, :3]

        return np_array

    def set_target_points(self,
                          weight: Weight,
                          points:np.ndarray,
                          target_value: int = 6000,
                          use_api:bool = False):
        """
        Sets the points for the specified weight in the blendshape node.
        ************************ WARNING *******************************
                THIS METHOD IS NOT UNDOABLE IF use_api IS True
        ****************************************************************
        Parameters:
            points (numpy.ndarray): A (N, 3) array of points to set.
                target_value (int): The target value for
                which to set the points.Default is 6000.
                use_api (bool): Whether to use the Maya API for setting points.
                Default is False.
        Example:
            >>> blendshape = Blendshape("myBlendshape")
            >>> weight = blendshape.get_weight_by_name("Smile")
            >>> points = np.array([(1.0, 2.0, 3.0),
                                   (4.0, 5.0, 6.0),
                                   (7.0, 8.0, 9.0)])
            >>> blendshape.set_target_points(weight, points)
        """
        # we need to add the fourrth row with 1.0
        ones = np.ones((points.shape[0], 1), dtype=points.dtype)
        points = np.hstack([points, ones])  # shape (N, 4)
        target_item_plug = self.get_target_group_plug(weight.id, target_value)
        # Find inputPointsTarget plugs
        input_points_plug = None
        for i in range(target_item_plug.numChildren()):
            child = target_item_plug.child(i)
            if child.name().endswith("inputPointsTarget"):
                input_points_plug = child

        if input_points_plug is None:
            raise RuntimeError("Could not find required plugs")
        # we will try to use a getAttr to keep the undo stack
        if use_api:
            m_point_array = mayaUtils.numpy_to_m_points(points)
            # # # Create MFnPointArrayData for points
            point_array_fn = om.MFnPointArrayData()
            point_array_fn.create()
            point_array_fn.set(m_point_array)
            input_points_plug.setMObject(point_array_fn.object())
        else:
            cmds.setAttr(input_points_plug.name(), len(points), *points.tolist(), type="pointArray")


    def set_target_components(self,
                              weight: Weight,
                              components: np.ndarray,
                              target_value: int = 6000,
                              use_api: bool = False):
        """
        Sets the component indices for the specified
        weight in the blendshape node.
        Parameters:
            components (numpy.ndarray): A list or array of component indices
                                        to set.
            target_value (int): The target value for which to set
                                the component indices. Default is 6000.
            use_api (bool): Whether to use the Maya API for setting components.
                            Default is False (undoable cmds path).
        Example:
            >>> blendshape = Blendshape("myBlendshape")
            >>> weight = blendshape.get_weight_by_name("Smile")
            >>> components = np.array([0, 1, 2, 3, 4])
            >>> blendshape.set_target_components(weight, components)
        """
        target_item_plug = self.get_target_group_plug(weight.id, target_value)

        # Find inputComponentsTarget and inputPointsTarget plugs
        input_components_plug = None
        for i in range(target_item_plug.numChildren()):
            child = target_item_plug.child(i)
            if child.name().endswith("inputComponentsTarget"):
                input_components_plug = child

        if input_components_plug is None:
            raise RuntimeError("Could not find inputComponentsTarget plug")

        comp_fn = om2.MFnSingleIndexedComponent()
        comp_obj = comp_fn.create(om2.MFn.kMeshVertComponent)
        comp_fn.addElements(components)
        comp_data = om2.MFnComponentListData()
        comp_data.create()
        comp_data.add(comp_obj)

        if use_api:
            # Set plugs with new data using API (faster, not undoable).
            sel_list = om2.MSelectionList()
            sel_list.add(input_components_plug.name())
            input_components_plug = sel_list.getPlug(0)
            input_components_plug.setMObject(comp_data.object())
            return

        # Undoable path using cmds.setAttr with componentList payload.
        component_tokens = [f"vtx[{int(index)}]" for index in np.asarray(components).flatten().tolist()]
        cmds.setAttr(input_components_plug.name(), len(component_tokens), *component_tokens, type="componentList")

    def get_target_delta(self, weight: Weight, target_value: int = 6000)-> np.ndarray:
        """
        Returns a numpy array of the same length as the base mesh vertices,
        where each entry corresponds to the delta point for that vertex.
        Parameters:
            weight (Weight): The weight to get the target delta for.
            use_api (bool): Whether to use the Maya API for retrieving points.
                    Default is False.
            target_value (int): The target value for which to retrieve
                                the delta points. Default is 6000.
        Returns:
            numpy.ndarray: A (N, 4) array of delta points where N
                           is the number of vertices in the base mesh.
        """
        # time_start = time.time()
        points = self.get_target_points(weight, target_value)
        components = self.get_target_components(weight, target_value)
        base_vertex_count = self.get_base_vertex_count()
        delta_array = np.zeros((base_vertex_count, 3), dtype=np.float64)
        # place the points at the indices specified in components
        delta_array[components] = points

        # time_end = time.time()
        # print(f"get_target_delta took {time_end - time_start} seconds")
        
        return delta_array

    def set_target_delta (self,
                          weight: Weight,
                          delta:np.ndarray,
                          use_api:bool = False,
                          target_value: int = 6000):
        """
        Sets the delta points for the specified weight in the blendshape node.
        ************************ WARNING *******************************
                THIS METHOD IS NOT UNDOABLE IF use_api IS True
        ****************************************************************
        Parameters:
            delta (numpy.ndarray): A (N, 3) array of delta points to set.
            use_api (bool): Whether to use the Maya API for setting points.
            Default is False.
            target_value (int): The target value for which to set the delta
            points. Default is 6000.
        Example:
            >>> blendshape = Blendshape("myBlendshape")
            >>> weight = blendshape.get_weight_by_name("Smile")
            >>> delta = [(1.0, 2.0, 3.0), (4.0, 5.0, 6.0), (7.0, 8.0, 9.0)]
            >>> blendshape.set_target_delta(weight, delta)
        """
        # generate components and points from delta
        if delta.ndim != 2 or delta.shape[1] != 3:
            raise ValueError("Delta must be a 2D numpy array with shape (N, 3)")
        # get the indices where the values on delta are not [0.0, 0.0, 0.0]
        components = np.where(~np.all(delta == [0.0, 0.0, 0.0], axis=1))[0]
        points = delta[components]
        # now we have to make sure that the index 0 is in components and 
        # we need to add a point [0.0, 0.0, 0.0] at the start of points
        if 0 not in components:
            components = np.insert(components, 0, 0)
            points = np.vstack([np.array([[0.0, 0.0, 0.0]]), points])
        self.set_target_points(weight, points, target_value, use_api)
        self.set_target_components(weight, components, target_value, use_api=use_api)
        return


    def get_delta_from_mesh(self, mesh_name:str)-> np.ndarray:
        """
        Returns a numpy array of the same length as the base mesh vertices,
        where each entry corresponds to the delta point for that vertex.
        Parameters:
            mesh_name (str): The name of the mesh to get the delta from.
        Returns:
            numpy.ndarray: A (N, 4) array of delta points where N is the number
            of vertices in the base mesh.
        """
        base_points = self.get_base_deformed_points()
        #self.print_numpy_array(base_points, name="Base deformed Points")
        mesh_points = mayaUtils.get_mesh_raw_points(mesh_name)
        
        if base_points.shape != mesh_points.shape:
            raise ValueError("Base mesh and target mesh must have the same"
                             " number of vertices")
        #self.print_numpy_array(mesh_points, name=f"Mesh '{mesh_name}' Points")
        delta = mesh_points - base_points
        #self.print_numpy_array(delta, name=f"Delta from mesh '{mesh_name}'")
        return delta
    
    def reset_target(self, weight: Weight, target_value: int = 6000, use_api: bool = False):
        """
        Resets the target points and components for the specified weight in
        the blendshape node.
        Parameters:
            weight (Weight): The weight to reset the target for.
            target_value (int): The target value for which to reset the target.
            Default is 6000.
        """
        delta =  np.zeros((0, 3))
        self.set_target_delta(weight=weight,
                                delta=delta,
                                target_value=target_value,
                                use_api=use_api)


    def get_weight_map_values(self, weight: Weight)-> list:
        """
        Returns a weight map for the specified weight, where each entry corresponds
        to the weight value for that vertex.
        Parameters:
            weight (Weight): The weight to get the weight map for.
        Returns:
            list: A list of weight values where each entry corresponds to a vertex in the base mesh.
        """
        vcount = self.get_base_vertex_count()
        weightAttr = f'{self.name}.inputTarget[0].inputTargetGroup[{weight.id}].targetWeights[0:{vcount-1}]'
        return cmds.getAttr(weightAttr) or [1.0]*vcount

    def set_weight_map_values(self, weight: Weight, values: list):
        """
        Sets the weight map for the specified weight, where each entry corresponds
        to the weight value for that vertex.
        Parameters:
            weight (Weight): The weight to set the weight map for.
            values (list): A list of weight values where each entry corresponds to a vertex in the base mesh.
        """
        vcount = self.get_base_vertex_count()
        if len(values) != vcount:
            raise ValueError(f"Length of values array must be equal to the number of vertices in the base mesh ({vcount}).")
        weightAttr = f'{self.name}.inputTarget[0].inputTargetGroup[{weight.id}].targetWeights[0:{vcount-1}]'
        cmds.setAttr(weightAttr, *values, size=len(values))

    # ------------------------------------------------------------------
    # Export / Import methods
    # ------------------------------------------------------------------

    def export_targets(self, path):
        """
        Export the blendshape targets as numpy compressed bin files to the path directory. 
        Parameters:
            path (str): The directory path where the target files will be saved.
        """
        if not os.path.exists(path):
            os.makedirs(path)
        export_data = {}
        for weight in self.get_weights():
            target_values = self.get_target_group_logical_indices(weight.id)
            for target_value in target_values:
                points = self.get_target_points(weight, target_value)
                components = self.get_target_components(weight, target_value)
                key = f"{weight}_{target_value}"
                export_data[f"{key}_points"] = points
                export_data[f"{key}_components"] = components
        file_path = os.path.join(path, f"{self.name}_targets.npz")
        np.savez_compressed(file_path, **export_data)

    def import_targets(self, file_path):
        """
        Import the blendshape targets from numpy compressed bin files in the path directory. 
        Parameters:
            path (str): The directory path where the target files are located.
        """
        if not os.path.exists(file_path):
            raise ValueError(f"Path '{file_path}' does not exist.")
        # separate the filename from the path
        if os.path.isfile(file_path):
            data = np.load(file_path)
            weights = dict()
            for key in data.files:
                if key.endswith("_points"):
                    # using rsplit so the extra underscores in the weight name are preserved
                    weight_name, target_value_str = key[:-7].rsplit('_', 1)
                    target_value = int(target_value_str)
                    weight_list = weights.get(weight_name, [])
                    weight_list.append(target_value)
                    weights[weight_name] = sorted(weight_list)[::-1]

            for weight_name, target_values in weights.items():
                weight = self.get_weight_by_name(weight_name)
                for target_value in target_values:
                    if weight is None and target_value == 6000:
                        weight = self.add_target(weight_name=weight_name)
                    elif weight and target_value not in weight.target_items:
                        weight = self.add_inbetween_target(weight=weight, target_item_index=target_value)
                    points = data[f"{weight_name}_{target_value}_points"]
                    components = data[f"{weight_name}_{target_value}_components"]
                    print(f"Importing target '{weight}' "
                          f"with value {target_value}, {len(points)} points, {len(components)} components")
                    self.set_target_points(weight=weight,
                                           points=points,
                                           target_value=target_value,
                                           use_api=True)
                    self.set_target_components(weight=weight,
                                               components=components,
                                               target_value=target_value,
                                               use_api=True)
            return