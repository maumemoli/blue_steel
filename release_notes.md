## What's new in v1.7.0

Full diff of `v1.6.5` → `v1.7.0` (30 files, +6195 / -1317).

### Work Shapes

**The Work Shapes panel is now a hierarchical tree.** It moved from the flat `QListView`/`WorkShapeItemsModel` backing store to an item-based `QTreeWidget` (`WorkShapesListView`) using shared `WorkShapeRoles`. `WorkShapeItemsModel` was retired (`models.py` -329 lines). Grouping and ordering mirror the Primaries tree: identical 16 px-per-level indentation, native branch glyph hidden, chevrons painted by the delegate.

- **Grouping & ordering** - drag a shape onto the middle of a group to nest it, onto a group's top/bottom edge to reorder as a sibling, or onto empty space to move it to the top level. **Ctrl+G** (or context-menu **Group Selected**) groups the selection; folder rows expose **Rename Group** and **Ungroup**. Ordering/nesting is persisted on the container in the new `workShapeSorting` attribute via the shared `TreeViewOrderingManager`, and reconciled against the rig on load.
- **Search** - a **Filter work shapes...** token search bar above the tree hides work shapes that do not match the entered terms, keeping group folders visible whenever one of their children matches. The active search is re-applied after tree rebuilds (add/remove/reload).
- **Extract Motion Axis** - new context submenu that splits a work shape's target delta into per-axis contributions: **X**, **Y**, **Z**, plus a **Positive** submenu (`X+`, `Y+`, `Z+`) and a **Negative** submenu (`X-`, `Y-`, `Z-`). The source shape keeps the remaining motion and each extraction creates a new work shape named `<shape>_extracted_<Axis>[Positive|Negative]`, inserted directly below its source (staying inside the same group). Driver connections are copied to the extracted shape (`extract_axis_motion_from_work_shape`).
- **Combine Work Shapes** - **Ctrl+J** (or context menu) sums the target deltas of the other selected work shapes into the active/current shape and deletes the sources (`combine_work_shapes`). The delegate paints an outline on the target so it's clear which shape receives the merge.
- **Apply Weights** - new context action above **Clear Weights** that applies masked weight maps to every selected work shape (`apply_masked_weight_maps_to_work_shapes`).
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

### Shapes / Split views

- **Shapes tree** - Alt+left-click any group row expands/collapses all groups.
- **Split Primary Group Assignments** - Alt+left-click a top-level group expands/collapses all groups; plain clicks are unchanged.

### Editor window

- **Workspace collapse/expand** - a collapse toggle button was added to the editor menu bar. In docked mode the released space goes to Maya's viewport (not the toolbox) by resizing the dock splitter/neighbors; it saves and restores window size, constraints and splitter state, works for floating and docked layouts, and handles dock/undock reparenting while collapsed. The menu bar is hidden while docked and collapsed.

### File dialogs

- **Maya-native file dialogs** - the File > Import/Export actions (BlendShape node and Alembic) and the OBJ / split-data directory pickers now use `cmds.fileDialog2` with `dialogStyle=2` instead of Qt's `QFileDialog`, so they match Maya's own file browser. Extension correction for `.ma`/`.mb`/`.abc` is unchanged.

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
