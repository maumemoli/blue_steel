"""
DeltaMap node — displays a normalized displacement gradient between an
orig mesh and a deformed mesh.

Optionally accepts a reference mesh; when connected the reference mesh
is used as the output geometry instead of the deformed mesh.

Originally based on the TensionMap plugin by Anno Schachner,
ported by Alexander Smirnov, modified by davidlatwe.
"""

import sys
import maya.api.OpenMaya as om2
import maya.OpenMaya as om

kPluginNodeName = "deltaMap"
origAttrName = "orig"
deformedAttrName = "deform"
referenceAttrName = "reference"
kPluginNodeClassify = "utility/general"
kPluginNodeId = om2.MTypeId(0x001384c0)


def maya_useNewAPI():
    pass


class DeltaMap(om2.MPxNode):

    def __init__(self):
        om2.MPxNode.__init__(self)
        self.isOrigDirty = True
        self.isDeformedDirty = True
        self.isReferenceDirty = True

    def initialize_ramp(self,
                        parentNode,
                        rampObj,
                        index,
                        position,
                        value,
                        interpolation):

        rampPlug = om2.MPlug(parentNode, rampObj)
        elementPlug = rampPlug.elementByLogicalIndex(index)

        positionPlug = elementPlug.child(0)
        positionPlug.setFloat(position)

        valuePlug = elementPlug.child(1)
        valuePlug.child(0).setFloat(value[0])
        valuePlug.child(1).setFloat(value[1])
        valuePlug.child(2).setFloat(value[2])

        interpPlug = elementPlug.child(2)
        interpPlug.setInt(interpolation)

    def postConstructor(self):
        values = [
            {"index": 0, "position": 0.0, "value": om2.MColor((0, 0, 0, 1))},
            {"index": 1, "position": 0.5, "value": om2.MColor((1, 0, 0, 1))},
            {"index": 2, "position": 1.0, "value": om2.MColor((1, 1, 0, 1))},
        ]
        for kwargs in values:
            self.initialize_ramp(parentNode=self.thisMObject(),
                                 rampObj=self.aColorRamp,
                                 interpolation=1,
                                 **kwargs)

    def setDependentsDirty(self, dirtyPlug, affectedPlugs):
        partialName = dirtyPlug.partialName()
        if partialName == origAttrName:
            self.isOrigDirty = True
        if partialName == deformedAttrName:
            self.isDeformedDirty = True
        if partialName == referenceAttrName:
            self.isReferenceDirty = True

        if self.isOrigDirty or self.isDeformedDirty or self.isReferenceDirty:
            outShapePlug = om2.MPlug(self.thisMObject(), self.aOutShape)
            affectedPlugs.append(outShapePlug)

    def compute(self, plug, data):
        if plug == self.aOutShape:
            thisObj = self.thisMObject()
            origHandle = data.inputValue(self.aOrigShape)
            deformedHandle = data.inputValue(self.aDeformedShape)
            refHandle = data.inputValue(self.aRefShape)
            outHandle = data.outputValue(self.aOutShape)
            colorRamp = om2.MRampAttribute(thisObj, self.aColorRamp)

            self._computeDelta(origHandle, deformedHandle,
                               refHandle, outHandle, colorRamp)

        data.setClean(plug)

    def _computeDelta(self, origHandle, deformedHandle,
                      refHandle, outHandle, colorRamp):
        self.isOrigDirty = False
        self.isDeformedDirty = False
        self.isReferenceDirty = False

        origObj = origHandle.asMesh()
        deformedObj = deformedHandle.asMesh()
        if origObj.isNull() or deformedObj.isNull():
            return

        origFn = om2.MFnMesh(origObj)
        deformedFn = om2.MFnMesh(deformedObj)
        numVerts = origFn.numVertices
        if deformedFn.numVertices != numVerts:
            return

        origPts = origFn.getPoints(om2.MSpace.kObject)
        defPts = deformedFn.getPoints(om2.MSpace.kObject)

        # Compute per-vertex displacement length
        lengths = [0.0] * numVerts
        maxLen = 0.0
        for i in range(numVerts):
            d = om2.MVector(defPts[i] - origPts[i])
            l = d.length()
            lengths[i] = l
            if l > maxLen:
                maxLen = l

        # Choose output mesh: reference if connected, else deformed
        refPlug = om2.MPlug(self.thisMObject(), DeltaMap.aRefShape)
        if refPlug.isConnected:
            outHandle.copy(refHandle)
            outHandle.setMObject(refHandle.asMesh())
        else:
            outHandle.copy(deformedHandle)
            outHandle.setMObject(deformedHandle.asMesh())

        outMesh = outHandle.asMesh()
        meshFn = om2.MFnMesh(outMesh)

        vertColors = om2.MColorArray()
        vertColors.setLength(numVerts)
        for i in range(numVerts):
            t = (lengths[i] / maxLen) if maxLen > 0.0 else 0.0
            vertColors[i] = colorRamp.getValueAtPosition(t)

        if not self.setAndAssignColors(meshFn, vertColors):
            self.setVertexColors(meshFn, vertColors)

    def setVertexColors(self, meshFn, vertColors):
        """This cannot name a colorSet"""
        numVerts = meshFn.numVertices
        vertIds = om2.MIntArray()
        vertIds.setLength(numVerts)

        for i in range(numVerts):
            vertIds[i] = i

        meshFn.setVertexColors(vertColors, vertIds)

    def setAndAssignColors(self, meshFn, vertColors):
        """This requires colorSet to be pre-existed"""
        if "deltaCS" not in meshFn.getColorSetNames():
            return False

        numFaceVerts = meshFn.numFaceVertices
        colorIdsOnFaceVertex = om2.MIntArray()
        colorIdsOnFaceVertex.setLength(numFaceVerts)

        vtx_num_per_poly, ploy_vtx_id = meshFn.getVertices()

        for i, colorId in enumerate(ploy_vtx_id):
            colorIdsOnFaceVertex[i] = colorId

        meshFn.setColors(vertColors, "deltaCS")
        meshFn.assignColors(colorIdsOnFaceVertex, "deltaCS")
        return True


