"""
Set of functions to manage attributes in Maya.
"""

from maya import cmds

# tags are simple string attributes added to nodes to store metadata.

def get_next_available_index(attr_name: str):
    """
    Get the next available index for a multi attribute.
    Parameters:
        attr_name (str): The name of the multi attribute.
    Returns:
        int: The next available index.
    Example:
        >>> next_index = get_next_available_index("myNode.myMultiAttr")
        >>> print(next_index)
        3
    """
    node = ".".join(attr_name.split(".")[:-1])
    attr = attr_name.split(".")[-1]
    if cmds.attributeQuery(attr,node=node, exists=True) and cmds.attributeQuery(attr,node=node, exists=True):
        # check if it is multi
        indices = cmds.getAttr(attr_name, multiIndices=True)
        if indices:
            return max(indices) + 1
        else:
            return 0
    else:
        raise ValueError(f"Attribute {attr_name} does not exist or is not multi")


def rename_attribute(node: str, old_name: str, new_name: str):
    """
    Rename an attribute on a node.
    Parameters:
        node (str): The name of the node.
        old_name (str): The current name of the attribute.
        new_name (str): The new name of the attribute.
    Returns:
        str: The name of the renamed attribute.
    Example:
        >>> rename_attribute("pCube1", "oldAttr", "newAttr")
        'pCube1.newAttr'
    """
    if not cmds.attributeQuery(old_name,node = node, exists=True):
        raise ValueError(f"Attribute {old_name} does not exist on node {node}")
    cmds.renameAttr(f"{node}.{old_name}", new_name)
    return f"{node}.{new_name}"

def add_tag(node: str, tag: str, value: str = ""):
    """
    Add a tag attribute to a node.
    Parameters:
        node (str): The name of the node.
        tag (str): The name of the tag.
        value (str): The value of the tag. Default is an empty string.
    Returns:
        str: The name of the created attribute.
    Example:
        >>> add_tag("pCube1", "myTag", "myValue")
        'pCube1.myTag'
    """
    if cmds.attributeQuery(tag,node = node, exists=True):
        return None
    attr_name = f"{node}.{tag}"
    if not cmds.objExists(attr_name):
        cmds.addAttr(node, longName=tag, dataType="string")
    cmds.setAttr(attr_name, value, type="string")
    return attr_name

def get_tag(node: str, tag: str):
    """
    Get the value of a tag attribute from a node.
    Parameters:
        node (str): The name of the node.
        tag (str): The name of the tag.
    Returns:
        str: The value of the tag, or None if the tag does not exist.
    Example:
        >>> get_tag("pCube1", "myTag")
        'myValue'
    """
    if not cmds.attributeQuery(tag,node = node, exists=True):
        return None
    attr_name = f"{node}.{tag}"
    return cmds.getAttr(attr_name)

def remove_attribute(node: str, tag: str):
    """
    Remove an attribute from a node.
    Parameters:
        node (str): The name of the node.
        tag (str): The name of the tag.
    Returns:
        bool: True if the tag was removed, False if the tag does not exist.
    Example:
        >>> remove_attribute("pCube1", "myTag")
        True
    """
    if not cmds.attributeQuery(tag,node = node, exists=True):
        return False
    attr_name = f"{node}.{tag}"
    cmds.deleteAttr(attr_name)
    return True

def add_message_attr(node: str, attr_name: str, linked_node: str = None):
    """
    Create a message attribute on a node.
    Parameters:
        node (str): The name of the node.
        attr_name (str): The name of the attribute.
        linked_node (str): The name of the linked node.
    Returns:
        str: The name of the created attribute.
    Example:
        >>> create_message_attr("pCube1", "myMessage")
        'pCube1.myMessage'
    """
    if cmds.attributeQuery(attr_name,node = node, exists=True):
        return None
    full_attr_name = f"{node}.{attr_name}"
    cmds.addAttr(node, longName=attr_name, attributeType="message")
    if linked_node and cmds.objExists(linked_node):
        cmds.connectAttr( f"{linked_node}.message",full_attr_name ,force=True)
    return full_attr_name

def get_message_attr(node: str, attr_name: str):
    """
    Get the connected node of a message attribute.
    Parameters:
        node (str): The name of the node.
        attr_name (str): The name of the attribute.
    Returns:
        str: The name of the connected node, or None if not connected.
    Example:
        >>> get_message_attr("pCube1", "myMessage")
        'pSphere1'
    """
    full_attr_name = f"{node}.{attr_name}"
    if not cmds.attributeQuery(attr_name,node = node, exists=True):
        return None
    connections = cmds.listConnections(full_attr_name, source=True, destination=False)
    if connections:
        return connections[0]
    return None

def add_float_attr(node: str,
                   attr_name: str,
                   default_value: float = 0.0,
                   min_value: float = 0.0,
                   max_value: float = 1.0,
                   keyable: bool = True):
    """
    Create a float attribute on a node.
    Parameters:
        node (str): The name of the node.
        attr_name (str): The name of the attribute.
        default_value (float): The default value of the attribute. Default is 0.0.
        min_value (float): The minimum value of the attribute. Default is None.
        max_value (float): The maximum value of the attribute. Default is None.
    Returns:
        str: The name of the created attribute.
    Example:
        >>> create_float_attr("pCube1", "myFloat", 1.0, 0.0, 10.0)
        'pCube1.myFloat'
    """
    if cmds.attributeQuery(attr_name,node = node, exists=True):
        return None
    full_attr_name = f"{node}.{attr_name}"
    cmds.addAttr(node, longName=attr_name, attributeType="float", defaultValue=default_value)
    if min_value is not None:
        cmds.addAttr(full_attr_name, edit=True, minValue=min_value)
    if max_value is not None:
        cmds.addAttr(full_attr_name, edit=True, maxValue=max_value)
    if keyable:
        cmds.setAttr(full_attr_name, keyable=True)

    return full_attr_name

def create_attribute_grp(name:str, lock_transforms: bool = True):
    """
    Create an empty group with all the transformation attributes removed.
    Parameters:
        name (str): The name of the group.
    Returns:
        str: The name of the created group.
    """
    if cmds.objExists(name):
        raise ValueError(f"Node {name} already exists.")

    grp = cmds.createNode("transform", name=name)
    # hide transformations
    for attr in ["translate", "rotate", "scale"]:
        for axis in ["X", "Y", "Z"]:
            full_attr = f"{attr}{axis}"
            if cmds.attributeQuery(full_attr, node=grp, exists=True):
                cmds.setAttr(f"{grp}.{full_attr}", lock=lock_transforms, keyable=False, channelBox=False)
    # hide visibility
    cmds.setAttr(f"{grp}.visibility", lock=True, keyable=False, channelBox=False)
    return grp


def get_nodes_by_tag(tag: str, type=None):
    """
    Get all nodes in the scene with the specified tag
    Parameters:
        tag (str): The tag to search for
        type (str): The type of node to search for (optional)
    Returns:
        list: A list of node names
    Example:
        >>> tagged_nodes = get_nodes_by_tag("BlueSteelMain")
    """
    if type:
        nodes = cmds.ls(type=type)
    else:
        nodes = cmds.ls()
    tagged_nodes = []
    for node in nodes:
        if cmds.attributeQuery(tag, node=node, exists=True):
            tagged_nodes.append(node)
    return tagged_nodes