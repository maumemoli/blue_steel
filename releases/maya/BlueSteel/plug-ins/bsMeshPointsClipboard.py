"""
Maya plugin that provides two commands for copying and pasting mesh point positions.

Commands:
    bsCopyMeshPoints  - Copies the raw vertex positions of the selected (or specified) mesh.
    bsPasteMeshPoints - Pastes previously copied vertex positions onto the selected
                        (or specified) mesh. This command is undoable.

Usage:
    # Copy points from a mesh
    cmds.bsCopyMeshPoints("pCube1")
    # or select a mesh and run:
    cmds.bsCopyMeshPoints()

    # Paste points onto a mesh
    cmds.bsPasteMeshPoints("pCube1")
    # or select a mesh and run:
    cmds.bsPasteMeshPoints()
    # then ctrl+z to undo
"""

from maya import OpenMaya as om, OpenMayaMPx as ompx, cmds

# ---------------------------------------------------------------------------
# Shared clipboard – stores an MPointArray and the vertex count for validation.
# ---------------------------------------------------------------------------
_clipboard_points = None  # MPointArray
_clipboard_vertex_count = 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _get_dag_path_from_arg(arg_str):
    """Resolve a node name to its MDagPath, extending to the shape if needed."""
    sel = om.MSelectionList()
    sel.add(arg_str)
    dag = om.MDagPath()
    sel.getDagPath(0, dag)
    if dag.node().apiType() == om.MFn.kTransform:
        dag.extendToShape()
    return dag


def _resolve_mesh(args):
    """Return an MDagPath for the mesh specified in *args* or from the active selection."""
    arg_str = None
    if args.length() > 0:
        arg_str = args.asString(0)
    else:
        sel = om.MSelectionList()
        om.MGlobal.getActiveSelectionList(sel)
        if sel.length() == 0:
            raise RuntimeError("No mesh specified and nothing is selected.")
        dag = om.MDagPath()
        sel.getDagPath(0, dag)
        if dag.node().apiType() == om.MFn.kTransform:
            dag.extendToShape()
        return dag

    return _get_dag_path_from_arg(arg_str)


def _read_points(dag_path):
    """Return (MPointArray, vertex_count) from the given mesh dag path."""
    mfn = om.MFnMesh(dag_path)
    points = om.MPointArray()
    mfn.getPoints(points)
    return points, points.length()


def _write_points(dag_path, points):
    """Set points on the mesh via MFnMesh.setPoints."""
    mfn = om.MFnMesh(dag_path)
    if mfn.numVertices() != points.length():
        raise RuntimeError(
            "Vertex count mismatch: mesh has {} vertices but data has {}.".format(
                mfn.numVertices(), points.length()
            )
        )
    mfn.setPoints(points)


def _find_orig_shape(dag_path):
    """Find the intermediate (original) shape if the mesh has deformer history."""
    transform = om.MDagPath(dag_path)
    if transform.node().apiType() != om.MFn.kTransform:
        transform.pop()
    mfn_transform = om.MFnDagNode(transform)
    for i in range(mfn_transform.childCount()):
        child = mfn_transform.child(i)
        if child.apiType() != om.MFn.kMesh:
            continue
        child_fn = om.MFnDagNode(child)
        if child_fn.isIntermediateObject:
            child_dag = om.MDagPath()
            child_fn.getPath(child_dag)
            return child_dag
    return None


# ---------------------------------------------------------------------------
# bsCopyMeshPoints
# ---------------------------------------------------------------------------
class BsCopyMeshPoints(ompx.MPxCommand):
    kPluginCmdName = "bsCopyMeshPoints"

    def __init__(self):
        super(BsCopyMeshPoints, self).__init__()

    @staticmethod
    def creator():
        return ompx.asMPxPtr(BsCopyMeshPoints())

    def doIt(self, args):
        global _clipboard_points, _clipboard_vertex_count
        dag = _resolve_mesh(args)
        _clipboard_points, _clipboard_vertex_count = _read_points(dag)
        self.displayInfo(
            "Copied {} vertices from '{}'.".format(
                _clipboard_vertex_count, dag.partialPathName()
            )
        )


