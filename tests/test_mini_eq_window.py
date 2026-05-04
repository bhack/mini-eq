from __future__ import annotations

from types import MethodType, SimpleNamespace

from tests._mini_eq_imports import import_mini_eq_module

window = import_mini_eq_module("window")


class FakeSwitch:
    def __init__(self, active: bool) -> None:
        self.active = active

    def get_active(self) -> bool:
        return self.active

    def set_active(self, active: bool) -> None:
        self.active = active


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

    window.MiniEqWindow.on_route_changed(fake_window, route_switch, None)

    assert route_switch.get_active() is False
    assert fake_window.updating_ui is False
    assert ("status", "metadata permission denied") in calls
