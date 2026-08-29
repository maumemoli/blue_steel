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

    @property
    def name(self)-> str or None: # type: ignore
        if self.blendshape:
            return cmds.getAttr(f"{self.blendshape}.targetDirectory[{self.index}].directoryName")
        return None