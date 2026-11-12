"""
Split data of a Blue Steel editor.

:class:`SplitData` stores, for every shape to split, the split shapes it
produces, the split map areas used by each split shape and the unique split
weights (area combinations) needed to perform the split.

:func:`build_split_data` generates that data from plain dictionaries and
:func:`compute_split_weight_values` computes the weight map of a split
weight. This module is Maya-free: all the scene queries happen in the api
layer (``BlueSteelEditor.generate_split_data`` and
``BlueSteelEditor.create_split_weight_head``).

Linked split maps:
    Two split maps used by the same shape are linked when the sets of their
    area endings are equal (side {L, R} and mouthSide {L, R}), including two
    split maps of the same split group. Linked split maps only produce their
    matching areas (L with L, R with R: no contralateral split shapes) and
    their weight is the per-vertex average of the matching areas, so equal
    values are kept and the split shapes still sum to the original shape.
    The other split maps produce every area combination and are multiplied.
"""
from dataclasses import dataclass, field
from itertools import product

import numpy as np

from .. import env

SEPARATOR = env.ENVIRONMENT.SEPARATOR
SHAPE_NAME_STR = env.ENVIRONMENT.SHAPE_NAME_STR
NO_SPLIT_GROUP = "NoSplit"
# split weight used by the shapes that do not need any splitting (all weights set to 1)
NO_SPLIT_WEIGHT = "noSplit"
SPLIT_AREAS_KEY = "splitAreas"
SPLIT_WEIGHT_KEY = "splitWeight"


def make_split_weight_name(areas: list) -> str:
    """
    Returns the split weight name of a list of split areas: the alphabetically
    sorted areas joined with "_".
    Parameters:
        areas (list): The split areas (full split map weight names).
    Returns:
        str: The split weight name, NO_SPLIT_WEIGHT when there are no areas.
    Example:
        >>> make_split_weight_name(["topBottom_T", "side_L"])
        'side_L_topBottom_T'
        >>> make_split_weight_name([])
        'noSplit'
    """
    if not areas:
        return NO_SPLIT_WEIGHT
    return "_".join(sorted(areas))


@dataclass
class SplitData:
    """
    Stores all the data related to the shapes that need to be split.

    Attributes:
        split_shapes (dict): {shape name: [split shape names]}. Ordered for
            insertion (primaries first). An empty list means the shape does
            not need any splitting.
        split_shapes_areas (dict): {split shape name: {"splitAreas": [areas],
            "splitWeight": split weight name}}.
        split_weights (dict): {split weight name: [areas]}. Always contains
            NO_SPLIT_WEIGHT, mapped to an empty list of areas. Linked split
            maps only contribute matching areas (side_L with mouthSide_L).
    Example:
        >>> data = SplitData()
        >>> data.add_split_shape("browUp", "browUpL", ["side_L"])
        >>> data.split_shapes
        {'browUp': ['browUpL']}
        >>> data.get_split_weight("browUpL")
        'side_L'
    """
    split_shapes: dict = field(default_factory=dict)
    split_shapes_areas: dict = field(default_factory=dict)
    split_weights: dict = field(default_factory=lambda: {NO_SPLIT_WEIGHT: []})

    @property
    def shapes(self) -> list:
        """ The shapes to split, in insertion order. """
        return list(self.split_shapes)

    def add_shape(self, shape: str) -> list:
        """
        Registers a shape to split, with no split shapes by default.
        Parameters:
            shape (str): The name of the shape.
        Returns:
            list: The split shapes list of the shape.
        """
        return self.split_shapes.setdefault(str(shape), [])

    def add_split_shape(self, shape: str, split_shape: str, areas: list) -> str:
        """
        Adds a split shape to a shape, storing its split areas and split weight.
        Parameters:
            shape (str): The name of the shape being split.
            split_shape (str): The name of the split shape.
            areas (list): The split areas used to generate the split shape.
        Returns:
            str: The split weight name of the split shape.
        """
        areas = list(areas)
        split_weight = make_split_weight_name(areas)
        split_shapes = self.add_shape(shape)
        if split_shape not in split_shapes:
            split_shapes.append(split_shape)
        self.split_shapes_areas[split_shape] = {SPLIT_AREAS_KEY: areas,
                                                SPLIT_WEIGHT_KEY: split_weight}
        self.split_weights.setdefault(split_weight, sorted(areas))
        return split_weight

    def get_split_weight(self, split_shape: str) -> str:
        """ Returns the split weight name of a split shape. """
        return self.split_shapes_areas[split_shape][SPLIT_WEIGHT_KEY]

    def get_split_areas(self, split_shape: str) -> list:
        """ Returns the split areas of a split shape. """
        return self.split_shapes_areas[split_shape][SPLIT_AREAS_KEY]

    def get_shape_split_weights(self, shape: str) -> list:
        """
        Returns the split weights needed by the split shapes of a shape,
        [NO_SPLIT_WEIGHT] when the shape does not need any splitting.
        """
        split_shapes = self.split_shapes.get(str(shape), [])
        if not split_shapes:
            return [NO_SPLIT_WEIGHT]
        split_weights = []
        for split_shape in split_shapes:
            split_weight = self.get_split_weight(split_shape)
            if split_weight not in split_weights:
                split_weights.append(split_weight)
        return split_weights


