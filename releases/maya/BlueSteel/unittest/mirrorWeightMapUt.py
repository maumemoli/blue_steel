"""Maya-side checks and benchmark for the blendShape weight map mirror.

Unlike the Maya-free ``tests/test_mirror_weight_map.py`` helpers, these cases
build a real mesh and blendShape inside Maya, because the surface sampling path
(`MirrorMapping.SURFACE`) goes through temporary skinClusters and
``copySkinWeights``.

Run inside Maya with the Blue Steel scripts on ``sys.path``::

    python -m unittest blue_steel.unittest.mirrorWeightMapUt

or execute the module directly to only print the benchmark timings::

    mirrorWeightMapUt.benchmark()

The benchmark is skipped by the test run when ``BLUE_STEEL_SKIP_BENCHMARK`` is
set in the environment, so slow machines can still run the agreement tests.
"""

import os
import sys
import time
import unittest

_PACKAGE_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "scripts")
)
if _PACKAGE_ROOT not in sys.path:
    sys.path.insert(0, _PACKAGE_ROOT)

import numpy as np
from maya import cmds

from blue_steel.api import mayaUtils
from blue_steel.api.blendshape import Blendshape
from blue_steel.mmtools.blendshape_transfer_tools import (
    sample_mirrored_weight_maps,
)

PLANE_NAME = "mirrorUtPlane"
TARGET_NAME = "mirrorUtTarget"
BLENDSHAPE_NAME = "mirrorUtBlendShape"


def _create_plane(subdivisions: int = 24) -> tuple:
    """Build an X-symmetric quad plane plus a two target blendShape.

    Parameters:
        subdivisions (int): Number of quads per side of the plane.

    Returns:
        tuple: ``(plane, blendshape, vertex_count, original_maps)`` with the
        two weight maps the tests mirror, in their untouched state.
    """

    plane = cmds.polyPlane(name=PLANE_NAME,
                           width=2.0,
                           height=2.0,
                           subdivisionsX=subdivisions,
                           subdivisionsY=subdivisions)[0]
    # Keep the plane centred so the symmetry plane is x = 0.
    cmds.setAttr(f"{plane}.translateX", 0)
    target = cmds.duplicate(plane, name=TARGET_NAME)[0]
    cmds.delete(target, constructionHistory=True)

    blendshape = cmds.blendShape(target, plane, name=BLENDSHAPE_NAME)[0]
    cmds.delete(target)
    cmds.setAttr(f"{blendshape}.weight[0]", 0.0)

    vertex_count = cmds.polyEvaluate(plane, vertex=True)
    points = mayaUtils.get_mesh_raw_points(plane)[:, :3].astype(np.float64)
    x_values = points[:, 0]

    blendshape_data = Blendshape(blendshape)
    # A left/right shaped map and a gradient map, both asymmetric enough that a
    # wrong mirror is visible.
    first_map = np.clip((x_values + 1.0) / 2.0, 0.0, 1.0)
    second_map = np.where(x_values >= 0.0, 1.0, 0.2)
    blendshape_data.set_weight_map_values(0, first_map.tolist())
    blendshape_data.set_weight_map_values(1, second_map.tolist())

    return plane, blendshape, vertex_count, [first_map, second_map]


def _delete_if_exists(*node_names: str) -> None:
    """Delete the given nodes when they still exist.

    Parameters:
        *node_names (str): Node names to remove.

    Returns:
        None
    """

    for node_name in node_names:
        if node_name and cmds.objExists(node_name):
            try:
                cmds.delete(node_name)
            except RuntimeError:
                pass


