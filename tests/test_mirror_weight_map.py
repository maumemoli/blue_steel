"""Tests for the blendShape weight map mirroring helpers in ``mayaUtils``.

``mayaUtils`` imports ``maya.OpenMaya``/``maya.cmds`` at module level and
``blue_steel/__init__`` requires a live Maya session, so the module is loaded
from its released path with lightweight package and Maya stubs, following
``test_topological_symmetry_map.py``. The geometric, falloff and mirror math is
pure numpy and runs without Maya; ``mirror_blendshape_weight_map`` is exercised
with a stubbed ``maya.cmds``.

Run with::

    python -m unittest discover -s tests -p "test_mirror_weight_map.py"
"""

import importlib
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


def _load_maya_utils():
    """Register the minimum package and Maya stubs ``mayaUtils`` imports."""

    maya = types.ModuleType("maya")
    maya.cmds = types.ModuleType("maya.cmds")
    maya.OpenMaya = types.ModuleType("maya.OpenMaya")
    sys.modules.setdefault("maya", maya)
    sys.modules.setdefault("maya.cmds", maya.cmds)
    sys.modules.setdefault("maya.OpenMaya", maya.OpenMaya)

    packages = {
        "blue_steel": PACKAGE_ROOT,
        "blue_steel.api": PACKAGE_ROOT / "api",
    }
    for name, path in packages.items():
        if name in sys.modules:
            continue
        module = types.ModuleType(name)
        module.__path__ = [str(path)]
        sys.modules[name] = module

    return importlib.import_module("blue_steel.api.mayaUtils")


mayaUtils = _load_maya_utils()


def _plane(columns: int = 4, rows: int = 4):
    """Build an X-symmetric plane in the YZ plane.

    ``x`` runs from ``-1`` to ``1`` and ``y`` from ``0`` to ``1``, so the plane
    ``x = 0`` is a geometric symmetry plane. ``columns`` must be even for the
    plane to contain vertices on the symmetry plane.

    Parameters:
        columns (int): Number of vertex columns along X.
        rows (int): Number of vertex rows along Y.

    Returns:
        numpy.ndarray: ``(N, 3)`` object-space points, one row per vertex.
    """

    x_values = np.linspace(-1.0, 1.0, columns)
    y_values = np.linspace(0.0, 1.0, rows)
    grid_x, grid_y = np.meshgrid(x_values, y_values)
    return np.column_stack([grid_x.ravel(), grid_y.ravel(), np.zeros(grid_x.size)])


class MirrorAxisTests(unittest.TestCase):
    """Tests for ``_mirror_axis_index`` and the axis enum."""

    def test_axis_index(self):
        """Axis names and enum members resolve in any case."""
        self.assertEqual(mayaUtils._mirror_axis_index("x"), 0)
        self.assertEqual(mayaUtils._mirror_axis_index("Y"), 1)
        self.assertEqual(mayaUtils._mirror_axis_index(" z "), 2)
        self.assertEqual(mayaUtils._mirror_axis_index(), 0)
        self.assertEqual(mayaUtils._mirror_axis_index(
            mayaUtils.MirrorAxis.Z), 2)

    def test_axis_enum_values(self):
        """Axis enum members keep their string value and order."""
        self.assertEqual(mayaUtils.MIRROR_AXES, ("x", "y", "z"))
        self.assertEqual(str(mayaUtils.MirrorAxis.Y), "y")
        self.assertEqual(mayaUtils.MirrorAxis.Y, "y")

    def test_invalid_axis(self):
        """Unknown axes raise a ValueError."""
        for axis in ("w", "", None, 1):
            with self.assertRaises(ValueError):
                mayaUtils._mirror_axis_index(axis)


class MirrorActionTests(unittest.TestCase):
    """Tests for ``_coerce_action`` and the action enum."""

    def test_action_enum(self):
        """Action members are strings and default to mirror."""
        self.assertEqual(str(mayaUtils.MirrorAction.FLIP), "flip")
        self.assertEqual(mayaUtils.MirrorAction.MIRROR, "mirror")
        self.assertEqual(mayaUtils._coerce_action(),
                         mayaUtils.MirrorAction.MIRROR)
        self.assertEqual(mayaUtils._coerce_action(mayaUtils.MirrorAction.FLIP),
                         mayaUtils.MirrorAction.FLIP)
        self.assertEqual(mayaUtils._coerce_action(" FLIP "),
                         mayaUtils.MirrorAction.FLIP)

    def test_invalid_action(self):
        """Unknown actions raise a ValueError listing the accepted ones."""
        with self.assertRaises(ValueError) as raised:
            mayaUtils._coerce_action("swap")
        self.assertIn("mirror", str(raised.exception))
        self.assertIn("flip", str(raised.exception))
        for action in ("", None, 3):
            with self.assertRaises(ValueError):
                mayaUtils._coerce_action(action)


class MirrorDirectionTests(unittest.TestCase):
    """Tests for ``_resolve_mirror_direction`` and the direction enum."""

    def test_left_is_negative(self):
        """Left to right means the negative side is the source side."""
        for direction in (mayaUtils.MirrorDirection.LEFT_TO_RIGHT,
                          "left_to_right", "l_to_r", "l>>r", "L >> R",
                          "negative_to_positive", "negative", True):
            self.assertTrue(mayaUtils._resolve_mirror_direction(direction),
                            direction)

    def test_right_to_left(self):
        """Right to left means the positive side is the source side."""
        for direction in (mayaUtils.MirrorDirection.RIGHT_TO_LEFT,
                          "right_to_left", "r_to_l", "l<<r", "L<<R",
                          "positive_to_negative", "positive", False):
            self.assertFalse(mayaUtils._resolve_mirror_direction(direction),
                             direction)

    def test_direction_enum(self):
        """Direction enum members keep their string value."""
        self.assertEqual(str(mayaUtils.MirrorDirection.RIGHT_TO_LEFT),
                         "right_to_left")
        self.assertEqual(mayaUtils.MirrorDirection.LEFT_TO_RIGHT,
                         "left_to_right")

    def test_invalid_direction(self):
        """Unknown directions raise a ValueError."""
        for direction in ("up", "", None, 1.5):
            with self.assertRaises(ValueError):
                mayaUtils._resolve_mirror_direction(direction)


