from .. import env
from . import logger
import logging
from enum import auto, Enum
from typing import List
import traceback
import maya.api.OpenMaya as om2
import maya.OpenMaya as om
import maya.OpenMayaUI as omui
from maya import cmds
if env.MAYA_VERSION > 2024:
    from PySide6.QtCore import QObject, Signal

else:
    from PySide2.QtCore import QObject, Signal

class BlueSteelEditorsTracker(QObject):
    """
    Tracks the Existence of Blue Steel Editors in the Maya scene,
    emitting signals on scene reset, scene opened, node added, node removed and node renamed.
    The class uses Scene callbacks to monitor the scene lifecycle,
    DG callbacks to track node deletion and addition,
    attaching node callbacks to track rename events.
    """

    sceneReset = Signal()
    sceneOpened = Signal()
    editorAdded = Signal(str)
    editorRemoved = Signal(str)
    editorRenamed = Signal(str, str)
    frameChanged = Signal(float)
    editor_tag = "BlueSteelEditorMain" # attribute to identify Blue Steel editors
    def __init__(self,parent=None):
        super().__init__(parent)
        self.existing_name_spaces = list()
        self._scene_callback_ids = list()
        self._dg_callback_ids = list()
        self._node_rename_callback_ids = list()
        self._tracked_mobjects = list()
        self.register_scene_editor_nodes()
        self._add_scene_lifecycle_callbacks()
        self._add_dg_callbacks()

    # ------------------------------------------------------------------
    # Callbacks
    # ------------------------------------------------------------------

    def _add_scene_lifecycle_callbacks(self):
        """Add callbacks to track scene lifecycle events."""
        # adding MEventMessage callbacks for name space changes
        # these will help us track when the scene is reset or opened
        for msg_type, func in [ (om2.MSceneMessage.kBeforeNew, self._on_scene_reset),
                                (om2.MSceneMessage.kBeforeOpen, self._on_scene_reset),
                                (om2.MSceneMessage.kBeforeImport, self._on_scene_reset),
                                (om2.MSceneMessage.kAfterOpen, self._on_scene_opened),
                                (om2.MSceneMessage.kAfterNew, self._on_scene_opened),
                                (om2.MSceneMessage.kAfterImport, self._on_scene_opened)]:
            cb = om2.MSceneMessage.addCallback(msg_type, func)
            self._scene_callback_ids.append(cb)
        # adding the frame changed callback to track the current frame and emit it to the UI
        cb = om2.MEventMessage.addEventCallback("timeChanged", self._on_frame_changed)
        self._scene_callback_ids.append(cb)

    def _add_dg_callbacks(self):
        """Add DG callbacks to track node addition, removal, and renaming."""
        for callback, func in [(om2.MDGMessage.addNodeAddedCallback, self._on_node_added),
                               (om2.MDGMessage.addNodeRemovedCallback, self._on_node_removed),
                               ]:
            cb = callback(func,
                          "container",
                          None)
            self._dg_callback_ids.append(cb)

    def _add_rename_callback(self, obj, *args):
        """Registers the per-node rename callback."""
        cid = None
        if obj in self._tracked_mobjects:
            return cid # already registered
        try:
            cid = om2.MNodeMessage.addNameChangedCallback(obj, self._on_node_renamed)
        except:
            pass  # Some internal nodes may fail
        return cid
    
    
    # ------------------------------------------------------------------
    # Callback handlers
    # ------------------------------------------------------------------

    def _is_blue_steel_editor(self, node: om2.MObject) -> bool:
        """Check if a node is a Blue Steel editor container."""
        fn_dep = om2.MFnDependencyNode(node)
        return fn_dep.hasAttribute(self.editor_tag)

    def _on_frame_changed(self, *args):
        """Triggered when the current time changes; emits frameChanged signal."""
        
        current_frame = cmds.currentTime(query=True)
        self.frameChanged.emit(current_frame)

    def _on_node_renamed(self, node_obj, old_name, client_data=None):
        """Triggered when a node is renamed."""
        # print(f"_on_node_renamed called for node: {node_obj}")
        node_name = self.get_mobj_name(node_obj)
        self.editorRenamed.emit(node_name, old_name)

    def _on_node_added(self, node_obj, client_data=None):
        """Triggered when a node is added."""
        # we need to add the rename callback for this node
        if not self._is_blue_steel_editor(node_obj):
            #print("Not concerning node addition, not a Blue Steel Editor")
            return
        
        cid = self._add_rename_callback(node_obj)
        if cid is not None:
            self._node_rename_callback_ids.append(cid)
            self._tracked_mobjects.append(node_obj)
        node_name = self.get_mobj_name(node_obj)
        # print(f"_on_node_added called for node: {node_name}")
        self.editorAdded.emit(node_name)

    def _on_scene_updated(self, *args):
        """Triggered when the namespace changes; re-registers editor nodes."""
        current_name_spaces = self._get_name_spaces()
        if current_name_spaces != self.existing_name_spaces:
            # namespace change detected
            # print("namespace change detected")
            self._update_existing_name_spaces()

    def _on_node_removed(self, node_obj, client_data=None):
        """Triggered when a node is removed."""
        node_name = self.get_mobj_name(node_obj)
        # print(f"_on_node_removed called for node: {node_name}")
        if node_obj in self._tracked_mobjects:
            idx = self._tracked_mobjects.index(node_obj)
            self._tracked_mobjects.pop(idx)
            cb_id = self._node_rename_callback_ids.pop(idx)
            try:
                om2.MMessage.removeCallback(cb_id)
            except Exception:
                pass
        self.editorRemoved.emit(node_name)

    def _on_scene_opened(self, *args):
        """Triggered after new/open scene; emits sceneOpened signal."""
        self._add_dg_callbacks()
        self.register_scene_editor_nodes()
        self.sceneOpened.emit()

    def _on_scene_reset(self, *args):
        """Triggered before new/open scene; removes DG callbacks safely."""
        self._remove_dg_callbacks()
        self._remove_rename_callbacks()
        self.sceneReset.emit()

    #------------------------------------------------------------------
    # Generic helpers
    #------------------------------------------------------------------
    def get_mobj_name(self, mobj: om2.MObject) -> str:
        """Return the name of a Maya MObject."""
        fn_dep = om2.MFnDependencyNode(mobj)
        return fn_dep.name()


    def _get_name_spaces(self) -> List[str]:
        """Return a list of all namespaces in the scene."""
        it = om2.MItDependencyNodes(om2.MFn.kNamespace)
        namespaces = []
        while not it.isDone():
            ns_obj = it.thisNode()
            fn_ns = om2.MFnDependencyNode(ns_obj)
            namespaces.append(fn_ns.name())
            it.next()
        return namespaces

    def _update_existing_name_spaces(self):
        """Update the stored list of existing namespaces."""
        self.existing_name_spaces = self._get_name_spaces()

    # ------------------------------------------------------------------
    # Cleanup helpers
    # ------------------------------------------------------------------

    def _remove_rename_callbacks(self):
        """Remove rename callbacks."""
        for cb in self._node_rename_callback_ids:
            om2.MMessage.removeCallback(cb)

        self._node_rename_callback_ids.clear()
        self._tracked_mobjects.clear()

    def _remove_dg_callbacks(self):
        """Remove DG callbacks."""
        for cb in self._dg_callback_ids:
            try:
                om2.MMessage.removeCallback(cb)
            except Exception:
                pass
        self._dg_callback_ids.clear()

    def _remove_scene_callbacks(self):
        """Remove scene lifecycle callbacks."""
        for cb in self._scene_callback_ids:
            try:
                om2.MMessage.removeCallback(cb)
            except Exception:
                pass
        self._scene_callback_ids.clear()

    def __del__(self):
        """Ensure cleanup on deletion."""
        self.kill()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def register_scene_editor_nodes(self):
        """Add rename callbacks to all existing scene nodes."""
        it = om2.MItDependencyNodes(om2.MFn.kContainer)
        self._tracked_mobjects.clear()
        self._node_rename_callback_ids.clear()
        while not it.isDone():
            node_obj = it.thisNode()
            if not self._is_blue_steel_editor(node_obj):
                it.next()
                continue
            cid =self._add_rename_callback(node_obj)
            self._node_rename_callback_ids.append(cid)
            self._tracked_mobjects.append(node_obj)
            it.next()

    def get_editor_names(self) -> List[str]:
        """Return the names of all currently tracked nodes."""
        names = []
        for obj in self._tracked_mobjects:
            fn_dep = om2.MFnDependencyNode(obj)
            names.append(fn_dep.name())
        return names

    def kill(self):
        """Remove all scene lifecycle callbacks."""
        self._remove_dg_callbacks()
        self._remove_rename_callbacks()
        self._remove_scene_callbacks()

    def __del__(self):
        """Ensure cleanup on deletion."""
        self.kill()


