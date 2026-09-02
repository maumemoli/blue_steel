# Blue Steel Editor UI — Structure Reference

This document describes the structure of the editor UI so a human (or a fresh
AI session) can understand where things live and intervene without re-reading
every source file.

Scope: the `blue_steel/ui/editor` package. The supporting `blue_steel/api`
layer is referenced by name only (see the dependency note in §1).

---

## 1. Architecture at a glance

The editor is a **dockable Qt window** (`MainWindow`) built from a set of
**feature mixins** over the classic Qt **Model/View** pattern:

```
MainWindow
├── MayaQWidgetDockableMixin        (Maya docking)
├── QMainWindow                     (Qt)
├── EditorUiMixin                   (builds the whole UI, wires signals)
├── SplitSettingsUiMixin            (Split tab UI + split settings logic)
├── EditorSessionMixin              (scene/tracker lifecycle, editor selection)
├── ShapesFeatureMixin              (shapes tree + primaries tree behavior)
├── WorkShapesFeatureMixin          (work-shapes panel behavior)
├── EditorOpsMixin                  (menu actions: add/remove/import/export…)
└── MainWindowMixin                 (cooperative super().__init__ terminator)
```

- **Models** (`models.py`) hold the shape data and expose Qt roles.
- **Views** (`views.py`) render lists/trees and handle mouse/drag/keyboard.
- **Delegates** (`delegates.py`) paint individual rows and own the slider
  drag math.
- **Widgets** (`widgets.py`) are standalone reusable Qt widgets (search bars,
  split trees, inline rename editor).
- **Controller layout** (`controllerLayoutWindow.py`) is a separate pop-up
  window for designing custom controller layouts.
- **Mixins** (`mainWindow.py` + `*Mixin.py`) are the controller layer: they
  translate UI events into calls on the `blue_steel.api` domain layer.

### Data flow

```
user interaction
   → view (mouse/keyboard/drag)  [views.py]
   → delegate (hit-testing, drag math, signals)  [delegates.py]
   → model (roles/data)  [models.py]
   → mixin handler (_on_* / _handle_*)  [*Mixin.py]
   → blue_steel.api.editor.BlueSteelEditor  [api/editor.py]
   → Maya scene graph
```

The reverse direction (scene → UI) is driven by **trackers**
(`api/trackers.py`), which emit Qt signals on Maya attribute/plugin changes;
the mixins subscribe to those and refresh models/views.

### Dependency on `blue_steel.api` (by name only)

The UI imports these domain classes/functions and treats them as a black box:

| Symbol | Where it comes from | Role |
|---|---|---|
| `BlueSteelEditor` | `api/editor.py` | The domain object for one editor system (shapes, splits, weights, persistence). |
| `SplitSession` | `api/editor.py` | Helper for the split-shapes workflow. |
| `BlueSteelEditorsTracker` | `api/trackers.py` | Tracks editor containers in the scene (add/remove/rename). |
| `BlendShapeNodeTracker` | `api/trackers.py` | Tracks one blendshape node's weights/targets. |
| `ControllerTracker` | `api/trackers.py` | Tracks a controller attribute group. |
| `Container` | `api/container.py` | Maya container wrapper. |
| misc. util functions | `api/attrUtils.py`, `api/mayaUtils.py`, `api/shapeEditorUtils.py`, `api/logger.py`, `api/constants.py` | Low-level helpers (attributes, mesh points, undo, logging). |

---

## 2. Package map

All files live in `blue_steel/ui/editor/`.

| File | Purpose |
|---|---|
| `__init__.py` | Public entry: re-exports `MainWindow`, `show`, `get_maya_main_window`. |
| `constants.py` | Colors, MIME types, Qt role ids, type-group ordering. |
| `qt.py` | PySide2/PySide6 shim + small Qt helpers + cursor-safe `Splitter`. |
| `models.py` | Qt item models and filter/sort proxy models. |
| `delegates.py` | Row painting + slider drag handling (`SliderItemDelegate`). |
| `views.py` | List/tree views, drag & drop, keyboard nav, icon hit-testing. |
| `widgets.py` | Reusable widgets (search bar, split trees, inline rename). |
| `controllerLayoutWindow.py` | Controller-layout designer window. |
| `mainWindow.py` | `MainWindow` class + `show()` entry point. |
| `mainWindowMixin.py` | Cooperative init base + shared decorators/utilities. |
| `editorUiMixin.py` | Builds the main window UI and connects signals. |
| `editorSessionMixin.py` | Trackers, editor selection, scene lifecycle. |
| `shapesFeatureMixin.py` | Shapes/primaries tree behavior and filters. |
| `splitSettingsUiMixin.py` | Split tab UI and split maps/groups/weights logic. |
| `workShapesFeatureMixin.py` | Work-shapes panel behavior. |
| `editorOpsMixin.py` | Menu-bar actions and import/export operations. |

---

## 3. Module reference

### `__init__.py`

Re-exports from `mainWindow.py`:

- `MainWindow` — the editor window class.
- `show()` — create/focus the singleton window.
- `get_maya_main_window()` — Maya's main window widget (re-exported from `qt.py`).

`__all__ = ["MainWindow", "show", "get_maya_main_window"]`.

---

### `constants.py`

**Constants**
- `SHAPE_CUSTOM_COLORS` — `dict[str, hex]` for the color filter row.
- `SHAPE_NAMES_MIME_TYPE`, `PRIMARY_TREE_MIME_TYPE`, `SPLIT_MAP_MIME_TYPE` — drag & drop MIME types.
- `PRIMARY_TREE_NAME_ROLE`, `PRIMARY_TREE_FOLDER_ROLE`, `PRIMARY_TREE_SORT_VALUE_ROLE` — Qt user roles for the primaries tree.
- `TYPE_GROUP_ORDER` — ordering for shape-type groups in the Shapes tree.

**Functions**
- `shape_type_group_name(shape_type)` — maps a logical type (`PrimaryShape`, `InbetweenShape`, …) to a display group name.

---

### `qt.py`

PySide2/PySide6 import shim: it re-exports every Qt class the editor uses
(`QMainWindow`, `QListView`, `QTreeWidget`, `QPainter`, `Qt`, `Signal`, …),
choosing the correct binding at import time. Also defines a few helpers.

