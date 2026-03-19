from maya import cmds


class TargetDirectory(object):
    """
    A class to represent a target directory with a name and an ID.
    """
    def __init__( self, index: int, blendshape: str):
        self.index = index
        self.blendshape = blendshape
    
    def __str__(self) -> str:
        """
        Returns the name of the target directory as its string representation.
        Returns:
            str: The name of the target directory.
        """
        return self.name

    def __eq__(self, value):
        """
        Compares two TargetDirectory objects for equality based on their ID and blendshape.
        Parameters:
            value (TargetDirectory): The TargetDirectory object to compare with.
        Returns:
            bool: True if the two TargetDirectory objects are equal, False otherwise.   
        """
        if isinstance(value, TargetDirectory):
            return self.index == value.index and self.blendshape == value.blendshape
        elif isinstance(value, int):
            return self.index == value
        elif isinstance(value, str):
            return self.name == value
    
        return False
    
    def __repr__(self) -> str:
        """
        Returns a string representation of the TargetDirectory object.  
        This includes the name and ID of the target directory.
        Returns:
            str: A string representation of the TargetDirectory object.
        Example:
            >>> td = TargetDirectory(id=2, blendshape="blendShape1")
        """
        return f"TargetDirectory: (name: \"{self.name}\", index: {self.index}, blendshape: {self.blendshape})"

    # @staticmethod
    # def DEFAULT():
    #     return TargetDirectory(index=0, blendshape=None)

    @property
    def name(self)-> str or None: # type: ignore
        if self.blendshape:
            return cmds.getAttr(f"{self.blendshape}.targetDirectory[{self.index}].directoryName")
        return None

    # @property
    # def parent_index(self)-> int or None: # type: ignore
    #     if self.blendshape:
    #         parent_index = cmds.getAttr(f"{self.blendshape}.targetDirectory[{self.index}].parentIndex")
    #         return parent_index
    #     return None

    # @parent_index.setter
    # def parent_index(self, index: int):
    #     if self.blendshape:
    #         old_parent_index = self.parent_index
    #         cmds.setAttr(f"{self.blendshape}.targetDirectory[{self.index}].parentIndex", index)
    #         # we need to remove this directory from the old parent's child indices
    #         old_parent_attr = f"{self.blendshape}.targetDirectory[{old_parent_index}].childIndices"
    #         old_parent_child_indices = cmds.getAttr(old_parent_attr) or []
    #         print("Getting old parent child indices:", old_parent_child_indices)
    #         # we need to set the index to negative to indicate it's a directory
    #         dir_index = -self.index
    #         if dir_index in old_parent_child_indices:
    #             old_parent_child_indices.remove(dir_index)
    #             print("Setting old parent child indices to:", old_parent_child_indices)
    #             cmds.setAttr(old_parent_attr,
    #                          old_parent_child_indices,
    #                          type="Int32Array")
    #         # we need to add this directory to the new parent's child indices
    #         new_parent_attr = f"{self.blendshape}.targetDirectory[{index}].childIndices"
    #         new_parent_child_indices = cmds.getAttr(new_parent_attr) or []
    #         if dir_index not in new_parent_child_indices:
    #             new_parent_child_indices.append(dir_index)
    #             cmds.setAttr(new_parent_attr,
    #                          new_parent_child_indices,
    #                          type="Int32Array")
    # @property
    # def child_indices(self) -> list:
    #     if self.blendshape:
    #         return cmds.getAttr(f"{self.blendshape}.targetDirectory[{self.index}].childIndices") or []
    #     return []
    
    # @child_indices.setter
    # def child_indices(self, indices: list):
    #     if self.blendshape:
    #         cmds.setAttr(f"{self.blendshape}.targetDirectory[{self.index}].childIndices",
    #                      indices,
    #                      type="Int32Array")
    
    # @property
    # def child_target_indices(self)-> list:
    #     return [idx for idx in self.child_indices if idx >=0]
    
    # @property
    # def child_target_dir_indices(self) -> list:
    #     return [abs(idx) for idx in self.child_indices if idx <0]
    
    # @property
    # def hierarchy_level(self) -> int:
    #     """
    #     Returns the hierarchy level of the target directory in the blendshape hierarchy.
    #     Returns:
    #         int: The hierarchy level of the target directory.
    #     Example:
    #         >>> td = TargetDirectory(id=2, blendshape="blendShape1")
    #         >>> print(td.hierarchy_level)
    #         2
    #     """
    #     level = 0
    #     current_dir = self
    #     counter = 0
    #     while current_dir.parent_index != 0 or counter <=100:
    #         counter +=1     
    #         parent_index = current_dir.parent_index
    #         current_dir = TargetDirectory(index=parent_index, blendshape=self.blendshape)
    #         level +=1
    #         if current_dir.index == 0:
    #             break
    #     return level

    # @property
    # def full_path(self) -> str:
    #     """
    #     Returns the full path of the target directory in the blendshape hierarchy.
    #     Returns:
    #         str: The full path of the target directory.
    #     Example:
    #         >>> td = TargetDirectory(id=2, blendshape="blendShape1")
    #         >>> print(td.full_path)
    #         RootGroup/MyGroup/SubGroup
    #     """
    #     path_parts = []
    #     current_dir = self
    #     counter = 0
    #     while current_dir.parent_index != 0 or counter <=100:
    #         counter +=1     
    #         parent_index = current_dir.parent_index
    #         path_parts.append(current_dir.name)
    #         print("Current dir:", current_dir.name, "Parent index:", parent_index)
    #         current_dir = TargetDirectory(index=parent_index, blendshape=self.blendshape)
    #         print("Parent dir:", current_dir.name, "Index:", current_dir.index)
    #         if current_dir.index == 0:
    #             break
    #     path_parts.reverse()
    #     return "|".join(path_parts)