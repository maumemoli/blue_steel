"""
Blue Steel Shapes HUD - Viewport 2.0 drawn blendShape weights HUD.

Unlike ``cmds.headsUpDisplay`` this HUD has an independently resizable frame
and font size (``frameWidth`` / ``frameHeight`` / ``hudScale``). It is drawn by
Viewport 2.0 through ``MUIDrawManager``, it shows up in playblasts. Its own
"Blue Steel Shapes HUD" display filter controls visibility independently of
scene Locators; hudManager includes the temporary shape in isolate sets.

Node:
    bsShapesHUD (locator shape)
        blendShape         message  - connect ``<blendShape>.message``
        listCombos         bool     - list weights driven by combinationShapes
        offsetX / offsetY  float    - normalized top-left anchor (0-1 of viewport,
                                      top-left origin)
        frameWidth/Height  float    - area size as fractions of the viewport
        hudScale           float    - font size only (relative to viewport height)
        textColor          float3
        titleColor         float3
        backgroundOpacity  float
        showFrame          bool     - draws an outline (used while transforming)

Command:
    bsShapesHUDQuery <node> -w <viewportWidth> -h <viewportHeight>
        Returns [x, y, width, height] of the HUD rectangle in pixels, top-left
        origin, for the given viewport size, independent of the text content.

The node marks itself ``doNotWrite`` so it is never saved with the scene.
"""

from maya import cmds
import maya.api.OpenMaya as om
import maya.api.OpenMayaUI as omui
import maya.api.OpenMayaRender as omr
from functools import lru_cache
import math


def maya_useNewAPI():
    """Tell Maya this plugin uses the Python API 2.0."""
    pass


NODE_NAME = "bsShapesHUD"
PLUGIN_VERSION = "1.3"
NODE_ID = om.MTypeId(0x0007BE51)
DRAW_DB_CLASSIFICATION = "drawdb/geometry/bsShapesHUD"
DRAW_REGISTRANT_ID = "bsShapesHUDPlugin"
DISPLAY_FILTER_NAME = "bsShapesHUD"
DISPLAY_FILTER_LABEL = "Blue Steel Shapes HUD"
QUERY_COMMAND_NAME = "bsShapesHUDQuery"

# ---------------------------------------------------------------------------
# Layout constants (shared by the draw override and the query command)
# ---------------------------------------------------------------------------
BASE_FONT_RATIO = 13.0 / 720.0   # font px per viewport px (height) at scale 1.0
TITLE_SCALE = 1.25
LINE_SPACING = 1.45
COLUMN_GAP = 1.5                  # in font units
PADDING = 0.5                     # in font units
MIN_FONT = 6
MAX_FONT = 200
FONT_FACE = "Arial"
DEFAULT_FRAME_WIDTH = 0.4
DEFAULT_FRAME_HEIGHT = 0.5

# Last drawn content per node name: {"title": str, "lines": [str], ...}
_LAST_CONTENT = {}


@lru_cache(maxsize=4096)
def text_width(text, font_size):
    """Measure VP2's explicit normal font style and unkerned glyph advances.

    The conservative fallback is for batch/layout-only use without a Qt GUI.
    Avoid constructing QFontMetrics without a GUI application in mayapy.
    """
    if int(cmds.about(version=True)) >= 2025:
        from PySide6.QtGui import QFont, QFontMetricsF, QGuiApplication
    else:
        from PySide2.QtGui import QFont, QFontMetricsF, QGuiApplication
    if QGuiApplication.instance() is None:
        return len(text) * font_size + 1.0
    font = QFont(FONT_FACE)
    font.setPixelSize(int(font_size))
    font.setWeight(QFont.Normal)
    font.setItalic(False)
    font.setStretch(QFont.Unstretched)
    # VP2 places glyphs without Qt's pair kerning. A shaped-string advance
    # underestimates labels containing pairs such as AV/To. Round per-glyph
    # advances conservatively and include the ink bounds as well.
    font.setKerning(False)
    metrics = QFontMetricsF(font)
    glyph_advance = sum(math.ceil(metrics.horizontalAdvance(char)) for char in text)
    return math.ceil(max(glyph_advance, metrics.horizontalAdvance(text),
                         metrics.boundingRect(text).width())) + 1.0


