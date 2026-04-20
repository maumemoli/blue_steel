from maya import OpenMaya as om, cmds
from datetime import datetime
import numpy as np
from ctypes import c_float, c_double, c_int, c_uint
from . import attrUtils
from functools import wraps

"""
Set of utility functions to use the maya API commands.
They are mostly used to convert Maya API arrays to numpy arrays and vice versa.
This is using Maya API v1.0 because in this circumstance it is faster than v2.0.
"""

# Utility function to get mfnMesh from a mesh name
def get_dag_path(node_name: str):
    """
    Get the MDagPath of a node by its name.
    Parameters:
        node_name (str): The name of the node.
    Returns:
        OpenMaya.MDagPath: The MDagPath of the node.
    Example:
        >>> dag_path = get_dag_path("pCube1")
    """
    selection_list = om.MSelectionList()
    selection_list.add(node_name)
    dag_path = om.MDagPath()
    selection_list.getDagPath(0, dag_path)
    return dag_path

def create_mfn_mesh(mesh_name: str):
    """
    Get the MFnMesh of a mesh by its name.
    Parameters:
        mesh_name(str) :The name of the mesh.
    Returns:
        OpenMaya.MFnMesh
        0The MFnMesh of the mesh.
    Example:
        >>> mfn_mesh = create_mfn_mesh("pCube1")
    """
    mfn_mesh = om.MFnMesh(get_dag_path(mesh_name))
    return mfn_mesh

# Utility functions to get Blendshape Plugs attributes
def get_dependency_node(node_name: str):
    """
    Get the MObject of the blendshape node.
    Returns:
        MObject: The MObject of the blendshape node.
    Example:
        >>> m_obj = get_dependency_node("blendShape1")
        >>> print(m_obj)
        <maya.OpenMaya.MObject object at 0x...>
    """
    sel_list = om.MSelectionList()
    sel_list.add(node_name)
    dependency_node = om.MObject()
    sel_list.getDependNode(0, dependency_node)
    return dependency_node

# mesh functions
def get_points_as_numpy(mesh_name: str):
    """
    Get the points of a mesh as a numpy array.
    Parameters:
        mesh_name (str): The name of the mesh.
    Returns:
        numpy.ndarray: A (N, 3) array of doubles where each row is [x, y, z].
    Example:
        >>> np_array = get_points_as_numpy("pCube1")
        >>> print(np_array)
        [[0.0, 0.0, 0.0],
         [1.0, 0.0, 0.0],
         [1.0, 1.0, 0.0],
         [0.0, 1.0, 0.0],
         [0.0, 0.0, 1.0],
         [1.0, 0.0, 1.0],
         [1.0, 1.0, 1.0],
         [0.0, 1.0, 1.0]]
    """
    mfn_mesh = create_mfn_mesh(mesh_name)
    points = om.MPointArray()
    mfn_mesh.getPoints(points, om.MSpace.kObject)
    np_array = m_points_to_numpy(points)
    # remove the w component
    np_array = np_array[:, :3]
    return np_array

def set_points_from_numpy(mesh_name: str, np_array: np.ndarray):
    """
    Set the points of a mesh from a numpy array.
    Parameters:
        mesh_name (str): The name of the mesh.
        np_array (numpy.ndarray): 
        A (N, 4) array of doubles where each row is [x, y, z, w].
    Example:
        >>> np_array = np.array([[0.0, 0.0, 0.0, 1.0],
        ...                      [1.0, 0.0, 0.0, 1.0],
        ...                      [1.0, 1.0, 0.0, 1.0],
        ...                      [0.0, 1.0, 0.0, 1.0],
        ...                      [0.0, 0.0, 1.0, 1.0],
        ...                      [1.0, 0.0, 1.0, 1.0],
        ...                      [1.0, 1.0, 1.0, 1.0],
        ...                      [0.0, 1.0, 1.0, 1.0]])
        >>> set_points_as_numpy("pCube1", np_array)
    """
    if np_array.shape[1] == 4:
        np_array = np_array[:, :3]
    mfn_mesh = create_mfn_mesh(mesh_name)
    m_point_array = numpy_to_m_points(np_array)
    mfn_mesh.setPoints(m_point_array)

