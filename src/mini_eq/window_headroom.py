from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")

from gi.repository import Gtk, Pango

from .appearance import style_manager_is_dark
from .core import EQ_PREAMP_MAX_DB, EQ_PREAMP_MIN_DB, clamp
from .window_utils import set_accessible_label


class MiniEqWindowHeadroomMixin:
    def make_headroom_panel(self) -> Gtk.Box:
        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=7)
        panel.add_css_class("headroom-panel")
        self.headroom_panel = panel

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        title = Gtk.Label(label="Headroom", xalign=0.0)
        title.add_css_class("metric-title")
        header.append(title)

        header_spacer = Gtk.Box()
        header_spacer.set_hexpand(True)
        header.append(header_spacer)

        self.headroom_fix_button = Gtk.Button(label="Set Safe")
        self.headroom_fix_button.add_css_class("headroom-fix-button")
        self.headroom_fix_button.set_tooltip_text("Lower Preamp to Restore Headroom")
        self.headroom_fix_button.set_visible(False)
        self.headroom_fix_button.connect("clicked", self.on_set_safe_preamp_clicked)
        header.append(self.headroom_fix_button)

        self.headroom_peak_label = Gtk.Label(label="Peak --", xalign=1.0)
        self.headroom_peak_label.add_css_class("headroom-peak-chip")
        self.headroom_peak_label.add_css_class("numeric")
        header.append(self.headroom_peak_label)
        panel.append(header)

        self.headroom_state_label = Gtk.Label(label="EQ off", xalign=0.0)
        self.headroom_state_label.add_css_class("headroom-state")
        self.headroom_state_label.add_css_class("numeric")
        self.headroom_state_label.set_wrap(True)
        self.headroom_state_label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        panel.append(self.headroom_state_label)

        self.headroom_meter_area = Gtk.DrawingArea()
        self.headroom_meter_area.add_css_class("headroom-meter-area")
        self.headroom_meter_area.set_content_width(260)
        self.headroom_meter_area.set_content_height(14)
        self.headroom_meter_area.set_hexpand(True)
        self.headroom_meter_area.set_accessible_role(Gtk.AccessibleRole.IMG)
        set_accessible_label(self.headroom_meter_area, "Headroom Meter")
        self.headroom_meter_area.set_draw_func(self.on_headroom_meter_draw)
        panel.append(self.headroom_meter_area)

        self.headroom_detail_label = Gtk.Label(xalign=0.0)
        self.headroom_detail_label.add_css_class("headroom-detail")
        self.headroom_detail_label.add_css_class("dim-label")
        self.headroom_detail_label.set_wrap(True)
        self.headroom_detail_label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        panel.append(self.headroom_detail_label)

        preamp_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        preamp_row.add_css_class("headroom-preamp-row")
        preamp_title = Gtk.Label(label="Preamp", xalign=0.0)
        preamp_title.add_css_class("metric-title")
        preamp_row.append(preamp_title)

        self.preamp_scale = Gtk.Scale.new_with_range(
            Gtk.Orientation.HORIZONTAL,
            EQ_PREAMP_MIN_DB,
            EQ_PREAMP_MAX_DB,
            0.5,
        )
        self.preamp_scale.set_draw_value(False)
        self.preamp_scale.set_hexpand(True)
        set_accessible_label(self.preamp_scale, "Preamp")
        self.preamp_scale.connect("value-changed", self.on_preamp_changed)
        preamp_row.append(self.preamp_scale)

        self.preamp_label.add_css_class("numeric")
        preamp_row.append(self.preamp_label)
        panel.append(preamp_row)

        return panel

    def set_headroom_state(
        self,
        *,
        state: str,
        peak_text: str,
        detail: str,
        peak_db: float | None,
        kind: str,
    ) -> None:
        self.headroom_peak_db = peak_db
        self.headroom_state_kind = kind
        self.headroom_state_label.set_text(state)
        self.headroom_peak_label.set_text(peak_text)
        self.headroom_detail_label.set_text(detail)

        for css_class in ("headroom-safe", "headroom-tight", "headroom-risk", "headroom-bypass"):
            self.headroom_state_label.remove_css_class(css_class)
            self.headroom_peak_label.remove_css_class(css_class)

        state_class = f"headroom-{kind}"
        self.headroom_state_label.add_css_class(state_class)
        self.headroom_peak_label.add_css_class(state_class)

        if self.headroom_panel is not None:
            for css_class in (
                "headroom-panel-safe",
                "headroom-panel-tight",
                "headroom-panel-risk",
                "headroom-panel-bypass",
            ):
                self.headroom_panel.remove_css_class(css_class)
            self.headroom_panel.add_css_class(f"headroom-panel-{kind}")

        if self.headroom_fix_button is not None:
            self.headroom_fix_button.set_visible(kind == "risk")

        self.headroom_meter_area.queue_draw()

    def on_set_safe_preamp_clicked(self, _button: Gtk.Button) -> None:
        peak = self.estimate_curve_peak_db()
        if peak <= 0.5:
            return

        target_preamp = self.controller.preamp_db - peak - 1.0
        self.preamp_scale.set_value(target_preamp)
        self.set_status("Preamp Lowered for Safe Headroom")

    def on_headroom_meter_draw(self, _area: Gtk.DrawingArea, cr, width: int, height: int) -> None:
        width_f = float(max(width, 1))
        height_f = float(max(height, 1))
        track_y = max(2.0, (height_f - 8.0) / 2.0)
        track_height = min(8.0, height_f - 4.0)
        radius = track_height / 2.0
        peak = self.headroom_peak_db
        kind = getattr(self, "headroom_state_kind", "bypass")

        def rounded_rect(x: float, y: float, rect_width: float, rect_height: float, rect_radius: float) -> None:
            cr.new_sub_path()
            cr.arc(x + rect_width - rect_radius, y + rect_radius, rect_radius, -1.5708, 0.0)
            cr.arc(x + rect_width - rect_radius, y + rect_height - rect_radius, rect_radius, 0.0, 1.5708)
            cr.arc(x + rect_radius, y + rect_height - rect_radius, rect_radius, 1.5708, 3.1416)
            cr.arc(x + rect_radius, y + rect_radius, rect_radius, 3.1416, 4.7124)
            cr.close_path()

        def x_for_db(value: float) -> float:
            return width_f * clamp((value + 12.0) / 18.0, 0.0, 1.0)

        application = self.get_application()
        style_manager = application.get_style_manager() if application is not None else None
        dark = style_manager_is_dark(style_manager)
        track_alpha = 0.06 if dark else 0.14
        inactive_alpha = 0.20 if dark else 0.36
        zero_rgba = (0.05, 0.07, 0.10, 0.62) if dark else (0.16, 0.18, 0.21, 0.48)
        marker_rgba = (0.96, 0.98, 1.0, 0.98) if dark else (0.12, 0.15, 0.18, 0.98)

        rounded_rect(0.0, track_y, width_f, track_height, radius)
        cr.set_source_rgba(1.0, 1.0, 1.0, track_alpha)
        cr.fill()

        if kind == "bypass" or peak is None:
            cr.set_source_rgba(1.0, 1.0, 1.0, inactive_alpha)
            cr.set_line_width(1.0)
            cr.move_to(x_for_db(0.0), track_y - 1.0)
            cr.line_to(x_for_db(0.0), track_y + track_height + 1.0)
            cr.stroke()
            return

        segments = (
            (-12.0, -3.0, (0.38, 0.78, 0.50, 0.78)),
            (-3.0, 0.0, (0.58, 0.66, 0.76, 0.64)),
            (0.0, 6.0, (1.0, 0.35, 0.28, 0.86)),
        )
        cr.save()
        rounded_rect(0.0, track_y, width_f, track_height, radius)
        cr.clip()
        for left_db, right_db, color in segments:
            left = x_for_db(left_db)
            right = x_for_db(right_db)
            cr.rectangle(left, track_y, max(right - left, 1.0), track_height)
            cr.set_source_rgba(*color)
            cr.fill()
        cr.restore()

        zero_x = x_for_db(0.0)
        cr.set_source_rgba(*zero_rgba)
        cr.set_line_width(1.0)
        cr.move_to(zero_x, track_y - 1.0)
        cr.line_to(zero_x, track_y + track_height + 1.0)
        cr.stroke()

        marker_x = x_for_db(peak)
        cr.set_source_rgba(*marker_rgba)
        cr.arc(marker_x, track_y + (track_height / 2.0), 3.2, 0.0, 6.2832)
        cr.fill()
