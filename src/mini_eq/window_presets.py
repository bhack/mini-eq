from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")

from gi.repository import Adw, Gio, GLib, Gtk, Pango

from .core import (
    DEFAULT_ACTIVE_BANDS,
    PRESET_FILE_SUFFIX,
    PRESET_VERSION,
    clear_output_preset_fallback_name,
    clear_output_preset_link,
    delete_preset_file,
    ensure_json_suffix,
    fader_band_count_for_profile,
    get_output_preset_fallback_name,
    get_output_preset_link,
    list_preset_names,
    load_mini_eq_preset_file,
    preset_path_for_name,
    preset_payload_state_signature,
    sanitize_preset_name,
    set_output_preset_fallback_name,
    set_output_preset_link,
    write_mini_eq_preset_file,
)
from .window_utils import requested_switch_state, set_accessible_label, set_switch_confirmed_state

APO_IMPORT_LABEL_PREFIX = "Imported APO: "
DELETED_PRESET_LABEL_PREFIX = "Unsaved copy: "


def imported_apo_curve_label_for_name(name: str) -> str:
    preset_name = sanitize_preset_name(name)
    if preset_name:
        return f"{APO_IMPORT_LABEL_PREFIX}{preset_name}"
    return "Imported APO"


def imported_apo_curve_label(path: str) -> str:
    return imported_apo_curve_label_for_name(Path(path).stem)


@dataclass(frozen=True)
class PresetPanelUiState:
    preset_state_text: str
    preset_state_class: str
    preset_state_tooltip: str
    current_curve_text: str
    current_curve_tooltip: str
    save_label: str
    save_tooltip: str
    primary_action: str
    save_as_visible: bool
    revert_visible: bool
    revert_label: str
    revert_tooltip: str
    reset_visible: bool
    reset_tooltip: str
    default_set_visible: bool
    default_clear_visible: bool
    default_separator_visible: bool
    file_separator_visible: bool
    library_separator_visible: bool
    export_label: str
    delete_visible: bool