def get_mesh_raw_points(mesh_name: str):
    """
    Get the raw points of a mesh as a numpy array.
    Parameters:
        mesh_name (str): The name of the mesh.
    Returns:
        numpy.ndarray: A (N, 4) array of doubles where each row is [x, y, z, w].
    Example:
        >>> np_array = get_mesh_raw_points("pCube1")
        >>> print(np_array)
        [[0.0, 0.0, 0.0, 1.0],
         [1.0, 0.0, 0.0, 1.0],
         [1.0, 1.0, 0.0, 1.0],
         [0.0, 1.0, 0.0, 1.0],
         [0.0, 0.0, 1.0, 1.0],
         [1.0, 0.0, 1.0, 1.0],
         [1.0, 1.0, 1.0, 1.0],
         [0.0, 1.0, 1.0, 1.0]]
    """
    mfn_mesh = create_mfn_mesh(mesh_name)
    raw_ptr = mfn_mesh.getRawPoints()
    num_verts = mfn_mesh.numVertices()
    
    # get a ctypes array from the raw pointer
    float_array_type = c_float * (num_verts * 3)
    ctypes_array = float_array_type.from_address(int(raw_ptr))
    # converting to numpy array
    np_array = np.ctypeslib.as_array(ctypes_array).reshape(num_verts, 3).copy()
    return np_array


def set_mesh_raw_points(mesh_name: str, np_array: np.ndarray):
    """
    Set the raw points of a mesh from a numpy array.
    Parameters:
        mesh_name (str): The name of the mesh.
        np_array (numpy.ndarray):
        A (N, 4) array of doubles where each row is [x, y, z, w].
    Example:
        >>> np_array = np.array([[0.0, 0.0, 0.0, 1.0],
        ...                      [1.0, 0.0, 0.0, 1.0],
        ...                      [1.0, 1.0, 0.0, 1.0],
        ...                      [0.0, 1.0, 0.0, 1.0],
        ...                      [0.0, 0.0, 1.0, 1.0],
        ...                      [1.0, 0.0, 1.0, 1.0],
        ...                      [1.0, 1.0, 1.0, 1.0],
        ...                      [0.0, 1.0, 1.0, 1.0]])
        >>> set_mesh_raw_points("pCube1", np_array)
    """
    mfn_mesh = create_mfn_mesh(mesh_name)
    # removing the w component
    if np_array.shape[1] == 4:
        np_array = np_array[:, :3]
    count = np_array.shape[0]
    # flattening the array and ensuring float32 type
    np_array = np_array.ravel().astype(np.float32)
    # convert numpy array to a ctypes array of floats (N * 3)
    
    # Get the raw pointer address
    raw_ptr = mfn_mesh.getRawPoints()
    # Create ctypes array from that address
    float_array_type = c_float * (count * 3)
    ctypes_array = float_array_type.from_address(int(raw_ptr))
    # Copy data directly to that memory location
    np.ctypeslib.as_array(ctypes_array)[:] = np_array
    # Update the mesh surface to reflect the changes
    mfn_mesh.updateSurface()

# Get the MPlug of an attribute
def get_plug(node_name: str, attr_name: str):
    """
    Get the MPlug of an attribute.
    Parameters:
        node_name (str): The name of the node.
        attr_name (str): The name of the attribute.
    Returns:
        OpenMaya.MPlug: The MPlug of the attribute.
    Example:
        >>> plug = get_plug("blendShape1", "weight[0]")
        >>> print(plug)
        <maya.OpenMaya.MPlug object at 0x...>
    """
    m_obj = get_dependency_node(node_name)
    m_fn_dep = om.MFnDependencyNode(m_obj)
    plug = m_fn_dep.findPlug(attr_name, False)
    return plug


# Utility functions to convert between MPointArray and numpy arrays
def m_points_to_numpy(m_point_array):
    """
    Convert a Maya MPointArray to a numpy ndarray.
    Parameters:
        m_point_array (om.MPointArray): The Maya point array to convert.
    Returns:
        numpy.ndarray: A (N, 4) array of doubles where each row is [x, y, z, w].
    Example:
        >>> arr = m_points_to_numpy(m_point_array)
        >>> for point in arr:
        ...     print(point)  # Each point is [x, y, z, w]
    """
    if m_point_array.length() == 0:
        # retrun a [0.0, 0.0, 0.0, 1.0] shaped array
        return np.array([[0.0, 0.0, 0.0, 1.0]])
    # Get number of points
    count = m_point_array.length()

    # Create a script util to hold a double4* (N * 4 doubles)
    util = om.MScriptUtil()
    util.createFromList([0.0] * (count * 4), count * 4)

    # Cast util memory to a double4 pointer
    ptr = om.MScriptUtil.asDouble4Ptr(util)

    # Fill that memory with the content of the MPointArray
    m_point_array.get(ptr)

    # Create a ctypes array view of the memory.
    # Each point is 4 doubles, so total doubles = count * 4
    c_array_type = c_double * (count * 4)
    c_array = c_array_type.from_address(int(ptr))

    # Let numpy view the same memory as a 1D array of doubles
    np_array = np.ctypeslib.as_array(c_array)

    # Reshape to (count, 4) for easier use
    np_array = np_array.reshape(count, 4)
    return np_array.copy()

