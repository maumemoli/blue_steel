# MMTools Wiki

## Overview

MMTools is a utility toolkit shipped with Blue Steel for common Maya rigging and
mesh-editing operations.

It focuses on:

- Cluster creation, painting, mirroring, and linking.
- Fast and reliable vertex position copy/paste workflows.
- Intermediate object updates.
- BlendShape target weight-map transfer between meshes.
- Fast attribute connection between selected nodes.

The standout workflow is **Copy Vtx Positions -> Paste Vtx Positions** for
Blendshape target editing. In production this is especially effective when used
with Blue Steel WorkShapes to make non-destructive facial rig changes.

## Launching MMTools

You can launch MMTools from the Blue Steel editor using the MMTools button.

Runtime commands are also registered from:

- [releases/maya/BlueSteel/scripts/blue_steel/mmtools/__init__.py](maya/BlueSteel/scripts/blue_steel/mmtools/__init__.py)

## Hotkey Runtime Commands

On launch, MMTools sets up a set of Maya runtime command slots for common
actions (for example launch UI, cluster tools, mirror tools, and utility
operations).

You can use those runtime command slots in Maya's Hotkey Editor to assign your
own keyboard shortcuts.

## Tool Groups

## Cluster Tools

Implemented in:

- [releases/maya/BlueSteel/scripts/blue_steel/mmtools/smartCluster.py](maya/BlueSteel/scripts/blue_steel/mmtools/smartCluster.py)

Available actions include:

- Create/Paint Cluster: create a cluster from current component selection.
- Toggle Cluster on/off: mute/unmute selected clusters.
- Select latest cluster: cycle through tracked cluster handles.
- Update Cluster List: rebuild working cluster list from selection or scene.
- Mirror Cluster: mirror a cluster to opposite side using selected axis.
- Smooth Flood Weights: smooth deformer paint values in paint context.
- Link Mirrored Cluster: connect mirrored handles with transform inversion.
- Reset Transformations: reset keyable channels to defaults.

### Notes

- Mirror behavior uses the configured mirror axis.
- Some operations depend on current selection mode and paint context.

## Mesh Tools

Implemented in:

- [releases/maya/BlueSteel/scripts/blue_steel/mmtools/meshTools.py](maya/BlueSteel/scripts/blue_steel/mmtools/meshTools.py)

Available actions:

- Copy Vtx Positions: stores selected mesh vertex positions in a plugin buffer.
- Paste Vtx Positions: pastes buffered positions to selected mesh.
- Update Intermediate Object: updates target intermediate shape from source.

### Notes

- Copy/paste is backed by `bsMeshPointsClipboard` and auto-loads the plugin on
  first use.
- Copy/paste requires compatible topology/vertex count.
- Paste expects a selected transform with a mesh shape.
- On meshes with history, paste is history-aware and works through the
  intermediate/orig shape path so the visible output shape matches your copied
  data.
- If a history mesh has no tweak connection, paste is blocked and MMTools shows
  an in-view warning.
- Update Intermediate Object expects exactly two selected transforms.

## Why Copy/Paste Is So Useful For Blendshape Work

When a blendshape target is in edit mode, artists often need to move sculpted
vertex deltas between targets, cleanup passes, or versions without baking or
collapsing deformation history.

In practice, this is especially valuable when artists are working with meshes
snapped to scans. Being able to quickly copy vertex positions from a mesh
produced by wrapping software and paste them onto a target in edit mode makes
facial target iteration much faster and safer.

MMTools Copy/Paste is ideal for this because:

- It is quick enough for iterative sculpt loops.
- It preserves a non-destructive workflow when used on history-driven meshes.
- It pairs naturally with Blue Steel WorkShapes for facial exploration and
  refinement.

## WorkShape + Blendshape Edit-Mode Workflow (Recommended)

This is the workflow we recommend for non-destructive facial blendshape rig
iteration in Blue Steel:

1. In Blue Steel, create/select a WorkShape and put the intended target into
   edit mode.
2. Sculpt or otherwise modify the source shape.
3. Select the source mesh transform and run **Copy Vtx Positions**.
4. Select the destination blendshape target/workshape mesh transform.
5. Run **Paste Vtx Positions**.
6. Validate deformation in context and continue iterating.

This pattern is very effective for transferring detailed facial edits while
keeping your rig process flexible and non-destructive.

## Attribute Tools

Implemented in:

- [releases/maya/BlueSteel/scripts/blue_steel/mmtools/connectionTools.py](maya/BlueSteel/scripts/blue_steel/mmtools/connectionTools.py)

Available action:

- Connect Same Name Attributes: connects keyable attributes with matching names
  from source node to target node.

## BlendShape Weight Map Transfer

Open it from **Blendshape Editor Tools > Transfer Weight Maps**. It copies the
per-vertex weight maps of every blendShape target from one mesh to another, so a
sculpted weight-map pass can be reused on a different (for example
retopologized) mesh.

