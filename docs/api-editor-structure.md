# Blue Steel API — `BlueSteelEditor` Structure Plan

This document proposes how to decompose the `BlueSteelEditor` "god class" in
`blue_steel/api/editor.py` (5,001 lines / ~255 KB) into a thin facade plus a
set of focused collaborator modules, without breaking any existing consumer.

It is written so a human (or a fresh AI session) can understand the target
structure, the ownership boundaries, and the migration order before touching
code.

## Summary

- [§1 Current state](#1-current-state)
- [§2 Design principles](#2-design-principles)
- [§3 Target architecture](#3-target-architecture)
- [§4 Target package map](#4-target-package-map)
- [§5 The `EditorContext` contract](#5-the-editorcontext-contract)
- [§6 Method migration map](#6-method-migration-map)
- [§7 Shared-state ownership](#7-shared-state-ownership)
- [§8 Phased migration plan](#8-phased-migration-plan)
- [§9 Backward-compatibility guarantees](#9-backward-compatibility-guarantees)
- [§10 Risks and mitigations](#10-risks-and-mitigations)
- [§11 Open decisions](#11-open-decisions)

Primary source under change:

- [`editor.py`](../releases/maya/BlueSteel/scripts/blue_steel/api/editor.py) — the class to decompose.

Supporting modules that already exist and should be reused rather than
duplicated:

- [`logic/network.py`](../releases/maya/BlueSteel/scripts/blue_steel/logic/network.py) — shape graph (`Network`, `Shape`, `ShapeList`).
- [`logic/shape.py`](../releases/maya/BlueSteel/scripts/blue_steel/logic/shape.py) — shape value object.
- [`logic/splitData.py`](../releases/maya/BlueSteel/scripts/blue_steel/logic/splitData.py) — split pose data.
- [`api/blendshape.py`](../releases/maya/BlueSteel/scripts/blue_steel/api/blendshape.py) — Maya `blendShape` node wrapper.
- [`api/container.py`](../releases/maya/BlueSteel/scripts/blue_steel/api/container.py) — Maya container wrapper.
- [`api/constants.py`](../releases/maya/BlueSteel/scripts/blue_steel/api/constants.py) — identifier strings (partially populated).
- [`api/blendshapeHUD.py`](../releases/maya/BlueSteel/scripts/blue_steel/api/blendshapeHUD.py), [`api/shapeEditorUtils.py`](../releases/maya/BlueSteel/scripts/blue_steel/api/shapeEditorUtils.py), [`api/attrUtils.py`](../releases/maya/BlueSteel/scripts/blue_steel/api/attrUtils.py), [`api/mayaUtils.py`](../releases/maya/BlueSteel/scripts/blue_steel/api/mayaUtils.py) — helpers.

Related doc: [`ui-structure.md`](ui-structure.md) describes the UI layer that
consumes this domain object.

---

## 1. Current state

`api/editor.py` contains two top-level classes:

| Class | Lines | Role |
|---|---|---|
| `SplitSession` | 58–167 | Per-split-run state (area→weight lookups, active areas). Already a good collaborator. |
| `BlueSteelEditor` | 169–5001 | Everything else: ~4,830 lines, ~218 methods and 21 properties. |

`BlueSteelEditor` currently aggregates at least nine unrelated
responsibilities. Approximate line spans:

| Concern | Lines | Representative methods |
|---|---|---|
| Module constants / identifiers | 40–55, 170–193 | `MAIN_BLENDSHAPE_STRING_IDENTIFIER`, … |
| `__init__` orchestration | 194–274 | sets up container, blendshapes, network, HUD |
| Skin cluster setup | 279–294 | `_get_skin_cluster` |
| HUD + heat map + DGA nodes | 295–573 | `display_heat_maps`, `_create_dga_heat_maps_node_network`, `toggle_hud_display` |
| Container metadata / identity | 603–707 | `uuid`, `name`, `*_blendshape_name`, `base_mesh` |
| Network / shape queries | 755–860, 2535–2724 | `build_network`, `sync_network`, `get_related_shapes_up/downstream` |
| Work shapes | 862–1420, 1850–1960, 2845–2896 | `extract_work_shape`, `get_work_shape_driver_nodes`, `disable_all_deformers` |
| Weight-map clipboard | 1237–1420 | `copy/paste/normalize/add/subtract` weight maps |
| Shape building (primary/inbetween/combo) | 1433–1750, 2724–3058 | `commit_shapes`, `add_primary_shape`, `add_combo_shape`, `remove_shapes` |
| Import / export IO | 2045–2535, 4461–4550 | `import_objs`, `export_objs`, `export_shapes_as_blendshape_node` |
| Lifecycle / repository classmethods | 3096–3366, 3449–3474 | `create_new`, `rename_editor`, `get_editors`, `prepare_for_publishing` |
| Combo/remap node factory | 3367–3448 | `create_combo_node`, `create_remap_value_node` |
| Custom shape colors | 3475–3533 | `read/write/set/remove_shape_custom_color` |
| **Split maps** | **3534–4965 (~1,430, ~90 methods)** | `create_split_map`, `split_shapes`, `split_and_commit_split_shapes`, `create_split_shapes_editor`, edit-map workflow |

Measured signals that motivate the split:

- **One class, many reasons to change.** A heat-map node change and a split
  bake change touch the same file. The class has no cohesion boundary.
- **Hard to test.** `unittest/workShapesUiUt.py` monkeypatches
  `api.BlueSteelEditor = object` because instantiating the real class needs a
  Maya scene with a fully built rig. Most logic is untestable in isolation.
- **Duplicated constants.** ~20 identifier strings are redeclared as class
  attributes even though `api/constants.py` already defines them.
- **Known TODO.** `build_network` (line ~757) carries
  `#TODO: THIS NEEDS TO BE UPDATED WITH THE set_blendshape LOGIC FROM THE NETWORK CLASS`,
  i.e. logic that belongs in `logic/network.py` currently lives in the facade.
- **Latent bug.** `BlueSteelEditor.uuid` (line 606) reads
  `self.container_view.uuid`, but `container_view` is never assigned. The
  property raises `AttributeError`.

Consumers import the class by module path. A repository-wide grep shows:

```
from ...api.editor import BlueSteelEditor   # UI, converters, mmtools
```

There are **no imports of submodules of `editor.py`**, only the class name
(and `SplitSession`). This is what makes the package conversion in §3 safe.

---

## 2. Design principles

1. **Composition over inheritance/mixins.** `BlueSteelEditor` becomes a thin
   facade that owns shared state and delegates to collaborator objects.
   Mixins were rejected: they keep a single object with one shared `self`,
   do not reduce the size of the change surface, and do not improve
   testability. Collaborators can be unit-tested with a fake context.
2. **Facade + delegation preserves the public API.** The facade re-exposes
   every public method and property with the same signature. Consumers never
   learn that the implementation moved.
3. **Narrow coupling via an explicit context protocol.** Collaborators receive
   an `EditorContext` (see §5), not the concrete `BlueSteelEditor`. This
   prevents circular imports and makes the real dependency surface explicit.
4. **Push logic down, don't just relocate it.** Graph bookkeeping goes into
   `logic/` (`Network`, `ShapeList`, `SplitData`); node manipulation goes into
   `api/` wrappers (`Blendshape`, `Container`). The new controller modules are
   **glue**, not new god classes.
5. **Staged, reversible migration.** Each phase is independently shippable and
   guarded by a reflection contract test, so a regression is caught before the
   next extraction.
6. **One owner per piece of mutable state.** Session state such as the split
   bake buffers or the weight-map clipboard belongs to exactly one
   collaborator (§7).

---

## 3. Target architecture

### Package conversion

`api/editor.py` becomes the package `api/editor/` with a re-exporting
`__init__.py`:

```python
# api/editor/__init__.py
from .facade import BlueSteelEditor
from .split.session import SplitSession

__all__ = ["BlueSteelEditor", "SplitSession"]
```

Because every consumer imports `from ...api.editor import BlueSteelEditor`,
this conversion requires **no call-site changes**. `SplitSession` stays
importable from the same path for the UI's split workflow.

### Layering

```
                         consumers
        UI mixins · converters · mmtools · tests
                            │
                 api/editor/__init__.py  (re-exports)
                            │
                 api/editor/facade.py
          BlueSteelEditor — state + delegation only
                            │
     ┌──────────┬───────────┼───────────┬──────────────┐
     │          │           │           │              │
 containerView heatMap   workShapes  shapeBuilder  networkController
     │          │           │           │              │
 colors    weightMapOps     io       lifecycle      split/
     └──────────┴───────────┴───────────┴──────────────┘
                            │
                    EditorContext (§5)
                            │
     ┌──────────┬───────────┼───────────┬──────────────┐
 logic/     api/          api/        api/          maya
 network.py blendshape.py container.py mayaUtils.py  cmds/mel
```

The facade is the only object consumers construct. Collaborators never import
`facade.py`.

---

## 4. Target package map

All new files live in `blue_steel/api/editor/`.

| File | Purpose | Owns mutable state |
|---|---|---|
| `__init__.py` | Public entry: re-exports `BlueSteelEditor`, `SplitSession`. | — |
| `facade.py` | `BlueSteelEditor`: shared-state init, orchestration, thin delegating properties/methods. | `locked_shapes`, `hud_on`, `skin_cluster`, core node refs |
| `context.py` | `EditorContext` protocol describing the narrow surface collaborators may use. | — |
| `containerView.py` | Container metadata and editor identity: node-name properties, `base_mesh`, `blendshapes`, `exists`. | `container` view/`uuid` |
| `networkController.py` | Build/sync the shape graph and expose relationship queries. Thin glue over `logic/network.py`. | — |
| `heatMap.py` | HUD toggle, heat-map blendshape, DGA node network, deformer ordering. | `heat_map_blendshape` |
| `workShapes.py` | Work-shape CRUD, driver connections, mute, weight/mask paint modes, deformer enable/disable. | `deformers_node_states` |
| `shapeBuilder.py` | Commit/add/remove/rename primaries, inbetweens, combos; combo/remap node factory; pose helpers. | `_stored_pose` |
| `weightMapOps.py` | Copy/paste/add/subtract/normalize/soft-selection weight-map operations. | `copied_weight_map_values` |
| `colors.py` | Custom shape color JSON attribute on the container. | — |
| `io.py` | OBJ, blendshape-node, and split-data import/export. | — |
| `lifecycle.py` | `create_new`, `get_editors`, `rename_editor`, shape-editor directories, publishing. | — |
| `split/__init__.py` | Re-exports the split collaborators. | — |
| `split/session.py` | `SplitSession` moved as-is. | split-run session |
| `split/splitMaps.py` | Split-map / split-group configuration, attributes, weights, `build_split_data`. | — |
| `split/splitBake.py` | Split meshes, bake/commit workflow, split-map edit workflow, split IO. | split bake buffers |

### Dependency direction

- `context.py` depends on nothing internal (uses `typing.Protocol` /
  `TYPE_CHECKING`).
- Leaf collaborators (`colors`, `io`, `shapeBuilder`, `weightMapOps`) may
  depend on `context`, `api/blendshape.py`, `api/mayaUtils.py`, `logic/`, and
  `maya.cmds` only.
- `heatMap`, `workShapes`, `networkController` may additionally call other
  collaborators via the context.
- `split/*` may depend on `weightMapOps` and `shapeBuilder` via the context.
- **No collaborator imports `facade.py`.**

---

## 5. The `EditorContext` contract

`context.py` declares exactly what a collaborator may touch on the editor.
This replaces the implicit "everything sees `self`" coupling with an explicit,
documented surface.

```python
# api/editor/context.py (illustrative)
from __future__ import annotations
from typing import Protocol, runtime_checkable

@runtime_checkable
class EditorContext(Protocol):
    # identity / container
    name: str
    container: "Container"
    separator: str
    dga_nodes_supported: bool

    # node wrappers
    blendshape: "Blendshape"
    split_blendshape: "Blendshape"
    work_blendshape: "Blendshape"
    heat_map_blendshape: "Blendshape | None"
    network: "Network"
    skin_cluster: "SkinCluster | None"

    # scene references
    base_mesh: str
    node_network_container: "Container"
    face_ctrl: str

    # collaborators (set by the facade in __init__)
    colors: "ColorsController"
    heat_map: "HeatMapController"
    work_shapes: "WorkShapesController"
    shapes: "ShapeBuilder"
    weights: "WeightMapController"
    network_ctl: "NetworkController"
    split_maps: "SplitMapController"
    split_bake: "SplitBakeController"

    # shared, low-level helpers
    def zero_out(self) -> None: ...
    def get_shape(self, shape_name: str): ...
```

Rules:

- Collaborators accept `context: EditorContext` in `__init__` and store it as
  `self._ctx`.
- If a collaborator needs a method that belongs to another collaborator, it
  calls `self._ctx.<collaborator>.<method>(...)`, keeping ownership clear.
- Any attribute added to the protocol must already be a facade attribute.

---

## 6. Method migration map

Source line numbers refer to the current `api/editor.py`. "→" means the method
moves into the destination module; the facade keeps a delegating wrapper with
the same name and signature.

### `containerView.py` (lines 603–707)

`uuid`, `name`, `editor_base_name`, `exists`, `main_blendshape_name`,
`split_blendshape_name`, `work_blendshape_name`, `heat_map_blendshape_name`,
`split_attr_grp`, `dga_visualizer`, `dga_delta`, `delta_map`, `face_ctrl`,
`heat_map_mesh`, `node_network_container`, `split_map_edit_mesh`,
`split_map_edit_blendshape`, `base_mesh`, `blendshapes`.

> Fix `uuid` (line 606) while moving: it must read the actual container view /
> `Container.uuid`, not the undefined `self.container_view`.

### `colors.py` (lines 3475–3533)

`_add_custom_shapes_color_attribute`, `read_custom_shapes_colors`,
`write_custom_shapes_colors`, `clear_custom_shapes_colors`,
`set_shape_custom_color`, `remove_shape_custom_color`.

### `heatMap.py` (lines 58, 295–573)

- `toggle_hud_display` (also keeps `hud_on` in sync on the facade)
- `display_heat_maps`, `set_heat_map_target`, `clear_heat_map_target`
- `_delete_heat_map_blendshape`, `_disconnect_heat_map_blendshape_target`,
  `_connect_target_to_heat_map_blendshape`
- `_delete_dga_heat_maps_node_network`, `_create_dga_heat_maps_node_network`,
  `_create_delta_heat_map_node`, `_create_heat_map_blendshape`
- `reorder_blendshapes_deformation_history`, `_are_blendshapes_ordered`,
  `get_deformers`
- properties `heat_map_display_state`, `current_heat_map_target`

### `weightMapOps.py` (lines 1237–1420)

Main clipboard ops: `copy_blendshape_weight_map_values`,
`paste_blendshape_weight_map_values_to_shape`,
`convert_soft_selection_to_weight_map`, `normalize_shapes_weight_map_values`.

Work-map wrappers: `copy_work_weight_map_values`,
`paste_work_weight_map_values`, `paste_inverted_work_weight_map_values`,
`add_work_weight_map_values`, `subtract_work_weight_map_values`,
`convert_soft_selection_to_work_weight_map`, `clear_work_weight_map_values`,
`normalize_work_weight_map_values`.

Split edit-map wrappers stay in `splitBake.py` but delegate to the shared
primitives in this module: `copy_edit_split_weight_map_values`,
`copy_split_weight_map_values`, `paste_edit_split_weight_map_values`,
`paste_inverted_edit_split_weight_map_values`,
`paste_multiplied_edit_split_weight_map_values`,
`add_edit_split_weight_map_values`, `subtract_edit_split_weight_map_values`,
`convert_soft_selection_to_edit_split_weight_map`.

### `workShapes.py` (lines 862–1420, 1850–1960, 2845–2896)

`extract_work_shape`, `delete_work_shape`, `delete_work_shapes`,
`add_work_shape`, `duplicate_work_shape`, `rename_work_shape`,
`set_work_shape_editable`, `disconnect_work_shape_drivers`,
`get_work_shape_driver_shapes`, `get_work_shape_driver_nodes`,
`get_shapes_with_connected_work_shapes`, `get_connected_work_shapes`,
`apply_active_work_shapes`, `_create_work_shape_set_driven_key`,
`connect_work_blendshape_weight_to_blendshape_weight`,
`get_work_blendshape_connected_targets_weights`, `get_work_shape_edit_mesh`,
`set_work_target_weight_paint_mode`, `set_work_target_mask_paint_mode`,
`get_work_shape_muted_state`, `set_work_shape_mute_state`,
`sync_up_muted_shapes`, `disable_all_deformers`, `enable_all_deformers`,
`add_shape_to_locked_shapes`, `remove_shape_from_locked_shapes`.

`locked_shapes` stays on the facade (UI reads `editor.locked_shapes`); the
controller mutates it through the context.

### `shapeBuilder.py` (lines 1433–1750, 2535–3058, 3367–3448)

Pose/edit helpers: `set_shape_pose`, `set_primary_shape_value`, `zero_out`,
`_store_current_pose`, `_restore_stored_pose`, `get_shape_editor_panel`.

Commit/add/remove: `commit_shape`, `commit_shapes`,
`_commit_batch_shapes_with_progress_bar`, `add_selected_at_current_pose`,
`add_new_primary_shape`, `add_new_inbetween_shape`, `add_primary_shape`,
`add_inbetween_shape`, `add_combo_shape`, `remove_shapes`,
`rename_primary_shape`, `reset_delta_for_shapes`, `get_shapes_with_zero_delta`.

Mute: `set_shape_mute_state`, `unmute_all_shapes`, `get_muted_shapes`.

Node factory: `create_combo_node`, `create_remap_value_node`,
`update_remap_nodes_values`.

### `networkController.py` (lines 755–860, 1969–2005, 2535–2724, 3078)

`build_network`, `sync_network`, `get_related_shapes_downstream`,
`get_related_shapes_upstream`, `get_related_shapes`, `get_primary_shapes`,
`get_primary_weights`, `get_all_shapes`, `get_shape`,
`get_work_blendshape_weights`, `get_primaries_target_dirs`,
`get_active_primary_weights`, `get_active_state_name`,
`fix_mid_layer_blendshapes_indices_position`.

`build_network` should **push its body into `logic/network.py`** (per its TODO)
and leave only glue here.

### `io.py` (lines 2045–2535)

`import_obj`, `import_objs`, `ingest_shapes_from_blendshape_node`,
`import_blendshape_node`, `import_shapes_from_blendshape_node`,
`export_shapes_as_blendshape_node`, `create_absolute_delta_blendshape`,
`export_blendshape_node`, `export_all_objs`, `export_objs`.

Prefer module-level functions that take explicit arguments (blendshape name,
mesh, directory) so they are testable without a full editor.

### `lifecycle.py` (lines 3096–3366, 3449–3474)

`get_editors`, `add_new_blendshape_to_container`, `create_new`,
`add_shape_editor_directory`, `get_shape_editor_directory_index`,
`remove_shape_editor_directory`, `rename_editor`, `prepare_for_publishing`.

Kept as `@classmethod` / `@staticmethod`; the facade forwards them so
`BlueSteelEditor.create_new(...)` still resolves.

### `split/session.py` (lines 58–167)

`SplitSession` moves unchanged.

### `split/splitMaps.py` (lines 3534–4249, 4461–4550, 4853–4885)

Configuration / attributes: `_sync_up_split_maps_attributes`,
`get_primary_split_group`, `set_primaries_split_group`,
`update_split_map_attributes_from_groups`, `add_primary_split_map_attribute`,
`_add_split_maps_order_attribute`, `_add_split_group_attribute`,
`_ensure_split_shape_name_item_in_groups`, `read_split_groups_attributes`,
`read_split_maps_order_attribute`, `write_split_maps_order_attribute`,
`write_split_groups_attributes`.

Split maps/groups/weights: `get_split_maps`, `create_split_map`,
`delete_split_map`, `rename_split_map`, `rename_split_map_weight`,
`rename_edit_split_map_edit_blendshape_weight`, `create_split_group`,
`rename_split_group`, `remove_split_group`, `add_split_map_to_split_group`,
`remove_split_map_from_split_group`, `add_weight_to_split_map`,
`remove_weight_from_split_map`, `add_weight_to_split_map_edit_blendshape`,
`remove_weight_from_split_map_edit_blendshape`, `get_split_map_areas`,
`get_split_map_weights`, `get_edit_split_map_weights`,
`get_edit_split_map_areas`, `normalize_split_map_weights`,
`normalize_edit_split_map_weights`, `is_split_map_normalized`,
`preview_split_primary_name`, `clear_all_split_maps`,
`get_primaries_split_groups_association`, `build_split_data`.

Data/IO: `export_split_data`, `import_split_data`, `export_split_settings`,
`import_split_settings`, `export_split_maps_weights`,
`import_split_maps_weights`, `connect_shape_to_split_map_blendshapes`.

### `split/splitBake.py` (lines 4249–4460, 4552–4965)

`create_split_maps_meshes`, `split_shapes`, `_split_session`,
`split_and_commit_split_shapes`, `create_split_shapes_editor`,
`create_split_map_edit_mesh`, `switch_visibility_to_split_map_edit_mesh`,
`get_current_edit_split_map`, `cancel_current_edit_split_map`,
`activate_edit_split_weight`, `set_current_edit_split_map_weight_paint_mask`,
`set_current_edit_split_map_weight_paint_weight`,
`set_current_edit_split_map_weight_active`,
`get_current_edit_split_map_weight_values`,
`set_current_edit_split_map_weight_value`, `create_split_map_edit_blendshape`,
`sync_split_map_weights_to_split_map_edit_weights`,
`apply_current_edit_split_map`.

### Not migrated

`compare_shapes_debug` (line 4965) is explicitly marked
`# debug function ... will be removed on release`; leave it on the facade or
delete it during the split.

---

## 7. Shared-state ownership

| State | Current location | New owner | Notes |
|---|---|---|---|
| `container` | `__init__` | facade | passed via context |
| `blendshape`, `split_blendshape`, `work_blendshape` | `__init__` | facade | passed via context |
| `heat_map_blendshape` | `__init__` / heat map | `heatMap` | facade exposes property backed by controller |
| `network` | `build_network` | `networkController` | facade keeps `self.network` for UI compatibility |
| `skin_cluster` | `__init__` | facade | set by `_get_skin_cluster`; keep on facade |
| `hud_on` | HUD toggle | facade | UI reads it |
| `locked_shapes` | property | facade | UI reads/writes it |
| `deformers_node_states` | enable/disable | `workShapes` | only used by deformer toggling |
| `_stored_pose` | store/restore | `shapeBuilder` | pose helpers own it; `io.py` calls store/restore through the context |
| `copied_weight_map_values` | copy/paste | `weightMapOps` | clipboard state |
| `split_blendshape_to_connect`, `split_bake_mesh`, `split_maps_group`, `split_map_blendshapes`, `split_map_blendshapes_weights` | `__init__` | `splitBake` | only used during a split run |
| identifier constants | class body | `api/constants.py` | see §8 phase 8 |

The facade keeps read-accessible properties for anything the UI currently
reads directly (`network`, `work_blendshape`, `blendshape`, `locked_shapes`,
`hud_on`, `split_attr_grp`, `face_ctrl`, `skin_cluster`). A grep of
`ui/editor` shows these are the attributes consumed:

```
work_blendshape (22) · name (15) · blendshape (10) · get_shape (7)
split_attr_grp (3) · get_primary_shapes (3) · face_ctrl (3) · …
```

All of those remain on the facade, either as true attributes or as delegating
properties.

---

## 8. Phased migration plan

Each phase is a standalone, reversible commit. Run the guardrail tests after
every phase.

### Phase 0 — Guardrails

- Add a reflection contract test (`unittest/editorContractUt.py`, matching the existing flat `unittest/` layout) that
  imports `BlueSteelEditor`/`SplitSession` and asserts a frozen set of public
  method/property names still exists. Generate the baseline set from the
  current class before refactoring.
- Add a grep-based test asserting every remaining `import ... api.editor` still
  resolves.

**Acceptance:** contract test passes against the unmodified class.

### Phase 1 — Package conversion (no behavior change)

- Move `editor.py` → `editor/facade.py`; add `editor/__init__.py`
  re-exporting `BlueSteelEditor` and `SplitSession`.
- Run all unittests; confirm import paths unchanged.

**Acceptance:** `from blue_steel.api.editor import BlueSteelEditor` works;
contract test passes.

### Phase 2 — `context.py` + `containerView.py` + `colors.py`

- Introduce the `EditorContext` protocol.
- Extract container/identity properties and custom-color methods (both are
  near-pure reads).
- Fix the `uuid` bug.

**Acceptance:** contract test passes; `editor.uuid` returns the container uuid
in Maya.

### Phase 3 — `heatMap.py`

- Extract heat map, HUD, DGA network, deformer ordering.
- Route `get_deformers` through the heat-map collaborator.

**Acceptance:** heat-map target set/clear and HUD toggle behave as before.

### Phase 4 — `weightMapOps.py` + `workShapes.py`

- Extract clipboard ops, then work-shape lifecycle.
- Move `copied_weight_map_values` and `deformers_node_states`.

**Acceptance:** extract/delete/duplicate work shape, driver connect, copy/paste
and normalize weight maps behave as before.

### Phase 5 — `shapeBuilder.py` + `networkController.py`

- Extract shape building, node factory, pose helpers, mutes.
- Push `build_network`'s body into `logic/network.py`; leave glue.

**Acceptance:** commit/add primary/inbetween/combo, rename, remove, and mute
behave as before; graph queries return identical results.

### Phase 6 — `io.py` + `lifecycle.py`

- Extract import/export and lifecycle/repository methods.
- Keep `create_new` / `rename_editor` as classmethods forwarded by the facade.

**Acceptance:** OBJ and blendshape-node round-trip; `BlueSteelEditor.create_new`,
`get_editors`, `rename_editor`, `prepare_for_publishing` behave as before.

### Phase 7 — `split/` package (largest, done last)

- Move `SplitSession` to `split/session.py`.
- Split config/attributes into `split/splitMaps.py` and the bake/edit workflow
  into `split/splitBake.py`.
- Move split-run state onto `splitBake`.

**Acceptance:** create/apply/edit/delete split maps; run
`create_split_shapes_editor`; import/export split data/settings/weights;
`split_and_commit_split_shapes` produces identical output.

### Phase 8 — Constants + facade slim-down

- Move the ~20 in-class identifiers into `api/constants.py`, adding the
  missing ones (`SPLIT_MAPS_AREA_ORDER_ATTR_STRING_IDENTIFIER`,
  `SPLIT_MAP_EDIT_MESH_ATTR_STRING_IDENTIFIER`,
  `SPLIT_MAP_EDIT_BLENDSHAPE_ATTR_STRING_IDENTIFIER`,
  `SPLIT_MAP_EDIT_CURRENT_ATTR_STRING_IDENTIFIER`,
  `CUSTOM_SHAPES_COLOR_ATTR_STRING_IDENTIFIER`, `SHAPE_NAME_STR`).
  Check for class-attribute reads from the UI first.
- Delete empty sections and add a `facade.py` module docstring documenting the
  delegation map.

**Acceptance:** all contract, logic, and UI unittests pass; manual Maya smoke
of the paths listed per phase.

---

## 9. Backward-compatibility guarantees

- **Import path unchanged:** `blue_steel.api.editor.BlueSteelEditor` and
  `...SplitSession` remain valid.
- **Public call signatures unchanged:** every public method/property keeps its
  name, parameters, defaults, return type, and decorators (`@undoable`,
  `@pause_shape_editor`, `@property`, `@classmethod`, `@staticmethod`).
- **Read-accessible attributes preserved on the facade:** `name`, `container`,
  `blendshape`, `split_blendshape`, `work_blendshape`, `network`,
  `locked_shapes`, `hud_on`, `skin_cluster`, `split_attr_grp`, `face_ctrl`,
  `base_mesh`, `separator`.
- **Undo behavior preserved:** a method that was a single undo step stays a
  single undo step.
- The reflection contract test in Phase 0 is the enforcement mechanism.

---

## 10. Risks and mitigations

| Risk | Mitigation |
|---|---|
| A public method is accidentally dropped. | Reflection contract test generated from the pre-refactor class; diff on every phase. |
| `@undoable` boundary shifts when a method moves. | Decorators travel with the method; verify each decorated method still yields one undo step in Maya. |
| Circular imports between facade and collaborators. | Collaborators depend only on `EditorContext`; add an import-lint check that no file in `editor/` imports `facade`. |
| `networkController` becomes a new god class. | Push graph logic into `logic/network.py`; keep the controller as glue, target < ~300 lines. |
| UI reads an attribute that moved off the facade. | Phase 0 grep inventory of `editor.*` accesses; keep delegating properties. |
| Constants have different values in `constants.py` vs class body. | Diff both sets during Phase 8; pick one canonical value and grep for hard-coded literals. |
| Maya session state lost between collaborators. | §7 assigns exactly one owner per state; facade passes itself as context. |

---

## 11. Open decisions

1. **`EditorContext` style:** `typing.Protocol` (structural, no runtime cost,
   needs a type checker to be useful) vs. an abstract base class (explicit,
   importable, slightly more boilerplate). Recommendation: `Protocol` with
   `runtime_checkable` for tests.
2. **Split module depth:** a `split/` subpackage (recommended, ~1,430 lines) vs.
   two flat `splitMaps.py` / `splitBake.py` files. A subpackage keeps the
   largest cluster isolated and leaves room for a future `splitEdit.py`.
3. **`io.py` shape:** module-level functions (easier to test, recommended) vs.
   a thin controller class matching the other collaborators.
4. **Constants:** fully migrate to `api/constants.py` (recommended) vs. keep
   class attributes as compatibility aliases.
5. **`compare_shapes_debug`:** delete during Phase 7 (it is marked for removal)
   vs. keep on the facade.
