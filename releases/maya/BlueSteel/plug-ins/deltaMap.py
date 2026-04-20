"""
DeltaMap deformer node.

Computes per-vertex displacement magnitude between base and deformed meshes,
maps that value through a color ramp, and writes vertex colors to the deformer
output mesh.

Node type: MPxDeformerNode (Maya API 1.0)
"""

import sys
import maya.OpenMaya as om
import maya.OpenMayaMPx as ompx
import maya.OpenMayaUI as omui

kPluginNodeName = "deltaMap"
baseMeshAttrName = "baseMesh"
deformedAttrName = "deformedMesh"
maxDeltaAttrName = "maxDelta"
avgDeltaAttrName = "avgDelta"
forceRefreshAttrName = "forceRefresh"
kPluginNodeClassify = "deformer"
kPluginNodeId = om.MTypeId(0x001384c0)


def _deformer_attr(name):
    """Resolve MPxDeformerNode static attrs across Maya versions."""
    def _is_mobject(value):
        if value is None:
            return False
        try:
            value.apiType()
            return True
        except Exception:
            return False

    direct = getattr(ompx.MPxDeformerNode, name, None)
    if _is_mobject(direct):
        return direct

    cvar_name = "MPxDeformerNode_" + name
    legacy = getattr(ompx.cvar, cvar_name, None)
    if _is_mobject(legacy):
        return legacy

    geo_cvar_name = "MPxGeometryFilter_" + name
    geo_legacy = getattr(ompx.cvar, geo_cvar_name, None)
    if _is_mobject(geo_legacy):
        return geo_legacy

    raise RuntimeError("Cannot resolve MPxDeformerNode attribute: %s" % name)


