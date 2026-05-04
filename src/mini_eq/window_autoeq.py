from __future__ import annotations

import math
import threading
from pathlib import Path
from typing import Any

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")

from gi.repository import Adw, Gdk, GLib, Gtk, Pango

from .appearance import style_manager_is_dark
from .autoeq import (
    AutoEqEntry,
    download_autoeq_preset_info,
    load_autoeq_entries,
    search_autoeq_entries,
)
from .core import (
    GRAPH_DB_MAX,
    GRAPH_DB_MIN,
    GRAPH_FREQ_MAX,
    GRAPH_FREQ_MIN,
    SAMPLE_RATE,
    EqBand,
    parse_apo_file,
    stepped_response_frequencies,
    total_response_db_at_frequencies,
)
from .glib_utils import destroy_glib_source
from .window_utils import set_accessible_description, set_accessible_label

AUTOEQ_PREVIEW_STEPS = 192
AUTOEQ_PREVIEW_DEBOUNCE_MS = 240
AUTOEQ_SERVICE_URL = "https://autoeq.app/"
AUTOEQ_PREVIEW_DEFAULT_DETAIL = "Select a profile to preview its curve"
AUTOEQ_PREVIEW_CONTENT_HEIGHT = 118
AUTOEQ_PREVIEW_DEFAULT_DB_LIMIT = 15.0
AUTOEQ_PREVIEW_DB_TICK_STEP = 5.0
AUTOEQ_PREVIEW_MAJOR_FREQ_TICKS = (20.0, 100.0, 1000.0, 10000.0, 20000.0)
AUTOEQ_PREVIEW_MINOR_FREQ_TICKS = (
    50.0,
    200.0,
    500.0,
    2000.0,
    5000.0,
)
AUTOEQ_PREVIEW_FREQ_TICKS = tuple(sorted(AUTOEQ_PREVIEW_MAJOR_FREQ_TICKS + AUTOEQ_PREVIEW_MINOR_FREQ_TICKS))
AUTOEQ_PREVIEW_FREQ_LABELS = {
    20.0: "20Hz",
    100.0: "100",
    1000.0: "1k",
    10000.0: "10k",
    20000.0: "20kHz",
}


def autoeq_row_markup(text: str) -> str:
    return GLib.markup_escape_text(text)


