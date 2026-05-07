from __future__ import annotations

from types import MethodType, SimpleNamespace

from tests._mini_eq_imports import import_mini_eq_module

window = import_mini_eq_module("window")


class FakeSwitch:
    def __init__(self, active: bool) -> None:
        self.active = active
        self.state = active

    def get_active(self) -> bool:
        return self.active

    def set_active(self, active: bool) -> None:
        self.active = active

    def get_state(self) -> bool:
        return self.state

    def set_state(self, state: bool) -> None:
        self.state = state


def test_on_close_request_starts_custom_shutdown_sequence() -> None:
    calls: list[str] = []
    fake_window = SimpleNamespace(
        ui_shutting_down=False,
        begin_close_request_shutdown=lambda: calls.append("begin"),
    )

    handled = window.MiniEqWindow.on_close_request(fake_window, None)

    assert handled is True
    assert calls == ["begin"]


def test_compact_warning_title_keeps_bluetooth_warning_glanceable() -> None:
    assert (
        window.compact_warning_title(
            "Bluetooth output is in headset mode. Switch back to A2DP for full-band music playback."
        )
        == "Headset"
    )


def test_begin_close_request_shutdown_restores_routing_before_delayed_quit(monkeypatch) -> None:
    scheduled: list[tuple[int, object]] = []
    application = SimpleNamespace(quit_count=0)
    application.quit = lambda: setattr(application, "quit_count", application.quit_count + 1)
    calls: list[object] = []

    monkeypatch.setattr(
        window.GLib,
        "timeout_add",
        lambda delay_ms, callback: scheduled.append((delay_ms, callback)) or 321,
    )

    fake_window = SimpleNamespace(
        ui_shutting_down=False,
        close_finish_source_id=0,
        updating_ui=False,
        route_switch=FakeSwitch(True),
        controller=SimpleNamespace(
            route_system_audio=lambda enabled, announce=True, refresh_output=True: calls.append(
                ("route", enabled, announce, refresh_output)
            )
        ),
        update_info_label=lambda: calls.append("info"),
        update_status_summary=lambda: calls.append("summary"),
        set_visible=lambda visible: calls.append(("visible", visible)),
        prepare_for_shutdown=lambda: calls.append("prepare"),
        get_application=lambda: application,
    )
    fake_window.finish_close_request = MethodType(window.MiniEqWindow.finish_close_request, fake_window)

    window.MiniEqWindow.begin_close_request_shutdown(fake_window)

    assert fake_window.route_switch.get_active() is False
    assert fake_window.updating_ui is False
    assert fake_window.close_finish_source_id == 321
    assert calls == [
        ("route", False, False, False),
        "info",
        "summary",
        ("visible", False),
        "prepare",
    ]
    assert scheduled[0][0] == window.ROUTING_CLOSE_SETTLE_MS

    scheduled[0][1]()

    assert fake_window.close_finish_source_id == 0
    assert application.quit_count == 1


def test_begin_close_request_shutdown_hides_when_background_mode_is_enabled() -> None:
    calls: list[object] = []
    application = SimpleNamespace(background_mode=True)

    fake_window = SimpleNamespace(
        ui_shutting_down=False,
        close_finish_source_id=0,
        updating_ui=False,
        route_switch=FakeSwitch(True),
        controller=SimpleNamespace(
            route_system_audio=lambda enabled, announce=True, refresh_output=True: calls.append(
                ("route", enabled, announce, refresh_output)
            )
        ),
        set_visible=lambda visible: calls.append(("visible", visible)),
        notify_control_state_changed=lambda: calls.append("notify"),
        get_application=lambda: application,
    )
    application.update_background_status = lambda: calls.append("background-status")

    window.MiniEqWindow.begin_close_request_shutdown(fake_window)

    assert fake_window.route_switch.get_active() is True
    assert fake_window.close_finish_source_id == 0
    assert calls == [
        ("visible", False),
        "notify",
        "background-status",
    ]


