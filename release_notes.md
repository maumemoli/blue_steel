## What's new in v1.7.2

Full diff of `v1.7.1` → `v1.7.2` (13 files, +892 / -73).

### Work Shapes

- **Apply Weights shortcut** - the weight-map apply action is no longer nested under the **Weight Maps** submenu: it is a top-level context-menu entry with the **Ctrl+Alt+A** shortcut and a tooltip. `WorkShapesListView._weight_map_targets()` resolves the selected work-shape leaves (falling back to the current item) and ignores group and driver rows, so the shortcut works for multi-selections.
- **Weight-map application rework** - `apply_masked_weight_maps_to_work_shapes` now bakes each shape's masked deformation through a temporary filter blendshape (transfer the weight map, connect the target, duplicate the filtered mesh) and then clears the source weight maps, instead of applying the mask in place. Missing shapes are skipped with a warning rather than raising.
- **Weighted propagation** - **Propagate to Active Shapes** now scales each active shape's delta mask by its current blendshape weight. `get_shapes_delta_masks` takes a parallel `shapes_weights` list and `propagate_work_shape_to_active_shapes` takes `active_shapes_weights`, so a shape at partial value receives a proportionally smaller share. The source work shape's drivers are disconnected before propagating, and the operation is now `@undoable` and `@timed`.
- **Propagation dialog weights** - the active-shapes dialog is now a two-column tree (`Active Shapes` / `Weight`) with an editable `_EnterSafeDoubleSpinBox` per shape (0.000-1.000, default 1.000). Editing a weight updates the shape's checkbox and the level check state, and value edits are mirrored across the current multi-selection (Ctrl/Shift selection on the weight fields is supported); a weight of 0.000 unchecks and excludes the shape. Enter commits the typed value without closing the dialog, and the **Propagate** button is no longer the dialog default.
- **Extract / Combine carry weight maps** - `extract_axis_motion_from_work_shape` now copies the source weight map onto the extracted shape, and **Combine Work Shapes** applies the masked weight maps of every source plus the target before merging.

### Sliders Drop Box

- **Drag-to-reorder** - dragging a selected row and releasing inside the box now rearranges the entries (shared insertion indicator; multi-selections move as a block and keep their relative order; releasing over empty space appends). The order is kept on the backing `PrimarySubsetProxyModel`, whose `selected_names()` now returns insertion/reorder order instead of an alphabetical list, backed by a new `reorder_selected_names(names, target, position)` and a parallel membership set for O(1) filtering. Tree rebuilds and filtering reapply the stored order (hidden rows after the visible block) and restore the selection and current item, so the arrangement survives refreshes and system switches. Drag-outside removal is unchanged.
- A tooltip documents the **drag inside to reorder / drag outside to remove** gestures.

### Docs & tests

- `docs/ui-structure.md` and `releases/WIKI.md` document the ordered drop-box model, the new reorder handlers, and the **Ctrl+Alt+A** apply-weights shortcut.
- New `releases/maya/BlueSteel/unittest/primaryDropBoxUiUt.py` (355 lines) covers `PrimarySubsetProxyModel` ordering, drop-box reorder/rebuild/selection persistence, and the drag gesture (`test_drag_inside_emits_reorder_request`, `test_multi_select_drag_moves_every_selected_entry`, `test_reorder_preserves_selection`, ...).

### Fixes & MMTOOLS

- `duplicate_base_mesh_at_current_pose` always returns the extracted mesh name (uses `fullPath=True`, moves and renames the `_extracted_GRP` consistently), fixing callers such as propagation that previously could receive `None`.
- **SmartCluster** - `create` now applies the soft-selection weights unconditionally (the `weighted` gate was removed), `make_paint_cluster` no longer enters paint mode when soft selection is off, and a leftover print statement and unused shape lookup were removed.
- `Blendshape.transfer_weight_map` / `connect_weight_map` docstring and formatting cleanup (parameter names, line wrapping).

<details>
<summary>Full commit list (v1.7.1 → v1.7.2)</summary>

