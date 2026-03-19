"""
Here go all the utility functions for the logic module.
"""
from .. import env
SEPARATOR = env.SEPARATOR


def combine_lists(lists:list, separator=SEPARATOR):
    """Combine multiple lists into all possible sorted combinations joined by a separator.

    Parameters:
        lists (list): List of lists to combine.
        separator (str): Separator between elements.

    Returns:
        list: Combined and sorted string combinations.

    Example:
        >>> combine_lists([["a", "b"], ["c", "d"]])
        ['a_c', 'a_d', 'b_c', 'b_d']
    """
    if len(lists) == 1:
        return lists[0]
    combined = [
        f"{sublist}{separator}{item}"
        for sublist in lists[0]
        for item in combine_lists(lists[1:])
    ]
    return [separator.join(sorted(x.split(separator))) for x in combined]

# string utilities
def sort_combo_name(combo_name: str, separator=SEPARATOR):
    """Sort the parts of a combo name alphabetically and return the sorted name.

    Parameters:
        combo_name (str): The combo name to sort.
        separator (str): Separator used to split and join the parts.

    Returns:
        str: The combo name with its parts sorted alphabetically.

    Example:
        >>> sort_combo_name("b_a", separator="_")
        'a_b'
    """
    parts = combo_name.split(separator)
    return separator.join(sorted(parts))

def is_primary(shape_name: str, separator=SEPARATOR):
    """Check if the shape is primary.

    Parameters:
        shape_name (str): The name of the shape to check.
        separator (str): Separator used to split the shape name.

    Returns:
        bool: True if the shape is primary, False otherwise.

    Example:
        >>> is_primary("a")
        True
        >>> is_primary("a_b")
        False
    """
    shape_parents = shape_name.split(separator)
    if len(shape_parents) == 1 and not is_inbetween(shape_name, separator):
        return True
    else:
        return False


def is_combo_and_inbetween(shape_name: str, separator=SEPARATOR):
    """Check if the shape is a combo and an inbetween.

    Parameters:
        shape_name (str): The shape name to check.
        separator (str): Separator used to split the shape name.

    Returns:
        tuple: (combo, inbetween) where combo and inbetween are bools.

    Example:
        >>> is_combo_and_inbetween("a_b10")
        (True, True)
    """
    shape_parents = shape_name.split(separator)
    combo = False
    inbetween = False
    if len(shape_parents) > 1:
        combo = True
    for parent in shape_parents:
        # check if the last two characters are digits
        digits_count = len([char for char in parent[-2:] if char.isdigit()])
        if digits_count == 2:
            inbetween = True
    return (combo, inbetween)


def is_combo_inbetween(shape_name: str, separator=SEPARATOR):
    """Check if the shape is a combo inbetween.

    Parameters:
        shape_name (str): The shape name to check.

    Returns:
        bool: True if the shape is a combo inbetween, False otherwise.

    Example:
        >>> is_combo_inbetween("a_b10")
        True
    """
    if is_combo_and_inbetween(shape_name, separator) == (True, True):
        return True
    else:
        return False


def is_inbetween(shape_name: str, separator=SEPARATOR):
    """Check if the shape is inbetween.

    Parameters:
        shape_name (str): The shape name to check.

    Returns:
        bool: True if the shape is inbetween, False otherwise.

    Example:
        >>> is_inbetween("b10")
        True
    """
    if is_combo_and_inbetween(shape_name, separator) == (False, True):
        return True
    else:
        return False


def is_combo(shape_name: str, separator=SEPARATOR):
    """Check if the shape is a combo.

    Parameters:
        shape_name (str): The shape name to check.

    Returns:
        bool: True if the shape is a combo, False otherwise.

    Example:
        >>> is_combo("a_b")
        True
    """
    if is_combo_and_inbetween(shape_name, separator) == (True, False):
        return True
    else:
        return False


def sort_for_insertion(shape_names: list, separator=SEPARATOR):
    """Sort a list of shape names for insertion order.
       The order is: Primaries, Inbetweens, Combos, ComboInbetweens.

    Parameters:
        shape_names (list): List of shape names to sort.
        separator (str): Separator used to split the shape names.
    Returns:
        list: Sorted list of shape names for insertion. 
    Example:
        >>> sort_for_insertion(["b10", "a", "a_b", "b", "a10", "a_b10"])
        ['a', 'b', 'a10', 'b10', 'a_b', 'a_b10']
    """
    def sort_key(name):
        if is_primary(name, separator):
            priority = 0
        elif is_inbetween(name, separator):
            priority = 1
        elif is_combo(name, separator):
            priority = 2
        elif is_combo_inbetween(name, separator):
            priority = 3
        else:
            priority = 4
        
        level = len(name.split(separator))

        sorted_name = sort_combo_name(name, separator)
        return (priority, level, sorted_name)

    return sorted(shape_names, key=sort_key)


