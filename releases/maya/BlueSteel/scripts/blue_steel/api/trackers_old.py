from .. import env
from . import logger
import logging
from enum import auto, Enum
from typing import List

import maya.api.OpenMaya as om2
import maya.OpenMaya as om
import maya.OpenMayaUI as omui
if env.MAYA_VERSION >=2023:
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


# class NodeView(QObject):
#     """
#     Tracks a specific Maya node by name, emitting signals on deletion, recreation
#     and destruction when the node is permanently removed fromthe undo stack.
#     Also handles scene lifecycle events to ensure proper cleanup of callbacks.
#     Args:
#         node_name (str): The name of the Maya node to track.
#         parent (QObject, optional): Parent QObject. Defaults to None.
#     Examples:
#         node_view = NodeView("myNode")
#         node_view.nodeDeleted.connect(lambda name: print(f"Node {name} deleted"))
#         node_view.nodeRecreated.connect(lambda name: print(f"Node {name} recreated"))
#         node_view.nodeDestroyed.connect(lambda name: print(f"Node {name} destroyed"))
#     """

#     nodeDeleted = Signal(QObject)
#     nodeRecreated = Signal(QObject)
#     nodeDestroyed = Signal(QObject)

#     def __init__(self, node_name: str, parent=None):
#         super().__init__(parent)
#         self._node_destroyed_callback_id = None
#         self._node_added_callback_id = None
#         self._node_removed_callback_id = None
#         self._node_callback_ids = set()
#         self._scene_callback_ids = set()
#         self._mobject = self._get_mobject(node_name)
#         self._mobject_handle = om2.MObjectHandle(self._mobject) if self._mobject else None
#         if not self._mobject:
#             raise RuntimeError(f"Node '{node_name}' does not exist.")

#         # Store MFnDependencyNode and node type name
#         self._fn_dep = om2.MFnDependencyNode(self._mobject)
#         self._node_type = self._fn_dep.typeName
#         self.node_name = self._fn_dep.name()
#         self.uuid = self._fn_dep.uuid().asString()

#         # the node will always track itself
#         # Register callbacks
#         self._add_node_added_callback()
#         self._add_node_removed_callback()
#         self._add_node_destroyed_callback()
#         self._add_scene_lifecycle_callbacks()

#     # ------------------------------------------------------------------
#     # Setup helpers
#     # ------------------------------------------------------------------
#     def _get_mobject(self, node_name: str) -> om2.MObject:
#         """Return MObject from node name, or None if not found."""
#         sel = om2.MSelectionList()
#         try:
#             sel.add(node_name)
#             return sel.getDependNode(0)
#         except Exception:
#             return None

#     def _add_node_added_callback(self):
#         cb = om2.MDGMessage.addNodeAddedCallback(self._on_node_added,
#                                                  self._node_type)
#         self._node_added_callback_id = cb

#     def _add_node_removed_callback(self):
#         """Add DG callbacks specific to this node's type."""
#         cb = om2.MDGMessage.addNodeRemovedCallback(self._on_node_removed,
#                                                  self._node_type)
#         self._node_removed_callback_id = cb


#     def _add_node_destroyed_callback(self):
#         """Add destruction callback specific to this node instance."""
#         if not self._mobject:
#             return
#         if self._node_destroyed_callback_id is not None:
#             # there is already a callback registered
#             return
#         cb = om2.MNodeMessage.addNodeDestroyedCallback(
#             self._mobject, self._on_node_destroyed
#         )
#         self._node_destroyed_callback_id = cb

#     def _remove_node_added_callback(self):
#         """Remove the node added callback."""
#         if self._node_added_callback_id is not None:
#             try:
#                 om2.MMessage.removeCallback(self._node_added_callback_id)
#             except Exception:
#                 pass
#             self._node_added_callback_id = None
#     def _remove_node_removed_callback(self):
#         """Remove the node removed callback."""
#         if self._node_removed_callback_id is not None:
#             try:
#                 om2.MMessage.removeCallback(self._node_removed_callback_id)
#             except Exception:
#                 pass
#             self._node_removed_callback_id = None

#     def _remove_node_destroyed_callback(self):
#         """Remove the node destroyed callback."""
#         if self._node_destroyed_callback_id is not None:
#             try:
#                 om2.MMessage.removeCallback(self._node_destroyed_callback_id)
#             except Exception:
#                 pass
#             self._node_destroyed_callback_id = None

#     def _remove_scene_callbacks(self):
#         """Remove scene reset callbacks."""
#         for cb in self._scene_callback_ids:
#             try:
#                 om2.MMessage.removeCallback(cb)
#             except Exception:
#                 pass
#         self._scene_callback_ids.clear()