**Classes**
- `OptionRect` — lightweight stand-in for `QStyleOptionViewItem`; carries only `rect` and `fontMetrics`.
  - `__init__(rect=None, font_metrics=None)`
- `SplitterHandle(QSplitterHandle)` — splitter handle that resets the mouse cursor.
  - `enterEvent(event)` — clear/set cursor.
  - `leaveEvent(event)` — restore cursor.
- `Splitter(QSplitter)` — splitter using `SplitterHandle`.
  - `createHandle()` — returns a `SplitterHandle`.

**Functions**
- `get_maya_main_window()` — wrap and return Maya's main window as a `QWidget` (or `None`).
- `exec_menu(menu, global_pos)` — show a context `QMenu` at a global position.
- `exec_dialog(dialog)` — run a `QDialog` modally.
- `start_drag(drag, action)` — run a `QDrag`.
- `make_shape_name_mime(shape_names, mime_type)` — build `QMimeData` for a list of shape names.
- `color_swatch_icon(color_hex, size=14)` — build a small color-swatch `QIcon`.
- `shape_custom_color_to_qcolor(value)` — convert a hex string/None to `QColor`/None.

---

### `models.py`

Qt models. Roles used throughout are `Qt.UserRole + N` constants (see
`ShapeItemsModel` below).

**Functions**
- `normalized_search_terms(terms)` — normalize a search input into lowercase whitespace-separated tokens.

**Classes**

- `ShapeItemsModel(QAbstractListModel)` — the single source model of all shape rows (primaries, inbetweens, combos). Signal: `primaryValueCommitted(str, float)`.
  - Roles: `NameRole`, `TypeRole`, `ValueRole`, `MutedRole`, `LevelRole`, `PrimariesRole`, `EditableRole`, `IsHeaderRole`, `HeaderLevelRole`, `HeaderCollapsedRole`, `UpstreamRelatedRole`, `DownstreamRelatedRole`, `LockedRole`, `LockIconVisibleRole`, `ColorRole`.
  - `__init__(parent=None)`
  - `set_editor(editor)` — attach a `BlueSteelEditor`.
  - `rowCount(parent)` — row count.
  - `roleNames()` — role-name map.
  - `data(index, role)` — read a role value.
  - `setData(index, value, role)` — write a role value (handles rename).
  - `flags(index)` — item flags (editable, selectable…).
  - `rebuild_from_editor(editor)` — rebuild rows from the editor.
  - `set_related_shape_names(upstream, downstream)` — store related-shape names for the current selection.
  - `get_name(source_row)` — shape name for a row.
  - `set_shape_value_from_tracker(shape_name, value)` — update a value from a tracker callback.
  - `set_shape_muted_state_local(shape_name, muted)` — set muted locally.
  - `set_shape_locked_state_local(shape_name, locked)` — set locked locally.
  - `set_shape_color_local(shape_name, color)` — set custom color locally.
  - `refresh_locked_states_from_editor()` — re-read lock states from the editor.
  - `get_shape_value(shape_name)` — read current value.
  - `set_shape_value_by_name(shape_name, value)` — set value and emit change.
  - `refresh_values_from_editor()` — re-read all values; returns changed pairs.

- `PrimaryShapesProxyModel(QSortFilterProxyModel)` — filter/sort view of primary shapes.
  - `__init__(parent=None)`
  - `set_search_terms(terms)` / `set_search_text(text)` — search filter.
  - `filterAcceptsRow(source_row, source_parent)` — row filter predicate.

- `ShapesFilterProxyModel(QSortFilterProxyModel)` — the main shapes filter/sort: builds the grouped tree (headers, levels), applies search, color, active-only, and value-sort logic.
  - `__init__(parent=None)`
  - `setSourceModel(model)` — attach source and wire change handlers.
  - `_invalidate_level_count_cache(*args)` / `_on_source_data_changed(...)` — internal cache/data-change handling.
  - `_is_value_sort_mode()` — whether value sorting is active.
  - `is_with_value_shape(model, index)` — whether a row is a shape with a value.
  - `_with_value_header_source_index(model)` — header index for "with value" rows.
  - `_has_visible_with_value_shapes(model)` — whether such rows are visible.
  - `sort(column, order)` — custom sort.
  - `set_search_terms(terms)` / `set_search_text(text)`
  - `set_selected_primaries(primary_names)` — restrict to a primary subset.
  - `set_visible_names(shape_names)` — restrict to explicit names.
  - `set_active_only(active_only)` — active-only filter.
  - `set_color_filter(color_hexes, include_no_color=False)` — color filter.
  - `color_filter_active()` — whether a color filter is set.
  - `toggle_level_collapsed(level)` — collapse/expand a type level.
  - `_shape_row_matches_filters(model, index)` — filter predicate.
  - `_count_visible_shapes_for_level(model, level)` — count helper.
  - `filterAcceptsRow(source_row, source_parent)` — filter predicate.
  - `data(index, role)` — overrides header/group rendering.
  - `lessThan(left, right)` — sort comparator.

- `PrimarySubsetProxyModel(QSortFilterProxyModel)` — view restricted to an explicit set of selected primary names.
  - `__init__(parent=None)`
  - `clear_selected_names()` / `add_selected_names(names)` / `remove_selected_names(names)`
  - `selected_names()`
  - `filterAcceptsRow(...)` / `lessThan(...)`

- `WorkShapeItemsModel(QAbstractListModel)` — model for work-shape rows. Signal: `valueCommitted(str, float)`.
  - Roles include `InEditModeRole`, `ConnectedRole`, `DriverConnectedRole`.
  - `__init__(parent=None)`
  - `rowCount(parent)`, `data(index, role)`, `flags(index)`, `setData(...)`
  - `rebuild_from_editor(editor)`
  - `has_connected_driver_shapes()`
  - `set_value_by_name(shape_name, value)` / `get_value(shape_name)` / `set_value_local(...)`
  - `set_muted_state_local(...)`
  - `is_shape_connected(shape_name)` / `set_connected_state_local(...)` / `set_driver_connected_state_local(...)`
  - `refresh_values_from_editor()`
  - `index_by_name(shape_name)`
  - `edit_shape_name()` / `set_edit_shape(shape_name)` — inline rename state.

