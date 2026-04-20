# we will try to import the dna module, if it fails we issue an error message
from os import makedirs
from os import path as ospath
from ...api.editor import BlueSteelEditor
from ...api import mayaUtils
from maya import cmds
from maya import mel
from maya.api import OpenMaya as om2
from maya.api import OpenMayaAnim as oma2
import numpy as np
import re
import os

try:
    import dna
    from mh_expression_editor.resource import Resources
    from mh_expression_editor.utils import general
    from mh_expression_editor import lib, roles, control
    from frt_api.rig import RigDataHandler
    from mh_expression_editor.utils import dcc
    from mh_character_assembler.importer import CharacterImporter
    from mh_character_assembler.config import Config
    from mh_assemble_lib.model.dnalib import DNAReader, Layer
    from mh_character_assembler.core.util import MayaUtil

except ImportError:
    import traceback
    traceback.print_exc()
    raise ImportError("Failed to import dna. Please make sure they are installed and available in the Python path.\n Refer to the documentation for more information on how to install the MetaHuman for Maya plugin: https://dev.epicgames.com/documentation/en-us/metahuman/installing-in-maya")



from dataclasses import dataclass, field
from typing import List, Optional, Dict, Tuple
from enum import Enum


class DriverType(Enum):
    DIRECT = "direct"
    PSD    = "psd"
    NONE   = "none"
    NOT_MAPPED = "not_mapped"  # for synthetic targets representing shared drivers (e.g. Ph1 parents), which don't have a driver type themselves since they're not directly from the DNA but are just organizational containers for the actual targets that drive them


@dataclass
class ConditionalEntry:
    """
    One piecewise segment of the GUI→Raw conditional mapping.
    Only active when GUI value is inside [from_value, to_value].
    Raw output is computed as:  raw = slope * gui + cut

    from_value    : GUI lower bound for this segment
    to_value      : GUI upper bound for this segment
    slope         : gradient of the linear function
    cut           : intercept — raw output when gui=0 (reset/default value)
    raw_at_from   : raw value when gui == from_value
    raw_at_to     : raw value when gui == to_value
    gui_for_raw_1 : GUI value that produces raw=1.0 within this segment's
                    range (None if 1.0 is not reachable within [from, to]).
                    For PSD entries this is instead the GUI value that
                    produces the required raw contribution value.
    """
    from_value:    float
    to_value:      float
    slope:         float
    cut:           float
    raw_at_from:   float
    raw_at_to:     float
    gui_for_raw_1: Optional[float]


@dataclass
class GUIControl:
    """
    One GUI control channel with all its conditional segments.

    channel       : Maya attribute path e.g. "CTRL_L_brow_raiseIn.ty"
    default_value : cut of the first segment — the reset/neutral value
    segments      : piecewise conditional entries in GUI-value order.
                    Usually 1, but can be 2+ for bidirectional sliders.
    """
    channel:       str
    default_value: float
    segments:      List[ConditionalEntry] = field(default_factory=list)


@dataclass
class RawControl:
    """
    One CTRL_expressions entry — the intermediate raw control in Maya.
    Sits between the GUI sliders and the blend shape / PSD evaluation.

    channel       : Maya attribute path e.g. "CTRL_expressions.browRaiseInL"
    required_value: the value this raw control must reach to activate the shape.
                    For direct connections: 1.0
                    For PSD contributions: 1.0 (assumed, since DNA stores RBF
                    weights rather than activation thresholds)
    gui_ctrls     : the GUI controls that drive this raw control,
                    each with full conditional segment data
    """
    channel:        str
    required_value: float
    gui_ctrls:      List[GUIControl] = field(default_factory=list)


@dataclass
class BlendShapeTarget:
    """
    blendshape_node : Maya blendShape node name
    target_index    : index on the blendShape node
    target_name     : blend shape channel name from the DNA
    driver_type     : DIRECT — one raw control drives this shape directly
                      PSD    — a corrective pose (multiple raw controls) drives it
                      NONE   — no behavior entry found at this LOD
    raw_ctrls       : the CTRL_expressions controls in the driver chain.
                      For DIRECT: one entry, required_value=1.0
                      For PSD:    one entry per raw control in the pose,
                                  each with its specific required_value
    """
    blendshape_node: str
    target_index:    int
    target_name:     str
    driver_type:     DriverType
    raw_ctrls:       List[RawControl] = field(default_factory=list)
    blue_steel_target_name: Optional[str] = None  # to be filled in later during conversion


@dataclass
class BlendShapeDelta:
    """
    Geometry delta payload for one blendshape target from DNA.
    """
    target_index: int
    target_name: str
    vertex_indices: List[int] = field(default_factory=list)
    deltas: List[Tuple[float, float, float]] = field(default_factory=list)


@dataclass
class JointDefinition:
    """
    One joint from DNA, including hierarchy and neutral local transform.
    """
    index: int
    name: str
    parent_index: int
    translation: Tuple[float, float, float]
    rotation: Tuple[float, float, float]


@dataclass
class MeshSkinWeights:
    """
    Skinning payload for one mesh extracted from DNA.
    """
    mesh_name: str
    vertex_count: int
    influences: List[str] = field(default_factory=list)
    # vertex index -> list of (joint name, weight)
    vertex_weights: Dict[int, List[Tuple[str, float]]] = field(default_factory=dict)

# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _load_dna(path: str):
    stream = dna.FileStream(
        path,
        dna.FileStream.AccessMode_Read,
        dna.FileStream.OpenMode_Binary
    )
    reader = dna.BinaryStreamReader(stream, dna.DataLayer_All)
    reader.read()
    if not dna.Status.isOk():
        raise RuntimeError(f"Failed to read DNA: {dna.Status.getLastMessage()}")
    return reader


def _find_mesh_index(reader, mesh_name: str) -> int:
    for i in range(reader.getMeshCount()):
        if reader.getMeshName(i) == mesh_name:
            return i

    available = [reader.getMeshName(i) for i in range(reader.getMeshCount())]
    raise ValueError(f"Mesh '{mesh_name}' not found. Available: {available}")


def _extract_positions(reader, mesh_index: int) -> List[Tuple[float, float, float]]:
    """
    Extract mesh vertex positions while supporting different DNA python bindings.
    """
    xs_fn = getattr(reader, "getVertexPositionXs", None)
    ys_fn = getattr(reader, "getVertexPositionYs", None)
    zs_fn = getattr(reader, "getVertexPositionZs", None)
    if callable(xs_fn) and callable(ys_fn) and callable(zs_fn):
        xs = list(xs_fn(mesh_index))
        ys = list(ys_fn(mesh_index))
        zs = list(zs_fn(mesh_index))
        if len(xs) == len(ys) == len(zs):
            return [(float(x), float(y), float(z)) for x, y, z in zip(xs, ys, zs)]

    count_fn = getattr(reader, "getVertexPositionCount", None)
    get_pos_fn = getattr(reader, "getVertexPosition", None)
    if callable(count_fn) and callable(get_pos_fn):
        positions: List[Tuple[float, float, float]] = []
        for i in range(int(count_fn(mesh_index))):
            p = get_pos_fn(mesh_index, i)
            if hasattr(p, "x") and hasattr(p, "y") and hasattr(p, "z"):
                positions.append((float(p.x), float(p.y), float(p.z)))
            elif isinstance(p, (list, tuple)) and len(p) >= 3:
                positions.append((float(p[0]), float(p[1]), float(p[2])))
            else:
                raise RuntimeError("Unsupported DNA vertex position payload")
        return positions

    raise RuntimeError(
        "Could not extract vertex positions from DNA reader. "
        "Expected one of: getVertexPositionXs/Ys/Zs or getVertexPositionCount+getVertexPosition."
    )


def _extract_polygons(reader, mesh_index: int) -> Tuple[List[int], List[int]]:
    """
    Extract polygon counts and polygon connects while supporting different
    DNA python bindings.
    """
    face_count_fn = getattr(reader, "getFaceCount", None)
    face_layout_fn = getattr(reader, "getFaceVertexLayoutIndices", None)
    direct_face_indices_fn = getattr(reader, "getFaceVertexIndices", None)

    if callable(face_count_fn) and callable(face_layout_fn):
        layout_count_fn = getattr(reader, "getVertexLayoutCount", None)
        layout_item_fn = getattr(reader, "getVertexLayout", None)

        layout_to_position: Dict[int, int] = {}
        if callable(layout_count_fn) and callable(layout_item_fn):
            for i in range(int(layout_count_fn(mesh_index))):
                layout_item = layout_item_fn(mesh_index, i)
                if hasattr(layout_item, "positionIndex"):
                    layout_to_position[i] = int(layout_item.positionIndex)
                elif isinstance(layout_item, (list, tuple)) and layout_item:
                    layout_to_position[i] = int(layout_item[0])

        polygon_counts: List[int] = []
        polygon_connects: List[int] = []
        for face_id in range(int(face_count_fn(mesh_index))):
            layout_indices = list(face_layout_fn(mesh_index, face_id))
            if not layout_indices:
                continue

            polygon_counts.append(len(layout_indices))
            for li in layout_indices:
                polygon_connects.append(layout_to_position.get(int(li), int(li)))

        if polygon_counts and polygon_connects:
            return polygon_counts, polygon_connects

    if callable(face_count_fn) and callable(direct_face_indices_fn):
        polygon_counts = []
        polygon_connects = []
        for face_id in range(int(face_count_fn(mesh_index))):
            indices = list(direct_face_indices_fn(mesh_index, face_id))
            if not indices:
                continue
            polygon_counts.append(len(indices))
            polygon_connects.extend(int(i) for i in indices)

        if polygon_counts and polygon_connects:
            return polygon_counts, polygon_connects

    raise RuntimeError(
        "Could not extract topology from DNA reader. "
        "Expected face and layout accessors (or direct face vertex indices)."
    )


def _extract_target_delta_xyz(delta_payload) -> Tuple[float, float, float]:
    """
    Coerce a DNA delta payload item to xyz values.
    """
    if hasattr(delta_payload, "x") and hasattr(delta_payload, "y") and hasattr(delta_payload, "z"):
        return float(delta_payload.x), float(delta_payload.y), float(delta_payload.z)

    if hasattr(delta_payload, "deltaX") and hasattr(delta_payload, "deltaY") and hasattr(delta_payload, "deltaZ"):
        return float(delta_payload.deltaX), float(delta_payload.deltaY), float(delta_payload.deltaZ)

    if isinstance(delta_payload, (list, tuple)) and len(delta_payload) >= 3:
        return float(delta_payload[0]), float(delta_payload[1]), float(delta_payload[2])

    raise RuntimeError("Unsupported DNA blendshape delta payload")


