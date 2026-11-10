"""Utilities for transferring blendShape weight maps between meshes by UV.

The transfer is done through temporary skinClusters: each blendShape target is
represented by a joint whose name matches the target weight name. The source
weight maps are written to the source skinCluster, ``copySkinWeights`` transfers
them by UV to a matching destination skinCluster, and the transferred weights
are then written into a destination blendShape, either newly created or an
existing node whose matching target maps are overwritten.

The temporary skinClusters are built on history-free duplicates of the source
and destination meshes, so meshes that already have a skinCluster or other
deformers are never modified by the transfer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence
from contextlib import nullcontext
import enum
from maya import cmds
from maya.api import OpenMaya as om
from maya.api import OpenMayaAnim as oma

import numpy as np

from ..api import mayaUtils
from ..api.blendshape import Blendshape
from ..api.mayaUtils import undoable
from ..api.skinCluster import SkinCluster
from ..api.targetDirectory import TargetDirectory

class WeightsTransferMethod(enum.Enum):
    UVS = "uvs"
    CLOSEST_POINT = "closestPoint"
    CLOSEST_COMPONENT = "closestComponent"
    RAY_CAST = "rayCast"



@dataclass
class _TargetWeightMap:
    """A source blendShape target and its per-vertex weight map.

    Attributes:
        index (int): Logical index of the target in the source blendShape.
        name (str): Weight alias / target name.
        weights (list[float]): One target-weight value per source vertex.
    """

    index: int
    name: str
    weights: list[float]


def _name_key(node_name: str) -> str:
    """Return a namespace- and DAG-path-independent node name.

    Parameters:
        node_name (str): Maya node name or DAG path.

    Returns:
        str: The short name of the node.
    """

    return node_name.rsplit("|", 1)[-1].rsplit(":", 1)[-1]


def _object_key(node_name: str) -> str:
    """Return a stable long name for comparing Maya objects.

    Parameters:
        node_name (str): Maya node name.

    Returns:
        str: The long name when available, otherwise the original name.
    """

    try:
        long_names = cmds.ls(node_name, long=True) or []
    except RuntimeError:
        return node_name
    return long_names[0] if long_names else node_name


def _unique_name(base_name: str) -> str:
    """Return a node name that does not exist in the scene.

    Parameters:
        base_name (str): Preferred node name.

    Returns:
        str: A unique node name.
    """

    if not cmds.objExists(base_name):
        return base_name

    index = 1
    while cmds.objExists(f"{base_name}{index}"):
        index += 1
    return f"{base_name}{index}"


def _get_mesh_transform_and_shape(mesh_name: str) -> tuple[str, str]:
    """Resolve a mesh transform and its non-intermediate mesh shape.

    Parameters:
        mesh_name (str): Transform or mesh shape name.

    Returns:
        tuple[str, str]: ``(transform, shape)``.

    Raises:
        ValueError: If the object is missing or has no non-intermediate mesh.
    """

    if not cmds.objExists(mesh_name):
        raise ValueError(f"Mesh '{mesh_name}' does not exist.")

    if cmds.objectType(mesh_name, isType="transform"):
        transform = mesh_name
        shapes = cmds.listRelatives(
            mesh_name,
            shapes=True,
            noIntermediate=True,
            fullPath=True,
        ) or []
        mesh_shapes = [
            shape for shape in shapes
            if cmds.objectType(shape, isType="mesh")
        ]
    elif cmds.objectType(mesh_name, isType="mesh"):
        mesh_shapes = [mesh_name]
        parents = cmds.listRelatives(mesh_name, parent=True, fullPath=True) or []
        transform = parents[0] if parents else mesh_name
    else:
        raise ValueError(
            f"Object '{mesh_name}' is not a mesh transform or mesh shape."
        )

    if not mesh_shapes:
        raise ValueError(
            f"Object '{mesh_name}' has no non-intermediate mesh shape."
        )

    if len(mesh_shapes) > 1:
        cmds.warning(
            f"Object '{mesh_name}' has multiple mesh shapes; "
            f"using '{mesh_shapes[0]}'."
        )

    return transform, mesh_shapes[0]


def _vertex_count(mesh_shape: str) -> int:
    """Return the number of vertices in a mesh shape.

    Parameters:
        mesh_shape (str): Mesh shape name.

    Returns:
        int: Vertex count.

    Raises:
        ValueError: If the mesh has no vertices.
    """

    vertex_count = cmds.polyEvaluate(mesh_shape, vertex=True)
    vertex_count = int(vertex_count or 0)
    if vertex_count <= 0:
        raise ValueError(f"Mesh '{mesh_shape}' has no vertices.")
    return vertex_count


def _base_matches_source(
    base_nodes: Sequence[str],
    source_transform: str,
    source_shape: str,
) -> bool:
    """Return whether a blendShape base matches the source mesh.

    Parameters:
        base_nodes (Sequence[str]): Base geometry names returned by the
            blendShape command.
        source_transform (str): Source mesh transform.
        source_shape (str): Source mesh shape.

    Returns:
        bool: True when one base node is the source transform or shape.
    """

    source_keys = {
        _object_key(source_transform),
        _object_key(source_shape),
    }
    return any(_object_key(base) in source_keys for base in base_nodes)


def _find_source_blendshape(
    source_transform: str,
    source_shape: str,
    requested_blendshape: Optional[str],
) -> str:
    """Resolve the blendShape node that deforms the source mesh.

    Parameters:
        source_transform (str): Source mesh transform.
        source_shape (str): Source mesh shape.
        requested_blendshape (str | None): Explicit blendShape override.

    Returns:
        str: The resolved blendShape node name.

    Raises:
        ValueError: If the blendShape is missing or ambiguous.
    """

    if requested_blendshape:
        if not cmds.objExists(requested_blendshape):
            raise ValueError(
                f"Source blendShape '{requested_blendshape}' does not exist."
            )
        if cmds.nodeType(requested_blendshape) != "blendShape":
            raise ValueError(
                f"Node '{requested_blendshape}' is not a blendShape node."
            )
        return requested_blendshape

    history = cmds.listHistory(source_transform) or []
    candidates: list[str] = []
    for node in history:
        if (
            cmds.nodeType(node) == "blendShape"
            and node not in candidates
        ):
            candidates.append(node)

    if not candidates:
        raise ValueError(
            f"No blendShape node was found in the history of '{source_transform}'."
        )

    matching = [
        candidate for candidate in candidates
        if _base_matches_source(
            cmds.blendShape(candidate, q=True, g=True) or [],
            source_transform,
            source_shape,
        )
    ]
    pool = matching or candidates

    if len(pool) == 1:
        return pool[0]

    names = ", ".join(sorted(pool))
    raise ValueError(
        f"Multiple blendShape nodes affect '{source_transform}': {names}. "
        "Pass source_blendshape explicitly."
    )


def _get_target_name(blendshape_name: str, target_index: int) -> str:
    """Return the alias of a blendShape target, with a safe fallback.

    Parameters:
        blendshape_name (str): BlendShape node name.
        target_index (int): Logical target index.

    Returns:
        str: Target alias, or ``target_<index>`` when the weight attribute
            exists without an alias.
    """

    try:
        alias = cmds.aliasAttr(
            f"{blendshape_name}.weight[{target_index}]",
            q=True,
        )
    except RuntimeError:
        alias = None

    return alias or f"target_{target_index}"


def _get_source_weight_map(
    blendshape: Blendshape,
    target_index: int,
    vertex_count: int,
) -> list[float]:
    """Read the target weight map for one source blendShape target.

    Unreadable maps fall back to a fully weighted map, and maps whose length
    does not match the mesh are padded with ``1.0`` or truncated so that the
    result always holds exactly ``vertex_count`` values.

    Parameters:
        blendshape (Blendshape): Source blendShape wrapper.
        target_index (int): Logical target index.
        vertex_count (int): Source mesh vertex count.

    Returns:
        list[float]: A dense weight map of ``vertex_count`` values.
    """

    try:
        values = blendshape.get_weight_map_values(target_index)
    except (RuntimeError, ValueError):
        values = None

    if values:
        if isinstance(values[0], (list, tuple)):
            values = list(values[0])
        values = [float(value) for value in values]
    else:
        values = [1.0] * vertex_count

    if len(values) < vertex_count:
        values.extend([1.0] * (vertex_count - len(values)))
    elif len(values) > vertex_count:
        cmds.warning(
            f"Weight map for target index {target_index} on "
            f"'{blendshape.name}' has {len(values)} values but the mesh has "
            f"{vertex_count} vertices; truncating the map."
        )
        values = values[:vertex_count]

    return values


def _get_source_targets(
    blendshape_name: str,
    vertex_count: int,
    selected_weights: Optional[Sequence[str]] = None,
) -> list[_TargetWeightMap]:
    """Collect target weight maps from the source blendShape.

    Parameters:
        blendshape_name (str): Source blendShape node name.
        vertex_count (int): Source mesh vertex count.
        selected_weights (Sequence[str] | None): Target names to include.
            ``None`` includes every target.

    Returns:
        list[_TargetWeightMap]: Targets ordered by logical target index.

    Raises:
        RuntimeError: If the blendShape has no target groups.
    """

    blendshape = Blendshape(blendshape_name)
    try:
        target_indices = cmds.getAttr(
            f"{blendshape_name}.inputTarget[0].inputTargetGroup",
            multiIndices=True,
        )
    except RuntimeError:
        target_indices = None

    if not target_indices:
        try:
            target_indices = cmds.getAttr(
                f"{blendshape_name}.weight",
                multiIndices=True,
            )
        except RuntimeError:
            target_indices = None

    target_indices = sorted({int(index) for index in target_indices or []})
    if not target_indices:
        raise RuntimeError(
            f"BlendShape '{blendshape_name}' has no targets to transfer."
        )

    target_names_by_index = {
        target_index: _get_target_name(blendshape_name, target_index)
        for target_index in target_indices
    }

    if selected_weights is None:
        selected_indices = target_indices
    else:
        if isinstance(selected_weights, str):
            selected_weights = [selected_weights]

        selected_names: list[str] = []
        seen_names: set[str] = set()
        for name in selected_weights:
            name = str(name)
            if name not in seen_names:
                seen_names.add(name)
                selected_names.append(name)

        available_names = set(target_names_by_index.values())
        missing_names = [
            name for name in selected_names
            if name not in available_names
        ]
        if missing_names:
            cmds.warning(
                f"Weight(s) not found on blendShape '{blendshape_name}' "
                f"and skipped: {', '.join(missing_names)}"
            )

        selected_name_set = set(selected_names)
        selected_indices = [
            target_index for target_index in target_indices
            if target_names_by_index[target_index] in selected_name_set
        ]

    targets: list[_TargetWeightMap] = []
    for target_index in selected_indices:
        targets.append(
            _TargetWeightMap(
                index=target_index,
                name=target_names_by_index[target_index],
                weights=_get_source_weight_map(
                    blendshape,
                    target_index,
                    vertex_count,
                ),
            )
        )
    return targets


def _get_source_target_directory_paths(
    blendshape_name: str,
    targets: Sequence[_TargetWeightMap],
) -> list[tuple[str, ...]]:
    """Collect root-relative folder paths for the selected targets only.

    The root is implicit regardless of its display name, so a target stored at
    the root maps to an empty tuple. Broken or cyclic ancestry is rejected
    before any destination or temporary node is created.

    Parameters:
        blendshape_name (str): Source blendShape node name.
        targets (Sequence[_TargetWeightMap]): Targets to collect paths for.

    Returns:
        list[tuple[str, ...]]: Folder names per target, ordered from the
            outermost folder to the target's direct parent.

    Raises:
        ValueError: If a target references a missing parent directory or the
            ancestry contains a cycle.
    """

    if not targets:
        return []

    blendshape = Blendshape(blendshape_name)
    directories = {
        directory.index: directory
        for directory in blendshape.get_target_dirs()
    }
    authored_parents = set(cmds.getAttr(
        f"{blendshape_name}.parentDirectory", multiIndices=True,
    ) or [])
    paths: list[tuple[str, ...]] = []
    for target in targets:
        index = (
            cmds.getAttr(f"{blendshape_name}.parentDirectory[{target.index}]")
            if target.index in authored_parents else 0
        )
        names: list[str] = []
        visited: set[int] = set()
        while index != 0:
            if index in visited or index not in directories:
                raise ValueError(
                    f"Invalid target directory ancestry for '{target.name}' "
                    f"on '{blendshape_name}' at directory index {index}."
                )
            visited.add(index)
            names.append(directories[index].name)
            index = cmds.getAttr(
                f"{blendshape_name}.targetDirectory[{index}].parentIndex"
            )
        paths.append(tuple(reversed(names)))
    return paths


def _resolve_target_directory(
    blendshape: Blendshape,
    path: tuple[str, ...],
    cache: dict[tuple[str, ...], TargetDirectory],
) -> TargetDirectory:
    """Resolve a folder path on the destination blendShape.

    Each folder is reused when a sibling with the same name already exists and
    created under its parent otherwise. Resolved prefixes are cached so that
    shared ancestors are only looked up or created once.

    Parameters:
        blendshape (Blendshape): Destination blendShape wrapper.
        path (tuple[str, ...]): Root-relative folder names from outermost to
            innermost. An empty path resolves to the root folder.
        cache (dict[tuple[str, ...], TargetDirectory]): Resolved folder cache,
            keyed by path prefix and updated in place.

    Returns:
        TargetDirectory: The innermost directory of ``path``.
    """

    parent = cache.setdefault(
        (), TargetDirectory(index=0, blendshape=blendshape.name),
    )
    for depth, name in enumerate(path, 1):
        prefix = path[:depth]
        if prefix not in cache:
            matches = [
                directory
                for directory in blendshape.get_target_dir_child_target_dirs(parent)
                if directory.name == name
            ]
            cache[prefix] = (
                min(matches, key=lambda directory: directory.index)
                if matches else blendshape.add_target_dir(name, parent.index)
            )
        parent = cache[prefix]
    return parent


def _safe_temp_name(name: str, index: int) -> str:
    """Return a Maya-safe temporary joint name for a target.

    Parameters:
        name (str): Original target name.
        index (int): Target index used for a fallback name.

    Returns:
        str: Sanitized name suitable for a temporary joint.
    """

    safe_name = "".join(
        character if character.isalnum() or character == "_" else "_"
        for character in name
    )
    if not safe_name:
        return f"target_{index}"
    if safe_name[0].isdigit():
        return f"target_{index}_{safe_name}"
    return safe_name


def _create_temp_namespace(prefix: str) -> str:
    """Create a unique root-level namespace for temporary nodes.

    Parameters:
        prefix (str): Namespace suffix identifying the source or destination.

    Returns:
        str: The created namespace name, without the absolute-path colon.
    """

    base_name = f"bsWeightTransfer_{prefix}"
    namespace = base_name
    index = 1
    while cmds.namespace(exists=f":{namespace}"):
        namespace = f"{base_name}{index}"
        index += 1

    cmds.namespace(add=f":{namespace}")
    return namespace


def _create_temp_side(
    mesh_transform: str,
    vertex_count: int,
    target_names: Sequence[str],
    prefix: str,
) -> tuple[str, str, list[str], str]:
    """Create a temporary duplicate, joint set, and skinCluster.

    The duplicate is history-free, so an existing skinCluster or other
    deformers on the original mesh are not carried into the temporary transfer
    surface.

    Parameters:
        mesh_transform (str): Original mesh transform to duplicate.
        vertex_count (int): Expected vertex count of the duplicate.
        target_names (Sequence[str]): Target names used for the joints.
        prefix (str): Namespace suffix identifying the source or destination.

    Returns:
        tuple[str, str, list[str], str]:
            ``(duplicate_mesh, skin_cluster, joints, namespace)``.
    """

    namespace = _create_temp_namespace(prefix)
    duplicate_mesh: Optional[str] = None
    skin_cluster: Optional[str] = None
    joints: list[str] = []
    used_names: set[str] = set()

    try:
        duplicate_mesh = cmds.duplicate(
            mesh_transform,
            name=f":{namespace}:mesh",
            upstreamNodes=False,
            inputConnections=False,
        )[0]

        try:
            cmds.delete(duplicate_mesh, constructionHistory=True)
        except RuntimeError as exc:
            cmds.warning(
                f"Could not remove history from duplicate '{duplicate_mesh}': "
                f"{exc}"
            )

        duplicate_transform, duplicate_shape = _get_mesh_transform_and_shape(
            duplicate_mesh
        )
        duplicate_vertex_count = _vertex_count(duplicate_shape)
        if duplicate_vertex_count != vertex_count:
            raise RuntimeError(
                f"Temporary duplicate '{duplicate_mesh}' has "
                f"{duplicate_vertex_count} vertices but the original mesh has "
                f"{vertex_count}."
            )

        remaining_skins = [
            node
            for node in (cmds.listHistory(duplicate_transform) or [])
            if cmds.nodeType(node) == "skinCluster"
        ]
        if remaining_skins:
            raise RuntimeError(
                f"Temporary duplicate '{duplicate_mesh}' still has a "
                f"skinCluster ({', '.join(remaining_skins)})."
            )

        for index, target_name in enumerate(target_names):
            safe_name = _safe_temp_name(target_name, index)
            unique_name = safe_name
            suffix = 1
            while unique_name in used_names:
                unique_name = f"{safe_name}{suffix}"
                suffix += 1
            used_names.add(unique_name)

            joints.append(
                cmds.createNode(
                    "joint",
                    name=f":{namespace}:{unique_name}",
                    skipSelect=True,
                )
            )

        skin_cluster = cmds.skinCluster(
            *joints,
            duplicate_transform,
            toSelectedBones=True,
            bindMethod=0,
            normalizeWeights=0,
            maximumInfluences=max(1, len(joints)),
            name=f":{namespace}:skin",
        )[0]

        try:
            cmds.setAttr(f"{skin_cluster}.normalizeWeights", 0)
            cmds.setAttr(f"{skin_cluster}.maxInfluences", len(joints))
            cmds.setAttr(f"{skin_cluster}.envelope", 0)
        except RuntimeError as exc:
            cmds.warning(
                f"Could not disable normalization on '{skin_cluster}': {exc}"
            )

        return duplicate_mesh, skin_cluster, joints, namespace
    except Exception:
        _cleanup_temp_side(
            skin_cluster,
            joints,
            duplicate_mesh,
            namespace,
        )
        raise


def _map_joints_to_influences(
    skin_cluster: str,
    joints: Sequence[str],
) -> list[int]:
    """Map each temporary joint to its skinCluster influence index.

    Parameters:
        skin_cluster (str): Temporary skinCluster name.
        joints (Sequence[str]): Joints in target order.

    Returns:
        list[int]: Influence indices aligned with ``joints``.

    Raises:
        RuntimeError: If a joint is not an influence of the skinCluster.
    """

    influences = cmds.skinCluster(skin_cluster, q=True, inf=True) or []
    influence_lookup: dict[str, int] = {}
    for index, influence in enumerate(influences):
        influence_lookup.setdefault(_name_key(influence), index)

    joint_indices: list[int] = []
    for joint in joints:
        key = _name_key(joint)
        if key not in influence_lookup:
            raise RuntimeError(
                f"Joint '{joint}' is not an influence of '{skin_cluster}'."
            )
        joint_indices.append(influence_lookup[key])

    return joint_indices


def _assign_weight_maps(
    skin_cluster: str,
    joints: Sequence[str],
    weight_maps: Sequence[Sequence[float]],
) -> None:
    """Write per-target weight maps into a temporary skinCluster.

    Parameters:
        skin_cluster (str): Destination skinCluster name.
        joints (Sequence[str]): Joints aligned with ``weight_maps``.
        weight_maps (Sequence[Sequence[float]]): Per-target weight maps.

    Returns:
        None

    Raises:
        ValueError: If the map count or map lengths are inconsistent.
    """

    if len(joints) != len(weight_maps):
        raise ValueError(
            "The number of temporary joints and weight maps must match."
        )

    vertex_count = len(weight_maps[0]) if weight_maps else 0
    for weight_map in weight_maps:
        if len(weight_map) != vertex_count:
            raise ValueError("All source weight maps must have the same length.")

    influences = cmds.skinCluster(skin_cluster, q=True, inf=True) or []
    influence_count = len(influences)
    joint_indices = _map_joints_to_influences(skin_cluster, joints)

    for vertex in range(vertex_count):
        values = [0.0] * influence_count
        for influence_index, weight_map in zip(joint_indices, weight_maps):
            values[influence_index] = float(weight_map[vertex])

        cmds.setAttr(
            f"{skin_cluster}.weightList[{vertex}].weights[0:{influence_count - 1}]",
            *values,
            size=influence_count,
        )


def _read_skin_weight_maps(
    skin_cluster: str,
    joints: Sequence[str],
    vertex_count: int,
) -> list[list[float]]:
    """Read per-target weight maps back from a temporary skinCluster.

    Parameters:
        skin_cluster (str): SkinCluster to read.
        joints (Sequence[str]): Joints in target order.
        vertex_count (int): Mesh vertex count.

    Returns:
        list[list[float]]: Weight maps aligned with ``joints``.
    """

    skin = SkinCluster(skin_cluster)
    joint_lookup = {
        _name_key(joint): index
        for index, joint in enumerate(joints)
    }
    weight_maps = [[0.0] * vertex_count for _ in joints]

    for vertex, weights_by_influence in skin.weight_data.items():
        for influence_name, weight in weights_by_influence.items():
            target_index = joint_lookup.get(_name_key(influence_name))
            if target_index is not None:
                weight_maps[target_index][vertex] = float(weight)

    return weight_maps


def _mesh_dag_path(mesh_name: str) -> "om.MDagPath":
    """Return the mesh shape DAG path of a transform or shape name.

    Parameters:
        mesh_name (str): Mesh transform or mesh shape name.

    Returns:
        om.MDagPath: DAG path of the mesh shape.

    Raises:
        ValueError: If the node is not a mesh.
    """

    selection = om.MSelectionList()
    selection.add(mesh_name)
    dag_path = selection.getDagPath(0)
    if dag_path.apiType() == om.MFn.kTransform:
        dag_path.extendToShape()
    if dag_path.apiType() != om.MFn.kMesh:
        raise ValueError(f"Node '{mesh_name}' is not a mesh.")
    return dag_path


def _skin_cluster_fn(skin_cluster: str) -> "oma.MFnSkinCluster":
    """Return an API 2.0 ``MFnSkinCluster`` for a skinCluster node.

    Parameters:
        skin_cluster (str): SkinCluster node name.

    Returns:
        oma.MFnSkinCluster: Function set bound to the node.
    """

    selection = om.MSelectionList()
    selection.add(skin_cluster)
    return oma.MFnSkinCluster(selection.getDependNode(0))


def _skin_influence_names(skin_cluster: str) -> list[str]:
    """Return the influence names of a skinCluster in its own order.

    Parameters:
        skin_cluster (str): SkinCluster node name.

    Returns:
        list[str]: Influence names, aligned with the weight lists of the
        cluster and with the order ``MFnSkinCluster.setWeights`` expects.
    """

    influence_paths = _skin_cluster_fn(skin_cluster).influenceObjects()
    return [path.partialPathName() for path in influence_paths]


def _full_vertex_component(vertex_count: int) -> "om.MObject":
    """Build a single indexed component covering every vertex of a mesh.

    Parameters:
        vertex_count (int): Number of vertices to cover.

    Returns:
        om.MObject: Mesh vertex component holding ``0 .. vertex_count - 1``.
    """

    component_fn = om.MFnSingleIndexedComponent()
    component = component_fn.create(om.MFn.kMeshVertComponent)
    vertex_count = int(vertex_count)
    if vertex_count > 0:
        # ``addElements`` expects an MIntArray; a Python range/list is silently
        # bound to something else on some Maya versions, which leaves the
        # component covering only a couple of vertices.
        elements = om.MIntArray()
        for vertex_id in range(vertex_count):
            elements.append(vertex_id)
        component_fn.addElements(elements)
    return component


def _skin_weights_flat(
    skin_cluster: str,
    vertex_count: int,
    influence_count: int,
) -> np.ndarray:
    """Read a skinCluster weight list as a flat ``(vertex, influence)`` array.

    One ``getAttr`` of the whole ``weightList`` range is used instead of
    ``MFnSkinCluster.getWeights``: it needs no component object and therefore
    cannot silently return the weights of only a couple of vertices.

    Parameters:
        skin_cluster (str): SkinCluster to read.
        vertex_count (int): Number of vertices to read.
        influence_count (int): Number of influences per vertex.

    Returns:
        numpy.ndarray: ``vertex_count * influence_count`` weights, vertex major.

    Raises:
        RuntimeError: If the skinCluster returns a different number of weights.
    """

    attribute = (f"{skin_cluster}.weightList[0:{int(vertex_count) - 1}]"
                 f".weights[0:{int(influence_count) - 1}]")
    values = cmds.getAttr(attribute) or []
    weights = np.asarray(values, dtype=np.float64).ravel()
    expected = int(vertex_count) * int(influence_count)
    if weights.size != expected:
        # A skinCluster keeps weight lists for removed vertices, so the range
        # can be longer than the mesh; only a shorter result is an error.
        if influence_count and weights.size % influence_count == 0 \
                and weights.size > expected:
            cmds.warning(
                f"SkinCluster '{skin_cluster}' holds "
                f"{weights.size // influence_count} weight lists for "
                f"{vertex_count} vertices: using the first ones."
            )
            weights = weights[:expected]
        else:
            raise RuntimeError(
                f"SkinCluster '{skin_cluster}' returned {weights.size} "
                f"weights but {expected} were expected for {vertex_count} "
                f"vertices and {influence_count} influences."
            )
    return weights


def _joint_influence_indices(
    skin_cluster: str,
    joints: Sequence[str],
) -> list[int]:
    """Map joints to skinCluster influence indices, in the given order.

    The indices follow ``MFnSkinCluster.influenceObjects()``, which is the
    order ``MFnSkinCluster.getWeights``/``setWeights`` use.

    Parameters:
        skin_cluster (str): SkinCluster node name.
        joints (Sequence[str]): Joints in the wanted order.

    Returns:
        list[int]: Influence index per joint.

    Raises:
        RuntimeError: If a joint is not an influence of the skinCluster.
    """

    influence_lookup: dict[str, int] = {}
    for index, influence_name in enumerate(_skin_influence_names(skin_cluster)):
        influence_lookup.setdefault(_name_key(influence_name), index)

    skin_fn = _skin_cluster_fn(skin_cluster)
    indices: list[int] = []
    for joint in joints:
        key = _name_key(joint)
        if key not in influence_lookup:
            raise RuntimeError(
                f"Joint '{joint}' is not an influence of '{skin_cluster}'."
            )
        # Prefer the index the cluster reports for the influence object: the
        # name lookup above only orders the joints, this is what the weight
        # arrays are laid out with.
        try:
            selection = om.MSelectionList()
            selection.add(joint)
            indices.append(int(skin_fn.indexForInfluenceObject(
                selection.getDagPath(0)
            )))
        except (RuntimeError, ValueError):
            indices.append(influence_lookup[key])
    return indices


def _assign_weight_maps_bulk(
    skin_cluster: str,
    mesh_name: str,
    joints: Sequence[str],
    weight_maps: Sequence[Sequence[float]],
) -> None:
    """Write per-target weight maps into a skinCluster in one API call.

    This is the bulk twin of :func:`_assign_weight_maps`, which loops over the
    vertices with one ``cmds.setAttr`` each. Both leave every influence that is
    not part of ``joints`` at zero.

    Parameters:
        skin_cluster (str): SkinCluster to write.
        mesh_name (str): Mesh the skinCluster deforms.
        joints (Sequence[str]): Joints aligned with ``weight_maps``.
        weight_maps (Sequence[Sequence[float]]): Per-target weight maps.

    Returns:
        None

    Raises:
        ValueError: If the map count or map lengths are inconsistent.
    """

    if len(joints) != len(weight_maps):
        raise ValueError(
            "The number of temporary joints and weight maps must match."
        )

    vertex_count = len(weight_maps[0]) if weight_maps else 0
    for weight_map in weight_maps:
        if len(weight_map) != vertex_count:
            raise ValueError("All source weight maps must have the same length.")
    if vertex_count == 0:
        return

    influence_count = len(_skin_influence_names(skin_cluster))
    if influence_count == 0:
        raise RuntimeError(f"SkinCluster '{skin_cluster}' has no influences.")

    matrix = np.zeros((vertex_count, influence_count), dtype=np.float64)
    for influence_index, weight_map in zip(
        _joint_influence_indices(skin_cluster, joints), weight_maps
    ):
        matrix[:, influence_index] = np.asarray(weight_map, dtype=np.float64)

    # ``MFnSkinCluster.setWeights`` wants MIntArray/MDoubleArray arguments; a
    # plain list is bound as an integer by the API 2.0 wrapper and fails with
    # "'list' object cannot be interpreted as an integer".
    influence_indices = om.MIntArray()
    for influence_index in range(influence_count):
        influence_indices.append(influence_index)

    try:
        _skin_cluster_fn(skin_cluster).setWeights(
            _mesh_dag_path(mesh_name),
            _full_vertex_component(vertex_count),
            influence_indices,
            om.MDoubleArray(matrix.reshape(-1).tolist()),
            normalize=False,
        )
        written = _skin_weights_flat(skin_cluster, vertex_count, influence_count)
        if np.allclose(written, matrix.reshape(-1), atol=1e-6):
            return
        cmds.warning(
            f"Bulk weight write to '{skin_cluster}' did not match the input: "
            f"falling back to a per-vertex write."
        )
    except RuntimeError as exc:
        cmds.warning(
            f"Bulk weight write to '{skin_cluster}' failed ({exc}): falling "
            f"back to a per-vertex write."
        )

    # The API path can be unavailable or lossy depending on the Maya version;
    # the per-vertex write is slower but always correct.
    _assign_weight_maps(skin_cluster, joints, weight_maps)


def _read_skin_weight_maps_bulk(
    skin_cluster: str,
    mesh_name: str,
    joints: Sequence[str],
    vertex_count: int,
) -> list[np.ndarray]:
    """Read per-target weight maps from a skinCluster in one API call.

    This is the bulk twin of :func:`_read_skin_weight_maps`.

    Parameters:
        skin_cluster (str): SkinCluster to read.
        mesh_name (str): Mesh the skinCluster deforms.
        joints (Sequence[str]): Joints in the wanted order.
        vertex_count (int): Mesh vertex count.

    Returns:
        list[numpy.ndarray]: ``float64`` weight maps aligned with ``joints``.

    Raises:
        RuntimeError: If a joint is not an influence of the skinCluster.
    """

    if vertex_count <= 0:
        return [np.empty(0, dtype=np.float64) for _ in joints]

    influence_count = len(_skin_influence_names(skin_cluster))
    if influence_count == 0:
        raise RuntimeError(f"SkinCluster '{skin_cluster}' has no influences.")

    weights = _skin_weights_flat(skin_cluster, vertex_count, influence_count)
    matrix = weights.reshape(vertex_count, influence_count)
    return [
        matrix[:, influence_index].copy()
        for influence_index in _joint_influence_indices(skin_cluster, joints)
    ]


def _get_uv_set(mesh_name: str, requested_uv_set: Optional[str]) -> str:
    """Resolve and validate a mesh UV set.

    Parameters:
        mesh_name (str): Mesh transform or shape name.
        requested_uv_set (str | None): Explicit UV set override.

    Returns:
        str: The UV set to use for the transfer.

    Raises:
        ValueError: If the evaluated mesh has no UV sets, the requested set is
            missing, or the selected set has no assigned UVs.
    """

    # Query the evaluated, non-intermediate shape. A transform's UV-set
    # attributes can also list stale sets from upstream/intermediate meshes.
    _, mesh_shape = _get_mesh_transform_and_shape(mesh_name)
    selection = om.MSelectionList()
    selection.add(mesh_shape)
    mesh_fn = om.MFnMesh(selection.getDagPath(0))
    uv_sets = list(mesh_fn.getUVSetNames())
    if not uv_sets:
        raise ValueError(f"Mesh '{mesh_name}' has no UV sets.")

    if requested_uv_set:
        if requested_uv_set not in uv_sets:
            raise ValueError(
                f"UV set '{requested_uv_set}' does not exist on "
                f"'{mesh_name}'. Available UV sets: {', '.join(uv_sets)}."
            )
        resolved_uv_set = requested_uv_set
    else:
        resolved_uv_set = mesh_fn.currentUVSetName()
        if resolved_uv_set not in uv_sets:
            cmds.warning(
                f"Could not determine the current UV set on '{mesh_name}'; "
                f"using '{uv_sets[0]}'."
            )
            resolved_uv_set = uv_sets[0]

    _, assigned_uvs = mesh_fn.getAssignedUVs(resolved_uv_set)
    if mesh_fn.numUVs(resolved_uv_set) == 0 or len(assigned_uvs) == 0:
        raise ValueError(
            f"UV set '{resolved_uv_set}' on '{mesh_name}' has no assigned UVs."
        )
    return resolved_uv_set


def _copy_skin_weights(
    source_skin: str,
    destination_skin: str,
    source_uv_set: str,
    destination_uv_set: str,
    transfer_method: WeightsTransferMethod
) -> None:
    """Copy the temporary skinCluster weights onto the destination one.

    Influences are matched one-to-one by joint name, so the joint order of the
    two temporary skinClusters does not matter.

    Parameters:
        source_skin (str): Source skinCluster name.
        destination_skin (str): Destination skinCluster name.
        source_uv_set (str): UV set on the source mesh, used for the UV-space
            transfer.
        destination_uv_set (str): UV set on the destination mesh, used for the
            UV-space transfer.
        transfer_method (WeightsTransferMethod): Surface association passed to
            ``copySkinWeights``. ``WeightsTransferMethod.UVS`` (the default) transfers in UV space
            using the given UV sets; any other value, such as
            ``WeightsTransferMethod.CLOSEST_POINT``, ``WeightsTransferMethod.CLOSEST_COMPONENT``, or ``WeightsTransferMethod.RAY_CAST``, is
            used as-is and ignores the UV sets.

    Returns:
        None
    """

    # Maya uses the uvSpace flag together with the closestPoint surface mode
    # to enable the UV-space transfer path. There is no separate "uvSpace"
    # surface-association value in Maya 2026.
    args = {"ss": source_skin,
            "ds": destination_skin,
            "noMirror": True,
            "influenceAssociation": "oneToOne",
            "surfaceAssociation": transfer_method.value}
    if transfer_method == WeightsTransferMethod.UVS:
        args["surfaceAssociation"] = "closestPoint"
        args["uvSpace"] = [source_uv_set, destination_uv_set]

    cmds.copySkinWeights(**args)


def _create_destination_blendshape(
    destination_transform: str,
    destination_shape: str,
    target_names: Sequence[str],
    weight_maps: Sequence[Sequence[float]],
    destination_blendshape: Optional[str],
    target_directory_paths: Optional[Sequence[tuple[str, ...]]] = None,
) -> str:
    """Reuse or create the destination blendShape and write its weight maps.

    Existing blendShape targets are matched by alias and their target-weight
    maps are overwritten. Missing target aliases are appended to the node.

    Parameters:
        destination_transform (str): Destination mesh transform.
        destination_shape (str): Destination mesh shape.
        target_names (Sequence[str]): Target names in source order.
        weight_maps (Sequence[Sequence[float]]): Transferred weight maps.
        destination_blendshape (str | None): Existing destination blendShape
            name, or a name to use for a newly created blendShape.
        target_directory_paths (Sequence[tuple[str, ...]] | None): Root-relative
            source folder paths aligned with targets. ``None`` leaves existing
            organization unchanged; an empty tuple places a target at the root.

    Returns:
        str: The destination blendShape name.

    Raises:
        ValueError: If an existing node is not a blendShape, is not connected
            to the destination mesh, or the maps are invalid.
        RuntimeError: If a target alias cannot be created correctly.
    """

    if len(target_names) != len(weight_maps):
        raise ValueError(
            "The number of destination target names and weight maps must match."
        )

    if (
        target_directory_paths is not None
        and len(target_directory_paths) != len(target_names)
    ):
        raise ValueError(
            "The number of target directory paths and targets must match."
        )

    directory_cache: dict[tuple[str, ...], TargetDirectory] = {}
    created_new = False
    if destination_blendshape and cmds.objExists(destination_blendshape):
        if cmds.nodeType(destination_blendshape) != "blendShape":
            raise ValueError(
                f"Destination node '{destination_blendshape}' is not a "
                f"blendShape."
            )

        base_nodes = cmds.blendShape(
            destination_blendshape,
            q=True,
            g=True,
        ) or []
        if not _base_matches_source(
            base_nodes,
            destination_transform,
            destination_shape,
        ):
            raise ValueError(
                f"Destination blendShape '{destination_blendshape}' is not "
                f"connected to '{destination_transform}'."
            )

        blendshape = Blendshape(destination_blendshape)
    else:
        blendshape_name = destination_blendshape or _unique_name(
            f"{_name_key(destination_transform)}_transferredWeightMaps_BS"
        )
        blendshape = Blendshape.create(
            blendshape_name,
            destination_transform,
        )
        created_new = True

    try:
        for index, target_name in enumerate(target_names):
            weight = blendshape.get_weight_by_name(target_name)
            if weight is None:
                weight = blendshape.add_target(target_name)
                if weight is None:
                    raise RuntimeError(
                        f"Could not add target '{target_name}' to "
                        f"'{blendshape.name}'."
                    )
                if str(weight) != target_name:
                    raise RuntimeError(
                        f"Could not create target alias '{target_name}' on "
                        f"'{blendshape.name}'."
                    )

            blendshape.set_weight_map_values(
                weight.id,
                list(weight_maps[index]),
            )
            if target_directory_paths is not None:
                directory = _resolve_target_directory(
                    blendshape, target_directory_paths[index], directory_cache,
                )
                blendshape.set_weight_parent_directory(weight, directory)
    except Exception:
        if created_new:
            _delete_node(blendshape.name)
        raise

    return blendshape.name


def _delete_node(node_name: Optional[str]) -> None:
    """Delete a node if it still exists.

    Parameters:
        node_name (str | None): Node to delete.

    Returns:
        None
    """

    if node_name and cmds.objExists(node_name):
        try:
            cmds.delete(node_name)
        except RuntimeError as exc:
            cmds.warning(f"Could not delete temporary node '{node_name}': {exc}")


def _cleanup_temp_side(
    skin_cluster: Optional[str],
    joints: Sequence[str],
    duplicate_mesh: Optional[str],
    namespace: Optional[str],
) -> None:
    """Delete one temporary duplicate, skinCluster, joints, and namespace.

    Parameters:
        skin_cluster (str | None): Temporary skinCluster name.
        joints (Sequence[str]): Temporary joints.
        duplicate_mesh (str | None): Temporary duplicate mesh name.
        namespace (str | None): Temporary namespace.

    Returns:
        None
    """

    _delete_node(skin_cluster)
    _delete_node(duplicate_mesh)

    remaining_joints = [
        joint for joint in joints
        if joint and cmds.objExists(joint)
    ]
    if remaining_joints:
        try:
            cmds.delete(remaining_joints)
        except RuntimeError as exc:
            cmds.warning(
                f"Could not delete temporary joints {remaining_joints}: {exc}"
            )

    if not namespace:
        return

    absolute_namespace = f":{namespace}"
    if not cmds.namespace(exists=absolute_namespace):
        return

    try:
        cmds.namespace(
            removeNamespace=absolute_namespace,
            mergeNamespaceWithRoot=False,
        )
    except RuntimeError as exc:
        cmds.warning(
            f"Could not remove temporary namespace '{namespace}': {exc}"
        )


def _restore_selection(selection: Sequence[str]) -> None:
    """Restore a previously captured selection.

    Parameters:
        selection (Sequence[str]): Selection to restore.

    Returns:
        None
    """

    try:
        if selection:
            cmds.select(selection, replace=True)
        else:
            cmds.select(clear=True)
    except RuntimeError as exc:
        cmds.warning(f"Could not restore the previous selection: {exc}")


@undoable
def transfer_blendshape_weight_maps(
    source_mesh: str,
    destination_mesh: str,
    transfer_method: WeightsTransferMethod,
    source_blendshape: Optional[str] = None,
    source_uv_set: Optional[str] = None,
    destination_uv_set: Optional[str] = None,
    destination_blendshape: Optional[str] = None,
    selected_weights: Optional[Sequence[str]] = None,
    organize_target_directories: bool = False,
) -> str:
    """Transfer blendShape target weight maps from one mesh to another.

    Two temporary skinClusters are created on history-free duplicates of the
    source and destination meshes, with one joint per blendShape target. The
    source target weight maps are written to the source skinCluster,
    ``copySkinWeights`` transfers them to the destination skinCluster using the
    requested ``WeightsTransferMethod`` (UV space by default), and
    the transferred maps are written to a destination blendShape. An existing
    destination blendShape is reused: matching target aliases are overwritten
    and missing targets are added. Existing skinClusters on the original meshes
    are never modified. All temporary duplicate meshes, skinClusters, joints,
    and namespaces are removed.

    Parameters:
        source_mesh (str): Source mesh transform or shape with a blendShape.
        destination_mesh (str): Destination mesh transform or shape.
        source_blendshape (str | None): Explicit source blendShape node. When
            omitted, the blendShape affecting ``source_mesh`` is auto-detected.
        source_uv_set (str | None): Source UV set. Defaults to the current set
            on the original source mesh, not its temporary duplicate.
        destination_uv_set (str | None): Destination UV set. Defaults to the
            current set on the original destination mesh.
        transfer_method (WeightsTransferMethod): Surface association requested for the copy.
            ``WeightsTransferMethod.UVS`` (the default) transfers in UV space using the resolved
            UV sets; any other value, such as ``WeightsTransferMethod.CLOSEST_POINT``,
            ``WeightsTransferMethod.CLOSEST_COMPONENT``, or ``WeightsTransferMethod.RAY_CAST``,
            is passed to ``copySkinWeights`` as the surface association and ignores the UV sets.
        destination_blendshape (str | None): Destination blendShape name.
            When the node exists it is reused and matching target weight maps
            are overwritten; when it does not exist it is created. ``None``
            creates a unique new blendShape.
        selected_weights (Sequence[str] | None): Target weight names to
            transfer. ``None`` transfers every source target. Missing names
            are warned about and skipped. An empty list creates a destination
            blendShape with no targets.
        organize_target_directories (bool): When True, recreate/reuse the source
            folder hierarchy for transferred targets, including moving existing
            matching targets. Root-level source targets move to the destination
            root. Only needed folders are created; unrelated destination targets
            and folder settings are unchanged. Defaults to False.

    Returns:
        str: Name of the destination blendShape (existing or newly created).

    Raises:
        ValueError: If the meshes, blendShape, UV sets, or arguments are
            invalid, including an existing destination blendShape that is not
            connected to the destination mesh.
        RuntimeError: If temporary skin construction or target creation fails.

    Example:
        >>> transfer_blendshape_weight_maps(
        ...     "sourceMesh",
        ...     "destinationMesh",
        ...     source_uv_set="map1",
        ...     destination_uv_set="map1",
        ...     destination_blendshape="destinationWeightMaps_BS",
        ...     selected_weights=["Smile", "Frown"],
        ...     organize_target_directories=True,
        ... )
        'destinationWeightMaps_BS'
    """

    source_transform, source_shape = _get_mesh_transform_and_shape(source_mesh)
    destination_transform, destination_shape = _get_mesh_transform_and_shape(
        destination_mesh
    )

    if _object_key(source_transform) == _object_key(destination_transform):
        raise ValueError(
            "Source and destination must be different mesh objects."
        )

    source_vertex_count = _vertex_count(source_shape)
    destination_vertex_count = _vertex_count(destination_shape)

    blendshape_name = _find_source_blendshape(
        source_transform,
        source_shape,
        source_blendshape,
    )
    targets = _get_source_targets(
        blendshape_name,
        source_vertex_count,
        selected_weights,
    )
    target_names = [target.name for target in targets]
    source_weight_maps = [target.weights for target in targets]
    target_directory_paths = (
        _get_source_target_directory_paths(blendshape_name, targets)
        if organize_target_directories else None
    )

    original_selection = cmds.ls(selection=True) or []
    if not targets:
        try:
            return _create_destination_blendshape(
                destination_transform,
                destination_shape,
                [],
                [],
                destination_blendshape,
            )
        finally:
            _restore_selection(original_selection)

    # Duplicating/deleting history can change a mesh's current UV set (and
    # expose stale UV-set attributes). Capture the user's choices before that
    # happens, just as the transfer UI does on the original meshes.
    resolved_source_uv = _get_uv_set(source_shape, source_uv_set)
    resolved_destination_uv = _get_uv_set(destination_shape, destination_uv_set)

    source_duplicate: Optional[str] = None
    destination_duplicate: Optional[str] = None
    source_skin: Optional[str] = None
    destination_skin: Optional[str] = None
    source_joints: list[str] = []
    destination_joints: list[str] = []
    source_namespace: Optional[str] = None
    destination_namespace: Optional[str] = None
    created_blendshape: Optional[str] = None

    try:
        (
            source_duplicate,
            source_skin,
            source_joints,
            source_namespace,
        ) = _create_temp_side(
            source_transform,
            source_vertex_count,
            target_names,
            "src",
        )
        _assign_weight_maps(
            source_skin,
            source_joints,
            source_weight_maps,
        )

        (
            destination_duplicate,
            destination_skin,
            destination_joints,
            destination_namespace,
        ) = _create_temp_side(
            destination_transform,
            destination_vertex_count,
            target_names,
            "dst",
        )

        # Validate that the selected sets survived duplication and binding.
        _get_uv_set(source_duplicate, resolved_source_uv)
        _get_uv_set(destination_duplicate, resolved_destination_uv)

        _copy_skin_weights(
            source_skin,
            destination_skin,
            resolved_source_uv,
            resolved_destination_uv,
            transfer_method,
        )

        destination_weight_maps = _read_skin_weight_maps(
            destination_skin,
            destination_joints,
            destination_vertex_count,
        )
        created_blendshape = _create_destination_blendshape(
            destination_transform,
            destination_shape,
            target_names,
            destination_weight_maps,
            destination_blendshape,
            target_directory_paths=target_directory_paths,
        )
        return created_blendshape
    finally:
        _cleanup_temp_side(
            source_skin,
            source_joints,
            source_duplicate,
            source_namespace,
        )
        _cleanup_temp_side(
            destination_skin,
            destination_joints,
            destination_duplicate,
            destination_namespace,
        )
        _restore_selection(original_selection)


def _resolve_sampled_weight_ids(
    blendshape_name: str,
    weight_ids: Optional[Sequence[int]] = None,
) -> list[int]:
    """Resolve the target ids a sampling run works on.

    Parameters:
        blendshape_name (str): BlendShape node name.
        weight_ids (Sequence[int], optional): Target logical indices to keep.
            ``None`` selects every ``inputTargetGroup`` of the node.

    Returns:
        list[int]: One target id per weight map to sample.

    Raises:
        ValueError: If the node has no weight map or an id is unknown.
    """

    existing = [int(group) for group in
                cmds.getAttr(
                    f"{blendshape_name}.inputTarget[0].inputTargetGroup",
                    multiIndices=True) or []]
    if weight_ids is None:
        if not existing:
            raise ValueError(f"Blendshape '{blendshape_name}' has no target "
                             f"weight maps to sample.")
        return existing

    resolved: list[int] = []
    for weight_id in weight_ids:
        resolved_id = int(weight_id)
        if resolved_id not in existing:
            raise ValueError(
                f"Weight id {resolved_id} of '{blendshape_name}' has no weight "
                f"map (existing weight maps: {existing or 'none'})."
            )
        resolved.append(resolved_id)
    if not resolved:
        raise ValueError("No weight map selected to sample.")
    return resolved


def _mirror_mesh_points(
    mesh_name: str,
    axis_index: int,
    symmetry_centre: Optional[float] = None,
) -> None:
    """Mirror the points of a mesh in place across one object-space axis.

    Parameters:
        mesh_name (str): Mesh transform or shape to mirror.
        axis_index (int): ``0`` for X, ``1`` for Y, ``2`` for Z.
        symmetry_centre (float, optional): Axis coordinate of the mirror plane.
            Defaults to the centre of the bounding box along the axis.

    Returns:
        None
    """

    mesh_fn = om.MFnMesh(_mesh_dag_path(mesh_name))
    points = mesh_fn.getPoints(om.MSpace.kObject)
    if len(points) == 0:
        return
    coordinates = [point[axis_index] for point in points]
    centre = (float(symmetry_centre) if symmetry_centre is not None
              else (min(coordinates) + max(coordinates)) / 2.0)

    # Build a fresh MPointArray instead of editing the MPoint objects in place:
    # MPoint's item assignment is not available on every Maya version this
    # package supports, while the constructor always is.
    mirrored_points = om.MPointArray()
    for point in points:
        components = [point[0], point[1], point[2]]
        components[axis_index] = 2.0 * centre - components[axis_index]
        mirrored_points.append(
            om.MPoint(components[0], components[1], components[2])
        )
    mesh_fn.setPoints(mirrored_points, om.MSpace.kObject)


def sample_mirrored_weight_maps(
    mesh_name: str,
    blendshape_name: str,
    weight_ids: Optional[Sequence[int]] = None,
    mirror_axis: str = "x",
    symmetry_centre: Optional[float] = None,
    progress=None,
    show_progress: bool = True,
) -> dict[int, np.ndarray]:
    """Sample the weight maps of a blendShape at their mirrored positions.

    Every vertex of ``mesh_name`` is reflected across the plane perpendicular to
    ``mirror_axis`` and the weight maps are read back from the surface at those
    reflected positions, so an asymmetric mesh still receives the weights of its
    opposite side. The sampling is done by Maya itself: two history-free
    duplicates get a temporary skinCluster whose joints stand for the
    blendShape targets, the source maps are written into the source cluster and
    one ``copySkinWeights`` call (``surfaceAssociation="closestPoint"``)
    transfers all of them onto the mirrored duplicate at once.

    This is the sampled twin of the vertex pairing in
    ``mayaUtils.mirror_blendshape_weight_map``: instead of pairing vertex ids it
    interpolates the weights of the triangle the reflected position lands on,
    which is both faster on dense meshes and smooth on meshes that are not
    exactly symmetric.

    Parameters:
        mesh_name (str): Mesh transform or shape that owns the weight maps. It
            has to be the base mesh of ``blendshape_name``.
        blendshape_name (str): BlendShape node owning the weight maps.
        weight_ids (Sequence[int], optional): Target logical indices to sample.
            ``None`` samples every ``inputTargetGroup`` weight map of the node.
        mirror_axis (str): Object-space axis of the mirror, ``"x"`` (default),
            ``"y"`` or ``"z"``.
        symmetry_centre (float, optional): Axis coordinate of the mirror plane.
            Defaults to the centre of the bounding box along the axis.
        progress (callable, optional): Called as ``progress(done, total)`` while
            the transfer runs, so a caller can drive a progress bar.
        show_progress (bool): Whether Maya's main progress bar is shown when no
            ``progress`` callback is given. Defaults to ``True``.

    Returns:
        dict[int, numpy.ndarray]: ``{weight_id: sampled values}`` with one
        ``float64`` value per vertex of ``mesh_name``.

    Raises:
        ValueError: If the mesh, the blendShape or a weight id is invalid, or if
            ``mesh_name`` is not the base mesh of ``blendshape_name``.
        RuntimeError: If the temporary skinCluster transfer fails.
        mayaUtils.MirrorCancelled: When the shown progress bar is cancelled.

    Example:
        >>> sampled = sample_mirrored_weight_maps("head_geo", "head_blendShapes",
        ...                                       weight_ids=[3])
        >>> sampled[3].shape
        (41281,)
    """

    axis_index = mayaUtils._mirror_axis_index(mirror_axis)
    source_transform, source_shape = _get_mesh_transform_and_shape(mesh_name)
    vertex_count = _vertex_count(source_shape)
    if vertex_count == 0:
        raise ValueError(f"Mesh '{mesh_name}' has no vertices to sample.")

    if not cmds.objExists(blendshape_name):
        raise ValueError(f"Blendshape node '{blendshape_name}' does not exist.")
    if cmds.nodeType(blendshape_name) != "blendShape":
        raise ValueError(f"'{blendshape_name}' is not a blendShape node.")

    base_nodes = cmds.blendShape(blendshape_name, query=True, geometry=True) or []
    if not base_nodes:
        raise ValueError(f"Blendshape '{blendshape_name}' has no base mesh.")
    if not _base_matches_source(base_nodes, source_transform, source_shape):
        raise ValueError(
            f"Mesh '{mesh_name}' is not the base mesh of "
            f"'{blendshape_name}': its weight maps belong to "
            f"'{base_nodes[0]}'."
        )

    resolved_ids = _resolve_sampled_weight_ids(blendshape_name, weight_ids)
    target_names = [_get_target_name(blendshape_name, target_id)
                    for target_id in resolved_ids]
    blendshape = Blendshape(blendshape_name)
    source_weight_maps = [
        _get_source_weight_map(blendshape, target_id, vertex_count)
        for target_id in resolved_ids
    ]
    original_selection = cmds.ls(selection=True) or []

    total_steps = 4 + len(resolved_ids)
    if progress is not None:
        progress_context = nullcontext(mayaUtils._noop_progress_update)
    elif show_progress:
        progress_context = mayaUtils.main_progress_bar(
            f"Sampling mirrored weights of '{blendshape_name}'...",
            total_steps,
        )
    else:
        progress_context = nullcontext(mayaUtils._noop_progress_update)

    source_duplicate: Optional[str] = None
    destination_duplicate: Optional[str] = None
    source_skin: Optional[str] = None
    destination_skin: Optional[str] = None
    source_joints: list[str] = []
    destination_joints: list[str] = []
    source_namespace: Optional[str] = None
    destination_namespace: Optional[str] = None

    with progress_context as update:
        def report(step, status):
            """Advance the bar, or the caller's own progress callback."""
            if progress is not None:
                progress(step, total_steps)
            else:
                update(status=status, progress=step)

        try:
            report(0, "Preparing the transfer...")
            (source_duplicate, source_skin, source_joints,
             source_namespace) = _create_temp_side(
                source_transform, vertex_count, target_names, "mirS"
            )
            report(1, "Preparing the source weights...")
            _assign_weight_maps_bulk(
                source_skin, source_duplicate, source_joints,
                source_weight_maps
            )

            report(2, "Preparing the mirrored mesh...")
            (destination_duplicate, destination_skin, destination_joints,
             destination_namespace) = _create_temp_side(
                source_transform, vertex_count, target_names, "mirD"
            )
            _mirror_mesh_points(destination_duplicate, axis_index,
                                symmetry_centre)

            report(3, "Sampling the mirrored weights...")
            _copy_skin_weights(
                source_skin,
                destination_skin,
                "map1",
                "map1",
                WeightsTransferMethod.CLOSEST_POINT,
            )

            report(4, "Reading the sampled weights...")
            sampled_maps = _read_skin_weight_maps_bulk(
                destination_skin, destination_duplicate, destination_joints,
                vertex_count
            )
        finally:
            _cleanup_temp_side(
                source_skin, source_joints, source_duplicate, source_namespace
            )
            _cleanup_temp_side(
                destination_skin,
                destination_joints,
                destination_duplicate,
                destination_namespace,
            )
            _restore_selection(original_selection)

    for weight_id, values in zip(resolved_ids, sampled_maps):
        if values.size != vertex_count:
            raise RuntimeError(
                f"Sampled weight map {weight_id} of '{blendshape_name}' has "
                f"{values.size} values but the mesh has {vertex_count}."
            )
    return dict(zip(resolved_ids, sampled_maps))


__all__ = ["sample_mirrored_weight_maps", "transfer_blendshape_weight_maps"]
