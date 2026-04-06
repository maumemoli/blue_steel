# Simplex shapes naming conversion module for blue_steel
# This module will read the simplex node definition and
# convert the shape names to blue_steel compatible names
# based on the sliders names and progressives,
# then it will add the shapes to the blue_steel editor.
# it will also provide an option to merge shapes with the same root but different sides into a single shape.
# The conversion will be based on the following rules:
# - The control attribute names will be converted to camel case if the SEPARATOR is present.
# - The control attribute values will be converted to percentage and appended to the name,
#   with 100% being omitted for cleaner names.
# - The side tokens (single char Upper Case) will be separated from the attribute name and
#   placed at the end of the name before the inbetween values.

from ... import env
import json
from ...logic import utilities
from ...api.blendshape import Blendshape
from ...api.editor import BlueSteelEditor
from maya import cmds, mel
import traceback
from dataclasses import dataclass , field
from typing import List, Optional, Dict, Tuple

SEPARATOR = env.SEPARATOR
SIMPLEX_SEPARATOR = "_"

@dataclass
class SimplexShape:
    simplex_target_name:     str
    control_attributes:           list = field(default_factory=list)
    control_values:           list = field(default_factory=list)
    blue_steel_target_name: Optional[str] = None  # to be filled in later during conversion
    blue_steel_merged_target_name: Optional[str] = None  # to be filled in later during conversion

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

def get_simplex_definition(simplex_node)-> dict:
    """
    Get the definition of a simplex node.

    Parameters:
        simplex_node (str): The name of the simplex node.

    Returns:
        dict: A dictionary containing the simplex node definition.
    """
    try:
        definition_json = cmds.getAttr(f"{simplex_node}.definition")
        definition = json.loads(definition_json)
        return definition
    except Exception as e:
        print(f"Failed to get definition for {simplex_node}: {e}")
        return {}

def generate_conversion_data(simplex_node)-> dict:
    """
    Generate conversion data from a simplex node definition.

    Parameters:
        simplex_node (str): The name of the simplex node.
    Returns:
        A dictionary containing the conversion data for the simplex node.
    """
    conversion_data = dict()
    controller = get_controller_from_simplex_node(simplex_node)
    conversion_data["controller"] = controller
    mesh = get_mesh_from_simplex_node(simplex_node)
    conversion_data["mesh"] = mesh
    definition = get_simplex_definition(simplex_node)
    sliders = definition.get("sliders", [])
    combos = definition.get("combos", [])
    shapes = definition.get("shapes", [])
    progressions = definition.get("progressions", [])
    shapes_count = 0
    merged_shapes_count = 0
    # getting the primaries and the inbetweens for each slider
    simplex_shapes = dict()
    for slider in sliders:
        progression = progressions[slider["prog"]]
        for shape_id, slider_value in progression["pairs"]:
            if shape_id == 0:
                continue  # skip the rest shape
            simplex_target_name = shapes[shape_id]["name"]
            control_attribtutes = [slider["name"]]
            control_values = [slider_value]
            simplex_shape = create_simplex_shape(simplex_target_name, control_attribtutes, control_values)
            shapes_count += 1
            simplex_shape_key = simplex_shape.blue_steel_merged_target_name
            if simplex_shape_key not in simplex_shapes:
                merged_shapes_count += 1
            shapes_list = simplex_shapes.get(simplex_shape_key, [])
            shapes_list.append(simplex_shape)
            simplex_shapes[simplex_shape_key] = shapes_list
    conversion_data["simplex_shapes"] = simplex_shapes
    # now we do the combos
    for combo in combos:
        pairs = combo["pairs"]
        simples_target_name = combo["name"]
        control_attributes = []
        control_values = []
        for slider_id, slider_value in pairs:
            slider = sliders[slider_id]
            control_attributes.append(slider["name"])
            control_values.append(slider_value)
        simplex_shape = create_simplex_shape(simples_target_name, control_attributes, control_values)
        shapes_count += 1
        simplex_shape_key = simplex_shape.blue_steel_merged_target_name
        if simplex_shape_key not in simplex_shapes:
            merged_shapes_count += 1
        shapes_list = simplex_shapes.get(simplex_shape_key, [])
        shapes_list.append(simplex_shape)
        simplex_shapes[simplex_shape_key] = shapes_list
    conversion_data["shapes_count"] = shapes_count
    conversion_data["merged_shapes_count"] = merged_shapes_count
    return conversion_data


