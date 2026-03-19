from ..api import mayaUtils
from maya import cmds
VERTEX_POS_BUFFER = None

def copy_selected_mesh_vertex_position():
    """Copy the vertex positions of the selected mesh to a buffer."""
    global VERTEX_POS_BUFFER
    sel = cmds.ls (selection=True, flatten=True)
    if not sel:
        cmds.warning ("Nothing selected.")
        return
    mesh = sel[0]
    # let's check if the selection is a transform with a mesh shape
    if not cmds.objectType (mesh, isType="transform"):
        cmds.warning ("Selected object is not a transform.")
        return
    shapes = cmds.listRelatives (mesh, shapes=True, fullPath=True)
    if not shapes:
        cmds.warning ("Selected transform has no shapes.")
        return
    global VERTEX_POS_BUFFER
    VERTEX_POS_BUFFER = mayaUtils.get_points_as_numpy(mesh)
    cmds.inViewMessage (message=f"{mesh} vertex positions copied to buffer.", pos="topCenter", fade=True)

def paste_vertex_positions_to_selected_mesh():
    """Paste the vertex positions from the buffer to the selected mesh."""
    global VERTEX_POS_BUFFER
    if VERTEX_POS_BUFFER is None:
        cmds.warning ("No vertex positions in buffer. Please copy vertex positions first.")
        return
    sel = cmds.ls (selection=True, flatten=True)
    if not sel:
        cmds.warning ("Nothing selected.")
        return
    mesh = sel[0]
    # let's check if the selection is a transform with a mesh shape
    if not cmds.objectType (mesh, isType="transform"):
        cmds.warning ("Selected object is not a transform.")
        return
    shapes = cmds.listRelatives (mesh, shapes=True, fullPath=True)
    if not shapes:
        cmds.warning ("Selected transform has no shapes.")
        return
    # let's check if this mesh has the same number of vertices as the buffer
    num_vertices = cmds.polyEvaluate (mesh, vertex=True)
    if num_vertices != VERTEX_POS_BUFFER.shape[0]:
        cmds.warning (f"Selected mesh has {num_vertices} vertices, but buffer has {VERTEX_POS_BUFFER.shape[0]} vertices. Please select a mesh with the same number of vertices as the buffer.")
        return
    # check if the mesh has history, if it does, we need to get the original mesh shapee
    history = cmds.listHistory (mesh, pruneDagObjects=True)
    
    if history:
        # we need to check if the mesh has the tweak locaion connected
        tweak_connected = cmds.listConnections (f"{shapes[0]}.tweakLocation", source=True, destination=False)
        if not tweak_connected:
            print (f"Mesh {mesh} has history but no tweakLocation connected. Please delete history or connect a tweak node to the mesh.")
            cmds.inViewMessage (message=f"Selected mesh has history but no tweakLocation connected. Please delete history or connect a tweak node to the mesh.",
                                pos="topCenter",
                                fade=True,
                                backColor=(1, 0, 0))
            return
    
    mayaUtils.set_points_from_numpy(mesh, VERTEX_POS_BUFFER)
    cmds.inViewMessage (message=f"Vertex positions pasted to {mesh}.", pos="topCenter", fade=True)

def update_intermediate_object():
    """Update the intermediate object of the selected mesh."""
    sel = cmds.ls (selection=True, flatten=True)
    if len(sel) != 2:
        cmds.warning ("Please select exactly two objects. The first should be the source mesh and the second should be the target mesh.")
        return
    # check if the first selection is a transform with a mesh shape
    source_mesh = sel[0]
    if not cmds.objectType (source_mesh, isType="transform"):
        cmds.warning ("First selected object is not a transform.")
        return
    source_shapes = cmds.listRelatives (source_mesh, shapes=True, fullPath=True)
    if not source_shapes:
        cmds.warning ("First selected transform has no shapes.")
        return  
    # check if the second selection is a transform with a mesh shape
    target_mesh = sel[1]
    if not cmds.objectType (target_mesh, isType="transform"):
        cmds.warning ("Second selected object is not a transform.")
        return  
    target_shapes = cmds.listRelatives (target_mesh, shapes=True, fullPath=True)
    if not target_shapes:
        cmds.warning ("Second selected transform has no shapes.")
        return
    # check if the source and target meshes have the same number of vertices
    source_num_vertices = cmds.polyEvaluate (source_mesh, vertex=True)
    target_num_vertices = cmds.polyEvaluate (target_mesh, vertex=True)
    if source_num_vertices != target_num_vertices:
        cmds.warning (f"Source mesh has {source_num_vertices} vertices, but target mesh has {target_num_vertices} vertices. Please select meshes with the same number of vertices.")
        return
    # check if the target mesh has an intermediate object, if it does, we will update the intermediate object, if it doesn't, we will create an intermediate object and connect it to the target mesh
    target_shapes = cmds.listRelatives (target_mesh, shapes=True, fullPath=True)
    intermediate_objects = []
    for shape in target_shapes:
        if cmds.objectType (shape) == "mesh" and cmds.getAttr (f"{shape}.intermediateObject"):
            intermediate_objects.append(shape)
    if not intermediate_objects:
        raise RuntimeError (f"Target mesh {target_mesh} has no intermediate object. Please create an intermediate object for the target mesh and try again.")
    for intermediate_object in intermediate_objects:
        cmds.setAttr (f"{intermediate_object}.intermediateObject", False)
        cmds.blendShape (source_mesh, intermediate_object, weight=(0, 1.0))  
        cmds.delete (intermediate_object, ch=True)
        cmds.setAttr (f"{intermediate_object}.intermediateObject", True)
