from blue_steel.logic.shape import Shape, PrimaryShape, ComboShape, ComboInbetweenShape, InbetweenShape
from blue_steel.logic.splitMap import SplitMap
import blue_steel.logic.utilities as util
import blue_steel.env as env
SEPARATOR = env.SEPARATOR


class Network(object):
    def __init__(self, name):
        """
        This class is used to create a network of shapes
        """
        self.name = name
        self.shapes = list()
        self.split_maps = list()

    def add_split_map(self, split_map: SplitMap):
        """
        Add a split map to the network
        """
        if split_map.name not in self.split_map_names:
            self.split_maps.append(split_map)

    def get_split_map(self, split_map_name: str):
        """
        Returns the split map
        """
        for split_map in self.split_maps:
            if split_map.name == split_map_name:
                return split_map
        return None

    def get_shape(self, shape_name: str):
        """
        Returns the split map
        """
        if shape_name in self.shapes:
            split_maps = list()
            # assuming this is a primary
            primaries = [shape_name]
            if not util.is_primary(shape_name):
                primaries = util.get_primaries(shape_name)
            for primary in primaries:
                for split_map in self.split_maps:
                    if primary in split_map.shapes:
                        if split_map not in split_maps:
                            split_maps.append(split_map)
            return Shape.create(shape_name, split_maps)
        else:
            return None

    @property
    def split_map_names(self):
        """
        Returns the split map names
        """
        split_map_names = list()
        for split_map in self.split_maps:
            split_map_names.append(split_map.name)

        return split_map_names

    def __get_type(self, shape_type: str):
        """
        Returns a list of shapes of the given type
        """
        shape_list = list()
        for shape in self.shapes:
            shape = self.get_shape(shape)
            if shape.type == shape_type:
                shape_list.append(shape)
        return shape_list

    @property
    def primaries(self):
        """
        Returns the primary shapes
        """
        return self.__get_type("PrimaryShape")

    @property
    def inbetweens(self):
        """
        Returns the inbetween shapes
        """
        return self.__get_type("InbetweenShape")

    @property
    def combo(self):
        """
        Returns the combo shapes
        """
        return self.__get_type("ComboShape")

    @property
    def combo_inbetween(self):
        """
        Returns the combo inbetween shapes
        """
        return self.__get_type("ComboInbetweenShape")

    def add_shape(self, shape_name: str, split_map_name=None):
        """
        Add a shape to the network
        """
        if Shape.is_primary(shape_name):
            if not split_map_name:
                raise NameError(f"must provide a split map name for {shape_name} Primary shape.")
            self._add_primary(shape_name, split_map_name)
        elif Shape.is_inbetween(shape_name):
            self._add_inbetween(shape_name)
        elif Shape.is_combo(shape_name) or Shape.is_combo_inbetween(shape_name):
            self._add_combo(shape_name)

    def _add_primary(self, shape_name, split_map_name):
        if split_map_name in self.split_map_names:
            split_map = self.get_split_map(split_map_name)
            if shape_name not in split_map.shapes:
                print(f"{shape_name} not in {split_map.name} split map. Adding it.")
                split_map.add_shape(shape_name)
            else:
                print(f"{shape_name} already in {split_map.name} split map.")
            self.shapes.append(shape_name)

        else:
            raise NameError(f"Split map {split_map_name} is missing.")

    def _add_inbetween(self, shape_name):
        primary = self.get_shape(util.get_primaries(shape_name)[0])
        if not primary:
            raise NameError(f"\"{shape_name}\" can't be added because its parent shape \""
                            f"{util.get_primaries(shape_name)[0]}\" is missing.")
        self.shapes.append(shape_name)

    def _add_combo(self, shape_name):
        parents = util.get_parents(shape_name)
        for parent_name in parents:
            shape = self.get_shape(parent_name)
            if not shape:
                raise NameError(f"\"{shape_name}\" can't be added because its parent shape \""
                                f"{parent_name}\" is missing.")
        self.shapes.append(shape_name)

    def __repr__(self):
        return self.name

    def __str__(self):
        return self.name