from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")

from gi.repository import Gio, GLib, Gtk

from .core import (
    PRESET_FILE_SUFFIX,
    PRESET_VERSION,
    ensure_json_suffix,
    fader_band_count_for_profile,
    list_preset_names,
    load_mini_eq_preset_file,
    preset_path_for_name,
    sanitize_preset_name,
    write_mini_eq_preset_file,
)


class MiniEqWindowPresetMixin:
    def refresh_preset_actions(self) -> None:
        has_named_preset = self.current_preset_name is not None
        has_preset_changes = has_named_preset and self.controller.state_signature() != self.saved_preset_signature
        self.preset_delete_button.set_sensitive(has_named_preset)
        self.preset_export_button.set_sensitive(True)
        self.preset_import_button.set_sensitive(True)
        self.preset_revert_button.set_sensitive(has_preset_changes)
        self.preset_save_button.set_sensitive(True)
        self.preset_save_as_button.set_sensitive(True)

    def refresh_preset_list(self) -> None:
        self.preset_names = list_preset_names()
        self.preset_model.splice(0, self.preset_model.get_n_items(), self.preset_names)

        selected_index = Gtk.INVALID_LIST_POSITION
        if self.current_preset_name in self.preset_names:
            selected_index = self.preset_names.index(self.current_preset_name)

        self.updating_preset_combo = True
        try:
            self.preset_combo.set_selected(selected_index)
        finally:
            self.updating_preset_combo = False

        self.update_preset_state()

    def update_preset_state(self) -> None:
        current_signature = self.controller.state_signature()
        current_name = self.current_preset_name or "Current State"

        self.preset_state_label.remove_css_class("preset-state-saved")
        self.preset_state_label.remove_css_class("preset-state-modified")
        self.preset_state_label.remove_css_class("preset-state-unsaved")

        if self.current_preset_name is None:
            self.preset_state_label.set_text("Unsaved")
            self.preset_state_label.add_css_class("preset-state-unsaved")
            self.preset_state_label.set_tooltip_text("Current curve has not been saved as a preset")
        elif current_signature == self.saved_preset_signature:
            self.preset_state_label.set_text("Saved")
            self.preset_state_label.add_css_class("preset-state-saved")
            self.preset_state_label.set_tooltip_text(f"{current_name} matches the saved preset")
        else:
            self.preset_state_label.set_text("Modified")
            self.preset_state_label.add_css_class("preset-state-modified")
            self.preset_state_label.set_tooltip_text(f"{current_name} has unsaved curve changes")

        self.refresh_preset_actions()

    def save_current_state_to_preset(self, name: str) -> None:
        preset_name = sanitize_preset_name(name)
        if not preset_name:
            raise ValueError("Preset name is empty")

        payload = self.controller.build_preset_payload(preset_name)
        write_mini_eq_preset_file(preset_path_for_name(preset_name), payload)
        self.current_preset_name = preset_name
        self.saved_preset_signature = self.controller.state_signature()
        self.refresh_preset_list()
        self.sync_ui_from_state()
        self.set_status(f"Saved Preset: {preset_name}")

    def load_library_preset(self, name: str) -> None:
        preset_name = sanitize_preset_name(name)
        payload = load_mini_eq_preset_file(preset_path_for_name(preset_name))
        self.controller.apply_preset_payload(payload)
        self.selected_band_index = 0
        self.set_visible_band_count(fader_band_count_for_profile(self.controller.bands))
        self.current_preset_name = preset_name
        self.saved_preset_signature = self.controller.state_signature()
        self.refresh_preset_list()
        self.sync_ui_from_state()
        self.set_status(f"Loaded Preset: {preset_name}")

    def prompt_for_preset_name(
        self,
        title: str,
        accept_label: str,
        initial_text: str,
        callback: Callable[[str], None],
    ) -> None:
        dialog = Gtk.Dialog(title=title, transient_for=self, modal=True)
        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
        dialog.add_button(accept_label, Gtk.ResponseType.ACCEPT)
        dialog.set_default_response(Gtk.ResponseType.ACCEPT)

        accept_button = dialog.get_widget_for_response(Gtk.ResponseType.ACCEPT)
        if accept_button is not None:
            accept_button.add_css_class("suggested-action")

        content = dialog.get_content_area()
        content.set_spacing(8)
        content.set_margin_top(12)
        content.set_margin_bottom(12)
        content.set_margin_start(12)
        content.set_margin_end(12)

        label = Gtk.Label(label="Preset name", xalign=0.0)
        content.append(label)

        entry = Gtk.Entry()
        entry.set_hexpand(True)
        entry.set_text(initial_text)
        entry.connect("activate", lambda _entry: dialog.response(Gtk.ResponseType.ACCEPT))
        content.append(entry)

        dialog.connect("response", self.on_preset_name_dialog_response, entry, callback)
        dialog.present()

    def on_preset_name_dialog_response(
        self,
        dialog: Gtk.Dialog,
        response_id: Gtk.ResponseType,
        entry: Gtk.Entry,
        callback: Callable[[str], None],
    ) -> None:
        if response_id == Gtk.ResponseType.ACCEPT:
            preset_name = sanitize_preset_name(entry.get_text())
            if not preset_name:
                self.set_status("Preset Name Is Empty")
            else:
                try:
                    callback(preset_name)
                except Exception as exc:
                    self.set_status(str(exc))

        dialog.destroy()

    def on_preset_selected(self, combo: Gtk.DropDown, _param: object) -> None:
        if self.updating_preset_combo:
            return

        selected = combo.get_selected()
        if selected == Gtk.INVALID_LIST_POSITION or selected >= len(self.preset_names):
            return

        try:
            self.load_library_preset(self.preset_names[selected])
        except Exception as exc:
            self.set_status(str(exc))

    def on_preset_save_clicked(self, button: Gtk.Button) -> None:
        if self.current_preset_name is not None:
            try:
                self.save_current_state_to_preset(self.current_preset_name)
            except Exception as exc:
                self.set_status(str(exc))
            return

        self.on_preset_save_as_clicked(button)

    def on_preset_save_as_clicked(self, button: Gtk.Button) -> None:
        initial_name = self.current_preset_name or ""
        self.prompt_for_preset_name("Save Preset As", "Save", initial_name, self.save_current_state_to_preset)

    def on_preset_revert_clicked(self, button: Gtk.Button) -> None:
        if self.current_preset_name is None:
            self.set_status("No Preset Selected")
            return

        preset_name = self.current_preset_name
        try:
            self.load_library_preset(preset_name)
            self.set_status(f"Reverted to Preset: {preset_name}")
        except Exception as exc:
            self.set_status(str(exc))

    def on_preset_delete_clicked(self, button: Gtk.Button) -> None:
        if self.current_preset_name is None:
            self.set_status("No Preset Selected")
            return

        try:
            preset_path = preset_path_for_name(self.current_preset_name)
            if preset_path.exists():
                preset_path.unlink()
            deleted_name = self.current_preset_name
            self.current_preset_name = None
            self.saved_preset_signature = self.controller.state_signature()
            self.refresh_preset_list()
            self.sync_ui_from_state()
            self.set_status(f"Deleted Preset: {deleted_name}")
        except Exception as exc:
            self.set_status(str(exc))

    def on_preset_import_clicked(self, button: Gtk.Button) -> None:
        dialog = Gtk.FileDialog(title="Import Mini EQ Preset")
        filters = Gio.ListStore.new(Gtk.FileFilter)
        file_filter = Gtk.FileFilter()
        file_filter.set_name("Mini EQ Presets")
        file_filter.add_pattern("*.json")
        filters.append(file_filter)
        dialog.set_filters(filters)
        dialog.set_default_filter(file_filter)
        dialog.open(self, None, self.on_preset_import_done)

    def on_preset_import_done(self, dialog: Gtk.FileDialog, result: Gio.AsyncResult) -> None:
        try:
            file = dialog.open_finish(result)
        except GLib.Error:
            return

        path = file.get_path()
        if path is None:
            self.set_status("Could Not Resolve Preset Path")
            return

        try:
            payload = load_mini_eq_preset_file(path)
            preset_name = sanitize_preset_name(str(payload.get("name", ""))) or sanitize_preset_name(Path(path).stem)
            if not preset_name:
                raise ValueError("Preset file does not contain a usable name")

            stored_payload = dict(payload)
            stored_payload["version"] = PRESET_VERSION
            stored_payload["name"] = preset_name
            write_mini_eq_preset_file(preset_path_for_name(preset_name), stored_payload)
            self.controller.apply_preset_payload(stored_payload)
            self.selected_band_index = 0
            self.set_visible_band_count(fader_band_count_for_profile(self.controller.bands))
            self.current_preset_name = preset_name
            self.saved_preset_signature = self.controller.state_signature()
            self.refresh_preset_list()
            self.sync_ui_from_state()
            self.set_status(f"Imported Preset: {preset_name}")
        except Exception as exc:
            self.set_status(str(exc))

    def on_preset_export_clicked(self, button: Gtk.Button) -> None:
        dialog = Gtk.FileDialog(title="Export Mini EQ Preset")
        filters = Gio.ListStore.new(Gtk.FileFilter)
        file_filter = Gtk.FileFilter()
        file_filter.set_name("Mini EQ Presets")
        file_filter.add_pattern("*.json")
        filters.append(file_filter)
        dialog.set_filters(filters)
        dialog.set_default_filter(file_filter)
        dialog.set_initial_name(f"{sanitize_preset_name(self.current_preset_name or 'mini-eq')}{PRESET_FILE_SUFFIX}")
        dialog.save(self, None, self.on_preset_export_done)

    def on_preset_export_done(self, dialog: Gtk.FileDialog, result: Gio.AsyncResult) -> None:
        try:
            file = dialog.save_finish(result)
        except GLib.Error:
            return

        path = file.get_path()
        if path is None:
            self.set_status("Could Not Resolve Export Path")
            return

        try:
            export_path = ensure_json_suffix(Path(path))
            payload = self.controller.build_preset_payload(self.current_preset_name or export_path.stem)
            write_mini_eq_preset_file(export_path, payload)
            self.set_status("Exported Preset")
        except Exception as exc:
            self.set_status(str(exc))
