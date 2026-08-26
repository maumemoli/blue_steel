"""
SplitData holds the split map configuration of a Blue Steel editor and
generates the split shape poses (pose names and area combinations) for the
shapes to split.

This module is Maya-free: all the scene queries happen in the api layer and
are passed to SplitData as plain dictionaries.
"""
from itertools import product

from .. import env

SEPARATOR = env.SEPARATOR
SHAPE_NAME_STR = "<<SHAPE_NAME>>"
NO_SPLIT_GROUP = "NoSplit"


class SplitData(object):
    """
    Pure-Python view of the split maps configuration of a Blue Steel editor.

    It bundles the data that used to be threaded through the split functions
    (split groups, primary to split group associations, split map areas) and
    generates the split shape poses for a shape: the pose names and the split
    map area combination that produces each pose.

    Per-primaries split info and area combinations are cached, since all the
    shapes sharing the same primaries (inbetweens, combos) produce the same
    combinations.
    """

    def __init__(self,
                 split_groups: dict,
                 primary_split_groups: dict,
                 split_map_areas: dict,
                 split_maps_order: list = None,
                 shape_name_area: str = SHAPE_NAME_STR,
                 separator: str = SEPARATOR) -> None:
        """
        Parameters:
            split_groups (dict): {split group name: [split map names]}, with the
                shape name area marking where the shape name goes.
            primary_split_groups (dict): {primary shape name: split group name}.
            split_map_areas (dict): {split map name: [full area weight names]}.
            split_maps_order (list): Display order of the split maps.
            shape_name_area (str): Placeholder marking the shape name position
                inside a split group.
            separator (str): The shape name separator of the editor.
        Example:
            >>> split_data = SplitData(
            ...     split_groups={"LeftRight": ["<<SHAPE_NAME>>", "side"]},
            ...     primary_split_groups={"browUp": "LeftRight"},
            ...     split_map_areas={"side": ["side_L", "side_R"]})
            >>> print(split_data.get_split_group_for_primary("browUp"))
            LeftRight
        """
        self.split_groups = split_groups or {}
        self.primary_split_groups = primary_split_groups or {}
        self.split_map_areas = split_map_areas or {}
        self.split_maps_order = split_maps_order or []
        self.shape_name_area = shape_name_area
        self.separator = separator
        self._shape_split_info_cache = {}
        self._area_combinations_cache = {}

    def get_split_group_for_primary(self, primary: str) -> str:
        """
        Returns the split group assigned to a primary shape.
        Parameters:
            primary (str): The name of the primary shape.
        Returns:
            str: The name of the split group assigned to the primary.
        Example:
            >>> split_data = SplitData(
            ...     split_groups={"LeftRight": ["<<SHAPE_NAME>>", "side"]},
            ...     primary_split_groups={"browUp": "LeftRight"},
            >>> print(split_data.get_split_group_for_primary("browUp"))
            LeftRight
        """
        return self.primary_split_groups[primary]

    def get_split_maps_for_primary(self, primary: str) -> list:
        """
        Returns the split maps of the split group assigned to a primary shape.
        Parameters:
            primary (str): The name of the primary shape.
        Returns:
            list: The split map names of the primary split group, [] when the
                primary is not split.
        Example:
            >>> split_data = SplitData(
            ...     split_groups={"LeftRight": ["<<SHAPE_NAME>>", "side"]},
            ...     primary_split_groups={"browUp": "LeftRight"},
            ...     split_map_areas={"side": ["side_L", "side_R"]})
            >>> print(split_data.get_split_maps_for_primary("browUp"))
            ['<<SHAPE_NAME>>', 'side']
        """
        split_group = self.get_split_group_for_primary(primary)
        return self.split_groups.get(split_group, [])

    def clear_caches(self) -> None:
        """
        Clears the split info and area combinations caches.
        Returns:
            None
        Example:
            >>> split_data = SplitData({}, {}, {})
            >>> split_data.clear_caches()
        """
        self._shape_split_info_cache = {}
        self._area_combinations_cache = {}

    def _get_shape_split_info(self, shape) -> tuple:
        """
        Returns the split info of a shape as
        (shape split maps, primary positions, split parent maps).
        Cached per primaries tuple since every shape sharing the same
        primaries (inbetweens, combos) produces the same split info.
        """
        primaries_key = tuple(shape.primaries)
        cached_info = self._shape_split_info_cache.get(primaries_key)
        if cached_info is not None:
            return cached_info

        shape_split_maps = []
        seen_split_maps = set()
        primary_positions = []
        split_parent_maps = {}
        for primary in shape.primaries:
            split_group = self.get_split_group_for_primary(primary)
            split_maps = self.split_groups.get(split_group, [])
            split_parent_maps[primary] = split_maps
            if split_group == NO_SPLIT_GROUP:
                primary_positions.append(None)
                continue
            for i, split_map in enumerate(split_maps):
                if split_map == self.shape_name_area:
                    # the area position marks where the shape name goes
                    primary_positions.append(i)
                    continue
                if split_map not in seen_split_maps:
                    shape_split_maps.append(split_map)
                    seen_split_maps.add(split_map)

        split_info = (shape_split_maps, primary_positions, split_parent_maps)
        self._shape_split_info_cache[primaries_key] = split_info
        return split_info

    def _get_area_combinations(self, shape_split_maps: list) -> list:
        """
        Returns every area combination of the given split maps.
        Cached per split maps tuple to avoid recomputing the cartesian
        product for shapes sharing the same primaries.
        """
        cache_key = tuple(shape_split_maps)
        combinations = self._area_combinations_cache.get(cache_key)
        if combinations is None:
            split_areas = [self.split_map_areas[split_map] for split_map in shape_split_maps]
            combinations = list(product(*split_areas)) if split_areas else []
            self._area_combinations_cache[cache_key] = combinations
        return combinations

    def get_split_shape_poses(self, shape) -> dict:
        """
        Returns the split shape poses of a shape.
        Parameters:
            shape (Shape): The shape to get the split poses for.
        Returns:
            dict: {split pose name: area combination} for the given shape.
        Example:
            >>> from types import SimpleNamespace
            >>> class FakeParent(str):
            ...     str_values = ["100"]
            ...     primaries = ["browUp"]
            >>> shape = SimpleNamespace(primaries=["browUp"], parents=[FakeParent("browUp")])
            >>> split_data = SplitData(
            ...     split_groups={"LeftRight": ["<<SHAPE_NAME>>", "side"]},
            ...     primary_split_groups={"browUp": "LeftRight"},
            ...     split_map_areas={"side": ["side_L", "side_R"]})
            >>> poses = split_data.get_split_shape_poses(shape)
            >>> print(sorted(poses))
            ['browUpL', 'browUpR']
        """
        split_shape_poses = {}
        if shape is None:
            return split_shape_poses
        shape_split_maps, primary_positions, split_parent_maps = self._get_shape_split_info(shape)
        for combo_areas in self._get_area_combinations(shape_split_maps):
            pose_name = self.generate_name_for_split_shape_pose(shape,
                                                                combo_areas,
                                                                split_parent_maps=split_parent_maps,
                                                                primary_positions=primary_positions)
            split_shape_poses[pose_name] = combo_areas
        return split_shape_poses

    def generate_name_for_split_shape_pose(self,
                                           shape,
                                           areas: list,
                                           split_parent_maps: dict = None,
                                           primary_positions: list = None) -> str:
        """
        Generates the pose name of a shape for the given area combination.

        The split areas are inserted in each primary name at the position of
        the shape name area of its split group. When the area does not come
        first, the primary is capitalized since it becomes a suffix.
        Parameters:
            shape (Shape): The shape to generate the pose name for.
            areas (list): The area combination of the split pose.
            split_parent_maps (dict): {primary: split maps of its split group}.
                Computed from the shape when None.
            primary_positions (list): Position of the shape name area in the
                split group of each primary. Computed from the shape when None.
        Returns:
            str: The generated split pose name.
        Example:
            >>> from types import SimpleNamespace
            >>> class FakeParent(str):
            ...     str_values = ["100"]
            ...     primaries = ["browUp"]
            >>> shape = SimpleNamespace(primaries=["browUp"], parents=[FakeParent("browUp")])
            >>> split_data = SplitData(
            ...     split_groups={"LeftRight": ["<<SHAPE_NAME>>", "side"]},
            ...     primary_split_groups={"browUp": "LeftRight"},
            ...     split_map_areas={"side": ["side_L", "side_R"]})
            >>> print(split_data.generate_name_for_split_shape_pose(shape, ["side_L"]))
            browUpL
        """
        if split_parent_maps is None or primary_positions is None:
            _, primary_positions, split_parent_maps = self._get_shape_split_info(shape)

        split_map_area_by_map = {}
        for area in areas:
            split_map_name, split_map_area = area.rsplit("_", 1)
            split_map_area_by_map[split_map_name] = split_map_area

        name_parts = []
        for primary, parent, primary_position in zip(shape.primaries, shape.parents, primary_positions):
            split_primary = primary if primary_position == 0 else primary[0].upper() + primary[1:]
            parent_value = parent.str_values[0]
            split_maps = split_parent_maps.get(primary)
            if not split_maps:
                # this primary is not split, keep the parent name as is
                name_parts.append(parent)
                continue
            primary_split_areas = []
            for split_map in split_maps:
                split_map_area = split_map_area_by_map.get(split_map)
                if split_map_area is not None:
                    primary_split_areas.append(split_map_area)
            # inserting the primary name at the position of the shape name area
            primary_split_areas.insert(primary_position, split_primary)
            split_primary = "".join(primary_split_areas)
            if parent_value != "100":
                split_primary = f"{split_primary}{parent_value}"
            name_parts.append(split_primary)
        return self.separator.join(name_parts)
