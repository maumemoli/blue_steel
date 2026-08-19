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
        command="from blue_steel.ui.editor import mainWindow; mainWindow.show()"
    )
