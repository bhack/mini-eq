from __future__ import annotations

import math
from collections.abc import Callable

import cairo
import gi

gi.require_version("Gdk", "4.0")
gi.require_version("Gtk", "4.0")

from gi.repository import Gdk, Gtk

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

FOCUS_BLUE = (0.47, 0.72, 1.0)
FOCUS_BLUE_LIGHT = (0.68, 0.84, 1.0)
FOCUS_BLUE_DARK = (0.24, 0.48, 0.76)

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
    ) -> None:
        super().__init__()
        self.index = index
        self.select_callback = select_callback
        self.gain_changed_callback = gain_changed_callback
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
        self.pointer_x = 0.0
        self.pointer_y = 0.0
        self.drag_start_gain_db = 0.0
        self.dragging_gain = False

        self.set_content_width(72)
        self.set_content_height(212)
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
        motion.connect("motion", self.on_motion)
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

    def y_to_gain(self, y: float, top: float, bottom: float) -> float:
        normalized = clamp((bottom - y) / max(bottom - top, 1.0), 0.0, 1.0)
        return round(((normalized * GAIN_RANGE_DB) + GAIN_MIN_DB) * 10.0) / 10.0

    def selected_frequency_label(self) -> str:
        if self.frequency >= 1000.0:
            return f"{self.frequency / 1000.0:.2g} kHz"
        return f"{self.frequency:.0f} Hz"

    def compact_filter_type_label(self) -> str:
        return FILTER_TYPE_SHORT_LABELS.get(self.filter_type_label, self.filter_type_label[:5])

    def compact_q_label(self) -> str:
        if self.q_value >= 10.0:
            return f"Q {self.q_value:.1f}"
        return f"Q {self.q_value:.2f}"

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

    def draw_micro_badge(
        self,
        cr,
        label: str,
        x: float,
        y: float,
        *,
        active: bool,
        alpha: float,
        color: tuple[float, float, float],
    ) -> None:
        width = 16.0
        height = 12.0
        rounded_rectangle(cr, x, y, width, height, 5.0)
        if active:
            cr.set_source_rgba(*color, 0.25 * alpha)
            cr.fill_preserve()
            cr.set_source_rgba(*color, 0.55 * alpha)
            cr.set_line_width(1.0)
            cr.stroke()
            text_color = (0.94, 0.97, 1.0)
        else:
            cr.set_source_rgba(1.0, 1.0, 1.0, 0.035 * alpha)
            cr.fill_preserve()
            cr.set_source_rgba(1.0, 1.0, 1.0, 0.08 * alpha)
            cr.set_line_width(1.0)
            cr.stroke()
            text_color = (0.50, 0.57, 0.64)
        self.draw_text(cr, label, x + (width / 2.0), y + 9.4, 7.6, text_color, bold=True)

    def on_draw(self, _area: Gtk.DrawingArea, cr, width: int, height: int) -> None:
        width_f = float(width)
        height_f = float(height)
        center_x = width_f / 2.0
        effective = self.active and not self.muted and (not self.solo_active or self.soloed)
        alpha = 1.0 if effective else 0.48
        engaged = self.selected or self.hovered or self.focused or self.dragging_gain

        if engaged:
            rounded_rectangle(cr, 2.0, 2.0, width_f - 4.0, height_f - 4.0, 15.0)
            if self.selected:
                cr.set_source_rgba(1.0, 1.0, 1.0, 0.036 * alpha)
            else:
                cr.set_source_rgba(1.0, 1.0, 1.0, 0.045 * alpha)
            cr.fill_preserve()
            border_alpha = 0.34 if self.selected else 0.15
            if self.focused:
                border_alpha = max(border_alpha, 0.34)
            if self.selected:
                cr.set_source_rgba(*FOCUS_BLUE, border_alpha * alpha)
            else:
                cr.set_source_rgba(0.82, 0.88, 0.94, border_alpha * alpha)
            cr.set_line_width(1.0)
            cr.stroke()

        self.draw_text(cr, str(self.index + 1), center_x, 16.0, 9.5, (0.82, 0.86, 0.90), bold=True)

        type_color = FOCUS_BLUE_LIGHT if self.selected else (0.66, 0.72, 0.78)
        if not self.active:
            type_color = (0.50, 0.56, 0.62)
        self.draw_text(cr, self.compact_filter_type_label(), center_x, 31.0, 8.6, type_color, bold=True)

        gain_text = f"{self.gain_db:+.1f} dB"
        gain_width = 58.0
        rounded_rectangle(cr, center_x - gain_width / 2.0, 37.0, gain_width, 18.0, 8.0)
        if self.selected:
            cr.set_source_rgba(*FOCUS_BLUE_DARK, 0.30 * alpha)
        else:
            cr.set_source_rgba(1.0, 1.0, 1.0, 0.07 * alpha)
        cr.fill()
        gain_color = FOCUS_BLUE_LIGHT if self.selected else (0.90, 0.94, 0.98)
        if not self.active:
            gain_color = (0.62, 0.68, 0.74)
        self.draw_text(cr, gain_text, center_x, 50.0, 8.8, gain_color, bold=True)

        track_top = 74.0
        track_bottom = height_f - 58.0
        track_x = center_x - 3.5
        track_width = 7.0
        knob_y = self.gain_to_y(self.gain_db, track_top, track_bottom)
        zero_y = self.gain_to_y(0.0, track_top, track_bottom)

        rounded_rectangle(cr, track_x - 2.0, track_top - 1.0, track_width + 4.0, track_bottom - track_top + 2.0, 6.0)
        cr.set_source_rgba(0.02, 0.03, 0.045, 0.42 * alpha)
        cr.fill()

        rounded_rectangle(cr, track_x, track_top, track_width, track_bottom - track_top, 3.5)
        track_gradient = cairo.LinearGradient(0, track_top, 0, track_bottom)
        track_gradient.add_color_stop_rgba(0.0, 0.20, 0.26, 0.34, 0.82 * alpha)
        track_gradient.add_color_stop_rgba(1.0, 0.10, 0.14, 0.20, 0.82 * alpha)
        cr.set_source(track_gradient)
        cr.fill()

        fill_top = min(knob_y, zero_y)
        fill_bottom = max(knob_y, zero_y)
        if fill_bottom - fill_top < 2.0:
            fill_bottom = fill_top + 2.0
        rounded_rectangle(cr, track_x, fill_top, track_width, fill_bottom - fill_top, 4.0)
        fill_gradient = cairo.LinearGradient(0, fill_top, 0, fill_bottom)
        if self.selected or self.dragging_gain:
            fill_gradient.add_color_stop_rgba(0.0, 0.48, 0.72, 0.98, 0.82 * alpha)
            fill_gradient.add_color_stop_rgba(1.0, 0.30, 0.58, 0.88, 0.82 * alpha)
        else:
            fill_gradient.add_color_stop_rgba(0.0, 0.58, 0.68, 0.78, 0.52 * alpha)
            fill_gradient.add_color_stop_rgba(1.0, 0.38, 0.48, 0.60, 0.52 * alpha)
        cr.set_source(fill_gradient)
        cr.fill()

        for tick_gain in (-24.0, -12.0, 0.0, 12.0, 24.0):
            tick_y = self.gain_to_y(tick_gain, track_top, track_bottom)
            tick_alpha = 0.32 if tick_gain == 0.0 else 0.14
            cr.set_source_rgba(0.82, 0.88, 0.94, tick_alpha * alpha)
            cr.set_line_width(1.15 if tick_gain == 0.0 else 1.0)
            cr.move_to(center_x + 9.0, tick_y)
            cr.line_to(center_x + (20.0 if tick_gain == 0.0 else 14.0), tick_y)
            cr.stroke()
            if tick_gain == 0.0:
                cr.move_to(center_x - 20.0, tick_y)
                cr.line_to(center_x - 9.0, tick_y)
                cr.stroke()

        knob_width = 26.0 if self.selected or self.dragging_gain else 24.0
        knob_height = 16.0
        knob_x = center_x - (knob_width / 2.0)
        knob_y_top = knob_y - (knob_height / 2.0)

        rounded_rectangle(cr, knob_x + 1.0, knob_y_top + 2.0, knob_width, knob_height, 5.0)
        cr.set_source_rgba(0.0, 0.0, 0.0, 0.28 * alpha)
        cr.fill()

        rounded_rectangle(cr, knob_x, knob_y_top, knob_width, knob_height, 5.0)
        if self.selected or self.dragging_gain:
            cr.set_source_rgba(0.42, 0.69, 0.96, 0.98 * alpha)
        else:
            cr.set_source_rgba(0.70, 0.77, 0.84, 0.98 * alpha)
        cr.fill_preserve()
        cr.set_source_rgba(0.0, 0.0, 0.0, 0.28 * alpha)
        cr.set_line_width(1.0)
        cr.stroke()
        cr.set_source_rgba(1.0, 1.0, 1.0, 0.24 * alpha)
        cr.set_line_width(1.0)
        cr.move_to(center_x - 7.0, knob_y)
        cr.line_to(center_x + 7.0, knob_y)
        cr.stroke()

        overview_freq_color = (0.76, 0.81, 0.86) if self.active else (0.54, 0.59, 0.64)
        if self.selected:
            overview_freq_color = FOCUS_BLUE_LIGHT
        self.draw_text(cr, self.selected_frequency_label(), center_x, height_f - 38.0, 8.9, overview_freq_color)

        q_color = (0.62, 0.68, 0.74) if self.active else (0.46, 0.52, 0.58)
        if self.selected:
            q_color = (0.78, 0.88, 0.98)
        self.draw_text(cr, self.compact_q_label(), center_x, height_f - 23.0, 8.5, q_color)

        badge_y = height_f - 18.0
        self.draw_micro_badge(
            cr,
            "M",
            center_x - 18.0,
            badge_y,
            active=self.muted,
            alpha=alpha,
            color=(0.96, 0.42, 0.42),
        )
        self.draw_micro_badge(
            cr,
            "S",
            center_x + 2.0,
            badge_y,
            active=self.soloed,
            alpha=alpha,
            color=FOCUS_BLUE,
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
        usable_height = max(float(self.get_allocated_height()) - 126.0, 1.0)
        multiplier = self.interaction_multiplier_for_state(state)
        gain = self.drag_start_gain_db - ((offset_y / usable_height) * GAIN_RANGE_DB * multiplier)
        gain = round(clamp(gain, GAIN_MIN_DB, GAIN_MAX_DB) * 10.0) / 10.0
        if gain != self.gain_db:
            self.gain_changed_callback(self.index, gain)

    def on_drag_begin(self, _gesture: Gtk.GestureDrag, x: float, y: float) -> None:
        self.grab_focus()
        self.pointer_x = x
        self.pointer_y = y
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

    def on_motion(self, _controller: Gtk.EventControllerMotion, x: float, y: float) -> None:
        self.pointer_x = x
        self.pointer_y = y

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
            return True

        return False

    def on_click_pressed(self, _gesture: Gtk.GestureClick, _press_count: int, _x: float, _y: float) -> None:
        self.grab_focus()
        self.select_callback(self.index)
