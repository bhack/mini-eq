from __future__ import annotations

import math

import gi

gi.require_version("Gtk", "4.0")

from gi.repository import GLib, Gtk

from .analyzer import (
    ANALYZER_DISPLAY_GAIN_MAX,
    ANALYZER_DISPLAY_GAIN_MIN,
    AnalyzerLoudnessSnapshot,
    analyzer_level_to_display_norm,
)
from .appearance import style_manager_is_dark
from .core import clamp
from .glib_utils import destroy_glib_source

ANALYZER_REDRAW_INTERVAL_S = 1.0 / 30.0
ANALYZER_PREVIEW_INTERVAL_S = 1.0 / 30.0
ANALYZER_PREVIEW_INTERVAL_MS = 33
ANALYZER_ATTACK_SMOOTHING_MAX = 0.25
ANALYZER_PIXEL_REDRAW_THRESHOLD = 1.0
CONTROL_ANALYZER_EMIT_INTERVAL_SECONDS = 0.10
LOUDNESS_METER_MIN_LUFS = -60.0
LOUDNESS_METER_MAX_LUFS = 0.0


def format_lufs(value: float) -> str:
    if not math.isfinite(value):
        return "-inf LUFS"
    return f"{value:.1f} LUFS"


def loudness_current_lufs(snapshot: AnalyzerLoudnessSnapshot | None) -> float | None:
    if snapshot is None:
        return None

    for value in (snapshot.shortterm_lufs, snapshot.momentary_lufs, snapshot.integrated_lufs):
        if math.isfinite(value):
            return value

    return None


def loudness_summary_lufs(snapshot: AnalyzerLoudnessSnapshot | None) -> str | None:
    value = loudness_current_lufs(snapshot)
    return format_lufs(value) if value is not None else None


def optional_lufs(value: float | None) -> str:
    if value is None:
        return "--"
    return format_lufs(value)


def loudness_meter_norm(value: float | None) -> float:
    if value is None or not math.isfinite(value):
        return 0.0
    span = LOUDNESS_METER_MAX_LUFS - LOUDNESS_METER_MIN_LUFS
    return clamp((value - LOUDNESS_METER_MIN_LUFS) / span, 0.0, 1.0)


def loudness_detail_text(loudness: AnalyzerLoudnessSnapshot | None, session_max: float | None) -> str:
    if loudness is None:
        return "Current -- · Peak --"
    return f"Current {optional_lufs(loudness_current_lufs(loudness))} · Peak {optional_lufs(session_max)}"


def loudness_tooltip_text(
    *,
    enabled: bool,
    frozen: bool,
    loudness: AnalyzerLoudnessSnapshot | None,
    session_max: float | None,
) -> str:
    if not enabled:
        return "Monitor off"
    if loudness is None:
        return "Monitor frozen" if frozen else "Monitor on"

    detail = loudness_detail_text(loudness, session_max)
    return f"Frozen · {detail}" if frozen else detail


def update_loudness_max(current_max: float | None, value: float) -> float | None:
    if not math.isfinite(value):
        return current_max
    if current_max is None or value > current_max:
        return value
    return current_max


