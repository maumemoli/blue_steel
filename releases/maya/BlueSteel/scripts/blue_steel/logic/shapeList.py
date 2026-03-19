from . import utilities
from .shape import Shape
from .. import env

SEPARATOR = env.SEPARATOR



class ShapeList(list):
    """
    A list to hold Shape instances with additional utility methods.

    Example:
        >>> shape_list = ShapeList()
        >>> shape_list.append(Shape.create("lipCornerPuller"))
    """
    def __init__(self, shape_list=None, separator=SEPARATOR):
        """
        Initialize a ShapeList instance.

        Parameters:
            shape_list (list): A list of Shape instances or shape names (str).
            separator (str): Separator used in shape names.
        """
        super().__init__()
        self._shape_set = set()  # to track unique shapes
        self._weight_id_map = {} # Map weight_id to shape
        if shape_list is None:
            shape_list = []
        self.separator = separator
        for shape in shape_list:
            self.append(shape)

    def get_shape_by_weight_id(self, weight_id: int)-> Shape:
        """
        Get a shape by its weight ID.
        
        Parameters:
            weight_id (int): The weight ID to look for.
            
        Returns:
            Shape or None: The shape with the matching weight ID.
        """
        return self._weight_id_map.get(weight_id)

    def clear(self):
        self._shape_set.clear()
        self._weight_id_map.clear()
        return super().clear()

    def get_adjacent_inbetweens(self, shape: str)-> tuple:
        """
        Find adjacent inbetween shapes for a given inbetween shape.

        Parameters:
            shape (str): The inbetween shape to find adjacent inbetweens for.
        Returns:
            tuple: (previous_sibling, next_sibling) or (None, None) if not found.
        """
        shape = self.get_shape(shape)
        if shape is None:
            raise ValueError(f"Shape {shape} not found in ShapeList")
        if shape.type != "InbetweenShape":
            raise ValueError(f"Shape {shape} is not an InbetweenShape")
        primary = shape.primaries[0]
        inbetweens = self.get_inbetween_shapes_for_primary(primary)
        if len(inbetweens) ==1:
            return None, None
        inbetweens.sort(key=lambda s: s.values[0])
        index = inbetweens.index(shape)
        if index == 0:
            return None, inbetweens[1]
        if index == len(inbetweens) -1:
            return inbetweens[index -1], None
        return inbetweens[index -1], inbetweens[index +1]
        
    def get_inbetween_shapes_for_primary(self, primary: str) -> "ShapeList":
        """
        Get all inbetween shapes associated with a given primary shape.

        Parameters:
            primary (str): The primary shape to find inbetweens for.

        Returns:
            ShapeList: A ShapeList containing all inbetween shapes for the primary.
        """
        inbetweens = ShapeList([], self.separator)
        for shape in self:
            if shape.type == "InbetweenShape" and shape.primaries[0] == primary:
                inbetweens.append(shape)
        # we need to sort the inbetweens by their value
        inbetweens.sort(key=lambda s: s.values[0])
        return inbetweens

    def get_shape_siblings(self, shape: str) -> "ShapeList":
        """
        Get all sibling shapes of a given shape.
        Parameters:
            shape (str): The shape to find siblings for.
            Returns:
                ShapeList: A ShapeList containing all sibling shapes.
        Example:
            >>> shape_list = ShapeList([Shape.create("lipCornerPuller"),
                                        Shape.create("lipCornerPuller50"),
                                        Shape.create("jawOpen"),
                                        Shape.create("jawOpen50"),
                                        Shape.create("jawOpen_lipCornerPuller"),
                                        Shape.create("jawOpen50_lipCornerPuller"),
                                        Shape.create("jawOpen_lipCornerPuller50"),
                                        Shape.create("jawOpen50_lipCornerPuller50")
                                        ])
            >>> siblings = shape_list.get_shape_siblings("jawOpen_lipCornerPuller50")
            >>> for sibling in siblings:
            ...     print(sibling)
            smile
            frown
        """
        siblings = ShapeList([], self.separator)
        shape = self.get_shape(shape)
        if shape is None:
            return siblings
        primaries = shape.primaries
        for other_shape in self:
            if other_shape == shape:
                continue
            if set(other_shape.primaries) == set(primaries):
                siblings.append(other_shape)
        return siblings


    def append(self, shape: Shape):
        """
        Append a Shape instance to the list.

        Parameters:
            shape (Shape): The Shape instance to append.

        """
        if shape in self._shape_set:
            self.remove(shape)
        self._shape_set.add(shape)
        if hasattr(shape, 'weight_id') and shape.weight_id is not None:
            self._weight_id_map[shape.weight_id] = shape
        super().append(shape)

    def __contains__(self, key):
        return key in self._shape_set
    

    def remove(self, shape):
        self._shape_set.discard(shape)
        if hasattr(shape, 'weight_id') and shape.weight_id is not None:
            self._weight_id_map.pop(shape.weight_id, None)
        return super().remove(shape)

    def extend(self, shapes: "ShapeList"):
        """
        Extend the list with multiple Shape instances.

        Parameters:
            shapes (ShapeList): A ShapeList instance to extend the list with.

        Raises:
            TypeError: If the provided argument is not a ShapeList instance.
        """
        if not isinstance(shapes, ShapeList):
            raise TypeError("Argument to extend must be a ShapeList instance")
        if shapes.separator != self.separator:
            raise ValueError("ShapeList instances must have the same separator to be extended.")
        # avoid adding duplicates
        shapes = [shape for shape in shapes if shape not in self]
        for shape in shapes:
            self._shape_set.add(str(shape))
        super().extend(shapes)

    def __eq__(self, value):
        return self._shape_set == value


    def get_valid_shapes(self)-> "ShapeList":
        """
        Get all valid shapes in the list.

        Returns:
            ShapeList: A ShapeList containing all valid shapes.
        """
        valid_shapes = ShapeList([], self.separator)
        for shape in self:
            if shape.type != "InvalidShape":
                valid_shapes.append(shape)
        return valid_shapes


    def sort_for_insertion(self) -> "ShapeList":
        """
        Sort the ShapeList in place based on insert priority.
        Primaries come before inbetween, and combos after.

        Returns:
             ShapeList: Sorted list of Shape instances.
        """
        type_priority = {
            "PrimaryShape": 0,
            "InbetweenShape": 1,
            "ComboShape": 2,
            "ComboInbetweenShape": 3,
            "InvalidShape": 4
        }
        return ShapeList(sorted(self,key=lambda shape: (type_priority.get(shape.type, 99),shape.level, shape)))

    def sort_for_display(self) -> "ShapeList":
        """
        Return a sorted ShapeList of Shape instances based on type priority, then names and level.
        Inbetween shapes come before primaries.

        Returns:
            ShapeList: Sorted list of Shape instances.
        """
        valid_shapes = self.get_valid_shapes()
        sorted_shapes = ShapeList([], self.separator)
        primaries = valid_shapes.primary_shapes
        for primary in primaries:
            sorted_shapes.append(primary)
            inbetweens = valid_shapes.get_inbetween_shapes_for_primary(primary)
            for inbetween in inbetweens:
                sorted_shapes.append(inbetween)
        combo = valid_shapes.get_combo_shapes()
        combo_inbetween = valid_shapes.get_combo_inbetween_shapes()
        combo.extend(combo_inbetween)
        # sorting the combos by level and name
        combo = ShapeList(sorted(combo, key=lambda shape: (shape.level, shape)))
        sorted_shapes.extend(combo)
        return sorted_shapes

    def get_shape(self, shape_name: str) -> Shape:
        """
        Get a Shape instance by its name.

        Parameters:
            shape_name (str): The name of the shape to retrieve.

        Returns:
            Shape or None: The Shape instance if found, None otherwise.
        """
        for shape in self:
            if shape == shape_name:
                return shape
        return None

    def get_missing_elements(self, shape_name: str) -> list:
        """
        Get the missing elements names of a shape by its name.

        Parameters:
            shape_name (str): The name of the shape to check for missing parents.

        Returns:
            list: List of missing parent names if shape is found, [] otherwise.
        """
        missing_parents = []
        tokens_num = len(shape_name.split(self.separator))
        if utilities.is_inbetween(shape_name, self.separator):
            primary = utilities.get_primaries(shape_name)[0]
            if primary not in self:
                missing_parents.append(primary)
            return missing_parents
        if tokens_num > 1:
            parents = utilities.get_parents(shape_name)
            for parent in parents:
                if parent not in self:
                    missing_parents.append(parent)
        return missing_parents


    @property
    def primary_shapes(self) -> "ShapeList":
        """
        Get all primary shapes in the list.

        Returns:
            ShapeList: A ShapeList containing all primary shapes.
        """
        primaries = ShapeList([], self.separator)
        for shape in self:
            if shape.type == "PrimaryShape":
                primaries.append(shape)
        return primaries

    @property
    def inbetween_shapes(self) -> "ShapeList":
        """
        Get all inbetween shapes in the list.

        Returns:
            ShapeList: A ShapeList containing all inbetween shapes.
        """
        inbetween_shapes = ShapeList([], self.separator)
        for shape in self:
            if shape.type == "InbetweenShape":
                inbetween_shapes.append(shape)
        return inbetween_shapes

    @property
    def combo_shapes(self) -> "ShapeList":
        """
        Get all combo shapes in the list.

        Returns:
            ShapeList: A ShapeList containing all combo shapes.
        """
        combos = ShapeList([], self.separator)
        for shape in self:
            if shape.type == "ComboShape":
                combos.append(shape)
        return combos

    @property
    def combo_inbetween_shapes(self) -> "ShapeList":
        """
        Get all combo inbetween shapes in the list.

        Returns:
            ShapeList: A ShapeList containing all combo inbetween shapes.
        """
        combo_inbetweens = ShapeList([], self.separator)
        for shape in self:
            if shape.type == "ComboInbetweenShape":
                combo_inbetweens.append(shape)
        return combo_inbetweens

    @property
    def invalid_shapes(self) -> "ShapeList":
        """
        Get all invalid shapes in the list.

        Returns:
            ShapeList: A ShapeList containing all invalid shapes.
        """
        invalids = ShapeList([], self.separator)
        for shape in self:
            if shape.type == "InvalidShape":
                invalids.append(shape)
        return invalids

    def get_related_shapes_upstream(self, shape_name: str) -> "ShapeList":
        """
        Get all the shapes that are going to have a value when the specific shape is set to 1.0.
        
        Parameters:
            shape_name (str): The name of the shape to find related upstream shapes for.
        Returns:
            ShapeList: A ShapeList containing all related upstream shapes.
        """
        related_shapes = ShapeList([], self.separator)
        shape = self.get_shape(shape_name)
        if shape is None:
            shape = Shape.create(shape_name, self.separator) # create a temporary shape to get its parents
        if shape.type in ["ComboShape", "ComboInbetweenShape"]:
            for other_shape in self:
                if other_shape == shape:
                    related_shapes.append(other_shape)
                elif  shape.level <= other_shape.level: # this is not upstream
                    continue
                elif other_shape.type == "InvalidShape":
                    continue
                elif other_shape.type in ["ComboShape", "ComboInbetweenShape"]:
                    if all(parent in shape.parents for parent in other_shape.parents):
                        related_shapes.append(other_shape)
                elif other_shape.type in ["PrimaryShape", "InbetweenShape"]:
                    if other_shape in shape.parents:
                        related_shapes.append(other_shape)
        return related_shapes

    def get_related_shapes_downstream(self, shape_name: str, include_self=False) -> "ShapeList":
        """
        Get all descendant shapes of a specific shape.

        Parameters:
            shape_name (str): The name of the shape to find descendants for.

        Returns:
            ShapeList: A ShapeList containing all descendant shapes.
        """
        descendants = ShapeList([], self.separator)
        shape = self.get_shape(shape_name)
        if shape is None:
            shape = Shape.create(shape_name, self.separator) # create a temporary shape to get its parents
        if shape.type == "InvalidShape":
            return descendants
        is_primary = shape.type == "PrimaryShape"
        is_combo = shape.type == "ComboShape"
        for other_shape in self:
            if other_shape == shape and not include_self:
                descendants.append(other_shape)
                continue
            subshapes = other_shape.primaries if is_primary or is_combo else other_shape.parents
            shape_parts = shape.primaries if is_combo else shape.parents
            if all(parent in subshapes for parent in shape_parts):
                descendants.append(other_shape)
        return descendants

    def get_affected(self, shape_name: str) -> "ShapeList":
        """
        Get all shapes affected by a specific shape.
        This similar to get_related_shapes_downstream, but it will include the inbetween shapes with the same primary.

        Parameters:
            shape_name (str): The name of the shape to find affected shapes for.

        Returns:
            ShapeList: A ShapeList containing all affected shapes.
        """
        affected = ShapeList([], self.separator)
        shape = self.get_shape(shape_name)
        if shape is None:
            return affected
        is_primary = shape.type in ["PrimaryShape", "ComboShape"]
        for other_shape in self:
            if other_shape == shape:
                continue
            subshapes = other_shape.primaries if is_primary else other_shape.parents
            if all(parent in subshapes for parent in shape.parents):
                affected.append(other_shape)
        return affected

    def get_inbetween_shapes(self) -> "ShapeList":
        """
        Get all inbetween shapes in the list.

        Returns:
            ShapeList: A ShapeList containing all inbetween shapes.
        """
        inbetweens = ShapeList([], self.separator)
        for shape in self:
            if shape.type == "InbetweenShape":
                inbetweens.append(shape)
        return inbetweens

    def get_combo_shapes(self) -> "ShapeList":
        """
        Get all combo shapes in the list.

        Returns:
            ShapeList: A ShapeList containing all combo shapes.
        """
        combos = ShapeList([], self.separator)
        for shape in self:
            if shape.type == "ComboShape":
                combos.append(shape)
        return combos

    def get_combo_inbetween_shapes(self) -> "ShapeList":
        """
        Get all combo inbetween shapes in the list.

        Returns:
            ShapeList: A ShapeList containing all combo inbetween shapes.
        """
        combo_inbetween = ShapeList([], self.separator)
        for shape in self:
            if shape.type == "ComboInbetweenShape":
                combo_inbetween.append(shape)
        return combo_inbetween

    def get_by_level(self, level: int) -> "ShapeList":
        """
        Get all shapes of a specific level.

        Parameters:
            level (int): The level of shapes to retrieve.

        Returns:
            ShapeList: A ShapeList containing all shapes of the specified level.
        """
        shapes_of_level = ShapeList([], self.separator)
        for shape in self:
            if shape.level == level:
                shapes_of_level.append(shape)
        return shapes_of_level

    @property
    def max_level(self) -> int:
        """
        Get the maximum level among all shapes in the list.

        Returns:
            int: The maximum level, or 0 if the list is empty.
        """
        if not self:
            return 0
        return max(shape.level for shape in self)