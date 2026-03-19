"""
This will handle the naming of the split map
"""
from .. import env
from . import utilities

SEPARATOR = env.SEPARATOR

class SplitMap(object):
    """
    This class will hold the suffices of the split map
    """
    def __init__(self, name: str, suffices: dict):
        """
        Set up the split map
        :param name: the name of the split map
        :param suffices: the suffices of the split map the long name is the key and the short name is the value
        """
        self.name = name
        self.suffices = suffices

    def __str__(self):
        return self.name

    def __repr__(self):
        return f"({self.name}, suffices: {self.suffices})"

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


    @classmethod
    def create_default(cls):
        """
        Create a none split map
        :return: the none split map
        """

        return cls(name = "DEFAULT",suffices = {"NONE": ""})

    @classmethod
    def create_left_right(cls, shapes= set):
        """
        Create a left right split map
        :return: the left right split map
        """
        return cls(name = "LEFT_RIGHT", suffices = {"LEFT": "L", "RIGHT": "R"})

    @classmethod
    def create_four(cls):
        """
        Create a quad split map
        :return: the quad split map
        """
        return cls(name = "QUAD",
                   suffices= {"TOPLEFT": "TL",
                              "TOPRIGHT": "TR",
                              "BOTTOMLEFT": "BL",
                              "BOTTOMRIGHT": "BR",})

    @classmethod
    def create_top_bottom(cls):
        """
        Create a left right split map
        :return: the left right split map
        """
        return cls(name = "TOP_BOTTOM",suffices = {"TOP": "T", "BOTTOM": "B"})