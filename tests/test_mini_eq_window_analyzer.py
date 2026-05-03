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
        self.analyzer_loudness_snapshot = analyzer.AnalyzerLoudnessSnapshot(-18.0, -17.0, -16.0)
        self.analyzer_session_max_shortterm_lufs = -12.0
        self.analyzer_preview_source_id = 0
        self.analyzer_preview_uses_tick_callback = False
        self.controller = FakeAnalyzerController()
        self.sync_count = 0

    def get_application(self) -> FakeApplication:
        return self.application

    def sync_ui_from_state(self) -> None:
        self.sync_count += 1


class FakeSummaryLabel:
    def __init__(self) -> None:
        self.text = ""
        self.tooltip = ""

    def set_text(self, text: str) -> None:
        self.text = text

    def set_tooltip_text(self, tooltip: str) -> None:
        self.tooltip = tooltip


class FakeTooltipWidget:
    def __init__(self) -> None:
        self.tooltip = ""

    def set_tooltip_text(self, tooltip: str) -> None:
        self.tooltip = tooltip


class FakeMeterArea:
    def __init__(self) -> None:
        self.draw_count = 0
        self.accessible_description = ""
        self.tooltip = ""

    def queue_draw(self) -> None:
        self.draw_count += 1

    def update_property(self, _properties: object, values: list[str]) -> None:
        self.accessible_description = values[0]

    def set_tooltip_text(self, tooltip: str) -> None:
        self.tooltip = tooltip


class AnalyzerSummaryWindow(window_analyzer.MiniEqWindowAnalyzerMixin):
    def __init__(self) -> None:
        self.analyzer_summary_label = FakeSummaryLabel()
        self.analyzer_loudness_value_label = FakeSummaryLabel()
        self.analyzer_loudness_meter_area = FakeMeterArea()
        self.monitor_panel = FakeTooltipWidget()
        self.monitor_title_label = FakeTooltipWidget()
        self.monitor_detail_row = FakeTooltipWidget()
        self.monitor_tooltip_widgets = (
            self.monitor_panel,
            self.monitor_title_label,
            self.monitor_detail_row,
            self.analyzer_loudness_meter_area,
            self.analyzer_loudness_value_label,
        )
        self.analyzer_enabled = True
        self.analyzer_frozen = False
        self.analyzer_smoothing = 0.4
        self.analyzer_display_gain_db = 6.0
        self.analyzer_loudness_snapshot = analyzer.AnalyzerLoudnessSnapshot(-18.25, -16.5, -14.0)
        self.analyzer_session_max_shortterm_lufs = -11.75


