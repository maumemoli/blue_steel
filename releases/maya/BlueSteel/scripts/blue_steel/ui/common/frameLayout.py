from ... import env
if env.MAYA_VERSION > 2024:
    from PySide6 import QtCore, QtGui, QtWidgets
    from shiboken6 import wrapInstance
else:
    from PySide2 import QtCore, QtGui, QtWidgets
    from shiboken2 import wrapInstance




class FrameLayout (QtWidgets.QWidget):
    """
    Custom FrameLayout class to create collapsible frames with a title."""
    def __init__(self , label , parent=None):
        print(f"Parent: {parent}")
        super().__init__(parent)

        self.label = label
        # self.setCheckable( True )
        # self.setChecked( True )
        # creating the main layout
        self.layout = QtWidgets.QVBoxLayout ()
        self.setLayout (self.layout)
        self.layout.setSpacing (0)
        self.layout.setContentsMargins(3, 3, 3, 3)
        # adding widgets
        self.init_widget ()

        # colors
        self.colorR = 100
        self.colorG = 100
        self.colorB = 100
        self.title.clicked.connect (self.collapse)

        # set the content layout
        self.content_layout = QtWidgets.QVBoxLayout ()
        self.frame.setLayout (self.content_layout)
        self.content_layout.setSpacing (4)
        self.content_layout.setContentsMargins (0 , 4 , 0 , 4)
        self.title.setChecked (True)
        # initial collapse
        #self.collapse ()

    def init_widget(self):
        self._create_frame ()
        self._create_title ()

        self.layout.addWidget (self.title)
        self.layout.addWidget (self.frame)

    def _create_frame(self):
        self.frame = QtWidgets.QFrame ()
        self.frame.setStyleSheet ("QFrame { border: 0px solid #5d5d5d;"
                                  "border-bottom-left-radius: 0px;"
                                  "border-bottom-right-radius: 0px;}")

    def _create_title(self):
        self.title = QtWidgets.QToolButton(text=self.label, checkable=True, checked=False)
        self.title.setStyleSheet("QToolButton { border: none;"
                                "background-color: #5d5d5d;"
                                "border-width: 5px;"
                                "border-radius: 2px;"
                                "border-color: #5d5d5d;color: #bbbbbb;"
                                "font-weight: bold}")
        
        # Make the entire button clickable (text + arrow)
        self.title.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
        self.title.setArrowType(QtCore.Qt.ArrowType.DownArrow)
        self.title.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        
        # Connect to toggled instead of clicked for better checkable button behavior
        self.title.toggled.connect(self.collapse)

    def collapse(self, checked=None):
        # If called from toggled signal, use the parameter, otherwise check button state
        if checked is None:
            is_expanded = self.title.isChecked()
        else:
            is_expanded = checked
            
        if is_expanded:
            content_height = self.content_layout.sizeHint().height()
            self.frame.setMaximumHeight(167777)
            self.frame.setMinimumHeight(content_height)
            self.title.setArrowType(QtCore.Qt.ArrowType.DownArrow)
        else:
            self.frame.setMinimumHeight(0)
            self.frame.setMaximumHeight(0)
            self.title.setArrowType(QtCore.Qt.ArrowType.RightArrow)

    def setColor(self , r , g , b):
        self.r = r
        self.g = g
        self.b = b
        self.setFrameLayoutStylesheet ()

    def addWidget(self , widget):
        '''
        This function receives a widget to add to its internal vertical
        layout.
        '''
        self.content_layout.addWidget (widget)
        content_height = self.content_layout.sizeHint().height()
        self.frame.setMinimumHeight (content_height)