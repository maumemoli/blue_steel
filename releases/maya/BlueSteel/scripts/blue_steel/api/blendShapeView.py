from .. import env
from .trackers import NodeView
import logging
from enum import auto, Enum
from typing import List

import maya.api.OpenMaya as om2
import maya.OpenMayaUI as omui
if env.MAYA_VERSION >=2023:
    from shiboken6 import wrapInstance
    from PySide6.QtCore import QObject, Signal, QAbstractListModel, Qt, QModelIndex, QSortFilterProxyModel, QItemSelection
    from PySide6.QtWidgets import QWidget, QVBoxLayout, QListView, QSplitter, QPushButton

else:
    from shiboken2 import wrapInstance
    from PySide2.QtCore import QObject, Signal, QAbstractListModel, Qt, QModelIndex, QSortFilterProxyModel, QItemSelection
    from PySide2.QtWidgets import QWidget, QVBoxLayout, QListView, QSplitter, QPushButton



class BlendShapeView(NodeView):
    """
    Manages the callbacks coming from the blend shape node to notify 
    of changes in the shape weights or targets using different Signals.
    """
    shapeAdded = Signal(int, str) # return index and name
    shapeRemoved = Signal(int, str) # return index and name
    shapeRenamed = Signal(int, str, str) # return index, new name and old name
    shapeValueChanged = Signal(int, str, float) # return index, name and new value
    inbetweenShapeValueChanged = Signal(int, str, float) # return index, name and new value from input connection
    comboShapeValueChanged = Signal(int, str, float) # return index, name and new value from input connection
    targetVisibilityChanged = Signal(int, str, bool) # return index and visibility state

    def __init__(self, node_name):
        super().__init__(node_name=node_name, parent=None)
        
        self._mobj = self._get_mobject(node_name)
        if self._mobj.apiType() != om2.MFn.kBlendShape:
            raise TypeError(f"Node '{node_name}' is not a blend shape.")
        self._fn_dep = om2.MFnDependencyNode(self._mobj)
        self._weight_plug = self._fn_dep.findPlug('weight', False)
        self._target_visibility_plug = self._fn_dep.findPlug('targetVisibility', False)
        self._attribute_callback_ids = set()
        self._last_indexes = []
        self._last_weights = []
        self._last_aliases = []
        self._depending_weights_idxs = set()
        self._store_indices_and_aliases()
        # print(f"Initialized BlendShapeView for node: {node_name}")

    
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
        print(f"Node added - re-establishing callbacks for node: {self.node_name}")
        self.start()

    def _on_node_removed(self, node_obj, client_data=None):
        """Handle node removed event to clean up callbacks."""
        super()._on_node_removed(node_obj, client_data)
        print(f"Node removed - cleaning up callbacks for node: {self.node_name}")
        self.stop()
    ### ------------------------------------------------------------------
    def _on_dirty_plug(self, node: om2.MObject, dirtyPlug: om2.MPlug, clientData):
        # This callback is called when a plug is dirtied
        # We can use it to monitor changes to the weight and targetVisibility plugs
        if dirtyPlug != self._weight_plug or not dirtyPlug.isElement:
            print(f"EXIT not weight array plug: {dirtyPlug.name()}")
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
            print("Error in index EXIT:", e)

            # Can't get the index, can't do anything
            return

        current_count = self._weight_plug.numElements()
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
            print(f"SHAPE: '{shape_name}' at index {index} value {shape_value}.")
            # print(f"SKIP VALUE CHANGE EMIT DUE TO INPUT CONNECTION: {message}, logical {index} name {shape_name} value {shape_value} plug {plugChanged.name()}")
            self.shapeValueChanged.emit(index, shape_name, shape_value)
            if self._depending_weights_idxs:
                print(f"  Processing {len(self._depending_weights_idxs)} depending weights due to input connections:")
                i = 1
                for depending_index in list(self._depending_weights_idxs):
                    depending_shape_name = self.get_shape_name(depending_index)
                    depending_shape_value = self.get_shape_value(depending_index)
                    print(f"   {i}. CONNECTED SHAPE : '{depending_shape_name}' at index {depending_index} value {depending_shape_value}.")
                    self.shapeValueChanged.emit(depending_index, depending_shape_name, depending_shape_value)
                    i += 1
                self._depending_weights_idxs.clear()

        elif message == 2056 and self._target_visibility_plug == plugChanged:  # TARGET VISIBILITY CHANGED?
            # print(f"TARGET VISIBILITY CHANGED: {message}, logical {index} {plugChanged} last count {self._last_count} current count {current_count}")
            self.targetVisibilityChanged.emit(index, shape_name, target_visibility)
            
        # elif self._weight_plug == plugChanged:
        #     print(f"OTHER WEIGHT CHANGE: {message}, logical {index} name {shape_name} value {shape_value} plug {plugChanged.name()}")
        # we need to clean up the depending weights indexes
        self._depending_weights_idxs.clear()


    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def start(self):
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

        self._attribute_callback_ids.add(attr_change_callback_id)
        self._attribute_callback_ids.add(dirty_plug_callback_id)

        # super().start()
        # # print("BlendShapeView started and callbacks registered.")

        
    def stop(self, *args, **kwargs):
        
        for cb_id in list(self._attribute_callback_ids):
            try:
                om2.MMessage.removeCallback(cb_id)
            except:
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
        super().kill()
        

    def __del__(self):
        print("BlendShapeView __del__ called")
        self.stop()
        super().__del__()
        