def is_valid(shape_name: str, separator=SEPARATOR):
    """Check if the shape name is valid.

    Parameters:
        shape_name (str): The shape name to check.
        separator (str): Separator used to split the shape name.

    Returns:
        bool: True if the shape name is valid, False otherwise.

    Example:
        >>> is_valid("a_b")
        True
    """
    primaries = get_primaries(shape_name, separator)
    parents = get_parents(shape_name, separator)
    
    if len(primaries) != len(shape_name.split(separator)):
        # This means there is an incremental of the same primary shape
        return False

    for parent in parents:
        if not is_inbetween(parent, separator):
            digits = [char for char in parent if char.isdigit()]
            if digits:
                return False
        else:
            primary = get_primaries(parent)[0]
            digits = [char for char in primary if char.isdigit()]
            if digits:
                return False
            if primary in parents:
                return False

    if len(set(parents)) != len(parents):
        return False

    return True

def list_possible_combo_shapes( shapes_list: list, separator=SEPARATOR, max_combo_size: int = 5) -> set:
    """
    Returns a list of possible combo shapes that can be created from the current primary shapes and inbetween shapes
    :param max_combo_size: optional maximum number of shapes to combine (e.g., 2 for pairs only, 3 for up to triplets)
    :return: a list of possible combo shapes
    """

    possible_combos = set()
    from itertools import combinations
    max_r = len(shapes_list) + 1 if max_combo_size is None else min(max_combo_size + 1, len(shapes_list) + 1)
    for r in range(2, max_r):
        combos = combinations(shapes_list, r)
        for combo in combos:
            # Sort the combo alphabetically to ensure consistent ordering (A_B instead of B_A)
            sorted_combo = sorted(combo)
            combo_shape_name = separator.join(sorted_combo)
            if is_valid(combo_shape_name, separator) is False:
                continue
            possible_combos.add(combo_shape_name)
    return possible_combos


def get_primaries(shape_name: str, separator=SEPARATOR):
    """Get the primary shape names from the shape name.

    Parameters:
        shape_name (str): The shape name to extract primaries from.
        separator (str): Separator used to split the shape name.

    Returns:
        list: Set of primary shape names.

    Example:
        >>> get_primaries("a_b10")
        {'a', 'b'}
    """
    primaries = list()
    for shape in shape_name.split(separator):
        if is_inbetween(shape, separator):
            primary = shape[:-2]
        else:
            primary = shape
        if primary not in primaries:
            primaries.append(primary)
    return primaries

def get_parents(shape_name: str, separator=SEPARATOR):
    """Get the parents of the shape.

    Parameters:
        shape_name (str): The shape name to extract parents from.
        separator (str): Separator used to split the shape name.

    Returns:
        list or None: Sorted list of parents, or None if the shape is primary.

    Example:
        >>> get_parents("a_b10")
        ['a', 'b10']
    """
    shape_parents = shape_name.split(separator)
    return sorted(shape_parents)

def get_shape_values(shape_name: str, separator=SEPARATOR):
    """Get the shape values from the shape name.

    Parameters:
        shape_name (str): The shape name to extract values from.
        separator (str): Separator used to split the shape name.

    Returns:
        list: List of float values for each parent.

    Example:
        >>> get_shape_values("a_b10")
        [1.0, 0.1]
    """
    shape_values = list()
    shape_parents = shape_name.split(separator)
    for parent in shape_parents:
        val = [char for char in parent[-2:] if char.isdigit()]
        if val:
            val = "".join(val)
        else:
            val = 100
        val = float(val)/100
        shape_values.append(val)
    return shape_values


def find_split_suffix(primary_name: str):
    """Find the split suffix for a primary shape name.
    The suffix is all capital letters at the end of the name.

    Parameters:
        primary_name (str): The primary shape name.
    Returns:
        str: The split suffix.
    """
    suffix = ""
    for char in primary_name[::-1]:
        if char.isupper():
            suffix = char + suffix
        else:
            break    
    return suffix

def get_split_suffices(shape_name: str, separator=SEPARATOR):
    """Get the split suffices for each primary shape in the shape name.

    Parameters:
        shape_name (str): The shape name to process.
        separator (str): Separator used in the shape name.

    Returns:
        list: List of split suffices for each primary shape.

    Example:
        >>> get_split_suffices("aR_bTR25", separator="_")
        ['R', 'TR']
    """
    shape_primaries = get_primaries(shape_name, separator)
    suffices = list()
    for primary in shape_primaries:
        suffix = find_split_suffix(primary)
        suffices.append(suffix)
    return suffices


def get_unsplit_name(shape_name: str, separator=SEPARATOR):
    """Get the unsplit shape name by removing separators.

    Parameters:
        shape_name (str): The shape name to process.
        separator (str): Separator used in the shape name.

    Returns:
        str: The unsplit shape name.

    Example:
        >>> get_unsplit_name("aR_bTR25", separator="_")
        'a_b25'    """
    shape_parents = shape_name.split(separator)
    unsplit_parents = list()
    for parent in shape_parents:
        if is_inbetween(parent, separator):
            primary = parent[:-2]
            digits = parent[-2:]
        else:
            primary = parent
            digits = ""
        suffix = find_split_suffix(primary)
        unsplit_primary = primary[:-len(suffix)] if suffix else primary
        unsplit_parent = f"{unsplit_primary}{digits}"
        unsplit_parents.append(unsplit_parent)
    return separator.join(unsplit_parents)