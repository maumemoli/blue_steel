from maya import cmds
import collections
from collections import defaultdict
import maya.api.OpenMaya as om
from .mesh import Mesh


class Blendshape(object):
    """
    Edit api nodes
    """
    def __init__(self, name):
        self.name = name
        self.base = self.get_base()
        self.dependency_node =self.get_dependency_node()
        self.mfn_dependency_node = om.MFnDependencyNode(self.dependency_node)

    def get_weights(self):
        '''
        Gets the list of the weights in the blendShape node:
        Returns  a dictionary with weights as keys and the correlated weight IDs as values.
        '''
        weights = cmds.aliasAttr(self.name, q=1)
        targets = {}
        if not weights:
            return targets
        weight_ids=weights[1::2]
        alias_names=weights[::2]
        i = 0
        for i in range(len(alias_names)):
            index = int(filter(str.isdigit, str(weight_ids[i])))
            target_name = alias_names[i]
            targets[target_name] = index
        return targets

    def __str__(self):
        return self.name


    @property
    def weights(self):
        return self.get_weights()


    def duplicate_base(self, name = None):
        points = self.get_base_points()
        if not name:
            name = self.base
        new_mesh = cmds.duplicate(self.base, name =name)
        new_mesh = Mesh(new_mesh[0])
        new_mesh.set_points(points)

        return new_mesh


    def get_base(self):
        '''
        Returns the input transformation node of the blendShape.
        '''
        set=cmds.listConnections (self.name, d=1, s=0, type='objectSet' )
        base=cmds.listConnections (set[0], d=1, s=0 )
        if base:
            return base[0]


    def rename_weight(self , old_name , new_name):
        '''
        Rename weight in the blendshape node:
        string, string
        renameWeight('oldName', 'newName')
        '''
        if new_name in self.get_weights().keys():
            return
        weight_id  =self.get_weight_id(old_name)
        cmds.aliasAttr (new_name , "{}.w[{}]".format( self.name, weight_id))

    def add_target(self, target = None, target_name=None, tangent = False):
        """""
        :param target:
        :return:
        """
        if target:
            if not cmds.objExists(target):
                target_name = target
        else:
            target = target_name
        if not target_name:
            target_name = self.base.split("|")[-1]
        weights = self.get_weights()
        target_id = 1
        if weights:
            target_id = int(sorted(weights.values())[-1]) +1
        if not cmds.objExists(target):
            target = self.duplicate_base(target_name)
        else:
            target= Mesh(target)

        cmds.blendShape (self.name , edit=True , t=(self.base , (target_id) , target , 1.0) ,tc=False, ts=tangent)
        self.rename_weight(target_id, target.name.split("|")[-1])
        return target

    def get_inbetween_targets(self , weight_name):
        '''
        Returns the list of the inbetween values for the specified target.
        '''
        weight_id = self.get_weight_id(weight_name)

        target_plugs = cmds.listAttr ("{}.inputTarget[0].inputTargetGroup[{}].inputTargetItem".format(self.name,weight_id) ,
            ca=1 , m=1 , st="inputTargetItem" , lf=1)

        inbetweens = [filter (str.isdigit , str (x)) for x in target_plugs]

        return inbetweens

    def connect_target(self, weight_name,mesh,target_value = 6000):

        weight_id = self.get_weight_id(weight_name)

        mesh_shape = cmds.listRelatives(mesh, s=True)
        mesh_output = "{}.worldMesh[0]".format(mesh_shape[0])
        blend_input = "{}.inputTarget[0].inputTargetGroup[{}].inputTargetItem[{}].inputGeomTarget".format(self.name, weight_id, target_value)
        if not cmds.isConnected (mesh_output, blend_input):
            cmds.connectAttr (mesh_output, blend_input , f=True)


    def disconnect_target(self, weight_name, target_value = 6000):
        weight_id = self.get_weight_id (weight_name)
        blend_input = "{}.inputTarget[0].inputTargetGroup[{}].inputTargetItem[{}].inputGeomTarget".format\
            (self.name, weight_id, target_value)
        connected = cmds.listConnections(blend_input, p=True)
        if not connected:
            return
        cmds.disconnectAttr(connected[0], blend_input )

    def edit_target(self, weight_name, edit = True):

        weight_id = self.get_weight_id(weight_name)
        cmds.sculptTarget (self.name, e=True, target=-1)
        if edit:
            cmds.sculptTarget (self.name , e=True , target=weight_id)

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


    def duplicate_target(self, weight_name, weight_value = 6000, apply_weight_map = False):

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
        weight_values = cmds.getAttr ('{0}.inputTarget[0].inputTargetGroup[{1}].targetWeights[0:{2}]'.format (self , weight_id,vertex_count))

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

    def sum_weight_map(self, weight_a, weight_b):
        weight_values_a = weight_a
        if isinstance(weight_a, basestring):
            weight_values_a = self.get_weight_map(weight_a)
        weight_values_b = weight_b
        if isinstance(weight_b, basestring):
            weight_values_b = self.get_weight_map(weight_b)
        weights = list()
        for i in range(len(weight_values_a)):
            w = weight_values_a[i] + weight_values_b[i]
            weights.append(w)
        return weights

    def subtract_weight_maps(self, weight_a, weight_b):
        weight_values_a = weight_a
        if isinstance(weight_a, basestring):
            weight_values_a = self.get_weight_map(weight_a)
        weight_values_b = weight_b
        if isinstance(weight_b, basestring):
            weight_values_b = self.get_weight_map(weight_b)

        weights = list()
        for i in range(len(weight_values_a)):
            w = weight_values_a[i] - weight_values_b[i]
            weights.append(w)
        return weights

    def multiply_weight_maps(self, weight_a, weight_b):
        weight_values_a = weight_a
        if isinstance(weight_a, basestring):
            weight_values_a = self.get_weight_map(weight_a)
        weight_values_b = weight_b
        if isinstance(weight_b, basestring):
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

    def get_weight_id(self, weight_name):
        weight_id = weight_name
        if isinstance(weight_name, basestring):
            weights = self.get_weights()
            weight_id = weights[weight_name]

        return weight_id

    def get_target_plug(self, weight_name, target_value=6000):
        # get the MObject from selection list
        #
        weight_id = self.get_weight_id(weight_name)
        selection_list = om.MSelectionList ()
        plug_name = "{}.inputTarget[0].inputTargetGroup[{}].inputTargetItem[{}]".format(
            self.name, weight_id, target_value)
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
        for i in xrange(vertex_count):
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
        for i in xrange(len(weights_values)):
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




