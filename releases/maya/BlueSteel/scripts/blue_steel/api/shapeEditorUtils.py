from maya import cmds
from . import mayaUtils
from . import attrUtils

# shape editor utilities

def create_shape_editor_group(group_name:str) -> int:
    """
    Create a new group in the shape editor.
    Parameters:
        group_name (str): The name of the group to create
        Returns:
            int: The index of the created group"""
    dir_id = attrUtils.get_next_available_index("shapeEditorManager.blendShapeDirectory")
    cmds.setAttr(f"shapeEditorManager.blendShapeDirectory[{dir_id}].directoryName",
                    group_name, type="string")
    return dir_id

def get_shape_editor_groups() -> list:
    """
    Get the list of groups in the shape editor.
    Returns:
        list: A list of group names in the shape editor.
    """
    groups = []
    dir_count = cmds.getAttr("shapeEditorManager.blendShapeDirectory", size=True)
    for i in range(dir_count):
        group_name = cmds.getAttr(f"shapeEditorManager.blendShapeDirectory[{i}].directoryName")
        groups.append(group_name)
    return groups


class ShapeGroup(int):
    def __new__(cls, group_index: int):
        return int.__new__(cls, group_index)
    
    @property
    def name(self) -> str:
        """
        Get the name of the shape editor group.
        Returns:
            str: The name of the shape editor group.
        Example:
            >>> shape_group = ShapeGroup(1)
            >>> print(shape_group.name)
            "MyShapeGroup"
        """
        # check if the group exists
        dir_indexes = cmds.getAttr("shapeEditorManager.blendShapeDirectory", multiIndices=True) or []
        if self not in dir_indexes:
            raise ValueError(f"Shape editor group with index {self} does not exist.")
        group_name = cmds.getAttr(f"shapeEditorManager.blendShapeDirectory[{self}].directoryName")
        return group_name

