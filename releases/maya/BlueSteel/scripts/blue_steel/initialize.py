import maya.cmds as cmds

def create_menu():
    menu_name = "BlueSteelMenu"

    if cmds.menu(menu_name, exists=True):
        cmds.deleteUI(menu_name)

    cmds.menu(
        menu_name,
        label="Blue Steel",
        parent="MayaWindow",
        tearOff=True
    )

    cmds.menuItem(
        label="Open Blue Steel",
        command="import blue_steel; blue_steel.show()"
    )