"""Unit tests for :class:`FaceCtrlSortingStore`.

Run: python releases/maya/BlueSteel/unittest/faceCtrlSortingUt.py

The store is pure Python, so these tests run without Maya or Qt. The module is
loaded directly from its file path to avoid importing the ``blue_steel``
package (whose ``__init__`` requires Maya).
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts/blue_steel/api/faceCtrlSorting.py"
SPEC = importlib.util.spec_from_file_location("faceCtrlSorting", MODULE_PATH)
face_ctrl_sorting = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = face_ctrl_sorting
SPEC.loader.exec_module(face_ctrl_sorting)

FaceCtrlSortingStore = face_ctrl_sorting.FaceCtrlSortingStore


def leaf(name):
    return {"name": name, "type": "primary"}


def group(name, children):
    return {"name": name, "type": "group", "children": list(children)}


class FakeEditor:
    """Minimal editor exposing the sorting attribute read/write pair."""

    def __init__(self, data=None):
        self.data = data
        self.writes = 0

    def read_face_ctrl_sorting_attribute(self):
        return self.data

    def write_face_ctrl_sorting_attribute(self, data):
        self.data = data
        self.writes += 1


def make_store(items):
    store = FaceCtrlSortingStore()
    store.from_dict({"version": 1, "items": items})
    return store


class FaceCtrlSortingStoreTests(unittest.TestCase):
    def test_empty_payload_starts_clean(self):
        for payload in (None, {}, {"version": 1}, ""):
            store = FaceCtrlSortingStore()
            store.from_dict(payload)
            self.assertEqual(store.ordered_tree(), [])
            self.assertEqual(list(store.iter_primary_names()), [])

    def test_legacy_flat_mapping_is_loaded(self):
        store = FaceCtrlSortingStore()
        store.from_dict({"Face": ["jawOpen", "mouthSmile"]})
        self.assertTrue(store.is_group("Face"))
        self.assertEqual(store.parent_of("jawOpen"), "Face")
        self.assertEqual(list(store.iter_primary_names()), ["jawOpen", "mouthSmile"])

    def test_duplicate_names_are_ignored(self):
        store = make_store([leaf("a"), leaf("a"), group("G", [leaf("a")])])
        self.assertEqual(list(store.iter_primary_names()), ["a"])

    def test_sync_adds_missing_and_prunes_removed(self):
        store = make_store([group("G", [leaf("a"), leaf("b")]), leaf("c")])
        changed = store.sync(["a", "c", "d"])
        self.assertTrue(changed)
        names = list(store.iter_primary_names())
        self.assertEqual(names, ["a", "c", "d"])
        self.assertNotIn("b", names)
        self.assertFalse(store.sync(["a", "c", "d"]))

    def test_sync_drops_empty_groups(self):
        store = make_store([group("G", [leaf("a")]), leaf("b")])
        store.sync(["b"])
        self.assertFalse(store.is_group("G"))
        self.assertEqual(store.ordered_tree(), [leaf("b")])

    def test_sync_keeps_empty_groups_when_asked(self):
        store = make_store([group("G", [leaf("a")]), leaf("b")])
        store.sync(["b"], drop_empty_groups=False)
        self.assertTrue(store.is_group("G"))
        self.assertEqual(store.ordered_tree(), [group("G", []), leaf("b")])

    def test_move_reorders_siblings(self):
        store = make_store([leaf("a"), leaf("b"), leaf("c")])
        self.assertTrue(store.move(["c"], "a", "before"))
        self.assertEqual(list(store.iter_primary_names()), ["c", "a", "b"])
        self.assertTrue(store.move(["c"], "b", "after"))
        self.assertEqual(list(store.iter_primary_names()), ["a", "b", "c"])

    def test_move_inside_reparents(self):
        store = make_store([leaf("a"), group("G", [leaf("b")])])
        self.assertTrue(store.move(["a"], "G", "inside"))
        self.assertEqual(store.parent_of("a"), "G")
        self.assertEqual(list(store.iter_primary_names()), ["b", "a"])

    def test_move_inside_rejected_for_primary_target(self):
        store = make_store([leaf("a"), leaf("b")])
        self.assertFalse(store.move(["a"], "b", "inside"))
        self.assertEqual(list(store.iter_primary_names()), ["a", "b"])

    def test_move_rejects_cycle(self):
        store = make_store([group("G", [group("H", [leaf("a")])])])
        self.assertFalse(store.move(["G"], "H", "inside"))
        self.assertTrue(store.contains("G"))

    def test_move_folder_carries_descendants_once(self):
        store = make_store([
            group("G", [leaf("a"), leaf("b")]),
            leaf("c"),
        ])
        self.assertTrue(store.move(["G", "a"], "c", "after"))
        self.assertEqual(store.ordered_tree(), [leaf("c"), group("G", [leaf("a"), leaf("b")])])

    def test_move_folder_before_and_after_sibling_folders(self):
        store = make_store([
            group("A", [leaf("a")]),
            group("B", [leaf("b")]),
            leaf("c"),
        ])
        self.assertTrue(store.move(["B"], "A", "before"))
        self.assertEqual(
            store.ordered_tree(),
            [group("B", [leaf("b")]), group("A", [leaf("a")]), leaf("c")],
        )
        self.assertTrue(store.move(["B"], "A", "after"))
        self.assertEqual(
            store.ordered_tree(),
            [group("A", [leaf("a")]), group("B", [leaf("b")]), leaf("c")],
        )

    def test_move_folder_inside_nests_subtree(self):
        store = make_store([
            group("A", [leaf("a")]),
            group("B", [leaf("b"), leaf("c")]),
        ])
        self.assertTrue(store.move(["B"], "A", "inside"))
        self.assertEqual(
            store.ordered_tree(),
            [group("A", [leaf("a"), group("B", [leaf("b"), leaf("c")])])],
        )
        self.assertEqual(store.parent_of("B"), "A")
        self.assertEqual(store.parent_of("c"), "B")

    def test_move_nested_folder_back_to_root(self):
        store = make_store([group("A", [group("B", [leaf("b")])])])
        self.assertTrue(store.move(["B"], "A", "after"))
        self.assertEqual(
            store.ordered_tree(),
            [group("A", []), group("B", [leaf("b")])],
        )
        self.assertEqual(store.parent_of("B"), None)

    def test_move_to_root_from_nested_group(self):
        store = make_store([
            group("A", [group("B", [leaf("b")]), leaf("a")]),
            leaf("c"),
        ])
        self.assertTrue(store.move_to_root(["B"]))
        self.assertEqual(
            store.ordered_tree(),
            [group("A", [leaf("a")]), leaf("c"), group("B", [leaf("b")])],
        )
        self.assertIsNone(store.parent_of("B"))
        self.assertEqual(store.parent_of("b"), "B")

    def test_move_to_root_ignores_selected_descendants(self):
        store = make_store([group("A", [group("B", [leaf("b")])])])
        self.assertTrue(store.move_to_root(["B", "b"]))
        self.assertEqual(
            store.ordered_tree(),
            [group("A", []), group("B", [leaf("b")])],
        )

    def test_move_to_root_noop_on_unknown_names(self):
        store = make_store([leaf("a")])
        self.assertFalse(store.move_to_root(["missing"]))
        self.assertEqual(store.ordered_tree(), [leaf("a")])

    def test_group_creates_folder_and_preserves_order(self):
        store = make_store([leaf("a"), leaf("b"), leaf("c")])
        created = store.group(["a", "c"], "Mouth")
        self.assertEqual(created, "Mouth")
        self.assertEqual(
            store.ordered_tree(),
            [group("Mouth", [leaf("a"), leaf("c")]), leaf("b")],
        )

    def test_group_generates_unique_name(self):
        store = make_store([leaf("a"), group("Group", [leaf("b")])])
        created = store.group(["a"], "Group")
        self.assertEqual(created, "Group2")

    def test_group_with_no_valid_names_returns_empty(self):
        store = make_store([leaf("a")])
        self.assertEqual(store.group(["missing"]), "")
        self.assertFalse(store.contains("missing"))

    def test_ungroup_promotes_children(self):
        store = make_store([leaf("a"), group("G", [leaf("b"), group("H", [leaf("c")])])])
        self.assertTrue(store.ungroup("G"))
        self.assertEqual(
            store.ordered_tree(),
            [leaf("a"), leaf("b"), group("H", [leaf("c")])],
        )
        self.assertFalse(store.is_group("G"))

    def test_ungroup_rejects_leaf(self):
        store = make_store([leaf("a")])
        self.assertFalse(store.ungroup("a"))

    def test_remove_subtree(self):
        store = make_store([group("G", [leaf("a")]), leaf("b")])
        self.assertTrue(store.remove("G"))
        self.assertEqual(store.ordered_tree(), [leaf("b")])
        self.assertFalse(store.contains("a"))
        self.assertFalse(store.remove("missing"))

    def test_rename(self):
        store = make_store([group("G", [leaf("a")])])
        self.assertTrue(store.rename("G", "Face"))
        self.assertTrue(store.is_group("Face"))
        self.assertEqual(store.parent_of("a"), "Face")
        self.assertFalse(store.rename("Face", "a"))
        self.assertFalse(store.rename("Face", "Face"))

    def test_add_primary(self):
        store = make_store([group("G", [])])
        self.assertTrue(store.add_primary("a"))
        self.assertFalse(store.add_primary("a"))
        self.assertTrue(store.add_primary("b", "G"))
        self.assertEqual(store.parent_of("a"), None)
        self.assertEqual(store.parent_of("b"), "G")
        self.assertFalse(store.add_primary("c", "missing"))

    def test_ordered_tree_is_a_deep_copy(self):
        store = make_store([group("G", [leaf("a")])])
        snapshot = store.ordered_tree()
        snapshot[0]["children"].append(leaf("x"))
        snapshot[0]["name"] = "Changed"
        self.assertEqual(store.ordered_tree(), [group("G", [leaf("a")])])

    def test_load_and_save_round_trip(self):
        editor = FakeEditor(data=None)
        store = FaceCtrlSortingStore()
        store.load(editor)
        store.add_primary("a")
        store.group(["a"], "G")
        store.save(editor)
        self.assertEqual(editor.writes, 1)

        reloaded = FaceCtrlSortingStore()
        reloaded.load(editor)
        self.assertEqual(reloaded.ordered_tree(), [group("G", [leaf("a")])])

    def test_load_tolerates_read_failure(self):
        class BrokenEditor:
            def read_face_ctrl_sorting_attribute(self):
                raise RuntimeError("boom")

        store = FaceCtrlSortingStore()
        store.load(BrokenEditor())
        self.assertEqual(store.ordered_tree(), [])


if __name__ == "__main__":
    unittest.main()
