from __future__ import annotations

from types import SimpleNamespace

import pytest

from tests._mini_eq_imports import core, import_mini_eq_module

dbus_control = import_mini_eq_module("dbus_control")


class FakeController:
    def __init__(self) -> None:
        self.eq_enabled = True
        self.routed = False
        self.output_sink = "alsa_output.test"
        self.enabled_values: list[bool] = []
        self.routed_values: list[bool] = []
        self.route_error: Exception | None = None

    def set_eq_enabled(self, enabled: bool) -> None:
        self.eq_enabled = enabled
        self.enabled_values.append(enabled)

    def route_system_audio(self, enabled: bool) -> None:
        if self.route_error is not None:
            raise self.route_error
        self.routed = enabled
        self.routed_values.append(enabled)


class FakeSwitch:
    def __init__(self, active: bool = False) -> None:
        self.active = active

    def set_active(self, active: bool) -> None:
        self.active = active


class FakeWindow:
    def __init__(self, controller: FakeController) -> None:
        self.current_preset_name: str | None = "Flat"
        self.ui_shutting_down = False
        self.updating_ui = False
        self.analyzer_enabled = False
        self.analyzer_levels = [0.0] * dbus_control.PANEL_ANALYZER_BINS
        self.controller = controller
        self.bypass_switch = FakeSwitch(controller.eq_enabled)
        self.route_switch = FakeSwitch(controller.routed)
        self.loaded_presets: list[str] = []
        self.update_count = 0

    def load_library_preset(self, name: str) -> None:
        self.current_preset_name = name
        self.loaded_presets.append(name)

    def present(self) -> None:
        pass

    def sync_ui_from_state(self) -> None:
        self.update_count += 1

    def update_eq_power_indicator(self) -> None:
        self.update_count += 1

    def update_info_label(self) -> None:
        self.update_count += 1

    def update_status_summary(self) -> None:
        self.update_count += 1

    def update_focus_summary(self) -> None:
        self.update_count += 1

    def invalidate_graph_response_cache(self) -> None:
        self.update_count += 1

    def queue_graph_draw(self) -> None:
        self.update_count += 1

    def update_preset_state(self) -> None:
        self.update_count += 1


def make_control() -> tuple[dbus_control.MiniEqDbusControl, FakeController, FakeWindow]:
    controller = FakeController()
    window = FakeWindow(controller)
    app = SimpleNamespace(controller=controller, window=window, activate=lambda: None, get_dbus_connection=lambda: None)
    return dbus_control.MiniEqDbusControl(app), controller, window


def test_dbus_control_state_contains_shell_summary() -> None:
    control, _controller, _window = make_control()

    state = {key: value.unpack() for key, value in control.state().items()}

    assert state == {
        "running": True,
        "eq_enabled": True,
        "routed": False,
        "preset_name": "Flat",
        "output_sink": "alsa_output.test",
        "analyzer_levels": [0.0] * dbus_control.PANEL_ANALYZER_BINS,
    }


def test_dbus_control_state_compacts_analyzer_levels_for_shell() -> None:
    control, _controller, window = make_control()
    window.analyzer_enabled = True
    window.analyzer_levels = [index / 29.0 for index in range(30)]

    state = {key: value.unpack() for key, value in control.state().items()}

    assert state["analyzer_levels"] == pytest.approx(
        [
            2 / 29.0,
            5 / 29.0,
            8 / 29.0,
            11 / 29.0,
            14 / 29.0,
            17 / 29.0,
            20 / 29.0,
            23 / 29.0,
            26 / 29.0,
            1.0,
        ]
    )


def test_dbus_control_state_hides_analyzer_levels_when_monitor_is_off() -> None:
    control, _controller, window = make_control()
    window.analyzer_enabled = False
    window.analyzer_levels = [1.0] * 30

    state = {key: value.unpack() for key, value in control.state().items()}

    assert state["analyzer_levels"] == [0.0] * dbus_control.PANEL_ANALYZER_BINS


def test_dbus_control_set_eq_enabled_updates_controller_and_window() -> None:
    control, controller, window = make_control()

    control.set_eq_enabled(False)

    assert controller.eq_enabled is False
    assert controller.enabled_values == [False]
    assert window.bypass_switch.active is False
    assert window.update_count == 6


def test_dbus_control_set_routing_enabled_updates_controller_and_window() -> None:
    control, controller, window = make_control()

    control.set_routing_enabled(True)

    assert controller.routed is True
    assert controller.routed_values == [True]
    assert window.route_switch.active is True
    assert window.update_count == 4


def test_dbus_control_set_routing_enabled_restores_equalized_output() -> None:
    control, controller, window = make_control()
    controller.eq_enabled = False
    window.bypass_switch.active = False

    control.set_routing_enabled(True)

    assert controller.routed is True
    assert controller.eq_enabled is True
    assert controller.enabled_values == [True]
    assert window.route_switch.active is True
    assert window.bypass_switch.active is True
    assert window.update_count == 7


def test_dbus_control_set_routing_enabled_restores_ui_on_failure() -> None:
    control, controller, window = make_control()
    controller.eq_enabled = False
    window.bypass_switch.active = False
    controller.route_error = RuntimeError("route failed")

    with pytest.raises(RuntimeError, match="route failed"):
        control.set_routing_enabled(True)

    assert controller.routed is False
    assert controller.eq_enabled is False
    assert controller.enabled_values == [True, False]
    assert window.route_switch.active is False
    assert window.bypass_switch.active is False
    assert window.update_count == 0


def test_dbus_control_set_preset_sanitizes_name() -> None:
    control, _controller, window = make_control()

    control.set_preset("../Headphones")

    assert window.loaded_presets == ["Headphones"]


def test_dbus_control_rejects_empty_preset_name() -> None:
    control, _controller, _window = make_control()

    with pytest.raises(ValueError, match="preset name is empty"):
        control.set_preset("../")


def test_dbus_introspection_exposes_expected_interface() -> None:
    node_info = dbus_control.Gio.DBusNodeInfo.new_for_xml(dbus_control.INTROSPECTION_XML)

    assert node_info.interfaces[0].name == dbus_control.INTERFACE_NAME
    assert {method.name for method in node_info.interfaces[0].methods} == {
        "GetState",
        "ListPresets",
        "SetEqEnabled",
        "SetRoutingEnabled",
        "SetPreset",
        "PresentWindow",
    }
    assert {signal.name for signal in node_info.interfaces[0].signals} == {
        "StateChanged",
        "PresetsChanged",
    }


def test_dbus_control_lists_presets(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr(core, "PRESET_STORAGE_DIR", tmp_path / "mini-eq-presets")
    core.write_mini_eq_preset_file(
        core.preset_path_for_name("Flat"),
        {"version": core.PRESET_VERSION, "name": "Flat", "bands": []},
    )
    control, _controller, _window = make_control()

    assert control.list_presets() == ["Flat"]
