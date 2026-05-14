from __future__ import annotations

from types import SimpleNamespace

import pytest

from tests._mini_eq_imports import core, import_mini_eq_module

analyzer = import_mini_eq_module("analyzer")
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
        eq_enabled_for_route = False
        if enabled and not self.eq_enabled:
            self.set_eq_enabled(True)
            eq_enabled_for_route = True

        if self.route_error is not None:
            if eq_enabled_for_route:
                self.set_eq_enabled(False)
            raise self.route_error
        self.routed = enabled
        self.routed_values.append(enabled)


class FakeSwitch:
    def __init__(self, active: bool = False) -> None:
        self.active = active
        self.state = active

    def set_active(self, active: bool) -> None:
        self.active = active

    def set_state(self, state: bool) -> None:
        self.state = state


class FakeConnection:
    def __init__(self) -> None:
        self.signals: list[tuple[str, object | None]] = []
        self.closed = False

    def emit_signal(
        self,
        _destination: str | None,
        _object_path: str,
        _interface_name: str,
        signal_name: str,
        parameters: object | None,
    ) -> None:
        self.signals.append((signal_name, parameters))

    def is_closed(self) -> bool:
        return self.closed


class ClosedErrorConnection(FakeConnection):
    def emit_signal(
        self,
        _destination: str | None,
        _object_path: str,
        _interface_name: str,
        signal_name: str,
        parameters: object | None,
    ) -> None:
        del signal_name, parameters
        raise dbus_control.GLib.Error(
            "connection is closed",
            dbus_control.Gio.io_error_quark(),
            dbus_control.Gio.IOErrorEnum.CLOSED,
        )


class FakeWindow:
    def __init__(self, controller: FakeController) -> None:
        self.current_preset_name: str | None = "Flat"
        self.ui_shutting_down = False
        self.updating_ui = False
        self.analyzer_enabled = False
        self.analyzer_levels = [0.0] * dbus_control.PANEL_ANALYZER_BINS
        self.analyzer_display_gain_db = 0.0
        self.controller = controller
        self.bypass_switch = FakeSwitch(controller.eq_enabled)
        self.route_switch = FakeSwitch(controller.routed)
        self.loaded_presets: list[str] = []
        self.update_count = 0
        self.current_curve_text = "Flat"
        self.preset_state_text = "Preset"
        self.output_preset_link = "Headphones"
        self.output_preset_auto_applied = False
        self.existing_presets = {"Flat", "Headphones"}
        self.visible = True
        self.present_count = 0
        self.startup_ids: list[str] = []

    def sync_control_switches_from_controller(self, *, route: bool = True, eq: bool = True) -> None:
        self.updating_ui = True
        try:
            if route:
                self.route_switch.set_active(self.controller.routed)
                self.route_switch.set_state(self.controller.routed)
            if eq:
                self.bypass_switch.set_active(self.controller.eq_enabled)
                self.bypass_switch.set_state(self.controller.eq_enabled)
        finally:
            self.updating_ui = False

    def refresh_after_route_state_changed(
        self,
        *,
        eq_was_enabled: bool,
        announce_enabled: bool | None = None,
        notify: bool = True,
    ) -> None:
        del announce_enabled, notify
        self.sync_control_switches_from_controller()
        self.update_eq_power_indicator()
        self.update_info_label()
        self.update_status_summary()
        self.update_focus_summary()
        if not eq_was_enabled and self.controller.eq_enabled:
            self.invalidate_graph_response_cache()
            self.queue_graph_draw()
            self.update_preset_state()

    def refresh_after_eq_state_changed(
        self,
        *,
        announce_enabled: bool | None = None,
        notify: bool = True,
    ) -> None:
        del announce_enabled, notify
        self.sync_control_switches_from_controller(route=False)
        self.update_eq_power_indicator()
        self.update_info_label()
        self.update_status_summary()
        self.invalidate_graph_response_cache()
        self.queue_graph_draw()
        self.update_preset_state()

    def load_library_preset(self, name: str) -> None:
        self.current_preset_name = name
        self.current_curve_text = name
        self.preset_state_text = "Preset"
        self.loaded_presets.append(name)

    def output_preset_link_name(self) -> str | None:
        return self.output_preset_link

    def preset_panel_ui_state(self) -> SimpleNamespace:
        return SimpleNamespace(
            current_curve_text=self.current_curve_text,
            preset_state_text=self.preset_state_text,
        )

    def preset_name_exists(self, preset_name: str) -> bool:
        return preset_name in self.existing_presets

    def present(self) -> None:
        self.present_count += 1

    def set_startup_id(self, startup_id: str) -> None:
        self.startup_ids.append(startup_id)

    def get_visible(self) -> bool:
        return self.visible

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
    app = SimpleNamespace(
        controller=controller,
        window=window,
        background_mode=True,
        start_at_login=False,
        start_active_at_login=False,
        activate=lambda: None,
        get_dbus_connection=lambda: None,
        present_main_window=lambda startup_id=None: None,
        quit_fully=lambda: None,
    )
    return dbus_control.MiniEqDbusControl(app), controller, window


