# Blue Steel Wiki

## Overview

Blue Steel is a blendshape authoring and management tool for Maya.

The editor is built around a shared shape model and multiple filtered views so
artists can work on dense facial rigs without losing context.

Core goals:

- Keep naming-based shape logic consistent.
- Make high-volume shape editing fast.
- Keep UI synchronized with scene/editor changes.

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

## Main Editor Panels

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

### Shapes

What it does:

- Shows all shapes grouped by level/type.
- Supports search and filtering.
- Supports set-pose by interaction.
- Supports context actions (for example extract selected).

Key behavior:

- Double-clicking a shape sets that pose.
- Shape rows reflect value/mute/editability state.

### Sliders Drop Box

What it does:

- Temporary subset list for selected primaries.
- Allows synchronized slider work over a focused subset.

### Work Shapes

What it does:

- Manage work blendshape targets.
- Supports adding/removing targets.
- Supports painting and edit mode toggling.
- Supports link operations and weight map copy/paste operations.

### Active Shapes

What it does:

- Filtered list of currently active shapes.
- Useful for quick debugging and contribution tracking.

## Common Workflows

### 1. Create or Load a System

1. Create a new editor from selected mesh, or select an existing system.
2. Blue Steel loads shape/network state and starts trackers.

### 2. Author Primaries

1. Use Add Primary to create a new empty primary shape.
2. Adjust primary values in the Primaries panel.
3. Rename primaries inline when needed.

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

- [releases/maya/scripts/blue_steel/ui/editor/mainWindow.py](maya/scripts/blue_steel/ui/editor/mainWindow.py)
- [releases/maya/scripts/blue_steel/api/editor.py](maya/scripts/blue_steel/api/editor.py)
- [references/design/Logic.md](../references/design/Logic.md)