def _elide(text, width, font, preserve_value=False):
    """Fit a label without reducing the font; retain its weight when possible."""
    if text_width(text, font) <= width:
        return text
    if text_width("...", font) > width:
        return ""
    prefix, suffix = text, ""
    if preserve_value and ": " in text:
        name, value = text.rsplit(": ", 1)
        if text_width("...: " + value, font) <= width:
            prefix, suffix = name, ": " + value
    low, high = 0, len(prefix)
    while low < high:
        mid = (low + high + 1) // 2
        if text_width(prefix[:mid] + "..." + suffix, font) <= width:
            low = mid
        else:
            high = mid - 1
    return prefix[:low] + "..." + suffix


def compute_layout(title, lines, vp_w, vp_h, offset_x, offset_y, scale,
                   frame_width=DEFAULT_FRAME_WIDTH, frame_height=DEFAULT_FRAME_HEIGHT):
    """Lay out columns inside a fixed frame, in physical viewport pixels.

    Frame position/dimensions are normalized to the viewport. ``scale`` controls
    font size only. ``rect`` always describes the configured frame, independent
    of its contents. Text uses the intersection of that frame and the viewport.
    Omitted shapes are indicated by a final standalone ``...`` entry.
    """
    vp_w, vp_h = max(1.0, float(vp_w)), max(1.0, float(vp_h))
    font = max(MIN_FONT, min(MAX_FONT, int(round(BASE_FONT_RATIO * max(0.05, scale) * vp_h))))
    title_font = max(MIN_FONT, min(MAX_FONT, int(round(font * TITLE_SCALE))))
    line_h, title_h, pad = font * LINE_SPACING, title_font * LINE_SPACING, font * PADDING
    x, y = float(offset_x) * vp_w, float(offset_y) * vp_h
    width, height = max(0.0, frame_width) * vp_w, max(0.0, frame_height) * vp_h
    left, top = max(0.0, x + pad), max(0.0, y + pad)
    right, bottom = min(vp_w, x + width - pad), min(vp_h, y + height - pad)
    items = []
    result = {"rect": (x, y, width, height), "items": items, "columns": [],
              "font": font, "title_font": title_font, "title_drawn": False,
              "overflow": bool(lines), "visible_count": 0}
    if right <= left or bottom <= top:
        return result

    # If only one body-height row fits, show the overflow cue rather than a
    # title that would hide the fact that there are undisplayed shapes.
    title_text = _elide(title, right - left, title_font)
    if title_text and top + title_h <= bottom and (not lines or top + title_h + line_h <= bottom):
        items.append((left, top + title_h, title_text, title_font))
        result["title_drawn"] = True
        top += title_h
    elif lines:
        if top + line_h <= bottom and text_width("...", font) <= right - left:
            items.append((left, top + line_h, "...", font))
        return result

    rows = max(0, int((bottom - top + 1e-6) // line_h))
    cursor, column_x = 0, left
    while rows and cursor < len(lines) and right - column_x >= text_width("...", font):
        column = lines[cursor:cursor + rows]
        desired_width = max(text_width(text, font) for text in column)
        column_width = min(max(desired_width, text_width("...", font)), right - column_x)
        result["columns"].append((column_x, top, column_width, len(column) * line_h))
        for row, text in enumerate(column):
            items.append((column_x, top + (row + 1) * line_h,
                          _elide(text, column_width, font, preserve_value=True), font))
        cursor += len(column)
        column_x += column_width + font * COLUMN_GAP

    result["overflow"] = cursor < len(lines)
    result["visible_count"] = cursor
    if result["overflow"] and cursor:
        # Reserve the final available slot for the cue; no count or extra row.
        last_x, last_y, _, last_font = items[-1]
        items[-1] = (last_x, last_y, "...", last_font)
        result["visible_count"] -= 1
    return result


def _connected_node(node_obj, attr_name):
    """Return the MObject connected to ``node.attr_name`` (source side) or None."""
    plug = om.MPlug(node_obj, om.MFnDependencyNode(node_obj).attribute(attr_name))
    if not plug.isDestination:
        return None
    src = plug.source()
    if src.isNull:
        return None
    return src.node()


def _collect_lines(blend_obj, list_combos):
    """Collect ``name: value`` lines for every non-zero weight of a blendShape."""
    fn = om.MFnDependencyNode(blend_obj)
    weight_plug = fn.findPlug("weight", False)
    lines = []
    for index in weight_plug.getExistingArrayAttributeIndices():
        elem = weight_plug.elementByLogicalIndex(index)
        try:
            value = elem.asFloat()
        except RuntimeError:
            continue
        if abs(value) <= 1e-6:
            continue
        if not list_combos and elem.isDestination:
            src = elem.source()
            if not src.isNull and om.MFnDependencyNode(src.node()).typeName == "combinationShape":
                continue
        name = fn.plugsAlias(elem) or "weight[{0}]".format(index)
        lines.append("{0}: {1}".format(name, round(value, 4)))
    return lines


# ---------------------------------------------------------------------------
# Node
# ---------------------------------------------------------------------------
class BsShapesHUDNode(omui.MPxLocatorNode):
    """Locator carrying the HUD settings; drawing happens in the draw override."""

    a_blend_shape = None
    a_list_combos = None
    a_offset_x = None
    a_offset_y = None
    a_scale = None
    a_frame_width = None
    a_frame_height = None
    a_text_color = None
    a_title_color = None
    a_background_opacity = None
    a_show_frame = None

    def __init__(self):
        omui.MPxLocatorNode.__init__(self)

    def postConstructor(self):
        try:
            om.MFnDependencyNode(self.thisMObject()).setDoNotWrite(True)
        except Exception:
            pass

    def isBounded(self):
        return False

    def excludeAsLocator(self):
        # A screen-space annotation must not disappear with scene locators.
        # Its own plugin display filter controls visibility instead.
        return False

    @staticmethod
    def creator():
        return BsShapesHUDNode()

    @staticmethod
    def initialize():
        msg = om.MFnMessageAttribute()
        num = om.MFnNumericAttribute()
        cls = BsShapesHUDNode

        cls.a_blend_shape = msg.create("blendShape", "bs")
        msg.storable = False
        om.MPxNode.addAttribute(cls.a_blend_shape)

        cls.a_list_combos = num.create("listCombos", "lc", om.MFnNumericData.kBoolean, True)
        num.keyable = False
        om.MPxNode.addAttribute(cls.a_list_combos)

        cls.a_offset_x = num.create("offsetX", "ofx", om.MFnNumericData.kFloat, 0.01)
        num.setMin(-1.0)
        num.setMax(2.0)
        om.MPxNode.addAttribute(cls.a_offset_x)

        cls.a_offset_y = num.create("offsetY", "ofy", om.MFnNumericData.kFloat, 0.02)
        num.setMin(-1.0)
        num.setMax(2.0)
        om.MPxNode.addAttribute(cls.a_offset_y)

        cls.a_scale = num.create("hudScale", "hsc", om.MFnNumericData.kFloat, 1.0)
        num.setMin(0.05)
        num.setMax(20.0)
        om.MPxNode.addAttribute(cls.a_scale)

        cls.a_frame_width = num.create("frameWidth", "fw", om.MFnNumericData.kFloat,
                                       DEFAULT_FRAME_WIDTH)
        num.setMin(0.001)
        num.setMax(1.0)
        om.MPxNode.addAttribute(cls.a_frame_width)

        cls.a_frame_height = num.create("frameHeight", "fh", om.MFnNumericData.kFloat,
                                        DEFAULT_FRAME_HEIGHT)
        num.setMin(0.001)
        num.setMax(1.0)
        om.MPxNode.addAttribute(cls.a_frame_height)

        cls.a_text_color = num.createColor("textColor", "tcl")
        num.default = (0.9, 0.9, 0.9)
        om.MPxNode.addAttribute(cls.a_text_color)

        cls.a_title_color = num.createColor("titleColor", "ttc")
        num.default = (1.0, 0.8, 0.3)
        om.MPxNode.addAttribute(cls.a_title_color)

        cls.a_background_opacity = num.create("backgroundOpacity", "bgo", om.MFnNumericData.kFloat, 0.35)
        num.setMin(0.0)
        num.setMax(1.0)
        om.MPxNode.addAttribute(cls.a_background_opacity)

        cls.a_show_frame = num.create("showFrame", "sfr", om.MFnNumericData.kBoolean, False)
        om.MPxNode.addAttribute(cls.a_show_frame)


# ---------------------------------------------------------------------------
# Draw override
# ---------------------------------------------------------------------------
# Draw content per DAG path, filled in prepareForDraw and read in
# addUIDrawables. Keep the content available independently of the MUserData
# token so the draw path and diagnostic queries can share the same data.
_DRAW_CACHE = {}
# Diagnostics, see ``bsShapesHUDQuery -stats``.
_STATS = {"prepare": 0, "draw": 0, "error": ""}


def _report_error(where, exc):
    """Record (and print once per message) an exception raised while drawing."""
    import traceback
    message = "{0}: {1}".format(where, exc)
    if _STATS["error"] != message:
        _STATS["error"] = message
        om.MGlobal.displayWarning("bsShapesHUD {0}\n{1}".format(message, traceback.format_exc()))


class BsShapesHUDData(om.MUserData):
    """Minimal user data handed back to Maya (content lives in _DRAW_CACHE)."""

    def __init__(self):
        try:
            om.MUserData.__init__(self, False)  # Maya < 2023 signature
        except Exception:
            om.MUserData.__init__(self)


def _plug_color(node, attr):
    plug = om.MPlug(node, attr)
    return om.MColor((plug.child(0).asFloat(), plug.child(1).asFloat(),
                      plug.child(2).asFloat(), 1.0))


def _gather_content(node):
    """Read the node settings and the blendShape weights into a plain dict."""
    cls = BsShapesHUDNode
    content = {
        "offset_x": om.MPlug(node, cls.a_offset_x).asFloat(),
        "offset_y": om.MPlug(node, cls.a_offset_y).asFloat(),
        "scale": om.MPlug(node, cls.a_scale).asFloat(),
        "frame_width": om.MPlug(node, cls.a_frame_width).asFloat(),
        "frame_height": om.MPlug(node, cls.a_frame_height).asFloat(),
        "background_opacity": om.MPlug(node, cls.a_background_opacity).asFloat(),
        "show_frame": om.MPlug(node, cls.a_show_frame).asBool(),
        "text_color": _plug_color(node, cls.a_text_color),
        "title_color": _plug_color(node, cls.a_title_color),
    }
    list_combos = om.MPlug(node, cls.a_list_combos).asBool()
    blend_obj = _connected_node(node, "blendShape")
    if blend_obj is None:
        content["title"] = "Blue Steel HUD: no blendShape connected"
        content["lines"] = []
    else:
        blend_name = om.MFnDependencyNode(blend_obj).name()
        content["title"] = blend_name if list_combos else "{0} (Hidden Combos)".format(blend_name)
        try:
            content["lines"] = _collect_lines(blend_obj, list_combos)
        except Exception as exc:  # never break the viewport
            content["lines"] = ["error: {0}".format(exc)]
    return content


class BsShapesHUDDrawOverride(omr.MPxDrawOverride):
    """Screen-space text drawing of the active blendShape weights."""

    def __init__(self, obj):
        # isAlwaysDirty=True: weights change constantly, redraw every refresh.
        omr.MPxDrawOverride.__init__(self, obj, BsShapesHUDDrawOverride.draw, True)

    @staticmethod
    def creator(obj):
        return BsShapesHUDDrawOverride(obj)

    @staticmethod
    def draw(context, data):
        # Everything is drawn through addUIDrawables.
        return

    def supportedDrawAPIs(self):
        return omr.MRenderer.kAllDevices

    def isBounded(self, obj_path, camera_path):
        return False

    def boundingBox(self, obj_path, camera_path):
        return om.MBoundingBox()

    def hasUIDrawables(self):
        return True

    def prepareForDraw(self, obj_path, camera_path, frame_context, old_data):
        _STATS["prepare"] += 1
        try:
            node = obj_path.node()
            content = _gather_content(node)
            _DRAW_CACHE[obj_path.fullPathName()] = content
            _LAST_CONTENT[om.MFnDependencyNode(node).name()] = content
        except Exception as exc:
            _report_error("prepareForDraw", exc)
        if isinstance(old_data, BsShapesHUDData):
            return old_data
        try:
            return BsShapesHUDData()
        except Exception:
            return None

    def addUIDrawables(self, obj_path, draw_manager, frame_context, data):
        _STATS["draw"] += 1
        try:
            content = _DRAW_CACHE.get(obj_path.fullPathName())
            if content is None:
                content = _gather_content(obj_path.node())
            self._draw_content(content, draw_manager, frame_context)
        except Exception as exc:
            _report_error("addUIDrawables", exc)

    @staticmethod
    def _draw_content(content, draw_manager, frame_context):
        origin_x, origin_y, vp_w, vp_h = frame_context.getViewportDimensions()
        layout = compute_layout(content["title"], content["lines"], vp_w, vp_h,
                                content["offset_x"], content["offset_y"], content["scale"],
                                content["frame_width"], content["frame_height"])

        def to_vp(x, y):
            # top-left origin -> VP2 bottom-left origin
            return om.MPoint(origin_x + x, origin_y + vp_h - y, 0.0)

        rx, ry, rw, rh = layout["rect"]
        center = to_vp(rx + rw * 0.5, ry + rh * 0.5)
        up = om.MVector(0.0, 1.0, 0.0)

        draw_manager.beginDrawable()
        draw_manager.setFontName(FONT_FACE)
        # The renderer's default style did not match QFont's normal Arial
        # metrics in newSplitMaps.mb. Set the complete style explicitly so
        # measured column widths and actual glyph advances agree.
        draw_manager.setFontWeight(omr.MUIDrawManager.kWeightNormal)
        draw_manager.setFontStretch(omr.MUIDrawManager.kStretchUnstretched)
        draw_manager.setFontIncline(omr.MUIDrawManager.kInclineNormal)
        if content["background_opacity"] > 0.0:
            draw_manager.setColor(om.MColor((0.0, 0.0, 0.0, content["background_opacity"])))
            draw_manager.rect2d(center, up, rw * 0.5, rh * 0.5, True)
        if content["show_frame"]:
            draw_manager.setColor(om.MColor((0.3, 0.75, 1.0, 1.0)))
            draw_manager.setLineWidth(1.5)
            draw_manager.rect2d(center, up, rw * 0.5, rh * 0.5, False)

        for index, (x, y_bottom, text, font_px) in enumerate(layout["items"]):
            draw_manager.setColor(content["title_color"] if index == 0 and layout["title_drawn"]
                                  else content["text_color"])
            draw_manager.setFontSize(int(font_px))
            draw_manager.text2d(to_vp(x, y_bottom), text, omr.MUIDrawManager.kLeft)
        draw_manager.endDrawable()


# ---------------------------------------------------------------------------
# Query command
# ---------------------------------------------------------------------------
class BsShapesHUDQueryCmd(om.MPxCommand):
    """Return the HUD rect [x, y, w, h] (top-left origin) for a viewport size."""

    def __init__(self):
        om.MPxCommand.__init__(self)

    @staticmethod
    def creator():
        return BsShapesHUDQueryCmd()

    @staticmethod
    def syntax():
        syntax = om.MSyntax()
        syntax.setObjectType(om.MSyntax.kStringObjects, 0, 1)
        syntax.addFlag("-w", "-width", om.MSyntax.kDouble)
        syntax.addFlag("-h", "-height", om.MSyntax.kDouble)
        syntax.addFlag("-s", "-stats")
        return syntax

    def doIt(self, args):
        db = om.MArgDatabase(self.syntax(), args)
        if db.isFlagSet("-s"):
            self.clearResult()
            self.setResult("prepare={0} draw={1} error={2}".format(
                _STATS["prepare"], _STATS["draw"], _STATS["error"] or "none"))
            return
        objects = db.getObjectStrings()
        if not objects:
            raise RuntimeError("bsShapesHUDQuery: a bsShapesHUD node name is required.")
        node_name = objects[0]
        width = db.flagArgumentDouble("-w", 0) if db.isFlagSet("-w") else 1920.0
        height = db.flagArgumentDouble("-h", 0) if db.isFlagSet("-h") else 1080.0

        sel = om.MSelectionList()
        sel.add(node_name)
        try:
            dag = sel.getDagPath(0)
            if dag.node().apiType() == om.MFn.kTransform:
                dag.extendToShape()
            obj = dag.node()
        except RuntimeError:
            obj = sel.getDependNode(0)
        fn = om.MFnDependencyNode(obj)
        content = _LAST_CONTENT.get(fn.name())
        offset_x = om.MPlug(obj, BsShapesHUDNode.a_offset_x).asFloat()
        offset_y = om.MPlug(obj, BsShapesHUDNode.a_offset_y).asFloat()
        scale = om.MPlug(obj, BsShapesHUDNode.a_scale).asFloat()
        title = content["title"] if content else fn.name()
        lines = content["lines"] if content else []
        frame_width = om.MPlug(obj, BsShapesHUDNode.a_frame_width).asFloat()
        frame_height = om.MPlug(obj, BsShapesHUDNode.a_frame_height).asFloat()
        layout = compute_layout(title, lines, width, height, offset_x, offset_y, scale,
                                frame_width, frame_height)
        self.clearResult()
        for value in layout["rect"]:
            self.appendToResult(float(value))


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------
def initializePlugin(obj):
    plugin = om.MFnPlugin(obj, "Blue Steel", PLUGIN_VERSION, "Any")
    plugin.registerNode(NODE_NAME, NODE_ID,
                        BsShapesHUDNode.creator, BsShapesHUDNode.initialize,
                        om.MPxNode.kLocatorNode, DRAW_DB_CLASSIFICATION)
    omr.MDrawRegistry.registerDrawOverrideCreator(DRAW_DB_CLASSIFICATION,
                                                  DRAW_REGISTRANT_ID,
                                                  BsShapesHUDDrawOverride.creator)
    plugin.registerCommand(QUERY_COMMAND_NAME, BsShapesHUDQueryCmd.creator,
                           BsShapesHUDQueryCmd.syntax)
    # MFnPlugin has no registerDisplayFilter method in Python API 2.0.
    # Use Maya's actual registration command; don't silently ignore failures.
    cmds.pluginDisplayFilter(DISPLAY_FILTER_NAME, register=True,
                             label=DISPLAY_FILTER_LABEL,
                             classification=DRAW_DB_CLASSIFICATION)
    # pluginDisplayFilter registration can reset the plugin metadata.
    plugin.version = PLUGIN_VERSION


def uninitializePlugin(obj):
    plugin = om.MFnPlugin(obj)
    if cmds.pluginDisplayFilter(DISPLAY_FILTER_NAME, exists=True):
        cmds.pluginDisplayFilter(DISPLAY_FILTER_NAME, deregister=True)
    plugin.deregisterCommand(QUERY_COMMAND_NAME)
    omr.MDrawRegistry.deregisterDrawOverrideCreator(DRAW_DB_CLASSIFICATION,
                                                    DRAW_REGISTRANT_ID)
    plugin.deregisterNode(NODE_ID)
    _LAST_CONTENT.clear()
    _DRAW_CACHE.clear()
