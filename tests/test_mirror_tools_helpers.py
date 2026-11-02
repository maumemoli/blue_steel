"""Maya-free tests for the ``mirror_tools`` MEL parsing helpers.

``mirror_tools`` imports ``maya.cmds``/``maya.mel`` and
``blue_steel.api.mayaUtils``, and ``blue_steel/__init__`` requires a live Maya
session. The helpers under test do no Maya calls, so the module is loaded from
its released path with a lightweight package/Maya stub instead.

Run with::

    python -m unittest discover -s tests -p "test_mirror_tools_helpers.py"
"""

import importlib.util
import sys
import types
import unittest
from pathlib import Path


PACKAGE_ROOT = (
    Path(__file__).resolve().parents[1]
    / "releases"
    / "maya"
    / "BlueSteel"
    / "scripts"
    / "blue_steel"
)
MODULE_PATH = PACKAGE_ROOT / "mmtools" / "mirror_tools.py"


def _install_stub_modules():
    """Register the minimum package and Maya stubs ``mirror_tools`` imports."""

    maya = types.ModuleType("maya")
    maya.cmds = types.ModuleType("maya.cmds")
    maya.mel = types.ModuleType("maya.mel")
    sys.modules.setdefault("maya", maya)
    sys.modules.setdefault("maya.cmds", maya.cmds)
    sys.modules.setdefault("maya.mel", maya.mel)

    packages = {
        "blue_steel": PACKAGE_ROOT,
        "blue_steel.api": PACKAGE_ROOT / "api",
        "blue_steel.mmtools": PACKAGE_ROOT / "mmtools",
    }
    for name, path in packages.items():
        if name in sys.modules:
            continue
        module = types.ModuleType(name)
        module.__path__ = [str(path)]
        sys.modules[name] = module

    if "blue_steel.api.mayaUtils" not in sys.modules:
        maya_utils = types.ModuleType("blue_steel.api.mayaUtils")

        def undoable(function):
            """Return ``function`` unchanged; Maya chunks are not needed here."""

            return function

        maya_utils.undoable = undoable
        sys.modules["blue_steel.api.mayaUtils"] = maya_utils


