from maya import cmds
import maya.OpenMayaUI as omui
from maya.app.general.mayaMixin import MayaQWidgetDockableMixin
from .. import smartCluster as smc
from .. import meshTools as mt
from .. import shape_editor_tools
from .. import connectionTools as ct
from ... import env
from ...ui.common.frameLayout import FrameLayout
from ...ui.common.icons import *
from ...env import MAYA_VERSION
from ...api.mayaUtils import undoable
import os
import sys

if env.MAYA_VERSION > 2024:
    from PySide6 import QtGui, QtWidgets, QtCore
    from shiboken6 import wrapInstance
else:
    from PySide2 import QtGui, QtWidgets, QtCore
    from shiboken2 import wrapInstance

WINDOW =None

def get_maya_main_window():
    """Get Maya's main window as a Qt object"""
    main_window_ptr = omui.MQtUtil.mainWindow()
    if main_window_ptr is not None:
        return wrapInstance(int(main_window_ptr), QtWidgets.QWidget)
    return None



class MmToolsUI (MayaQWidgetDockableMixin , QtWidgets.QMainWindow):
    MAYA_MAIN_WINDOW = get_maya_main_window()

    def __init__(self, title="MMTools", parent =MAYA_MAIN_WINDOW ):
        self.delete_instences()
        super(MmToolsUI , self).__init__(parent= parent)
        self.setObjectName (title)
        self.title = title
        self.collapsible = list()
        self.setWindowTitle(self.title)
        self.adjustSize()
        self.mirror_cluster_axis = "X"
        self.setAttribute (QtCore.Qt.WA_DeleteOnClose)
        # The deleteInstances() dose not remove the workspace control, and we need to remove it manually
        workspace_control_name = '{}WorkspaceControl'.format(self.objectName() )
        self.delete_control (workspace_control_name)
        # this class is inheriting MayaQWidgetDockableMixin.show(), which will e
        # ventually call maya.cmds.workspaceControl.
        # I'm calling it again, since the MayaQWidgetDockableMixin dose not have the option to use the
        # "tabToControl" flag,
        # which was the only way i found i can dock my window next to the channel controls,
        # attributes editor and modelling toolkit.
        self.show (dockable=True  , floating=True)


        # self.content.adjustSize()

        # Creates a widget.
        self.mainWidget=QtWidgets.QWidget ()
        self.mainWidget.setMinimumWidth(180)
        # Apply the widget as the central widget of the QMainWindow.
        self.setCentralWidget(self.mainWidget)
        # create a scroll area

        # Create a vertical layout
        mainLayout=QtWidgets.QVBoxLayout()
        # Apply the layout to the widget.
        self.mainWidget.setLayout(mainLayout)
        clusters_frame_layout=FrameLayout( 'Cluster Tools' )
        # firstFrameLayout.setColor( 50 , 50 , 50 )
        create_cluster_btn=QtWidgets.QPushButton( 'Create/Paint Cluster' )
        create_cluster_btn.clicked.connect(smc.make_paint_cluster)
        toggle_cluster_btn = QtWidgets.QPushButton( 'Toggle Cluster on/off' )
        toggle_cluster_btn.clicked.connect (smc.toggle_cluster_state)

        select_cluster_btn = QtWidgets.QPushButton( 'Select latest cluster' )
        select_cluster_btn.clicked.connect(smc.cycle_selected_clusters)

        update_cluster_list = QtWidgets.QPushButton( 'Update Cluster List' )
        update_cluster_list.clicked.connect(smc.update_clusters_list_with_selection)

        # mirror cluster layout
        mirror_cluster_widget = QtWidgets.QWidget()
        mirror_widget_layout = QtWidgets.QHBoxLayout()
        mirror_widget_layout.setContentsMargins(0, 0, 0, 0)
        mirror_widget_layout.setSpacing(2)
        mirror_cluster_widget.setLayout(mirror_widget_layout)

        mirror_cluster_btn = QtWidgets.QPushButton( 'Mirror Cluster' )
        mirror_cluster_btn.clicked.connect (smc.mirror_selected_cluster)



        x_button = QtWidgets.QPushButton( 'X' )
        x_button.setCheckable(True)
        x_button.setFixedWidth (25)
        x_button.setAutoExclusive(True)
        x_button.setChecked(True)
        # x_button.clicked.connect(set_axis)

        y_button = QtWidgets.QPushButton( 'Y' )
        y_button.setFixedWidth(25)
        y_button.setCheckable(True)
        y_button.setAutoExclusive (True)

        z_button = QtWidgets.QPushButton( 'Z' )
        z_button.setCheckable(True)
        z_button.setFixedWidth (25)
        z_button.setAutoExclusive (True)

        # button group
        self.mirror_axis_grp_btn = QtWidgets.QButtonGroup()
        self.mirror_axis_grp_btn.addButton(x_button)
        self.mirror_axis_grp_btn.addButton(y_button)
        self.mirror_axis_grp_btn.addButton(z_button)
        self.mirror_axis_grp_btn.buttonClicked.connect (self.change_mirror_cluster_axis)
        # adding to layout
        mirror_widget_layout.addWidget(mirror_cluster_btn)
        mirror_widget_layout.addWidget (x_button)
        mirror_widget_layout.addWidget (y_button)
        mirror_widget_layout.addWidget (z_button)

        smooth_flood_btn = QtWidgets.QPushButton( 'Smooth Flood Weights' )
        smooth_flood_btn.clicked.connect (smc.smooth_flood)

        link_cluster_btn = QtWidgets.QPushButton( 'Link Mirrored Cluster' )
        link_cluster_btn.clicked.connect(smc.link_mirrored_cluster)

        reset_transformation_btn = QtWidgets.QPushButton( 'Reset Transformations' )
        reset_transformation_btn.clicked.connect(smc.reset_transformations)



        clusters_frame_layout.addWidget(create_cluster_btn)
        clusters_frame_layout.addWidget(toggle_cluster_btn)
        clusters_frame_layout.addWidget (select_cluster_btn)
        clusters_frame_layout.addWidget (update_cluster_list)
        clusters_frame_layout.addWidget (mirror_cluster_widget)
        clusters_frame_layout.addWidget (smooth_flood_btn)
        clusters_frame_layout.addWidget (link_cluster_btn)
        clusters_frame_layout.addWidget (reset_transformation_btn)

        # Mesh tools frame layout
        mesh_tools_frame_layout = FrameLayout( 'Mesh Tools' )
        copy_vertex_pos_btn = QtWidgets.QPushButton( 'Copy Vtx Positions' )
        copy_vertex_pos_btn.clicked.connect(mt.copy_selected_mesh_vertex_position)
        mesh_tools_frame_layout.addWidget(copy_vertex_pos_btn)

        paste_vertex_pos_btn = QtWidgets.QPushButton( 'Paste Vtx Positions' )
        paste_vertex_pos_btn.clicked.connect(mt.paste_vertex_positions_to_selected_mesh)
        mesh_tools_frame_layout.addWidget(paste_vertex_pos_btn)

        update_intermediate_btn = QtWidgets.QPushButton( 'Update Intermediate Object' )
        update_intermediate_btn.clicked.connect(mt.update_intermediate_object)
        mesh_tools_frame_layout.addWidget(update_intermediate_btn)

        # Attribute tools frame layout
        attribute_tools_frame_layout = FrameLayout( 'Attribute Tools' )
        connect_same_name_btn = QtWidgets.QPushButton( 'Connect Same Name Attributes' )
        connect_same_name_btn.clicked.connect(ct.connect_same_name_attributes)
        attribute_tools_frame_layout.addWidget(connect_same_name_btn)

        # Blendshape Editor Tools frame layout
        blendshape_editor_frame_layout = FrameLayout( 'Blendshape Editor Tools' )
        split_selected_target_btn = QtWidgets.QPushButton( 'Split XYZ Selected Target' )
        split_selected_target_btn.clicked.connect(shape_editor_tools.split_on_axis_selected_blendshape_targets)
        blendshape_editor_frame_layout.addWidget(split_selected_target_btn)
        filler = QtWidgets.QSpacerItem( 20 , 40 , QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Expanding)

        bake_shapes_frame_layout = FrameLayout( 'Duplicate On Timeline Range' )
        # we need to create a layout with a frame range and a number of steps
        duplicate_on_timeline_range_widget = QtWidgets.QWidget()
        duplicate_on_timeline_range_layout = QtWidgets.QVBoxLayout()
        duplicate_on_timeline_range_layout.setContentsMargins(0, 0, 0, 0)
        duplicate_on_timeline_range_widget.setLayout(duplicate_on_timeline_range_layout)
        time_range_layout = QtWidgets.QHBoxLayout()
        time_range_layout.setContentsMargins(0, 0, 0, 0)
        start_frame_label = QtWidgets.QLabel( 'Start:' )
        self.start_frame_spinbox = QtWidgets.QSpinBox()
        self.start_frame_spinbox.setMinimum(-100000)
        self.start_frame_spinbox.setMaximum(100000)
        self.start_frame_spinbox.setValue(int(cmds.playbackOptions(q=True, min=True)))
        self.duplicate_num_label = QtWidgets.QLabel( '#' )
        self.duplicate_num_spinbox = QtWidgets.QSpinBox()
        self.duplicate_num_spinbox.setMinimum(1)
        self.duplicate_num_spinbox.setMaximum(10)
        self.duplicate_num_spinbox.setValue(3)
        end_frame_label = QtWidgets.QLabel( 'End:' )
        self.end_frame_spinbox = QtWidgets.QSpinBox()
        self.end_frame_spinbox.setMinimum(-100000)
        self.end_frame_spinbox.setMaximum(100000)
        self.end_frame_spinbox.setValue(int(cmds.playbackOptions(q=True, max=True)))
        time_range_layout.addWidget(start_frame_label)
        time_range_layout.addWidget(self.start_frame_spinbox)
        time_range_layout.addWidget(self.duplicate_num_label)
        time_range_layout.addWidget(self.duplicate_num_spinbox)
        time_range_layout.addWidget(end_frame_label)
        time_range_layout.addWidget(self.end_frame_spinbox)
        
        bake_shapes_frame_layout.addWidget(duplicate_on_timeline_range_widget)
        set_time_range_btn = QtWidgets.QPushButton( 'Set Time Line Range' )
        set_time_range_btn.clicked.connect(self._on_set_time_range_clicked)
        set_time_range_btn.setToolTip( 'Set the time line range to the values in the spinboxes' )
        get_time_range_btn = QtWidgets.QPushButton( 'Get Time Line Range' )
        get_time_range_btn.clicked.connect(self._on_get_time_range_clicked)
        get_time_range_btn.setToolTip( 'Get the time line range and set the values in the spinboxes' )

        # we need to add a text field for the duplicate name
        duplicate_name_layout = QtWidgets.QHBoxLayout()
        duplicate_name_layout.setContentsMargins(0, 0, 0, 0)
        duplicate_name_label = QtWidgets.QLabel( 'Duplicate Name:' )
        self.duplicate_name_line_edit = QtWidgets.QLineEdit()
        self.duplicate_name_line_edit.setPlaceholderText( 'Enter a name for the duplicate' )
        duplicate_name_layout.addWidget(duplicate_name_label)
        duplicate_name_layout.addWidget(self.duplicate_name_line_edit)
        # finally we need to add a button to duplicate the selected shapes on the timeline range
        duplicate_on_timeline_range_btn = QtWidgets.QPushButton( 'Duplicate On Timeline Range' )
        duplicate_on_timeline_range_btn.clicked.connect(self._duplicate_on_timeline_range)

        duplicate_on_timeline_range_layout.addLayout(duplicate_name_layout)
        duplicate_on_timeline_range_layout.addWidget(set_time_range_btn)
        duplicate_on_timeline_range_layout.addLayout(time_range_layout)
        duplicate_on_timeline_range_layout.addWidget(get_time_range_btn)
        duplicate_on_timeline_range_layout.addWidget(duplicate_on_timeline_range_btn)

        mainLayout.addWidget(mesh_tools_frame_layout)
        mainLayout.addWidget(clusters_frame_layout)
        mainLayout.addWidget(attribute_tools_frame_layout)
        mainLayout.addWidget(bake_shapes_frame_layout)
        mainLayout.addWidget(blendshape_editor_frame_layout)

        mainLayout.addItem(filler)

        cmds.workspaceControl (workspace_control_name , e=True , dtc=["ToolBox" , "right"] , wp="preferred" , mw=180)
        self.raise_ ()

    def change_mirror_cluster_axis(self, btn):
        smc.MIRROR_CLUSTER_AXIS =  btn.text()
        print (btn.text())

    @staticmethod
    def delete_instences():
        '''
        Look like on 2017 this needs to be a little diffrents, like in this function,
        However, i might be missing something since ive done this very late at night :)
        '''

        for obj in get_maya_main_window ().children ():

            if str (type (obj)) == "<class '{}.MyDockingWindow'>".format (os.path.splitext (
                    os.path.basename (__file__)[0])):  # ""<class 'moduleName.mayaMixin.MyDockingWindow'>":

                if obj.__class__.__name__ == "MyDockingWindow":  # Compare object names

                    obj.setParent (None)
                    obj.deleteLater ()


    @staticmethod
    def delete_control(control):

        if cmds.workspaceControl(control, q=True, exists=True):
            cmds.workspaceControl(control, e=True, close=True)
            cmds.deleteUI(control, control=True)


    def _on_set_time_range_clicked(self):
        start_frame = self.start_frame_spinbox.value()
        end_frame = self.end_frame_spinbox.value()
        cmds.playbackOptions(min=start_frame, max=end_frame)

    def _on_get_time_range_clicked(self):
        start_frame = int(cmds.playbackOptions(q=True, min=True))
        end_frame = int(cmds.playbackOptions(q=True, max=True))
        self.start_frame_spinbox.setValue(start_frame)
        self.end_frame_spinbox.setValue(end_frame)
    @undoable
    def _duplicate_on_timeline_range(self):
        start_frame = self.start_frame_spinbox.value()
        end_frame = self.end_frame_spinbox.value()
        num_duplicates = self.duplicate_num_spinbox.value()
        separator = env.SEPARATOR
        duplicate_name = self.duplicate_name_line_edit.text()
        selection = cmds.ls(sl=True, long=True)
        if not selection:
            cmds.warning("No objects selected to duplicate.")
            return
        if not duplicate_name:
            cmds.warning("Please enter a name for the duplicate.")
            return
        offset = 1.0 / (num_duplicates)
        range_length = end_frame - start_frame
        current_offset = 0.0
        current_frame = start_frame
        for i in range(1, num_duplicates+1):
            duplicate_suffix = int(offset*(i)*100)
            if duplicate_suffix == 100:
                duplicate_suffix = ""
            current_frame = start_frame + (range_length * (i* offset))
            cmds.currentTime(current_frame)
            duplicate_tokens = duplicate_name.split(separator)
            renamed_tokens = []
            for token in duplicate_tokens:
                renamed_tokens.append(f"{token}{duplicate_suffix}")
            new_name = separator.join(renamed_tokens)
            duplicated = cmds.duplicate(selection[0], name = new_name)[0]

def show():
    global WINDOW
    WINDOW = MmToolsUI()
