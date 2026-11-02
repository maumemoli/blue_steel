"""PySide UI for the MM Tools mirror tools (MEL ``mirrorToolsUI`` port).

The dialog is a direct translation of the MEL window:

- *Selected geometry* and *Seam edge* show the rest-pose proxy and the seam
  edge stored by :func:`blue_steel.mmtools.mirror_tools.create_proxy`.
- **Define Rest Pose** / **Update Rest Pose** store the rest pose.
- **Actions** holds *Mirror* (one half) and *Flip* (whole shape).
- **Discard Rest pose and** holds *Symmetrize*, *Flip* and *Mirror*, which work
  directly on the selection.
- *Mirror Axis*, the ``L<<R`` / ``L>>R`` checkbox and *Seam Gradient %* drive
  the axis, the side kept by the mirror operations and the width of the
  bounding-box gradient that blends the mirrored half into the kept half.

Every button calls the matching function in
:mod:`blue_steel.mmtools.mirror_tools`; the dialog itself only reads and
writes the shared :data:`blue_steel.mmtools.mirror_tools.STATE`.

Attributes:
    WINDOW (MirrorToolsUI | None): The current dialog instance.
"""

from __future__ import annotations

from typing import Optional

from maya import cmds
import maya.OpenMayaUI as omui

from ... import env
from .. import mirror_tools

if env.ENVIRONMENT.MAYA_VERSION > 2024:
    from PySide6 import QtCore, QtWidgets
    from shiboken6 import wrapInstance
else:
    from PySide2 import QtCore, QtWidgets
    from shiboken2 import wrapInstance

WINDOW: Optional["MirrorToolsUI"] = None

POSITIVE_LABEL = "L<<R"
NEGATIVE_LABEL = "L>>R"


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