- a92c842 Removed print statement from create classmethod in smartCluster
- d3cb8ae Apply soft-selection weights unconditionally in SmartCluster
- 2673ef8 Weight work-shape propagation by active-shape weights
- df058fb Add drag-to-reorder to the Sliders Drop Box
- 8086a25 Fixed bug on duplicate_base_mesh_at_current_pose that was not always returning a string
- ad1c035 Add Ctrl+Alt+A shortcut for Apply Weights and rework weight-map propagation

</details>

## What's new in v1.7.1

Full diff of `v1.7.0` → `v1.7.1` (8 files, +455 / -57).

### Work Shapes

- **Search** - a **Filter work shapes...** token search bar above the tree hides work shapes that do not match the entered terms, keeping group folders visible whenever one of their children matches. The active search is re-applied after tree rebuilds (add/remove/reload).

### File dialogs

- **Maya-native file dialogs** - the File > Import/Export actions (BlendShape node and Alembic) and the OBJ / split-data directory pickers now use `cmds.fileDialog2` with `dialogStyle=2` instead of Qt's `QFileDialog`, so they match Maya's own file browser. Extension correction for `.ma`/`.mb`/`.abc` is unchanged. New helpers `_maya_file_dialog`, `_maya_open_file_dialog`, `_maya_save_file_dialog` and `_maya_directory_dialog` centralize the calls.

### Shape interchange (Alembic / BlendShape node)

- **Shared sequence metadata** - metadata writing was centralized in `_add_sequence_metadata_to_node`, now used by both the blendshape-node and Alembic exporters, so blendshape-node exports carry the same `shapesSequenceMetaData` (`totalShapes`, `shapesList`, `controlSorting`, `customShapeColorAttributes`, `currentUnitTime`, `exportType`, `editorVersion`).
- **Import restores layout metadata** - `import_blendshape_node` reads `controlSorting` and `customShapeColorAttributes` from the imported metadata, and `ingest_shapes_from_blendshape_node` gained `control_sorting` / `custom_shapes_colors` parameters to re-apply them, so imported shapes keep their ordering and custom colors.
- **More robust export/import** - `currentUnitTime` is written from `cmds.currentTime` instead of `currentUnit`, the export type (`absolute` / `relative`) and editor version are recorded, temporary-node deletion is guarded with `cmds.objExists`, and the `AbcExport` job string quotes the file path and normalizes backslashes to forward slashes so paths containing spaces survive parsing.

<details>
<summary>Full commit list (v1.7.0 → v1.7.1)</summary>

- 4616e82 Add search filter to the Work Shapes panel
- e122c39 Use Maya-native file dialogs for OBJ, BlendShape, Alembic, and split-data selection
- e1e0c85 refactor: improve Alembic shape interchange metadata handling

</details>

## What's new in v1.7.0

Full diff of `v1.6.5` → `v1.7.0` (30 files, +6195 / -1317).

### Work Shapes

**The Work Shapes panel is now a hierarchical tree.** It moved from the flat `QListView`/`WorkShapeItemsModel` backing store to an item-based `QTreeWidget` (`WorkShapesListView`) using shared `WorkShapeRoles`. `WorkShapeItemsModel` was retired (`models.py` -329 lines). Grouping and ordering mirror the Primaries tree: identical 16 px-per-level indentation, native branch glyph hidden, chevrons painted by the delegate.