def numpy_to_m_points(np_array: np.ndarray):
    """
    Convert a numpy ndarray of shape (N, 4) to a Maya MPointArray.
    Parameters:
        np_array (numpy.ndarray):
        A (N, 4) array of doubles where each row is [x, y, z, w].
    Returns:
        OpenMaya.MPointArray:
        A Maya point array containing the points from np_array.
    Example:
        >>> m_point_array = numpy_to_m_points(np_array)
        >>> for i in range(m_point_array.length()):
        ...     point = m_point_array[i]
        ...     print(point.x, point.y, point.z, point.w)

    """
    if np_array.ndim != 2 or np_array.shape[1] != 4:
        if np_array.ndim == 2 and np_array.shape[1] == 3:
            # if the input is (N, 3), we can add a w component of 1.0
            np_array = np.hstack((np_array, np.ones((np_array.shape[0], 1))))
        else:
            raise ValueError("Input array must have shape (N, 4) or (N, 3)")

    count = np_array.shape[0]

    # Allocate a double array (count * 4) inside an MScriptUtil
    util = om.MScriptUtil()
    util.createFromList([0.0] * (count * 4), count * 4)

    # Get a pointer of type double4*
    ptr = om.MScriptUtil.asDouble4Ptr(util)

    # Create a ctypes view of that buffer and a numpy view on top of it
    c_array_type = c_double * (count * 4)
    c_array = c_array_type.from_address(int(ptr))
    np_view = np.ctypeslib.as_array(c_array).reshape(count, 4)

    # Copy the user numpy data into the MScriptUtil buffer
    np.copyto(np_view, np_array)

    # Build a new MPointArray directly from the pointer and count
    # This is the key: MPointArray(double4* ptr, unsigned int count)
    return om.MPointArray(ptr, count)

def undoable(func):
    """
    Decorator to wrap a function in a Maya undo chunk.
    Ensures the chunk is closed even if the function fails.
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        cmds.undoInfo(openChunk=True, chunkName=func.__name__)
        try:
            return func(*args, **kwargs)
        finally:
            cmds.undoInfo(closeChunk=True)
    return wrapper

def get_mesh_bounding_box(mesh_name: str, world = True):
    """
    Get the bounding box of a mesh.
    Parameters:
        mesh_name (str): The name of the mesh.
        world (bool): If True, returns world-space bounding box. If False, returns object-space bounding box.
    Returns:
        tuple: A tuple containing two tuples:
            - min_point (tuple): A (3,) tuple representing the minimum point (x, y, z).
            - max_point (tuple): A (3,) tuple representing the maximum point (x, y, z).
    Example:
        >>> min_point, max_point = get_mesh_bounding_box("pCube1", world=True)
        >>> print("Min Point:", min_point)
        Min Point: (0.0, 0.0, 0.0)
        >>> print("Max Point:", max_point)
        Max Point: (1.0, 1.0, 1.0)
    """
    dag_path = get_dag_path(mesh_name)
    mfn_mesh = om.MFnMesh(dag_path)
    bbox = mfn_mesh.boundingBox()
    
    if world:
        # Transform the bounding box to world space
        bbox.transformUsing(dag_path.inclusiveMatrix())
    
    min_point = (bbox.min().x, bbox.min().y, bbox.min().z)
    max_point = (bbox.max().x, bbox.max().y, bbox.max().z)
    return min_point, max_point

def disconnect_node(node):
    """
    Disconnect all connections to and from a node.
    Parameters:
        node (str): The name of the node to disconnect.
    """
    if not cmds.objExists(node):
        raise RuntimeError(f"Node '{node}' does not exist")

    # List all connections (plugs, not just nodes)
    connections = cmds.listConnections(node, plugs=True, connections=True) or []

    # connections comes as pairs: [src, dst, src, dst...]
    for i in range(0, len(connections), 2):
        src = connections[i]
        dst = connections[i + 1]

        try:
            cmds.disconnectAttr(src, dst)
        except RuntimeError:
            # Some connections are locked or not disconnectable
            pass