---

### `delegates.py`

Row painting and slider-drag logic.

**Classes**

- `_DragEventFilter(QObject)` — application-wide event filter active during a slider drag; forwards mouse moves/releases to the delegate so dragging continues even when the cursor leaves the view.
  - `__init__(delegate)`
  - `eventFilter(watched, event)` — route events to `delegate.external_drag_*`.

- `SliderItemDelegate(QStyledItemDelegate)` — paints a shape row (name, value bar, mute/lock/connected-mesh/work-edit icons) and owns the value drag interaction.
  - Signals: `valueDragStarted()`, `valueDragEnded()`, `valueDragDelta(float)`, `valueDragSelectionContext(bool)`, `muteToggleRequested(str, bool)`, `lockToggleRequested(str, bool)`, `connectedMeshRequested(str)`, `workEditModeToggleRequested(str, bool)`.
  - `_is_primary_tree_view()` — detect which view kind this delegate serves.
  - `sizeHint(option, index)`
  - `__init__(parent=None)`
  - `_open_drag_undo_chunk()` / `_close_drag_undo_chunk()` — wrap a drag in one undo chunk.
  - `set_name_column_width(width)` / `value_column_width()` / `_value_text_width(option)`
  - `_area_rects(option, index)` — layout rectangles (name/value/icon areas).
  - `_tree_row_indent(index)`
  - `_connected_mesh_icon_rect(option, index)` / `_mute_icon_rect(...)` / `_edit_mode_icon_rect(...)` / `_lock_icon_rect(...)` — icon hit rectangles.
  - `_is_lock_icon_visible(index)` / `_shows_mute_icon(index)` / `_is_work_edit_mode_icon_visible(index)` / `_panel_reserved_icon_slots()` / `_reserved_icon_slots(index)` — visibility helpers.
  - `_draw_icon_pixmap(painter, icon_rect, icon)`
  - `paint(painter, option, index)` — main paint routine.
  - `createEditor(parent, option, index)` / `setEditorData(...)` / `setModelData(...)` / `updateEditorGeometry(...)` — inline editing.
  - `_set_drag_value_from_pos(model, x_pos)` — map a pointer x to a value.
  - `_resolve_drag_targets(index)` — decide which shapes move together (linked/selection).
  - `_start_drag(model, index, event_pos, value_rect)` — begin a drag.
  - `_end_drag(model, x_pos)` — finish a drag.
  - `_install_drag_event_filter()` / `_remove_drag_event_filter()` — manage `_DragEventFilter`.
  - `viewport_x_from_global(global_pos)` — global → viewport x.
  - `is_drag_active()`
  - `external_drag_move(x_pos)` / `external_drag_end(x_pos)` / `external_drag_start(model, index, event_pos, item_rect)` — the "external drag" API used by the views.
  - `editorEvent(event, model, option, index)` — handle icon clicks within rows.

- `SplitMapWeightSliderDelegate(SliderItemDelegate)` — variant for split-map weight rows.
  - `sizeHint(...)`, `_row_rects(...)`, `_area_rects(...)`, `paint(...)`, `editorEvent(...)`, `updateEditorGeometry(...)`, `_shows_mute_icon(...)`, `_panel_reserved_icon_slots()`.

---

### `views.py`

Views and drag/keyboard behavior.

**Functions**
- `_is_slider_delegate(delegate)` — duck-type check for the slider-drag API (reload-safe, avoids `isinstance`).

**Classes**

- `SliderDragViewMixin` — shared mouse handling for slider-style views. Cooperates with `SliderItemDelegate.external_drag_*`.
  - `_slider_delegate()` — return the delegate (handles list vs tree column delegates).
  - `_resolve_icon_click(event_pos)` — map a click to an icon action (default `None`).
  - `_emit_icon_click(payload)` — emit the resolved icon action.
  - `mousePressEvent(event)` / `mouseMoveEvent(event)` / `mouseReleaseEvent(event)` / `mouseDoubleClickEvent(event)` — icon clicks + delegate drag forwarding.

- `PrimaryDropListView(SliderDragViewMixin, QListView)` — drop target list for primaries.
  - `__init__(drop_callback, remove_callback=None, parent=None)`
  - `_selected_shape_names()`
  - `_show_context_menu(pos)`
  - `_shape_names_from_mime(mime_data)`
  - `_can_accept_drop(mime_data)`
  - `_resolve_mute_icon_click(event_pos)` / `_resolve_lock_icon_click(event_pos)` / `_resolve_icon_click(event_pos)`
  - `dragEnterEvent(event)` / `dragMoveEvent(event)` / `dropEvent(event)`

- `SplitMapWeightsList(SliderDragViewMixin, QListWidget)` — weight list for split maps (delegate-driven drag only).

- `SliderListView(SliderDragViewMixin, QListView)` — main shapes list (primary shapes panel).
  - `__init__(parent=None)`
  - `_selected_draggable_shape_names()`
  - `startDrag(supportedActions)` — begin a name drag.
  - `_resolve_mute_icon_click(event_pos)` / `_resolve_connected_mesh_icon_click(event_pos)` / `_resolve_lock_icon_click(event_pos)` / `_resolve_work_edit_mode_icon_click(event_pos)` / `_resolve_icon_click(event_pos)`

- `WorkShapesListView(SliderListView)` — work-shapes list.
  - `__init__(...)`
  - `_shape_names_from_mime(mime_data)` / `_receiver_name_at_pos(pos)`
  - `dragEnterEvent` / `dragMoveEvent` / `dropEvent`
  - `_show_context_menu(pos)`

- `ShapeTreeWidget(SliderDragViewMixin, QTreeWidget)` — the Shapes tree.
  - Signals: `toggleUpstreamFilterRequested()`, `pageNavigationPoseRequested(str)`.
  - `_resolve_icon_click(event_pos)`
  - `_selected_draggable_shape_names()`
  - `_next_selectable_item(start_item, direction)` / `_move_to_next_selectable_item(direction)`
  - `startDrag(supportedActions)` / `keyPressEvent(event)`

