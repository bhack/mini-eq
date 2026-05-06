from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")

from gi.repository import Adw, Gio, GLib, Gtk

from .core import (
    DEFAULT_ACTIVE_BANDS,
    PRESET_FILE_SUFFIX,
    PRESET_VERSION,
    clear_default_preset_name,
    clear_output_preset_link,
    delete_preset_file,
    ensure_json_suffix,
    fader_band_count_for_profile,
    get_default_preset_name,
    get_output_preset_link,
    list_preset_names,
    load_mini_eq_preset_file,
    preset_path_for_name,
    sanitize_preset_name,
    set_default_preset_name,
    set_output_preset_link,
    write_mini_eq_preset_file,
)


class MiniEqWindowPresetMixin:
    def output_preset_link_name(self) -> str | None:
        try:
            return get_output_preset_link(self.controller.output_sink)
        except Exception:
            return None

    def default_preset_name(self) -> str | None:
        try:
            return get_default_preset_name()
        except Exception:
            return None

    def output_preset_is_active(self) -> bool:
        linked_preset = self.output_preset_link_name()
        return bool(
            linked_preset
            and self.current_preset_name == linked_preset
            and self.controller.state_signature() == self.saved_preset_signature
        )

    def has_unsaved_curve_changes(self) -> bool:
        if self.current_preset_name is None:
            return self.controller.state_signature() != self.default_preset_signature

        return self.controller.state_signature() != self.saved_preset_signature

    def update_output_preset_state(self) -> None:
        label = getattr(self, "output_preset_state_label", None)
        if label is None:
            return

        switch = getattr(self, "output_preset_switch", None)
        self.output_preset_auto_applied = False

        def sync_output_preset_switch(
            *,
            active: bool,
            sensitive: bool,
            tooltip: str,
            status_text: str = "",
            status_tooltip: str | None = None,
        ) -> None:
            label.set_text(status_text)
            label.set_tooltip_text(status_tooltip or tooltip)

            if switch is None:
                return

            self.updating_output_preset_switch = True
            try:
                switch.set_active(active)
            finally:
                self.updating_output_preset_switch = False
            switch.set_sensitive(sensitive)
            switch.set_tooltip_text(tooltip)

        try:
            linked_preset = get_output_preset_link(self.controller.output_sink)
        except Exception as exc:
            sync_output_preset_switch(
                active=False,
                sensitive=False,
                tooltip="Output preset links are unavailable",
                status_text="Unavailable",
                status_tooltip=str(exc),
            )
            return

        has_output = bool(self.controller.output_sink)
        has_named_preset = self.current_preset_name is not None

        if not linked_preset:
            if not has_output:
                tooltip = "Select an Output"
            elif not has_named_preset:
                tooltip = "Save a Preset First"
            else:
                tooltip = "Use Selected Preset for This Output"
            sync_output_preset_switch(
                active=False,
                sensitive=has_output and has_named_preset,
                tooltip=tooltip,
            )
            return

        self.output_preset_auto_applied = self.output_preset_is_active()
        if self.output_preset_auto_applied:
            sync_output_preset_switch(
                active=True,
                sensitive=has_output,
                tooltip="Clear Output Preset",
            )
            return

        if has_named_preset:
            sync_output_preset_switch(
                active=True,
                sensitive=has_output,
                tooltip="Clear Output Preset",
                status_text="Different",
                status_tooltip=f"This output currently uses {linked_preset}",
            )
            return

        sync_output_preset_switch(
            active=True,
            sensitive=has_output,
            tooltip="Clear Output Preset",
            status_text="Linked",
            status_tooltip=f"This output uses {linked_preset}",
        )

    def refresh_preset_actions(self) -> None:
        has_named_preset = self.current_preset_name is not None
        has_preset_changes = has_named_preset and self.controller.state_signature() != self.saved_preset_signature
        self.preset_delete_button.set_sensitive(has_named_preset)
        self.preset_export_button.set_sensitive(True)
        self.preset_import_button.set_sensitive(True)
        self.preset_revert_button.set_sensitive(has_preset_changes)
        self.preset_save_button.set_sensitive(True)
        self.preset_save_as_button.set_sensitive(True)
        self.update_output_preset_state()
        self.update_default_preset_state()

    def update_default_preset_state(self) -> None:
        label = getattr(self, "default_preset_state_label", None)
        set_button = getattr(self, "default_preset_set_button", None)
        clear_button = getattr(self, "default_preset_clear_button", None)

        try:
            default_preset = get_default_preset_name()
        except Exception as exc:
            if label is not None:
                label.set_text("Unavailable")
                label.set_tooltip_text(str(exc))
            if set_button is not None:
                set_button.set_sensitive(False)
            if clear_button is not None:
                clear_button.set_sensitive(False)
            return

        has_named_preset = self.current_preset_name is not None
        if set_button is not None:
            set_button.set_sensitive(has_named_preset)
        if clear_button is not None:
            clear_button.set_sensitive(default_preset is not None)

        if label is None:
            return

        if default_preset is None:
            label.set_text("None")
            label.set_tooltip_text("No default preset")
            return

        if default_preset in self.preset_names:
            label.set_text(default_preset)
            label.set_tooltip_text("Used when the selected output has no preset")
            return

        label.set_text("Missing")
        label.set_tooltip_text(f"Default preset {default_preset} is unavailable")

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
        self.output_preset_curve_auto_loaded = False
        self.refresh_preset_list()
        self.sync_ui_from_state()
        self.set_status(f"Saved Preset: {preset_name}")
        self.notify_control_presets_changed()
        self.notify_control_state_changed()

    def load_library_preset(
        self,
        name: str,
        *,
        auto: bool = False,
        output_preset_auto: bool = True,
        status_message: str | None = None,
    ) -> None:
        preset_name = sanitize_preset_name(name)
        payload = load_mini_eq_preset_file(preset_path_for_name(preset_name))
        self.controller.apply_preset_payload(payload)
        self.selected_band_index = None
        self.set_visible_band_count(fader_band_count_for_profile(self.controller.bands))
        self.current_preset_name = preset_name
        self.saved_preset_signature = self.controller.state_signature()
        self.refresh_preset_list()
        self.sync_ui_from_state()
        self.output_preset_curve_auto_loaded = bool(auto)
        self.output_preset_auto_applied = (auto and output_preset_auto) or self.output_preset_is_active()
        if status_message is not None:
            self.set_status(status_message)
        elif auto:
            self.set_status(f"Applied Output Preset: {preset_name}")
        else:
            self.set_status(f"Loaded Preset: {preset_name}")
        self.notify_control_state_changed()

    def apply_output_preset_for_current_output(
        self,
        *,
        reset_auto_preset_without_link: bool = False,
        announce_no_output_preset: bool = False,
    ) -> bool:
        try:
            linked_preset = get_output_preset_link(self.controller.output_sink)
        except Exception as exc:
            self.update_preset_state()
            self.set_status(str(exc))
            self.notify_control_state_changed()
            return True

        if not linked_preset:
            if self.has_unsaved_curve_changes():
                self.output_preset_auto_applied = False
                self.output_preset_curve_auto_loaded = False
                self.update_preset_state()
                if announce_no_output_preset:
                    self.set_status("Kept Unsaved Changes")
                self.notify_control_state_changed()
                return announce_no_output_preset

            default_preset = get_default_preset_name()
            should_apply_default_preset = default_preset is not None and (
                reset_auto_preset_without_link or self.current_preset_name is None
            )
            # TODO(#8): Prefer a port-specific fallback profile here when route matching is available.
            if should_apply_default_preset:
                try:
                    self.load_library_preset(
                        default_preset,
                        auto=True,
                        output_preset_auto=False,
                        status_message="Applied Default Preset",
                    )
                except Exception:
                    self.output_preset_auto_applied = False
                    self.output_preset_curve_auto_loaded = False
                    self.update_preset_state()
                    self.notify_control_state_changed()
                else:
                    return True

            if reset_auto_preset_without_link:
                self.controller.reset_state()
                self.current_preset_name = None
                self.selected_band_index = None
                self.set_visible_band_count(DEFAULT_ACTIVE_BANDS)
                self.output_preset_curve_auto_loaded = False
                self.output_preset_auto_applied = False
                self.sync_ui_from_state()
                self.set_status("Reset to Neutral")
                self.notify_control_state_changed()
                return True

            self.output_preset_auto_applied = False
            self.output_preset_curve_auto_loaded = False
            self.update_preset_state()
            if announce_no_output_preset:
                self.set_status("Kept Current Curve")
            self.notify_control_state_changed()
            return announce_no_output_preset

        if self.has_unsaved_curve_changes():
            self.output_preset_auto_applied = False
            self.output_preset_curve_auto_loaded = False
            self.update_preset_state()
            self.set_status("Kept Unsaved Changes")
            self.notify_control_state_changed()
            return True

        try:
            self.load_library_preset(linked_preset, auto=True)
        except Exception:
            self.output_preset_auto_applied = False
            self.output_preset_curve_auto_loaded = False
            self.update_preset_state()
            self.set_status(f"Output Preset Unavailable: {linked_preset}")
            self.notify_control_state_changed()
            return True

        self.output_preset_auto_applied = True
        self.update_output_preset_state()
        self.notify_control_state_changed()
        return True

    def prompt_for_preset_name(
        self,
        title: str,
        accept_label: str,
        initial_text: str,
        callback: Callable[[str], None],
    ) -> None:
        dialog = Adw.Dialog()
        dialog.set_title(title)
        dialog.set_content_width(420)
        dialog.set_follows_content_size(True)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content.set_margin_top(18)
        content.set_margin_bottom(18)
        content.set_margin_start(18)
        content.set_margin_end(18)

        label = Gtk.Label(label="Preset name", xalign=0.0)
        label.add_css_class("heading")
        content.append(label)

        entry = Gtk.Entry()
        entry.set_hexpand(True)
        entry.set_text(initial_text)
        content.append(entry)

        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        actions.set_halign(Gtk.Align.END)

        cancel_button = Gtk.Button(label="Cancel")
        cancel_button.set_can_shrink(True)
        cancel_button.connect("clicked", lambda _button: dialog.close())
        actions.append(cancel_button)

        accept_button = Gtk.Button(label=accept_label)
        accept_button.set_can_shrink(True)
        accept_button.add_css_class("suggested-action")
        accept_button.connect("clicked", self.on_preset_name_dialog_accept, dialog, entry, callback)
        actions.append(accept_button)

        entry.connect("activate", self.on_preset_name_dialog_accept, dialog, entry, callback)
        content.append(actions)

        dialog.set_child(content)
        dialog.set_default_widget(accept_button)
        dialog.set_focus(entry)
        dialog.present(self)

    def on_preset_name_dialog_accept(
        self,
        _widget: Gtk.Widget,
        dialog: Adw.Dialog,
        entry: Gtk.Entry,
        callback: Callable[[str], None],
    ) -> None:
        preset_name = sanitize_preset_name(entry.get_text())
        if not preset_name:
            self.set_status("Preset Name Is Empty")
            entry.grab_focus()
            return

        try:
            callback(preset_name)
        except Exception as exc:
            self.set_status(str(exc))
            entry.grab_focus()
            return

        dialog.close()

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

    def on_use_preset_for_output_clicked(self, _button: Gtk.Widget) -> None:
        if self.current_preset_name is None:
            self.set_status("No Preset Selected")
            return

        try:
            preset_name = set_output_preset_link(self.controller.output_sink, self.current_preset_name)
            self.output_preset_auto_applied = self.output_preset_is_active()
            self.output_preset_curve_auto_loaded = False
            self.update_preset_state()
            self.set_status(f"Linked Output Preset: {preset_name}")
            self.notify_control_state_changed()
        except Exception as exc:
            self.set_status(str(exc))

    def on_use_preset_as_default_clicked(self, _button: Gtk.Widget) -> None:
        if self.current_preset_name is None:
            self.set_status("No Preset Selected")
            return

        try:
            preset_name = set_default_preset_name(self.current_preset_name)
            self.output_preset_curve_auto_loaded = False
            self.update_preset_state()
            self.set_status(f"Default Preset Set: {preset_name}")
            self.notify_control_state_changed()
        except Exception as exc:
            self.set_status(str(exc))
            self.notify_control_state_changed()

    def on_clear_default_preset_clicked(self, _button: Gtk.Widget) -> None:
        try:
            removed = clear_default_preset_name()
            self.output_preset_curve_auto_loaded = False
            self.update_preset_state()
            if removed:
                self.set_status(f"Cleared Default Preset: {removed}")
            else:
                self.set_status("No Default Preset")
            self.notify_control_state_changed()
        except Exception as exc:
            self.set_status(str(exc))
            self.notify_control_state_changed()

    def on_clear_output_preset_link_clicked(self, _button: Gtk.Widget) -> None:
        try:
            removed = clear_output_preset_link(self.controller.output_sink)
            self.output_preset_auto_applied = False
            self.output_preset_curve_auto_loaded = False
            self.update_preset_state()
            if removed:
                self.set_status(f"Cleared Output Preset: {removed}")
            else:
                self.set_status("No Output Preset")
            self.notify_control_state_changed()
        except Exception as exc:
            self.set_status(str(exc))

    def on_output_preset_switch_changed(self, switch: Gtk.Switch, _param: object | None = None) -> None:
        if self.updating_output_preset_switch:
            return

        if switch.get_active():
            self.on_use_preset_for_output_clicked(switch)
        else:
            self.on_clear_output_preset_link_clicked(switch)

        self.update_preset_state()

    def on_preset_delete_clicked(self, button: Gtk.Button) -> None:
        if self.current_preset_name is None:
            self.set_status("No Preset Selected")
            return

        preset_name = self.current_preset_name
        dialog = Adw.AlertDialog()
        dialog.set_heading("Delete preset?")
        dialog.set_body(f"{preset_name} will be removed from your preset library.")
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("delete", "Delete")
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")
        dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.choose(self, None, lambda dialog, result: self.on_preset_delete_dialog_done(dialog, result, preset_name))

    def on_preset_delete_dialog_done(
        self,
        dialog: Adw.AlertDialog,
        result: Gio.AsyncResult,
        preset_name: str,
    ) -> None:
        try:
            response = dialog.choose_finish(result)
        except GLib.Error:
            return

        if response != "delete":
            return

        try:
            delete_preset_file(preset_name)
            self.current_preset_name = None
            self.saved_preset_signature = self.controller.state_signature()
            self.refresh_preset_list()
            self.sync_ui_from_state()
            self.set_status(f"Deleted Preset: {preset_name}")
            self.notify_control_presets_changed()
            self.notify_control_state_changed()
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
            self.selected_band_index = None
            self.set_visible_band_count(fader_band_count_for_profile(self.controller.bands))
            self.current_preset_name = preset_name
            self.saved_preset_signature = self.controller.state_signature()
            self.refresh_preset_list()
            self.sync_ui_from_state()
            self.set_status(f"Imported Preset: {preset_name}")
            self.notify_control_presets_changed()
            self.notify_control_state_changed()
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