def nodeCreator():
    return DeltaMap()


def initialize():
    tAttr = om2.MFnTypedAttribute()

    DeltaMap.aOrigShape = tAttr.create(origAttrName,
                                       origAttrName,
                                       om2.MFnMeshData.kMesh)
    tAttr.storable = True

    DeltaMap.aDeformedShape = tAttr.create(deformedAttrName,
                                           deformedAttrName,
                                           om2.MFnMeshData.kMesh)
    tAttr.storable = True

    DeltaMap.aRefShape = tAttr.create(referenceAttrName,
                                      referenceAttrName,
                                      om2.MFnMeshData.kMesh)
    tAttr.storable = True

    DeltaMap.aOutShape = tAttr.create("out", "out", om2.MFnMeshData.kMesh)
    tAttr.writable = False
    tAttr.storable = False

    DeltaMap.aColorRamp = om2.MRampAttribute().createColorRamp("color", "color")

    DeltaMap.addAttribute(DeltaMap.aOrigShape)
    DeltaMap.addAttribute(DeltaMap.aDeformedShape)
    DeltaMap.addAttribute(DeltaMap.aRefShape)
    DeltaMap.addAttribute(DeltaMap.aOutShape)
    DeltaMap.addAttribute(DeltaMap.aColorRamp)
    DeltaMap.attributeAffects(DeltaMap.aOrigShape, DeltaMap.aOutShape)
    DeltaMap.attributeAffects(DeltaMap.aDeformedShape, DeltaMap.aOutShape)
    DeltaMap.attributeAffects(DeltaMap.aRefShape, DeltaMap.aOutShape)
    DeltaMap.attributeAffects(DeltaMap.aColorRamp, DeltaMap.aOutShape)


def AEtemplateString(nodeName):
    templStr = ''
    templStr += 'global proc AE%sTemplate(string $nodeName)\n' % nodeName
    templStr += '{\n'
    templStr += 'editorTemplate -beginScrollLayout;\n'
    templStr += '   editorTemplate -beginLayout "Color Remaping" -collapse 0;\n'
    templStr += '       AEaddRampControl( $nodeName + ".color" );\n'
    templStr += '   editorTemplate -endLayout;\n'
    templStr += 'editorTemplate -addExtraControls; // add any other attributes\n'
    templStr += 'editorTemplate -endScrollLayout;\n'
    templStr += '}\n'

    return templStr


def initializePlugin(mobject):
    mplugin = om2.MFnPlugin(mobject)
    try:
        mplugin.registerNode(kPluginNodeName, kPluginNodeId,
                             nodeCreator, initialize)
        om.MGlobal.executeCommand(AEtemplateString(kPluginNodeName))
    except Exception:
        sys.stderr.write("Failed to register node: " + kPluginNodeName)
        raise


def uninitializePlugin(mobject):
    mplugin = om2.MFnPlugin(mobject)
    try:
        mplugin.deregisterNode(kPluginNodeId)
    except Exception:
        sys.stderr.write("Failed to deregister node: " + kPluginNodeName)
        raise