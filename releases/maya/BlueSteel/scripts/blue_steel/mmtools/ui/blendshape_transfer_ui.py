"""UI for transferring blendShape target weight maps between meshes.

The dialog exposes every argument of
:func:`blue_steel.mmtools.blendshape_transfer_tools.transfer_blendshape_weight_maps`,
including every :class:`~blue_steel.mmtools.blendshape_transfer_tools.WeightsTransferMethod`
(UV, closest point, closest component, and ray cast).
The selected meshes prefill the source and destination fields, while blendShape
and UV-set choices are derived from each mesh and remain editable. UV sets are
only used by the UV transfer method.

Attributes:
    WINDOW (BlendshapeTransferUI | None): The current dialog instance.
"""

from __future__ import annotations

from typing import Callable, Optional

from maya import cmds
import maya.OpenMayaUI as omui

from ... import env
from ..blendshape_transfer_tools import transfer_blendshape_weight_maps, WeightsTransferMethod

if env.ENVIRONMENT.MAYA_VERSION > 2024:
    from PySide6 import QtCore, QtWidgets
    from shiboken6 import wrapInstance
else:
    from PySide2 import QtCore, QtWidgets
    from shiboken2 import wrapInstance

WINDOW: Optional["BlendshapeTransferUI"] = None

TRANSFER_METHOD_LABELS: dict[WeightsTransferMethod, str] = {
    WeightsTransferMethod.UVS: "UV",
    WeightsTransferMethod.CLOSEST_POINT: "Closest Point",
    WeightsTransferMethod.CLOSEST_COMPONENT: "Closest Component",
    WeightsTransferMethod.RAY_CAST: "Ray Cast",
}
TRANSFER_METHODS_BY_LABEL: dict[str, WeightsTransferMethod] = {
    label: method for method, label in TRANSFER_METHOD_LABELS.items()
}
TRANSFER_METHOD_TOOLTIP = (
    "Surface association used to match the destination surface: 'UV' "
    "transfers in UV space using the selected UV sets, 'Closest Point', "
    "'Closest Component', and 'Ray Cast' match in world space."
)


def _get_maya_main_window() -> Optional[QtWidgets.QWidget]:
    """Return Maya's main window as a Qt widget.

    Returns:
        QtWidgets.QWidget | None: The Maya main window, or ``None`` when Maya
            does not expose a main window.
    """

    main_window_ptr = omui.MQtUtil.mainWindow()
    if main_window_ptr is None:
        return None
    return wrapInstance(int(main_window_ptr), QtWidgets.QWidget)


def _short_name(node_name: str) -> str:
    """Return a node name without its DAG path.

    Parameters:
        node_name (str): Maya node name or DAG path.

    Returns:
        str: The short node name, including any namespace.
    """

    return node_name.rsplit("|", 1)[-1]


def _object_key(node_name: str) -> str:
    """Return a stable long name for Maya object comparisons.

    Parameters:
        node_name (str): Maya node name.

    Returns:
        str: The long name when available, otherwise the original name.
    """

    try:
        long_names = cmds.ls(node_name, long=True) or []
    except RuntimeError:
        return node_name
    return long_names[0] if long_names else node_name


def _mesh_transform_and_shape(
    mesh_name: str,
) -> Optional[tuple[str, str]]:
    """Resolve a transform or mesh shape to ``(transform, shape)``.

    Parameters:
        mesh_name (str): Transform or mesh shape name.

    Returns:
        tuple[str, str] | None: The mesh transform and non-intermediate shape,
            or ``None`` when the object is not a mesh.
    """

    if not mesh_name or not cmds.objExists(mesh_name):
        return None

    try:
        if cmds.objectType(mesh_name, isType="transform"):
            transform = mesh_name
            shapes = cmds.listRelatives(
                mesh_name,
                shapes=True,
                noIntermediate=True,
                fullPath=True,
            ) or []
            mesh_shapes = [
                shape for shape in shapes
                if cmds.objectType(shape, isType="mesh")
            ]
        elif cmds.objectType(mesh_name, isType="mesh"):
            mesh_shapes = [mesh_name]
            parents = cmds.listRelatives(
                mesh_name,
                parent=True,
                fullPath=True,
            ) or []
            transform = parents[0] if parents else mesh_name
        else:
            return None
    except RuntimeError:
        return None

    if not mesh_shapes:
        return None
    return transform, mesh_shapes[0]


