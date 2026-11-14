"""HUD lifecycle for the Blue Steel shapes HUD.

Two back-ends are supported:

* ``bsShapesHUD`` plugin (preferred): a Viewport 2.0 drawn HUD that can be
  freely offset/scaled and shows up in playblasts.
* :mod:`blendshapeHUD` (fallback): native ``cmds.headsUpDisplay`` blocks.

This module also manages the "real estate": while the shapes HUD is on, the
native Maya HUDs located in the sections it covers are hidden temporarily and
restored afterwards. Only the HUDs that *we* hid are restored, and the record
is mirrored in an optionVar so it survives a crash / editor re-instantiation.
"""

from __future__ import annotations

from typing import Iterable, List, Optional, Sequence, Set, Tuple

from maya import cmds

from . import blendshapeHUD

PLUGIN_NAME = "bsShapesHUD"
PLUGIN_VERSION = "1.3"
NODE_TYPE = "bsShapesHUD"
QUERY_COMMAND = "bsShapesHUDQuery"
DISPLAY_FILTER_NAME = "bsShapesHUD"
HUD_TRANSFORM_NAME = "blueSteelShapesHUD"

OV_OFFSET_X = "blueSteel_hudOffsetX"
OV_OFFSET_Y = "blueSteel_hudOffsetY"
OV_SCALE = "blueSteel_hudScale"
OV_FRAME_WIDTH = "blueSteel_hudFrameWidth"
OV_FRAME_HEIGHT = "blueSteel_hudFrameHeight"
OV_HIDDEN_HUDS = "blueSteel_hiddenHUDs"

DEFAULT_OFFSET_X = 0.01
DEFAULT_OFFSET_Y = 0.02
DEFAULT_SCALE = 1.0
DEFAULT_FRAME_WIDTH = 0.4
DEFAULT_FRAME_HEIGHT = 0.5

# Maya HUD grid: sections 0-4 across the top, 5-9 across the bottom.
HUD_COLUMNS = 5
NATIVE_FALLBACK_SECTIONS = frozenset(range(0, 5))

_hidden_huds: List[str] = []
_viewport_watch_timer = None
_viewport_watch_error = None


# ---------------------------------------------------------------------------
# Plugin / node helpers
# ---------------------------------------------------------------------------
def ensure_plugin() -> bool:
    """Load the ``bsShapesHUD`` plugin if needed.

    Returns:
        bool: True if the plugin is available.
    """
    try:
        if not cmds.pluginInfo(PLUGIN_NAME, query=True, loaded=True):
            cmds.loadPlugin(PLUGIN_NAME, quiet=True)
        loaded = bool(cmds.pluginInfo(PLUGIN_NAME, query=True, loaded=True))
    except RuntimeError as exc:
        cmds.warning(f"Could not load {PLUGIN_NAME} plugin, using native HUD. Error: {exc}")
        return False
    if loaded and not _plugin_is_current():
        # Never clear the user's undo history or force-unload an active draw
        # override just to upgrade it. A restart safely loads the new build.
        raise RuntimeError("An older bsShapesHUD plugin is loaded. Restart Maya "
                           "to load the HUD column-spacing fix (version 1.3).")
    return loaded


def _plugin_is_current() -> bool:
    """Check the registered plugin version, not just command availability."""
    return cmds.pluginInfo(PLUGIN_NAME, query=True, version=True) == PLUGIN_VERSION


def get_hud_shape() -> Optional[str]:
    """Return the existing plugin HUD shape, if any."""
    try:
        if not cmds.pluginInfo(PLUGIN_NAME, query=True, loaded=True):
            return None
    except RuntimeError:
        return None
    shapes = cmds.ls(type=NODE_TYPE, long=True) or []
    return shapes[0] if shapes else None


def plugin_hud_exists() -> bool:
    """Return True if a plugin HUD node exists."""
    return get_hud_shape() is not None


def hud_exists(blend_shape: str) -> bool:
    """Return True if any shapes HUD (plugin or native) is displayed."""
    return plugin_hud_exists() or bool(blendshapeHUD.hud_exists(blend_shape))


