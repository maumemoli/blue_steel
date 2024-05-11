"""
shape module:
This classes is used to detect the shapes based on the name.
The shape type is determined by the name.
The shape types are:
PrimaryShape: Ex. str(lipCornerPuller)
InbetweenShape: Ex. str(lipCornerPuller50) 50 is the value of the inbetween.
ComboShape: Ex. str(lipCornerPuller_lipFunneler) lipCornerPuller and lipFunneler are the parents of the combo shape.
ComboInbetweenShape: Ex. str(lipCornerPuller_lipFunneler50) lipCornerPuller and lipFunneler50 are the parents of the
    combo shape and 50 is the value of the inbetween in this case one of the parents is an inbetween shape.
"""
from blue_steel.logic.splitMap import SplitMap
import blue_steel.logic.utilities as utilities
import blue_steel.env as env
SEPARATOR = env.SEPARATOR



class Shape(object):
    """
    This class is used to detect the shape type based on the name.
    To create a shape use the create method:
    shape = Shape.create("lipCornerPuller") a PrimaryShape is created.
    shape = Shape.create("lipCornerPuller50") a InbetweenShape is created.
    shape = Shape.create("lipCornerPuller_lipFunneler") a ComboShape is created.
    shape = Shape.create("lipCornerPuller_lipFunneler50") a ComboInbetweenShape is created.
    """

    def __init__(self, shape_name: str, split_maps=None):
        """
        Set up the shape name
        :param shape_name: the shape name
        :param split_maps: the split maps with the primary shapes split associated.
        """
        shape_name = SEPARATOR.join(sorted(shape_name.split(SEPARATOR)))
        self.shape_name = shape_name
        shape_primaries = utilities.get_primaries(shape_name)
        # if the split maps are not provided create an empty one.
        if split_maps is None:
            split_maps = list()
            none_split_map = SplitMap(name="NONE", suffices={"": ""}, shapes=shape_primaries)
            split_maps.append(none_split_map)
        self.split_maps = split_maps
        # checking if the splitmaps are valid
        split_maps_tokens = list()
        for split_map in self.split_maps:
            split_maps_tokens.extend(split_map.shapes)
        no_split_shapes = set(shape_primaries) - set(split_maps_tokens)
        if no_split_shapes:
            raise ValueError(f"Split maps do not contain the following shapes: {no_split_shapes}")

    @property
    def split_names(self):
        """
        Get the split names
        :return: the split names
        """
        split_shapes = list()
        for split_map in self.split_maps:
            map_shapes = list()
            for split_shape in split_map.generate_split_shapes(self.shape_name):
                if split_shape:
                    map_shapes.append(split_shape)
            if map_shapes:
                split_shapes.append(map_shapes)
        # combining the split names
        return utilities.combine_lists(split_shapes)

    @property
    def level(self):
        """
        Get the level of the shape
        :return: the level of the shape
        """

        return len(self.shape_name.split(SEPARATOR))

    @property
    def parents(self):
        """
        Get the parents of the shape
        :return: the parents of the shape
        """
        return utilities.get_parents(self.shape_name)

    @staticmethod
    def is_valid(shape_name):
        """
        Check if the shape is valid
        :return: True if the shape is valid
        """
        return utilities.is_valid(shape_name)

    @staticmethod
    def is_combo_inbetween(shape_name: str):
        """
        Check if the shape is a combo inbetween shape
        :return: True if the shape is a combo inbetween shape
        """
        return utilities.is_combo_inbetween(shape_name)

    @staticmethod
    def is_combo(shape_name: str):
        """
        Check if the shape is a combo shape
        :return: True if the shape is a combo shape
        """
        return utilities.is_combo(shape_name)

    @staticmethod
    def is_inbetween(shape_name: str):
        """
        Check if the shape is an inbetween shape
        :return: True if the shape is an inbetween shape
        """
        return utilities.is_inbetween(shape_name)

    @staticmethod
    def is_primary(shape_name: str):
        """
        Check if the shape is a primary shape
        :return: True if the shape is a primary shape
        """
        return utilities.is_primary(shape_name)

    @property
    def primaries(self):
        return utilities.get_primaries(self.shape_name)

    @property
    def values(self):
        """
        Get the shape values based on the last two digits of the parent name.
        If the parent name has less than two digits the value is 100.
        """
        shape_values = utilities.get_shape_values(self.shape_name)
        return shape_values

    @classmethod
    def create(cls, shape_name: str, split_maps=None):
        """
        Create a shape based on the shape name
        :param shape_name: the shape name
        :param split_maps: the split maps
        """
        if not utilities.is_valid(shape_name):
            raise ValueError("Invalid shape name: {}".format(shape_name))
        if cls.is_primary(shape_name):
            return PrimaryShape(shape_name, split_maps)
        elif cls.is_inbetween(shape_name):
            return InbetweenShape(shape_name, split_maps)
        elif cls.is_combo(shape_name):
            return ComboShape(shape_name, split_maps)
        elif cls.is_combo_inbetween(shape_name):
            return ComboInbetweenShape(shape_name, split_maps)
        else:
            return None

    @property
    def type(self):
        return type(self).__name__

    def __str__(self):
        return self.shape_name

    def __repr__(self):
        return self.shape_name

class InbetweenShape(Shape):
    """
    This class is used to create inbetween shapes
    """
    def __int__(self, shape_name: str, split_maps: list):
        super(InbetweenShape).__init__(shape_name, split_maps)


class ComboShape(Shape):
    """
    This class is used to create combo shapes
    """
    def __int__(self, shape_name: str, split_maps: list):
        super(ComboShape).__init__(shape_name, split_maps)


class PrimaryShape(Shape):
    """
    This class is used to create primary shapes
    """
    def __int__(self, shape_name: str, split_maps: list):
        super(PrimaryShape).__init__(shape_name, split_maps)


class ComboInbetweenShape(Shape):
    """
    This class is used to create combo inbetween shapes
    """
    def __int__(self, shape_name: str, split_maps: list):
        super(ComboInbetweenShape).__init__(shape_name, split_maps)

















