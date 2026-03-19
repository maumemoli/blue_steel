# MMTools Wiki

## Overview

MMTools is a utility toolkit shipped with Blue Steel for common Maya rigging and
mesh-editing operations.

It focuses on:

- Cluster creation, painting, mirroring, and linking.
- Vertex position copy/paste workflows.
- Intermediate object updates.
- Fast attribute connection between selected nodes.

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

- Copy Vtx Positions: stores selected mesh vertex positions in a buffer.
- Paste Vtx Positions: pastes buffered positions to selected mesh.
- Update Intermediate Object: updates target intermediate shape from source.

### Notes

- Copy/paste requires compatible vertex counts.
- Update Intermediate Object expects exactly two selected transforms.

## Attribute Tools

Implemented in:

- [releases/maya/BlueSteel/scripts/blue_steel/mmtools/connectionTools.py](maya/BlueSteel/scripts/blue_steel/mmtools/connectionTools.py)

Available action:

- Connect Same Name Attributes: connects keyable attributes with matching names
  from source node to target node.

## UI Module

The MMTools window is built in:

- [releases/maya/BlueSteel/scripts/blue_steel/ui/mmtools/__init__.py](maya/BlueSteel/scripts/blue_steel/ui/mmtools/__init__.py)

UI sections map directly to function modules:

- Cluster Tools -> smartCluster
- Mesh Tools -> meshTools
- Attribute Tools -> connectionTools

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

### Attribute connect misses channels

- Only keyable attributes are considered.
- Names must match exactly between source and target.
