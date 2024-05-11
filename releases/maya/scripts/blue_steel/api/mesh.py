import maya.api.OpenMaya as om
from datetime import datetime


class Mesh(object):
    """
    Just a wrapper for the mesh API commands, sets and gets vertices position.
    """

    def __init__(self, name):
        """
        Set up the mesh mfn.
        :param name:
        """
        self.name = name
        self.dag_path = self.get_dag_path(name)
        self.mfn_mesh = om.MFnMesh(self.dag_path)

    def __str__(self):
        return self.name

    def __repr__(self):
        return self.name

    @staticmethod
    def get_dag_path(name):
        """
        Returns the dag path
        :return: the dag path
        """
        selection_list = om.MSelectionList ()
        selection_list.add(name)
        dag_path = selection_list.getDagPath (0)
        return dag_path

    def get_points(self):
        """

        :return:
        """
        return self.mfn_mesh.getPoints()

    def set_points(self, points):
        self.mfn_mesh.setPoints(points)

