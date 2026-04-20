from maya import cmds
import maya.OpenMayaUI as omui
from maya.app.general.mayaMixin import MayaQWidgetDockableMixin
from ...mmtools import smartCluster as smc
from ...mmtools import meshTools as mt
from ...mmtools import shape_editor_tools
from ...mmtools import connectionTools as ct
from ... import env
from ..common.frameLayout import FrameLayout
from ..common.icons import *
from ...env import MAYA_VERSION
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

        mainLayout.addWidget(mesh_tools_frame_layout)
        mainLayout.addWidget(clusters_frame_layout)
        mainLayout.addWidget(attribute_tools_frame_layout)
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


# class FrameLayout (QtWidgets.QWidget):
#     def __init__(self , label , parent=None):
#         super (FrameLayout , self).__init__ (parent)

#         self.label = label
#         # self.setCheckable( True )
#         # self.setChecked( True )
#         # creating the main layout
#         self.layout = QtWidgets.QVBoxLayout ()
#         self.setLayout (self.layout)
#         self.layout.setSpacing (0)
#         self.layout.setMargin (0)
#         # adding widgets
#         self.init_widget ()

#         # colors
#         self.colorR = 100
#         self.colorG = 100
#         self.colorB = 100
#         self.title.clicked.connect (self.collapse)

#         # set the content layout
#         self.content_layout = QtWidgets.QVBoxLayout ()
#         self.frame.setLayout (self.content_layout)
#         self.content_layout.setSpacing (4)
#         self.content_layout.setMargin (0)
#         self.content_layout.setContentsMargins (0 , 4 , 0 , 4)

#     def init_widget(self):
#         self._create_frame ()
#         self._create_title ()

#         self.layout.addWidget (self.title)
#         self.layout.addWidget (self.frame)

#     def _create_frame(self):
#         self.frame = QtWidgets.QFrame ()
#         self.frame.setStyleSheet ("QFrame { border: 0px solid #5d5d5d;"
#                                   "border-bottom-left-radius: 0px;"
#                                   "border-bottom-right-radius: 0px;}")

#     def _create_title(self):

#         self.title = QtWidgets.QToolButton (text=self.label , checkable=True , checked=False)
#         self.title.setStyleSheet ("QToolButton { border: none;"
#                                   "background-color: #5d5d5d;"
#                                   "border-width: 5px;"
#                                   "border-radius: 2px;"
#                                   "border-color: #5d5d5d;color: #bbbbbb;"
#                                   "font-weight: bold}")
#         self.title.setToolButtonStyle (QtCore.Qt.ToolButtonTextBesideIcon)
#         self.title.setArrowType (QtCore.Qt.ArrowType.DownArrow)
#         self.title.setSizePolicy (QtWidgets.QSizePolicy.Expanding , QtWidgets.QSizePolicy.Fixed)

#     def collapse(self):
#         if self.title.isChecked ():
#             self.frame.setMaximumHeight (167777)
#             self.title.setArrowType (QtCore.Qt.ArrowType.DownArrow)
#         else:
#             self.frame.setMaximumHeight (0)
#             self.title.setArrowType (QtCore.Qt.ArrowType.RightArrow)

#     def setColor(self , r , g , b):
#         self.r = r
#         self.g = g
#         self.b = b
#         self.setFrameLayoutStylesheet ()

#     def addWidget(self , widget):
#         '''
#         This function receives a widget to add to its internal vertical
#         layout.
#         '''
#         self.content_layout.addWidget (widget)



# class CollapsibleBox(QtWidgets.QWidget):
#     def __init__(self, title="", parent=None):
#         super(CollapsibleBox, self).__init__(parent)
#         self.toggle_button = QtWidgets.QToolButton(text=title, checkable=True, checked=False)
#         self.toggle_button.setStyleSheet("QToolButton { border: none;"
#                                          "background-color: #5d5d5d;border-width: 2px;"
#                                          "border-radius: 2px;"
#                                          "border-color: #5d5d5d;color: #bbbbbb;"
#                                          "font-weight: bold}")
#         self.toggle_button.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
#         self.toggle_button.setArrowType(QtCore.Qt.ArrowType.RightArrow)
#         self.toggle_button.setSizePolicy (QtWidgets.QSizePolicy.Expanding , QtWidgets.QSizePolicy.Fixed)
#         self.toggle_button.pressed.connect(self.on_pressed)
#         self.toggle_animation = QtCore.QParallelAnimationGroup(self)

#         self.content_area = QtWidgets.QScrollArea(maximumHeight=0, minimumHeight=0)
#         self.content_area.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
#         self.content_area.setFrameShape(QtWidgets.QFrame.NoFrame)

#         main_box_layout = QtWidgets.QVBoxLayout(self)
#         main_box_layout.setSpacing(0)
#         main_box_layout.setContentsMargins(0, 0, 0, 0)
#         main_box_layout.addWidget(self.toggle_button)
#         main_box_layout.addWidget(self.content_area)


#         # adding a dummy button for testing puposes
#         # self.add_button("dummy")

#         # self.content_area.setLayout (content_layout)
#         self.adjustSize()
#     def update_collapsible_animation(self):
#         self.toggle_animation.addAnimation (QtCore.QPropertyAnimation (self , b"minimumHeight"))
#         self.toggle_animation.addAnimation (QtCore.QPropertyAnimation (self , b"maximumHeight"))
#         self.toggle_animation.addAnimation (QtCore.QPropertyAnimation (self.content_area , b"maximumHeight"))

#         collapsed_height = self.sizeHint ().height () - self.content_area.maximumHeight ()
#         content_height = self.content_layout.sizeHint ().height ()
#         for i in range (self.toggle_animation.animationCount ()):
#             animation = self.toggle_animation.animationAt (i)
#             animation.setDuration (2)
#             animation.setStartValue (collapsed_height)
#             animation.setEndValue (collapsed_height + content_height)

#         content_animation = self.toggle_animation.animationAt (self.toggle_animation.animationCount () - 1)
#         content_animation.setDuration (2)
#         content_animation.setStartValue (0)
#         content_animation.setEndValue (content_height)


#     @QtCore.Slot()
#     def on_pressed(self):
#         checked = self.toggle_button.isChecked()
#         self.toggle_button.setArrowType(QtCore.Qt.ArrowType.DownArrow
#                                         if not checked else QtCore.Qt.ArrowType.RightArrow)
#         self.toggle_animation.setDirection(QtCore.QAbstractAnimation.Forward
#                                            if not checked else QtCore.QAbstractAnimation.Backward)
#         self.toggle_animation.start()

#     @property
#     def content_layout(self):
#         content_layout = self.content_area.layout()
#         if content_layout:
#             return content_layout

#     @content_layout.setter
#     def content_layout(self, layout):
#         old_layout = self.content_area.layout()
#         del old_layout
#         self.content_area.setLayout(layout)
#         self.update_collapsible_animation ()


#     def add_button(self, title, func=None):
#         content_layout = self.content_layout
#         button = QtWidgets.QPushButton(title)
#         button.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
#         if func:
#             button.connect(func)
#         if not content_layout:
#             print("creating new layout")
#             content_layout = QtWidgets.QVBoxLayout (self)
#             content_layout.setSpacing (0)
#             content_layout.addWidget (button)

#             self.content_layout = content_layout
#         else:
#             self.content_layout.addWidget(button)
#             self.update_collapsible_animation()


def show():
    global WINDOW
    WINDOW = MmToolsUI()
