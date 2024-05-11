"""
This will handle the naming of the split map
"""
import blue_steel.env as env
import blue_steel.logic.utilities as utilities
SEPARATOR = env.SEPARATOR

class SplitMap(object):
    """
    This class will hold the suffices of the split map
    """
    def __init__(self, name: str, suffices: dict, shapes=list()):
        """
        Set up the split map
        :param name: the name of the split map
        :param suffices: the suffices of the split map the long name is the key and the short name is the value
        :param shapes: the shapes that belong to the split map
        """
        self.name = name
        self.suffices = suffices
        self._shapes = shapes

    def __str__(self):
        return self.name

    def __repr__(self):
        return self.name

    def clear_shapes(self):
        """
        Clear the shapes
        """
        self._shapes = list()

    def add_shape(self, shape_name: str):
        """
        Add a shape to the split map
        :param shape_name: the shape name
        """
        if shape_name not in self._shapes:
            self._shapes.append(shape_name)

    def add_shapes(self, shapes: list):
        """
        Add a list of shapes to the split map
        :param shapes: the list of shapes
        """
        for shape_name in shapes:
            self.add_shape(shape_name)

    @property
    def shapes(self):
        """
        Returns the shapes
        :return: the shapes
        """
        return self._shapes

    @shapes.setter
    def shapes(self, shapes: list):
        """
        Set the shapes
        :param shapes: the shapes
        """
        self._shapes = shapes

    @property
    def short_suffices(self):
        """
        Returns the short suffices
        :return: the short suffices
        """
        return self.suffices.values()

    @property
    def long_suffices(self):
        """
        Returns the long suffices
        :return: the long suffices
        """
        return self.suffices.keys()

    @staticmethod
    def separate_digits(name: str):
        """
        Separate the incremental digits from the name.
        :param name: the name with digits to separate
        :return: name, digits
        """
        return utilities.separate_digits(name)

    def generate_split_shapes(self, shape_name: str):
        """
        Returns the split names based on the shape name.
        :param shape_name: the shape name to split
        :return: the split shapes
        """
        split_shapes = list()
        shape_name_tokens = shape_name.split(SEPARATOR)
        for suffix in self.short_suffices:
            shape_tokens = list()
            for shape in shape_name_tokens:
                shape_primary = utilities.get_primaries(shape)[0]
                if shape_primary in self.shapes:
                    name, digits = self.separate_digits(shape)
                    split_shape = f"{name}{suffix}{digits}"
                    if split_shape:
                        shape_tokens.append(split_shape)
            split_shapes.append(SEPARATOR.join(shape_tokens))
        return split_shapes

    @classmethod
    def create_default(cls, shapes=list()):
        """
        Create a none split map
        :return: the none split map
        """

        return cls("DEFAULT", {"DEFAULT": ""}, shapes)

    @classmethod
    def create_left_right(cls, shapes=list()):
        """
        Create a left right split map
        :return: the left right split map
        """
        return cls("LEFT_RIGHT", {"LEFT": "L", "RIGHT": "R"}, shapes)

    @classmethod
    def create_four(cls, shapes=list()):
        """
        Create a quad split map
        :return: the quad split map
        """
        return cls("QUAD", {"TOPLEFT": "TL", "TOPRIGHT": "TR", "BOTTOMLEFT": "BL", "BOTTOMRIGHT": "BR",}, shapes)