class MirrorWeightMapUt(unittest.TestCase):
    """Agreement checks between the sampled and the exact pairing paths."""

    def setUp(self):
        self._cleanup_nodes()
        (self.plane,
         self.blendshape,
         self.vertex_count,
         self.original_maps) = _create_plane(24)
        self.points = mayaUtils.get_mesh_raw_points(self.plane)[:, :3]
        self.mapping = mayaUtils.compute_geometric_symmetry_map(self.points, "x")

    def tearDown(self):
        self._cleanup_nodes()

    def _cleanup_nodes(self) -> None:
        """Remove the test mesh, target and blendShape.

        Returns:
            None
        """

        _delete_if_exists(BLENDSHAPE_NAME, TARGET_NAME, PLANE_NAME)

    def _reset_maps(self) -> None:
        """Restore the untouched test weight maps.

        Returns:
            None
        """

        blendshape = Blendshape(self.blendshape)
        for weight_id, weight_map in enumerate(self.original_maps):
            blendshape.set_weight_map_values(weight_id, weight_map.tolist())

    def test_sampled_values_match_the_mirrored_vertices(self):
        """On a symmetric mesh the sample equals the mirrored vertex value."""
        sampled = sample_mirrored_weight_maps(
            self.plane, self.blendshape, weight_ids=[0, 1], show_progress=False
        )

        self.assertEqual(sorted(sampled), [0, 1])
        for weight_id, expected in enumerate(self.original_maps):
            values = np.asarray(sampled[weight_id], dtype=np.float64)
            self.assertEqual(values.shape, (self.vertex_count,))
            np.testing.assert_allclose(values,
                                       expected[self.mapping],
                                       atol=0.05,
                                       err_msg=f"weight map {weight_id}")

    def test_surface_and_geometric_mirror_agree(self):
        """Both mappings produce the same mirrored weight map."""
        geometric = mayaUtils.mirror_blendshape_weight_map(
            self.plane,
            self.blendshape,
            weight_id=0,
            mapping=mayaUtils.MirrorMapping.GEOMETRIC,
            show_progress=False,
        )
        self._reset_maps()
        surface = mayaUtils.mirror_blendshape_weight_map(
            self.plane,
            self.blendshape,
            weight_id=0,
            mapping=mayaUtils.MirrorMapping.SURFACE,
            sampler=sample_mirrored_weight_maps,
            show_progress=False,
        )

        np.testing.assert_allclose(surface[0], geometric[0], atol=0.05)

    def test_surface_mirror_keeps_the_source_side(self):
        """A surface mirror only rewrites the destination side."""
        mirrored = mayaUtils.mirror_blendshape_weight_map(
            self.plane,
            self.blendshape,
            weight_id=0,
            mapping=mayaUtils.MirrorMapping.SURFACE,
            sampler=sample_mirrored_weight_maps,
            mirror_blend_falloff=0.0,
            show_progress=False,
        )

        self.assertTrue(np.allclose(mirrored[0], self.original_maps[0], atol=0.05))


class MirrorWeightMapBenchmark(unittest.TestCase):
    """Timing comparison of the sampled transfer and the vertex pairing."""

    def setUp(self):
        if os.environ.get("BLUE_STEEL_SKIP_BENCHMARK"):
            raise unittest.SkipTest("BLUE_STEEL_SKIP_BENCHMARK is set")
        _delete_if_exists(BLENDSHAPE_NAME, TARGET_NAME, PLANE_NAME)
        (self.plane,
         self.blendshape,
         self.vertex_count,
         self.original_maps) = _create_plane(500)

    def tearDown(self):
        _delete_if_exists(BLENDSHAPE_NAME, TARGET_NAME, PLANE_NAME)

    def test_surface_is_faster_than_the_pairing(self):
        """Print and compare the timings of both mirror paths."""
        points = mayaUtils.get_mesh_raw_points(self.plane)[:, :3]

        start = time.perf_counter()
        mayaUtils.compute_geometric_symmetry_map(points, "x")
        pairing_seconds = time.perf_counter() - start

        start = time.perf_counter()
        mayaUtils.mirror_blendshape_weight_map(
            self.plane,
            self.blendshape,
            weight_id=0,
            mapping=mayaUtils.MirrorMapping.GEOMETRIC,
            show_progress=False,
        )
        geometric_seconds = time.perf_counter() - start

        Blendshape(self.blendshape).set_weight_map_values(
            0, self.original_maps[0].tolist()
        )
        start = time.perf_counter()
        mayaUtils.mirror_blendshape_weight_map(
            self.plane,
            self.blendshape,
            weight_id=0,
            mapping=mayaUtils.MirrorMapping.SURFACE,
            sampler=sample_mirrored_weight_maps,
            show_progress=False,
        )
        surface_seconds = time.perf_counter() - start

        print(f"\n[benchmark] {self.vertex_count} vertices")
        print(f"[benchmark]   pairing only         : {pairing_seconds:.3f}s")
        print(f"[benchmark]   geometric mirror     : {geometric_seconds:.3f}s")
        print(f"[benchmark]   surface mirror       : {surface_seconds:.3f}s")

        self.assertGreater(self.vertex_count, 100000)
        self.assertLess(surface_seconds, geometric_seconds)


def benchmark() -> None:
    """Run only the benchmark case and print its timings.

    Returns:
        None
    """

    suite = unittest.TestLoader().loadTestsFromTestCase(MirrorWeightMapBenchmark)
    unittest.TextTestRunner(verbosity=2).run(suite)


if __name__ == "__main__":
    unittest.main(verbosity=2)
