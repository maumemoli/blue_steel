# Built-in
import importlib.util
import re
import os
import sys
import logging

# External
from maya import cmds, mel

#: logger
LOGGER = logging.getLogger(__name__)


def _resolve_mayapy_executable() -> str:
    """Return the mayapy executable path if possible."""
    current_executable = sys.executable
    exe_name = os.path.basename(current_executable).lower()
    if "mayapy" in exe_name:
        return current_executable

    # Fallback for interpreter names that do not include mayapy.
    mayapy_name = "mayapy.exe" if os.name == "nt" else "mayapy"
    sibling_candidate = os.path.join(os.path.dirname(current_executable), mayapy_name)
    if os.path.exists(sibling_candidate):
        return sibling_candidate

    return current_executable


def _detect_maya_version_from_path(path: str) -> str:
    """Extract Maya version from an executable path if present."""
    match = re.search(r"maya(\d{4})", path, re.IGNORECASE)
    if match:
        return match.group(1)
    return "unknown"


def _build_manual_numpy_install_instructions(mayapy_executable: str) -> str:
    """Build OS-specific manual installation instructions for numpy."""
    maya_version = _detect_maya_version_from_path(mayapy_executable)
    os_name = "Windows" if os.name == "nt" else ("macOS" if sys.platform == "darwin" else "Linux")
    quoted_mayapy = f'"{mayapy_executable}"'
    command = f"{quoted_mayapy} -m pip install --user numpy"

    lines = [
        f"Blue Steel install: numpy is required but not installed.",
        f"Detected OS: {os_name}",
        f"Detected Maya version: {maya_version}",
        "Please install numpy manually using Maya Python:",
    ]

    if os_name == "Windows":
        lines.append(f"PowerShell/CMD command: {command}")
    else:
        lines.append(f"Terminal command: {command}")

    return "\n".join(lines)


def _show_numpy_install_popup(mayapy_executable: str) -> None:
    """Show a Maya popup with a selectable manual numpy install command."""
    maya_version = _detect_maya_version_from_path(mayapy_executable)
    os_name = "Windows" if os.name == "nt" else ("macOS" if sys.platform == "darwin" else "Linux")
    quoted_mayapy = f'"{mayapy_executable}"'
    command = f"{quoted_mayapy} -m pip install --user numpy"

    window_name = "BlueSteelNumpyInstallWindow"
    if cmds.window(window_name, exists=True):
        cmds.deleteUI(window_name)

    cmds.window(window_name, title="Blue Steel: NumPy Required", sizeable=False, widthHeight=(860, 180))
    cmds.columnLayout(adjustableColumn=True, rowSpacing=8, columnAttach=("both", 10))
    cmds.text(label="NumPy is required to continue Blue Steel installation.", align="left")
    cmds.text(label=f"Detected OS: {os_name}", align="left")
    cmds.text(label=f"Detected Maya version: {maya_version}", align="left")
    cmds.text(label="If you are trying to install Blue Steel at work, please contact your IT department for assistance.", align="left")
    cmds.text(label="Copy and run this command in PowerShell/CMD/Terminal:", align="left")
    cmds.textField("BlueSteelNumpyInstallCommand", text=command)
    cmds.button(label="Close", command=lambda *_: cmds.deleteUI(window_name))
    cmds.showWindow(window_name)


def ensure_numpy_installed(target_path: str = "") -> bool:
    """Check whether numpy is available in Maya Python.

    Returns:
        bool: True if numpy is available, otherwise False after warning.
    """
    _ = target_path  # compatibility with any existing calls that pass target_path

    if importlib.util.find_spec("numpy") is not None:
        return True

    mayapy_executable = _resolve_mayapy_executable()
    try:
        _show_numpy_install_popup(mayapy_executable)
    except Exception:
        instructions = _build_manual_numpy_install_instructions(mayapy_executable)
        LOGGER.warning(instructions)
        # Keep this function safe to call outside Maya contexts.
        print(instructions)
        cmds.warning("Blue Steel install: numpy is missing. Unable to show popup; see Script Editor for instructions.")
    return False


def onMayaDroppedPythonFile(*args):
    if not ensure_numpy_installed():
        return

    mod_dir = os.path.dirname(__file__)
    template_mod_file = os.path.join(mod_dir, "blue_steel_template.mod")
    shelf_file = os.path.join(mod_dir, "shelves", "shelf_BlueSteel.mel")
    with open(template_mod_file, "r") as fp:
        mod_template = fp.read()
    mod_content = mod_template.replace("<BLUE_STEEL_MOD_PATH>", mod_dir)
    # module_name = mod_template.splitlines()[0].split(" ")[1]
    scripts_dir = os.path.join(mod_dir, "scripts")
    if not scripts_dir in sys.path:
        sys.path.append(scripts_dir)

    user_maya_dir = os.environ.get("MAYA_APP_DIR")
    user_mods_dir = os.path.join(user_maya_dir, "modules")
    if not os.path.isdir(user_mods_dir):
        os.makedirs(user_mods_dir)
    cap = "Blue Steel module file location"
    result = cmds.fileDialog2(caption=cap, dir=user_mods_dir, fileMode=2)
    chosen_dir = result[0]
    chosen_mod_path = os.path.join(chosen_dir, "blue_steel.mod")
    with open(chosen_mod_path, "w+") as fp:
        fp.write(mod_content)
    LOGGER.info(f"Placed Blue Steel mod file at {chosen_mod_path}")

    # we need to load the shelf file to add the Blue Steel shelf to the user's UI
    normalized = os.path.normpath(shelf_file)
    shelf_file_unix = normalized.replace(os.sep, '/')

    if os.path.exists(shelf_file) and cmds.shelfLayout("BlueSteel", exists=True) == False:
        mel.eval(f'loadNewShelf("{shelf_file_unix}")')
