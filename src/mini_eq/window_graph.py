from __future__ import annotations

import math

import cairo
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")

from gi.repository import Gdk, GLib, Gtk

from .analyzer import analyzer_db_to_display_norm
from .appearance import style_manager_is_dark
from .core import (
    DEFAULT_BAND_Q,
    EQ_Q_MAX,
    EQ_Q_MIN,
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
    EqBand,
    band_is_effective,
    bands_have_solo,
    clamp,
    format_frequency,
    total_response_db,
    total_response_db_at_frequencies,
)
from .window_utils import set_switch_confirmed_state

ENGINE_CONTROL_REFRESH_INTERVAL_MS = 16
FOCUS_BLUE = (0.47, 0.72, 1.0)
FOCUS_BLUE_LIGHT = (0.68, 0.84, 1.0)
RESPONSE_AMBER = (0.84, 0.46, 0.12)
GRAPH_PLOT_LEFT = 58.0
GRAPH_PLOT_RIGHT = 62.0
GRAPH_PLOT_TOP = 26.0
GRAPH_PLOT_BOTTOM = 34.0
SELECTED_BAND_PLACEHOLDER_FREQUENCY_HZ = 1000.0
GRAPH_DRAG_START_THRESHOLD_PX = 2.0
GRAPH_POINT_HIT_RADIUS_PX = 32.0


def rounded_rectangle_path(cr, x: float, y: float, width: float, height: float, radius: float) -> None:
    radius = min(radius, width / 2.0, height / 2.0)
    cr.new_sub_path()
    cr.arc(x + width - radius, y + radius, radius, -math.pi / 2.0, 0.0)
    cr.arc(x + width - radius, y + height - radius, radius, 0.0, math.pi / 2.0)
    cr.arc(x + radius, y + height - radius, radius, math.pi / 2.0, math.pi)
    cr.arc(x + radius, y + radius, radius, math.pi, math.pi * 1.5)
    cr.close_path()


def filter_type_label(filter_type: int) -> str:
    return FILTER_TYPE_ORDER[FILTER_TYPE_INDEX_BY_VALUE.get(filter_type, 0)]