class MirrorMappingTests(unittest.TestCase):
    """Tests for ``_coerce_mapping`` and the mapping enum."""

    def test_mapping_enum(self):
        """Mapping members are strings and default to the geometric map."""
        self.assertEqual(mayaUtils.MIRROR_MAPPINGS,
                         ("geometric", "topological", "surface"))
        self.assertEqual(str(mayaUtils.MirrorMapping.TOPOLOGICAL),
                         "topological")
        self.assertEqual(str(mayaUtils.MirrorMapping.SURFACE), "surface")
        self.assertEqual(mayaUtils.MirrorMapping.GEOMETRIC, "geometric")
        self.assertEqual(mayaUtils._coerce_mapping(),
                         mayaUtils.MirrorMapping.GEOMETRIC)
        self.assertEqual(
            mayaUtils._coerce_mapping(mayaUtils.MirrorMapping.TOPOLOGICAL),
            mayaUtils.MirrorMapping.TOPOLOGICAL)
        self.assertEqual(mayaUtils._coerce_mapping(" TOPOLOGICAL "),
                         mayaUtils.MirrorMapping.TOPOLOGICAL)
        self.assertEqual(mayaUtils._coerce_mapping("surface"),
                         mayaUtils.MirrorMapping.SURFACE)

    def test_invalid_mapping(self):
        """Unknown mappings raise a ValueError listing the accepted ones."""
        with self.assertRaises(ValueError) as raised:
            mayaUtils._coerce_mapping("uv")
        self.assertIn("geometric", str(raised.exception))
        self.assertIn("topological", str(raised.exception))
        for mapping in ("", None, 2, False):
            with self.assertRaises(ValueError):
                mayaUtils._coerce_mapping(mapping)


class MainProgressBarTests(unittest.TestCase):
    """Tests for ``main_progress_bar`` and the cancellation plumbing."""

    def test_noop_without_maya_progress_bar(self):
        """The bar degrades to a no-op when Maya cannot provide it."""
        with mayaUtils.main_progress_bar("Mirroring", 10) as update:
            # The Maya stubs of this module have no ``mel`` module, so the
            # callback must neither raise nor report anything.
            self.assertIsNone(update(status="step", step=1))
            self.assertIsNone(update(progress=4, poll=False))

    def test_geometric_progress_is_monotonic(self):
        """The geometric pairing reports every block and ends at the total."""
        points = _plane(5, 3)
        reports = []
        mayaUtils.compute_geometric_symmetry_map(
            points, "x", progress=lambda done, total: reports.append((done, total)))

        self.assertTrue(reports)
        total = reports[0][1]
        self.assertTrue(all(report[1] == total for report in reports))
        dones = [done for done, _total in reports]
        self.assertEqual(dones, sorted(dones))
        self.assertEqual(dones[0], 0)
        self.assertEqual(dones[-1], total)


class GeometricSymmetryMapTests(unittest.TestCase):
    """Tests for ``compute_geometric_symmetry_map``."""

    def test_plane_pairs_across_the_axis(self):
        """Every vertex maps to the mirrored column of its row."""
        points = _plane(5, 3)
        mapping = mayaUtils.compute_geometric_symmetry_map(points, "x")

        self.assertEqual(mapping.shape, (points.shape[0],))
        for vertex_id, (x_value, y_value, _) in enumerate(points):
            row = int(round(y_value * 2))
            column = int(round((x_value + 1.0) / 0.5))
            self.assertEqual(mapping[vertex_id], row * 5 + (4 - column))
        self._assert_involution(mapping)

    def test_seam_vertices_map_to_themselves(self):
        """Vertices on the symmetry plane are their own mirror."""
        points = _plane(5, 3)
        mapping = mayaUtils.compute_geometric_symmetry_map(points, "x")

        seam = np.flatnonzero(np.isclose(points[:, 0], 0.0))
        self.assertGreater(seam.size, 0)
        for vertex_id in seam:
            self.assertEqual(mapping[vertex_id], vertex_id)

    def test_other_axes(self):
        """The Y and Z axes pair the same way as X."""
        points = _plane(5, 3)
        points = points[:, [1, 0, 2]]
        mapping = mayaUtils.compute_geometric_symmetry_map(points, "y")
        self._assert_involution(mapping)
        self.assertTrue(np.all(mapping >= 0))

    def test_offset_symmetry_centre(self):
        """An explicit symmetry centre overrides the bounding box centre."""
        points = np.array([[-1.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, 0.0]])
        self.assertEqual(
            mayaUtils.compute_geometric_symmetry_map(points, "x").tolist(),
            [1, 0, 2])
        self.assertEqual(
            mayaUtils.compute_geometric_symmetry_map(
                points, "x", symmetry_centre=-1.0).tolist(),
            [0, -1, -1])

    def test_asymmetric_vertices_stay_unmapped(self):
        """Vertices without a counterpart are reported as -1."""
        points = np.array([[-2.0, 0.0, 0.0], [-1.0, 0.0, 0.0],
                           [0.5, 0.0, 0.0], [1.2, 0.0, 0.0]])
        mapping = mayaUtils.compute_geometric_symmetry_map(points, "x")

        self.assertEqual(mapping[0], 3)
        self.assertEqual(mapping[3], 0)
        self.assertEqual(mapping[1], -1)
        self.assertEqual(mapping[2], -1)

    def test_tolerance(self):
        """The tolerance decides how close a counterpart has to be."""
        points = np.array([[-2.0, 0.0, 0.0], [2.0, 0.0, 0.0],
                           [-1.0, 0.0, 0.0], [1.002, 0.0, 0.0]])
        self.assertEqual(
            mayaUtils.compute_geometric_symmetry_map(points, "x").tolist(),
            [1, 0, -1, -1])
        self.assertEqual(
            mayaUtils.compute_geometric_symmetry_map(
                points, "x", tolerance=1e-2).tolist(),
            [1, 0, 3, 2])

    def test_default_tolerance(self):
        """The default tolerance is a thousandth of an object unit."""
        self.assertAlmostEqual(mayaUtils.DEFAULT_MIRROR_TOLERANCE, 0.001)
        points = np.array([[-2.0, 0.0, 0.0], [2.0, 0.0, 0.0],
                           [-1.0, 0.0, 0.0], [1.0 + 5e-4, 0.0, 0.0]])
        self.assertEqual(
            mayaUtils.compute_geometric_symmetry_map(
                points, "x", tolerance=None).tolist(),
            [1, 0, 3, 2])

    def test_single_vertex_and_extra_columns(self):
        """A lone vertex is unmapped and the W column of points is ignored."""
        self.assertEqual(
            mayaUtils.compute_geometric_symmetry_map([[1.0, 2.0, 3.0]], "x").tolist(),
            [-1])
        points = np.column_stack([_plane(3, 1), np.ones(3)])
        self.assertEqual(
            mayaUtils.compute_geometric_symmetry_map(points, "x").tolist(),
            [2, 1, 0])

    def test_invalid_input(self):
        """Malformed points, axes and tolerances raise a ValueError."""
        with self.assertRaises(ValueError):
            mayaUtils.compute_geometric_symmetry_map([1.0, 2.0, 3.0], "x")
        with self.assertRaises(ValueError):
            mayaUtils.compute_geometric_symmetry_map(_plane(3, 1), "w")
        with self.assertRaises(ValueError):
            mayaUtils.compute_geometric_symmetry_map(_plane(3, 1), "x",
                                                     tolerance=0.0)
        with self.assertRaises(ValueError):
            # A flat mesh has no extent along Z to mirror across.
            mayaUtils.compute_geometric_symmetry_map(_plane(3, 1), "z")

    def test_large_mesh_performance(self):
        """A 100k vertex plane is paired in well under a second."""
        points = _plane(500, 200)
        self.assertGreaterEqual(points.shape[0], 100000)

        import time
        start = time.perf_counter()
        mapping = mayaUtils.compute_geometric_symmetry_map(points, "x")
        elapsed = time.perf_counter() - start
        print(f"\n[perf] {points.shape[0]} vertices paired in {elapsed:.3f}s")

        self.assertTrue(np.all(mapping >= 0))
        self._assert_involution(mapping)
        self.assertLess(elapsed, 5.0)

    def _assert_involution(self, mapping) -> None:
        """Assert the map is symmetric: the opposite of the opposite is itself."""
        valid = np.arange(mapping.size)[mapping >= 0]
        self.assertTrue(np.array_equal(mapping[mapping[valid]], valid))


