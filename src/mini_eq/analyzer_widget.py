from __future__ import annotations

import math
from collections.abc import Sequence
from functools import lru_cache

import gi

gi.require_version("Gdk", "4.0")
gi.require_version("Gsk", "4.0")
gi.require_version("Gtk", "4.0")
gi.require_version("Graphene", "1.0")

from gi.repository import Gdk, GObject, Graphene, Gsk, Gtk

from .analyzer import (
    ANALYZER_BAND_FREQUENCIES,
    analyzer_band_edges,
    analyzer_bin_center_frequencies,
    analyzer_level_to_display_norm,
)
from .appearance import style_manager_is_dark
from .core import GRAPH_FREQ_MAX, GRAPH_FREQ_MIN, clamp

ANALYZER_DARK_BAR_COLOR = (0.33, 0.78, 0.90)
ANALYZER_DARK_LINE_COLOR = (0.58, 0.90, 0.98)
ANALYZER_DARK_BAR_ALPHA = 0.15
ANALYZER_DARK_BAR_ALPHA_INACTIVE = 0.06
ANALYZER_DARK_LINE_ALPHA = 0.32
ANALYZER_DARK_LINE_ALPHA_INACTIVE = 0.14
ANALYZER_LIGHT_BAR_COLOR = (0.03, 0.46, 0.60)
ANALYZER_LIGHT_LINE_COLOR = (0.00, 0.34, 0.50)
ANALYZER_LIGHT_BAR_ALPHA = 0.17
ANALYZER_LIGHT_BAR_ALPHA_INACTIVE = 0.07
ANALYZER_LIGHT_LINE_ALPHA = 0.36
ANALYZER_LIGHT_LINE_ALPHA_INACTIVE = 0.15


def analyzer_plot_palette(
    *,
    dark: bool,
    enabled: bool,
) -> tuple[tuple[float, float, float, float], tuple[float, float, float, float]]:
    if dark:
        bar_color = ANALYZER_DARK_BAR_COLOR
        line_color = ANALYZER_DARK_LINE_COLOR
        bar_alpha = ANALYZER_DARK_BAR_ALPHA if enabled else ANALYZER_DARK_BAR_ALPHA_INACTIVE
        line_alpha = ANALYZER_DARK_LINE_ALPHA if enabled else ANALYZER_DARK_LINE_ALPHA_INACTIVE
    else:
        bar_color = ANALYZER_LIGHT_BAR_COLOR
        line_color = ANALYZER_LIGHT_LINE_COLOR
        bar_alpha = ANALYZER_LIGHT_BAR_ALPHA if enabled else ANALYZER_LIGHT_BAR_ALPHA_INACTIVE
        line_alpha = ANALYZER_LIGHT_LINE_ALPHA if enabled else ANALYZER_LIGHT_LINE_ALPHA_INACTIVE

    return (*bar_color, bar_alpha), (*line_color, line_alpha)


def analyzer_frequency_to_x(frequency: float, width: float, left: float, right: float) -> float:
    usable = max(width - left - right, 1.0)
    position = (math.log10(clamp(frequency, GRAPH_FREQ_MIN, GRAPH_FREQ_MAX)) - math.log10(GRAPH_FREQ_MIN)) / (
        math.log10(GRAPH_FREQ_MAX) - math.log10(GRAPH_FREQ_MIN)
    )
    return left + (usable * position)


@lru_cache(maxsize=64)
def cached_analyzer_bar_geometry(
    width: float,
    left: float,
    right: float,
    count: int,
) -> tuple[tuple[float, float, float], ...]:
    plot_right = max(left + 1.0, width - right)
    if count <= 0:
        return ()

    if count == len(ANALYZER_BAND_FREQUENCIES):
        frequencies = ANALYZER_BAND_FREQUENCIES
    else:
        frequencies = analyzer_bin_center_frequencies(count)
    edges = analyzer_band_edges(frequencies)

    geometry: list[tuple[float, float, float]] = []
    for index in range(count):
        raw_x0 = clamp(analyzer_frequency_to_x(edges[index], width, left, right), left, plot_right)
        raw_x1 = clamp(analyzer_frequency_to_x(edges[index + 1], width, left, right), left, plot_right)
        center_x = clamp(analyzer_frequency_to_x(frequencies[index], width, left, right), left, plot_right)
        bucket_width = raw_x1 - raw_x0
        inner_gap = min(1.5, bucket_width * 0.35) if count > 1 else 0.0
        x0 = raw_x0 + inner_gap / 2.0
        x1 = raw_x1 - inner_gap / 2.0

        if x1 <= x0:
            x0 = clamp(center_x - 0.5, left, max(left, plot_right - 1.0))
            x1 = clamp(x0 + 1.0, x0 + 1.0, plot_right)

        geometry.append((x0, x1 - x0, center_x))

    return tuple(geometry)