def test_analyzer_bars_follow_log_frequency_edges() -> None:
    width = 640.0
    left = window_graph.GRAPH_PLOT_LEFT
    right = window_graph.GRAPH_PLOT_RIGHT
    plot_right = width - right
    count = len(analyzer.ANALYZER_BAND_FREQUENCIES)

    geometry = analyzer_widget.analyzer_bar_geometry(width, left, right, count)
    edges = analyzer.analyzer_band_edges(analyzer.ANALYZER_BAND_FREQUENCIES)
    axis_min = edges[0]
    axis_max = edges[-1]

    assert geometry[0][0] == pytest.approx(left)
    assert geometry[-1][0] + geometry[-1][1] == pytest.approx(plot_right)
    assert all(x0 >= left for x0, _bar_width, _center_x in geometry)
    assert all(x0 + bar_width <= plot_right for x0, bar_width, _center_x in geometry)
    assert all(left <= center_x <= plot_right for _x0, _bar_width, center_x in geometry)

    assert geometry[1][0] == pytest.approx(
        analyzer_widget.analyzer_frequency_to_x(edges[1], width, left, right, axis_min, axis_max) + 0.75,
    )
    assert geometry[0][1] == pytest.approx(geometry[-1][1], abs=0.65)
    for frequency, (_x0, _bar_width, center_x) in zip(
        analyzer.ANALYZER_BAND_FREQUENCIES,
        geometry,
        strict=True,
    ):
        assert center_x == pytest.approx(
            analyzer_widget.analyzer_frequency_to_x(frequency, width, left, right, axis_min, axis_max)
        )

    band_5k_index = analyzer.ANALYZER_BAND_FREQUENCIES.index(5000.0)
    assert geometry[band_5k_index][2] == pytest.approx(
        analyzer_widget.analyzer_frequency_to_x(5000.0, width, left, right, axis_min, axis_max)
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


def test_analyzer_palette_uses_darker_monitor_overlay_in_light_mode() -> None:
    dark_bar, dark_line = analyzer_widget.analyzer_plot_palette(dark=True, enabled=True)
    light_bar, light_line = analyzer_widget.analyzer_plot_palette(dark=False, enabled=True)

    assert light_bar[2] < dark_bar[2]
    assert light_line[2] < dark_line[2]
    assert light_line[3] > dark_line[3]


def test_analyzer_palette_uses_lower_alpha_when_disabled() -> None:
    enabled_bar, enabled_line = analyzer_widget.analyzer_plot_palette(dark=False, enabled=True)
    disabled_bar, disabled_line = analyzer_widget.analyzer_plot_palette(dark=False, enabled=False)

    assert disabled_bar[3] < enabled_bar[3]
    assert disabled_line[3] < enabled_line[3]


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
    assert window.analyzer_loudness_snapshot is None
    assert window.analyzer_session_max_shortterm_lufs is None
    assert window.application.analyzer_count == 1
    assert window.application.state_count == 1
    assert window.sync_count == 1


def test_analyzer_summary_prefers_live_shortterm_loudness() -> None:
    window = AnalyzerSummaryWindow()

    window.update_analyzer_summary_label()

    assert window.analyzer_summary_label.text == "On · -16.5 LUFS"
    assert window.analyzer_summary_label.tooltip == "Current -16.5 LUFS · Peak -11.8 LUFS"
    assert "momentary" not in window.analyzer_summary_label.tooltip
    assert "integrated" not in window.analyzer_summary_label.tooltip
    assert window.analyzer_loudness_value_label.text == "-16.5 LUFS"
    assert window.analyzer_loudness_meter_area.draw_count == 1
    assert window.analyzer_loudness_meter_area.accessible_description == "Current -16.5 LUFS · Peak -11.8 LUFS"
    assert window.monitor_panel.tooltip == window.analyzer_summary_label.tooltip
    assert window.monitor_title_label.tooltip == window.analyzer_summary_label.tooltip
    assert window.monitor_detail_row.tooltip == window.analyzer_summary_label.tooltip
    assert window.analyzer_loudness_meter_area.tooltip == window.analyzer_summary_label.tooltip
    assert window.analyzer_loudness_value_label.tooltip == window.analyzer_summary_label.tooltip


def test_format_lufs_handles_silence() -> None:
    assert window_analyzer.format_lufs(float("-inf")) == "-inf LUFS"


def test_analyzer_summary_clears_loudness_details_without_snapshot() -> None:
    window = AnalyzerSummaryWindow()
    window.analyzer_loudness_snapshot = None
    window.analyzer_session_max_shortterm_lufs = None

    window.update_analyzer_summary_label()

    assert window.analyzer_summary_label.text == "On · +6 dB"
    assert window.analyzer_summary_label.tooltip == "Monitor on"
    assert window.analyzer_loudness_value_label.text == "--"
    assert window.analyzer_loudness_meter_area.accessible_description == "Current -- · Peak --"


def test_analyzer_summary_shows_off_in_main_loudness_value() -> None:
    window = AnalyzerSummaryWindow()
    window.analyzer_enabled = False

    window.update_analyzer_summary_label()

    assert window.analyzer_summary_label.text == "Off"
    assert window.analyzer_summary_label.tooltip == "Monitor off"
    assert window.analyzer_loudness_value_label.text == "Off"
    assert window.analyzer_loudness_meter_area.accessible_description == "Monitor is off"


def test_analyzer_summary_marks_frozen_loudness_in_tooltip() -> None:
    window = AnalyzerSummaryWindow()
    window.analyzer_frozen = True

    window.update_analyzer_summary_label()

    assert window.analyzer_summary_label.text == "Frozen · -16.5 LUFS"
    assert window.analyzer_summary_label.tooltip == "Frozen · Current -16.5 LUFS · Peak -11.8 LUFS"


def test_loudness_meter_norm_maps_lufs_to_meter_range() -> None:
    assert window_analyzer.loudness_meter_norm(None) == pytest.approx(0.0)
    assert window_analyzer.loudness_meter_norm(float("-inf")) == pytest.approx(0.0)
    assert window_analyzer.loudness_meter_norm(-60.0) == pytest.approx(0.0)
    assert window_analyzer.loudness_meter_norm(-30.0) == pytest.approx(0.5)
    assert window_analyzer.loudness_meter_norm(0.0) == pytest.approx(1.0)
    assert window_analyzer.loudness_meter_norm(3.0) == pytest.approx(1.0)


def test_loudness_summary_falls_back_while_shortterm_is_not_ready() -> None:
    snapshot = analyzer.AnalyzerLoudnessSnapshot(-21.0, float("-inf"), float("-inf"))

    assert window_analyzer.loudness_current_lufs(snapshot) == pytest.approx(-21.0)
    assert window_analyzer.loudness_summary_lufs(snapshot) == "-21.0 LUFS"


def test_visible_loudness_falls_back_while_shortterm_is_not_ready() -> None:
    window = AnalyzerSummaryWindow()
    window.analyzer_loudness_snapshot = analyzer.AnalyzerLoudnessSnapshot(-21.0, float("-inf"), float("-inf"))
    window.analyzer_session_max_shortterm_lufs = None

    window.update_analyzer_summary_label()

    assert window.analyzer_summary_label.text == "On · -21.0 LUFS"
    assert window.analyzer_summary_label.tooltip == "Current -21.0 LUFS · Peak --"
    assert window.analyzer_loudness_value_label.text == "-21.0 LUFS"
    assert window.analyzer_loudness_meter_area.accessible_description == "Current -21.0 LUFS · Peak --"


def test_loudness_session_max_ignores_silence() -> None:
    assert window_analyzer.update_loudness_max(None, float("-inf")) is None
    assert window_analyzer.update_loudness_max(-18.0, -20.0) == pytest.approx(-18.0)
    assert window_analyzer.update_loudness_max(-18.0, -12.0) == pytest.approx(-12.0)