class BlendShapeNodeTracker(QObject):
    """
    Manages the callbacks coming from the blend shape node to notify 
    of changes in the shape weights or targets using different Signals.
    """
    shapeAdded = Signal(int, str) # return index and name
    shapeRemoved = Signal(int, str) # return index and name
    shapeRenamed = Signal(int, str, str) # return index, new name and old name
    shapeInputConnected = Signal(int, bool) # return index and name
    shapeValueChanged = Signal(int, str, float) # return index, name and new value
    plugIsDirty = Signal(int, str) # return index and name
    sculptTargetChanged = Signal(int, str) # return index and name
    # connectedShapeValueChanged = Signal(int, str) # return index and name from input connection
    targetVisibilityChanged = Signal(int, str, bool) # return index and visibility state
    nodeDeleted = Signal(str)

    def __init__(self, node_name, parent=None):
        super().__init__(parent=parent)
        self._mobj = self._get_mobject(node_name)
        self._mobj_handle = om2.MObjectHandle(self._mobj) if self._mobj else None
        if self._mobj.apiType() != om2.MFn.kBlendShape:
            raise TypeError(f"Node '{node_name}' is not a blend shape.")
        self._fn_dep = om2.MFnDependencyNode(self._mobj)
        self._weight_plug = self._fn_dep.findPlug('weight', False)
        self._input_target_group_plug = self._fn_dep.findPlug('inputTargetGroup', False)
        self._target_visibility_plug = self._fn_dep.findPlug('targetVisibility', False)
        self._sculpt_target_plug = self._fn_dep.findPlug('sculptTargetIndex', False)
        self._out_geometry_plug = self._fn_dep.findPlug('outputGeometry', False) 
        # attribute change callbacks
        self._attribute_callback_ids = set()
        self._last_indexes = []
        self._last_weights = []
        self._last_aliases = []
        self._depending_weights_idxs = set()
        self._store_indices_and_aliases()
        self.chached_weights = self._get_current_weights_values()

    @property
    def node_name(self):
        # check if the mobject is still valid
        if self._fn_dep:
            return self._fn_dep.name()
        return "<deleted>"

    def _get_current_weights_values(self):
        """Return a dictionary of current weight values by index."""
        current_weights = {}
        for i in self._weight_plug.getExistingArrayAttributeIndices():
            weight_plug = self._weight_plug.elementByLogicalIndex(i)
            current_weights[i] = weight_plug.asFloat()
        return current_weights


    def _track_other_affected_weight_plugs(self, plug: om2.MPlug):
        """Track other weight plugs that may be affected by input connections."""
        # This function can be expanded to track other plugs if needed
        # get the node of the plug
        desination_weight_indices = set()
        try:
            if plug.isConnected:
                # print(f"There is a  source plug connected to: {plug.name()}")
                source_plug = plug.source()
                source_node = source_plug.node() # MObject
                
                # print(f"plug nname: {plug.name()}")
                # source_plug = plug.source()
                # print(f"source plug: {source_plug.name()}")
                mfn_dep = om2.MFnDependencyNode(source_node)
                if not mfn_dep.typeName == "transform":
                    # print(f"EXIT not a connected to a transform node\n    Plug: {plug.name()}\n    Node: {mfn_dep.name()}")
                    return
            # print (f"_track_other_affected_weight_plugs called for plug: {node_name}")
            out_going_plugs = plug.destinations()
            paresed = list()
            for out_plug in out_going_plugs:
                # let's get the destination nodes
                out_node = out_plug.node()
                if out_node in paresed:
                    continue
                out_mfn_dep = om2.MFnDependencyNode(out_node)
                out_node_name = out_mfn_dep.name()
                # print(f"  Connected to: {out_node_name}")
                all_connected_plugs = out_mfn_dep.getConnections()
                outgoing_plugs = [p for p in all_connected_plugs if p.destinations()]
                for out_plug in outgoing_plugs:
                    # we needto fing where this plug connects to
                    dest_plugs = out_plug.destinations()
                    for dest_plug in dest_plugs:
                        if dest_plug != self._weight_plug:
                            #print(f"    Skipping not weight plug: {dest_plug.name()}")
                            continue
                        dest_index = dest_plug.logicalIndex()
                        desination_weight_indices.add(dest_index)
            return desination_weight_indices

        except Exception as e:
            print("=== Exception in _track_other_affected_weight_plugs ===")
            traceback.print_exc()
            return desination_weight_indices

    def _get_mobject(self, node_name: str) -> om2.MObject:
        """Return MObject from node name, or None if not found."""
        sel = om2.MSelectionList()
        try:
            sel.add(node_name)
            return sel.getDependNode(0)
        except Exception:
            return None
        
    def _store_indices_and_aliases(self):
        # Store the current indices and weights
        self._last_indexes = list(self._weight_plug.getExistingArrayAttributeIndices()) or []
        self._last_weights = [self._weight_plug.elementByLogicalIndex(i).asFloat() for i in self._last_indexes]
        self._last_aliases = [self._weight_plug.elementByLogicalIndex(i).name().split(".")[-1] for i in self._last_indexes]
        # print(f"Stored indices: {self._last_indexes}, weights: {self._last_weights}, aliases: {self._last_aliases}")

    def get_last_alias_at_index(self, index):
        if index not in self._last_indexes:
            return None
        idx = self._last_indexes.index(index)
        return self._last_aliases[idx]

    @property
    def _last_count(self):
        return len(self._last_indexes)
    # ------------------------------------------------------------------
    # Callback handler
    # ------------------------------------------------------------------

    def _on_node_added(self, node_obj, client_data=None):
        """Handle node added event to re-establish callbacks."""
        super()._on_node_added(node_obj, client_data)
        # print(f"Node added - re-establishing callbacks for node: {self.node_name}")
        self.start()

    def _on_node_removed(self, node_obj, client_data=None):
        """Handle node removed event to clean up callbacks."""
        if self._mobj == node_obj:
            self.nodeDeleted.emit(self.node_name)
            # print(f"Node removed - cleaning up callbacks for node: {self.node_name}")
            self.kill()
        
    ### ------------------------------------------------------------------
    def _on_dirty_plug(self, node: om2.MObject, dirtyPlug: om2.MPlug, clientData):
        # This callback is called when a plug is dirtied
        # We can use it to monitor changes to the weight and targetVisibility plugs
        if dirtyPlug != self._weight_plug or not dirtyPlug.isElement:
            # print(f"EXIT not weight array plug: {dirtyPlug.name()}")
            return # not the plug we want to monitor
        # let's check if there is an input connection
        if dirtyPlug.connectedTo(True, False):
            # let's evaluate the plug to update its value
            logical_index = dirtyPlug.logicalIndex()
            shape_name = self.get_shape_name(logical_index)
            # print(f"PLUG IS DIRTY: logical {logical_index} name {shape_name} plug {dirtyPlug.name()}")
            self.plugIsDirty.emit(logical_index, shape_name)

    ### ------------------------------------------------------------------ 
    def _on_attribute_changed(self, message, plugChanged: om2.MPlug, otherPlugChanged, clentData):


        # if message & om2.MNodeMessage.kConnectionMade:
        #     print(f"Connection made: {plugChanged.name()} -> {otherPlugChanged.name()}")
        
        # elif message & om2.MNodeMessage.kConnectionBroken:
        #     print(f"Connection broken: {plugChanged.name()} -X- {otherPlugChanged.name()}")

        # print(f"_on_attribute_changed called for plug: {plugChanged.name()}, message: {message}")
        # Only process weight array element changes

        
        # check if the plug is the sculptTarget plug
        if plugChanged == self._sculpt_target_plug:
            # let's get the value of the attribute of the plug
            target_id = plugChanged.asInt()
            shape_name = self.get_shape_name(target_id) if target_id >=0 else "None"
            self.sculptTargetChanged.emit(target_id, shape_name)
            #print(f"SCULPT TARGET CHANGED: {message}, target id {target_id} shape name {shape_name}")
            return

        



        if not plugChanged.isElement:
            #print(f"EXIT not array plug: {plugChanged.name()}")
            return

        try:
            if plugChanged not in  [self._weight_plug,
                                    self._target_visibility_plug,
                                    self._out_geometry_plug]:
                #print("Wrong plug EXIT", plugChanged.name())
                return
        except Exception as e:
            # If we can't even check the array, bail
            #print("Exception EXIT:", e)

            return

        
        try:
            index = plugChanged.logicalIndex()
            # shape_value = self.get_shape_value(index)
            shape_name = self.get_shape_name(index)
            last_shape_name = self.get_last_alias_at_index(index)
            target_visibility = self.get_target_visibility(index)
        except Exception as e:
            # print("Error in index EXIT:", e)

            # Can't get the index, can't do anything
            return

        current_count = self._weight_plug.numElements()
        
        # Debug print with decoded message
        msg_str = self._get_attribute_message_string(message)
        # print(f"MSG: {msg_str} ({message}), logical {index} {plugChanged.name()}")

        # Array element add/remove (6144 = kConnectionMade | kConnectionBroken)
        if message == 6144 and plugChanged == self._weight_plug:
            # print(f"ADDED: {message}, logical {index} {plugChanged} last count {self._last_count} current count {current_count}")
            if current_count > self._last_count:
                self.shapeAdded.emit(index, shape_name)
                # print("Added index")

            self._store_indices_and_aliases()

        elif message == 2052 and plugChanged == self._out_geometry_plug : # OUTPUT GEOMETRY CHANGED?
            # WE ARE GOING TO USE THIS TO DETECT WEIGHT VALUE CHANGES
            # we need to compare the current weights with the cached weights
            changed_weights = dict()
            current_weights = self._get_current_weights_values()
            for idx, current_value in current_weights.items():
                cached_value = self.chached_weights.get(idx, None)
                if cached_value is None or abs(cached_value - current_value) > 0.0001:
                    changed_weights[idx] = current_value
            if changed_weights:
                for idx, value in changed_weights.items():
                    shape_name = self.get_shape_name(idx)
                    self.shapeValueChanged.emit(idx, shape_name, value)
                    # print(f"  Emitted shapeValueChanged for shape: '{shape_name}' at index {idx} at value {value} due to output geometry change.")
                # update the cached weights
                self.chached_weights = current_weights

        elif message == 10240 and plugChanged == self._weight_plug:

            #print(f"REMOVED: {message}, logical {index} {plugChanged} last count {self._last_count} current count {current_count}")
            if current_count < self._last_count:
                self.shapeRemoved.emit(index, last_shape_name)
                # print("Removed index")
            self._store_indices_and_aliases()

        # Value changed (2304 = kAttributeSet | kAttributeEval)
        elif message == 2304 and plugChanged == self._weight_plug:  # NAME CHANGED?
            # print(f"WEIGHT NAME CHANGED: {message}, logical {index} {plugChanged} last count {self._last_count} current count {current_count}")
            if current_count == self._last_count and last_shape_name is not None:
                self.shapeRenamed.emit(index, shape_name, last_shape_name)


        elif message == 2056 and self._target_visibility_plug == plugChanged:  # TARGET VISIBILITY CHANGED?
            # print(f"TARGET VISIBILITY CHANGED: {message}, logical {index} {plugChanged} last count {self._last_count} current count {current_count}")
            self.targetVisibilityChanged.emit(index, shape_name, target_visibility)
        
        elif message == 18433 and self._weight_plug == plugChanged:  # INPUT CONNECTION MADE
            #print(f"INPUT CONNECTION MADE: {message}, logical {index} {plugChanged} last count {self._last_count} current count {current_count}")
            self.shapeInputConnected.emit(index, True)
        elif message == 18434 and self._weight_plug == plugChanged:  # INPUT CONNECTION BROKEN
            #print(f"INPUT CONNECTION BROKEN: {message}, logical {index} {plugChanged} last count {self._last_count} current count {current_count}")
            self.shapeInputConnected.emit(index, False)

        self._depending_weights_idxs.clear()


    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def start(self):
        node_removed_callback_id = om2.MDGMessage.addNodeRemovedCallback(
            self._on_node_removed,
            self._fn_dep.typeName,)
        dirty_plug_callback_id = om2.MNodeMessage.addNodeDirtyPlugCallback(
            self._mobj,
            self._on_dirty_plug,
            None
        )
        attr_change_callback_id = om2.MNodeMessage.addAttributeChangedCallback(
            self._mobj,
            self._on_attribute_changed,
            None
        )

        self._attribute_callback_ids.add(node_removed_callback_id)
        self._attribute_callback_ids.add(attr_change_callback_id)
        self._attribute_callback_ids.add(dirty_plug_callback_id)

    def stop(self, *args, **kwargs):
        
        for cb_id in list(self._attribute_callback_ids):
            try:
                om2.MMessage.removeCallback(cb_id)
            except:
                # print(f"Failed to remove callback id: {cb_id}")
                pass
        self._attribute_callback_ids.clear()


    def get_shape_count(self):
        return self._weight_plug.numElements()

    def get_shape_indices(self):
        indices = []
        for i in range(self._weight_plug.numElements()):
            element = self._weight_plug.elementByPhysicalIndex(i)
            indices.append(element.logicalIndex())
        return sorted(indices)

    def get_shape_name(self, index):
        available_indices = self._weight_plug.getExistingArrayAttributeIndices()
        if index not in available_indices:
            return f"weight[{index}]"
        else:
            element = self._weight_plug.elementByLogicalIndex(index)
            return self._fn_dep.plugsAlias(element)

    def get_target_visibility(self, index):
        available_indices = self._target_visibility_plug.getExistingArrayAttributeIndices()
        if index not in available_indices:
            return False
        else:
            element = self._target_visibility_plug.elementByLogicalIndex(index)
            return element.asBool()
        
    def get_shape_value(self, index):
        element = self._weight_plug.elementByLogicalIndex(index)
        print(f"Getting shape value for plug: {element.name()}")
        if element.isDestination:
            src = element.source()
            if not src.isNull:
                print(f"  Getting connected shape value from source plug: {src.name()}")
                plug_value = src.asFloat()  # safe: read upstream, no blendShape eval
                return plug_value
        return element.asFloat()   


    def kill(self):
        self.stop()
        self._mobj = None
        self._fn_dep = None
        self._weight_plug = None
        self._target_visibility_plug = None
        self._attribute_callback_ids.clear()
        
        

    def __del__(self):
        self.kill()

    def _get_attribute_message_string(self, msg):
        """Helper to decode MNodeMessage attribute change flags into a readable string."""
        flags = []
        if msg & om2.MNodeMessage.kConnectionMade:
            flags.append("kConnectionMade")
        if msg & om2.MNodeMessage.kConnectionBroken:
            flags.append("kConnectionBroken")
        if msg & om2.MNodeMessage.kAttributeEval:
            flags.append("kAttributeEval")
        if msg & om2.MNodeMessage.kAttributeSet:
            flags.append("kAttributeSet")
        if msg & om2.MNodeMessage.kAttributeLocked:
            flags.append("kAttributeLocked")
        if msg & om2.MNodeMessage.kAttributeUnlocked:
            flags.append("kAttributeUnlocked")
        if msg & om2.MNodeMessage.kAttributeAdded:
            flags.append("kAttributeAdded")
        if msg & om2.MNodeMessage.kAttributeRemoved:
            flags.append("kAttributeRemoved")
        if msg & om2.MNodeMessage.kAttributeRenamed:
            flags.append("kAttributeRenamed")
        if msg & om2.MNodeMessage.kAttributeKeyable:
            flags.append("kAttributeKeyable")
        if msg & om2.MNodeMessage.kAttributeUnkeyable:
            flags.append("kAttributeUnkeyable")
        if msg & om2.MNodeMessage.kAttributeArrayAdded:
            flags.append("kAttributeArrayAdded")
        if msg & om2.MNodeMessage.kAttributeArrayRemoved:
            flags.append("kAttributeArrayRemoved")
        if msg & om2.MNodeMessage.kOtherPlugSet:
            flags.append("kOtherPlugSet")
        
        return " | ".join(flags) if flags else f"Unknown({msg})"