def analyzer_bar_geometry(
    width: float,
    left: float,
    right: float,
    count: int,
) -> list[tuple[float, float, float]]:
    return list(
        cached_analyzer_bar_geometry(
            round(float(width), 2),
            round(float(left), 2),
            round(float(right), 2),
            int(count),
        )
    )


def analyzer_plot_points(
    levels: Sequence[float],
    width: float,
    height: float,
    display_gain_db: float,
) -> tuple[list[tuple[float, float, float, float]], list[tuple[float, float]]]:
    base_y = height
    usable_height = max(height, 1.0)
    bars: list[tuple[float, float, float, float]] = []
    spectrum_points: list[tuple[float, float]] = []
    last_bar_edge = 0.0

    for level, (x0, bar_width, center_x) in zip(
        levels,
        cached_analyzer_bar_geometry(round(float(width), 2), 0.0, 0.0, len(levels)),
        strict=False,
    ):
        normalized = analyzer_level_to_display_norm(float(level), display_gain_db)
        y = base_y - (usable_height * normalized)
        bar_height = max(base_y - y, 1.0)
        bars.append((x0, y, bar_width, bar_height))
        if not spectrum_points:
            spectrum_points.append((x0, y))
        spectrum_points.append((center_x, y))
        last_bar_edge = x0 + bar_width

    if spectrum_points:
        spectrum_points.append((last_bar_edge, spectrum_points[-1][1]))

    return bars, spectrum_points


class AnalyzerPlotWidget(Gtk.Widget):
    __gtype_name__ = "MiniEqAnalyzerPlotWidget"

    def __init__(self) -> None:
        super().__init__()
        self._content_width = 1
        self._content_height = 1
        self._levels: tuple[float, ...] = ()
        self._display_gain_db = 0.0
        self._enabled = False

    @GObject.Property(type=int, default=1)
    def content_width(self) -> int:
        return self._content_width

    @content_width.setter
    def content_width(self, value: int) -> None:
        self._content_width = max(1, int(value))
        self.queue_resize()

    @GObject.Property(type=int, default=1)
    def content_height(self) -> int:
        return self._content_height

    @content_height.setter
    def content_height(self, value: int) -> None:
        self._content_height = max(1, int(value))
        self.queue_resize()

    def set_content_width(self, width: int) -> None:
        self.props.content_width = width

    def set_content_height(self, height: int) -> None:
        self.props.content_height = height

    def set_analyzer_state(
        self,
        levels: Sequence[float],
        *,
        display_gain_db: float,
        enabled: bool,
    ) -> None:
        self._levels = tuple(float(level) for level in levels)
        self._display_gain_db = float(display_gain_db)
        self._enabled = bool(enabled)

    def is_dark_appearance(self) -> bool:
        root = self.get_root()
        application = root.get_application() if root is not None and hasattr(root, "get_application") else None
        style_manager = application.get_style_manager() if hasattr(application, "get_style_manager") else None
        return style_manager_is_dark(style_manager)

    def do_measure(
        self,
        orientation: Gtk.Orientation,
        _for_size: int,
    ) -> tuple[int, int, int, int]:
        if orientation == Gtk.Orientation.HORIZONTAL:
            minimum = natural = self._content_width
        else:
            minimum = natural = self._content_height

        return minimum, natural, -1, -1

    def do_snapshot(self, snapshot: Gtk.Snapshot) -> None:
        width = self.get_width()
        height = self.get_height()
        if width <= 0 or height <= 0 or not any(level > 0.01 for level in self._levels):
            return

        bar_rgba, line_rgba = analyzer_plot_palette(dark=self.is_dark_appearance(), enabled=self._enabled)
        bar_color = Gdk.RGBA(red=bar_rgba[0], green=bar_rgba[1], blue=bar_rgba[2], alpha=bar_rgba[3])
        line_color = Gdk.RGBA(red=line_rgba[0], green=line_rgba[1], blue=line_rgba[2], alpha=line_rgba[3])

        bars, spectrum_points = analyzer_plot_points(
            self._levels,
            float(width),
            float(height),
            self._display_gain_db,
        )
        for x, y, bar_width, bar_height in bars:
            snapshot.append_color(bar_color, Graphene.Rect().init(x, y, bar_width, bar_height))

        if not spectrum_points:
            return

        builder = Gsk.PathBuilder.new()
        builder.move_to(spectrum_points[0][0], spectrum_points[0][1])
        for x, y in spectrum_points[1:]:
            builder.line_to(x, y)

        snapshot.append_stroke(builder.to_path(), Gsk.Stroke.new(1.3), line_color)
