from maya import OpenMaya
from datetime import datetime
import numpy
import numpy as np
from ctypes import c_float, c_double, c_int, c_uint


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

    def get_dag_path(self):
        selection_list = OpenMaya.MSelectionList()
        selection_list.add(self.name)
        dag_path = OpenMaya.MDagPath()
        selection_list.getDagPath(0, dag_path)
        return dag_path

    def get_mfn_mesh(self):
        mfn_mesh = OpenMaya.MFnMesh(self.get_dag_path())
        return mfn_mesh

    def __str__(self):
        return self.name

    def __repr__(self):
        return self.name


    def get_points(self):
        """

        :return:
        """
        return self.get_mfn_mesh().getPoints()

    def set_points(self, points):
        self.get_mfn_mesh().setPoints(points)

    def get_points_as_numpy(self):
        mfn_mesh = self.get_mfn_mesh()
        points = OpenMaya.MPointArray()
        mfn_mesh.getPoints(points, OpenMaya.MSpace.kObject)

        np_array = self.m_points_to_numpy(points)
        return np_array

        num_points = points.length()
        array_size = num_points * 4  # 4 floats per point (x,y,z,w)
        util = OpenMaya.MScriptUtil()
        util.createFromList([float()] * array_size, array_size)
        ptr = OpenMaya.MScriptUtil.asFloat4Ptr(util)
        points.get(ptr)  # copy points to ptr

        c_float_array = ((c_float * 4) * num_points).from_address(int(ptr))  # x,y,z,w per point
        np_array = numpy.ctypeslib.as_array(c_float_array)  # shape: (num_points, 4)
        np_array = np_array.copy()
        print(np_array.shape)
        return np_array

    def set_points_as_numpy(self, num_array):
        #  (float, 4, c_double, om.MScriptUtil.asDouble4Ptr)
        m_point_array = self.numpy_to_m_points(num_array)
        print(m_point_array.length())
        self.set_points(m_point_array)

    @staticmethod
    def m_points_to_numpy(m_point_array):
        """
        Convert a Maya MPointArray to a numpy ndarray.

        Parameters
        ----------
        m_point_array : om.MPointArray
            The Maya point array to convert.

        Returns
        -------
        numpy.ndarray
            A (N, 4) array of doubles where each row is [x, y, z, w].
        """
        # Get number of points
        count = m_point_array.length()

        # Create a script util to hold a double4* (N * 4 doubles)
        util = OpenMaya.MScriptUtil()
        util.createFromList([0.0] * (count * 4), count * 4)

        # Cast util memory to a double4 pointer
        ptr = OpenMaya.MScriptUtil.asDouble4Ptr(util)

        # Fill that memory with the content of the MPointArray
        m_point_array.get(ptr)

        # Create a ctypes array view of the memory.
        # Each point is 4 doubles, so total doubles = count * 4
        c_array_type = c_double * (count * 4)
        c_array = c_array_type.from_address(int(ptr))

        # Let numpy view the same memory as a 1D array of doubles
        np_array = np.ctypeslib.as_array(c_array)

        # Reshape to (count, 4) for easier use
        return np_array.reshape(count, 4)

    @staticmethod
    def numpy_to_m_points(np_array):
        """
        Convert a numpy ndarray of shape (N, 4) to a Maya MPointArray
        using a direct SWIG pointer (fast, no Python loop).

        Parameters
        ----------
        np_array : numpy.ndarray
            A (N, 4) array of doubles where each row is [x, y, z, w].

        Returns
        -------
        OpenMaya.MPointArray
            A Maya point array containing the points from np_array.
        """
        if np_array.ndim != 2 or np_array.shape[1] != 4:
            raise ValueError("Input array must have shape (N, 4)")

        count = np_array.shape[0]

        # Allocate a double array (count * 4) inside an MScriptUtil
        util = OpenMaya.MScriptUtil()
        util.createFromList([0.0] * (count * 4), count * 4)

        # Get a pointer of type double4*
        ptr = OpenMaya.MScriptUtil.asDouble4Ptr(util)

        # Create a ctypes view of that buffer and a numpy view on top of it
        c_array_type = c_double * (count * 4)
        c_array = c_array_type.from_address(int(ptr))
        np_view = np.ctypeslib.as_array(c_array).reshape(count, 4)

        # Copy the user numpy data into the MScriptUtil buffer
        np.copyto(np_view, np_array)

        # Build a new MPointArray directly from the pointer and count
        # This is the key: MPointArray(double4* ptr, unsigned int count)
        return OpenMaya.MPointArray(ptr, count)