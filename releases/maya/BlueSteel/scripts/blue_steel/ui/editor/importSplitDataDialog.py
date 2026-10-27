"""Dialog that collects the settings for importing Blue Steel split data.

The dialog replaces the raw directory dialog previously used by
``EditorOpsMixin._import_split_data``. It lets the user pick the split data
folder, choose how split map weights are transferred, and pick which split
data is imported (split groups and/or split maps).

The transfer method defaults to ``None``, which means the maps are imported by
vertex ID. Every other entry mirrors :class:`WeightsTransferMethod`. Those
methods need the ``neutral.obj`` written next to the split data, so they are
only selectable while that file exists in the chosen folder.

Example:
    >>> from blue_steel.ui.editor.importSplitDataDialog import ImportSplitDataDialog
    >>> dialog = ImportSplitDataDialog(initial_path="/tmp/split_data")
    >>> if dialog.exec():
    ...     print(dialog.import_path(), dialog.transfer_method())
"""

from __future__ import annotations

import os
from typing import Callable, Optional, Tuple

from maya import cmds

from ...mmtools.blendshape_transfer_tools import WeightsTransferMethod
from .qt import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

NEUTRAL_OBJ_FILENAME = "neutral.obj"
"""str: Neutral mesh file the source-mesh transfer methods are built from."""

TRANSFER_METHOD_ITEMS: Tuple[Tuple[Optional[WeightsTransferMethod], str], ...] = (
    (None, "None (Vertex ID)"),
    (WeightsTransferMethod.UVS, "UVs"),
    (WeightsTransferMethod.CLOSEST_POINT, "Closest Point"),
    (WeightsTransferMethod.CLOSEST_COMPONENT, "Closest Component"),
    (WeightsTransferMethod.RAY_CAST, "Ray Cast"),
)
"""tuple[tuple[Optional[WeightsTransferMethod], str], ...]: Combo entries.

The first entry is the default: ``None`` transfers the split map weights by
vertex ID and needs no ``neutral.obj``.
"""


def transfer_method_label(
    transfer_method: Optional[WeightsTransferMethod],
) -> str:
    """Return the dialog label of a transfer method.

    Parameters:
        transfer_method (Optional[WeightsTransferMethod]): Transfer method
            reported by the dialog, ``None`` for the vertex-ID transfer.

    Returns:
        str: The label shown in the transfer method combo, falling back to
            the vertex-ID label for unknown values.
    """

    for method, label in TRANSFER_METHOD_ITEMS:
        if method is transfer_method:
            return label
    return TRANSFER_METHOD_ITEMS[0][1]


def _maya_directory_picker(caption: str) -> Optional[str]:
    """Ask the user for a directory through Maya's native file dialog.

    Parameters:
        caption (str): Title shown in the dialog.

    Returns:
        Optional[str]: The chosen directory, or ``None`` when cancelled.
    """

    result = cmds.fileDialog2(
        caption=caption,
        fileMode=3,
        dialogStyle=2,
        okCaption="Select",
    )
    if not result:
        return None
    return result[0]