def test_dbus_control_state_contains_shell_summary() -> None:
    control, _controller, _window = make_control()

    state = {key: value.unpack() for key, value in control.state().items()}

    assert state == {
        "api_version": dbus_control.API_VERSION,
        "app_version": dbus_control.__version__,
        "capabilities": list(dbus_control.CAPABILITIES),
        "running": True,
        "eq_enabled": True,
        "routed": False,
        "preset_name": "Flat",
        "curve_name": "Flat",
        "curve_status": "preset",
        "curve_label": "Flat",
        "output_sink": "alsa_output.test",
        "output_preset_name": "Headphones",
        "output_preset_status": "different",
        "output_preset_label": "Different - Headphones",
        "output_preset_auto_applied": False,
        "analyzer_enabled": False,
        "background_mode": True,
        "start_at_login": False,
        "start_active_at_login": False,
        "window_visible": True,
    }


def test_dbus_control_state_marks_modified_curve_for_shell() -> None:
    control, _controller, window = make_control()
    window.current_curve_text = "Flat"
    window.preset_state_text = "Modified"

    state = {key: value.unpack() for key, value in control.state().items()}

    assert state["curve_name"] == "Flat"
    assert state["curve_status"] == "modified"
    assert state["curve_label"] == "Flat (modified)"


@pytest.mark.parametrize(
    ("current_preset_name", "auto_applied", "existing_presets", "status", "label"),
    [
        ("Headphones", True, {"Headphones"}, "applied", "Applied - Headphones"),
        ("Headphones", False, {"Headphones"}, "modified", "Modified - Headphones"),
        ("Flat", False, {"Flat", "Headphones"}, "different", "Different - Headphones"),
        (None, False, {"Headphones"}, "linked", "Linked - Headphones"),
        ("Flat", False, {"Flat"}, "missing", "Missing - Headphones"),
    ],
)
def test_dbus_control_state_describes_output_preset_for_shell(
    current_preset_name: str | None,
    auto_applied: bool,
    existing_presets: set[str],
    status: str,
    label: str,
) -> None:
    control, _controller, window = make_control()
    window.current_preset_name = current_preset_name
    window.output_preset_auto_applied = auto_applied
    window.existing_presets = existing_presets

    state = {key: value.unpack() for key, value in control.state().items()}

    assert state["output_preset_status"] == status
    assert state["output_preset_label"] == label


def test_dbus_control_compacts_analyzer_levels_for_shell_signal() -> None:
    control, _controller, window = make_control()
    window.analyzer_enabled = True
    window.analyzer_levels = [index / 29.0 for index in range(30)]

    levels = control.analyzer_levels()

    assert levels == pytest.approx(
        [
            analyzer.analyzer_level_to_display_norm(2 / 29.0),
            analyzer.analyzer_level_to_display_norm(5 / 29.0),
            analyzer.analyzer_level_to_display_norm(8 / 29.0),
            analyzer.analyzer_level_to_display_norm(11 / 29.0),
            analyzer.analyzer_level_to_display_norm(14 / 29.0),
            analyzer.analyzer_level_to_display_norm(17 / 29.0),
            analyzer.analyzer_level_to_display_norm(20 / 29.0),
            analyzer.analyzer_level_to_display_norm(23 / 29.0),
            analyzer.analyzer_level_to_display_norm(26 / 29.0),
            analyzer.analyzer_level_to_display_norm(1.0),
        ]
    )


def test_dbus_control_applies_display_gain_to_shell_analyzer_levels() -> None:
    control, _controller, window = make_control()
    window.analyzer_enabled = True
    window.analyzer_display_gain_db = 20.0
    window.analyzer_levels = [analyzer.normalize_spectrum_db(-40.0)] * 30

    levels = control.analyzer_levels()

    assert levels == pytest.approx([analyzer.analyzer_db_to_display_norm(-20.0)] * dbus_control.PANEL_ANALYZER_BINS)


def test_dbus_control_hides_analyzer_levels_when_monitor_is_off() -> None:
    control, _controller, window = make_control()
    window.analyzer_enabled = False
    window.analyzer_levels = [1.0] * 30

    assert control.analyzer_levels() == [0.0] * dbus_control.PANEL_ANALYZER_BINS