class ControllerTracker(QObject):
    """
    Tracks attribute changes on a Maya node (e.g. a rig controller),
    emitting signals when user-defined attributes are added, removed,
    or when any attribute value changes.
    """

    attributeChanged = Signal(str, object)  # attr partial name, new value
    attributeAdded = Signal(str)            # attr partial name
    attributeRemoved = Signal(str)          # attr partial name
    nodeDeleted = Signal(str)               # node name

    def __init__(self, node_name: str, parent=None):
        super().__init__(parent=parent)
        self._mobj = self._get_mobject(node_name)
        if self._mobj is None or self._mobj.isNull():
            raise ValueError(f"Node '{node_name}' not found.")
        self._fn_dep = om2.MFnDependencyNode(self._mobj)
        self._callback_ids = set()

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def node_name(self) -> str:
        if self._fn_dep:
            return self._fn_dep.name()
        return "<deleted>"

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_mobject(self, node_name: str) -> om2.MObject:
        """Return MObject from node name, or None if not found."""
        sel = om2.MSelectionList()
        try:
            sel.add(node_name)
            return sel.getDependNode(0)
        except Exception:
            return None

    def _get_plug_value(self, plug: om2.MPlug):
        """Attempt to read a plug value as a Python object."""
        try:
            api_type = plug.attribute().apiType()
            if api_type in (om2.MFn.kDoubleLinearAttribute, om2.MFn.kFloatLinearAttribute,
                            om2.MFn.kDoubleAngleAttribute, om2.MFn.kFloatAngleAttribute,
                            om2.MFn.kDoubleAttribute, om2.MFn.kFloatAttribute):
                return plug.asDouble()
            elif api_type in (om2.MFn.kIntAttribute, om2.MFn.kLongAttribute, om2.MFn.kShortAttribute):
                return plug.asInt()
            elif api_type == om2.MFn.kBoolAttribute:
                return plug.asBool()
            elif api_type == om2.MFn.kEnumAttribute:
                return plug.asInt()
            elif api_type == om2.MFn.kStringAttribute:
                return plug.asString()
            else:
                return plug.asDouble()
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Callback handlers
    # ------------------------------------------------------------------

    def _on_attribute_changed(self, message, plug: om2.MPlug, other_plug: om2.MPlug, client_data):
        """Handles attribute change messages from MNodeMessage."""
        if plug.isNull:
            return

        if message & om2.MNodeMessage.kAttributeAdded:
            self.attributeAdded.emit(plug.partialName())
            return

        if message & om2.MNodeMessage.kAttributeRemoved:
            self.attributeRemoved.emit(plug.partialName())
            return

        if message & om2.MNodeMessage.kAttributeSet:
            if plug.isCompound:
                return  # children fire individually; skip parent to avoid duplicates
            value = self._get_plug_value(plug)
            self.attributeChanged.emit(plug.partialName(), value)

    def _on_node_removed(self, node_obj, client_data=None):
        """Triggered when the tracked node is removed from the scene."""
        if node_obj == self._mobj:
            self.nodeDeleted.emit(self.node_name)
            self.kill()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self):
        """Register attribute change and node-removed callbacks."""
        attr_cb = om2.MNodeMessage.addAttributeChangedCallback(
            self._mobj,
            self._on_attribute_changed,
            None
        )
        node_removed_cb = om2.MDGMessage.addNodeRemovedCallback(
            self._on_node_removed,
            self._fn_dep.typeName
        )
        self._callback_ids.add(attr_cb)
        self._callback_ids.add(node_removed_cb)

    def stop(self):
        """Remove all registered callbacks."""
        for cb_id in list(self._callback_ids):
            try:
                om2.MMessage.removeCallback(cb_id)
            except Exception:
                pass
        self._callback_ids.clear()

    def kill(self):
        """Stop tracking and release all references."""
        self.stop()
        self._mobj = None
        self._fn_dep = None

    def __del__(self):
        self.kill()

