from __future__ import annotations

import pytest

from tests._mini_eq_imports import import_mini_eq_module

window_analyzer = import_mini_eq_module("window_analyzer")
window_graph = import_mini_eq_module("window_graph")


class AnalyzerGeometryWindow(
    window_analyzer.MiniEqWindowAnalyzerMixin,
    window_graph.MiniEqWindowGraphMixin,
):
    pass


def test_analyzer_bars_fill_plot_bounds() -> None:
    window = AnalyzerGeometryWindow()
    width = 640.0
    left = 58.0
    right = 52.0
    plot_right = width - right
    count = len(window_analyzer.ANALYZER_BAND_FREQUENCIES)
    window.analyzer_levels = [0.0] * count

    geometry = window.analyzer_bar_geometry(width, left, right, count)

    assert geometry[0][0] == pytest.approx(left)
    assert geometry[-1][0] + geometry[-1][1] == pytest.approx(plot_right)
    assert all(x0 >= left for x0, _bar_width, _center_x in geometry)
    assert all(x0 + bar_width <= plot_right for x0, bar_width, _center_x in geometry)
    assert all(left <= center_x <= plot_right for _x0, _bar_width, center_x in geometry)

    bar_widths = [bar_width for _x0, bar_width, _center_x in geometry]
    assert max(bar_widths) - min(bar_widths) < 1.0
