# Blue Steel — Copilot Instructions

These instructions describe the coding style and conventions of this repository.
All generated code must match the existing code's style and readability.

## Project context

- This is a **Maya Python plugin** for blendshape authoring (Blue Steel).
- Code runs inside Maya's embedded Python (Python 3.x), using `maya.cmds`, `maya.mel`,
  `maya.OpenMaya` (`om`), `maya.api.OpenMaya` (`om2`), `numpy`, and PySide2/PySide6.
- Core API layer: `releases/maya/BlueSteel/scripts/blue_steel/api/` — class-based
  wrappers around Maya nodes (`Blendshape`, `Weight`, `Container`, `SkinCluster`,
  `TargetDirectory`, `BlueSteelEditor`).
- Logic layer: `releases/maya/BlueSteel/scripts/blue_steel/logic/` — pure-Python domain
  objects (`Shape`, `ShapeList`, `Network`, `SplitMap`). Keep `maya` imports out of the
  logic layer; Maya access belongs in the `api/` layer.
- The package defines `env` globals (`VERSION`, `ICONS_PATH`, `SEPARATOR`, `MAYA_VERSION`,
  `DGA_NODES_SUPPORTED`) — import and reuse them instead of hardcoding.

## Imports and file header

- Import order: `from __future__ import annotations`, then stdlib (`os`, `time`,
  `json`), then third-party (`numpy as np`), then Maya (`from maya import cmds, mel`,
  `from maya import OpenMaya as om`, `from maya.api import OpenMaya as om2`), then
  local package imports (`from . import mayaUtils`, `from ..logic.shape import Shape`).
- One symbol group per import line; avoid wildcard imports.
- Keep the PySide2/PySide6 compatibility `try/except ImportError` shim in UI modules.

## Naming and layout

- `snake_case` for functions, methods, variables; `PascalCase` for classes;
  `UPPER_SNAKE_CASE` for module and class constants.
- Names are descriptive even when long — `get_target_dir_child_target_dirs` is
  preferred over abbreviations like `get_tdir_children`.
- Node/string identifiers are declared as class constants and referenced via those
  constants — never scatter raw attribute/node name strings through the code:
  `MAIN_BLENDSHAPE_STRING_IDENTIFIER = "mainBlendShape"`.
- Module-level feature/debug flags live at the top of the file (`VERBOSE`, `TIMED`)
  and gate all diagnostics/timing output.
- Group class methods by topic with banner comments:
  ```python
  # -----------------------------
  # Weights methods
  # -----------------------------
  ```
  Common groups: Properties, Creation methods, Weights methods, Target methods,
  Export / Import methods, Shapes management.
- Use `from __future__ import annotations` at the top of modules that need it.

## Docstrings (required for every public method)

Follow this exact style — summary line, then `Parameters:`, `Returns:`, and a
**mandatory** doctest `Example:` block:

```python
def get_weights(self) -> list:
    """
    Returns a list of weights in the blendShape node.
    Each weight is represented as a Weight object with a name and an ID.
    Returns:
        list: A list of Weight objects.
    Example:
        >>> blendshape = Blendshape("myBlendshape")
        >>> weights = blendshape.get_weights()
        >>> for weight in weights:
        ...     print(f"Weight Name: {weight.name}, Weight ID: {weight.id}")
        Weight Name: Smile, Weight ID: 0
    """
```

- One short imperative summary line first ("Returns...", "Sets...", "Adds...").
- A second sentence may clarify non-obvious behavior (as above).
- Parameters listed as `name (type): description` indented under `Parameters:`.
- `Returns:` gives `type:` then description; mention `None` when it can be returned.
- **Every public method must include an `Example:` doctest block** — no exceptions
  for "trivial" methods. Only internal `_private` helpers may skip it.
- Examples must be realistic and self-contained: create the object first
  (`>>> blendshape = Blendshape.create("myBlendshape", "pCube1")`), show the call,
  and show the expected printed output ("Smile", "pCube1", "[5500, 6000]").
- Examples use the canonical fixture names from the codebase: `myBlendshape`,
  `pCube1`, weight names like `Smile` / `Frown` / `Blink`.

## Readability rules

- One statement per line; no semicolons or comma-joined side effects.
- Keep lines under ~100 characters; break long calls and f-strings across lines,
  matching the existing wrapping style (arguments indented one level, closing
  paren on its own indentation level).
- Blank line between logical steps inside a method; two blank lines between
  top-level definitions; one blank line between methods.
- Prefer early-exit guard clauses at the top of the method so the happy path
  stays at the left margin.
