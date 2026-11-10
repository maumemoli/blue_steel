from maya import OpenMaya as om, cmds
from datetime import datetime
import numpy as np
from ctypes import c_float, c_double, c_int, c_uint
from . import attrUtils
from enum import Enum
from functools import wraps
from contextlib import contextmanager
import time

"""
Set of utility functions to use the maya API commands.
They are mostly used to convert Maya API arrays to numpy arrays and vice versa.
This is using Maya API v1.0 because in this circumstance it is faster than v2.0.
"""

def timed(func):
    """
    Decorator to measure the execution time of a function.
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        start_time = time.time()
        try:
            return func(*args, **kwargs)
        finally:
            end_time = time.time()
            elapsed_time = end_time - start_time
            hours, remainder = divmod(elapsed_time, 3600)
            minutes, seconds = divmod(remainder, 60)
            print(f"{func.__name__} executed in  {int(hours):02d}:{int(minutes):02d}:{seconds:05.2f}")
    return wrapper


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


def assign_default_material(meshes):
    meshes = cmds.ls(meshes, dag=True, type="mesh", long=True)

    if not meshes:
        cmds.warning("No mesh shapes found.")
        return

    # Assign the default shading group
    cmds.sets(meshes, edit=True, forceElement="initialShadingGroup")

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


def get_mesh_vertex_neighbors(mesh_name: str):
    """Build undirected vertex adjacency for a mesh as flat index arrays.

    Edges are derived from the polygon perimeter, which avoids per-vertex API
    queries and works for triangles, quads and ngons alike.

    Parameters:
        mesh_name (str): The name of the mesh.

    Returns:
        tuple: ``(neighbors_row, neighbors_col)`` where each pair
        ``(neighbors_row[i], neighbors_col[i])`` is a unique undirected edge.
    """
    mfn_mesh = create_mfn_mesh(mesh_name)
    num_vertices = mfn_mesh.numVertices()

    # getVertices returns (polygon vertex counts, flattened polygon vertex ids).
    polygon_counts = om.MIntArray()
    polygon_vertices = om.MIntArray()
    mfn_mesh.getVertices(polygon_counts, polygon_vertices)

    counts = np.asarray(list(polygon_counts), dtype=np.int64)
    vertices = np.asarray(list(polygon_vertices), dtype=np.int64)

    total = vertices.size
    if total == 0:
        empty = np.empty(0, dtype=np.int64)
        return empty, empty

    # Start offset of each polygon in the flat vertex id array.
    starts = np.zeros(counts.size, dtype=np.int64)
    np.cumsum(counts[:-1], out=starts[1:])

    polygon_starts = np.repeat(starts, counts)
    local_indices = np.arange(total, dtype=np.int64) - polygon_starts
    polygon_sizes = np.repeat(counts, counts)

    # Next vertex in each polygon, wrapping around to close the perimeter.
    next_global = polygon_starts + ((local_indices + 1) % polygon_sizes)

    a = vertices
    b = vertices[next_global]

    # Drop degenerate edges and make the adjacency symmetric.
    valid = a != b
    a, b = a[valid], b[valid]
    row = np.concatenate([a, b])
    col = np.concatenate([b, a])

    # Deduplicate directed pairs.
    keys = row.astype(np.int64) * num_vertices + col
    keys = np.unique(keys)
    row = keys // num_vertices
    col = keys % num_vertices

    return row.astype(np.int64), col.astype(np.int64)


def _sorted_index(sorted_values: np.ndarray, keys: np.ndarray) -> np.ndarray:
    """Find the position of many keys in a sorted array.

    Parameters:
        sorted_values (numpy.ndarray): Sorted one dimensional array.
        keys (numpy.ndarray): Keys to look up.

    Returns:
        numpy.ndarray: The index of every key, ``-1`` when it is absent.

    Example:
        >>> _sorted_index(np.array([1, 4, 9]), np.array([4, 5]))
        array([ 1, -1])
    """
    positions = np.searchsorted(sorted_values, keys)
    in_range = positions < sorted_values.size
    found = np.zeros(keys.size, dtype=bool)
    found[in_range] = sorted_values[positions[in_range]] == keys[in_range]
    return np.where(found, positions, -1)


def _sorted_contains(sorted_values: np.ndarray, keys: np.ndarray) -> np.ndarray:
    """Test many keys for membership in a sorted array.

    Parameters:
        sorted_values (numpy.ndarray): Sorted one dimensional array.
        keys (numpy.ndarray): Keys to look up.

    Returns:
        numpy.ndarray: One boolean per key, True when the key is present.

    Example:
        >>> _sorted_contains(np.array([1, 4, 9]), np.array([4, 5]))
        array([ True, False])
    """
    return _sorted_index(sorted_values, keys) >= 0


def _build_vertex_ring_csr(polygon_counts,
                           polygon_vertices,
                           num_vertices: int):
    """Build the ordered one-ring of every mesh vertex as a CSR structure.

    The ring order only depends on the polygon windings: a polygon corner
    whose vertex is ``v`` links the previous corner vertex of that polygon to
    the next one, which is one step along the ring of ``v``. Every ring is
    stored in the same winding-derived orientation, so a mirrored pair of
    vertices traverses its two rings in opposite directions. Rings are a cycle
    for manifold interior vertices and a path across the boundary for vertices
    on an open border.

    The ring walk is vectorized over all vertices (one numpy pass per ring
    position), so no per-vertex Python loop is involved.

    Parameters:
        polygon_counts (sequence): Number of vertices per polygon, as returned
            by ``MFnMesh.getVertices``.
        polygon_vertices (sequence): Flattened polygon vertex ids, as returned
            by ``MFnMesh.getVertices``.
        num_vertices (int): Total vertex count of the mesh.

    Returns:
        tuple: ``(ring_flat, ring_offsets, ring_keys, ring_cols)`` where
        ``ring_flat[ring_offsets[v]:ring_offsets[v + 1]]`` is the ordered ring
        of vertex ``v``, ``ring_keys`` is the sorted array of
        ``v * num_vertices + neighbour`` keys and ``ring_cols`` the matching
        ring column. The last two give O(log n) ring position lookups.

    Example:
        >>> flat, offsets, keys, cols = _build_vertex_ring_csr(counts, verts, 8)
        >>> ring = flat[offsets[3]:offsets[4]]
    """
    num_vertices = int(num_vertices)
    counts = np.asarray(polygon_counts, dtype=np.int64).ravel()
    vertices = np.asarray(polygon_vertices, dtype=np.int64).ravel()

    empty = (np.empty(0, dtype=np.int32),
             np.zeros(num_vertices + 1, dtype=np.int64),
             np.empty(0, dtype=np.int64),
             np.empty(0, dtype=np.int64))
    if num_vertices <= 0 or counts.size == 0 or vertices.size == 0:
        return empty

    # Polygons with fewer than three vertices cannot contribute a ring step.
    if not np.all(counts >= 3):
        polygon_ids = np.repeat(np.arange(counts.size, dtype=np.int64), counts)
        usable = counts >= 3
        vertices = vertices[usable[polygon_ids]]
        counts = counts[usable]
        if counts.size == 0:
            return empty

    starts = np.cumsum(counts) - counts
    sizes = np.repeat(counts, counts)
    polygon_starts = np.repeat(starts, counts)
    local = np.arange(vertices.size, dtype=np.int64) - polygon_starts

    prev_vertex = vertices[polygon_starts + (local - 1) % sizes]
    next_vertex = vertices[polygon_starts + (local + 1) % sizes]

    # Degenerate corners (repeated or collapsed vertices) would corrupt the walk.
    usable = ((prev_vertex != vertices) &
              (next_vertex != vertices) &
              (prev_vertex != next_vertex))
    if not usable.all():
        vertices = vertices[usable]
        prev_vertex = prev_vertex[usable]
        next_vertex = next_vertex[usable]
    if vertices.size == 0:
        return empty

    # One directed arc per corner: (vertex, previous ring neighbour) -> next.
    keys = vertices * num_vertices + prev_vertex
    unique_keys, first = np.unique(keys, return_index=True)
    arc_vertex = vertices[first]
    arc_prev = prev_vertex[first]
    arc_next = next_vertex[first]

    # Successor arc of the walk: the arc whose previous neighbour is this next.
    successor_keys = arc_vertex * num_vertices + arc_next
    successor = _sorted_index(unique_keys, successor_keys)

    # First arc of every vertex (arcs are sorted by vertex, then by neighbour).
    ring_start = np.searchsorted(unique_keys,
                                 np.arange(num_vertices, dtype=np.int64) * num_vertices)
    has_arc = np.zeros(num_vertices, dtype=bool)
    inside = ring_start < unique_keys.size
    has_arc[inside] = ((unique_keys[ring_start[inside]] // num_vertices) ==
                       np.flatnonzero(inside))
    ring_start = np.where(has_arc, ring_start, -1)

    # Rings are walked from one end: an arc whose previous neighbour is not the
    # next of any other arc starts a path across the boundary. Cycle vertices
    # have no such arc and start on their first one.
    heads = np.flatnonzero(~_sorted_contains(np.sort(successor_keys),
                                             arc_vertex * num_vertices + arc_prev))
    if heads.size:
        head_vertex = arc_vertex[heads]
        positions = np.searchsorted(head_vertex, np.arange(num_vertices, dtype=np.int64))
        matching = np.zeros(num_vertices, dtype=bool)
        inside = positions < heads.size
        matching[inside] = head_vertex[positions[inside]] == np.flatnonzero(inside)
        ring_start[matching] = heads[positions[matching]]

    arcs_per_vertex = np.bincount(arc_vertex, minlength=num_vertices)
    width = int(arcs_per_vertex.max()) + 1
    padded = np.full((num_vertices, width), -1, dtype=np.int32)
    ring_len = np.zeros(num_vertices, dtype=np.int64)

    current = ring_start.copy()
    active = current >= 0
    if active.any():
        # The first ring element is the previous neighbour of the start arc.
        padded[active, 0] = arc_prev[current[active]]
        ring_len[active] = 1
    seen = np.zeros(unique_keys.size, dtype=bool)
    for column in range(1, width):
        if not active.any():
            break
        step = active & ~seen[np.where(active, current, 0)]
        if not step.any():
            break
        arc_ids = current[step]
        following = successor[arc_ids]
        # A ring cycle closes when the last arc points back to the start arc;
        # a path across the boundary ends on a missing successor and still
        # contributes its last neighbour.
        keep = ~((following >= 0) & (following == ring_start[step]))
        if not keep.any():
            break
        selected = np.flatnonzero(step)[keep]
        arc_ids = arc_ids[keep]
        padded[selected, column] = arc_next[arc_ids]
        ring_len[selected] += 1
        seen[arc_ids] = True
        current[selected] = following[keep]
        active = np.zeros(num_vertices, dtype=bool)
        active[selected] = current[selected] >= 0

    ring_offsets = np.zeros(num_vertices + 1, dtype=np.int64)
    np.cumsum(ring_len, out=ring_offsets[1:])
    valid = np.arange(width, dtype=np.int64)[None, :] < ring_len[:, None]
    ring_flat = padded[valid].astype(np.int32)

    # Lookup table of every (vertex, ring neighbour) key -> ring column.
    ring_vertex = np.repeat(np.arange(num_vertices, dtype=np.int64), ring_len)
    lookup_keys = ring_vertex * num_vertices + ring_flat
    lookup_cols = (np.arange(ring_flat.size, dtype=np.int64) -
                   np.repeat(ring_offsets[:-1], ring_len))
    order = np.argsort(lookup_keys, kind="stable")
    lookup_keys = lookup_keys[order]
    lookup_cols = lookup_cols[order]

    if lookup_keys.size:
        keep = np.empty(lookup_keys.size, dtype=bool)
        keep[0] = True
        keep[1:] = lookup_keys[1:] != lookup_keys[:-1]
        lookup_keys = lookup_keys[keep]
        lookup_cols = lookup_cols[keep]

    return ring_flat, ring_offsets, lookup_keys, lookup_cols


def _lookup_ring_columns(vertices: np.ndarray,
                         neighbours: np.ndarray,
                         num_vertices: int,
                         ring_keys: np.ndarray,
                         ring_cols: np.ndarray) -> np.ndarray:
    """Resolve the ring position of ``neighbour`` for many vertex pairs at once.

    Parameters:
        vertices (numpy.ndarray): Vertex ids owning the ring to search.
        neighbours (numpy.ndarray): Neighbour ids to locate in those rings.
        num_vertices (int): Total vertex count, used to build the flat keys.
        ring_keys (numpy.ndarray): Sorted lookup keys from
            :func:`_build_vertex_ring_csr`.
        ring_cols (numpy.ndarray): Ring columns matching ``ring_keys``.

    Returns:
        numpy.ndarray: The ring column of every pair, ``-1`` when the
        neighbour is not part of the ring.
    """
    keys = vertices * num_vertices + neighbours
    positions = _sorted_index(ring_keys, keys)

    columns = np.full(keys.size, -1, dtype=np.int64)
    columns[positions >= 0] = ring_cols[positions[positions >= 0]]
    return columns


def compute_topological_symmetry_map(polygon_counts,
                                     polygon_vertices,
                                     num_vertices: int,
                                     seed_edge,
                                     stats: dict = None) -> list:
    """Map every vertex of a mesh to its topological mirror across a seam edge.

    The mapping is purely topological, so the mesh does not need to be
    geometrically symmetric. ``seed_edge`` must be an edge lying on the
    symmetry line (both of its vertices are on the mirror seam, as in Maya's
    *Topological Symmetry*), which makes the recursion deterministic: the two
    endpoints map to themselves and every ring is reflected around the already
    mapped neighbour of its parent.

    Walking a pair ``x -> y`` whose parent pair is ``px -> py``, the ring of
    ``x`` is read forward from ``px`` while the ring of ``y`` is read backward
    from ``py`` (a mirror reverses the ring order), so the matching is
    ``ring[x][(i + k) % d] <-> ring[y][(j - k) % d]`` with ``i``, ``j`` the
    ring columns of ``px`` and ``py`` and ``d`` the common ring length.

    Parameters:
        polygon_counts (sequence): Number of vertices per polygon, as returned
            by ``MFnMesh.getVertices``.
        polygon_vertices (sequence): Flattened polygon vertex ids, as returned
            by ``MFnMesh.getVertices``.
        num_vertices (int): Total vertex count of the mesh.
        seed_edge (tuple): Two vertex ids of an edge on the symmetry line.
        stats (dict, optional): When given, filled with the ``"unmapped"`` and
            ``"conflicts"`` counters.

    Returns:
        list: One entry per vertex. The entry is the opposite vertex id, the
        same index for vertices on the symmetry line and ``None`` when the
        vertex cannot be mapped (other shell, valence mismatch, conflict).

    Example:
        >>> mapping = compute_topological_symmetry_map(counts, verts, 8, (2, 3))
        >>> mapping[0]
        7
    """
    num_vertices = int(num_vertices)
    if num_vertices <= 0:
        return []
    if seed_edge is None:
        raise ValueError("seed_edge must contain exactly two vertex ids.")
    try:
        if len(seed_edge) != 2:
            raise ValueError("seed_edge must contain exactly two vertex ids.")
        seed_a, seed_b = int(seed_edge[0]), int(seed_edge[1])
    except (TypeError, IndexError) as error:
        raise ValueError("seed_edge must contain exactly two vertex ids.") from error

    if seed_a == seed_b:
        raise ValueError("seed_edge needs two different vertex ids.")
    for vertex_id in (seed_a, seed_b):
        if not 0 <= vertex_id < num_vertices:
            raise ValueError(f"Vertex id {vertex_id} is out of range "
                             f"(mesh has {num_vertices} vertices).")

    ring_flat, ring_offsets, ring_keys, ring_cols = _build_vertex_ring_csr(
        polygon_counts, polygon_vertices, num_vertices)
    ring_len = np.diff(ring_offsets)

    opposite = np.full(num_vertices, -1, dtype=np.int64)
    if ring_len[seed_a] == 0 or ring_len[seed_b] == 0:
        if stats is not None:
            stats["unmapped"] = num_vertices
            stats["conflicts"] = 0
        return [None] * num_vertices

    opposite[seed_a] = seed_a
    opposite[seed_b] = seed_b
    conflicts = 0

    # Level-synchronised BFS. Every entry is (x, y, px, py): x maps to y and
    # the parent neighbour px of x maps to the parent neighbour py of y.
    level_x = [seed_a, seed_b]
    level_y = [seed_a, seed_b]
    level_px = [seed_b, seed_a]
    level_py = [seed_b, seed_a]

    while level_x:
        columns_x = _lookup_ring_columns(
            np.asarray(level_x, dtype=np.int64),
            np.asarray(level_px, dtype=np.int64),
            num_vertices, ring_keys, ring_cols).tolist()
        columns_y = _lookup_ring_columns(
            np.asarray(level_y, dtype=np.int64),
            np.asarray(level_py, dtype=np.int64),
            num_vertices, ring_keys, ring_cols).tolist()

        next_x, next_y, next_px, next_py = [], [], [], []
        for x, y, column_x, column_y in zip(level_x, level_y, columns_x, columns_y):
            if column_x < 0 or column_y < 0:
                conflicts += 1
                continue

            ring_size = int(ring_len[x])
            if ring_size != int(ring_len[y]):
                conflicts += 1
                continue

            start_x = int(ring_offsets[x])
            start_y = int(ring_offsets[y])
            for step in range(1, ring_size):
                forward = int(ring_flat[start_x + (column_x + step) % ring_size])
                backward = int(ring_flat[start_y + (column_y - step) % ring_size])
                mapped_forward = int(opposite[forward])
                mapped_backward = int(opposite[backward])
                if mapped_forward == -1 and mapped_backward == -1:
                    opposite[forward] = backward
                    opposite[backward] = forward
                    next_x.append(forward)
                    next_y.append(backward)
                    next_px.append(x)
                    next_py.append(y)
                elif mapped_forward != backward or mapped_backward != forward:
                    conflicts += 1

        level_x, level_y, level_px, level_py = next_x, next_y, next_px, next_py

    mapped = opposite.tolist()
    result = [None if vertex_id < 0 else vertex_id for vertex_id in mapped]
    if stats is not None:
        stats["unmapped"] = sum(1 for vertex_id in mapped if vertex_id < 0)
        stats["conflicts"] = conflicts
    return result


def _resolve_seed_edge(mfn_mesh,
                       mesh_name: str,
                       edge,
                       num_vertices: int) -> tuple:
    """Resolve an edge given as id, ``"mesh.e[12]"`` string or vertex pair.

    Parameters:
        mfn_mesh (OpenMaya.MFnMesh): Mesh function set used to query edges.
        mesh_name (str): Mesh shape name owning the mesh vertices, used to
            build the edge component when only an edge id is given.
        edge (int | str | tuple | list): Edge id, edge component name or the
            two vertex ids of the edge.
        num_vertices (int): Total vertex count of the mesh.

    Returns:
        tuple: The two vertex ids of the edge.

    Example:
        >>> _resolve_seed_edge(mfn_mesh, "pCube1", "pCube1.e[4]", 8)
        (2, 3)
    """
    if isinstance(edge, (tuple, list)):
        if len(edge) != 2:
            raise ValueError("An edge must be given as two vertex ids.")
        vertex_pair = (int(edge[0]), int(edge[1]))
    elif isinstance(edge, int) and not isinstance(edge, bool):
        vertex_pair = _edge_vertices(f"{mesh_name}.e[{int(edge)}]",
                                     mfn_mesh.numEdges(), int(edge))
    elif isinstance(edge, str):
        component = edge.rsplit(".", 1)[-1]
        if "[" not in component or "]" not in component:
            raise ValueError(f"'{edge}' is not an edge component name.")
        edge_id = int(component[component.index("[") + 1:component.index("]")])
        node_name = edge.rsplit(".", 1)[0] if "." in edge else mesh_name
        vertex_pair = _edge_vertices(f"{node_name}.e[{edge_id}]",
                                     mfn_mesh.numEdges(), edge_id)
    else:
        raise ValueError("edge must be an edge id, an edge component name or "
                         "a pair of vertex ids.")

    if vertex_pair[0] == vertex_pair[1]:
        raise ValueError(f"Edge {edge} resolves to a single vertex id.")
    for vertex_id in vertex_pair:
        if not 0 <= vertex_id < num_vertices:
            raise ValueError(f"Edge {edge} resolves to vertex id {vertex_id}, "
                             f"outside the mesh vertex range.")
    return vertex_pair


def _edge_vertices(edge_component: str, num_edges: int, edge_id: int) -> tuple:
    """Get the two vertex ids of an edge through a component conversion.

    ``MFnMesh.getEdgeVertices`` is bound in the Maya API 1.0 Python wrapper as
    ``getEdgeVertices(index, int2&)`` and therefore refuses ``MIntArray``
    (``TypeError: argument 3 of type 'int2 &'``). Converting the edge component
    to vertices avoids the ``int2`` pointer dance and works for every Maya
    version this package supports.

    Parameters:
        edge_component (str): Edge component name, e.g. ``"pCube1.e[12]"``.
        num_edges (int): Total edge count of the mesh, used for validation.
        edge_id (int): Index of the edge in the mesh.

    Returns:
        tuple: The two vertex ids of the edge.

    Example:
        >>> _edge_vertices("pCube1.e[4]", 12, 4)
        (2, 3)
    """
    if not 0 <= edge_id < num_edges:
        raise ValueError(f"Edge index {edge_id} is out of range "
                         f"(mesh has {num_edges} edges).")

    try:
        converted = cmds.polyListComponentConversion(edge_component,
                                                     fromEdge=True,
                                                     toVertex=True)
    except RuntimeError as error:
        raise ValueError(f"Could not resolve edge '{edge_component}': {error}") from error
    vertex_components = cmds.ls(converted, flatten=True) or []

    vertex_ids = []
    for vertex_component in vertex_components:
        if ".vtx[" not in vertex_component:
            continue
        start = vertex_component.index(".vtx[") + len(".vtx[")
        vertex_ids.append(int(vertex_component[start:vertex_component.index("]")]))

    if len(vertex_ids) != 2:
        raise ValueError(f"Edge '{edge_component}' resolves to "
                         f"{len(vertex_ids)} vertices instead of 2.")
    return vertex_ids[0], vertex_ids[1]


def _get_active_edge() -> str:
    """Get the first selected edge component name.

    Returns:
        str: The edge component name, e.g. ``"pCube1.e[12]"``.

    Raises:
        ValueError: When the current selection contains no edge.
    """
    for item in cmds.ls(selection=True, flatten=True) or []:
        if ".e[" in item:
            return item
    raise ValueError("No edge in the current selection: select a symmetry "
                     "edge or pass one explicitly.")


def _resolve_mesh_shape_name(mesh_name: str) -> str:
    """Resolve a mesh transform name to the name of its mesh shape.

    Parameters:
        mesh_name (str): Mesh shape or transform name.

    Returns:
        str: The mesh shape name, unchanged when one was given.

    Raises:
        ValueError: When the node does not exist or owns no mesh shape.

    Example:
        >>> _resolve_mesh_shape_name("head_geo")
        'head_geoShape'
    """
    if not cmds.objExists(mesh_name):
        raise ValueError(f"Node '{mesh_name}' does not exist.")
    if cmds.nodeType(mesh_name) == "mesh":
        return mesh_name

    shapes = cmds.listRelatives(mesh_name, shapes=True, noIntermediate=True) or []
    for shape in shapes:
        if cmds.nodeType(shape) == "mesh":
            return shape
    raise ValueError(f"Node '{mesh_name}' owns no mesh shape.")


def get_mesh_topological_symmetry_map(mesh_name: str, edge=None) -> list:
    """Map the vertices of a mesh to their topological mirror across an edge.

    The edge must lie on the symmetry line of the mesh (both endpoints on the
    mirror seam), matching Maya's *Topological Symmetry* workflow. The mapping
    is purely topological and therefore also works on meshes that are not
    geometrically symmetric. Middle line vertices map to themselves and
    vertices that cannot be mapped (other mesh shells, valence mismatches,
    conflicting windings) map to ``None``; a warning summarises those.

    Parameters:
        mesh_name (str): Mesh shape or mesh transform name.
        edge (int | str | tuple | list, optional): Edge id, edge component name
            such as ``"pCube1.e[12]"`` or ``(vertex_a, vertex_b)``. When
            ``None``, the first selected edge is used.

    Returns:
        list: One entry per vertex: the opposite vertex id, the same index for
        vertices on the symmetry line and ``None`` for unmapped vertices.

    Example:
        >>> mapping = get_mesh_topological_symmetry_map("head", "head.e[128]")
        >>> mapping[0]
        1274
    """
    if edge is None:
        edge = _get_active_edge()

    mesh_name = _resolve_mesh_shape_name(mesh_name)
    mfn_mesh = create_mfn_mesh(mesh_name)
    num_vertices = mfn_mesh.numVertices()
    if num_vertices == 0:
        cmds.warning(f"Mesh '{mesh_name}' has no vertices to map.")
        return []

    polygon_counts = om.MIntArray()
    polygon_vertices = om.MIntArray()
    mfn_mesh.getVertices(polygon_counts, polygon_vertices)

    seed_edge = _resolve_seed_edge(mfn_mesh, mesh_name, edge, num_vertices)
    stats = {}
    mapping = compute_topological_symmetry_map(list(polygon_counts),
                                               list(polygon_vertices),
                                               num_vertices,
                                               seed_edge,
                                               stats=stats)

    unmapped = stats.get("unmapped", 0)
    conflicts = stats.get("conflicts", 0)
    if unmapped or conflicts:
        cmds.warning(f"Topological symmetry from edge "
                     f"{seed_edge[0]}-{seed_edge[1]} on '{mesh_name}' is not "
                     f"exact: {unmapped} of {num_vertices} vertices could not "
                     f"be mapped ({conflicts} conflicts).")
    return mapping

# ----------------------------------------------------------------------
# Blendshape weight map mirroring
# ----------------------------------------------------------------------
class MirrorAction(str, Enum):
    """Operation applied to a blendShape weight map.

    Members compare equal to their plain string value, so ``MirrorAction.FLIP
    == "flip"`` holds and MEL or UI callers can keep passing strings.
    """

    MIRROR = "mirror"
    """Copy the source side onto the destination side."""

    FLIP = "flip"
    """Swap the two sides of the axis."""

    def __str__(self) -> str:
        return self.value


class MirrorAxis(str, Enum):
    """Object-space axis a mirror is performed across."""

    X = "x"
    Y = "y"
    Z = "z"

    def __str__(self) -> str:
        return self.value


class MirrorDirection(str, Enum):
    """Side of the axis a mirror copies its values from.

    ``LEFT_TO_RIGHT`` means the negative side of the axis is the source side,
    matching :mod:`blue_steel.mmtools.mirror_tools` (``L>>R``).
    """

    LEFT_TO_RIGHT = "left_to_right"
    RIGHT_TO_LEFT = "right_to_left"

    def __str__(self) -> str:
        return self.value


class MirrorMapping(str, Enum):
    """Source of the vertex pairing a mirror works on.

    ``GEOMETRIC`` pairs every vertex with the nearest vertex to its reflected
    position and therefore only needs the mesh to be symmetric in shape.
    ``TOPOLOGICAL`` pairs the vertices through the topological symmetry map of
    a seam edge, like Maya's *Topological Symmetry*, so it also works on
    meshes that are only symmetric in topology.
    """

    GEOMETRIC = "geometric"
    """Nearest geometric mirror within the match tolerance."""

    TOPOLOGICAL = "topological"
    """Topological symmetry map grown from a seam edge."""

    def __str__(self) -> str:
        return self.value


MIRROR_AXES = tuple(axis.value for axis in MirrorAxis)
"""Object-space axes usable as mirror axis, in coordinate order."""

MIRROR_MAPPINGS = tuple(mapping.value for mapping in MirrorMapping)
"""Vertex pairing sources supported by the weight map mirror."""

DEFAULT_MIRROR_BLEND_FALLOFF = 0.2
"""Default mirror blend falloff, as a fraction of the bbox extent."""

DEFAULT_MIRROR_TOLERANCE = 0.001
"""Default vertex match tolerance, in object space units."""

_MIRROR_DIRECTION_ALIASES = {
    # Left is the negative side of the axis, as in the mirror tools.
    "left_to_right": True,
    "l_to_r": True,
    "l>>r": True,
    "negative_to_positive": True,
    "negative": True,
    "right_to_left": False,
    "r_to_l": False,
    "l<<r": False,
    "positive_to_negative": False,
    "positive": False,
}


def _coerce_action(action=MirrorAction.MIRROR) -> MirrorAction:
    """Normalize an action given as enum member or string.

    Parameters:
        action (MirrorAction | str): Action to normalize.

    Returns:
        MirrorAction: The matching enum member.

    Raises:
        ValueError: If the action is not ``"mirror"`` or ``"flip"``.

    Example:
        >>> _coerce_action("FLIP")
        <MirrorAction.FLIP: 'flip'>
    """
    if isinstance(action, MirrorAction):
        return action
    if isinstance(action, str):
        normalized = action.strip().lower()
        for member in MirrorAction:
            if member.value == normalized:
                return member
    accepted = " or ".join(repr(member.value) for member in MirrorAction)
    raise ValueError(f"Unsupported mirror action {action!r}: use {accepted}.")


def _coerce_mapping(mapping=MirrorMapping.GEOMETRIC) -> MirrorMapping:
    """Normalize a vertex pairing source given as enum member or string.

    Parameters:
        mapping (MirrorMapping | str): Pairing source to normalize.

    Returns:
        MirrorMapping: The matching enum member.

    Raises:
        ValueError: If the mapping is not ``"geometric"`` or
            ``"topological"``.

    Example:
        >>> _coerce_mapping(" TOPOLOGICAL ")
        <MirrorMapping.TOPOLOGICAL: 'topological'>
    """
    if isinstance(mapping, MirrorMapping):
        return mapping
    if isinstance(mapping, str):
        normalized = mapping.strip().lower()
        for member in MirrorMapping:
            if member.value == normalized:
                return member
    accepted = " or ".join(repr(member.value) for member in MirrorMapping)
    raise ValueError(f"Unsupported mirror mapping {mapping!r}: use {accepted}.")


def _mirror_axis_index(axis=MirrorAxis.X) -> int:
    """Return the coordinate index of a mirror axis.

    Parameters:
        axis (MirrorAxis | str): Axis to resolve, in any case.

    Returns:
        int: ``0`` for X, ``1`` for Y and ``2`` for Z.

    Raises:
        ValueError: If the axis is not X, Y or Z.

    Example:
        >>> _mirror_axis_index("Y")
        1
        >>> _mirror_axis_index(MirrorAxis.Z)
        2
    """
    name = axis.value if isinstance(axis, MirrorAxis) else axis
    if isinstance(name, str) and name.strip().lower() in MIRROR_AXES:
        return MIRROR_AXES.index(name.strip().lower())
    raise ValueError(f"Unsupported mirror axis {axis!r}: use 'x', 'y' or 'z'.")


def _resolve_mirror_direction(mirror_direction=MirrorDirection.LEFT_TO_RIGHT) -> bool:
    """Resolve the side of the axis a mirror copies its values from.

    ``"left"`` is the negative side of the axis and ``"right"`` the positive
    one, matching :mod:`blue_steel.mmtools.mirror_tools` (``L>>R`` keeps the
    negative side, ``L<<R`` the positive one).

    Parameters:
        mirror_direction (MirrorDirection | str | bool): Direction to resolve.
            Besides the enum members, the spellings
            ``left_to_right``/``l_to_r``/``l>>r``/``negative_to_positive``/
            ``negative`` and ``right_to_left``/``r_to_l``/``l<<r``/
            ``positive_to_negative``/``positive`` are accepted, in any case
            and with optional spaces or dashes. A boolean is used as is.

    Returns:
        bool: ``True`` when the negative side of the axis is the source side
        (``L>>R``), ``False`` when the positive side is (``L<<R``).

    Raises:
        ValueError: If the direction is not a known spelling.

    Example:
        >>> _resolve_mirror_direction(MirrorDirection.RIGHT_TO_LEFT)
        False
        >>> _resolve_mirror_direction("l>>r")
        True
    """
    if isinstance(mirror_direction, bool):
        return mirror_direction
    if isinstance(mirror_direction, MirrorDirection):
        normalized = mirror_direction.value
    elif isinstance(mirror_direction, str):
        normalized = mirror_direction.strip().lower().replace(" ", "").replace("-", "_")
    else:
        normalized = None

    source_is_negative = _MIRROR_DIRECTION_ALIASES.get(normalized)
    if source_is_negative is None:
        raise ValueError(f"Unsupported mirror direction "
                         f"{mirror_direction!r}: use "
                         f"{MirrorDirection.LEFT_TO_RIGHT.value!r} or "
                         f"{MirrorDirection.RIGHT_TO_LEFT.value!r}.")
    return source_is_negative


def compute_geometric_symmetry_map(points,
                                   axis=MirrorAxis.X,
                                   tolerance: float = DEFAULT_MIRROR_TOLERANCE,
                                   symmetry_centre: float = None) -> np.ndarray:
    """Pair every vertex of a mesh with its geometric mirror counterpart.

    The pairing happens in object space: each vertex is reflected across the
    plane perpendicular to ``axis`` that goes through ``symmetry_centre`` and
    the closest vertex to that reflected position is used as its mirror. Only
    vertices whose distance to the reflected position stays within
    ``tolerance`` are paired, so the result is exact for symmetric meshes and
    keeps border or asymmetric vertices unmapped instead of pairing them with
    an unrelated vertex.

    The search is fully vectorized: the axis coordinates are sorted once and
    every vertex gets a candidate window through ``numpy.searchsorted``, which
    reduces the nearest-neighbour search to the two remaining axes. Candidate
    pairs are processed in bounded blocks, so the memory use does not grow
    with the mesh size.

    Parameters:
        points (numpy.ndarray | sequence): ``(N, 3)`` object-space vertex
            positions, one row per vertex. A fourth column is ignored.
        axis (MirrorAxis | str): Mirror axis, ``x`` (default), ``y`` or ``z``.
        tolerance (float, optional): Maximum distance, in object units,
            between a vertex and the reflected position of its counterpart.
            Defaults to :data:`DEFAULT_MIRROR_TOLERANCE` (``0.001``), which
            suits the centimetre-scale meshes the tools target; pass a
            smaller value for meshes modelled at a much smaller scale.
        symmetry_centre (float, optional): Axis coordinate of the mirror
            plane. Defaults to the centre of the bounding box along ``axis``.

    Returns:
        numpy.ndarray: One int64 vertex id per vertex, the source vertex id
        of its mirror pair, the vertex itself when it sits on the mirror plane
        and ``-1`` when no counterpart is within ``tolerance``.

    Raises:
        ValueError: If ``points`` is not an ``(N, 3)`` array, if the axis is
            not X, Y or Z, if the mesh has no extent along the axis or if
            ``tolerance`` is not positive.

    Example:
        >>> points = np.array([[-1.0, 0.0, 0.0], [1.0, 0.0, 0.0]])
        >>> compute_geometric_symmetry_map(points, "x")
        array([1, 0])
    """
    points = np.asarray(points, dtype=np.float64)
    if points.ndim != 2 or points.shape[1] < 3:
        raise ValueError("points must be an (N, 3) array of object-space "
                         "vertex positions.")
    points = points[:, :3]
    axis_index = _mirror_axis_index(axis)
    num_vertices = points.shape[0]
    opposite = np.full(num_vertices, -1, dtype=np.int64)
    if num_vertices < 2:
        return opposite

    coordinates = points[:, axis_index]
    coordinate_min = float(coordinates.min())
    coordinate_max = float(coordinates.max())
    if coordinate_max - coordinate_min <= 0.0:
        raise ValueError(f"The mesh has no extent along the "
                         f"{MIRROR_AXES[axis_index].upper()} axis: pick "
                         f"another mirror axis.")
    if symmetry_centre is None:
        symmetry_centre = (coordinate_min + coordinate_max) / 2.0
    else:
        symmetry_centre = float(symmetry_centre)

    if tolerance is None:
        tolerance = DEFAULT_MIRROR_TOLERANCE
    tolerance = float(tolerance)
    if not tolerance > 0.0:
        raise ValueError("tolerance must be a positive distance.")

    # Sorted axis coordinates give every vertex a bounded candidate window:
    # a counterpart can only be inside it if its axis coordinate matches the
    # reflected coordinate within the tolerance.
    order = np.argsort(coordinates, kind="stable")
    sorted_coordinates = coordinates[order]
    other_axes = [index for index in range(3) if index != axis_index]
    sorted_other = points[order][:, other_axes]
    mirrored_other = points[:, other_axes]
    mirrored_coordinates = 2.0 * symmetry_centre - coordinates
    tolerance_squared = tolerance * tolerance

    block_size = 1024
    # Upper bound of candidate pairs evaluated in one array operation.
    pair_budget = 1 << 21

    for block_start in range(0, num_vertices, block_size):
        block_stop = min(block_start + block_size, num_vertices)
        block_mirrored = mirrored_coordinates[block_start:block_stop]
        window_low = np.searchsorted(sorted_coordinates,
                                     block_mirrored - tolerance,
                                     side="left")
        window_high = np.searchsorted(sorted_coordinates,
                                      block_mirrored + tolerance,
                                      side="right")
        window_size = window_high - window_low
        if window_size.size == 0 or not window_size.any():
            continue

        # Dense windows of large meshes are split again to keep the temporary
        # (block x window) arrays small.
        chunk_size = max(1, pair_budget // max(int(window_size.max()), 1))
        for chunk_start in range(block_start, block_stop, chunk_size):
            chunk_stop = min(chunk_start + chunk_size, block_stop)
            offset = chunk_start - block_start
            local_size = window_size[offset:offset + chunk_stop - chunk_start]
            local_max = int(local_size.max())
            if local_max <= 0:
                continue

            columns = (window_low[offset:offset + chunk_stop - chunk_start, None]
                       + np.arange(local_max, dtype=np.int64)[None, :])
            active = np.arange(local_max, dtype=np.int64)[None, :] < local_size[:, None]
            np.minimum(columns, num_vertices - 1, out=columns)
            candidates = order[columns]

            chunk_mirrored = mirrored_other[chunk_start:chunk_stop]
            delta_axis = (sorted_coordinates[columns]
                          - block_mirrored[offset:offset + chunk_stop - chunk_start, None])
            delta_x = sorted_other[columns, 0] - chunk_mirrored[:, 0][:, None]
            delta_y = sorted_other[columns, 1] - chunk_mirrored[:, 1][:, None]
            distances = (delta_axis * delta_axis
                         + delta_x * delta_x + delta_y * delta_y)
            distances = np.where(active, distances, np.inf)

            best = np.argmin(distances, axis=1)
            best_distances = distances[np.arange(best.size), best]
            found = best_distances <= tolerance_squared
            if not found.any():
                continue

            chunk_opposite = opposite[chunk_start:chunk_stop]
            chunk_opposite[found] = candidates[found, best[found]]

    return opposite


def compute_mirror_falloff_weights(coordinates,
                                   minimum: float,
                                   maximum: float,
                                   mirror_direction=MirrorDirection.LEFT_TO_RIGHT,
                                   band_fraction: float = None) -> np.ndarray:
    """Build the per-vertex mirror weight of a bounding box gradient.

    The symmetry plane is the centre of the bounding box along the mirror
    axis. Vertices on the source side get ``0``, vertices on the destination
    side get ``1`` and a smoothstep band centred on the plane blends the two.
    The band width is ``band_fraction`` of the bounding box extent, so ``0``
    produces a hard split and ``1`` a gradient across the whole mesh.

    ``blue_steel.mmtools.mirror_tools.gradient_weights`` is the list based
    twin of this function; it cannot be reused here because ``mirror_tools``
    imports this module itself. That twin takes the band as a percentage, so
    call it with ``band_percent=band_fraction * 100``.

    This function performs no Maya calls, which keeps the mirror math testable
    outside Maya.

    Parameters:
        coordinates (sequence | numpy.ndarray): Coordinate of every vertex
            along the mirror axis, in object space.
        minimum (float): Lowest coordinate of the bounding box.
        maximum (float): Highest coordinate of the bounding box.
        mirror_direction (MirrorDirection | str | bool): Side the values are
            copied from. ``"left"`` is the negative side of the axis, so
            ``MirrorDirection.LEFT_TO_RIGHT`` keeps the negative side and
            writes towards the positive one.
        band_fraction (float, optional): Width of the transition band as a
            fraction of ``maximum - minimum``, clamped to ``0..1``. Defaults to
            :data:`DEFAULT_MIRROR_BLEND_FALLOFF` (``0.2``, i.e. 20%).

    Returns:
        numpy.ndarray: One mirror weight between ``0`` and ``1`` per
        coordinate, in the same order as ``coordinates``.

    Raises:
        ValueError: If the bounding box has no extent along the axis or the
            direction is unknown.

    Example:
        >>> compute_mirror_falloff_weights([-1.0, 0.0, 1.0], -1.0, 1.0,
        ...                               MirrorDirection.LEFT_TO_RIGHT, 0.0)
        array([0. , 0.5, 1. ])
    """
    coordinates = np.asarray(coordinates, dtype=np.float64).ravel()
    minimum = float(minimum)
    maximum = float(maximum)
    width = maximum - minimum
    if width <= 0.0:
        raise ValueError("The mesh has no extent along the mirror axis; pick "
                         "another axis or offset the mesh.")

    source_is_negative = _resolve_mirror_direction(mirror_direction)
    if band_fraction is None:
        band_fraction = DEFAULT_MIRROR_BLEND_FALLOFF
    band = width * min(max(float(band_fraction), 0.0), 1.0)
    half_band = band / 2.0

    # The weight has to grow towards the destination side: towards +axis when
    # the negative side is the source and towards -axis otherwise.
    direction = 1.0 if source_is_negative else -1.0
    offset = coordinates - (minimum + maximum) / 2.0

    if half_band <= 0.0:
        # Hard split. Seam vertices shared by both sides stay neutral.
        weights = np.where(offset * direction > 0.0, 1.0, 0.0)
        weights[offset == 0.0] = 0.5
        return weights

    ramp = np.clip((direction * offset / half_band + 1.0) / 2.0, 0.0, 1.0)
    return ramp * ramp * (3.0 - 2.0 * ramp)


def compute_symmetrized_mirror_coordinates(coordinates,
                                          mapping,
                                          symmetry_centre: float = None) -> np.ndarray:
    """Move every vertex pair onto a symmetric position along the mirror axis.

    The falloff of a mirror is read from the axis coordinates of the vertices,
    which assumes that a pair sits at the same distance on both sides of the
    symmetry plane. A topological pairing only guarantees that, so the
    coordinates are symmetrized here before they feed
    :func:`compute_mirror_falloff_weights`: every pair ``(i, j)`` receives the
    mean of its two distances to the plane, signed by the side of the vertex,
    so both members end up mirrored around the plane even when the mesh is
    asymmetric.

    Vertices without a counterpart are filtered out: they keep their raw
    coordinate and cannot influence the result, because
    :func:`mirror_weight_map_values` leaves them untouched anyway.

    This function performs no Maya calls, which keeps the mirror math testable
    outside Maya.

    Parameters:
        coordinates (sequence | numpy.ndarray): Coordinate of every vertex
            along the mirror axis, in object space.
        mapping (sequence | numpy.ndarray): One counterpart vertex id per
            vertex, ``-1`` or ``None`` for vertices without a counterpart.
        symmetry_centre (float, optional): Axis coordinate of the mirror plane.
            Defaults to the centre of the coordinate bounding box, i.e. the
            plane :func:`compute_mirror_falloff_weights` splits on.

    Returns:
        numpy.ndarray: One symmetrized coordinate per vertex, in the same order
        as ``coordinates``.

    Raises:
        ValueError: If ``mapping`` and ``coordinates`` have different lengths
            or if ``mapping`` contains vertex ids outside the vertex range.

    Example:
        >>> compute_symmetrized_mirror_coordinates(
        ...     [-0.9, 1.1], [1, 0], 0.0)
        array([-1. ,  1. ])
    """
    coordinates = np.asarray(coordinates, dtype=np.float64).ravel()
    num_vertices = coordinates.size

    if np.any([entry is None for entry in mapping]):
        mapping = [-1 if entry is None else entry for entry in mapping]
    mapping = np.asarray(mapping, dtype=np.int64).ravel()
    if mapping.size != num_vertices:
        raise ValueError(f"mapping has {mapping.size} entries but there are "
                         f"{num_vertices} coordinates.")
    if num_vertices and not np.all((mapping >= -1) & (mapping < num_vertices)):
        raise ValueError("mapping contains vertex ids outside the mesh "
                         f"vertex range (0..{num_vertices - 1}).")

    if symmetry_centre is None:
        centre = (float(coordinates.min()) + float(coordinates.max())) / 2.0
    else:
        centre = float(symmetry_centre)

    offsets = coordinates - centre
    paired = mapping >= 0
    symmetrized = coordinates.copy()
    if paired.any():
        pair_offsets = offsets[mapping[paired]]
        magnitudes = (np.abs(offsets[paired]) + np.abs(pair_offsets)) / 2.0
        # Both members of a pair get the same distance on their own side of
        # the plane, so the falloff fades symmetrically across it.
        signs = np.where(offsets[paired] < 0.0, -1.0, 1.0)
        symmetrized[paired] = centre + signs * magnitudes
    return symmetrized


MIRROR_ACTIONS = tuple(action.value for action in MirrorAction)
"""String values of the actions supported by :func:`mirror_weight_map_values`."""


def mirror_weight_map_values(values,
                            mapping,
                            falloff=None,
                            action=MirrorAction.MIRROR) -> np.ndarray:
    """Mirror or flip a per-vertex weight map along a vertex mapping.

    ``mapping`` comes from :func:`compute_geometric_symmetry_map` or from
    :func:`get_mesh_topological_symmetry_map`: entry ``i`` is the vertex whose
    value vertex ``i`` receives. Vertices mapped to ``-1`` keep their value.

    ``MirrorAction.MIRROR`` copies the source side onto the destination side
    and leaves the source side untouched, blending the two inside the falloff
    band. ``MirrorAction.FLIP`` swaps both sides, so the band fades the swap to
    a half/half mix on the mirror plane instead of fading it to nothing.

    This function performs no Maya calls and never mutates ``values``.

    Parameters:
        values (sequence | numpy.ndarray): One weight per mesh vertex.
        mapping (sequence | numpy.ndarray): One source vertex id per vertex,
            ``-1`` for unmapped vertices.
        falloff (sequence | numpy.ndarray, optional): One blend factor between
            ``0`` (keep the current value) and ``1`` (take the mirrored value)
            per vertex. Defaults to ``1`` for every vertex, i.e. a full copy.
        action (MirrorAction | str): ``MirrorAction.MIRROR`` to copy one side
            onto the other, ``MirrorAction.FLIP`` to swap both sides.

    Returns:
        numpy.ndarray: The new weight map as float64.

    Raises:
        ValueError: If the action is unknown, if the arrays have different
            lengths or if ``mapping`` contains an out of range vertex id.

    Example:
        >>> mirror_weight_map_values([0.0, 1.0], [1, 0], [0.0, 1.0],
        ...                          MirrorAction.MIRROR)
        array([0., 0.])
    """
    action = _coerce_action(action)

    values = np.array(values, dtype=np.float64, copy=True).ravel()
    mapping = np.asarray(mapping, dtype=np.int64).ravel()
    if mapping.size != values.size:
        raise ValueError(f"mapping has {mapping.size} entries but the weight "
                         f"map has {values.size}.")

    num_vertices = values.size
    in_range = (mapping >= 0) & (mapping < num_vertices)
    if not np.all((mapping >= -1) & (mapping < num_vertices)):
        raise ValueError("mapping contains vertex ids outside the mesh "
                         f"vertex range (0..{num_vertices - 1}).")

    if falloff is None:
        falloff = np.ones(num_vertices, dtype=np.float64)
    else:
        falloff = np.asarray(falloff, dtype=np.float64).ravel()
        if falloff.size != num_vertices:
            raise ValueError(f"falloff has {falloff.size} entries but the "
                             f"weight map has {num_vertices}.")
        falloff = np.clip(falloff, 0.0, 1.0)

    swappable = np.zeros(num_vertices, dtype=np.int64)
    swappable[in_range] = mapping[in_range]
    mirrored = np.where(in_range, values[swappable], values)

    if action == MirrorAction.FLIP:
        # Swap on both sides: the band blends to a half/half mix on the seam
        # instead of fading the swap out.
        falloff = np.maximum(falloff, 1.0 - falloff)

    return values + (mirrored - values) * falloff


def _resolve_weight_ids(blendshape_name: str, weight_id=None) -> list:
    """Resolve the target weight ids a weight map operation works on.

    Parameters:
        blendshape_name (str): BlendShape node name.
        weight_id (None | int | str | blue_steel.api.blendshape.Weight):
            ``None`` selects every ``inputTargetGroup`` of the node, an int is
            used as is, a ``Weight`` contributes its ``id`` and a plain string
            is looked up in the weight aliases.

    Returns:
        list[int]: One target id per weight map to process.

    Raises:
        ValueError: If the node has no weight map or the id cannot be
            resolved.

    Example:
        >>> _resolve_weight_ids("blendShape1", 2)
        [2]
    """
    if weight_id is None:
        groups = cmds.getAttr(f"{blendshape_name}.inputTarget[0].inputTargetGroup",
                              multiIndices=True) or []
        weight_ids = [int(group) for group in groups]
        if not weight_ids:
            raise ValueError(f"Blendshape '{blendshape_name}' has no target "
                             f"weight maps to mirror.")
        return weight_ids

    if isinstance(weight_id, bool):
        raise ValueError("weight_id must be a weight id, a weight name or "
                         "None to mirror every weight map.")

    if isinstance(weight_id, int):
        resolved_id = weight_id
    else:
        resolved_id = getattr(weight_id, "id", None)
        if resolved_id is not None:
            resolved_id = int(resolved_id)
        elif isinstance(weight_id, str):
            aliases = cmds.listAttr(f"{blendshape_name}.weight", multi=True) or []
            if weight_id not in aliases:
                raise ValueError(f"'{weight_id}' is not a weight of "
                                 f"blendshape '{blendshape_name}'.")
            resolved_id = aliases.index(weight_id)
        else:
            raise ValueError(f"Unsupported weight id {weight_id!r}.")

    weight_ids = [int(group) for group in
                  cmds.getAttr(f"{blendshape_name}.inputTarget[0].inputTargetGroup",
                               multiIndices=True) or []]
    if resolved_id not in weight_ids:
        raise ValueError(f"Weight id {resolved_id} of '{blendshape_name}' has "
                         f"no weight map (existing weight maps: "
                         f"{weight_ids or 'none'}).")
    return [resolved_id]


def _weight_map_attribute(blendshape_name: str, weight_id: int,
                          num_vertices: int) -> str:
    """Build the ``targetWeights`` attribute path of a weight map.

    Parameters:
        blendshape_name (str): BlendShape node name.
        weight_id (int): Target logical index owning the weight map.
        num_vertices (int): Number of vertices of the base mesh.

    Returns:
        str: Attribute path covering every vertex of the weight map.

    Example:
        >>> _weight_map_attribute("blendShape1", 0, 8)
        'blendShape1.inputTarget[0].inputTargetGroup[0].targetWeights[0:7]'
    """
    return (f"{blendshape_name}.inputTarget[0].inputTargetGroup[{weight_id}]"
            f".targetWeights[0:{num_vertices - 1}]")


def _get_weight_map_values(blendshape_name: str, weight_id: int,
                           num_vertices: int) -> np.ndarray:
    """Read a ``targetWeights`` weight map of a blendShape node.

    Parameters:
        blendshape_name (str): BlendShape node name.
        weight_id (int): Target logical index owning the weight map.
        num_vertices (int): Number of vertices of the base mesh.

    Returns:
        numpy.ndarray: One weight per vertex, all ``1.0`` when the map was
        never painted (same fallback as ``Blendshape.get_weight_map_values``).
    """
    values = cmds.getAttr(_weight_map_attribute(blendshape_name, weight_id,
                                               num_vertices))
    if not values:
        return np.ones(num_vertices, dtype=np.float64)

    values = np.asarray(values, dtype=np.float64).ravel()
    if values.size != num_vertices:
        raise ValueError(f"Weight map {weight_id} of '{blendshape_name}' has "
                         f"{values.size} values but the base mesh has "
                         f"{num_vertices} vertices.")
    return values


def _set_weight_map_values(blendshape_name: str, weight_id: int,
                           values: np.ndarray):
    """Write a ``targetWeights`` weight map of a blendShape node.

    Parameters:
        blendshape_name (str): BlendShape node name.
        weight_id (int): Target logical index owning the weight map.
        values (numpy.ndarray): One weight per vertex of the base mesh.
    """
    values = np.asarray(values, dtype=np.float64).ravel()
    attribute = _weight_map_attribute(blendshape_name, weight_id, values.size)
    connections = cmds.listConnections(f"{attribute.rsplit('[', 1)[0]}[0]",
                                      source=True,
                                      destination=False) or []
    if connections:
        raise ValueError(f"Weight map {weight_id} of '{blendshape_name}' is "
                         f"connected from '{connections[0]}': disconnect the "
                         f"weight map before mirroring it.")
    cmds.setAttr(attribute, *values.tolist(), size=values.size)


def _get_sculpt_target_ids(blendshape_name: str) -> list:
    """Return the ``sculptTargetIndex`` values of a blendShape node.

    Mirrors ``Blendshape.get_sculpt_target_indices`` without importing the
    ``blendshape`` module, which already imports this one.

    Parameters:
        blendshape_name (str): BlendShape node name.

    Returns:
        list[int]: One index per ``inputTarget`` element, ``-1`` when the
        target is not in sculpt mode.
    """
    sculpt_ids = []
    input_target_plug = get_plug(blendshape_name, "inputTarget")
    for index in range(input_target_plug.numElements()):
        target_item_plug = input_target_plug.elementByPhysicalIndex(index)
        for child_index in range(target_item_plug.numChildren()):
            child_plug = target_item_plug.child(child_index)
            if child_plug.name().endswith("sculptTargetIndex"):
                sculpt_ids.append(child_plug.asInt())
    return sculpt_ids


@undoable
def mirror_blendshape_weight_map(mesh_name: str,
                                 blendshape_name: str,
                                 weight_id=None,
                                 action=MirrorAction.MIRROR,
                                 mirror_axis=MirrorAxis.X,
                                 mirror_direction=MirrorDirection.LEFT_TO_RIGHT,
                                 mirror_blend_falloff: float = None,
                                 tolerance: float = DEFAULT_MIRROR_TOLERANCE,
                                 symmetry_centre: float = None,
                                 mapping=MirrorMapping.GEOMETRIC,
                                 symmetry_edge=None) -> dict:
    """Mirror or flip the weight map of a blendShape target in object space.

    Every vertex of ``mesh_name`` is paired with its counterpart across the
    bounding box centre of ``mirror_axis``. ``mapping`` selects how that
    pairing is found: ``MirrorMapping.GEOMETRIC`` (default) uses
    :func:`compute_geometric_symmetry_map` and only needs a symmetric shape,
    ``MirrorMapping.TOPOLOGICAL`` uses
    :func:`get_mesh_topological_symmetry_map` on ``symmetry_edge``, which also
    works on meshes that are only symmetric in topology. The weight maps are
    then read with one ``getAttr`` and written with one ``setAttr`` per map,
    which keeps high resolution meshes fast.

    ``"mirror"`` copies the values of the source side onto the other side and
    leaves the source side untouched. ``"flip"`` swaps both sides.
    ``mirror_blend_falloff`` blends the operation across a smoothstep band
    centred on the symmetry plane, expressed as a fraction of the bounding
    box extent along the axis (``0`` = hard split). The topological pairing
    describes the pairs of an asymmetric mesh more reliably, so its falloff is
    read from the symmetrized positions of the pairs (see
    :func:`compute_symmetrized_mirror_coordinates`) instead of the raw vertex
    coordinates; unpaired vertices are filtered out of that computation and
    keep their weight values.

    Parameters:
        mesh_name (str): Mesh transform or shape whose vertex order defines
            the weight maps. It has to be the base mesh of ``blendshape_name``.
        blendshape_name (str): BlendShape node owning the weight maps.
        weight_id (None | int | str | Weight): Target logical index of the
            weight map. ``None`` mirrors every ``inputTargetGroup`` weight map
            of the node; a weight name (or ``Weight``) is accepted as well.
        action (MirrorAction | str): ``MirrorAction.MIRROR`` (default) or
            ``MirrorAction.FLIP``. The ``"mirror"``/``"flip"`` strings are
            accepted too.
        mirror_axis (MirrorAxis | str): Mirror axis, ``MirrorAxis.X``
            (default), ``"y"`` or ``"z"``. It is required by both mappings:
            the topological one needs it to place the falloff band.
        mirror_direction (MirrorDirection | str): Side the values are copied
            from. ``MirrorDirection.LEFT_TO_RIGHT`` (default) keeps the
            negative side of the axis and writes towards the positive one,
            ``MirrorDirection.RIGHT_TO_LEFT`` does the opposite. The
            ``l>>r``/``l<<r`` spellings are accepted too.
        mirror_blend_falloff (float, optional): Width of the transition band as
            a fraction of the bounding box extent along the axis, clamped to
            ``0..1``. Defaults to :data:`DEFAULT_MIRROR_BLEND_FALLOFF`
            (``0.2``, i.e. 20%).
        tolerance (float, optional): Maximum distance between a vertex and the
            reflected position of its counterpart, in object units. Defaults
            to :data:`DEFAULT_MIRROR_TOLERANCE` (``0.001``); vertices that
            cannot be matched keep their value. Only used by
            ``MirrorMapping.GEOMETRIC``, which is the only mapping that
            searches for a counterpart in space.
        symmetry_centre (float, optional): Axis coordinate of the mirror plane.
            Defaults to the centre of the bounding box along the axis. The
            falloff band is always centred on the bounding box centre.
        mapping (MirrorMapping | str): Source of the vertex pairing,
            ``MirrorMapping.GEOMETRIC`` (default) or
            ``MirrorMapping.TOPOLOGICAL``. The ``"geometric"``/
            ``"topological"`` strings are accepted too.
        symmetry_edge (None | int | str | tuple | list): Edge lying on the
            symmetry line, given as edge id, edge component name
            (``"head.e[128]"``) or ``(vertex_a, vertex_b)``. Only used by
            ``MirrorMapping.TOPOLOGICAL``; ``None`` falls back to the first
            selected edge.

    Returns:
        dict: ``{weight_id: numpy.ndarray}`` with the weight map written for
        every processed target.

    Raises:
        ValueError: If the action, axis, direction, mapping or ``weight_id``
            is invalid, if ``symmetry_edge`` is passed for the geometric
            mapping, if the topological mapping pairs no vertex, if
            ``blendshape_name`` is not a blendShape node, if the mesh is not
            the base mesh of the blendShape or if a weight map is connected
            and therefore cannot be overwritten.

    Example:
        >>> maps = mirror_blendshape_weight_map("head_geo", "head_blendShapes",
        ...                                     weight_id="Smile",
        ...                                     action=MirrorAction.FLIP)
        >>> maps[3].max()
        1.0
        >>> maps = mirror_blendshape_weight_map(
        ...     "head_geo", "head_blendShapes",
        ...     mapping=MirrorMapping.TOPOLOGICAL, symmetry_edge="head_geo.e[128]")
        >>> len(maps)
        4
    """
    action = _coerce_action(action)
    mapping = _coerce_mapping(mapping)
    if not cmds.objExists(blendshape_name):
        raise ValueError(f"Blendshape node '{blendshape_name}' does not exist.")
    if cmds.nodeType(blendshape_name) != "blendShape":
        raise ValueError(f"'{blendshape_name}' is not a blendShape node.")

    mesh_shape = _resolve_mesh_shape_name(mesh_name)
    base_meshes = cmds.blendShape(blendshape_name, query=True, geometry=True) or []
    if not base_meshes:
        raise ValueError(f"Blendshape '{blendshape_name}' has no base mesh.")

    points = get_mesh_raw_points(mesh_shape).astype(np.float64)
    num_vertices = points.shape[0]
    if num_vertices == 0:
        raise ValueError(f"Mesh '{mesh_shape}' has no vertices to mirror.")

    base_vertices = cmds.polyEvaluate(base_meshes[0], vertex=True)
    if base_vertices != num_vertices:
        raise ValueError(f"Mesh '{mesh_shape}' has {num_vertices} vertices but "
                         f"the base mesh of '{blendshape_name}' has "
                         f"{base_vertices}: mirroring a weight map requires "
                         f"the base mesh of the blendShape.")
    base_shape = _resolve_mesh_shape_name(base_meshes[0])
    if cmds.ls(base_shape, long=True)[0] != cmds.ls(mesh_shape, long=True)[0]:
        cmds.warning(f"'{mesh_shape}' is not the base mesh of "
                     f"'{blendshape_name}' ('{base_shape}' is): the weight "
                     f"maps are mirrored on the vertex order of "
                     f"'{mesh_shape}'.")

    axis_index = _mirror_axis_index(mirror_axis)
    coordinates = points[:, axis_index]

    if mapping is MirrorMapping.TOPOLOGICAL:
        topological_mapping = get_mesh_topological_symmetry_map(mesh_shape,
                                                                symmetry_edge)
        vertex_mapping = np.array([-1 if vertex_id is None else int(vertex_id)
                                   for vertex_id in topological_mapping],
                                  dtype=np.int64)
        if vertex_mapping.size != num_vertices:
            raise ValueError(f"Topological symmetry of '{mesh_shape}' mapped "
                             f"{vertex_mapping.size} vertices but the mesh "
                             f"has {num_vertices}.")
        if not np.any(vertex_mapping >= 0):
            raise ValueError(f"Topological symmetry of '{mesh_shape}' paired "
                             f"no vertex: check that symmetry_edge lies on "
                             f"the symmetry line of the mesh.")
        # A topological pairing makes no assumption about the shape of the
        # mesh, so the falloff is read from the symmetrized positions of the
        # pairs; unpaired vertices are filtered out and keep their values.
        falloff_coordinates = compute_symmetrized_mirror_coordinates(
            coordinates, vertex_mapping, symmetry_centre)
    else:
        if symmetry_edge is not None:
            raise ValueError("symmetry_edge is only used by the topological "
                             "mapping: pass mapping='topological' together "
                             "with the edge, or drop the edge.")
        vertex_mapping = compute_geometric_symmetry_map(
            points,
            mirror_axis,
            tolerance=tolerance,
            symmetry_centre=symmetry_centre)
        falloff_coordinates = coordinates

    falloff = compute_mirror_falloff_weights(falloff_coordinates,
                                             float(coordinates.min()),
                                             float(coordinates.max()),
                                             mirror_direction,
                                             mirror_blend_falloff)

    weight_ids = _resolve_weight_ids(blendshape_name, weight_id)

    # Maya refuses to edit the weight map of the target being sculpted.
    sculpt_ids = _get_sculpt_target_ids(blendshape_name)
    active_sculpt_id = next((i for i in sculpt_ids if i >= 0), None)
    if active_sculpt_id is not None:
        cmds.sculptTarget(blendshape_name, edit=True, t=-1)

    mirrored_maps = {}
    try:
        for target_id in weight_ids:
            values = _get_weight_map_values(blendshape_name, target_id,
                                            num_vertices)
            mirrored = mirror_weight_map_values(values, vertex_mapping,
                                               falloff, action)
            _set_weight_map_values(blendshape_name, target_id, mirrored)
            mirrored_maps[target_id] = mirrored
    finally:
        if active_sculpt_id is not None:
            cmds.sculptTarget(blendshape_name, edit=True, t=active_sculpt_id)

    unmapped = int(np.count_nonzero(vertex_mapping < 0))
    # The topological helper already reports its unmapped vertices and
    # conflicts for the seed edge, so only the geometric pairing warns here.
    if unmapped and mapping is MirrorMapping.GEOMETRIC:
        cmds.warning(f"Mirroring '{blendshape_name}' on the "
                     f"{MIRROR_AXES[axis_index].upper()} "
                     f"axis mapped {num_vertices - unmapped} of {num_vertices} "
                     f"vertices: {unmapped} vertices kept their weight map "
                     f"values (check the axis, the symmetry centre and the "
                     f"tolerance).")
    return mirrored_maps


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

def _get_shape_editor_ui():
    """Return the currently open Shape Editor UI type and name.
    Returns:
        tuple[str | None, str | None]: (ui_type, ui_name)
        where ui_type is either "workspaceControl" or "window".
    """
    controls = cmds.lsUI(type="workspaceControl") or []
    for control in controls:
        if "shapePanel" in control:
            return control
    return None


def get_softselection_values() -> list:
    """Get the current soft selection as a dense vertex weight map.

    Maya symmetry is temporarily disabled while capturing the rich selection and
    restored to its original state immediately afterward.

    Returns:
        list: One weight per mesh vertex. Unselected vertices have a weight of 0.0.

    Raises:
        ValueError: If the selection contains vertices from more than one mesh.
    """
    rich_selection = om.MRichSelection()
    symmetry_enabled = cmds.symmetricModelling(query=True, symmetry=True)
    try:
        if symmetry_enabled:
            cmds.symmetricModelling(symmetry=False)
        om.MGlobal.getRichSelection(rich_selection)
    finally:
        if symmetry_enabled:
            cmds.symmetricModelling(symmetry=True)

    selection = om.MSelectionList()
    rich_selection.getSelection(selection)
    iterator = om.MItSelectionList(selection, om.MFn.kMeshVertComponent)

    weights = None
    selected_mesh = None
    while not iterator.isDone():
        dag_path = om.MDagPath()
        component = om.MObject()
        iterator.getDagPath(dag_path, component)

        mesh_name = dag_path.fullPathName()
        if selected_mesh is None:
            selected_mesh = mesh_name
            weights = np.zeros(om.MFnMesh(dag_path).numVertices(), dtype=np.float64)
        elif mesh_name != selected_mesh:
            raise ValueError("Soft selection must contain vertices from only one mesh.")

        component_fn = om.MFnSingleIndexedComponent(component)
        has_weights = component_fn.hasWeights()
        for component_index in range(component_fn.elementCount()):
            vertex_index = component_fn.element(component_index)
            weights[vertex_index] = (
                component_fn.weight(component_index).influence()
                if has_weights else 1.0
            )

        iterator.next()

    return weights.tolist() if weights is not None else []


def disable_viewport_update(func):
    """Decorator that temporarily disables viewport updates for faster batch operations."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            # Open a new undo chunk for the wrapped function
            cmds.undoInfo(openChunk=True)
            cmds.scriptEditorInfo(
                                  suppressWarnings=True,
                                  )
            cmds.refresh(suspend=True)
            return func(*args, **kwargs)
        finally:
            
            cmds.scriptEditorInfo(
                                  suppressWarnings=False,
                                  )
            cmds.refresh(suspend=False)
            cmds.undoInfo(closeChunk=True)
            cmds.refresh(force=True)
    return wrapper


