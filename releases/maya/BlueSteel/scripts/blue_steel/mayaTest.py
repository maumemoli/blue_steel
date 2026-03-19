import random
import maya.cmds as cmds

def generate_facs_shapes(total_shapes=1000, separator="_", blendshape_node=None):
    """
    Generate FACS-based shape names for testing BlueSteel performance.
    
    Parameters:
        total_shapes (int): Total number of shapes to generate
        separator (str): Separator for combo shapes
        blendshape_node (str): Existing blendshape node to check for duplicates
    
    Returns:
        list: List of unique shape names
    """
    
    # Get existing shapes from blendshape if provided
    existing_shapes = set()
    if blendshape_node and cmds.objExists(blendshape_node):
        aliases = cmds.aliasAttr(blendshape_node, q=True) or []
        existing_shapes = {aliases[i] for i in range(0, len(aliases), 2)}
        print(f"Found {len(existing_shapes)} existing shapes in {blendshape_node}")
    
    # FACS Action Units and their common names
    facs_primary_shapes = [
        "innerBrowRaiser", "outerBrowRaiser", "browLowerer", "upperLidRaiser",
        "cheekRaiser", "lidTightener", "noseWrinkler", "upperLipRaiser",
        "nasolabialDeepener", "lipCornerPuller", "zygomatic", "lipCornerDepressor",
        "lowerLipDepressor", "chinRaiser", "lipPuckerer", "lipStretcher",
        "lipFunneler", "lipTightener", "lipPressor", "lipsToward",
        "jawDrop", "mouthStretch", "lipBite", "jawThrust",
        "jawSideways", "jawClench", "tongueOut", "eyesClosed",
        "eyeSquint", "noseFlare", "dimpler", "lipSuck",
        "cheekPuff", "cheekSuck", "mouthLeft", "mouthRight",
        "smile", "frown", "fear", "anger", "disgust", "surprise",
        "sadness", "contempt", "eyeBrowFlash", "wink",
        "kissLips", "mouthOpen", "teethShow", "gumShow"
    ]
    
    # Generate different inbetween values
    inbetween_values = [25, 30, 40, 50, 60, 70, 75, 80, 90]
    
    shapes = []
    used_primary_names = set(existing_shapes)  # Start with existing shapes
    
    # Adjust distribution for small numbers
    if total_shapes < 10:
        primary_count = max(2, int(total_shapes * 0.6))
        inbetween_count = max(1, int(total_shapes * 0.3))
        combo_count = max(0, total_shapes - primary_count - inbetween_count - 1)
        combo_inbetween_count = max(0, total_shapes - primary_count - inbetween_count - combo_count)
    else:
        primary_count = max(2, int(total_shapes * 0.20))
        inbetween_count = int(total_shapes * 0.30)
        combo_count = int(total_shapes * 0.30)
        combo_inbetween_count = total_shapes - primary_count - inbetween_count - combo_count
    
    print(f"Generating {total_shapes} NEW shapes (excluding {len(existing_shapes)} existing):")
    print(f"  - {primary_count} Primary shapes")
    print(f"  - {inbetween_count} Inbetween shapes")
    print(f"  - {combo_count} Combo shapes")
    print(f"  - {combo_inbetween_count} Combo inbetween shapes")
    
    # Track used combo combinations to avoid duplicates
    used_combos = set()
    
    # Add existing combos to used_combos set
    for existing in existing_shapes:
        if separator in existing:
            used_combos.add(existing)
    
    # 1. Generate Primary Shapes - NO DUPLICATES
    for i in range(primary_count):
        attempts = 0
        while attempts < 100:  # Prevent infinite loop
            if i < len(facs_primary_shapes):
                candidate_name = facs_primary_shapes[i]
            else:
                base_shape = random.choice(facs_primary_shapes)
                variation = random.choice(['Left', 'Right', 'Upper', 'Lower', 'Inner', 'Outer'])
                candidate_name = f"{base_shape}{variation}"
            
            if candidate_name not in used_primary_names:
                used_primary_names.add(candidate_name)
                shapes.append(candidate_name)
                break
            attempts += 1
        
        if attempts >= 100:
            # Fallback: create a unique name with index
            base_shape = random.choice(facs_primary_shapes)
            candidate_name = f"{base_shape}Gen{i}"
            used_primary_names.add(candidate_name)
            shapes.append(candidate_name)
    
    # Convert to list for sampling (no duplicates guaranteed)
    available_primaries = [name for name in used_primary_names if name not in existing_shapes]
    
    # 2. Generate Inbetween Shapes
    available_inbetweens = []
    for i in range(inbetween_count):
        if available_primaries:
            attempts = 0
            while attempts < 50:
                primary = random.choice(available_primaries)
                value = random.choice(inbetween_values)
                inbetween_name = f"{primary}{value}"
                
                if inbetween_name not in existing_shapes and inbetween_name not in [s for s in shapes]:
                    shapes.append(inbetween_name)
                    available_inbetweens.append(inbetween_name)
                    break
                attempts += 1
            
            if attempts >= 50:
                # Fallback with unique suffix
                primary = random.choice(available_primaries)
                inbetween_name = f"{primary}Gen{i}"
                shapes.append(inbetween_name)
                available_inbetweens.append(inbetween_name)
    
    # 3. Generate Combo Shapes (2-4 components) - NO DUPLICATES
    for i in range(combo_count):
        if len(available_primaries) >= 2:
            max_components = min(4, len(available_primaries))
            num_components = random.randint(2, max_components)
            
            # Keep trying until we get a unique combination
            attempts = 0
            while attempts < 50:  # Prevent infinite loop
                components = random.sample(available_primaries, num_components)
                combo_name = separator.join(sorted(components))  # Sort for consistency
                
                if combo_name not in used_combos and combo_name not in existing_shapes:
                    used_combos.add(combo_name)
                    shapes.append(combo_name)
                    break
                attempts += 1
            
            if attempts >= 50:
                # Fallback: create a simple primary instead
                base_shape = random.choice(facs_primary_shapes)
                fallback_name = f"{base_shape}ComboGen{i}"
                shapes.append(fallback_name)
        else:
            base_shape = random.choice(facs_primary_shapes)
            fallback_name = f"{base_shape}ComboGen{i}"
            shapes.append(fallback_name)
    
    # 4. Generate Combo Inbetween Shapes - NO DUPLICATES
    for i in range(combo_inbetween_count):
        if len(available_primaries) >= 2 and available_inbetweens:
            max_components = min(3, len(available_primaries))
            num_components = random.randint(2, max_components)
            
            # Pick an existing inbetween as one component
            inbetween_shape = random.choice(available_inbetweens)
            
            # Get the primary name from the inbetween (remove numeric suffix)
            primary_from_inbetween = ''.join(char for char in inbetween_shape if not char.isdigit())
            
            # Pick additional primaries (excluding the one already used in inbetween)
            available_for_combo = [p for p in available_primaries if p != primary_from_inbetween]
            
            if len(available_for_combo) >= (num_components - 1):
                attempts = 0
                while attempts < 50:  # Prevent infinite loop
                    additional_components = random.sample(available_for_combo, num_components - 1)
                    
                    # Combine inbetween with other primaries
                    all_components = [inbetween_shape] + additional_components
                    combo_inbetween_name = separator.join(sorted(all_components))
                    
                    if combo_inbetween_name not in used_combos and combo_inbetween_name not in existing_shapes:
                        used_combos.add(combo_inbetween_name)
                        shapes.append(combo_inbetween_name)
                        break
                    attempts += 1
                
                if attempts >= 50:
                    # Fallback: create a simple inbetween
                    if available_primaries:
                        primary = random.choice(available_primaries)
                        value = random.choice(inbetween_values)
                        fallback_name = f"{primary}{value}ComboGen{i}"
                        shapes.append(fallback_name)
            else:
                if available_primaries:
                    primary = random.choice(available_primaries)
                    value = random.choice(inbetween_values)
                    fallback_name = f"{primary}{value}ComboGen{i}"
                    shapes.append(fallback_name)
        else:
            if available_primaries:
                primary = random.choice(available_primaries)
                value = random.choice(inbetween_values)
                fallback_name = f"{primary}{value}ComboGen{i}"
                shapes.append(fallback_name)
    
    # Shuffle to mix the order
    random.shuffle(shapes)
    
    print(f"Generated {len(shapes)} unique new shapes")
    return shapes

# Usage example:
def generate_for_bluesteel_editor(blue_steel_editor, total_shapes=100):
    """
    Generate shapes for an existing BlueSteelEditor instance
    """
    blendshape_node = blue_steel_editor.blendshape.name
    return generate_facs_shapes(total_shapes, "_", blendshape_node)