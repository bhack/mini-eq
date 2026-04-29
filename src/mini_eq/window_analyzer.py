from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")

from gi.repository import GLib, Gtk

from .analyzer import (
    ANALYZER_BAND_FREQUENCIES,
    ANALYZER_DISPLAY_GAIN_MAX,
    ANALYZER_DISPLAY_GAIN_MIN,
    analyzer_bin_center_frequencies,
    analyzer_level_to_display_norm,
)
from .core import clamp
from .glib_utils import destroy_glib_source

ANALYZER_REDRAW_INTERVAL_S = 1.0 / 30.0
ANALYZER_PREVIEW_INTERVAL_MS = 33
ANALYZER_ATTACK_SMOOTHING_MAX = 0.25
ANALYZER_PIXEL_REDRAW_THRESHOLD = 1.0
CONTROL_STATE_EMIT_INTERVAL_SECONDS = 0.10


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

        self.analyzer_preview_source_id = GLib.timeout_add(ANALYZER_PREVIEW_INTERVAL_MS, self.on_analyzer_preview_tick)

    def stop_analyzer_preview(self, *, stop_backend: bool = True) -> None:
        if stop_backend:
            self.controller.set_analyzer_enabled(False)

        if self.analyzer_preview_source_id > 0:
            destroy_glib_source(self.analyzer_preview_source_id)
            self.analyzer_preview_source_id = 0

    def queue_analyzer_draw(self, *, force: bool = False) -> None:
        if not hasattr(self, "analyzer_area"):
            return

        now = GLib.get_monotonic_time() / 1_000_000.0
        if not force and now - getattr(self, "analyzer_last_redraw_time", 0.0) < ANALYZER_REDRAW_INTERVAL_S:
            return

        pixel_heights = self.current_analyzer_pixel_heights()
        if not force and not self.analyzer_pixels_changed(pixel_heights):
            return

        self.analyzer_pending_pixel_heights = pixel_heights
        self.analyzer_last_redraw_time = now
        self.analyzer_area.queue_draw()

    def current_analyzer_pixel_heights(self) -> tuple[float, ...]:
        if not hasattr(self, "analyzer_area"):
            return ()

        width = self.analyzer_area.get_allocated_width()
        height = self.analyzer_area.get_allocated_height()
        if width <= 0 or height <= 0:
            return ()

        _width_f, height_f, _left, _right, top, bottom = self.graph_plot_bounds(width, height)
        usable_height = max(height_f - top - bottom, 1.0)
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

    def analyzer_bin_frequencies(self) -> list[float]:
        if not self.analyzer_levels:
            return []

        count = len(self.analyzer_levels)
        if getattr(self, "analyzer_frequency_cache_key", None) == count:
            return self.analyzer_frequency_cache

        if count == len(ANALYZER_BAND_FREQUENCIES):
            frequencies = list(ANALYZER_BAND_FREQUENCIES)
        else:
            frequencies = list(analyzer_bin_center_frequencies(count))
        self.analyzer_frequency_cache_key = count
        self.analyzer_frequency_cache = frequencies
        return frequencies

    def analyzer_bar_geometry(
        self,
        width: float,
        left: float,
        right: float,
        count: int,
    ) -> list[tuple[float, float, float]]:
        cache_key = (
            count,
            round(float(width), 2),
            round(float(left), 2),
            round(float(right), 2),
        )
        if getattr(self, "graph_analyzer_geometry_key", None) == cache_key:
            return self.graph_analyzer_geometry

        plot_right = max(left + 1.0, width - right)
        plot_width = plot_right - left
        if count <= 0:
            self.graph_analyzer_geometry_key = cache_key
            self.graph_analyzer_geometry = []
            return []

        bucket_width = plot_width / count
        inner_gap = min(1.5, bucket_width * 0.35) if count > 1 else 0.0
        geometry: list[tuple[float, float, float]] = []
        for index in range(count):
            raw_x0 = left + (bucket_width * index)
            raw_x1 = left + (bucket_width * (index + 1))
            x0 = left if index == 0 else max(left, raw_x0 + inner_gap / 2.0)
            x1 = plot_right if index == count - 1 else min(plot_right, raw_x1 - inner_gap / 2.0)
            center_x = (x0 + x1) / 2.0

            if x1 <= x0:
                x0 = clamp(center_x - 0.5, left, max(left, plot_right - 1.0))
                x1 = clamp(x0 + 1.0, x0 + 1.0, plot_right)

            geometry.append((x0, x1 - x0, center_x))

        self.graph_analyzer_geometry_key = cache_key
        self.graph_analyzer_geometry = geometry
        return geometry

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
        self.maybe_emit_control_state_changed(now)
        return False

    def on_analyzer_preview_tick(self) -> bool:
        if self.ui_shutting_down:
            self.analyzer_preview_source_id = 0
            return False

        if not self.analyzer_enabled and not any(level > 0.01 for level in self.analyzer_levels):
            self.analyzer_preview_source_id = 0
            return False

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
            self.maybe_emit_control_state_changed(now)

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

    def maybe_emit_control_state_changed(self, now: float) -> None:
        last_emit = getattr(self, "control_state_last_emit_time", 0.0)
        if now - last_emit < CONTROL_STATE_EMIT_INTERVAL_SECONDS:
            return

        self.control_state_last_emit_time = now
        self.emit_control_state_changed()

    def emit_control_state_changed(self) -> None:
        application = self.get_application()
        if hasattr(application, "emit_control_state_changed"):
            application.emit_control_state_changed()