class ShapeEditor(object):
    def __init__(self):
        manager_node = "shapeEditorManager"
        if not cmds.objExists(manager_node):
            raise RuntimeError("Shape Editor Manager node does not exist in the scene.")
        return


    def _get_blendshapes(self):
        """
        Get all blendshape nodes in the shape editor.
        Returns:
            list: A list of blendshape node names.
        Example:
            >>> shape_editor = ShapeEditor()
            >>> blendshapes = shape_editor._get_blendshapes()
            >>> print(blendshapes)
            ['blendShape1', 'blendShape2']
        """
        blendshapes = cmds.ls(exactType="blendShape")
        return blendshapes

    def _get_blendshapes_mid_layer_idxs(self):
        """
        Get all blendshape nodes in the shape editor with their mid layer ids.
        Returns:
            list: A list of tuples with blendshape name and mid layer id.
        """
        blendshapes = self._get_blendshapes()
        mid_layer_ids = []
        for blendshape in blendshapes:
            mid_layer_ids.append(self._get_blendshape_mid_layer_id(blendshape))
        return mid_layer_ids

    def _get_blendshapes_mid_layer_parents(self) -> list:
        """
        Get all blendshape nodes in the shape editor with the specified mid layer parent id.
        Returns:
            list: A list of blendshape int with the mid layer parent id.
        Example:
            >>> shape_editor = ShapeEditor()
            >>> parent_idxs = shape_editor.get_blendshape_by_mid_layer_parents()
            >>> print(parent_idxs)
            [0, 1, 2]
        """
        blendshapes = self._get_blendshapes()
        parent_idxs = []
        for blendshape in blendshapes:
            parent_id = self._get_blendshape_mid_layer_parent(blendshape)
            parent_idxs.append(parent_id)
        return parent_idxs

    def _get_blendshape_mid_layer_id(self, blendshape_name: str) -> int:
        """
        Get the index of a blendshape node in the shape editor.
        Parameters:
            blendshape_name (str): The name of the blendshape node.
        Returns:
            int: The index of the blendshape node in the shape editor.
        Example:
            >>> blendshape_id = get_blendshape_mid_layer_id("blendShape1")
            >>> print(blendshape_id)
            1
        """
        if not cmds.objExists(blendshape_name):
            raise ValueError(f"Blendshape node {blendshape_name} does not exist")
        return cmds.getAttr(f"{blendshape_name}.midLayerId")

    def _get_blendshape_mid_layer_parent(self, blendshape_name: str) -> int:
        """
        Get the parent index of a blendshape node in the shape editor.
        Parameters:
            blendshape_name (str): The name of the blendshape node.
        Returns:
            int: The parent index of the blendshape node in the shape editor.
        Example:
            >>> parent_id = get_blendshape_mid_layer_parent("blendShape1")
            >>> print(parent_id)
            0
        """
        if not cmds.objExists(blendshape_name):
            raise ValueError(f"Blendshape node {blendshape_name} does not exist")
        return cmds.getAttr(f"{blendshape_name}.midLayerParent")

    def parent_item_to_root_group(self, item_id: int, root_id: int = 0):
        """
        Parent an item to a root group in the shape editor.
        Parameters:
            item_id (int): The id of the item to parent.
            root_id (int): The id of the root group to parent to. Default is 0 (the root).
        Returns:
            None
        Example:
            >>> parent_item_to_root_group(1, 0)
        """
        # first we need to remove the item from its current parent
        if item_id >= 0:
            current_parent_id = cmds.getAttr(f"shapeEditorManager.blendShapeDirectory[{item_id}].parentIndex")
        cmds.setAttr(f"shapeEditorManager.blendShapeDirectory[{item_id}].parentIndex", root_id)

    def create_new_root_group(self, group_name: str, parent_id = 0,children: list = None):
        """
        Create a new root group in the shape editor.
        A root group is a top-level group that can contain other groups and blendshape nodes.
        These groups live under the "shapeEditorManager.blendShapeDirectory" attribute.
        Parameters:
            group_name (str): The name of the group to create.
            children (list): A list of child nodes to add to the group.
        Returns:
            int: The id of the created group. 
        Example:
            >>> create_new_group("MyBlendshapeGroup")
            "MyBlendshapeGroup"
        """
        next_id = attrUtils.get_next_available_index("shapeEditorManager.blendShapeDirectory")
        cmds.setAttr(f"shapeEditorManager.blendShapeDirectory[{next_id}].directoryName", group_name, type="string")
        # parenting to the root
        cmds.setAttr(f"shapeEditorManager.blendShapeDirectory[{next_id}].parentIndex", parent_id)
        # adding the new group to the root childIndices
        root_children = cmds.getAttr(f"shapeEditorManager.blendShapeDirectory[{parent_id}].childIndices") or []
        root_children.append(-next_id)
        cmds.setAttr(f"shapeEditorManager.blendShapeDirectory[{parent_id}].childIndices", root_children, type="Int32Array")
        return next_id

    def get_root_items():
        """
        Get all the root items in the shape editor.
        Root items are the top-level items in the shape editor.
        They can be blendshape nodes or groups.
        Returns:
            list: A list with item_ids.
        Example:
            >>> root_items = get_root_items()  
            >>> print(root_items)
            [1, -1, 2, -2]
        """
        root_idxs = cmds.getAttr("shapeEditorManager.blendShapeDirectory", multiIndices=True) or []
        for idx in root_idxs:
            print(cmds.getAttr(f"shapeEditorManager.blendShapeDirectory[{idx}].directoryName"))
            print("parentIndex:", cmds.getAttr(f"shapeEditorManager.blendShapeDirectory[{idx}].parentIndex"))
            print("--- CHILDREN ---")
            root_children = cmds.getAttr(f"shapeEditorManager.blendShapeDirectory[{idx}].childIndices") or []
            for child in root_children:
                print(child)
        return root_idxs
        idx = cmds.getAttr("shapeEditorManager.blendShapeDirectory[0].childIndices", multiIndices=True) or []
        return idx

    def add_items_to_root_group(items: list, group_id: int):
        """
        Add items to a group in the shape editor.
        The items is a int list that can be blendshape nodes or other groups.
        A group will hold a negative index while a blendshape node will hold a positive index.
        Parameters:
            blendshape_list (list): A list of blendshape node names.
            group_id (int): The id of the group to add the blendshapes to.
        Returns:
            None
        Example:
            >>> add_blendshapes_to_group(["blendShape1", "blendShape2"], 1)
        """
        pass