Implemented in:

- [releases/maya/BlueSteel/scripts/blue_steel/mmtools/blendshape_transfer_tools.py](maya/BlueSteel/scripts/blue_steel/mmtools/blendshape_transfer_tools.py) — the transfer engine (`transfer_blendshape_weight_maps`, `WeightsTransferMethod`).
- [releases/maya/BlueSteel/scripts/blue_steel/mmtools/ui/blendshape_transfer_ui.py](maya/BlueSteel/scripts/blue_steel/mmtools/ui/blendshape_transfer_ui.py) — the `BlendshapeTransferUI` dialog and its `show_window()` entry point.

Dialog fields:

- **Source Mesh** / **Destination Mesh**: the meshes that receive and provide the
  weight maps (`Pick` fills the field from the current selection). Both meshes
  prefill from the scene selection when the dialog opens.
- **Source BlendShape**: the blendShapes found in the source mesh history (the
  first one is selected by default).
- **Destination BlendShape**: an existing blendShape on the destination mesh
  (matching target weight maps are overwritten, missing targets are added) or
  **Create New...**.
- **New BlendShape Name**: optional name for the created destination blendShape;
  an automatic name is used when empty.
- **Method**: surface association used by `copySkinWeights` — **UV** (default),
  **Closest Point**, **Closest Component** or **Ray Cast**.
- **Source UV Set** / **Destination UV Set**: used by the UV method only; these
  fields are disabled for the world-space methods. Defaults are read from the
  original meshes before any duplication happens.
- **Weights to Transfer**: every source target, all checked by default. Ctrl/Shift
  select several entries and click a checkbox to toggle them together.
- **Match Source Target Directories**: recreates or reuses the nested folder
  hierarchy of the source blendShape in the destination blendShape and moves the
  transferred targets into it. Root-level source targets move to the destination
  root; only the needed folders are created and unrelated destination targets or
  folder settings are left untouched.

### Notes

- The transfer never touches the original meshes' deformers: each side is built
  on a history-free duplicate, with one temporary joint per target name, a
  temporary skinCluster per duplicate, and `copySkinWeights` doing the actual
  transfer. The temporary duplicate meshes, skinClusters, joints and namespaces
  are removed and the previous selection is restored afterwards.
- The temporary skinCluster envelope is disabled so the transferred weights are
  not scaled, and the read-back values are written straight into the destination
  blendShape targets.
- The source and destination meshes must be different objects. A supplied
  existing destination blendShape must be connected to the destination mesh.
- The dialog window title is **Transfer BlendShape Weight Maps**.
- Weight maps are per-vertex: the transferred maps are resampled onto the
  destination by the chosen method (UV space or world-space association), so the
  destination does not need the same vertex count. UV transfer needs a valid UV
  set on both meshes; the world-space methods ignore UV sets entirely.
- The same engine powers **Split Data import** with a weight transfer method: it
  is fed by the `neutral.obj` written next to the split data, and reuses the
  destination blendShape instead of creating a new one.

## UI Module

The MMTools window is built in:

- [releases/maya/BlueSteel/scripts/blue_steel/mmtools/ui/__init__.py](maya/BlueSteel/scripts/blue_steel/mmtools/ui/__init__.py)

UI sections map directly to function modules:

- Cluster Tools -> smartCluster
- Mesh Tools -> meshTools
- Attribute Tools -> connectionTools
- Blendshape Editor Tools -> blendshape_transfer_ui (Transfer Weight Maps),
  shape_editor_tools

## Typical Workflows

### Mirror cluster workflow

1. Select source cluster handle.
2. Optional: select target mirrored cluster handle.
3. Set mirror axis in MMTools UI.
4. Run Mirror Cluster.
5. Optional: run Link Mirrored Cluster.

### Vertex transfer workflow

1. Select source mesh and run Copy Vtx Positions.
2. Select target mesh with matching topology.
3. Run Paste Vtx Positions.

### Facial blendshape non-destructive workflow

1. Open the Blue Steel editor and choose a WorkShape.
2. Set the destination blendshape target/workshape to edit mode.
3. Copy from a source facial shape using Copy Vtx Positions.
4. Paste into the target using Paste Vtx Positions.
5. Repeat as needed to build and refine the final facial target set.

### Fast control hookup workflow

1. Select source node, then target node.
2. Run Connect Same Name Attributes.
3. Verify connections in Channel Box/Node Editor.

## Troubleshooting

### Nothing happens on cluster tools

- Confirm valid selection (cluster handle or mesh components).
- Confirm current Maya context (paint-related tools require paint context).

### Paste Vtx Positions fails

- Ensure vertex count matches copied buffer.
- Ensure selected object is a transform with mesh shape.
- Ensure `bsMeshPointsClipboard` is available and loadable.
- If the mesh has history, ensure tweak/orig-shape plumbing is valid.

### Attribute connect misses channels

- Only keyable attributes are considered.
- Names must match exactly between source and target.
