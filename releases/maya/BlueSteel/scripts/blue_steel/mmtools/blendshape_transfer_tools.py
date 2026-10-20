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

from maya import cmds

from ..api.blendshape import Blendshape
from ..api.mayaUtils import undoable
from ..api.skinCluster import SkinCluster


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
        str: Target alias or ``target_<index>`` when no alias is authored.
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


def _get_uv_set(mesh_name: str, requested_uv_set: Optional[str]) -> str:
    """Resolve and validate a mesh UV set.

    Parameters:
        mesh_name (str): Mesh transform or shape name.
        requested_uv_set (str | None): Explicit UV set override.

    Returns:
        str: The UV set to use for the transfer.

    Raises:
        ValueError: If the mesh has no UV sets or the requested set is missing.
    """

    uv_sets = cmds.polyUVSet(mesh_name, q=True, allUVSets=True) or []
    if not uv_sets:
        raise ValueError(f"Mesh '{mesh_name}' has no UV sets.")

    if requested_uv_set:
        if requested_uv_set not in uv_sets:
            raise ValueError(
                f"UV set '{requested_uv_set}' does not exist on "
                f"'{mesh_name}'. Available UV sets: {', '.join(uv_sets)}."
            )
        return requested_uv_set

    current_uv_sets = cmds.polyUVSet(
        mesh_name,
        q=True,
        currentUVSet=True,
    ) or []
    if current_uv_sets and current_uv_sets[0] in uv_sets:
        return current_uv_sets[0]

    cmds.warning(
        f"Could not determine the current UV set on '{mesh_name}'; "
        f"using '{uv_sets[0]}'."
    )
    return uv_sets[0]


def _copy_skin_weights_by_uv(
    source_skin: str,
    destination_skin: str,
    source_uv_set: str,
    destination_uv_set: str,
) -> None:
    """Copy skin weights between two temporary skinClusters by UV.

    Parameters:
        source_skin (str): Source skinCluster name.
        destination_skin (str): Destination skinCluster name.
        source_uv_set (str): UV set on the source mesh.
        destination_uv_set (str): UV set on the destination mesh.

    Returns:
        None
    """

    # Maya uses the uvSpace flag together with the closestPoint surface mode
    # to enable the UV-space transfer path. There is no separate "uvSpace"
    # surface-association value in Maya 2026.
    cmds.copySkinWeights(
        ss=source_skin,
        ds=destination_skin,
        noMirror=True,
        surfaceAssociation="closestPoint",
        uvSpace=[source_uv_set, destination_uv_set],
        influenceAssociation="oneToOne",
    )


def _create_destination_blendshape(
    destination_transform: str,
    destination_shape: str,
    target_names: Sequence[str],
    weight_maps: Sequence[Sequence[float]],
    destination_blendshape: Optional[str],
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
def transfer_blendshape_weight_maps_by_uv(
    source_mesh: str,
    destination_mesh: str,
    source_blendshape: Optional[str] = None,
    source_uv_set: Optional[str] = None,
    destination_uv_set: Optional[str] = None,
    destination_blendshape: Optional[str] = None,
    selected_weights: Optional[Sequence[str]] = None,
) -> str:
    """Transfer blendShape target weight maps from one mesh to another by UV.

    Two temporary skinClusters are created on history-free duplicates of the
    source and destination meshes, with one joint per blendShape target. The
    source target weight maps are written to the source skinCluster,
    ``copySkinWeights`` transfers them to the destination skinCluster by UV, and
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
        source_uv_set (str | None): Source UV set. Defaults to the current set.
        destination_uv_set (str | None): Destination UV set. Defaults to the
            current set.
        destination_blendshape (str | None): Destination blendShape name.
            When the node exists it is reused and matching target weight maps
            are overwritten; when it does not exist it is created. ``None``
            creates a unique new blendShape.
        selected_weights (Sequence[str] | None): Target weight names to
            transfer. ``None`` transfers every source target. Missing names
            are warned about and skipped. An empty list creates a destination
            blendShape with no targets.

    Returns:
        str: Name of the destination blendShape (existing or newly created).

    Raises:
        ValueError: If the meshes, blendShape, UV sets, or arguments are
            invalid, including an existing destination blendShape that is not
            connected to the destination mesh.
        RuntimeError: If temporary skin construction or target creation fails.

    Example:
        >>> transfer_blendshape_weight_maps_by_uv(
        ...     "sourceMesh",
        ...     "destinationMesh",
        ...     source_uv_set="map1",
        ...     destination_uv_set="map1",
        ...     destination_blendshape="destinationWeightMaps_BS",
        ...     selected_weights=["Smile", "Frown"],
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

        resolved_source_uv = _get_uv_set(source_duplicate, source_uv_set)
        resolved_destination_uv = _get_uv_set(
            destination_duplicate,
            destination_uv_set,
        )

        _copy_skin_weights_by_uv(
            source_skin,
            destination_skin,
            resolved_source_uv,
            resolved_destination_uv,
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


__all__ = ["transfer_blendshape_weight_maps_by_uv"]
