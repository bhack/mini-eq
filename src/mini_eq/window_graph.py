from __future__ import annotations

import math

import cairo
import gi

gi.require_version("Gtk", "4.0")

from gi.repository import GLib, Gtk

from .analyzer import analyzer_db_to_display_norm, analyzer_level_to_display_norm
from .core import (
    FILTER_TYPE_INDEX_BY_VALUE,
    FILTER_TYPE_ORDER,
    FILTER_TYPES,
    GRAPH_DB_MAX,
    GRAPH_DB_MIN,
    GRAPH_FREQ_MAX,
    GRAPH_FREQ_MIN,
    MAX_BANDS,
    MODE_INDEX_BY_VALUE,
    SAMPLE_RATE,
    band_is_effective,
    bands_have_solo,
    clamp,
    format_frequency,
    total_response_db,
    total_response_db_at_frequencies,
)

ENGINE_CONTROL_REFRESH_INTERVAL_MS = 16
FOCUS_BLUE = (0.47, 0.72, 1.0)
FOCUS_BLUE_LIGHT = (0.68, 0.84, 1.0)
RESPONSE_AMBER = (0.84, 0.46, 0.12)


def filter_type_label(filter_type: int) -> str:
    return FILTER_TYPE_ORDER[FILTER_TYPE_INDEX_BY_VALUE.get(filter_type, 0)]