def _get_area_suffix(split_map: str, area: str) -> str:
    """ Returns the area suffix of a full split map weight name ("side_L" -> "L"). """
    prefix = f"{split_map}_"
    if area.startswith(prefix):
        return area[len(prefix):]
    return area.rsplit("_", 1)[-1]


def _get_split_map_endings(split_map: str, split_map_areas: dict) -> frozenset:
    """ Returns the set of area endings of a split map ({"L", "R"} for side_L, side_R). """
    return frozenset(_get_area_suffix(split_map, area) for area in split_map_areas.get(split_map, []))


def _group_linked_split_maps(split_maps: list, split_map_areas: dict) -> list:
    """
    Groups the linked split maps together.

    Two split maps are linked when the sets of their area endings are equal
    (side {L, R} and mouthSide {L, R}). The order of the split maps is kept,
    each group takes the position of its first split map. A split map without
    areas stays on its own.
    Parameters:
        split_maps (list): The split map names.
        split_map_areas (dict): {split map name: [full area weight names]}.
    Returns:
        list: A list of groups, each group being a list of split map names.
    Example:
        >>> _group_linked_split_maps(["side", "tb", "mouthSide"],
        ...                          {"side": ["side_L", "side_R"],
        ...                           "tb": ["tb_T", "tb_B"],
        ...                           "mouthSide": ["mouthSide_L", "mouthSide_R"]})
        [['side', 'mouthSide'], ['tb']]
    """
    groups = []
    group_by_endings = {}
    for split_map in split_maps:
        endings = _get_split_map_endings(split_map, split_map_areas)
        if not endings:
            groups.append([split_map])
            continue
        group = group_by_endings.get(endings)
        if group is None:
            group = [split_map]
            group_by_endings[endings] = group
            groups.append(group)
        else:
            group.append(split_map)
    return groups


def _get_split_group_options(group: list, split_map_areas: dict) -> list:
    """
    Returns the area options of a group of linked split maps: one tuple of
    full area names (one per split map of the group) for each option.
        - single split map: one option per area.
        - linked split maps: one option per common ending, matching areas only
          ("L" -> ("side_L", "mouthSide_L")), in the area order of the first map.
    """
    first_map = group[0]
    if len(group) == 1:
        return [(area,) for area in split_map_areas.get(first_map, [])]
    area_by_ending = {
        split_map: {_get_area_suffix(split_map, area): area for area in split_map_areas.get(split_map, [])}
        for split_map in group
    }
    options = []
    for area in split_map_areas.get(first_map, []):
        ending = _get_area_suffix(first_map, area)
        options.append(tuple(area_by_ending[split_map][ending] for split_map in group))
    return options


