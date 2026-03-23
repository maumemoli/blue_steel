from maya import cmds
from maya import mel
import maya.api.OpenMaya as OpenMaya

CLUSTERS = []
MIRROR_CLUSTER_AXIS = "X"


def reset_transformations():
    selection = cmds.ls (sl=True)
    if not selection:
        return
    for selected in selection:
        channels = cmds.listAttr (selected , k=True)
        excluded_channels = ["visibility"]
        for channel in channels:
            if channel not in excluded_channels:
                default_value = cmds.attributeQuery (channel , n=selected , ld=True)
                if not cmds.getAttr ("{}.{}".format (selected , channel) , l=True):  # check for incoming connections
                    try:
                        cmds.setAttr ("{}.{}".format (selected , channel) , default_value[0])
                    except Exception as e:
                        cmds.warning ("Could not reset {}.{}: {}".format (selected , channel , e))



def make_paint_cluster(*args):
    """ Create a paintable cluster"""
    selection = cmds.filterExpand (sm=31)
    global CLUSTERS

    if selection:
        weighted = False
        if cmds.softSelect (q=True , sse=True):
            weighted = True

        symmetry = cmds.symmetricModelling (q=True , symmetry=True)
        if symmetry:
            cmds.symmetricModelling (symmetry=False)
        cluster = SmartCluster.create (weighted)
        if symmetry:
            # mirrorCluster(cluster.handle)
            cmds.symmetricModelling (symmetry=True)
        if not weighted:
            cluster.paint ()

    else:
        selection = cmds.ls (sl=True)
        cluster = SmartCluster (selection[0])
        if cluster.cluster:  # check if the selected object is a cluster handle
            cluster = SmartCluster (selection[0])
            cluster.paint ()


def iterations_from_vertex_count(vertex_count,
                                 min_vert=100,
                                 max_vert=50000,
                                 min_iter=1,
                                 max_iter=3):

    if vertex_count <= min_vert:
        return min_iter
    if vertex_count >= max_vert:
        return max_iter
    ratio = float (vertex_count - min_vert) / float (max_vert - min_vert)
    return int (round (min_iter + ratio * (max_iter - min_iter)))


def smooth_flood(*args):
    """Smooth the value of a the the deformer in paint mode"""
    components = cmds.filterExpand(sm=(31, 32, 34, 35, 70)) or []
    # 31=vtx, 32=edge, 34=face, 35=uv, 70=vtxFace
    if components:
        mesh = components[0].split ('.')[0]
    else:
        sel = cmds.ls (sl=True , o=True , long=True) or []
        if not sel:
            return
        mesh = sel[0]

    
    try:
        vertex_count = cmds.polyEvaluate (mesh , v=True)
    except Exception:
        vertex_count = 100

    iterations = iterations_from_vertex_count (vertex_count)
    current_context = cmds.currentCtx ()
    if not current_context == "artAttrContext":
        return
    operation = cmds.artAttrCtx (current_context , q=True , sao=True)
    value = cmds.artAttrCtx (current_context , q=True , value=True)
    opacity = cmds.artAttrCtx (current_context , q=True , opacity=True)
    cmds.artAttrCtx (current_context , e=True , sao="smooth")
    cmds.artAttrCtx (current_context , e=True , value=1.0)
    cmds.artAttrCtx (current_context , e=True , opacity=1.0)
    for _ in range (iterations):
        cmds.artAttrCtx (current_context , e=True , clear=True)
    cmds.artAttrCtx (current_context , e=True , sao=operation)
    cmds.artAttrCtx (current_context , e=True , value=value)
    cmds.artAttrCtx (current_context , e=True , opacity=opacity)


def paint_selected_cluster(*args):
    """ gets in paint mode for selected clusters"""
    selection = cmds.ls (sl=True)
    selected = filter_clusters (selection)
    if selected:
        selected[0].paint ()


def cycle_selected_clusters(*args):
    """Cycle and select trough the CLUSTER list """
    update_clusters_list ()
    selection = cmds.ls (sl=True)
    current = 0
    global CLUSTERS
    if selection:
        if CLUSTERS:
            if selection[0] in CLUSTERS:  # update current index with the selected handle
                current = CLUSTERS.index (selection[0])
    if CLUSTERS:
        cmds.select (CLUSTERS[current - 1])


