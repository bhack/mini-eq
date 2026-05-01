from __future__ import annotations

import math
from collections.abc import Callable

import cairo
import gi

gi.require_version("Gdk", "4.0")
gi.require_version("Gtk", "4.0")

from gi.repository import Gdk, Gtk

from .appearance import style_manager_is_dark
from .core import (
    EQ_GAIN_MAX_DB,
    EQ_GAIN_MIN_DB,
    clamp,
)

DRAG_THRESHOLD_PX = 3.0
GAIN_MIN_DB = EQ_GAIN_MIN_DB
GAIN_MAX_DB = EQ_GAIN_MAX_DB
GAIN_RANGE_DB = GAIN_MAX_DB - GAIN_MIN_DB
GAIN_STEP_DB = 0.5
GAIN_FINE_STEP_DB = 0.1
GAIN_COARSE_STEP_DB = 3.0
GAIN_PAGE_STEP_DB = 3.0
GAIN_DRAG_FINE_MULTIPLIER = 0.20
GAIN_DRAG_COARSE_MULTIPLIER = 2.0
TICK_GAINS = (-24.0, -12.0, 0.0, 12.0, 24.0)
TICK_ZERO_GAIN = 0.0
TICK_INNER_OFFSET_PX = 9.0
TICK_MINOR_OUTER_OFFSET_PX = 14.0
TICK_ZERO_OUTER_OFFSET_PX = 20.0
TICK_MINOR_LINE_WIDTH = 1.0
TICK_ZERO_LINE_WIDTH = 1.15
DARK_TICK_ZERO_ALPHA = 0.42
DARK_TICK_MINOR_ALPHA = 0.20
LIGHT_TICK_ZERO_ALPHA = 0.46
LIGHT_TICK_MINOR_ALPHA = 0.32

FOCUS_BLUE = (0.47, 0.72, 1.0)
FOCUS_BLUE_LIGHT = (0.68, 0.84, 1.0)

FILTER_TYPE_SHORT_LABELS = {
    "Off": "Off",
    "Bell": "Bell",
    "Hi-pass": "HP",
    "Hi-shelf": "HS",
    "Lo-pass": "LP",
    "Lo-shelf": "LS",
    "Notch": "Notch",
    "Allpass": "AP",
    "Bandpass": "BP",
}


def rounded_rectangle(cr, x: float, y: float, width: float, height: float, radius: float) -> None:
    right = x + width
    bottom = y + height
    radius = min(radius, width / 2.0, height / 2.0)
    cr.new_sub_path()
    cr.arc(right - radius, y + radius, radius, -math.pi / 2.0, 0.0)
    cr.arc(right - radius, bottom - radius, radius, 0.0, math.pi / 2.0)
    cr.arc(x + radius, bottom - radius, radius, math.pi / 2.0, math.pi)
    cr.arc(x + radius, y + radius, radius, math.pi, 3.0 * math.pi / 2.0)
    cr.close_path()