- `PrimaryTreeWidget(SliderDragViewMixin, QTreeWidget)` — the Primaries tree.
  - Signal: `pageNavigationPoseRequested(str)`.
  - `_resolve_icon_click(event_pos)`, `_selected_draggable_shape_names()`, `_next_selectable_item(...)`, `_move_to_next_selectable_item(...)`, `startDrag(...)`, `keyPressEvent(...)`.

- `PrimaryTreeItem(QTreeWidgetItem)` — primaries tree item with custom ordering.
  - `__lt__(other)` — sort by name/folder/value.

- `SplitPrimaryAssignmentsView(SliderDragViewMixin, QTreeWidget)` — split primary → group assignment tree.
  - Signal: `assignmentChanged(str, object)`.
  - `__init__(parent=None)`
  - `_update_group_icon(item)`
  - `set_source_model(source_model)` / `primary_names()`
  - `set_assignments(group_names, assignments)`
  - `sync_source_data(top_left, bottom_right, roles)`
  - `set_search_terms(terms)` / `set_search_text(text)`
  - `startDrag(supported_actions)`
  - `_drop_group_name(pos)`
  - `dragEnterEvent` / `dragMoveEvent` / `dropEvent` / `mousePressEvent`

---

### `widgets.py`

Standalone reusable widgets.

**Classes**

- `TokenSearchBar(QWidget)` — search box that tokenizes text and shows removable chips. Signal: `searchChanged(object)`.
  - `__init__(placeholder="", parent=None)`
  - `setPlaceholderText(text)` / `text()` / `terms()` / `setText(text)` / `clear()`
  - `_commit_editor_text()` / `_remove_token(token, emit=True)` / `_emit_search_changed(*args)`

- `SplitMapsTree(QTreeWidget)` — list of split maps. Signal: `currentMapChanged(str)`.
  - `__init__(parent=None)`
  - `set_maps(maps)` — populate.
  - `map_name(item=None)` / `map_items()` / `find_map(map_name)`
  - `_on_current_item_changed(current, previous)`
  - `startDrag(supported_actions)`

- `SplitMapStatusDelegate(QStyledItemDelegate)` — paints a status column for split maps.
  - `paint(painter, option, index)`

- `SplitGroupsTree(QTreeWidget)` — tree of split groups → maps. Signals: `mapSelected(str)`, `mapsChanged(dict)`, `mapDraggedOut(str, str)`, `groupSelected(str)`.
  - `__init__(parent=None)`
  - `set_groups(split_groups, selected_group="")`
  - `selected_group_name()` / `select_group(group_name)`
  - `_group_name(item)` / `_map_names(group_item)` / `groups()`
  - `_on_current_item_changed(current, previous)`
  - `_event_position(event)` (staticmethod)
  - `dragEnterEvent` / `dragMoveEvent` / `dropEvent` / `startDrag`

- `InlineWorkshapeRenameEditor(QLineEdit)` — inline rename field. Signals: `submitted()`, `canceled()`.
  - `keyPressEvent(event)` / `focusOutEvent(event)`

---

### `controllerLayoutWindow.py`

A separate pop-up window for designing custom controller layouts (sliders/quads
on a canvas, bound to Maya attributes).

**Classes**

- `DraggablePaletteButton(QPushButton)` — palette button that starts a drag to add a controller.
  - `__init__(label, controller_type, parent=None)` / `mouseMoveEvent(event)`

- `DraggableAttributeList(QListWidget)` — list of attributes that can be dragged onto controller zones.
  - `__init__(parent=None)` / `mousePressEvent` / `mouseMoveEvent` / `mouseReleaseEvent`

- `AttributePopupButton(QPushButton)` — button that opens an attribute picker popup. Signal: `currentTextChanged(str)`.
  - `__init__`, `set_options(items)`, `currentText()`, `setCurrentText(text)`, `_refresh_button_text()`, `_show_popup()`

- `CanvasControllerWidget(QFrame)` — base class for a controller drawn on the canvas. Signals: `selected(object, bool)`, `changed()`, `zoneSelected(str)`.
  - `__init__(canvas, controller_type, parent=None)`
  - `is_interacting()` / `set_selected(state)` / `set_edit_mode(state)`
  - `to_dict()` / `load_dict(data)`
  - `_corner_rect(corner)` / `_resolve_handle(pos)` / `_clamp_to_canvas(rect)`
  - `_paint_overlay(painter)` / `_drop_zone_rects()` / `_drop_zone_title(zone)` / `_zone_attribute(zone)` / `_set_zone_attribute(zone, attr_name)` / `_drop_zone_label_vertical(zone)` / `_drop_zone_for_pos(pos)` / `_paint_drop_zones(painter)`
  - `_label_text()` / `_draw_fitted_text(...)` / `_format_attr_display(...)` / `_paint_label(...)`
  - `_interaction_press(pos)` / `_interaction_move(pos)` / `_interaction_release(pos)`
  - `mousePressEvent` / `keyPressEvent` / `mouseMoveEvent` / `mouseReleaseEvent` / `dragEnterEvent` / `dragMoveEvent` / `dragLeaveEvent` / `dropEvent`

- `SliderControllerWidget(CanvasControllerWidget)` — a slider controller.
  - `__init__(canvas, orientation, parent=None)`
  - `to_dict()` / `load_dict(data)` / `set_value(value, emit=True)`
  - `_label_text()` / `_interaction_press` / `_interaction_move` / `_interaction_release`
  - `_drop_zone_rects()` / `_drop_zone_title(zone)` / `_drop_zone_label_vertical(zone)` / `_zone_attribute(zone)` / `_set_zone_attribute(...)`
  - `paintEvent(event)`

- `QuadControllerWidget(CanvasControllerWidget)` — a 2-axis quad controller.
  - `__init__(canvas, parent=None)` / `to_dict()` / `load_dict(data)` / `set_xy(x, y, emit=True)`
  - `_label_text()` / `_interaction_press` / `_interaction_move`
  - `_drop_zone_rects()` / `_drop_zone_title(zone)` / `_drop_zone_label_vertical(zone)` / `_zone_attribute(zone)` / `_set_zone_attribute(...)`
  - `paintEvent(event)`