class MirrorToolsUI(QtWidgets.QDialog):
    """Dialog for mirroring and symmetrizing blendshape shapes.

    Attributes:
        WINDOW_TITLE (str): Title of the dialog window.
    """

    WINDOW_TITLE = "Mirror Tools"
    BUTTON_WIDTH = 100

    def __init__(
        self,
        parent: Optional[QtWidgets.QWidget] = None,
    ) -> None:
        """Build the dialog and mirror the current tool state into it.

        Parameters:
            parent (QtWidgets.QWidget | None): Optional parent widget.

        Returns:
            None
        """

        super().__init__(parent)
        self.setObjectName("MirrorToolsUI")
        self.setWindowTitle(self.WINDOW_TITLE)
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose)
        self.setMinimumWidth(220)

        mirror_tools.sync_state_with_scene()
        self._build_ui()
        self._refresh_fields()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        """Create every widget and connect its signal.

        Returns:
            None
        """

        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setSpacing(6)
        main_layout.setContentsMargins(6, 6, 6, 6)

        rest_pose_group = QtWidgets.QGroupBox("Rest Pose")
        rest_pose_form = QtWidgets.QFormLayout(rest_pose_group)
        rest_pose_form.setFieldGrowthPolicy(
            QtWidgets.QFormLayout.AllNonFixedFieldsGrow
        )

        self.selected_geometry_edit = QtWidgets.QLineEdit()
        self.selected_geometry_edit.setReadOnly(True)
        self.selected_geometry_edit.setPlaceholderText(
            "No rest pose defined"
        )
        self.selected_geometry_edit.setToolTip(
            "Hidden rest-pose proxy stored in "
            f"{mirror_tools.PROXY_GROUP_NAME}."
        )
        rest_pose_form.addRow("Selected geometry:", self.selected_geometry_edit)

        self.seam_edge_edit = QtWidgets.QLineEdit()
        self.seam_edge_edit.setReadOnly(True)
        self.seam_edge_edit.setPlaceholderText("No seam edge defined")
        self.seam_edge_edit.setToolTip(
            "Index of the middle edge used to split the mesh in halves."
        )
        rest_pose_form.addRow("Seam edge:", self.seam_edge_edit)

        rest_pose_buttons = QtWidgets.QHBoxLayout()
        rest_pose_buttons.setContentsMargins(0, 0, 0, 0)
        self.define_rest_pose_button = QtWidgets.QPushButton(
            "Define Rest Pose"
        )
        self.define_rest_pose_button.setFixedWidth(self.BUTTON_WIDTH)
        self.define_rest_pose_button.setToolTip(
            "Duplicate the selected mesh into the hidden rest-pose group and "
            "store the selected middle edge as the seam edge."
        )
        self.update_rest_pose_button = QtWidgets.QPushButton(
            "Update Rest Pose"
        )
        self.update_rest_pose_button.setToolTip(
            "Refresh the stored rest-pose proxy from the selected mesh, "
            "keeping the current seam edge."
        )
        rest_pose_buttons.addWidget(self.define_rest_pose_button)
        rest_pose_buttons.addWidget(self.update_rest_pose_button)
        rest_pose_form.addRow(rest_pose_buttons)
        main_layout.addWidget(rest_pose_group)

        actions_group = QtWidgets.QGroupBox("Actions")
        actions_layout = QtWidgets.QVBoxLayout(actions_group)
        actions_layout.setSpacing(4)
        actions_row = QtWidgets.QHBoxLayout()
        actions_row.setContentsMargins(0, 0, 0, 0)
        self.mirror_button = QtWidgets.QPushButton("Mirror")
        self.mirror_button.setFixedWidth(self.BUTTON_WIDTH)
        self.mirror_button.setToolTip(
            "Mirror the selected shapes across the seam so the kept side is "
            "preserved and the other side is flipped."
        )
        self.flip_button = QtWidgets.QPushButton("Flip")
        self.flip_button.setFixedWidth(self.BUTTON_WIDTH)
        self.flip_button.setToolTip(
            "Flip the selected shapes across the seam, replacing the whole "
            "shape with its mirrored version."
        )
        actions_row.addWidget(self.mirror_button)
        actions_row.addWidget(self.flip_button)
        actions_layout.addLayout(actions_row)
        main_layout.addWidget(actions_group)

        discard_group = QtWidgets.QGroupBox("Discard Rest pose and:")
        discard_layout = QtWidgets.QVBoxLayout(discard_group)
        discard_layout.setSpacing(4)
        discard_row = QtWidgets.QHBoxLayout()
        discard_row.setContentsMargins(0, 0, 0, 0)
        self.symmetrize_button = QtWidgets.QPushButton("Symmetrize")
        self.symmetrize_button.setToolTip(
            "Make the selected mesh symmetric by averaging it with its "
            "mirrored copy."
        )
        self.symmetrize_flip_button = QtWidgets.QPushButton("Flip")
        self.symmetrize_flip_button.setToolTip(
            "Replace the selected mesh with its mirrored copy."
        )
        self.symmetrize_mirror_button = QtWidgets.QPushButton("Mirror")
        self.symmetrize_mirror_button.setToolTip(
            "Mirror the selected mesh onto its opposite side."
        )
        discard_row.addWidget(self.symmetrize_button)
        discard_row.addWidget(self.symmetrize_flip_button)
        discard_row.addWidget(self.symmetrize_mirror_button)
        discard_layout.addLayout(discard_row)
        main_layout.addWidget(discard_group)

        settings_group = QtWidgets.QGroupBox("Settings")
        settings_form = QtWidgets.QFormLayout(settings_group)
        settings_form.setFieldGrowthPolicy(
            QtWidgets.QFormLayout.AllNonFixedFieldsGrow
        )
        self.axis_combo = QtWidgets.QComboBox()
        self.axis_combo.addItems(list(mirror_tools.AXES))
        self.axis_combo.setToolTip("Axis used to mirror and symmetrize.")
        settings_form.addRow("Mirror Axis:", self.axis_combo)

        self.negative_check = QtWidgets.QCheckBox(POSITIVE_LABEL)
        self.negative_check.setToolTip(
            "Unchecked (L<<R) keeps the positive side, checked (L>>R) keeps "
            "the negative side of the mirror axis."
        )
        settings_form.addRow(self.negative_check)

        self.gradient_band_spin = QtWidgets.QDoubleSpinBox()
        self.gradient_band_spin.setRange(0.0, 100.0)
        self.gradient_band_spin.setDecimals(1)
        self.gradient_band_spin.setSingleStep(1.0)
        self.gradient_band_spin.setSuffix(" %")
        self.gradient_band_spin.setValue(
            mirror_tools.STATE.gradient_band_percent
        )
        self.gradient_band_spin.setToolTip(
            "Width of the smooth blend across the symmetry plane, as a "
            "percentage of the rest-pose bounding box along the mirror axis. "
            "0 is a hard split, 100 blends across the whole model."
        )
        settings_form.addRow("Seam Gradient %:", self.gradient_band_spin)
        main_layout.addWidget(settings_group)

        self.status_label = QtWidgets.QLabel("")
        self.status_label.setWordWrap(True)
        main_layout.addWidget(self.status_label)

        close_row = QtWidgets.QHBoxLayout()
        close_row.addStretch(1)
        self.close_button = QtWidgets.QPushButton("Close")
        close_row.addWidget(self.close_button)
        main_layout.addLayout(close_row)

        self.define_rest_pose_button.clicked.connect(self._on_define_rest_pose)
        self.update_rest_pose_button.clicked.connect(self._on_update_rest_pose)
        self.mirror_button.clicked.connect(
            lambda: self._run(mirror_tools.flip, "Mirror done.", "mirror")
        )
        self.flip_button.clicked.connect(
            lambda: self._run(mirror_tools.flip, "Flip done.", "flip")
        )
        self.symmetrize_button.clicked.connect(
            lambda: self._run(
                mirror_tools.symmetrize,
                "Symmetrize done.",
                "sym",
            )
        )
        self.symmetrize_flip_button.clicked.connect(
            lambda: self._run(
                mirror_tools.symmetrize,
                "In-place flip done.",
                "flip",
            )
        )
        self.symmetrize_mirror_button.clicked.connect(
            lambda: self._run(
                mirror_tools.side_to_side,
                "In-place mirror done.",
            )
        )
        self.axis_combo.currentTextChanged.connect(self._on_axis_changed)
        self.negative_check.toggled.connect(self._on_negative_toggled)
        self.gradient_band_spin.valueChanged.connect(
            self._on_gradient_band_changed
        )
        self.close_button.clicked.connect(self.close)

    # ------------------------------------------------------------------
    # State synchronization
    # ------------------------------------------------------------------
    def _refresh_fields(self) -> None:
        """Show the current tool state in the read-only fields.

        Returns:
            None
        """

        state = mirror_tools.STATE
        self.selected_geometry_edit.setText(state.rest_geometry or "")
        self.seam_edge_edit.setText(state.seam_edge or "")

        self.axis_combo.blockSignals(True)
        self.axis_combo.setCurrentText(state.axis)
        self.axis_combo.blockSignals(False)

        self.negative_check.blockSignals(True)
        self.negative_check.setChecked(state.negative)
        self.negative_check.setText(
            NEGATIVE_LABEL if state.negative else POSITIVE_LABEL
        )
        self.negative_check.blockSignals(False)

        self.gradient_band_spin.blockSignals(True)
        self.gradient_band_spin.setValue(state.gradient_band_percent)
        self.gradient_band_spin.blockSignals(False)

    def _set_status(self, message: str, error: bool = False) -> None:
        """Write a status message under the buttons.

        Parameters:
            message (str): Message to display.
            error (bool): Paint the message red when ``True``.

        Returns:
            None
        """

        self.status_label.setText(message)
        self.status_label.setStyleSheet(
            "color: #e06c6c;" if error else "color: #9c9c9c;"
        )

    def _run(self, function, message: str, *args) -> None:
        """Call a mirror tool operation and report failures in the dialog.

        Parameters:
            function (Callable): Mirror tool function to call.
            message (str): Status text shown when the call succeeds.
            *args: Arguments forwarded to ``function``.

        Returns:
            None
        """

        try:
            function(*args)
        except Exception as error:  # noqa: BLE001 - surfaced to the artist
            error_message = str(error).strip().splitlines()[0]
            cmds.warning(error_message)
            self._set_status(error_message, error=True)
            QtWidgets.QMessageBox.critical(
                self,
                self.WINDOW_TITLE,
                error_message,
            )
            return
        self._refresh_fields()
        self._set_status(message)

    # ------------------------------------------------------------------
    # Callbacks
    # ------------------------------------------------------------------
    def _on_define_rest_pose(self) -> None:
        """Store the selected mesh and middle edge as the rest pose.

        Returns:
            None
        """

        self._run(mirror_tools.create_proxy, "Rest pose defined.", "c")

    def _on_update_rest_pose(self) -> None:
        """Refresh the rest-pose proxy from the selected mesh.

        Returns:
            None
        """

        self._run(mirror_tools.create_proxy, "Rest pose updated.", "u")

    def _on_axis_changed(self, axis: str) -> None:
        """Store the selected mirror axis.

        Parameters:
            axis (str): New axis label.

        Returns:
            None
        """

        if not axis:
            return
        mirror_tools.set_axis(axis)

    def _on_negative_toggled(self, checked: bool) -> None:
        """Store which side of the axis the mirror keeps.

        Parameters:
            checked (bool): ``True`` for ``L>>R``.

        Returns:
            None
        """

        mirror_tools.set_negative(checked)
        self.negative_check.setText(
            NEGATIVE_LABEL if checked else POSITIVE_LABEL
        )

    def _on_gradient_band_changed(self, value: float) -> None:
        """Store the seam blend band width.

        Parameters:
            value (float): Band width as a percentage of the bounding box.

        Returns:
            None
        """

        mirror_tools.set_gradient_band_percent(value)


def show_window(
    parent: Optional[QtWidgets.QWidget] = None,
) -> None:
    """Open the Mirror Tools dialog.

    Parameters:
        parent (QtWidgets.QWidget | None): Optional parent widget. When
            omitted, Maya's main window is used.

    Returns:
        None
    """

    global WINDOW

    if WINDOW is not None:
        try:
            WINDOW.close()
        except RuntimeError:
            pass

    WINDOW = MirrorToolsUI(parent or _get_maya_main_window())
    WINDOW.show()
    WINDOW.raise_()
    WINDOW.activateWindow()
