from __future__ import annotations

import pytest

from tests._mini_eq_imports import import_mini_eq_module

analyzer = import_mini_eq_module("analyzer")
analyzer_widget = import_mini_eq_module("analyzer_widget")
window_analyzer = import_mini_eq_module("window_analyzer")
window_graph = import_mini_eq_module("window_graph")


class FakeApplication:
    def __init__(self) -> None:
        self.state_count = 0
        self.analyzer_count = 0

    def emit_control_state_changed(self) -> None:
        self.state_count += 1

    def emit_control_analyzer_levels_changed(self) -> None:
        self.analyzer_count += 1


class AnalyzerSignalWindow(window_analyzer.MiniEqWindowAnalyzerMixin):
    def __init__(self) -> None:
        self.application = FakeApplication()
        self.ui_shutting_down = False
        self.analyzer_enabled = True
        self.analyzer_frozen = False
        self.analyzer_levels = [0.0, 0.0]
        self.analyzer_smoothing = 0.5
        self.analyzer_last_frame_time = 0.0
        self.control_analyzer_last_emit_time = 0.0

    def get_application(self) -> FakeApplication:
        return self.application


class UnmappedAnalyzerArea:
    def __init__(self) -> None:
        self.draw_count = 0

    def is_drawable(self) -> bool:
        return False

    def queue_draw(self) -> None:
        self.draw_count += 1


class AnalyzerDrawWindow(window_analyzer.MiniEqWindowAnalyzerMixin):
    def __init__(self) -> None:
        self.analyzer_area = UnmappedAnalyzerArea()


class AllocatedAnalyzerArea:
    def __init__(self, width: int, height: int) -> None:
        self.width = width
        self.height = height

    def get_allocated_width(self) -> int:
        return self.width

    def get_allocated_height(self) -> int:
        return self.height


class AnalyzerAllocatedWindow(window_analyzer.MiniEqWindowAnalyzerMixin):
    def __init__(self, width: int, height: int) -> None:
        self.analyzer_area = AllocatedAnalyzerArea(width, height)
        self.analyzer_levels = [0.5, 1.0]
        self.analyzer_display_gain_db = 0.0


class FakeAnalyzerController:
    def __init__(self) -> None:
        self.enabled_values: list[bool] = []

    def set_analyzer_enabled(self, enabled: bool) -> bool:
        self.enabled_values.append(enabled)
        return True


class TickAnalyzerArea:
    def __init__(self) -> None:
        self.callback = None
        self.removed_ids: list[int] = []

    def add_tick_callback(self, callback):
        self.callback = callback
        return 42

    def remove_tick_callback(self, callback_id: int) -> None:
        self.removed_ids.append(callback_id)


class AnalyzerPreviewWindow(window_analyzer.MiniEqWindowAnalyzerMixin):
    def __init__(self) -> None:
        self.analyzer_enabled = True
        self.analyzer_preview_source_id = 0
        self.analyzer_preview_uses_tick_callback = False
        self.analyzer_preview_last_tick_time = 0.0
        self.controller = FakeAnalyzerController()
        self.analyzer_area = TickAnalyzerArea()


class FakeFrameClock:
    def __init__(self, frame_time: float) -> None:
        self.frame_time = frame_time

    def get_frame_time(self) -> int:
        return int(self.frame_time * 1_000_000)


class PreviewFrameWindow(window_analyzer.MiniEqWindowAnalyzerMixin):
    def __init__(self) -> None:
        self.ui_shutting_down = False
        self.analyzer_preview_last_tick_time = 1.0
        self.tick_times: list[float | None] = []

    def on_analyzer_preview_tick(self, now: float | None = None) -> bool:
        self.tick_times.append(now)
        return True


class FakeSwitch:
    def __init__(self, active: bool) -> None:
        self.active = active

    def get_active(self) -> bool:
        return self.active


class AnalyzerToggleWindow(window_analyzer.MiniEqWindowAnalyzerMixin):
    def __init__(self) -> None:
        self.application = FakeApplication()
        self.updating_ui = False
        self.analyzer_enabled = True
        self.analyzer_levels = [0.8, 0.4]
        self.analyzer_preview_source_id = 0
        self.analyzer_preview_uses_tick_callback = False
        self.controller = FakeAnalyzerController()
        self.sync_count = 0

    def get_application(self) -> FakeApplication:
        return self.application

    def sync_ui_from_state(self) -> None:
        self.sync_count += 1


