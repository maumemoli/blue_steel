"""Shared helpers for the Blue Steel editor main window.

These are small decorators and utilities that remove the repetitive guard and
tracker-pause patterns used across the many ``MainWindow`` action handlers.

Example:
    >>> from blue_steel.ui.editor import mainWindowMixin as helpers
    >>> names = helpers.target_shape_names("jawOpen", ["jawOpen", "lipCorner"])
"""

from __future__ import annotations

from functools import wraps
from typing import List, Sequence


class MainWindowMixin:
    """Cooperative base for the ``MainWindow`` feature mixins.

    ``MainWindow`` participates in Qt's cooperative ``super().__init__`` chain,
    so every mixin must forward constructor arguments to the next class in the
    method resolution order instead of swallowing them.

    Example:
        >>> class MyMixin(MainWindowMixin):
        ...     pass
    """

    def __init__(self, *args, **kwargs) -> None:
        # These mixins sit after the Qt widget classes in the MRO. Qt's
        # cooperative ``super().__init__`` chain can still be carrying
        # constructor arguments (such as ``parent``) when it reaches us, and
        # forwarding them to ``object.__init__`` would raise. Swallow them and
        # finish the chain with a clean ``object.__init__()``.
        super().__init__()


def requires_editor(func):
    """Decorate a handler that needs ``self.current_editor`` to be set.

    When no editor is selected the handler sets a warning status and returns
    ``None`` instead of running its body.

    Example:
        >>> @requires_editor
        ... def remove_selected(self):
        ...     ...
    """
    @wraps(func)
    def wrapper(self, *args, **kwargs):
        if getattr(self, "current_editor", None) is None:
            self._set_status("No system selected.", warning=True)
            return None
        return func(self, *args, **kwargs)

    return wrapper


def pause_active_trackers(func):
    """Decorate a handler that mutates blendshape data while trackers are live.

    The call is wrapped with ``_stop_active_blendshape_trackers`` and
    ``_start_active_blendshape_trackers`` so Maya attribute callbacks do not
    fire while the editor performs a mutation.

    Example:
        >>> @pause_active_trackers
        ... def delete_shapes(self):
        ...     ...
    """
    @wraps(func)
    def wrapper(self, *args, **kwargs):
        self._stop_active_blendshape_trackers()
        try:
            return func(self, *args, **kwargs)
        finally:
            self._start_active_blendshape_trackers()

    return wrapper


def target_shape_names(shape_name: str, selected_names: Sequence[str]) -> List[str]:
    """Return the ordered name list a multi-select handler should apply to.

    Parameters:
        shape_name (str): The name of the clicked shape.
        selected_names (Sequence[str]): Currently selected shape names.

    Returns:
        List[str]: The deduplicated selected names when ``shape_name`` is among
        them, otherwise a single-element list containing ``shape_name``.

    Example:
        >>> target_shape_names("b", ["a", "b", "b"])
        ['a', 'b']
        >>> target_shape_names("c", ["a", "b"])
        ['c']
    """
    if shape_name in selected_names:
        return list(dict.fromkeys(str(name) for name in selected_names))
    return [str(shape_name)]
