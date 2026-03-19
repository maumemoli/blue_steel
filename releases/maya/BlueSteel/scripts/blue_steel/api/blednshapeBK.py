from maya import cmds
import collections
from collections import defaultdict
import maya.api.OpenMaya as om
from .mesh import Mesh
from dataclasses import dataclass, field
import re

@dataclass
class Weight:
    """
    A simple data class to represent a weight with a name and an ID.

    Attributes:
        name (str): The name of the weight.
        id (int): The unique identifier for the weight.

    Example:
        >>> w = Weight(name="Spine", id=3)
        >>> print(w.name)
        Spine
        >>> print(w.id)
        3
    """
    name: str
    id: int

    def __str__(self) -> str:
        """
        Returns the name of the weight as its string representation.

        Returns:
            str: The name of the weight.
        """
        return self.name

    def __repr__(self) -> str:
        """
        Returns a string representation of the Weight object.
        This includes the name and ID of the weight.
        :return: A string representation of the Weight object.
        Example:
        >>> w = Weight(name="Spine", id=3)
        """
        return f"Weight: (name: '{self.name}' id: {self.id})"

    def __eq__(self, other):
        """
        Checks equality between this Weight object and another object.
        If the other object is a Weight, it compares their names.
        If the other object is a string, it compares the name of this Weight with that string.
        :param other: The object to compare with.
        """
        if isinstance(other, Weight):
            return self.name == other.name
        if isinstance(other, str):
            return self.name == other
        return False

    def __hash__(self):
        return hash(self.name)

