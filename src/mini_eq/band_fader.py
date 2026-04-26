from __future__ import annotations

import math
from collections.abc import Callable

import cairo
import gi

gi.require_version("Gdk", "4.0")
gi.require_version("Gtk", "4.0")

from gi.repository import Gdk, Gtk

from .core import (
    EQ_FREQUENCY_MAX_HZ,
    EQ_FREQUENCY_MIN_HZ,
    EQ_GAIN_MAX_DB,
    EQ_GAIN_MIN_DB,
    EQ_Q_MAX,
    EQ_Q_MIN,
    clamp,
)
from .filter_glyph import draw_filter_glyph

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
FREQUENCY_MIN_HZ = EQ_FREQUENCY_MIN_HZ
FREQUENCY_MAX_HZ = EQ_FREQUENCY_MAX_HZ
Q_MIN = EQ_Q_MIN
Q_MAX = EQ_Q_MAX
SCRUB_PIXELS_PER_OCTAVE = 96.0
SCRUB_FINE_PIXELS_PER_OCTAVE = 260.0
SCRUB_COARSE_PIXELS_PER_OCTAVE = 42.0
SCROLL_OCTAVE_STEP = 1.0 / 12.0
SCROLL_FINE_OCTAVE_STEP = 1.0 / 48.0
SCROLL_COARSE_OCTAVE_STEP = 1.0 / 3.0

