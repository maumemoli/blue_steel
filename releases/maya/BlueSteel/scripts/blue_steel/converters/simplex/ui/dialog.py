from .... import env
from maya import cmds
from ..commands import (get_blendshape_from_simplex_node,
                        get_available_simplex_nodes,
                        get_controller_from_simplex_node,
                        get_mesh_from_simplex_node,
                        load_simplex_plugin,
                        simplex_plugin_loaded,
                        add_simplex_shapes_to_editor)
import maya.OpenMayaUI as omui

if env.MAYA_VERSION > 2024:
    from PySide6 import QtCore, QtGui, QtWidgets
    from shiboken6 import wrapInstance
else:
    from PySide2 import QtCore, QtGui, QtWidgets
    from shiboken2 import wrapInstance


def get_maya_main_window():
    """Get Maya's main window as a Qt object"""
    main_window_ptr = omui.MQtUtil.mainWindow()
    if main_window_ptr is not None:
        return wrapInstance(int(main_window_ptr), QtWidgets.QWidget)
    return None


class SimplexConverterDialog(QtWidgets.QDialog):
    """Dialog for converting Simplex systems to Blue Steel"""
    
    def __init__(self, parent=None):
        super(SimplexConverterDialog, self).__init__(parent)
        self.setWindowTitle("Convert Simplex to Blue Steel")
        self.setMinimumWidth(400)
        self.setMinimumHeight(500)
        
        # Store result data
        self.result_data = None
        
        # Setup UI
        self.setup_ui()
        self.create_connections()
        
        # Populate the simplex nodes list
        self.refresh_simplex_nodes()
    
    def setup_ui(self):
        """Set up the user interface"""
        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)
        
        # Title label
        title_label = QtWidgets.QLabel("Convert Simplex System")
        title_font = title_label.font()
        title_font.setPointSize(12)
        title_font.setBold(True)
        title_label.setFont(title_font)
        main_layout.addWidget(title_label)
        
        # Simplex Nodes section
        nodes_label = QtWidgets.QLabel("Simplex Nodes:")
        main_layout.addWidget(nodes_label)
        
        # Add refresh button for simplex nodes
        nodes_header_layout = QtWidgets.QHBoxLayout()
        self.refresh_nodes_btn = QtWidgets.QPushButton("Refresh")
        self.refresh_nodes_btn.setMaximumWidth(80)
        nodes_header_layout.addStretch()
        nodes_header_layout.addWidget(self.refresh_nodes_btn)
        main_layout.addLayout(nodes_header_layout)
        
        # Simplex nodes list
        self.simplex_nodes_list = QtWidgets.QListWidget()
        self.simplex_nodes_list.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.simplex_nodes_list.setMaximumHeight(150)
        main_layout.addWidget(self.simplex_nodes_list)
        
        # Controller section
        controller_label = QtWidgets.QLabel("Controller:")
        main_layout.addWidget(controller_label)
        
        self.controller_field = QtWidgets.QLineEdit()
        self.controller_field.setPlaceholderText("Controller object name")
        main_layout.addWidget(self.controller_field)
        
        # Setup completer for controller field
        self.controller_completer = QtWidgets.QCompleter()
        self.controller_completer.setCaseSensitivity(QtCore.Qt.CaseInsensitive)
        self.controller_completer.setFilterMode(QtCore.Qt.MatchContains)
        self.controller_field.setCompleter(self.controller_completer)
        
        # Mesh section
        mesh_label = QtWidgets.QLabel("Mesh:")
        main_layout.addWidget(mesh_label)
        
        self.mesh_field = QtWidgets.QLineEdit()
        self.mesh_field.setPlaceholderText("Mesh object name")
        main_layout.addWidget(self.mesh_field)
        
        # Setup completer for mesh field
        self.mesh_completer = QtWidgets.QCompleter()
        self.mesh_completer.setCaseSensitivity(QtCore.Qt.CaseInsensitive)
        self.mesh_completer.setFilterMode(QtCore.Qt.MatchContains)
        self.mesh_field.setCompleter(self.mesh_completer)
        
        # Options section
        main_layout.addSpacing(10)
        options_label = QtWidgets.QLabel("Options:")
        main_layout.addWidget(options_label)
        
        self.merge_sides_checkbox = QtWidgets.QCheckBox("Merge Sides (L/R)")
        self.merge_sides_checkbox.setToolTip("Merge left and right sides into single shapes")
        main_layout.addWidget(self.merge_sides_checkbox)
        
        # Level range
        level_layout = QtWidgets.QHBoxLayout()
        level_label = QtWidgets.QLabel("Level Range:")
        self.min_level_spin = QtWidgets.QSpinBox()
        self.min_level_spin.setMinimum(1)
        self.min_level_spin.setMaximum(10)
        self.min_level_spin.setValue(1)
        self.min_level_spin.setMaximumWidth(60)
        
        level_to_label = QtWidgets.QLabel("to")
        
        self.max_level_spin = QtWidgets.QSpinBox()
        self.max_level_spin.setMinimum(1)
        self.max_level_spin.setMaximum(10)
        self.max_level_spin.setValue(10)
        self.max_level_spin.setMaximumWidth(60)
        
        level_layout.addWidget(level_label)
        level_layout.addWidget(self.min_level_spin)
        level_layout.addWidget(level_to_label)
        level_layout.addWidget(self.max_level_spin)
        level_layout.addStretch()
        main_layout.addLayout(level_layout)
        
        # Add stretch to push buttons to bottom
        main_layout.addStretch()
        
        # Button section
        button_layout = QtWidgets.QHBoxLayout()
        button_layout.addStretch()
        
        self.convert_btn = QtWidgets.QPushButton("Convert")
        self.convert_btn.setMinimumWidth(100)
        self.convert_btn.setDefault(True)
        
        self.cancel_btn = QtWidgets.QPushButton("Cancel")
        self.cancel_btn.setMinimumWidth(100)
        
        button_layout.addWidget(self.convert_btn)
        button_layout.addWidget(self.cancel_btn)
        main_layout.addLayout(button_layout)
    
    def create_connections(self):
        """Create signal connections"""
        self.simplex_nodes_list.itemSelectionChanged.connect(self.on_simplex_node_selected)
        self.refresh_nodes_btn.clicked.connect(self.refresh_simplex_nodes)
        self.controller_field.textChanged.connect(self.update_controller_completer)
        self.mesh_field.textChanged.connect(self.update_mesh_completer)
        self.convert_btn.clicked.connect(self.on_convert)
        self.cancel_btn.clicked.connect(self.reject)
    
    def get_transform_nodes_without_geometry(self):
        """Get all transform nodes that don't have geometry children"""
        all_transforms = cmds.ls(type='transform') or []
        transforms_without_geo = []
        
        for transform in all_transforms:
            # Check if the transform has any shape children
            shapes = cmds.listRelatives(transform, shapes=True, noIntermediate=True) or []
            if not shapes:
                transforms_without_geo.append(transform)
        
        return transforms_without_geo
    
    def get_geometry_nodes(self):
        """Get all mesh geometry nodes"""
        # Get all mesh transforms
        meshes = cmds.ls(type='mesh', noIntermediate=True) or []
        geometry_transforms = []
        
        for mesh in meshes:
            # Get the transform parent
            parent = cmds.listRelatives(mesh, parent=True)
            if parent:
                geometry_transforms.append(parent[0])
        
        return list(set(geometry_transforms))  # Remove duplicates
    
    def update_controller_completer(self, text):
        """Update the controller field completer with matching transforms"""
        if len(text) < 1:  # Only search after typing at least 1 character
            return
        
        transforms = self.get_transform_nodes_without_geometry()
        model = QtCore.QStringListModel(transforms)
        self.controller_completer.setModel(model)
    
    def update_mesh_completer(self, text):
        """Update the mesh field completer with matching geometries"""
        if len(text) < 1:  # Only search after typing at least 1 character
            return
        
        geometries = self.get_geometry_nodes()
        model = QtCore.QStringListModel(geometries)
        self.mesh_completer.setModel(model)
    
    def refresh_simplex_nodes(self):
        """Refresh the list of simplex nodes in the scene"""

        
        self.simplex_nodes_list.clear()
        simplex_nodes = get_available_simplex_nodes()
        
        if simplex_nodes:
            for node in simplex_nodes:
                self.simplex_nodes_list.addItem(node)
        else:
            # Add a message item if no nodes found
            item = QtWidgets.QListWidgetItem("No Simplex nodes found")
            item.setFlags(QtCore.Qt.NoItemFlags)
            item.setForeground(QtGui.QColor(128, 128, 128))
            self.simplex_nodes_list.addItem(item)
    
    def on_simplex_node_selected(self):
        """Handle simplex node selection"""
        
        selected_items = self.simplex_nodes_list.selectedItems()
        if not selected_items:
            return
        
        simplex_node = selected_items[0].text()
        
        # Check if it's a valid node (not the "no nodes" message)
        if not cmds.objExists(simplex_node):
            return
        
        # Get and set controller
        controller = get_controller_from_simplex_node(simplex_node)
        if controller:
            self.controller_field.setText(controller)
        else:
            self.controller_field.clear()
        
        # Get and set mesh
        mesh = get_mesh_from_simplex_node(simplex_node)
        if mesh:
            self.mesh_field.setText(mesh)
        else:
            self.mesh_field.clear()
    
    def validate_inputs(self):
        """Validate the input fields"""
        selected_items = self.simplex_nodes_list.selectedItems()
        if not selected_items:
            QtWidgets.QMessageBox.warning(
                self,
                "No Simplex Node Selected",
                "Please select a Simplex node from the list."
            )
            return False
        
        simplex_node = selected_items[0].text()
        if not cmds.objExists(simplex_node):
            QtWidgets.QMessageBox.warning(
                self,
                "Invalid Simplex Node",
                "The selected Simplex node does not exist."
            )
            return False
        
        controller = self.controller_field.text().strip()
        if not controller:
            QtWidgets.QMessageBox.warning(
                self,
                "No Controller",
                "Please specify a controller object."
            )
            return False
        
        if not cmds.objExists(controller):
            QtWidgets.QMessageBox.warning(
                self,
                "Invalid Controller",
                f"The controller '{controller}' does not exist in the scene."
            )
            return False
        
        mesh = self.mesh_field.text().strip()
        if not mesh:
            QtWidgets.QMessageBox.warning(
                self,
                "No Mesh",
                "Please specify a mesh object."
            )
            return False
        
        if not cmds.objExists(mesh):
            QtWidgets.QMessageBox.warning(
                self,
                "Invalid Mesh",
                f"The mesh '{mesh}' does not exist in the scene."
            )
            return False
        
        # Validate level range
        if self.min_level_spin.value() > self.max_level_spin.value():
            QtWidgets.QMessageBox.warning(
                self,
                "Invalid Level Range",
                "Minimum level cannot be greater than maximum level."
            )
            return False
        
        return True
    
    def on_convert(self):
        """Handle convert button click"""
        if not self.validate_inputs():
            return
        
        # Store the result data
        selected_items = self.simplex_nodes_list.selectedItems()
        self.result_data = {
            'simplex_node': selected_items[0].text(),
            'blendshape_node': get_blendshape_from_simplex_node(selected_items[0].text()),
            'controller': self.controller_field.text().strip(),
            'mesh': self.mesh_field.text().strip(),
            'merge_sides': self.merge_sides_checkbox.isChecked(),
            'level_range': (self.min_level_spin.value(), self.max_level_spin.value())
        }
        
        self.accept()
    
    def get_result(self):
        """Get the dialog result data"""
        return self.result_data


def show_simplex_converter_dialog():
    """Show the Simplex converter dialog"""
    
    # Check if Simplex plugin is loaded
    if not simplex_plugin_loaded():
        reply = QtWidgets.QMessageBox.question(
            get_maya_main_window(),
            "Simplex Plugin Not Loaded",
            "The Simplex plugin is not loaded. Would you like to load it now?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.Yes
        )
        
        if reply == QtWidgets.QMessageBox.Yes:
            if not load_simplex_plugin():
                QtWidgets.QMessageBox.critical(
                    get_maya_main_window(),
                    "Plugin Load Failed",
                    "Failed to load the Simplex plugin. Please load it manually."
                )
                return None
        else:
            return None
    
    # Create and show dialog
    dialog = SimplexConverterDialog(parent=get_maya_main_window())
    result = dialog.exec_()
    
    if result == QtWidgets.QDialog.Accepted:
        return dialog.get_result()
    
    return None

