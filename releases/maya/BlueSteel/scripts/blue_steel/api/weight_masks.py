from .blendshape import Blendshape
from maya import cmds
import numpy as np

def delta_vectors_length_to_weight_mask(delta_vectors: np.ndarray):
    """
    Convert the lengths of delta vectors to a weight mask.

    Parameters:
        delta_vectors (np.ndarray): Array of delta vectors with shape (N, 3)

    Returns:
        np.ndarray: Array of weights corresponding to each delta vector
    """
    pass

def get_target_delta_vectors(blendshape_node: str,
                             input_target_index: int,
                             target_value: int = 6000) -> np.ndarray:
    """
    Get the delta vectors for a specific target shape in a blendshape node.

    Parameters:
        blendshape_node (str): The name of the blendshape node
        input_target_index (int): The index of the target shape
        target_value (int): The target value for the blendshape (default: 6000)
    Returns:
        np.ndarray: Array of delta vectors for the target shape
    """
    if not cmds.objExists(blendshape_node) or not cmds.nodeType(blendshape_node) == "blendShape":
        raise ValueError(f"Blendshape node '{blendshape_node}' does not exist or is not a blendShape.")
    blendshape = Blendshape(blendshape_node)
    return blendshape.get_target_delta(input_target_index, target_value)