- **Grouping & ordering** - drag a shape onto the middle of a group to nest it, onto a group's top/bottom edge to reorder as a sibling, or onto empty space to move it to the top level. **Ctrl+G** (or context-menu **Group Selected**) groups the selection; folder rows expose **Rename Group** and **Ungroup**. Ordering/nesting is persisted on the container in the new `workShapeSorting` attribute via the shared `TreeViewOrderingManager`, and reconciled against the rig on load.
- **Extract Motion Axis** - new context submenu that splits a work shape's target delta into per-axis contributions: **X**, **Y**, **Z**, plus a **Positive** submenu (`X+`, `Y+`, `Z+`) and a **Negative** submenu (`X-`, `Y-`, `Z-`). The source shape keeps the remaining motion and each extraction creates a new work shape named `<shape>_extracted_<Axis>[Positive|Negative]`, inserted directly below its source (staying inside the same group). Driver connections are copied to the extracted shape (`extract_axis_motion_from_work_shape`).
- **Combine Work Shapes** - **Ctrl+J** (or context menu) sums the target deltas of the other selected work shapes into the active/current shape and deletes the sources (`combine_work_shapes`). The delegate paints an outline on the target so it's clear which shape receives the merge.
- **Apply Weights** - **Ctrl+Alt+A** (or the context action above **Clear Weights**) applies masked weight maps to every selected work shape (`apply_masked_weight_maps_to_work_shapes`).
- **Clear Weights now multi-shape** - `clear_work_weight_map_values` was renamed to `clear_work_weights_map_values(shape_names)` and accepts a list; Normalize, Apply and Clear all receive the full work-shape selection.
- **Auto Edit mode** - new checkable toolbar toggle (EDIT icon, distinct red checked state). It keeps the work blendshape sculpt target in sync with the highlighted work shape via `currentItemChanged`, so Edit mode no longer has to be re-entered for each shape (`auto_edit_work_shape_button`, `_auto_edit_work_shape`, `_activate_work_shape_edit_mode`).
- **Propagate to Active Shapes** - replaced the "minimum propagation level" behavior with a dialog listing active shapes grouped by level with checkboxes, so the exact targets can be chosen. Propagated shapes are automatically grouped into a `<work_shape>_Propagation` folder (`get_active_shapes` added to the API; `propagate_work_shape_to_active_shapes` now takes an `active_shapes` list).
- **Driver disclosure** - **Alt+right-click** a driver triangle expands/collapses all drivers of every work shape; a single left-click on a group's custom chevron toggles that group; nested rows indented like the Primaries tree.
- `extract_work_shape` now automatically connects the extracted shape's driver shapes.

### Primaries