def _set_do_not_write(node: str) -> None:
    """Flag a node so it is never written into the scene file."""
    try:
        import maya.api.OpenMaya as om
        sel = om.MSelectionList()
        sel.add(node)
        om.MFnDependencyNode(sel.getDependNode(0)).setDoNotWrite(True)
    except Exception:
        pass


def _get_plug(node: str, attr: str):
    import maya.api.OpenMaya as om
    sel = om.MSelectionList()
    sel.add(f"{node}.{attr}")
    return sel.getPlug(0)


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
def _ov_float(name: str, default: float) -> float:
    if cmds.optionVar(exists=name):
        try:
            return float(cmds.optionVar(query=name))
        except (TypeError, ValueError):
            pass
    return default


def load_settings() -> Tuple[float, float, float]:
    """Return the saved (offset_x, offset_y, font_scale); frame size is separate."""
    return (_ov_float(OV_OFFSET_X, DEFAULT_OFFSET_X),
            _ov_float(OV_OFFSET_Y, DEFAULT_OFFSET_Y),
            _ov_float(OV_SCALE, DEFAULT_SCALE))


def save_settings(offset_x: float, offset_y: float, scale: float) -> None:
    """Persist HUD position and font scale without changing frame dimensions."""
    cmds.optionVar(floatValue=(OV_OFFSET_X, float(offset_x)))
    cmds.optionVar(floatValue=(OV_OFFSET_Y, float(offset_y)))
    cmds.optionVar(floatValue=(OV_SCALE, float(scale)))


def load_frame_size() -> Tuple[float, float]:
    """Saved frame width/height as viewport fractions; defaults are 40% x 50%."""
    return (max(0.001, min(1.0, _ov_float(OV_FRAME_WIDTH, DEFAULT_FRAME_WIDTH))),
            max(0.001, min(1.0, _ov_float(OV_FRAME_HEIGHT, DEFAULT_FRAME_HEIGHT))))


def save_frame_size(width: float, height: float) -> None:
    """Persist frame dimensions independently of the existing position/font settings."""
    cmds.optionVar(floatValue=(OV_FRAME_WIDTH, max(0.001, min(1.0, width))))
    cmds.optionVar(floatValue=(OV_FRAME_HEIGHT, max(0.001, min(1.0, height))))


def get_frame_size() -> Optional[Tuple[float, float]]:
    """Return current frame width/height as viewport fractions, if a HUD exists."""
    shape = get_hud_shape()
    if shape is None:
        return None
    return (cmds.getAttr(f"{shape}.frameWidth"), cmds.getAttr(f"{shape}.frameHeight"))


def set_frame_size(width: float, height: float, save: bool = False,
                   refresh: bool = True) -> None:
    """Resize the HUD area without touching font size or the undo queue."""
    shape = get_hud_shape()
    if shape is None:
        return
    width, height = max(0.001, min(1.0, width)), max(0.001, min(1.0, height))
    _get_plug(shape, "frameWidth").setFloat(width)
    _get_plug(shape, "frameHeight").setFloat(height)
    if save:
        save_frame_size(width, height)
    if refresh:
        refresh_viewports()


def get_transform() -> Optional[Tuple[float, float, float]]:
    """Return the current (offset_x, offset_y, scale) of the plugin HUD."""
    shape = get_hud_shape()
    if shape is None:
        return None
    return (cmds.getAttr(f"{shape}.offsetX"),
            cmds.getAttr(f"{shape}.offsetY"),
            cmds.getAttr(f"{shape}.hudScale"))


def set_transform(offset_x: float, offset_y: float, scale: float,
                  save: bool = False, refresh: bool = True) -> None:
    """Set the HUD placement without touching the undo queue.

    Parameters:
        offset_x: Normalized left position.
        offset_y: Normalized top position.
        scale: Relative font size (does not resize the frame).
        save: Also persist into optionVars.
        refresh: Schedule a viewport refresh.
    """
    shape = get_hud_shape()
    if shape is None:
        return
    _get_plug(shape, "offsetX").setFloat(float(offset_x))
    _get_plug(shape, "offsetY").setFloat(float(offset_y))
    _get_plug(shape, "hudScale").setFloat(max(0.05, float(scale)))
    if save:
        save_settings(offset_x, offset_y, scale)
    if refresh:
        refresh_viewports()