def pause_shape_editor(func):
    """Decorator that temporarily closes Shape Editor for faster batch operations.

    If the Shape Editor is open, it is closed before running the wrapped function,
    then reopened afterward (only if it was originally open).
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        ui_name = _get_shape_editor_ui()
        was_open = ui_name is not None

        if was_open:
            try:
                cmds.deleteUI(ui_name)
            except Exception as e:
                cmds.warning(f"Could not close Shape Editor '{ui_name}': {e}")

        try:
            return func(*args, **kwargs)
        finally:
            if was_open:
                print(f"Shape Editor '{ui_name}' was closed; attempting to restore...")
                try:
                    cmds.ShapeEditor()
                except Exception as e:
                    cmds.warning(f"Could not restore Shape Editor: {e}")

            else:
                print("Shape Editor was not open before; no need to restore.")

    return wrapper

def calculate_mesh_bounding_box_offset(mesh_name: str,
                                       offset: float = 1.1,
                                       world: bool = True):
    """
    Calculate the bounding box of a mesh with an offset.
    Parameters:
        mesh_name (str): The name of the mesh.
        offset (float): The offset to apply to the bounding box.
        world (bool): If True, returns world-space bounding box. If False, returns object-space bounding box.
    Returns:
        tuple: A tuple containing two tuples:
            - min_point (tuple): A (3,) tuple representing the minimum point (x, y, z).
            - max_point (tuple): A (3,) tuple representing the maximum point (x, y, z).
    Example:
        >>> min_point, max_point = calculate_mesh_bounding_box_offset("pCube1", 0.1, world=True)
        >>> print("Min Point:", min_point)
        Min Point: (-0.1, -0.1, -0.1)
        >>> print("Max Point:", max_point)
        Max Point: (1.1, 1.1, 1.1)
    """
    min_point, max_point = get_mesh_bounding_box(mesh_name, world=world)
    off_set_vector = []
    for i in range(3):
        off_set_vector.append((max_point[i] - min_point[i]) * offset)
    return off_set_vector

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

@contextmanager
def _preserve_node_connections(node: str):
    """
    Context manager that disconnects all connections to and from a node and restores them on exit.

    The connections are reconnected in a finally block so they are always
    restored, even when the wrapped block raises. Only the connections that
    were actually disconnected are reconnected.
    Parameters:
        node (str): The name of the node whose connections should be suspended
    Yields:
        list: The (source, destination) plug pairs that were disconnected
    Example:
        >>> with blue_steel._preserve_node_connections("blendShape1"):
        ...     cmds.file("path.ma", exportSelected=True)
    """
    if not cmds.objExists(node):
        raise ValueError(f"Node '{node}' does not exist.")

    incoming = cmds.listConnections(
        node,
        source=True,
        destination=False,
        connections=True,
        plugs=True,
    ) or []
    outgoing = cmds.listConnections(
        node,
        source=False,
        destination=True,
        connections=True,
        plugs=True,
    ) or []

    connections = []
    connections.extend((incoming[i + 1], incoming[i]) for i in range(0, len(incoming), 2))
    connections.extend((outgoing[i], outgoing[i + 1]) for i in range(0, len(outgoing), 2))
    connections = list(dict.fromkeys(connections))

    disconnected = []
    try:
        for source, destination in connections:
            if not cmds.isConnected(source, destination):
                continue
            cmds.disconnectAttr(source, destination)
            disconnected.append((source, destination))
        yield disconnected
    finally:
        for source, destination in disconnected:
            try:
                cmds.connectAttr(source, destination, force=True)
            except Exception as e:
                cmds.warning(f"Could not reconnect '{source}' to '{destination}'. Error: {e}")
