"""Ordered group/primary tree persisted on the editor container.

The primaries panel used to derive its folders from the blendshape target
directories. It is now driven by a JSON tree stored in the container attribute
:data:`blue_steel.env.Environment.FACE_CTRL_SORTING_ATTR_STRING_IDENTIFIER`
(``faceCtrlSorting``) and handled by :class:`FaceCtrlSortingStore`.

The store is deliberately Qt-free: the UI translates drag/drop and keyboard
gestures into :class:`FaceCtrlSortingStore` calls, and the store owns all
ordering, grouping, reparenting, and reconciliation logic. That keeps the tree
data unit-testable without Maya or a Qt event loop.

Example:
    >>> store = FaceCtrlSortingStore()
    >>> store.from_dict({"version": 1, "items": [
    ...     {"name": "GroupA", "type": "group",
    ...      "children": [{"name": "jawOpen", "type": "primary"}]},
    ...     {"name": "mouthSmile", "type": "primary"}]})
    >>> store.iter_primary_names()
    ['jawOpen', 'mouthSmile']
    >>> store.group(["mouthSmile"], "Mouth")
    'Mouth'
"""

from __future__ import annotations

from copy import deepcopy
from typing import Dict, Iterator, List, Optional, Sequence


SCHEMA_VERSION = 1
GROUP_TYPE = "group"
PRIMARY_TYPE = "primary"
_DEFAULT_GROUP_NAME = "Group"


