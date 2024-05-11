"""
Here go all the utility functions for the logic module.
"""
import blue_steel.env as env
SEPARATOR = env.SEPARATOR


def combine_lists(lists: list):
    """
    Combine the lists
    """
    combined = []
    for sublist in lists[0]:
        if len(lists) == 1:
            combined.append(sublist)
        else:
            for item in combine_lists(lists[1:]):
                combined.append(f"{sublist}{SEPARATOR}{item}")
    # sorting alphabetically all the items
    combined = [SEPARATOR.join(sorted(x.split(SEPARATOR))) for x in combined]
    return combined

# string utilities


def is_primary(shape_name: str):
    """
    Chek if the shape is primary
    :param shape_name: the shape name
    :return: True if the shape is primary
    """
    shape_parents = shape_name.split(SEPARATOR)
    if len(shape_parents) == 1 and not is_inbetween(shape_name):
        return True
    else:
        return False


def is_combo_and_inbetween(shape_name: str):
    """
    Check if the shape is a combo and an inbetween
    :param shape_name: the shape name
    :return: True Truer if the shape is a combo and an inbetween
    """
    shape_parents = shape_name.split(SEPARATOR)
    combo = False
    inbetween = False
    if len(shape_parents) > 1:
        combo = True
    for parent in shape_parents:
        digits = [char for char in parent[-2:] if char.isdigit()]
        if len(digits) == 2:
            inbetween = True
    return (combo, inbetween)


def is_combo_inbetween(shape_name: str):
    """
    Check if the shape isa combo inbetween
    :param shape_name: the shape name
    :return: True if the shape is a combo inbetween
    """
    if is_combo_and_inbetween(shape_name) == (True, True):
        return True
    else:
        return False


def is_inbetween(shape_name: str):
    """
    Check if the shape is inbetween
    :param shape_name: the shape name
    :return: True if the shape is inbetween
    """
    if is_combo_and_inbetween(shape_name) == (False, True):
        return True
    else:
        return False


def is_combo(shape_name: str):
    """
    Check if the shape is combo
    :param shape_name: the shape name
    :return: True if the shape is combo
    """
    if is_combo_and_inbetween(shape_name) == (True, False):
        return True
    else:
        return False


def is_valid(shape_name: str):
    """
    Check if the shape is valid
    :param shape_name: the shape name
    :return: True if the shape_name is valid
    """
    parents = shape_name.split(SEPARATOR)
    for parent in parents:
        if not is_inbetween(parent):
            digits = [char for char in parent if char.isdigit()]
            if digits:
                return False
        else:
            if parent[:-2] in parents:
                return False

    if len(set(parents)) != len(parents):
        return False

    return True


def get_primaries(shape_name: str):
    """
    get the primary shapes names from the shape name
    :return: the primary shape name or None if the shape is not an inbetween.
    """
    primaries = list()
    for shape in shape_name.split(SEPARATOR):
        if is_inbetween(shape):
            primaries.append(shape[:-2])
        else:
            primaries.append(shape)
    return primaries


def get_shape_values(shape_name: str):
    """
    Get the shape values from the shape name
    :param shape_name: the shape name
    :return: the shape values
    """
    shape_values = list()
    shape_parents = shape_name.split(SEPARATOR)
    for parent in shape_parents:
        val = [char for char in parent[-2:] if char.isdigit()]
        if val:
            val = "".join(val)
        else:
            val = 100
        val = float(val)/100
        shape_values.append(val)
    return shape_values


def separate_digits(name: str):
    """
    Separate the incremental digits from the name.
    :param name: the name with digits to separate
    :return: name, digits
    """
    digits = "".join([char for char in name[-2:] if char.isdigit()])
    if digits:
        return name[:-2], digits
    else:
        return name, ""


def get_parents(shape_name: str):
    """
    Get the parents of the shape
    :param shape_name: the shape name
    :return: the parents or None if the shape is primary
    """
    shape_parents = shape_name.split(SEPARATOR)
    if len(shape_parents) > 1:
        return shape_parents
    else:
        return None
