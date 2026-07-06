import maya.cmds as cmds
import math
HUD_BLENDSHAPE_WEIGHTS_PREFIX = "HUDBlendshapeWeights"
HUD_BLENDSHAPE_WEIGHTS_SECTION = 0
HUD_MASTER_NAME = ""

"""
USAGE: IN THE SCRIPT EDITOR PASTE THE FOLLOWING CODE

TO RUN THE HUD:
Select the head with the blendshape or or the blendShape itself

Run the following code:
import blendShapeHud as bl
blend = bl.get_blend_shape_on_selected_mesh()
if blend:
    # you can set list_combos to False if you want to ignore the combos
    bl.create_master_hud(blend_shape = blend, list_combos = True)
    
TO CLEAR THE HUD:
bl.clear_huds()
    
"""

def get_section_capacity():
    model_panels = cmds.getPanel(type="modelPanel")
    for panel in model_panels:
        model_editor = cmds.modelPanel(panel, query=True, modelEditor=True)
        width = cmds.modelEditor(model_editor, q=True,w= True)
        height = cmds.modelEditor(model_editor, q=True,h= True)
        
        if not cmds.control(panel, q=True, isObscured=True):
            return int(((height/2))/30) 

def get_data_alignment_size():
    model_panels = cmds.getPanel(type="modelPanel")
    for panel in model_panels:
        model_editor = cmds.modelPanel(panel, query=True, modelEditor=True)
        width = cmds.modelEditor(model_editor, q=True,w= True)
        if not cmds.control(panel, q=True, isObscured=True):
            return(int(width/6))
            
        
def get_blend_shape_on_selected_mesh():
    sel = cmds.ls(sl=True)
    # Get the history of the mesh and filter blendShapes
    if cmds.nodeType(sel[0]) == "blendShape":
        return sel[0]
    
    history = cmds.listHistory(sel[0], pruneDagObjects=True) or []
    blendshapes = [node for node in history if cmds.nodeType(node) == "blendShape"]
    if blendshapes:
        return blendshapes[0]

def get_blend_shape_value(blend_shape, weight_name):
    return cmds.getAttr("{0}.{1}".format(blend_shape, weight_name))
    
    
def find_heads_up_in_section(section):
    heads = cmds.headsUpDisplay(q=True, lh=True)
    section_blocks = []
    blocks = []
    for h in heads:
        current_section = cmds.headsUpDisplay(h, q=True, section=True)
        if current_section == section:
            section_blocks.append(h)
            blocks.append(cmds.headsUpDisplay(h, q=True, block=True))
    section_blocks = [s for _, s in sorted(zip(blocks, section_blocks))]
    return section_blocks
    
def displayGrid():
    heads = find_heads_up_in_section(HUD_BLENDSHAPE_WEIGHTS_SECTION)
    for h in heads:
        cmds.headsUpDisplay(h, sg=True)

def clear_section(section):
    huds = find_heads_up_in_section(section) or []
    for hud in huds:
        cmds.headsUpDisplay(hud, rem=True)

def get_weight_driver(blend_shape, weight_name):
    connections = cmds.listConnections("{0}.{1}".format(blend_shape, weight_name), source=True, destination=False) or []
    if connections:
        return connections[0]
    return None
    
def refresh_hud(hud_name,  blend_shape, list_combos = False):
    block_width = get_data_alignment_size()
    section = HUD_BLENDSHAPE_WEIGHTS_SECTION
    prefix = HUD_BLENDSHAPE_WEIGHTS_PREFIX
    if not cmds.objExists(blend_shape):
        clear_huds()
        return
    clear_child_huds()
    capacity = get_section_capacity()
    weights = cmds.listAttr("{0}.weight".format(blend_shape), multi=True) or []
    block_id =  cmds.headsUpDisplay(nextFreeBlock= section)
    active_weights_names = list()
    active_weights_values = list()
    for weight_name in weights:
        if not list_combos:
            driver = get_weight_driver(blend_shape, weight_name)
            if driver is not None and cmds.nodeType(driver) == "combinationShape":
                # print("Skipping combo weight: {0}".format(weight_name))
                continue
        weight_value = cmds.getAttr("{0}.{1}".format(blend_shape, weight_name))
        if not math.isclose(weight_value, 0.0, abs_tol=1e-6):
            active_weights_names.append(weight_name)
            active_weights_values.append(weight_value)
            
    for weight_name, weight_value in zip(active_weights_names, active_weights_values):
        block_id = cmds.headsUpDisplay(nextFreeBlock= section)
        if section == 4 and block_id == capacity:
            cmds.headsUpDisplay(hud_name,e=True, label = "...")
            return
        hud_name = "{0}_{1}_{2}".format(prefix, blend_shape, weight_name)
        weight_string = str(round(weight_value, 4))
        
        if block_id == capacity:            
            section+=1
            clear_section(section)
            block_id = cmds.headsUpDisplay(nextFreeBlock= section)
        
        cmds.headsUpDisplay(hud_name,
                            section = section,
                            padding = 4,
                            block= block_id,
                            label = "{0}: {1}".format(weight_name, weight_string),
                            blockSize='small',
                            dw =0,
                            labelFontSize='small',
                            ba= "left",
                            dp= 3,)

            
    
def clear_child_huds():
    huds = cmds.headsUpDisplay(q=True, lh=True) or []
    for hud in huds:
        if hud.startswith(HUD_BLENDSHAPE_WEIGHTS_PREFIX) and hud != HUD_MASTER_NAME:
            cmds.headsUpDisplay(hud, rem=True)

def hud_exists(blend_shape):
    hud_name = "{0}_{1}".format(HUD_BLENDSHAPE_WEIGHTS_PREFIX, blend_shape)
    return cmds.headsUpDisplay(hud_name, q=True, ex=True)

def clear_huds():
    huds = cmds.headsUpDisplay(q=True, lh=True) or []
    for hud in huds:
        if hud.startswith(HUD_BLENDSHAPE_WEIGHTS_PREFIX):
            cmds.headsUpDisplay(hud, rem=True)

def create_master_hud(blend_shape, list_combos= False):
    if not blend_shape:
        return
    global HUD_MASTER_NAME
    clear_huds()
    
    prefix = HUD_BLENDSHAPE_WEIGHTS_PREFIX
    section = HUD_BLENDSHAPE_WEIGHTS_SECTION
    block_id = cmds.headsUpDisplay(nextFreeBlock= section)
    combo_text = "(Hidden Combos)" if not list_combos else ""
    display_hud_name = "{0}_{1}".format(HUD_BLENDSHAPE_WEIGHTS_PREFIX, blend_shape)
    # check if the hud exists and remove it
    if cmds.headsUpDisplay(display_hud_name, q=True, ex=True):
        cmds.headsUpDisplay(display_hud_name, rem = True)
    # let's create the heads up display
    cmds.headsUpDisplay(display_hud_name,
                        padding=0,
                        section = section,
                        block= block_id,
                        c=lambda: refresh_hud(display_hud_name, blend_shape, list_combos),
                        label = "{0} {1}".format(blend_shape, combo_text),
                        blockSize='small',
                        labelFontSize='large',
                        ba= "left",
                        dp= 3,
                        atr=True)
    HUD_MASTER_NAME = display_hud_name
    return display_hud_name