def reset_transform(save: bool = True) -> None:
    """Reset position, font size and frame dimensions to their defaults."""
    set_transform(DEFAULT_OFFSET_X, DEFAULT_OFFSET_Y, DEFAULT_SCALE, save=save, refresh=False)
    set_frame_size(DEFAULT_FRAME_WIDTH, DEFAULT_FRAME_HEIGHT, save=save)


def set_show_frame(state: bool) -> None:
    """Toggle the outline drawn around the HUD (used while transforming)."""
    shape = get_hud_shape()
    if shape is None:
        return
    _get_plug(shape, "showFrame").setBool(bool(state))
    refresh_viewports()


def refresh_viewports() -> None:
    """Schedule a refresh of the 3D views."""
    try:
        import maya.api.OpenMayaUI as omui
        omui.M3dView.scheduleRefreshAllViews()
    except Exception:
        cmds.refresh(force=True)


def _model_panels() -> List[str]:
    return [p for p in (cmds.getPanel(type="modelPanel") or [])]


def ensure_panels_show_hud() -> None:
    """Make sure the plugin display filter is on in every model panel.

    Registering a plugin display filter does not always turn it on in panels
    that already exist, in which case the HUD node is silently filtered out.
    """
    for panel in _model_panels():
        try:
            editor = cmds.modelPanel(panel, query=True, modelEditor=True)
            cmds.modelEditor(editor, edit=True, pluginObjects=(DISPLAY_FILTER_NAME, True))
        except RuntimeError:
            pass


def _sync_isolate_membership() -> None:
    """Include only our temporary HUD in each active isolate set.

    This leaves the user's isolated geometry and selection unchanged. API set
    edits avoid filling the undo queue with periodic housekeeping. Deleting the
    temporary HUD removes its membership automatically.
    """
    import maya.api.OpenMaya as om
    shape = get_hud_shape()
    if shape is None:
        return
    selection = om.MSelectionList()
    selection.add(shape)
    dag = selection.getDagPath(0)
    for panel in _model_panels():
        if not cmds.isolateSelect(panel, query=True, state=True):
            continue
        set_name = cmds.isolateSelect(panel, query=True, viewObjects=True)
        if not set_name:
            continue
        selection = om.MSelectionList()
        selection.add(set_name)
        isolate_set = om.MFnSet(selection.getDependNode(0))
        member = (dag, om.MObject.kNullObj)
        if not isolate_set.isMember(member):
            isolate_set.addMember(member)
            # Rebuild the panel's filter now, rather than one idle cycle later.
            cmds.isolateSelect(panel, update=True)


def _watch_viewports() -> None:
    """Handle isolation changes and weight-list growth after HUD creation."""
    global _viewport_watch_error
    try:
        if not plugin_hud_exists():
            _stop_viewport_watch()
            restore_hidden_huds()
            return
        _sync_isolate_membership()
        update_conflicts()
        _viewport_watch_error = None
    except RuntimeError as exc:
        if str(exc) != _viewport_watch_error:
            _viewport_watch_error = str(exc)
            cmds.warning(f"Blue Steel HUD viewport update: {exc}")


def _start_viewport_watch() -> None:
    global _viewport_watch_timer
    if cmds.about(batch=True):
        return
    if _viewport_watch_timer is None:
        if int(cmds.about(version=True)) >= 2025:
            from PySide6.QtCore import QTimer
        else:
            from PySide2.QtCore import QTimer
        _viewport_watch_timer = QTimer()
        _viewport_watch_timer.setInterval(250)
        _viewport_watch_timer.timeout.connect(_watch_viewports)
    _viewport_watch_timer.start()


def _stop_viewport_watch() -> None:
    if _viewport_watch_timer is not None:
        _viewport_watch_timer.stop()


