import maya.cmds as cmds
import maya.api.OpenMaya as om
import maya.api.OpenMayaAnim as oma
import numpy as np


class SkinCluster(object):

    def __init__(self, skin_cluster):

        if not cmds.objExists(skin_cluster):
            raise RuntimeError(
                "SkinCluster does not exist: {}".format(skin_cluster)
            )

        selection = om.MSelectionList()
        selection.add(skin_cluster)

        self.skin_m_object = selection.getDependNode(0)

        if not self.skin_m_object.hasFn(om.MFn.kSkinClusterFilter):
            raise RuntimeError(
                "{} is not a skinCluster".format(skin_cluster)
            )

        self.name = skin_cluster
        self.skin_fn = oma.MFnSkinCluster(self.skin_m_object)

        self.mesh_m_object = None
        self.mesh_dag_path = None

        self.influences = None
        self.weight_data = {}

        # Get the mesh affected by the skinCluster
        self._get_mesh()

        # Cache influences
        self.influences = self.get_influences()

        # Cache the current influence matrices.
        # This becomes our reference/rest pose.
        self.bind_matrices = self._get_current_matrices()

        # Cache weights
        self.weight_data = self.get_weights()

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @classmethod
    def from_mesh(cls, mesh):

        shapes = cmds.listRelatives(
            mesh,
            shapes=True,
            noIntermediate=True,
            fullPath=True
        ) or []

        if not shapes:
            raise RuntimeError(
                "Could not find a mesh shape for {}".format(mesh)
            )

        selection = om.MSelectionList()
        selection.add(shapes[0])

        mesh_m_object = selection.getDependNode(0)

        iterator = om.MItDependencyGraph(
            mesh_m_object,
            om.MItDependencyGraph.kDownstream,
            om.MItDependencyGraph.kPlugLevel
        )

        while not iterator.isDone():

            current = iterator.currentNode()

            if current.hasFn(om.MFn.kSkinClusterFilter):

                skin_fn = oma.MFnSkinCluster(current)

                return cls(skin_fn.name())

            iterator.next()

        return None

    # ------------------------------------------------------------------
    # Mesh
    # ------------------------------------------------------------------

    def _get_mesh(self):

        geometries = self.skin_fn.getOutputGeometry()

        if not geometries:
            raise RuntimeError(
                "SkinCluster {} has no output geometry".format(
                    self.name
                )
            )

        self.mesh_m_object = geometries[0]
        self.mesh_dag_path = om.MDagPath.getAPathTo(
            self.mesh_m_object
        )

    # ------------------------------------------------------------------
    # Influences
    # ------------------------------------------------------------------

    def get_influences(self):

        influences = self.skin_fn.influenceObjects()

        return [
            influence.partialPathName()
            for influence in influences
        ]

    # ------------------------------------------------------------------
    # Matrices
    # ------------------------------------------------------------------

    def _get_current_matrices(self):
        """
        Return the current world-space matrices of all influences.

        Returns:
            numpy.ndarray:
                Shape: (num_influences, 16)
        """

        influences = self.skin_fn.influenceObjects()

        matrices = np.empty(
            (len(influences), 16),
            dtype=np.float64
        )

        for i, influence in enumerate(influences):

            matrix = influence.inclusiveMatrix()

            matrices[i] = np.array(
                matrix,
                dtype=np.float64
            ).reshape(16)

        return matrices

    def is_pose_changed(self, tolerance=1e-6):
        """
        Check whether any influence has moved from the cached
        rest/bind pose.

        Args:
            tolerance (float): Matrix comparison tolerance.

        Returns:
            bool: True if the pose has changed.
        """

        current_matrices = self._get_current_matrices()

        if current_matrices.shape != self.bind_matrices.shape:
            return True

        return not np.allclose(
            current_matrices,
            self.bind_matrices,
            rtol=0.0,
            atol=tolerance
        )

    # ------------------------------------------------------------------
    # Weights
    # ------------------------------------------------------------------

    def get_weights(self):

        weight_data = {}

        vertex_iter = om.MItGeometry(self.mesh_m_object)

        while not vertex_iter.isDone():

            component = vertex_iter.currentItem()

            weights, influence_count = self.skin_fn.getWeights(
                self.mesh_dag_path,
                component
            )

            weight_data[vertex_iter.index()] = dict(
                zip(
                    self.influences,
                    weights
                )
            )

            vertex_iter.next()

        return weight_data

    def get_influence_weights(self, influence):

        if influence not in self.influences:
            return None

        return [
            self.weight_data[i][influence]
            for i in range(len(self.weight_data))
        ]