def create_simplex_shape(simplex_target_name, control_attributes, control_values)-> SimplexShape:
    """
    Create a simplex shape name based on the shape name, control attributes, and control values.

    Parameters:
        simplex_target_name (str): The base shape name.
        control_attributes (list of str): List of control attribute names.
        control_values (list of float): List of control attribute values.

    Returns:
        SimplexShape: The generated simplex shape.
    """
    # generating the blue_steel_target_name and the blue_steel_merged_target_name
    # based on the control attributes and values
    blue_steel_shape_parts = set()
    blue_steel_merged_shape_parts = set()
    for attribute, value in zip(control_attributes, control_values):
        value_str = f"{int(value * 100):02d}"  # Convert to percentage and format as two digits
        if value_str == "100":
            value_str = ""  # Omit the value for 100% to keep the name cleaner
        merged_name, side = convert_simplex_slider_name(attribute)
        blue_steel_part = f"{merged_name}{side}{value_str}"
        blue_steel_merged_part = f"{merged_name}{value_str}"
        blue_steel_shape_parts.add(blue_steel_part)
        blue_steel_merged_shape_parts.add(blue_steel_merged_part)
    blue_steel_target_name = SEPARATOR.join(sorted(blue_steel_shape_parts))
    blue_steel_merged_target_name = SEPARATOR.join(sorted(blue_steel_merged_shape_parts))
    return SimplexShape(simplex_target_name,
                        control_attributes=control_attributes,
                        control_values=control_values,
                        blue_steel_target_name=blue_steel_target_name,
                        blue_steel_merged_target_name=blue_steel_merged_target_name)


def convert_simplex_slider_name(slider_name: str) -> tuple[str, str]:
    """
    Convert the simplex slider name to a blue_steel compatible name by converting the separators to camel case
    and separating the side prefixes, returning the cleaned shape name and the side prefix.

    Parameters:
        slider_name (str): The simplex shape name to be cleaned.
    Returns:
        tuple[str, str]: A tuple containing the cleaned shape name and separating the side prefix.
    Example:
        >>> convert_simplex_slider_name("L_eye_smile")
        ("eyeSmile", "L")
        >>> convert_simplex_slider_name("mouth_frown_R")
        ("mouthFrown", "R")
    """
    parts = slider_name.split(SEPARATOR)
    cleaned_parts = []
    sides = []
    for part in parts:
        if len(part) == 1 and part.isupper():
            sides.append(part)  # Store the side prefix
            continue  # Skip side prefixes
        if len(cleaned_parts) > 0 :
            part = part.capitalize()  # Capitalize the first letter of subsequent parts for better readability
        cleaned_parts.append(part)
    side = "".join(sides) if sides else ""  # Combine side prefixes if there are multiple
    sanitized_name =  "".join(cleaned_parts)
    return (sanitized_name, side)

    
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

def get_simplex_node_from_controller(controller)-> str:
    """
    Get the simplex node associated with a controller.

    Parameters:
        controller (str): The name of the controller.

    Returns:
        str: The name of the associated simplex node.
    """
    if cmds.attributeQuery("solver", node=controller, exists=True):  # Check if the attribute exists before querying connections
        simplex_node = cmds.listConnections(f"{controller}.solver")
        if simplex_node:
            return simplex_node[0]
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
            transform = cmds.listRelatives(base_mesh[0], parent=True, fullPath=True)
            if transform:
                return transform[0]
    return None

