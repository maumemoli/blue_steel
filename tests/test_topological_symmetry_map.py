"""Maya-free tests for the topological symmetry helpers in ``mayaUtils``.

``mayaUtils`` imports ``maya.OpenMaya``/``maya.cmds`` at module level, and
``blue_steel/__init__`` requires a live Maya session. The helpers under test are
pure numpy, so the module is loaded from its released path with lightweight
package and Maya stubs, following ``test_mirror_tools_helpers.py``.

Run with::

    python -m unittest discover -s tests -p "test_topological_symmetry_map.py"
"""

import importlib
import sys
import time
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


def _grid(columns: int, rows: int):
    """Build a flat quad grid, wound counter-clockwise seen from +Z.

    Vertex ids are ``row * (columns + 1) + column``. The grid is topologically
    symmetric across the vertical line going through the middle column, which
    requires an even ``columns`` count.

    Parameters:
        columns (int): Number of quads across.
        rows (int): Number of quads up.

    Returns:
        tuple: ``(num_vertices, polygon_counts, polygon_vertices)`` in the
        shape returned by ``MFnMesh.getVertices``.
    """
    width = columns + 1
    counts = []
    vertices = []
    for row in range(rows):
        for column in range(columns):
            counts.append(4)
            vertices.extend((row * width + column,
                             row * width + column + 1,
                             (row + 1) * width + column + 1,
                             (row + 1) * width + column))
    return width * (rows + 1), counts, vertices


def _grid_seed_edge(columns: int):
    """Get the vertical edge on the middle column of the first grid row."""
    width = columns + 1
    middle_column = columns // 2
    return middle_column, width + middle_column


def _tube(columns: int, rings: int):
    """Build a quad tube, closed in longitude and open at both ends.

    Vertex ids are ``ring * columns + column``. The tube is topologically
    symmetric across the vertical plane going through column ``0`` and
    column ``columns / 2``.

    Parameters:
        columns (int): Number of quads around the tube.
        rings (int): Number of vertex rings along the tube.

    Returns:
        tuple: ``(num_vertices, polygon_counts, polygon_vertices)`` in the
        shape returned by ``MFnMesh.getVertices``.
    """
    counts = []
    vertices = []
    for ring in range(rings - 1):
        for column in range(columns):
            following = (column + 1) % columns
            counts.append(4)
            vertices.extend((ring * columns + column,
                             ring * columns + following,
                             (ring + 1) * columns + following,
                             (ring + 1) * columns + column))
    return rings * columns, counts, vertices


