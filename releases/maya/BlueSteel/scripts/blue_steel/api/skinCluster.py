import maya.OpenMaya as om
import maya.OpenMayaAnim as oma
import maya.cmds as cmds
import maya.mel as mel

class SkinCluster(object):
    def __init__(self, mesh):
        self.mesh = mesh
        self.mesh_shape = cmds.listRelatives(mesh, s=True)
        self.skin_fn = None
        self.mesh_m_object= None
        self.mesh_dag_path =None
        self.weight_data = dict()
        self.influences = None
        self.get_skin_fn ()
        if self.skin_fn:
            self.weight_data = self.get_weights()


    def get_skin_fn(self):

        m_sel = om.MSelectionList ()
        m_sel.add (self.mesh_shape[0])
        self.mesh_m_object = om.MObject ()
        self.mesh_dag_path = om.MDagPath ()
        m_sel.getDependNode (0 , self.mesh_m_object)
        m_sel.getDagPath (0 , self.mesh_dag_path)
        iter_dg = om.MItDependencyGraph (self.mesh_m_object ,
                                        om.MItDependencyGraph.kDownstream ,
                                        om.MItDependencyGraph.kPlugLevel)
        while not iter_dg.isDone ():
            current_item = iter_dg.currentItem ()

            if current_item.hasFn (om.MFn.kSkinClusterFilter):

                self.skin_fn = oma.MFnSkinCluster (current_item)
                break
            iter_dg.next ()

    def get_influences(self):
        # Influences & Influence count
        influences = om.MDagPathArray ()
        inf_count = self.skin_fn.influenceObjects (influences)
        # Get node names for influences
        return  [influences[i].partialPathName () for i in range (inf_count)]

    def get_weights(self):
        self.influences = self.get_influences()
        weight_data = {}  # Ordered by vertIter 0-numVerts
        vert_iter = om.MItGeometry (self.mesh_m_object)
        while not vert_iter.isDone ():
            vert_inf_count = om.MScriptUtil ()
            vert_inf_count_ptr = vert_inf_count.asUintPtr ()
            om.MScriptUtil.setUint (vert_inf_count_ptr , 0)
            weights = om.MDoubleArray ()
            self.skin_fn.getWeights (self.mesh_dag_path ,
                               vert_iter.currentItem () ,
                               weights ,
                               vert_inf_count_ptr)
            # Create a dictionary for each vert index in the mesh
            # All influences will be returned for each vert, but may have 0 influence
            weight_data[vert_iter.index ()] = dict (zip (self.influences , weights))
            vert_iter.next ()
        return weight_data

    def get_influence_weights(self, influence):
        if influence in self.influences:
            weights = list()
            for i in range(len(self.weight_data.keys())):
                weights.append(self.weight_data[i][influence])
            return weights