def filter_clusters(transforms , as_string=False):
    """Gets rid of the objects that are not cluster's handles
    as_string: if False return the a list of SmartCluster objects
    """
    clusters = []
    for transform in transforms:
        cluster = SmartCluster ()
        if cluster.load (transform):
            cluster.load (transform)
            if not as_string:
                clusters.append (cluster)
            else:
                clusters.append (cluster.handle)
    return clusters




def update_clusters_list(*args):
    global CLUSTERS
    updated = []
    for cluster in CLUSTERS:
        if cmds.objExists (cluster):
            updated.append (cluster)
    CLUSTERS = list (updated)


def update_clusters_list_with_selection(*args):
    """Updates the CLUSTER list with the selected clusters, if there is no selection it will update the list with all the clusters in the scene"""
    global CLUSTERS
    selection = cmds.ls (sl=True)
    cluster_handlers = filter_clusters (selection , as_string=True)
    if not cluster_handlers:
        # we will select all the clusters in the scene if there is no selection to update the list with
        all_cluster_handlers_shape = cmds.ls (type="clusterHandle")
        # we need to get the transform of the cluster handle to be able to select it and add it to the list
        cluster_handlers = cmds.listRelatives (all_cluster_handlers_shape , p=True)
    CLUSTERS = sorted (cluster_handlers)


def toggle_cluster_state(*args):
    selection = cmds.ls (sl=True)
    selected = filter_clusters (selection)
    toggle = selected[0].muted

    if toggle:
        for cluster in selected:
            cluster.muted = False
        print ('ON'),
    else:
        for cluster in selected:
            cluster.muted = True
        print ('OFF'),


def link_mirrored_cluster():
    selection = cmds.ls(sl=True)
    base_cluster = selection[0]
    mirror_axis = ["X","Y","Z"]
    mirror_cluster_handle = selection[1]
    global  MIRROR_CLUSTER_AXIS
    axis = MIRROR_CLUSTER_AXIS
    inverted_axis = [x for x in mirror_axis if not x == axis]
    mirror_node = cmds.createNode("multiplyDivide", n="{}_MDV".format(mirror_cluster_handle))
    for axis in mirror_axis:
        cmds.setAttr("{}.input2{}".format(mirror_node, axis), -1)
        if axis in inverted_axis:
            cmds.connectAttr("{}.rotate{}".format(base_cluster, axis),
                             "{}.input1{}".format(mirror_node, axis))
            cmds.connectAttr ("{}.output{}".format (mirror_node , axis),
                              "{}.rotate{}".format (mirror_cluster_handle , axis))
        else:
            cmds.connectAttr ("{}.rotate{}".format (base_cluster , axis) ,
                              "{}.rotate{}".format (mirror_cluster_handle , axis))

        if axis not in inverted_axis:
            cmds.connectAttr ("{}.translate{}".format (base_cluster , axis) ,
                              "{}.input1{}".format (mirror_node , axis))
            cmds.connectAttr ("{}.output{}".format (mirror_node , axis) ,
                              "{}.translate{}".format (mirror_cluster_handle , axis))
        else:
            cmds.connectAttr ("{}.translate{}".format (base_cluster , axis) ,
                              "{}.translate{}".format (mirror_cluster_handle , axis))
        cmds.connectAttr ("{}.scale{}".format (base_cluster , axis) ,
                          "{}.scale{}".format (mirror_cluster_handle , axis))


def mirror_selected_cluster():
    sel = cmds.ls (sl=True)
    mirror_cluster_handle = None
    if len(sel) ==2:
        if SmartCluster(sel[1]).cluster:
            mirror_cluster_handle = sel[1]

    mirror_cluster (sel[0], mirror_cluster_handle)