- `ControllerCanvas(QWidget)` — the canvas that hosts and manipulates controllers. Signals: `controllerSelected(object)`, `controllerChanged()`, `zoneAttributeSelected(str)`.
  - `__init__(parent=None)`
  - `set_snap_enabled(state)` / `snap_rect(rect)`
  - `set_edit_mode(state)`
  - `selected_controller()` / `selected_controllers()` / `last_changed_controller()` / `controllers()`
  - `frame_all_controllers(padding=20)` / `clear_controllers()` / `remove_selected_controllers()`
  - `_set_selected(controller, additive=False)`
  - `_store_edit_start_geometries(initiator)` / `_apply_edit_move_delta(initiator, delta)`
  - `_store_interaction_snapshots()` / `_propagate_interaction_delta(initiator)`
  - `_on_controller_selected(...)` / `_on_controller_changed()` / `_on_zone_selected(attr_name)`
  - `add_controller(controller_type, pos=None)`
  - `serialize()` / `deserialize(items)`
  - `dragEnterEvent` / `dragMoveEvent` / `dropEvent` / `mousePressEvent` / `keyPressEvent` / `paintEvent`

- `ControllerLayoutWindow(QWidget)` — the designer window that ties palette, canvas, and settings together.
  - `__init__(...)` — builds the whole window.
  - `_set_status(text)` / `_current_editor()` / `set_current_editor(editor)`
  - `_controller_attr_names()` / `_populate_combo_with_attrs(...)` / `_populate_attr_combos()` / `_populate_primary_attr_list(attrs)` / `_filter_primary_attr_list(text)` / `_select_primary_attr_in_list(attr_name)`
  - `_on_zone_attribute_selected(attr_name)` / `_on_edit_toggled(checked)`
  - `_on_controller_selected(controller)` / `_refresh_settings_panel_from_selected()`
  - `_on_slider_ui_changed(value)` / `_on_quad_ui_changed(value)`
  - `_plug_for_attr(attr_name)` / `_set_attr_value(attr_name, value)` / `_get_attr_value(attr_name)`
  - `_apply_controller_to_attrs(controller)` / `_refresh_controller_values_from_attrs()` / `_bound_attr_names()`
  - `_kill_script_jobs()` / `_on_external_attr_changed()` / `_rebuild_attr_script_jobs()`
  - `_serialized_layout()` / `_persist_layout_to_container()` / `_load_layout_from_editor()`
  - `_save_layout_to_file()` / `_load_layout_from_file()`
  - `_on_cancel_edit()` / `_on_canvas_changed()` / `_frame_all_controllers_on_open()`
  - `showEvent(event)` / `closeEvent(event)`

---

### `mainWindow.py`

The main editor window and entry point.

**Classes**
- `MainWindow(MayaQWidgetDockableMixin, QMainWindow, EditorUiMixin, SplitSettingsUiMixin, EditorSessionMixin, ShapesFeatureMixin, WorkShapesFeatureMixin, EditorOpsMixin)` — the dockable editor.
  - `__init__(parent=None, version=None)` — calls `super().__init__(parent)` then initializes all editor state, models, proxies, and builds the UI.
  - `_set_status(message, *, warning=False, error=False)` — set the status bar text/color.

