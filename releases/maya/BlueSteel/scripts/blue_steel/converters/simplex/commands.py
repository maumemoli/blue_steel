# Simplex shapes naming conversion module for blue_steel
# simplex shape name structure:
# Separator: "_"
# Side: "L" or "R"
# ShapeName: string representing the shape
# Value: 2-digit integer (00-100)
# Primary: <Side>_<ShapeName>
# Inbetween: <Side>_<ShapeName>_<Value>
# Combo: <Side>_<ShapeName1>_<Side>_<ShapeName2>_...
# Combo Inbetween: <Side>_<ShapeName1>_<Value1>_<Side>_<ShapeName2>_<Value2>_...
from ... import env
from ...logic import utilities
from ...api.blendshape import Blendshape
from ...api.editor import BlueSteelEditor
from maya import cmds, mel
import traceback


SEPARATOR = env.SEPARATOR
SIMPLEX_SEPARATOR = "_"

def get_available_simplex_nodes()-> list:
    """
    Get a list of available simplex nodes in the scene.

    Returns:
        list of str: List of simplex node names.
    """
    simplex_nodes = cmds.ls(et="simplex_maya") or []
    return simplex_nodes

def simplex_plugin_loaded()-> bool:
    """
    Check if the Simplex plugin is loaded.

    Returns:
        bool: True if the Simplex plugin is loaded, False otherwise.
    """
    loaded_plugins = cmds.pluginInfo(query=True, listPlugins=True) or []
    return "simplex_maya" in loaded_plugins

def load_simplex_plugin()-> bool:
    """
    Load the Simplex plugin if it is not already loaded.

    Returns:
        bool: True if the Simplex plugin is loaded or successfully loaded, False otherwise.
    """
    if not simplex_plugin_loaded():
        try:
            cmds.loadPlugin("simplex_maya")
            return True
        except Exception as e:
            print("Failed to load Simplex plugin:", e)
            return False
    return True

def get_controller_from_simplex_node(simplex_node)-> str:
    """
    Get the controller associated with a simplex node.

    Parameters:
        simplex_node (str): The name of the simplex node.

    Returns:
        str: The name of the associated controller.
    """
    controller = cmds.listConnections(f"{simplex_node}.ctrlMsg", s=True, d=False)
    if controller:
        return controller[0]
    return None

def get_blendshape_from_simplex_node(simplex_node)-> str:
    """
    Get the blendshape associated with a simplex node.

    Parameters:
        simplex_node (str): The name of the simplex node.

    Returns:
        str: The name of the associated blendshape.
    """
    connections = cmds.listConnections(f"{simplex_node}.weights", s=False, d=True)
    blendshapes = [c for c in set(connections) if cmds.nodeType(c) == "blendShape"] if connections else []
    if blendshapes:
        return blendshapes[0]
    return None

def get_mesh_from_simplex_node(simplex_node)-> str:
    """
    Get the mesh associated with a simplex node.

    Parameters:
        simplex_node (str): The name of the simplex node.

    Returns:
        str: The name of the associated mesh.
    """
    blendshape = get_blendshape_from_simplex_node(simplex_node)
    if blendshape:
        base_mesh = cmds.blendShape(blendshape, query=True, geometry=True)
        if base_mesh:
            transform = cmds.listRelatives(base_mesh[0], parent=True)
            if transform:
                return transform[0]
    return None

def connect_blue_steel_ctrl_to_simplex_ctrl(blue_steel_ctrl: str, simplex_ctrl: str, merge_sides: bool = False):
    """
    Connect a blue_steel controller to a simplex controller.

    Parameters:
        blue_steel_ctrl (str): The name of the blue_steel controller.
        simplex_ctrl (str): The name of the simplex controller.
    """
    # get all the attributes on the blue_steel controller
    simplex_attr = cmds.listAttr(simplex_ctrl, keyable=True, scalar=True) or []
    # print(f"Simplex attributes: {simplex_attr}")
    blue_steel_attr = cmds.listAttr(blue_steel_ctrl, keyable=True, scalar=True) or []
    # print(f"Blue Steel attributes: {blue_steel_attr}")
    # convert the simplex attribute names to blue_steel attribute names
    converted = simplex_shape_names_to_blue_steel(simplex_attr, merge_sides=merge_sides)
    # print(f"Converted attributes: {converted}")

    for blue_steel_shape_name in converted.keys():
        simplex_shape_names = converted[blue_steel_shape_name]
        for simplex_shape_name in simplex_shape_names:
            if blue_steel_shape_name in blue_steel_attr:
                print(f"Connecting {blue_steel_ctrl}.{blue_steel_shape_name} to {simplex_ctrl}.{simplex_shape_name}")
                cmds.connectAttr(f"{blue_steel_ctrl}.{blue_steel_shape_name}", f"{simplex_ctrl}.{simplex_shape_name}", force=True)