class MiniEqWindowAutoEqMixin:
    def on_import_autoeq_clicked(self, _button: Gtk.Widget) -> None:
        active_dialog = getattr(self, "autoeq_dialog", None)
        if active_dialog is not None and self.autoeq_dialog_is_active():
            active_dialog.present(self)
            GLib.idle_add(self.focus_autoeq_search_entry)
            return

        dialog = Adw.Dialog()
        dialog.set_title("Import from AutoEq")
        dialog.set_content_width(640)
        dialog.set_content_height(560)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content.set_margin_top(18)
        content.set_margin_bottom(18)
        content.set_margin_start(18)
        content.set_margin_end(18)

        search_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        search_entry = Gtk.SearchEntry()
        search_entry.set_hexpand(True)
        search_entry.set_placeholder_text("Search headphones")
        set_accessible_label(search_entry, "Search AutoEq Headphones")
        search_row.append(search_entry)

        refresh_button = Gtk.Button()
        refresh_button.set_icon_name("view-refresh-symbolic")
        refresh_button.set_tooltip_text("Refresh AutoEq Profiles")
        set_accessible_label(refresh_button, "Refresh AutoEq Profiles")
        search_row.append(refresh_button)
        content.append(search_row)

        status_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        status_label = Gtk.Label(xalign=0.0)
        status_label.set_hexpand(True)
        status_label.add_css_class("dim-label")
        status_row.append(status_label)

        spinner = Gtk.Spinner()
        spinner.set_visible(False)
        status_row.append(spinner)
        content.append(status_row)

        results_list = Gtk.ListBox()
        results_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        results_list.add_css_class("boxed-list")

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_min_content_height(240)
        scroller.set_vexpand(True)
        scroller.set_child(results_list)
        content.append(scroller)

        preview_shell = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        preview_shell.add_css_class("autoeq-preview")

        preview_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        preview_title = Gtk.Label(label="Select a profile to import", xalign=0.0)
        preview_title.set_hexpand(True)
        preview_title.set_ellipsize(Pango.EllipsizeMode.END)
        preview_title.add_css_class("heading")
        preview_header.append(preview_title)

        preview_count_label = Gtk.Label(xalign=1.0)
        preview_count_label.add_css_class("dim-label")
        preview_header.append(preview_count_label)
        preview_shell.append(preview_header)

        preview_area = Gtk.DrawingArea()
        preview_area.set_content_height(AUTOEQ_PREVIEW_CONTENT_HEIGHT)
        preview_area.set_hexpand(True)
        set_accessible_label(preview_area, "AutoEq curve preview")
        set_accessible_description(preview_area, "No AutoEq profile selected")
        preview_area.set_draw_func(self.on_autoeq_preview_draw)
        preview_shell.append(preview_area)

        preview_detail = Gtk.Label(label=AUTOEQ_PREVIEW_DEFAULT_DETAIL, xalign=0.0)
        preview_detail.set_hexpand(True)
        preview_detail.set_ellipsize(Pango.EllipsizeMode.END)
        preview_detail.add_css_class("dim-label")
        preview_shell.append(preview_detail)
        content.append(preview_shell)

        footer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        footer.set_hexpand(True)

        attribution_link = Gtk.LinkButton(uri=AUTOEQ_SERVICE_URL, label="Generated by AutoEq")
        attribution_link.set_halign(Gtk.Align.START)
        attribution_link.set_hexpand(True)
        attribution_link.set_tooltip_text("Open autoeq.app")
        footer.append(attribution_link)

        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        actions.set_halign(Gtk.Align.END)

        cancel_button = Gtk.Button(label="Cancel")
        cancel_button.connect("clicked", lambda _button: dialog.close())
        actions.append(cancel_button)

        import_button = Gtk.Button(label="Import")
        import_button.add_css_class("suggested-action")
        import_button.set_sensitive(False)
        actions.append(import_button)
        footer.append(actions)
        content.append(footer)

        self.autoeq_dialog = dialog
        self.autoeq_search_entry = search_entry
        self.autoeq_refresh_button = refresh_button
        self.autoeq_spinner = spinner
        self.autoeq_status_label = status_label
        self.autoeq_results_list = results_list
        self.autoeq_import_button = import_button
        self.autoeq_cancel_button = cancel_button
        self.autoeq_preview_title = preview_title
        self.autoeq_preview_count_label = preview_count_label
        self.autoeq_preview_area = preview_area
        self.autoeq_preview_detail = preview_detail
        self.autoeq_import_in_progress = False
        self.autoeq_selected_entry = None
        self.autoeq_preview_path = None
        self.autoeq_preview_preamp_db = None
        self.autoeq_preview_target_label = None
        self.autoeq_preview_bands = []
        self.autoeq_preview_error = None
        self.autoeq_preview_loading = False
        self.autoeq_preview_source_id = 0
        self.autoeq_dialog_closed = False
        self.autoeq_profiles_request_id += 1
        self.autoeq_import_request_id += 1
        self.autoeq_preview_request_id += 1

        search_entry.connect("search-changed", self.on_autoeq_search_changed)
        search_entry.connect("activate", self.on_autoeq_search_entry_activated)
        refresh_button.connect("clicked", lambda _button: self.start_autoeq_profiles_load(refresh=True))
        results_list.connect("row-selected", self.on_autoeq_row_selected)
        import_button.connect("clicked", self.on_autoeq_import_clicked)
        result_keys = Gtk.EventControllerKey()
        result_keys.connect("key-pressed", self.on_autoeq_results_key_pressed)
        results_list.add_controller(result_keys)
        dialog.connect("closed", self.on_autoeq_dialog_closed)

        dialog.set_child(content)
        dialog.set_default_widget(import_button)
        dialog.set_focus(search_entry)
        dialog.present(self)
        self.start_autoeq_profiles_load(refresh=False)

    def autoeq_dialog_is_active(self) -> bool:
        return bool(
            getattr(self, "autoeq_dialog", None) is not None and not getattr(self, "autoeq_dialog_closed", False)
        )

    def on_autoeq_dialog_closed(self, dialog: Adw.Dialog) -> None:
        if dialog is getattr(self, "autoeq_dialog", None):
            self.cleanup_autoeq_dialog()

    def cleanup_autoeq_dialog(self) -> None:
        if getattr(self, "autoeq_dialog_closed", False):
            return

        self.autoeq_dialog_closed = True
        self.autoeq_profiles_request_id += 1
        self.autoeq_import_request_id += 1
        self.autoeq_preview_request_id += 1

        if self.autoeq_preview_source_id > 0:
            destroy_glib_source(self.autoeq_preview_source_id)
            self.autoeq_preview_source_id = 0

        spinner = getattr(self, "autoeq_spinner", None)
        if spinner is not None:
            spinner.stop()
            spinner.set_visible(False)

        self.autoeq_import_in_progress = False
        self.autoeq_dialog = None
        self.autoeq_search_entry = None
        self.autoeq_refresh_button = None
        self.autoeq_spinner = None
        self.autoeq_status_label = None
        self.autoeq_results_list = None
        self.autoeq_import_button = None
        self.autoeq_cancel_button = None
        self.autoeq_preview_title = None
        self.autoeq_preview_count_label = None
        self.autoeq_preview_area = None
        self.autoeq_preview_detail = None

    def focus_autoeq_search_entry(self) -> bool:
        search_entry = getattr(self, "autoeq_search_entry", None)
        if search_entry is not None:
            search_entry.grab_focus()
        return False

    def set_autoeq_busy(self, busy: bool, message: str) -> None:
        self.autoeq_status_label.set_text(message)
        self.autoeq_spinner.set_visible(busy)
        if busy:
            self.autoeq_spinner.start()
        else:
            self.autoeq_spinner.stop()

        self.autoeq_refresh_button.set_sensitive(not busy)
        self.autoeq_search_entry.set_sensitive(not busy)
        self.autoeq_results_list.set_sensitive(not busy)
        self.update_autoeq_import_button_sensitivity(busy=busy)

    def selected_autoeq_entry(self) -> AutoEqEntry | None:
        results_list = getattr(self, "autoeq_results_list", None)
        if results_list is None:
            return None

        row = results_list.get_selected_row()
        entry = getattr(row, "autoeq_entry", None)
        return entry if isinstance(entry, AutoEqEntry) else None

    def can_import_autoeq_preview(self) -> bool:
        results_list = getattr(self, "autoeq_results_list", None)
        entry = self.selected_autoeq_entry()
        path = self.autoeq_preview_path
        return (
            results_list is not None
            and results_list.get_sensitive()
            and entry is not None
            and entry == self.autoeq_selected_entry
            and path is not None
            and Path(path).is_file()
            and self.autoeq_preview_target_label is not None
            and self.autoeq_preview_error is None
            and not self.autoeq_preview_loading
            and not getattr(self, "autoeq_import_in_progress", False)
        )

    def update_autoeq_import_button_sensitivity(self, *, busy: bool = False) -> None:
        import_button = getattr(self, "autoeq_import_button", None)
        if import_button is not None:
            import_button.set_sensitive(not busy and self.can_import_autoeq_preview())

    def set_autoeq_import_in_progress(self, in_progress: bool) -> None:
        self.autoeq_import_in_progress = in_progress
        dialog = getattr(self, "autoeq_dialog", None)
        if dialog is not None:
            dialog.set_can_close(not in_progress)

        cancel_button = getattr(self, "autoeq_cancel_button", None)
        if cancel_button is not None:
            cancel_button.set_sensitive(not in_progress)

    def start_autoeq_profiles_load(self, *, refresh: bool) -> None:
        self.autoeq_profiles_request_id += 1
        request_id = self.autoeq_profiles_request_id
        self.set_autoeq_busy(True, "Refreshing AutoEq profiles…" if refresh else "Loading AutoEq profiles…")

        def load_profiles() -> None:
            try:
                entries = load_autoeq_entries(refresh=refresh)
                GLib.idle_add(self.finish_autoeq_profiles_load, request_id, entries, None)
            except Exception as exc:
                GLib.idle_add(self.finish_autoeq_profiles_load, request_id, [], str(exc))

        threading.Thread(target=load_profiles, daemon=True).start()

    def finish_autoeq_profiles_load(self, request_id: int, entries: list[AutoEqEntry], error: str | None) -> bool:
        if request_id != self.autoeq_profiles_request_id or not self.autoeq_dialog_is_active():
            return False

        if error is not None:
            self.autoeq_entries = []
            self.set_autoeq_busy(False, error)
            self.update_autoeq_results()
            GLib.idle_add(self.focus_autoeq_search_entry)
            return False

        self.autoeq_entries = entries
        self.set_autoeq_busy(False, f"Loaded {len(entries):,} AutoEq profiles")
        self.update_autoeq_results()
        GLib.idle_add(self.focus_autoeq_search_entry)
        return False

    def on_autoeq_search_changed(self, _entry: Gtk.SearchEntry) -> None:
        self.update_autoeq_results()

    def clear_autoeq_results(self) -> None:
        while row := self.autoeq_results_list.get_row_at_index(0):
            self.autoeq_results_list.remove(row)

    def show_autoeq_placeholder(self, message: str) -> None:
        row = Gtk.ListBoxRow()
        row.set_selectable(False)
        row.set_activatable(False)

        label = Gtk.Label(label=message, xalign=0.0)
        label.set_hexpand(True)
        label.set_wrap(True)
        label.add_css_class("dim-label")
        label.set_margin_top(12)
        label.set_margin_bottom(12)
        label.set_margin_start(12)
        label.set_margin_end(12)

        row.set_child(label)
        self.autoeq_results_list.append(row)

    def update_autoeq_results(self) -> None:
        self.clear_autoeq_results()
        self.autoeq_import_button.set_sensitive(False)
        self.clear_autoeq_preview()

        query = self.autoeq_search_entry.get_text().strip()
        if not query:
            if self.autoeq_entries:
                self.autoeq_status_label.set_text("Search by headphone model")
                self.show_autoeq_placeholder("Search by headphone model")
            return

        if len(query) < 2:
            self.autoeq_status_label.set_text("Keep typing to search")
            self.show_autoeq_placeholder("Keep typing to search")
            return

        results = search_autoeq_entries(self.autoeq_entries, query, limit=80)
        if not results:
            self.autoeq_status_label.set_text("No AutoEq profiles found")
            self.show_autoeq_placeholder("No AutoEq profiles found")
            return

        for entry in results:
            self.autoeq_results_list.append(self.make_autoeq_result_row(entry))

        self.autoeq_status_label.set_text(f"{len(results)} match{'es' if len(results) != 1 else ''}")

    def make_autoeq_result_row(self, entry: AutoEqEntry) -> Gtk.ListBoxRow:
        row = Adw.ActionRow()
        row.set_title(autoeq_row_markup(entry.name))
        row.set_title_lines(1)
        row.set_subtitle(autoeq_row_markup(entry.detail or "AutoEq"))
        row.set_subtitle_lines(1)
        row.set_tooltip_text(f"{entry.name}\n{entry.detail}" if entry.detail else entry.name)
        row.set_selectable(True)
        row.set_activatable(True)
        row.autoeq_entry = entry  # type: ignore[attr-defined]
        return row

    def on_autoeq_row_selected(self, _list_box: Gtk.ListBox, row: Gtk.ListBoxRow | None) -> None:
        self.autoeq_import_button.set_sensitive(False)
        entry = getattr(row, "autoeq_entry", None)
        if isinstance(entry, AutoEqEntry):
            self.schedule_autoeq_preview_load(entry)
        else:
            self.clear_autoeq_preview()

    def on_autoeq_search_entry_activated(self, _entry: Gtk.SearchEntry) -> None:
        self.on_autoeq_import_clicked(self.autoeq_import_button)

    def on_autoeq_results_key_pressed(
        self,
        _controller: Gtk.EventControllerKey,
        keyval: int,
        _keycode: int,
        _state: Gdk.ModifierType,
    ) -> bool:
        if keyval not in {Gdk.KEY_Return, Gdk.KEY_KP_Enter}:
            return False

        self.on_autoeq_import_clicked(self.autoeq_import_button)
        return True

    def on_autoeq_import_clicked(self, _button: Gtk.Button) -> None:
        row = self.autoeq_results_list.get_selected_row()
        entry = getattr(row, "autoeq_entry", None)
        if not isinstance(entry, AutoEqEntry):
            return
        if not self.can_import_autoeq_preview():
            return

        preview_path = self.autoeq_preview_path
        if preview_path is None:
            return

        self.autoeq_import_request_id += 1
        request_id = self.autoeq_import_request_id
        self.finish_autoeq_import(request_id, entry, str(preview_path), None)

    def finish_autoeq_import(self, request_id: int, entry: AutoEqEntry, path: str, error: str | None) -> bool:
        if request_id != self.autoeq_import_request_id or not self.autoeq_dialog_is_active():
            return False

        if error is not None:
            self.set_autoeq_import_in_progress(False)
            self.set_autoeq_busy(False, error)
            return False

        try:
            imported_count = self.import_apo_preset_path(path, imported_name=entry.name)
        except Exception as exc:
            self.set_autoeq_import_in_progress(False)
            self.set_autoeq_busy(False, str(exc))
            return False

        self.set_autoeq_import_in_progress(False)
        self.set_autoeq_busy(False, f"Imported {imported_count} band(s) from {entry.name}")
        self.set_status(f"Imported AutoEq Preset: {entry.name}")
        dialog = getattr(self, "autoeq_dialog", None)
        if dialog is not None:
            dialog.force_close()
        return False

    def clear_autoeq_preview(self) -> None:
        if self.autoeq_preview_source_id > 0:
            destroy_glib_source(self.autoeq_preview_source_id)
            self.autoeq_preview_source_id = 0

        self.autoeq_selected_entry = None
        self.autoeq_preview_path = None
        self.autoeq_preview_preamp_db = None
        self.autoeq_preview_target_label = None
        self.autoeq_preview_bands = []
        self.autoeq_preview_error = None
        self.autoeq_preview_loading = False
        self.autoeq_preview_request_id += 1

        self.autoeq_preview_title.set_text("Select a profile to import")
        self.autoeq_preview_count_label.set_text("")
        self.autoeq_preview_detail.set_text(AUTOEQ_PREVIEW_DEFAULT_DETAIL)
        self.set_autoeq_preview_accessible_description("No AutoEq profile selected")
        self.autoeq_preview_area.queue_draw()

    def schedule_autoeq_preview_load(self, entry: AutoEqEntry) -> None:
        if self.autoeq_preview_source_id > 0:
            destroy_glib_source(self.autoeq_preview_source_id)
            self.autoeq_preview_source_id = 0

        self.autoeq_selected_entry = entry
        self.autoeq_preview_path = None
        self.autoeq_preview_preamp_db = None
        self.autoeq_preview_target_label = None
        self.autoeq_preview_bands = []
        self.autoeq_preview_error = None
        self.autoeq_preview_loading = False
        self.autoeq_preview_request_id += 1
        request_id = self.autoeq_preview_request_id

        self.autoeq_preview_title.set_text("Curve Preview")
        self.autoeq_preview_count_label.set_text("Preview")
        self.autoeq_preview_detail.set_text(entry.detail or "AutoEq")
        self.set_autoeq_preview_accessible_description(f"AutoEq curve preview for {entry.name}")
        self.autoeq_preview_area.queue_draw()
        self.autoeq_preview_source_id = GLib.timeout_add(
            AUTOEQ_PREVIEW_DEBOUNCE_MS,
            self.on_autoeq_preview_debounce_timeout,
            request_id,
            entry,
        )

    def on_autoeq_preview_debounce_timeout(self, request_id: int, entry: AutoEqEntry) -> bool:
        self.autoeq_preview_source_id = 0
        if request_id != self.autoeq_preview_request_id or self.autoeq_selected_entry != entry:
            return False

        self.start_autoeq_preview_load(entry, request_id=request_id)
        return False

    def start_autoeq_preview_load(self, entry: AutoEqEntry, *, request_id: int | None = None) -> None:
        if request_id is None:
            self.autoeq_preview_request_id += 1
            request_id = self.autoeq_preview_request_id

        self.autoeq_selected_entry = entry
        self.autoeq_preview_loading = True
        self.autoeq_preview_count_label.set_text("Loading")
        self.set_autoeq_preview_accessible_description(f"Loading AutoEq curve preview for {entry.name}")
        self.autoeq_preview_area.queue_draw()

        def load_preview() -> None:
            try:
                preset = download_autoeq_preset_info(entry)
                preamp, bands = parse_apo_file(str(preset.path))
                GLib.idle_add(
                    self.finish_autoeq_preview_load,
                    request_id,
                    entry,
                    str(preset.path),
                    preamp,
                    bands,
                    preset.target_label,
                    None,
                )
            except Exception as exc:
                GLib.idle_add(self.finish_autoeq_preview_load, request_id, entry, "", 0.0, [], None, str(exc))

        threading.Thread(target=load_preview, daemon=True).start()

    def finish_autoeq_preview_load(
        self,
        request_id: int,
        entry: AutoEqEntry,
        path: str,
        preamp_db: float,
        bands: list[EqBand],
        target_label: str | None,
        error: str | None,
    ) -> bool:
        if (
            request_id != self.autoeq_preview_request_id
            or self.autoeq_selected_entry != entry
            or not self.autoeq_dialog_is_active()
        ):
            return False

        self.autoeq_preview_loading = False
        self.autoeq_preview_error = error
        self.autoeq_preview_path = Path(path) if path else None
        self.autoeq_preview_preamp_db = preamp_db if error is None else None
        self.autoeq_preview_target_label = target_label if error is None else None
        self.autoeq_preview_bands = bands

        if error is not None:
            self.autoeq_preview_count_label.set_text("Unavailable")
            self.autoeq_preview_detail.set_text(error)
            self.set_autoeq_preview_accessible_description(
                f"AutoEq curve preview unavailable for {entry.name}: {error}"
            )
        else:
            self.autoeq_preview_count_label.set_text(f"{len(bands)} filters")
            detail = entry.detail or "AutoEq"
            self.autoeq_preview_detail.set_text(self.autoeq_preview_detail_text(preamp_db, detail, target_label))
            description_parts = [f"{len(bands)} filters", f"preamp {preamp_db:+.1f} dB"]
            if target_label:
                description_parts.append(f"target {target_label}")
            self.set_autoeq_preview_accessible_description(
                f"AutoEq curve preview for {entry.name}: {', '.join(description_parts)}"
            )

        self.update_autoeq_import_button_sensitivity()
        self.autoeq_preview_area.queue_draw()
        return False

    def autoeq_preview_detail_text(self, preamp_db: float, detail: str, target_label: str | None) -> str:
        parts = []
        if target_label:
            parts.append(f"Target: {target_label}")
        parts.append(f"Preamp {preamp_db:+.1f} dB")
        if detail:
            parts.append(detail)
        return " - ".join(parts)

    def set_autoeq_preview_accessible_description(self, description: str) -> None:
        preview_area = getattr(self, "autoeq_preview_area", None)
        if preview_area is not None:
            set_accessible_description(preview_area, description)

    def autoeq_preview_palette(self) -> dict[str, tuple[float, float, float, float]]:
        try:
            dark = style_manager_is_dark(getattr(self, "style_manager", None))
        except Exception:
            dark = False

        if dark:
            return {
                "background": (1.0, 1.0, 1.0, 0.06),
                "border": (1.0, 1.0, 1.0, 0.16),
                "grid": (1.0, 1.0, 1.0, 0.16),
                "grid_major": (1.0, 1.0, 1.0, 0.26),
                "axis": (1.0, 1.0, 1.0, 0.36),
                "label": (0.92, 0.95, 0.98, 0.58),
                "message": (0.92, 0.95, 0.98, 0.72),
                "response_shadow": (1.0, 0.58, 0.18, 0.36),
                "response": (1.0, 0.62, 0.22, 1.0),
            }

        return {
            "background": (0.04, 0.07, 0.10, 0.05),
            "border": (0.04, 0.08, 0.12, 0.16),
            "grid": (0.10, 0.16, 0.22, 0.14),
            "grid_major": (0.10, 0.16, 0.22, 0.24),
            "axis": (0.10, 0.16, 0.22, 0.36),
            "label": (0.12, 0.15, 0.18, 0.58),
            "message": (0.12, 0.15, 0.18, 0.72),
            "response_shadow": (0.82, 0.34, 0.02, 0.28),
            "response": (0.82, 0.34, 0.02, 1.0),
        }

    def autoeq_preview_db_limit(self, response) -> float:
        response_values = [abs(float(db_value)) for db_value in response]
        if not response_values:
            return AUTOEQ_PREVIEW_DEFAULT_DB_LIMIT

        max_response = max(response_values)
        stepped_limit = math.ceil(max_response / AUTOEQ_PREVIEW_DB_TICK_STEP) * AUTOEQ_PREVIEW_DB_TICK_STEP
        return max(AUTOEQ_PREVIEW_DEFAULT_DB_LIMIT, min(max(abs(GRAPH_DB_MIN), abs(GRAPH_DB_MAX)), stepped_limit))

    def on_autoeq_preview_draw(self, _area: Gtk.DrawingArea, cr, width: int, height: int) -> None:
        width_f = float(width)
        height_f = float(height)
        radius = 10.0
        palette = self.autoeq_preview_palette()

        cr.set_source_rgba(*palette["background"])
        self.rounded_rectangle(cr, 0.5, 0.5, max(width_f - 1.0, 1.0), max(height_f - 1.0, 1.0), radius)
        cr.fill()

        cr.set_source_rgba(*palette["border"])
        self.rounded_rectangle(cr, 0.5, 0.5, max(width_f - 1.0, 1.0), max(height_f - 1.0, 1.0), radius)
        cr.stroke()

        bands = self.autoeq_preview_bands
        preamp_db = self.autoeq_preview_preamp_db
        frequencies: list[float] = []
        response: list[float] = []
        if bands and preamp_db is not None:
            frequencies = stepped_response_frequencies(SAMPLE_RATE, AUTOEQ_PREVIEW_STEPS)
            response = total_response_db_at_frequencies(bands, preamp_db, SAMPLE_RATE, frequencies)

        db_limit = self.autoeq_preview_db_limit(response)
        left, right, top, bottom = self.draw_autoeq_preview_grid(cr, width_f, height_f, palette, db_limit)

        if self.autoeq_preview_loading:
            self.draw_autoeq_preview_message(cr, width_f, height_f, "Loading preview", palette["message"])
            return

        if self.autoeq_preview_error is not None:
            self.draw_autoeq_preview_message(cr, width_f, height_f, "Preview unavailable", palette["message"])
            return

        if len(response) == 0:
            self.draw_autoeq_preview_message(cr, width_f, height_f, "No profile selected", palette["message"])
            return

        plot_width = max(width_f - left - right, 1.0)
        plot_height = max(height_f - top - bottom, 1.0)
        db_min = -db_limit
        db_max = db_limit

        points: list[tuple[float, float]] = []
        for frequency, db_value in zip(frequencies, response, strict=False):
            x = self.autoeq_preview_frequency_x(frequency, left, plot_width)
            y = self.autoeq_preview_db_y(db_value, top, plot_height, db_min, db_max)
            points.append((x, y))

        if len(points) < 2:
            return

        cr.set_source_rgba(*palette["response_shadow"])
        cr.set_line_width(5.0)
        cr.move_to(points[0][0], points[0][1])
        for x, y in points[1:]:
            cr.line_to(x, y)
        cr.stroke()

        cr.set_source_rgba(*palette["response"])
        cr.set_line_width(2.0)
        cr.move_to(points[0][0], points[0][1])
        for x, y in points[1:]:
            cr.line_to(x, y)
        cr.stroke()

    def draw_autoeq_preview_grid(
        self,
        cr,
        width: float,
        height: float,
        palette: dict[str, tuple[float, float, float, float]],
        db_limit: float,
    ) -> tuple[float, float, float, float]:
        left = 34.0
        right = 28.0
        top = 12.0
        bottom = 22.0
        plot_width = max(width - left - right, 1.0)
        plot_height = max(height - top - bottom, 1.0)
        db_min = -db_limit
        db_max = db_limit

        cr.save()
        cr.set_line_width(1.0)

        for frequency in AUTOEQ_PREVIEW_FREQ_TICKS:
            x = self.autoeq_preview_frequency_x(frequency, left, plot_width)
            major = frequency in AUTOEQ_PREVIEW_MAJOR_FREQ_TICKS
            cr.set_source_rgba(*(palette["grid_major"] if major else palette["grid"]))
            cr.move_to(x, top)
            cr.line_to(x, top + plot_height)
            cr.stroke()

        tick_start = math.ceil(db_min / AUTOEQ_PREVIEW_DB_TICK_STEP) * AUTOEQ_PREVIEW_DB_TICK_STEP
        tick = tick_start
        while tick <= db_max + 0.01:
            y = self.autoeq_preview_db_y(tick, top, plot_height, db_min, db_max)
            cr.set_source_rgba(*(palette["axis"] if abs(tick) < 0.01 else palette["grid_major"]))
            cr.move_to(left, y)
            cr.line_to(width - right, y)
            cr.stroke()
            tick += AUTOEQ_PREVIEW_DB_TICK_STEP

        self.draw_autoeq_preview_axis_labels(
            cr, width, height, left, right, top, plot_width, plot_height, db_limit, palette
        )
        cr.restore()
        return left, right, top, bottom

    def draw_autoeq_preview_axis_labels(
        self,
        cr,
        width: float,
        height: float,
        left: float,
        right: float,
        top: float,
        plot_width: float,
        plot_height: float,
        db_limit: float,
        palette: dict[str, tuple[float, float, float, float]],
    ) -> None:
        cr.select_font_face("Cantarell")
        cr.set_font_size(9.0)
        cr.set_source_rgba(*palette["label"])
        db_min = -db_limit
        db_max = db_limit

        for tick in (-db_limit, 0.0, db_limit):
            label = "0" if abs(tick) < 0.01 else f"{tick:+.0f}"
            extents = cr.text_extents(label)
            y = self.autoeq_preview_db_y(tick, top, plot_height, db_min, db_max)
            cr.move_to(max(4.0, left - extents.width - 6.0), y + (extents.height * 0.5))
            cr.show_text(label)

        label_y = height - 7.0
        for frequency, label in AUTOEQ_PREVIEW_FREQ_LABELS.items():
            extents = cr.text_extents(label)
            x = self.autoeq_preview_frequency_x(frequency, left, plot_width) - (extents.width * 0.5)
            x = max(left, min(width - right - extents.width, x))
            cr.move_to(x, label_y)
            cr.show_text(label)

    def autoeq_preview_frequency_x(self, frequency: float, left: float, plot_width: float) -> float:
        log_min = math.log10(GRAPH_FREQ_MIN)
        log_max = math.log10(GRAPH_FREQ_MAX)
        log_position = (math.log10(float(frequency)) - log_min) / (log_max - log_min)
        return left + (plot_width * max(0.0, min(1.0, log_position)))

    def autoeq_preview_db_y(
        self,
        db_value: float,
        top: float,
        plot_height: float,
        db_min: float,
        db_max: float,
    ) -> float:
        y_norm = (db_max - float(db_value)) / (db_max - db_min)
        return top + (plot_height * max(0.0, min(1.0, y_norm)))

    def draw_autoeq_preview_message(
        self,
        cr,
        width: float,
        height: float,
        text: str,
        color: tuple[float, float, float, float],
    ) -> None:
        cr.select_font_face("Cantarell")
        cr.set_font_size(12.0)
        cr.set_source_rgba(*color)
        extents = cr.text_extents(text)
        cr.move_to(
            (width - extents.width) * 0.5 - extents.x_bearing, (height - extents.height) * 0.5 - extents.y_bearing
        )
        cr.show_text(text)

    def rounded_rectangle(self, cr, x: float, y: float, width: float, height: float, radius: float) -> None:
        right = x + width
        bottom = y + height
        cr.new_sub_path()
        cr.arc(right - radius, y + radius, radius, -math.pi * 0.5, 0.0)
        cr.arc(right - radius, bottom - radius, radius, 0.0, math.pi * 0.5)
        cr.arc(x + radius, bottom - radius, radius, math.pi * 0.5, math.pi)
        cr.arc(x + radius, y + radius, radius, math.pi, math.pi * 1.5)
        cr.close_path()


def initialize_autoeq_window_state(window: Any) -> None:
    window.autoeq_entries: list[AutoEqEntry] = []
    window.autoeq_dialog = None
    window.autoeq_search_entry = None
    window.autoeq_refresh_button = None
    window.autoeq_spinner = None
    window.autoeq_status_label = None
    window.autoeq_results_list = None
    window.autoeq_import_button = None
    window.autoeq_cancel_button = None
    window.autoeq_import_in_progress = False
    window.autoeq_dialog_closed = False
    window.autoeq_selected_entry: AutoEqEntry | None = None
    window.autoeq_preview_path: Path | None = None
    window.autoeq_preview_preamp_db: float | None = None
    window.autoeq_preview_target_label: str | None = None
    window.autoeq_preview_bands: list[EqBand] = []
    window.autoeq_preview_error: str | None = None
    window.autoeq_preview_loading = False
    window.autoeq_profiles_request_id = 0
    window.autoeq_import_request_id = 0
    window.autoeq_preview_source_id = 0
    window.autoeq_preview_request_id = 0
    window.autoeq_preview_title = None
    window.autoeq_preview_count_label = None
    window.autoeq_preview_area = None
    window.autoeq_preview_detail = None