class Blendshape(object):
    """
    Blendshape class to handle blendshape nodes in Maya.
    """
    INPUT_TARGET = "{0}.inputTarget[0].inputTargetGroup[{1}].inputTargetItem[{2}]"
    def __init__(self, name: str):
        self.name = name
        self.base = self.get_base()
        if self.base is None:
            raise ValueError(f"Blendshape node '{self.name}' has no base mesh connected.")
        self.dependency_node = self.get_dependency_node()
        self.mfn_dependency_node = om.MFnDependencyNode(self.dependency_node)

    def __str__(self):
        return self.name

    def __repr__(self):
        return f"Blendshape: {self.name}"

    # properties
    @property
    def weights(self):
        return self.get_weights()

    @classmethod
    def create(cls, name:str, base_mesh:str):
        """
        Creates a new blendshape node with the specified name and base mesh.
        :param name: The name of the blendshape node to be created.
        :param base_mesh: The base mesh to which the blendshape will be applied.
        :return: The name of the created blendshape node.
        """
        if not cmds.objExists(base_mesh):
            raise ValueError(f"Base mesh '{base_mesh}' does not exist.")
        blendshape_node = cmds.blendShape(base_mesh, name=name, origin='world', foc=True)[0]
        return cls(blendshape_node)

    # Base geometry methods
    def get_base(self):
        '''
        Returns the input transformation node of the blendShape.
        '''
        base = cmds.blendShape(self.name, q=True, g=True) or None
        return base[0] if base else None

    def duplicate_base(self, name = None):
        '''
        Duplicates the base mesh of the blendShape node.
        :param name: The name of the new mesh. If None, it will use the base mesh name.
        :return: The name of the new mesh.
        '''
        points = self.get_base_points()
        if name is None:
            name = self.base.split('|')[-1]
        new_mesh = cmds.duplicate(self.base, name =name)
        # making sure this new mesh is equal to the base mesh
        mesh = Mesh(new_mesh[0])
        mesh.set_points(points)

        return new_mesh[0]

    # Weights methods
    def get_weights(self):
        """
        Returns a list of weights in the blendShape node.
        Each weight is represented as a Weight object with a name and an ID.
        :return: A list of Weight objects.
        """
        aliases = cmds.aliasAttr(self.name, q=True)
        if not aliases:
            return aliases

        weights = [
            Weight(name=aliases[i], id=int(re.search(r'\d+', aliases[i + 1]).group()))
            for i in range(0, len(aliases), 2)
        ]
        return weights

    def get_highest_weight_id(self):
        """
        Returns the highest weight ID in the blendshape node.
        """
        weights = self.get_weights()
        if not weights:
            return None
        return max(weight.id for weight in weights)

    def get_weight_id(self, weight_name):
        """
        Returns the weight ID from the weights list for the given weight name.
        :param weight_name: The name of the weight.
        :return: The ID of the weight or None if not found.
        """
        weights = self.get_weights()
        if weight_name in weights:
            for weight in weights:
                if weight.name == weight_name:
                    return weight.id
        return None

    def get_weight_name(self, weight_id):
        '''
        Returns the weight name for the given weight ID.
        :param weight_id: The ID of the weight.
        :return: The name of the weight or None if not found.
        '''
        weights = self.get_weights()
        if weights:
            for weight in weights:
                if weight.id == weight_id:
                    return weight.name
        return None

    # Targets methods
    def rename_weight(self , old_name: str , new_name: str):
        '''
        Rename weight in the blendshape node:
        string, string
        renameWeight('oldName', 'newName')
        '''
        if new_name in self.get_weights():
            return
        weight_id = self.get_weight_id(old_name)
        cmds.aliasAttr(new_name, "{}.w[{}]".format(self.name, weight_id))

    def add_target(self, target_name: str, target_object = None):
        """""
        Adds a new target to the blendShape node.
        :param target_name: The name of the target to be added.
        :param target_object: The mesh object to be used as the target. If None, the target will be the base mesh.
        :return: The ID of the newly added target.
        """
        if target_name in self.get_weights():
            i=1
            new_target_name = f"{target_name}{i}"
            while new_target_name in self.get_weights():
                i += 1
                new_target_name = f"{target_name}{i}"
            target_name = new_target_name
        target_id = self.get_highest_weight_id()
        if target_id is None:
            target_id = 0
        else:
            target_id += 1
        if not target_object:
            target_object = self.base
        cmds.blendShape(self.name , edit=True, t=(self.base, target_id, target_object, 1.0), tc=False, ts=False)
        # making sure the target_name is the same as the weight name
        current_weight_name = self.get_weight_name(target_id)
        if target_name != current_weight_name:
            self.rename_weight(current_weight_name, target_name)
        return target_id

    def get_inbetween_targets(self , weight_name):
        '''
        Returns the list of the inbetween values for the specified target.
        :param weight_name: The name of the weight to get the inbetween targets for.
        :return: A list of inbetween target values for the specified weight.
        '''
        weight_id = self.get_weight_id(weight_name)
        if not weight_id:
            raise ValueError(f"Weight '{weight_name}' not found in blendshape '{self.name}'.")

        target_plugs = cmds.listAttr (f"{self.name}.inputTarget[0].inputTargetGroup[{weight_id}].inputTargetItem",
                                      ca=1 ,
                                      m=1 ,
                                      st="inputTargetItem" ,lf=1)

        return [re.findall(r'\d+', x)[0] for x in target_plugs]

    def connect_target(self, weight_name: str, mesh:str,target_value = 6000):
        """
        Connects a target mesh to the blendshape node for the specified weight and target value.
        :param weight_name: The name of the weight to connect the target mesh to.
        :param mesh: The mesh object to connect as a target.
        :param target_value: The target value for the blendshape. Default is 6000.
        :return: True if the target was successfully connected, False otherwise.
        """
        weight_id = self.get_weight_id(weight_name)
        if weight_id is None:
            return False
        mesh_shape = cmds.listRelatives(mesh, s=True)
        mesh_output = "{}.worldMesh[0]".format(mesh_shape[0])
        blend_input = self.get_target_group_plug(weight_id, target_value)
        if not cmds.isConnected (mesh_output, blend_input):
            cmds.connectAttr (mesh_output, blend_input , f=True)
            return True
        return False

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
        """
        sel = om.MSelectionList()
        sel.add(self.name)
        blendshape_obj = sel.getDependNode(0)
        fn_dep = om.MFnDependencyNode(blendshape_obj)
        input_target_plug = fn_dep.findPlug("inputTarget", False)
        target_plug = input_target_plug.elementByLogicalIndex(0)
        target_group_plug = target_plug.child(0).elementByLogicalIndex(weight_id)
        target_item_plug = target_group_plug.child(0).elementByLogicalIndex(target_item_id)
        return target_item_plug

    def disconnect_target(self, weight_name, target_value = 6000):
        """
        Disconnects a target mesh from the blendshape node for the specified weight and target value.
        :param weight_name: The name of the weight to disconnect the target mesh from.
        :param target_value: The target value for the blendshape. Default is 6000.
        :return: True if the target was successfully disconnected, False otherwise.
        """
        weight_id = self.get_weight_id (weight_name)
        if weight_id is None:
            return False
        blend_input = self.get_target_group_plug (weight_id, target_value)
        connected = cmds.listConnections(blend_input, p=True)
        if not connected:
            return False
        cmds.disconnectAttr(connected[0], blend_input )
        return True

    def edit_target(self, weight_name, edit = True):

        weight_id = self.get_weight_id(weight_name)
        cmds.sculptTarget (self.name, e=True, target=-1)
        if edit:
            cmds.sculptTarget (self.name , e=True , target=weight_id)

    def get_target_delta(self, weight_name, target_value=6000):
        """
        Returns the delta points for the specified weight and target value.
        :param weight_name: The name of the weight to get the delta points for.
        :param target_value: The target value for the blendshape. Default is 6000.
        :return: A tuple containing the target points and their indices.
        """
        target_points, target_indices = self.get_target_points(weight_name, target_value)
        base_points = self.get_base_points()
        delta_points = [target_points[i] - base_points[target_indices[i]] for i in range(len(target_indices))]
        return delta_points, target_indices
    # Weight map methods
    def apply_weight_maps(self):
        weights = self.get_weights()
        for weight in weights:
            self.apply_weight_map(weight)

    def apply_weight_map(self, weight_name):
        target_values = self.get_inbetween_targets(weight_name)

        for target_value in target_values:
            temp = self.duplicate_target(weight_name, target_value, True)
            self.connect_target(weight_name, temp, target_value)
            cmds.delete(temp)
        self.clear_weight_map (weight_name)

    def duplicate_target(self, weight_name: str, weight_value = 6000, apply_weight_map = False):

        target = self.duplicate_base(name=weight_name)
        target_points, target_indices = self.get_target_points(weight_name, weight_value)
        base_points = self.get_base_points()
        target_mesh_points = om.MPointArray (base_points)
        weight_values = None
        if apply_weight_map:
            weight_values = self.get_weight_map_api(weight_name)
        for i in range (len(target_points)):
            delta_point = om.MVector (target_points[i])
            if apply_weight_map:
                delta_point = delta_point * weight_values[target_indices[i]]
            summed_mpoint = om.MPoint (delta_point + om.MVector (base_points[target_indices[i]]))
            target_mesh_points[ target_indices[i]] = summed_mpoint

        target.set_points(target_mesh_points)
        return target

    def combine_targets(self, weight_names, weight_values = 6000, name = None):

        if not name:
            name = "_".join(weight_names)

        combined_target = self.duplicate_base(name=name)
        if not isinstance(weight_values, list):
            mult = len(weight_names)
            weight_values = [weight_values] * mult

        base_points = self.get_base_points()
        for (weight_name, weight_value) in zip(weight_names, weight_values):
            target_points , target_indices = self.get_target_points (weight_name , weight_value)
            for i in range (len (target_points)):
                summed_mpoint = om.MPoint (om.MVector (target_points[i]) + om.MVector (base_points[target_indices[i]]))
                base_points[target_indices[i]] = summed_mpoint

        combined_target.set_points (base_points)
        return combined_target

    def get_weight_map(self,weight_name):
        """
        return the weight values
        :param weight:
        :return:
        """

        weight_id = self.get_weight_id(weight_name)
        vertex_count = cmds.polyEvaluate (self.base , v=1) -1
        weight_values = cmds.getAttr ('{0}.inputTarget[0].inputTargetGroup[{1}].targetWeights[0:{2}]'.format (self, weight_id, vertex_count))

        return weight_values

    def set_weight_map(self, weight_name, weight_values):

        weight_id = self.get_weight_id(weight_name)

        vertex_count = cmds.polyEvaluate (self.base , v=1) - 1
        cmds.setAttr ('{0}.inputTarget[0].inputTargetGroup[{1}].targetWeights[0:{2}]'.format (self , weight_id , vertex_count),*weight_values,
                      size = len(weight_values))

    def normalize_weight_maps(self, weights =None):
        if not weights:
            weights =self.get_weights().keys()
        if len(weights) < 1:
            return
        weight_lists  = list()
        for weight in weights:
            weight_values = self.get_weight_map(str(weight))
            weight_lists.append(weight_values)
        for i in range(len(weight_lists[0])):
            mult = 0.0
            for j in range(len(weight_lists)):
                mult += weight_lists[j][i]
            for j in range(len(weight_lists)):
                weight_lists[j][i] = weight_lists[j][i] / mult

        for i, weight in enumerate(weights):
            self.set_weight_map(str(weight), weight_lists[i])

    def sum_weight_maps(self, weight_a, weight_b):
        weight_values_a = weight_a
        if isinstance(weight_a, str):
            weight_values_a = self.get_weight_map(weight_a)
        weight_values_b = weight_b
        if isinstance(weight_b, str):
            weight_values_b = self.get_weight_map(weight_b)
        weights = list()
        for i in range(len(weight_values_a)):
            w = weight_values_a[i] + weight_values_b[i]
            weights.append(w)
        return weights

    def subtract_weight_maps(self, weight_a, weight_b):
        weight_values_a = weight_a
        if isinstance(weight_a, str):
            weight_values_a = self.get_weight_map(weight_a)
        weight_values_b = weight_b
        if isinstance(weight_b, str):
            weight_values_b = self.get_weight_map(weight_b)

        weights = list()
        for i in range(len(weight_values_a)):
            w = weight_values_a[i] - weight_values_b[i]
            weights.append(w)
        return weights

    def multiply_weight_maps(self, weight_a, weight_b):
        weight_values_a = weight_a
        if isinstance(weight_a, str):
            weight_values_a = self.get_weight_map(weight_a)
        weight_values_b = weight_b
        if isinstance(weight_b, str):
            weight_values_b = self.get_weight_map(weight_b)

        weights = list()
        for i in range(len(weight_values_a)):
            w = weight_values_a[i] * weight_values_b[i]
            weights.append(w)
        return weights

    def invert_weight_map(self, weight):

        weight_values = self.get_weight_map_api(weight)
        for i in range(len(weight_values)):
            weight_values[i] = 1.0 - weight_values[i]
        self.set_weight_map_api(weight, weight_values)


    def get_target_plug(self, weight_name, target_value=6000):
        # get the MObject from selection list
        #
        weight_id = self.get_weight_id(weight_name)
        selection_list = om.MSelectionList ()
        plug_name = self.INPUT_TARGET.format(self.name, weight_id, target_value)
        selection_list.add (plug_name)
        plug = selection_list.getPlug (0)
        return  plug

    def get_target_weight_plug(self, weight_name):
        weight_id = self.get_weight_id(weight_name)

        # get the MObject from selection list
        #
        selection_list = om.MSelectionList ()
        plug_name = '{0}.inputTarget[0].inputTargetGroup[{1}].targetWeights'.format (self , weight_id)
        selection_list.add (plug_name)
        plug = selection_list.getPlug (0)
        return  plug

    def normalize_weight_maps_api(self, weights=None):
        if not weights:
            weights =self.get_weights().keys()
        plugs =[self.get_target_weight_plug(str(x)) for x in weights]
        vertex_count = cmds.polyEvaluate (self.base , v=1)
        for i in range(vertex_count):
            max_weight = 0.0
            vals = list ()
            for plug in plugs:
                val = plug.elementByLogicalIndex (i).asDouble ()

                vals.append(val)
                max_weight += val

            for plug, val in zip(plugs, vals):
                n_val = float(val) / float(max_weight)
                plug.elementByLogicalIndex (i).setDouble (n_val)

    def clear_weight_map(self, weight_name):
        weight_id = self.get_weight_id(weight_name)

        plug = self.get_target_weight_plug(weight_id)
        weight_indexes = plug.getExistingArrayAttributeIndices()
        modifier = om.MDGModifier ()
        for i in weight_indexes:
            modifier.removeMultiInstance (plug.elementByLogicalIndex (i) , True)
        modifier.doIt ()

    def set_weight_map_api(self, weight_name, weights_values):

        plug = self.get_target_weight_plug(weight_name)
        if isinstance(weights_values, float):
            vertex_count = cmds.polyEvaluate (self.base , v=1)
            weights_values = [weights_values]*vertex_count
        for i in range(len(weights_values)):
            weight_value = weights_values[i]
            plug.elementByLogicalIndex (i).setDouble (weight_value)

    def get_weight_map_api(self, weight_name):

        plug = self.get_target_weight_plug(weight_name)
        ids = plug.getExistingArrayAttributeIndices()

        vertex_count = cmds.polyEvaluate (self.base , v=1)
        max_id = 0
        if ids:
            max_id = max (ids)

        if max_id > vertex_count:
            weights = [1.0] * max_id
        else:
            weights = [1.0] * vertex_count

        for i in ids:
            weight= plug.elementByLogicalIndex (i).asDouble ()
            weights[i] = weight

        return weights

    def invert_weight_map_api(self, weight_name):

        plug = self.get_target_weight_plug(weight_name)
        ids = plug.getExistingArrayAttributeIndices()

        vertex_count = cmds.polyEvaluate (self.base , v=1)
        weights = [0.0] * (vertex_count)

        for i in range(vertex_count):
            inv_weights= 1.0 - (plug.elementByLogicalIndex (i).asDouble ())
            plug.elementByLogicalIndex (ids[i]).setDouble (inv_weights)

        return weights

    def get_dependency_node(self):
        sel_list = om.MSelectionList()
        sel_list.add(self.name)
        return sel_list.getDependNode(0)

    def get_base_points(self):

        input_geo_plug = self.mfn_dependency_node.findPlug ('input', True).elementByPhysicalIndex (0)
        base_mesh = input_geo_plug.child (0).asMObject ()
        base_fn_mesh = om.MFnMesh (base_mesh)
        points = base_fn_mesh.getPoints(om.MSpace.kObject)
        return points

    def get_target_points(self, weight_name, target_value=6000):

        weight_id = self.get_weight_id (weight_name)

        base_points = self.get_base_points()
        target_plug = self.get_target_plug(weight_id, target_value)
        input_points_target_plug = target_plug.child (3)
        input_components_target_plug = target_plug.child (4)

        # if connected, retrieves the input target object and queries his points
        input_points_target_data = input_points_target_plug.asMDataHandle().data()
        input_components_target_data = input_components_target_plug.asMDataHandle().data()
        # to read the deltas, use a MFnPointArrayData
        target_points = om.MPointArray()
        fn_points = om.MFnPointArrayData(input_points_target_data)
        fn_points.copyTo(target_points)



        # use MFnSingleIndexedComponent to extract an MIntArray with the indices
        dg_component_fn = om.MFnComponentListData(input_components_target_data)

        single_component_fn = om.MFnSingleIndexedComponent (dg_component_fn.get(0))
        target_indices = single_component_fn.getElements ()

        return target_points, target_indices

    def set_target_points(self, weight_name,target_points, target_indices, target_value=6000 ):

        weight_id = self.get_weight_id (weight_name)

        target_plug = self.get_target_plug(weight_id, target_value)
        input_points_target_plug = target_plug.child (3)
        input_components_target_plug = target_plug.child (4)

        # set the indexes
        fn_single_component_data =  om.MFnSingleIndexedComponent().create(om.MFn.kMeshVertComponent)
        fn_single_component = om.MFnSingleIndexedComponent(fn_single_component_data)
        fn_single_component.addElements(target_indices)
        input_components_target_plug.setMObject(fn_single_component.object())

        delta_points_data = om.MFnPointArrayData(om.MFnPointArrayData().create())
        delta_points_data.set(target_points)
        input_points_target_plug.setMObject(delta_points_data.object())