def compute_split_weight_values(areas: list,
                                split_map_areas: dict,
                                area_values: dict,
                                vertex_count: int = None) -> np.ndarray:
    """
    Computes the per-vertex weight map of a split weight.

    The split maps of the areas are grouped into linked groups. Each group
    gives a factor: the area values for a single split map, the per-vertex
    average of the matching areas for linked split maps. The weight map is
    the product of the factors. Since every split map is normalized, the
    split weights of a shape still sum to 1 at every vertex.
    Parameters:
        areas (list): The areas of the split weight.
        split_map_areas (dict): {split map name: [full area weight names]}.
        area_values (dict): {full area weight name: per-vertex values}.
        vertex_count (int): The vertex count, used when there are no areas
            (no split weight, all values set to 1).
    Returns:
        np.ndarray: The per-vertex weight values.
    Example:
        >>> compute_split_weight_values(["side_L", "mouthSide_L"],
        ...                             {"side": ["side_L", "side_R"],
        ...                              "mouthSide": ["mouthSide_L", "mouthSide_R"]},
        ...                             {"side_L": [0.7], "mouthSide_L": [0.5]})
        array([0.6])
    """
    if not areas:
        if vertex_count is None:
            raise ValueError("A vertex count is needed to compute a split weight without areas.")
        return np.ones(vertex_count, dtype=float)
    map_by_area = {area: split_map for split_map, map_areas in split_map_areas.items() for area in map_areas}
    area_by_map = {}
    for area in areas:
        split_map = map_by_area.get(area)
        if split_map is None:
            raise ValueError(f"Split area '{area}' does not belong to any split map.")
        if area not in area_values:
            raise ValueError(f"Split area '{area}' has no weight values.")
        area_by_map[split_map] = area
    values = None
    for group in _group_linked_split_maps(list(area_by_map), split_map_areas):
        factor = np.mean([np.asarray(area_values[area_by_map[split_map]], dtype=float)
                          for split_map in group], axis=0)
        values = factor if values is None else values * factor
    return values


def _get_shape_split_layout(primaries: list,
                            primary_split_groups: dict,
                            split_groups: dict,
                            shape_name_area: str) -> tuple:
    """
    Returns the split layout of a shape from its primaries as
    (shape split maps, primary positions, primary split maps).
        - shape split maps: the unique split maps used by the shape, in order.
          A split map shared by several primaries is used once.
        - primary positions: position of the shape name area in the split
          group of each primary.
        - primary split maps: {primary: split maps of its split group}, empty
          for the primaries that are not split.
    """
    shape_split_maps = []
    primary_positions = []
    primary_split_maps = {}
    for primary in primaries:
        split_group = primary_split_groups.get(primary, NO_SPLIT_GROUP)
        split_maps = [] if split_group == NO_SPLIT_GROUP else list(split_groups.get(split_group, []))
        area_maps = [split_map for split_map in split_maps if split_map != shape_name_area]
        if not area_maps:
            # nothing to split for this primary
            primary_split_maps[primary] = []
            primary_positions.append(0)
            continue
        primary_split_maps[primary] = split_maps
        primary_positions.append(split_maps.index(shape_name_area) if shape_name_area in split_maps else 0)
        for split_map in area_maps:
            if split_map not in shape_split_maps:
                shape_split_maps.append(split_map)
    return shape_split_maps, primary_positions, primary_split_maps