def test_post_present_setup_routes_before_starting_monitor_for_auto_route() -> None:
    calls: list[object] = []
    controller = SimpleNamespace(routed=False)

    def route_system_audio(enabled: bool) -> None:
        calls.append(("route", enabled))
        controller.routed = enabled

    controller.route_system_audio = route_system_audio

    fake_window = SimpleNamespace(
        post_present_source_id=99,
        ui_shutting_down=False,
        post_present_ready=False,
        auto_route_on_startup=True,
        updating_ui=False,
        present_after_setup=False,
        route_switch=FakeSwitch(False),
        controller=controller,
        start_preset_monitoring=lambda: calls.append("preset-monitor"),
        apply_output_preset_for_current_output=lambda: calls.append("output-preset"),
        update_eq_power_indicator=lambda: calls.append("power"),
        update_info_label=lambda: calls.append("info"),
        update_status_summary=lambda: calls.append("summary"),
        update_focus_summary=lambda: calls.append("focus"),
        start_analyzer_preview=lambda: calls.append("monitor"),
        notify_control_state_changed=lambda: calls.append("notify"),
        set_status=lambda message: calls.append(("status", message)),
        present=lambda: calls.append("present"),
    )

    keep_source = window.MiniEqWindow.on_post_present_setup_idle(fake_window)

    assert keep_source is False
    assert fake_window.post_present_source_id == 0
    assert fake_window.post_present_ready is True
    assert fake_window.route_switch.get_active() is True
    assert fake_window.route_switch.get_state() is True
    assert calls == [
        "preset-monitor",
        "output-preset",
        ("route", True),
        "power",
        "info",
        "summary",
        "focus",
        "monitor",
        "notify",
    ]


def test_on_route_changed_resets_switch_when_routing_fails() -> None:
    calls: list[object] = []

    def fail_route(_enabled: bool) -> None:
        raise RuntimeError("metadata permission denied")

    fake_window = SimpleNamespace(
        updating_ui=False,
        controller=SimpleNamespace(
            eq_enabled=True,
            routed=False,
            route_system_audio=fail_route,
        ),
        update_eq_power_indicator=lambda: calls.append("power"),
        update_info_label=lambda: calls.append("info"),
        update_status_summary=lambda: calls.append("summary"),
        update_focus_summary=lambda: calls.append("focus"),
        set_status=lambda message: calls.append(("status", message)),
        notify_control_state_changed=lambda: calls.append("notify"),
    )
    route_switch = FakeSwitch(True)

    handled = window.MiniEqWindow.on_route_changed(fake_window, route_switch, None)

    assert handled is True
    assert route_switch.get_active() is False
    assert route_switch.get_state() is False
    assert fake_window.updating_ui is False
    assert ("status", "metadata permission denied") in calls


def test_on_route_changed_syncs_bypass_when_controller_enables_eq() -> None:
    calls: list[object] = []
    controller = SimpleNamespace(eq_enabled=False, routed=False)

    def route_system_audio(enabled: bool) -> None:
        calls.append(("route", enabled))
        controller.eq_enabled = True
        controller.routed = enabled

    controller.route_system_audio = route_system_audio

    fake_window = SimpleNamespace(
        updating_ui=False,
        controller=controller,
        bypass_switch=FakeSwitch(False),
        update_eq_power_indicator=lambda: calls.append("power"),
        update_info_label=lambda: calls.append("info"),
        update_status_summary=lambda: calls.append("summary"),
        update_focus_summary=lambda: calls.append("focus"),
        invalidate_graph_response_cache=lambda: calls.append("invalidate"),
        queue_graph_draw=lambda: calls.append("draw"),
        update_preset_state=lambda: calls.append("preset-state"),
        set_status=lambda message: calls.append(("status", message)),
        notify_control_state_changed=lambda: calls.append("notify"),
    )
    route_switch = FakeSwitch(True)

    handled = window.MiniEqWindow.on_route_changed(fake_window, route_switch, None)

    assert handled is True
    assert fake_window.bypass_switch.get_active() is True
    assert fake_window.bypass_switch.get_state() is True
    assert route_switch.get_state() is True
    assert fake_window.updating_ui is False
    assert calls == [
        ("route", True),
        "power",
        "info",
        "summary",
        "focus",
        "invalidate",
        "draw",
        "preset-state",
        ("status", "System-wide EQ On"),
        "notify",
    ]


def test_on_bypass_changed_resets_switch_when_engine_update_fails() -> None:
    calls: list[object] = []

    def fail_enabled(_enabled: bool) -> None:
        raise RuntimeError("control update failed")

    fake_window = SimpleNamespace(
        updating_ui=False,
        controller=SimpleNamespace(eq_enabled=True, set_eq_enabled=fail_enabled),
        update_eq_power_indicator=lambda: calls.append("power"),
        update_info_label=lambda: calls.append("info"),
        update_status_summary=lambda: calls.append("summary"),
        invalidate_graph_response_cache=lambda: calls.append("invalidate"),
        queue_graph_draw=lambda: calls.append("draw"),
        update_preset_state=lambda: calls.append("preset-state"),
        set_status=lambda message: calls.append(("status", message)),
        notify_control_state_changed=lambda: calls.append("notify"),
    )
    bypass_switch = FakeSwitch(False)

    handled = window.MiniEqWindow.on_bypass_changed(fake_window, bypass_switch, None)

    assert handled is True
    assert bypass_switch.get_active() is True
    assert bypass_switch.get_state() is True
    assert fake_window.updating_ui is False
    assert calls == ["power", ("status", "control update failed")]