class MiniEqWindowPresetMixin:
    def output_preset_target(self):
        try:
            return self.controller.output_preset_target()
        except Exception:
            return None

    def output_preset_keys(self, target=None) -> tuple[str, ...]:
        if target is not None:
            keys = tuple(getattr(target, "keys", ()))
            if keys:
                return keys

        output_sink = getattr(self.controller, "output_sink", None)
        try:
            keys = tuple(self.controller.output_preset_keys())
        except Exception:
            keys = ()

        if keys:
            return keys
        return (output_sink,) if output_sink else ()

    def output_preset_link_key(self, target=None) -> str:
        if target is not None:
            link_key = str(getattr(target, "link_key", "") or "").strip()
            if link_key:
                return link_key

        try:
            return self.controller.output_preset_link_key()
        except Exception:
            return getattr(self.controller, "output_sink", "") or ""

    def output_preset_has_route(self, target=None) -> bool:
        return bool(getattr(target, "has_route_key", False))

    def output_preset_scope_text(self, target=None) -> tuple[str, str, str]:
        if self.output_preset_has_route(target):
            return "port", "port", "Port"
        return "EQ output", "output", "EQ Output"

    def update_output_scope_state(self, target=None) -> None:
        label = getattr(self, "output_scope_state_label", None)
        scope_label = getattr(self, "output_preset_scope_label", None)

        if scope_label is not None:
            scope_label.set_text("Auto Preset")

        if label is None:
            return

        output_sink = getattr(self.controller, "output_sink", None)
        route = getattr(target, "route", None)
        route_name = None
        if route is not None:
            route_name = getattr(route, "description", None) or getattr(route, "name", None)

        if self.output_preset_has_route(target):
            route_key = getattr(route, "output_preset_key", None)
            route_id = getattr(route, "name", None)
            route_text = str(route_name or route_id or "current output port")
            label.set_text(route_text)
            tooltip_parts = [f"Auto presets use {route_text}."]
            if route_id and route_name and route_id != route_name:
                tooltip_parts.append(f"Route: {route_id}")
            if route_key:
                tooltip_parts.append("The preset link is tied to this detected port.")
            label.set_tooltip_text("\n".join(tooltip_parts))
            return

        if output_sink:
            label.set_text("Output-wide")
            label.set_tooltip_text("No reliable port route was reported; auto preset links use the selected EQ output.")
            return

        label.set_text("No output")
        label.set_tooltip_text("Select an EQ output before linking an auto preset.")

    def output_preset_link_name(self) -> str | None:
        try:
            target = self.output_preset_target()
            return get_output_preset_link(self.output_preset_keys(target))
        except Exception:
            return None

    def fallback_preset_name(self) -> str | None:
        try:
            return get_output_preset_fallback_name()
        except Exception:
            return None

    def set_curve_revert_baseline(self, label: str) -> None:
        self.curve_revert_baseline_label = label
        self.curve_revert_baseline_signature = self.controller.state_signature()
        self.curve_revert_baseline_payload = self.controller.build_preset_payload(label)

    def relabel_curve_revert_baseline(self, label: str) -> None:
        self.curve_revert_baseline_label = label

    def set_curve_revert_baseline_payload(
        self,
        label: str,
        payload: dict[str, object],
        signature: str,
    ) -> None:
        self.curve_revert_baseline_label = label
        self.curve_revert_baseline_signature = signature
        self.curve_revert_baseline_payload = dict(payload)
        self.curve_revert_baseline_payload["name"] = label

    def clear_curve_revert_baseline(self) -> None:
        self.curve_revert_baseline_label = None
        self.curve_revert_baseline_signature = None
        self.curve_revert_baseline_payload = None

    def curve_revert_label(self) -> str | None:
        if self.current_preset_name is not None:
            return self.current_preset_name

        return getattr(self, "curve_revert_baseline_label", None)

    def curve_revert_signature(self) -> str | None:
        if self.current_preset_name is not None:
            return self.saved_preset_signature

        return getattr(self, "curve_revert_baseline_signature", None)

    def has_curve_revert_changes(self) -> bool:
        revert_signature = self.curve_revert_signature()
        return revert_signature is not None and self.controller.state_signature() != revert_signature

    def curve_revert_target_is_neutral(self) -> bool:
        return self.current_preset_name is None and self.curve_revert_signature() == self.default_preset_signature

    def curve_revert_target_is_library_preset(self) -> bool:
        label = self.curve_revert_label()
        return bool(label and self.preset_name_exists(label))

    def compact_curve_source_label(self, label: str) -> str:
        if label.startswith(APO_IMPORT_LABEL_PREFIX):
            return "Imported curve"
        if label.startswith(DELETED_PRESET_LABEL_PREFIX):
            return "Deleted preset copy"
        return label

    def curve_source_tooltip(self, label: str) -> str:
        if label.startswith(APO_IMPORT_LABEL_PREFIX):
            source_name = label[len(APO_IMPORT_LABEL_PREFIX) :]
            return f"Imported from {source_name}."
        if label.startswith(DELETED_PRESET_LABEL_PREFIX):
            source_name = label[len(DELETED_PRESET_LABEL_PREFIX) :]
            return f"Deleted preset: {source_name}. Curve is kept."
        return label

    def current_curve_source_label(self) -> str | None:
        if self.current_preset_name is not None:
            return None

        label = self.curve_revert_label()
        signature = self.curve_revert_signature()
        if not label or signature is None or signature == self.default_preset_signature:
            return None
        return label

    def current_curve_running_text(
        self,
        *,
        current_signature: str | None = None,
        revert_signature: str | None = None,
    ) -> tuple[str, str]:
        current_signature = current_signature or self.controller.state_signature()
        if revert_signature is None:
            revert_signature = self.curve_revert_signature()

        if self.current_preset_name is not None:
            if current_signature == self.saved_preset_signature:
                return (self.current_preset_name, f"Saved preset: {self.current_preset_name}.")
            return (self.current_preset_name, f"Unsaved edits from {self.current_preset_name}.")

        label = self.curve_revert_label()
        if current_signature == self.default_preset_signature:
            if (
                self.has_neutral_reapply_target(
                    current_signature=current_signature,
                    revert_signature=revert_signature,
                )
                and label
            ):
                compact_label = self.compact_curve_source_label(label)
                if self.preset_name_exists(label):
                    return (
                        "Neutral",
                        f"Neutral. Load {compact_label} to restore.",
                    )
                return (
                    "Neutral",
                    f"Neutral. Reapply restores {compact_label}.",
                )
            return ("Neutral", "Neutral curve.")

        if label and revert_signature is not None and revert_signature != self.default_preset_signature:
            compact_label = self.compact_curve_source_label(label)
            if current_signature == revert_signature:
                return (compact_label, self.curve_source_tooltip(label))
            return (compact_label, f"Unsaved edits from {compact_label}.")

        return ("Unsaved curve", "Not saved as a preset.")

    def suggested_save_as_name(self) -> str:
        if self.current_preset_name is not None:
            return self.current_preset_name

        if self.controller.state_signature() == self.default_preset_signature:
            return ""

        label = self.current_curve_source_label()
        if label and label.startswith(APO_IMPORT_LABEL_PREFIX):
            return sanitize_preset_name(label[len(APO_IMPORT_LABEL_PREFIX) :])
        if label and label.startswith(DELETED_PRESET_LABEL_PREFIX):
            return sanitize_preset_name(label[len(DELETED_PRESET_LABEL_PREFIX) :])
        if label == "Imported APO":
            return label
        return ""

    def preset_name_exists(self, name: str) -> bool:
        return preset_path_for_name(name).exists()

    def confirm_preset_replacement(
        self,
        preset_name: str,
        body: str,
        replace_callback: Callable[[], None],
    ) -> None:
        dialog = Adw.AlertDialog()
        dialog.set_heading("Replace preset?")
        dialog.set_body(body)
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("replace", "Replace")
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")
        dialog.set_response_appearance("replace", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.choose(
            self,
            None,
            lambda dialog, result: self.on_preset_replace_dialog_done(dialog, result, replace_callback),
        )

    def on_preset_replace_dialog_done(
        self,
        dialog: Adw.AlertDialog,
        result: Gio.AsyncResult,
        replace_callback: Callable[[], None],
    ) -> None:
        try:
            response = dialog.choose_finish(result)
        except GLib.Error:
            return

        if response != "replace":
            return

        try:
            replace_callback()
        except Exception as exc:
            self.set_status(str(exc))

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

    def has_neutral_curve_changes(self) -> bool:
        return self.controller.state_signature() != self.default_preset_signature

    def has_neutral_reapply_target(
        self,
        *,
        current_signature: str | None = None,
        revert_signature: str | None = None,
    ) -> bool:
        current_signature = current_signature or self.controller.state_signature()
        if revert_signature is None:
            revert_signature = self.curve_revert_signature()
        return bool(
            self.current_preset_name is None
            and current_signature == self.default_preset_signature
            and revert_signature is not None
            and revert_signature != self.default_preset_signature
        )

    def preset_panel_ui_state(self) -> PresetPanelUiState:
        current_signature = self.controller.state_signature()
        has_named_preset = self.current_preset_name is not None
        clean_named_preset = has_named_preset and current_signature == self.saved_preset_signature
        neutral = current_signature == self.default_preset_signature
        revert_signature = self.curve_revert_signature()
        revert_label = self.curve_revert_label() or "curve baseline"
        revert_display_label = self.compact_curve_source_label(revert_label)
        has_revert_target = revert_signature is not None and not self.curve_revert_target_is_neutral()
        revert_target_is_library_preset = self.curve_revert_target_is_library_preset()
        revert_visible = (
            has_revert_target and current_signature != revert_signature and not revert_target_is_library_preset
        )
        neutral_reapply_target = self.has_neutral_reapply_target(
            current_signature=current_signature,
            revert_signature=revert_signature,
        )
        reset_visible = not neutral
        default_preset = self.fallback_preset_name()
        default_set_visible = clean_named_preset
        default_clear_visible = default_preset is not None
        curve_group_visible = has_named_preset or revert_visible or reset_visible
        default_group_visible = default_set_visible or default_clear_visible
        export_label = "Export Preset…" if has_named_preset else "Export Current Curve…"
        current_curve_text, current_curve_tooltip = self.current_curve_running_text(
            current_signature=current_signature,
            revert_signature=revert_signature,
        )

        if has_named_preset and current_signature == self.saved_preset_signature:
            preset_state_text = "Preset"
            preset_state_class = "preset-state-saved"
            preset_state_tooltip = f"Running curve matches saved preset {self.current_preset_name}"
        elif has_named_preset:
            preset_state_text = "Modified"
            preset_state_class = "preset-state-modified"
            preset_state_tooltip = f"Running curve is modified from {self.current_preset_name}"
        elif neutral:
            preset_state_text = "Neutral"
            preset_state_class = "preset-state-neutral"
            preset_state_tooltip = "Current curve is neutral"
        elif revert_signature is not None and current_signature == revert_signature:
            preset_state_text = "Unsaved"
            preset_state_class = "preset-state-unsaved"
            preset_state_tooltip = "Current curve has not been saved as a preset"
        else:
            preset_state_text = "Modified"
            preset_state_class = "preset-state-modified"
            preset_state_tooltip = "Current curve has unsaved changes"

        if revert_visible and neutral_reapply_target:
            revert_action_label = f"Reapply {revert_display_label}"
            revert_tooltip = f"Apply {revert_display_label} again"
        elif revert_visible:
            revert_action_label = f"Revert to {revert_display_label}"
            revert_tooltip = f"Revert to {revert_display_label}"
        elif has_revert_target:
            revert_action_label = f"Revert to {revert_display_label}"
            revert_tooltip = "No curve changes to revert"
        else:
            revert_action_label = f"Revert to {revert_display_label}"
            revert_tooltip = "No preset baseline to revert to"

        primary_action = "reapply" if neutral_reapply_target and revert_visible else "save"
        save_label = "Reapply" if primary_action == "reapply" else ("Save" if has_named_preset else "Save As…")
        save_tooltip = (
            f"Apply {revert_display_label} again"
            if primary_action == "reapply"
            else ("Save changes to the current preset" if has_named_preset else "Save the running curve as a preset")
        )

        return PresetPanelUiState(
            preset_state_text=preset_state_text,
            preset_state_class=preset_state_class,
            preset_state_tooltip=preset_state_tooltip,
            current_curve_text=current_curve_text,
            current_curve_tooltip=current_curve_tooltip,
            save_label=save_label,
            save_tooltip=save_tooltip,
            primary_action=primary_action,
            save_as_visible=has_named_preset or primary_action == "reapply",
            revert_visible=revert_visible,
            revert_label=revert_action_label,
            revert_tooltip=revert_tooltip,
            reset_visible=reset_visible,
            reset_tooltip="Reset all bands and preamp to neutral" if reset_visible else "Curve is already neutral",
            default_set_visible=default_set_visible,
            default_clear_visible=default_clear_visible,
            default_separator_visible=curve_group_visible and default_group_visible,
            file_separator_visible=curve_group_visible or default_group_visible,
            library_separator_visible=has_named_preset,
            export_label=export_label,
            delete_visible=has_named_preset,
        )

    def update_output_preset_state(self) -> None:
        label = getattr(self, "output_preset_state_label", None)
        if label is None:
            return

        switch = getattr(self, "output_preset_switch", None)
        self.output_preset_auto_applied = False
        target = self.output_preset_target()
        self.update_output_scope_state(target)
        scope_text, _scope_kind, _status_scope = self.output_preset_scope_text(target)
        clear_tooltip = f"Clear auto preset for {scope_text}"

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
                set_switch_confirmed_state(switch, active)
            finally:
                self.updating_output_preset_switch = False
            switch.set_sensitive(sensitive)
            switch.set_tooltip_text(tooltip)

        try:
            linked_preset = get_output_preset_link(self.output_preset_keys(target))
        except Exception as exc:
            sync_output_preset_switch(
                active=False,
                sensitive=False,
                tooltip="Auto preset links are unavailable",
                status_text="Unavailable",
                status_tooltip=str(exc),
            )
            return

        has_output = bool(self.controller.output_sink)
        current_signature = self.controller.state_signature()
        has_named_preset = self.current_preset_name is not None
        has_linkable_preset = has_named_preset and current_signature == self.saved_preset_signature

        if not linked_preset:
            if not has_output:
                tooltip = "Select an EQ Output"
            elif not has_named_preset:
                tooltip = "Save a Preset First"
            elif not has_linkable_preset:
                tooltip = "Save or load the preset before linking it"
            else:
                tooltip = f"Use selected preset automatically for {scope_text}"
            sync_output_preset_switch(
                active=False,
                sensitive=has_output and has_linkable_preset,
                tooltip=tooltip,
            )
            return

        self.output_preset_auto_applied = bool(
            linked_preset
            and self.current_preset_name == linked_preset
            and self.controller.state_signature() == self.saved_preset_signature
        )
        if not self.preset_name_exists(linked_preset):
            sync_output_preset_switch(
                active=True,
                sensitive=has_output,
                tooltip=clear_tooltip,
                status_text="Missing",
                status_tooltip=f"Auto preset for {scope_text} uses missing preset {linked_preset}",
            )
            return

        if self.output_preset_auto_applied:
            sync_output_preset_switch(
                active=True,
                sensitive=has_output,
                tooltip=clear_tooltip,
                status_text="Applied",
                status_tooltip=f"Auto preset for {scope_text} uses {linked_preset}",
            )
            return

        if has_named_preset:
            status_text = "Modified" if self.current_preset_name == linked_preset else "Different"
            sync_output_preset_switch(
                active=True,
                sensitive=has_output,
                tooltip=clear_tooltip,
                status_text=status_text,
                status_tooltip=f"Auto preset for {scope_text} uses {linked_preset}",
            )
            return

        sync_output_preset_switch(
            active=True,
            sensitive=has_output,
            tooltip=clear_tooltip,
            status_text="Linked",
            status_tooltip=f"Auto preset for {scope_text} uses {linked_preset}; current curve is not that preset.",
        )

    def set_preset_widget_visible(self, name: str, visible: bool) -> None:
        widget = getattr(self, name, None)
        if widget is not None:
            widget.set_visible(visible)

    def set_preset_widget_label(self, name: str, text: str) -> None:
        label = getattr(self, f"{name}_label", None)
        if label is not None:
            label.set_text(text)
            return

        widget = getattr(self, name, None)
        if widget is not None:
            widget.set_label(text)

    def refresh_preset_actions(self, state: PresetPanelUiState | None = None) -> None:
        state = state or self.preset_panel_ui_state()

        self.preset_primary_action = state.primary_action
        self.set_preset_widget_label("preset_save_button", state.save_label)
        self.preset_save_button.set_sensitive(True)
        self.preset_save_button.set_tooltip_text(state.save_tooltip)

        self.set_preset_widget_visible("preset_save_as_button", state.save_as_visible)
        self.preset_save_as_button.set_sensitive(True)

        self.set_preset_widget_visible("preset_revert_button", state.revert_visible)
        self.set_preset_widget_label("preset_revert_button", state.revert_label)
        self.preset_revert_button.set_sensitive(state.revert_visible)
        self.preset_revert_button.set_tooltip_text(state.revert_tooltip)

        self.set_preset_widget_visible("preset_reset_to_neutral_button", state.reset_visible)
        self.preset_reset_to_neutral_button.set_sensitive(state.reset_visible)
        self.preset_reset_to_neutral_button.set_tooltip_text(state.reset_tooltip)

        self.set_preset_widget_visible("default_preset_set_button", state.default_set_visible)
        self.set_preset_widget_visible("default_preset_clear_button", state.default_clear_visible)
        self.set_preset_widget_visible(
            "preset_default_heading",
            state.default_set_visible or state.default_clear_visible,
        )
        self.default_preset_set_button.set_sensitive(state.default_set_visible)
        self.default_preset_set_button.set_tooltip_text(
            "Use the loaded saved preset when an output has no auto preset."
        )
        self.default_preset_clear_button.set_sensitive(state.default_clear_visible)
        self.default_preset_clear_button.set_tooltip_text(
            "Bypass unmatched outputs instead of loading a fallback preset"
        )

        self.set_preset_widget_visible("preset_default_separator", state.default_separator_visible)
        self.set_preset_widget_visible("preset_file_separator", state.file_separator_visible)
        self.set_preset_widget_visible("preset_library_separator", state.library_separator_visible)

        self.preset_export_button.set_sensitive(True)
        self.set_preset_widget_label("preset_export_button", state.export_label)
        self.preset_import_button.set_sensitive(True)

        self.set_preset_widget_visible("preset_delete_button", state.delete_visible)
        self.preset_delete_button.set_sensitive(state.delete_visible)
        self.update_output_preset_state()
        self.update_fallback_preset_state()

    def refresh_preset_library_popover(self) -> None:
        load_button = getattr(self, "preset_load_button", None)
        if load_button is not None:
            load_button.set_label("Choose…")
            load_button.set_sensitive(bool(self.preset_names))
            load_button.set_tooltip_text("Load a saved preset" if self.preset_names else "No saved presets")

        box = getattr(self, "preset_library_box", None)
        if box is None:
            return

        while child := box.get_first_child():
            box.remove(child)

        if not self.preset_names:
            empty_label = Gtk.Label(label="No saved presets", xalign=0.0)
            empty_label.add_css_class("dim-label")
            empty_label.set_margin_top(8)
            empty_label.set_margin_bottom(8)
            empty_label.set_margin_start(10)
            empty_label.set_margin_end(10)
            box.append(empty_label)
            return

        for preset_name in self.preset_names:
            button = Gtk.Button()
            button.set_can_shrink(True)
            button.set_hexpand(True)
            button.add_css_class("popover-action")
            button.add_css_class("preset-library-action")
            button.add_css_class("flat")
            button.set_tooltip_text(preset_name)

            label = Gtk.Label(label=preset_name, xalign=0.0)
            label.set_hexpand(True)
            label.set_wrap(True)
            label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
            label.set_max_width_chars(42)
            button.set_child(label)
            button.connect("clicked", self.on_preset_library_button_clicked, preset_name)
            box.append(button)

    def on_preset_library_button_clicked(self, _button: Gtk.Button, preset_name: str) -> None:
        popover = getattr(self, "preset_library_popover", None)
        if popover is not None:
            popover.popdown()

        try:
            self.load_library_preset(preset_name)
        except Exception as exc:
            self.set_status(str(exc))

    def selected_preset_combo_index(self) -> int:
        if (
            self.current_preset_name is not None
            and self.current_preset_name in self.preset_names
            and self.controller.state_signature() == self.saved_preset_signature
        ):
            return self.preset_names.index(self.current_preset_name)
        return Gtk.INVALID_LIST_POSITION

    def sync_preset_combo_selection(self) -> None:
        combo = getattr(self, "preset_combo", None)
        if combo is None:
            return

        self.updating_preset_combo = True
        try:
            combo.set_selected(self.selected_preset_combo_index())
        finally:
            self.updating_preset_combo = False

    def update_fallback_preset_state(self) -> None:
        label = getattr(self, "default_preset_state_label", None)
        set_button = getattr(self, "default_preset_set_button", None)
        clear_button = getattr(self, "default_preset_clear_button", None)
        row = getattr(self, "default_preset_row", None)

        try:
            default_preset = get_output_preset_fallback_name()
        except Exception as exc:
            self.fallback_preset_row_visible = True
            if row is not None:
                row.set_visible(True)
            if label is not None:
                label.set_text("Unavailable")
                label.set_tooltip_text(str(exc))
            if set_button is not None:
                set_button.set_sensitive(False)
            if clear_button is not None:
                clear_button.set_sensitive(False)
            return

        self.fallback_preset_row_visible = default_preset is not None
        if row is not None:
            row.set_visible(self.fallback_preset_row_visible)

        has_named_preset = self.current_preset_name is not None
        if set_button is not None:
            set_button.set_sensitive(has_named_preset)
        if clear_button is not None:
            clear_button.set_sensitive(default_preset is not None)

        if label is None:
            return

        if default_preset is None:
            label.set_text("Bypass")
            label.set_tooltip_text("Unmatched outputs use no fallback preset.")
            return

        if default_preset in self.preset_names:
            label.set_text(default_preset)
            label.set_tooltip_text("Used when the active output has no auto preset.")
            return

        label.set_text("Missing")
        label.set_tooltip_text(f"Fallback preset {default_preset} is unavailable")

    def keep_current_curve_as_unsaved_copy(self, preset_name: str) -> None:
        preserve_revert_baseline = (
            self.curve_revert_baseline_label == preset_name and self.curve_revert_baseline_payload is not None
        )
        self.current_preset_name = None
        self.saved_preset_signature = self.controller.state_signature()
        if preserve_revert_baseline:
            self.relabel_curve_revert_baseline(f"{DELETED_PRESET_LABEL_PREFIX}{preset_name}")
            return

        self.set_curve_revert_baseline(f"{DELETED_PRESET_LABEL_PREFIX}{preset_name}")

    def sync_current_preset_signature_from_library(self) -> None:
        if self.current_preset_name is None:
            return

        preset_name = self.current_preset_name
        try:
            payload = load_mini_eq_preset_file(preset_path_for_name(preset_name))
            signature = preset_payload_state_signature(payload)
        except Exception:
            self.keep_current_curve_as_unsaved_copy(preset_name)
            self.set_status("Preset unavailable")
            return

        self.saved_preset_signature = signature
        self.set_curve_revert_baseline_payload(preset_name, payload, signature)

    def refresh_preset_list(self) -> None:
        self.preset_names = list_preset_names()
        if self.current_preset_name is not None and self.current_preset_name not in self.preset_names:
            self.keep_current_curve_as_unsaved_copy(self.current_preset_name)
        else:
            self.sync_current_preset_signature_from_library()

        self.preset_model.splice(0, self.preset_model.get_n_items(), self.preset_names)
        self.sync_preset_combo_selection()
        self.refresh_preset_library_popover()

        self.update_preset_state()

    def update_preset_state(self) -> None:
        state = self.preset_panel_ui_state()

        self.preset_state_label.remove_css_class("preset-state-saved")
        self.preset_state_label.remove_css_class("preset-state-modified")
        self.preset_state_label.remove_css_class("preset-state-unsaved")
        self.preset_state_label.remove_css_class("preset-state-neutral")

        self.preset_state_label.set_text(state.preset_state_text)
        self.preset_state_label.add_css_class(state.preset_state_class)
        self.preset_state_label.set_tooltip_text(state.preset_state_tooltip)

        self.update_current_curve_state()
        self.sync_preset_combo_selection()
        self.refresh_preset_actions(state)

    def update_current_curve_state(self) -> None:
        label = getattr(self, "current_curve_state_label", None)
        row = getattr(self, "current_curve_row", None)
        if label is None:
            return

        current_curve_text, current_curve_tooltip = self.current_curve_running_text()
        label.set_text(current_curve_text)
        label.set_tooltip_text(current_curve_tooltip)
        if row is not None:
            row.set_visible(True)

    def save_current_state_to_preset(self, name: str) -> None:
        preset_name = sanitize_preset_name(name)
        if not preset_name:
            raise ValueError("Preset name is empty")

        payload = self.controller.build_preset_payload(preset_name)
        write_mini_eq_preset_file(preset_path_for_name(preset_name), payload)
        self.current_preset_name = preset_name
        self.saved_preset_signature = self.controller.state_signature()
        self.set_curve_revert_baseline(preset_name)
        self.output_preset_curve_auto_loaded = False
        self.refresh_preset_list()
        self.sync_ui_from_state()
        self.set_status("Preset saved")
        self.notify_control_presets_changed()
        self.notify_control_state_changed()

    def save_current_state_to_preset_as(self, name: str) -> None:
        preset_name = sanitize_preset_name(name)
        if not preset_name:
            raise ValueError("Preset name is empty")

        if preset_name != self.current_preset_name and self.preset_name_exists(preset_name):
            self.confirm_preset_replacement(
                preset_name,
                f"{preset_name} already exists. Replace it with the current curve?",
                lambda: self.save_current_state_to_preset(preset_name),
            )
            return

        self.save_current_state_to_preset(preset_name)

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
        self.set_curve_revert_baseline(preset_name)
        self.refresh_preset_list()
        self.sync_ui_from_state()
        self.output_preset_curve_auto_loaded = bool(auto)
        self.output_preset_auto_applied = (auto and output_preset_auto) or self.output_preset_is_active()
        if status_message is not None:
            self.set_status(status_message)
        elif auto:
            self.set_status("Auto preset applied")
        else:
            self.set_status("Preset loaded")
        self.notify_control_state_changed()

    def reset_curve_to_neutral(self, status_message: str = "Reset to neutral") -> None:
        reapply_label = self.curve_revert_label()
        reapply_signature = self.curve_revert_signature()
        reapply_payload = getattr(self, "curve_revert_baseline_payload", None)

        self.controller.reset_state()
        self.current_preset_name = None
        self.saved_preset_signature = self.controller.state_signature()
        if (
            reapply_label
            and reapply_signature is not None
            and reapply_signature != self.default_preset_signature
            and reapply_payload is not None
        ):
            self.set_curve_revert_baseline_payload(reapply_label, reapply_payload, reapply_signature)
        else:
            self.set_curve_revert_baseline("Neutral")
        self.selected_band_index = None
        self.set_visible_band_count(DEFAULT_ACTIVE_BANDS)
        self.output_preset_curve_auto_loaded = False
        self.output_preset_auto_applied = False
        self.refresh_preset_list()
        self.sync_ui_from_state()
        self.set_status(status_message)
        self.notify_control_state_changed()

    def apply_output_preset_for_current_output(
        self,
        *,
        reset_auto_preset_without_link: bool = False,
        announce_no_output_preset: bool = False,
    ) -> bool:
        target = self.output_preset_target()
        try:
            linked_preset = get_output_preset_link(self.output_preset_keys(target))
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
                    self.set_status("Current curve kept")
                self.notify_control_state_changed()
                return announce_no_output_preset

            default_preset = get_output_preset_fallback_name()
            should_apply_default_preset = default_preset is not None and (
                reset_auto_preset_without_link or self.current_preset_name is None
            )
            if should_apply_default_preset:
                try:
                    self.load_library_preset(
                        default_preset,
                        auto=True,
                        output_preset_auto=False,
                        status_message="Fallback preset applied",
                    )
                except Exception:
                    self.output_preset_auto_applied = False
                    self.output_preset_curve_auto_loaded = False
                    self.update_preset_state()
                    self.set_status("Fallback preset unavailable")
                    self.notify_control_state_changed()
                else:
                    return True

            if reset_auto_preset_without_link:
                self.reset_curve_to_neutral("Unmatched output bypassed")
                return True

            self.output_preset_auto_applied = False
            self.output_preset_curve_auto_loaded = False
            self.update_preset_state()
            self.notify_control_state_changed()
            return False

        if self.has_unsaved_curve_changes():
            self.output_preset_auto_applied = False
            self.output_preset_curve_auto_loaded = False
            self.update_preset_state()
            self.set_status("Current curve kept")
            self.notify_control_state_changed()
            return True

        try:
            self.load_library_preset(linked_preset, auto=True)
        except Exception:
            self.output_preset_auto_applied = False
            self.output_preset_curve_auto_loaded = False
            self.update_preset_state()
            self.set_status("Auto preset unavailable")
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
        set_accessible_label(entry, "Preset name")
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
            self.set_status("Preset name is empty")
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
        if getattr(self, "preset_primary_action", "save") == "reapply":
            self.on_preset_revert_clicked(button)
            return

        if self.current_preset_name is not None:
            try:
                self.save_current_state_to_preset(self.current_preset_name)
            except Exception as exc:
                self.set_status(str(exc))
            return

        self.on_preset_save_as_clicked(button)

    def on_preset_save_as_clicked(self, button: Gtk.Button) -> None:
        initial_name = self.suggested_save_as_name()
        self.prompt_for_preset_name("Save Preset As", "Save", initial_name, self.save_current_state_to_preset_as)

    def on_preset_revert_clicked(self, button: Gtk.Button) -> None:
        if self.current_preset_name is not None:
            preset_name = self.current_preset_name
            try:
                self.load_library_preset(preset_name)
                self.set_status("Preset restored")
            except Exception as exc:
                self.set_status(str(exc))
            return

        payload = getattr(self, "curve_revert_baseline_payload", None)
        if payload is None:
            self.set_status("Nothing to restore")
            return

        baseline_label = self.curve_revert_label() or "Curve Baseline"
        reapply_from_neutral = self.has_neutral_reapply_target()
        if reapply_from_neutral:
            try:
                if self.preset_name_exists(baseline_label):
                    self.load_library_preset(
                        baseline_label,
                        status_message="Preset restored",
                    )
                    return
            except Exception:
                pass

        try:
            self.controller.apply_preset_payload(payload)
            self.current_preset_name = None
            self.saved_preset_signature = self.controller.state_signature()
            self.output_preset_auto_applied = False
            self.output_preset_curve_auto_loaded = False
            self.selected_band_index = None
            self.set_visible_band_count(fader_band_count_for_profile(self.controller.bands))
            self.sync_ui_from_state()
            self.set_status("Curve restored")
            self.notify_control_state_changed()
        except Exception as exc:
            self.set_status(str(exc))

    def on_preset_reset_to_neutral_clicked(self, _button: Gtk.Button) -> None:
        try:
            self.reset_curve_to_neutral()
        except Exception as exc:
            self.set_status(str(exc))

    def on_use_preset_for_output_clicked(self, _button: Gtk.Widget) -> None:
        if self.current_preset_name is None:
            self.set_status("Choose a preset first")
            return
        if self.controller.state_signature() != self.saved_preset_signature:
            self.set_status("Save or load preset first")
            return

        target = self.output_preset_target()
        try:
            set_output_preset_link(self.output_preset_link_key(target), self.current_preset_name)
            self.output_preset_auto_applied = self.output_preset_is_active()
            self.output_preset_curve_auto_loaded = False
            self.update_preset_state()
            self.set_status("Auto preset linked")
            self.notify_control_state_changed()
        except Exception as exc:
            self.set_status(str(exc))

    def on_use_preset_as_fallback_clicked(self, _button: Gtk.Widget) -> None:
        if self.current_preset_name is None:
            self.set_status("Choose a preset first")
            return
        if self.controller.state_signature() != self.saved_preset_signature:
            self.set_status("Save or load preset first")
            return

        try:
            set_output_preset_fallback_name(self.current_preset_name)
            self.output_preset_curve_auto_loaded = False
            self.update_preset_state()
            self.set_status("Fallback preset set")
            self.notify_control_state_changed()
        except Exception as exc:
            self.set_status(str(exc))
            self.notify_control_state_changed()

    def on_bypass_unmatched_outputs_clicked(self, _button: Gtk.Widget) -> None:
        try:
            removed = clear_output_preset_fallback_name()
            self.output_preset_curve_auto_loaded = False
            self.update_preset_state()
            if removed:
                self.set_status("Unmatched outputs bypassed")
            else:
                self.set_status("Unmatched outputs already bypassed")
            self.notify_control_state_changed()
        except Exception as exc:
            self.set_status(str(exc))
            self.notify_control_state_changed()

    def on_clear_output_preset_link_clicked(self, _button: Gtk.Widget) -> None:
        target = self.output_preset_target()
        try:
            removed = clear_output_preset_link(self.output_preset_keys(target))
            self.output_preset_auto_applied = False
            self.output_preset_curve_auto_loaded = False
            self.update_preset_state()
            if removed:
                self.set_status("Auto preset cleared")
            else:
                self.set_status("No auto preset")
            self.notify_control_state_changed()
        except Exception as exc:
            self.set_status(str(exc))

    def on_output_preset_switch_changed(self, switch: Gtk.Switch, state: object | None = None) -> bool:
        if self.updating_output_preset_switch:
            return False

        if requested_switch_state(switch, state):
            self.on_use_preset_for_output_clicked(switch)
        else:
            self.on_clear_output_preset_link_clicked(switch)

        self.update_preset_state()
        self.updating_output_preset_switch = True
        try:
            set_switch_confirmed_state(switch, switch.get_active())
        finally:
            self.updating_output_preset_switch = False
        return True

    def on_preset_delete_clicked(self, button: Gtk.Button) -> None:
        if self.current_preset_name is None:
            self.set_status("Choose a preset first")
            return

        preset_name = self.current_preset_name
        dialog = Adw.AlertDialog()
        dialog.set_heading("Delete preset?")
        dialog.set_body(f"{preset_name} will be removed from your preset library. The current curve will stay active.")
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
            self.keep_current_curve_as_unsaved_copy(preset_name)
            self.refresh_preset_list()
            self.sync_ui_from_state()
            self.set_status("Preset deleted; curve kept")
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

    def import_library_preset_payload(self, preset_name: str, payload: dict[str, object]) -> None:
        write_mini_eq_preset_file(preset_path_for_name(preset_name), payload)
        self.controller.apply_preset_payload(payload)
        self.selected_band_index = None
        self.set_visible_band_count(fader_band_count_for_profile(self.controller.bands))
        self.current_preset_name = preset_name
        self.saved_preset_signature = self.controller.state_signature()
        self.set_curve_revert_baseline(preset_name)
        self.refresh_preset_list()
        self.sync_ui_from_state()
        self.set_status("Preset imported")
        self.notify_control_presets_changed()
        self.notify_control_state_changed()

    def on_preset_import_done(self, dialog: Gtk.FileDialog, result: Gio.AsyncResult) -> None:
        try:
            file = dialog.open_finish(result)
        except GLib.Error:
            return

        path = file.get_path()
        if path is None:
            self.set_status("Could not open preset")
            return

        try:
            payload = load_mini_eq_preset_file(path)
            preset_name = sanitize_preset_name(str(payload.get("name", ""))) or sanitize_preset_name(Path(path).stem)
            if not preset_name:
                raise ValueError("Preset file does not contain a usable name")

            stored_payload = dict(payload)
            stored_payload["version"] = PRESET_VERSION
            stored_payload["name"] = preset_name
            if self.preset_name_exists(preset_name):
                self.confirm_preset_replacement(
                    preset_name,
                    f"{preset_name} already exists. Replace it with the imported preset?",
                    lambda: self.import_library_preset_payload(preset_name, stored_payload),
                )
                return

            self.import_library_preset_payload(preset_name, stored_payload)
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
        export_name = self.current_preset_name or self.suggested_save_as_name() or "mini-eq"
        dialog.set_initial_name(f"{sanitize_preset_name(export_name)}{PRESET_FILE_SUFFIX}")
        dialog.save(self, None, self.on_preset_export_done)

    def on_preset_export_done(self, dialog: Gtk.FileDialog, result: Gio.AsyncResult) -> None:
        try:
            file = dialog.save_finish(result)
        except GLib.Error:
            return

        path = file.get_path()
        if path is None:
            self.set_status("Could not export preset")
            return

        try:
            export_path = ensure_json_suffix(Path(path))
            payload = self.controller.build_preset_payload(self.current_preset_name or export_path.stem)
            write_mini_eq_preset_file(export_path, payload)
            self.set_status("Preset exported")
        except Exception as exc:
            self.set_status(str(exc))