def mirror_cluster(cluster_handle, mirrored_cluster_handle=None):
    global  MIRROR_CLUSTER_AXIS
    axis = MIRROR_CLUSTER_AXIS
    axis_ref = ["X","Y","Z"]
    mirror_mode = "".join([x for x in axis_ref if not x == axis])
    base_cluster = SmartCluster ()
    base_cluster.load (cluster_handle)
    base_cluster_state = base_cluster.muted
    mesh = base_cluster.get_mesh ()
    mirror_inverse = True
    # get the mesh position
    mesh_position = OpenMaya.MVector (*cmds.xform (mesh , q=True , ws=True , t=True))
    cluster_position = OpenMaya.MVector (*base_cluster.pivot_position)
    mirror_position = cluster_position - mesh_position
    mirror_index = axis_ref.index(axis)
    if mirror_position[mirror_index] >= 0.0:
        mirror_inverse = False
    mirror_position[mirror_index] = mirror_position[mirror_index] * -1.0
    mirror_position = OpenMaya.MVector (mirror_position[0], mirror_position[1] , mirror_position[2])
    mirror_position = mirror_position + mesh_position

    # getting the opposite point in the mesh
    muted_mirror_cluster = True
    if not mirrored_cluster_handle:
        vert_id = get_closest_vert_id (mesh , [mirror_position[0] , mirror_position[1] , mirror_position[2]])
        vert = "{}.vtx[{}]".format (mesh , vert_id)
        cmds.select (vert)
        mirrored_cluster = SmartCluster.create(weighted=False)


    else:
        mirrored_cluster = SmartCluster(mirrored_cluster_handle)

    if not mirrored_cluster.muted:
        mirrored_cluster.muted = True
        muted_mirror_cluster = False

    cmds.xform (mesh , ws=True , t=(0.0 , 0.0 , 0.0))  # resetting the mesh position to perform the mirror
    base_cluster.muted = True

    cmds.copyDeformerWeights (ss=mesh , ds=mesh , sd=base_cluster.cluster , dd=mirrored_cluster.cluster ,
                              sa="closestPoint" , mirrorMode=mirror_mode , mirrorInverse=mirror_inverse)
    cmds.xform (mesh , ws=True ,
                t=[mesh_position[0] , mesh_position[1] , mesh_position[2]])  # putting the mesh back in position
    base_cluster.muted = base_cluster_state
    mirrored_cluster.muted = muted_mirror_cluster

    if not mirrored_cluster_handle:
        cmds.xform (mirrored_cluster.handle , ws=True , rp=[mirror_position[0] , mirror_position[1] , mirror_position[2]])
        # query if there is a keyframe
        keyframes = cmds.keyframe (base_cluster.handle , q=True)
        inverted = ["translate{}".format(axis) , "rotate{}".format(mirror_mode[0]) , "rotate{}".format(mirror_mode[1])]
        k_attrs = cmds.listAttr (base_cluster.handle , k=True)
        if keyframes:
            # query all the the keyable channels

            for k_attr in k_attrs:
                k_frames = cmds.keyframe ("{}.{}".format (base_cluster.handle , k_attr) , q=True)
                k_values = cmds.keyframe ("{}.{}".format (base_cluster.handle , k_attr) , q=True , vc=True)
                for f , v in zip (k_frames , k_values):
                    if k_attr in inverted:
                        v = v * -1.0
                    cmds.setKeyframe (mirrored_cluster.handle , at=k_attr , time=f , v=v)
        else:
            for k_attr in k_attrs:
                attr = cmds.getAttr ("{}.{}".format (base_cluster.handle , k_attr))
                if k_attr in inverted:
                    attr = attr * -1.0
                cmds.setAttr ("{}.{}".format (mirrored_cluster.handle , k_attr) , attr)