def _extract_blendshape_target_deltas(
    reader,
    mesh_index: int,
    target_index: int,
) -> Tuple[List[int], List[Tuple[float, float, float]]]:
    """
    Extract sparse blendshape deltas for a target while supporting different
    DNA python bindings.
    """
    vertex_indices_fn = getattr(reader, "getBlendShapeTargetVertexIndices", None)
    dx_fn = getattr(reader, "getBlendShapeTargetDeltaXs", None)
    dy_fn = getattr(reader, "getBlendShapeTargetDeltaYs", None)
    dz_fn = getattr(reader, "getBlendShapeTargetDeltaZs", None)

    if callable(vertex_indices_fn) and callable(dx_fn) and callable(dy_fn) and callable(dz_fn):
        vertex_indices = [int(i) for i in list(vertex_indices_fn(mesh_index, target_index))]
        dx = list(dx_fn(mesh_index, target_index))
        dy = list(dy_fn(mesh_index, target_index))
        dz = list(dz_fn(mesh_index, target_index))

        if len(vertex_indices) == len(dx) == len(dy) == len(dz):
            deltas = [(float(x), float(y), float(z)) for x, y, z in zip(dx, dy, dz)]
            return vertex_indices, deltas

    count_fn = getattr(reader, "getBlendShapeTargetDeltaCount", None)
    get_delta_fn = getattr(reader, "getBlendShapeTargetDelta", None)
    if callable(count_fn) and callable(get_delta_fn) and callable(vertex_indices_fn):
        vertex_indices = [int(i) for i in list(vertex_indices_fn(mesh_index, target_index))]
        delta_count = int(count_fn(mesh_index, target_index))
        sample_count = min(delta_count, len(vertex_indices))

        deltas: List[Tuple[float, float, float]] = []
        for i in range(sample_count):
            deltas.append(_extract_target_delta_xyz(get_delta_fn(mesh_index, target_index, i)))

        if len(deltas) == len(vertex_indices):
            return vertex_indices, deltas

    raise RuntimeError(
        "Could not extract blendshape deltas from DNA reader. "
        "Expected target vertex indices plus delta xyz accessors."
    )


def _assign_default_shader(mesh_transform: str) -> None:
    """
    Assign Maya's default initial shading group to a newly created mesh.
    """
    shapes = cmds.listRelatives(
        mesh_transform,
        shapes=True,
        noIntermediate=True,
        fullPath=True,
    ) or []

    if not shapes:
        shapes = [mesh_transform]

    for shape in shapes:
        cmds.sets(shape, edit=True, forceElement="initialShadingGroup")


def _get_mesh_dag_path(node_name: str) -> om2.MDagPath:
    sel = om2.MSelectionList()
    sel.add(node_name)
    dag = sel.getDagPath(0)
    if dag.apiType() == om2.MFn.kTransform:
        dag.extendToShape()
    if dag.apiType() != om2.MFn.kMesh:
        raise ValueError(f"Node '{node_name}' is not a mesh")
    return dag


def _get_skincluster_fn(node_name: str) -> oma2.MFnSkinCluster:
    sel = om2.MSelectionList()
    sel.add(node_name)
    skin_obj = sel.getDependNode(0)
    return oma2.MFnSkinCluster(skin_obj)


def _build_full_vertex_component(vertex_count: int):
    comp_fn = om2.MFnSingleIndexedComponent()
    comp_obj = comp_fn.create(om2.MFn.kMeshVertComponent)
    if vertex_count > 0:
        comp_fn.addElements(range(vertex_count))
    return comp_obj


def _build_skin_weight_matrix(
    skin_data: MeshSkinWeights,
    cluster_influences: List[str],
    vertex_count: int,
) -> np.ndarray:
    """
    Build a dense [vertex_count, influence_count] weight matrix from sparse DNA weights.
    """
    influence_to_col = {name: idx for idx, name in enumerate(cluster_influences)}
    weights = np.zeros((vertex_count, len(cluster_influences)), dtype=np.float64)

    for vertex_id in range(vertex_count):
        for joint_name, weight in skin_data.vertex_weights.get(vertex_id, []):
            col = influence_to_col.get(joint_name)
            if col is not None:
                weights[vertex_id, col] = float(weight)

    return weights


def _safe_maya_name(name: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_]", "_", name)
    if not safe:
        safe = "target"
    if safe[0].isdigit():
        safe = f"_{safe}"
    return safe


def _build_target_mesh_from_deltas(
    base_mesh: str,
    target_name: str,
    vertex_indices: List[int],
    deltas: List[Tuple[float, float, float]],
) -> str:
    """
    Duplicate base mesh and apply sparse per-vertex deltas.
    """
    temp_mesh = cmds.duplicate(base_mesh, name=f"{_safe_maya_name(target_name)}_tmp")[0]

    if not vertex_indices or not deltas:
        return temp_mesh

    points = mayaUtils.get_mesh_raw_points(temp_mesh)
    point_count = int(points.shape[0])

    sample_count = min(len(vertex_indices), len(deltas))
    if sample_count <= 0:
        return temp_mesh

    indices = np.asarray(vertex_indices[:sample_count], dtype=np.int64)
    delta_array = np.asarray(deltas[:sample_count], dtype=points.dtype)
    if delta_array.ndim != 2 or delta_array.shape[1] != 3:
        return temp_mesh

    valid = (indices >= 0) & (indices < point_count)
    if np.any(valid):
        # Vectorized sparse add; supports repeated vertex IDs correctly.
        np.add.at(points, indices[valid], delta_array[valid])
        mayaUtils.set_mesh_raw_points(temp_mesh, points)

    return temp_mesh


def _extract_joint_vector(reader, joint_index: int, kind: str) -> Tuple[float, float, float]:
    """
    Read a joint neutral transform vector from DNA reader across binding variants.
    kind: "translation" or "rotation"
    """
    if kind == "translation":
        vector_fn = getattr(reader, "getNeutralJointTranslation", None)
        xs_fn = getattr(reader, "getNeutralJointTranslationXs", None)
        ys_fn = getattr(reader, "getNeutralJointTranslationYs", None)
        zs_fn = getattr(reader, "getNeutralJointTranslationZs", None)
    elif kind == "rotation":
        vector_fn = getattr(reader, "getNeutralJointRotation", None)
        xs_fn = getattr(reader, "getNeutralJointRotationXs", None)
        ys_fn = getattr(reader, "getNeutralJointRotationYs", None)
        zs_fn = getattr(reader, "getNeutralJointRotationZs", None)
    else:
        raise ValueError(f"Unsupported joint vector kind: {kind}")

    if callable(vector_fn):
        v = vector_fn(joint_index)
        if hasattr(v, "x") and hasattr(v, "y") and hasattr(v, "z"):
            return float(v.x), float(v.y), float(v.z)
        if isinstance(v, (list, tuple)) and len(v) >= 3:
            return float(v[0]), float(v[1]), float(v[2])

    if callable(xs_fn) and callable(ys_fn) and callable(zs_fn):
        xs = list(xs_fn())
        ys = list(ys_fn())
        zs = list(zs_fn())
        if joint_index < len(xs) and joint_index < len(ys) and joint_index < len(zs):
            return float(xs[joint_index]), float(ys[joint_index]), float(zs[joint_index])

    raise RuntimeError(f"Could not extract neutral joint {kind} for index {joint_index}")


def _read_joint_definitions_from_reader(reader) -> List[JointDefinition]:
    """
    Read all joints (hierarchy + neutral local transforms) from an already-open DNA reader.
    """
    joint_count = int(reader.getJointCount())
    joints: List[JointDefinition] = []

    for joint_index in range(joint_count):
        joint_name = str(reader.getJointName(joint_index))
        parent_index = int(reader.getJointParentIndex(joint_index))
        translation = _extract_joint_vector(reader, joint_index, "translation")
        rotation = _extract_joint_vector(reader, joint_index, "rotation")
        joints.append(JointDefinition(
            index=joint_index,
            name=joint_name,
            parent_index=parent_index,
            translation=translation,
            rotation=rotation,
        ))

    return joints


def _resolve_joint_group_indices(reader, lod: Optional[int]) -> List[int]:
    """
    Resolve joint-group indices to evaluate for a given LOD.

    Different DNA bindings expose LOD data differently; this helper supports:
    1) cumulative boundaries: [count_at_lod0, count_at_lod1, ...]
    2) per-group lod assignment: one value per group
    3) fallback to all groups
    """
    group_count = int(reader.getJointGroupCount())
    all_indices = list(range(group_count))

    if lod is None:
        return all_indices

    lods_fn = getattr(reader, "getJointGroupLODs", None)
    if not callable(lods_fn):
        return all_indices

    try:
        lod_data = [int(v) for v in list(lods_fn())]
    except Exception:
        return all_indices

    if not lod_data:
        return all_indices

    # Case 1: one lod value per group index.
    if len(lod_data) == group_count:
        return [idx for idx, group_lod in enumerate(lod_data) if group_lod <= int(lod)]

    # Case 2: cumulative boundaries (same pattern used for blendshape LOD arrays).
    if lod < len(lod_data):
        boundary = max(0, min(group_count, int(lod_data[lod])))
        return list(range(boundary))

    return all_indices


def _build_raw_control_vector(reader, raw_control_values: Dict[str, float]) -> np.ndarray:
    """
    Build a dense raw-control vector from a {raw_control_name: value} map.
    """
    raw_count = int(reader.getRawControlCount())
    vector = np.zeros(raw_count, dtype=np.float64)

    if not raw_control_values:
        return vector

    name_to_index = {
        str(reader.getRawControlName(i)): i
        for i in range(raw_count)
    }

    for raw_name, raw_value in raw_control_values.items():
        idx = name_to_index.get(str(raw_name))
        if idx is None:
            continue
        vector[idx] = float(raw_value)

    return vector


def _decode_joint_attribute_index(attr_index: int, joint_count: int, slot_count: int) -> Tuple[int, int]:
    """
    Decode a DNA joint variable attribute index into (joint_index, attribute_slot).

    Most bindings expose a joint-major packing: attr = joint_index * slot_count + slot.
    A fallback attr-major decode is also supported for compatibility.
    """
    if slot_count <= 0:
        return -1, -1

    joint_idx = attr_index // slot_count
    slot_idx = attr_index % slot_count
    if 0 <= joint_idx < joint_count:
        return joint_idx, slot_idx

    alt_joint_idx = attr_index % joint_count if joint_count > 0 else -1
    alt_slot_idx = attr_index // joint_count if joint_count > 0 else -1
    if 0 <= alt_joint_idx < joint_count and 0 <= alt_slot_idx < slot_count:
        return alt_joint_idx, alt_slot_idx

    return -1, -1


