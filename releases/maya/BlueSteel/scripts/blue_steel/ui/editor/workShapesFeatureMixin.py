"""Blue Steel editor main window.

This module contains the :class:`MainWindow` dockable editor and the ``show``
entry point. Models, delegates, views, and standalone widgets have been moved
to the sibling modules in this package.

Example:
    >>> from blue_steel.ui.editor import mainWindow
    >>> win = mainWindow.show()
    >>> win.set_current_editor("characterA_blueSteel_container")
"""

from __future__ import annotations

from typing import List, Optional, Sequence

from maya import cmds

from ... import env
from ...api.treeViewOrderingManager import TreeViewOrderingManager
from .constants import (
    PRIMARY_TREE_FOLDER_ROLE,
    PRIMARY_TREE_NAME_ROLE,
)
from .mainWindowMixin import MainWindowMixin, target_shape_names
from .models import (
    ShapeItemsModel,
    WorkShapeRoles,
)
from .qt import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGuiApplication,
    QInputDialog,
    QLabel,
    QModelIndex,
    QSpinBox,
    QTimer,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    Qt,
)
from .widgets import (
    InlineWorkshapeRenameEditor,
)


class WorkShapesFeatureMixin(MainWindowMixin):
    def _selected_work_shape_names(self) -> List[str]:
        """Return the names of the selected work shapes.

        Returns:
            List[str]: The selected work-shape names.
        """
        names: List[str] = []
        for item in self.work_shapes_view.selectedItems():
            if bool(item.data(0, ShapeItemsModel.IsHeaderRole)):
                continue
            name = str(item.data(0, PRIMARY_TREE_NAME_ROLE) or item.data(0, ShapeItemsModel.NameRole) or "")
            if name:
                names.append(name)
        return names


    def _first_selected_work_shape_name(self) -> Optional[str]:
        """Return the first selected work-shape name, or ``None``.

        Returns:
            Optional[str]: The first selected work-shape name, or ``None``
            when no work shape is selected.
        """
        selected_names = self._selected_work_shape_names()
        if not selected_names:
            return None
        return selected_names[0]


    def _select_work_shape(self, shape_name: str) -> None:
        """Select a work shape in the work-shapes view.

        Parameters:
            shape_name (str): The work-shape name to select.

        Returns:
            None
        """
        item = self._work_shape_item(shape_name)
        if item is None:
            return
        view = self.work_shapes_view
        view.clearSelection()
        item.setSelected(True)
        view.setCurrentItem(item)


    def _on_work_shapes_selection_changed(self, *_args) -> None:
        """Update the button panel and heat-map target on selection changes.

        Returns:
            None
        """
        self._update_work_shape_button_panel()
        self._update_heat_map_target_from_work_shapes_selection()


    def _update_work_shape_button_panel(self) -> None:
        """Enable or disable the work-shape action buttons based on state.

        Returns:
            None
        """
        has_editor = self.current_editor is not None and self.current_editor.work_blendshape is not None
        selected_shape_name = self._first_selected_work_shape_name()
        has_selection = bool(selected_shape_name)
        self.work_add_button.setEnabled(has_editor)
        self.work_remove_button.setEnabled(has_editor and has_selection)
        self.work_paint_button.setEnabled(has_editor and has_selection)
        self.apply_work_shapes_button.setEnabled(has_editor and self._has_connected_driver_shapes())


    def _stop_active_blendshape_trackers(self) -> None:
        """Stop every active blendshape tracker.

        Returns:
            None
        """
        for tracker in (
            self.blendshape_tracker,
            self.work_blendshape_tracker,
            self.split_map_edit_blendshape_tracker,
        ):
            if tracker is not None:
                # print(f"Stopping active blendshape tracker {tracker.node_name}.")
                tracker.stop()


    def _start_active_blendshape_trackers(self) -> None:
        """Start every active blendshape tracker.

        Returns:
            None
        """
        for tracker in (
            self.blendshape_tracker,
            self.work_blendshape_tracker,
            self.split_map_edit_blendshape_tracker,
        ):
            if tracker is not None:
                # print(f"Starting active blendshape tracker {tracker.node_name}.")
                tracker.start()


    def _reload_work_shapes_from_editor(self) -> None:
        """Rebuild the work-shape tree and refresh dependent UI.

        Returns:
            None
        """
        self._rebuild_work_shapes_tree()
        self._update_delegate_name_columns()
        self._update_work_shape_button_panel()


    # ------------------------------------------------------------------
    # Work-shapes tree: build, persist, and mutate through the shared store
    # ------------------------------------------------------------------
    def _rebuild_work_shapes_tree(self) -> None:
        """Build the Work Shapes tree from the persisted sorting store."""
        selected = set(self._selected_work_shape_names())
        collapsed_folders = self._collapsed_work_shape_folder_names()
        self.work_shapes_view.clear()
        self._work_shape_tree_items.clear()

        editor = self.current_editor
        if editor is None or editor.work_blendshape is None:
            self.work_shapes_view._sync_driver_expansion(None)
            return

        weights = sorted(editor.get_work_blendshape_weights() or [], key=lambda w: str(w).lower())
        names = [str(weight) for weight in weights]
        store = self._work_shape_sorting_store()
        if store.sync(names):
            self._save_work_shape_sorting_store(store)

        connected_weights = set(editor.get_work_blendshape_connected_targets_weights() or [])
        sculpt_indices = set(editor.work_blendshape.get_sculpt_target_indices() or [])
        info_by_name = {}
        edit_name = None
        for weight in weights:
            name = str(weight)
            connected = weight in connected_weights
            driver_connected = bool(editor.get_work_shape_driver_nodes(weight))
            drivers = ()
            if driver_connected:
                try:
                    drivers = tuple(dict.fromkeys(
                        str(driver) for driver in (editor.get_work_shape_driver_shapes(name) or []) if driver
                    ))
                except (RuntimeError, ValueError):
                    # A custom or partially disconnected graph may expose driver
                    # nodes without resolvable shape inputs; keep the parent usable.
                    drivers = ()
            info_by_name[name] = {
                "value": float(editor.work_blendshape.get_weight_value(weight)),
                "muted": bool(editor.get_work_shape_muted_state(name)),
                "connected": connected,
                "driver_connected": driver_connected,
                "driver_names": drivers,
                "tooltip": "Connected extraction mesh" if connected else None,
            }
            if edit_name is None and int(weight.id) in sculpt_indices:
                edit_name = name

        self._build_work_shapes_tree(
            store.ordered_tree(), None, info_by_name, edit_name, selected, collapsed_folders
        )
        self.work_shapes_view._sync_driver_expansion(editor)


    def _build_work_shapes_tree(
        self,
        nodes: Sequence[dict],
        parent_item: Optional[QTreeWidgetItem],
        info_by_name: dict,
        edit_name: Optional[str],
        selected_names: set,
        collapsed_folders: set,
    ) -> None:
        """Recursively create Work Shapes tree items from the store's nodes."""
        for node in nodes:
            name = str(node.get("name") or "")
            if not name:
                continue
            if node.get("type") == "group":
                folder = QTreeWidgetItem([name])
                folder.setData(0, PRIMARY_TREE_FOLDER_ROLE, True)
                folder.setData(0, PRIMARY_TREE_NAME_ROLE, name)
                folder.setData(0, ShapeItemsModel.NameRole, name)
                folder.setData(0, ShapeItemsModel.TypeRole, "WorkShapeFolder")
                folder.setData(0, ShapeItemsModel.ValueRole, 0.0)
                folder.setData(0, ShapeItemsModel.EditableRole, False)
                folder.setData(0, ShapeItemsModel.IsHeaderRole, True)
                folder.setData(0, ShapeItemsModel.MutedRole, False)
                folder.setData(0, ShapeItemsModel.LockedRole, False)
                folder.setData(0, ShapeItemsModel.LockIconVisibleRole, False)
                folder_font = folder.font(0)
                folder_font.setBold(True)
                folder.setFont(0, folder_font)
                folder.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsDragEnabled | Qt.ItemIsDropEnabled)
                if parent_item is None:
                    self.work_shapes_view.addTopLevelItem(folder)
                else:
                    parent_item.addChild(folder)
                folder.setExpanded(name not in collapsed_folders)
                self._update_work_shape_folder_icon(folder)
                self._build_work_shapes_tree(
                    node.get("children", []), folder, info_by_name, edit_name, selected_names, collapsed_folders
                )
                continue

            info = info_by_name.get(name)
            if info is None:
                # A stale persisted name that is not in the rig; sync removes it.
                continue
            leaf = QTreeWidgetItem([name])
            leaf.setData(0, PRIMARY_TREE_NAME_ROLE, name)
            leaf.setData(0, ShapeItemsModel.NameRole, name)
            leaf.setData(0, ShapeItemsModel.TypeRole, "WorkShape")
            leaf.setData(0, ShapeItemsModel.ValueRole, info["value"])
            leaf.setData(0, ShapeItemsModel.MutedRole, info["muted"])
            leaf.setData(0, ShapeItemsModel.EditableRole, True)
            leaf.setData(0, ShapeItemsModel.IsHeaderRole, False)
            leaf.setData(0, ShapeItemsModel.LockedRole, False)
            leaf.setData(0, ShapeItemsModel.LockIconVisibleRole, False)
            leaf.setData(0, WorkShapeRoles.InEditModeRole, name == edit_name)
            leaf.setData(0, WorkShapeRoles.ConnectedRole, info["connected"])
            leaf.setData(0, WorkShapeRoles.DriverConnectedRole, info["driver_connected"])
            leaf.setData(0, WorkShapeRoles.DriverNamesRole, info["driver_names"])
            if info.get("tooltip"):
                leaf.setData(0, Qt.ToolTipRole, info["tooltip"])
            leaf.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsEditable | Qt.ItemIsDragEnabled)
            if parent_item is None:
                self.work_shapes_view.addTopLevelItem(leaf)
            else:
                parent_item.addChild(leaf)
            self._work_shape_tree_items[name] = leaf
            if name in selected_names:
                leaf.setSelected(True)


    def _update_work_shape_folder_icon(self, item: Optional[QTreeWidgetItem]) -> None:
        """Match a Work Shapes folder's chevron to its expansion state.

        Mirrors ``_update_primary_tree_folder_icon`` so the delegate-painted
        group disclosure uses the same open/closed icon as the Primaries tree.
        """
        if item is None or not bool(item.data(0, PRIMARY_TREE_FOLDER_ROLE)):
            return
        open_icon = getattr(self, "_primary_tree_folder_open_icon", None)
        closed_icon = getattr(self, "_primary_tree_folder_closed_icon", None)
        if item.isExpanded() and open_icon is not None and not open_icon.isNull():
            item.setIcon(0, open_icon)
        elif closed_icon is not None and not closed_icon.isNull():
            item.setIcon(0, closed_icon)


    def _work_shape_sorting_store(self) -> TreeViewOrderingManager:
        """Return a Work Shapes store loaded from the active editor."""
        store = TreeViewOrderingManager(env.ENVIRONMENT.WORK_SHAPE_SORTING_ATTR_STRING_IDENTIFIER)
        try:
            store.load(self.current_editor)
        except Exception:
            store.from_dict(None)
        return store


    def _save_work_shape_sorting_store(self, store: TreeViewOrderingManager) -> None:
        """Persist the Work Shapes ordering, reporting failures without raising."""
        if self.current_editor is None:
            return
        try:
            store.save(self.current_editor)
        except Exception as exc:
            self._set_status(f"Failed saving work shape ordering: {exc}", warning=True)


    def _collapsed_work_shape_folder_names(self) -> set:
        """Collect names of currently collapsed Work Shapes folders."""
        collapsed = set()
        stack = [self.work_shapes_view.topLevelItem(i) for i in range(self.work_shapes_view.topLevelItemCount())]
        while stack:
            item = stack.pop()
            if item is None:
                continue
            if item.data(0, PRIMARY_TREE_FOLDER_ROLE) and not item.isExpanded():
                collapsed.add(str(item.data(0, ShapeItemsModel.NameRole) or item.text(0) or ""))
            for i in range(item.childCount()):
                stack.append(item.child(i))
        return collapsed


    def _work_shape_item(self, shape_name: str) -> Optional[QTreeWidgetItem]:
        """Return the tree item for ``shape_name`` (``None`` when absent)."""
        return self._work_shape_tree_items.get(str(shape_name))


    def _work_shape_edit_name(self) -> Optional[str]:
        """Return the work shape currently in sculpt/edit mode, if any."""
        for name, item in self._work_shape_tree_items.items():
            if bool(item.data(0, WorkShapeRoles.InEditModeRole)):
                return name
        return None


    def _set_work_shape_edit_name(self, shape_name: Optional[str]) -> None:
        """Update InEditModeRole on every work-shape item."""
        target = str(shape_name) if shape_name else None
        for name, item in self._work_shape_tree_items.items():
            should_edit = name == target
            if bool(item.data(0, WorkShapeRoles.InEditModeRole)) != should_edit:
                item.setData(0, WorkShapeRoles.InEditModeRole, should_edit)
        self.work_shapes_view.viewport().update()


    def _has_connected_driver_shapes(self) -> bool:
        """Return whether any work shape has a connected driver."""
        for item in self._work_shape_tree_items.values():
            if bool(item.data(0, WorkShapeRoles.DriverConnectedRole)):
                return True
        return False


    def _work_shape_value(self, shape_name: str) -> Optional[float]:
        """Return the cached tree value for ``shape_name``."""
        item = self._work_shape_item(shape_name)
        if item is None:
            return None
        return float(item.data(0, ShapeItemsModel.ValueRole) or 0.0)


    def _set_work_shape_value_local(self, shape_name: str, value: float) -> None:
        """Update one tree value from tracker callbacks without writing to Maya."""
        item = self._work_shape_item(shape_name)
        if item is None:
            return
        clamped = max(0.0, min(1.0, float(value)))
        if abs(float(item.data(0, ShapeItemsModel.ValueRole) or 0.0) - clamped) <= 1e-6:
            return
        self._syncing_work_shapes_tree = True
        try:
            item.setData(0, ShapeItemsModel.ValueRole, clamped)
        finally:
            self._syncing_work_shapes_tree = False


    def _set_work_shape_muted_local(self, shape_name: str, muted: bool) -> None:
        """Update one tree muted state without forcing a rebuild."""
        item = self._work_shape_item(shape_name)
        if item is None:
            return
        target = bool(muted)
        if bool(item.data(0, ShapeItemsModel.MutedRole)) == target:
            return
        self._syncing_work_shapes_tree = True
        try:
            item.setData(0, ShapeItemsModel.MutedRole, target)
        finally:
            self._syncing_work_shapes_tree = False
        self.work_shapes_view.viewport().update()


    def _set_work_shape_connected_local(self, shape_name: str, connected: bool) -> None:
        """Update one tree connected-mesh state without forcing a rebuild."""
        item = self._work_shape_item(shape_name)
        if item is None:
            return
        target = bool(connected)
        if bool(item.data(0, WorkShapeRoles.ConnectedRole)) == target:
            return
        self._syncing_work_shapes_tree = True
        try:
            item.setData(0, WorkShapeRoles.ConnectedRole, target)
            if target:
                item.setData(0, Qt.ToolTipRole, "Connected extraction mesh")
            else:
                item.setData(0, Qt.ToolTipRole, None)
        finally:
            self._syncing_work_shapes_tree = False
        self.work_shapes_view.viewport().update()


    def _set_work_shape_driver_connected_local(self, shape_name: str, connected: bool) -> None:
        """Update one tree driver state, refreshing cached driver names."""
        item = self._work_shape_item(shape_name)
        if item is None or self.current_editor is None or self.current_editor.work_blendshape is None:
            return
        target = bool(connected)
        drivers = ()
        if target:
            try:
                drivers = tuple(dict.fromkeys(
                    str(driver) for driver in (self.current_editor.get_work_shape_driver_shapes(shape_name) or []) if driver
                ))
            except (RuntimeError, ValueError):
                drivers = ()
        if (
            bool(item.data(0, WorkShapeRoles.DriverConnectedRole)) == target
            and item.data(0, WorkShapeRoles.DriverNamesRole) == drivers
        ):
            return
        self._syncing_work_shapes_tree = True
        try:
            item.setData(0, WorkShapeRoles.DriverConnectedRole, target)
            item.setData(0, WorkShapeRoles.DriverNamesRole, drivers)
        finally:
            self._syncing_work_shapes_tree = False
        index = self.work_shapes_view.indexFromItem(item, 0)
        if index.isValid() and self._work_shapes_delegate is not None:
            self._work_shapes_delegate.sizeHintChanged.emit(index)
        self.work_shapes_view.viewport().update()


    def _commit_work_shape_value(self, shape_name: str, value: float) -> None:
        """Write a work-shape value to Maya and report it."""
        if self.current_editor is None or self.current_editor.work_blendshape is None:
            return
        weight = self.current_editor.work_blendshape.get_weight_by_name(shape_name)
        if weight is None:
            return
        self.current_editor.work_blendshape.set_weight_value(weight, max(0.0, min(1.0, float(value))))
        self._on_work_shape_value_committed(shape_name, max(0.0, min(1.0, float(value))))


    def _on_work_shapes_tree_data_changed(self, top_left: QModelIndex, _bottom_right: QModelIndex, roles=None) -> None:
        """Commit work-shape value edits coming from the tree's sliders."""
        if self._syncing_work_shapes_tree:
            return
        if self.current_editor is None or self.current_editor.work_blendshape is None:
            return
        if roles and ShapeItemsModel.ValueRole not in roles:
            return
        item = self.work_shapes_view.itemFromIndex(top_left)
        if item is None or bool(item.data(0, ShapeItemsModel.IsHeaderRole)):
            return
        if not bool(item.data(0, ShapeItemsModel.EditableRole)):
            return
        shape_name = str(item.data(0, ShapeItemsModel.NameRole) or "")
        if not shape_name:
            return
        value = max(0.0, min(1.0, float(item.data(0, ShapeItemsModel.ValueRole) or 0.0)))
        self._commit_work_shape_value(shape_name, value)


    def _sync_work_shape_tree_values(self) -> List[tuple]:
        """Pull current work-blendshape values and update tree items in place."""
        if self.current_editor is None or self.current_editor.work_blendshape is None:
            return []
        changed: List[tuple] = []
        for name, item in self._work_shape_tree_items.items():
            new_value = self.current_editor.work_blendshape.get_weight_value_by_name(name)
            clamped = max(0.0, min(1.0, float(new_value or 0.0)))
            if abs(float(item.data(0, ShapeItemsModel.ValueRole) or 0.0) - clamped) <= 1e-6:
                continue
            self._set_work_shape_value_local(name, clamped)
            changed.append((name, clamped))
        return changed


    def _on_work_shapes_move_requested(self, names, target: str, position: str) -> None:
        """Apply a drag-reorder/reparent coming from the Work Shapes tree."""
        if self.current_editor is None:
            return
        store = self._work_shape_sorting_store()
        if str(position) == "root" or not str(target):
            changed = store.move_to_root(list(names))
        else:
            changed = store.move(list(names), str(target), str(position))
        if not changed:
            return
        self._save_work_shape_sorting_store(store)
        # Defer the rebuild until the drop event has fully unwound; clearing the
        # tree synchronously inside dropEvent can leave Qt holding stale items.
        QTimer.singleShot(0, self._rebuild_work_shapes_tree)


    def _group_selected_work_shapes(self) -> None:
        """Create a new folder containing the selected work shapes (Ctrl+G)."""
        if self.current_editor is None:
            return
        selected = self._selected_work_shape_names()
        if not selected:
            self._set_status("Select one or more work shapes to group.", warning=True)
            return
        name, ok = QInputDialog.getText(self, "Group Work Shapes", "Group name:", text="Group")
        if not ok:
            return
        store = self._work_shape_sorting_store()
        created = store.group(selected, (name or "").strip() or "Group")
        if not created:
            return
        self._save_work_shape_sorting_store(store)
        self._rebuild_work_shapes_tree()
        self._set_status(f"Grouped {len(selected)} work shape(s) into '{created}'.")


    def _rename_work_shape_folder(self, item: Optional[QTreeWidgetItem]) -> None:
        """Prompt for and apply a new name for a Work Shapes folder."""
        if self.current_editor is None or item is None:
            return
        old_name = str(item.data(0, ShapeItemsModel.NameRole) or item.text(0) or "")
        if not old_name:
            return
        new_name, ok = QInputDialog.getText(self, "Rename Group", "Group name:", text=old_name)
        if not ok:
            return
        new_name = (new_name or "").strip()
        if not new_name or new_name == old_name:
            return
        store = self._work_shape_sorting_store()
        if not store.rename(old_name, new_name):
            self._set_status(f"Could not rename group '{old_name}'.", warning=True)
            return
        self._save_work_shape_sorting_store(store)
        self._rebuild_work_shapes_tree()
        self._set_status(f"Renamed group '{old_name}' to '{new_name}'.")


    def _ungroup_selected_work_shapes(self) -> None:
        """Dissolve the selected Work Shapes folder, promoting its children."""
        if self.current_editor is None:
            return
        item = self.work_shapes_view.currentItem()
        if item is None or not bool(item.data(0, PRIMARY_TREE_FOLDER_ROLE)):
            self._set_status("Select a group to ungroup.", warning=True)
            return
        group_name = str(item.data(0, ShapeItemsModel.NameRole) or "")
        store = self._work_shape_sorting_store()
        if not store.ungroup(group_name):
            return
        self._save_work_shape_sorting_store(store)
        self._rebuild_work_shapes_tree()
        self._set_status(f"Ungrouped '{group_name}'.")


    def _on_add_work_shape_clicked(self) -> None:
        """Create a new work shape and select it.

        Returns:
            None
        """
        if self.current_editor is None:
            self._set_status("No system selected.", warning=True)
            return
        try:
            self._stop_active_blendshape_trackers()
            work_shape_name = str(self.current_editor.add_work_shape())
        except Exception as exc:
            self._set_status(f"Error creating work shape: {exc}", error=True)
            return
        finally:
            self._start_active_blendshape_trackers()
        self._reload_work_shapes_from_editor()
        self._select_work_shape(work_shape_name)
        self._set_status(f"Created work shape '{work_shape_name}'.")


    def _on_remove_work_shapes_clicked(self) -> None:
        """Remove the selected work shapes.

        Returns:
            None
        """
        if self.current_editor is None:
            self._set_status("No system selected.", warning=True)
            return
        shape_names = self._selected_work_shape_names()
        if not shape_names:
            self._set_status("No work shapes selected.", warning=True)
            return

        active_edit_shape = self._work_shape_edit_name()
        if active_edit_shape in shape_names:
            try:
                cmds.sculptTarget(self.current_editor.work_blendshape.name, e=True, t=-1)
            except Exception:
                pass
            self._set_work_shape_edit_name(None)

        removed_count = 0
        try:
            self._stop_active_blendshape_trackers()
            self.current_editor.delete_work_shapes(shape_names)
            removed_count = len(shape_names)
        except Exception as exc:
            self._set_status(f"Error removing work shape(s): {exc}", error=True)
            return
        finally:
            self._start_active_blendshape_trackers()

        self._reload_work_shapes_from_editor()
        self._set_status(f"Removed {removed_count} work shape(s).")


    def _on_paint_work_shape_clicked(self) -> None:
        """Enter paint mode for the selected work shape.

        Alt-click paints weights; otherwise paints masks.

        Returns:
            None
        """
        if self.current_editor is None:
            self._set_status("No system selected.", warning=True)
            return
        paint_weight = bool(QGuiApplication.keyboardModifiers() & Qt.AltModifier)
        shape_name = self._first_selected_work_shape_name()
        if not shape_name:
            self._set_status("Select one work shape first.", warning=True)
            return
        try:
            if paint_weight:
                target_id = self.current_editor.set_work_target_weight_paint_mode(shape_name)
            else:
                target_id = self.current_editor.set_work_target_mask_paint_mode(shape_name)
        except Exception as exc:
            self._set_status(f"Error entering paint mode: {exc}", error=True)
            return
        self._set_status(f"Paint mode on '{shape_name}' (target id {target_id}).")


    def _on_apply_work_shapes_clicked(self) -> None:
        """Apply the active work shapes to their connected shapes.

        Returns:
            None
        """
        if self.current_editor is None:
            self._set_status("No system selected.", warning=True)
            return
        try:
            self._stop_active_blendshape_trackers()
            applied_work_shapes = self.current_editor.apply_active_work_shapes()
        except Exception as exc:
            self._set_status(f"Error applying work shapes: {exc}", error=True)
            return
        finally:
            self._start_active_blendshape_trackers()
        self._reload_shapes_from_editor()
        self._set_status(f"Committed {len(applied_work_shapes)} linked shape(s). Check the Script Editor for the list.")


    def _on_work_shape_edit_mode_toggle_requested(self, shape_name: str, _state: bool) -> None:
        """Handle a work-shape edit-mode icon toggle.

        Parameters:
            shape_name (str): The work-shape name.
            _state (bool): The requested state (unused).

        Returns:
            None
        """
        self._on_toggle_work_shape_edit_mode(shape_name)


    def _on_toggle_work_shape_edit_mode(self, shape_name: Optional[str] = None) -> None:
        """Toggle edit mode for a work shape.

        Parameters:
            shape_name (Optional[str]): The work-shape name; defaults to the
                first selected work shape.

        Returns:
            None
        """
        if self.current_editor is None:
            self._set_status("No system selected.", warning=True)
            return
        if self.current_editor.work_blendshape is None:
            self._set_status("Work blendshape not found.", warning=True)
            return

        shape_name = shape_name or self._first_selected_work_shape_name()
        active_shape_name = self._work_shape_edit_name()
        if not shape_name:
            if active_shape_name:
                try:
                    cmds.sculptTarget(self.current_editor.work_blendshape.name, e=True, t=-1)
                except Exception as exc:
                    self._set_status(f"Error disabling edit mode: {exc}", error=True)
                    return
                self._set_work_shape_edit_name(None)
                self._set_status("Work shape edit mode disabled.")
                self._update_work_shape_button_panel()
                return
            self._set_status("Select one work shape first.", warning=True)
            return

        if active_shape_name == shape_name:
            try:
                cmds.sculptTarget(self.current_editor.work_blendshape.name, e=True, t=-1)
            except Exception as exc:
                self._set_status(f"Error disabling edit mode: {exc}", error=True)
                return
            self._set_work_shape_edit_name(None)
            self._set_status("Work shape edit mode disabled.")
            self._update_work_shape_button_panel()
            return

        item = self._work_shape_item(shape_name)
        if item is not None and bool(item.data(0, WorkShapeRoles.ConnectedRole)):
            self._set_status(f"Cannot enable edit mode for '{shape_name}' because it has a connected mesh.", warning=True)
            self._update_work_shape_button_panel()
            return

        try:
            self.current_editor.set_work_shape_editable(shape_name)
        except Exception as exc:
            self._set_status(f"Error enabling edit mode: {exc}", error=True)
            return
        self._set_work_shape_edit_name(shape_name)
        self._set_status(f"Edit mode enabled for '{shape_name}'.")

        self._update_work_shape_button_panel()


    def _on_work_shapes_double_clicked(self, item, column: int = 0) -> None:
        """Begin inline rename on a parent work shape.

        Driver-label double-clicks are handled separately by the view.

        Parameters:
            item (QTreeWidgetItem): The clicked tree item.
            column (int): The clicked column.

        Returns:
            None
        """
        if self.current_editor is None or item is None or column != 0:
            return
        if bool(item.data(0, ShapeItemsModel.IsHeaderRole)):
            return
        shape_name = str(item.data(0, ShapeItemsModel.NameRole) or "")
        if not shape_name:
            return
        self._begin_inline_workshape_rename(item)


    def _on_work_shape_driver_pose_requested(self, driver_name: str) -> None:
        """Activate the double-clicked driver, not the parent's first connection."""
        if self.current_editor is None or not driver_name:
            return
        if self.shapes_list_active_button.isChecked():
            self.shapes_list_active_button.setChecked(False)
        self._set_shape_pose_by_name(driver_name)
        self._select_shape_and_primaries(driver_name)


    def _on_work_shape_driver_removal_requested(self, work_shape_name: str, driver_name: str) -> None:
        """Disconnect only the dragged driver; never delete the driver shape."""
        if self.current_editor is None or not work_shape_name or not driver_name:
            return
        try:
            self._stop_active_blendshape_trackers()
            self.current_editor.disconnect_work_shape_drivers(work_shape_name, [driver_name])
        except Exception as exc:
            self._set_status(f"Error removing driver '{driver_name}' from '{work_shape_name}': {exc}", error=True)
            return
        finally:
            self._start_active_blendshape_trackers()
        self._reload_work_shapes_from_editor()
        self._select_work_shape(work_shape_name)
        self._set_status(f"Removed driver '{driver_name}' from '{work_shape_name}'.")


    def _on_work_shape_drop_received(self, work_shape_name: str, source_shape_name: str) -> None:
        """Connect a work shape to a dropped source shape.

        Parameters:
            work_shape_name (str): The work shape receiving the connection.
            source_shape_name (str): The dropped source shape name.

        Returns:
            None
        """
        if self.current_editor is None:
            self._set_status("No system selected.", warning=True)
            return
        try:
            self._stop_active_blendshape_trackers()
            self.current_editor.connect_work_blendshape_weight_to_blendshape_weight(work_shape_name,
                                                                           source_shape_name)
        except Exception as exc:
            self._set_status(f"Error connecting work shape '{work_shape_name}': {exc}", error=True)
            return
        finally:
            self._start_active_blendshape_trackers()
        self._reload_work_shapes_from_editor()
        self._set_work_shape_driver_connected_local(work_shape_name, True)
        self._select_work_shape(work_shape_name)
        self._set_status(f"Connected work shape '{work_shape_name}' to '{source_shape_name}'.")


    def _on_work_shape_break_link_requested(self, work_shape_name: str) -> None:
        """Break the connection between a work shape and its driver.

        Parameters:
            work_shape_name (str): The work shape name.

        Returns:
            None
        """
        if self.current_editor is None:
            self._set_status("No system selected.", warning=True)
            return
        try:
            self._stop_active_blendshape_trackers()
            self.current_editor.disconnect_work_shape_drivers(work_shape_name)
        except Exception as exc:
            self._set_status(f"Error breaking link for '{work_shape_name}': {exc}", error=True)
            return
        finally:
            self._start_active_blendshape_trackers()
        self._reload_work_shapes_from_editor()
        self._set_work_shape_driver_connected_local(work_shape_name, False)
        self._select_work_shape(work_shape_name)
        self._set_status(f"Broke link for work shape '{work_shape_name}'.")


    def _has_copied_work_weight_map_values(self) -> bool:
        """Return whether copied work weight-map values are available.

        Returns:
            bool: ``True`` when copied weight-map values exist.
        """
        if self.current_editor is None:
            return False
        return getattr(self.current_editor, "copied_weight_map_values", None) is not None


    def _on_work_shape_duplicate_requested(self, work_shape_name: str) -> None:
        """Duplicate a work shape and select the copy.

        Parameters:
            work_shape_name (str): The work shape to duplicate.

        Returns:
            None
        """
        if self.current_editor is None:
            self._set_status("No system selected.", warning=True)
            return
        try:
            self._stop_active_blendshape_trackers()
            new_work_shape_name = str(self.current_editor.duplicate_work_shape(work_shape_name))
        except Exception as exc:
            self._set_status(f"Error duplicating work shape '{work_shape_name}': {exc}", error=True)
            return
        finally:
            self._start_active_blendshape_trackers()
        self._reload_work_shapes_from_editor()
        self._select_work_shape(new_work_shape_name)
        self._set_status(f"Duplicated work shape '{work_shape_name}' to '{new_work_shape_name}'.")  


    def _on_work_shape_extract_requested(self, work_shape_name: str) -> None:
        """Extract a shape from a work shape.

        Parameters:
            work_shape_name (str): The work shape to extract from.

        Returns:
            None
        """
        if self.current_editor is None:
            self._set_status("No system selected.", warning=True)
            return
        try:
            self._stop_active_blendshape_trackers()
            new_shape_name = str(self.current_editor.extract_work_shape(work_shape_name))
        except Exception as exc:
            self._set_status(f"Error extracting shape from work shape '{work_shape_name}': {exc}", error=True)
            return
        finally:
            self._start_active_blendshape_trackers()
        self._reload_work_shapes_from_editor()
        if self.current_editor is not None and self.current_editor.work_blendshape is not None:
            weight = self.current_editor.work_blendshape.get_weight_by_name(work_shape_name)
            if weight is not None:
                self._set_work_shape_connected_local(work_shape_name, bool(weight in (self.current_editor.get_work_blendshape_connected_targets_weights() or [])))
        self._select_work_shape(work_shape_name)
        self._set_status(f"Extracted shape '{new_shape_name}' from work shape '{work_shape_name}'.")


    def _on_work_shape_extract_axis_motion_requested(self, work_shape_name: str, axis: str) -> None:
        """Extract the motion along a single axis from a work shape.

        Parameters:
            work_shape_name (str): The work shape to extract motion from.
            axis (str): The combined axis/sign selector ('x', 'y', 'z', 'x+', 'y+',
                'z+', 'x-', 'y-', 'z-').

        Returns:
            None
        """
        if self.current_editor is None:
            self._set_status("No system selected.", warning=True)
            return
        try:
            self._stop_active_blendshape_trackers()
            new_shape_name = str(self.current_editor.extract_axis_motion_from_work_shape(work_shape_name, axis))
        except Exception as exc:
            self._set_status(
                f"Error extracting '{axis}' motion from work shape '{work_shape_name}': {exc}", error=True)
            return
        finally:
            self._start_active_blendshape_trackers()
        self._reload_work_shapes_from_editor()
        self._select_work_shape(work_shape_name)
        self._set_status(
            f"Extracted '{axis}' motion from work shape '{work_shape_name}' to '{new_shape_name}'.")


    def _on_work_shape_propagate_to_active_shapes_requested(self, work_shape_name: str) -> None:
        """Propagate a work shape to a user-selected subset of active shapes.

        Opens a dialog listing the currently active shapes grouped by level and
        sorted by descending weight, each with a checkbox, plus the mask
        blurring options, then calls the editor propagation routine for the
        checked shapes.

        Parameters:
            work_shape_name (str): The work shape to propagate from.

        Returns:
            None
        """
        if self.current_editor is None:
            self._set_status("No system selected.", warning=True)
            return

        active_shapes = dict(self.current_editor.get_active_shapes() or {})
        shapes_by_level: dict = {}
        for shape_name in active_shapes:
            shape = self.current_editor.get_shape(shape_name)
            level = int(getattr(shape, "level", 0) or 0)
            shapes_by_level.setdefault(level, []).append(shape_name)
        if not shapes_by_level:
            self._set_status("No active shapes to propagate.", warning=True)
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("Propagate to Active Shapes")
        layout = QVBoxLayout(dialog)
        form = QFormLayout()
        blur_iterations_spin = QSpinBox(dialog)
        blur_iterations_spin.setRange(0, 999)
        blur_iterations_spin.setValue(10)
        form.addRow("Weights Blur Iteration", blur_iterations_spin)
        blur_strength_spin = QDoubleSpinBox(dialog)
        blur_strength_spin.setRange(0.0, 1.0)
        blur_strength_spin.setSingleStep(0.05)
        blur_strength_spin.setDecimals(2)
        blur_strength_spin.setValue(1.0)
        form.addRow("Weights Blur Strength", blur_strength_spin)
        layout.addLayout(form)

        layout.addWidget(QLabel("Active shapes to propagate:", dialog))
        active_shapes_tree = QTreeWidget(dialog)
        active_shapes_tree.setHeaderHidden(True)
        active_shapes_tree.setRootIsDecorated(True)
        active_shapes_tree.setUniformRowHeights(True)
        active_shapes_tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        checkable_flags = Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable
        level_items: dict = {}
        for level in sorted(shapes_by_level):
            level_names = sorted(
                shapes_by_level[level],
                key=lambda name: active_shapes.get(name, 0.0),
                reverse=True,
            )
            level_item = QTreeWidgetItem([f"Level {level} ({len(level_names)})"])
            level_item.setFlags(checkable_flags)
            level_item.setCheckState(0, Qt.Checked)
            level_font = level_item.font(0)
            level_font.setBold(True)
            level_item.setFont(0, level_font)
            active_shapes_tree.addTopLevelItem(level_item)
            for shape_name in level_names:
                value = float(active_shapes.get(shape_name, 0.0) or 0.0)
                shape_item = QTreeWidgetItem([f"{shape_name}   {value:.3f}"])
                shape_item.setFlags(checkable_flags)
                shape_item.setCheckState(0, Qt.Checked)
                shape_item.setData(0, Qt.UserRole, shape_name)
                level_item.addChild(shape_item)
            level_item.setExpanded(True)
            level_items[level] = level_item
        layout.addWidget(active_shapes_tree)

        syncing: dict = {"active": False}

        def selected_leaf_items() -> list:
            return [
                item
                for item in active_shapes_tree.selectedItems()
                if item.childCount() == 0
            ]

        def refresh_level_state(level_item: QTreeWidgetItem) -> None:
            child_states = [
                level_item.child(i).checkState(0)
                for i in range(level_item.childCount())
            ]
            if not child_states:
                return
            if all(state == Qt.Checked for state in child_states):
                level_item.setCheckState(0, Qt.Checked)
            elif all(state == Qt.Unchecked for state in child_states):
                level_item.setCheckState(0, Qt.Unchecked)
            else:
                level_item.setCheckState(0, Qt.PartiallyChecked)

        def on_active_shape_item_changed(item: QTreeWidgetItem, _column: int) -> None:
            if syncing["active"]:
                return
            syncing["active"] = True
            try:
                state = item.checkState(0)
                if item.childCount() > 0:
                    target_state = Qt.Unchecked if state == Qt.Unchecked else Qt.Checked
                    for i in range(item.childCount()):
                        item.child(i).setCheckState(0, target_state)
                elif item.isSelected():
                    for other_item in selected_leaf_items():
                        other_item.setCheckState(0, state)
                for level_item in level_items.values():
                    refresh_level_state(level_item)
            finally:
                syncing["active"] = False

        active_shapes_tree.itemChanged.connect(on_active_shape_item_changed)

        def checked_shape_names() -> list:
            names = []
            for level_item in level_items.values():
                for i in range(level_item.childCount()):
                    child = level_item.child(i)
                    if child.checkState(0) == Qt.Checked:
                        names.append(str(child.data(0, Qt.UserRole) or ""))
            return [name for name in names if name]

        def accept_if_shapes_selected() -> None:
            if not checked_shape_names():
                self._set_status("Select at least one active shape to propagate.", warning=True)
                return
            dialog.accept()

        dialog_buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel,
            parent=dialog,
        )
        dialog_buttons.button(QDialogButtonBox.Ok).setText("Propagate")
        dialog_buttons.accepted.connect(accept_if_shapes_selected)
        dialog_buttons.rejected.connect(dialog.reject)
        layout.addWidget(dialog_buttons)
        if hasattr(dialog, "exec"):
            result = dialog.exec()
        else:
            result = dialog.exec_()
        if result != QDialog.Accepted:
            self._set_status("Propagation cancelled.")
            return

        selected_active_shapes = checked_shape_names()
        blur_iterations = blur_iterations_spin.value()
        blur_strength = blur_strength_spin.value()
        try:
            self._stop_active_blendshape_trackers()
            self.current_editor.propagate_work_shape_to_active_shapes(
                work_shape_name,
                active_shapes=selected_active_shapes,
                normalize=True,
                blur_iterations=blur_iterations,
                blur_strength=blur_strength,
            )
        except Exception as exc:
            self._set_status(f"Error propagating work shape '{work_shape_name}': {exc}", error=True)
            return
        finally:
            self._start_active_blendshape_trackers()
        self._reload_work_shapes_from_editor()
        self._set_status(
            f"Propagated work shape '{work_shape_name}' to active shapes "
            f"( blur {blur_iterations} x {blur_strength:.2f})."
        )


    def _on_work_shape_connected_mesh_requested(self, work_shape_name: str) -> None:
        """Select the mesh connected to a work shape.

        Parameters:
            work_shape_name (str): The work shape name.

        Returns:
            None
        """
        if self.current_editor is None or self.current_editor.work_blendshape is None:
            self._set_status("No system selected.", warning=True)
            return
        weight = self.current_editor.work_blendshape.get_weight_by_name(work_shape_name)
        if weight is None:
            self._set_status(f"Work shape '{work_shape_name}' not found.", warning=True)
            return
        try:
            edit_mesh = self.current_editor.get_work_shape_edit_mesh(weight)
        except Exception as exc:
            self._set_status(f"Error finding connected mesh for '{work_shape_name}': {exc}", error=True)
            return
        if not edit_mesh or not cmds.objExists(edit_mesh):
            self._set_status(f"No connected mesh found for '{work_shape_name}'.", warning=True)
            return
        cmds.select(edit_mesh, replace=True)
        self._set_status(f"Selected connected mesh '{edit_mesh}' for '{work_shape_name}'.")


    def _on_work_shape_copy_weights_requested(self, work_shape_name: str) -> None:
        """Copy weight-map values from a work shape.

        Parameters:
            work_shape_name (str): The work shape to copy from.

        Returns:
            None
        """
        if self.current_editor is None:
            self._set_status("No system selected.", warning=True)
            return
        try:
            self.current_editor.copy_work_weight_map_values(work_shape_name)
        except Exception as exc:
            self._set_status(f"Error copying weight map values from '{work_shape_name}': {exc}", error=True)
            return
        self._set_status(f"Copied weight map values from '{work_shape_name}'.")


    def _on_work_shape_paste_weights_requested(self, work_shape_name: str) -> None:
        """Paste copied weight-map values onto a work shape.

        Parameters:
            work_shape_name (str): The work shape to paste onto.

        Returns:
            None
        """
        if self.current_editor is None:
            self._set_status("No system selected.", warning=True)
            return
        try:
            self.current_editor.paste_work_weight_map_values(work_shape_name)
        except Exception as exc:
            self._set_status(f"Error pasting weight map values to '{work_shape_name}': {exc}", error=True)
            return
        self._set_status(f"Pasted weight map values to '{work_shape_name}'.")


    def _on_work_shape_paste_inverted_weights_requested(self, work_shape_name: str) -> None:
        """Paste inverted copied weight-map values onto a work shape.

        Parameters:
            work_shape_name (str): The work shape to paste onto.

        Returns:
            None
        """
        if self.current_editor is None:
            self._set_status("No system selected.", warning=True)
            return
        try:
            self.current_editor.paste_inverted_work_weight_map_values(work_shape_name)
        except Exception as exc:
            self._set_status(f"Error pasting inverted weight map values to '{work_shape_name}': {exc}", error=True)
            return
        self._set_status(f"Pasted inverted weight map values to '{work_shape_name}'.")


    def _on_work_shape_add_copied_weights_requested(self, work_shape_name: str) -> None:
        """Add copied weight-map values to a work shape.

        Parameters:
            work_shape_name (str): The work shape to add to.

        Returns:
            None
        """
        if self.current_editor is None:
            self._set_status("No system selected.", warning=True)
            return
        try:
            self.current_editor.add_work_weight_map_values(work_shape_name)
        except Exception as exc:
            self._set_status(f"Error adding copied weight map values to '{work_shape_name}': {exc}", error=True)
            return
        self._set_status(f"Added copied weight map values to '{work_shape_name}'.")


    def _on_work_shape_subtract_copied_weights_requested(self, work_shape_name: str) -> None:
        """Subtract copied weight-map values from a work shape.

        Parameters:
            work_shape_name (str): The work shape to subtract from.

        Returns:
            None
        """
        if self.current_editor is None:
            self._set_status("No system selected.", warning=True)
            return
        try:
            self.current_editor.subtract_work_weight_map_values(work_shape_name)
        except Exception as exc:
            self._set_status(f"Error subtracting copied weight map values from '{work_shape_name}': {exc}", error=True)
            return
        self._set_status(f"Subtracted copied weight map values from '{work_shape_name}'.")


    def _on_work_shapes_normalize_weights_requested(self, work_shape_names: Sequence[str]) -> None:
        """Normalize weight maps across the selected work shapes.

        Parameters:
            work_shape_names (Sequence[str]): The work-shape names to
                normalize.

        Returns:
            None
        """
        if self.current_editor is None:
            self._set_status("No system selected.", warning=True)
            return
        shape_names = [str(name) for name in (work_shape_names or []) if str(name)]
        if not shape_names:
            self._set_status("No work shapes selected.", warning=True)
            return
        if len(shape_names) == 1:
            self._set_status(f"Cannot Normalize Only One Work Shape", warning=True)
            return
        try:
            self.current_editor.normalize_work_weight_map_values(shape_names)
        except Exception as exc:
            self._set_status(f"Error normalizing work-shape weight maps: {exc}", error=True)
            return
        self._set_status(f"Normalized weight maps for {len(shape_names)} work shape(s).")


    def _on_work_shape_apply_weights_requested(self, work_shape_names: Sequence[str]) -> None:
        """Apply the masked weight maps to the given work shapes.

        Parameters:
            work_shape_names (Sequence[str]): The work-shape names to apply the
                masked weight maps to.

        Returns:
            None
        """
        if self.current_editor is None:
            self._set_status("No system selected.", warning=True)
            return
        shape_names = [str(name) for name in (work_shape_names or []) if str(name)]
        if not shape_names:
            self._set_status("No work shapes selected.", warning=True)
            return
        try:
            print(f"Applying masked weight maps for {len(shape_names)} work shape(s)...")
            self.current_editor.apply_masked_weight_maps_to_work_shapes(shape_names)
        except Exception as exc:
            self._set_status(f"Error applying masked weight maps: {exc}", error=True)
            return
        self._set_status(f"Applied masked weight maps for {len(shape_names)} work shape(s).")


    def _on_work_shape_clear_weights_requested(self, work_shape_names: Sequence[str]) -> None:
        """Clear the weight-map values of the given work shapes.

        Parameters:
            work_shape_names (Sequence[str]): The work-shape names to clear.

        Returns:
            None
        """
        if self.current_editor is None:
            self._set_status("No system selected.", warning=True)
            return
        shape_names = [str(name) for name in (work_shape_names or []) if str(name)]
        if not shape_names:
            self._set_status("No work shapes selected.", warning=True)
            return
        try:
            print(f"Clearing weight map values for {len(shape_names)} work shape(s)...")
            self.current_editor.clear_work_weights_map_values(shape_names)
        except Exception as exc:
            self._set_status(f"Error clearing weight map values: {exc}", error=True)
            return
        self._set_status(f"Cleared weight map values for {len(shape_names)} work shape(s).")


    def _begin_inline_workshape_rename(self, item: Optional[QTreeWidgetItem]) -> None:
        """Begin inline renaming of a work shape.

        Parameters:
            item (QTreeWidgetItem): The tree item of the work shape.

        Returns:
            None
        """
        if self.current_editor is None or item is None:
            return
        old_name = str(item.data(0, ShapeItemsModel.NameRole) or "")
        if not old_name:
            return

        if self._workshape_rename_editor is not None:
            self._cancel_inline_workshape_rename()

        class _OptionRect:
            pass

        index = self.work_shapes_view.indexFromItem(item, 0)
        option = _OptionRect()
        option.rect = self.work_shapes_view.visualRect(index)
        _, text_rect = self._work_shapes_delegate._area_rects(option, index)

        editor = InlineWorkshapeRenameEditor(self.work_shapes_view.viewport())
        editor.setText(old_name)
        editor.setGeometry(text_rect.adjusted(0, 2, 0, -2))
        editor.selectAll()
        editor.show()
        editor.setFocus(Qt.MouseFocusReason)

        self._workshape_rename_editor = editor
        self._workshape_rename_old_name = old_name
        editor.submitted.connect(self._commit_inline_workshape_rename)
        editor.canceled.connect(self._cancel_inline_workshape_rename)


    def _cancel_inline_workshape_rename(self) -> None:
        """Cancel the active inline work-shape rename editor.

        Returns:
            None
        """
        editor = self._workshape_rename_editor
        self._workshape_rename_editor = None
        self._workshape_rename_old_name = ""
        if editor is not None:
            editor.deleteLater()


    def _commit_inline_workshape_rename(self) -> None:
        """Commit the active inline work-shape rename editor.

        Returns:
            None
        """
        editor = self._workshape_rename_editor
        old_name = self._workshape_rename_old_name
        self._workshape_rename_editor = None
        self._workshape_rename_old_name = ""
        if editor is None:
            return

        new_name = (editor.text() or "").strip()
        editor.deleteLater()

        if self.current_editor is None or not old_name:
            return
        if not new_name or new_name == old_name:
            return

        try:
            self._stop_active_blendshape_trackers()
            self.current_editor.rename_work_shape(old_name, new_name)
        except Exception as exc:
            self._set_status(f"Error renaming work shape: {exc}", error=True)
            return
        finally:
            self._start_active_blendshape_trackers()

        if self._work_shape_edit_name() == old_name:
            self._set_work_shape_edit_name(new_name)
        self._reload_work_shapes_from_editor()
        self._select_work_shape(new_name)
        self._set_status(f"Renamed work shape '{old_name}' to '{new_name}'.")


    def _capture_linked_drag_state(self) -> None:
        """Capture start values for a linked drag.

        Returns:
            None
        """
        self._linked_primary_start_values = {}
        self._linked_work_start_values = {}
        for shape_name in self._selected_primary_drop_shape_names():
            value = self._shape_model.get_shape_value(shape_name)
            if value is None:
                continue
            self._linked_primary_start_values[shape_name] = value
        for shape_name in self._selected_work_shape_names():
            value = self._work_shape_value(shape_name)
            if value is None:
                continue
            self._linked_work_start_values[shape_name] = float(value)


    def _on_linked_drag_started(self) -> None:
        """Mark the linked drag as active and capture its start state.

        Returns:
            None
        """
        self._linked_drag_active = True
        self._linked_drag_ctrl_pressed = bool(QGuiApplication.keyboardModifiers() & Qt.ControlModifier)
        self._capture_linked_drag_state()


    def _on_linked_drag_selection_context(self, can_propagate: bool) -> None:
        """Record whether a linked drag may propagate.

        Parameters:
            can_propagate (bool): Whether propagation is allowed.

        Returns:
            None
        """
        self._linked_drag_can_propagate = bool(can_propagate)


    def _on_linked_drag_ended(self) -> None:
        """Clear the linked drag state when the drag ends.

        Returns:
            None
        """
        self._linked_drag_active = False
        self._linked_primary_start_values = {}
        self._linked_work_start_values = {}
        self._linked_drag_can_propagate = False
        self._linked_drag_ctrl_pressed = False


    def _on_linked_drag_delta(self, delta_value: float) -> None:
        """Apply a linked-drag delta to primary and work shapes.

        Parameters:
            delta_value (float): The value delta to apply.

        Returns:
            None
        """
        if not self._linked_drag_active:
            return
        if not self._linked_drag_can_propagate:
            return
        if not self._linked_drag_ctrl_pressed:
            return
        for shape_name, start_value in self._linked_primary_start_values.items():
            target_value = max(0.0, min(1.0, start_value + float(delta_value)))
            self._shape_model.set_shape_value_by_name(shape_name, target_value)
        for shape_name, start_value in self._linked_work_start_values.items():
            target_value = max(0.0, min(1.0, start_value + float(delta_value)))
            self._commit_work_shape_value(shape_name, target_value)


    def _on_work_shape_value_committed(self, shape_name: str, value: float) -> None:
        """Report a committed work-shape value.

        Parameters:
            shape_name (str): The work-shape name.
            value (float): The committed value.

        Returns:
            None
        """
        if self._linked_drag_active:
            return
        self._set_status(f"Set work shape '{shape_name}' to {value:.3f}")


    def _on_work_shape_value_changed(self, shape_id: int, shape_name: str, value: float) -> None:
        """Update the local work-shape model value from a tracker change.

        Parameters:
            shape_id (int): The work-shape target id (unused).
            shape_name (str): The work-shape name.
            value (float): The new value.

        Returns:
            None
        """
        del shape_id
        self._set_work_shape_value_local(shape_name, value)


    def _on_work_shape_structure_changed(self, *_args) -> None:
        """Reload work shapes after a structure change.

        Returns:
            None
        """
        print("Work shape structure changed, reloading work shapes from editor...")
        if self.current_editor is not None and self.current_editor.work_blendshape is not None:
            self.current_editor.work_blendshape.invalidate_weights_cache()
        self._reload_work_shapes_from_editor()


    def _on_work_sculpt_target_changed(self, target_id: int, _shape_name: str) -> None:
        """Sync the edit-shape selection with the sculpt target.

        Parameters:
            target_id (int): The active sculpt target id.
            _shape_name (str): The shape name (unused).

        Returns:
            None
        """
        if self.current_editor is None or self.current_editor.work_blendshape is None:
            self._set_work_shape_edit_name(None)
            self._update_work_shape_button_panel()
            return
        if target_id < 0:
            self._set_work_shape_edit_name(None)
            self._update_work_shape_button_panel()
            return
        weight = self.current_editor.work_blendshape.get_weight_by_id(target_id)
        self._set_work_shape_edit_name(str(weight) if weight is not None else None)
        self._update_work_shape_button_panel()


    def _on_work_shapes_mute_toggle_requested(self, shape_name: str, state: bool) -> None:
        """Handle work-shape delegate mute icon clicks with shapes-panel semantics.

        Parameters:
            shape_name (str): The clicked work-shape name.
            state (bool): The requested mute state.

        Returns:
            None
        """
        if self.current_editor is None:
            return

        target_names = target_shape_names(shape_name, self._selected_work_shape_names())

        try:
            if self.work_blendshape_tracker is not None:
                self.work_blendshape_tracker.stop()
            for target_name in target_names:
                self.current_editor.set_work_shape_mute_state(target_name, bool(state))
                self._set_work_shape_muted_local(target_name, bool(state))
            if len(target_names) == 1:
                self._set_status(f"{'Muted' if state else 'Unmuted'} work shape '{target_names[0]}'.")
            else:
                self._set_status(f"{'Muted' if state else 'Unmuted'} {len(target_names)} selected work shape(s).")
        except Exception as exc:
            self._set_status(f"Error toggling work-shape mute state: {exc}", error=True)
        finally:
            if self.work_blendshape_tracker is not None:
                self.work_blendshape_tracker.start()


    def _on_work_blendshape_target_connection_changed(self, _target_id: int, connected: bool) -> None:
        """Update local connection state when a work target connection changes.

        Parameters:
            _target_id (int): The work target id.
            connected (bool): Whether the target is now connected.

        Returns:
            None
        """
        if self.current_editor is None or self.current_editor.work_blendshape is None:
            return
        work_weight = self.current_editor.work_blendshape.get_weight_by_id(_target_id)
        if work_weight is None:
            return
        work_shape_name = str(work_weight)
        self._set_work_shape_connected_local(work_shape_name, bool(connected))
        if connected and self._work_shape_edit_name() == work_shape_name:
            try:
                cmds.sculptTarget(self.current_editor.work_blendshape.name, e=True, t=-1)
            except Exception:
                pass
            self._set_work_shape_edit_name(None)
        self._update_work_shape_button_panel()


    def _on_work_blendshape_driver_connection_changed(self, target_id: int, connected: bool) -> None:
        """Update local driver state when a work driver connection changes.

        Parameters:
            target_id (int): The work target id.
            connected (bool): Whether the driver is now connected.

        Returns:
            None
        """
        if self.current_editor is None or self.current_editor.work_blendshape is None:
            return
        work_weight = self.current_editor.work_blendshape.get_weight_by_id(target_id)
        if work_weight is None:
            return
        self._set_work_shape_driver_connected_local(str(work_weight), bool(connected))
        


    def _on_work_blendshape_deleted(self, blendshape_name: str) -> None:
        """Handle deletion of the work blendshape node.

        Parameters:
            blendshape_name (str): The deleted blendshape node name.

        Returns:
            None
        """
        self.set_current_editor(None)
        self._set_status(f"Work blendshape '{blendshape_name}' deleted.", warning=True)

