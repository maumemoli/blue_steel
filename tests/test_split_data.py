"""Tests for the Maya-free split data helpers in ``logic/splitData.py``.

``blue_steel/__init__`` and ``env`` require a live Maya session, so the module
is loaded from its released path with lightweight package and env stubs.

Run with::

    python -m unittest discover -s tests -p "test_split_data.py"
"""

import importlib.util
import itertools
import sys
import types
import unittest
from pathlib import Path

import numpy as np


PACKAGE_ROOT = (
    Path(__file__).resolve().parents[1]
    / "releases"
    / "maya"
    / "BlueSteel"
    / "scripts"
    / "blue_steel"
)
MODULE_NAME = "_split_data_test_pkg.logic.splitData"


def _load_split_data():
    """Load ``splitData`` with a stub package exposing a minimal ``env``."""
    package = types.ModuleType("_split_data_test_pkg")
    package.__path__ = []
    logic = types.ModuleType("_split_data_test_pkg.logic")
    logic.__path__ = []
    env = types.ModuleType("_split_data_test_pkg.env")
    env.ENVIRONMENT = types.SimpleNamespace(SEPARATOR="_", SHAPE_NAME_STR="<<SHAPE_NAME>>")
    package.env = env
    sys.modules["_split_data_test_pkg"] = package
    sys.modules["_split_data_test_pkg.logic"] = logic
    sys.modules["_split_data_test_pkg.env"] = env
    spec = importlib.util.spec_from_file_location(MODULE_NAME, PACKAGE_ROOT / "logic" / "splitData.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[MODULE_NAME] = module
    spec.loader.exec_module(module)
    return module


split_data_module = _load_split_data()
SHAPE_NAME = "<<SHAPE_NAME>>"


class FakeParent(str):
    def __new__(cls, name, value="100"):
        obj = str.__new__(cls, name)
        obj.str_values = [value]
        return obj


class FakeShape(str):
    """Duck-typed Shape: name, primaries and parents (with str_values)."""

    def __new__(cls, name, parents):
        obj = str.__new__(cls, name)
        obj.primaries = [primary for primary, _ in parents]
        obj.parents = [
            FakeParent(primary if value == "100" else f"{primary}{value}", value)
            for primary, value in parents
        ]
        return obj


SPLIT_MAP_AREAS = {
    "side": ["side_L", "side_R"],
    "mouthSide": ["mouthSide_L", "mouthSide_R"],
    "tb": ["tb_T", "tb_B"],
    "lcr": ["lcr_L", "lcr_C", "lcr_R"],
}
SPLIT_GROUPS = {
    "LR": [SHAPE_NAME, "side"],
    "MouthLR": [SHAPE_NAME, "mouthSide"],
    "TBLR": ["tb", SHAPE_NAME, "side"],
    "LCR": [SHAPE_NAME, "lcr"],
}


def _build(shapes, primary_split_groups):
    return split_data_module.build_split_data(shapes=shapes,
                                              primary_split_groups=primary_split_groups,
                                              split_groups=SPLIT_GROUPS,
                                              split_map_areas=SPLIT_MAP_AREAS)


def _random_area_values(rng, vertex_count=50):
    """Normalized random weights for every split map."""
    area_values = {}
    for areas in SPLIT_MAP_AREAS.values():
        raw = rng.random((len(areas), vertex_count))
        raw /= raw.sum(axis=0)
        for area, values in zip(areas, raw):
            area_values[area] = values
    return area_values


def _shape_weight_sum(data, shape, area_values):
    total = 0.0
    for split_shape in data.split_shapes[shape]:
        areas = data.get_split_areas(split_shape)
        total = total + split_data_module.compute_split_weight_values(areas, SPLIT_MAP_AREAS, area_values)
    return total


class SplitWeightNameTest(unittest.TestCase):
    def test_sorted_join(self):
        self.assertEqual(split_data_module.make_split_weight_name(["tb_T", "side_L"]), "side_L_tb_T")

    def test_no_split(self):
        self.assertEqual(split_data_module.make_split_weight_name([]), split_data_module.NO_SPLIT_WEIGHT)


class LinkedGroupsTest(unittest.TestCase):
    def test_same_endings_are_linked(self):
        groups = split_data_module._group_linked_split_maps(["side", "tb", "mouthSide"], SPLIT_MAP_AREAS)
        self.assertEqual(groups, [["side", "mouthSide"], ["tb"]])

    def test_different_ending_sets_are_not_linked(self):
        groups = split_data_module._group_linked_split_maps(["side", "lcr"], SPLIT_MAP_AREAS)
        self.assertEqual(groups, [["side"], ["lcr"]])


class BuildSplitDataTest(unittest.TestCase):
    def test_unlinked_names_unchanged(self):
        shapes = [FakeShape("browUp", [("browUp", "100")]),
                  FakeShape("jawOpen", [("jawOpen", "100")]),
                  FakeShape("browUp50", [("browUp", "50")]),
                  FakeShape("browUp_jawOpen", [("browUp", "100"), ("jawOpen", "100")])]
        data = _build(shapes, {"browUp": "LR", "jawOpen": "NoSplit"})
        self.assertEqual(data.split_shapes["browUp"], ["browUpL", "browUpR"])
        self.assertEqual(data.split_shapes["jawOpen"], [])
        self.assertEqual(data.split_shapes["browUp50"], ["browUpL50", "browUpR50"])
        self.assertEqual(data.split_shapes["browUp_jawOpen"], ["browUpL_jawOpen", "browUpR_jawOpen"])

    def test_linked_maps_only_produce_matching_areas(self):
        shape = FakeShape("browUp_lipPucker", [("browUp", "100"), ("lipPucker", "100")])
        data = _build([shape], {"browUp": "LR", "lipPucker": "MouthLR"})
        self.assertEqual(data.split_shapes["browUp_lipPucker"],
                         ["browUpL_lipPuckerL", "browUpR_lipPuckerR"])
        self.assertEqual(data.get_split_weight("browUpL_lipPuckerL"), "mouthSide_L_side_L")

    def test_linked_and_independent_maps(self):
        shape = FakeShape("browUp_lipPucker", [("browUp", "100"), ("lipPucker", "100")])
        data = _build([shape], {"browUp": "TBLR", "lipPucker": "MouthLR"})
        self.assertEqual(sorted(data.split_shapes["browUp_lipPucker"]),
                         sorted(["TBrowUpL_lipPuckerL", "TBrowUpR_lipPuckerR",
                                 "BBrowUpL_lipPuckerL", "BBrowUpR_lipPuckerR"]))

    def test_different_ending_sets_keep_all_pairings(self):
        shape = FakeShape("browUp_lipPucker", [("browUp", "100"), ("lipPucker", "100")])
        data = _build([shape], {"browUp": "LR", "lipPucker": "LCR"})
        self.assertEqual(len(data.split_shapes["browUp_lipPucker"]), 6)


class ComputeSplitWeightValuesTest(unittest.TestCase):
    def test_no_areas_is_all_ones(self):
        values = split_data_module.compute_split_weight_values([], SPLIT_MAP_AREAS, {}, vertex_count=3)
        np.testing.assert_array_equal(values, np.ones(3))

    def test_equal_linked_maps_keep_values(self):
        side_l = np.array([0.0, 0.25, 0.5, 1.0])
        area_values = {"side_L": side_l, "side_R": 1 - side_l,
                       "mouthSide_L": side_l.copy(), "mouthSide_R": 1 - side_l}
        values = split_data_module.compute_split_weight_values(["side_L", "mouthSide_L"],
                                                               SPLIT_MAP_AREAS, area_values)
        np.testing.assert_allclose(values, side_l)

    def test_different_linked_maps_are_averaged(self):
        area_values = {"side_L": np.array([0.7]), "side_R": np.array([0.3]),
                       "mouthSide_L": np.array([0.5]), "mouthSide_R": np.array([0.5])}
        left = split_data_module.compute_split_weight_values(["side_L", "mouthSide_L"],
                                                             SPLIT_MAP_AREAS, area_values)
        right = split_data_module.compute_split_weight_values(["side_R", "mouthSide_R"],
                                                              SPLIT_MAP_AREAS, area_values)
        np.testing.assert_allclose(left, [0.6])
        np.testing.assert_allclose(right, [0.4])

    def test_independent_maps_are_multiplied(self):
        area_values = {"side_L": np.array([0.5]), "tb_T": np.array([0.4])}
        values = split_data_module.compute_split_weight_values(["side_L", "tb_T"],
                                                               SPLIT_MAP_AREAS, area_values)
        np.testing.assert_allclose(values, [0.2])

    def test_unknown_area_raises(self):
        with self.assertRaises(ValueError):
            split_data_module.compute_split_weight_values(["nope_L"], SPLIT_MAP_AREAS, {})


class PartitionOfUnityTest(unittest.TestCase):
    """The split weights of a shape must sum to 1 at every vertex."""

    def test_sums_to_one(self):
        rng = np.random.default_rng(0)
        area_values = _random_area_values(rng)
        groups = ["LR", "MouthLR", "TBLR", "LCR"]
        for group_a, group_b in itertools.product(groups, repeat=2):
            shape = FakeShape("browUp_lipPucker", [("browUp", "100"), ("lipPucker", "100")])
            data = _build([shape], {"browUp": group_a, "lipPucker": group_b})
            with self.subTest(groups=(group_a, group_b)):
                np.testing.assert_allclose(_shape_weight_sum(data, "browUp_lipPucker", area_values), 1.0)

    def test_three_linked_maps_sum_to_one(self):
        rng = np.random.default_rng(1)
        area_values = _random_area_values(rng)
        shape = FakeShape("a_b_c", [("a", "100"), ("b", "100"), ("c", "100")])
        data = _build([shape], {"a": "LR", "b": "MouthLR", "c": "TBLR"})
        self.assertEqual(len(data.split_shapes["a_b_c"]), 4)
        np.testing.assert_allclose(_shape_weight_sum(data, "a_b_c", area_values), 1.0)


if __name__ == "__main__":
    unittest.main()