#     # ------------------------------------------------------------------
#     # Scene lifecycle protection
#     # ------------------------------------------------------------------
#     def _add_scene_lifecycle_callbacks(self):
#         """Add callbacks to clean up DG callbacks before a new scene is created/opened."""
#         for msg_type in (om2.MSceneMessage.kBeforeNew, om2.MSceneMessage.kBeforeOpen):
#             cb = om2.MSceneMessage.addCallback(msg_type, self._on_scene_reset)
#             self._scene_callback_ids.add(cb)

#     def _on_scene_reset(self, *args):
#         """Triggered before new/open scene; removes DG callbacks safely."""
#         self.nodeDestroyed.emit(self)
#         self.kill()

#     # ------------------------------------------------------------------
#     # Callback handlers
#     # ------------------------------------------------------------------
#     def _on_node_destroyed(self, obj, client_data=None):
#         """Triggered when viewed node is destroyed."""
#         print(f"_on_node_destroyed called for node: {self.node_name, self}")
#         print(f"MObjectHandle is valid: {self._mobject_handle.isValid() if self._mobject_handle else 'No handle'}")
#         print(f"MObjectHandle is alive: {self._mobject_handle.isAlive() if self._mobject_handle else 'No handle'}")
#         self.nodeDestroyed.emit(self)
#         self.kill()
    

#     def _on_node_added(self, node_obj, client_data=None):
#         """Triggered when the node is added (undo recreation check)."""
#         if self._mobject == node_obj:
#             print(f"_on_node_added called for node: {self.node_name, self}")
#             print(f"MObjectHandle is valid: {self._mobject_handle.isValid() if self._mobject_handle else 'No handle'}")
#             print(f"MObjectHandle is alive: {self._mobject_handle.isAlive() if self._mobject_handle else 'No handle'}")
#             self.nodeRecreated.emit(self)
#         return
            
#     def _on_node_removed(self, node_obj, client_data=None):
#         """Triggered when the node is removed (before deletion)."""
#         if self._mobject == node_obj:
#             print(f"_on_node_removed called for node: {self.node_name, self}")
#             print(f"MObjectHandle is valid: {self._mobject_handle.isValid() if self._mobject_handle else 'No handle'}")
#             print(f"MObjectHandle is alive: {self._mobject_handle.isAlive() if self._mobject_handle else 'No handle'}")
#             self.nodeDeleted.emit(self)
#         return

#     # ------------------------------------------------------------------
#     # Public API
#     # ------------------------------------------------------------------

#     def node_type(self) -> str:
#         """Return the Maya node type (e.g., 'blendShape', 'mesh', etc.)."""
#         return self._node_type


#     def kill(self):
#         """Stop tracking and clean up callbacks."""
#         self._remove_node_added_callback()
#         self._remove_node_removed_callback()
#         self._remove_node_destroyed_callback()
#         self._remove_scene_callbacks()
#         self._mobject_handle = None
#         self._mobject = None