class DeltaMap(ompx.MPxDeformerNode):
    aBaseMesh = om.MObject()
    aDeformedMesh = om.MObject()
    aColorRamp = om.MObject()
    aMaxDelta = om.MObject()
    aAvgDelta = om.MObject()
    aForceRefresh = om.MObject()

    def __init__(self):
        ompx.MPxDeformerNode.__init__(self)
        # Heavy delta/color evaluation is only needed when compare inputs change.
        self._needsColorRecompute = True

    def initialize_ramp(self,
                        parentNode,
                        rampObj,
                        index,
                        position,
                        value,
                        interpolation):
        rampPlug = om.MPlug(parentNode, rampObj)
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
            {"index": 0, "position": 0.0, "value": (0.0, 0.0, 1.0)},
            {"index": 1, "position": 0.25, "value": (0.0, 1.0, 1.0)},
            {"index": 2, "position": 0.5, "value": (0.0, 1.0, 0.0)},
            {"index": 3, "position": 0.75, "value": (1.0, 1.0, 0.0)},
            {"index": 4, "position": 1.0, "value": (1.0, 0.0, 0.0)},
        ]
        for kwargs in values:
            self.initialize_ramp(parentNode=self.thisMObject(),
                                 rampObj=self.aColorRamp,
                                 interpolation=1,
                                 **kwargs)

    def _get_points_from_mesh_obj(self, meshObj):
        pts = om.MPointArray()
        meshFn = om.MFnMesh(meshObj)
        meshFn.getPoints(pts, om.MSpace.kObject)
        return pts, meshFn.numVertices()

    def setDependentsDirty(self, dirtyPlug, affectedPlugs):
        attrObj = dirtyPlug.attribute()
        if attrObj == DeltaMap.aBaseMesh or attrObj == DeltaMap.aDeformedMesh or attrObj == DeltaMap.aColorRamp:
            self._needsColorRecompute = True

        if attrObj == DeltaMap.aBaseMesh or attrObj == DeltaMap.aDeformedMesh or attrObj == DeltaMap.aColorRamp or attrObj == DeltaMap.aForceRefresh:
            try:
                outPlug = om.MPlug(self.thisMObject(), _deformer_attr("outputGeom"))
                affectedPlugs.append(outPlug)
            except Exception:
                pass

    def deform(self, dataBlock, geoIter, matrix, multiIndex):
        envelope = dataBlock.inputValue(_deformer_attr("envelope")).asFloat()
        if envelope <= 0.0:
            return

        # Pass-through on regular input updates; only recompute on base/deformed changes.
        if not self._needsColorRecompute:
            return

        thisObj = self.thisMObject()
        colorRamp = om.MRampAttribute(thisObj, self.aColorRamp)

        inputArray = dataBlock.outputArrayValue(_deformer_attr("input"))
        inputArray.jumpToElement(multiIndex)
        inputMeshObj = inputArray.outputValue().child(_deformer_attr("inputGeom")).asMesh()
        if inputMeshObj.isNull():
            return

        basePlug = om.MPlug(thisObj, DeltaMap.aBaseMesh)
        if basePlug.isConnected():
            baseObj = dataBlock.inputValue(self.aBaseMesh).asMesh()
        else:
            baseObj = inputMeshObj

        deformedPlug = om.MPlug(thisObj, DeltaMap.aDeformedMesh)
        if deformedPlug.isConnected():
            deformedObj = dataBlock.inputValue(self.aDeformedMesh).asMesh()
        else:
            deformedObj = inputMeshObj

        if baseObj.isNull() or deformedObj.isNull():
            return

        # Write colors on the deformer output geometry to stay in DG flow.
        outputMeshObj = om.MObject()
        try:
            outputGeomArray = dataBlock.outputArrayValue(_deformer_attr("outputGeom"))
            outputGeomArray.jumpToElement(multiIndex)
            outputMeshObj = outputGeomArray.outputValue().asMesh()
        except Exception:
            pass
        if outputMeshObj.isNull():
            outputMeshObj = inputMeshObj

        outputFn = om.MFnMesh(outputMeshObj)
        numVerts = outputFn.numVertices()

        # Use direct mesh data points (object/local space) for best performance.
        basePts, baseNumVerts = self._get_points_from_mesh_obj(baseObj)
        defPts, defNumVerts = self._get_points_from_mesh_obj(deformedObj)

        if baseNumVerts != numVerts or defNumVerts != numVerts:
            return

        lengths = [0.0] * numVerts
        maxLen = 0.0
        for i in range(numVerts):
            d = defPts[i] - basePts[i]
            l = d.length()
            lengths[i] = l
            if l > maxLen:
                maxLen = l

        avgLen = (sum(lengths) / float(numVerts)) if numVerts > 0 else 0.0
        try:
            dataBlock.outputValue(self.aMaxDelta).setFloat(maxLen)
            dataBlock.outputValue(self.aAvgDelta).setFloat(avgLen)
        except Exception:
            pass

        vertColors = om.MColorArray()
        for i in range(numVerts):
            t = (lengths[i] / maxLen) if maxLen > 0.0 else 0.0
            color = om.MColor()
            colorRamp.getColorAtPosition(t, color)
            vertColors.append(color)

        self.setAndAssignColors(outputFn, vertColors)
        try:
            forceRefresh = dataBlock.inputValue(self.aForceRefresh).asBool()
        except Exception:
            forceRefresh = False
        if forceRefresh:
            self._forceConnectedShapeRefresh(multiIndex)

        self._needsColorRecompute = False

    def setVertexColors(self, meshFn, vertColors):
        numVerts = meshFn.numVertices()
        vertIds = om.MIntArray()
        vertIds.setLength(numVerts)

        for i in range(numVerts):
            vertIds[i] = i

        meshFn.setVertexColors(vertColors, vertIds)

    def _forceConnectedShapeRefresh(self, multiIndex):
        """Force viewport color refresh on downstream output shape meshes."""
        try:
            outGeomPlug = om.MPlug(self.thisMObject(), _deformer_attr("outputGeom"))
            elemPlug = outGeomPlug.elementByLogicalIndex(multiIndex)

            destPlugs = om.MPlugArray()
            elemPlug.connectedTo(destPlugs, False, True)
            if destPlugs.length() == 0:
                return

            refreshedAny = False
            for i in range(destPlugs.length()):
                nodeObj = destPlugs[i].node()
                if not nodeObj.hasFn(om.MFn.kMesh):
                    continue

                depFn = om.MFnDependencyNode(nodeObj)

                # Toggle displayColors and displayColorAsGreyScale via API plugs
                # to mimic the manual viewport refresh behavior without MEL chains.
                try:
                    displayPlug = depFn.findPlug("displayColors", False)
                    displayPlug.setBool(False)
                    displayPlug.setBool(True)
                except Exception:
                    pass

                try:
                    grayPlug = depFn.findPlug("displayColorAsGreyScale", False)
                    oldGray = grayPlug.asBool()
                    grayPlug.setBool(not oldGray)
                    grayPlug.setBool(oldGray)
                except Exception:
                    pass

                try:
                    om.MFnMesh(nodeObj).updateSurface()
                except Exception:
                    pass

                refreshedAny = True

            if refreshedAny:
                try:
                    omui.M3dView.scheduleRefreshAllViews()
                except Exception:
                    # Fallback for Maya versions where scheduleRefreshAllViews
                    # is not available in this binding.
                    om.MGlobal.executeCommandOnIdle('refresh -f;')
        except Exception as e:
            print("***Skipped connected-shape refresh. Error: %s" % e)

    def setAndAssignColors(self, meshFn, vertColors):
        colorSetNames = []
        meshFn.getColorSetNames(colorSetNames)
        if "deltaCS" not in colorSetNames:
            try:
                meshFn.createColorSetWithName("deltaCS")
            except Exception:
                # If creation fails, fall back to per-vertex assignment on current set.
                self.setVertexColors(meshFn, vertColors)
                return True

        numFaceVerts = meshFn.numFaceVertices()
        colorIdsOnFaceVertex = om.MIntArray()
        colorIdsOnFaceVertex.setLength(numFaceVerts)

        vtx_num_per_poly = om.MIntArray()
        poly_vtx_id = om.MIntArray()
        meshFn.getVertices(vtx_num_per_poly, poly_vtx_id)

        for i in range(numFaceVerts):
            colorIdsOnFaceVertex[i] = poly_vtx_id[i]

        meshFn.setColors(vertColors, "deltaCS")
        meshFn.assignColors(colorIdsOnFaceVertex, "deltaCS")
        try:
            meshFn.setCurrentColorSetName("deltaCS")
            meshFn.setDisplayColors(True)
        except Exception:
            pass
        return True