- **Hierarchical ordering & grouping** - `PrimaryTreeWidget` gained internal drag-and-drop to reorder, nest (drop on a group's middle band) or move to root (drop on empty space), with a self-drawn drop indicator (line for reorder, filled rect for nesting). **Ctrl+G** groups the selection. The context menu adds **Group Selected**, **Rename Group**, **Ungroup** and **Split Selected Primaries**.
- Ordering/grouping persists on the container in the `faceCtrlSorting` attribute through the shared `TreeViewOrderingManager` (renamed from `FaceCtrlSortingStore`, moved to `api/treeViewOrderingManager.py`; persisted attribute names unchanged so existing scenes keep working). New editor accessors `read/write_sorting_attribute`.
- **Alt+left-click** a group header expands/collapses every group; a plain click still toggles only the clicked group.

### Active Shapes

- New `ActiveShapesItemDelegate` for the read-only monitor list (`ActiveShapesListView`): suppresses the slider track, fill and type indicator, and uses a fixed value width so resizing doesn't stretch the value column.
- **Alt+left-click** a level header expands/collapses every level at once via `ShapesFilterProxyModel.set_all_levels_collapsed()` (the pinned **With Value** header is skipped).

### Sliders Drop Box

- New **Add Active** button (ADD icon) next to **Get Active**: it merges the currently active primaries into the box instead of replacing its contents. **Get Active** now uses the refresh icon. Both have clear tooltips (`_add_primary_drop_list_from_active`, shared `_active_primary_names`).
- **Drag-out removal** - dragging a selected row outside the box and releasing removes the selected entries, with a closed-hand cursor while dragging and a trash-bin cursor once outside. Value-scrub and lock-icon areas are excluded so slider scrubbing and icon clicks still work.
- **Drag-to-reorder** - dragging a selected row within the box now rearranges the entries (a blue insertion line shows the drop target); multi-selections move together and keep their relative order. The order is stored on the backing `PrimarySubsetProxyModel`, so it survives refreshes and system switches for the session, and is restored when rows are rebuilt. Releasing over empty space moves the selection to the end.

### Shapes / Split views

- **Shapes tree** - Alt+left-click any group row expands/collapses all groups.
- **Split Primary Group Assignments** - Alt+left-click a top-level group expands/collapses all groups; plain clicks are unchanged.

### Editor window

- **Workspace collapse/expand** - a collapse toggle button was added to the editor menu bar. In docked mode the released space goes to Maya's viewport (not the toolbox) by resizing the dock splitter/neighbors; it saves and restores window size, constraints and splitter state, works for floating and docked layouts, and handles dock/undock reparenting while collapsed. The menu bar is hidden while docked and collapsed.

### Mesh utilities

- **Copy Vtx Positions** / **Paste Vtx Positions** buttons added to the side toolbar (new `copy_vertices_icon.svg` / `paste_vertices_icon.svg`), wired to the existing `meshTools.copy_selected_mesh_vertex_position` / `paste_vertex_positions_to_selected_mesh`.

### Shape interchange (Alembic)

- Export and import shape sequences as **Alembic (.abc)**, including metadata (total shapes, shape list, unit time, sorting) stored under the new `shapesSequenceMetaData` attribute; editor menu entries were added. This replaces the previous `.ma`/`.mb` blendshape export.
- New helpers: `export_shapes_as_alembic`, `import_shapes_from_alembic`, `ingest_shapes_from_blendshape_node`, `import_shapes_from_blendshape_node`, `_connect_mesh_to_blendshape`, plus `ShapeImportCancelled` for clean progress-bar cancellation.

### Performance & internals

- `@timed` decorator for timing functions and `disable_viewport_update` to suspend viewport refreshes during heavy operations (`mayaUtils.py`), plus `_preserve_node_connections` context manager for safe temporary disconnections.
- Split-commit-shape optimization; `SplitSession.commit_pose` gained an `invert_shape` flag to invert the split deformation before baking.
- Removed the obsolete `api/mayaToNumpy_ref.py`.
- Shared UI refactors: `SliderIconClickMixin`, `ReorderableTreeWidgetMixin`, `OutsideRemovalDragMixin`, and `build_trash_cursor()`.

### Docs & tests

- Docs updated: `docs/api-editor-structure.md`, `docs/ui-structure.md`, `releases/WIKI.md`.
- New/expanded tests: `activeShapesUiUt.py`, `primaryDropBoxUiUt.py`, `treeViewOrderingManagerUt.py`, `workShapeExtractionOrderingUt.py`, `workShapesUiUt.py`, `tests/maya/test_editor_collapse.py`.

<details>
<summary>Full commit list (v1.6.5 → v1.7.0)</summary>

- bb0384e Added copy, paste vertices buttons to the side toolbar
- 32cd6e8 Add Alt+left-click expand/collapse-all for Active Shapes and split groups
- 8dad427 Added alt click to collapse expand shapes tree view groups
- c4bdf65 Alt + left click on the primary groups will collapse/expand all the groups
- b51e8ba ui: implement specialized ActiveShapesItemDelegate for read-only monitor list
- eee1ab7 feat: implement workspace collapse/expand functionality for Blue Steel editor
- f024bfd Enable drag-out removal in Sliders Drop Box
- ddc9ff7 Add 'Add Active' action to Sliders Drop Box
- 5367f85 version up
- 7427dd4 Add Auto Edit mode for work shapes
- 0fd2c46 Changed naming on extracted motion work shapes
- e5ae2fa Implement 'Combine Work Shapes' feature
- 9193bcf Added combined work shapes function added function to place the extracted motion axis workshape under the parent shape
- 5bd75c6 Added extract motion to functions to the workshapes context menu
- b33db0b First draft of the extract axis motion function
- 2ec691f Add Apply Weights work-shape action and support multi-shape clear
- 7905f99 Created static method _connect_mesh_to_blendshape
- a6f2e22 Added timed wrapper to check speed of functions
- 777954a feat: add Alembic shape interchange and improve batch performance
- fc51ed4 First pass on optimization of the split commit shapes
- 992d30b Renamed _group_propagated_work_shape to a more generic name _group_work_shapes
- 314a265 refactor: improve work shape propagation and logging
- 32317d5 Removed mayaToNumpy_ref.py
- 05dcc39 refactor: rename FaceCtrlSortingStore to TreeViewOrderingManager
- 2b30513 feat: hierarchical grouping/ordering for work shapes
- e2f29ba feat: implement hierarchical ordering and grouping for primary shapes
- ea1ec56 added data string for control attributes ordering and groups with methods to add the data
- 3ce613c Implement Alt+right-click to expand/collapse all drivers in WorkShapesListView
- af89836 Refactor 'Propagate to Active Shapes' to allow specific shape selection via a dialog
- 4af7c25 Added get active shapes function to editor.py
- 0f1f48d changed version

</details>
