# we will try to import the dna module, if it fails we issue an error message
from os import makedirs
from os import path as ospath
from ...api.editor import BlueSteelEditor
import re
import os

try:
    import dna
except ImportError:
    import traceback
    traceback.print_exc()
    raise ImportError("Failed to import dna. Please make sure they are installed and available in the Python path.\n Refer to the documentation for more information on how to install the MetaHuman for Maya plugin: https://dev.epicgames.com/documentation/en-us/metahuman/installing-in-maya")



from dataclasses import dataclass, field
from typing import List, Optional, Dict
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
    mesh_index = None
    for i in range(reader.getMeshCount()):
        if reader.getMeshName(i) == mesh_name:
            mesh_index = i
            break
    if mesh_index is None:
        available = [reader.getMeshName(i) for i in range(reader.getMeshCount())]
        raise ValueError(f"Mesh '{mesh_name}' not found. Available: {available}")

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


