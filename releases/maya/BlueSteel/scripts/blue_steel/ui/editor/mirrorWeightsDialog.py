"""Dialog that collects the options for mirroring a split weight map.

The Split Map Editor mirrors the selected split-map weight through
:meth:`blue_steel.api.editor.BlueSteelEditor.mirror_edit_split_weight_map_values`,
which takes a handful of options that cannot be derived from the selection:
the action (mirror or flip), the mirror axis and direction, the falloff band,
the vertex pairing (object-space or topological) and, for the topological
pairing, the edge seeding the symmetry map and the match tolerance.

The dialog is a non-modal tool window so Maya stays interactive: the user can
select an edge on the symmetry line in the viewport and press **Pick Selected
Edge** while the dialog is open. It only collects the options; the Split Map
Editor calls the editor API when the dialog is accepted.

Example:
    >>> from blue_steel.ui.editor.mirrorWeightsDialog import MirrorWeightsDialog
    >>> dialog = MirrorWeightsDialog(parent=window)
    >>> dialog.set_target_shape("mouth_left")
    >>> dialog.show()
    >>> dialog.settings()["mirror_axis"]
    <MirrorAxis.X: 'x'>
"""

from __future__ import annotations

from typing import Optional, Tuple

from maya import cmds

from ...api import mayaUtils
from .qt import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
    Qt,
)

MIRROR_ACTION_ITEMS: Tuple[Tuple[object, str], ...] = (
    (mayaUtils.MirrorAction.MIRROR, "Mirror (copy source side)"),
    (mayaUtils.MirrorAction.FLIP, "Flip (swap sides)"),
)
"""tuple[tuple[object, str], ...]: Action combo entries."""

MIRROR_AXIS_ITEMS: Tuple[Tuple[object, str], ...] = (
    (mayaUtils.MirrorAxis.X, "X"),
    (mayaUtils.MirrorAxis.Y, "Y"),
    (mayaUtils.MirrorAxis.Z, "Z"),
)
"""tuple[tuple[object, str], ...]: Mirror axis combo entries."""

MIRROR_DIRECTION_ITEMS: Tuple[Tuple[object, str], ...] = (
    (mayaUtils.MirrorDirection.LEFT_TO_RIGHT, "Left → Right (l>>r)"),
    (mayaUtils.MirrorDirection.RIGHT_TO_LEFT, "Right → Left (l<<r)"),
)
"""tuple[tuple[object, str], ...]: Mirror direction combo entries."""

MIRROR_MAPPING_ITEMS: Tuple[Tuple[object, str], ...] = (
    (mayaUtils.MirrorMapping.GEOMETRIC, "Object Space (Geometric)"),
    (mayaUtils.MirrorMapping.TOPOLOGICAL, "Topological Symmetry"),
)
"""tuple[tuple[object, str], ...]: Vertex pairing combo entries."""

DEFAULT_MIRROR_SETTINGS = {
    "action": mayaUtils.MirrorAction.MIRROR,
    "mirror_axis": mayaUtils.MirrorAxis.X,
    "mirror_direction": mayaUtils.MirrorDirection.LEFT_TO_RIGHT,
    "mirror_blend_falloff": mayaUtils.DEFAULT_MIRROR_BLEND_FALLOFF,
    "tolerance": mayaUtils.DEFAULT_MIRROR_TOLERANCE,
    "mapping": mayaUtils.MirrorMapping.GEOMETRIC,
    "symmetry_edge": None,
}
"""dict: Options of every opening when the caller remembers none.

The keys match the keyword arguments of
:meth:`blue_steel.api.editor.BlueSteelEditor.mirror_edit_split_weight_map_values`
and ``mirror_blend_falloff`` is a fraction of the bounding box (``0.2`` is
shown as ``20 %`` in the dialog).
"""