def _load_module():
    """Load ``mirror_tools`` from its released path with stubs installed."""

    _install_stub_modules()
    spec = importlib.util.spec_from_file_location(
        "blue_steel.mmtools.mirror_tools",
        MODULE_PATH,
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


mirror_tools = _load_module()


class GetIdsTests(unittest.TestCase):
    """``get_ids`` is the port of the MEL ``getID`` helper."""

    def test_drops_label_and_queried_id(self):
        self.assertEqual(
            mirror_tools.get_ids("VERTEX      8:      3    9"),
            ["3", "9"],
        )

    def test_handles_newlines_and_extra_spaces(self):
        self.assertEqual(
            mirror_tools.get_ids("FACE 12:   4   \n 7\r\n"),
            ["4", "7"],
        )

    def test_returns_empty_for_empty_output(self):
        self.assertEqual(mirror_tools.get_ids(""), [])

    def test_ignores_non_numeric_tokens(self):
        self.assertEqual(
            mirror_tools.get_ids("EDGE 0: 12 null 7"),
            ["12", "7"],
        )


class MatchStrTests(unittest.TestCase):
    """``match_str`` is the port of the MEL ``matchStr`` helper."""

    def test_membership(self):
        self.assertTrue(mirror_tools.match_str("3", ["1", "2", "3"]))
        self.assertFalse(mirror_tools.match_str("4", ["1", "2", "3"]))

    def test_ignores_numeric_prefixes(self):
        self.assertFalse(mirror_tools.match_str("1", ["10", "11"]))


class ParseEdgeTests(unittest.TestCase):
    """``parse_edge`` replaces the MEL ``tokenize`` edge parsing."""

    def test_plain_edge(self):
        self.assertEqual(
            mirror_tools.parse_edge("pPlane1.e[12]"),
            ("pPlane1", "12"),
        )

    def test_dotted_shape_name(self):
        self.assertEqual(
            mirror_tools.parse_edge("|group|pPlane1_shape.e[0]"),
            ("|group|pPlane1_shape", "0"),
        )

    def test_invalid_component_raises(self):
        with self.assertRaises(RuntimeError):
            mirror_tools.parse_edge("pPlane1.vtx[3]")


class StateTests(unittest.TestCase):
    """Axis/negative state mirrors the MEL globals."""

    def setUp(self):
        self.state = mirror_tools.STATE
        self.state.reset()

    def tearDown(self):
        self.state.reset()

    def test_default_axis(self):
        self.assertEqual(self.state.axis, "X")
        self.assertEqual(mirror_tools.axis_index(), 0)

    def test_set_axis_normalizes_case(self):
        self.assertEqual(mirror_tools.set_axis("z"), "Z")
        self.assertEqual(self.state.axis, "Z")
        self.assertEqual(mirror_tools.axis_index(), 2)

    def test_set_axis_rejects_unknown_axis(self):
        with self.assertRaises(ValueError):
            mirror_tools.set_axis("W")

    def test_axis_index_accepts_explicit_axis(self):
        self.assertEqual(mirror_tools.axis_index("Y"), 1)
        with self.assertRaises(ValueError):
            mirror_tools.axis_index("Q")

    def test_set_negative_coerces_to_bool(self):
        self.assertIs(mirror_tools.set_negative(1), True)
        self.assertTrue(self.state.negative)
        self.assertIs(mirror_tools.set_negative(0), False)
        self.assertFalse(self.state.negative)

    def test_reset_restores_defaults(self):
        self.state.rest_geometry = "pPlane1_mirrorProxy"
        self.state.seam_edge = "4"
        self.state.axis = "Y"
        self.state.negative = True
        self.state.reset()
        self.assertEqual(self.state.rest_geometry, "")
        self.assertEqual(self.state.seam_edge, "")
        self.assertEqual(self.state.axis, "X")
        self.assertFalse(self.state.negative)

    def test_has_rest_pose_requires_geometry_and_seam(self):
        self.assertFalse(mirror_tools.has_rest_pose())
        self.state.rest_geometry = "pPlane1_mirrorProxy"
        self.assertFalse(mirror_tools.has_rest_pose())

    def test_gradient_band_defaults_to_ten_percent(self):
        self.assertEqual(
            self.state.gradient_band_percent,
            mirror_tools.DEFAULT_GRADIENT_BAND_PERCENT,
        )
        self.assertEqual(mirror_tools.DEFAULT_GRADIENT_BAND_PERCENT, 10.0)

    def test_set_gradient_band_percent_clamps(self):
        self.assertEqual(mirror_tools.set_gradient_band_percent(25), 25.0)
        self.assertEqual(self.state.gradient_band_percent, 25.0)
        self.assertEqual(mirror_tools.set_gradient_band_percent(-10), 0.0)
        self.assertEqual(mirror_tools.set_gradient_band_percent(250), 100.0)
        self.assertEqual(self.state.gradient_band_percent, 100.0)

    def test_reset_restores_gradient_band(self):
        mirror_tools.set_gradient_band_percent(60)
        self.state.reset()
        self.assertEqual(
            self.state.gradient_band_percent,
            mirror_tools.DEFAULT_GRADIENT_BAND_PERCENT,
        )


class GradientWeightsTests(unittest.TestCase):
    """``gradient_weights`` replaces the old paint-mode weight map.

    The symmetry plane is the bounding-box centre; ``L<<R`` (``negative``
    false) keeps the positive side, so weights decrease as the coordinate
    grows.
    """

    def test_smoothstep_band_around_symmetry_plane(self):
        weights = mirror_tools.gradient_weights(
            [0.0, 4.0, 4.5, 5.0, 5.5, 6.0, 10.0],
            0.0,
            10.0,
        )
        self.assertEqual(weights[0], 1.0)
        self.assertEqual(weights[1], 1.0)
        self.assertAlmostEqual(weights[2], 1.0)
        self.assertAlmostEqual(weights[3], 0.5)
        self.assertAlmostEqual(weights[4], 0.0)
        self.assertEqual(weights[5], 0.0)
        self.assertEqual(weights[6], 0.0)

    def test_negative_flag_keeps_the_negative_side(self):
        self.assertEqual(
            mirror_tools.gradient_weights([0.0, 10.0], 0.0, 10.0),
            [1.0, 0.0],
        )
        self.assertEqual(
            mirror_tools.gradient_weights(
                [0.0, 10.0],
                0.0,
                10.0,
                negative=True,
            ),
            [0.0, 1.0],
        )

    def test_mirrored_coordinates_are_complementary(self):
        coordinates = [0.0, 1.25, 3.0, 5.0, 7.5, 8.75, 10.0]
        weights = mirror_tools.gradient_weights(
            coordinates,
            0.0,
            10.0,
            band_percent=40.0,
        )
        mirrored = mirror_tools.gradient_weights(
            [10.0 - coordinate for coordinate in coordinates],
            0.0,
            10.0,
            band_percent=40.0,
        )
        for weight, mirror_weight in zip(weights, mirrored):
            self.assertAlmostEqual(weight + mirror_weight, 1.0)

    def test_weights_decrease_towards_the_kept_side(self):
        coordinates = [index / 10.0 for index in range(101)]
        weights = mirror_tools.gradient_weights(
            coordinates,
            0.0,
            10.0,
            band_percent=25.0,
        )
        self.assertEqual(weights, sorted(weights, reverse=True))
        self.assertEqual(weights[0], 1.0)
        self.assertEqual(weights[-1], 0.0)

    def test_zero_band_is_a_hard_split(self):
        self.assertEqual(
            mirror_tools.gradient_weights([2.0, 5.0, 8.0], 0.0, 10.0, 0.0),
            [1.0, 0.5, 0.0],
        )

    def test_full_band_spans_the_whole_bounding_box(self):
        weights = mirror_tools.gradient_weights(
            [0.0, 2.5, 5.0, 7.5, 10.0],
            0.0,
            10.0,
            band_percent=100.0,
        )
        self.assertAlmostEqual(weights[0], 1.0)
        self.assertAlmostEqual(weights[2], 0.5)
        self.assertAlmostEqual(weights[4], 0.0)
        self.assertGreater(weights[1], 0.5)
        self.assertLess(weights[3], 0.5)

    def test_band_percent_is_clamped(self):
        full = mirror_tools.gradient_weights(
            [0.0, 5.0, 10.0], 0.0, 10.0, band_percent=100.0
        )
        clamped = mirror_tools.gradient_weights(
            [0.0, 5.0, 10.0], 0.0, 10.0, band_percent=250.0
        )
        self.assertEqual(full, clamped)
        self.assertEqual(
            mirror_tools.gradient_weights(
                [2.0], 0.0, 10.0, band_percent=-5.0
            ),
            [1.0],
        )

    def test_none_band_uses_the_default(self):
        coordinates = [2.0, 5.0, 8.0]
        self.assertEqual(
            mirror_tools.gradient_weights(
                coordinates, 0.0, 10.0, band_percent=None
            ),
            mirror_tools.gradient_weights(coordinates, 0.0, 10.0),
        )

    def test_non_unit_bounding_box(self):
        weights = mirror_tools.gradient_weights(
            [-2.0, -1.0, 0.0, 1.0, 2.0],
            -2.0,
            2.0,
            band_percent=50.0,
        )
        self.assertAlmostEqual(weights[0], 1.0)
        self.assertAlmostEqual(weights[1], 1.0)
        self.assertAlmostEqual(weights[2], 0.5)
        self.assertAlmostEqual(weights[3], 0.0)
        self.assertAlmostEqual(weights[4], 0.0)

    def test_weights_stay_in_range(self):
        weights = mirror_tools.gradient_weights(
            [-100.0, -1.0, 0.0, 1.0, 100.0],
            -1.0,
            1.0,
            band_percent=5.0,
        )
        for weight in weights:
            self.assertGreaterEqual(weight, 0.0)
            self.assertLessEqual(weight, 1.0)

    def test_degenerate_bbox_raises(self):
        with self.assertRaises(ValueError):
            mirror_tools.gradient_weights([1.0, 1.0], 1.0, 1.0)


if __name__ == "__main__":
    unittest.main()
