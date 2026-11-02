"""Mirror and symmetry tools ported from the MM Tools ``mirTools`` MEL script.

This module is a line-by-line port of the ``mirrorToolsUI`` tool family from
``local references/mmTools_MEL/mmTools.mel``:

- ``createProxy``      -> :func:`create_proxy`
- ``symmetrize``       -> :func:`symmetrize`
- ``sideToside``       -> :func:`side_to_side`
- ``flip``             -> :func:`flip`
- ``transferShapeOnHalf`` -> :func:`transfer_shape_on_half`
- ``combineShapes``    -> :func:`combine_shapes`
- ``transferShape``    -> :func:`transfer_shape`
- ``invertMergeMesh``  -> :func:`invert_merge_mesh`
- ``getHalfMesh``      -> :func:`get_half_mesh`
- ``findNextVert``     -> :func:`find_next_vert`
- ``getID`` / ``matchStr`` -> :func:`get_ids` / :func:`match_str`

The workflow is unchanged:

1. **Define Rest Pose** duplicates the selected mesh into the hidden
   ``GRP_mirrorToolsProxyShapes`` group (``<mesh>_mirrorProxy``) and stores the
   selected seam edge.
2. **Mirror** / **Flip** build a symmetric copy of the rest pose, combine it
   with every selected shape, flip the result with :func:`invert_merge_mesh`
   and blend the flipped half back onto the selected shape.
3. **Symmetrize** / **Flip** / **Mirror** under *Discard Rest pose* work
   directly on the selected mesh.

Like the MEL script, :func:`invert_merge_mesh` relies on the ``meshRemap``
command shipped with the ``meshReorder`` plugin: the seam-edge triangle pair is
used to remap the mirrored duplicate so it can be blend-shaped back onto the
original mesh. The plugin is loaded on demand; a clear error is raised when it
is not available. :func:`call_mesh_remap` is the single indirection used to
invoke it, which keeps the rest of the module testable without the plugin.

The one-half transfer (the *Mirror* actions) does not use paint mode. The
per-vertex blend weight is derived from the bounding box of the symmetrised
rest pose: vertices on the kept side get ``0``, vertices on the flipped side
get ``1``, and a smoothstep band centred on the symmetry plane (width =
:attr:`MirrorToolsState.gradient_band_percent` percent of the bounding box
along the mirror axis) blends the two. The map is written straight into the
temporary blendShape target weights, so the result is deterministic and does
not depend on any paint context.

Attributes:
    STATE (MirrorToolsState): Session state mirroring the MEL globals
        ``$selBaseGeo``, ``$selBaseEdge``, ``$direction`` and ``$negative``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

from maya import cmds, mel

from ..api.mayaUtils import undoable

PROXY_GROUP_NAME = "GRP_mirrorToolsProxyShapes"
"""Name of the hidden group that stores the rest-pose proxies."""

PROXY_SUFFIX = "_mirrorProxy"
"""Suffix of the duplicated rest-pose proxy shape."""

MESH_REORDER_PLUGIN = "meshReorder"
"""Plugin that provides the ``meshRemap`` command used by the mirror math."""

AXES: Tuple[str, str, str] = ("X", "Y", "Z")
"""Axis order matching the MEL *Mirror Axis* option menu."""

EDGE_PATTERN = re.compile(r"^(?P<shape>.+)\.e\[(?P<index>\d+)\]$")
"""Matches an edge component such as ``pPlane1.e[12]``."""

DEFAULT_GRADIENT_BAND_PERCENT = 10.0
"""Default width of the seam blend band, as a percentage of the bbox."""

_INTEGRAL_PATTERN = re.compile(r"^[0-9]+$")


@dataclass
class MirrorToolsState:
    """Session state of the mirror tools.

    Mirrors the MEL globals ``$selBaseGeo``, ``$selBaseEdge``, ``$direction``
    and ``$negative``.

    Attributes:
        rest_geometry (str): Rest-pose proxy shape shown in *Selected
            geometry*.
        seam_edge (str): Index of the seam (middle) edge shown in *Seam edge*.
        axis (str): Mirror axis, one of ``"X"``, ``"Y"`` or ``"Z"``.
        negative (bool): When ``True`` the negative side of the axis is the
            side kept by *Mirror* (``L>>R``), otherwise the positive side is
            kept (``L<<R``).
        gradient_band_percent (float): Width of the smoothstep band centred on
            the symmetry plane, as a percentage of the rest-pose bounding box
            along the mirror axis. ``0`` is a hard split.
    """

    rest_geometry: str = ""
    seam_edge: str = ""
    axis: str = "X"
    negative: bool = False
    gradient_band_percent: float = DEFAULT_GRADIENT_BAND_PERCENT

    def reset(self) -> None:
        """Restore every value to its default."""

        self.rest_geometry = ""
        self.seam_edge = ""
        self.axis = "X"
        self.negative = False
        self.gradient_band_percent = DEFAULT_GRADIENT_BAND_PERCENT


STATE = MirrorToolsState()


# ----------------------------------------------------------------------
# Selection and polyInfo helpers
# ----------------------------------------------------------------------
def _short_name(node_name: str) -> str:
    """Return a node name without its DAG path or namespace.

    Parameters:
        node_name (str): Maya node name or DAG path.

    Returns:
        str: The bare node name.
    """

    return node_name.rsplit("|", 1)[-1].rsplit(":", 1)[-1]


def _dag_leaf(node_name: str) -> str:
    """Return a node name without its DAG path, keeping the namespace.

    Parameters:
        node_name (str): Maya node name or DAG path.

    Returns:
        str: The node name after the last ``|``.
    """

    return node_name.rsplit("|", 1)[-1]


def match_str(value: str, values: Sequence[str]) -> bool:
    """Return whether ``value`` is present in ``values``.

    Port of the MEL ``matchStr`` helper.

    Parameters:
        value (str): Value to look for.
        values (Sequence[str]): Values to search.

    Returns:
        bool: ``True`` when ``value`` is part of ``values``.
    """

    return value in values


def get_ids(component_info: str) -> List[str]:
    """Extract the connected component ids from ``polyInfo`` output.

    Port of the MEL ``getID`` helper. ``polyInfo`` returns strings shaped like
    ``"VERTEX      8:      3    9"``; the label is dropped by the numeric
    filter and the second token (the queried component id) is dropped
    explicitly, so only the connected component ids remain.

    Parameters:
        component_info (str): A single ``polyInfo`` result string.

    Returns:
        list[str]: The connected component ids, in ``polyInfo`` order.
    """

    tokens = [
        token.strip()
        for token in re.split(r"[ :\n\r]+", component_info or "")
        if token.strip()
    ]
    # The second token is the id of the queried component itself, matching the
    # MEL `$tokens[1] = "null";` blanking.
    del tokens[1:2]
    return [token for token in tokens if _INTEGRAL_PATTERN.match(token)]


def _poly_info(component: str, flag: str) -> List[str]:
    """Run ``polyInfo`` and return the connected component ids.

    Parameters:
        component (str): Component to query, e.g. ``"pPlane1.e[3]"``.
        flag (str): ``polyInfo`` flag name, one of ``ev``, ``ef``, ``ve`` or
            ``fe``.

    Returns:
        list[str]: The connected component ids.

    Raises:
        RuntimeError: If Maya cannot resolve the component.
    """

    try:
        result = cmds.polyInfo(component, **{flag: True}) or []
    except RuntimeError as error:
        raise RuntimeError(
            f"Could not query '{component}' with polyInfo -{flag}: {error}"
        ) from error
    if not result:
        return []
    return get_ids(result[0])


def parse_edge(edge: str) -> Tuple[str, str]:
    """Split an edge component into its shape name and edge index.

    Parameters:
        edge (str): Edge component such as ``"pPlane1.e[12]"``.

    Returns:
        tuple[str, str]: ``(shape, edge_index)``.

    Raises:
        RuntimeError: If ``edge`` is not an edge component.
    """

    match = EDGE_PATTERN.match(edge or "")
    if match is None:
        raise RuntimeError(f"'{edge}' is not a valid edge component.")
    return match.group("shape"), match.group("index")


def axis_index(axis: Optional[str] = None) -> int:
    """Return the 0-based index of a mirror axis.

    Parameters:
        axis (str | None): Axis name to resolve. Defaults to
            :attr:`MirrorToolsState.axis`.

    Returns:
        int: ``0`` for X, ``1`` for Y and ``2`` for Z.

    Raises:
        ValueError: If the axis is not one of X, Y or Z.
    """

    axis = (axis or STATE.axis or "X").upper()
    if axis not in AXES:
        raise ValueError(f"Unsupported mirror axis '{axis}'.")
    return AXES.index(axis)


def set_axis(axis: str) -> str:
    """Set the mirror axis used by the tools.

    Parameters:
        axis (str): One of ``"X"``, ``"Y"`` or ``"Z"`` (case insensitive).

    Returns:
        str: The axis that was stored.

    Raises:
        ValueError: If the axis is not one of X, Y or Z.
    """

    axis = (axis or "").upper()
    if axis not in AXES:
        raise ValueError(f"Unsupported mirror axis '{axis}'.")
    STATE.axis = axis
    return STATE.axis


def set_negative(negative: bool) -> bool:
    """Set which side of the mirror axis is kept by *Mirror*.

    Parameters:
        negative (bool): ``True`` for ``L>>R`` (negative side kept),
            ``False`` for ``L<<R`` (positive side kept).

    Returns:
        bool: The stored flag.
    """

    STATE.negative = bool(negative)
    return STATE.negative


def set_gradient_band_percent(value: float) -> float:
    """Set the width of the seam blend band.

    Parameters:
        value (float): Band width as a percentage of the rest-pose bounding
            box along the mirror axis. Clamped to ``0..100``.

    Returns:
        float: The stored percentage.
    """

    STATE.gradient_band_percent = _clamp(float(value), 0.0, 100.0)
    return STATE.gradient_band_percent


def has_rest_pose() -> bool:
    """Return whether a usable rest pose and seam edge are defined.

    Returns:
        bool: ``True`` when *Selected geometry* and *Seam edge* point at live
            scene objects.
    """

    if not STATE.rest_geometry or not STATE.seam_edge:
        return False
    return cmds.objExists(STATE.rest_geometry)


def sync_state_with_scene() -> str:
    """Recover the rest-pose proxy from the hidden group when possible.

    The MEL tool kept the proxy only in globals; because the proxy is stored
    in the scene we can restore *Selected geometry* after a reload. The seam
    edge is still session-only, exactly like the MEL global.

    Returns:
        str: The rest-pose proxy that is now in use, or an empty string.
    """

    if has_rest_pose():
        return STATE.rest_geometry
    if not cmds.objExists(PROXY_GROUP_NAME):
        return ""
    children = cmds.listRelatives(PROXY_GROUP_NAME, children=True) or []
    transforms = [
        child for child in children
        if cmds.objectType(child, isType="transform")
    ]
    if not transforms:
        return ""
    STATE.rest_geometry = transforms[0]
    return STATE.rest_geometry


# ----------------------------------------------------------------------
# Mirror gradient helpers
# ----------------------------------------------------------------------
def _clamp(value: float, minimum: float, maximum: float) -> float:
    """Clamp ``value`` between ``minimum`` and ``maximum``.

    Parameters:
        value (float): Value to clamp.
        minimum (float): Lower bound.
        maximum (float): Upper bound.

    Returns:
        float: The clamped value.
    """

    return max(minimum, min(maximum, value))


def gradient_weights(
    coordinates: Sequence[float],
    minimum: float,
    maximum: float,
    negative: bool = False,
    band_percent: float = DEFAULT_GRADIENT_BAND_PERCENT,
) -> List[float]:
    """Build the per-vertex mirror weight from a bounding-box gradient.

    The symmetry plane is the centre of the bounding box. Vertices on the kept
    side get ``0``, vertices on the flipped side get ``1``, and a smoothstep
    band centred on the symmetry plane blends the two. The band width is
    ``band_percent`` percent of the bounding box extent, so ``0`` produces a
    hard split and ``100`` a gradient across the whole model.

    This function performs no Maya calls, which keeps the mirror math testable
    outside Maya.

    Parameters:
        coordinates (Sequence[float]): Coordinate of every vertex along the
            mirror axis, in the rest pose's object space.
        minimum (float): Lowest coordinate of the bounding box.
        maximum (float): Highest coordinate of the bounding box.
        negative (bool): When ``True`` the negative side of the axis is kept
            (``L>>R``), otherwise the positive side is kept (``L<<R``).
        band_percent (float): Width of the transition band as a percentage of
            ``maximum - minimum``. Clamped to ``0..100``.

    Returns:
        list[float]: One mirror weight between ``0`` and ``1`` per coordinate.

    Raises:
        ValueError: If the bounding box has no extent along the axis.
    """

    centre = (minimum + maximum) / 2.0
    width = maximum - minimum
    if width <= 0.0:
        raise ValueError(
            "The rest pose has no extent along the mirror axis; pick another "
            "axis or update the rest pose."
        )

    band = width * _clamp(
        DEFAULT_GRADIENT_BAND_PERCENT if band_percent is None
        else float(band_percent),
        0.0,
        100.0,
    ) / 100.0
    half_band = band / 2.0
    # L<<R keeps the positive side, so the weight grows towards -axis; L>>R
    # keeps the negative side, so it grows towards +axis.
    direction = 1.0 if negative else -1.0

    weights: List[float] = []
    for coordinate in coordinates:
        if half_band <= 0.0:
            # Hard split: still give the symmetry plane itself a half weight so
            # shared seam vertices stay neutral.
            offset = coordinate - centre
            if offset == 0.0:
                weights.append(0.5)
            elif offset * direction > 0.0:
                weights.append(1.0)
            else:
                weights.append(0.0)
            continue
        normalized = direction * (coordinate - centre) / half_band
        ramp = _clamp((normalized + 1.0) / 2.0, 0.0, 1.0)
        weights.append(ramp * ramp * (3.0 - 2.0 * ramp))
    return weights


def _mesh_shape(node_name: str) -> str:
    """Resolve a transform or shape name to its non-intermediate mesh shape.

    Parameters:
        node_name (str): Mesh transform or mesh shape name.

    Returns:
        str: Full path of the mesh shape.

    Raises:
        RuntimeError: If ``node_name`` is not a polygon mesh.
    """

    if cmds.objectType(node_name, isType="mesh"):
        return cmds.ls(node_name, long=True)[0]
    shapes = cmds.listRelatives(
        node_name,
        shapes=True,
        noIntermediate=True,
        fullPath=True,
    ) or []
    mesh_shapes = [
        shape for shape in shapes if cmds.objectType(shape, isType="mesh")
    ]
    if not mesh_shapes:
        raise RuntimeError(
            f"'{_short_name(node_name)}' has no mesh shape to mirror."
        )
    return mesh_shapes[0]


def _axis_coordinates(mesh: str, axis: Optional[str] = None) -> List[float]:
    """Return the object-space coordinate of every vertex along the axis.

    The points are read in one ``MFnMesh`` call instead of one ``xform`` query
    per vertex, so the gradient stays fast on high-resolution meshes.

    Parameters:
        mesh (str): Mesh transform or mesh shape name.
        axis (str | None): Axis to read. Defaults to
            :attr:`MirrorToolsState.axis`.

    Returns:
        list[float]: One coordinate per vertex, in vertex index order.
    """

    # Imported lazily so the module can be loaded without ``maya.api`` (the
    # gradient math is exercised by Maya-free tests).
    from maya.api import OpenMaya as om

    index = axis_index(axis)
    shape = _mesh_shape(mesh)
    selection = om.MSelectionList()
    selection.add(shape)
    mesh_fn = om.MFnMesh(selection.getDependNode(0))
    points = mesh_fn.getPoints(om.MSpace.kObject)
    return [
        (point.x, point.y, point.z)[index]
        for point in points
    ]


def get_mirror_gradient(
    symobj: Optional[str] = None,
    band_percent: Optional[float] = None,
) -> List[float]:
    """Return the mirror weight of every vertex from the rest-pose bbox.

    Parameters:
        symobj (str | None): Symmetrised rest-pose mesh. Defaults to
            :attr:`MirrorToolsState.rest_geometry`.
        band_percent (float | None): Transition band width as a percentage of
            the bounding box along the axis. Defaults to
            :attr:`MirrorToolsState.gradient_band_percent`.

    Returns:
        list[float]: One mirror weight per vertex of ``symobj``.

    Raises:
        RuntimeError: If the rest pose is missing.
        ValueError: If the rest pose has no extent along the mirror axis.
    """

    symobj = symobj or STATE.rest_geometry
    if not symobj or not cmds.objExists(symobj):
        raise RuntimeError(
            "Define a rest pose before using the mirror tools."
        )

    if band_percent is None:
        band_percent = STATE.gradient_band_percent

    coordinates = _axis_coordinates(symobj)
    if not coordinates:
        raise ValueError(
            f"The rest pose '{_short_name(symobj)}' has no vertices."
        )
    return gradient_weights(
        coordinates,
        min(coordinates),
        max(coordinates),
        negative=STATE.negative,
        band_percent=band_percent,
    )


# ----------------------------------------------------------------------
# BlendShape helpers
# ----------------------------------------------------------------------
def _blendshape_weight_name(blend_shape: str, target: str) -> str:
    """Return the weight alias of ``target`` on ``blend_shape``.

    Parameters:
        blend_shape (str): BlendShape node name.
        target (str): Target mesh that was added to the node.

    Returns:
        str: Weight alias to use with ``setAttr``.

    Raises:
        RuntimeError: If the blendShape has no weight attributes.
    """

    aliases = cmds.listAttr(f"{blend_shape}.weight", multi=True) or []
    short_target = _short_name(target)
    if short_target in aliases:
        return short_target
    for alias in aliases:
        if short_target in alias:
            return alias
    if aliases:
        return aliases[0]
    raise RuntimeError(
        f"BlendShape '{blend_shape}' has no target weight attributes."
    )


def _target_weight_index(blend_shape: str, target: str) -> int:
    """Return the logical index of ``target`` in ``blend_shape``.

    The weight alias order of a blendShape node follows the target logical
    indices, so the alias position is the ``inputTargetGroup`` index.

    Parameters:
        blend_shape (str): BlendShape node name.
        target (str): Target mesh that was added to the node.

    Returns:
        int: Logical index of the target weights.

    Raises:
        RuntimeError: If the target has no weight attribute.
    """

    aliases = cmds.listAttr(f"{blend_shape}.weight", multi=True) or []
    weight_name = _blendshape_weight_name(blend_shape, target)
    if weight_name not in aliases:
        raise RuntimeError(
            f"BlendShape '{blend_shape}' has no weight for "
            f"'{_short_name(target)}'."
        )
    return aliases.index(weight_name)


def _set_blendshape_weight(
    blend_shape: str,
    target: str,
    value: float,
) -> None:
    """Set a blendShape target weight.

    Parameters:
        blend_shape (str): BlendShape node name.
        target (str): Target mesh used to resolve the weight alias.
        value (float): Weight value.

    Returns:
        None
    """

    weight_name = _blendshape_weight_name(blend_shape, target)
    cmds.setAttr(f"{blend_shape}.{weight_name}", value)


def _set_blendshape_weight_map(
    blend_shape: str,
    target: str,
    weights: Sequence[float],
) -> None:
    """Write a per-vertex weight map onto a blendShape target.

    Replaces the paint-mode flood with a direct ``setAttr`` on
    ``inputTarget[0].inputTargetGroup[<index>].targetWeights``, using the same
    attribute path as
    :meth:`blue_steel.api.blendshape.Blendshape.set_weight_map_values`.

    Parameters:
        blend_shape (str): BlendShape node name.
        target (str): Target mesh whose weight map is overwritten.
        weights (Sequence[float]): One weight per base vertex.

    Returns:
        None

    Raises:
        RuntimeError: If ``weights`` is empty.
    """

    weights = list(weights)
    if not weights:
        raise RuntimeError("Cannot write an empty blendShape weight map.")
    index = _target_weight_index(blend_shape, target)
    attribute = (
        f"{blend_shape}.inputTarget[0].inputTargetGroup[{index}]"
        f".targetWeights[0:{len(weights) - 1}]"
    )
    cmds.setAttr(attribute, *weights, size=len(weights))


# ----------------------------------------------------------------------
# meshRemap plugin
# ----------------------------------------------------------------------
def ensure_mesh_reorder_plugin() -> None:
    """Load the ``meshReorder`` plugin that provides ``meshRemap``.

    The MEL script hard-codes ``meshReorder.so``; Maya resolves the plain
    plugin name to the platform specific extension, so that name is used here.

    Returns:
        None

    Raises:
        RuntimeError: If the plugin cannot be loaded.
    """

    try:
        loaded = cmds.pluginInfo(
            MESH_REORDER_PLUGIN,
            query=True,
            loaded=True,
        )
    except RuntimeError:
        loaded = False
    if loaded:
        return
    try:
        cmds.loadPlugin(MESH_REORDER_PLUGIN, quiet=True)
    except RuntimeError as error:
        raise RuntimeError(
            "The mirror tools need the 'meshRemap' command from the "
            f"'{MESH_REORDER_PLUGIN}' plugin, which could not be loaded: "
            f"{error}"
        ) from error
    if not cmds.pluginInfo(MESH_REORDER_PLUGIN, query=True, loaded=True):
        raise RuntimeError(
            "The mirror tools need the 'meshRemap' command from the "
            f"'{MESH_REORDER_PLUGIN}' plugin, which is not loaded."
        )


def call_mesh_remap(vertices: Sequence[str]) -> None:
    """Remap a mirrored mesh from six corresponding vertices.

    Port of the MEL ``eval ("meshRemap ...")`` call. This indirection exists so
    the plugin call can be stubbed by tests.

    Parameters:
        vertices (Sequence[str]): Three vertices of the source face followed
            by three vertices of the mirrored face.

    Returns:
        None
    """

    mel.eval("meshRemap " + " ".join(vertices))


# ----------------------------------------------------------------------
# Topology helpers
# ----------------------------------------------------------------------
def find_next_vert(shape: str, face: str, selected_edge_id: str) -> List[str]:
    """Return the seam edge vertices plus the next vertex of ``face``.

    Port of the MEL ``findNextVert`` helper: the two vertices of the seam
    edge are followed by the third vertex of ``face`` reached through the
    shared edge.

    Parameters:
        shape (str): Mesh shape/transform name.
        face (str): Face index.
        selected_edge_id (str): Index of the seam edge.

    Returns:
        list[str]: ``[seam_vertex_a, seam_vertex_b, next_vertex]``.

    Raises:
        RuntimeError: If the seam edge or its neighbouring edge cannot be
            resolved.
    """

    edge_component = f"{shape}.e[{selected_edge_id}]"
    edge_vertices = _poly_info(edge_component, "ev")
    if len(edge_vertices) < 2:
        raise RuntimeError(
            f"Edge '{edge_component}' does not have two vertices."
        )
    seam_vertex = edge_vertices[1]

    connected_edges = _poly_info(f"{shape}.vtx[{seam_vertex}]", "ve")
    face_edges = _poly_info(f"{shape}.f[{face}]", "fe")

    shared_edges = [
        edge
        for edge in connected_edges
        if match_str(edge, face_edges) and edge != selected_edge_id
    ]
    if not shared_edges:
        raise RuntimeError(
            f"Could not find an edge of face '{shape}.f[{face}]' connected "
            f"to the seam edge '{selected_edge_id}'."
        )

    shared_vertices = _poly_info(
        f"{shape}.e[{shared_edges[0]}]",
        "ev",
    )
    next_vertex = None
    for vertex in shared_vertices:
        if vertex != seam_vertex:
            next_vertex = vertex
    if next_vertex is None:
        raise RuntimeError(
            f"Could not find the next vertex for face '{shape}.f[{face}]'."
        )

    result = list(edge_vertices)
    result.append(next_vertex)
    return result


def get_half_mesh(
    obj: str,
    symobj: Optional[str] = None,
) -> Tuple[List[str], List[str]]:
    """Split a mesh into the kept side and the seam vertices.

    Port of the MEL ``getHalfMesh`` helper. The side of every vertex is
    decided from the *rest pose* (``symobj``) so a deformed shape still maps
    to the same half. The returned side is the negative half when
    :attr:`MirrorToolsState.negative` is set (``L>>R``) and the positive half
    otherwise. The rest-pose coordinates are read in one ``MFnMesh`` call.

    The mirror transfer itself uses :func:`get_mirror_gradient`; this helper is
    kept for scripts that need the split components (and for MEL parity).

    Parameters:
        obj (str): Mesh whose components are returned.
        symobj (str | None): Rest-pose mesh used to classify the vertices.
            Defaults to :attr:`MirrorToolsState.rest_geometry`.

    Returns:
        tuple[list[str], list[str]]: ``(side_components, seam_components)``.

    Raises:
        RuntimeError: If the rest-pose mesh is missing or does not match the
            vertex count of the shape.
    """

    symobj = symobj or STATE.rest_geometry
    if not symobj or not cmds.objExists(symobj):
        raise RuntimeError(
            "Define a rest pose before using the mirror tools."
        )

    vertex_count = int(cmds.polyEvaluate(obj, vertex=True) or 0)
    coordinates = _axis_coordinates(symobj)
    if len(coordinates) != vertex_count:
        raise RuntimeError(
            f"'{_short_name(obj)}' has {vertex_count} vertices but the "
            f"rest pose '{_short_name(symobj)}' has {len(coordinates)}; "
            "the rest pose must be a duplicate of the mirrored mesh."
        )

    positive: List[str] = []
    negative: List[str] = []
    zero: List[str] = []

    for vertex, value in enumerate(coordinates):
        component = f"{obj}.vtx[{vertex}]"
        if value > 0:
            positive.append(component)
        elif value < 0:
            negative.append(component)
        else:
            zero.append(component)

    side = negative if STATE.negative else positive
    return side, zero


# ----------------------------------------------------------------------
# Shape transfer helpers
# ----------------------------------------------------------------------
def combine_shapes(shapes: Sequence[str], home: str) -> str:
    """Combine several shapes onto a duplicate of ``home``.

    Port of the MEL ``combineShapes`` helper: duplicate ``home``, blend every
    shape onto it at weight ``1``, then delete the history so the duplicate
    keeps the combined positions.

    Parameters:
        shapes (Sequence[str]): Shapes to add to the duplicate.
        home (str): Mesh that is duplicated and used as the blend base.

    Returns:
        str: Name of the combined duplicate.

    Raises:
        RuntimeError: If no shapes were supplied.
    """

    shapes = list(shapes)
    if not shapes:
        raise RuntimeError("No shapes were supplied to combine.")
    combined = cmds.duplicate(home, name="combined shapes")[0]
    blend_shape = cmds.blendShape(shapes, combined)[0]
    for shape in shapes:
        _set_blendshape_weight(blend_shape, shape, 1.0)
    cmds.delete(combined, constructionHistory=True)
    return combined


def transfer_shape(shape: str, home: str) -> None:
    """Bake ``shape`` onto ``home`` at weight ``1``.

    Port of the MEL ``transferShape`` helper.

    Parameters:
        shape (str): Shape that provides the target positions.
        home (str): Mesh that receives the shape.

    Returns:
        None
    """

    blend_shape = cmds.blendShape(shape, home)[0]
    _set_blendshape_weight(blend_shape, shape, 1.0)
    cmds.delete(home, constructionHistory=True)


def transfer_shape_on_half(
    sym_home: str,
    shape_a: str,
    shape_b: str,
) -> None:
    """Transfer ``shape_a`` onto ``shape_b`` with a bounding-box gradient.

    Port of the MEL ``transferShapeOnHalf`` helper, with the paint-mode weight
    map replaced by a deterministic gradient: :func:`get_mirror_gradient`
    returns ``0`` on the kept side, ``1`` on the flipped side and a smoothstep
    band centred on the symmetry plane of ``sym_home`` (the symmetrised rest
    pose). The map is written straight into the temporary blendShape target
    weights and the result is baked into ``shape_b`` by deleting its history.

    Parameters:
        sym_home (str): Symmetric rest shape that defines the bbox gradient.
        shape_a (str): Shape that provides the flipped positions.
        shape_b (str): Shape that receives the flipped half.

    Returns:
        None

    Raises:
        RuntimeError: If ``shape_b`` does not match the rest-pose vertex count
            or the blendShape target weights cannot be resolved.
        ValueError: If the rest pose has no extent along the mirror axis.
    """

    weights = get_mirror_gradient(sym_home)
    vertex_count = int(cmds.polyEvaluate(shape_b, vertex=True) or 0)
    if len(weights) != vertex_count:
        raise RuntimeError(
            f"'{_short_name(shape_b)}' has {vertex_count} vertices but the "
            f"rest pose '{_short_name(sym_home)}' has {len(weights)}; the "
            "mirror gradient cannot be applied."
        )

    blend_shape = cmds.blendShape(shape_a, shape_b)[0]
    _set_blendshape_weight(blend_shape, shape_a, 1.0)
    _set_blendshape_weight_map(blend_shape, shape_a, weights)

    cmds.delete(shape_b, constructionHistory=True)


def invert_merge_mesh(edge: str, axis: str, intensity: float) -> None:
    """Mirror a mesh across ``axis`` and blend it back at ``intensity``.

    Port of the MEL ``invertMergeMesh`` helper. The mesh is duplicated,
    mirrored with a negative scale, has its normals flipped, and is remapped
    by ``meshRemap`` using the triangle pair that shares the seam edge. A
    blendShape at ``intensity`` then bakes the mirrored positions onto the
    original mesh.

    Parameters:
        edge (str): Seam edge of the mesh, e.g. ``"pPlane1.e[12]"``.
        axis (str): Mirror axis, one of ``"X"``, ``"Y"`` or ``"Z"``.
        intensity (float): ``0.5`` produces a symmetric mesh, ``1.0`` a fully
            mirrored one.

    Returns:
        None

    Raises:
        RuntimeError: If the edge or its two faces cannot be resolved, or the
            ``meshRemap`` plugin is unavailable.
    """

    ensure_mesh_reorder_plugin()

    shape, selected_edge_id = parse_edge(edge)
    connected_faces = _poly_info(edge, "ef")
    if len(connected_faces) < 2:
        raise RuntimeError(
            f"Edge '{edge}' must be shared by two faces to be used as a "
            "seam edge."
        )

    shape_vertices = find_next_vert(shape, connected_faces[0], selected_edge_id)
    mirror_vertices = find_next_vert(shape, connected_faces[1], selected_edge_id)

    mirror_shape = cmds.duplicate(shape)[0]
    cmds.setAttr(f"{mirror_shape}.scale{axis.upper()}", -1)
    cmds.makeIdentity(
        mirror_shape,
        apply=True,
        translate=False,
        rotate=False,
        scale=True,
        normal=False,
    )
    cmds.polyNormal(
        mirror_shape,
        normalMode=0,
        userNormalMode=0,
        constructionHistory=False,
    )
    cmds.delete(mirror_shape, constructionHistory=True)

    shape_long = cmds.ls(shape, long=True)[0]
    mirror_shape_long = cmds.ls(mirror_shape, long=True)[0]

    shape_selection = [
        f"{shape_long}.vtx[{vertex}]" for vertex in shape_vertices
    ]
    mirror_selection = [
        f"{mirror_shape_long}.vtx[{vertex}]" for vertex in mirror_vertices
    ]

    cmds.delete(shape, constructionHistory=True)

    print(
        "The vertices are:\n{}\n{}\n{}\n{}\n{}\n{}".format(
            *(shape_selection + mirror_selection)
        )
    )

    call_mesh_remap(shape_selection + mirror_selection)

    blend_shape = cmds.blendShape(mirror_shape, shape)[0]
    _set_blendshape_weight(blend_shape, mirror_shape, intensity)
    cmds.delete(mirror_shape)
    cmds.delete(shape, constructionHistory=True)


# ----------------------------------------------------------------------
# Tool entries (MEL callbacks)
# ----------------------------------------------------------------------
def _ensure_proxy_group() -> str:
    """Create the hidden rest-pose proxy group when it is missing.

    Returns:
        str: Name of the proxy group.
    """

    if cmds.objExists(PROXY_GROUP_NAME):
        print("Group is already there not creating it")
    else:
        print(f"Creating {PROXY_GROUP_NAME}")
        cmds.group(empty=True, world=True, name=PROXY_GROUP_NAME)
    cmds.setAttr(f"{PROXY_GROUP_NAME}.visibility", 0)
    return PROXY_GROUP_NAME


@undoable
def create_proxy(action: str = "c") -> str:
    """Define or update the rest pose used by *Mirror* and *Flip*.

    Port of the MEL ``createProxy`` callback. ``"c"`` (Define Rest Pose)
    requires an edge selection and stores that edge as the seam edge; ``"u"``
    (Update Rest Pose) only re-duplicates the selected mesh, keeping the
    stored seam edge.

    Parameters:
        action (str): ``"c"`` to define the rest pose, ``"u"`` to update it.

    Returns:
        str: Name of the new rest-pose proxy.

    Raises:
        RuntimeError: If the action is unknown, nothing is selected, or
            Define Rest Pose is used without a selected edge.
    """

    if action not in ("c", "u"):
        raise ValueError("Action must be 'c' (create) or 'u' (update).")

    selection = cmds.ls(selection=True) or []
    if not selection:
        raise RuntimeError("Select a mesh (and a seam edge) first.")

    if action == "c" and not (cmds.filterExpand(sm=32) or []):
        raise RuntimeError("Please select one of the middle edges.")

    group = _ensure_proxy_group()
    shape = selection[0].split(".")[0]

    proxy_name = f"{shape}{PROXY_SUFFIX}"
    if cmds.objExists(proxy_name):
        cmds.delete(proxy_name)
        print("Removing proxy shape")

    proxy = cmds.duplicate(shape, name=proxy_name)[0]

    if action == "c":
        _, STATE.seam_edge = parse_edge(selection[0])

    cmds.parent(proxy, group)
    STATE.rest_geometry = proxy

    cmds.select(shape, replace=True)
    print(
        f"Rest pose proxy: {STATE.rest_geometry} (seam edge {STATE.seam_edge})"
    )
    return proxy


@undoable
def symmetrize(action: str = "sym") -> None:
    """Symmetrize or flip the selected mesh in place.

    Port of the MEL ``symmetrize`` callback used by the *Discard Rest pose
    and* buttons. ``"sym"`` mirrors the selected mesh onto itself at half
    intensity, ``"flip"`` replaces it with its mirrored version.

    Parameters:
        action (str): ``"sym"`` for Symmetrize, ``"flip"`` for Flip.

    Returns:
        None

    Raises:
        RuntimeError: If nothing is selected, the rest pose is missing, or
            the action is unknown.
    """

    if action not in ("sym", "flip"):
        raise ValueError("Action must be 'sym' (symmetrize) or 'flip'.")

    selection = cmds.ls(selection=True) or []
    if not selection:
        raise RuntimeError("Select a mesh first.")
    if not has_rest_pose():
        raise RuntimeError("Define a rest pose and seam edge first.")

    intensity = 0.5 if action == "sym" else 1.0
    edge = f"{selection[0]}.e[{STATE.seam_edge}]"
    invert_merge_mesh(edge, STATE.axis, intensity)
    cmds.select(selection[0], replace=True)


@undoable
def side_to_side() -> None:
    """Mirror the selected mesh onto its opposite side.

    Port of the MEL ``sideToside`` callback (*Mirror* under *Discard Rest
    pose*): a symmetric copy and a mirrored copy are built from the selected
    mesh and the mirrored half is blended onto the selection.

    Returns:
        None

    Raises:
        RuntimeError: If nothing is selected or the rest pose is missing.
    """

    selection = cmds.ls(selection=True) or []
    if not selection:
        raise RuntimeError("Select a mesh first.")
    if not has_rest_pose():
        raise RuntimeError("Define a rest pose and seam edge first.")

    shape = selection[0]
    symmetric_head = cmds.duplicate(shape)[0]
    invert_merge_mesh(
        f"{symmetric_head}.e[{STATE.seam_edge}]",
        STATE.axis,
        0.5,
    )

    side_head = cmds.duplicate(shape)[0]
    invert_merge_mesh(
        f"{side_head}.e[{STATE.seam_edge}]",
        STATE.axis,
        1.0,
    )

    transfer_shape_on_half(symmetric_head, side_head, shape)
    cmds.delete(symmetric_head, side_head)


@undoable
def flip(action: str = "mirror") -> None:
    """Mirror or flip every selected shape using the stored rest pose.

    Port of the MEL ``flip`` callback. For each selected shape the rest pose
    is symmetrized, the shape is combined with it, the combination is
    inverted with the seam edge and the result is transferred back, either on
    one half only (``"mirror"``) or on the whole shape (``"flip"``).

    Parameters:
        action (str): ``"mirror"`` for the *Mirror* button, ``"flip"`` for
            the *Flip* button.

    Returns:
        None

    Raises:
        RuntimeError: If nothing is selected, the rest pose is missing, or the
            action is unknown.
    """

    if action not in ("mirror", "flip"):
        raise ValueError("Action must be 'mirror' or 'flip'.")

    selection = cmds.ls(selection=True) or []
    if not selection:
        raise RuntimeError("Select one or more shapes first.")
    if not has_rest_pose():
        raise RuntimeError("Define a rest pose and seam edge first.")

    rest = STATE.rest_geometry

    for shape in selection:
        symmetric_home = cmds.duplicate(
            rest,
            name=f"{_dag_leaf(rest)}Symmetric",
        )[0]
        invert_merge_mesh(
            f"{symmetric_home}.e[{STATE.seam_edge}]",
            STATE.axis,
            0.5,
        )

        symmetric_shape = combine_shapes([symmetric_home, shape], rest)
        invert_merge_mesh(
            f"{symmetric_shape}.e[{STATE.seam_edge}]",
            STATE.axis,
            1.0,
        )

        flipped_shape = combine_shapes([rest, symmetric_shape], symmetric_home)
        flipped_shape = cmds.rename(
            flipped_shape,
            f"{_dag_leaf(shape)}_flipped",
        )

        if action == "mirror":
            transfer_shape_on_half(symmetric_home, flipped_shape, shape)
        else:
            transfer_shape(flipped_shape, shape)

        cmds.delete(symmetric_home)
        cmds.delete(flipped_shape)
        cmds.delete(symmetric_shape)
