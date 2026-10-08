"""Tests for Work Shape axis-extraction ordering.

Run: python releases/maya/BlueSteel/unittest/workShapeExtractionOrderingUt.py

``extract_axis_motion_from_work_shape`` should drop the extracted work shape
immediately below the shape it was extracted from in the persisted
``workShapeSorting`` tree. These tests exercise that behavior without Maya by
loading the pure :class:`TreeViewOrderingManager` directly and AST-extracting
the two production methods from ``api/editor.py`` (importing the module would
require Maya).

Only ``numpy`` and the ``undoable`` / ``timed`` decorators are needed to run
the extracted extraction method, so they are injected into its namespace.
"""
from __future__ import annotations

import ast
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

import numpy as np


API_DIR = Path(__file__).resolve().parents[1] / "scripts/blue_steel/api"
ATTRIBUTE_NAME = "workShapeSorting"


def _load_ordering_manager():
    """Import the pure ordering store without touching the Maya package."""
    path = API_DIR / "treeViewOrderingManager.py"
    spec = importlib.util.spec_from_file_location("treeViewOrderingManager", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.TreeViewOrderingManager


TreeViewOrderingManager = _load_ordering_manager()


def _load_editor_methods():
    """AST-extract the production methods so Maya is never imported."""
    path = API_DIR / "editor.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    wanted = {"_place_work_shape_after_in_sorting", "extract_axis_motion_from_work_shape"}
    methods = [
        node
        for cls in tree.body if isinstance(cls, ast.ClassDef)
        for node in cls.body
        if isinstance(node, ast.FunctionDef) and node.name in wanted
    ]
    namespace = {
        "VERBOSE": False,
        "np": np,
        "undoable": lambda func: func,
        "timed": lambda func: func,
    }
    exec(compile(ast.Module(body=methods, type_ignores=[]), str(path), "exec"), namespace)
    return (
        namespace["_place_work_shape_after_in_sorting"],
        namespace["extract_axis_motion_from_work_shape"],
    )


place_work_shape_after_in_sorting, extract_axis_motion_from_work_shape = _load_editor_methods()


def leaf(name):
    return {"name": name, "type": "primary"}


def group(name, children):
    return {"name": name, "type": "group", "children": list(children)}


class SortingHost:
    """Minimal editor host exposing the sorting-attribute read/write pair."""

    def __init__(self, items=None):
        self.attributes = {ATTRIBUTE_NAME: {"version": 1, "items": list(items or [])}}
        self.writes = 0

    def read_sorting_attribute(self, attr_name):
        return self.attributes.get(attr_name)

    def write_sorting_attribute(self, attr_name, data):
        self.attributes[attr_name] = data
        self.writes += 1

    def _work_shape_sorting_store(self):
        store = TreeViewOrderingManager(ATTRIBUTE_NAME)
        try:
            store.load(self)
        except Exception:
            store.from_dict(None)
        return store

    def ordered_names(self):
        return list(self._work_shape_sorting_store().iter_primary_names())

    def parent_of(self, name):
        return self._work_shape_sorting_store().parent_of(name)


class PlaceWorkShapeAfterInSortingTests(unittest.TestCase):
    def test_places_extracted_immediately_after_source_at_root(self):
        host = SortingHost([leaf("src"), leaf("other"), leaf("src_x_extracted")])
        place_work_shape_after_in_sorting(host, "src_x_extracted", "src")
        self.assertEqual(host.ordered_names(), ["src", "src_x_extracted", "other"])
        self.assertIsNone(host.parent_of("src_x_extracted"))

    def test_places_extracted_after_source_inside_its_group(self):
        host = SortingHost([group("Mouth", [leaf("src"), leaf("other")]), leaf("src_x_extracted")])
        place_work_shape_after_in_sorting(host, "src_x_extracted", "src")
        self.assertEqual(host.ordered_names(), ["src", "src_x_extracted", "other"])
        self.assertEqual(host.parent_of("src_x_extracted"), "Mouth")

    def test_noop_when_source_is_not_tracked_yet(self):
        host = SortingHost([leaf("other"), leaf("src_x_extracted")])
        place_work_shape_after_in_sorting(host, "src_x_extracted", "src")
        self.assertEqual(host.ordered_names(), ["other", "src_x_extracted"])
        self.assertEqual(host.writes, 0)


class ExtractAxisMotionOrderingTests(unittest.TestCase):
    def _make_host(self):
        """Build a host whose work blendshape returns a real numpy delta."""
        host = SortingHost()
        weight = Mock(id=0)
        extracted_weight = Mock(id=1)
        work = Mock()
        work.get_weight_by_name.side_effect = [weight, extracted_weight]
        work.get_target_delta.return_value = np.array([[1.0, -2.0, 3.0]])
        host.work_blendshape = work
        host.add_work_shape = Mock(return_value="src_x_extracted")
        host._place_work_shape_after_in_sorting = Mock()
        return host

    def test_extraction_places_result_after_source(self):
        host = self._make_host()
        result = extract_axis_motion_from_work_shape(host, "src", "x+")
        self.assertEqual(result, "src_x_extracted")
        host.add_work_shape.assert_called_once_with("src_xPositive_extracted")
        host._place_work_shape_after_in_sorting.assert_called_once_with("src_x_extracted", "src")

    def test_invalid_axis_raises_without_ordering(self):
        host = self._make_host()
        with self.assertRaises(ValueError):
            extract_axis_motion_from_work_shape(host, "src", "q")
        host._place_work_shape_after_in_sorting.assert_not_called()


if __name__ == "__main__":
    unittest.main()