class MirrorFalloffTests(unittest.TestCase):
    """Tests for ``compute_mirror_falloff_weights``."""

    def test_hard_split(self):
        """A zero band splits the mesh on the symmetry plane."""
        weights = mayaUtils.compute_mirror_falloff_weights(
            [-1.0, 0.0, 1.0], -1.0, 1.0,
            mayaUtils.MirrorDirection.LEFT_TO_RIGHT, 0.0)
        self.assertEqual(weights.tolist(), [0.0, 0.5, 1.0])

        weights = mayaUtils.compute_mirror_falloff_weights(
            [-1.0, 0.0, 1.0], -1.0, 1.0, "l<<r", 0.0)
        self.assertEqual(weights.tolist(), [1.0, 0.5, 0.0])

    def test_band_is_monotonic_and_smooth(self):
        """The band ramps from 0 to 1 through a half weight at the centre."""
        coordinates = np.linspace(-1.0, 1.0, 101)
        weights = mayaUtils.compute_mirror_falloff_weights(
            coordinates, -1.0, 1.0, mayaUtils.MirrorDirection.LEFT_TO_RIGHT, 1.0)

        self.assertAlmostEqual(weights[0], 0.0)
        self.assertAlmostEqual(weights[-1], 1.0)
        self.assertAlmostEqual(weights[50], 0.5)
        self.assertTrue(np.all(np.diff(weights) >= 0.0))

    def test_band_fraction_is_clamped(self):
        """Band fractions outside 0..1 are clamped."""
        coordinates = np.linspace(-1.0, 1.0, 11)
        wide = mayaUtils.compute_mirror_falloff_weights(
            coordinates, -1.0, 1.0, "l>>r", 5.0)
        hard = mayaUtils.compute_mirror_falloff_weights(
            coordinates, -1.0, 1.0, "l>>r", -0.5)
        self.assertTrue(np.allclose(wide,
                                    mayaUtils.compute_mirror_falloff_weights(
                                        coordinates, -1.0, 1.0, "l>>r", 1.0)))
        self.assertTrue(np.allclose(hard,
                                    mayaUtils.compute_mirror_falloff_weights(
                                        coordinates, -1.0, 1.0, "l>>r", 0.0)))

    def test_default_band(self):
        """The default falloff is a fifth of the bounding box."""
        weights = mayaUtils.compute_mirror_falloff_weights(
            [-1.0, 0.0, 1.0], -1.0, 1.0)
        self.assertTrue(np.all((weights >= 0.0) & (weights <= 1.0)))
        self.assertAlmostEqual(
            mayaUtils.DEFAULT_MIRROR_BLEND_FALLOFF, 0.2)
        self.assertTrue(np.allclose(
            weights,
            mayaUtils.compute_mirror_falloff_weights(
                [-1.0, 0.0, 1.0], -1.0, 1.0, "l>>r", 0.2)))

    def test_invalid_input(self):
        """Flat axes and unknown directions raise a ValueError."""
        with self.assertRaises(ValueError):
            mayaUtils.compute_mirror_falloff_weights([1.0], 1.0, 1.0)
        with self.assertRaises(ValueError):
            mayaUtils.compute_mirror_falloff_weights([1.0], 0.0, 2.0, "up")


