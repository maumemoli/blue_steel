"""Shared constants for the Blue Steel editor UI.

Colors, MIME types, and Qt role ids live here so models, delegates, views, and
the main window can import them from one place instead of redefining magic
strings and numbers.

Example:
    >>> from blue_steel.ui.editor import constants
    >>> constants.SHAPE_CUSTOM_COLORS["Red"]
    '#e74c3c'
"""

from __future__ import annotations

from .qt import Qt

# Custom shape colors offered in the Shapes panel color-filter row.
SHAPE_CUSTOM_COLORS = {
    "Red": "#e74c3c",
    "Blue": "#4a90d9",
    "Green": "#4ba66d",
    "Yellow": "#f1c40f",
    "Pink": "#e84393",
    "Purple": "#9b59b6",
}

# Custom MIME types used for editor drag-and-drop.
SHAPE_NAMES_MIME_TYPE = "application/x-blue-steel-shape-names"
PRIMARY_TREE_MIME_TYPE = "application/x-qabstractitemmodeldatalist"
SPLIT_MAP_MIME_TYPE = "application/x-blue-steel-split-map"

# Qt user-role ids used by the primaries tree (MainWindow + PrimaryTreeItem).
PRIMARY_TREE_NAME_ROLE = Qt.UserRole + 200
PRIMARY_TREE_FOLDER_ROLE = Qt.UserRole + 201
PRIMARY_TREE_SORT_VALUE_ROLE = Qt.UserRole + 905

# Stable ordering for the type sub-groups rendered in the Shapes tree.
TYPE_GROUP_ORDER = {
    "Primaries": 0,
    "Inbetweens": 1,
    "Combos": 2,
    "Combo Inbetweens": 3,
    "Other": 99,
}


def shape_type_group_name(shape_type: str) -> str:
    """Map a logical shape type to the display group used in the Shapes tree.

    Parameters:
        shape_type (str): The ``type`` role value for a shape row.

    Returns:
        str: The display group name.

    Example:
        >>> shape_type_group_name("ComboInbetweenShape")
        'Combo Inbetweens'
    """
    if shape_type == "PrimaryShape":
        return "Primaries"
    if shape_type == "InbetweenShape":
        return "Inbetweens"
    if shape_type == "ComboShape":
        return "Combos"
    if shape_type == "ComboInbetweenShape":
        return "Combo Inbetweens"
    return "Other"