def test_dbus_control_emits_compact_analyzer_levels_signal() -> None:
    control, _controller, window = make_control()
    connection = FakeConnection()
    control.connection = connection
    window.analyzer_enabled = True
    window.analyzer_levels = [index / 29.0 for index in range(30)]

    control.emit_analyzer_levels_changed()

    assert len(connection.signals) == 1
    signal_name, parameters = connection.signals[0]
    assert signal_name == "AnalyzerLevelsChanged"
    assert parameters is not None
    (levels,) = parameters.unpack()
    assert levels == pytest.approx(
        [
            analyzer.analyzer_level_to_display_norm(2 / 29.0),
            analyzer.analyzer_level_to_display_norm(5 / 29.0),
            analyzer.analyzer_level_to_display_norm(8 / 29.0),
            analyzer.analyzer_level_to_display_norm(11 / 29.0),
            analyzer.analyzer_level_to_display_norm(14 / 29.0),
            analyzer.analyzer_level_to_display_norm(17 / 29.0),
            analyzer.analyzer_level_to_display_norm(20 / 29.0),
            analyzer.analyzer_level_to_display_norm(23 / 29.0),
            analyzer.analyzer_level_to_display_norm(26 / 29.0),
            analyzer.analyzer_level_to_display_norm(1.0),
        ]
    )


def test_dbus_control_ignores_closed_connection_before_signal_emit() -> None:
    control, _controller, window = make_control()
    connection = FakeConnection()
    connection.closed = True
    control.connection = connection
    control.registration_id = 12
    window.analyzer_enabled = True

    control.emit_analyzer_levels_changed()

    assert connection.signals == []
    assert control.connection is None
    assert control.registration_id == 0


def test_dbus_control_ignores_closed_connection_error_during_signal_emit() -> None:
    control, _controller, window = make_control()
    connection = ClosedErrorConnection()
    control.connection = connection
    control.registration_id = 12
    window.analyzer_enabled = True

    control.emit_analyzer_levels_changed()

    assert control.connection is None
    assert control.registration_id == 0


def test_dbus_control_set_eq_enabled_updates_controller_and_window() -> None:
    control, controller, window = make_control()

    control.set_eq_enabled(False)

    assert controller.eq_enabled is False
    assert controller.enabled_values == [False]
    assert window.bypass_switch.active is False
    assert window.bypass_switch.state is False
    assert window.update_count == 6


def test_dbus_control_set_routing_enabled_updates_controller_and_window() -> None:
    control, controller, window = make_control()

    control.set_routing_enabled(True)

    assert controller.routed is True
    assert controller.routed_values == [True]
    assert window.route_switch.active is True
    assert window.route_switch.state is True
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
    assert window.route_switch.state is True
    assert window.bypass_switch.active is True
    assert window.bypass_switch.state is True
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
    assert window.route_switch.state is False
    assert window.bypass_switch.active is False
    assert window.bypass_switch.state is False
    assert window.update_count == 0


def test_dbus_control_set_preset_sanitizes_name() -> None:
    control, _controller, window = make_control()

    control.set_preset("../Headphones")

    assert window.loaded_presets == ["Headphones"]


def test_dbus_control_present_window_forwards_startup_id() -> None:
    calls: list[str | None] = []
    app = SimpleNamespace(
        controller=None,
        window=None,
        background_mode=False,
        start_at_login=False,
        start_active_at_login=False,
        activate=lambda: None,
        get_dbus_connection=lambda: None,
        present_main_window=lambda startup_id=None: calls.append(startup_id),
        quit_fully=lambda: None,
    )
    control = dbus_control.MiniEqDbusControl(app)

    control.present_window("startup-token")

    assert calls == ["startup-token"]


def test_dbus_control_present_window_sets_startup_id_without_application_helper() -> None:
    controller = FakeController()
    window = FakeWindow(controller)
    app = SimpleNamespace(
        controller=controller,
        window=window,
        background_mode=False,
        start_at_login=False,
        start_active_at_login=False,
        activate=lambda: None,
        get_dbus_connection=lambda: None,
        quit_fully=lambda: None,
    )
    control = dbus_control.MiniEqDbusControl(app)

    control.present_window("startup-token")

    assert window.startup_ids == ["startup-token"]
    assert window.present_count == 1


def test_dbus_control_quit_delegates_to_application_full_quit() -> None:
    calls: list[str] = []
    app = SimpleNamespace(
        controller=None,
        window=None,
        background_mode=False,
        start_at_login=False,
        start_active_at_login=False,
        activate=lambda: None,
        get_dbus_connection=lambda: None,
        present_main_window=lambda startup_id=None: None,
        quit_fully=lambda: calls.append("quit"),
    )
    control = dbus_control.MiniEqDbusControl(app)

    control.quit()

    assert calls == ["quit"]


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
        "PresentWindowWithStartupId",
        "Quit",
    }
    assert {signal.name for signal in node_info.interfaces[0].signals} == {
        "AnalyzerLevelsChanged",
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