def _evaluate_joint_deltas_from_raw_vector(reader, raw_vector: np.ndarray, lod: Optional[int]) -> Dict[int, Dict[str, np.ndarray]]:
    """
    Evaluate DNA joint behavior matrix for a dense raw-control vector.

    Returns
    -------
    Dict[joint_index, {"t": np.ndarray(3), "r": np.ndarray(3)}]
        Local translation/rotation deltas to add to neutral transforms.
    """
    joint_count = int(reader.getJointCount())
    if joint_count <= 0:
        return {}

    variable_attr_indices_fn = getattr(reader, "getJointVariableAttributeIndices", None)
    if not callable(variable_attr_indices_fn):
        raise RuntimeError("DNA binding does not expose getJointVariableAttributeIndices; cannot evaluate posed joints")

    variable_attr_indices = [int(v) for v in list(variable_attr_indices_fn(0))]
    if not variable_attr_indices:
        return {}

    max_attr = max(variable_attr_indices)
    inferred_slot_count = int(np.ceil((max_attr + 1) / float(joint_count))) if joint_count > 0 else 0
    slot_count = max(6, inferred_slot_count)

    deltas: Dict[int, Dict[str, np.ndarray]] = {
        j: {
            "t": np.zeros(3, dtype=np.float64),
            "r": np.zeros(3, dtype=np.float64),
        }
        for j in range(joint_count)
    }

    group_indices = _resolve_joint_group_indices(reader, lod)
    for group_index in group_indices:
        input_indices = [int(v) for v in list(reader.getJointGroupInputIndices(group_index))]
        output_indices = [int(v) for v in list(reader.getJointGroupOutputIndices(group_index))]
        values = [float(v) for v in list(reader.getJointGroupValues(group_index))]

        if not input_indices or not output_indices:
            continue

        input_count = len(input_indices)
        output_count = len(output_indices)
        if len(values) < (input_count * output_count):
            continue

        local_x = np.zeros(input_count, dtype=np.float64)
        for i, raw_idx in enumerate(input_indices):
            if 0 <= raw_idx < raw_vector.shape[0]:
                local_x[i] = raw_vector[raw_idx]

        for output_row, output_idx in enumerate(output_indices):
            row_start = output_row * input_count
            row_end = row_start + input_count
            coeffs = np.asarray(values[row_start:row_end], dtype=np.float64)
            delta_value = float(np.dot(coeffs, local_x))
            if abs(delta_value) <= 1e-12:
                continue

            variable_attr_idx = output_idx
            if 0 <= output_idx < len(variable_attr_indices):
                variable_attr_idx = variable_attr_indices[output_idx]

            joint_idx, slot_idx = _decode_joint_attribute_index(variable_attr_idx, joint_count, slot_count)
            if joint_idx < 0:
                continue

            if slot_idx <= 2:
                deltas[joint_idx]["t"][slot_idx] += delta_value
            elif 3 <= slot_idx <= 5:
                deltas[joint_idx]["r"][slot_idx - 3] += delta_value

    return deltas


def _raw_values_from_target(target: BlendShapeTarget) -> Dict[str, float]:
    """
    Convert one BlendShapeTarget driver chain to {raw_control_name: required_value}.
    """
    values: Dict[str, float] = {}
    for raw_ctrl in target.raw_ctrls:
        if not raw_ctrl.channel:
            continue
        values[str(raw_ctrl.channel)] = float(raw_ctrl.required_value)
    return values


def _find_skincluster_for_mesh(mesh_name: str) -> Optional[str]:
    """
    Return the first skinCluster found in mesh history, if any.
    """
    shape_nodes = cmds.listRelatives(mesh_name, shapes=True, noIntermediate=True, fullPath=True) or []
    history = cmds.listHistory(shape_nodes[0], pruneDagObjects=True) if shape_nodes else cmds.listHistory(mesh_name, pruneDagObjects=True)
    if not history:
        return None

    for node in history:
        if cmds.nodeType(node) == "skinCluster":
            return node
    return None


def _make_segment(from_v: float, to_v: float, slope: float, cut: float,
                  target_raw: float = 1.0) -> ConditionalEntry:
    """
    Build a ConditionalEntry and compute derived values.
    target_raw controls what gui_for_raw_1 solves for
    (1.0 for direct, required_value for PSD entries).
    """
    raw_at_from = slope * from_v + cut
    raw_at_to   = slope * to_v   + cut

    if abs(slope) < 1e-9:
        gui_for_target = None
    else:
        candidate = (target_raw - cut) / slope
        gui_for_target = candidate if from_v <= candidate <= to_v else None

    return ConditionalEntry(
        from_value    = from_v,
        to_value      = to_v,
        slope         = slope,
        cut           = cut,
        raw_at_from   = raw_at_from,
        raw_at_to     = raw_at_to,
        gui_for_raw_1 = gui_for_target,
    )


def _build_raw_to_gui(reader) -> Dict[int, List[dict]]:
    """
    Returns all GUI→Raw conditional entries grouped by raw control index.
    Preserves every entry including multiple segments for the same pair.

    { raw_ctrl_index: [ {channel, gui_idx, from, to, slope, cut}, ... ] }
    """
    gui_inputs  = list(reader.getGUIToRawInputIndices())
    gui_outputs = list(reader.getGUIToRawOutputIndices())
    from_vals   = list(reader.getGUIToRawFromValues())
    to_vals     = list(reader.getGUIToRawToValues())
    slopes      = list(reader.getGUIToRawSlopeValues())
    cuts        = list(reader.getGUIToRawCutValues())

    raw_to_gui: Dict[int, List[dict]] = {}
    for i in range(len(gui_outputs)):
        raw_idx = gui_outputs[i]
        gui_idx = gui_inputs[i]
        raw_to_gui.setdefault(raw_idx, []).append({
            "channel": reader.getGUIControlName(gui_idx),
            "gui_idx": gui_idx,
            "from":    from_vals[i],
            "to":      to_vals[i],
            "slope":   slopes[i],
            "cut":     cuts[i],
        })
    return raw_to_gui


def _build_gui_ctrls(entries: List[dict], target_raw: float = 1.0) -> List[GUIControl]:
    """
    Given a list of raw GUI→Raw entries for one raw control, build GUIControl
    objects with full piecewise segment data.
    Groups multiple entries by channel, sorts by from_value.
    target_raw is the raw value we're solving gui_for_raw_1 for.
    """
    channel_map: Dict[str, List[dict]] = {}
    for e in entries:
        channel_map.setdefault(e["channel"], []).append(e)

    result: List[GUIControl] = []
    for channel, segs in channel_map.items():
        segs_sorted = sorted(segs, key=lambda s: s["from"])
        segments = [
            _make_segment(s["from"], s["to"], s["slope"], s["cut"], target_raw)
            for s in segs_sorted
        ]
        result.append(GUIControl(
            channel=channel,
            default_value=segs_sorted[0]["cut"],
            segments=segments,
        ))
    return result


def _generate_blue_steel_name(raw_ctrls: List[RawControl]) -> str:
    """
    Generate a blue_steel_target_name from raw controls.

    Format: sorted control names (without CTRL_expressions. prefix),
    with required value as integer percentage appended if != 1.0.

    Example: eyeCheekRaiseL_mouthCornerPullL50
    """
    if not raw_ctrls:
        return ""

    parts = []
    for raw in raw_ctrls:
        # Extract the name without the "CTRL_expressions." prefix
        name = raw.channel.split(".")[-1] if raw.channel else "unknown"
        
        if re.search(r'Ph\d$', name):
            # in this case we need to take the value of the gui control
            name = name[:-3]  # remove the "Ph1" suffix for cleaner naming
            gui_ctrl = raw.gui_ctrls[0] if raw.gui_ctrls else None
            if gui_ctrl and gui_ctrl.segments:
                seg = gui_ctrl.segments[0]  # assuming the first segment is representative
                value_int = int(round(seg.gui_for_raw_1 * 100)) if seg.gui_for_raw_1 is not None else ""
                if value_int != 100:  # only append if not the default 1.0 (100%)
                    name = f"{name}{value_int}"

        parts.append(name)

    # Sort and join
    parts.sort()
    return "_".join(parts)


def _build_psd_map(reader, raw_to_gui: Dict[int, List[dict]]) -> Dict[int, List[RawControl]]:
    """
    { unified_input_index: [RawControl, ...] }

    Each RawControl represents one CTRL_expressions entry required by the PSD,
    carrying its required_value and the GUI controls that can reach it.

    Note: The DNA's getPSDValues() returns RBF interpolation weights, NOT
    activation thresholds. These weights can be any value (e.g. 4.0) and don't
    directly represent the control value needed to fire the pose. For Blue Steel
    purposes, we assume all PSD-participating controls need required_value=1.0.

    Keys match getBlendShapeChannelInputIndices() values directly
    (confirmed: getPSDRowIndices() uses the same unified index space).
    """
    psd_rows  = list(reader.getPSDRowIndices())
    psd_cols  = list(reader.getPSDColumnIndices())
    psd_vals  = list(reader.getPSDValues())
    raw_count = reader.getRawControlCount()

    # Group sparse PSD table entries by their unified input index
    psd_entries: Dict[int, List[tuple]] = {}
    for i in range(len(psd_rows)):
        psd_entries.setdefault(psd_rows[i], []).append((psd_cols[i], psd_vals[i]))

    psd_map: Dict[int, List[RawControl]] = {}

    for unified_idx, requirements in psd_entries.items():
        raw_ctrls: List[RawControl] = []

        for raw_idx, psd_weight in requirements:
            raw_name = (
                reader.getRawControlName(raw_idx)
                if raw_idx < raw_count
                else None  # sanity check, should never happen in a valid PSD table
            )
            # PSD values are RBF interpolation weights/coefficients, NOT activation thresholds.
            # They can be any value (including > 1.0) and don't represent the control value
            # needed to fire the pose. For Blue Steel, we assume all PSD-participating 
            # controls need to be at 1.0 (full) since the actual activation depends on
            # complex RBF interpolation that we can't easily reverse-engineer.
            required_raw = 1.0
            gui_entries = raw_to_gui.get(raw_idx, [])
            gui_ctrls   = _build_gui_ctrls(gui_entries, target_raw=required_raw)

            raw_ctrls.append(RawControl(
                channel=raw_name,
                required_value=required_raw,
                gui_ctrls=gui_ctrls,
            ))

        if raw_ctrls:
            psd_map[unified_idx] = raw_ctrls

    return psd_map


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def build_mesh_from_dna(mesh_name: str, dna_path: str) -> str:
    """
    Build a Maya mesh from a DNA file.

    Parameters
    ----------
    mesh_name : mesh name found in the DNA file
    dna_path  : path to a MetaHuman DNA file

    Returns
    -------
    str : created mesh transform name in Maya
    """
    if not dna_path or not ospath.exists(dna_path):
        raise ValueError(f"DNA file does not exist: {dna_path}")

    reader = _load_dna(dna_path)
    mesh_index = _find_mesh_index(reader, mesh_name)
    positions = _extract_positions(reader, mesh_index)
    polygon_counts, polygon_connects = _extract_polygons(reader, mesh_index)

    if not positions:
        raise RuntimeError(f"No vertex positions found for mesh '{mesh_name}'")
    if not polygon_counts:
        raise RuntimeError(f"No polygon data found for mesh '{mesh_name}'")

    if cmds.objExists(mesh_name):
        cmds.delete(mesh_name)

    points = [om2.MPoint(x, y, z) for x, y, z in positions]
    mesh_fn = om2.MFnMesh()
    mesh_obj = mesh_fn.create(points, polygon_counts, polygon_connects)

    shape_fn = om2.MFnDagNode(mesh_obj)
    shape_path = shape_fn.fullPathName()
    if cmds.objExists(shape_path) and cmds.nodeType(shape_path) == "transform":
        mesh_transform = cmds.rename(shape_path, mesh_name)
    else:
        cmds.error(f"Expected a transform node but got {shape_path} of type {cmds.nodeType(shape_path)}")

    _assign_default_shader(mesh_transform)
    load_blendshapes_on_mesh(mesh_name=mesh_transform, dna_path=dna_path)
    return mesh_transform