def simplex_shape_names_to_blue_steel(shape_names, merge_sides=False)-> dict:
    """
    Convert simplex shape names to blue_steel shape names.

    Parameters:
        shape_names (list of str): List of simplex shape names.

    Returns:
        list of str: List of blue_steel shape names.
    """
    converted_names = {}
    for name in shape_names:
        # Example conversion logic; modify as needed
        values = get_shape_values(name)
        roots, sides, values = extract_shape_elements(name)
        converted_parts = []
        for value, root, side in zip(values, roots, sides):
            if merge_sides:
                converted_part = f"{root}{value}"
            else:
                converted_part = f"{root}{side}{value}"
            converted_parts.append(converted_part)
        
        converted_name = SEPARATOR.join(converted_parts)
        names_list = converted_names.get(converted_name, [])
        names_list.append(name)
        converted_names[converted_name] = names_list

    return converted_names


def reset_simplex_controller(controller):
    """
    Reset the simplex controller to its default state.

    Parameters:
        controller: The simplex controller object.
    """
    # get all the float attributes on the controller
    float_attrs = cmds.listAttr(controller, keyable=True, scalar=True) or []
    for attr in float_attrs:
        cmds.setAttr(f"{controller}.{attr}", 0.0)


def set_simplex_controller_shapes_values(controller, shape_names):
    """
    Set the simplex controller shapes values based on the provided shape names.

    Parameters:
        controller: The simplex controller object.
        shape_names (list of str): List of simplex shape names.
    """
    for shape_name in shape_names:
        roots, sides, values = extract_shape_elements(shape_name)
        for root, side, value in zip(roots, sides, values):
            attr_name = f"{side}_{root}"
            control_value = int(value)/100.0 if value else 1.0
            # print(f"Setting {controller}.{attr_name} to {control_value}")
            if cmds.attributeQuery(attr_name, node=controller, exists=True):
                cmds.setAttr(f"{controller}.{attr_name}", control_value)

def duplicate_simplex_shapes(blendshape_node, controller, mesh, merge_sides = False, level_range = (1,10)):
    """
    Duplicate simplex shapes from a blendshape node to a controller.

    Parameters:
        blendshape_node: The blendshape node containing simplex shapes.
        controller: The simplex controller object.
        mesh: The mesh object associated with the blendshape.
    """
    blendshape = Blendshape(blendshape_node)
    shape_names = [str(w) for w in blendshape.get_weights() if w != "Rest_faceshapes"]
    converted_names = simplex_shape_names_to_blue_steel(shape_names, merge_sides=merge_sides)
    insertion_sorted = utilities.sort_for_insertion(converted_names.keys())
    # creating a group to hold the duplicated shapes
    shapes_group = cmds.group(empty=True, name=f"{mesh}_simplexShapes_grp")
    for shape_name in insertion_sorted:
        shape_level = len(utilities.get_parents(shape_name, SEPARATOR) )
        # print(f"Processing shape: {shape_name} at level {shape_level}")
        if shape_level < level_range[0] or shape_level > level_range[1]:
            continue
        source_shapes = converted_names[shape_name]
        reset_simplex_controller(controller)
        # print(f"Setting controller for shape: {shape_name} using source shapes: {source_shapes}")
        set_simplex_controller_shapes_values(controller, source_shapes)
        dup = cmds.duplicate(mesh, name=shape_name)[0]
        name = cmds.parent(dup, shapes_group)

def add_simplex_shapes_to_editor(editor: BlueSteelEditor,
                                 blendshape_node: str,
                                 controller: str,
                                 mesh: str,
                                 merge_sides: bool = False,
                                 level_range: tuple = (1,10)):
    """
    Add simplex shapes to the blue_steel shape editor.

    Parameters:
        editor: The blue_steel shape editor object.
        blendshape_node: The blendshape node containing simplex shapes.
        controller: The simplex controller object.
        mesh: The mesh object associated with the blendshape.
    """
    blendshape = Blendshape(blendshape_node)
    shape_names = [str(w) for w in blendshape.get_weights() if w != "Rest_faceshapes"]
    converted_names = simplex_shape_names_to_blue_steel(shape_names, merge_sides=merge_sides)
    insertion_sorted = utilities.sort_for_insertion(converted_names.keys())
    gMainProgressBar = mel.eval('$tmp = $gMainProgressBar')
    total_shapes = len(insertion_sorted)
    # --- Start the progress bar ---
    cmds.progressBar(gMainProgressBar, edit=True,
                    beginProgress=True,
                    isInterruptable=True,
                    status=f'Processing {total_shapes} shapes...',
                    maxValue=total_shapes)
    try:
        for shape_name in insertion_sorted:
            cmds.progressBar(gMainProgressBar,
                    edit=True,
                    step=1,
                    status=f'Adding shape: {shape_name}...')
            shape_level = len(utilities.get_parents(shape_name, SEPARATOR) )
            if shape_level < level_range[0] or shape_level > level_range[1]:
                continue
            source_shapes = converted_names[shape_name]
            reset_simplex_controller(controller)
            set_simplex_controller_shapes_values(controller, source_shapes)
            editor.commit_shape(shape_name, mesh)
    except Exception as e:
        print("An error occurred while adding simplex shapes to the editor:")
        traceback.print_exc()
    finally:
        # --- End the progress bar ---
        cmds.progressBar(gMainProgressBar, edit=True, endProgress=True)