**Functions**
- `show() -> MainWindow` — return the existing singleton window or create it (parented to Maya's main window). This is the entry point used by `blue_steel.show()`.

---

### `mainWindowMixin.py`

Shared base and utilities for all feature mixins.

**Classes**
- `MainWindowMixin` — cooperative `super().__init__` terminator (see §4).
  - `__init__(*args, **kwargs)` — swallows leftover constructor args and calls `super().__init__()`.

**Functions**
- `requires_editor(func)` — decorator: if `self.current_editor` is None, show a warning status and return `None` instead of running the handler.
- `pause_active_trackers(func)` — decorator: wrap a mutation with `_stop_active_blendshape_trackers()` / `_start_active_blendshape_trackers()`.
- `target_shape_names(shape_name, selected_names)` — resolve the ordered name list a multi-select handler should act on.

---

### `editorUiMixin.py`

`EditorUiMixin(MainWindowMixin)` — builds and lays out the main window UI and wires up signals.

- `_allow_horizontal_collapse(widget)` — let a widget shrink horizontally.
- `_compact_layout(layout, *, margin=0)` — tighten a layout's margins/spacing.
- `_prepare_toolbar_button(button, *, height=24)` — style a toolbar button.
- `_create_work_tool_button(label, icon)` — create a work-shapes tool button.
- `_set_dock_button_state(docked)` — update the dock/undock button.
- `_dock_to_maya_panel()` — dock the window into a Maya panel.
- `_toggle_docking()` — toggle docked state.
- `_build_ui()` — build the entire window (tabs, panels, toolbars, splitters).
- `showEvent(event)` — first-show hook.
- `_schedule_initial_splitter_layout()` / `_apply_initial_splitter_layout()` — set initial splitter sizes.
- `_apply_primaries_branch_icons()` — apply folder/branch icons.
- `_is_primary_tree_folder_item(item)` / `_update_primary_tree_folder_icon(item)`
- `_on_primaries_item_expanded(item)` / `_on_primaries_item_collapsed(item)` / `_on_primaries_item_clicked(item, column)` / `_on_primaries_item_double_clicked(item, column)`
- `_show_primaries_context_menu(pos)`
- `_on_add_inbetween_requested(primary_name)`
- `_begin_inline_primary_rename(item)` / `_cancel_inline_primary_rename()` / `_commit_inline_primary_rename()`
- `_build_tools_panel(parent_layout)`
- `_create_tool_button(label, icon=None, *, track_enabled=True)`
- `_connect_ui_signals()` — wire all widget signals to handlers.
- `_on_main_splitter_moved(...)` / `_on_editor_splitter_moved(...)` / `resizeEvent(event)`
- `_update_shapes_header_compact_mode()` / `_set_splitter_first_pane_size(splitter, target_width)`
- `_on_split_groups_splitter_moved(...)` / `_set_split_group_buttons_compact_mode(compact)`
- `_on_split_maps_splitter_moved(...)` / `_set_split_map_buttons_compact_mode(compact)`
- `_on_split_map_weights_splitter_moved(...)` / `_set_split_map_weight_buttons_compact_mode(compact)`
- `_on_third_column_splitter_moved(...)`
- `_on_main_tab_changed(index)` / `_is_split_tab_active()`
- `_sync_split_map_edit_mesh_visibility(visible)`
- `_update_third_column_section_minimums()`
- `_force_tools_panel_startup_compact_mode()` / `_sync_tools_panel_compact_mode_from_splitter()` / `_set_tools_panel_compact_mode(compact, *, force=False)` / `_update_tools_button_panel()`
- `_set_split_settings_enabled(enabled)`

---

### `editorSessionMixin.py`

`EditorSessionMixin(MainWindowMixin)` — tracker lifecycle, editor selection, scene events.

- `_clear_trackers_for_scene_operation()` / `_restart_trackers_after_scene_operation()`
- `_setup_scene_editor_tracker()` — create the editor-list tracker.
- `_dispose_tracker(tracker)` (static) / `_clear_scene_editor_tracker()`
- `_setup_blendshape_tracker()` / `_setup_split_map_edit_blendshape_tracker()` / `_clear_split_map_edit_blendshape_tracker()` / `_clear_blendshape_tracker()`
- `_setup_split_attr_grp_tracker()` / `_clear_split_attr_grp_tracker()`
- `_schedule_split_attr_grp_value_refresh(attr, value)` / `_schedule_split_attr_grp_full_refresh(*args)` / `_schedule_split_attr_grp_refresh(*, full)`
- `_reload_split_settings_from_tracker()`
- `_on_split_attr_grp_deleted(node_name)`
- `_reload_editor_menu()` — repopulate the editor combo.
- `_select_first_available_editor()`
- `_on_editor_selected(name)`
- `_on_scene_reset()` / `_on_scene_opened()` / `_on_editor_added(name)` / `_on_editor_removed(name)` / `_on_editor_renamed(new_name, old_name)` / `_on_scene_frame_changed(frame)`
- `_reload_shapes_from_editor()`
- `_update_window_title()`
- `set_current_editor(name)` — switch the active editor (rebuilds UI/models/trackers).
- `refresh_ui()` — refresh everything for the current editor.
- `closeEvent(event)` — cleanup trackers on close.

---

### `shapesFeatureMixin.py`

`ShapesFeatureMixin(MainWindowMixin)` — Shapes tree + Primaries tree behavior and filters.

- `_selected_shape_names_from_shapes_view()` / `_selected_shape_names_from_active_shapes_view()`
- `_select_shape_in_shapes_tree(shape_name, *, ensure_visible=True)`
- `_on_value_drag_state_changed(active)` / `_resort_value_sorted_lists_if_needed()`
- `_apply_shapes_name_sort()`
- `_first_selected_shape_name()`
- `_clear_related_shapes_cache()` / `_get_cached_related_shape_names(shape_name, *, upstream)`
- `_set_directional_shapes_filter_state(...)` / `_set_active_shapes_filter_state(checked)` / `_set_shapes_value_filter_button_state(checked)`
- `_filter_shapes_active(checked)` / `_refresh_active_shapes_filter()` / `_filter_shapes_downstream(checked)` / `_filter_shapes_upstream(checked)`
- `_on_color_filter_swatch_toggled(...)` / `_clear_color_filter_actions()` / `_clear_shapes_filters(keep_selection=False, rebuild_ui=True)`
- `_on_primaries_search_changed(terms)` / `_on_shapes_search_changed(terms)` / `_on_active_shapes_search_changed(terms)`
- `_on_shape_model_data_changed(...)`
- `_on_shapes_item_clicked(item, column)` / `_on_shapes_selection_changed()` / `_on_shapes_toggle_upstream_filter_requested()` / `_on_shapes_double_clicked(item, column)`
- `_show_shapes_context_menu(pos)`
- `_set_shapes_custom_color(shape_names, color_hex)` / `_apply_shape_color_to_views(...)` / `_clear_shapes_custom_color(shape_names)`
- `_on_shapes_item_expanded(item)` / `_on_shapes_item_collapsed(item)` / `_update_shapes_tree_group_icon(item)` / `_on_shapes_tree_data_changed(...)`
- `_on_active_shapes_item_clicked(proxy_index)` / `_on_active_shapes_selection_changed(...)` / `_on_active_shapes_double_clicked(proxy_index)`
- `_select_shape_and_primaries(shape_name, *, focus_shape=False)`
- `_set_shape_pose_from_proxy_index(proxy_model, proxy_index)` / `_set_shape_pose_by_name(shape_name)`
- `_compute_tree_max_name_width(tree)` / `_compute_filtered_max_name_width(view, model)` / `_update_delegate_name_columns()`
- `_rebuild_shapes_tree()` / `_sync_shapes_tree_items_from_source_rows(...)`
- `_selected_primary_tree_names()` / `_selected_split_primary_names()`
- `_on_primary_drop_list_dropped(names)` / `_on_primary_drop_remove_requested(names)` / `_fill_primary_drop_list_from_active()`
- `_selected_names_from_list_view(view, model)` / `_selected_active_shape_names()` / `_selected_primary_drop_shape_names()`
- `_on_display_heat_map_toggled(checked)` / `_is_heat_map_switch_active()` / `_set_heat_map_target_for_editor(...)` / `_clear_heat_map_target_for_editor()` / `_update_heat_map_target_from_shapes_selection()` / `_update_heat_map_target_from_active_shapes_selection()` / `_update_heat_map_target_from_work_shapes_selection()`
- `_refresh_primary_folder_sort_values()` / `_sort_primaries_tree()` / `_iter_primary_tree_leaves()` / `_get_primary_tree_value(shape_name)`
- `_on_primary_tree_slider_changed(shape_name, value)` / `_on_primaries_tree_data_changed(...)` / `_sync_primary_tree_slider(shape_name, value)` / `_rebuild_primaries_tree()` / `_apply_primaries_tree_filter(terms)`
- `_on_primaries_selection_changed(...)` / `_on_exclusive_filter_toggled(checked)` / `_apply_primary_selection_shapes_filter(selected_names)`
- `_on_primary_value_committed(shape_name, value)` / `_on_shape_value_changed(shape_id, shape_name, value)` / `_on_shape_structure_changed(...)`
- `_on_shapes_mute_toggle_requested(shape_name, state)` / `_on_active_shapes_mute_toggle_requested(...)` / `_on_primary_drop_mute_toggle_requested(...)` / `_apply_shape_mute_toggle(...)`
- `_on_shapes_lock_toggle_requested(...)` / `_on_active_shapes_lock_toggle_requested(...)` / `_on_primary_drop_lock_toggle_requested(...)` / `_apply_shape_lock_toggle(...)`
- `_on_shape_renamed(...)` / `_on_blendshape_deleted(blendshape_name)` / `_update_info_labels()`

---

### `splitSettingsUiMixin.py`

`SplitSettingsUiMixin(MainWindowMixin)` — Split tab UI and split maps/groups/weights logic.

- `_build_split_settings_tab(parent_widget)` — build the Split tab.
- `_reload_split_settings_from_editor()`
- `_refresh_split_primary_assignments()` / `_refresh_split_groups()` / `_refresh_split_maps()` / `_refresh_split_map_weights(split_map_name=None)` / `_sync_split_map_weight_slider_values()`
- `_on_split_map_weight_value_changed(...)`
- `_selected_split_group_name()` / `_selected_split_map_name()` / `_current_edit_split_map_name()` / `_selected_split_map_weight_area()`
- `_on_split_map_weight_selection_changed(current, previous)` / `_update_split_map_weight_operation_buttons()`
- `_on_split_primary_search_changed(terms)` / `_on_split_primaries_tree_data_changed(...)`
- `_on_primary_split_group_changed(group_name, primary_names)`
- `_show_split_primaries_context_menu(pos)`
- `_split_selected_shapes(primary_names)`
- `_on_split_group_map_selected(split_map_name)` / `_on_split_group_selection_changed(group_name)` / `_on_split_map_selection_changed(split_map_name)`
- `_check_split_maps_normalization(split_map_name=None)`
- `_show_split_maps_context_menu(pos)` / `_show_split_map_weights_context_menu(pos)`
- `_run_split_weight_map_operation(method_name, status_verb, weight_name="")`
- `_on_normalize_split_map_weights_requested()`
- `_on_create_split_group_clicked()` / `_on_remove_split_group_clicked()` / `_on_rename_split_group_clicked()`
- `_on_split_group_maps_changed(split_groups)` / `_on_split_group_map_dragged_out(group_name, map_name)`
- `_on_add_split_map_clicked()` / `_on_rename_split_map_clicked()` / `_on_remove_split_map_clicked()`
- `_on_edit_split_map_clicked()` / `_on_normalize_edit_split_map_weights_clicked()` / `_on_apply_edit_split_map_clicked()` / `_on_cancel_edit_split_map_clicked()`
- `_on_add_split_map_weight_clicked()` / `_on_rename_split_map_weight_clicked()` / `_on_paint_split_map_weight_mask_clicked()` / `_on_remove_split_map_weight_clicked()`
- `_on_split_map_edit_weight_value_changed(...)` / `_on_split_map_edit_structure_changed(...)` / `_on_split_map_edit_blendshape_deleted(...)`

---

### `workShapesFeatureMixin.py`

`WorkShapesFeatureMixin(MainWindowMixin)` — Work-shapes panel behavior.

- `_selected_work_shape_names()` / `_first_selected_work_shape_name()` / `_select_work_shape(shape_name)`
- `_on_work_shapes_selection_changed(...)` / `_update_work_shape_button_panel()`
- `_stop_active_blendshape_trackers()` / `_start_active_blendshape_trackers()`
- `_reload_work_shapes_from_editor()`
- `_on_add_work_shape_clicked()` / `_on_remove_work_shapes_clicked()` / `_on_paint_work_shape_clicked()` / `_on_apply_work_shapes_clicked()`
- `_on_work_shape_edit_mode_toggle_requested(shape_name, state)` / `_on_toggle_work_shape_edit_mode(shape_name=None)`
- `_on_work_shapes_double_clicked(model_index)`
- `_on_work_shape_drop_received(work_shape_name, source_shape_name)` / `_on_work_shape_break_link_requested(work_shape_name)`
- `_has_copied_work_weight_map_values()`
- `_on_work_shape_duplicate_requested(...)` / `_on_work_shape_extract_requested(...)` / `_on_work_shape_connected_mesh_requested(...)`
- `_on_work_shape_copy_weights_requested(...)` / `_on_work_shape_paste_weights_requested(...)` / `_on_work_shape_paste_inverted_weights_requested(...)` / `_on_work_shape_add_copied_weights_requested(...)` / `_on_work_shape_subtract_copied_weights_requested(...)` / `_on_work_shapes_normalize_weights_requested(...)` / `_on_work_shape_clear_weights_requested(...)`
- `_begin_inline_workshape_rename(model_index)` / `_cancel_inline_workshape_rename()` / `_commit_inline_workshape_rename()`
- `_capture_linked_drag_state()` / `_on_linked_drag_started()` / `_on_linked_drag_selection_context(can_propagate)` / `_on_linked_drag_ended()` / `_on_linked_drag_delta(delta_value)`
- `_on_work_shape_value_committed(shape_name, value)` / `_on_work_shape_value_changed(shape_id, shape_name, value)` / `_on_work_shape_structure_changed(...)` / `_on_work_sculpt_target_changed(target_id, shape_name)`
- `_on_work_shapes_mute_toggle_requested(shape_name, state)` / `_on_work_blendshape_target_connection_changed(target_id, connected)` / `_on_work_blendshape_driver_connection_changed(target_id, connected)` / `_on_work_blendshape_deleted(blendshape_name)`

---

### `editorOpsMixin.py`

`EditorOpsMixin(MainWindowMixin)` — menu-bar actions and import/export/utility operations.

- `_show_controller_layout_window()` / `_editor_for_controller_layout()` / `_clear_controller_layout_window_ref()`
- `commit_selected()` / `add_selected_at_current_pose()` / `_on_add_primary_clicked()`
- `remove_selected_shapes(shape_names=None)` / `remove_shapes_from_focused_view()` / `remove_selected_primaries()`
- `toggle_mute_selected_shapes()` / `unmute_all_shapes()` / `unlock_all_shapes()`
- `select_face_ctrl()` / `zero_all()` / `rename_selected_mesh()`
- `extract_selected(selected_shapes)` / `duplicate_at_value()`
- `launch_mmtools()` / `_on_toggle_hud_clicked()` / `compare_shapes_debug()`
- `_create_menu_bar()` — build the menu bar and wire actions.
- `_create_new_editor()` / `_import_objs()` / `_import_shapes_from_blendshape_node(absolute_delta=False)` / `_import_split_data()`
- `_on_create_split_shapes_editor_requested()` / `_export_split_data()` / `_export_objs()` / `_export_shapes_as_blendshape_node(absolute_delta=False)`
- `_rename_current_editor()` / `_on_fix_invisible_blendshapes_requested()`
- `_toggle_exploded_container_action_state(collapsed)` / `_toggle_node_editor_container_view()`
- `_on_connect_simplex_controller_requested()` / `_on_simplex_converter_requested()` / `_on_prepare_for_publishing_requested()`
- `show_about()`

---

## 4. Cross-cutting patterns

### Cooperative `super().__init__` / `MainWindowMixin`

`MainWindow` uses multiple inheritance (`MayaQWidgetDockableMixin`, `QMainWindow`,
and six feature mixins). Its `__init__` calls `super().__init__(parent)`, which
walks the whole MRO. `MainWindowMixin.__init__(*args, **kwargs)` sits at the end
of the chain, swallows any leftover constructor arguments, and calls
`super().__init__()` so the chain ends at `object.__init__()` instead of raising
`TypeError`. All six feature mixins inherit from it; none define their own
`__init__`.

### Decorators / helpers (`mainWindowMixin.py`)

- `@requires_editor` — guard handlers that need an active editor.
- `@pause_active_trackers` — pause tracker callbacks around mutations.
- `target_shape_names(...)` — resolve the list of names a multi-select handler acts on.

### Slider drag (delegate + view)

A slider drag is split between the view and the delegate:

- `views.py::SliderDragViewMixin` forwards mouse press/move/release to the
  delegate's `external_drag_start/move/end` API and checks `is_drag_active()`.
- `delegates.py::SliderItemDelegate` owns the drag math (`_start_drag`,
  `_end_drag`, `_set_drag_value_from_pos`, `_resolve_drag_targets`) and installs
  a global `_DragEventFilter` so dragging keeps working when the cursor leaves
  the view. It wraps each drag in one undo chunk.
- The view checks for the delegate API via duck typing (`_is_slider_delegate`)
  rather than `isinstance`, so package reloads don't break identity checks.

### Reload-safe duck typing

`views.py::_is_slider_delegate(delegate)` checks `hasattr(delegate,
"external_drag_start") and hasattr(delegate, "is_drag_active")` instead of
`isinstance(delegate, SliderItemDelegate)`. This survives `importlib.reload`,
which recreates class objects and would otherwise break `isinstance`.

### Qt event overrides & `OptionRect`

Qt event handlers are named `mousePressEvent`, `keyPressEvent`, etc., which trip
Python linters — they carry `# noqa: N802`. `OptionRect` (in `qt.py`) is a cheap
`QStyleOptionViewItem` stand-in used by delegate geometry helpers that only need
`rect` and `fontMetrics`.

### Signal summary (important ones)

| Signal | Owner | Purpose |
|---|---|---|
| `primaryValueCommitted(str, float)` | `ShapeItemsModel` | A primary value was committed. |
| `valueCommitted(str, float)` | `WorkShapeItemsModel` | A work-shape value was committed. |
| `valueDragStarted/Ended/Delta(float)/SelectionContext(bool)` | `SliderItemDelegate` | Slider drag lifecycle. |
| `muteToggleRequested(str, bool)` / `lockToggleRequested(str, bool)` | `SliderItemDelegate` | Icon click → mute/lock. |
| `connectedMeshRequested(str)` | `SliderItemDelegate` | Connected-mesh icon clicked. |
| `workEditModeToggleRequested(str, bool)` | `SliderItemDelegate` | Work-edit icon clicked. |
| `searchChanged(object)` | `TokenSearchBar` | Search text/tokens changed. |
| `currentMapChanged(str)` | `SplitMapsTree` | Selected split map changed. |
| `mapSelected/mapsChanged/mapDraggedOut/groupSelected` | `SplitGroupsTree` | Split group tree interactions. |
| `assignmentChanged(str, object)` | `SplitPrimaryAssignmentsView` | Primary→group assignment changed. |
| `submitted()` / `canceled()` | `InlineWorkshapeRenameEditor` | Inline rename committed/canceled. |

---

## 5. Quick "where to look" index

| Task | Files / methods |
|---|---|
| Open/focus the editor | `mainWindow.py::show()`, `blue_steel/__init__.py` |
| Build the window layout | `editorUiMixin.py::_build_ui`, `_connect_ui_signals` |
| Add/remove/rename/commit shapes | `editorOpsMixin.py`, `api/editor.py` |
| Slider drag (value scrub) | `delegates.py::SliderItemDelegate` (`external_drag_*`, `_start_drag`, `_end_drag`), `views.py::SliderDragViewMixin` |
| Icon clicks (mute/lock/connected/edit) | `delegates.py` icon-rect helpers + signals, `views.py::_resolve_icon_click` |
| Search / filter / color / active-only | `widgets.py::TokenSearchBar`, `models.py::ShapesFilterProxyModel`, `shapesFeatureMixin.py` |
| Primaries tree | `views.py::PrimaryTreeWidget`, `shapesFeatureMixin.py::_rebuild_primaries_tree` |
| Work shapes | `models.py::WorkShapeItemsModel`, `workShapesFeatureMixin.py` |
| Split maps/groups/weights | `splitSettingsUiMixin.py`, `widgets.py::SplitMapsTree/SplitGroupsTree` |
| Controller layout designer | `controllerLayoutWindow.py` |
| Scene/editor lifecycle & trackers | `editorSessionMixin.py`, `api/trackers.py` |
| Status bar / window title | `mainWindow.py::_set_status`, `editorSessionMixin.py::_update_window_title` |