def read_blendshape_deltas(
    dna_path: str,
    mesh_name: str = "head_lod0_mesh",
    show_progress: bool = True,
) -> List[BlendShapeDelta]:
    """
    Read sparse blendshape deltas for every target on a DNA mesh.
    """
    if not dna_path or not ospath.exists(dna_path):
        raise ValueError(f"DNA file does not exist: {dna_path}")

    reader = _load_dna(dna_path)
    mesh_index = _find_mesh_index(reader, mesh_name)

    results: List[BlendShapeDelta] = []
    target_count = int(reader.getBlendShapeTargetCount(mesh_index))

    if show_progress:
        g_main_progress_bar = mel.eval('$tmp = $gMainProgressBar')
        cmds.progressBar(
            g_main_progress_bar,
            edit=True,
            beginProgress=True,
            isInterruptable=True,
            status=f"Reading {target_count} blendshape deltas...",
            maxValue=max(target_count, 1),
        )
        try:
            for target_idx in range(target_count):
                if cmds.progressBar(g_main_progress_bar, query=True, isCancelled=True):
                    raise RuntimeError("Blendshape delta reading cancelled by user.")

                channel_idx = reader.getBlendShapeChannelIndex(mesh_index, target_idx)
                target_name = str(reader.getBlendShapeChannelName(channel_idx))
                vertex_indices, deltas = _extract_blendshape_target_deltas(reader, mesh_index, target_idx)

                results.append(BlendShapeDelta(
                    target_index=target_idx,
                    target_name=target_name,
                    vertex_indices=vertex_indices,
                    deltas=deltas,
                ))
                cmds.progressBar(
                    g_main_progress_bar,
                    edit=True,
                    step=1,
                    status=f"Reading target: {target_name}",
                )
        finally:
            cmds.progressBar(g_main_progress_bar, edit=True, endProgress=True)
    else:
        for target_idx in range(target_count):
            channel_idx = reader.getBlendShapeChannelIndex(mesh_index, target_idx)
            target_name = str(reader.getBlendShapeChannelName(channel_idx))
            vertex_indices, deltas = _extract_blendshape_target_deltas(reader, mesh_index, target_idx)

            results.append(BlendShapeDelta(
                target_index=target_idx,
                target_name=target_name,
                vertex_indices=vertex_indices,
                deltas=deltas,
            ))

    return results


def _load_blendshape_targets_on_mesh(
    mesh_name: str,
    blendshape_node: str,
    targets: List[BlendShapeDelta],
    delete_target_meshes: bool = True,
) -> str:
    """
    Apply pre-read blendshape targets to an existing blendShape node.
    """
    aliases = cmds.aliasAttr(blendshape_node, query=True) or []
    existing_aliases = set(aliases[0::2])
    weight_indices = cmds.getAttr(f"{blendshape_node}.weight", multiIndices=True) or []
    next_weight_index = (max(weight_indices) + 1) if weight_indices else 0

    g_main_progress_bar = mel.eval('$tmp = $gMainProgressBar')
    total_targets = len(targets)
    cmds.progressBar(
        g_main_progress_bar,
        edit=True,
        beginProgress=True,
        isInterruptable=True,
        status=f"Loading {total_targets} Targets on {mesh_name}...",
        maxValue=max(total_targets, 1),
    )
    try:
        for target in targets:
            if cmds.progressBar(g_main_progress_bar, query=True, isCancelled=True):
                raise RuntimeError("Blendshape loading cancelled by user.")

            if not target.vertex_indices:
                cmds.progressBar(
                    g_main_progress_bar,
                    edit=True,
                    step=1,
                    status=f"Skipping empty target: {target.target_name}",
                )
                continue

            alias_name = target.target_name
            if alias_name in existing_aliases:
                alias_name = f"{target.target_name}_{target.target_index}"

            temp_target = _build_target_mesh_from_deltas(
                base_mesh=mesh_name,
                target_name=alias_name,
                vertex_indices=target.vertex_indices,
                deltas=target.deltas,
            )

            try:
                cmds.blendShape(
                    blendshape_node,
                    edit=True,
                    target=(mesh_name, next_weight_index, temp_target, 1.0),
                )
                cmds.aliasAttr(alias_name, f"{blendshape_node}.w[{next_weight_index}]")
                existing_aliases.add(alias_name)
                next_weight_index += 1
            finally:
                if delete_target_meshes and cmds.objExists(temp_target):
                    cmds.delete(temp_target)

            cmds.progressBar(
                g_main_progress_bar,
                edit=True,
                step=1,
                status=f"Target Added: {alias_name}",
            )
    finally:
        cmds.progressBar(g_main_progress_bar, edit=True, endProgress=True)

    return blendshape_node


def load_blendshapes_on_mesh(
    mesh_name: str,
    dna_path: str,
    blendshape_node_name: Optional[str] = None,
    delete_target_meshes: bool = True,
) -> str:
    """
    Build a Maya blendShape on mesh_name from DNA target deltas.
    """
    if not cmds.objExists(mesh_name):
        raise ValueError(f"Mesh does not exist in Maya scene: {mesh_name}")

    targets = read_blendshape_deltas(dna_path=dna_path, mesh_name=mesh_name, show_progress=True)
    node_name = blendshape_node_name or f"{mesh_name}_blendShapes"

    if cmds.objExists(node_name):
        blendshape_node = node_name
    else:
        blendshape_node = cmds.blendShape(mesh_name, name=node_name, origin="world", foc=True)[0]

    return _load_blendshape_targets_on_mesh(
        mesh_name=mesh_name,
        blendshape_node=blendshape_node,
        targets=targets,
        delete_target_meshes=delete_target_meshes,
    )


def read_joints_from_dna(dna_path: str) -> List[JointDefinition]:
    """
    Read all joints from a DNA file, including hierarchy and neutral transforms.
    """
    if not dna_path or not ospath.exists(dna_path):
        raise ValueError(f"DNA file does not exist: {dna_path}")

    reader = _load_dna(dna_path)
    return _read_joint_definitions_from_reader(reader)


def read_posed_joints_from_dna(
    dna_path: str,
    raw_control_values: Dict[str, float],
    lod: Optional[int] = 0,
) -> List[JointDefinition]:
    """
    Evaluate joint transforms for one pose described by raw-control values.

    Parameters
    ----------
    dna_path           : path to a MetaHuman DNA file
    raw_control_values : map of raw control name -> control value
                         (e.g. {"CTRL_expressions.browRaiseInL": 1.0})
    lod                : optional LOD to evaluate; use None to evaluate all groups

    Returns
    -------
    List[JointDefinition]
        Joint hierarchy with posed local translation/rotation values
        (neutral + DNA behavior deltas).
    """
    if not dna_path or not ospath.exists(dna_path):
        raise ValueError(f"DNA file does not exist: {dna_path}")

    reader = _load_dna(dna_path)
    neutral_joints = _read_joint_definitions_from_reader(reader)
    raw_vector = _build_raw_control_vector(reader, raw_control_values)
    deltas = _evaluate_joint_deltas_from_raw_vector(reader, raw_vector, lod=lod)

    posed: List[JointDefinition] = []
    for joint in neutral_joints:
        joint_delta = deltas.get(joint.index)
        if joint_delta is None:
            posed_t = joint.translation
            posed_r = joint.rotation
        else:
            posed_t = (
                float(joint.translation[0] + joint_delta["t"][0]),
                float(joint.translation[1] + joint_delta["t"][1]),
                float(joint.translation[2] + joint_delta["t"][2]),
            )
            posed_r = (
                float(joint.rotation[0] + joint_delta["r"][0]),
                float(joint.rotation[1] + joint_delta["r"][1]),
                float(joint.rotation[2] + joint_delta["r"][2]),
            )

        posed.append(JointDefinition(
            index=joint.index,
            name=joint.name,
            parent_index=joint.parent_index,
            translation=posed_t,
            rotation=posed_r,
        ))

    return posed


def read_posed_joints_for_blendshape_targets(
    dna_path: str,
    mesh_name: str = "head_lod0_mesh",
    lod: int = 0,
) -> Dict[str, List[JointDefinition]]:
    """
    Evaluate posed joints for every blendshape target pose on a mesh.

    For each target, raw controls are populated from its driver chain
    (RawControl.required_value), then DNA joint behavior is evaluated.

    Returns
    -------
    Dict[str, List[JointDefinition]]
        target_name -> posed joints list
    """
    if not dna_path or not ospath.exists(dna_path):
        raise ValueError(f"DNA file does not exist: {dna_path}")

    reader = _load_dna(dna_path)
    neutral_joints = _read_joint_definitions_from_reader(reader)
    targets = read_blendshape_targets(
        dna_path=dna_path,
        mesh_name=mesh_name,
        lod=lod,
    )

    posed_by_target: Dict[str, List[JointDefinition]] = {}
    for target in targets:
        if not target.raw_ctrls:
            continue

        raw_values = _raw_values_from_target(target)
        if not raw_values:
            continue

        raw_vector = _build_raw_control_vector(reader, raw_values)
        deltas = _evaluate_joint_deltas_from_raw_vector(reader, raw_vector, lod=lod)

        posed: List[JointDefinition] = []
        for joint in neutral_joints:
            joint_delta = deltas.get(joint.index)
            if joint_delta is None:
                posed_t = joint.translation
                posed_r = joint.rotation
            else:
                posed_t = (
                    float(joint.translation[0] + joint_delta["t"][0]),
                    float(joint.translation[1] + joint_delta["t"][1]),
                    float(joint.translation[2] + joint_delta["t"][2]),
                )
                posed_r = (
                    float(joint.rotation[0] + joint_delta["r"][0]),
                    float(joint.rotation[1] + joint_delta["r"][1]),
                    float(joint.rotation[2] + joint_delta["r"][2]),
                )

            posed.append(JointDefinition(
                index=joint.index,
                name=joint.name,
                parent_index=joint.parent_index,
                translation=posed_t,
                rotation=posed_r,
            ))

        target_key = str(target.target_name)
        if target_key in posed_by_target:
            target_key = f"{target_key}_{target.target_index}"
        posed_by_target[target_key] = posed

    return posed_by_target


