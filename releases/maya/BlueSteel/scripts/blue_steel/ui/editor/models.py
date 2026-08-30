"""Editor data models and filter proxies.

This module holds the shared shape source model, the work-shape model, and the
proxy models that present filtered views of the source model. It is extracted
from the monolithic ``mainWindow`` module so model logic stays UI-independent.

Example:
    >>> from blue_steel.ui.editor import models
    >>> model = models.ShapeItemsModel()
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Set

from maya import cmds

from ...api.editor import BlueSteelEditor
from .qt import (
    QAbstractListModel,
    QColor,
    QModelIndex,
    QSortFilterProxyModel,
    Qt,
    QTimer,
    QWidget,
    Signal,
    shape_custom_color_to_qcolor,
)


def normalized_search_terms(terms) -> List[str]:
    """Normalize search terms into a list of stripped, lowercase strings."""
    if isinstance(terms, str):
        terms = [terms]
    return [str(term).strip().lower() for term in (terms or []) if str(term).strip()]



class ShapeItemsModel(QAbstractListModel):
    """Shared source model containing all shape rows for the active editor.

    Notes:
    - `PrimaryShape` rows are user-editable.
    - Non-primary rows are read-only in UI.

    Example:
        >>> model = ShapeItemsModel()
        >>> model.rebuild_from_editor(editor)
        >>> model.rowCount()
        124
    """

    NameRole = Qt.UserRole + 1
    TypeRole = Qt.UserRole + 2
    ValueRole = Qt.UserRole + 3
    MutedRole = Qt.UserRole + 4
    LevelRole = Qt.UserRole + 5
    PrimariesRole = Qt.UserRole + 6
    EditableRole = Qt.UserRole + 7
    IsHeaderRole = Qt.UserRole + 8
    HeaderLevelRole = Qt.UserRole + 9
    HeaderCollapsedRole = Qt.UserRole + 10
    UpstreamRelatedRole = Qt.UserRole + 11
    DownstreamRelatedRole = Qt.UserRole + 12
    LockedRole = Qt.UserRole + 13
    LockIconVisibleRole = Qt.UserRole + 14
    ColorRole = Qt.UserRole + 15

    primaryValueCommitted = Signal(str, float)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._editor: Optional[BlueSteelEditor] = None
        self._rows: List[dict] = []
        self._row_by_name: Dict[str, int] = {}
        self._upstream_related_names: Set[str] = set()
        self._downstream_related_names: Set[str] = set()

    def set_editor(self, editor: Optional[BlueSteelEditor]) -> None:
        """Attach editor instance used for write operations."""
        self._editor = editor

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        if parent.isValid():
            return 0
        return len(self._rows)

    def roleNames(self):  # noqa: N802
        return {
            self.NameRole: b"name",
            self.TypeRole: b"type",
            self.ValueRole: b"value",
            self.MutedRole: b"muted",
            self.LevelRole: b"level",
            self.PrimariesRole: b"primaries",
            self.EditableRole: b"editable",
            self.IsHeaderRole: b"isHeader",
            self.HeaderLevelRole: b"headerLevel",
            self.HeaderCollapsedRole: b"headerCollapsed",
            self.UpstreamRelatedRole: b"upstreamRelated",
            self.DownstreamRelatedRole: b"downstreamRelated",
            self.LockedRole: b"locked",
            self.LockIconVisibleRole: b"lockIconVisible",
            self.ColorRole: b"customColor",
        }

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self._rows)):
            return None

        row = self._rows[index.row()]
        if role in (Qt.DisplayRole, self.NameRole):
            return row["name"]
        if role == self.TypeRole:
            return row["type"]
        if role == self.ValueRole:
            return row["value"]
        if role == self.MutedRole:
            return row["muted"]
        if role == self.LevelRole:
            return row["level"]
        if role == self.PrimariesRole:
            return row["primaries"]
        if role == self.EditableRole:
            return row["editable"]
        if role == self.IsHeaderRole:
            return bool(row.get("is_header", False))
        if role == self.HeaderLevelRole:
            return int(row.get("header_level", row.get("level", 0)))
        if role == self.UpstreamRelatedRole:
            name = str(row.get("name", ""))
            return name in self._upstream_related_names
        if role == self.DownstreamRelatedRole:
            name = str(row.get("name", ""))
            return name in self._downstream_related_names
        if role == self.LockedRole:
            return bool(row.get("locked", False))
        if role == self.LockIconVisibleRole:
            return bool(row.get("lock_icon_visible", False))
        if role == self.ColorRole:
            return row.get("color", None)
        if role == Qt.ToolTipRole:
            return row.get("tooltip", None)
        return None

    def setData(self, index: QModelIndex, value, role: int = Qt.EditRole) -> bool:  # noqa: N802
        if not index.isValid() or not (0 <= index.row() < len(self._rows)):
            return False

        row = self._rows[index.row()]
        if role == Qt.ToolTipRole:
            row["tooltip"] = value
            self.dataChanged.emit(index, index, [Qt.ToolTipRole])
            return True

        if role not in (Qt.EditRole, self.ValueRole):
            return False
        if not row["editable"] or self._editor is None:
            return False

        try:
            new_value = float(value)
        except (TypeError, ValueError):
            return False

        new_value = max(0.0, min(1.0, round(new_value, 4)))
        if abs(new_value - row["value"]) <= 1e-6:
            return False

        try:
            self._editor.set_primary_shape_value(row["shape"], new_value)
        except Exception as exc:
            cmds.warning(f"Failed setting shape '{row['name']}': {exc}")
            return False

        row["value"] = new_value
        self.dataChanged.emit(index, index, [self.ValueRole, Qt.DisplayRole])
        self.primaryValueCommitted.emit(row["name"], new_value)
        return True

    def flags(self, index: QModelIndex):
        if not index.isValid():
            return Qt.NoItemFlags
        row = self._rows[index.row()]
        if bool(row.get("is_header", False)):
            return Qt.ItemIsEnabled | Qt.ItemIsSelectable
        flags = Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsDragEnabled
        if row["editable"]:
            flags |= Qt.ItemIsEditable
        return flags

    def rebuild_from_editor(self, editor: Optional[BlueSteelEditor]) -> None:
        """Rebuild full rows from editor network and current blendshape values.

        Example:
            >>> model.rebuild_from_editor(editor)
            >>> names = [model.data(model.index(i, 0), model.NameRole) for i in range(model.rowCount())]
        """
        self.beginResetModel()
        self._rows = []
        self._row_by_name = {}
        self._upstream_related_names.clear()
        self._downstream_related_names.clear()
        self._editor = editor

        if editor is None:
            self.endResetModel()
            return

        editor.sync_network()
        all_shapes = editor.get_all_shapes().sort_for_display()
        weights = editor.blendshape.get_weights() or set()
        weight_by_name = {str(weight): weight for weight in weights}
        locked_shape_names = {str(name) for name in (getattr(editor, "locked_shapes", set()) or set())}
        custom_colors = editor.read_custom_shapes_colors() or {}

        valid_shapes = [shape for shape in all_shapes if shape.type != "InvalidShape"]
        level_counts: Dict[int, int] = {}
        for shape in valid_shapes:
            level = int(shape.level)
            level_counts[level] = level_counts.get(level, 0) + 1

        current_level = None
        for shape in valid_shapes:
            level = int(shape.level)
            if current_level != level:
                header_name = f"Level {level} ({level_counts.get(level, 0)})"
                self._rows.append(
                    {
                        "name": header_name,
                        "type": "LevelHeader",
                        "value": 0.0,
                        "muted": False,
                        "level": level,
                        "primaries": tuple(),
                        "editable": False,
                        "shape": None,
                        "is_header": True,
                        "header_level": level,
                        "locked": False,
                        "lock_icon_visible": False,
                    }
                )
                current_level = level

            weight = weight_by_name.get(str(shape))
            value = editor.blendshape.get_weight_value(weight) if weight is not None else 0.0
            primaries = tuple(str(primary) for primary in shape.primaries)
            custom_color = custom_colors.get(str(shape))
            row_data = {
                "name": str(shape),
                "type": shape.type,
                "value": float(value),
                "muted": bool(getattr(shape, "muted", False)),
                "level": level,
                "primaries": primaries,
                "editable": shape.type == "PrimaryShape",
                "shape": shape,
                "is_header": False,
                "header_level": level,
                "locked": str(shape) in locked_shape_names,
                "lock_icon_visible": shape.type != "PrimaryShape",
                "color": shape_custom_color_to_qcolor(custom_color),
            }
            self._row_by_name[row_data["name"]] = len(self._rows)
            self._rows.append(row_data)

        self.endResetModel()

    def set_related_shape_names(self, upstream_names: Sequence[str], downstream_names: Sequence[str]) -> None:
        """Update related-shape highlight state and notify changed rows only."""
        new_upstream = {str(name) for name in (upstream_names or []) if name}
        new_downstream = {str(name) for name in (downstream_names or []) if name}

        if new_upstream == self._upstream_related_names and new_downstream == self._downstream_related_names:
            return

        changed_names = (
            self._upstream_related_names
            .union(self._downstream_related_names)
            .union(new_upstream)
            .union(new_downstream)
        )
        self._upstream_related_names = new_upstream
        self._downstream_related_names = new_downstream

        for shape_name in changed_names:
            row_index = self._row_by_name.get(shape_name)
            if row_index is None:
                continue
            model_index = self.index(row_index, 0)
            self.dataChanged.emit(
                model_index,
                model_index,
                [self.UpstreamRelatedRole, self.DownstreamRelatedRole, Qt.DisplayRole],
            )

    def get_name(self, source_row: int) -> Optional[str]:
        if 0 <= source_row < len(self._rows):
            return self._rows[source_row]["name"]
        return None

    def set_shape_value_from_tracker(self, shape_name: str, value: float) -> None:
        """Fast-path value update from tracker signal without writing back to Maya."""
        row_index = self._row_by_name.get(shape_name)
        if row_index is None:
            return
        clamped_value = max(0.0, min(1.0, float(value)))
        row = self._rows[row_index]
        if abs(row["value"] - clamped_value) <= 1e-6:
            return
        row["value"] = clamped_value
        model_index = self.index(row_index, 0)
        self.dataChanged.emit(model_index, model_index, [self.ValueRole, Qt.DisplayRole])

    def set_shape_muted_state_local(self, shape_name: str, muted: bool) -> None:
        """Update muted flag in-model without forcing a full rebuild."""
        row_index = self._row_by_name.get(shape_name)
        if row_index is None:
            return
        row = self._rows[row_index]
        target = bool(muted)
        if bool(row.get("muted", False)) == target:
            return
        row["muted"] = target
        model_index = self.index(row_index, 0)
        self.dataChanged.emit(model_index, model_index, [self.MutedRole, Qt.DisplayRole])

    def set_shape_locked_state_local(self, shape_name: str, locked: bool) -> None:
        """Update locked flag in-model without forcing a full rebuild."""
        row_index = self._row_by_name.get(shape_name)
        if row_index is None:
            return
        row = self._rows[row_index]
        target = bool(locked)
        if bool(row.get("locked", False)) == target:
            return
        row["locked"] = target
        model_index = self.index(row_index, 0)
        self.dataChanged.emit(model_index, model_index, [self.LockedRole, Qt.DisplayRole])

    def set_shape_color_local(self, shape_name: str, color: Optional[QColor]) -> None:
        """Update the custom text color in-model without forcing a full rebuild."""
        row_index = self._row_by_name.get(shape_name)
        if row_index is None:
            return
        row = self._rows[row_index]
        row["color"] = color
        model_index = self.index(row_index, 0)
        self.dataChanged.emit(model_index, model_index, [self.ColorRole, Qt.DisplayRole])

    def refresh_locked_states_from_editor(self) -> int:
        """Sync lock flags for all non-header rows from editor lock state."""
        if self._editor is None:
            return 0

        locked_names = {str(name) for name in (getattr(self._editor, "locked_shapes", set()) or set())}
        changed_count = 0
        for row_index, row in enumerate(self._rows):
            if bool(row.get("is_header", False)):
                continue
            shape_name = str(row.get("name", ""))
            target = shape_name in locked_names
            if bool(row.get("locked", False)) == target:
                continue
            row["locked"] = target
            model_index = self.index(row_index, 0)
            self.dataChanged.emit(model_index, model_index, [self.LockedRole, Qt.DisplayRole])
            changed_count += 1

        return changed_count

    def get_shape_value(self, shape_name: str) -> Optional[float]:
        row_index = self._row_by_name.get(shape_name)
        if row_index is None:
            return None
        return float(self._rows[row_index].get("value", 0.0))

    def set_shape_value_by_name(self, shape_name: str, value: float) -> bool:
        row_index = self._row_by_name.get(shape_name)
        if row_index is None:
            return False
        return self.setData(self.index(row_index, 0), value, self.ValueRole)

    def refresh_values_from_editor(self) -> List[tuple]:
        """Pull current blendshape values and update rows without rebuilding structure.

        Returns a list of changed rows as tuples: (name, value, is_primary).
        """
        if self._editor is None:
            return []

        weights = self._editor.blendshape.get_weights() or set()
        weight_by_name = {str(weight): weight for weight in weights}
        changed: List[tuple] = []

        for row_index, row in enumerate(self._rows):
            if bool(row.get("is_header", False)):
                continue
            weight = weight_by_name.get(row.get("name", ""))
            new_value = self._editor.blendshape.get_weight_value(weight) if weight is not None else 0.0
            clamped_value = max(0.0, min(1.0, float(new_value)))
            if abs(float(row.get("value", 0.0)) - clamped_value) <= 1e-6:
                continue
            row["value"] = clamped_value
            changed.append((row_index, str(row.get("name", "")), clamped_value, bool(row.get("editable", False))))

        if changed:
            # One range emit so handlers process the whole batch once.
            self.dataChanged.emit(
                self.index(changed[0][0], 0),
                self.index(changed[-1][0], 0),
                [self.ValueRole, Qt.DisplayRole],
            )

        return [(name, value, is_primary) for _row, name, value, is_primary in changed]



class PrimaryShapesProxyModel(QSortFilterProxyModel):
    """Proxy model for primary-only listing with text filtering."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._search_terms: List[str] = []
        self.setDynamicSortFilter(False)

    def set_search_terms(self, terms) -> None:
        self._search_terms = normalized_search_terms(terms)
        self.invalidateFilter()

    def set_search_text(self, text: str) -> None:
        self.set_search_terms([text])

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:  # noqa: N802
        model = self.sourceModel()
        if model is None:
            return False
        index = model.index(source_row, 0, source_parent)
        shape_type = model.data(index, ShapeItemsModel.TypeRole)
        if shape_type != "PrimaryShape":
            return False
        if not self._search_terms:
            return True
        name = (model.data(index, ShapeItemsModel.NameRole) or "").lower()
        return any(term in name for term in self._search_terms)