HitRect = tuple[float, float, float, float]


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
        frequency_changed_callback: Callable[[int, float], None],
        q_changed_callback: Callable[[int, float], None],
        mute_toggled_callback: Callable[[int, bool], None],
        solo_toggled_callback: Callable[[int, bool], None],
        edit_requested_callback: Callable[[int, str, Gtk.Widget], None],
    ) -> None:
        super().__init__()
        self.index = index
        self.select_callback = select_callback
        self.gain_changed_callback = gain_changed_callback
        self.frequency_changed_callback = frequency_changed_callback
        self.q_changed_callback = q_changed_callback
        self.mute_toggled_callback = mute_toggled_callback
        self.solo_toggled_callback = solo_toggled_callback
        self.edit_requested_callback = edit_requested_callback
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
        self.drag_start_frequency = 0.0
        self.drag_start_q = 0.0
        self.active_drag_target = "gain"
        self.focus_target = "gain"
        self.hover_target = "gain"
        self.hit_rects: dict[str, HitRect] = {}
        self.dragging_gain = False
        self.dragging_parameter = False

        self.set_content_width(72)
        self.set_content_height(230)
        self.set_hexpand(False)
        self.set_focusable(True)
        self.set_accessible_role(Gtk.AccessibleRole.SLIDER)
        self.set_cursor_from_name("ns-resize")
        self.set_tooltip_text("Drag gain. Drag/scroll Freq or Q on the selected band. Double-click a value to type it.")
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

    def register_hit_rect(self, name: str, x: float, y: float, width: float, height: float) -> None:
        self.hit_rects[name] = (x, y, width, height)

    def hit_test(self, x: float, y: float) -> str:
        for name in ("mute", "solo"):
            rect = self.hit_rects.get(name)
            if rect is not None and self.rect_contains(rect, x, y):
                return name

        if self.selected:
            for name in ("type", "q", "frequency"):
                rect = self.hit_rects.get(name)
                if rect is not None and self.rect_contains(rect, x, y):
                    return name

        return "gain"

    def rect_contains(self, rect: HitRect, x: float, y: float) -> bool:
        rect_x, rect_y, rect_width, rect_height = rect
        return rect_x <= x <= rect_x + rect_width and rect_y <= y <= rect_y + rect_height

    def selected_frequency_label(self) -> str:
        if self.frequency >= 1000.0:
            return f"{self.frequency / 1000.0:.2g} kHz"
        return f"{self.frequency:.0f} Hz"

    def selected_q_label(self) -> str:
        return f"Q {self.q_value:.3g}"

    def draw_pill(
        self,
        cr,
        text: str,
        x: float,
        y: float,
        width: float,
        height: float,
        *,
        selected: bool,
        active: bool,
    ) -> None:
        rounded_rectangle(cr, x, y, width, height, height / 2.0)
        if selected:
            cr.set_source_rgba(1.0, 0.63, 0.18, 0.18 if active else 0.08)
        else:
            cr.set_source_rgba(1.0, 1.0, 1.0, 0.06 if active else 0.035)
        cr.fill_preserve()
        border_alpha = 0.22 if selected else 0.08
        cr.set_source_rgba(1.0, 0.72, 0.32, border_alpha if active else border_alpha * 0.55)
        cr.set_line_width(1.0)
        cr.stroke()
        color = (1.0, 0.82, 0.48) if selected else (0.78, 0.83, 0.88)
        if not active:
            color = (0.56, 0.62, 0.68)
        self.draw_text(cr, text, x + width / 2.0, y + height - 6.0, 8.9, color, bold=selected)

    def draw_type_pill(
        self,
        cr,
        x: float,
        y: float,
        width: float,
        height: float,
        *,
        selected: bool,
        active: bool,
    ) -> None:
        rounded_rectangle(cr, x, y, width, height, height / 2.0)
        if selected:
            cr.set_source_rgba(1.0, 0.63, 0.18, 0.18 if active else 0.08)
        else:
            cr.set_source_rgba(1.0, 1.0, 1.0, 0.035 if active else 0.020)
        cr.fill_preserve()
        cr.set_source_rgba(1.0, 0.72, 0.32, (0.22 if selected else 0.06) if active else 0.04)
        cr.set_line_width(1.0)
        cr.stroke()

        glyph_width = 24.0 if selected else 18.0
        glyph_height = 10.0 if selected else 8.0
        glyph_x = x + (width - glyph_width) / 2.0
        if selected:
            glyph_x -= 4.0
        glyph_y = y + (height - glyph_height) / 2.0
        glyph_color = (1.0, 0.78, 0.42, 0.94) if selected else (0.64, 0.70, 0.76, 0.62)
        if not active:
            glyph_color = (0.48, 0.53, 0.58, 0.48)
        draw_filter_glyph(
            cr,
            self.filter_type,
            glyph_x,
            glyph_y,
            glyph_width,
            glyph_height,
            glyph_color,
            gain_db=self.gain_db,
            line_width=1.35 if selected else 1.0,
        )

        if selected:
            caret_x = x + width - 11.0
            caret_y = y + (height / 2.0) + 1.0
            cr.set_source_rgba(1.0, 0.78, 0.42, 0.82)
            cr.set_line_width(1.2)
            cr.move_to(caret_x - 3.0, caret_y - 2.0)
            cr.line_to(caret_x, caret_y + 1.5)
            cr.line_to(caret_x + 3.0, caret_y - 2.0)
            cr.stroke()

    def draw_state_button(
        self,
        cr,
        text: str,
        x: float,
        y: float,
        width: float,
        height: float,
        *,
        pressed: bool,
        hovered: bool,
        solo: bool,
        effective: bool,
    ) -> None:
        rounded_rectangle(cr, x, y, width, height, 5.0)
        if pressed:
            if solo:
                cr.set_source_rgba(0.45, 0.78, 1.0, 0.34 if effective else 0.24)
            else:
                cr.set_source_rgba(1.0, 0.48, 0.26, 0.34)
        else:
            cr.set_source_rgba(1.0, 1.0, 1.0, 0.055 if effective else 0.030)
        cr.fill_preserve()

        if pressed:
            border = (0.62, 0.88, 1.0) if solo else (1.0, 0.62, 0.36)
            cr.set_source_rgba(*border, 0.58)
        elif hovered:
            cr.set_source_rgba(1.0, 0.72, 0.32, 0.32)
        else:
            cr.set_source_rgba(1.0, 1.0, 1.0, 0.08 if effective else 0.05)
        cr.set_line_width(1.0)
        cr.stroke()

        if pressed:
            color = (0.94, 0.98, 1.0) if solo else (1.0, 0.90, 0.82)
        elif effective:
            color = (0.70, 0.76, 0.82)
        else:
            color = (0.48, 0.54, 0.60)
        self.draw_text(cr, text, x + width / 2.0, y + height - 4.5, 8.0, color, bold=pressed)

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

    def on_draw(self, _area: Gtk.DrawingArea, cr, width: int, height: int) -> None:
        self.hit_rects = {}
        width_f = float(width)
        height_f = float(height)
        center_x = width_f / 2.0
        effective = self.active and not self.muted and (not self.solo_active or self.soloed)
        alpha = 1.0 if effective else 0.48
        engaged = self.selected or self.hovered or self.focused or self.dragging_gain

        if engaged:
            rounded_rectangle(cr, 2.0, 2.0, width_f - 4.0, height_f - 4.0, 15.0)
            if self.selected:
                cr.set_source_rgba(1.0, 0.64, 0.18, 0.11 * alpha)
            else:
                cr.set_source_rgba(1.0, 1.0, 1.0, 0.045 * alpha)
            cr.fill_preserve()
            border_alpha = 0.42 if self.selected else 0.16
            if self.focused:
                border_alpha = max(border_alpha, 0.34)
            cr.set_source_rgba(1.0, 0.68, 0.26, border_alpha * alpha)
            cr.set_line_width(1.2 if self.selected else 1.0)
            cr.stroke()

        self.draw_text(cr, str(self.index + 1), center_x, 18.0, 10.0, (0.82, 0.86, 0.90), bold=True)

        gain_text = f"{self.gain_db:+.1f} dB"
        gain_width = 58.0
        rounded_rectangle(cr, center_x - gain_width / 2.0, 27.0, gain_width, 19.0, 9.0)
        if self.selected:
            cr.set_source_rgba(1.0, 0.70, 0.30, 0.22 * alpha)
        else:
            cr.set_source_rgba(1.0, 1.0, 1.0, 0.07 * alpha)
        cr.fill()
        gain_color = (1.0, 0.84, 0.55) if self.selected else (0.90, 0.94, 0.98)
        if not self.active:
            gain_color = (0.62, 0.68, 0.74)
        self.draw_text(cr, gain_text, center_x, 41.0, 9.0, gain_color, bold=True)

        state_button_y = 50.0
        state_button_width = 23.0
        state_button_height = 14.0
        mute_x = center_x - state_button_width - 2.5
        solo_x = center_x + 2.5
        self.register_hit_rect("mute", mute_x, state_button_y, state_button_width, state_button_height)
        self.register_hit_rect("solo", solo_x, state_button_y, state_button_width, state_button_height)
        self.draw_state_button(
            cr,
            "M",
            mute_x,
            state_button_y,
            state_button_width,
            state_button_height,
            pressed=self.muted,
            hovered=self.hover_target == "mute" or self.focus_target == "mute",
            solo=False,
            effective=effective,
        )
        self.draw_state_button(
            cr,
            "S",
            solo_x,
            state_button_y,
            state_button_width,
            state_button_height,
            pressed=self.soloed,
            hovered=self.hover_target == "solo" or self.focus_target == "solo",
            solo=True,
            effective=effective,
        )

        track_top = 75.0
        track_bottom = height_f - 92.0
        track_x = center_x - 3.5
        track_width = 7.0
        knob_y = self.gain_to_y(self.gain_db, track_top, track_bottom)
        zero_y = self.gain_to_y(0.0, track_top, track_bottom)
        self.register_hit_rect("gain", 0.0, 0.0, width_f, max(track_bottom + 16.0, 1.0))

        rounded_rectangle(cr, track_x - 2.0, track_top - 1.0, track_width + 4.0, track_bottom - track_top + 2.0, 6.0)
        cr.set_source_rgba(0.02, 0.03, 0.045, 0.45 * alpha)
        cr.fill()

        rounded_rectangle(cr, track_x, track_top, track_width, track_bottom - track_top, 3.5)
        track_gradient = cairo.LinearGradient(0, track_top, 0, track_bottom)
        track_gradient.add_color_stop_rgba(0.0, 0.20, 0.26, 0.33, 0.86 * alpha)
        track_gradient.add_color_stop_rgba(1.0, 0.10, 0.14, 0.19, 0.86 * alpha)
        cr.set_source(track_gradient)
        cr.fill()

        fill_top = min(knob_y, zero_y)
        fill_bottom = max(knob_y, zero_y)
        if fill_bottom - fill_top < 2.0:
            fill_bottom = fill_top + 2.0
        rounded_rectangle(cr, track_x, fill_top, track_width, fill_bottom - fill_top, 4.0)
        fill_gradient = cairo.LinearGradient(0, fill_top, 0, fill_bottom)
        fill_gradient.add_color_stop_rgba(0.0, 1.0, 0.76, 0.28, 0.95 * alpha)
        fill_gradient.add_color_stop_rgba(1.0, 1.0, 0.44, 0.08, 0.95 * alpha)
        cr.set_source(fill_gradient)
        cr.fill()

        for tick_gain in (-24.0, -12.0, 0.0, 12.0, 24.0):
            tick_y = self.gain_to_y(tick_gain, track_top, track_bottom)
            cr.set_source_rgba(0.82, 0.88, 0.94, (0.30 if tick_gain == 0.0 else 0.18) * alpha)
            cr.set_line_width(1.0)
            cr.move_to(center_x + 9.0, tick_y)
            cr.line_to(center_x + (17.0 if tick_gain == 0.0 else 14.0), tick_y)
            cr.stroke()
            if tick_gain == 0.0:
                cr.move_to(center_x - 17.0, tick_y)
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
        knob_gradient = cairo.LinearGradient(0, knob_y_top, 0, knob_y_top + knob_height)
        if self.selected or self.dragging_gain:
            knob_gradient.add_color_stop_rgba(0.0, 1.0, 0.72, 0.32, 0.98 * alpha)
            knob_gradient.add_color_stop_rgba(1.0, 0.85, 0.43, 0.12, 0.98 * alpha)
        else:
            knob_gradient.add_color_stop_rgba(0.0, 0.92, 0.96, 1.0, 0.98 * alpha)
            knob_gradient.add_color_stop_rgba(1.0, 0.66, 0.72, 0.78, 0.98 * alpha)
        cr.set_source(knob_gradient)
        cr.fill_preserve()
        cr.set_source_rgba(0.0, 0.0, 0.0, 0.34 * alpha)
        cr.set_line_width(1.0)
        cr.stroke()
        cr.set_source_rgba(1.0, 1.0, 1.0, 0.42 * alpha)
        cr.set_line_width(1.0)
        cr.move_to(center_x - 7.0, knob_y)
        cr.line_to(center_x + 7.0, knob_y)
        cr.stroke()

        if self.selected:
            pill_x = 7.0
            pill_width = width_f - 14.0
            frequency_y = height_f - 78.0
            q_y = height_f - 53.0
            type_y = height_f - 28.0
            self.register_hit_rect("frequency", pill_x, frequency_y, pill_width, 19.0)
            self.register_hit_rect("q", pill_x, q_y, pill_width, 19.0)
            self.register_hit_rect("type", pill_x, type_y, pill_width, 20.0)
            self.draw_pill(
                cr,
                self.selected_frequency_label(),
                pill_x,
                frequency_y,
                pill_width,
                19.0,
                selected=self.hover_target == "frequency" or self.focus_target == "frequency",
                active=self.active,
            )
            self.draw_pill(
                cr,
                self.selected_q_label(),
                pill_x,
                q_y,
                pill_width,
                19.0,
                selected=self.hover_target == "q" or self.focus_target == "q",
                active=self.active,
            )
            self.draw_type_pill(
                cr,
                pill_x,
                type_y,
                pill_width,
                20.0,
                selected=self.hover_target == "type" or self.focus_target == "type",
                active=self.active,
            )
        else:
            overview_freq_color = (0.72, 0.77, 0.82) if self.active else (0.54, 0.59, 0.64)
            overview_q_color = (0.60, 0.66, 0.72) if self.active else (0.46, 0.51, 0.56)
            self.draw_text(cr, self.selected_frequency_label(), center_x, height_f - 61.0, 8.7, overview_freq_color)
            self.draw_text(cr, self.selected_q_label(), center_x, height_f - 41.0, 8.0, overview_q_color)
            type_width = 42.0
            self.draw_type_pill(
                cr,
                center_x - type_width / 2.0,
                height_f - 29.0,
                type_width,
                17.0,
                selected=self.hover_target == "type" or self.focus_target == "type",
                active=self.active,
            )

    def interaction_multiplier_for_state(self, state: Gdk.ModifierType) -> float:
        if state & Gdk.ModifierType.SHIFT_MASK:
            return GAIN_DRAG_FINE_MULTIPLIER
        if state & Gdk.ModifierType.CONTROL_MASK:
            return GAIN_DRAG_COARSE_MULTIPLIER
        return 1.0

    def scrub_pixels_per_octave_for_state(self, state: Gdk.ModifierType) -> float:
        if state & Gdk.ModifierType.SHIFT_MASK:
            return SCRUB_FINE_PIXELS_PER_OCTAVE
        if state & Gdk.ModifierType.CONTROL_MASK:
            return SCRUB_COARSE_PIXELS_PER_OCTAVE
        return SCRUB_PIXELS_PER_OCTAVE

    def scroll_octave_step_for_state(self, state: Gdk.ModifierType) -> float:
        if state & Gdk.ModifierType.SHIFT_MASK:
            return SCROLL_FINE_OCTAVE_STEP
        if state & Gdk.ModifierType.CONTROL_MASK:
            return SCROLL_COARSE_OCTAVE_STEP
        return SCROLL_OCTAVE_STEP

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

    def frequency_from_octaves(self, base_frequency: float, octaves: float) -> float:
        frequency = clamp(base_frequency * math.pow(2.0, octaves), FREQUENCY_MIN_HZ, FREQUENCY_MAX_HZ)
        return round(frequency * 100.0) / 100.0

    def q_from_octaves(self, base_q: float, octaves: float) -> float:
        q_value = clamp(max(base_q, Q_MIN) * math.pow(2.0, octaves), Q_MIN, Q_MAX)
        return round(q_value * 1000.0) / 1000.0

    def update_frequency_from_drag(self, offset_x: float, state: Gdk.ModifierType) -> None:
        octaves = offset_x / self.scrub_pixels_per_octave_for_state(state)
        frequency = self.frequency_from_octaves(self.drag_start_frequency, octaves)
        if frequency != self.frequency:
            self.frequency_changed_callback(self.index, frequency)

    def update_q_from_drag(self, offset_x: float, state: Gdk.ModifierType) -> None:
        octaves = offset_x / self.scrub_pixels_per_octave_for_state(state)
        q_value = self.q_from_octaves(self.drag_start_q, octaves)
        if q_value != self.q_value:
            self.q_changed_callback(self.index, q_value)

    def on_drag_begin(self, _gesture: Gtk.GestureDrag, x: float, y: float) -> None:
        self.grab_focus()
        self.pointer_x = x
        self.pointer_y = y
        self.active_drag_target = self.hit_test(x, y)
        self.focus_target = self.active_drag_target
        self.drag_start_gain_db = self.gain_db
        self.drag_start_frequency = self.frequency
        self.drag_start_q = self.q_value
        self.dragging_gain = False
        self.dragging_parameter = False
        self.select_callback(self.index)
        self.queue_draw()

    def on_drag_update(self, gesture: Gtk.GestureDrag, offset_x: float, offset_y: float) -> None:
        if self.active_drag_target in {"type", "mute", "solo"}:
            return

        if not self.dragging_gain and not self.dragging_parameter:
            if math.hypot(offset_x, offset_y) < DRAG_THRESHOLD_PX:
                return
            self.dragging_gain = self.active_drag_target == "gain"
            self.dragging_parameter = self.active_drag_target in {"frequency", "q"}

        state = gesture.get_current_event_state()
        if self.active_drag_target == "frequency":
            self.update_frequency_from_drag(offset_x, state)
        elif self.active_drag_target == "q":
            self.update_q_from_drag(offset_x, state)
        else:
            self.update_gain_from_drag(offset_y, state)

    def on_drag_end(self, _gesture: Gtk.GestureDrag, _offset_x: float, _offset_y: float) -> None:
        if not (self.dragging_gain or self.dragging_parameter) and self.active_drag_target == "type" and self.selected:
            self.edit_requested_callback(self.index, "type", self)
        self.dragging_gain = False
        self.dragging_parameter = False
        self.queue_draw()

    def apply_direct_gain_delta(self, delta_db: float) -> None:
        self.grab_focus()
        self.select_callback(self.index)
        gain = round(clamp(self.gain_db + delta_db, GAIN_MIN_DB, GAIN_MAX_DB) * 10.0) / 10.0
        if gain != self.gain_db:
            self.gain_changed_callback(self.index, gain)

    def apply_direct_frequency_octaves(self, octaves: float) -> None:
        self.grab_focus()
        self.select_callback(self.index)
        frequency = self.frequency_from_octaves(self.frequency, octaves)
        if frequency != self.frequency:
            self.frequency_changed_callback(self.index, frequency)

    def apply_direct_q_octaves(self, octaves: float) -> None:
        self.grab_focus()
        self.select_callback(self.index)
        q_value = self.q_from_octaves(self.q_value, octaves)
        if q_value != self.q_value:
            self.q_changed_callback(self.index, q_value)

    def on_motion_enter(self, _controller: Gtk.EventControllerMotion, _x: float, _y: float) -> None:
        self.hovered = True
        self.queue_draw()

    def on_motion(self, _controller: Gtk.EventControllerMotion, x: float, y: float) -> None:
        self.pointer_x = x
        self.pointer_y = y
        hover_target = self.hit_test(x, y)
        if hover_target != self.hover_target:
            self.hover_target = hover_target
            if hover_target in {"frequency", "q"}:
                self.set_cursor_from_name("ew-resize")
            elif hover_target in {"type", "mute", "solo"}:
                self.set_cursor_from_name("pointer")
            else:
                self.set_cursor_from_name("ns-resize")
            self.queue_draw()

    def on_motion_leave(self, _controller: Gtk.EventControllerMotion) -> None:
        self.hovered = False
        self.hover_target = "gain"
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
        if self.selected and self.hover_target in {"frequency", "q"}:
            octaves = self.scroll_octave_step_for_state(state)
            if dy > 0.0:
                octaves = -octaves
            if self.hover_target == "frequency":
                self.focus_target = "frequency"
                self.apply_direct_frequency_octaves(octaves)
            else:
                self.focus_target = "q"
                self.apply_direct_q_octaves(octaves)
        else:
            step = self.direct_step_for_state(state)
            self.focus_target = "gain"
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
        octave_step = self.scroll_octave_step_for_state(state)
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
            if self.focus_target in {"frequency", "q"}:
                direction = 1.0 if key_deltas[keyval] > 0.0 else -1.0
                if self.focus_target == "frequency":
                    self.apply_direct_frequency_octaves(octave_step * direction)
                else:
                    self.apply_direct_q_octaves(octave_step * direction)
            else:
                self.apply_direct_gain_delta(key_deltas[keyval])
            return True

        if keyval in (Gdk.KEY_0, Gdk.KEY_KP_0, Gdk.KEY_Home):
            self.grab_focus()
            self.select_callback(self.index)
            if self.focus_target == "q":
                if self.q_value != 1.0:
                    self.q_changed_callback(self.index, 1.0)
            elif self.focus_target == "frequency":
                return True
            elif self.gain_db != 0.0:
                self.gain_changed_callback(self.index, 0.0)
            return True

        if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter, Gdk.KEY_space):
            self.grab_focus()
            self.select_callback(self.index)
            if self.focus_target == "mute":
                self.mute_toggled_callback(self.index, not self.muted)
                return True
            if self.focus_target == "solo":
                self.solo_toggled_callback(self.index, not self.soloed)
                return True
            if self.focus_target in {"frequency", "q", "type"}:
                self.edit_requested_callback(self.index, self.focus_target, self)
            return True

        return False

    def on_click_pressed(self, _gesture: Gtk.GestureClick, press_count: int, x: float, y: float) -> None:
        target = self.hit_test(x, y)
        self.focus_target = target
        if press_count == 1 and target == "mute":
            self.grab_focus()
            self.select_callback(self.index)
            self.mute_toggled_callback(self.index, not self.muted)
            return
        if press_count == 1 and target == "solo":
            self.grab_focus()
            self.select_callback(self.index)
            self.solo_toggled_callback(self.index, not self.soloed)
            return
        if press_count >= 2 and target in {"frequency", "q"}:
            self.grab_focus()
            self.select_callback(self.index)
            self.edit_requested_callback(self.index, target, self)
