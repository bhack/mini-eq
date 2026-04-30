from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")

from gi.repository import GLib, Gtk

from .analyzer import (
    ANALYZER_DISPLAY_GAIN_MAX,
    ANALYZER_DISPLAY_GAIN_MIN,
    analyzer_level_to_display_norm,
)
from .core import clamp
from .glib_utils import destroy_glib_source

ANALYZER_REDRAW_INTERVAL_S = 1.0 / 30.0
ANALYZER_PREVIEW_INTERVAL_S = 1.0 / 30.0
ANALYZER_PREVIEW_INTERVAL_MS = 33
ANALYZER_ATTACK_SMOOTHING_MAX = 0.25
ANALYZER_PIXEL_REDRAW_THRESHOLD = 1.0
CONTROL_ANALYZER_EMIT_INTERVAL_SECONDS = 0.10


class MiniEqWindowAnalyzerMixin:
    def start_analyzer_preview(self) -> None:
        if not self.analyzer_enabled:
            return

        if self.analyzer_preview_source_id != 0:
            return

        try:
            started = self.controller.set_analyzer_enabled(True)
        except Exception as exc:
            self.set_status(f"Monitor Unavailable: {exc}")
            started = False

        if not started:
            self.analyzer_enabled = False
            self.updating_ui = True
            try:
                self.analyzer_switch.set_active(False)
            finally:
                self.updating_ui = False
            self.sync_ui_from_state()
            return

        self.start_analyzer_preview_clock()

    def stop_analyzer_preview(self, *, stop_backend: bool = True) -> None:
        if stop_backend:
            self.controller.set_analyzer_enabled(False)

        if self.analyzer_preview_source_id > 0:
            if getattr(self, "analyzer_preview_uses_tick_callback", False):
                remove_tick_callback = getattr(self.analyzer_area, "remove_tick_callback", None)
                if callable(remove_tick_callback):
                    remove_tick_callback(self.analyzer_preview_source_id)
            else:
                destroy_glib_source(self.analyzer_preview_source_id)
            self.analyzer_preview_source_id = 0
            self.analyzer_preview_uses_tick_callback = False

    def start_analyzer_preview_clock(self) -> None:
        add_tick_callback = getattr(self.analyzer_area, "add_tick_callback", None)
        if callable(add_tick_callback):
            self.analyzer_preview_source_id = add_tick_callback(self.on_analyzer_preview_frame)
            self.analyzer_preview_uses_tick_callback = True
            return

        self.analyzer_preview_source_id = GLib.timeout_add(ANALYZER_PREVIEW_INTERVAL_MS, self.on_analyzer_preview_tick)
        self.analyzer_preview_uses_tick_callback = False

    def on_analyzer_preview_frame(self, _widget: Gtk.Widget, frame_clock: object) -> bool:
        get_frame_time = getattr(frame_clock, "get_frame_time", None)
        now = (
            float(get_frame_time()) / 1_000_000.0
            if callable(get_frame_time)
            else GLib.get_monotonic_time() / 1_000_000.0
        )

        if self.ui_shutting_down:
            return self.on_analyzer_preview_tick(now)

        last_tick = getattr(self, "analyzer_preview_last_tick_time", 0.0)
        if now - last_tick < ANALYZER_PREVIEW_INTERVAL_S:
            return True

        self.analyzer_preview_last_tick_time = now
        return self.on_analyzer_preview_tick(now)

    def queue_analyzer_draw(self, *, force: bool = False) -> None:
        if not hasattr(self, "analyzer_area"):
            return

        if not self.analyzer_area_is_drawable():
            return

        now = GLib.get_monotonic_time() / 1_000_000.0
        if not force and now - getattr(self, "analyzer_last_redraw_time", 0.0) < ANALYZER_REDRAW_INTERVAL_S:
            return

        pixel_heights = self.current_analyzer_pixel_heights()
        if not force and not self.analyzer_pixels_changed(pixel_heights):
            return

        self.analyzer_last_redraw_time = now
        self.sync_analyzer_plot_widget()
        self.analyzer_area.queue_draw()

    def sync_analyzer_plot_widget(self) -> None:
        if not hasattr(self, "analyzer_area"):
            return

        set_analyzer_state = getattr(self.analyzer_area, "set_analyzer_state", None)
        if callable(set_analyzer_state):
            set_analyzer_state(
                self.analyzer_levels,
                display_gain_db=getattr(self, "analyzer_display_gain_db", 0.0),
                enabled=getattr(self, "analyzer_enabled", False),
            )

    def analyzer_area_is_drawable(self) -> bool:
        if not hasattr(self, "analyzer_area"):
            return False

        for widget in (self, self.analyzer_area):
            is_drawable = getattr(widget, "is_drawable", None)
            if callable(is_drawable) and not is_drawable():
                return False

            get_mapped = getattr(widget, "get_mapped", None)
            if callable(get_mapped) and not get_mapped():
                return False

        return True

    def current_analyzer_pixel_heights(self) -> tuple[float, ...]:
        if not hasattr(self, "analyzer_area"):
            return ()

        width = self.analyzer_area.get_allocated_width()
        height = self.analyzer_area.get_allocated_height()
        if width <= 0 or height <= 0:
            return ()

        usable_height = max(float(height), 1.0)
        display_gain_db = getattr(self, "analyzer_display_gain_db", 0.0)
        heights: list[float] = []

        for level in self.analyzer_levels:
            normalized = analyzer_level_to_display_norm(float(level), display_gain_db)
            heights.append(usable_height * normalized)

        return tuple(heights)

    def analyzer_pixels_changed(self, current: tuple[float, ...]) -> bool:
        previous = getattr(self, "analyzer_drawn_pixel_heights", ())

        if len(current) != len(previous):
            self.analyzer_drawn_pixel_heights = current
            return True

        for current_height, previous_height in zip(current, previous, strict=False):
            if abs(current_height - previous_height) >= ANALYZER_PIXEL_REDRAW_THRESHOLD:
                self.analyzer_drawn_pixel_heights = current
                return True

        return False

    def on_analyzer_levels(self, levels: list[float]) -> None:
        if self.ui_shutting_down:
            return

        GLib.idle_add(self.on_analyzer_levels_idle, tuple(levels))

    def on_analyzer_levels_idle(self, levels: tuple[float, ...]) -> bool:
        if self.ui_shutting_down:
            return False

        if not self.analyzer_enabled or self.analyzer_frozen:
            self.analyzer_last_frame_time = GLib.get_monotonic_time() / 1_000_000.0
            return False

        if len(levels) != len(self.analyzer_levels):
            self.analyzer_levels = [0.0] * len(levels)

        for index, value in enumerate(levels):
            current = self.analyzer_levels[index]
            target = float(value)
            smoothing = (
                min(self.analyzer_smoothing, ANALYZER_ATTACK_SMOOTHING_MAX)
                if target > current
                else self.analyzer_smoothing
            )
            self.analyzer_levels[index] = (current * smoothing) + (target * (1.0 - smoothing))

        now = GLib.get_monotonic_time() / 1_000_000.0
        self.analyzer_last_frame_time = now
        self.queue_analyzer_draw()
        self.maybe_emit_control_analyzer_levels_changed(now)
        return False

    def on_analyzer_preview_tick(self, now: float | None = None) -> bool:
        if self.ui_shutting_down:
            self.analyzer_preview_source_id = 0
            self.analyzer_preview_uses_tick_callback = False
            return False

        if not self.analyzer_enabled and not any(level > 0.01 for level in self.analyzer_levels):
            self.analyzer_preview_source_id = 0
            self.analyzer_preview_uses_tick_callback = False
            return False

        if now is None:
            now = GLib.get_monotonic_time() / 1_000_000.0
        age = now - getattr(self, "analyzer_last_frame_time", 0.0)

        if self.analyzer_enabled and not self.analyzer_frozen and age < 0.18:
            return True

        still_visible = False
        for index, current in enumerate(self.analyzer_levels):
            decayed = current * (0.78 if self.analyzer_enabled else 0.68)
            if decayed > 0.01:
                still_visible = True
            self.analyzer_levels[index] = decayed

        if still_visible:
            self.queue_analyzer_draw()
            self.maybe_emit_control_analyzer_levels_changed(now)

        return True

    def on_analyzer_changed(self, switch: Gtk.Switch, _param: object) -> None:
        if self.updating_ui:
            return

        self.analyzer_enabled = switch.get_active()
        if self.analyzer_enabled:
            self.start_analyzer_preview()
        else:
            self.stop_analyzer_preview()
            self.analyzer_levels = [0.0] * len(self.analyzer_levels)
            self.queue_analyzer_draw(force=True)
            self.emit_control_analyzer_levels_changed()
        self.sync_ui_from_state()
        self.emit_control_state_changed()

    def update_analyzer_summary_label(self) -> None:
        smoothing = int(round(self.analyzer_smoothing * 100.0))
        display_gain = f"{self.analyzer_display_gain_db:+.0f} dB"

        if not self.analyzer_enabled:
            analyzer_summary = "Off"
            analyzer_tooltip = "Monitor is off"
        elif self.analyzer_frozen:
            analyzer_summary = f"Frozen · {smoothing}% smooth · {display_gain}"
            analyzer_tooltip = f"Monitor frozen; {smoothing}% smoothing; {display_gain} display gain"
        else:
            analyzer_summary = f"On · {smoothing}% smooth · {display_gain}"
            analyzer_tooltip = f"Monitor on; {smoothing}% smoothing; {display_gain} display gain"

        self.analyzer_summary_label.set_text(analyzer_summary)
        self.analyzer_summary_label.set_tooltip_text(analyzer_tooltip)

    def on_analyzer_freeze_changed(self, switch: Gtk.Switch, _param: object) -> None:
        if self.updating_ui:
            return

        self.analyzer_frozen = switch.get_active()
        self.sync_ui_from_state()
        self.emit_control_state_changed()

    def on_analyzer_smoothing_changed(self, scale: Gtk.Scale) -> None:
        self.analyzer_smoothing = clamp(scale.get_value() / 100.0, 0.15, 0.95)
        self.analyzer_smoothing_label.set_text(f"{int(round(self.analyzer_smoothing * 100.0))}%")
        self.update_analyzer_summary_label()

        if self.updating_ui:
            return

        self.queue_analyzer_draw(force=True)

    def on_analyzer_display_gain_changed(self, scale: Gtk.Scale) -> None:
        self.analyzer_display_gain_db = clamp(
            scale.get_value(),
            ANALYZER_DISPLAY_GAIN_MIN,
            ANALYZER_DISPLAY_GAIN_MAX,
        )
        self.analyzer_display_gain_label.set_text(f"{self.analyzer_display_gain_db:+.0f} dB")
        self.update_analyzer_summary_label()

        if self.updating_ui:
            return

        self.invalidate_graph_background_cache()
        self.queue_graph_draw()
        self.queue_analyzer_draw(force=True)

    def maybe_emit_control_analyzer_levels_changed(self, now: float) -> None:
        last_emit = getattr(self, "control_analyzer_last_emit_time", 0.0)
        if now - last_emit < CONTROL_ANALYZER_EMIT_INTERVAL_SECONDS:
            return

        self.control_analyzer_last_emit_time = now
        self.emit_control_analyzer_levels_changed()

    def emit_control_state_changed(self) -> None:
        application = self.get_application()
        if hasattr(application, "emit_control_state_changed"):
            application.emit_control_state_changed()

    def emit_control_analyzer_levels_changed(self) -> None:
        application = self.get_application()
        if hasattr(application, "emit_control_analyzer_levels_changed"):
            application.emit_control_analyzer_levels_changed()