def connect_blue_steel_ctrl_to_simplex_ctrl(blue_steel_ctrl: str, simplex_ctrl: str):
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
    simplex_node = get_simplex_node_from_controller(simplex_ctrl)
    definition = get_simplex_definition(simplex_node)
    sliders = definition.get("sliders", [])
    # print(f"Converted attributes: {converted}")
    for slider in sliders:
        merged_name, side = convert_simplex_slider_name(slider["name"])
        split_name = f"{merged_name}{side}"
        if merged_name in blue_steel_attr and slider["name"] in simplex_attr:
            cmds.connectAttr(f"{blue_steel_ctrl}.{merged_name}", f"{simplex_ctrl}.{slider['name']}", force=True)
        elif split_name in blue_steel_attr and slider["name"] in simplex_attr:
            cmds.connectAttr(f"{blue_steel_ctrl}.{split_name}", f"{simplex_ctrl}.{slider['name']}", force=True)



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


def set_simplex_controller_shapes_values(controller, simplex_shapes: list):
    """
    Set the simplex controller shapes values based on the provided simplex shape.

    Parameters:
        controller: The simplex controller object.
        simplex_shapes (list of SimplexShape): The list of simplex shape objects.
    """
    reset_simplex_controller(controller)
    for simplex_shape in simplex_shapes:
        attributes, values = simplex_shape.control_attributes, simplex_shape.control_values
        for attr, value in zip(attributes, values):
            if cmds.attributeQuery(attr, node=controller, exists=True):
                cmds.setAttr(f"{controller}.{attr}", value)

def add_simplex_shapes_to_editor(editor: BlueSteelEditor,
                                 simplex_node: str,
                                 mesh: str,
                                 merge_sides: bool = False,
                                 level_range: tuple = (1,10)):
    """
    Add simplex shapes to the blue_steel shape editor.

    Parameters:
        editor: The blue_steel shape editor object.
        simplex_node: The simplex node containing simplex shapes.
        mesh: The mesh object associated with the simplex node.
        merge_sides: Whether to merge shapes with the same root but different sides into a single shape.
        level_range: A tuple specifying the range of shape levels to include (inclusive).
    """
    simplex_data = generate_conversion_data(simplex_node)
    controller = simplex_data["controller"]
    simplex_shapes = simplex_data["simplex_shapes"]
    insertion_sorted = utilities.sort_for_insertion(simplex_shapes.keys())
    gMainProgressBar = mel.eval('$tmp = $gMainProgressBar')
    total_shapes = simplex_data["shapes_count"] if not merge_sides else simplex_data["merged_shapes_count"]
    # --- Start the progress bar ---
    cmds.progressBar(gMainProgressBar, edit=True,
                    beginProgress=True,
                    isInterruptable=True,
                    status=f'Processing {total_shapes} shapes...',
                    maxValue=total_shapes)
    try:
        for shapes_group_name in insertion_sorted:
            shapes_group = simplex_shapes[shapes_group_name]
            shape_level = len(utilities.get_parents(shapes_group_name, SEPARATOR) )
            if shape_level < level_range[0] or shape_level > level_range[1]:
                continue
            if merge_sides:
                set_simplex_controller_shapes_values(controller, shapes_group)
                cmds.progressBar(gMainProgressBar,
                        edit=True,
                        step=1,
                        status=f'Adding shape: {shapes_group_name}...')
                editor.commit_shape(shapes_group_name, mesh)
            else:
                for shape in shapes_group:
                    set_simplex_controller_shapes_values(controller, [shape])
                    cmds.progressBar(gMainProgressBar,
                            edit=True,
                            step=1,
                            status=f'Adding shape: {shape.blue_steel_target_name}...')
                    editor.commit_shape(shape.blue_steel_target_name, mesh)
            
    except Exception as e:
        print("An error occurred while adding simplex shapes to the editor:")
        traceback.print_exc()
    finally:
        # --- End the progress bar ---
        cmds.progressBar(gMainProgressBar, edit=True, endProgress=True)