class MiniEqWindowAnalyzerMixin:
    def update_loudness_detail_labels(
        self,
        loudness: AnalyzerLoudnessSnapshot | None,
        session_max: float | None,
    ) -> None:
        monitor_enabled = getattr(self, "analyzer_enabled", False)
        detail = "Monitor is off" if not monitor_enabled else loudness_detail_text(loudness, session_max)
        value_label = getattr(self, "analyzer_loudness_value_label", None)
        if value_label is not None:
            value_label.set_text("Off" if not monitor_enabled else optional_lufs(loudness_current_lufs(loudness)))

        meter_area = getattr(self, "analyzer_loudness_meter_area", None)
        if meter_area is not None:
            meter_area.queue_draw()
            update_property = getattr(meter_area, "update_property", None)
            if callable(update_property):
                update_property([Gtk.AccessibleProperty.DESCRIPTION], [detail])

    def on_loudness_meter_draw(self, _area: Gtk.DrawingArea, cr, width: int, height: int) -> None:
        width_f = float(max(width, 1))
        height_f = float(max(height, 1))
        track_height = min(7.0, max(4.0, height_f - 6.0))
        track_y = (height_f - track_height) / 2.0
        radius = track_height / 2.0
        loudness = getattr(self, "analyzer_loudness_snapshot", None)
        session_max = getattr(self, "analyzer_session_max_shortterm_lufs", None)

        def rounded_rect(x: float, y: float, rect_width: float, rect_height: float, rect_radius: float) -> None:
            cr.new_sub_path()
            cr.arc(x + rect_width - rect_radius, y + rect_radius, rect_radius, -1.5708, 0.0)
            cr.arc(x + rect_width - rect_radius, y + rect_height - rect_radius, rect_radius, 0.0, 1.5708)
            cr.arc(x + rect_radius, y + rect_height - rect_radius, rect_radius, 1.5708, 3.1416)
            cr.arc(x + rect_radius, y + rect_radius, rect_radius, 3.1416, 4.7124)
            cr.close_path()

        application = self.get_application()
        style_manager = application.get_style_manager() if application is not None else None
        dark = style_manager_is_dark(style_manager)
        track_rgba = (1.0, 1.0, 1.0, 0.08) if dark else (0.03, 0.10, 0.16, 0.12)
        fill_rgba = (0.33, 0.78, 0.90, 0.70) if dark else (0.03, 0.46, 0.60, 0.62)
        marker_rgba = (0.97, 0.99, 1.0, 0.98) if dark else (0.08, 0.13, 0.18, 0.92)

        rounded_rect(0.0, track_y, width_f, track_height, radius)
        cr.set_source_rgba(*track_rgba)
        cr.fill()

        current_value = loudness_current_lufs(loudness)
        current_x = width_f * loudness_meter_norm(current_value)
        if current_x > 0.5:
            cr.save()
            rounded_rect(0.0, track_y, width_f, track_height, radius)
            cr.clip()
            cr.rectangle(0.0, track_y, current_x, track_height)
            cr.set_source_rgba(*fill_rgba)
            cr.fill()
            cr.restore()

        if session_max is None or not math.isfinite(session_max):
            return

        marker_x = width_f * loudness_meter_norm(session_max)
        cr.set_source_rgba(*marker_rgba)
        cr.set_line_width(1.4)
        cr.move_to(marker_x, track_y - 2.0)
        cr.line_to(marker_x, track_y + track_height + 2.0)
        cr.stroke()

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

    def on_analyzer_loudness(self, snapshot: AnalyzerLoudnessSnapshot | None) -> None:
        if self.ui_shutting_down:
            return

        GLib.idle_add(self.on_analyzer_loudness_idle, snapshot)

    def on_analyzer_loudness_idle(self, snapshot: AnalyzerLoudnessSnapshot | None) -> bool:
        if self.ui_shutting_down:
            return False

        if not self.analyzer_enabled:
            self.analyzer_loudness_snapshot = None
            self.analyzer_session_max_shortterm_lufs = None
            self.update_analyzer_summary_label()
            return False

        if not self.analyzer_frozen:
            self.analyzer_loudness_snapshot = snapshot
            if snapshot is not None:
                self.analyzer_session_max_shortterm_lufs = update_loudness_max(
                    getattr(self, "analyzer_session_max_shortterm_lufs", None),
                    snapshot.shortterm_lufs,
                )
            self.update_analyzer_summary_label()

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
            self.analyzer_loudness_snapshot = None
            self.analyzer_session_max_shortterm_lufs = None
            self.start_analyzer_preview()
        else:
            self.stop_analyzer_preview()
            self.analyzer_levels = [0.0] * len(self.analyzer_levels)
            self.analyzer_loudness_snapshot = None
            self.analyzer_session_max_shortterm_lufs = None
            self.queue_analyzer_draw(force=True)
            self.emit_control_analyzer_levels_changed()
        self.sync_ui_from_state()
        self.emit_control_state_changed()

    def update_analyzer_summary_label(self) -> None:
        display_gain = f"{self.analyzer_display_gain_db:+.0f} dB"
        loudness = getattr(self, "analyzer_loudness_snapshot", None)
        loudness_summary = loudness_summary_lufs(loudness)
        session_max = getattr(self, "analyzer_session_max_shortterm_lufs", None)

        if not self.analyzer_enabled:
            analyzer_summary = "Off"
        elif self.analyzer_frozen:
            analyzer_summary = f"Frozen · {loudness_summary or display_gain}"
        else:
            analyzer_summary = f"On · {loudness_summary or display_gain}"
        analyzer_tooltip = loudness_tooltip_text(
            enabled=bool(self.analyzer_enabled),
            frozen=bool(self.analyzer_frozen),
            loudness=loudness,
            session_max=session_max,
        )

        self.analyzer_summary_label.set_text(analyzer_summary)
        self.update_loudness_detail_labels(loudness, session_max)
        self.analyzer_summary_label.set_tooltip_text(analyzer_tooltip)
        tooltip_widgets = getattr(self, "monitor_tooltip_widgets", (self.analyzer_summary_label,))
        for widget in tooltip_widgets:
            widget.set_tooltip_text(analyzer_tooltip)

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