class ShapesFilterProxyModel(QSortFilterProxyModel):
    """Proxy model for shapes list with text and selected-primary filtering.

    Example:
        >>> proxy.set_selected_primaries({"jawOpen", "lipCornerPuller"})
        >>> proxy.set_search_text("lip")
    """

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._search_terms: List[str] = []
        self._selected_primaries: Set[str] = set()
        self._visible_names: Optional[Set[str]] = None
        self._active_only = False
        self._collapsed_levels: Set[int] = set()
        self._color_filter_hexes: Optional[Set[str]] = None
        self._color_filter_include_no_color = False
        self._color_filter_enabled = False
        self._sort_order = Qt.AscendingOrder
        self._level_visible_count_cache: Dict[int, int] = {}
        self._with_value_epsilon = 1e-6
        self._filter_invalidate_timer = QTimer(self)
        self._filter_invalidate_timer.setSingleShot(True)
        self._filter_invalidate_timer.setInterval(33)
        self._filter_invalidate_timer.timeout.connect(self.invalidateFilter)
        self.setDynamicSortFilter(False)

    def setSourceModel(self, sourceModel) -> None:  # noqa: N802
        old_model = self.sourceModel()
        if old_model is not None:
            try:
                old_model.modelReset.disconnect(self._invalidate_level_count_cache)
                old_model.rowsInserted.disconnect(self._invalidate_level_count_cache)
                old_model.rowsRemoved.disconnect(self._invalidate_level_count_cache)
                old_model.layoutChanged.disconnect(self._invalidate_level_count_cache)
                old_model.dataChanged.disconnect(self._on_source_data_changed)
            except Exception:
                pass

        super().setSourceModel(sourceModel)
        self._invalidate_level_count_cache()

        new_model = self.sourceModel()
        if new_model is not None:
            new_model.modelReset.connect(self._invalidate_level_count_cache)
            new_model.rowsInserted.connect(self._invalidate_level_count_cache)
            new_model.rowsRemoved.connect(self._invalidate_level_count_cache)
            new_model.layoutChanged.connect(self._invalidate_level_count_cache)
            new_model.dataChanged.connect(self._on_source_data_changed)

    def _invalidate_level_count_cache(self, *_args) -> None:
        self._level_visible_count_cache.clear()

    def _on_source_data_changed(self, _top_left, _bottom_right, roles) -> None:
        self._invalidate_level_count_cache()
        # Re-filter only for proxies where row visibility depends on values.
        # This is mainly the active-only panel; throttle to keep slider drags smooth.
        if self._color_filter_enabled and (
            (not roles) or (ShapeItemsModel.ColorRole in roles) or (Qt.DisplayRole in roles)
        ):
            self._filter_invalidate_timer.start()
            return
        if not self._active_only:
            return
        if (not roles) or (ShapeItemsModel.ValueRole in roles) or (Qt.DisplayRole in roles):
            self._filter_invalidate_timer.start()

    def _is_value_sort_mode(self) -> bool:
        return self.sortRole() == ShapeItemsModel.ValueRole

    def is_with_value_shape(self, model, index: QModelIndex) -> bool:
        if not index.isValid() or bool(model.data(index, ShapeItemsModel.IsHeaderRole)):
            return False
        value = float(model.data(index, ShapeItemsModel.ValueRole) or 0.0)
        return value > self._with_value_epsilon

    def _with_value_header_source_index(self, model) -> QModelIndex:
        for row in range(model.rowCount()):
            idx = model.index(row, 0)
            if bool(model.data(idx, ShapeItemsModel.IsHeaderRole)):
                return idx
        return QModelIndex()

    def _has_visible_with_value_shapes(self, model) -> bool:
        for row in range(model.rowCount()):
            idx = model.index(row, 0)
            if not self._shape_row_matches_filters(model, idx):
                continue
            if self.is_with_value_shape(model, idx):
                return True
        return False

    def sort(self, column: int, order: Qt.SortOrder = Qt.AscendingOrder) -> None:  # noqa: N802
        """Track requested sort order while keeping header pinning deterministic."""
        self._sort_order = order
        # Run proxy sort in ascending mode; lessThan applies requested direction.
        super().sort(column, Qt.AscendingOrder)

    def set_search_terms(self, terms) -> None:
        self._search_terms = normalized_search_terms(terms)
        self._invalidate_level_count_cache()
        self.invalidateFilter()

    def set_search_text(self, text: str) -> None:
        self.set_search_terms([text])

    def set_selected_primaries(self, primary_names: Sequence[str]) -> None:
        self._selected_primaries = set(primary_names)
        self._invalidate_level_count_cache()
        self.invalidateFilter()

    def set_visible_names(self, shape_names: Optional[Sequence[str]]) -> None:
        if shape_names is None:
            self._visible_names = None
        else:
            self._visible_names = set(str(name) for name in shape_names)
        self._invalidate_level_count_cache()
        self.invalidateFilter()

    def set_active_only(self, active_only: bool) -> None:
        self._active_only = bool(active_only)
        self._invalidate_level_count_cache()
        self.invalidateFilter()

    def set_color_filter(self, color_hexes: Optional[Set[str]], include_no_color: bool = False) -> None:
        """Filter rows by custom shape colors; pass color_hexes=None to disable."""
        if color_hexes is None:
            self._color_filter_enabled = False
            self._color_filter_hexes = None
            self._color_filter_include_no_color = False
        else:
            self._color_filter_enabled = True
            self._color_filter_hexes = {QColor(str(color_hex)).name() for color_hex in color_hexes}
            self._color_filter_include_no_color = bool(include_no_color)
        self._invalidate_level_count_cache()
        self.invalidateFilter()

    def color_filter_active(self) -> bool:
        return self._color_filter_enabled

    def toggle_level_collapsed(self, level: int) -> None:
        level = int(level)
        if level in self._collapsed_levels:
            self._collapsed_levels.remove(level)
        else:
            self._collapsed_levels.add(level)
        self.invalidateFilter()

    def _shape_row_matches_filters(self, model, index: QModelIndex) -> bool:
        """Return True when a non-header row matches search/primary filters."""
        if not index.isValid():
            return False
        if bool(model.data(index, ShapeItemsModel.IsHeaderRole)):
            return False

        name = model.data(index, ShapeItemsModel.NameRole) or ""
        if self._visible_names is not None and name not in self._visible_names:
            return False
        if self._search_terms and not any(term in name.lower() for term in self._search_terms):
            return False
        if self._active_only:
            value = float(model.data(index, ShapeItemsModel.ValueRole) or 0.0)
            if value <= self._with_value_epsilon:
                return False
        if self._color_filter_enabled:
            row_color = model.data(index, ShapeItemsModel.ColorRole)
            if isinstance(row_color, QColor) and row_color.isValid():
                if row_color.name() not in (self._color_filter_hexes or set()):
                    return False
            elif not self._color_filter_include_no_color:
                return False

        if not self._selected_primaries:
            return True

        primaries = model.data(index, ShapeItemsModel.PrimariesRole) or tuple()
        return bool(self._selected_primaries.intersection(set(primaries)))

    def _count_visible_shapes_for_level(self, model, level: int) -> int:
        """Count rows matching active filters for one level (ignores collapse state)."""
        cache_key = (level, self._is_value_sort_mode())
        cached = self._level_visible_count_cache.get(cache_key)
        if cached is not None:
            return cached

        count = 0
        for row in range(model.rowCount()):
            idx = model.index(row, 0)
            row_level = int(model.data(idx, ShapeItemsModel.LevelRole) or 0)
            if row_level != level:
                continue
            if not self._shape_row_matches_filters(model, idx):
                continue
            # In value-sort mode, rows with active values are moved to the top
            # "With Value" section and should not be counted under level headers.
            if self._is_value_sort_mode() and self.is_with_value_shape(model, idx):
                continue
            count += 1
        self._level_visible_count_cache[cache_key] = count
        return count

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:  # noqa: N802
        model = self.sourceModel()
        if model is None:
            return False
        index = model.index(source_row, 0, source_parent)

        is_header = bool(model.data(index, ShapeItemsModel.IsHeaderRole))
        level = int(model.data(index, ShapeItemsModel.LevelRole) or 0)
        is_value_sort = self._is_value_sort_mode()
        if is_header:
            if is_value_sort and index == self._with_value_header_source_index(model):
                return self._has_visible_with_value_shapes(model)
            return self._count_visible_shapes_for_level(model, level) > 0
        if is_value_sort and self.is_with_value_shape(model, index):
            return self._shape_row_matches_filters(model, index)
        if level in self._collapsed_levels:
            return False
        return self._shape_row_matches_filters(model, index)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):  # noqa: N802
        if not index.isValid():
            return super().data(index, role)

        source_index = self.mapToSource(index)
        if not source_index.isValid():
            return super().data(index, role)

        if bool(source_index.data(ShapeItemsModel.IsHeaderRole)):
            level = int(source_index.data(ShapeItemsModel.LevelRole) or 0)
            is_with_value_header = (
                self._is_value_sort_mode()
                and source_index == self._with_value_header_source_index(self.sourceModel())
            )
            if role in (Qt.DisplayRole, ShapeItemsModel.NameRole):
                if is_with_value_header:
                    count = 0
                    for row in range(self.sourceModel().rowCount()):
                        idx = self.sourceModel().index(row, 0)
                        if self._shape_row_matches_filters(self.sourceModel(), idx) and self.is_with_value_shape(self.sourceModel(), idx):
                            count += 1
                    return f"With Value ({count})"
                count = self._count_visible_shapes_for_level(self.sourceModel(), level)
                return f"Level {level} ({count})"
            if role == ShapeItemsModel.HeaderCollapsedRole:
                if is_with_value_header:
                    return False
                return level in self._collapsed_levels

        if role == ShapeItemsModel.HeaderCollapsedRole and index.isValid():
            source_index = self.mapToSource(index)
            if source_index.isValid() and bool(source_index.data(ShapeItemsModel.IsHeaderRole)):
                level = int(source_index.data(ShapeItemsModel.LevelRole) or 0)
                return level in self._collapsed_levels
        return super().data(index, role)

    def lessThan(self, left: QModelIndex, right: QModelIndex) -> bool:  # noqa: N802
        model = self.sourceModel()
        if model is None:
            return False

        if self._is_value_sort_mode():
            ascending = self._sort_order == Qt.AscendingOrder
            with_value_header = self._with_value_header_source_index(model)

            def value_sort_rank(index: QModelIndex):
                is_header = bool(model.data(index, ShapeItemsModel.IsHeaderRole))
                level = int(model.data(index, ShapeItemsModel.LevelRole) or 0)
                name = (model.data(index, ShapeItemsModel.NameRole) or "").lower()
                value = float(model.data(index, ShapeItemsModel.ValueRole) or 0.0)
                if is_header and index == with_value_header:
                    return (0, 0, 0, "")
                if self.is_with_value_shape(model, index):
                    # Inside "With Value": level first, then value.
                    value_key = value if ascending else -value
                    return (1, level, value_key, name)
                if is_header:
                    return (2, level, 0, "")
                # Non-valued shapes remain under normal level headers.
                return (3, level, 0, name)

            left_rank = value_sort_rank(left)
            right_rank = value_sort_rank(right)
            if left_rank == right_rank:
                return False
            return left_rank < right_rank

        left_level = int(model.data(left, ShapeItemsModel.LevelRole) or 0)
        right_level = int(model.data(right, ShapeItemsModel.LevelRole) or 0)
        if left_level != right_level:
            return left_level < right_level

        left_is_header = bool(model.data(left, ShapeItemsModel.IsHeaderRole))
        right_is_header = bool(model.data(right, ShapeItemsModel.IsHeaderRole))
        if left_is_header != right_is_header:
            return left_is_header
        if left_is_header and right_is_header:
            return False

        ascending = self._sort_order == Qt.AscendingOrder

        if self.sortRole() == ShapeItemsModel.NameRole:
            left_name = (model.data(left, ShapeItemsModel.NameRole) or "").lower()
            right_name = (model.data(right, ShapeItemsModel.NameRole) or "").lower()
            if left_name == right_name:
                return False
            return left_name < right_name if ascending else left_name > right_name

        if self.sortRole() == ShapeItemsModel.ValueRole:
            left_value = float(model.data(left, ShapeItemsModel.ValueRole) or 0.0)
            right_value = float(model.data(right, ShapeItemsModel.ValueRole) or 0.0)
            if abs(left_value - right_value) > 1e-9:
                return left_value < right_value if ascending else left_value > right_value
            left_name = (model.data(left, ShapeItemsModel.NameRole) or "").lower()
            right_name = (model.data(right, ShapeItemsModel.NameRole) or "").lower()
            if left_name == right_name:
                return False
            return left_name < right_name

        return super().lessThan(left, right)



