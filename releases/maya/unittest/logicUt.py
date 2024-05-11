#from ..scripts.blue_steel.logic.shape import Shape

import sys
sys.path.append(r'C:\\git\\blue_steel\\releases\\maya\\scripts\\')
import os
import unittest
from importlib import reload
import blue_steel.logic.shape as sh
import blue_steel.logic.splitMap as sm
import blue_steel.logic.network as net
reload(sh)
reload(sm)
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

    def test_split_map(self):
        split_maps = self.create_split_maps()
        shape = sh.Shape("lipCornerPuller_jawOpen_lipDimpler50_lipFunneler", split_maps)
        result = ['jawOpen_lipCornerPullerL_lipDimplerL50_lipFunnelerTL',
                  'jawOpen_lipCornerPullerL_lipDimplerL50_lipFunnelerTR',
                  'jawOpen_lipCornerPullerL_lipDimplerL50_lipFunnelerBL',
                  'jawOpen_lipCornerPullerL_lipDimplerL50_lipFunnelerBR',
                  'jawOpen_lipCornerPullerR_lipDimplerR50_lipFunnelerTL',
                  'jawOpen_lipCornerPullerR_lipDimplerR50_lipFunnelerTR',
                  'jawOpen_lipCornerPullerR_lipDimplerR50_lipFunnelerBL',
                  'jawOpen_lipCornerPullerR_lipDimplerR50_lipFunnelerBR']
        self.assertEqual(shape.split_names, result)
        split_maps[1].clear_shapes()
        self.assertEqual(split_maps[1].shapes, [])

        return True

    @staticmethod
    def create_split_map(name, long_suffices, short_suffices, shapes):
        return sm.SplitMap(name, {k: v for k, v in zip(long_suffices, short_suffices)}, shapes)

    @classmethod
    def create_split_maps(cls):
        split_maps = list()

        split_map = sm.SplitMap.create_default(shapes=["jawOpen", "lipsTogether", "lipsPart"])
        split_maps.append(split_map)
        split_map = sm.SplitMap.create_left_right(shapes=["lipCornerPuller", "lipDimpler", "noseWrinkler"])
        split_maps.append(split_map)
        split_map = sm.SplitMap.create_four(shapes=["lipFunneler", "lipPucker", "lipsPressor"])
        split_maps.append(split_map)
        return split_maps

class TestNetwork(unittest.TestCase):

    def test_create(self):
        network = net.Network("shapesSystem")
        self.assertEqual(network.name, "shapesSystem")
        return True

    def test_add_split_map(self):
        split_maps = TestShape.create_split_maps()
        for split_map in split_maps:
            split_map.clear_shapes()
        network = net.Network("shapesSystem")
        for split_map in split_maps:
            network.add_split_map(split_map)
        self.assertEqual(network.split_map_names, ["DEFAULT", "LEFT_RIGHT", "QUAD"])
        network.add_shape("lipCornerPuller", "LEFT_RIGHT")
        network.add_shape("lipFunneler", "QUAD")
        network.add_shape("jawOpen", "DEFAULT")
        network.add_shape("lipCornerPuller50")
        network.add_shape("lipCornerPuller_lipFunneler")
        network.add_shape("lipCornerPuller_lipFunneler_jawOpen")
        network.add_shape("lipCornerPuller50_lipFunneler")
        # for split_map in split_maps:
        #     print(split_map.name)
        #     print(split_map.shapes)
        jaw_open = network.get_shape("lipCornerPuller50_lipFunneler").split_names
        print(jaw_open)
        print(network.primaries)
        print(network.inbetweens)
        print(network.combo)
        print(network.combo_inbetween)
        # print(jaw_open.split_maps[0].shapes)


if __name__ == "__main__":
    unittest.main()