def reload_plugin() -> bool:
    """Unload and reload the plugin (picks up code changes).

    Returns:
        bool: True if the plugin is loaded afterwards.
    """
    hide()
    try:
        if cmds.pluginInfo(PLUGIN_NAME, query=True, loaded=True):
            cmds.unloadPlugin(PLUGIN_NAME)
    except RuntimeError as exc:
        cmds.warning(f"Could not unload {PLUGIN_NAME}; restart Maya instead: {exc}")
        return False
    return ensure_plugin()


def diagnose() -> str:
    """Return (and print) a report explaining why the HUD may not be visible."""
    lines = []
    try:
        loaded = cmds.pluginInfo(PLUGIN_NAME, query=True, loaded=True)
    except RuntimeError:
        loaded = False
    lines.append(f"plugin loaded: {loaded}")
    if loaded:
        lines.append(f"plugin path: {cmds.pluginInfo(PLUGIN_NAME, query=True, path=True)}")
        lines.append(f"plugin version: {cmds.pluginInfo(PLUGIN_NAME, query=True, version=True)}")
        lines.append(f"HUD filter registered: {cmds.pluginDisplayFilter(DISPLAY_FILTER_NAME, exists=True)}")
        try:
            lines.append(f"draw stats: {cmds.bsShapesHUDQuery(stats=True)}")
        except Exception as exc:
            lines.append(f"draw stats: unavailable ({exc}) - reload the plugin: hudManager.reload_plugin()")
    shape = get_hud_shape()
    lines.append(f"hud node: {shape}")
    if shape:
        src = cmds.listConnections(f"{shape}.blendShape", source=True, destination=False) or []
        lines.append(f"connected blendShape: {src}")
        lines.append("offset/font scale: {0}".format(get_transform()))
        if _plugin_is_current():
            lines.append("frame size (viewport fractions): {0}".format(get_frame_size()))
        lines.append(f"visibility: {cmds.getAttr(shape + '.visibility')}")
    lines.append(f"native HUD master: {blendshapeHUD.HUD_MASTER_NAME or None}")
    lines.append(f"hidden Maya HUDs: {_hidden_huds}")
    visible = set(cmds.getPanel(visiblePanels=True) or [])
    for panel in _model_panels():
        if panel not in visible:
            continue
        editor = cmds.modelPanel(panel, query=True, modelEditor=True)
        info = [f"panel {panel}:",
                f"renderer={cmds.modelEditor(editor, query=True, rendererName=True)}",
                f"locators={cmds.modelEditor(editor, query=True, locators=True)}",
                f"pluginShapes={cmds.modelEditor(editor, query=True, pluginShapes=True)}"]
        try:
            info.append("hudFilter={0}".format(
                cmds.modelEditor(editor, query=True, queryPluginObjects=DISPLAY_FILTER_NAME)))
        except Exception:
            pass
        try:
            isolated = cmds.isolateSelect(panel, query=True, state=True)
            info.append(f"isolate={isolated}")
            if isolated and shape:
                set_name = cmds.isolateSelect(panel, query=True, viewObjects=True)
                included = bool(set_name and cmds.sets(shape, isMember=set_name))
                info.append(f"HUD_in_isolate_set={included}")
        except RuntimeError as exc:
            info.append(f"isolate_query_error={exc}")
        lines.append(" ".join(info))
    report = "\n".join(lines)
    print(report)
    return report


# ---------------------------------------------------------------------------
# Create / delete
# ---------------------------------------------------------------------------
def create(blend_shape: str, list_combos: bool = True) -> Optional[str]:
    """Create the plugin HUD for a blendShape.

    Parameters:
        blend_shape: The blendShape node name.
        list_combos: Whether combination-driven weights are listed.

    Returns:
        str | None: The HUD shape, or None if the plugin is unavailable.
    """
    if not ensure_plugin():
        return None
    delete()
    selection = cmds.ls(selection=True)
    transform = cmds.createNode("transform", name=HUD_TRANSFORM_NAME, skipSelect=True)
    shape = cmds.createNode(NODE_TYPE, name=f"{HUD_TRANSFORM_NAME}Shape",
                            parent=transform, skipSelect=True)
    for node in (transform, shape):
        _set_do_not_write(node)
        cmds.setAttr(f"{node}.hiddenInOutliner", True)
    # Not selectable from the viewport.
    cmds.setAttr(f"{shape}.overrideEnabled", True)
    cmds.setAttr(f"{shape}.overrideDisplayType", 2)
    cmds.connectAttr(f"{blend_shape}.message", f"{shape}.blendShape", force=True)
    cmds.setAttr(f"{shape}.listCombos", bool(list_combos))
    offset_x, offset_y, scale = load_settings()
    cmds.setAttr(f"{shape}.offsetX", offset_x)
    cmds.setAttr(f"{shape}.offsetY", offset_y)
    cmds.setAttr(f"{shape}.hudScale", scale)
    frame_width, frame_height = load_frame_size()
    cmds.setAttr(f"{shape}.frameWidth", frame_width)
    cmds.setAttr(f"{shape}.frameHeight", frame_height)
    for attr in ("translate", "rotate", "scale"):
        cmds.setAttr(f"{transform}.{attr}", lock=True)
    if selection:
        cmds.select(selection, replace=True)
    else:
        cmds.select(clear=True)
    return cmds.ls(shape, long=True)[0]