class EqBandFader(Gtk.DrawingArea):
    def __init__(
        self,
        index: int,
        select_callback: Callable[[int], None],
        gain_changed_callback: Callable[[int, float], None],
        activate_callback: Callable[[int], None] | None = None,
    ) -> None:
        super().__init__()
        self.index = index
        self.select_callback = select_callback
        self.gain_changed_callback = gain_changed_callback
        self.activate_callback = activate_callback
        self.gain_db = 0.0
        self.frequency = 0.0
        self.frequency_label = ""
        self.q_value = 0.0
        self.q_label = ""
        self.filter_type = 0
        self.filter_type_label = ""
        self.selected = False
        self.active = True
        self.muted = False
        self.soloed = False
        self.solo_active = False
        self.hovered = False
        self.focused = False
        self.drag_start_gain_db = 0.0
        self.dragging_gain = False

        self.set_content_width(72)
        self.set_content_height(182)
        self.set_hexpand(False)
        self.set_focusable(True)
        self.set_accessible_role(Gtk.AccessibleRole.SLIDER)
        self.set_cursor_from_name("ns-resize")
        self.set_tooltip_text("Drag gain. Select a band to edit type, frequency, Q, mute, and solo below.")
        self.set_draw_func(self.on_draw)
        self.update_accessible_state()

        drag = Gtk.GestureDrag()
        drag.connect("drag-begin", self.on_drag_begin)
        drag.connect("drag-update", self.on_drag_update)
        drag.connect("drag-end", self.on_drag_end)
        self.add_controller(drag)

        motion = Gtk.EventControllerMotion()
        motion.connect("enter", self.on_motion_enter)
        motion.connect("leave", self.on_motion_leave)
        self.add_controller(motion)

        focus = Gtk.EventControllerFocus()
        focus.connect("enter", self.on_focus_enter)
        focus.connect("leave", self.on_focus_leave)
        self.add_controller(focus)

        scroll = Gtk.EventControllerScroll.new(Gtk.EventControllerScrollFlags.VERTICAL)
        scroll.connect("scroll", self.on_scroll)
        self.add_controller(scroll)

        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self.on_key_pressed)
        self.add_controller(keys)

        click = Gtk.GestureClick()
        click.connect("pressed", self.on_click_pressed)
        self.add_controller(click)

    def is_dark(self) -> bool:
        root = self.get_root()
        application = root.get_application() if root is not None and hasattr(root, "get_application") else None
        style_manager = application.get_style_manager() if application is not None else None
        return style_manager_is_dark(style_manager)

    def set_band_state(
        self,
        *,
        gain_db: float,
        frequency: float,
        frequency_label: str,
        q_value: float,
        q_label: str,
        filter_type: int,
        filter_type_label: str,
        selected: bool,
        active: bool,
        muted: bool,
        soloed: bool,
        solo_active: bool,
    ) -> None:
        changed = (
            self.gain_db != gain_db
            or self.frequency != frequency
            or self.frequency_label != frequency_label
            or self.q_value != q_value
            or self.q_label != q_label
            or self.filter_type != filter_type
            or self.filter_type_label != filter_type_label
            or self.selected != selected
            or self.active != active
            or self.muted != muted
            or self.soloed != soloed
            or self.solo_active != solo_active
        )
        self.gain_db = gain_db
        self.frequency = frequency
        self.frequency_label = frequency_label
        self.q_value = q_value
        self.q_label = q_label
        self.filter_type = filter_type
        self.filter_type_label = filter_type_label
        self.selected = selected
        self.active = active
        self.muted = muted
        self.soloed = soloed
        self.solo_active = solo_active
        self.update_accessible_state()
        if changed:
            self.queue_draw()

    def update_accessible_state(self) -> None:
        description_parts = []
        if self.frequency_label:
            description_parts.append(self.frequency_label)
        if self.filter_type_label:
            description_parts.append(self.filter_type_label)
        if self.q_label:
            description_parts.append(f"Q {self.q_label}")
        if self.muted:
            description_parts.append("Muted")
        if self.soloed:
            description_parts.append("Solo")
        elif self.solo_active:
            description_parts.append("Suppressed by solo")
        if not self.active:
            description_parts.append("Inactive")

        description = ", ".join(description_parts)
        self.update_property(
            [
                Gtk.AccessibleProperty.LABEL,
                Gtk.AccessibleProperty.DESCRIPTION,
                Gtk.AccessibleProperty.VALUE_MIN,
                Gtk.AccessibleProperty.VALUE_MAX,
                Gtk.AccessibleProperty.VALUE_NOW,
                Gtk.AccessibleProperty.VALUE_TEXT,
            ],
            [
                f"Band {self.index + 1} Gain",
                description,
                GAIN_MIN_DB,
                GAIN_MAX_DB,
                self.gain_db,
                f"{self.gain_db:+.1f} dB",
            ],
        )

    def gain_to_y(self, gain_db: float, top: float, bottom: float) -> float:
        normalized = (clamp(gain_db, GAIN_MIN_DB, GAIN_MAX_DB) - GAIN_MIN_DB) / GAIN_RANGE_DB
        return bottom - ((bottom - top) * normalized)

    def track_bounds(self, height: float) -> tuple[float, float]:
        track_top = 56.0
        minimum_track_length = 42.0
        bottom_margin = 44.0 if self.show_q_in_tile(height) else 32.0
        track_bottom = max(track_top + minimum_track_length, height - bottom_margin)
        return track_top, track_bottom

    def selected_frequency_label(self) -> str:
        if self.frequency >= 1000.0:
            return f"{self.frequency / 1000.0:.2g} kHz"
        return f"{self.frequency:.0f} Hz"

    def compact_filter_type_label(self) -> str:
        return FILTER_TYPE_SHORT_LABELS.get(self.filter_type_label, self.filter_type_label[:5])

    def compact_q_label(self) -> str:
        if self.q_value >= 10.0:
            return f"{self.q_value:.1f}"
        return f"{self.q_value:.2f}"

    def show_q_in_tile(self, height: float) -> bool:
        return height >= 170.0

    def draw_text(
        self,
        cr,
        text: str,
        x: float,
        y: float,
        size: float,
        color: tuple[float, float, float],
        *,
        bold: bool = False,
        center: bool = True,
    ) -> None:
        cr.select_font_face("Sans", 0, 1 if bold else 0)
        cr.set_font_size(size)
        extents = cr.text_extents(text)
        text_x = x - (extents.width / 2.0) - extents.x_bearing if center else x
        cr.set_source_rgb(*color)
        cr.move_to(text_x, y)
        cr.show_text(text)

    def draw_state_badge(
        self,
        cr,
        label: str,
        x: float,
        y: float,
        *,
        width: float,
        color: tuple[float, float, float],
        alpha: float,
    ) -> None:
        rounded_rectangle(cr, x, y, width, 15.0, 6.5)
        cr.set_source_rgba(*color, 0.22 * alpha)
        cr.fill_preserve()
        cr.set_source_rgba(*color, 0.50 * alpha)
        cr.set_line_width(1.0)
        cr.stroke()
        self.draw_text(cr, label, x + (width / 2.0), y + 10.7, 7.8, (0.94, 0.97, 1.0), bold=True)

    def on_draw(self, _area: Gtk.DrawingArea, cr, width: int, height: int) -> None:
        width_f = float(width)
        height_f = float(height)
        center_x = width_f / 2.0
        effective = self.active and not self.muted and (not self.solo_active or self.soloed)
        alpha = 1.0 if effective else 0.48
        engaged = self.selected or self.hovered or self.focused or self.dragging_gain
        dark = self.is_dark()
        if dark:
            engaged_fill_rgb = (1.0, 1.0, 1.0)
            selected_fill_alpha = 0.026
            hover_fill_alpha = 0.045
            text_main = (0.82, 0.86, 0.90)
            text_type_selected = (0.72, 0.78, 0.84)
            text_type = (0.66, 0.72, 0.78)
            text_disabled = (0.50, 0.56, 0.62)
            gain_color_selected = (0.91, 0.95, 0.99)
            gain_color_normal = (0.90, 0.94, 0.98)
            gain_color_disabled = (0.62, 0.68, 0.74)
            track_shadow = (0.02, 0.03, 0.045, 0.42)
            track_gradient_colors = ((0.20, 0.26, 0.34, 0.82), (0.10, 0.14, 0.20, 0.82))
            selected_fill_gradient_colors = ((0.56, 0.69, 0.81, 0.56), (0.38, 0.51, 0.64, 0.56))
            fill_gradient_colors = ((0.58, 0.68, 0.78, 0.52), (0.38, 0.48, 0.60, 0.52))
            tick_color = (0.82, 0.88, 0.94)
            tick_zero_alpha = DARK_TICK_ZERO_ALPHA
            tick_minor_alpha = DARK_TICK_MINOR_ALPHA
            knob_shadow = (0.0, 0.0, 0.0, 0.28)
            knob_selected = (0.54, 0.72, 0.90)
            knob_normal = (0.70, 0.77, 0.84)
            knob_border = (0.0, 0.0, 0.0, 0.28)
            knob_highlight = (1.0, 1.0, 1.0, 0.24)
            overview_freq = (0.76, 0.81, 0.86)
            overview_freq_disabled = (0.54, 0.59, 0.64)
            q_text = (0.60, 0.66, 0.72)
            q_text_disabled = (0.46, 0.52, 0.58)
        else:
            engaged_fill_rgb = (0.0, 0.0, 0.0)
            selected_fill_alpha = 0.030
            hover_fill_alpha = 0.045
            text_main = (0.15, 0.20, 0.25)
            text_type_selected = (0.18, 0.27, 0.36)
            text_type = (0.28, 0.35, 0.42)
            text_disabled = (0.52, 0.58, 0.64)
            gain_color_selected = (0.12, 0.18, 0.24)
            gain_color_normal = (0.20, 0.27, 0.34)
            gain_color_disabled = (0.58, 0.63, 0.68)
            track_shadow = (0.0, 0.0, 0.0, 0.20)
            track_gradient_colors = ((0.54, 0.64, 0.74, 0.94), (0.32, 0.43, 0.55, 0.94))
            selected_fill_gradient_colors = ((0.16, 0.45, 0.72, 0.84), (0.08, 0.30, 0.50, 0.84))
            fill_gradient_colors = ((0.24, 0.43, 0.60, 0.76), (0.14, 0.28, 0.44, 0.76))
            tick_color = (0.13, 0.19, 0.26)
            tick_zero_alpha = LIGHT_TICK_ZERO_ALPHA
            tick_minor_alpha = LIGHT_TICK_MINOR_ALPHA
            knob_shadow = (0.0, 0.0, 0.0, 0.18)
            knob_selected = (0.36, 0.61, 0.84)
            knob_normal = (0.52, 0.64, 0.75)
            knob_border = (0.0, 0.0, 0.0, 0.20)
            knob_highlight = (1.0, 1.0, 1.0, 0.36)
            overview_freq = (0.20, 0.28, 0.36)
            overview_freq_disabled = (0.60, 0.65, 0.70)
            q_text = (0.34, 0.42, 0.50)
            q_text_disabled = (0.66, 0.70, 0.74)

        if engaged:
            rounded_rectangle(cr, 2.0, 2.0, width_f - 4.0, height_f - 4.0, 15.0)
            if self.selected:
                cr.set_source_rgba(*engaged_fill_rgb, selected_fill_alpha * alpha)
            else:
                cr.set_source_rgba(*engaged_fill_rgb, hover_fill_alpha * alpha)
            cr.fill_preserve()
            border_alpha = 0.30 if self.selected else 0.15
            if self.focused:
                border_alpha = max(border_alpha, 0.34)
            if self.selected:
                cr.set_source_rgba(*FOCUS_BLUE, border_alpha * alpha)
            else:
                cr.set_source_rgba(0.82, 0.88, 0.94, border_alpha * alpha)
            cr.set_line_width(1.0)
            cr.stroke()

        self.draw_text(cr, str(self.index + 1), center_x, 15.0, 10.0, text_main, bold=True)

        type_color = text_type_selected if self.selected else text_type
        if not self.active:
            type_color = text_disabled
        self.draw_text(cr, self.compact_filter_type_label(), center_x, 29.5, 9.0, type_color, bold=True)

        gain_label = f"{self.gain_db:+.1f} dB"
        gain_width = 60.0
        rounded_rectangle(cr, center_x - gain_width / 2.0, 35.0, gain_width, 18.0, 8.0)
        if self.selected:
            cr.set_source_rgba(*engaged_fill_rgb, 0.08 * alpha)
        else:
            cr.set_source_rgba(*engaged_fill_rgb, 0.07 * alpha)
        cr.fill()
        gain_color = gain_color_selected if self.selected else gain_color_normal
        if not self.active:
            gain_color = gain_color_disabled
        self.draw_text(cr, gain_label, center_x, 48.1, 9.3, gain_color, bold=True)

        track_top, track_bottom = self.track_bounds(height_f)
        track_x = center_x - 3.5
        track_width = 7.0
        knob_y = self.gain_to_y(self.gain_db, track_top, track_bottom)
        zero_y = self.gain_to_y(0.0, track_top, track_bottom)

        rounded_rectangle(cr, track_x - 2.0, track_top - 1.0, track_width + 4.0, track_bottom - track_top + 2.0, 6.0)
        cr.set_source_rgba(track_shadow[0], track_shadow[1], track_shadow[2], track_shadow[3] * alpha)
        cr.fill()

        rounded_rectangle(cr, track_x, track_top, track_width, track_bottom - track_top, 3.5)
        track_gradient = cairo.LinearGradient(0, track_top, 0, track_bottom)
        track_gradient.add_color_stop_rgba(0.0, *track_gradient_colors[0][:3], track_gradient_colors[0][3] * alpha)
        track_gradient.add_color_stop_rgba(1.0, *track_gradient_colors[1][:3], track_gradient_colors[1][3] * alpha)
        cr.set_source(track_gradient)
        cr.fill()

        fill_top = min(knob_y, zero_y)
        fill_bottom = max(knob_y, zero_y)
        if fill_bottom - fill_top < 2.0:
            fill_bottom = fill_top + 2.0
        rounded_rectangle(cr, track_x, fill_top, track_width, fill_bottom - fill_top, 4.0)
        fill_gradient = cairo.LinearGradient(0, fill_top, 0, fill_bottom)
        if self.selected or self.dragging_gain:
            fill_gradient.add_color_stop_rgba(
                0.0,
                *selected_fill_gradient_colors[0][:3],
                selected_fill_gradient_colors[0][3] * alpha,
            )
            fill_gradient.add_color_stop_rgba(
                1.0,
                *selected_fill_gradient_colors[1][:3],
                selected_fill_gradient_colors[1][3] * alpha,
            )
        else:
            fill_gradient.add_color_stop_rgba(0.0, *fill_gradient_colors[0][:3], fill_gradient_colors[0][3] * alpha)
            fill_gradient.add_color_stop_rgba(1.0, *fill_gradient_colors[1][:3], fill_gradient_colors[1][3] * alpha)
        cr.set_source(fill_gradient)
        cr.fill()

        for tick_gain in TICK_GAINS:
            is_zero_tick = tick_gain == TICK_ZERO_GAIN
            tick_y = self.gain_to_y(tick_gain, track_top, track_bottom)
            tick_alpha = tick_zero_alpha if is_zero_tick else tick_minor_alpha
            cr.set_source_rgba(*tick_color, tick_alpha * alpha)
            cr.set_line_width(TICK_ZERO_LINE_WIDTH if is_zero_tick else TICK_MINOR_LINE_WIDTH)
            cr.move_to(center_x + TICK_INNER_OFFSET_PX, tick_y)
            outer_offset = TICK_ZERO_OUTER_OFFSET_PX if is_zero_tick else TICK_MINOR_OUTER_OFFSET_PX
            cr.line_to(center_x + outer_offset, tick_y)
            cr.stroke()
            if is_zero_tick:
                cr.move_to(center_x - TICK_ZERO_OUTER_OFFSET_PX, tick_y)
                cr.line_to(center_x - TICK_INNER_OFFSET_PX, tick_y)
                cr.stroke()

        knob_width = 26.0 if self.selected or self.dragging_gain else 24.0
        knob_height = 16.0
        knob_x = center_x - (knob_width / 2.0)
        knob_y_top = knob_y - (knob_height / 2.0)

        rounded_rectangle(cr, knob_x + 1.0, knob_y_top + 2.0, knob_width, knob_height, 5.0)
        cr.set_source_rgba(knob_shadow[0], knob_shadow[1], knob_shadow[2], knob_shadow[3] * alpha)
        cr.fill()

        rounded_rectangle(cr, knob_x, knob_y_top, knob_width, knob_height, 5.0)
        if self.selected or self.dragging_gain:
            cr.set_source_rgba(*knob_selected, 0.98 * alpha)
        else:
            cr.set_source_rgba(*knob_normal, 0.98 * alpha)
        cr.fill_preserve()
        cr.set_source_rgba(knob_border[0], knob_border[1], knob_border[2], knob_border[3] * alpha)
        cr.set_line_width(1.0)
        cr.stroke()
        cr.set_source_rgba(knob_highlight[0], knob_highlight[1], knob_highlight[2], knob_highlight[3] * alpha)
        cr.set_line_width(1.0)
        cr.move_to(center_x - 7.0, knob_y)
        cr.line_to(center_x + 7.0, knob_y)
        cr.stroke()

        overview_freq_color = overview_freq if self.active else overview_freq_disabled
        if self.show_q_in_tile(height_f):
            q_color = q_text if self.active else q_text_disabled
            self.draw_text(cr, self.selected_frequency_label(), center_x, height_f - 25.0, 9.0, overview_freq_color)
            self.draw_text(cr, self.compact_q_label(), center_x, height_f - 11.0, 8.6, q_color)
        else:
            self.draw_text(cr, self.selected_frequency_label(), center_x, height_f - 13.0, 9.0, overview_freq_color)

        badge_y = 52.0
        badge_right = width_f - 8.0
        if self.muted and self.soloed:
            badge_width = 24.0
            self.draw_state_badge(
                cr,
                "M/S",
                badge_right - badge_width,
                badge_y,
                width=badge_width,
                color=(0.78, 0.65, 0.98),
                alpha=alpha,
            )
        elif self.muted:
            self.draw_state_badge(
                cr,
                "M",
                badge_right - 14.0,
                badge_y,
                width=14.0,
                color=(0.94, 0.44, 0.44),
                alpha=alpha,
            )
        elif self.soloed:
            self.draw_state_badge(
                cr,
                "S",
                badge_right - 14.0,
                badge_y,
                width=14.0,
                color=FOCUS_BLUE,
                alpha=alpha,
            )

    def interaction_multiplier_for_state(self, state: Gdk.ModifierType) -> float:
        if state & Gdk.ModifierType.SHIFT_MASK:
            return GAIN_DRAG_FINE_MULTIPLIER
        if state & Gdk.ModifierType.CONTROL_MASK:
            return GAIN_DRAG_COARSE_MULTIPLIER
        return 1.0

    def direct_step_for_state(self, state: Gdk.ModifierType) -> float:
        if state & Gdk.ModifierType.SHIFT_MASK:
            return GAIN_FINE_STEP_DB
        if state & Gdk.ModifierType.CONTROL_MASK:
            return GAIN_COARSE_STEP_DB
        return GAIN_STEP_DB

    def update_gain_from_drag(self, offset_y: float, state: Gdk.ModifierType) -> None:
        track_top, track_bottom = self.track_bounds(float(self.get_allocated_height()))
        usable_height = max(track_bottom - track_top, 1.0)
        multiplier = self.interaction_multiplier_for_state(state)
        gain = self.drag_start_gain_db - ((offset_y / usable_height) * GAIN_RANGE_DB * multiplier)
        gain = round(clamp(gain, GAIN_MIN_DB, GAIN_MAX_DB) * 10.0) / 10.0
        if gain != self.gain_db:
            self.gain_changed_callback(self.index, gain)

    def on_drag_begin(self, _gesture: Gtk.GestureDrag, _x: float, _y: float) -> None:
        self.grab_focus()
        self.drag_start_gain_db = self.gain_db
        self.dragging_gain = False
        self.select_callback(self.index)
        self.queue_draw()

    def on_drag_update(self, gesture: Gtk.GestureDrag, offset_x: float, offset_y: float) -> None:
        if not self.dragging_gain:
            if math.hypot(offset_x, offset_y) < DRAG_THRESHOLD_PX:
                return
            self.dragging_gain = True

        state = gesture.get_current_event_state()
        self.update_gain_from_drag(offset_y, state)

    def on_drag_end(self, _gesture: Gtk.GestureDrag, _offset_x: float, _offset_y: float) -> None:
        self.dragging_gain = False
        self.queue_draw()

    def apply_direct_gain_delta(self, delta_db: float) -> None:
        self.grab_focus()
        self.select_callback(self.index)
        gain = round(clamp(self.gain_db + delta_db, GAIN_MIN_DB, GAIN_MAX_DB) * 10.0) / 10.0
        if gain != self.gain_db:
            self.gain_changed_callback(self.index, gain)

    def on_motion_enter(self, _controller: Gtk.EventControllerMotion, _x: float, _y: float) -> None:
        self.hovered = True
        self.queue_draw()

    def on_motion_leave(self, _controller: Gtk.EventControllerMotion) -> None:
        self.hovered = False
        self.set_cursor_from_name("ns-resize")
        self.queue_draw()

    def on_focus_enter(self, _controller: Gtk.EventControllerFocus) -> None:
        self.focused = True
        self.queue_draw()

    def on_focus_leave(self, _controller: Gtk.EventControllerFocus) -> None:
        self.focused = False
        self.queue_draw()

    def on_scroll(self, controller: Gtk.EventControllerScroll, _dx: float, dy: float) -> bool:
        if dy == 0.0:
            return False

        state = controller.get_current_event_state()
        step = self.direct_step_for_state(state)
        self.apply_direct_gain_delta(step if dy < 0.0 else -step)
        return True

    def on_key_pressed(
        self,
        _controller: Gtk.EventControllerKey,
        keyval: int,
        _keycode: int,
        state: Gdk.ModifierType,
    ) -> bool:
        step = self.direct_step_for_state(state)
        key_deltas = {
            Gdk.KEY_Up: step,
            Gdk.KEY_KP_Up: step,
            Gdk.KEY_Right: step,
            Gdk.KEY_KP_Right: step,
            Gdk.KEY_Down: -step,
            Gdk.KEY_KP_Down: -step,
            Gdk.KEY_Left: -step,
            Gdk.KEY_KP_Left: -step,
            Gdk.KEY_Page_Up: GAIN_PAGE_STEP_DB,
            Gdk.KEY_KP_Page_Up: GAIN_PAGE_STEP_DB,
            Gdk.KEY_Page_Down: -GAIN_PAGE_STEP_DB,
            Gdk.KEY_KP_Page_Down: -GAIN_PAGE_STEP_DB,
        }

        if keyval in key_deltas:
            self.apply_direct_gain_delta(key_deltas[keyval])
            return True

        if keyval in (Gdk.KEY_0, Gdk.KEY_KP_0, Gdk.KEY_Home):
            self.grab_focus()
            self.select_callback(self.index)
            if self.gain_db != 0.0:
                self.gain_changed_callback(self.index, 0.0)
            return True

        if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter, Gdk.KEY_space):
            self.grab_focus()
            self.select_callback(self.index)
            if self.activate_callback is not None:
                self.activate_callback(self.index)
            return True

        return False

    def on_click_pressed(self, _gesture: Gtk.GestureClick, _press_count: int, _x: float, _y: float) -> None:
        self.grab_focus()
        self.select_callback(self.index)