class SymmetrizedCoordinateTests(unittest.TestCase):
    """Tests for ``compute_symmetrized_mirror_coordinates``."""

    def test_symmetric_pairs_are_unchanged(self):
        """An already symmetric pairing keeps its coordinates."""
        coordinates = np.array([-1.0, -0.5, 0.0, 0.5, 1.0])
        symmetrized = mayaUtils.compute_symmetrized_mirror_coordinates(
            coordinates, [4, 3, 2, 1, 0])
        np.testing.assert_allclose(symmetrized, coordinates)

    def test_asymmetric_pair_shares_its_distance(self):
        """Both members get the mean distance on their own side."""
        symmetrized = mayaUtils.compute_symmetrized_mirror_coordinates(
            [-0.9, 1.1], [1, 0], 0.0)
        np.testing.assert_allclose(symmetrized, [-1.0, 1.0])

        # The pair stays mirrored around the plane of the explicit centre.
        symmetrized = mayaUtils.compute_symmetrized_mirror_coordinates(
            [-0.9, 1.1], [1, 0], 0.5)
        np.testing.assert_allclose(symmetrized, [-0.5, 1.5])

    def test_default_centre_is_the_coordinate_centre(self):
        """Without a centre the bounding box centre of the axis is used."""
        coordinates = np.array([-1.0, -0.4, 0.5, 1.2])
        # Bounding box centre 0.1: the pair is averaged around it, the
        # unpaired vertices keep their coordinates.
        symmetrized = mayaUtils.compute_symmetrized_mirror_coordinates(
            coordinates, [2, -1, 0, -1])
        np.testing.assert_allclose(symmetrized, [-0.65, -0.4, 0.85, 1.2])

    def test_seam_vertices_stay_on_the_plane(self):
        """A self-paired vertex sits on the symmetry plane."""
        symmetrized = mayaUtils.compute_symmetrized_mirror_coordinates(
            [-1.0, 0.0, 1.0], [2, 1, 0])
        np.testing.assert_allclose(symmetrized, [-1.0, 0.0, 1.0])

    def test_unpaired_vertices_are_filtered_out(self):
        """``-1`` and ``None`` entries keep their coordinate."""
        symmetrized = mayaUtils.compute_symmetrized_mirror_coordinates(
            [-0.9, 1.1, 0.4], [1, None, -1], 0.0)
        np.testing.assert_allclose(symmetrized, [-1.0, 1.1, 0.4])

    def test_invalid_input(self):
        """Mismatched lengths and out of range ids raise a ValueError."""
        with self.assertRaises(ValueError):
            mayaUtils.compute_symmetrized_mirror_coordinates([0.0, 1.0], [0])
        with self.assertRaises(ValueError):
            mayaUtils.compute_symmetrized_mirror_coordinates([0.0, 1.0], [2, 0])


class BlendMirroredValuesTests(unittest.TestCase):
    """Tests for ``blend_mirrored_weight_map_values``."""

    def test_mirror_blends_by_falloff(self):
        """A zero falloff keeps the value, a full falloff takes the mirror."""
        result = mayaUtils.blend_mirrored_weight_map_values(
            [0.2, 0.8], [0.9, 0.1], [0.0, 1.0])
        np.testing.assert_allclose(result, [0.2, 0.1])

        half = mayaUtils.blend_mirrored_weight_map_values(
            [0.2, 0.8], [0.9, 0.1], [0.5, 0.5])
        np.testing.assert_allclose(half, [0.55, 0.45])

    def test_missing_falloff_takes_the_mirror(self):
        """Without a falloff the sampled value fully replaces the old one."""
        result = mayaUtils.blend_mirrored_weight_map_values(
            [0.25, 0.75], [0.75, 0.25])
        np.testing.assert_allclose(result, [0.75, 0.25])

    def test_flip_swaps_both_sides(self):
        """Flip swaps the values and half mixes them on the band."""
        swapped = mayaUtils.blend_mirrored_weight_map_values(
            [0.2, 0.8], [0.8, 0.2], [1.0, 1.0], "flip")
        np.testing.assert_allclose(swapped, [0.8, 0.2])

        mixed = mayaUtils.blend_mirrored_weight_map_values(
            [0.2, 0.8], [0.8, 0.2], [0.5, 0.5], "flip")
        np.testing.assert_allclose(mixed, [0.5, 0.5])

    def test_does_not_mutate_its_arguments(self):
        """The input lists are left untouched."""
        values = [0.2, 0.8]
        mirrored = [0.8, 0.2]
        mayaUtils.blend_mirrored_weight_map_values(values, mirrored, [1.0, 1.0])
        self.assertEqual(values, [0.2, 0.8])
        self.assertEqual(mirrored, [0.8, 0.2])

    def test_invalid_input(self):
        """Mismatched lengths and unknown actions raise a ValueError."""
        with self.assertRaises(ValueError):
            mayaUtils.blend_mirrored_weight_map_values([0.0, 1.0], [0.0])
        with self.assertRaises(ValueError):
            mayaUtils.blend_mirrored_weight_map_values(
                [0.0, 1.0], [1.0, 0.0], [0.0])
        with self.assertRaises(ValueError):
            mayaUtils.blend_mirrored_weight_map_values(
                [0.0, 1.0], [1.0, 0.0], [1.0, 1.0], "swap")