class PrimarySubsetProxyModel(QSortFilterProxyModel):
    """Primary-only subset view without headers, driven by an explicit name set."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._selected_names: Set[str] = set()
        self.setDynamicSortFilter(False)

    def clear_selected_names(self) -> None:
        self._selected_names.clear()
        self.invalidateFilter()

    def add_selected_names(self, names: Sequence[str]) -> None:
        for name in names:
            if name:
                self._selected_names.add(str(name))
        self.invalidateFilter()

    def selected_names(self) -> List[str]:
        return sorted(self._selected_names)

    def remove_selected_names(self, names: Sequence[str]) -> int:
        remove_names = {str(name) for name in names if name}
        if not remove_names:
            return 0
        removed = len(remove_names.intersection(self._selected_names))
        if removed:
            self._selected_names.difference_update(remove_names)
            self.invalidateFilter()
        return removed

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:  # noqa: N802
        model = self.sourceModel()
        if model is None:
            return False
        index = model.index(source_row, 0, source_parent)
        if bool(model.data(index, ShapeItemsModel.IsHeaderRole)):
            return False
        if model.data(index, ShapeItemsModel.TypeRole) != "PrimaryShape":
            return False
        name = str(model.data(index, ShapeItemsModel.NameRole) or "")
        return name in self._selected_names

    def lessThan(self, left: QModelIndex, right: QModelIndex) -> bool:  # noqa: N802
        model = self.sourceModel()
        if model is None:
            return False
        left_name = (model.data(left, ShapeItemsModel.NameRole) or "").lower()
        right_name = (model.data(right, ShapeItemsModel.NameRole) or "").lower()
        if left_name == right_name:
            return False
        return left_name < right_name



class WorkShapeItemsModel(QAbstractListModel):
    """List model for work blendshape weights rendered with slider delegate style."""

    NameRole = ShapeItemsModel.NameRole
    TypeRole = ShapeItemsModel.TypeRole
    ValueRole = ShapeItemsModel.ValueRole
    MutedRole = ShapeItemsModel.MutedRole
    LevelRole = ShapeItemsModel.LevelRole
    PrimariesRole = ShapeItemsModel.PrimariesRole
    EditableRole = ShapeItemsModel.EditableRole
    IsHeaderRole = ShapeItemsModel.IsHeaderRole
    HeaderLevelRole = ShapeItemsModel.HeaderLevelRole
    HeaderCollapsedRole = ShapeItemsModel.HeaderCollapsedRole
    LockedRole = ShapeItemsModel.LockedRole
    LockIconVisibleRole = ShapeItemsModel.LockIconVisibleRole
    InEditModeRole = Qt.UserRole + 50
    ConnectedRole = Qt.UserRole + 51
    DriverConnectedRole = Qt.UserRole + 52

    valueCommitted = Signal(str, float)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._editor: Optional[BlueSteelEditor] = None
        self._rows: List[dict] = []
        self._row_by_name: Dict[str, int] = {}
        self._edit_shape_name: Optional[str] = None

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        if parent.isValid():
            return 0
        return len(self._rows)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self._rows)):
            return None
        row = self._rows[index.row()]
        if role in (Qt.DisplayRole, self.NameRole):
            return row["name"]
        if role == self.TypeRole:
            return row["type"]
        if role == self.ValueRole:
            return row["value"]
        if role == self.MutedRole:
            return bool(row.get("muted", False))
        if role == self.LevelRole:
            return 0
        if role == self.PrimariesRole:
            return tuple()
        if role == self.EditableRole:
            return True
        if role == self.IsHeaderRole:
            return False
        if role == self.HeaderLevelRole:
            return 0
        if role == self.HeaderCollapsedRole:
            return False
        if role == self.LockedRole:
            return False
        if role == self.LockIconVisibleRole:
            return False
        if role == self.InEditModeRole:
            return str(row["name"]) == str(self._edit_shape_name)
        if role == self.ConnectedRole:
            return bool(row.get("connected", False))
        if role == self.DriverConnectedRole:
            return bool(row.get("driver_connected", False))
        if role == Qt.ToolTipRole:
            return row.get("tooltip", None)
        return None

    def flags(self, index: QModelIndex):
        if not index.isValid():
            return Qt.NoItemFlags
        return Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsEditable

    def setData(self, index: QModelIndex, value, role: int = Qt.EditRole) -> bool:  # noqa: N802
        if not index.isValid() or not (0 <= index.row() < len(self._rows)):
            return False
        if role == Qt.ToolTipRole:
            row = self._rows[index.row()]
            tooltip_text = str(value).strip() if value else ""
            if row.get("tooltip", "") == tooltip_text:
                return False
            if tooltip_text:
                row["tooltip"] = tooltip_text
            else:
                row.pop("tooltip", None)
            self.dataChanged.emit(index, index, [Qt.ToolTipRole])
            return True
        if role not in (Qt.EditRole, self.ValueRole):
            return False
        if self._editor is None or self._editor.work_blendshape is None:
            return False
        try:
            new_value = max(0.0, min(1.0, float(value)))
        except (TypeError, ValueError):
            return False
        row = self._rows[index.row()]
        if abs(float(row["value"]) - new_value) <= 1e-6:
            return False
        weight = self._editor.work_blendshape.get_weight_by_name(row["name"])
        if weight is None:
            return False
        self._editor.work_blendshape.set_weight_value(weight, new_value)
        row["value"] = new_value
        self.dataChanged.emit(index, index, [self.ValueRole, Qt.DisplayRole])
        self.valueCommitted.emit(str(row["name"]), new_value)
        return True

    def rebuild_from_editor(self, editor: Optional[BlueSteelEditor]) -> None:
        self.beginResetModel()
        self._editor = editor
        self._rows = []
        self._row_by_name = {}
        self._edit_shape_name = None
        if editor is not None and editor.work_blendshape is not None:
            connected_weights = set(editor.get_work_blendshape_connected_targets_weights() or [])
            sculpt_target_indices = set(editor.work_blendshape.get_sculpt_target_indices() or [])
            weights = sorted(editor.get_work_blendshape_weights() or [], key=lambda w: str(w).lower())
            for weight in weights:
                name = str(weight)
                value = float(editor.work_blendshape.get_weight_value(weight))
                muted = bool(editor.get_work_shape_muted_state(name))
                connected = weight in connected_weights
                driver_connected = bool(editor.get_work_shape_driver(weight))
                self._row_by_name[name] = len(self._rows)
                row = {
                    "name": name,
                    "type": "WorkShape",
                    "value": value,
                    "muted": muted,
                    "connected": connected,
                    "driver_connected": driver_connected,
                }
                if connected:
                    row["tooltip"] = "Connected extraction mesh"
                self._rows.append(row)
                if self._edit_shape_name is None and int(weight.id) in sculpt_target_indices:
                    self._edit_shape_name = name
        self.endResetModel()

    def has_connected_driver_shapes(self) -> bool:
        for row in self._rows:
            if bool(row.get("driver_connected", False)):
                return True
        return False

    def set_value_by_name(self, shape_name: str, value: float) -> None:
        row_index = self._row_by_name.get(shape_name)
        if row_index is None:
            return
        self.setData(self.index(row_index, 0), value, self.ValueRole)

    def get_value(self, shape_name: str) -> Optional[float]:
        row_index = self._row_by_name.get(shape_name)
        if row_index is None:
            return None
        return float(self._rows[row_index]["value"])

    def set_value_local(self, shape_name: str, value: float) -> None:
        """Update one row value from external tracker callbacks without writing to Maya."""
        row_index = self._row_by_name.get(shape_name)
        if row_index is None:
            return
        clamped_value = max(0.0, min(1.0, float(value)))
        row = self._rows[row_index]
        if abs(float(row.get("value", 0.0)) - clamped_value) <= 1e-6:
            return
        row["value"] = clamped_value
        model_index = self.index(row_index, 0)
        self.dataChanged.emit(model_index, model_index, [self.ValueRole, Qt.DisplayRole])

    def set_muted_state_local(self, shape_name: str, muted: bool) -> None:
        """Update one row muted state from UI callbacks without forcing rebuild."""
        row_index = self._row_by_name.get(shape_name)
        if row_index is None:
            return
        row = self._rows[row_index]
        target = bool(muted)
        if bool(row.get("muted", False)) == target:
            return
        row["muted"] = target
        model_index = self.index(row_index, 0)
        self.dataChanged.emit(model_index, model_index, [self.MutedRole, Qt.DisplayRole])

    def is_shape_connected(self, shape_name: str) -> bool:
        row_index = self._row_by_name.get(shape_name)
        if row_index is None:
            return False
        return bool(self._rows[row_index].get("connected", False))

    def set_connected_state_local(self, shape_name: str, connected: bool) -> None:
        row_index = self._row_by_name.get(shape_name)
        if row_index is None:
            return
        row = self._rows[row_index]
        target_connected = bool(connected)
        if bool(row.get("connected", False)) == target_connected:
            return
        row["connected"] = target_connected
        if target_connected:
            row["tooltip"] = "Connected extraction mesh"
        else:
            row.pop("tooltip", None)
        model_index = self.index(row_index, 0)
        self.dataChanged.emit(model_index, model_index, [self.ConnectedRole, Qt.ToolTipRole, Qt.DisplayRole])

    def set_driver_connected_state_local(self, shape_name: str, connected: bool) -> None:
        row_index = self._row_by_name.get(shape_name)
        if row_index is None:
            return
        row = self._rows[row_index]
        target_connected = bool(connected)
        if bool(row.get("driver_connected", False)) == target_connected:
            return
        row["driver_connected"] = target_connected
        model_index = self.index(row_index, 0)
        self.dataChanged.emit(model_index, model_index, [self.DriverConnectedRole, Qt.DisplayRole])

    def refresh_values_from_editor(self) -> List[tuple]:
        """Pull current work-blendshape values and update rows without rebuilding.

        Returns a list of changed rows as tuples: (name, value).
        """
        if self._editor is None or self._editor.work_blendshape is None:
            return []

        work_blendshape = self._editor.work_blendshape
        changed: List[tuple] = []

        for row_index, row in enumerate(self._rows):
            new_value = work_blendshape.get_weight_value_by_name(str(row.get("name", "")))
            clamped_value = max(0.0, min(1.0, float(new_value or 0.0)))
            if abs(float(row.get("value", 0.0)) - clamped_value) <= 1e-6:
                continue
            row["value"] = clamped_value
            model_index = self.index(row_index, 0)
            self.dataChanged.emit(model_index, model_index, [self.ValueRole, Qt.DisplayRole])
            changed.append((str(row.get("name", "")), clamped_value))

        return changed

    def index_by_name(self, shape_name: str) -> QModelIndex:
        row_index = self._row_by_name.get(shape_name)
        if row_index is None:
            return QModelIndex()
        return self.index(row_index, 0)

    def edit_shape_name(self) -> Optional[str]:
        return self._edit_shape_name

    def set_edit_shape(self, shape_name: Optional[str]) -> None:
        previous = self._edit_shape_name
        next_name = str(shape_name) if shape_name else None
        if next_name and next_name not in self._row_by_name:
            next_name = None
        if previous == next_name:
            return
        self._edit_shape_name = next_name
        for changed_name in (previous, next_name):
            if not changed_name:
                continue
            changed_index = self.index_by_name(changed_name)
            if changed_index.isValid():
                self.dataChanged.emit(changed_index, changed_index, [self.InEditModeRole, Qt.DisplayRole])