def extract_shape_elements(shape_name)-> list:
    """
    Separate the side prefixes from a shape name by removing separators returning three lists.
    The first list contains the roots without side prefixes and values,
    the second list contains the sides,
    and the third list contains the values.

    Parameters:
        shape_name (str): The simplex shape name.
    Returns:
        list: The unsplit shape name.
    Example:
        >>> get_unsplit_shape_name("L_eyeSmile_50_R_mouthFrown_30")
        ['eyeSmile50', "mouthFrown30"], ['L', 'R']
    """
    roots = []
    sides = []
    values = []
    parents = get_shape_parents(shape_name)
    for parent in parents:
        primary = ""
        value = ""
        side = ""
        parts = parent.split(SIMPLEX_SEPARATOR)
        if parts[0] in ["L", "R"]:
            side = parts[0]
            parts = parts[1:]
        if all(x.isdigit() for x in parts[-1:]):
            value = parts[-1]
            parts = parts[:-1]
        primary = SIMPLEX_SEPARATOR.join(parts)  # Center or no specific side
        roots.append(primary)
        sides.append(side)
        values.append(value)

    return roots, sides, values


def get_shape_sides(shape_name)-> list:
    """
    Get the sides from a simplex shape name.

    Parameters:
        shape_name (str): The simplex shape name.
    Returns:
        list: List of sides found in the shape name.
    Example:
        >>> get_shape_sides("L_eyeSmile50_R_mouthFrown30")
        ['L', 'R']
    """
    sides = []
    parents = get_shape_parents(shape_name)
    for parent in parents:
        parts = parent.split(SIMPLEX_SEPARATOR)
        if parts[0] in ["L", "R"]:
            sides.append(parts[0])
        else:
            sides.append("")  # Center or no specific side
    return sides

def get_shape_parents(shape_name)-> list:
    """
    Get the parent shapes from a simplex shape name.

    Parameters:
        shape_name (str): The simplex shape name.
    Returns:
        list: List of parent shape names.
    Example:
        >>> get_shape_parents("L_eyeSmile_50_R_mouthFrown_30")
        ['L_eyeSmile_50', 'R_mouthFrown_30']
    """
    parents = []
    parts = shape_name.split(SIMPLEX_SEPARATOR)
    i = 0
    while i < len(parts):
        if parts[i] in ["L", "R"] and i + 1 < len(parts):
            parent = parts[i] + SIMPLEX_SEPARATOR + parts[i + 1]
            if i + 2 < len(parts) and parts[i + 2].isdigit():
                parent += SIMPLEX_SEPARATOR + parts[i + 2]
                i += 1
            parents.append(parent)
            i += 2
        else:
            i += 1
    return parents

def get_shape_primaries(shape_name)-> list:
    """
    Get the primary shapes from a simplex shape name.

    Parameters:
        shape_name (str): The simplex shape name.
    Returns:
        list: List of primary shape names.
    Example:
        >>> get_shape_primaries("L_eyeSmile_50_R_mouthFrown_30")
        ['L_eyeSmile', 'R_mouthFrown']
    """
    parents = get_shape_parents(shape_name)
    primaries = []
    for parent in parents:
        parts = parent.split(SIMPLEX_SEPARATOR)
        if all(x.isdigit() for x in parts[-1:]):
            primary = SIMPLEX_SEPARATOR.join(parts[:-1])
        else:
            primary = parent
        primaries.append(primary)
    return primaries

def get_shape_values(shape_name)-> list:
    """
    Get the shape values from a simplex shape name.

    Parameters:
        shape_name (str): The simplex shape name.
    Returns:
        list: List of shape values.
    Example:
        >>> get_shape_values("L_eyeSmile_50_R_mouthFrown_30")
        [0.5, 0.3]
    """
    values = []
    parents = get_shape_parents(shape_name)
    for parent in parents:
        parts = parent.split(SIMPLEX_SEPARATOR)
        if all(x.isdigit() for x in parts[-1:]):
            value_str = parts[-1]
            value = int(value_str) / 100.0
        else:
            value = 1.0
        values.append(value)
    return values