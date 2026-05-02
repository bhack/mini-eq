from __future__ import annotations

from tests._mini_eq_imports import import_mini_eq_module

core = import_mini_eq_module("core")
window_graph = import_mini_eq_module("window_graph")


class FakeLabel:
    def __init__(self) -> None:
        self.text = ""
        self.tooltip = ""
        self.visible = True

    def set_text(self, text: str) -> None:
        self.text = text

    def set_tooltip_text(self, text: str) -> None:
        self.tooltip = text

    def set_visible(self, visible: bool) -> None:
        self.visible = visible


class FakeSwitch:
    def __init__(self, active: bool) -> None:
        self.active = active

    def get_active(self) -> bool:
        return self.active


class FocusSummaryWindow(window_graph.MiniEqWindowGraphMixin):
    def __init__(self, *, route_active: bool, selected_band_index: int | None = 0) -> None:
        self.selected_band_index = selected_band_index
        self.controller = type(
            "Controller",
            (),
            {"bands": [core.EqBand(core.FILTER_TYPES["Bell"], 32.0, gain_db=1.8)]},
        )()
        self.route_switch = FakeSwitch(route_active)
        self.focus_label = FakeLabel()
        self.band_count_label = FakeLabel()
        self.inspector_summary_label = FakeLabel()


def test_filter_type_label_handles_non_contiguous_filter_values() -> None:
    assert window_graph.filter_type_label(core.FILTER_TYPES["Allpass"]) == "Allpass"
    assert window_graph.filter_type_label(core.FILTER_TYPES["Bandpass"]) == "Bandpass"


def test_focus_summary_keeps_selected_band_visible_when_system_eq_is_off() -> None:
    window = FocusSummaryWindow(route_active=False)

    window.update_focus_summary()

    assert window.focus_label.text == "Band 1 • 32 • +1.8 dB"
    assert window.band_count_label.text == "Bell"
    assert window.band_count_label.visible is True
    assert "System-wide EQ is off." in window.focus_label.tooltip


def test_focus_summary_handles_no_selected_band() -> None:
    window = FocusSummaryWindow(route_active=True, selected_band_index=None)

    window.update_focus_summary()

    assert window.focus_label.text == "No band selected"
    assert window.band_count_label.visible is False
    assert window.inspector_summary_label.text == "No Band"
