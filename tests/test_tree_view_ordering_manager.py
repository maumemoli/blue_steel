"""Maya-free tests for alphabetical primary insertion in the sorting tree.

The ordering store is deliberately Qt- and Maya-free, so this test loads
``treeViewOrderingManager.py`` straight from the released package instead of
importing ``blue_steel`` (whose ``__init__`` requires Maya).

Run with::

    python -m unittest discover -s tests -p "test_tree_view_ordering_manager.py"
"""

import importlib.util
import sys
import unittest
from pathlib import Path


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "releases"
    / "maya"
    / "BlueSteel"
    / "scripts"
    / "blue_steel"
    / "api"
    / "treeViewOrderingManager.py"
)


def _load_module():
    """Load the ordering store module from its file path."""
    spec = importlib.util.spec_from_file_location(
        "blue_steel_tree_view_ordering_manager_test", MODULE_PATH
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


tree_ordering = _load_module()
TreeViewOrderingManager = tree_ordering.TreeViewOrderingManager


def _items(store):
    """Return the flattened ``(name, level)`` display order of ``store``."""
    order = []

    def walk(nodes, level):
        for node in nodes:
            order.append((node["name"], level))
            walk(node.get("children", []), level + 1)

    walk(store.to_dict()["items"], 0)
    return order


def _root_names(store):
    """Return the root-level names in display order."""
    return [node["name"] for node in store.to_dict()["items"]]


class AlphabeticalInsertTests(unittest.TestCase):
    """New primaries are inserted in name order, existing order is untouched."""

    def test_add_primary_inserts_alphabetically_at_root(self):
        store = TreeViewOrderingManager(sort_new_primaries=True)
        for name in ("zAbc", "mAbc", "aAbc"):
            self.assertTrue(store.add_primary(name))
        self.assertEqual(_root_names(store), ["aAbc", "mAbc", "zAbc"])
        self.assertEqual(list(store.iter_primary_names()), ["aAbc", "mAbc", "zAbc"])
        # The node index and parents stay consistent after the inserts.
        self.assertIsNone(store.parent_of("aAbc"))
        self.assertTrue(store.contains("zAbc"))

    def test_insert_is_case_insensitive_with_deterministic_tie_break(self):
        store = TreeViewOrderingManager(sort_new_primaries=True)
        for name in ("Beta", "alpha", "ALPHA2", "Alpha"):
            store.add_primary(name)
        self.assertEqual(
            _root_names(store), ["Alpha", "alpha", "ALPHA2", "Beta"]
        )

    def test_groups_keep_their_slot_and_leaves_stay_sorted(self):
        store = TreeViewOrderingManager(sort_new_primaries=True)
        store.from_dict({
            "version": 1,
            "items": [
                {"name": "Mouth", "type": "group",
                 "children": [{"name": "jawOpen", "type": "primary"}]},
                {"name": "noseSneer", "type": "primary"},
            ],
        })
        self.assertTrue(store.add_primary("cheekPuff"))
        self.assertEqual(_root_names(store), ["Mouth", "cheekPuff", "noseSneer"])
        # A name sorting after every leaf still lands after the group.
        self.assertTrue(store.add_primary("zzTop"))
        self.assertEqual(
            _root_names(store), ["Mouth", "cheekPuff", "noseSneer", "zzTop"]
        )

    def test_add_primary_inside_group_sorts_group_children(self):
        store = TreeViewOrderingManager(sort_new_primaries=True)
        store.from_dict({
            "version": 1,
            "items": [
                {"name": "Mouth", "type": "group",
                 "children": [{"name": "jawOpen", "type": "primary"}]},
            ],
        })
        self.assertTrue(store.add_primary("chin", "Mouth"))
        children = store.to_dict()["items"][0]["children"]
        self.assertEqual([child["name"] for child in children], ["chin", "jawOpen"])
        self.assertEqual(store.parent_of("chin"), "Mouth")

    def test_duplicate_add_is_rejected_without_moving(self):
        store = TreeViewOrderingManager(sort_new_primaries=True)
        store.add_primary("jawOpen")
        store.add_primary("cheekPuff")
        self.assertFalse(store.add_primary("jawOpen"))
        self.assertEqual(_root_names(store), ["cheekPuff", "jawOpen"])


class AppendDefaultTests(unittest.TestCase):
    """The Work Shapes style store keeps appending new names last."""

    def test_default_store_appends(self):
        store = TreeViewOrderingManager()
        for name in ("zAbc", "aAbc", "mAbc"):
            store.add_primary(name)
        self.assertEqual(_root_names(store), ["zAbc", "aAbc", "mAbc"])

    def test_default_sync_appends_missing_names(self):
        store = TreeViewOrderingManager()
        store.add_primary("zAbc")
        self.assertTrue(store.sync(["zAbc", "aAbc"]))
        self.assertEqual(_root_names(store), ["zAbc", "aAbc"])


class SyncTests(unittest.TestCase):
    """The reconcile pass uses the same alphabetical placement as add_primary."""

    def test_sync_inserts_missing_names_alphabetically(self):
        store = TreeViewOrderingManager(sort_new_primaries=True)
        store.add_primary("noseSneer")
        self.assertTrue(store.sync(["noseSneer", "cheekPuff", "browDown"]))
        self.assertEqual(
            _root_names(store), ["browDown", "cheekPuff", "noseSneer"]
        )
        # A second sync with the same names is a no-op.
        self.assertFalse(store.sync(["noseSneer", "cheekPuff", "browDown"]))

    def test_sync_keeps_custom_order_and_places_missing_before_first_larger_leaf(self):
        store = TreeViewOrderingManager(sort_new_primaries=True)
        for name in ("zzz", "aaa"):
            store.add_primary(name)
        # Simulate a user drag/drop reordering to a non-alphabetical order.
        store.move(["zzz"], "aaa", "before")
        self.assertEqual(_root_names(store), ["zzz", "aaa"])
        self.assertTrue(store.sync(["zzz", "aaa", "mmm"]))
        self.assertEqual(_root_names(store), ["mmm", "zzz", "aaa"])

    def test_sync_prunes_removed_primaries_and_empty_groups(self):
        store = TreeViewOrderingManager(sort_new_primaries=True)
        store.from_dict({
            "version": 1,
            "items": [
                {"name": "Mouth", "type": "group",
                 "children": [{"name": "jawOpen", "type": "primary"}]},
                {"name": "noseSneer", "type": "primary"},
            ],
        })
        self.assertTrue(store.sync(["noseSneer", "cheekPuff"]))
        self.assertEqual(_root_names(store), ["cheekPuff", "noseSneer"])
        self.assertFalse(store.contains("Mouth"))
        self.assertFalse(store.contains("jawOpen"))


if __name__ == "__main__":
    unittest.main()