#     def __del__(self):
#         """Ensure cleanup on deletion."""
#         print(f"NodeView __del__ called for node: {self.node_name}")
#         self.kill()



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
    connectedShapeValueChanged = Signal(int, str, float) # return index, name and new value from input connection
    inbetweenShapeValueChanged = Signal(int, str, float) # return index, name and new value from input connection
    comboShapeValueChanged = Signal(int, str, float) # return index, name and new value from input connection
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
        self._target_visibility_plug = self._fn_dep.findPlug('targetVisibility', False)
        # attribute change callbacks
        self._attribute_callback_ids = set()
        self._last_indexes = []
        self._last_weights = []
        self._last_aliases = []
        self._depending_weights_idxs = set()
        self._store_indices_and_aliases()
        # print(f"Initialized BlendShapeView for node: {node_name}")

    @property
    def node_name(self):
        # check if the mobject is still valid
        if self._fn_dep:
            return self._fn_dep.name()
        return "<deleted>"


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
            self._depending_weights_idxs.add(dirtyPlug.logicalIndex())

    ### ------------------------------------------------------------------ 
    def _on_attribute_changed(self, message, plugChanged: om2.MPlug, otherPlugChanged, clentData):
        # Only process weight array element changes
        if not plugChanged.isElement:
            # print(f"EXIT not array plug: {plugChanged.name()}")
            return

        try:
            if plugChanged not in  [self._weight_plug, self._target_visibility_plug]:
                # print("Wrong plug EXIT", plugChanged.name())
                return
        except Exception as e:
            # If we can't even check the array, bail
            # print("Exception EXIT:", e)
            return

        
        try:
            index = plugChanged.logicalIndex()
            shape_value = self.get_shape_value(index)
            shape_name = self.get_shape_name(index)
            last_shape_name = self.get_last_alias_at_index(index)
            target_visibility = self.get_target_visibility(index)
        except Exception as e:
            # print("Error in index EXIT:", e)

            # Can't get the index, can't do anything
            return

        current_count = self._weight_plug.numElements()
        
        # Debug print with decoded message
        # msg_str = self._get_attribute_message_string(message)
        # print(f"MSG: {msg_str} ({message}), logical {index} {plugChanged.name()}")

        # Array element add/remove (6144 = kConnectionMade | kConnectionBroken)
        if message == 6144 and plugChanged == self._weight_plug:
            # print(f"ADDED: {message}, logical {index} {plugChanged} last count {self._last_count} current count {current_count}")
            if current_count > self._last_count:
                self.shapeAdded.emit(index, shape_name)
                # print("Added index")

            self._store_indices_and_aliases()

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

        elif message == 2056 and self._weight_plug == plugChanged:  # VALUE CHANGED?
            # print(f"SHAPE WEIGHT VALUE CHANGED: {message}, logical {index} {plugChanged} last count {self._last_count} current count {current_count}")
            # if plugChanged.connectedTo(False, True) or plugChanged.connectedTo(False, False): # this should prevent
            #print(f"SHAPE: '{shape_name}' at index {index} value {shape_value}.")
            # print(f"SKIP VALUE CHANGE EMIT DUE TO INPUT CONNECTION: {message}, logical {index} name {shape_name} value {shape_value} plug {plugChanged.name()}")
            self.shapeValueChanged.emit(index, shape_name, shape_value)
            if self._depending_weights_idxs:
                #print(f"  Processing {len(self._depending_weights_idxs)} depending weights due to input connections:")
                i = 1
                for depending_index in list(self._depending_weights_idxs):
                    depending_shape_name = self.get_shape_name(depending_index)
                    depending_shape_value = self.get_shape_value(depending_index)
                    #print(f"   {i}. CONNECTED SHAPE : '{depending_shape_name}' at index {depending_index} value {depending_shape_value}.")
                    self.connectedShapeValueChanged.emit(depending_index, depending_shape_name, depending_shape_value)
                    i += 1
                self._depending_weights_idxs.clear()

        elif message == 2056 and self._target_visibility_plug == plugChanged:  # TARGET VISIBILITY CHANGED?
            # print(f"TARGET VISIBILITY CHANGED: {message}, logical {index} {plugChanged} last count {self._last_count} current count {current_count}")
            self.targetVisibilityChanged.emit(index, shape_name, target_visibility)
        
        elif message == 18433 and self._weight_plug == plugChanged:  # INPUT CONNECTION MADE
            #print(f"INPUT CONNECTION MADE: {message}, logical {index} {plugChanged} last count {self._last_count} current count {current_count}")
            self.shapeInputConnected.emit(index, True)
        elif message == 18434 and self._weight_plug == plugChanged:  # INPUT CONNECTION BROKEN
            #print(f"INPUT CONNECTION BROKEN: {message}, logical {index} {plugChanged} last count {self._last_count} current count {current_count}")
            self.shapeInputConnected.emit(index, False)


        # elif self._weight_plug == plugChanged:
        #     msg_str = self._get_attribute_message_string(message)
        #     print(f"OTHER WEIGHT CHANGE: {msg_str} ({message}), logical {index} name {shape_name} value {shape_value} plug {plugChanged.name()}")
        # we need to clean up the depending weights indexes
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

        # super().start()
        # # print("BlendShapeView started and callbacks registered.")

        
    def stop(self, *args, **kwargs):
        
        for cb_id in list(self._attribute_callback_ids):
            try:
                om2.MMessage.removeCallback(cb_id)
            except:
                # print(f"Failed to remove callback id: {cb_id}")
                pass
        self._attribute_callback_ids.clear()
        # super().stop()
        # # print("BlendShapeView stopped and callbacks removed.")

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
        available_indices = self._weight_plug.getExistingArrayAttributeIndices()
        if index not in available_indices:
            return 0.0
        else:
            element = self._weight_plug.elementByLogicalIndex(index)
            return element.asFloat()


    def kill(self):
        self.stop()
        self._mobj = None
        self._fn_dep = None
        self._weight_plug = None
        self._target_visibility_plug = None
        self._attribute_callback_ids.clear()
        
        

    def __del__(self):
        #print("BlendShapeView __del__ called")
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

