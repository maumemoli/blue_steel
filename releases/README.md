# Blue Steel Releases

This folder contains installable packaging for Blue Steel in Autodesk Maya.

## What Blue Steel Does

Blue Steel manages facial shape systems built on blendshapes, with a UI for:

- Editing primary shape values.
- Creating and managing inbetweens and combos.
- Filtering and inspecting active/related shapes.
- Managing work shapes and linked shape behavior.

## Layout

- [releases/maya](maya): Maya release payload.
- [releases/maya/scripts/blue_steel](maya/scripts/blue_steel): Runtime Python package.
- [releases/maya/drag_into_Maya_to_install.py](maya/drag_into_Maya_to_install.py): Drag-and-drop installer script.

## Quick Start (Maya)

1. Download BlueSteel-v#.#.#zip from the [latest release](https://github.com/maumemoli/blue_steel/releases).
2. Unzip the file and place the Bluesteel folder where you want to keep it or copy it in the may modules directory.
3. Drag [drag_into_Maya_to_install.py](releases/maya/BlueSteel/drag_into_Maya_to_install.py) into Maya.
4. The prompt will ask to locate the module folder and it will create a blue_steel.mod file.
5. The script will also create a BlueSteel shelf.
6. Restart Maya to visualize the icons of the shelf.
7. Launch Blue Steel.

## Dependency: NumPy

Blue Steel requires NumPy in Maya's Python environment.

If NumPy is missing, install it with Maya's `mayapy` executable.

### Windows

```powershell
"C:\Program Files\Autodesk\Maya2026\bin\mayapy.exe" -m pip install numpy
```

### macOS

```bash
"/Applications/Autodesk/maya2026/Maya.app/Contents/bin/mayapy" -m pip install  numpy
```

### Linux

```bash
"/usr/autodesk/maya2026/bin/mayapy" -m pip install numpy
```

Tip: adjust the Maya version in the path (`2026`) to match your installed version.

## Documentation

- Blue Steel workflow wiki: [releases/WIKI.md](WIKI.md)
- MMTools wiki: [releases/MMTOOLS_WIKI.md](MMTOOLS_WIKI.md)