class MirrorWeightMapTests(unittest.TestCase):
    """Tests for ``mirror_weight_map_values``."""

    def test_mirror_copies_one_side(self):
        """``mirror`` leaves the source side and copies onto the other one."""
        values = [0.2, 0.8]
        result = mayaUtils.mirror_weight_map_values(
            values, [1, 0], [0.0, 1.0], mayaUtils.MirrorAction.MIRROR)
        np.testing.assert_allclose(result, [0.2, 0.2])
        self.assertEqual(values, [0.2, 0.8])

    def test_flip_swaps_both_sides(self):
        """``flip`` swaps the two sides of the weight map."""
        result = mayaUtils.mirror_weight_map_values(
            [0.2, 0.8], [1, 0], [0.0, 1.0], mayaUtils.MirrorAction.FLIP)
        np.testing.assert_allclose(result, [0.8, 0.2])

        # String spellings are still accepted for MEL and UI callers.
        np.testing.assert_allclose(
            mayaUtils.mirror_weight_map_values(
                [0.2, 0.8], [1, 0], [0.0, 1.0], "flip"),
            [0.8, 0.2])

    def test_band_blends(self):
        """The falloff blends between the current and the mirrored value."""
        result = mayaUtils.mirror_weight_map_values(
            [0.2, 0.8], [1, 0], [0.5, 0.5], "mirror")
        self.assertEqual(result.tolist(), [0.5, 0.5])

        flipped = mayaUtils.mirror_weight_map_values(
            [0.2, 0.8], [1, 0], [0.5, 0.5], "flip")
        self.assertEqual(flipped.tolist(), [0.5, 0.5])

    def test_unmapped_vertices_keep_their_value(self):
        """Vertices mapped to -1 are left untouched by both actions."""
        for action in mayaUtils.MIRROR_ACTIONS:
            result = mayaUtils.mirror_weight_map_values(
                [0.2, 0.9], [-1, 1], [1.0, 1.0], action)
            self.assertEqual(result.tolist(), [0.2, 0.9], action)

    def test_missing_falloff_copies_everything(self):
        """Without a falloff the mirrored value fully replaces the old one."""
        result = mayaUtils.mirror_weight_map_values([0.25, 0.75], [1, 0])
        self.assertEqual(result.tolist(), [0.75, 0.25])

    def test_invalid_input(self):
        """Unknown actions, mismatched lengths and bad ids raise ValueError."""
        with self.assertRaises(ValueError):
            mayaUtils.mirror_weight_map_values([0.0], [0], action="swap")
        with self.assertRaises(ValueError):
            mayaUtils.mirror_weight_map_values([0.0, 1.0], [0])
        with self.assertRaises(ValueError):
            mayaUtils.mirror_weight_map_values([0.0], [0], [0.0, 1.0])
        with self.assertRaises(ValueError):
            mayaUtils.mirror_weight_map_values([0.0], [3])


class SculptingContextTests(unittest.TestCase):
    """Tests for ``non_sculpting_context``."""

    def setUp(self):
        from unittest import mock

        self.cmds = _FakeCmds()
        self._patcher = mock.patch.object(mayaUtils, "cmds", self.cmds)
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()

    def test_sculpt_context_is_parked_and_restored(self):
        """A sculpt context is left for the block and reinstated after it."""
        self.cmds.current_context = "sculptMeshCacheContext"
        with mayaUtils.non_sculpting_context() as context:
            self.assertEqual(context, "sculptMeshCacheContext")
            self.assertEqual(self.cmds.current_context, "selectSuperContext")

        self.assertEqual(self.cmds.current_context, "sculptMeshCacheContext")
        self.assertEqual(self.cmds.tool_history,
                         ["selectSuperContext", "sculptMeshCacheContext"])

    def test_blendshape_paint_context_is_parked(self):
        """The blendShape paint context is handled like the sculpt one."""
        self.cmds.current_context = "artAttrBlendShapeContext"
        with mayaUtils.non_sculpting_context():
            self.assertEqual(self.cmds.current_context, "selectSuperContext")
        self.assertEqual(self.cmds.current_context, "artAttrBlendShapeContext")

    def test_other_contexts_are_untouched(self):
        """A non sculpt context is passed through without switching tools."""
        self.cmds.current_context = "moveSuperContext"
        with mayaUtils.non_sculpting_context() as context:
            self.assertEqual(context, "moveSuperContext")
        self.assertEqual(self.cmds.tool_history, [])

    def test_context_is_restored_after_a_failure(self):
        """The previous context comes back even when the block raises."""
        self.cmds.current_context = "sculptMeshCacheContext"
        with self.assertRaises(RuntimeError):
            with mayaUtils.non_sculpting_context():
                raise RuntimeError("boom")
        self.assertEqual(self.cmds.current_context, "sculptMeshCacheContext")

    def test_unknown_context_is_safe(self):
        """A missing context query does not break the context manager."""
        self.cmds.currentCtx = None
        with mayaUtils.non_sculpting_context() as context:
            self.assertIsNone(context)
        self.assertEqual(self.cmds.tool_history, [])


class _FakePlug:
    """Minimal stand-in for ``OpenMaya.MPlug`` with no elements."""

    def numElements(self) -> int:
        return 0


class _FakeCmds:
    """Minimal stand-in for ``maya.cmds`` covering the weight map API."""

    def __init__(self):
        self.warnings = []
        self.node_types = {}
        self.shapes = {}
        self.base_meshes = {}
        self.vertex_counts = {}
        self.groups = {}
        self.weight_aliases = {}
        self.weight_maps = {}
        self.connections = {}
        self.sculpt_targets = {}
        self.set_calls = []
        self.current_context = "selectSuperContext"
        self.tool_history = []

    def warning(self, message):
        self.warnings.append(message)

    def currentCtx(self):
        return self.current_context

    def setToolTo(self, tool_name):
        self.tool_history.append(tool_name)
        self.current_context = tool_name

    def undoInfo(self, **kwargs):
        pass

    def objExists(self, name):
        return True

    def nodeType(self, name):
        return self.node_types.get(name, "mesh")

    def listRelatives(self, name, **kwargs):
        return list(self.shapes.get(name, []))

    def ls(self, items=None, **kwargs):
        if isinstance(items, str):
            items = [items]
        return list(items or [])

    def blendShape(self, name, query=False, geometry=False, **kwargs):
        return list(self.base_meshes.get(name, []))

    def polyEvaluate(self, mesh, vertex=False):
        return self.vertex_counts.get(mesh, 0)

    def listAttr(self, attribute, multi=False):
        node = attribute.rsplit(".", 1)[0]
        return list(self.weight_aliases.get(node, []))

    def getAttr(self, attribute, multiIndices=False):
        node, path = attribute.split(".", 1)
        if multiIndices:
            if path != "inputTarget[0].inputTargetGroup":
                raise AssertionError(f"Unexpected multi getAttr {attribute}")
            return list(self.groups.get(node, []))
        if "targetWeights[" not in path:
            raise AssertionError(f"Unexpected getAttr {attribute}")
        target_id = int(path.split("inputTargetGroup[")[1].split("]")[0])
        values = self.weight_maps.get((node, target_id))
        if values is None:
            return None
        start, end = path.rsplit("[", 1)[1].rstrip("]").split(":")
        return list(values[int(start):int(end) + 1])

    def setAttr(self, attribute, *values, **kwargs):
        node, path = attribute.split(".", 1)
        target_id = int(path.split("inputTargetGroup[")[1].split("]")[0])
        self.weight_maps[(node, target_id)] = list(values)
        self.set_calls.append((attribute, list(values), kwargs.get("size")))

    def listConnections(self, attribute, **kwargs):
        return list(self.connections.get(attribute, []))

    def sculptTarget(self, name, edit=False, t=0):
        self.sculpt_targets[name] = t


