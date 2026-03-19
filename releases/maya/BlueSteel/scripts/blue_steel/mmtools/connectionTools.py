from maya import cmds


def connect_same_name_attributes():
    """Connect attributes with the same name between two nodes."""
    sel = cmds.ls (selection=True)
    if len(sel) != 2:
        cmds.warning ("Please select exactly two nodes.")
        return
    source_node, target_node = sel
    attrs1 = cmds.listAttr (source_node, keyable=True)
    attrs2 = cmds.listAttr (target_node, keyable=True)
    if not attrs1 or not attrs2:
        cmds.warning ("Both selected nodes must have keyable attributes.")
        return
    common_attrs = set(attrs1) & set(attrs2)
    if not common_attrs:
        cmds.warning ("No common keyable attributes found between the selected nodes.")
        return
    for attr in common_attrs:
        try:
            cmds.connectAttr (f"{source_node}.{attr}", f"{target_node}.{attr}", force=True)
            print (f"Connected {source_node}.{attr} to {target_node}.{attr}")
        except Exception as e:
            print (f"Failed to connect {source_node}.{attr} to {target_node}.{attr}: {e}")