class SmartCluster (object):

    def __init__(self , name=None):
        self.handle = None
        self.cluster = None
        self.mesh = None
        self.cluster_set = None
        if name:
            self.load (name)

    def load(self , handle):
        '''
        load cluster from the handle
        '''
        self.handle = handle
        self.cluster = self.get_cluster ()
        if not self.cluster:
            return False
        self.mesh = self.get_mesh ()
        return True

    def get_cluster(self):
        if self.handle:

            cluster = cmds.listConnections ("{}.worldMatrix".format(self.handle) , type='cluster')
            if cluster:
                return cluster[0]
            else:
                return False

    @property
    def pivot_position(self):
        if self.handle:
            if cmds.objExists (self.handle):
                return cmds.xform (self.handle , q=True , rp=True)

    @property
    def pivot_world_position(self):
        if self.handle:
            if cmds.objExists (self.handle):
                return cmds.xform (self.handle , q=True , rp=True , ws=True)

    def get_mesh(self):
        cluster_set = cmds.listConnections (self.cluster , type='objectSet')
        if cluster_set:
            mesh = cmds.listConnections (cluster_set[0] , type='shape')
            if mesh:
                return mesh[0]
            else:
                return False

    @classmethod
    def create(cls , weighted=True):
        selection = cmds.filterExpand (sm=31)
        transform = selection[0].split ('.')[0]
        shape = cmds.listRelatives (transform , s=True)
        all_vertex = cmds.polyEvaluate (v=True)

        if selection:
            elements , weights = soft_selection ()
            all_weights = [0.0] * all_vertex
            if weighted:
                for element , weight in zip (elements , weights):
                    all_weights[element] = weight
            cluster = cls ()
            maya_version = int(cmds.about(v=True))
            if maya_version >= 2022:
                cluster.cluster , cluster.handle = cmds.cluster (useComponentTags=False)
            else:
                cluster.cluster, cluster.handle = cmds.cluster()
            deformer_set = cmds.listConnections ('{}.message'.format (cluster.cluster))[0]
            cmds.sets ('{}.vtx[0:{}]'.format (transform , all_vertex) , add=deformer_set)

            cmds.setAttr ('{0}.weightList[0].weights[0:{1}]'.format (cluster.cluster , (all_vertex - 1)) ,
                          *all_weights ,
                          size=len (all_weights))
            cluster.mesh = cluster.get_mesh ()
            global CLUSTERS
            if cluster.handle not in CLUSTERS:
                CLUSTERS.append (cluster.handle)
            return cluster

    def paint(self):
        cmds.select (self.mesh)
        mel.eval ('artAttrToolScript 4 \"cluster\"; artSetToolAndSelectAttr artAttrCtx cluster.{}.weights'.format (
            self.cluster))

    @property
    def muted(self):
        if cmds.getAttr ('{}.nodeState'.format (self.cluster)) == 0:
            return False
        else:
            return True

    @muted.setter
    def muted(self , state):
        if state:
            cmds.setAttr ('{}.nodeState'.format (self.cluster) , 1)
        else:
            cmds.setAttr ('{}.nodeState'.format (self.cluster) , 0)

    def toggle_state(self):
        if self.muted:
            self.muted = False
        else:
            self.muted = True

    def __str__(self):
        return self.handle

    def __repr__(self):
        return self.handle


def soft_selection():
    # Grab the soft selection
    soft_select = OpenMaya.MGlobal.getRichSelection ()
    selection = soft_select.getSelection ()

    # Filter Defeats the purpose of the else statement
    iterator = OpenMaya.MItSelectionList (selection , OpenMaya.MFn.kMeshVertComponent)
    elements , weights = [] , []
    while not iterator.isDone ():
        dag_path , component = iterator.getComponent ()
        dag_path.pop ()  # Grab the parent of the shape node
        fn_comp = OpenMaya.MFnSingleIndexedComponent (component)
        get_weight = lambda i: fn_comp.weight (i).influence if fn_comp.hasWeights else 1.0

        for i in range (fn_comp.elementCount):
            elements.append (fn_comp.element (i))
            weights.append (get_weight (i))
        iterator.next ()

    return elements , weights


def get_dag_path(node_name):
    sel = OpenMaya.MSelectionList ()
    sel.add (node_name)
    dag_path = sel.getDagPath (0)
    return dag_path


def get_closest_vert_id(mesh , p):
    if isinstance (mesh , OpenMaya.MFnMesh):
        mfn_mesh = mesh
    else:
        mfn_mesh = OpenMaya.MFnMesh (get_dag_path (mesh))

    closest_point , closest_face_id = mfn_mesh.getClosestPoint (OpenMaya.MPoint (*p) , space=OpenMaya.MSpace.kWorld)
    face_verts = mfn_mesh.getPolygonVertices (closest_face_id)
    distance_sorted_face_verts = sorted (face_verts , key=lambda v_id: (
        closest_point.distanceTo (mfn_mesh.getPoint (v_id , OpenMaya.MSpace.kWorld))))
    return distance_sorted_face_verts[0]