class FaceCtrlSortingStore:
    """In-memory ordered tree of primary folders and leaves.

    The persisted payload is a nested tree that maps directly onto the Qt
    tree widget, so loading is a single depth-first pass::

        {
            "version": 1,
            "items": [
                {"name": "GroupA", "type": "group",
                 "children": [{"name": "jawOpen", "type": "primary"}]},
                {"name": "mouthSmile", "type": "primary"},
            ],
        }

    Nodes are indexed by name for O(1) lookups, mutations, and reparenting.
    """

    def __init__(self) -> None:
        self._items: List[dict] = []
        self._index: Dict[str, dict] = {}
        self._parent: Dict[str, Optional[str]] = {}

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------
    def load(self, editor) -> None:
        """Load the tree from ``editor``'s sorting attribute.

        Parameters:
            editor: A :class:`blue_steel.api.editor.BlueSteelEditor` exposing
                ``read_face_ctrl_sorting_attribute``.

        Returns:
            None
        """
        data = None
        if editor is not None and hasattr(editor, "read_face_ctrl_sorting_attribute"):
            try:
                data = editor.read_face_ctrl_sorting_attribute()
            except Exception:
                data = None
        self.from_dict(data)

    def save(self, editor) -> None:
        """Persist the tree onto ``editor``'s sorting attribute.

        Parameters:
            editor: A :class:`blue_steel.api.editor.BlueSteelEditor` exposing
                ``write_face_ctrl_sorting_attribute``.

        Returns:
            None
        """
        if editor is None or not hasattr(editor, "write_face_ctrl_sorting_attribute"):
            return
        editor.write_face_ctrl_sorting_attribute(self.to_dict())

    def to_dict(self) -> dict:
        """Return a JSON-serializable snapshot of the tree.

        Returns:
            dict: ``{"version": 1, "items": [...]}``.
        """
        return {"version": SCHEMA_VERSION, "items": deepcopy(self._items)}

    def from_dict(self, data) -> None:
        """Replace the current tree with ``data``.

        Tolerates ``None``, malformed payloads, the nested ``items`` schema,
        and the legacy flat ``{group_name: [names]}`` mapping. Unknown primary
        names are kept; :meth:`sync` reconciles them against the rig.

        Parameters:
            data (dict | None): The decoded attribute payload.

        Returns:
            None
        """
        self._items = []
        self._index = {}
        self._parent = {}
        raw_items = self._extract_items(data)
        for raw_node in raw_items:
            node = self._parse_node(raw_node, parent=None)
            if node is not None:
                self._items.append(node)
        self._reindex()

    # ------------------------------------------------------------------
    # Reconciliation
    # ------------------------------------------------------------------
    def sync(self, primary_names: Sequence[str], drop_empty_groups: bool = True) -> bool:
        """Reconcile the tree with the rig's actual primary names.

        Removes primaries that no longer exist, optionally drops groups left
        empty by the removal, and appends newly added primaries at the root in
        case-insensitive alphabetical order.

        Parameters:
            primary_names (Sequence[str]): Names of the primaries currently in
                the rig.
            drop_empty_groups (bool): When ``True`` (default) remove groups that
                contain no primaries after pruning.

        Returns:
            bool: ``True`` when the tree changed.
        """
        actual = {str(name) for name in primary_names}
        removed = False

        def prune(nodes: List[dict], parent: Optional[str]) -> List[dict]:
            nonlocal removed
            kept: List[dict] = []
            for node in nodes:
                name = node.get("name")
                if node.get("type") == PRIMARY_TYPE:
                    if name in actual:
                        kept.append(node)
                    else:
                        removed = True
                    continue
                node["children"] = prune(node.get("children", []), name)
                if drop_empty_groups and not node["children"]:
                    removed = True
                    continue
                kept.append(node)
            return kept

        self._items = prune(self._items, None)

        existing = set(self._index)
        missing = sorted((name for name in actual if name not in existing), key=str.lower)
        for name in missing:
            self._items.append({"name": name, "type": PRIMARY_TYPE})
            removed = True

        if removed:
            self._reindex()
        return removed

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------
    def contains(self, name: str) -> bool:
        """Return ``True`` when ``name`` exists in the tree."""
        return str(name) in self._index

    def is_group(self, name: str) -> bool:
        """Return ``True`` when ``name`` is a folder node."""
        node = self._index.get(str(name))
        return bool(node) and node.get("type") == GROUP_TYPE

    def parent_of(self, name: str) -> Optional[str]:
        """Return the parent folder name for ``name`` (``None`` at root)."""
        return self._parent.get(str(name))

    def iter_primary_names(self) -> Iterator[str]:
        """Yield primary names in display order (depth first)."""
        for node in self._iter_nodes(self._items):
            if node.get("type") == PRIMARY_TYPE:
                yield str(node.get("name"))

    def ordered_tree(self) -> List[dict]:
        """Return a deep copy of the nested tree for the view builder."""
        return deepcopy(self._items)

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------
    def add_primary(self, name: str, parent: Optional[str] = None) -> bool:
        """Append a primary leaf to ``parent`` (or the root).

        Parameters:
            name (str): Primary name.
            parent (Optional[str]): Existing folder name, or ``None`` for root.

        Returns:
            bool: ``True`` when a new leaf was added.
        """
        name = str(name)
        if not name or name in self._index:
            return False
        if parent is not None and not self.is_group(parent):
            return False
        node = {"name": name, "type": PRIMARY_TYPE}
        self._sibling_list(parent).append(node)
        self._index[name] = node
        self._parent[name] = parent
        return True

    def move(self, names: Sequence[str], target: str, position: str) -> bool:
        """Reorder or reparent ``names`` relative to ``target``.

        Parameters:
            names (Sequence[str]): Node names to move (deduplicated, ordered by
                their current display position).
            target (str): Existing node to anchor the move against.
            position (str): ``"before"``, ``"after"``, or ``"inside"``.

        Returns:
            bool: ``True`` when the tree changed.
        """
        target = str(target)
        if position not in {"before", "after", "inside"}:
            return False
        target_node = self._index.get(target)
        if target_node is None:
            return False
        if position == "inside" and target_node.get("type") != GROUP_TYPE:
            return False

        wanted = []
        seen = set()
        for name in self._ordered_names(names):
            name = str(name)
            if name == target or name in seen or name not in self._index:
                continue
            if any(self._is_ancestor(existing, name) for existing in seen):
                # A selected folder already carries this descendant.
                continue
            if self._is_ancestor(name, target):
                # Moving a node relative to one of its own descendants is a cycle.
                continue
            seen.add(name)
            wanted.append(name)
        if not wanted:
            return False

        # Detach first so index math on the target stays valid.
        detached = self._detach(wanted)
        if target not in self._index:
            # Target was inside the detached subtree; restore and abort.
            self._reinsert(detached)
            return False

        if position == "inside":
            target_node.setdefault("children", [])
            for node in detached:
                target_node["children"].append(node)
                self._parent[node["name"]] = target
        else:
            parent_name = self._parent.get(target)
            siblings = self._sibling_list(parent_name)
            index = siblings.index(self._index[target])
            if position == "after":
                index += 1
            for offset, node in enumerate(detached):
                siblings.insert(index + offset, node)
                self._parent[node["name"]] = parent_name

        self._reindex()
        return True

    def move_to_root(self, names: Sequence[str]) -> bool:
        """Move ``names`` (with their subtrees) to the end of the root level.

        Parameters:
            names (Sequence[str]): Node names to move.

        Returns:
            bool: ``True`` when the tree changed.
        """
        chosen: List[str] = []
        for name in self._ordered_names(names):
            name = str(name)
            if name not in self._index:
                continue
            if any(self._is_ancestor(existing, name) for existing in chosen):
                # A selected folder already carries this descendant.
                continue
            chosen.append(name)
        if not chosen:
            return False
        detached = self._detach(chosen)
        self._items.extend(detached)
        self._reindex()
        return True

    def group(self, names: Sequence[str], group_name: Optional[str] = None) -> str:
        """Create a folder containing ``names`` and return its name.

        The folder is inserted at the position of the first selected node, and
        the moved nodes keep their relative display order.

        Parameters:
            names (Sequence[str]): Names to move into the new folder.
            group_name (Optional[str]): Requested folder name; a unique name is
                generated when empty or already taken.

        Returns:
            str: The created folder name, or ``""`` when nothing was grouped.
        """
        wanted = [
            str(name) for name in self._ordered_names(names)
            if str(name) in self._index
        ]
        # Drop descendants whose folder is also selected to avoid double moves.
        normalized: List[str] = []
        chosen: List[str] = []
        for name in wanted:
            if any(self._is_ancestor(existing, name) for existing in chosen):
                continue
            chosen.append(name)
            normalized.append(name)
        wanted = normalized
        if not wanted:
            return ""

        unique_name = self._unique_name(group_name or _DEFAULT_GROUP_NAME)
        anchor = wanted[0]
        insert_parent = self._parent.get(anchor)
        siblings = self._sibling_list(insert_parent)
        insert_index = siblings.index(self._index[anchor])

        detached = self._detach(wanted)
        group_node = {"name": unique_name, "type": GROUP_TYPE, "children": []}
        for node in detached:
            group_node["children"].append(node)
            self._parent[node["name"]] = unique_name

        siblings.insert(insert_index, group_node)
        self._parent[unique_name] = insert_parent
        self._index[unique_name] = group_node
        self._reindex()
        return unique_name

    def ungroup(self, name: str) -> bool:
        """Dissolve a folder, promoting its children to the folder's parent.

        Parameters:
            name (str): Folder name.

        Returns:
            bool: ``True`` when a folder was dissolved.
        """
        name = str(name)
        node = self._index.get(name)
        if node is None or node.get("type") != GROUP_TYPE:
            return False
        parent_name = self._parent.get(name)
        siblings = self._sibling_list(parent_name)
        index = siblings.index(node)
        children = list(node.get("children", []))
        siblings.pop(index)
        for offset, child in enumerate(children):
            siblings.insert(index + offset, child)
            self._parent[child["name"]] = parent_name
        self._reindex()
        return True

    def remove(self, name: str) -> bool:
        """Remove a node and its subtree.

        Parameters:
            name (str): Node name.

        Returns:
            bool: ``True`` when the node existed.
        """
        name = str(name)
        node = self._index.get(name)
        if node is None:
            return False
        parent_name = self._parent.get(name)
        siblings = self._sibling_list(parent_name)
        siblings.remove(node)
        self._reindex()
        return True

    def rename(self, old_name: str, new_name: str) -> bool:
        """Rename a node in place.

        Parameters:
            old_name (str): Existing node name.
            new_name (str): Desired name; ignored when empty or already taken.

        Returns:
            bool: ``True`` when the node was renamed.
        """
        old_name = str(old_name)
        new_name = str(new_name)
        if not new_name or old_name == new_name:
            return False
        node = self._index.get(old_name)
        if node is None or new_name in self._index:
            return False
        node["name"] = new_name
        self._reindex()
        return True

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _extract_items(self, data) -> List[dict]:
        if isinstance(data, dict):
            if isinstance(data.get("items"), list):
                return list(data["items"])
            # Legacy flat mapping: {group_name: [primary, primary, ...]}.
            if data and all(isinstance(value, list) for value in data.values()):
                converted = []
                for group_name, members in data.items():
                    converted.append({
                        "name": str(group_name),
                        "type": GROUP_TYPE,
                        "children": [
                            {"name": str(member), "type": PRIMARY_TYPE}
                            for member in members
                        ],
                    })
                return converted
        if isinstance(data, list):
            return list(data)
        return []

    def _parse_node(self, raw, parent: Optional[str]) -> Optional[dict]:
        if not isinstance(raw, dict):
            return None
        name = raw.get("name")
        if name is None or str(name) == "":
            return None
        name = str(name)
        if name in self._index:
            return None
        node_type = raw.get("type")
        is_group = node_type == GROUP_TYPE or (node_type is None and isinstance(raw.get("children"), list))
        if is_group:
            node = {"name": name, "type": GROUP_TYPE, "children": []}
            self._index[name] = node
            self._parent[name] = parent
            for child in raw.get("children", []):
                parsed = self._parse_node(child, name)
                if parsed is not None:
                    node["children"].append(parsed)
            return node
        node = {"name": name, "type": PRIMARY_TYPE}
        self._index[name] = node
        self._parent[name] = parent
        return node

    def _reindex(self) -> None:
        index: Dict[str, dict] = {}
        parent: Dict[str, Optional[str]] = {}
        self._walk(self._items, None, index, parent)
        self._index = index
        self._parent = parent

    @staticmethod
    def _walk(nodes: List[dict], parent_name: Optional[str],
              index: Dict[str, dict], parents: Dict[str, Optional[str]]) -> None:
        for node in nodes:
            name = node["name"]
            index[name] = node
            parents[name] = parent_name
            if node.get("type") == GROUP_TYPE:
                FaceCtrlSortingStore._walk(node.get("children", []), name, index, parents)

    @staticmethod
    def _iter_nodes(nodes: List[dict]) -> Iterator[dict]:
        for node in nodes:
            yield node
            if node.get("type") == GROUP_TYPE:
                yield from FaceCtrlSortingStore._iter_nodes(node.get("children", []))

    def _ordered_names(self, names: Sequence[str]) -> List[str]:
        wanted = {str(name) for name in names}
        return [
            str(node["name"]) for node in self._iter_nodes(self._items)
            if node["name"] in wanted
        ]

    def _sibling_list(self, parent_name: Optional[str]) -> List[dict]:
        if parent_name is None:
            return self._items
        node = self._index.get(parent_name)
        if node is None:
            return self._items
        node.setdefault("children", [])
        return node["children"]

    def _detach(self, names: Sequence[str]) -> List[dict]:
        detached: List[dict] = []
        for name in names:
            node = self._index.get(name)
            if node is None:
                continue
            siblings = self._sibling_list(self._parent.get(name))
            if node in siblings:
                siblings.remove(node)
            detached.append(node)
        self._reindex()
        return detached

    def _reinsert(self, nodes: Sequence[dict]) -> None:
        for node in nodes:
            self._items.append(node)
        self._reindex()

    def _is_ancestor(self, ancestor: str, name: str) -> bool:
        current = self._parent.get(name)
        while current is not None:
            if current == ancestor:
                return True
            current = self._parent.get(current)
        return False

    def _unique_name(self, base: str) -> str:
        base = str(base)
        if base not in self._index:
            return base
        counter = 2
        while f"{base}{counter}" in self._index:
            counter += 1
        return f"{base}{counter}"