def _blendshapes_for_mesh(mesh_name: str) -> list[str]:
    """Return blendShape nodes that deform a mesh.

    Parameters:
        mesh_name (str): Mesh transform or shape name.

    Returns:
        list[str]: BlendShape nodes whose base geometry is the mesh.
    """

    resolved_mesh = _mesh_transform_and_shape(mesh_name)
    if resolved_mesh is None:
        return []

    transform, shape = resolved_mesh
    mesh_keys = {_object_key(transform), _object_key(shape)}
    blend_shapes: list[str] = []

    try:
        history = cmds.listHistory(transform) or []
    except RuntimeError:
        history = []

    for node in history:
        if cmds.nodeType(node) != "blendShape" or node in blend_shapes:
            continue
        base_nodes = cmds.blendShape(node, q=True, g=True) or []
        if any(_object_key(base) in mesh_keys for base in base_nodes):
            blend_shapes.append(node)

    return blend_shapes


def _target_names(blendshape_name: str) -> list[str]:
    """Return blendShape target aliases in logical target order.

    Parameters:
        blendshape_name (str): BlendShape node name.

    Returns:
        list[str]: Target aliases, with ``target_<index>`` fallbacks for
            targets that have no alias.
    """

    if not blendshape_name or not cmds.objExists(blendshape_name):
        return []

    try:
        target_indices = cmds.getAttr(
            f"{blendshape_name}.inputTarget[0].inputTargetGroup",
            multiIndices=True,
        )
    except RuntimeError:
        target_indices = None

    if not target_indices:
        try:
            target_indices = cmds.getAttr(
                f"{blendshape_name}.weight",
                multiIndices=True,
            )
        except RuntimeError:
            target_indices = None

    target_names: list[str] = []
    for target_index in sorted({int(index) for index in target_indices or []}):
        try:
            alias = cmds.aliasAttr(
                f"{blendshape_name}.weight[{target_index}]",
                q=True,
            )
        except RuntimeError:
            alias = None
        target_names.append(alias or f"target_{target_index}")

    return target_names


def _uv_sets_for_mesh(mesh_name: str) -> tuple[list[str], Optional[str]]:
    """Return the UV sets and current UV set for a mesh.

    Parameters:
        mesh_name (str): Mesh transform or shape name.

    Returns:
        tuple[list[str], str | None]: All UV sets and the current UV set, or
            empty values when the mesh is invalid or has no UV sets.
    """

    resolved_mesh = _mesh_transform_and_shape(mesh_name)
    if resolved_mesh is None:
        return [], None

    transform, _shape = resolved_mesh
    try:
        uv_sets = cmds.polyUVSet(transform, q=True, allUVSets=True) or []
    except RuntimeError:
        uv_sets = []
    if not uv_sets:
        return [], None

    try:
        current_uv_sets = cmds.polyUVSet(
            transform,
            q=True,
            currentUVSet=True,
        ) or []
    except RuntimeError:
        current_uv_sets = []

    current_uv_set = current_uv_sets[0] if current_uv_sets else None
    if current_uv_set not in uv_sets:
        current_uv_set = uv_sets[0]
    return uv_sets, current_uv_set


def _selected_mesh() -> Optional[str]:
    """Return the first selected mesh transform.

    Returns:
        str | None: The first mesh transform in the selection, or ``None``
            when the selection contains no meshes.
    """

    selection = cmds.ls(selection=True, long=True) or []
    for node in selection:
        resolved_mesh = _mesh_transform_and_shape(node)
        if resolved_mesh is not None:
            return resolved_mesh[0]
    return None


