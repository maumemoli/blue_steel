"""
shape module:
This module provides classes to detect and represent shape types based on their names.

Shape types:
    - PrimaryShape: e.g. "lipCornerPuller"
    - InbetweenShape: e.g. "lipCornerPuller50" (50 is the inbetween value)
    - ComboShape: e.g. "lipCornerPuller_lipFunneler" (combo of two parents)
    - ComboInbetweenShape: e.g. "lipCornerPuller_lipFunneler50" (combo with inbetween parent)
"""
from ..api.blendshape import Weight
from . import utilities
from .. import env
from maya import cmds

SEPARATOR = env.SEPARATOR

class Shape(str):
    """
    Represents a shape and detects its type based on the name.

    Example:
        >>> shape = Shape.create("lipCornerPuller")  # PrimaryShape
        >>> inbetween_shape = Shape.create("lipCornerPuller50")  # InbetweenShape
        >>> combo_shape = Shape.create("lipCornerPuller_lipFunneler")  # ComboShape
        >>> combo_inbetween_shape = Shape.create("lipCornerPuller_lipFunneler50")  # ComboInbetweenShape
    """
    def __new__(cls, shape_name: str, separator=SEPARATOR):
        obj = str.__new__(cls, shape_name)
        obj.separator = separator
        obj.weight_id = None
        obj._weight_value = 1.0
        obj.muted = False
        return obj


    def __repr__(self):
        return f"{self.type}({super().__repr__()})"



    @property
    def level(self):
        """
        Get the level of the shape (number of parents).

        Returns:
            int: Level of the shape.
        """
        if self.type == "InvalidShape":
            return -1
        return len(self.split(self.separator))

    @property
    def parents(self):
        """
        Get the parent names of the shape.

        Returns:
            list: List of parent names.
        Example:
            >>> shape = Shape.create("lipCornerPuller_lipFunneler50")
            >>> shape.parents
            ['lipCornerPuller', 'lipFunneler50']
        """
        if self.type == "InvalidShape":
            return []
        parents = utilities.get_parents(self, self.separator)
        return [Shape.create(parent, self.separator) for parent in parents]

    @property
    def primaries(self):
        """
        Get the primary shapes from the shape name.

        Returns:
            list: List of primary shape names.
        """
        if self.type == "InvalidShape":
            return []
        primaries = utilities.get_primaries(self, self.separator)
        return [Shape.create(primary, self.separator) for primary in primaries]

    @property
    def split_combined_name(self):
        """
        Get the split combined shape names removing the prefix (all the uppercase letters at the end of each parent name).

        Returns:
            list: List of split combined shape names.
        """
        # TODO: This is a bit hacky, need to find a better way to do this. Maybe add a method in utilities to get the combined name without the prefix.
        if self.type == "InvalidShape":
            return []
        combined_parents = list()
        for parent in self.parents:
            parent_value = int(parent.values[0]*100)
            if parent_value == 100:
                parent_value = ""
            else:
                parent_value = str(parent_value)
            parent_primary = parent.primaries[0]
            truncation_index = len(parent_primary)
            for char in reversed(parent_primary):
                print(f"Checking char '{char}' in parent '{parent_primary}' for truncation")
                if char.isupper():
                    truncation_index -= 1
                    print(f"Char '{char}' is uppercase, truncation index now {truncation_index}")
                else:
                    break
            print(f"Truncation index for {parent_primary}: {truncation_index}")
            split_combined_shape = f"{parent_primary[:truncation_index]}{parent_value}"
            combined_parents.append(split_combined_shape)
        return self.separator.join(combined_parents)
    
    @property
    def values(self):
        """
        Get the shape values based on the last two digits of the parent name.
        If the parent name has less than two digits, the value is 100.

        Returns:
            list: List of shape values.
        """
        if self.type == "InvalidShape":
            return []
        shape_values = utilities.get_shape_values(self, self.separator)
        return shape_values

    @classmethod
    def create(cls, shape_name: str, separator=SEPARATOR):
        """
        Create a Shape instance based on the shape name.

        Parameters:
            shape_name (str): The shape name.
            separator (str): Separator used in shape names.

        Returns:
            Shape: An instance of PrimaryShape, InbetweenShape, ComboShape, or ComboInbetweenShape.

        Raises:
            ValueError: If the shape name is invalid.

        Example:
            >>> shape = Shape.create("lipCornerPuller")
        """
        if not utilities.is_valid(shape_name, separator):
            return InvalidShape(shape_name, separator)

        if utilities.is_primary(shape_name, separator):
            return PrimaryShape(shape_name, separator)
        if utilities.is_inbetween(shape_name, separator):
            return InbetweenShape(shape_name, separator)
        if utilities.is_combo(shape_name, separator):
            sorted_name = utilities.sort_combo_name(shape_name, separator)
            return ComboShape(sorted_name, separator)
        if utilities.is_combo_inbetween(shape_name, separator):
            sorted_name = utilities.sort_combo_name(shape_name, separator)
            return ComboInbetweenShape(sorted_name, separator)
        
        return None

    @property
    def unsplit_name(self):
        """
        Get the unsplit name of the shape (without separators).

        Returns:
            str: Unsplitted shape name.
        """
        return utilities.get_unsplit_name(self, self.separator)

    @property
    def split_suffices(self):
        """
        Get the split suffixes of the shape (parts after the first parent).

        Returns:
            list: List of suffixes.
        """
        return utilities.get_split_suffixes(self, self.separator)

    @property
    def type(self):
        """
        Get the type name of the shape.

        Returns:
            str: Type name.
        """
        return type(self).__name__

class InbetweenShape(Shape):
    """
    Represents an inbetween shape.

    Example:
        >>> shape = InbetweenShape("lipCornerPuller50")
    """
    def __new__(cls, shape_name: str, separator=SEPARATOR):
        obj = super().__new__(cls, shape_name, separator)
        return obj

class ComboShape(Shape):
    """
    Represents a combo shape.

    Example:
        >>> shape = ComboShape("lipCornerPuller_lipFunneler")
    """
    def __new__(cls, shape_name: str, separator=SEPARATOR):
        shape_name = utilities.sort_combo_name(shape_name, separator)
        obj = super().__new__(cls, shape_name, separator)
        return obj

class PrimaryShape(Shape):
    """
    Represents a primary shape.

    Example:
        >>> shape = PrimaryShape("lipCornerPuller")
    """
    def __new__(cls, shape_name: str, separator=SEPARATOR):
        obj = super().__new__(cls, shape_name, separator)
        return obj

class ComboInbetweenShape(Shape):
    """
    Represents a combo inbetween shape.

    Example:
        >>> shape = ComboInbetweenShape("lipCornerPuller_lipFunneler50")
    """
    def __new__(cls, shape_name: str, separator=SEPARATOR):
        obj = super().__new__(cls, shape_name, separator)
        return obj

class InvalidShape(Shape):
    """
    Represents an invalid shape.
    """
    def __new__(cls, shape_name: str, separator=SEPARATOR, missing_elements=[]):
        obj = super().__new__(cls, shape_name, separator)
        obj.missing_elements = missing_elements
        return obj