# ---------------------------------------------------------------------------
# bsPasteMeshPoints  (undoable)
# ---------------------------------------------------------------------------
class BsPasteMeshPoints(ompx.MPxCommand):
    kPluginCmdName = "bsPasteMeshPoints"

    def __init__(self):
        super(BsPasteMeshPoints, self).__init__()
        self._dag_path = None
        self._orig_dag_path = None
        self._old_points = None
        self._old_count = 0
        self._old_orig_points = None
        self._new_orig_points = None
        self._modifier = None

    @staticmethod
    def creator():
        return ompx.asMPxPtr(BsPasteMeshPoints())

    def isUndoable(self):
        return True

    def doIt(self, args):
        if _clipboard_points is None:
            raise RuntimeError("No points in clipboard. Run bsCopyMeshPoints first.")

        self._dag_path = _resolve_mesh(args)
        # Snapshot current points for undo.
        self._old_points, self._old_count = _read_points(self._dag_path)

        # If the mesh has deformer history, find the orig shape and precompute
        # the new orig points so that the output matches the clipboard.
        self._orig_dag_path = _find_orig_shape(self._dag_path)
        if self._orig_dag_path is not None:
            self._old_orig_points, _ = _read_points(self._orig_dag_path)
            self._new_orig_points = om.MPointArray()
            for i in range(_clipboard_vertex_count):
                orig = self._old_orig_points[i]
                clip = _clipboard_points[i]
                out = self._old_points[i]
                self._new_orig_points.append(
                    om.MPoint(
                        orig.x + clip.x - out.x,
                        orig.y + clip.y - out.y,
                        orig.z + clip.z - out.z,
                    )
                )

        self.redoIt()

    def redoIt(self):
        if self._orig_dag_path is not None:
            _write_points(self._orig_dag_path, self._new_orig_points)
        else:
            _write_points(self._dag_path, _clipboard_points)
        # Conform normals via MDGModifier so it shares the undo chunk.
        transform = om.MDagPath(self._dag_path)
        transform.pop()
        self._modifier = om.MDGModifier()
        # self._modifier.commandToExecute(
        #     'polyNormal -normalMode 2 -userNormalMode 0 -ch 0 "{}"'.format(
        #         transform.partialPathName()
        #     )
        # )
        self._modifier.doIt()

    def undoIt(self):
        if self._modifier is not None:
            self._modifier.undoIt()
        if self._orig_dag_path is not None:
            _write_points(self._orig_dag_path, self._old_orig_points)
        else:
            _write_points(self._dag_path, self._old_points)


# ---------------------------------------------------------------------------
# Plugin registration
# ---------------------------------------------------------------------------
def initializePlugin(m_object):
    plugin = ompx.MFnPlugin(m_object, "BlueSteel", "1.0", "Any")
    try:
        plugin.registerCommand(
            BsCopyMeshPoints.kPluginCmdName, BsCopyMeshPoints.creator
        )
    except Exception:
        raise RuntimeError(
            "Failed to register command: {}".format(BsCopyMeshPoints.kPluginCmdName)
        )
    try:
        plugin.registerCommand(
            BsPasteMeshPoints.kPluginCmdName, BsPasteMeshPoints.creator
        )
    except Exception:
        raise RuntimeError(
            "Failed to register command: {}".format(BsPasteMeshPoints.kPluginCmdName)
        )


def uninitializePlugin(m_object):
    plugin = ompx.MFnPlugin(m_object)
    try:
        plugin.deregisterCommand(BsCopyMeshPoints.kPluginCmdName)
    except Exception:
        raise RuntimeError(
            "Failed to deregister command: {}".format(BsCopyMeshPoints.kPluginCmdName)
        )
    try:
        plugin.deregisterCommand(BsPasteMeshPoints.kPluginCmdName)
    except Exception:
        raise RuntimeError(
            "Failed to deregister command: {}".format(BsPasteMeshPoints.kPluginCmdName)
        )