def _cube():
    """Build a closed cube as six outward wound quads.

    Vertex ids follow ``bottom = 0..3`` (counter-clockwise) and
    ``top = 4..7``. The plane going through the edges ``0-4`` and ``2-6`` is
    a symmetry plane, so seeding on ``0-4`` pairs ``1 <-> 3`` and ``5 <-> 7``.

    Returns:
        tuple: ``(num_vertices, polygon_counts, polygon_vertices)`` in the
        shape returned by ``MFnMesh.getVertices``.
    """
    faces = [(3, 2, 1, 0), (4, 5, 6, 7), (0, 1, 5, 4),
             (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
    counts = [len(face) for face in faces]
    return 8, counts, [vertex for face in faces for vertex in face]


def _triangle_fan(segments: int):
    """Build a disk made of triangles around a centre vertex ``0``.

    The outer ring is ``1..segments`` and the disk is symmetric across the
    horizontal axis, which goes through the centre and the first ring vertex.

    Parameters:
        segments (int): Number of triangles, must be even.

    Returns:
        tuple: ``(num_vertices, polygon_counts, polygon_vertices)`` in the
        shape returned by ``MFnMesh.getVertices``.
    """
    counts = []
    vertices = []
    for segment in range(segments):
        counts.append(3)
        vertices.extend((0, segment + 1, (segment + 1) % segments + 1))
    return segments + 1, counts, vertices


def _edges(polygon_counts, polygon_vertices):
    """Build the unique undirected edges of a polygon soup, in face order."""
    edges = []
    seen = set()
    offset = 0
    for count in polygon_counts:
        face = polygon_vertices[offset:offset + count]
        offset += count
        for index, vertex in enumerate(face):
            edge = tuple(sorted((vertex, face[(index + 1) % count])))
            if edge in seen or edge[0] == edge[1]:
                continue
            seen.add(edge)
            edges.append(edge)
    return edges


class _FakeIntArray(list):
    """Minimal stand-in for ``OpenMaya.MIntArray``."""

    def setLength(self, length: int) -> None:
        self[:] = [0] * length


class _FakeCmds:
    """Minimal stand-in for ``maya.cmds`` covering warnings and edge lookup."""

    def __init__(self):
        self.warnings = []
        self.selection = []
        self.node_types = {}
        self.shapes = {}
        self.edge_lookup = {}

    def warning(self, message: str) -> None:
        self.warnings.append(message)

    def ls(self, items=None, **kwargs) -> list:
        if kwargs.get("selection"):
            return list(self.selection)
        return list(items or [])

    def objExists(self, name: str) -> bool:
        return True

    def nodeType(self, name: str) -> str:
        return self.node_types.get(name, "mesh")

    def listRelatives(self, name: str, **kwargs) -> list:
        return list(self.shapes.get(name, []))

    def polyListComponentConversion(self, component: str, **kwargs) -> list:
        if component not in self.edge_lookup:
            raise RuntimeError(f"No edge {component}")
        mesh = component.rsplit(".", 1)[0]
        return [f"{mesh}.vtx[{vertex_id}]"
                for vertex_id in self.edge_lookup[component]]

    def register_edges(self, mesh_name: str, edges) -> None:
        """Register ``mesh_name.e[i] -> (v0, v1)`` for every edge."""
        for edge_id, vertices in enumerate(edges):
            self.edge_lookup[f"{mesh_name}.e[{edge_id}]"] = vertices


class _FakeMesh:
    """Minimal stand-in for ``OpenMaya.MFnMesh`` topology queries."""

    def __init__(self, num_vertices, polygon_counts, polygon_vertices):
        self._num_vertices = num_vertices
        self._counts = polygon_counts
        self._vertices = polygon_vertices
        self._edges = _edges(polygon_counts, polygon_vertices)

    def numVertices(self) -> int:
        return self._num_vertices

    def numEdges(self) -> int:
        return len(self._edges)

    def getEdgeVertices(self, *args, **kwargs) -> None:
        raise AssertionError(
            "getEdgeVertices takes an int2& in the Maya API 1.0 bindings: "
            "edges must be resolved through polyListComponentConversion.")

    def getVertices(self, polygon_counts, polygon_vertices) -> None:
        polygon_counts.extend(self._counts)
        polygon_vertices.extend(self._vertices)


class TopologicalSymmetryMapTests(unittest.TestCase):
    """Tests for ``compute_topological_symmetry_map``."""

    def test_grid_symmetry_map(self):
        """A plane grid maps every vertex to the mirrored column of its row."""
        num_vertices, counts, vertices = _grid(4, 3)
        mapping = mayaUtils.compute_topological_symmetry_map(
            counts, vertices, num_vertices, _grid_seed_edge(4))

        self.assertEqual(len(mapping), num_vertices)
        self._assert_mirrored_columns(mapping, columns=4, rows=3)
        self._assert_involution(mapping)

    def test_grid_middle_line_vertices_map_to_themselves(self):
        """Vertices sitting on the symmetry line keep their own index."""
        num_vertices, counts, vertices = _grid(4, 3)
        mapping = mayaUtils.compute_topological_symmetry_map(
            counts, vertices, num_vertices, _grid_seed_edge(4))

        width = 5
        middle_column = 2
        for row in range(4):
            vertex_id = row * width + middle_column
            self.assertEqual(mapping[vertex_id], vertex_id)

    def test_tube_symmetry_map(self):
        """A closed-in-longitude tube maps the seam columns of every ring."""
        num_vertices, counts, vertices = _tube(8, 4)
        mapping = mayaUtils.compute_topological_symmetry_map(
            counts, vertices, num_vertices, (0, 8))

        self.assertEqual(len(mapping), num_vertices)
        for ring in range(4):
            for column in range(8):
                vertex_id = ring * 8 + column
                self.assertEqual(mapping[vertex_id], ring * 8 + (8 - column) % 8)
        self._assert_involution(mapping)

    def test_single_quad_self_maps(self):
        """A single quad has every vertex on the symmetry plane."""
        mapping = mayaUtils.compute_topological_symmetry_map([4], [0, 1, 2, 3], 4, (0, 1))
        self.assertEqual(mapping, [0, 1, 2, 3])

    def test_extra_shell_is_unmapped(self):
        """Vertices of other mesh shells cannot be reached and map to None."""
        num_a, counts_a, vertices_a = _grid(4, 3)
        num_b, counts_b, vertices_b = _grid(2, 2)
        mapping = mayaUtils.compute_topological_symmetry_map(
            counts_a + counts_b,
            vertices_a + [vertex_id + num_a for vertex_id in vertices_b],
            num_a + num_b,
            _grid_seed_edge(4))

        self.assertEqual(len(mapping), num_a + num_b)
        self.assertEqual(mapping[num_a:], [None] * num_b)
        self._assert_mirrored_columns(mapping[:num_a], columns=4, rows=3)

    def test_asymmetric_topology_is_partially_mapped(self):
        """Holes on one side stop the mirror but keep the map an involution."""
        num_vertices, counts, vertices = _grid(4, 3)
        faces = [vertices[index:index + 4] for index in range(0, len(vertices), 4)]
        counts = []
        vertices = []
        for face_index, face in enumerate(faces):
            # Drop the two right-most quads of the middle and top rows only.
            if face_index in (7, 11):
                continue
            counts.append(4)
            vertices.extend(face)

        stats = {}
        mapping = mayaUtils.compute_topological_symmetry_map(
            counts, vertices, num_vertices, _grid_seed_edge(4), stats=stats)

        self.assertEqual(len(mapping), num_vertices)
        self.assertGreater(stats["unmapped"], 0)
        self.assertIn(None, mapping)
        self.assertEqual(mapping[2], 2)
        self._assert_involution(mapping)

    def test_closed_cube_symmetry_map(self):
        """A closed cube mirrors the diagonal vertices around a seam edge."""
        num_vertices, counts, vertices = _cube()
        mapping = mayaUtils.compute_topological_symmetry_map(
            counts, vertices, num_vertices, (0, 4))

        self.assertEqual(mapping, [0, 3, 2, 1, 4, 7, 6, 5])
        self._assert_involution(mapping)

    def test_triangle_fan_symmetry_map(self):
        """Triangle faces and a high valence centre ring map across the seam."""
        num_vertices, counts, vertices = _triangle_fan(6)
        mapping = mayaUtils.compute_topological_symmetry_map(
            counts, vertices, num_vertices, (0, 1))

        self.assertEqual(mapping, [0, 1, 6, 5, 4, 3, 2])
        self._assert_involution(mapping)

    def test_degenerate_polygon_is_ignored(self):
        """Polygons with fewer than three vertices do not break the rings."""
        num_vertices, counts, vertices = _grid(4, 3)
        mapping = mayaUtils.compute_topological_symmetry_map(
            [2] + counts, [0, 1] + vertices, num_vertices, _grid_seed_edge(4))

        self.assertEqual(len(mapping), num_vertices)
        self._assert_mirrored_columns(mapping, columns=4, rows=3)

    def test_empty_mesh(self):
        """Empty and polygon-less meshes return an unmapped list."""
        self.assertEqual(mayaUtils.compute_topological_symmetry_map([], [], 0, (0, 1)), [])
        self.assertEqual(mayaUtils.compute_topological_symmetry_map([], [], 4, (0, 1)),
                         [None] * 4)

    def test_invalid_seed_edge(self):
        """Malformed or out of range seed edges raise a ValueError."""
        num_vertices, counts, vertices = _grid(4, 3)
        for seed_edge in [(2, 2), (2,), (0, num_vertices), None]:
            with self.assertRaises(ValueError):
                mayaUtils.compute_topological_symmetry_map(counts, vertices,
                                                           num_vertices, seed_edge)

    def test_large_mesh_performance(self):
        """A 200k vertex grid is mapped in a fraction of a second."""
        columns, rows = 500, 400
        num_vertices, counts, vertices = _grid(columns, rows)
        self.assertGreater(num_vertices, 200000)

        start = time.perf_counter()
        mapping = mayaUtils.compute_topological_symmetry_map(
            counts, vertices, num_vertices, _grid_seed_edge(columns))
        elapsed = time.perf_counter() - start
        print(f"\n[perf] {num_vertices} vertices mapped in {elapsed:.3f}s")

        self.assertEqual(len(mapping), num_vertices)
        self.assertNotIn(None, mapping)
        self.assertLess(elapsed, 5.0)

    def _assert_mirrored_columns(self, mapping, columns: int, rows: int) -> None:
        """Assert every vertex maps to the mirrored column of its row."""
        width = columns + 1
        for vertex_id in range((rows + 1) * width):
            row, column = divmod(vertex_id, width)
            self.assertEqual(mapping[vertex_id], row * width + (columns - column))

    def _assert_involution(self, mapping) -> None:
        """Assert the map is symmetric: the opposite of the opposite is itself."""
        for vertex_id, opposite in enumerate(mapping):
            if opposite is None:
                continue
            self.assertEqual(mapping[opposite], vertex_id)


class MayaWrapperTests(unittest.TestCase):
    """Tests for ``get_mesh_topological_symmetry_map`` with stubbed Maya."""

    def setUp(self):
        from unittest import mock

        self.num_vertices, self.counts, self.vertices = _grid(4, 3)
        self.mesh = _FakeMesh(self.num_vertices, self.counts, self.vertices)
        self.cmds = _FakeCmds()
        self.maya = types.SimpleNamespace(MIntArray=_FakeIntArray)
        self.expected = mayaUtils.compute_topological_symmetry_map(
            self.counts, self.vertices, self.num_vertices, _grid_seed_edge(4))
        self.seed_edge = _grid_seed_edge(4)
        self.edges = _edges(self.counts, self.vertices)
        self.edge_id = self.edges.index(self.seed_edge)
        self.cmds.register_edges("grid", self.edges)

        self._patchers = [
            mock.patch.object(mayaUtils, "create_mfn_mesh", lambda name: self.mesh),
            mock.patch.object(mayaUtils, "cmds", self.cmds),
            mock.patch.object(mayaUtils, "om", self.maya),
        ]
        for patcher in self._patchers:
            patcher.start()

    def tearDown(self):
        for patcher in reversed(self._patchers):
            patcher.stop()

    def test_edge_component_name(self):
        """An ``mesh.e[n]`` string resolves to the edge vertices."""
        mapping = mayaUtils.get_mesh_topological_symmetry_map(
            "grid", f"grid.e[{self.edge_id}]")
        self.assertEqual(mapping, self.expected)
        self.assertEqual(self.cmds.warnings, [])

    def test_edge_id_and_vertex_pair(self):
        """Edge ids and vertex pairs give the same map as the edge name."""
        self.assertEqual(mayaUtils.get_mesh_topological_symmetry_map("grid", self.edge_id),
                         self.expected)
        self.assertEqual(mayaUtils.get_mesh_topological_symmetry_map("grid", self.seed_edge),
                         self.expected)

    def test_selected_edge(self):
        """Without an explicit edge the current selection is used."""
        self.cmds.selection = ["grid.vtx[3]", f"grid.e[{self.edge_id}]"]
        self.assertEqual(mayaUtils.get_mesh_topological_symmetry_map("grid"), self.expected)

    def test_no_selected_edge_raises(self):
        """An empty selection without an explicit edge raises a ValueError."""
        with self.assertRaises(ValueError):
            mayaUtils.get_mesh_topological_symmetry_map("grid")

    def test_partial_map_warns(self):
        """An asymmetric mesh warns with the unmapped vertex count."""
        counts = []
        vertices = []
        faces = [self.vertices[index:index + 4]
                 for index in range(0, len(self.vertices), 4)]
        for face_index, face in enumerate(faces):
            if face_index in (7, 11):
                continue
            counts.append(4)
            vertices.extend(face)
        self.mesh = _FakeMesh(self.num_vertices, counts, vertices)

        mapping = mayaUtils.get_mesh_topological_symmetry_map("grid", self.seed_edge)
        self.assertIn(None, mapping)
        self.assertEqual(len(self.cmds.warnings), 1)
        self.assertIn("could not be mapped", self.cmds.warnings[0])

    def test_invalid_edge_raises(self):
        """Out of range, unknown and malformed edges raise a ValueError."""
        with self.assertRaises(ValueError):
            mayaUtils.get_mesh_topological_symmetry_map("grid", "grid.e[9999]")
        with self.assertRaises(ValueError):
            mayaUtils.get_mesh_topological_symmetry_map("grid", "grid")
        with self.assertRaises(ValueError):
            mayaUtils.get_mesh_topological_symmetry_map("grid", -1)

        self.cmds.edge_lookup.clear()
        with self.assertRaises(ValueError):
            mayaUtils.get_mesh_topological_symmetry_map("grid", f"grid.e[{self.edge_id}]")

    def test_transform_name_is_resolved_to_shape(self):
        """A mesh transform name is resolved to its mesh shape."""
        self.cmds.node_types["head"] = "transform"
        self.cmds.shapes["head"] = ["headShape"]
        self.cmds.register_edges("headShape", self.edges)
        self.cmds.register_edges("head", self.edges)

        self.assertEqual(
            mayaUtils.get_mesh_topological_symmetry_map("head", f"head.e[{self.edge_id}]"),
            self.expected)
        self.assertEqual(mayaUtils.get_mesh_topological_symmetry_map("head", self.edge_id),
                         self.expected)

    def test_transform_without_shape_raises(self):
        """A node without a mesh shape raises a ValueError."""
        self.cmds.node_types["group1"] = "transform"
        with self.assertRaises(ValueError):
            mayaUtils.get_mesh_topological_symmetry_map("group1", self.seed_edge)


if __name__ == "__main__":
    unittest.main()