def _set_combo_value(combo: QComboBox, value) -> None:
    """Select the entry of ``combo`` that carries ``value``.

    Parameters:
        combo (QComboBox): Combo to update.
        value: Item data to select. When no entry carries it the combo keeps
            its current entry.

    Returns:
        None
    """

    for index in range(combo.count()):
        if combo.itemData(index) == value:
            combo.setCurrentIndex(index)
            return


def _fill_combo(combo: QComboBox, items: Tuple[Tuple[object, str], ...]) -> None:
    """Populate a combo from an ``(item_data, label)`` table.

    Parameters:
        combo (QComboBox): Combo to fill.
        items (tuple[tuple[object, str], ...]): Entries to add.

    Returns:
        None
    """

    for item_data, label in items:
        combo.addItem(label, item_data)


class MirrorWeightsDialog(QDialog):
    """Collect the mirror options of one split weight map.

    Attributes:
        _target_label (QLabel): Weight map the options are applied to.
        _action_combo (QComboBox): ``MirrorAction`` selection.
        _axis_combo (QComboBox): ``MirrorAxis`` selection.
        _direction_combo (QComboBox): ``MirrorDirection`` selection.
        _falloff_spin (QDoubleSpinBox): Falloff band in percent.
        _tolerance_spin (QDoubleSpinBox): Geometric match tolerance.
        _mapping_combo (QComboBox): ``MirrorMapping`` selection.
        _edge_edit (QLineEdit): Picked symmetry edge, read only.
        _pick_edge_button (QPushButton): Reads the current edge selection.
        _clear_edge_button (QPushButton): Forgets the picked edge.
        _hint_label (QLabel): Mode dependent help text.
        _mirror_button (QPushButton): Accept button of the button box.
        _form (QFormLayout): Form holding the option rows, used to grey out
            the label of a disabled field.
        _edge (Optional[str]): Picked symmetry edge component name.
        _pick_failed (bool): Whether the last pick found no edge.
        _edge_armed (bool): Whether this dialog switched Maya into edge
            selection mode and still has to restore it.
        _previous_mapping (str): Mapping shown before the last combo change.
        _previous_selection_mode (Optional[tuple]): Selection mode and
            component mask saved before edge selection mode was armed.

    Example:
        >>> dialog = MirrorWeightsDialog(parent=window)
        >>> dialog.set_settings({"mirror_axis": "z"})
        >>> dialog.settings()["mirror_axis"]
        <MirrorAxis.Z: 'z'>
    """

    def __init__(self, parent: Optional[QWidget] = None, settings: dict = None) -> None:
        """Build the dialog and apply the initial options.

        Parameters:
            parent (Optional[QWidget]): Parent widget of the tool window.
            settings (dict, optional): Options to restore, for example the
                settings a previous opening was accepted with. Missing keys
                fall back to :data:`DEFAULT_MIRROR_SETTINGS`.

        Returns:
            None
        """

        super().__init__(parent)
        self._edge: Optional[str] = None
        self._pick_failed = False
        self._edge_armed = False
        self._previous_selection_mode: Optional[tuple] = None
        self._previous_mapping = None
        self._target_shape = ""
        self.setWindowTitle("Mirror Weights")
        # A tool window keeps Maya interactive, so an edge can be picked in the
        # viewport while the dialog is open.
        self.setWindowFlag(Qt.Tool, True)
        self.setWindowFlag(Qt.Window, True)
        self.setMinimumWidth(430)
        self._build_ui()
        self._previous_mapping = self._mapping_combo.currentData()
        self.set_settings(settings)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        """Create the option fields, the edge picker and the button box.

        Returns:
            None
        """

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        self._target_label = QLabel("Target shape: None", self)
        self._target_label.setWordWrap(True)
        layout.addWidget(self._target_label)

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(6)
        self._form = form
        layout.addLayout(form)

        self._action_combo = QComboBox(self)
        _fill_combo(self._action_combo, MIRROR_ACTION_ITEMS)
        self._action_combo.setToolTip(
            "Mirror keeps the source side and copies it onto the other side; "
            "flip swaps both sides")
        self._action_label = QLabel("Action:", self)
        form.addRow(self._action_label, self._action_combo)

        self._axis_combo = QComboBox(self)
        _fill_combo(self._axis_combo, MIRROR_AXIS_ITEMS)
        self._axis_combo.setToolTip("Object-space axis the mirror is performed across")
        self._axis_label = QLabel("Axis:", self)
        form.addRow(self._axis_label, self._axis_combo)

        self._direction_combo = QComboBox(self)
        _fill_combo(self._direction_combo, MIRROR_DIRECTION_ITEMS)
        self._direction_combo.setToolTip(
            "Side the values are copied from: left is the negative side of the "
            "axis (mirror only, flip swaps both sides)")
        self._direction_label = QLabel("Direction:", self)
        form.addRow(self._direction_label, self._direction_combo)

        self._mapping_combo = QComboBox(self)
        _fill_combo(self._mapping_combo, MIRROR_MAPPING_ITEMS)
        self._mapping_combo.setToolTip(
            "Object space pairs every vertex with the nearest vertex to its "
            "reflected position; topological symmetry pairs the vertices "
            "through the symmetry edge")
        self._mapping_label = QLabel("Mapping:", self)
        form.addRow(self._mapping_label, self._mapping_combo)

        self._falloff_spin = QDoubleSpinBox(self)
        self._falloff_spin.setRange(0.0, 100.0)
        self._falloff_spin.setDecimals(1)
        self._falloff_spin.setSingleStep(5.0)
        self._falloff_spin.setSuffix(" %")
        self._falloff_spin.setToolTip(
            "Width of the transition band as a percentage of the bounding box "
            "along the axis (0 % splits hard on the symmetry plane). Mirror "
            "only: flip always swaps both sides with a hard edge")
        falloff_row = QHBoxLayout()
        falloff_row.setContentsMargins(0, 0, 0, 0)
        falloff_row.addWidget(self._falloff_spin, 1)
        falloff_row.addStretch(1)
        self._falloff_label = QLabel("Falloff:", self)
        form.addRow(self._falloff_label, falloff_row)

        self._tolerance_spin = QDoubleSpinBox(self)
        self._tolerance_spin.setRange(0.000001, 1000.0)
        self._tolerance_spin.setDecimals(6)
        self._tolerance_spin.setSingleStep(0.001)
        self._tolerance_spin.setToolTip(
            "Maximum distance between a vertex and the reflected position of "
            "its counterpart, in object units (object-space mapping only)")
        tolerance_row = QHBoxLayout()
        tolerance_row.setContentsMargins(0, 0, 0, 0)
        tolerance_row.addWidget(self._tolerance_spin, 1)
        tolerance_row.addStretch(1)
        self._tolerance_label = QLabel("Tolerance:", self)
        form.addRow(self._tolerance_label, tolerance_row)

        self._edge_edit = QLineEdit(self)
        self._edge_edit.setReadOnly(True)
        self._edge_edit.setPlaceholderText("No edge picked (uses the selected edge)")
        self._edge_edit.setToolTip("Edge on the symmetry line used by the topological mapping")
        edge_row = QHBoxLayout()
        edge_row.setContentsMargins(0, 0, 0, 0)
        edge_row.addWidget(self._edge_edit, 1)
        self._pick_edge_button = QPushButton("Pick Selected Edge", self)
        self._pick_edge_button.setToolTip(
            "Use the edge that is currently selected in the viewport; when no "
            "edge is selected, edge selection mode is switched on so the next "
            "press can pick one")
        edge_row.addWidget(self._pick_edge_button, 0)
        self._clear_edge_button = QPushButton("Clear", self)
        self._clear_edge_button.setToolTip("Forget the picked edge")
        edge_row.addWidget(self._clear_edge_button, 0)
        self._edge_label = QLabel("Symmetry Edge:", self)
        form.addRow(self._edge_label, edge_row)

        self._hint_label = QLabel("", self)
        self._hint_label.setWordWrap(True)
        layout.addWidget(self._hint_label)

        layout.addStretch(1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel,
            parent=self,
        )
        self._mirror_button = buttons.button(QDialogButtonBox.Ok)
        self._mirror_button.setText("Mirror")
        close_button = buttons.button(QDialogButtonBox.Cancel)
        close_button.setText("Close")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._action_combo.currentIndexChanged.connect(
            lambda _index=0: self._refresh_state())
        self._mapping_combo.currentIndexChanged.connect(self._on_mapping_changed)
        self._pick_edge_button.clicked.connect(self._on_pick_edge_clicked)
        self._clear_edge_button.clicked.connect(self._on_clear_edge_clicked)

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------
    def state(self) -> dict:
        """Return the raw options shown in the dialog.

        Unlike :meth:`settings` this keeps the falloff percentage even for the
        flip action, so the options can be remembered between openings without
        losing the mirror falloff of the user.

        Returns:
            dict: ``action``, ``mirror_axis``, ``mirror_direction``,
            ``mirror_blend_falloff`` (a ``0..1`` fraction),
            ``tolerance``, ``mapping`` and ``symmetry_edge``.
        """

        return {
            "action": self._action_combo.currentData(),
            "mirror_axis": self._axis_combo.currentData(),
            "mirror_direction": self._direction_combo.currentData(),
            "mirror_blend_falloff": float(self._falloff_spin.value()) / 100.0,
            "tolerance": float(self._tolerance_spin.value()),
            "mapping": self._mapping_combo.currentData(),
            "symmetry_edge": self.selected_edge(),
        }

    def settings(self) -> dict:
        """Return the chosen options as editor API keyword arguments.

        Flip always swaps both sides with a hard edge, so the falloff is forced
        to ``0.0`` for it; the greyed-out field keeps the value a later mirror
        would use.

        Returns:
            dict: ``action``, ``mirror_axis``, ``mirror_direction``,
            ``mirror_blend_falloff`` (a ``0..1`` fraction),
            ``tolerance``, ``mapping`` and ``symmetry_edge``.
        """

        values = self.state()
        if self._is_flip():
            values["mirror_blend_falloff"] = 0.0
        return values

    def set_settings(self, settings: dict = None) -> None:
        """Apply options without running anything.

        Parameters:
            settings (dict, optional): Options to restore. Missing keys keep
                the :data:`DEFAULT_MIRROR_SETTINGS` values.

        Returns:
            None
        """

        values = dict(DEFAULT_MIRROR_SETTINGS)
        values.update(settings or {})

        _set_combo_value(self._action_combo, values["action"])
        _set_combo_value(self._axis_combo, values["mirror_axis"])
        _set_combo_value(self._direction_combo, values["mirror_direction"])
        _set_combo_value(self._mapping_combo, values["mapping"])

        falloff = values.get("mirror_blend_falloff")
        if falloff is None:
            falloff = mayaUtils.DEFAULT_MIRROR_BLEND_FALLOFF
        self._falloff_spin.setValue(float(falloff) * 100.0)

        tolerance = values.get("tolerance")
        if tolerance is None:
            tolerance = mayaUtils.DEFAULT_MIRROR_TOLERANCE
        self._tolerance_spin.setValue(float(tolerance))

        edge = values.get("symmetry_edge")
        self._edge = None if edge is None else str(edge)
        self._pick_edge_button.setEnabled(True)
        self._edge_edit.setText(self._edge or "")
        self._pick_failed = False
        self._restore_selection_mode()
        # Selecting the mapping entries above fires the change slot; restore the
        # tracking state so the freshly applied edge is not treated as stale.
        self._previous_mapping = self._mapping_combo.currentData()
        self._refresh_state()

    def set_target_shape(self, shape_name: str) -> None:
        """Show which weight map the options apply to.

        Parameters:
            shape_name (str): Weight alias of the split shape, empty when no
                weight is selected.

        Returns:
            None
        """

        self._target_shape = shape_name or ""
        if self._target_shape:
            self._target_label.setText(f"Target shape: <b>{self._target_shape}</b>")
        else:
            self._target_label.setText("Target shape: None")

    def target_shape(self) -> str:
        """Return the weight map the dialog was last pointed at.

        Returns:
            str: Weight alias, empty when none was set.
        """

        return self._target_shape

    def selected_edge(self) -> Optional[str]:
        """Return the picked symmetry edge.

        Returns:
            Optional[str]: Edge component name, ``None`` when no edge was
            picked and the editor API should use the current selection.
        """

        return self._edge

    def pick_edge_from_selection(self) -> Optional[str]:
        """Return the edge selected in the viewport, if any.

        Unlike :func:`blue_steel.api.mayaUtils._get_active_edge` this does not
        raise when the selection holds no edge, so the dialog can simply show
        a hint instead of failing.

        Returns:
            Optional[str]: The first selected edge component name, or ``None``.
        """

        for item in cmds.ls(selection=True, flatten=True) or []:
            if ".e[" in str(item):
                return str(item)
        return None

    def _on_pick_edge_clicked(self) -> None:
        """Pick the selected edge, or arm Maya's edge selection mode.

        When the selection already holds an edge it is stored right away;
        otherwise Maya is switched to component/edge selection mode so the
        next press can grab the edge the user clicks in the viewport.

        Returns:
            None
        """

        edge = self.pick_edge_from_selection()
        if edge is None:
            self._pick_failed = not self._arm_edge_selection()
            self._refresh_state()
            return
        self._edge = edge
        self._edge_edit.setText(edge)
        self._pick_failed = False
        self._restore_selection_mode()
        self._refresh_state()

    def _on_clear_edge_clicked(self) -> None:
        """Forget the picked edge so the current selection is used.

        Returns:
            None
        """

        self._edge = None
        self._pick_failed = False
        self._edge_edit.clear()
        self._restore_selection_mode()
        self._refresh_state()

    def _on_mapping_changed(self, _index: int = 0) -> None:
        """Clear the edge when the mapping stops using it.

        A picked edge belongs to the topology of one mesh, so it is dropped as
        soon as the topological mapping is left instead of failing on the next
        topological run.

        Parameters:
            _index (int): Index of the new mapping entry, unused.

        Returns:
            None
        """

        mapping = self._mapping_combo.currentData()
        if (self._previous_mapping == mayaUtils.MirrorMapping.TOPOLOGICAL
                and mapping != mayaUtils.MirrorMapping.TOPOLOGICAL):
            self._edge = None
            self._pick_failed = False
            self._edge_edit.clear()
            self._restore_selection_mode()
        self._previous_mapping = mapping
        self._refresh_state()

    # ------------------------------------------------------------------
    # Maya selection mode
    # ------------------------------------------------------------------
    def _arm_edge_selection(self) -> bool:
        """Switch Maya to component/edge selection mode for the edge pick.

        Returns:
            bool: ``True`` when edge selection mode is active afterwards.
        """

        try:
            self._remember_selection_mode()
            cmds.selectMode(component=True)
            cmds.selectType(allComponents=False, meshComponents=True, edge=True)
        except Exception:
            self._edge_armed = False
            return False
        self._edge_armed = True
        return True

    def _remember_selection_mode(self) -> None:
        """Store Maya's selection mode and component mask before arming.

        Returns:
            None
        """

        if self._previous_selection_mode is not None:
            return
        self._previous_selection_mode = (
            bool(cmds.selectMode(query=True, component=True)),
            bool(cmds.selectType(query=True, vertex=True)),
            bool(cmds.selectType(query=True, edge=True)),
            bool(cmds.selectType(query=True, face=True)),
        )

    def _restore_selection_mode(self) -> None:
        """Restore the selection mode saved by :meth:`_arm_edge_selection`.

        Does nothing when this dialog did not switch the mode itself.

        Returns:
            None
        """

        previous = self._previous_selection_mode
        self._previous_selection_mode = None
        self._edge_armed = False
        if previous is None:
            return
        component, vertex, edge, face = previous
        try:
            if component:
                cmds.selectMode(component=True)
                cmds.selectType(allComponents=False,
                                meshComponents=True,
                                vertex=vertex,
                                edge=edge,
                                face=face)
            else:
                cmds.selectMode(object=True)
        except Exception:
            pass

    def closeEvent(self, event) -> None:
        """Restore Maya's selection mode before the tool window closes.

        Parameters:
            event: The close event of the tool window.

        Returns:
            None
        """

        self._restore_selection_mode()
        super().closeEvent(event)

    def _is_topological(self) -> bool:
        """Return whether the topological pairing is selected.

        Returns:
            bool: ``True`` when the mapping combo holds the topological entry.
        """

        return self._mapping_combo.currentData() == mayaUtils.MirrorMapping.TOPOLOGICAL

    def _is_flip(self) -> bool:
        """Return whether the flip action is selected.

        Returns:
            bool: ``True`` when the action combo holds the flip entry.
        """

        return self._action_combo.currentData() == mayaUtils.MirrorAction.FLIP

    def _refresh_state(self) -> None:
        """Grey out the fields the active action and mapping do not use.

        Returns:
            None
        """

        flip = self._is_flip()
        topological = self._is_topological()

        # Flip swaps both sides, so there is no source side to copy from and no
        # copy to blend across the falloff band.
        self._set_row_enabled(self._direction_combo, self._direction_label,
                              not flip)
        self._set_row_enabled(self._falloff_spin, self._falloff_label,
                              not flip)

        self._set_row_enabled(self._tolerance_spin, self._tolerance_label,
                              not topological)
        self._set_row_enabled(self._edge_edit, self._edge_label, topological)
        self._pick_edge_button.setEnabled(topological)
        self._clear_edge_button.setEnabled(topological)

        self._hint_label.setText(self._hint_text(topological, flip))
        self._mirror_button.setToolTip(
            "Apply the weight map mirror of the target shape with these options")

    def _set_row_enabled(self, field, label, enabled: bool) -> None:
        """Enable or grey out one form row, label included.

        Parameters:
            field (QWidget): Widget of the row.
            label (QLabel): Label of the row.
            enabled (bool): Whether the row is usable.

        Returns:
            None
        """

        field.setEnabled(enabled)
        label.setEnabled(enabled)

    def _hint_text(self, topological: bool, flip: bool) -> str:
        """Build the help text of the active action and mapping.

        Parameters:
            topological (bool): Whether the topological pairing is selected.
            flip (bool): Whether the flip action is selected.

        Returns:
            str: One or two sentences describing what the options do.
        """

        if flip:
            action_hint = ("Flip swaps both sides with a hard edge, so the "
                           "direction and the falloff do not apply.")
        else:
            action_hint = ("Mirror copies the source side onto the other side "
                           "and blends the copy across the falloff band.")

        if not topological:
            return (f"{action_hint} Object-space mapping pairs each vertex with "
                    f"the nearest vertex to its reflected position; vertices "
                    f"outside the tolerance keep their values.")

        if self._edge_armed:
            mapping_hint = ("Edge selection mode is on: select an edge on the "
                            "symmetry line in the viewport, then press Pick "
                            "Selected Edge again.")
        elif self._pick_failed:
            mapping_hint = ("Edge selection mode could not be switched on. "
                            "Select an edge on the symmetry line in the "
                            "viewport and press Pick Selected Edge again.")
        elif self._edge:
            mapping_hint = ("Topological mapping pairs the vertices through the "
                            "picked edge; the falloff is read from the "
                            "symmetrized positions of the pairs.")
        else:
            mapping_hint = ("Topological mapping needs an edge on the symmetry "
                            "line. Pick one, or leave the field empty to use "
                            "the selected edge.")
        return f"{action_hint} {mapping_hint}"
