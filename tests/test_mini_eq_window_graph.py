from __future__ import annotations

from types import SimpleNamespace

from tests._mini_eq_imports import import_mini_eq_module

core = import_mini_eq_module("core")
window_graph = import_mini_eq_module("window_graph")


class FakeLabel:
    def __init__(self) -> None:
        self.text = ""
        self.tooltip = ""
        self.visible = True
        self.css_classes: set[str] = set()

    def set_text(self, text: str) -> None:
        self.text = text

    def set_tooltip_text(self, text: str) -> None:
        self.tooltip = text

    def set_visible(self, visible: bool) -> None:
        self.visible = visible

    def add_css_class(self, css_class: str) -> None:
        self.css_classes.add(css_class)

    def remove_css_class(self, css_class: str) -> None:
        self.css_classes.discard(css_class)


class FakeSwitch:
    def __init__(self, active: bool) -> None:
        self.active = active
        self.sensitive = True

    def get_active(self) -> bool:
        return self.active

    def set_sensitive(self, sensitive: bool) -> None:
        self.sensitive = sensitive


class FakeScale:
    def __init__(self, value: float) -> None:
        self.value = value

    def get_value(self) -> float:
        return self.value


class FocusSummaryWindow(window_graph.MiniEqWindowGraphMixin):
    def __init__(
        self,
        *,
        route_active: bool,
        selected_band_index: int | None = 0,
        controller_routed: bool | None = None,
        eq_enabled: bool = True,
    ) -> None:
        self.selected_band_index = selected_band_index
        controller_state = {
            "bands": [core.EqBand(core.FILTER_TYPES["Bell"], 32.0, gain_db=1.8)],
            "eq_enabled": eq_enabled,
        }
        if controller_routed is not None:
            controller_state["routed"] = controller_routed
        self.controller = type("Controller", (), controller_state)()
        self.route_switch = FakeSwitch(route_active)
        self.bypass_switch = FakeSwitch(False)
        self.bypass_state_label = FakeLabel()
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


def test_focus_summary_uses_controller_route_state_over_stale_switch() -> None:
    window = FocusSummaryWindow(route_active=False, controller_routed=True)

    window.update_focus_summary()

    assert "System-wide EQ is off." not in window.focus_label.tooltip


def test_compare_state_uses_controller_route_state_over_stale_switch() -> None:
    window = FocusSummaryWindow(route_active=False, controller_routed=True, eq_enabled=True)

    window.update_eq_power_indicator()

    assert window.bypass_switch.sensitive is True
    assert window.bypass_state_label.text == "Equalized"
    assert "compare-state-equalized" in window.bypass_state_label.css_classes


def test_focus_summary_handles_no_selected_band() -> None:
    window = FocusSummaryWindow(route_active=True, selected_band_index=None)

    window.update_focus_summary()

    assert window.focus_label.text == "No band selected"
    assert window.band_count_label.visible is False
    assert window.inspector_summary_label.text == "No Band"


def test_preamp_change_refreshes_preset_metadata() -> None:
    calls: list[object] = []
    controller = SimpleNamespace(set_preamp_db=lambda value: calls.append(("preamp", value)))
    test_window = SimpleNamespace(
        updating_ui=False,
        preamp_label=FakeLabel(),
        controller=controller,
        invalidate_graph_response_cache=lambda: calls.append("invalidate"),
        queue_response_draw=lambda: calls.append("draw"),
        schedule_curve_metadata_refresh=lambda: calls.append("metadata"),
    )

    window_graph.MiniEqWindowGraphMixin.on_preamp_changed(test_window, FakeScale(-3.5))

    assert test_window.preamp_label.text == "-3.5 dB"
    assert calls == [("preamp", -3.5), "invalidate", "draw", "metadata"]


def test_curve_metadata_refresh_updates_preset_state_immediately(monkeypatch) -> None:
    calls: list[object] = []
    test_window = SimpleNamespace(
        curve_metadata_refresh_source_id=0,
        ui_shutting_down=False,
        update_preset_state=lambda: calls.append("preset-state"),
        on_curve_metadata_refresh_idle=lambda: False,
    )
    monkeypatch.setattr(
        window_graph.GLib,
        "idle_add",
        lambda callback: calls.append(("idle", callback)) or 42,
    )

    window_graph.MiniEqWindowGraphMixin.schedule_curve_metadata_refresh(test_window)

    assert calls == [("preset-state"), ("idle", test_window.on_curve_metadata_refresh_idle)]
    assert test_window.curve_metadata_refresh_source_id == 42


def test_curve_metadata_refresh_updates_preset_state_with_pending_idle(monkeypatch) -> None:
    calls: list[object] = []
    test_window = SimpleNamespace(
        curve_metadata_refresh_source_id=42,
        ui_shutting_down=False,
        update_preset_state=lambda: calls.append("preset-state"),
        on_curve_metadata_refresh_idle=lambda: False,
    )
    monkeypatch.setattr(window_graph.GLib, "idle_add", lambda _callback: calls.append("unexpected-idle"))

    window_graph.MiniEqWindowGraphMixin.schedule_curve_metadata_refresh(test_window)

    assert calls == ["preset-state"]
    assert test_window.curve_metadata_refresh_source_id == 42