class MiniEqWindowGraphMixin:
    def queue_graph_draw(self) -> None:
        self.graph_area.queue_draw()
        if hasattr(self, "graph_response_area"):
            self.graph_response_area.queue_draw()

    def queue_response_draw(self) -> None:
        if not hasattr(self, "graph_response_area"):
            self.queue_graph_draw()
            return

        self.graph_response_area.queue_draw()

    def invalidate_graph_background_cache(self) -> None:
        self.graph_background_revision = getattr(self, "graph_background_revision", 0) + 1
        self.graph_background_surface_key = None

    def invalidate_graph_response_cache(self) -> None:
        self.graph_response_revision = getattr(self, "graph_response_revision", 0) + 1
        self.graph_response_surface_key = None

    def active_band_indexes(self) -> list[int]:
        return [index for index, band in enumerate(self.controller.bands) if band.filter_type != FILTER_TYPES["Off"]]

    def visible_band_limit(self) -> int:
        return self.visible_band_count

    def set_visible_band_count(self, count: int) -> None:
        self.visible_band_count = int(clamp(float(count), 1.0, float(MAX_BANDS)))
        if self.selected_band_index >= self.visible_band_count:
            self.selected_band_index = self.visible_band_count - 1

    def select_band(self, index: int) -> None:
        self.selected_band_index = max(0, min(MAX_BANDS - 1, index))
        if self.selected_band_index >= self.visible_band_count:
            self.set_visible_band_count(self.selected_band_index + 1)
        self.sync_ui_from_state()

    def update_quick_fader_strip(self) -> None:
        solo_active = bands_have_solo(self.controller.bands)
        for index in range(len(self.band_fader_widgets)):
            self.update_band_fader(index, solo_active)

        self.fader_title_label.set_text(f"{self.visible_band_count} Bands")

    def update_band_fader(self, index: int, solo_active: bool | None = None) -> None:
        if index < 0 or index >= len(self.band_fader_widgets):
            return

        if solo_active is None:
            solo_active = bands_have_solo(self.controller.bands)

        band = self.controller.bands[index]
        visible = index < self.visible_band_count
        box = self.band_fader_boxes[index]
        box.set_visible(visible)
        fader = self.band_fader_widgets[index]
        fader.set_visible(visible)
        fader.set_band_state(
            gain_db=band.gain_db,
            frequency=band.frequency,
            frequency_label=format_frequency(band.frequency),
            q_value=band.q,
            q_label=f"{band.q:.2f}",
            filter_type=band.filter_type,
            filter_type_label=filter_type_label(band.filter_type),
            selected=index == self.selected_band_index,
            active=band.filter_type != FILTER_TYPES["Off"],
            muted=band.mute,
            soloed=band.solo,
            solo_active=solo_active,
        )

        box.remove_css_class("eq-band-box-selected")
        box.remove_css_class("eq-band-box-muted")
        if index == self.selected_band_index:
            box.set_opacity(1.0)
            box.add_css_class("eq-band-box-selected")
        else:
            effective = band_is_effective(band, solo_active)
            box.set_opacity(0.98 if effective else 0.62)
            if not effective:
                box.add_css_class("eq-band-box-muted")

    def schedule_curve_metadata_refresh(self) -> None:
        if getattr(self, "curve_metadata_refresh_source_id", 0) != 0:
            return

        self.curve_metadata_refresh_source_id = GLib.idle_add(self.on_curve_metadata_refresh_idle)

    def on_curve_metadata_refresh_idle(self) -> bool:
        self.curve_metadata_refresh_source_id = 0
        if getattr(self, "ui_shutting_down", False):
            return False

        self.update_status_summary()
        self.update_preset_state()
        return False

    def schedule_band_engine_update(self, index: int) -> None:
        self.pending_engine_band_indexes.add(index)
        if getattr(self, "engine_control_refresh_source_id", 0) != 0:
            return

        self.engine_control_refresh_source_id = GLib.timeout_add(
            ENGINE_CONTROL_REFRESH_INTERVAL_MS,
            self.on_engine_control_refresh_timeout,
        )

    def on_engine_control_refresh_timeout(self) -> bool:
        self.engine_control_refresh_source_id = 0
        if getattr(self, "ui_shutting_down", False):
            self.pending_engine_band_indexes.clear()
            return False

        pending_indexes = sorted(self.pending_engine_band_indexes)
        self.pending_engine_band_indexes.clear()
        for index in pending_indexes:
            self.controller.apply_band_to_engine(index)
        return False

    def update_focus_summary(self) -> None:
        selected = self.controller.bands[self.selected_band_index]
        selected_filter_type = filter_type_label(selected.filter_type)
        route_enabled = self.route_switch.get_active()
        if route_enabled:
            self.focus_label.set_text(
                f"Band {self.selected_band_index + 1} • {format_frequency(selected.frequency)} • {selected.gain_db:+.1f} dB"
            )
            self.band_count_label.set_text(selected_filter_type)
            self.band_count_label.set_visible(True)
        else:
            self.focus_label.set_text("Shape the curve, then enable Audio Routing to hear it system-wide")
            self.band_count_label.set_visible(False)
        self.inspector_summary_label.set_text(
            f"{selected_filter_type} • {format_frequency(selected.frequency)} • {selected.gain_db:+.1f} dB"
        )

    def update_selected_band_editor(self) -> None:
        selected = self.controller.bands[self.selected_band_index]
        band_title = f"Band {self.selected_band_index + 1}"
        self.selected_band_label.set_text(band_title)
        filter_type = filter_type_label(selected.filter_type)
        full_summary = f"{band_title} • {filter_type} • {selected.frequency:.1f} Hz • Q {selected.q:.3f} • {selected.gain_db:+.1f} dB"
        self.selected_band_label.set_tooltip_text(full_summary)
        self.selected_band_type_combo.set_selected(FILTER_TYPE_INDEX_BY_VALUE.get(selected.filter_type, 0))
        self.selected_band_frequency_spin.set_value(selected.frequency)
        self.selected_band_q_spin.set_value(selected.q)
        self.selected_band_gain_spin.set_value(selected.gain_db)
        self.selected_band_mute_button.set_active(selected.mute)
        self.selected_band_solo_button.set_active(selected.solo)

    def update_eq_power_indicator(self) -> None:
        self.bypass_state_label.remove_css_class("toolbar-inline-state-live")
        self.bypass_state_label.remove_css_class("toolbar-inline-state-bypass")

        if self.controller.eq_enabled:
            self.bypass_state_label.add_css_class("toolbar-inline-state-live")
            self.bypass_state_label.set_tooltip_text("EQ Is Processing")
            self.bypass_state_label.set_text("Live")
        else:
            self.bypass_state_label.add_css_class("toolbar-inline-state-bypass")
            self.bypass_state_label.set_tooltip_text("EQ Is Bypassed")
            self.bypass_state_label.set_text("Bypassed")

    def sync_ui_from_state(self) -> None:
        self.updating_ui = True

        try:
            self.bypass_switch.set_active(not self.controller.eq_enabled)
            self.update_eq_power_indicator()
            self.analyzer_switch.set_active(self.analyzer_enabled)
            self.analyzer_freeze_switch.set_active(self.analyzer_frozen)
            self.analyzer_state_label.set_text(
                "Frozen"
                if self.analyzer_frozen and self.analyzer_enabled
                else ("Live" if self.analyzer_enabled else "Off")
            )
            self.analyzer_smoothing_label.set_text(f"{int(round(self.analyzer_smoothing * 100.0))}%")
            self.analyzer_display_gain_label.set_text(f"{self.analyzer_display_gain_db:+.0f} dB")
            self.update_analyzer_summary_label()
            self.preamp_scale.set_value(self.controller.preamp_db)
            self.preamp_label.set_text(f"{self.controller.preamp_db:.1f} dB")
            self.mode_combo.set_selected(MODE_INDEX_BY_VALUE[self.controller.eq_mode])
            self.graph_title_label.set_text("Active Curve" if self.route_switch.get_active() else "Preview Curve")
            self.analyzer_mode_combo.set_selected(0)
            self.analyzer_smoothing_scale.set_value(self.analyzer_smoothing * 100.0)
            self.analyzer_display_gain_scale.set_value(self.analyzer_display_gain_db)

            self.update_quick_fader_strip()
            self.update_focus_summary()
            self.update_selected_band_editor()
        finally:
            self.updating_ui = False

        self.invalidate_graph_background_cache()
        self.invalidate_graph_response_cache()
        self.update_preset_state()
        self.update_info_label()
        self.update_status_summary()
        self.queue_graph_draw()
        self.queue_analyzer_draw(force=True)

    def on_graph_pressed(self, gesture: Gtk.GestureClick, _press_count: int, x: float, _y: float) -> None:
        width = self.graph_area.get_allocated_width()
        if width <= 0:
            return

        plot_left = 58.0
        plot_right = 52.0
        freq = self.x_to_frequency(x, width, plot_left, plot_right)
        visible_limit = self.visible_band_limit()
        visible_active = [index for index in self.active_band_indexes() if index < visible_limit]
        candidates = visible_active or list(range(visible_limit))
        target = min(
            candidates,
            key=lambda index: abs(math.log10(max(self.controller.bands[index].frequency, 10.0)) - math.log10(freq)),
        )
        self.select_band(target)

    def on_preamp_changed(self, scale: Gtk.Scale) -> None:
        value = scale.get_value()
        self.preamp_label.set_text(f"{value:.1f} dB")

        if self.updating_ui:
            return

        self.controller.set_preamp_db(value)
        self.update_status_summary()
        self.invalidate_graph_response_cache()
        self.queue_response_draw()

    def on_band_card_pressed(
        self, gesture: Gtk.GestureClick, _press_count: int, _x: float, _y: float, index: int
    ) -> None:
        if self.updating_ui:
            return

        if self.selected_band_index != index:
            self.select_band(index)
            return

        return

    def on_custom_band_fader_selected(self, index: int) -> None:
        if self.updating_ui or self.selected_band_index == index:
            return

        self.select_band(index)

    def on_custom_band_fader_activated(self, index: int) -> None:
        if self.updating_ui:
            return

        if self.selected_band_index != index:
            self.select_band(index)
            return

        return

    def on_custom_band_fader_changed(self, index: int, gain_db: float) -> None:
        if self.updating_ui:
            return

        changed = self.controller.set_band_gain(index, gain_db, apply=False)
        if changed:
            self.schedule_band_engine_update(index)
        self.selected_band_index = index
        self.updating_ui = True
        try:
            self.update_band_fader(index)
            self.update_focus_summary()
            self.update_selected_band_editor()
        finally:
            self.updating_ui = False

        self.invalidate_graph_response_cache()
        self.queue_response_draw()
        self.schedule_curve_metadata_refresh()

    def on_custom_band_frequency_changed(self, index: int, frequency: float) -> None:
        if self.updating_ui:
            return

        changed = self.controller.set_band_frequency(index, frequency, apply=False)
        if changed:
            self.schedule_band_engine_update(index)
        self.selected_band_index = index
        self.updating_ui = True
        try:
            self.update_band_fader(index)
            self.update_focus_summary()
            self.update_selected_band_editor()
        finally:
            self.updating_ui = False

        self.invalidate_graph_response_cache()
        self.queue_response_draw()
        self.schedule_curve_metadata_refresh()

    def on_custom_band_q_changed(self, index: int, q_value: float) -> None:
        if self.updating_ui:
            return

        changed = self.controller.set_band_q(index, q_value, apply=False)
        if changed:
            self.schedule_band_engine_update(index)
        self.selected_band_index = index
        self.updating_ui = True
        try:
            self.update_band_fader(index)
            self.update_focus_summary()
            self.update_selected_band_editor()
        finally:
            self.updating_ui = False

        self.invalidate_graph_response_cache()
        self.queue_response_draw()
        self.schedule_curve_metadata_refresh()

    def on_custom_band_mute_toggled(self, index: int, muted: bool) -> None:
        if self.updating_ui:
            return

        self.controller.set_band_mute(index, muted)
        self.selected_band_index = index
        self.updating_ui = True
        try:
            self.update_quick_fader_strip()
            self.update_focus_summary()
            self.update_selected_band_editor()
        finally:
            self.updating_ui = False

        self.update_status_summary()
        self.invalidate_graph_response_cache()
        self.queue_response_draw()
        self.update_preset_state()

    def on_custom_band_solo_toggled(self, index: int, soloed: bool) -> None:
        if self.updating_ui:
            return

        self.controller.set_band_solo(index, soloed)
        self.selected_band_index = index
        self.updating_ui = True
        try:
            self.update_quick_fader_strip()
            self.update_focus_summary()
            self.update_selected_band_editor()
        finally:
            self.updating_ui = False

        self.update_status_summary()
        self.invalidate_graph_response_cache()
        self.queue_response_draw()
        self.update_preset_state()

    def on_band_fader_changed(self, scale: Gtk.Scale, index: int) -> None:
        if self.updating_ui:
            return

        self.controller.set_band_gain(index, scale.get_value())
        self.selected_band_index = index
        self.updating_ui = True
        try:
            self.update_quick_fader_strip()
            self.update_focus_summary()
        finally:
            self.updating_ui = False

        self.update_status_summary()
        self.invalidate_graph_response_cache()
        self.queue_response_draw()

    def on_selected_band_type_changed(self, combo: Gtk.DropDown, _param: object) -> None:
        if self.updating_ui:
            return

        selected = combo.get_selected()
        if selected >= len(FILTER_TYPE_ORDER):
            return

        index = self.selected_band_index
        self.controller.set_band_type(index, FILTER_TYPES[FILTER_TYPE_ORDER[selected]])
        self.updating_ui = True
        try:
            self.update_quick_fader_strip()
            self.update_focus_summary()
            self.update_selected_band_editor()
        finally:
            self.updating_ui = False

        self.update_status_summary()
        self.invalidate_graph_response_cache()
        self.queue_response_draw()
        self.update_preset_state()

    def on_selected_band_frequency_changed(self, spin: Gtk.SpinButton) -> None:
        if self.updating_ui:
            return

        self.on_custom_band_frequency_changed(self.selected_band_index, spin.get_value())

    def on_selected_band_q_changed(self, spin: Gtk.SpinButton) -> None:
        if self.updating_ui:
            return

        self.on_custom_band_q_changed(self.selected_band_index, spin.get_value())

    def on_selected_band_gain_changed(self, spin: Gtk.SpinButton) -> None:
        if self.updating_ui:
            return

        self.on_custom_band_fader_changed(self.selected_band_index, spin.get_value())

    def on_selected_band_mute_changed(self, button: Gtk.ToggleButton, _param: object) -> None:
        if self.updating_ui:
            return

        self.on_custom_band_mute_toggled(self.selected_band_index, button.get_active())

    def on_selected_band_solo_changed(self, button: Gtk.ToggleButton, _param: object) -> None:
        if self.updating_ui:
            return

        self.on_custom_band_solo_toggled(self.selected_band_index, button.get_active())

    def frequency_to_x(self, frequency: float, width: float, left: float, right: float) -> float:
        usable = max(width - left - right, 1.0)
        position = (math.log10(clamp(frequency, GRAPH_FREQ_MIN, GRAPH_FREQ_MAX)) - math.log10(GRAPH_FREQ_MIN)) / (
            math.log10(GRAPH_FREQ_MAX) - math.log10(GRAPH_FREQ_MIN)
        )
        return left + (usable * position)

    def x_to_frequency(self, x: float, width: float, left: float, right: float) -> float:
        usable = max(width - left - right, 1.0)
        normalized = clamp((x - left) / usable, 0.0, 1.0)
        log_freq = math.log10(GRAPH_FREQ_MIN) + normalized * (math.log10(GRAPH_FREQ_MAX) - math.log10(GRAPH_FREQ_MIN))
        return math.pow(10.0, log_freq)

    def db_to_y(self, db_value: float, height: float, top: float, bottom: float) -> float:
        usable = max(height - top - bottom, 1.0)
        normalized = (clamp(db_value, GRAPH_DB_MIN, GRAPH_DB_MAX) - GRAPH_DB_MIN) / (GRAPH_DB_MAX - GRAPH_DB_MIN)
        return (height - bottom) - (usable * normalized)

    def analyzer_level_to_y(self, level: float, height: float, top: float, bottom: float) -> float:
        usable = max(height - top - bottom, 1.0)
        normalized = analyzer_level_to_display_norm(level, getattr(self, "analyzer_display_gain_db", 0.0))
        return (height - bottom) - (usable * normalized)

    def analyzer_display_db_to_y(self, display_db: float, height: float, top: float, bottom: float) -> float:
        usable = max(height - top - bottom, 1.0)
        normalized = analyzer_db_to_display_norm(display_db)
        return (height - bottom) - (usable * normalized)

    def graph_layout_key(self, width: float, height: float) -> tuple[int, int]:
        return (int(round(width)), int(round(height)))

    def response_band_key(self, band) -> tuple[int, float, float, float, int, int, bool, bool]:
        return (
            int(band.filter_type),
            round(float(band.frequency), 4),
            round(float(band.gain_db), 4),
            round(float(band.q), 5),
            int(band.mode),
            int(band.slope),
            bool(band.mute),
            bool(band.solo),
        )

    def total_response_points(
        self,
        width: float,
        height: float,
        left: float,
        right: float,
        top: float,
        bottom: float,
    ) -> list[tuple[float, float]]:
        cache_key = (
            self.graph_layout_key(width, height),
            round(float(self.controller.preamp_db), 4),
            tuple(self.response_band_key(band) for band in self.controller.bands),
        )

        if getattr(self, "graph_response_cache_key", None) == cache_key:
            return self.graph_response_cache_points

        pixels = list(range(int(left), int(width - right)))
        frequencies = [self.x_to_frequency(float(pixel), width, left, right) for pixel in pixels]
        db_values = total_response_db_at_frequencies(
            self.controller.bands,
            self.controller.preamp_db,
            SAMPLE_RATE,
            frequencies,
            clamp_output=True,
        )
        points = [
            (float(pixel), self.db_to_y(float(db_value), height, top, bottom))
            for pixel, db_value in zip(pixels, db_values, strict=True)
        ]

        self.graph_response_cache_key = cache_key
        self.graph_response_cache_points = points
        return points

    def selected_response_points(
        self,
        width: float,
        height: float,
        left: float,
        right: float,
        top: float,
        bottom: float,
        selected_band,
    ) -> list[tuple[float, float]]:
        solo_active = bands_have_solo(self.controller.bands)
        if not band_is_effective(selected_band, solo_active):
            return []

        cache_key = (
            self.graph_layout_key(width, height),
            self.selected_band_index,
            self.response_band_key(selected_band),
        )

        if getattr(self, "graph_selected_response_cache_key", None) == cache_key:
            return self.graph_selected_response_cache_points

        pixels = list(range(int(left), int(width - right)))
        frequencies = [self.x_to_frequency(float(pixel), width, left, right) for pixel in pixels]
        db_values = total_response_db_at_frequencies([selected_band], 0.0, SAMPLE_RATE, frequencies, clamp_output=True)
        points = [
            (float(pixel), self.db_to_y(float(db_value), height, top, bottom))
            for pixel, db_value in zip(pixels, db_values, strict=True)
        ]

        self.graph_selected_response_cache_key = cache_key
        self.graph_selected_response_cache_points = points
        return points

    def draw_text(self, cr, text: str, x: float, y: float, rgb: tuple[float, float, float], size: float) -> None:
        cr.set_source_rgb(*rgb)
        cr.set_font_size(size)
        cr.move_to(x, y)
        cr.show_text(text)

    def graph_plot_bounds(self, width: int, height: int) -> tuple[float, float, float, float, float, float]:
        width_f = float(width)
        height_f = float(height)
        return width_f, height_f, 58.0, 52.0, 26.0, 34.0

    def graph_cached_background_surface(
        self,
        width: int,
        height: int,
        width_f: float,
        height_f: float,
        left: float,
        right: float,
        top: float,
        bottom: float,
    ):
        cache_key = (
            width,
            height,
            getattr(self, "graph_background_revision", 0),
            bool(self.analyzer_enabled),
            round(float(self.analyzer_db_floor), 4),
            round(float(getattr(self, "analyzer_display_gain_db", 0.0)), 4),
        )
        if getattr(self, "graph_background_surface_key", None) == cache_key:
            return self.graph_background_surface

        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, max(width, 1), max(height, 1))
        surface_cr = cairo.Context(surface)
        self.draw_graph_background(surface_cr, width_f, height_f, left, right, top, bottom)
        surface.flush()
        self.graph_background_surface_key = cache_key
        self.graph_background_surface = surface
        return surface

    def draw_graph_background(
        self,
        cr,
        width_f: float,
        height_f: float,
        left: float,
        right: float,
        top: float,
        bottom: float,
    ) -> None:
        plot_width = width_f - left - right
        plot_height = height_f - top - bottom

        cr.set_source_rgb(0.032, 0.046, 0.064)
        cr.rectangle(0, 0, width_f, height_f)
        cr.fill()

        background = cairo.LinearGradient(0, top, 0, height_f - bottom)
        background.add_color_stop_rgba(0.0, 0.10, 0.15, 0.22, 0.98)
        background.add_color_stop_rgba(1.0, 0.05, 0.08, 0.12, 0.98)
        cr.set_source(background)
        cr.rectangle(left, top, plot_width, plot_height)
        cr.fill()

        db_lines = [-24, -18, -12, -6, 0, 6, 12, 18, 24]
        freq_lines = [20, 30, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000]

        for db_value in db_lines:
            y = self.db_to_y(float(db_value), height_f, top, bottom)
            if db_value == 0:
                cr.set_source_rgba(0.72, 0.80, 0.88, 0.24)
                cr.set_line_width(1.6)
            else:
                cr.set_source_rgba(0.45, 0.52, 0.60, 0.18)
                cr.set_line_width(1.0)
            cr.move_to(left, y)
            cr.line_to(width_f - right, y)
            cr.stroke()
            label = "+0 dB" if db_value == 0 else f"{db_value:+d}"
            self.draw_text(cr, label, 10, y + 4, (0.72, 0.76, 0.80), 11.5)

        analyzer_db_lines = [-60, -40, -20, 0]
        for db_value in analyzer_db_lines:
            y = self.analyzer_display_db_to_y(float(db_value), height_f, top, bottom)
            cr.set_source_rgba(0.42, 0.78, 0.92, 0.10 if db_value != 0 else 0.18)
            cr.set_line_width(1.0)
            cr.move_to(left, y)
            cr.line_to(width_f - right, y)
            cr.stroke()
            label = "0 dBFS" if db_value == 0 else str(db_value)
            self.draw_text(cr, label, width_f - right + 8, y + 4, (0.45, 0.78, 0.86), 10.5)

        for freq in freq_lines:
            x = self.frequency_to_x(float(freq), width_f, left, right)
            cr.set_source_rgba(0.45, 0.52, 0.60, 0.16)
            cr.set_line_width(1.0)
            cr.move_to(x, top)
            cr.line_to(x, height_f - bottom)
            cr.stroke()
            label = f"{int(freq / 1000)}k" if freq >= 1000 else str(freq)
            self.draw_text(cr, label, x - 10, height_f - 10, (0.72, 0.76, 0.80), 11.5)

        cr.set_source_rgba(0.85, 0.90, 0.96, 0.10)
        cr.set_line_width(1.0)
        cr.rectangle(left, top, plot_width, plot_height)
        cr.stroke()

        self.draw_text(cr, "20 Hz", left, 18, (0.82, 0.85, 0.89), 11.5)
        self.draw_text(cr, "20 kHz", width_f - 58, 18, (0.82, 0.85, 0.89), 11.5)
        if self.analyzer_enabled:
            self.draw_text(cr, "Monitor", left + 10, top + 18, (0.50, 0.86, 0.98), 12.5)

    def graph_cached_response_surface(
        self,
        width: int,
        height: int,
        width_f: float,
        height_f: float,
        left: float,
        right: float,
        top: float,
        bottom: float,
    ):
        cache_key = (
            self.graph_layout_key(width_f, height_f),
            getattr(self, "graph_response_revision", 0),
        )
        if getattr(self, "graph_response_surface_key", None) == cache_key:
            return self.graph_response_surface

        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, max(width, 1), max(height, 1))
        surface_cr = cairo.Context(surface)
        self.draw_graph_response_overlay(surface_cr, width_f, height_f, left, right, top, bottom)
        surface.flush()
        self.graph_response_surface_key = cache_key
        self.graph_response_surface = surface
        return surface

    def draw_graph_analyzer(
        self,
        cr,
        width_f: float,
        height_f: float,
        left: float,
        right: float,
        top: float,
        bottom: float,
    ) -> None:
        if not any(level > 0.01 for level in self.analyzer_levels):
            return

        geometry = self.analyzer_bar_geometry(width_f, left, right, len(self.analyzer_levels))
        spectrum_points: list[tuple[float, float]] = []
        base_y = height_f - bottom
        usable_height = max(height_f - top - bottom, 1.0)
        display_gain_db = getattr(self, "analyzer_display_gain_db", 0.0)
        cr.set_source_rgba(0.33, 0.78, 0.90, 0.20 if self.analyzer_enabled else 0.08)
        for level, (x0, bar_width, center_x) in zip(self.analyzer_levels, geometry, strict=False):
            normalized = analyzer_level_to_display_norm(level, display_gain_db)
            y = base_y - (usable_height * normalized)
            cr.rectangle(x0, y, bar_width, max(base_y - y, 1.0))
            if not spectrum_points:
                spectrum_points.append((x0, y))
            spectrum_points.append((center_x, y))
            last_bar_edge = x0 + bar_width
        cr.fill()

        if spectrum_points:
            spectrum_points.append((last_bar_edge, spectrum_points[-1][1]))
            cr.set_source_rgba(0.58, 0.90, 0.98, 0.42 if self.analyzer_enabled else 0.20)
            cr.set_line_width(1.6)
            cr.move_to(spectrum_points[0][0], spectrum_points[0][1])
            for x, y in spectrum_points[1:]:
                cr.line_to(x, y)
            cr.stroke()

    def draw_graph_response_overlay(
        self,
        cr,
        width_f: float,
        height_f: float,
        left: float,
        right: float,
        top: float,
        bottom: float,
    ) -> None:
        selected_band = self.controller.bands[self.selected_band_index]
        selected_x = self.frequency_to_x(selected_band.frequency, width_f, left, right)

        cr.set_source_rgba(0.54, 0.74, 0.96, 0.18)
        cr.set_line_width(1.4)
        cr.move_to(selected_x, top)
        cr.line_to(selected_x, height_f - bottom)
        cr.stroke()

        selected_points = self.selected_response_points(width_f, height_f, left, right, top, bottom, selected_band)
        points = self.total_response_points(width_f, height_f, left, right, top, bottom)

        if points:
            base_y = self.db_to_y(0.0, height_f, top, bottom)
            cr.move_to(points[0][0], base_y)
            for x, y in points:
                cr.line_to(x, y)
            cr.line_to(points[-1][0], base_y)
            cr.close_path()
            gradient = cairo.LinearGradient(0, top, 0, height_f - bottom)
            fill_alpha_top = 0.24 if self.controller.eq_enabled else 0.10
            fill_alpha_bottom = 0.02 if self.controller.eq_enabled else 0.01
            gradient.add_color_stop_rgba(0.0, *RESPONSE_AMBER, fill_alpha_top)
            gradient.add_color_stop_rgba(1.0, *RESPONSE_AMBER, fill_alpha_bottom)
            cr.set_source(gradient)
            cr.fill()

            if selected_points:
                cr.set_source_rgba(0.50, 0.80, 0.98, 0.28 if self.controller.eq_enabled else 0.12)
                cr.set_line_width(1.4)
                cr.move_to(selected_points[0][0], selected_points[0][1])
                for x, y in selected_points[1:]:
                    cr.line_to(x, y)
                cr.stroke()

            cr.set_source_rgba(*RESPONSE_AMBER, 0.12 if self.controller.eq_enabled else 0.06)
            cr.set_line_width(6.0)
            cr.new_path()
            cr.move_to(points[0][0], points[0][1])
            for x, y in points[1:]:
                cr.line_to(x, y)
            cr.stroke()

            if self.controller.eq_enabled:
                cr.set_source_rgb(*RESPONSE_AMBER)
            else:
                cr.set_source_rgb(0.58, 0.64, 0.72)
            cr.set_line_width(2.6)
            cr.new_path()
            cr.move_to(points[0][0], points[0][1])
            for x, y in points[1:]:
                cr.line_to(x, y)
            cr.stroke()

        active = self.active_band_indexes()
        solo_active = bands_have_solo(self.controller.bands)

        for index in active:
            band = self.controller.bands[index]
            x = self.frequency_to_x(band.frequency, width_f, left, right)
            y = self.db_to_y(
                total_response_db(self.controller.bands, self.controller.preamp_db, SAMPLE_RATE, band.frequency),
                height_f,
                top,
                bottom,
            )
            selected = index == self.selected_band_index
            effective = band_is_effective(band, solo_active)
            if selected:
                cr.set_source_rgb(*FOCUS_BLUE_LIGHT)
            elif effective:
                cr.set_source_rgb(0.78, 0.85, 0.93)
            else:
                cr.set_source_rgb(0.44, 0.50, 0.57)
            cr.arc(x, y, 5.8 if selected else (4.2 if effective else 3.6), 0.0, math.tau)
            cr.fill()

            if selected:
                cr.set_source_rgba(*FOCUS_BLUE, 0.24)
                cr.arc(x, y, 12.0, 0.0, math.tau)
                cr.fill()

        if not self.controller.eq_enabled:
            self.draw_text(cr, "Bypassed", width_f - 104, top + 18, (0.96, 0.77, 0.44), 12.0)

    def on_graph_draw(self, area: Gtk.DrawingArea, cr, width: int, height: int) -> None:
        if width <= 0 or height <= 0:
            return

        width_f, height_f, left, right, top, bottom = self.graph_plot_bounds(width, height)

        background_surface = self.graph_cached_background_surface(
            width, height, width_f, height_f, left, right, top, bottom
        )
        cr.set_source_surface(background_surface, 0, 0)
        cr.paint()

    def on_analyzer_draw(self, area: Gtk.DrawingArea, cr, width: int, height: int) -> None:
        if width <= 0 or height <= 0:
            return

        width_f, height_f, left, right, top, bottom = self.graph_plot_bounds(width, height)
        pending = getattr(self, "analyzer_pending_pixel_heights", ())
        self.analyzer_drawn_pixel_heights = pending or self.current_analyzer_pixel_heights()
        self.analyzer_pending_pixel_heights = ()
        self.draw_graph_analyzer(cr, width_f, height_f, left, right, top, bottom)

    def on_graph_response_draw(self, area: Gtk.DrawingArea, cr, width: int, height: int) -> None:
        if width <= 0 or height <= 0:
            return

        width_f, height_f, left, right, top, bottom = self.graph_plot_bounds(width, height)

        response_surface = self.graph_cached_response_surface(
            width, height, width_f, height_f, left, right, top, bottom
        )
        cr.set_source_surface(response_surface, 0, 0)
        cr.paint()