def nodeCreator():
    return ompx.asMPxPtr(DeltaMap())


def initialize():
    tAttr = om.MFnTypedAttribute()
    nAttr = om.MFnNumericAttribute()

    DeltaMap.aBaseMesh = tAttr.create(baseMeshAttrName,
                                      baseMeshAttrName,
                                      om.MFnData.kMesh)
    tAttr.setStorable(True)

    DeltaMap.aDeformedMesh = tAttr.create(deformedAttrName,
                                          deformedAttrName,
                                          om.MFnData.kMesh)
    tAttr.setStorable(True)

    DeltaMap.aColorRamp = om.MRampAttribute.createColorRamp("color", "color")

    DeltaMap.aMaxDelta = nAttr.create(maxDeltaAttrName,
                                      maxDeltaAttrName,
                                      om.MFnNumericData.kFloat,
                                      0.0)
    nAttr.setWritable(False)
    nAttr.setStorable(False)
    nAttr.setKeyable(False)

    DeltaMap.aAvgDelta = nAttr.create(avgDeltaAttrName,
                                      avgDeltaAttrName,
                                      om.MFnNumericData.kFloat,
                                      0.0)
    nAttr.setWritable(False)
    nAttr.setStorable(False)
    nAttr.setKeyable(False)

    DeltaMap.aForceRefresh = nAttr.create(forceRefreshAttrName,
                                          forceRefreshAttrName,
                                          om.MFnNumericData.kBoolean,
                                          True)
    nAttr.setWritable(True)
    nAttr.setStorable(True)
    nAttr.setKeyable(True)

    DeltaMap.addAttribute(DeltaMap.aBaseMesh)
    DeltaMap.addAttribute(DeltaMap.aDeformedMesh)
    DeltaMap.addAttribute(DeltaMap.aColorRamp)
    DeltaMap.addAttribute(DeltaMap.aMaxDelta)
    DeltaMap.addAttribute(DeltaMap.aAvgDelta)
    DeltaMap.addAttribute(DeltaMap.aForceRefresh)

    outputGeom = _deformer_attr("outputGeom")
    DeltaMap.attributeAffects(DeltaMap.aBaseMesh, outputGeom)
    DeltaMap.attributeAffects(DeltaMap.aDeformedMesh, outputGeom)
    DeltaMap.attributeAffects(DeltaMap.aColorRamp, outputGeom)
    DeltaMap.attributeAffects(DeltaMap.aBaseMesh, DeltaMap.aMaxDelta)
    DeltaMap.attributeAffects(DeltaMap.aDeformedMesh, DeltaMap.aMaxDelta)
    DeltaMap.attributeAffects(DeltaMap.aColorRamp, DeltaMap.aMaxDelta)
    DeltaMap.attributeAffects(DeltaMap.aBaseMesh, DeltaMap.aAvgDelta)
    DeltaMap.attributeAffects(DeltaMap.aDeformedMesh, DeltaMap.aAvgDelta)
    DeltaMap.attributeAffects(DeltaMap.aColorRamp, DeltaMap.aAvgDelta)
    DeltaMap.attributeAffects(DeltaMap.aForceRefresh, outputGeom)


def AEtemplateString(nodeName):
    templStr = ''
    templStr += 'global proc AE%sTemplate(string $nodeName)\n' % nodeName
    templStr += '{\n'
    templStr += 'editorTemplate -beginScrollLayout;\n'
    templStr += '   editorTemplate -beginLayout "Color Remaping" -collapse 0;\n'
    templStr += '       AEaddRampControl( $nodeName + ".color" );\n'
    templStr += '       editorTemplate -addControl ( $nodeName + ".forceRefresh" );\n'
    templStr += '   editorTemplate -endLayout;\n'
    templStr += 'editorTemplate -addExtraControls; // add any other attributes\n'
    templStr += 'editorTemplate -endScrollLayout;\n'
    templStr += '}\n'

    return templStr


def initializePlugin(mobject):
    mplugin = ompx.MFnPlugin(mobject)
    try:
        mplugin.registerNode(kPluginNodeName, kPluginNodeId,
                             nodeCreator, initialize,
                             ompx.MPxNode.kDeformerNode)
        om.MGlobal.executeCommand(AEtemplateString(kPluginNodeName))
    except Exception:
        sys.stderr.write("Failed to register node: " + kPluginNodeName)
        raise


def uninitializePlugin(mobject):
    mplugin = ompx.MFnPlugin(mobject)
    try:
        mplugin.deregisterNode(kPluginNodeId)
    except Exception:
        sys.stderr.write("Failed to deregister node: " + kPluginNodeName)
        raise