def delete() -> None:
    """Delete every plugin HUD node."""
    shape = get_hud_shape()
    while shape is not None:
        parent = (cmds.listRelatives(shape, parent=True, fullPath=True) or [None])[0]
        cmds.delete(parent or shape)
        shape = get_hud_shape()


# ---------------------------------------------------------------------------
# Real estate: hide/restore conflicting native HUDs
# ---------------------------------------------------------------------------
def sections_overlapping(rect: Sequence[float], vp_w: float, vp_h: float) -> Set[int]:
    """Map a HUD rectangle onto Maya's HUD section grid.

    Parameters:
        rect: (x, y, width, height), pixels, top-left origin.
        vp_w: Viewport width.
        vp_h: Viewport height.

    Returns:
        set[int]: Sections 0-9 overlapped by the rectangle.
    """
    if vp_w <= 0 or vp_h <= 0:
        return set()
    x, y, w, h = rect
    left = max(0.0, x)
    right = min(float(vp_w), x + w)
    top = max(0.0, y)
    bottom = min(float(vp_h), y + h)
    if right <= left or bottom <= top:
        return set()
    col_w = vp_w / float(HUD_COLUMNS)
    first_col = int(min(HUD_COLUMNS - 1, left // col_w))
    last_col = int(min(HUD_COLUMNS - 1, (right - 1e-6) // col_w))
    half = vp_h / 2.0
    rows = []
    if top < half:
        rows.append(0)
    if bottom > half:
        rows.append(1)
    return {row * HUD_COLUMNS + col for row in rows for col in range(first_col, last_col + 1)}


def _active_viewport_size() -> Tuple[int, int]:
    try:
        import maya.api.OpenMayaUI as omui
        view = omui.M3dView.active3dView()
        return view.portWidth(), view.portHeight()
    except Exception:
        return 1920, 1080


def query_rect(vp_w: float, vp_h: float) -> Optional[Tuple[float, float, float, float]]:
    """Return the fixed frame for a viewport size, not the text's bounding box."""
    shape = get_hud_shape()
    if shape is None:
        return None
    try:
        result = cmds.bsShapesHUDQuery(shape, w=float(vp_w), h=float(vp_h))
    except Exception:
        return None
    if not result or len(result) < 4:
        return None
    return tuple(float(v) for v in result[:4])


def covered_sections() -> Set[int]:
    """Return the sections covered by the current shapes HUD."""
    if plugin_hud_exists():
        vp_w, vp_h = _active_viewport_size()
        rect = query_rect(vp_w, vp_h)
        if rect is None:
            return set()
        return sections_overlapping(rect, vp_w, vp_h)
    if blendshapeHUD.HUD_MASTER_NAME and cmds.headsUpDisplay(
            blendshapeHUD.HUD_MASTER_NAME, query=True, exists=True):
        return set(NATIVE_FALLBACK_SECTIONS)
    return set()


def _is_own_hud(name: str) -> bool:
    return name.startswith(blendshapeHUD.HUD_BLENDSHAPE_WEIGHTS_PREFIX)


def _save_hidden_record() -> None:
    if cmds.optionVar(exists=OV_HIDDEN_HUDS):
        cmds.optionVar(remove=OV_HIDDEN_HUDS)
    if _hidden_huds:
        cmds.optionVar(stringValue=(OV_HIDDEN_HUDS, _hidden_huds[0]))
        for name in _hidden_huds[1:]:
            cmds.optionVar(stringValueAppend=(OV_HIDDEN_HUDS, name))


def _load_hidden_record() -> List[str]:
    if not cmds.optionVar(exists=OV_HIDDEN_HUDS):
        return []
    value = cmds.optionVar(query=OV_HIDDEN_HUDS)
    if isinstance(value, str):
        return [value] if value else []
    return [v for v in (value or []) if v]


def hidden_huds() -> List[str]:
    """Return the HUDs currently hidden by Blue Steel."""
    return list(_hidden_huds)


def hide_conflicting_huds(sections: Iterable[int]) -> List[str]:
    """Hide visible native HUDs located in ``sections``.

    Parameters:
        sections: HUD sections to clear.

    Returns:
        list[str]: Newly hidden HUD names.
    """
    sections = set(sections)
    newly_hidden = []
    for name in cmds.headsUpDisplay(query=True, listHeadsUpDisplays=True) or []:
        if _is_own_hud(name) or name in _hidden_huds:
            continue
        try:
            if cmds.headsUpDisplay(name, query=True, section=True) not in sections:
                continue
            if not cmds.headsUpDisplay(name, query=True, visible=True):
                continue
            cmds.headsUpDisplay(name, edit=True, visible=False)
        except RuntimeError:
            continue
        _hidden_huds.append(name)
        newly_hidden.append(name)
    _save_hidden_record()
    return newly_hidden


def restore_hidden_huds(names: Optional[Iterable[str]] = None) -> None:
    """Restore HUDs hidden by :func:`hide_conflicting_huds`.

    Parameters:
        names: Restrict to these names; all recorded HUDs when None.
    """
    targets = list(_hidden_huds) if names is None else [n for n in names if n in _hidden_huds]
    for name in targets:
        try:
            if cmds.headsUpDisplay(name, query=True, exists=True):
                cmds.headsUpDisplay(name, edit=True, visible=True)
        except RuntimeError:
            pass
        _hidden_huds.remove(name)
    _save_hidden_record()


def update_conflicts() -> None:
    """Re-evaluate which native HUDs must be hidden for the current placement."""
    sections = covered_sections()
    to_restore = []
    for name in _hidden_huds:
        try:
            exists = cmds.headsUpDisplay(name, query=True, exists=True)
            section = cmds.headsUpDisplay(name, query=True, section=True) if exists else None
        except RuntimeError:
            section = None
        if section not in sections:
            to_restore.append(name)
    restore_hidden_huds(to_restore)
    hide_conflicting_huds(sections)


def recover_stale_hidden_huds() -> None:
    """Restore HUDs left hidden by a previous session (e.g. after a crash)."""
    for name in _load_hidden_record():
        if name not in _hidden_huds:
            _hidden_huds.append(name)
    restore_hidden_huds()


# ---------------------------------------------------------------------------
# High level
# ---------------------------------------------------------------------------
def show(blend_shape: str, list_combos: bool = True) -> bool:
    """Display the shapes HUD and hide conflicting native HUDs.

    Returns:
        bool: True if the plugin HUD is used, False for the native fallback.
    """
    hide(restore=False)
    used_plugin = create(blend_shape, list_combos=list_combos) is not None
    if used_plugin:
        ensure_panels_show_hud()
        _sync_isolate_membership()
        _start_viewport_watch()
    else:
        blendshapeHUD.create_master_hud(blend_shape, list_combos=list_combos)
    # Populate the draw cache so the rect query reflects the real content.
    try:
        cmds.refresh(currentView=True, force=True)
    except RuntimeError:
        pass
    update_conflicts()
    return used_plugin


def hide(restore: bool = True) -> None:
    """Remove the shapes HUD (both back-ends) and restore hidden native HUDs."""
    _stop_viewport_watch()
    delete()
    blendshapeHUD.clear_huds()
    if restore:
        restore_hidden_huds()