def generate_split_shape_name(shape,
                              area_by_split_map: dict,
                              primary_positions: list,
                              primary_split_maps: dict,
                              separator: str = SEPARATOR) -> str:
    """
    Generates the name of a split shape.

    The area suffixes are inserted in each primary name at the position of
    the shape name area of its split group. When the shape name does not come
    first, the primary is capitalized since it becomes a suffix. The
    inbetween value of the parent is appended. Parents whose primary is not
    split are kept as they are.
    Parameters:
        shape (Shape): The shape being split.
        area_by_split_map (dict): {split map: full area name} of the split shape.
        primary_positions (list): Position of the shape name area for each primary.
        primary_split_maps (dict): {primary: split maps of its split group}.
        separator (str): The shape name separator.
    Returns:
        str: The split shape name.
    Example:
        >>> # browUp split with ["<<SHAPE_NAME>>", "side"] and area "side_L"
        >>> # -> "browUpL"
    """
    name_parts = []
    for primary, parent, primary_position in zip(shape.primaries, shape.parents, primary_positions):
        split_maps = primary_split_maps.get(primary)
        if not split_maps:
            # this primary is not split, keep the parent name as is
            name_parts.append(str(parent))
            continue
        split_primary = primary if primary_position == 0 else primary[0].upper() + primary[1:]
        name_tokens = []
        for split_map in split_maps:
            area = area_by_split_map.get(split_map)
            if area is not None:
                name_tokens.append(_get_area_suffix(split_map, area))
        # inserting the primary name at the position of the shape name area
        name_tokens.insert(primary_position, split_primary)
        split_parent = "".join(name_tokens)
        parent_value = parent.str_values[0]
        if parent_value != "100":
            split_parent = f"{split_parent}{parent_value}"
        name_parts.append(split_parent)
    return separator.join(name_parts)


def build_split_data(shapes: list,
                     primary_split_groups: dict,
                     split_groups: dict,
                     split_map_areas: dict,
                     separator: str = SEPARATOR,
                     shape_name_area: str = SHAPE_NAME_STR) -> SplitData:
    """
    Builds the split data of a list of shapes.

    Every area combination of the split maps of a shape produces a split
    shape, except for linked split maps (same set of area endings) which only
    produce their matching areas: side × mouthSide gives browUpL_lipPuckerL
    and browUpR_lipPuckerR only.
    Parameters:
        shapes (list): The shapes to split (Shape objects), sorted for insertion.
        primary_split_groups (dict): {primary name: split group name}.
        split_groups (dict): {split group name: [split map names]}, with the
            shape name area marking where the shape name goes.
        split_map_areas (dict): {split map name: [full area weight names]}.
        separator (str): The shape name separator.
        shape_name_area (str): Placeholder marking the shape name position.
    Returns:
        SplitData: The split data of the shapes.
    Example:
        >>> data = build_split_data(shapes=[browUp],
        ...                         primary_split_groups={"browUp": "LeftRight"},
        ...                         split_groups={"LeftRight": ["<<SHAPE_NAME>>", "side"]},
        ...                         split_map_areas={"side": ["side_L", "side_R"]})
        >>> data.split_shapes
        {'browUp': ['browUpL', 'browUpR']}
    """
    split_data = SplitData()
    # all the shapes sharing the same primaries share the same layout and combinations
    layout_cache = {}
    for shape in shapes:
        split_data.add_shape(shape)
        primaries = [str(primary) for primary in shape.primaries]
        cache_key = tuple(primaries)
        cached = layout_cache.get(cache_key)
        if cached is None:
            shape_split_maps, primary_positions, primary_split_maps = _get_shape_split_layout(
                primaries, primary_split_groups, split_groups, shape_name_area)
            # linked split maps only produce their matching areas
            groups = _group_linked_split_maps(shape_split_maps, split_map_areas)
            grouped_split_maps = [split_map for group in groups for split_map in group]
            group_options = [_get_split_group_options(group, split_map_areas) for group in groups]
            combinations = [
                tuple(area for option in options for area in option)
                for options in product(*group_options)
            ] if group_options else []
            cached = (grouped_split_maps, primary_positions, primary_split_maps, combinations)
            layout_cache[cache_key] = cached
        grouped_split_maps, primary_positions, primary_split_maps, combinations = cached
        for combination in combinations:
            area_by_split_map = dict(zip(grouped_split_maps, combination))
            split_shape = generate_split_shape_name(shape,
                                                    area_by_split_map,
                                                    primary_positions,
                                                    primary_split_maps,
                                                    separator=separator)
            split_data.add_split_shape(shape, split_shape, combination)
    return split_data
