from __future__ import annotations

import cairo

from .core import FILTER_TYPES


def _points_for_shelf(
    gain_db: float, high_side: bool, x: float, y: float, width: float, height: float
) -> tuple[float, float]:
    mid = y + height * 0.50
    high = y + height * 0.22
    low = y + height * 0.78
    shelf_y = high if gain_db >= 0.0 else low
    return (mid, shelf_y) if high_side else (shelf_y, mid)


def draw_filter_glyph(
    cr,
    filter_type: int,
    x: float,
    y: float,
    width: float,
    height: float,
    rgba: tuple[float, float, float, float],
    *,
    gain_db: float = 0.0,
    line_width: float = 1.2,
) -> None:
    left = x
    right = x + width
    top = y
    bottom = y + height
    mid_y = y + height * 0.50
    center_x = x + width * 0.50
    peak_y = y + (height * (0.18 if gain_db >= 0.0 else 0.82))
    opposite_y = y + (height * (0.82 if gain_db >= 0.0 else 0.18))

    cr.save()
    cr.set_source_rgba(*rgba)
    cr.set_line_width(line_width)
    cr.set_line_cap(cairo.LINE_CAP_ROUND)
    cr.set_line_join(cairo.LINE_JOIN_ROUND)

    if filter_type == FILTER_TYPES["Off"]:
        cr.move_to(left + width * 0.22, mid_y)
        cr.line_to(right - width * 0.22, mid_y)
    elif filter_type in (FILTER_TYPES["Bell"], FILTER_TYPES["Resonance"]):
        cr.move_to(left, mid_y)
        cr.curve_to(left + width * 0.20, mid_y, left + width * 0.28, peak_y, center_x, peak_y)
        cr.curve_to(right - width * 0.28, peak_y, right - width * 0.20, mid_y, right, mid_y)
    elif filter_type == FILTER_TYPES["Notch"]:
        cr.move_to(left, mid_y)
        cr.curve_to(left + width * 0.22, mid_y, left + width * 0.34, bottom, center_x, bottom)
        cr.curve_to(right - width * 0.34, bottom, right - width * 0.22, mid_y, right, mid_y)
    elif filter_type == FILTER_TYPES["Lo-pass"]:
        cr.move_to(left, top + height * 0.24)
        cr.line_to(left + width * 0.45, top + height * 0.24)
        cr.line_to(right, bottom - height * 0.20)
    elif filter_type == FILTER_TYPES["Hi-pass"]:
        cr.move_to(left, bottom - height * 0.20)
        cr.line_to(left + width * 0.55, top + height * 0.24)
        cr.line_to(right, top + height * 0.24)
    elif filter_type == FILTER_TYPES["Lo-shelf"]:
        left_y, right_y = _points_for_shelf(gain_db, False, x, y, width, height)
        cr.move_to(left, left_y)
        cr.curve_to(left + width * 0.28, left_y, left + width * 0.36, right_y, center_x, right_y)
        cr.line_to(right, right_y)
    elif filter_type == FILTER_TYPES["Hi-shelf"]:
        left_y, right_y = _points_for_shelf(gain_db, True, x, y, width, height)
        cr.move_to(left, left_y)
        cr.line_to(center_x, left_y)
        cr.curve_to(right - width * 0.36, left_y, right - width * 0.28, right_y, right, right_y)
    elif filter_type == FILTER_TYPES["Bandpass"]:
        cr.move_to(left, bottom - height * 0.22)
        cr.curve_to(
            left + width * 0.25,
            bottom - height * 0.22,
            left + width * 0.28,
            top + height * 0.18,
            center_x,
            top + height * 0.18,
        )
        cr.curve_to(
            right - width * 0.28,
            top + height * 0.18,
            right - width * 0.25,
            bottom - height * 0.22,
            right,
            bottom - height * 0.22,
        )
    elif filter_type == FILTER_TYPES["Allpass"]:
        cr.move_to(left, mid_y)
        cr.curve_to(
            left + width * 0.20, top + height * 0.22, left + width * 0.30, bottom - height * 0.22, center_x, mid_y
        )
        cr.curve_to(
            right - width * 0.30, top + height * 0.22, right - width * 0.20, bottom - height * 0.22, right, mid_y
        )
    else:
        cr.move_to(left, mid_y)
        cr.curve_to(left + width * 0.25, mid_y, left + width * 0.35, opposite_y, center_x, opposite_y)
        cr.curve_to(right - width * 0.35, opposite_y, right - width * 0.25, mid_y, right, mid_y)

    cr.stroke()
    cr.restore()
