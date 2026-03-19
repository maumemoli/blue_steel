from turtle import shape
from .shape import Shape, PrimaryShape, ComboShape, ComboInbetweenShape, InbetweenShape, InvalidShape
from .shapeList import ShapeList
from ..api.blendshape import Blendshape, Weight
from .splitMap import SplitMap
from . import utilities
from .. import env
from itertools import product

SEPARATOR = env.SEPARATOR


class Network(object):
    def __init__(self, shapes_list = None, separator=SEPARATOR):
        """
        This manages a network of shapes associated with a blendshape node.
        :param shapes_list: optional ShapeList to initialize the network with
        :param separator: the separator used in the shape names
        
        """
        self.separator = separator
        self.name = "Unnamed_Network"
        # list of Shapes
        self._shapes = ShapeList([], self.separator)
        self.split_maps = [SplitMap.create_default()]
        self.muted_shapes = set()
        # this is a dictionary that holds the split maps associated with each shape
        self.shape_split_maps_association = dict()
        if isinstance(shapes_list, ShapeList):
            if shapes_list.separator != self.separator:
                raise ValueError("The separator of the shapes list does not match the network separator.")
            for shape in shapes_list.sort_for_insertion():
                shape = self.create_shape(shape)
                self.add_shape(shape)


    def __eq__(self, value):
        return self._shapes == value

    def __iter__(self):
        return iter(self._shapes)

    def __contains__(self, item):
        return item in self._shapes

    def __len__(self):
        return len(self._shapes)

    def __getitem__(self, index):
        return self._shapes[index]

    def get_split_map(self, name: str):
        """
        Returns the split map by name
        :param name: the name of the split map
        :return: the split map
        """
        for split_map in self.split_maps:
            if split_map.name == name:
                return split_map
        return None

    
    def get_weight_muted_state(self, weight: Weight) -> bool:
        """
        Returns the muted state of the weight in the blendshape
        :param weight: the weight to check
        :return: True if the weight is muted, False otherwise
        """
        if self._blendshape is None:
            raise ValueError("Blendshape is not set for the network.")
        parent_dir = self._blendshape.get_weight_parent_directory(weight)
        return not bool(self._blendshape.get_target_dir_weight_value(parent_dir))


    def set_weight_muted_state(self, weight: Weight, state: bool):
        """
        Sets the muted state of the weight in the blendshape
        :param weight: the weight to set
        :param state: True to mute, False to unmute
        """
        if self._blendshape is None:
            raise ValueError("Blendshape is not set for the network.")
        parent_target_dir = self._blendshape.get_weight_parent_directory(weight)
        self._blendshape.set_target_dir_visibility(parent_target_dir, not state)


    def clear_all_shapes(self):
        """
        Clears all shapes from the network
        """
        self._shapes.clear()

    def get_shape_by_weight_id(self, weight_id: int)-> Shape:
        """
        Returns the shape by weight id
        :param weight_id: the weight id of the shape
        :return: the shape
        """
        return self._shapes.get_shape_by_weight_id(weight_id)

    def get_shape(self, shape_name: str)-> Shape:
        """
        Returns the shape by name
        :param shape_name: the name of the shape
        :return: the shape
        """
        return self._shapes.get_shape(shape_name)

    def remove_shape(self, shape_name: str):
        """
        Remove a shape from the network
        :param shape_name: the name of the shape to remove
        """
        shape = self.get_shape(shape_name)
        if shape is None:
            print(f"Shape '{shape_name}' not found in the network. Cannot remove.")
            return
        # let's check if the shape has children
        if shape.type in ["PrimaryShape", "InbetweenShape"] and self._shapes.get_affected(shape_name):
            raise ValueError(f"Can't remove shape \"{shape_name}\" because it has children:"
                              f" {', '.join(self._shapes.get_affected(shape_name))}")
        self._shapes.remove(shape_name)
        if shape_name in self.shape_split_maps_association:
            del self.shape_split_maps_association[shape_name]

    def get_related_shapes(self, shape_names: list)-> ShapeList:
        """
        Returns a list of shapes that are related to the given shapes
        :param shape_names: the names of the shapes to get the related shapes for
        :return: a list of shapes that are related to the given shapes
        """
        related_shapes = ShapeList([], self.separator)
        for shape_name in shape_names:
            shape = self.get_shape(shape_name)
            if shape is None:
                continue
            related_shapes.append(shape)
            # get descendants
            descendants = self._shapes.get_related_shapes_downstream(shape_name)
            if len(shape_names) == 1:
                related_shapes.extend(descendants)
                return related_shapes.sort_for_display()
            for descendant in descendants:
                descendant_primaries = descendant.primaries
                if len(shape_names) <= len(descendant_primaries):
                    if all(primary in descendant_primaries for primary in shape_names):
                        related_shapes.append(descendant)
                else:
                    if all(primary in shape_names for primary in descendant_primaries):
                        related_shapes.append(descendant)

        return related_shapes.sort_for_display()
    
    def list_possible_combo_shapes(self,shapes_list, max_combo_size: int = 5) -> set:
        """
        Returns a list of possible combo shapes that can be created from the current primary shapes and inbetween shapes
        :param max_combo_size: optional maximum number of shapes to combine (e.g., 2 for pairs only, 3 for up to triplets)
        :return: a list of possible combo shapes
        """
        # we need to include the inbetween
        shapes = set()
        for shape in shapes_list:
            shape = self.get_shape(shape)
            if shape is not None:
                for parent in shape.parents:
                    if shape.type == "PrimaryShape":
                        inbetweens = self.get_inbetween_shapes_for_primary(shape)
                        for inbetween in inbetweens:
                            shapes.add(inbetween)
                    else:
                        shapes.add(parent)
                # we need to include the inbetween shapes associated with the primary shapes
        possible_shapes = utilities.list_possible_combo_shapes( shapes_list=shapes,
                                                                separator=self.separator,
                                                                max_combo_size = max_combo_size)
        return possible_shapes


    def add_split_map(self, split_map: SplitMap):
        """
        Add a split map to the network
        """
        if split_map.name not in self.split_map_names:
            self.split_maps.append(split_map)

    def add_split_map_to_shape(self, shape_name: str, split_map: SplitMap):
        """
        Add a split map to a shape
        :param shape_name: the name of the shape to add
        :param split_map: the split maps to associate with the shape
        """
        if not utilities.is_primary(shape_name, self.separator):
            raise NameError(f"\"{shape_name}\" is not a primary shape, split maps can only"
                            "be associated with primary shapes.")
        if shape_name not in self._shapes:
            raise NameError(f"Shape \"{shape_name}\" is not defined in the network.")
        shape_split_maps = self.shape_split_maps_association.get(shape_name, [])
        if split_map.name not in [s for s in shape_split_maps]:
            shape_split_maps.append(split_map)
        self.shape_split_maps_association[shape_name] = shape_split_maps

    def get_shapes_by_level(self, level: int):
        """
        Returns a list of shapes by their level
        """
        return self._shapes.get_by_level(level)

    def get_related_shapes_downstream(self, shape_name: str) -> ShapeList:
        """
        Returns a list of shapes that are descendants of the given shape
        :param shape_name: the name of the shape to get the descendants of
        :return: a list of shapes that are descendants of the given shape
        """
        return self._shapes.get_related_shapes_downstream(shape_name)

    def get_related_shapes_upstream(self, shape_name: str) -> ShapeList:
        """
        Returns a list of shapes that are ancestors of the given shape
        :param shape_name: the name of the shape to get the ancestors of
        :return: a list of shapes that are ancestors of the given shape
        """
        return self._shapes.get_related_shapes_upstream(shape_name)

    def get_inbetween_shapes_for_primary(self, primary_shape: str) -> ShapeList:
        """
        Returns a list of inbetween shapes for the given primary shape
        :param primary_shape: the name of the primary shape to get the inbetween shapes for
        :return: a list of inbetween shapes for the given primary shape
        """
        return self._shapes.get_inbetween_shapes_for_primary(primary_shape)

    def get_adjacent_inbetweens(self, shape: str) -> ShapeList:
        """
        Get the inbetween siblings of a given inbetween shape.
        :param shape: the inbetween shape to get the siblings for
        :return: a list of inbetween shapes that are siblings of the given inbetween shape
        """
        return self._shapes.get_adjacent_inbetweens(shape)

    @property
    def split_map_names(self):
        """
        Returns the split map names
        """
        split_map_names = list()
        for split_map in self.split_maps:
            split_map_names.append(split_map.name)

        return split_map_names

    def create_shape(self, shape_name: str) -> Shape:
        """
        Create a shape find the category where it belongs and add it to the network
        :param shape_name: the name of the shape to create
        :return: the created shape
        """
        missing_elements = self._shapes.get_missing_elements(shape_name)
        
        if missing_elements:
            # print(f"Missing elements for shape '{shape_name}': {missing_elements}")
            shape = InvalidShape(shape_name, self.separator, missing_elements)

        else:
            shape = Shape.create(shape_name, self.separator)
        return shape

    def add_shape(self, shape: Shape):
        """
        Add a shape to the network
        :param shape: the shape to add
        """
        self._shapes.append(shape)
        # print(f"Shape '{shape}' added successfully. Total shapes in network: {len(self._shapes)}")
        # print(f"Current shapes in network: {self._shapes}")


    def get_primary_shapes(self) -> ShapeList:
        """
        Returns a list of primary shapes in the network
        """
        return self._shapes.primary_shapes

    def get_inbetween_shapes(self) -> ShapeList:
        """
        Returns a list of inbetween shapes in the network
        """
        return self._shapes.inbetween_shapes

    def get_combo_shapes(self) -> ShapeList:
        """
        Returns a list of combo shapes in the network
        """
        return self._shapes.combo_shapes

    def get_combo_inbetween_shapes(self) -> ShapeList:
        """
        Returns a list of combo inbetween shapes in the network
        """
        return self._shapes.combo_inbetween_shapes
    
    def get_invalid_shapes(self) -> ShapeList:
        """
        Returns a list of invalid shapes in the network
        """
        return self._shapes.invalid_shapes

    def split_shape(self, shape: Shape):
        """
        Generate the split names for the given shape according to the split maps associated with it.
        Example:
        for shape "a" and split maps [{"LEFT": "L", "RIGHT": "R"}], the split names will be:
        ["aL", "aR"]
        for shape "b" and split maps [{"TOP": "T", "BOTTOM": "B"}, {"LEFT": "L", "RIGHT": "R"}], the split names will be:
        ["bTL", "bTR", "bBL", "bBR"]
        for a combo shape "a_b" the split maps will follow the primary shapes,
        so if "a" has split maps [{"LEFT": "L", "RIGHT": "R"}] and
        "b" has split maps [{"TOP": "T", "BOTTOM": "B"},{"LEFT": "L", "RIGHT": "R"}], the split names will be:
        ["aL_bTL", "aL_bBL", "aR_bTR", "aR_bBR",]

        :param shape: the shape to split
        :return: a list of split names
        """
        # doing the primary shapes first
        if not isinstance(shape, PrimaryShape):
            return []

        split_names = [shape]
        for split_map in self.shape_split_maps_association[shape]:
            split_names = [
                f"{split_name}{short_suffix}"
                for split_name in split_names
                for long_suffix, short_suffix in split_map.suffices.items()
            ]
        return split_names

    def _split_base_level_shape(self, shape: Shape)-> list:
        """
        Generate the split names for the given base level shape according to the split maps associated with it.
        :param shape: the shape to split
        :return: a list of split names
        """
        value = ""
        shape_name = shape
        if isinstance(shape, InbetweenShape):
            value = shape[-2:]
            shape_name = shape[:-2]
        split_names = [shape_name]
        for split_map in self.shape_split_maps_association[shape_name]:
            suffices = list(split_map.suffices.values())
            split_names = [f"{split_name}{s}{value}" for split_name in split_names for s in suffices]
        return split_names

    def info(self):
        """
        Print the network information
        """
        print(f"Network Name: {self.name}")
        print(f"Number of Shapes:       {len(self._shapes)}")
        print(f"Primary Shapes:         {len(self.get_primary_shapes())}")
        print(f"Inbetween Shapes:       {len(self.get_inbetween_shapes())}")
        print(f"Combo Shapes:           {len(self.get_combo_shapes())}")
        print(f"Combo Inbetween Shapes: {len(self.get_combo_inbetween_shapes())}")
        print(f"Invalid Shapes:         {len(self.get_invalid_shapes())}")
        print(f"Number of Split Maps: {len(self.split_maps)}")
        print(f"Split Maps:")
        for split_map in self.split_maps:
            print(f"  - {split_map}")


    def __repr__(self):
        return f"Shapes Network: {self.name}, Number of Shapes: {len(self._shapes)}, Number of Split Maps: {len(self.split_maps)}"

    def __str__(self):
        return self.name