class MiniEqWindowGraphMixin:
    def is_system_routed(self) -> bool:
        controller = getattr(self, "controller", None)
        routed = getattr(controller, "routed", None)
        if routed is not None:
            return bool(routed)

        route_switch = getattr(self, "route_switch", None)
        return bool(route_switch is not None and route_switch.get_active())

    def is_dark_appearance(self) -> bool:
        application = self.get_application()
        style_manager = application.get_style_manager() if application is not None else None
        return style_manager_is_dark(style_manager)

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
        if self.selected_band_index is not None and self.selected_band_index >= self.visible_band_count:
            self.selected_band_index = None

    def select_band(self, index: int) -> None:
        self.selected_band_index = max(0, min(MAX_BANDS - 1, index))
        if self.selected_band_index >= self.visible_band_count:
            self.set_visible_band_count(self.selected_band_index + 1)
        self.sync_ui_from_state()

    def selected_band(self):
        index = self.selected_band_index
        if index is None or index < 0 or index >= len(self.controller.bands):
            return None
        return index, self.controller.bands[index]

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
        if not getattr(self, "ui_shutting_down", False):
            self.update_preset_state()

        if getattr(self, "curve_metadata_refresh_source_id", 0) != 0:
            return

        self.curve_metadata_refresh_source_id = GLib.idle_add(self.on_curve_metadata_refresh_idle)

    def on_curve_metadata_refresh_idle(self) -> bool:
        self.curve_metadata_refresh_source_id = 0
        if getattr(self, "ui_shutting_down", False):
            return False

        self.update_status_summary()
        self.update_preset_state()
        notify_control_state_changed = getattr(self, "notify_control_state_changed", None)
        if callable(notify_control_state_changed):
            notify_control_state_changed()
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
        selected_entry = self.selected_band()
        if selected_entry is None:
            self.focus_label.set_text("No band selected")
            self.band_count_label.set_text("")
            self.band_count_label.set_visible(False)
            self.focus_label.set_tooltip_text("No band selected")
            self.band_count_label.set_tooltip_text("")
            self.inspector_summary_label.set_text("No Band")
            return

        selected_index, selected = selected_entry
        selected_filter_type = filter_type_label(selected.filter_type)
        self.focus_label.set_text(
            f"Band {selected_index + 1} • {format_frequency(selected.frequency)} • {selected.gain_db:+.1f} dB"
        )
        self.band_count_label.set_text(selected_filter_type)
        self.band_count_label.set_visible(True)
        tooltip = f"{selected_filter_type} band at {format_frequency(selected.frequency)}, {selected.gain_db:+.1f} dB"
        if not self.is_system_routed():
            tooltip = f"{tooltip}. System-wide EQ is off."
        self.focus_label.set_tooltip_text(tooltip)
        self.band_count_label.set_tooltip_text(tooltip)
        self.inspector_summary_label.set_text(
            f"{selected_filter_type} • {format_frequency(selected.frequency)} • {selected.gain_db:+.1f} dB"
        )

    def update_selected_band_editor(self) -> None:
        selected_entry = self.selected_band()
        editor_groups = (
            "selected_band_state_box",
            "selected_band_type_box",
            "selected_band_frequency_box",
            "selected_band_q_box",
            "selected_band_gain_box",
        )
        editor_controls = (
            self.selected_band_type_combo,
            self.selected_band_frequency_spin,
            self.selected_band_q_spin,
            self.selected_band_gain_spin,
            self.selected_band_mute_button,
            self.selected_band_solo_button,
        )
        if selected_entry is None:
            self.selected_band_label.set_text("No Band")
            self.selected_band_label.set_tooltip_text("No band selected")
            self.selected_band_type_combo.set_selected(FILTER_TYPE_INDEX_BY_VALUE.get(FILTER_TYPES["Off"], 0))
            self.selected_band_frequency_spin.set_value(SELECTED_BAND_PLACEHOLDER_FREQUENCY_HZ)
            self.selected_band_q_spin.set_value(DEFAULT_BAND_Q)
            self.selected_band_gain_spin.set_value(0.0)
            self.selected_band_mute_button.set_active(False)
            self.selected_band_solo_button.set_active(False)
            for control in editor_controls:
                control.set_sensitive(False)
            for group_name in editor_groups:
                group = getattr(self, group_name, None)
                if group is not None:
                    group.set_visible(True)
            return

        selected_index, selected = selected_entry
        for control in editor_controls:
            control.set_sensitive(True)
        for group_name in editor_groups:
            group = getattr(self, group_name, None)
            if group is not None:
                group.set_visible(True)

        band_title = f"Band {selected_index + 1}"
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
        route_enabled = self.is_system_routed()
        self.bypass_switch.set_sensitive(route_enabled)

        if not route_enabled:
            self.bypass_switch.set_tooltip_text("Turn on System-wide EQ to compare")
            return

        if self.controller.eq_enabled:
            self.bypass_switch.set_tooltip_text("A/B Compare: equalized audio is playing")
        else:
            self.bypass_switch.set_tooltip_text("A/B Compare: original audio is playing")

    def sync_ui_from_state(self) -> None:
        self.updating_ui = True

        try:
            set_switch_confirmed_state(self.route_switch, self.controller.routed)
            set_switch_confirmed_state(self.bypass_switch, self.controller.eq_enabled)
            self.update_eq_power_indicator()
            self._sync_monitor_controls_unlocked()
            self.analyzer_smoothing_label.set_text(f"{int(round(self.analyzer_smoothing * 100.0))}%")
            self.analyzer_display_gain_label.set_text(f"{self.analyzer_display_gain_db:+.0f} dB")
            self.preamp_scale.set_value(self.controller.preamp_db)
            self.preamp_label.set_text(f"{self.controller.preamp_db:.1f} dB")
            self.mode_combo.set_selected(MODE_INDEX_BY_VALUE[self.controller.eq_mode])
            self.graph_title_label.set_text("EQ Curve")
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
        height = self.graph_area.get_allocated_height()
        if width <= 0 or height <= 0:
            return

        width_f, height_f, left, right, top, bottom = self.graph_plot_bounds(width, height)
        freq = self.x_to_frequency(x, width_f, left, right)
        visible_limit = self.visible_band_limit()
        visible_active = [index for index in self.active_band_indexes() if index < visible_limit]
        candidates = visible_active or list(range(visible_limit))
        target = min(
            candidates,
            key=lambda index: abs(math.log10(max(self.controller.bands[index].frequency, 10.0)) - math.log10(freq)),
        )
        self.select_band(target)

    def on_graph_drag_begin(self, gesture: Gtk.GestureDrag, start_x: float, start_y: float) -> None:
        self.clear_graph_drag_state()
        width = self.graph_area.get_allocated_width()
        height = self.graph_area.get_allocated_height()
        if width <= 0 or height <= 0:
            return

        width_f, height_f, left, right, top, bottom = self.graph_plot_bounds(width, height)

        visible_limit = self.visible_band_limit()
        active = [index for index in self.active_band_indexes() if index < visible_limit]
        if not active:
            active = list(range(visible_limit))

        best_index = -1
        min_dist = float("inf")
        best_point_x = 0.0
        best_point_y = 0.0

        for index in active:
            band = self.controller.bands[index]
            bx = self.frequency_to_x(band.frequency, width_f, left, right)
            by = self.db_to_y(
                total_response_db(self.controller.bands, self.controller.preamp_db, SAMPLE_RATE, band.frequency),
                height_f,
                top,
                bottom,
            )
            dist = math.sqrt((bx - start_x) ** 2 + (by - start_y) ** 2)
            if dist < min_dist:
                min_dist = dist
                best_index = index
                best_point_x = bx
                best_point_y = by

        if min_dist < GRAPH_POINT_HIT_RADIUS_PX:
            self.drag_band_index = best_index
            self.drag_start_q = self.controller.bands[best_index].q
            self.drag_start_point_x = best_point_x
            self.drag_start_point_y = best_point_y
            self.select_band(best_index)

    def clear_graph_drag_state(self) -> None:
        self.drag_band_index = None
        self.drag_start_q = None
        self.drag_start_point_x = None
        self.drag_start_point_y = None
        self.drag_edit_active = False

    def graph_drag_threshold_passed(
        self,
        offset_x: float,
        offset_y: float,
    ) -> bool:
        return math.hypot(offset_x, offset_y) >= GRAPH_DRAG_START_THRESHOLD_PX

    def on_graph_drag_update(self, gesture: Gtk.GestureDrag, offset_x: float, offset_y: float) -> None:
        drag_index = getattr(self, "drag_band_index", None)
        if drag_index is None:
            return

        width = self.graph_area.get_allocated_width()
        height = self.graph_area.get_allocated_height()
        if width <= 0 or height <= 0:
            return

        width_f, height_f, left, right, top, bottom = self.graph_plot_bounds(width, height)

        success, start_x, start_y = gesture.get_start_point()
        if not success:
            return
        if not getattr(self, "drag_edit_active", False):
            if not self.graph_drag_threshold_passed(offset_x, offset_y):
                return
            self.drag_edit_active = True

        state = gesture.get_current_event_state()
        is_shift = (state & Gdk.ModifierType.SHIFT_MASK) != 0

        bands = self.controller.bands
        band = bands[drag_index]

        changed_f = False
        changed_g = False
        changed_q = False

        if is_shift:
            # Shift + Vertical -> Q adjustment (isolated)
            start_q = getattr(self, "drag_start_q", band.q)
            new_q = clamp(start_q - (offset_y * 0.005), EQ_Q_MIN, EQ_Q_MAX)
            changed_q = self.controller.set_band_q(drag_index, new_q, apply=False)
        else:
            # No shift -> Frequency and Gain adjustment
            drag_start_point_x = getattr(self, "drag_start_point_x", None)
            curr_x = (drag_start_point_x if drag_start_point_x is not None else start_x) + offset_x
            freq = self.x_to_frequency(curr_x, width_f, left, right)
            changed_f = self.controller.set_band_frequency(drag_index, freq, apply=False)

            # Gain adjustment (only for gain-capable filters)
            if band.filter_type in {FILTER_TYPES["Bell"], FILTER_TYPES["Hi-shelf"], FILTER_TYPES["Lo-shelf"]}:
                drag_start_point_y = getattr(self, "drag_start_point_y", None)
                curr_y = (drag_start_point_y if drag_start_point_y is not None else start_y) + offset_y
                target_db = self.y_to_db(curr_y, height_f, top, bottom)

                # To make the point stay under the mouse on the combined curve, we calculate
                # the gain needed for this band by subtracting the contribution of all other bands.
                # We preserve the full band list to maintain solo context during calculations.
                temp_bands = [
                    EqBand(
                        filter_type=FILTER_TYPES["Off"] if i == drag_index else b.filter_type,
                        frequency=b.frequency,
                        gain_db=b.gain_db,
                        q=b.q,
                        mode=b.mode,
                        slope=b.slope,
                        mute=b.mute,
                        solo=b.solo,
                    )
                    for i, b in enumerate(bands)
                ]
                db_others = total_response_db(temp_bands, self.controller.preamp_db, SAMPLE_RATE, freq)

                # Required gain for this band at the current mouse frequency
                new_gain = target_db - db_others

                # Adjustment for shelf filters: at center frequency, a shelf provides half its gain in dB.
                if band.filter_type in {FILTER_TYPES["Lo-shelf"], FILTER_TYPES["Hi-shelf"]}:
                    new_gain *= 2.0

                changed_g = self.controller.set_band_gain(drag_index, new_gain, apply=False)

        if changed_f or changed_g or changed_q:
            self.schedule_band_engine_update(drag_index)
            self.selected_band_index = drag_index
            self.updating_ui = True
            try:
                self.update_band_fader(drag_index)
                self.update_focus_summary()
                self.update_selected_band_editor()
            finally:
                self.updating_ui = False

            self.invalidate_graph_response_cache()
            self.queue_response_draw()
            self.schedule_curve_metadata_refresh()

    def on_graph_drag_end(self, _gesture: Gtk.GestureDrag, _offset_x: float, _offset_y: float) -> None:
        self.clear_graph_drag_state()

    def on_preamp_changed(self, scale: Gtk.Scale) -> None:
        value = scale.get_value()
        self.preamp_label.set_text(f"{value:.1f} dB")

        if self.updating_ui:
            return

        self.controller.set_preamp_db(value)
        self.invalidate_graph_response_cache()
        self.queue_response_draw()
        self.schedule_curve_metadata_refresh()

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
        self.schedule_curve_metadata_refresh()

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
        self.schedule_curve_metadata_refresh()

    def on_selected_band_type_changed(self, combo: Gtk.DropDown, _param: object) -> None:
        if self.updating_ui:
            return

        selected = combo.get_selected()
        if selected >= len(FILTER_TYPE_ORDER):
            return

        index = self.selected_band_index
        if index is None:
            return
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
        self.schedule_curve_metadata_refresh()

    def on_selected_band_frequency_changed(self, spin: Gtk.SpinButton) -> None:
        if self.updating_ui:
            return

        if self.selected_band_index is None:
            return

        self.on_custom_band_frequency_changed(self.selected_band_index, spin.get_value())

    def on_selected_band_q_changed(self, spin: Gtk.SpinButton) -> None:
        if self.updating_ui:
            return

        if self.selected_band_index is None:
            return

        self.on_custom_band_q_changed(self.selected_band_index, spin.get_value())

    def on_selected_band_gain_changed(self, spin: Gtk.SpinButton) -> None:
        if self.updating_ui:
            return

        if self.selected_band_index is None:
            return

        self.on_custom_band_fader_changed(self.selected_band_index, spin.get_value())

    def on_selected_band_mute_changed(self, button: Gtk.ToggleButton, _param: object) -> None:
        if self.updating_ui:
            return

        if self.selected_band_index is None:
            return

        self.on_custom_band_mute_toggled(self.selected_band_index, button.get_active())

    def on_selected_band_solo_changed(self, button: Gtk.ToggleButton, _param: object) -> None:
        if self.updating_ui:
            return

        if self.selected_band_index is None:
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

    def y_to_db(self, y: float, height: float, top: float, bottom: float) -> float:
        usable = max(height - top - bottom, 1.0)
        normalized = clamp(((height - bottom) - y) / usable, 0.0, 1.0)
        return GRAPH_DB_MIN + normalized * (GRAPH_DB_MAX - GRAPH_DB_MIN)

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
        return width_f, height_f, GRAPH_PLOT_LEFT, GRAPH_PLOT_RIGHT, GRAPH_PLOT_TOP, GRAPH_PLOT_BOTTOM

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
            self.is_dark_appearance(),
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
        dark = self.is_dark_appearance()

        if dark:
            plot_top_color = (0.105, 0.155, 0.225, 0.98)
            plot_bottom_color = (0.045, 0.070, 0.108, 0.98)
            major_grid = (0.72, 0.80, 0.88, 0.28)
            grid = (0.45, 0.52, 0.60, 0.20)
            vertical_grid = (0.45, 0.52, 0.60, 0.18)
            axis_label = (0.72, 0.76, 0.80)
            edge_label = (0.82, 0.85, 0.89)
            border = (0.85, 0.90, 0.96, 0.14)
            analyzer_grid = (0.42, 0.78, 0.92)
            analyzer_label = (0.45, 0.78, 0.86)
            monitor_label = (0.50, 0.86, 0.98)
        else:
            plot_top_color = (0.95, 0.97, 0.99, 0.98)
            plot_bottom_color = (0.81, 0.87, 0.93, 0.98)
            major_grid = (0.18, 0.25, 0.32, 0.34)
            grid = (0.20, 0.28, 0.36, 0.20)
            vertical_grid = (0.20, 0.28, 0.36, 0.18)
            axis_label = (0.18, 0.25, 0.32)
            edge_label = (0.12, 0.18, 0.24)
            border = (0.16, 0.23, 0.30, 0.24)
            analyzer_grid = (0.04, 0.42, 0.58)
            analyzer_label = (0.02, 0.34, 0.50)
            monitor_label = (0.02, 0.36, 0.54)

        background = cairo.LinearGradient(0, top, 0, height_f - bottom)
        background.add_color_stop_rgba(0.0, *plot_top_color)
        background.add_color_stop_rgba(1.0, *plot_bottom_color)
        cr.set_source(background)
        rounded_rectangle_path(cr, left, top, plot_width, plot_height, 7.0)
        cr.fill()

        db_lines = [-24, -18, -12, -6, 0, 6, 12, 18, 24]
        freq_lines = [20, 30, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000]

        for db_value in db_lines:
            y = self.db_to_y(float(db_value), height_f, top, bottom)
            if db_value == 0:
                cr.set_source_rgba(*major_grid)
                cr.set_line_width(1.6)
            else:
                cr.set_source_rgba(*grid)
                cr.set_line_width(1.0)
            cr.move_to(left, y)
            cr.line_to(width_f - right, y)
            cr.stroke()
            axis_text = "+0 dB" if db_value == 0 else f"{db_value:+d}"
            self.draw_text(cr, axis_text, 10, y + 4, axis_label, 11.5)

        analyzer_db_lines = [-60, -40, -20, 0]
        for db_value in analyzer_db_lines:
            y = self.analyzer_display_db_to_y(float(db_value), height_f, top, bottom)
            cr.set_source_rgba(*analyzer_grid, 0.10 if db_value != 0 else 0.18)
            cr.set_line_width(1.0)
            cr.move_to(left, y)
            cr.line_to(width_f - right, y)
            cr.stroke()
            label = "0 dBFS" if db_value == 0 else str(db_value)
            self.draw_text(cr, label, width_f - right + 8, y + 4, analyzer_label, 10.5)

        for freq in freq_lines:
            x = self.frequency_to_x(float(freq), width_f, left, right)
            cr.set_source_rgba(*vertical_grid)
            cr.set_line_width(1.0)
            cr.move_to(x, top)
            cr.line_to(x, height_f - bottom)
            cr.stroke()
            freq_text = f"{int(freq / 1000)}k" if freq >= 1000 else str(freq)
            self.draw_text(cr, freq_text, x - 10, height_f - 10, axis_label, 11.5)

        cr.set_source_rgba(*border)
        cr.set_line_width(1.0)
        rounded_rectangle_path(cr, left + 0.5, top + 0.5, plot_width - 1.0, plot_height - 1.0, 6.5)
        cr.stroke()

        self.draw_text(cr, "20 Hz", left, 18, edge_label, 11.5)
        self.draw_text(cr, "20 kHz", width_f - 58, 18, edge_label, 11.5)
        if self.analyzer_enabled:
            self.draw_text(cr, "Monitor", left + 10, top + 18, monitor_label, 12.5)

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
            self.is_dark_appearance(),
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
        dark = self.is_dark_appearance()
        selected_line = (0.54, 0.74, 0.96, 0.18) if dark else (0.03, 0.32, 0.60, 0.24)
        selected_response = (0.50, 0.80, 0.98) if dark else (0.02, 0.34, 0.62)
        disabled_response = (0.58, 0.64, 0.72) if dark else (0.34, 0.40, 0.46)
        selected_point = FOCUS_BLUE_LIGHT if dark else (0.02, 0.30, 0.56)
        selected_halo = FOCUS_BLUE if dark else (0.02, 0.36, 0.68)
        effective_point = (0.78, 0.85, 0.93) if dark else (0.18, 0.25, 0.32)
        inactive_point = (0.44, 0.50, 0.57) if dark else (0.50, 0.56, 0.62)
        response_amber = RESPONSE_AMBER if dark else (0.82, 0.34, 0.02)
        selected_entry = self.selected_band()
        selected_points = []
        if selected_entry is not None:
            _, selected_band = selected_entry
            selected_x = self.frequency_to_x(selected_band.frequency, width_f, left, right)

            cr.set_source_rgba(*selected_line)
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
            gradient.add_color_stop_rgba(0.0, *response_amber, fill_alpha_top)
            gradient.add_color_stop_rgba(1.0, *response_amber, fill_alpha_bottom)
            cr.set_source(gradient)
            cr.fill()

            if selected_points:
                cr.set_source_rgba(*selected_response, 0.28 if self.controller.eq_enabled else 0.12)
                cr.set_line_width(1.4)
                cr.move_to(selected_points[0][0], selected_points[0][1])
                for x, y in selected_points[1:]:
                    cr.line_to(x, y)
                cr.stroke()

            cr.set_source_rgba(*response_amber, 0.12 if self.controller.eq_enabled else 0.06)
            cr.set_line_width(6.0)
            cr.new_path()
            cr.move_to(points[0][0], points[0][1])
            for x, y in points[1:]:
                cr.line_to(x, y)
            cr.stroke()

            if self.controller.eq_enabled:
                cr.set_source_rgb(*response_amber)
            else:
                cr.set_source_rgb(*disabled_response)
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
                cr.set_source_rgb(*selected_point)
            elif effective:
                cr.set_source_rgb(*effective_point)
            else:
                cr.set_source_rgb(*inactive_point)
            cr.arc(x, y, 5.8 if selected else (4.2 if effective else 3.6), 0.0, math.tau)
            cr.fill()

            if selected:
                cr.set_source_rgba(*selected_halo, 0.24)
                cr.arc(x, y, 12.0, 0.0, math.tau)
                cr.fill()

    def on_graph_draw(self, _area: Gtk.DrawingArea, cr, width: int, height: int) -> None:
        if width <= 0 or height <= 0:
            return

        width_f, height_f, left, right, top, bottom = self.graph_plot_bounds(width, height)

        background_surface = self.graph_cached_background_surface(
            width, height, width_f, height_f, left, right, top, bottom
        )
        cr.set_source_surface(background_surface, 0, 0)
        cr.paint()

    def on_graph_response_draw(self, _area: Gtk.DrawingArea, cr, width: int, height: int) -> None:
        if width <= 0 or height <= 0:
            return

        width_f, height_f, left, right, top, bottom = self.graph_plot_bounds(width, height)

        response_surface = self.graph_cached_response_surface(
            width, height, width_f, height_f, left, right, top, bottom
        )
        cr.set_source_surface(response_surface, 0, 0)
        cr.paint()