- Comments explain *why*, not *what*; put them on their own line above the code
  they describe (`# reversing the list to have 6000 first`).
- Extract repeated expressions into a well-named local variable instead of
  repeating a long call (e.g. `weight_id = weight.id`).
- Avoid clever one-liners; a simple `for` loop beats a dense comprehension when
  the body is more than one short expression.

## Error handling

- Use **guard clauses with early return/raise** — no deep nesting.
- Low-level API wrappers (e.g. `blendshape.py`) **raise** `ValueError` or
  `RuntimeError` with descriptive, context-rich f-string messages:
  ```python
  if not self.base:
      raise ValueError(f"Blendshape node '{self.name}'"
                       " has no base mesh connected.")
  ```
- Editor/UI-level methods (e.g. `editor.py`) **do not crash the session** — print a
  warning and return instead:
  ```python
  if weight is None:
      print(f"Warning: Weight '{shape_name}' not found in blendshape '{self.name}'.")
      return
  ```
- Always validate `cmds.objExists(...)` before operating on a node by name.

## Undoability rules (critical)

- Any **user-facing operation that mutates the scene** is decorated with `@undoable`
  (from `api.mayaUtils`). Heavy batch operations also use `@pause_shape_editor`.
- Prefer `cmds.setAttr` / `cmds.*` for writes so they stay undoable.
- Raw Maya API writes (`MPlug.setMObject`, etc.) are **not undoable**. When a fast
  API path is offered, expose it behind `use_api: bool = False` and include the
  warning banner in the docstring:
  ```python
  """
  Sets the points for the specified weight in the blendshape node.
  ************************ WARNING *******************************
          THIS METHOD IS NOT UNDOABLE IF use_api IS True
  ****************************************************************
  ...
  """
  ```
- Use `om2` (`maya.api.OpenMaya`) for fast read-only traversal (plugs, arrays); fall
  back to `om` (API 1.0) only where legacy data types require it, with a comment
  explaining why.

## Maya-specific conventions

- Blendshape internals: full targets live at target item **6000**, inbetweens in
  **5000–6000** (`value = 5000 + weight * 1000`). Respect these constants.
- Weights are represented by the `Weight` class (a `str` subclass carrying `.id`,
  `.target_items`, `.blend_shape`). Look up weights via `get_weight_by_name` /
  `get_weight_by_id` — never rebuild weight lists by hand.
- Access blendshape internals through the `get_target_*_plug` helpers and the
  `INPUT_TARGET` string template instead of hand-building attribute paths.
- All vertex/delta data is `numpy` — deltas are `(N, 3)` arrays. Use the existing
  `mayaUtils` helpers (`get_mesh_raw_points`, `set_mesh_raw_points`,
  `numpy_to_m_points`, `m_points_to_numpy`) rather than reimplementing conversions.
- Comment Maya quirks with the *reason*, e.g. `# reversing the list to have 6000 first`,
  or why a `cmds.evalDeferred` is needed after sourcing a MEL script.
- Batch operations over shapes show a progress bar and always end it in `finally`:
  ```python
  gMainProgressBar = mel.eval('$tmp = $gMainProgressBar')
  cmds.progressBar(gMainProgressBar, edit=True, beginProgress=True,
                   isInterruptable=True, status=..., maxValue=total)
  try:
      ...
  finally:
      cmds.progressBar(gMainProgressBar, edit=True, endProgress=True)
  ```
- UI code must support both Qt bindings via the compatibility shim:
  ```python
  try:
      from PySide2 import QtWidgets
      from shiboken2 import wrapInstance
  except ImportError:
      from PySide6 import QtWidgets
      from shiboken6 import wrapInstance
  ```

## General Python style

- Prefer **f-strings** in new code (older `.format()` call sites may remain untouched).
- **Every `def` declaration must annotate its return type with `->`** — including
  `-> None` for methods that return nothing and `-> 'Blendshape'` (quoted) for
  self-class returns in `@classmethod` factories. Parameter types are annotated
  where they add clarity (`def get_weight_by_id(self, weight_id: int) -> Weight or None:`),
  but don't force full typing on every local variable.
- Properties wrap cheap `cmds.getAttr` lookups and return `None` when data is missing
  rather than raising.
- Diagnostics use `print(f"...")` and are gated behind `VERBOSE` / `TIMED` flags.
- Small static/class helpers belong on the class (`@staticmethod`, `@classmethod`)
  when they operate on the class's own node types (e.g. `Blendshape.create`).
- Don't add features beyond what was asked; match the surrounding code's level of
  abstraction and verbosity.
