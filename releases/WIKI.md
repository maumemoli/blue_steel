# Blue Steel Wiki

Current documented version: **v1.6.0-beta.7**

## Overview

Blue Steel is a blendshape authoring and management tool for Maya.

The editor is built around a shared shape model and multiple filtered views so
artists can work on dense facial rigs without losing context.

Core goals:

- Keep naming-based shape logic consistent.
- Make high-volume shape editing fast.
- Keep UI synchronized with scene/editor changes.

The current interface is divided into two main tabs:

- **Editor**: the primary workspace for authoring, inspecting, and managing
  facial shapes and WorkShapes.
- **Split Settings**: the workspace for configuring split groups and split maps
  before creating split shape systems.

## Quick Links

- [Shape Types](#shape-types)
- [Editor Tab](#editor-tab)
- [Split Settings Tab](#split-settings-tab)
- [Split Maps and Split Groups](#split-maps-and-split-groups)
- [How Combo Splits Avoid Duplication](#how-combo-splits-avoid-duplication)
- [SkinCluster-Aware Shape Extraction](#skincluster-aware-shape-extraction)
- [Common Workflows](#common-workflows)
- [Troubleshooting](#troubleshooting)
- [MMTools Wiki](MMTOOLS_WIKI.md)

## Prerequisites

Blue Steel requires NumPy to be installed in the Maya Python environment.

Install NumPy with `mayapy`:

### Windows

```powershell
"C:\Program Files\Autodesk\Maya2026\bin\mayapy.exe" -m pip install numpy
```

### macOS

```bash
"/Applications/Autodesk/maya2026/Maya.app/Contents/bin/mayapy" -m pip install numpy
```

### Linux

```bash
"/usr/autodesk/maya2026/bin/mayapy" -m pip install numpy
```

If your Maya version differs, replace `2026` in the path.

If you are still having trouble installing NumPy, see this [Autodesk Forum post](https://forums.autodesk.com/t5/maya-programming-forum/guide-how-to-install-numpy-scipy-in-maya-windows-64-bit/td-p/5796722).

## Videos

- [Blue Steel Quick Start Guide](https://www.youtube.com/watch?v=ci4G5WN6mcs)

## Shape Types

Blue Steel classifies shape names into these types:

- Primary: base shape name with no numeric suffix.
  - Example: `jawOpen`
- Inbetween: primary name with a two-digit suffix.
  - Example: `jawOpen50`
- Combo: multiple parents joined by the configured separator.
  - Example: `jawOpen_lipCornerPull`
- Combo Inbetween: combo name where one parent includes an inbetween suffix.
  - Example: `jawOpen50_lipCornerPull`

Shape validity and typing are driven by the logic layer.

## Main Tabs

### Editor

The Editor tab contains the day-to-day Blue Steel authoring tools. It includes
the Primaries tree, Shapes tree, Sliders Drop Box, Work Shapes, Active Shapes,
and the collapsible tool sidebar.

### Split Settings

The Split Settings tab contains the split-map settings used to organize primary
assignments, split groups, and split maps. Use it when preparing a combined
shape system for splitting. See [Split Settings Tab](#split-settings-tab) for
the setup concepts and combo-processing behavior.

## Split Settings Tab

The tab is labeled **Split Settings** in the current UI. It contains four main
areas:

- **Primary Split Group Assignment**: assigns each primary shape to a Split
  Group.
- **Split Groups**: organizes one or more reusable Split Maps for assignment to
  primaries.
- **Split Maps**: manages the available maps and their regions.
- **Split Map Editor**: creates and edits the normalized regions of a selected
  map.

## Split Maps and Split Groups

A **Split Map** is a reusable set of normalized regions that defines how a
shape should be divided. The regions of a map should combine to describe the
complete split.

For example, a `LeftRight` Split Map contains two regions:

- `Left`
- `Right`

A **Split Group** is an ordered collection of Split Maps. Primaries are assigned
to Split Groups, rather than defining all of their split regions independently.
This makes the maps reusable across many primaries and combinations.

### Map Order and Suffixes

The order of the Split Maps in a Split Group determines the order of the
suffixes in the generated shape names.

For example, combining an `UpperLower` map with a `LeftRight` map produces four
regions:

- Upper Left: `UL`
- Upper Right: `UR`
- Lower Left: `DL`
- Lower Right: `DR`

When `UpperLower` comes before `LeftRight`, the generated suffix order is `UL`,
`UR`, `DL`, `DR`. Changing the map order changes how the suffixes are composed,
so Split Group order should be chosen deliberately and kept consistent.

## How Combo Splits Avoid Duplication

Split Maps become particularly useful when processing combination shapes. Blue
Steel gathers the Split Maps used by the Split Groups of every primary in the
combo, combines those maps, and processes each shared map only once.

Consider a combo between:

- `lipCornerPuller`, assigned to `LeftRightSplitGroup [LeftRight]`
- `lipFunneler`, assigned to `MouthSplitGroup [UpperLower, LeftRight]`

It may be tempting to create one four-region map for `lipFunneler`. However, if
the combined Upper and Lower influence on each side is equivalent to the
corresponding Left and Right regions, combining that map with the `LeftRight`
map from `lipCornerPuller` would generate eight shapes. Four would be redundant
because the Left/Right information is already represented in the four-region
map.

Using the reusable maps above allows Blue Steel to detect that `LeftRight` is
shared by both primaries. The combo is therefore processed from the unique map
set:

```text
MouthSplitGroup:     [UpperLower, LeftRight]
LeftRightSplitGroup: [LeftRight]
Unique combo maps:   [UpperLower, LeftRight]
```

The common `LeftRight` split is processed once, avoiding redundant output
shapes. The important principle is to build reusable Split Maps for meaningful
regions, combine them in ordered Split Groups, and let combo processing remove
duplicate map usage across primaries.

## Editor Tab

### Sidebar Tool Buttons

#### MMTools Button

- Opens the MMTools utility window.
- See the [MMTools Wiki](MMTOOLS_WIKI.md) for its cluster, mesh, and vertex
  copy/paste workflows.

#### Editor Group

- **Select Controller**: Select the current controller in the scene.
- **Controller Layout**: Open the controller layout window for the current
  editor.
- **Zero All**: Set all values to zero.
- **Rename To Pose**: Rename the current selected mesh to match the pose name. This is useful to commit a shape at the current pose.
- **Duplicate Rename**: Duplicate and rename the current selection.

#### Shapes Edit Group
- **Add/Commit New Primary**: Add a new primary shape (from selection or empty).
- **Add/Commit At Current Pose**: Add a shape at the current pose, naming it from active values.
- **Commit Selected**: Commit the selected shapes.

#### Shapes Preview Group

- **Unmute All Shapes**: Unmute all shapes for preview.
- **Unlock All Shapes**: Unlock all shapes for editing.
- **Toggle HUD**: Toggle the Blue Steel HUD. Hold Alt to change the HUD without
  listing active combinations.

#### Debug Group
- **Compare Shapes**: Compare selected shapes for differences.

### Primaries

What it does:

- Displays primary shapes in a directory-like tree.
- Lets you edit values directly.
- Supports inline rename.
- Supports context actions like adding inbetweens.

Key behavior:

- Value edits commit to the active editor.
- Sorting can be by name or value.
- Folder rows summarize descendant values for sorting.
- Selecting primaries filters the Shapes panel to related shapes.
- The filtering method can use standard matching or an exclusive exact
  relationship.
- Double-clicking a primary sets its defined pose.

### Shapes

What it does:

- Shows all shapes grouped by level/type.
- Supports search and filtering.
- Supports set-pose by interaction.
- Supports context actions including Extract Selected and Reset Deltas.

Key behavior:

- Double-clicking a shape sets that pose.
- Shape rows reflect value/mute/editability state.
- Shapes are grouped by level and type.
- Multiple search terms can be entered as removable search tokens.
- Shape extraction supports base meshes with a skinCluster and compensates for
  skeletal deformation when the extracted mesh is committed as a target.

Top bar toggle buttons:

- **Auto Pose**: Automatically set the pose of a selected shape.
- **List Active**: Capture and display only the shapes that have a value when
  the button is enabled. The list is a snapshot and does not update
  interactively as values change.
- **Downstream**: Display shapes affected by the selected shape.
- **Upstream**: Display shapes that affect the selected shape.
- **Highlight Related**: Highlight upstream and downstream relationships while
  keeping the complete Shapes list visible.

Selecting a primary clears the List Active, Upstream, and Downstream filters.

### Sliders Drop Box

What it does:

- Temporary subset list for selected primaries.
- Allows synchronized slider work over a focused subset.
- Accepts dragged shapes and can populate active primaries with **Get Active**.

### Work Shapes

What it does:

- Manage work blendshape targets.
- Supports adding/removing targets.
- Supports painting and edit mode toggling.
- Supports drag-and-drop links from source shapes.
- Supports duplicating and extracting WorkShape meshes.
- Supports breaking links and applying all linked WorkShapes.
- Supports weight-map copy, paste, inverted paste, add, subtract, normalize, and
  clear operations.

Key behavior:

- Double-click a WorkShape to rename it inline.
- Alt+double-click a linked WorkShape to set and select its connected driver
  shape.
- The WorkShape context-menu **Extract Mesh** operation is separate from regular
  shape extraction and is currently unavailable when the editor mesh has a
  skinCluster.


### Active Shapes

What it does:

- Filtered list of currently active shapes.
- Useful for quick debugging and contribution tracking.

Key behavior:

- The panel updates as shape values change.
- Double-clicking an active shape selects it in Shapes and selects its driving
  primaries.
- Active shapes can be searched with multiple search tokens.

### Heat Map

When the required DGA nodes are available, **Display Heat Map** visualizes the
selected target on the editor mesh. The control is hidden when those nodes are
not supported.

## Menus

- **File**: create a new editor, import/export OBJ shape sets, or exit.
- **Utilities**: rename the current editor, expose or collapse container nodes,
  and repair blendshape targets hidden by directory-index issues.
- **Split Shapes**: import/export split data or create a split-shapes editor.
- **Converters/Clean-Up**: convert or connect Simplex systems and prepare an
  editor for publishing.
- **Help**: open the About dialog.

## SkinCluster-Aware Shape Extraction

The current editor supports extracting regular shapes when the base mesh has a
skinCluster. This is important for rigs where one or more primaries also move
the skeleton.

During extraction, Blue Steel keeps the skinCluster active so the extracted
mesh contains the complete posed result, including the deformation produced by
the moving joints. When that mesh is committed back to the blendshape, Blue
Steel uses Maya's shape inversion to compensate for the existing deformation
stack and stores the correct target delta.

Without this compensation, the skeletal deformation would already be present
in the extracted mesh and would then be applied again by the rig, producing a
double transformation. The inverted target prevents that duplication, so the
committed shape matches the extracted pose when evaluated with the skeleton.

This support applies to **Extract Selected** in the Shapes panel and the normal
shape commit workflow. It does not currently apply to **Extract Mesh** in the
Work Shapes context menu.

## Common Workflows

### 1. Create or Load a System

1. Create a new editor from selected mesh, or select an existing system.
2. Blue Steel loads shape/network state and starts trackers.

### 2. Author Primaries

1. Commit a selected mesh with a valid primary name such as `lipCornerPuller`,
   or use **Add/Commit New Primary** to create an empty primary.

### 3. Add Inbetweens

1. Right-click a primary in Primaries.
2. Choose Add Inbetween.
3. Enter a two-digit value (`00` to `99`).
4. Blue Steel creates the inbetween, refreshes UI, sets its pose, and selects it.

### 4. Extract or Duplicate Meshes

1. Select one or more shapes in Shapes.
2. Use context action Extract Selected to extract mesh output from the current pose.
3. Use Duplicate Rename for quick pose mesh duplication.

### 5. Commit Shapes

1. Select polygon mesh(es) in Maya.
2. Click Commit Selected.
3. Blue Steel validates names and inserts shapes in dependency-safe order.

### 6. Make Non-Destructive Changes With WorkShapes

1. Add a WorkShape or duplicate an existing one.
2. Enter edit mode and sculpt the target.
3. Drag a source shape onto the WorkShape to link it when needed.
4. Apply linked WorkShapes when the edits are ready.

MMTools vertex Copy/Paste works especially well here for transferring wrapped
scan results onto a WorkShape or blendshape target in edit mode. See the
[MMTools Wiki](MMTOOLS_WIKI.md).

## Tracking and Synchronization

Blue Steel uses scene and blendshape trackers to keep the editor synchronized:

- Scene editor tracker: editor add/remove/rename/open/reset events.
- Blendshape trackers: value changes, shape adds/removes/renames, node deletes.

Most write operations stop trackers during the mutation and restart afterward to
avoid feedback loops.

## Naming and Validation Notes

- Inbetween values use two digits.
- Invalid names are rejected by the logic/network layer.
- Combo ordering is normalized by separator-aware sorting.

## Troubleshooting

### Inbetween added but not visible

- Clear shape filters.
- Refresh UI.
- Confirm name validity.

### Rename or add actions fail

- Verify current system is selected.
- Check status bar error text for exact API exception.

### UI seems stale

- Use Refresh.
- Ensure trackers are active and target nodes still exist.

## Related Files

- [Editor UI](maya/BlueSteel/scripts/blue_steel/ui/editor/mainWindow.py)
- [Split Settings UI](maya/BlueSteel/scripts/blue_steel/ui/editor/splitSettings.py)
- [Editor API](maya/BlueSteel/scripts/blue_steel/api/editor.py)
- [MMTools Wiki](MMTOOLS_WIKI.md)
- [references/design/Logic.md](../references/design/Logic.md)