class ImportSplitDataDialog(QDialog):
    """Collect a split data folder, transfer method, and payload selection.

    Attributes:
        _path_edit (QLineEdit): Split data folder field.
        _browse_button (QPushButton): Opens the folder picker for the field.
        _transfer_combo (QComboBox): Transfer method selection.
        _neutral_hint_label (QLabel): Shown when ``neutral.obj`` is missing.
        _split_groups_checkbox (QCheckBox): Import split groups.
        _split_maps_checkbox (QCheckBox): Import split maps and weights.
        _import_button (QPushButton): Accept button of the button box.
        _neutral_obj_available (bool): Whether the current folder has a
            ``neutral.obj``.

    Example:
        >>> dialog = ImportSplitDataDialog(initial_path="/tmp/split_data")
        >>> dialog.transfer_method() is None
        True
    """

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        initial_path: str = "",
        directory_picker: Optional[Callable[[str], Optional[str]]] = None,
    ) -> None:
        """Build the dialog, optionally pre-filling the folder field.

        Parameters:
            parent (Optional[QWidget]): Parent widget for the modal dialog.
            initial_path (str): Folder shown in the path field on open.
            directory_picker (Optional[Callable[[str], Optional[str]]]):
                Callable that returns a directory for a caption. Defaults to
                Maya's native directory dialog; the editor injects its own
                wrapper so both dialogs stay consistent.

        Returns:
            None
        """

        super().__init__(parent)
        self._directory_picker = directory_picker or _maya_directory_picker
        self._neutral_obj_available = False
        self.setWindowTitle("Import Split Data")
        self.setMinimumWidth(500)
        self._build_ui()
        self._path_edit.setText(initial_path or "")
        self._refresh_state()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        """Create the fields, options, and button box of the dialog.

        Returns:
            None
        """

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        path_label = QLabel("Split Data Folder:", self)
        layout.addWidget(path_label)

        path_row = QHBoxLayout()
        self._path_edit = QLineEdit(self)
        self._path_edit.setPlaceholderText("Path to the split data folder")
        path_row.addWidget(self._path_edit, 1)
        self._browse_button = QPushButton("Browse...", self)
        self._browse_button.setToolTip("Browse for the split data folder")
        path_row.addWidget(self._browse_button, 0)
        layout.addLayout(path_row)

        method_label = QLabel("Transfer Method:", self)
        layout.addWidget(method_label)

        self._transfer_combo = QComboBox(self)
        for transfer_method, label in TRANSFER_METHOD_ITEMS:
            self._transfer_combo.addItem(label, transfer_method)
        layout.addWidget(self._transfer_combo)

        self._neutral_hint_label = QLabel(
            "neutral.obj was not found in this folder. Split maps can only be "
            "transferred by vertex ID.",
            self,
        )
        self._neutral_hint_label.setWordWrap(True)
        self._neutral_hint_label.setVisible(False)
        layout.addWidget(self._neutral_hint_label)

        layout.addSpacing(6)
        options_label = QLabel("Split Data To Import:", self)
        layout.addWidget(options_label)

        self._split_groups_checkbox = QCheckBox("Split Groups", self)
        self._split_groups_checkbox.setChecked(True)
        layout.addWidget(self._split_groups_checkbox)

        self._split_maps_checkbox = QCheckBox("Split Maps", self)
        self._split_maps_checkbox.setChecked(True)
        layout.addWidget(self._split_maps_checkbox)

        layout.addStretch(1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel,
            parent=self,
        )
        self._import_button = buttons.button(QDialogButtonBox.Ok)
        self._import_button.setText("Import")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._path_edit.textChanged.connect(self._on_path_changed)
        self._browse_button.clicked.connect(self._browse_for_path)
        self._split_groups_checkbox.toggled.connect(
            lambda _checked=False: self._refresh_state())
        self._split_maps_checkbox.toggled.connect(
            lambda _checked=False: self._refresh_state())

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------
    def _browse_for_path(self) -> None:
        """Open the folder picker and write the result into the path field.

        Returns:
            None
        """

        directory = self._directory_picker("Select Split Data Directory")
        if not directory:
            return
        self._path_edit.setText(directory)

    def _on_path_changed(self, _text: str) -> None:
        """Refresh the transfer method state after the path was edited.

        Parameters:
            _text (str): New field text, unused beyond triggering the refresh.

        Returns:
            None
        """

        self._refresh_state()

    def _refresh_state(self) -> None:
        """Re-evaluate ``neutral.obj``, the method items, and the Import button.

        Returns:
            None
        """

        path = self.import_path()
        self._neutral_obj_available = bool(path) and os.path.isfile(
            os.path.join(path, NEUTRAL_OBJ_FILENAME))
        self._update_transfer_method_items()
        self._neutral_hint_label.setVisible(
            bool(path) and not self._neutral_obj_available)
        self._import_button.setEnabled(self._is_selection_valid())

    def _update_transfer_method_items(self) -> None:
        """Enable only the methods the current folder can actually run.

        ``None`` (vertex ID) always stays available. The other entries need
        ``neutral.obj``, so they are disabled and the selection is reset to
        the vertex-ID entry while that file is missing.

        Returns:
            None
        """

        model = self._transfer_combo.model()
        for index in range(self._transfer_combo.count()):
            enabled = (
                self._neutral_obj_available
                or self._transfer_combo.itemData(index) is None
            )
            item = model.item(index) if hasattr(model, "item") else None
            if item is not None:
                item.setEnabled(enabled)

        if not self._neutral_obj_available:
            self._transfer_combo.setCurrentIndex(0)

        if self._neutral_obj_available:
            self._transfer_combo.setToolTip(
                "Transfer split map weights from neutral.obj to the current mesh.")
        else:
            self._transfer_combo.setToolTip(
                "neutral.obj is missing, so the weights can only be "
                "transferred by vertex ID.")

    def _is_selection_valid(self) -> bool:
        """Return whether the current selections allow an import.

        Returns:
            bool: ``True`` when the folder exists and at least one split data
                type is selected.
        """

        path = self.import_path()
        if not path or not os.path.isdir(path):
            return False
        return self.import_settings() or self.import_weights()

    # ------------------------------------------------------------------
    # Results
    # ------------------------------------------------------------------
    def import_path(self) -> str:
        """Return the split data folder typed into the dialog.

        Returns:
            str: The expanded folder path, or ``""`` when the field is empty.
        """

        path = (self._path_edit.text() or "").strip()
        return os.path.expanduser(path) if path else ""

    def transfer_method(self) -> Optional[WeightsTransferMethod]:
        """Return the selected transfer method.

        Returns:
            Optional[WeightsTransferMethod]: The selected enum member, or
                ``None`` for the default vertex-ID transfer.
        """

        transfer_method = self._transfer_combo.currentData()
        return (
            transfer_method
            if isinstance(transfer_method, WeightsTransferMethod)
            else None
        )

    def import_settings(self) -> bool:
        """Return whether split groups should be imported.

        Returns:
            bool: ``True`` when the Split Groups checkbox is checked.
        """

        return self._split_groups_checkbox.isChecked()

    def import_weights(self) -> bool:
        """Return whether split maps should be imported.

        Returns:
            bool: ``True`` when the Split Maps checkbox is checked.
        """

        return self._split_maps_checkbox.isChecked()
