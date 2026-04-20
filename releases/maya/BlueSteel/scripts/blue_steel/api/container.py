from maya import cmds


class Container(object):
    """
    This class handles dag containers
    """

    def __init__(self, name):
        """
        Set up the container
        :param name: the name of the container
        """
        self.name = name

    @property
    def published_attributes(self):
        """
        Get the published attributes of the container
        :return: the published attributes of the container
        """
        return cmds.container(self.name, query=True, publishAttr=True) or []

    @property
    def published_names(self):
        """
        Get the names of the published attributes of the container
        :return: the names of the published attributes of the container
        """
        return cmds.container(self.name, query=True, publishName=True) or []


    @property
    def bindings(self):
        """
        Get the binds of the container
        :return: the binds of the container
        """
        bindings = cmds.container(self.name, query= True, bindAttr=True) or []
        # let's split the bindings in  lists of two elements
        return [bindings[i:i + 2] for i in range(0, len(bindings), 2)]

    def bind_attribute(self, node_attr: str, attr_name=None):
        """
        Publish and bind a node attribute to the container
        :param node_attr: the node and attribute to publish, e.g. "pSphere1.translate"
        :param attr_name: the name of the attribute to publish, if None, it will use the node_attr str after "."
        """
        if not attr_name:
            attr_name = node_attr.split('.')[-1]
        cmds.container(self.name, e=True, publishAndBind=[node_attr, attr_name])

    def unbind_attribute(self, attribute: str):
        """
        Unpublish and unbind a list of node attributes to the container
        :param bindings: the binding to unpublish, e.g. [["pSphere1.translateX", "translateX"]...]
        """
        print(f"Unbinding attribute {attribute} from container {self.name}")
        cmds.container(self.name, edit=True, unbindAndUnpublish=attribute)
        # refreshing the channel box to reflect the changes
        cmds.channelBox('mainChannelBox', edit=True, update=True)

    @staticmethod
    def create(name: str, members=[]):
        """
        Create a container
        :param name: the name of the container
        :param members: the members of the container
        :return: the container
        """
        container = cmds.container(name=name)
        if members:
            cmds.container(container, edit=True, addNode=members)
        return Container(container)


    def set_icon(self, icon_path: str):
        """
        Set the icon of the container
        :param icon_path: the path to the icon
        """
        # Check if the custom icon file exists
        cmds.setAttr(f"{self.name}.iconName", icon_path, type="string")

    @property
    def members(self):
        """
        Get the members of the container
        :return: the members of the container
        """
        return cmds.container(self.name, query=True, nodeList=True) or []

    def remove_member(self, member: str):
        """
        Remove a member from the container
        :param member: the member to remove
        """
        if member in self.members:
            cmds.container(self.name, edit=True, removeNode=member)

    def add_member(self, member: str):
        """
        Add a member to the container
        :param member: the member to add
        """
        if member not in self.members:
            cmds.container(self.name, edit=True, addNode=member)

    def add_mesh_as_member(self, mesh: str):
        """
        Add a mesh as a member to the container
        :param mesh: the mesh to add as a member
        """
        #container -edit -force   -includeShapes -includeTransform  -addNode test_heatMapMesh test_blueSteelEditor ;
        cmds.container(self.name,
                        edit=True,
                        force=True,
                        includeShapes=True,
                        includeTransform=True,
                        addNode=mesh)

    def remove(self):
        """
        Remove the container
        """
        cmds.container(self.name, edit=True, removeContainer=True)
        self.name = None
        del self
