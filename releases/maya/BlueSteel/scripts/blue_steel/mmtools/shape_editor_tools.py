from maya import cmds, mel
import numpy as np
from blue_steel.api.blendshape import Blendshape

def split_on_axis_selected_blendshape_targets():
    """Split the selected blendshape targets based on their axis."""
    # TODO: add support for inbetweens
    selected_targets = mel.eval("getShapeEditorTreeviewSelection(4);")
    if not selected_targets:
        cmds.warning("Please select a blendshape target to split.")
        return
    targets_to_split = dict()
    for target in selected_targets:
        blendshape_node, weight_index = target.split(".", 1)
        if blendshape_node in targets_to_split:
            targets_to_split[blendshape_node].append(int(weight_index))
        else:
            targets_to_split[blendshape_node] = [int(weight_index)]
    for blendshape_node, weight_indices in targets_to_split.items():
        blendshape = Blendshape(blendshape_node)
        for weight_index in weight_indices:
            weight = blendshape.get_weight_by_id(weight_index)
            if weight is None:
                cmds.warning(f"Could not find weight id '{weight_index}' on '{blendshape_node}'.")
                continue

            # Use full delta so vertex/component indexing is preserved while splitting.
            target_delta = blendshape.get_target_delta(weight)
            axes = ["X", "Y", "Z"]
            orientations = ["Positive", "Negative"]

            for axis_index, current_axis in enumerate(axes):
                axis_values = target_delta[:, axis_index]
                for current_orientation in orientations:
                    new_target_delta = np.zeros_like(target_delta)

                    if current_orientation == "Positive":
                        mask = axis_values > 0.0
                    else:
                        mask = axis_values < 0.0

                    # Keep only the selected axis component for the selected direction.
                    new_target_delta[mask, axis_index] = axis_values[mask]

                    split_target_name = f"{weight}_{current_axis}_{current_orientation}"
                    split_target_weight = blendshape.get_weight_by_name(split_target_name)
                    if split_target_weight is None:
                        split_target_weight = blendshape.add_target(split_target_name)

                    blendshape.set_target_delta(split_target_weight, new_target_delta)


