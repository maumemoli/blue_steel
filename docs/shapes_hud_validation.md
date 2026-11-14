# Shapes HUD: GUI validation and remaining limitations

## Silent disappearance reproduction

Tested in disposable **Maya 2024.2.4** and **Maya 2026.3** GUI processes, using
isolated preference directories under `test_not_git/hud_probe_<version>`.
The artist's running Maya session was not used.

The original plugin draws correctly in an unfiltered viewport. Enabling Isolate
Select after drawing removes the HUD without an exception; toggling the HUD
again while isolated does not bring it back. Disabling Locators also filters it
out. A valid DAG node and `visibility=True` are therefore not sufficient
visibility diagnostics.

The original custom display filter was never registered:
`maya.api.OpenMaya.MFnPlugin` has no `registerDisplayFilter` method, and that
exception was swallowed.

## Fix in plugin version 1.1

- Register the dedicated filter with `cmds.pluginDisplayFilter`.
- Return `False` from `MPxLocatorNode.excludeAsLocator` so scene locator
  visibility does not control the screen-space HUD.
- Include only the transient HUD shape in active isolate sets. Preserve the
  user's geometry membership and selection. Update the panel immediately.
- While the HUD is active, a scoped timer handles later isolation changes and
  updates native HUD conflicts as the displayed list changes. Stop on hide.
- Check the plugin version explicitly. Never flush undo history or force-unload
  an artist's active draw override automatically to install a newer build.
  Restart Maya to load version 1.1.

## Independent frame sizing in plugin version 1.2

- Corner handles resize the area in both axes without changing font size.
  Dragging inside moves the frame; the wheel changes only the font.
- Frame width/height are normalized viewport fractions, saved separately from
  position and font scale. Existing settings default to a 40% x 50% frame.
- Text fills columns within the intersection of the frame and viewport. Long
  labels are elided (retaining the weight value when possible). When shapes
  are omitted, the last available entry is exactly `...`, with no extra count.
- Text uses measured Arial pixel-font metrics, matching the VP2 draw font.
  The background, outline, query rectangle and native HUD conflict region all
  describe the fixed area, regardless of active-shape count.
- Commit/cancel/reset include frame dimensions. Font-aware minimum frame size
  and wheel limits keep room for the overflow cue without auto-shrinking text.
- Restart Maya to load version 1.2's new node attributes safely.

## Column overlap correction in plugin version 1.3

Reproduced using `D:/work/Caesar/scenes/newSplitMaps.mb`, with 65 active weights
on `CaesarSkin_mainBlendshape`. The source scene was opened without executing
script nodes and was never saved or overwritten.

The layout measured normal Arial, but VP2's default font style produced different
advances: one long combo label measured 682 pixels but rendered approximately
738 pixels wide at font size 19. Explicit normal weight, normal incline and
unstretched text restored agreement. VP2 also does not apply Qt's pair kerning;
width calculation now disables it and conservatively accumulates glyph advances.
The fix changes font measurement/style, not the user's frame or font-size controls.

GUI validation in Maya 2024 and 2026 confirmed zero HUD pixels in inter-column
gaps or outside the frame for the supplied scene, using default/wide frames and
font scales 0.65, 1.0 and 1.4. Source-scene playblasts at 640x360 and 1280x720 also
passed the column-gap checks. New regression coverage verifies the explicit draw
style, unkerned widths, and rendered gutters for representative long combo names.
**32 tests passed in each Maya GUI version.** Local artifacts are under
`test_not_git/hud_columns_2024` and `test_not_git/hud_columns_2026`.
Restart Maya to load plugin version 1.3 safely.

## Weight ordering

Both back-ends list the non-zero weights **highest value first**, so the shapes
doing the most work are always the visible ones and the overflow `...` marker
only ever hides the lowest values:

- The plugin sorts `(value, name)` pairs collected from the `weight` array in
  `bsShapesHUD._collect_lines`; the native fallback sorts the same pairs in
  `blendshapeHUD.collect_active_weights` (shared by `refresh_hud`).
- Signed values are compared (`1.0, 0.5, -0.3`), not magnitudes, and the sort is
  stable, so equal values keep their previous order (weight index for the
  plugin, `listAttr` order for the native blocks).
- Zero weights and, unless combos are listed, `combinationShape`-driven weights
  stay filtered out before sorting.
- Plugin version stays 1.3: the change is content-only (no new node attributes),
  so an already loaded 1.3 keeps drawing until Maya is restarted.

`TestWeightOrdering` covers both back-ends with weight indices that do not match
the value order, including a negative value, a tie and a zero weight.

## Checks performed

`releases/maya/BlueSteel/unittest/shapesHUDUt.py` contains 34 tests, including GUI
color-buffer pixel assertions rather than only testing whether a node exists.
**Run these tests only in disposable scenes: their setup creates new scenes.**

GUI checks passed in both versions:

- HUD stays visible with scene locators hidden.
- Dedicated HUD filter can still explicitly hide it.
- HUD works in an isolated viewport and after repeated off/on toggles.
- Enabling isolation after showing the HUD is handled.
- Native HUDs in overlapping sections hide and restore, without enabling HUDs
  that were already hidden.
- Moving from the top-left to the bottom-right changes the conflicting HUD set.
- VP2 playblast PNGs at 640x360 and 1280x720 contain the gold HUD title while
  Locators are disabled and Isolate Select is enabled.
- Normal drawing, idling and retoggling work in a clean scene. Full Blue Steel
  editor and transform-window smoke checks also passed in Maya 2026.
- All four resize corners preserve font size and the opposite anchor. Moving,
  wheel resizing, commit, cancel, reset and frame persistence are exercised
  through the production gizmo/API. A simulated 2x-DPI test checks physical
  viewport queries and logical-coordinate handle placement.
- Fixed-frame layout tests cover exact fits, extra shapes, multiple columns,
  empty lists, long labels, tiny frames and partly offscreen rectangles.
- GUI pixel checks verify rendered body text and the final ellipsis stay inside
  the frame. Additional 640x360 and 1280x720 playblasts were checked with a
  distinctive magenta body color to exclude Maya's RGB axis ornaments: both
  resolutions contain the ellipsis glyphs and have zero HUD pixels outside
  the configured frame, in both Maya versions.

The version 1.2 run passed **29 tests in each Maya GUI version**. Local logs and
playblasts are under `test_not_git/hud_sizing_2024` and
`test_not_git/hud_sizing_2026`; earlier 1.1 checks used `hud_probe_<version>`.
These are diagnostic artifacts, not release files. Maya 2022/2023/2025 and
physical multi-monitor DPI transitions were not tested.

## Remaining save limitation

`doNotWrite` prevents the transient shape/transform from being written, but
saving with the HUD active still writes a `requires bsShapesHUD` declaration.
Setting `pluginInfo(writeRequires=False)` did not remove it in the GUI test.
This part of the original validation checklist remains open.

**Workaround: turn the HUD off before saving.** Saving after removing the HUD
was verified not to include its plugin dependency. A save-lifecycle solution
needs separate implementation and tests; no speculative save callbacks have
been installed in the artist's session.