def create_joints_from_dna(
    dna_path: str,
    root_group_name: Optional[str] = None,
    delete_existing: bool = False,
) -> List[str]:
    """
    Create Maya joints from DNA hierarchy and neutral transforms.

    Parameters
    ----------
    dna_path        : path to a MetaHuman DNA file
    root_group_name : optional transform to parent all root joints under
    delete_existing : if True, delete joints with conflicting names first

    Returns
    -------
    List[str] : created joint names in DNA order
    """
    joints = read_joints_from_dna(dna_path)
    if not joints:
        return []

    created_by_index: Dict[int, str] = {}

    for joint in joints:
        if cmds.objExists(joint.name):
            if delete_existing:
                cmds.delete(joint.name)
            else:
                raise ValueError(
                    f"Joint '{joint.name}' already exists in scene. "
                    "Use delete_existing=True to replace it."
                )

        created_by_index[joint.index] = cmds.createNode("joint", name=joint.name)

    for joint in joints:
        child = created_by_index[joint.index]
        parent_idx = joint.parent_index
        if parent_idx != joint.index and parent_idx in created_by_index:
            cmds.parent(child, created_by_index[parent_idx])

    for joint in joints:
        joint_name = created_by_index[joint.index]
        cmds.setAttr(f"{joint_name}.translate", *joint.translation, type="double3")
        cmds.setAttr(f"{joint_name}.rotate", *joint.rotation, type="double3")

    if root_group_name:
        if cmds.objExists(root_group_name):
            if delete_existing:
                cmds.delete(root_group_name)
                root_group = cmds.createNode("transform", name=root_group_name)
            else:
                root_group = root_group_name
        else:
            root_group = cmds.createNode("transform", name=root_group_name)

        for joint in joints:
            if joint.parent_index == joint.index or joint.parent_index not in created_by_index:
                cmds.parent(created_by_index[joint.index], root_group)

    return [created_by_index[j.index] for j in joints]


