"""
This will handle the naming of the split map
"""
from .. import env
from . import utilities

SEPARATOR = env.SEPARATOR

class SplitMap(object):
    """
    This class will hold the suffixes of the split map
    """
    def __init__(self, name: str, suffixes: dict):
        """
        Set up the split map
        :param name: the name of the split map
        :param suffixes: the suffixes of the split map the long name is the key and the short name is the value
        """
        self.name = name
        self.suffixes = suffixes

    def __str__(self):
        return self.name

    def __repr__(self):
        return f"({self.name}, suffixes: {self.suffixes})"

    @property
    def short_suffixes(self):
        """
        Returns the short suffixes
        :return: the short suffixes
        """
        return self.suffixes.values()

    @property
    def long_suffixes(self):
        """
        Returns the long suffixes
        :return: the long suffixes
        """
        return self.suffixes.keys()


    @classmethod
    def create_default(cls):
        """
        Create a none split map
        :return: the none split map
        """

        return cls(name = "DEFAULT",suffixes = {"NONE": ""})

    @classmethod
    def create_left_right(cls, shapes= set):
        """
        Create a left right split map
        :return: the left right split map
        """
        return cls(name = "LEFT_RIGHT", suffixes = {"LEFT": "L", "RIGHT": "R"})

    @classmethod
    def create_four(cls):
        """
        Create a quad split map
        :return: the quad split map
        """
        return cls(name = "QUAD",
                   suffixes= {"TOPLEFT": "TL",
                              "TOPRIGHT": "TR",
                              "BOTTOMLEFT": "BL",
                              "BOTTOMRIGHT": "BR",})

    @classmethod
    def create_top_bottom(cls):
        """
        Create a left right split map
        :return: the left right split map
        """
        return cls(name = "TOP_BOTTOM",suffixes = {"TOP": "T", "BOTTOM": "B"})