class BlendshapeTransferUI(QtWidgets.QDialog):
    """Dialog for transferring blendShape weight maps between two meshes.

    The dialog exposes every argument of
    :func:`blue_steel.mmtools.blendshape_transfer_tools.transfer_blendshape_weight_maps`,
    including the ``WeightsTransferMethod`` used for the surface association.

    Attributes:
        CREATE_NEW_LABEL (str): Destination combo item used to create a new
            blendShape.
        _updating (bool): Guard used while combo boxes are repopulated.
        _updating_weight_checks (bool): Guard used while weight-item check
            states are synchronized.
    """

    CREATE_NEW_LABEL = "Create New..."
    WINDOW_TITLE = "Transfer BlendShape Weight Maps"

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        """Initialize the transfer dialog and populate it from the selection.

        Parameters:
            parent (QtWidgets.QWidget | None): Optional parent widget.

        Returns:
            None
        """

        super().__init__(parent)
        self.setObjectName("BlendshapeTransferUI")
        self.setWindowTitle(self.WINDOW_TITLE)
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose)
        self.setMinimumWidth(520)
        self.resize(560, 720)

        self._updating = False
        self._updating_weight_checks = False
        self._last_source_mesh_key: Optional[str] = None
        self._last_destination_mesh_key: Optional[str] = None

        self._build_ui()
        self._refresh_mesh_completers()
        self._load_selection()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        """Create all dialog widgets and connect their signals.

        Returns:
            None
        """

        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setSpacing(8)

        mesh_group = QtWidgets.QGroupBox("Meshes")
        mesh_form = QtWidgets.QFormLayout(mesh_group)
        mesh_form.setFieldGrowthPolicy(
            QtWidgets.QFormLayout.AllNonFixedFieldsGrow
        )

        self.source_mesh_edit = QtWidgets.QLineEdit()
        self.source_mesh_edit.setPlaceholderText("Source mesh transform")
        source_mesh_row, self.source_pick_button = self._create_mesh_row(
            self.source_mesh_edit
        )
        mesh_form.addRow("Source Mesh:", source_mesh_row)

        self.destination_mesh_edit = QtWidgets.QLineEdit()
        self.destination_mesh_edit.setPlaceholderText(
            "Destination mesh transform"
        )
        destination_mesh_row, self.destination_pick_button = (
            self._create_mesh_row(self.destination_mesh_edit)
        )
        mesh_form.addRow("Destination Mesh:", destination_mesh_row)
        main_layout.addWidget(mesh_group)

        blendshape_group = QtWidgets.QGroupBox("BlendShapes")
        blendshape_form = QtWidgets.QFormLayout(blendshape_group)
        blendshape_form.setFieldGrowthPolicy(
            QtWidgets.QFormLayout.AllNonFixedFieldsGrow
        )

        self.source_blendshape_combo = QtWidgets.QComboBox()
        self.source_blendshape_combo.setToolTip(
            "BlendShapes found in the source mesh history."
        )
        blendshape_form.addRow(
            "Source BlendShape:",
            self.source_blendshape_combo,
        )

        self.destination_blendshape_combo = QtWidgets.QComboBox()
        self.destination_blendshape_combo.setToolTip(
            "Reuse a destination blendShape or create a new one."
        )
        blendshape_form.addRow(
            "Destination BlendShape:",
            self.destination_blendshape_combo,
        )

        self.new_blendshape_name_edit = QtWidgets.QLineEdit()
        self.new_blendshape_name_edit.setPlaceholderText(
            "Optional; an automatic name is used when empty"
        )
        blendshape_form.addRow(
            "New BlendShape Name:",
            self.new_blendshape_name_edit,
        )
        main_layout.addWidget(blendshape_group)

        uv_group = QtWidgets.QGroupBox("UV Sets")
        self.uv_group = uv_group
        uv_form = QtWidgets.QFormLayout(uv_group)
        uv_form.setFieldGrowthPolicy(
            QtWidgets.QFormLayout.AllNonFixedFieldsGrow
        )

        self.source_uv_combo = QtWidgets.QComboBox()
        self.source_uv_combo.setToolTip(
            "UV set used on the source mesh by the UV transfer method."
        )
        uv_form.addRow("Source UV Set:", self.source_uv_combo)

        self.destination_uv_combo = QtWidgets.QComboBox()
        self.destination_uv_combo.setToolTip(
            "UV set used on the destination mesh by the UV transfer method."
        )
        uv_form.addRow("Destination UV Set:", self.destination_uv_combo)

        method_group = QtWidgets.QGroupBox("Transfer Method")
        method_form = QtWidgets.QFormLayout(method_group)
        method_form.setFieldGrowthPolicy(
            QtWidgets.QFormLayout.AllNonFixedFieldsGrow
        )

        self.transfer_method_combo = QtWidgets.QComboBox()
        self.transfer_method_combo.addItems(list(TRANSFER_METHODS_BY_LABEL))
        self.transfer_method_combo.setCurrentText(
            TRANSFER_METHOD_LABELS[WeightsTransferMethod.UVS]
        )
        self.transfer_method_combo.setToolTip(TRANSFER_METHOD_TOOLTIP)
        method_form.addRow("Method:", self.transfer_method_combo)

        main_layout.addWidget(method_group)
        main_layout.addWidget(uv_group)

        weights_group = QtWidgets.QGroupBox("Weights to Transfer")
        weights_layout = QtWidgets.QVBoxLayout(weights_group)
        weights_hint = QtWidgets.QLabel(
            "All targets are checked by default. Select multiple items "
            "with Ctrl/Shift and click a checkbox to toggle them together."
        )
        weights_hint.setWordWrap(True)
        weights_layout.addWidget(weights_hint)

        self.weight_list = QtWidgets.QListWidget()
        self.weight_list.setSelectionMode(
            QtWidgets.QAbstractItemView.ExtendedSelection
        )
        self.weight_list.setMinimumHeight(180)
        weights_layout.addWidget(self.weight_list)

        self.organize_target_directories_check = QtWidgets.QCheckBox(
            "Match Source Target Directories"
        )
        self.organize_target_directories_check.setChecked(False)
        self.organize_target_directories_check.setToolTip(
            "Recreate or reuse nested source folders in the destination blendShape "
            "and move transferred targets into them. Ungrouped source targets "
            "move to the root. Unrelated targets and folder settings are unchanged."
        )
        weights_layout.addWidget(self.organize_target_directories_check)
        main_layout.addWidget(weights_group, 1)

        self.status_label = QtWidgets.QLabel("")
        self.status_label.setWordWrap(True)
        main_layout.addWidget(self.status_label)

        button_layout = QtWidgets.QHBoxLayout()
        button_layout.addStretch(1)
        self.transfer_button = QtWidgets.QPushButton("Transfer")
        self.transfer_button.setDefault(True)
        self.close_button = QtWidgets.QPushButton("Close")
        button_layout.addWidget(self.transfer_button)
        button_layout.addWidget(self.close_button)
        main_layout.addLayout(button_layout)

        self.source_mesh_edit.editingFinished.connect(
            self._refresh_source_mesh_context
        )
        self.destination_mesh_edit.editingFinished.connect(
            self._refresh_destination_mesh_context
        )
        self.source_pick_button.clicked.connect(self._pick_source_mesh)
        self.destination_pick_button.clicked.connect(
            self._pick_destination_mesh
        )
        self.source_blendshape_combo.currentTextChanged.connect(
            self._on_source_blendshape_changed
        )
        self.destination_blendshape_combo.currentTextChanged.connect(
            self._on_destination_blendshape_changed
        )
        self.transfer_method_combo.currentTextChanged.connect(
            self._on_transfer_method_changed
        )
        self.weight_list.itemChanged.connect(self._on_weight_item_changed)
        self.transfer_button.clicked.connect(self._transfer)
        self.close_button.clicked.connect(self.close)

        self._update_uv_group_state()

    def _create_mesh_row(
        self,
        line_edit: QtWidgets.QLineEdit,
    ) -> tuple[QtWidgets.QWidget, QtWidgets.QPushButton]:
        """Create a mesh field row with a selection-pick button.

        Parameters:
            line_edit (QtWidgets.QLineEdit): Mesh name field.

        Returns:
            tuple[QtWidgets.QWidget, QtWidgets.QPushButton]: The row widget
                and its pick button.
        """

        row = QtWidgets.QWidget()
        row_layout = QtWidgets.QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(4)
        row_layout.addWidget(line_edit, 1)

        pick_button = QtWidgets.QPushButton("Pick")
        pick_button.setFixedWidth(52)
        pick_button.setToolTip("Use the first selected mesh.")
        row_layout.addWidget(pick_button)
        return row, pick_button

    # ------------------------------------------------------------------
    # Derived choices
    # ------------------------------------------------------------------
    def _refresh_mesh_completers(self) -> None:
        """Populate mesh text-field autocomplete with scene transforms.

        Returns:
            None
        """

        try:
            transforms = cmds.ls(type="transform", long=True) or []
        except RuntimeError:
            transforms = []

        transform_names = sorted({
            _short_name(transform) for transform in transforms
        })

        for line_edit in (
            self.source_mesh_edit,
            self.destination_mesh_edit,
        ):
            completer = QtWidgets.QCompleter(transform_names, line_edit)
            completer.setCaseSensitivity(QtCore.Qt.CaseInsensitive)
            completer.setFilterMode(QtCore.Qt.MatchContains)
            completer.setCompletionMode(
                QtWidgets.QCompleter.PopupCompletion
            )
            line_edit.setCompleter(completer)

    def _load_selection(self) -> None:
        """Prefill mesh fields from the first two selected mesh objects.

        Returns:
            None
        """

        selection = cmds.ls(selection=True, long=True) or []
        source_mesh = ""
        destination_mesh = ""

        if selection:
            source_mesh_data = _mesh_transform_and_shape(selection[0])
            if source_mesh_data is not None:
                source_mesh = source_mesh_data[0]
        if len(selection) > 1:
            destination_mesh_data = _mesh_transform_and_shape(selection[1])
            if destination_mesh_data is not None:
                destination_mesh = destination_mesh_data[0]

        self.source_mesh_edit.setText(
            _short_name(source_mesh) if source_mesh else ""
        )
        self.destination_mesh_edit.setText(
            _short_name(destination_mesh) if destination_mesh else ""
        )
        self._refresh_source_mesh_context()
        self._refresh_destination_mesh_context()

    def _refresh_source_mesh_context(self) -> None:
        """Refresh source blendShapes, UV sets, and weight items.

        Returns:
            None
        """

        if self._updating:
            return

        mesh_name = self.source_mesh_edit.text().strip()
        mesh_key = (
            _object_key(mesh_name)
            if mesh_name and cmds.objExists(mesh_name)
            else mesh_name
        )
        if mesh_key == self._last_source_mesh_key:
            return
        self._last_source_mesh_key = mesh_key

        self._updating = True
        try:
            blend_shapes = _blendshapes_for_mesh(mesh_name)
            previous_blendshape = self.source_blendshape_combo.currentText()

            self.source_blendshape_combo.clear()
            self.source_blendshape_combo.addItems(blend_shapes)
            if previous_blendshape in blend_shapes:
                self.source_blendshape_combo.setCurrentText(
                    previous_blendshape
                )
            elif blend_shapes:
                self.source_blendshape_combo.setCurrentIndex(0)

            uv_sets, current_uv_set = _uv_sets_for_mesh(mesh_name)
            self.source_uv_combo.clear()
            self.source_uv_combo.addItems(uv_sets)
            if current_uv_set in uv_sets:
                self.source_uv_combo.setCurrentText(current_uv_set)

            self._refresh_weight_list()
        finally:
            self._updating = False

    def _refresh_destination_mesh_context(
        self,
        select_name: Optional[str] = None,
    ) -> None:
        """Refresh destination blendShapes and UV sets.

        Parameters:
            select_name (str | None): Optional blendShape to select after
                refreshing, typically the node created by a transfer.

        Returns:
            None
        """

        if self._updating:
            return

        mesh_name = self.destination_mesh_edit.text().strip()
        mesh_key = (
            _object_key(mesh_name)
            if mesh_name and cmds.objExists(mesh_name)
            else mesh_name
        )
        if select_name is None and mesh_key == self._last_destination_mesh_key:
            return
        self._last_destination_mesh_key = mesh_key

        self._updating = True
        try:
            blend_shapes = _blendshapes_for_mesh(mesh_name)
            previous_blendshape = self.destination_blendshape_combo.currentText()

            self.destination_blendshape_combo.clear()
            self.destination_blendshape_combo.addItems(blend_shapes)
            self.destination_blendshape_combo.addItem(
                self.CREATE_NEW_LABEL
            )

            preferred_blendshape = select_name or previous_blendshape
            if preferred_blendshape == self.CREATE_NEW_LABEL:
                self.destination_blendshape_combo.setCurrentText(
                    self.CREATE_NEW_LABEL
                )
            elif preferred_blendshape in blend_shapes:
                self.destination_blendshape_combo.setCurrentText(
                    preferred_blendshape
                )
            elif blend_shapes:
                self.destination_blendshape_combo.setCurrentIndex(0)
            else:
                self.destination_blendshape_combo.setCurrentText(
                    self.CREATE_NEW_LABEL
                )

            if not blend_shapes:
                self.new_blendshape_name_edit.setText("blendShape")

            uv_sets, current_uv_set = _uv_sets_for_mesh(mesh_name)
            self.destination_uv_combo.clear()
            self.destination_uv_combo.addItems(uv_sets)
            if current_uv_set in uv_sets:
                self.destination_uv_combo.setCurrentText(current_uv_set)

            self._update_new_blendshape_state()
        finally:
            self._updating = False

    def _refresh_weight_list(self) -> None:
        """Rebuild the checked weight list from the source blendShape.

        Returns:
            None
        """

        self._updating_weight_checks = True
        try:
            self.weight_list.clear()
            blendshape_name = self.source_blendshape_combo.currentText()
            for target_name in _target_names(blendshape_name):
                item = QtWidgets.QListWidgetItem(target_name)
                item.setFlags(
                    item.flags() | QtCore.Qt.ItemIsUserCheckable
                )
                item.setCheckState(QtCore.Qt.Checked)
                self.weight_list.addItem(item)
            self.status_label.setText("")
        finally:
            self._updating_weight_checks = False

    def _update_new_blendshape_state(self) -> None:
        """Enable the new-name field only when creating a new blendShape.

        Returns:
            None
        """

        create_new = (
            self.destination_blendshape_combo.currentText()
            == self.CREATE_NEW_LABEL
        )
        self.new_blendshape_name_edit.setEnabled(create_new)

    def _selected_transfer_method(self) -> WeightsTransferMethod:
        """Return the transfer method chosen in the method combo.

        Returns:
            WeightsTransferMethod: The selected surface association, falling
                back to ``WeightsTransferMethod.UVS`` when the combo holds an
                unknown entry.
        """

        return TRANSFER_METHODS_BY_LABEL.get(
            self.transfer_method_combo.currentText(),
            WeightsTransferMethod.UVS,
        )

    def _update_uv_group_state(self) -> None:
        """Enable the UV-set fields only for the UV transfer method.

        Returns:
            None
        """

        uses_uvs = (
            self._selected_transfer_method() == WeightsTransferMethod.UVS
        )
        self.uv_group.setEnabled(uses_uvs)
        if uses_uvs:
            self.uv_group.setToolTip(
                "UV sets are used by the UV transfer method."
            )
        else:
            self.uv_group.setToolTip(
                "UV sets are only used by the UV transfer method."
            )

    # ------------------------------------------------------------------
    # UI callbacks
    # ------------------------------------------------------------------
    def _on_source_blendshape_changed(self, _text: str) -> None:
        """Refresh weight items when the source blendShape changes.

        Parameters:
            _text (str): Current blendShape combo text.

        Returns:
            None
        """

        if not self._updating:
            self._refresh_weight_list()

    def _on_destination_blendshape_changed(self, _text: str) -> None:
        """Update the new-name field when the destination choice changes.

        Parameters:
            _text (str): Current destination combo text.

        Returns:
            None
        """

        self._update_new_blendshape_state()

    def _on_transfer_method_changed(self, _text: str) -> None:
        """Enable or disable the UV-set fields for the chosen method.

        Parameters:
            _text (str): Current transfer-method combo text.

        Returns:
            None
        """

        self._update_uv_group_state()

    def _on_weight_item_changed(
        self,
        item: QtWidgets.QListWidgetItem,
    ) -> None:
        """Apply a checkbox change to every selected weight item.

        Parameters:
            item (QtWidgets.QListWidgetItem): Item whose check state changed.

        Returns:
            None
        """

        if self._updating_weight_checks:
            return

        selected_items = self.weight_list.selectedItems()
        if item not in selected_items or len(selected_items) < 2:
            return

        check_state = item.checkState()
        self._updating_weight_checks = True
        try:
            for selected_item in selected_items:
                if selected_item.checkState() != check_state:
                    selected_item.setCheckState(check_state)
        finally:
            self._updating_weight_checks = False

    def _pick_source_mesh(self) -> None:
        """Set the source mesh field from the current selection.

        Returns:
            None
        """

        self._pick_mesh(self.source_mesh_edit, self._refresh_source_mesh_context)

    def _pick_destination_mesh(self) -> None:
        """Set the destination mesh field from the current selection.

        Returns:
            None
        """

        self._pick_mesh(
            self.destination_mesh_edit,
            self._refresh_destination_mesh_context,
        )

    def _pick_mesh(
        self,
        line_edit: QtWidgets.QLineEdit,
        refresh_callback: Callable[[], None],
    ) -> None:
        """Set a mesh field to the first selected mesh and refresh it.

        Parameters:
            line_edit (QtWidgets.QLineEdit): Field to update.
            refresh_callback (Callable[[], None]): Context refresh function.

        Returns:
            None
        """

        mesh_name = _selected_mesh()
        if mesh_name is None:
            cmds.warning("Select a mesh before using the pick button.")
            return

        line_edit.setText(_short_name(mesh_name))
        refresh_callback()

    def _checked_weight_names(self) -> list[str]:
        """Return the names of all checked weight items.

        Returns:
            list[str]: Checked target names in source target order.
        """

        weight_names: list[str] = []
        for row in range(self.weight_list.count()):
            item = self.weight_list.item(row)
            if item.checkState() == QtCore.Qt.Checked:
                weight_names.append(item.text())
        return weight_names

    def _destination_blendshape_value(self) -> Optional[str]:
        """Return the selected destination blendShape or new name.

        Returns:
            str | None: Existing blendShape name, explicit new name, or
                ``None`` for an automatically named new blendShape.
        """

        combo_text = self.destination_blendshape_combo.currentText()
        if combo_text == self.CREATE_NEW_LABEL:
            new_name = self.new_blendshape_name_edit.text().strip()
            return new_name or None
        return combo_text or None

    def _transfer(self) -> None:
        """Validate the form and start the weight-map transfer.

        Returns:
            None
        """

        source_mesh = self.source_mesh_edit.text().strip()
        destination_mesh = self.destination_mesh_edit.text().strip()
        source_blendshape = self.source_blendshape_combo.currentText().strip()

        if not source_mesh or not destination_mesh:
            QtWidgets.QMessageBox.warning(
                self,
                "Missing Mesh",
                "Choose both a source and a destination mesh.",
            )
            return

        if _object_key(source_mesh) == _object_key(destination_mesh):
            QtWidgets.QMessageBox.warning(
                self,
                "Invalid Meshes",
                "The source and destination must be different meshes.",
            )
            return

        if not source_blendshape:
            QtWidgets.QMessageBox.warning(
                self,
                "Missing Source BlendShape",
                "Choose a source blendShape with target weights.",
            )
            return

        if self.weight_list.count() == 0:
            QtWidgets.QMessageBox.warning(
                self,
                "No Targets",
                "The selected source blendShape has no targets to transfer.",
            )
            return

        try:
            transfer_method = self._selected_transfer_method()
            result = transfer_blendshape_weight_maps(
                source_mesh=source_mesh,
                destination_mesh=destination_mesh,
                transfer_method=transfer_method,
                source_blendshape=source_blendshape,
                source_uv_set=self.source_uv_combo.currentText() or None,
                destination_uv_set=(
                    self.destination_uv_combo.currentText() or None
                ),
                destination_blendshape=self._destination_blendshape_value(),
                selected_weights=self._checked_weight_names(),
                organize_target_directories=(
                    self.organize_target_directories_check.isChecked()
                ),
            )
        except Exception as exc:
            cmds.warning(str(exc))
            QtWidgets.QMessageBox.critical(
                self,
                "Transfer Failed",
                str(exc),
            )
            return

        self.status_label.setText(
            f"Transferred weight maps to '{result}' using "
            f"{TRANSFER_METHOD_LABELS[transfer_method]}."
        )
        self._refresh_destination_mesh_context(select_name=result)


def show_window(
    parent: Optional[QtWidgets.QWidget] = None,
) -> None:
    """Open the blendShape weight-map transfer dialog.

    Parameters:
        parent (QtWidgets.QWidget | None): Optional parent widget. When omitted,
            Maya's main window is used.

    Returns:
        None
    """

    global WINDOW

    if WINDOW is not None:
        try:
            WINDOW.close()
        except RuntimeError:
            pass

    WINDOW = BlendshapeTransferUI(parent or _get_maya_main_window())
    WINDOW.show()
    WINDOW.raise_()
    WINDOW.activateWindow()