def read_skinweights_from_dna(
    dna_path: str,
    mesh_name: str = "head_lod0_mesh",
    drop_zero_weights: bool = True,
    show_progress: bool = True,
) -> MeshSkinWeights:
    """
    Read skin weights for a specific DNA mesh.
    """
    if not dna_path or not ospath.exists(dna_path):
        raise ValueError(f"DNA file does not exist: {dna_path}")

    reader = _load_dna(dna_path)
    mesh_index = _find_mesh_index(reader, mesh_name)
    vertex_count = int(reader.getVertexPositionCount(mesh_index))

    joint_count = int(reader.getJointCount())
    all_joint_names = [str(reader.getJointName(i)) for i in range(joint_count)]

    result = MeshSkinWeights(mesh_name=mesh_name, vertex_count=vertex_count)
    influence_set = set()

    get_joint_indices = reader.getSkinWeightsJointIndices
    get_weight_values = reader.getSkinWeightsValues
    influence_add = influence_set.add
    vertex_weights = result.vertex_weights

    flat_joint_indices = None
    flat_weights = None
    influences_per_vertex = 0

    # Faster path on bindings that expose flattened skin data per mesh.
    try:
        candidate_joint_indices = [int(i) for i in list(get_joint_indices(mesh_index))]
        candidate_weights = [float(w) for w in list(get_weight_values(mesh_index))]
        if (
            vertex_count > 0
            and len(candidate_joint_indices) == len(candidate_weights)
            and len(candidate_joint_indices) % vertex_count == 0
        ):
            inferred = len(candidate_joint_indices) // vertex_count
            if inferred > 0:
                flat_joint_indices = candidate_joint_indices
                flat_weights = candidate_weights
                influences_per_vertex = inferred
    except TypeError:
        # This binding requires (mesh_index, vertex_id) access.
        pass

    def _read_vertex_pairs(vertex_id: int) -> List[Tuple[str, float]]:
        if flat_joint_indices is not None and flat_weights is not None:
            start = vertex_id * influences_per_vertex
            end = start + influences_per_vertex
            joint_indices = flat_joint_indices[start:end]
            weights = flat_weights[start:end]
        else:
            joint_indices = [int(i) for i in list(get_joint_indices(mesh_index, vertex_id))]
            weights = [float(w) for w in list(get_weight_values(mesh_index, vertex_id))]

        pairs: List[Tuple[str, float]] = []
        for joint_index, weight in zip(joint_indices, weights):
            if joint_index < 0 or joint_index >= joint_count:
                continue
            if drop_zero_weights and abs(weight) <= 1e-12:
                continue

            joint_name = all_joint_names[joint_index]
            pairs.append((joint_name, weight))
            influence_add(joint_name)
        return pairs

    if show_progress:
        g_main_progress_bar = mel.eval('$tmp = $gMainProgressBar')
        cmds.progressBar(
            g_main_progress_bar,
            edit=True,
            beginProgress=True,
            isInterruptable=True,
            status=f"Reading skinweights for {vertex_count} vertices...",
            maxValue=max(vertex_count, 1),
        )
        progress_update_step = max(1, vertex_count // 200)
        try:
            for vertex_id in range(vertex_count):
                if cmds.progressBar(g_main_progress_bar, query=True, isCancelled=True):
                    raise RuntimeError("Skinweight reading cancelled by user.")

                vertex_weights[vertex_id] = _read_vertex_pairs(vertex_id)

                if (vertex_id % progress_update_step == 0) or (vertex_id == vertex_count - 1):
                    cmds.progressBar(
                        g_main_progress_bar,
                        edit=True,
                        progress=vertex_id + 1,
                        status=f"Reading vertex {vertex_id + 1}/{vertex_count}",
                    )
        finally:
            cmds.progressBar(g_main_progress_bar, edit=True, endProgress=True)
    else:
        for vertex_id in range(vertex_count):
            vertex_weights[vertex_id] = _read_vertex_pairs(vertex_id)

    result.influences = sorted(influence_set)
    return result


def load_skinweights_on_mesh(
    mesh_name: str,
    dna_path: str,
    skincluster_name: Optional[str] = None,
    create_skincluster_if_missing: bool = True,
    replace_existing_weights: bool = True,
    normalize_weights: bool = True,
) -> str:
    """
    Load DNA skin weights onto a specific Maya mesh.

    Returns the skinCluster node name.
    """
    if not cmds.objExists(mesh_name):
        raise ValueError(f"Mesh does not exist in Maya scene: {mesh_name}")

    skin_data = read_skinweights_from_dna(
        dna_path=dna_path,
        mesh_name=mesh_name,
        drop_zero_weights=False,
        show_progress=True,
    )
    existing_skincluster = _find_skincluster_for_mesh(mesh_name)

    if existing_skincluster:
        skin_cluster = existing_skincluster
    else:
        if not create_skincluster_if_missing:
            raise ValueError(f"No skinCluster found on mesh '{mesh_name}'")

        if not skin_data.influences:
            raise RuntimeError(f"No influences found in DNA skin weights for mesh '{mesh_name}'")

        missing_joints = [j for j in skin_data.influences if not cmds.objExists(j)]
        if missing_joints:
            raise ValueError(
                "Cannot create skinCluster because some DNA joints are missing in scene: "
                f"{missing_joints[:20]}"
            )

        skin_cluster = cmds.skinCluster(
            skin_data.influences,
            mesh_name,
            toSelectedBones=True,
            normalizeWeights=1 if normalize_weights else 0,
            name=skincluster_name or f"{mesh_name}_skinCluster",
        )[0]

    cluster_influences = cmds.skinCluster(skin_cluster, query=True, influence=True) or []
    influence_set = set(cluster_influences)

    required_influences = set(skin_data.influences)
    missing_from_cluster = [j for j in sorted(required_influences) if j not in influence_set and cmds.objExists(j)]
    if missing_from_cluster:
        cmds.skinCluster(skin_cluster, edit=True, addInfluence=missing_from_cluster, weight=0.0)
        cluster_influences = cmds.skinCluster(skin_cluster, query=True, influence=True) or []
        influence_set = set(cluster_influences)

    unresolved = [j for j in sorted(required_influences) if j not in influence_set]
    if unresolved:
        raise ValueError(
            f"These DNA influences are not available on skinCluster '{skin_cluster}': {unresolved[:20]}"
        )

    vertex_count = int(cmds.polyEvaluate(mesh_name, vertex=True) or 0)
    vertex_count = min(vertex_count, skin_data.vertex_count)

    # Fast path: set all weights in one API call for replace mode.
    if replace_existing_weights and vertex_count > 0:
        try:
            g_main_progress_bar = mel.eval('$tmp = $gMainProgressBar')
            cmds.progressBar(
                g_main_progress_bar,
                edit=True,
                beginProgress=True,
                isInterruptable=True,
                status=f"Applying skinweights on {mesh_name} (fast path)...",
                maxValue=3,
            )

            mesh_dag = _get_mesh_dag_path(mesh_name)
            skin_fn = _get_skincluster_fn(skin_cluster)
            vertex_component = _build_full_vertex_component(vertex_count)
            cmds.progressBar(g_main_progress_bar, edit=True, step=1, status="Resolving influences...")

            influence_indices = om2.MIntArray()
            for inf in cluster_influences:
                sel = om2.MSelectionList()
                sel.add(inf)
                inf_dag = sel.getDagPath(0)
                influence_indices.append(int(skin_fn.indexForInfluenceObject(inf_dag)))

            weight_matrix = _build_skin_weight_matrix(
                skin_data=skin_data,
                cluster_influences=cluster_influences,
                vertex_count=vertex_count,
            )

            if normalize_weights:
                row_sums = weight_matrix.sum(axis=1)
                non_zero = row_sums > 1e-12
                weight_matrix[non_zero] = weight_matrix[non_zero] / row_sums[non_zero, None]
            cmds.progressBar(g_main_progress_bar, edit=True, step=1, status="Applying weights...")

            weight_values = om2.MDoubleArray(weight_matrix.reshape(-1).tolist())
            skin_fn.setWeights(
                mesh_dag,
                vertex_component,
                influence_indices,
                weight_values,
                normalize_weights,
            )
            cmds.progressBar(g_main_progress_bar, edit=True, step=1, status="Skinweights applied.")
            cmds.progressBar(g_main_progress_bar, edit=True, endProgress=True)
            return skin_cluster
        except Exception as exc:
            try:
                cmds.progressBar(g_main_progress_bar, edit=True, endProgress=True)
            except Exception:
                pass
            cmds.warning(
                f"Falling back to per-vertex skinPercent in load_skinweights_on_mesh due to API error: {exc}"
            )

    return _load_skinweights_on_mesh_with_skinpercent(
        mesh_name=mesh_name,
        skin_cluster=skin_cluster,
        skin_data=skin_data,
        cluster_influences=cluster_influences,
        vertex_count=vertex_count,
        replace_existing_weights=replace_existing_weights,
        normalize_weights=normalize_weights,
    )


def _load_skinweights_on_mesh_with_skinpercent(
    mesh_name: str,
    skin_cluster: str,
    skin_data: MeshSkinWeights,
    cluster_influences: List[str],
    vertex_count: int,
    replace_existing_weights: bool,
    normalize_weights: bool,
) -> str:
    """
    Fallback loader: apply skin weights using per-vertex cmds.skinPercent calls.
    """
    g_main_progress_bar = mel.eval('$tmp = $gMainProgressBar')
    cmds.progressBar(
        g_main_progress_bar,
        edit=True,
        beginProgress=True,
        isInterruptable=True,
        status=f"Applying skinweights on {mesh_name}...",
        maxValue=max(vertex_count, 1),
    )
    try:
        for vertex_id in range(vertex_count):
            if cmds.progressBar(g_main_progress_bar, query=True, isCancelled=True):
                raise RuntimeError("Skinweight loading cancelled by user.")

            component = f"{mesh_name}.vtx[{vertex_id}]"
            weights_for_vertex = skin_data.vertex_weights.get(vertex_id, [])

            if replace_existing_weights:
                mapped = dict(weights_for_vertex)
                transform_values = [(inf, float(mapped.get(inf, 0.0))) for inf in cluster_influences]
            else:
                transform_values = [(joint_name, float(weight)) for joint_name, weight in weights_for_vertex]

            cmds.skinPercent(
                skin_cluster,
                component,
                transformValue=transform_values,
                normalize=normalize_weights,
            )
            cmds.progressBar(
                g_main_progress_bar,
                edit=True,
                step=1,
                status=f"Applying vertex {vertex_id + 1}/{vertex_count}",
            )
    finally:
        cmds.progressBar(g_main_progress_bar, edit=True, endProgress=True)

    return skin_cluster

def read_blendshape_targets(
    dna_path: str,
    mesh_name: str = "head_lod0_mesh",
    lod: int = 0,
    blendshape_node_name: Optional[str] = None,
) -> List[BlendShapeTarget]:
    """
    Read every blend shape target on the given mesh and return the full
    driver chain:

      BlendShapeTarget
        └── RawControl  (CTRL_expressions.*)
              └── GUIControl  (CTRL_L_*.*, CTRL_R_*.*)
                    └── ConditionalEntry  (piecewise segment)

    Parameters
    ----------
    dna_path             : path to the .dna file
    mesh_name            : mesh name in the DNA (e.g. "head_lod0_mesh")
    lod                  : LOD level to read blend shape behavior from
    blendshape_node_name : override Maya blendShape node name; defaults to
                           "{mesh_name}_blendShapes"
    """
    reader    = _load_dna(dna_path)
    node_name = blendshape_node_name or f"{mesh_name}_blendShapes"

    # Find mesh index
    mesh_index = _find_mesh_index(reader, mesh_name)

    raw_count  = reader.getRawControlCount()
    raw_to_gui = _build_raw_to_gui(reader)
    psd_map    = _build_psd_map(reader, raw_to_gui)

    # LOD-filtered blend shape behavior entries
    lod_bounds = list(reader.getBlendShapeChannelLODs())
    lod_count  = lod_bounds[lod] if lod < len(lod_bounds) else len(lod_bounds)
    bs_inputs  = list(reader.getBlendShapeChannelInputIndices())[:lod_count]
    bs_outputs = list(reader.getBlendShapeChannelOutputIndices())[:lod_count]

    channel_to_inputs: Dict[int, List[int]] = {}
    for i in range(len(bs_outputs)):
        channel_to_inputs.setdefault(bs_outputs[i], []).append(bs_inputs[i])

    results: List[BlendShapeTarget] = []
    target_count = reader.getBlendShapeTargetCount(mesh_index)
    used_raw_indices: set = set()  # Track which raw controls drive actual deltas
    
    single_raw_channels = list() # keeping track of a raw channel that are driving directly a blendshape target
    multiple_raw_channels = list() # keeping track of raw channels that are driving a blendshape target through a PSD (so we can detect and warn about overlaps later)
    inbetween_parents = list() # keeping track of raw channels that are driving a blendshape target through a PSD but that are also driving directly another blendshape target, as this can be a sign of missing behavior entries in the DNA (e.g. a control that should only drive a PSD but that is also driving directly a target with required_value < 1.0, which can be a sign that the PSD entry for this control is missing from the DNA, causing it to fall back to direct driving with default required_value=1.0)
    for target_idx in range(target_count):
        bs_ch_idx   = reader.getBlendShapeChannelIndex(mesh_index, target_idx)
        target_name = reader.getBlendShapeChannelName(bs_ch_idx)
        input_indices = channel_to_inputs.get(bs_ch_idx, [])

        if not input_indices:
            continue

        raw_ctrls: List[RawControl] = []
        is_direct = False
        is_psd    = False

        for input_idx in input_indices:
            if input_idx < raw_count:
                # ── Direct path ───────────────────────────────────────────────
                # input_idx IS the raw control index
                is_direct = True
                used_raw_indices.add(input_idx)
                raw_name  = reader.getRawControlName(input_idx)
                gui_ctrls = _build_gui_ctrls(
                    raw_to_gui.get(input_idx, []),
                    target_raw=1.0
                )
                raw_ctrls.append(RawControl(
                    channel=raw_name,
                    required_value=1.0,
                    gui_ctrls=gui_ctrls,
                ))
            else:
                # ── PSD path ──────────────────────────────────────────────────
                # input_idx is the unified PSD key (same index space, no offset)
                is_psd = True
                psd_raw_ctrls = psd_map.get(input_idx, [])
                raw_ctrls.extend(psd_raw_ctrls)
                # Track raw controls used by this PSD
                for rc in psd_raw_ctrls:
                    for raw_idx in range(raw_count):
                        if reader.getRawControlName(raw_idx) == rc.channel:
                            used_raw_indices.add(raw_idx)
                            break

        # Skip targets with no control expressions
        if not raw_ctrls or any(rc.channel is None for rc in raw_ctrls):
            # we have a sanity check failure where the PSD references a raw control index that doesn't exist in the DNA
            # print(f"Warning: Blend shape target '{target_name}' references a raw control index that exceeds the raw control count in the DNA. This target will be skipped.")
            continue

        driver_type = (
            DriverType.DIRECT if is_direct and not is_psd else
            DriverType.PSD    if is_psd    else
            DriverType.NONE
        )
        blue_steel_target_name = _generate_blue_steel_name(raw_ctrls)
        blendshape_target =BlendShapeTarget(
                                            blendshape_node=node_name,
                                            target_index=target_idx,
                                            target_name=target_name,
                                            driver_type=driver_type,
                                            raw_ctrls=raw_ctrls,
                                            blue_steel_target_name=blue_steel_target_name,)
    
        if len(raw_ctrls) == 1 and driver_type == DriverType.DIRECT:
            if raw_ctrls[0] not in single_raw_channels:
                single_raw_channels.append(raw_ctrls[0])
        else:
            for rc in raw_ctrls:
                if rc not in multiple_raw_channels:
                    multiple_raw_channels.append(rc)
        results.append(blendshape_target)

    # let's report if there are multiple__raw channels that are not in single_raw_channels, as this means we have some raw controls that are driving only PSD targets without any direct target, which can be a sign of missing behavior entries in the DNA
    missing_channels = [ch for ch in multiple_raw_channels if ch not in single_raw_channels]
    if missing_channels:
        for ch in sorted(missing_channels, key=lambda x: x.channel):
            blendshape_target = BlendShapeTarget(
                blendshape_node=node_name,
                target_index=-1,
                target_name=ch.channel,
                driver_type=DriverType.NOT_MAPPED,
                raw_ctrls=[],
                blue_steel_target_name=_generate_blue_steel_name([ch]),
            )
            results.append(blendshape_target)
            # print(f"  - {ch.channel.split('.')[-1]}")  # print only the control name without the "CTRL_expressions." prefix

    return results


def transfer_to_bluesteel(dnapath: str, blue_steel_editor: BlueSteelEditor):
    targets = read_blendshape_targets(dnapath)
    # we need the directory of the dna file to save the json files for each target in the same location
    dna_dir = os.path.dirname(dnapath)
    # we need to check if there is
    for t in targets:
        blue_steel_editor.add_target(t)

def print_targets(targets: List[BlendShapeTarget]):
    counts = {t: 0 for t in DriverType}
    for t in targets:
        counts[t.driver_type] += 1

    print(f"\nTotal: {len(targets)}  |  "
          f"Direct: {counts[DriverType.DIRECT]}  |  "
          f"PSD: {counts[DriverType.PSD]}  |  "
          f"None: {counts[DriverType.NONE]}\n")

    for t in targets:
        tag = f"[{t.driver_type.value.upper():<6}]"
        print(f"[{t.target_index:>3}] {tag}  {t.blendshape_node}.{t.target_name}")

        for raw in t.raw_ctrls:
            print(f"         CTRL_expressions : {raw.channel}"
                  f"  (required = {raw.required_value:.4f})")
            for g in raw.gui_ctrls:
                print(f"           GUI : {g.channel}"
                      f"  default={g.default_value:.4f}")
                for j, seg in enumerate(g.segments):
                    peak = (f"gui={seg.gui_for_raw_1:.4f}"
                            if seg.gui_for_raw_1 is not None
                            else "never reaches target")
                    print(f"             seg {j+1}: "
                          f"gui [{seg.from_value:.4f}→{seg.to_value:.4f}]  "
                          f"raw [{seg.raw_at_from:.4f}→{seg.raw_at_to:.4f}]  "
                          f"slope={seg.slope:.4f}  cut={seg.cut:.4f}  "
                          f"► {peak}")
        print()


def _find_loaded_plugin_for_node_type(node_type: str) -> Optional[str]:
    """
    Return the loaded plugin that registers node_type, if any.
    """
    plugins = cmds.pluginInfo(query=True, listPlugins=True) or []
    for plugin_name in plugins:
        try:
            depends = cmds.pluginInfo(plugin_name, query=True, dependNode=True) or []
        except Exception:
            continue
        if node_type in depends:
            return plugin_name
    return None


def _ensure_plugin_with_node_type_loaded(node_type: str, plugin_candidates: List[str]) -> str:
    """
    Ensure a plugin providing node_type is loaded.
    """
    existing = _find_loaded_plugin_for_node_type(node_type)
    if existing:
        return existing

    for plugin_name in plugin_candidates:
        try:
            if not cmds.pluginInfo(plugin_name, query=True, loaded=True):
                cmds.loadPlugin(plugin_name, quiet=True)
        except Exception:
            continue

        existing = _find_loaded_plugin_for_node_type(node_type)
        if existing:
            return existing

    existing = _find_loaded_plugin_for_node_type(node_type)
    if existing:
        return existing

    raise RuntimeError(
        f"Could not find a loaded plugin providing node type '{node_type}'. "
        f"Tried: {plugin_candidates}"
    )


def _ensure_embedded_rl4_node(node_name: str = "embeddedNodeRL4_1") -> str:
    """
    Ensure an embeddedNodeRL4 exists and return node name.
    """
    if cmds.objExists(node_name):
        if cmds.nodeType(node_name) != "embeddedNodeRL4":
            raise ValueError(f"Node '{node_name}' exists but is not type embeddedNodeRL4")
        return node_name

    return cmds.createNode("embeddedNodeRL4", name=node_name)


def _create_embedded_rl4_with_command(
    node_name: str,
    dna_path: str,
    control_naming: str = "<objName>.<attrName>",
    joint_naming: str = "<objName>.<attrName>",
    blend_shape_naming: str = "<objName>.<attrName>",
    animated_map_naming: str = "<objName>.<attrName>",
) -> Tuple[Optional[str], Optional[str]]:
    """
    Try creating/setup RL4 through the plugin MEL command createEmbeddedNodeRL4.

    Returns
    -------
    Tuple[node_name_or_none, mel_command_or_none]
    """
    if cmds.objExists(node_name):
        if cmds.nodeType(node_name) != "embeddedNodeRL4":
            raise ValueError(f"Node '{node_name}' exists but is not type embeddedNodeRL4")
        return node_name, None

    try:
        exists = int(mel.eval('exists "createEmbeddedNodeRL4"'))
    except Exception:
        exists = 0

    if not exists:
        return None, None

    def _esc(text: str) -> str:
        return str(text).replace('"', '\\"')

    dna_norm = str(dna_path).replace("\\", "/")
    mel_command = "createEmbeddedNodeRL4"
    mel_command += f' -n "{_esc(node_name)}"'
    mel_command += f' -dfp "{_esc(dna_norm)}"'
    mel_command += f' -cn "{_esc(control_naming)}"'
    mel_command += f' -jn "{_esc(joint_naming)}"'
    mel_command += f' -bsn "{_esc(blend_shape_naming)}"'
    mel_command += f' -amn "{_esc(animated_map_naming)}";'

    before = set(cmds.ls(type="embeddedNodeRL4") or [])
    cmd_result = mel.eval(mel_command)
    after = set(cmds.ls(type="embeddedNodeRL4") or [])

    if cmds.objExists(node_name) and cmds.nodeType(node_name) == "embeddedNodeRL4":
        return node_name, mel_command

    if isinstance(cmd_result, str) and cmds.objExists(cmd_result) and cmds.nodeType(cmd_result) == "embeddedNodeRL4":
        return cmd_result, mel_command

    new_nodes = sorted(list(after - before))
    if new_nodes:
        return new_nodes[0], mel_command

    return None, mel_command


def _set_string_attr_if_exists(node: str, attr_names: List[str], value: str) -> Optional[str]:
    """
    Set first matching string attr on node. Returns full attr path if set.
    """
    for attr in attr_names:
        if not cmds.attributeQuery(attr, node=node, exists=True):
            continue
        try:
            cmds.setAttr(f"{node}.{attr}", value, type="string")
            return f"{node}.{attr}"
        except Exception:
            continue
    return None


def _hide_transform_channels(node: str) -> None:
    """
    Hide and lock standard transform channels on a control holder transform.
    """
    attrs = [
        "tx", "ty", "tz",
        "rx", "ry", "rz",
        "sx", "sy", "sz",
        "v",
    ]
    for attr in attrs:
        plug = f"{node}.{attr}"
        if not cmds.objExists(plug):
            continue
        try:
            cmds.setAttr(plug, lock=True, keyable=False, channelBox=False)
        except Exception:
            pass


def _ensure_expression_control_group(
    group_name: str,
    expression_names: List[str],
) -> Dict[str, str]:
    """
    Ensure control transform and expression attrs exist.

    Returns
    -------
    Dict[str, str]
        raw control name -> full Maya attr plug
    """
    if cmds.objExists(group_name):
        if cmds.nodeType(group_name) != "transform":
            raise ValueError(f"Node '{group_name}' exists but is not a transform")
        ctrl_group = group_name
    else:
        ctrl_group = cmds.createNode("transform", name=group_name)

    _hide_transform_channels(ctrl_group)

    raw_to_plug: Dict[str, str] = {}
    used_attr_names: set = set(cmds.listAttr(ctrl_group) or [])

    for raw_name in expression_names:
        short_name = str(raw_name).split(".")[-1]
        attr_name = _safe_maya_name(short_name)

        if attr_name in used_attr_names and not cmds.attributeQuery(attr_name, node=ctrl_group, exists=True):
            suffix = 1
            while cmds.attributeQuery(f"{attr_name}_{suffix}", node=ctrl_group, exists=True):
                suffix += 1
            attr_name = f"{attr_name}_{suffix}"

        if not cmds.attributeQuery(attr_name, node=ctrl_group, exists=True):
            cmds.addAttr(
                ctrl_group,
                longName=attr_name,
                attributeType="double",
                min=0.0,
                max=1.0,
                defaultValue=0.0,
                keyable=True,
            )
        else:
            try:
                cmds.addAttr(f"{ctrl_group}.{attr_name}", edit=True, min=0.0, max=1.0)
                cmds.setAttr(f"{ctrl_group}.{attr_name}", keyable=True, channelBox=True)
            except Exception:
                pass

        used_attr_names.add(attr_name)
        raw_to_plug[str(raw_name)] = f"{ctrl_group}.{attr_name}"

    return raw_to_plug


def _connect_attr_force(source_plug: str, dest_plug: str) -> bool:
    """
    Force-connect source -> dest, disconnecting existing incoming connection on dest.
    """
    if not cmds.objExists(source_plug) or not cmds.objExists(dest_plug):
        return False

    incoming = cmds.listConnections(dest_plug, source=True, destination=False, plugs=True) or []
    for in_plug in incoming:
        try:
            cmds.disconnectAttr(in_plug, dest_plug)
        except Exception:
            pass

    try:
        cmds.connectAttr(source_plug, dest_plug, force=True)
        return True
    except Exception:
        return False


def _connect_expression_inputs_to_rl4(
    rl4_node: str,
    raw_names: List[str],
    raw_to_ctrl_plug: Dict[str, str],
) -> Tuple[int, List[str]]:
    """
    Connect expression attrs to RL4 node inputs.

    Uses a name match strategy first, then indexed-array fallbacks.
    """
    connected = 0
    missing: List[str] = []

    connectable_attrs = set(cmds.listAttr(rl4_node, connectable=True) or [])
    all_attrs = set(cmds.listAttr(rl4_node) or [])

    array_candidates = [
        "inputValues",
        "inputs",
        "input",
        "rawControls",
        "rawControlValues",
        "controlValues",
    ]
    array_candidates = [a for a in array_candidates if a in all_attrs]

    for idx, raw_name in enumerate(raw_names):
        source_plug = raw_to_ctrl_plug.get(raw_name)
        if not source_plug:
            missing.append(raw_name)
            continue

        short_name = str(raw_name).split(".")[-1]
        safe_short = _safe_maya_name(short_name)

        matched = False
        name_candidates = [
            short_name,
            safe_short,
            f"input_{short_name}",
            f"input_{safe_short}",
            str(raw_name),
            str(raw_name).replace(".", "_"),
        ]

        for attr in name_candidates:
            if attr not in connectable_attrs:
                continue
            if _connect_attr_force(source_plug, f"{rl4_node}.{attr}"):
                connected += 1
                matched = True
                break

        if matched:
            continue

        for base_attr in array_candidates:
            if _connect_attr_force(source_plug, f"{rl4_node}.{base_attr}[{idx}]"):
                connected += 1
                matched = True
                break

            children = cmds.attributeQuery(base_attr, node=rl4_node, listChildren=True) or []
            for child in children:
                if _connect_attr_force(source_plug, f"{rl4_node}.{base_attr}[{idx}].{child}"):
                    connected += 1
                    matched = True
                    break
            if matched:
                break

        if not matched:
            missing.append(raw_name)

    return connected, missing


def _connect_rl4_outputs_to_joints(
    rl4_node: str,
    joints: List[JointDefinition],
) -> Tuple[int, List[str]]:
    """
    Connect RL4 joint outputs to Maya joints.

    Uses attribute-name heuristics and indexed-array fallbacks.
    """
    connected = 0
    unresolved_joints: List[str] = []

    all_attrs = set(cmds.listAttr(rl4_node) or [])

    tx_arrays = [a for a in ["outputTranslateX", "translateX", "translationsX"] if a in all_attrs]
    ty_arrays = [a for a in ["outputTranslateY", "translateY", "translationsY"] if a in all_attrs]
    tz_arrays = [a for a in ["outputTranslateZ", "translateZ", "translationsZ"] if a in all_attrs]
    rx_arrays = [a for a in ["outputRotateX", "rotateX", "rotationsX"] if a in all_attrs]
    ry_arrays = [a for a in ["outputRotateY", "rotateY", "rotationsY"] if a in all_attrs]
    rz_arrays = [a for a in ["outputRotateZ", "rotateZ", "rotationsZ"] if a in all_attrs]

    vector_translate = [a for a in ["outputTranslations", "outputTranslate", "translations"] if a in all_attrs]
    vector_rotate = [a for a in ["outputRotations", "outputRotate", "rotations"] if a in all_attrs]

    for joint in joints:
        joint_name = str(joint.name)
        if not cmds.objExists(joint_name):
            unresolved_joints.append(joint_name)
            continue

        joint_connected = 0
        j_safe = _safe_maya_name(joint_name)

        # Name-based scalar output candidates.
        for axis, dst_attr in [("tx", "translateX"), ("ty", "translateY"), ("tz", "translateZ"), ("rx", "rotateX"), ("ry", "rotateY"), ("rz", "rotateZ")]:
            direct_candidates = [
                f"{joint_name}_{axis}",
                f"{j_safe}_{axis}",
                f"{joint_name}{axis.upper()}",
                f"{j_safe}{axis.upper()}",
            ]
            for src_attr in direct_candidates:
                if src_attr in all_attrs and _connect_attr_force(f"{rl4_node}.{src_attr}", f"{joint_name}.{dst_attr}"):
                    joint_connected += 1
                    break

        # Index-based scalar arrays.
        idx = int(joint.index)
        for arr in tx_arrays:
            if _connect_attr_force(f"{rl4_node}.{arr}[{idx}]", f"{joint_name}.translateX"):
                joint_connected += 1
                break
        for arr in ty_arrays:
            if _connect_attr_force(f"{rl4_node}.{arr}[{idx}]", f"{joint_name}.translateY"):
                joint_connected += 1
                break
        for arr in tz_arrays:
            if _connect_attr_force(f"{rl4_node}.{arr}[{idx}]", f"{joint_name}.translateZ"):
                joint_connected += 1
                break
        for arr in rx_arrays:
            if _connect_attr_force(f"{rl4_node}.{arr}[{idx}]", f"{joint_name}.rotateX"):
                joint_connected += 1
                break
        for arr in ry_arrays:
            if _connect_attr_force(f"{rl4_node}.{arr}[{idx}]", f"{joint_name}.rotateY"):
                joint_connected += 1
                break
        for arr in rz_arrays:
            if _connect_attr_force(f"{rl4_node}.{arr}[{idx}]", f"{joint_name}.rotateZ"):
                joint_connected += 1
                break

        # Index-based vector arrays (compound children).
        if joint_connected < 6:
            for arr in vector_translate:
                children = cmds.attributeQuery(arr, node=rl4_node, listChildren=True) or []
                if len(children) >= 3:
                    okx = _connect_attr_force(f"{rl4_node}.{arr}[{idx}].{children[0]}", f"{joint_name}.translateX")
                    oky = _connect_attr_force(f"{rl4_node}.{arr}[{idx}].{children[1]}", f"{joint_name}.translateY")
                    okz = _connect_attr_force(f"{rl4_node}.{arr}[{idx}].{children[2]}", f"{joint_name}.translateZ")
                    joint_connected += int(okx) + int(oky) + int(okz)
                    if okx and oky and okz:
                        break

            for arr in vector_rotate:
                children = cmds.attributeQuery(arr, node=rl4_node, listChildren=True) or []
                if len(children) >= 3:
                    okx = _connect_attr_force(f"{rl4_node}.{arr}[{idx}].{children[0]}", f"{joint_name}.rotateX")
                    oky = _connect_attr_force(f"{rl4_node}.{arr}[{idx}].{children[1]}", f"{joint_name}.rotateY")
                    okz = _connect_attr_force(f"{rl4_node}.{arr}[{idx}].{children[2]}", f"{joint_name}.rotateZ")
                    joint_connected += int(okx) + int(oky) + int(okz)
                    if okx and oky and okz:
                        break

        connected += joint_connected
        if joint_connected == 0:
            unresolved_joints.append(joint_name)

    return connected, unresolved_joints

def create_expression_ctrl_group(
    dna_path: str,
    ctrl_group_name: str = "CTRL_expressions"):
    """Create the control group with the expression attributes, without connecting them to any RL4 node.
    This can be used when the user wants to set up the embedded RL4 node manually (e.g. through the createEmbeddedNodeRL4 command) but still wants to have the control group with the expression attributes created for them.
    """
    reader = _load_dna(dna_path)
    raw_names = [str(reader.getRawControlName(i)) for i in range(int(reader.getRawControlCount()))]
    return  _ensure_expression_control_group(ctrl_group_name, raw_names)

def setup_embedded_rl4_driver(
    dna_path: str,
    rl4_node_name: str = "embeddedNodeRL4_1",
    ctrl_group_name: str = "CTRL_expressions",
    plugin_candidates: Optional[List[str]] = None,
) -> Dict[str, object]:
    """
    Build a basic RL4 driving setup:
    1) Ensure RL4 plugin is loaded.
    2) Ensure embeddedNodeRL4 node exists.
    3) Create CTRL_expressions transform and expression attrs (0..1).
    4) Set DNA file path on the RL4 node.
    5) Connect expression inputs and joint outputs.

    Returns a summary dictionary with counts and unresolved items.
    """
    if not dna_path or not ospath.exists(dna_path):
        raise ValueError(f"DNA file does not exist: {dna_path}")

    candidates = plugin_candidates or [
        "embeddedRL4",
        "embeddedRL4.mll",
        "RigLogic4",
        "RigLogic4.mll",
    ]

    plugin_name = _ensure_plugin_with_node_type_loaded("embeddedNodeRL4", candidates)

    reader = _load_dna(dna_path)
    raw_names = [str(reader.getRawControlName(i)) for i in range(int(reader.getRawControlCount()))]
    joints = _read_joint_definitions_from_reader(reader)

    raw_to_ctrl_plug = _ensure_expression_control_group(ctrl_group_name, raw_names)

    rl4_node, create_command = _create_embedded_rl4_with_command(
        node_name=rl4_node_name,
        dna_path=dna_path,
        control_naming="<objName>.<attrName>",
        joint_naming="<objName>.<attrName>",
        blend_shape_naming="<objName>.<attrName>",
        animated_map_naming="<objName>.<attrName>",
    )

    used_create_command = rl4_node is not None and create_command is not None
    if rl4_node is None:
        rl4_node = _ensure_embedded_rl4_node(rl4_node_name)

    dna_attr = _set_string_attr_if_exists(
        rl4_node,
        ["dnaFilePath", "dnaPath", "dnaFile", "filePath", "dna"],
        dna_path,
    )

    # If createEmbeddedNodeRL4 was used, it should already establish the naming-based
    # connections. We still run fallback wiring only when needed.
    input_connected, missing_inputs = _connect_expression_inputs_to_rl4(
        rl4_node=rl4_node,
        raw_names=raw_names,
        raw_to_ctrl_plug=raw_to_ctrl_plug,
    )

    output_connected, unresolved_joints = _connect_rl4_outputs_to_joints(
        rl4_node=rl4_node,
        joints=joints,
    )

    return {
        "plugin": plugin_name,
        "rl4_node": rl4_node,
        "ctrl_group": ctrl_group_name,
        "used_createEmbeddedNodeRL4": used_create_command,
        "createEmbeddedNodeRL4_command": create_command,
        "dna_attr": dna_attr,
        "raw_control_count": len(raw_names),
        "joint_count": len(joints),
        "input_connections_made": input_connected,
        "output_connections_made": output_connected,
        "missing_input_controls": missing_inputs,
        "unresolved_output_joints": unresolved_joints,
    }


#=============================================================================
# Meta human expression editor rig builder
#=============================================================================

def _create_config_from_dna(mh_path: str) -> Config:
    """
    Create a configuration dictionary from the MetaHuman file path.
    """
    if not ospath.exists(mh_path):
        raise ValueError(f"MetaHuman file does not exist: {mh_path}")
    if ospath.isfile(mh_path):
        mh_path = ospath.dirname(mh_path)
    name = ospath.split(mh_path)[-1]
    # Creating the "config key"
    bodyDnaPath = ospath.join(mh_path,"body.dna")
    if not ospath.exists(bodyDnaPath):
        raise ValueError(f"MetaHuman file does not contain body.dna: {mh_path}")
    headDnaPath = ospath.join(mh_path,"head.dna")
    if not ospath.exists(headDnaPath):
        raise ValueError(f"MetaHuman file does not contain head.dna: {mh_path}")
    mapsDirPath = ospath.join(mh_path,"Maps")
    if not ospath.exists(mapsDirPath):
        raise ValueError(f"MetaHuman file does not contain Maps folder: {mh_path}")
    config= {
              "bodyDnaPath": bodyDnaPath,
              "mapsDirPath": mapsDirPath, 
              "headDnaPath": headDnaPath,
            }
    return Config(config)


def build_facial_rig_from_dna(dna_path: str, up_axis: str = "dna"):
    """
    Build the facial rig for a MetaHuman character.
    
    Args:
        dna_path (str): Path to the DNA file.

        up_axis (str): Up axis for the rig ('y', 'z', 'dna').
                       Defaults to "dna".
    """
    # we need to take the directory name
    character_importer = CharacterImporter()
    character_importer.config = _create_config_from_dna(dna_path)
    character_importer.config.options.import_head = True
    character_importer.config.options.import_body = False
    character_importer.config.options.import_textures = False
    character_importer.config.options.combine_skeletons = False
    character_importer.config.scene_orientation_string_value = up_axis
    character_importer.config.options.scene_orientation = character_importer.config.resolve_scene_orientation()
    dna = DNAReader.read(character_importer.config.head_dna_path, Layer.all)
    character_importer.import_head(dna)
    character_importer.namespace_head_joints()
    character_importer.scene_cleanup()
    character_importer.connect_follow_head()
    character_importer.create_rl_nodes()
    character_importer.order_display_layers()
    character_importer.create_head_controls_set()

    print(f"Config created from DNA: {character_importer.config}")

def build_expressions_rig(dna_path: str, up_axis: str = "dna"):
    """
    Build the expressions rig for a MetaHuman character.
    
    Args:
        dna_path (str): Path to the DNA file.
        up_axis (str): Up axis for the rig ('y', 'z', 'dna').
                       Defaults to "dna".
    """
    if not Resources().initialize_from_dna_file(dna_path):
        raise RuntimeError(f"MetaHuman DNA format not supported.")
    
    node_name = control.Controller.DNA_CALIB_NODE_NAME

    config = general.load_json(Resources().config_file_path)

    joint_pruning_threshold = [
            config["pruning_threshold"]["joint_translation_pruning_threshold"],
            config["pruning_threshold"]["joint_rotation_pruning_threshold"],
            config["pruning_threshold"]["joint_scale_pruning_threshold"],
        ]
    head_turns_main_expressions = config["head_turns_data"]["main_expressions"]
    neck_joints = config["neck_joints"]
    neck_joints_values = []
    
    for main_expression in head_turns_main_expressions:
        main_expression_data = config["head_turns_data"]["neck_joints_animation"][main_expression]
        for neck_joint in neck_joints:
            neck_joints_values.extend(main_expression_data[neck_joint])

    lib.validate_rdf_compatibility(Resources().rdf_file_path, Resources().dna_file_path)
    result = lib.orient_dna(Resources().dna_file_path, up_axis)
    if result is not None:
        print(f"DNA orientation result: {result}")
    load_dna_file_path = result[0]
    up_axis = result[1]
    global_up_axis_rotation = result[2]
    cbs_pruning_threshold = config["pruning_threshold"]["corrective_blend_shape_pruning_threshold"]
    # build Rig Data handler
    rig = RigDataHandler(
                Resources().rdf_file_path,
                load_dna_file_path,
                **config["pruning_threshold"],)
            
    # starting the rig assembling process
    dcc.assemble_rig_editing_scene(
            rig = rig,
            **config["gui_positioning"], #left_arm_joint_name, eye_aim_control_name, right_eye_control_name, gui_object_name,
            up_axis=up_axis,
            rotation=global_up_axis_rotation,
        )
    dcc.add_dna_calib_node(
        node_name,
        Resources().dna_file_path,
        Resources().rdf_file_path,
        cbs_pruning_threshold,
        joint_pruning_threshold,
        head_turns_main_expressions,
        neck_joints,
        neck_joints_values,
        global_up_axis_rotation)