class MirrorBlendshapeWeightMapTests(unittest.TestCase):
    """Tests for ``mirror_blendshape_weight_map`` with stubbed Maya."""

    def setUp(self):
        from unittest import mock

        self.points = _plane(5, 3)
        self.num_vertices = self.points.shape[0]
        self.blendshape = "head_blendShapes"
        self.mesh = "head"

        self.cmds = _FakeCmds()
        self.cmds.node_types[self.blendshape] = "blendShape"
        self.cmds.node_types[self.mesh] = "mesh"
        self.cmds.base_meshes[self.blendshape] = [self.mesh]
        self.cmds.vertex_counts[self.mesh] = self.num_vertices
        self.cmds.groups[self.blendshape] = [0, 1]
        self.cmds.weight_aliases[self.blendshape] = ["Smile", "Frown"]

        # Left side 0.0, right side 1.0, seam vertices 0.5 per target.
        columns = np.round((self.points[:, 0] + 1.0) * 2.0).astype(int)
        for target_id in (0, 1):
            self.cmds.weight_maps[(self.blendshape, target_id)] = (
                columns * 0.25).tolist()

        self._patchers = [
            mock.patch.object(mayaUtils, "cmds", self.cmds),
            mock.patch.object(mayaUtils, "get_mesh_raw_points",
                              lambda name: self.points.copy()),
            mock.patch.object(mayaUtils, "get_plug",
                              lambda name, attribute: _FakePlug()),
        ]
        for patcher in self._patchers:
            patcher.start()

    def tearDown(self):
        for patcher in reversed(self._patchers):
            patcher.stop()

    def _expected(self, values, weight_id=0, **kwargs):
        mapping = mayaUtils.compute_geometric_symmetry_map(self.points, "x")
        coordinates = self.points[:, 0]
        falloff = mayaUtils.compute_mirror_falloff_weights(
            coordinates,
            float(coordinates.min()),
            float(coordinates.max()),
            kwargs.pop("mirror_direction", "left_to_right"),
            kwargs.pop("mirror_blend_falloff", None))
        return mayaUtils.mirror_weight_map_values(
            values, mapping, falloff, kwargs.pop("action", "mirror"))

    def test_all_weight_maps_by_default(self):
        """Without a weight id every inputTargetGroup map is mirrored."""
        before = {target_id: list(self.cmds.weight_maps[(self.blendshape, target_id)])
                  for target_id in (0, 1)}

        result = mayaUtils.mirror_blendshape_weight_map(self.mesh, self.blendshape)

        self.assertEqual(sorted(result), [0, 1])
        self.assertEqual(len(self.cmds.set_calls), 2)
        for target_id in (0, 1):
            expected = self._expected(before[target_id])
            self.assertTrue(np.allclose(result[target_id], expected))
            self.assertTrue(np.allclose(
                self.cmds.weight_maps[(self.blendshape, target_id)], expected))
        self.assertEqual(self.cmds.warnings, [])

    def test_single_weight_id(self):
        """A weight id limits the operation to that target."""
        result = mayaUtils.mirror_blendshape_weight_map(
            self.mesh, self.blendshape, weight_id=1,
            action=mayaUtils.MirrorAction.FLIP)

        self.assertEqual(list(result), [1])
        self.assertEqual(len(self.cmds.set_calls), 1)
        self.assertIn("inputTargetGroup[1]", self.cmds.set_calls[0][0])
        self.assertEqual(self.cmds.set_calls[0][2], self.num_vertices)

    def test_weight_name_is_resolved(self):
        """A weight alias is resolved to its target id."""
        result = mayaUtils.mirror_blendshape_weight_map(
            self.mesh, self.blendshape, weight_id="Smile")
        self.assertEqual(list(result), [0])

    def test_mirror_direction(self):
        """Right to left copies the positive side onto the negative one."""
        before = list(self.cmds.weight_maps[(self.blendshape, 0)])
        result = mayaUtils.mirror_blendshape_weight_map(
            self.mesh, self.blendshape, weight_id=0,
            mirror_direction="right_to_left", mirror_blend_falloff=0.0)

        positive = self.points[:, 0] > 0.0
        mapping = mayaUtils.compute_geometric_symmetry_map(self.points, "x")
        mirrored = np.asarray(before)[mapping]
        # The source side keeps its values, the destination side is replaced.
        self.assertTrue(np.allclose(result[0][positive],
                                    np.asarray(before)[positive]))
        self.assertTrue(np.allclose(result[0][~positive], mirrored[~positive]))
        self.assertTrue(np.allclose(
            result[0],
            self._expected(before,
                           mirror_direction="right_to_left",
                           mirror_blend_falloff=0.0)))

    def test_unmapped_vertices_warn(self):
        """An asymmetric mesh warns about the vertices it could not pair."""
        from unittest import mock

        points = self.points.copy()
        points[1, 0] = 0.6
        with mock.patch.object(mayaUtils, "get_mesh_raw_points",
                               lambda name: points.copy()):
            mayaUtils.mirror_blendshape_weight_map(
                self.mesh, self.blendshape, weight_id=0)

        self.assertEqual(len(self.cmds.warnings), 1)
        self.assertIn("kept their weight map", self.cmds.warnings[0])

    def _topological_mapping(self):
        """Pair the columns of the test plane, leaving the last row unmapped."""
        mapping = []
        for start in range(0, self.num_vertices, 5):
            mapping.extend([start + 4, start + 3, start + 2, start + 1, start])
        mapping[-5:] = [None] * 5
        return mapping

    def _topological_expected(self, values, points, topological):
        """Mirror ``values`` with the symmetrized falloff of a pairing."""
        mapping = np.array([-1 if entry is None else entry
                            for entry in topological], dtype=np.int64)
        coordinates = points[:, 0]
        symmetrized = mayaUtils.compute_symmetrized_mirror_coordinates(
            coordinates, mapping)
        falloff = mayaUtils.compute_mirror_falloff_weights(
            symmetrized,
            float(coordinates.min()),
            float(coordinates.max()))
        return mapping, mayaUtils.mirror_weight_map_values(
            values, mapping, falloff)

    def test_topological_mapping(self):
        """The topological option pairs through the symmetry map of an edge."""
        from unittest import mock

        topological = self._topological_mapping()
        calls = []

        def fake_topological_map(mesh_name, edge=None, progress=None,
                                 show_progress=True):
            calls.append((mesh_name, edge))
            return list(topological)

        before = list(self.cmds.weight_maps[(self.blendshape, 0)])
        with mock.patch.object(mayaUtils, "get_mesh_topological_symmetry_map",
                               fake_topological_map):
            result = mayaUtils.mirror_blendshape_weight_map(
                self.mesh, self.blendshape, weight_id=0,
                mapping="topological", symmetry_edge=(2, 3))

        self.assertEqual(calls, [(self.mesh, (2, 3))])
        _, expected = self._topological_expected(before, self.points,
                                                 topological)
        self.assertTrue(np.allclose(result[0], expected))
        self.assertTrue(np.allclose(
            self.cmds.weight_maps[(self.blendshape, 0)], expected))
        # Unpaired vertices keep their weight map values.
        self.assertTrue(np.allclose(result[0][-5:], np.asarray(before)[-5:]))
        # The topological helper reports its own unmapped vertices.
        self.assertEqual(self.cmds.warnings, [])

    def test_topological_falloff_is_symmetrized(self):
        """An asymmetric mesh is mirrored on the symmetrized positions."""
        from unittest import mock

        points = self.points.copy()
        # Break the symmetry of one pair without moving the bounding box.
        points[1, 0] = -0.2
        topological = self._topological_mapping()
        before = list(self.cmds.weight_maps[(self.blendshape, 0)])
        falloff_kwargs = {"mirror_blend_falloff": 1.0}

        with mock.patch.object(mayaUtils, "get_mesh_raw_points",
                               lambda name: points.copy()), \
                mock.patch.object(mayaUtils,
                                  "get_mesh_topological_symmetry_map",
                                  lambda name, edge=None, progress=None,
                                  show_progress=True: list(topological)):
            result = mayaUtils.mirror_blendshape_weight_map(
                self.mesh, self.blendshape, weight_id=0,
                mapping=mayaUtils.MirrorMapping.TOPOLOGICAL,
                **falloff_kwargs)

        mapping = np.array([-1 if entry is None else entry
                            for entry in topological], dtype=np.int64)
        coordinates = points[:, 0]
        minimum, maximum = float(coordinates.min()), float(coordinates.max())
        symmetrized = mayaUtils.compute_symmetrized_mirror_coordinates(
            coordinates, mapping)
        expected = mayaUtils.mirror_weight_map_values(
            before, mapping,
            mayaUtils.compute_mirror_falloff_weights(
                symmetrized, minimum, maximum, "l>>r", 1.0))
        self.assertTrue(np.allclose(result[0], expected))

        # The raw coordinates would split the band asymmetrically instead.
        raw_expected = mayaUtils.mirror_weight_map_values(
            before, mapping,
            mayaUtils.compute_mirror_falloff_weights(
                coordinates, minimum, maximum, "l>>r", 1.0))
        self.assertFalse(np.allclose(expected, raw_expected))

    def test_symmetry_edge_requires_topological_mapping(self):
        """A seed edge without the topological mapping is rejected."""
        with self.assertRaises(ValueError) as raised:
            mayaUtils.mirror_blendshape_weight_map(
                self.mesh, self.blendshape, weight_id=0,
                symmetry_edge="head.e[12]")
        self.assertIn("topological", str(raised.exception))
        self.assertEqual(self.cmds.set_calls, [])

    def test_topological_mapping_without_pairs_raises(self):
        """A mapping that pairs no vertex is rejected."""
        from unittest import mock

        with mock.patch.object(mayaUtils, "get_mesh_topological_symmetry_map",
                               lambda name, edge=None, progress=None,
                               show_progress=True:
                               [None] * self.num_vertices):
            with self.assertRaises(ValueError) as raised:
                mayaUtils.mirror_blendshape_weight_map(
                    self.mesh, self.blendshape, weight_id=0,
                    mapping="topological")
        self.assertIn("paired no vertex", str(raised.exception))
        self.assertEqual(self.cmds.set_calls, [])

    def test_cancel_leaves_the_weight_maps_untouched(self):
        """Cancelling the progress bar writes nothing and returns {}."""
        from unittest import mock
        from contextlib import contextmanager

        @contextmanager
        def fake_progress_bar(*_args, **_kwargs):
            def update(**_update_kwargs):
                raise mayaUtils.MirrorCancelled("cancelled")
            yield update

        with mock.patch.object(mayaUtils, "main_progress_bar",
                               fake_progress_bar):
            result = mayaUtils.mirror_blendshape_weight_map(
                self.mesh, self.blendshape, weight_id=0)

        self.assertEqual(result, {})
        self.assertEqual(self.cmds.set_calls, [])
        self.assertTrue(any("cancelled" in warning
                            for warning in self.cmds.warnings))

    def test_surface_mapping_needs_a_sampler(self):
        """The sampled mapping explains that it needs the surface sampler."""
        with self.assertRaises(ValueError) as raised:
            mayaUtils.mirror_blendshape_weight_map(
                self.mesh, self.blendshape, weight_id=0, mapping="surface")
        self.assertIn("sampler", str(raised.exception))
        self.assertEqual(self.cmds.set_calls, [])

    def test_surface_mapping_blends_the_sampled_values(self):
        """A sampler's values are blended like a mirrored weight map."""
        from unittest import mock

        sampled = np.full(self.num_vertices, 0.25, dtype=np.float64)
        calls = {}

        def fake_sampler(**kwargs):
            calls.update(kwargs)
            return {0: sampled}

        before = list(self.cmds.weight_maps[(self.blendshape, 0)])
        with mock.patch.object(mayaUtils, "compute_geometric_symmetry_map",
                               side_effect=AssertionError("no pairing")):
            result = mayaUtils.mirror_blendshape_weight_map(
                self.mesh, self.blendshape, weight_id=0,
                mapping="surface", sampler=fake_sampler)

        self.assertEqual(calls["mesh_name"], self.mesh)
        self.assertEqual(calls["blendshape_name"], self.blendshape)
        self.assertEqual(calls["weight_ids"], [0])
        self.assertEqual(calls["mirror_axis"], "x")
        self.assertTrue(callable(calls["progress"]))

        coordinates = self.points[:, 0]
        falloff = mayaUtils.compute_mirror_falloff_weights(
            coordinates, float(coordinates.min()), float(coordinates.max()))
        expected = mayaUtils.blend_mirrored_weight_map_values(
            before, sampled, falloff)
        self.assertTrue(np.allclose(result[0], expected))
        self.assertTrue(np.allclose(
            self.cmds.weight_maps[(self.blendshape, 0)], expected))

    def test_surface_mapping_rejects_the_symmetry_edge(self):
        """The sampled mapping does not use a symmetry edge."""
        with self.assertRaises(ValueError) as raised:
            mayaUtils.mirror_blendshape_weight_map(
                self.mesh, self.blendshape, weight_id=0, mapping="surface",
                symmetry_edge="head.e[12]",
                sampler=lambda **_kwargs: {0: np.zeros(self.num_vertices)})
        self.assertIn("symmetry_edge", str(raised.exception))
        self.assertEqual(self.cmds.set_calls, [])

    def test_sculpt_context_is_restored_around_the_mirror(self):
        """A sculpt context is parked for the mirror and restored after it."""
        self.cmds.current_context = "artAttrBlendShapeContext"

        mayaUtils.mirror_blendshape_weight_map(
            self.mesh, self.blendshape, weight_id=0)

        self.assertEqual(self.cmds.current_context, "artAttrBlendShapeContext")
        self.assertEqual(self.cmds.tool_history,
                         ["selectSuperContext", "artAttrBlendShapeContext"])
        self.assertEqual(len(self.cmds.set_calls), 1)

    def test_sculpt_context_is_restored_after_a_cancel(self):
        """Cancelling the mirror still reinstates the paint context."""
        from unittest import mock
        from contextlib import contextmanager

        @contextmanager
        def fake_progress_bar(*_args, **_kwargs):
            def update(**_update_kwargs):
                raise mayaUtils.MirrorCancelled("cancelled")
            yield update

        self.cmds.current_context = "sculptMeshCacheContext"
        with mock.patch.object(mayaUtils, "main_progress_bar",
                               fake_progress_bar):
            result = mayaUtils.mirror_blendshape_weight_map(
                self.mesh, self.blendshape, weight_id=0)

        self.assertEqual(result, {})
        self.assertEqual(self.cmds.current_context, "sculptMeshCacheContext")
        self.assertEqual(self.cmds.set_calls, [])

    def test_connected_weight_map_raises(self):
        """Connected weight maps cannot be overwritten."""
        attribute = (f"{self.blendshape}.inputTarget[0]"
                     f".inputTargetGroup[0].targetWeights[0]")
        self.cmds.connections[attribute] = ["sourceNode.targetWeights"]

        with self.assertRaises(ValueError):
            mayaUtils.mirror_blendshape_weight_map(
                self.mesh, self.blendshape, weight_id=0)
        self.assertEqual(self.cmds.set_calls, [])

    def test_invalid_arguments(self):
        """Unknown actions, weight ids and vertex counts raise a ValueError."""
        with self.assertRaises(ValueError):
            mayaUtils.mirror_blendshape_weight_map(
                self.mesh, self.blendshape, action="swap")
        with self.assertRaises(ValueError):
            mayaUtils.mirror_blendshape_weight_map(
                self.mesh, self.blendshape, weight_id=7)
        with self.assertRaises(ValueError):
            mayaUtils.mirror_blendshape_weight_map(
                self.mesh, self.blendshape, weight_id="Unknown")
        with self.assertRaises(ValueError):
            mayaUtils.mirror_blendshape_weight_map(
                self.mesh, self.blendshape, mirror_axis="w")
        with self.assertRaises(ValueError):
            mayaUtils.mirror_blendshape_weight_map(
                self.mesh, self.blendshape, mapping="uv")

        self.cmds.vertex_counts[self.mesh] = self.num_vertices + 1
        with self.assertRaises(ValueError):
            mayaUtils.mirror_blendshape_weight_map(self.mesh, self.blendshape)

    def test_sculpt_target_is_restored(self):
        """A target in sculpt mode is released and restored around the write."""
        from unittest import mock

        with mock.patch.object(mayaUtils, "_get_sculpt_target_ids",
                               lambda name: [0, -1]):
            mayaUtils.mirror_blendshape_weight_map(
                self.mesh, self.blendshape, weight_id=0)
        self.assertEqual(self.cmds.sculpt_targets.get(self.blendshape), 0)


if __name__ == "__main__":
    unittest.main()