def test_analyzer_bars_follow_log_frequency_edges() -> None:
    width = 640.0
    left = 58.0
    right = 52.0
    plot_right = width - right
    count = len(analyzer.ANALYZER_BAND_FREQUENCIES)

    geometry = analyzer_widget.analyzer_bar_geometry(width, left, right, count)
    edges = analyzer.analyzer_band_edges(analyzer.ANALYZER_BAND_FREQUENCIES)

    assert geometry[0][0] > left
    assert geometry[-1][0] + geometry[-1][1] <= plot_right
    assert all(x0 >= left for x0, _bar_width, _center_x in geometry)
    assert all(x0 + bar_width <= plot_right for x0, bar_width, _center_x in geometry)
    assert all(left <= center_x <= plot_right for _x0, _bar_width, center_x in geometry)

    assert geometry[0][0] == pytest.approx(
        analyzer_widget.analyzer_frequency_to_x(edges[0], width, left, right) + 0.75,
    )
    for frequency, (_x0, _bar_width, center_x) in zip(
        analyzer.ANALYZER_BAND_FREQUENCIES,
        geometry,
        strict=True,
    ):
        assert center_x == pytest.approx(analyzer_widget.analyzer_frequency_to_x(frequency, width, left, right))

    band_5k_index = analyzer.ANALYZER_BAND_FREQUENCIES.index(5000.0)
    assert geometry[band_5k_index][2] == pytest.approx(
        analyzer_widget.analyzer_frequency_to_x(5000.0, width, left, right)
    )


def test_analyzer_plot_geometry_matches_full_graph_coordinates() -> None:
    full_width = 640.0
    left = window_graph.GRAPH_PLOT_LEFT
    right = window_graph.GRAPH_PLOT_RIGHT
    plot_width = full_width - left - right
    count = len(analyzer.ANALYZER_BAND_FREQUENCIES)

    full_geometry = analyzer_widget.analyzer_bar_geometry(full_width, left, right, count)
    plot_geometry = analyzer_widget.analyzer_bar_geometry(plot_width, 0.0, 0.0, count)

    for (full_x, full_bar_width, full_center), (plot_x, plot_bar_width, plot_center) in zip(
        full_geometry,
        plot_geometry,
        strict=True,
    ):
        assert plot_x == pytest.approx(full_x - left)
        assert plot_bar_width == pytest.approx(full_bar_width)
        assert plot_center == pytest.approx(full_center - left)


def test_analyzer_pixel_heights_use_allocated_plot_height() -> None:
    window = AnalyzerAllocatedWindow(900, 200)

    heights = window.current_analyzer_pixel_heights()

    assert heights[0] == pytest.approx(
        200.0 * analyzer.analyzer_level_to_display_norm(0.5, window.analyzer_display_gain_db)
    )
    assert heights[1] == pytest.approx(
        200.0 * analyzer.analyzer_level_to_display_norm(1.0, window.analyzer_display_gain_db)
    )


def test_analyzer_widget_plot_points_use_plot_local_coordinates() -> None:
    levels = (0.5, 1.0)

    bars, spectrum_points = analyzer_widget.analyzer_plot_points(levels, 320.0, 120.0, 0.0)

    assert len(bars) == len(levels)
    assert bars[0][0] >= 0.0
    assert bars[-1][0] + bars[-1][2] <= 320.0
    assert bars[0][3] == pytest.approx(120.0 * analyzer.analyzer_level_to_display_norm(0.5))
    assert bars[1][3] == pytest.approx(120.0 * analyzer.analyzer_level_to_display_norm(1.0))
    assert spectrum_points[0][0] == pytest.approx(bars[0][0])
    assert spectrum_points[-1][0] == pytest.approx(bars[-1][0] + bars[-1][2])


def test_analyzer_level_frames_emit_compact_control_signal() -> None:
    window = AnalyzerSignalWindow()

    assert window.on_analyzer_levels_idle((1.0, 0.5)) is False

    assert window.application.analyzer_count == 1
    assert window.application.state_count == 0


def test_analyzer_redraw_skips_unmapped_area() -> None:
    window = AnalyzerDrawWindow()

    window.queue_analyzer_draw()

    assert window.analyzer_area.draw_count == 0


def test_analyzer_preview_uses_frame_clock_tick_callback() -> None:
    window = AnalyzerPreviewWindow()

    window.start_analyzer_preview()

    assert window.controller.enabled_values == [True]
    assert window.analyzer_preview_source_id == 42
    assert window.analyzer_preview_uses_tick_callback is True

    window.stop_analyzer_preview()

    assert window.controller.enabled_values == [True, False]
    assert window.analyzer_area.removed_ids == [42]
    assert window.analyzer_preview_source_id == 0
    assert window.analyzer_preview_uses_tick_callback is False


def test_analyzer_preview_frame_coalesces_to_30hz() -> None:
    window = PreviewFrameWindow()

    assert window.on_analyzer_preview_frame(None, FakeFrameClock(1.01)) is True
    assert window.tick_times == []

    assert window.on_analyzer_preview_frame(None, FakeFrameClock(1.04)) is True
    assert window.tick_times == [pytest.approx(1.04)]


def test_analyzer_toggle_off_emits_zero_level_signal() -> None:
    window = AnalyzerToggleWindow()

    window.on_analyzer_changed(FakeSwitch(False), None)

    assert window.controller.enabled_values == [False]
    assert window.analyzer_enabled is False
    assert window.analyzer_levels == [0.0, 0.0]
    assert window.application.analyzer_count == 1
    assert window.application.state_count == 1
    assert window.sync_count == 1
