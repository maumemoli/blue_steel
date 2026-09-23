"""Single source of truth for the Blue Steel version.

This module intentionally has **no imports** so it can be loaded in isolation
by the drag-and-drop installer (``drag_into_Maya_to_install.py``) before the
``blue_steel`` package is importable, without needing ``sys.path`` or
``sys.modules`` setup.

The value is the PEP 440 normalized form of the human-readable release tag
``v1.6.5-beta1`` (i.e. ``str(Version("v1.6.5-beta1"))``), which keeps the
generated ``.mod`` file contents unchanged.
"""

__version__ = "1.6.5-beta.1"
