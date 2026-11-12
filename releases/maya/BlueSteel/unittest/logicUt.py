#from ..scripts.blue_steel.logic.shape import Shape

import sys
sys.path.append(r'C:\\git\\blue_steel\\releases\\maya\\scripts\\')
import os
import unittest
from importlib import reload
import blue_steel.logic.shape as sh
import blue_steel.logic.network as net
reload(sh)
reload(net)


class TestShape(unittest.TestCase):
    def test_is_combo_inbetween(self):
        self.assertTrue(sh.Shape.is_combo_inbetween("a_b10"))
        self.assertFalse(sh.Shape.is_combo_inbetween("a"))
        self.assertFalse(sh.Shape.is_combo_inbetween("b10"))
        self.assertFalse(sh.Shape.is_combo_inbetween("a_b"))

        return True

    def test_is_inbetween(self):
        self.assertTrue(sh.Shape.is_inbetween("b10"))
        self.assertFalse(sh.Shape.is_inbetween("a_b10"))
        self.assertFalse(sh.Shape.is_inbetween("a"))
        self.assertFalse(sh.Shape.is_inbetween("a_b"))

        return True

    def test_is_primary(self):
        self.assertTrue(sh.Shape.is_primary("a"))
        self.assertFalse(sh.Shape.is_primary("a_b10"))
        self.assertFalse(sh.Shape.is_primary("b10"))
        self.assertFalse(sh.Shape.is_primary("a_b"))

        return True

    def test_is_combo(self):
        self.assertTrue(sh.Shape.is_combo("a_b"))
        self.assertFalse(sh.Shape.is_combo("a"))
        self.assertFalse(sh.Shape.is_combo("b10"))
        self.assertFalse(sh.Shape.is_combo("a_b10"))

        return True

    def test_get_primaries(self):
        self.assertEqual(sh.Shape("a_b10").primaries, ["a", "b"])

        return True

    def test_shape_values(self):
        self.assertEqual(sh.Shape("a_b10").values, [1.0, 0.1])

        return True

    def test_shape_parents(self):
        self.assertEqual(sh.Shape("a_b10").parents, ["a", "b10"])

        return True

    def test_level(self):
        self.assertEqual(sh.Shape("a_b10").level, 2)
        self.assertEqual(sh.Shape("a").level, 1)
        return True

    def test_is_valid(self):
        self.assertTrue(sh.Shape("a_b10").is_valid)
        self.assertTrue(sh.Shape("a").is_valid)
        self.assertTrue(sh.Shape("b10").is_valid)
        self.assertTrue(sh.Shape("a_b").is_valid)
        return True

    def test_create(self):
        self.assertEqual(sh.Shape.create("a_b10").type, "ComboInbetweenShape")
        self.assertEqual(sh.Shape.create("a").type, "PrimaryShape")
        self.assertEqual(sh.Shape.create("b10").type, "InbetweenShape")
        self.assertEqual(sh.Shape.create("a_b").type, "ComboShape")
        return True


class TestNetwork(unittest.TestCase):

    def test_create(self):
        network = net.Network("shapesSystem")
        self.assertEqual(network.name, "shapesSystem")
        return True


if __name__ == "__main__":
    unittest.main()

