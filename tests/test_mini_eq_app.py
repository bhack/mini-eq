from __future__ import annotations

from importlib.resources import files
from types import SimpleNamespace

from tests._mini_eq_imports import import_mini_eq_module

app = import_mini_eq_module("app")


def test_style_resource_is_packaged_with_application_css() -> None:
    css = files("mini_eq").joinpath("style.css").read_text(encoding="utf-8")

    assert ".toolbar-row" in css
    assert ".headroom-panel" in css


class FakeWindow:
    def __init__(self, *, ui_shutting_down: bool) -> None:
        self.ui_shutting_down = ui_shutting_down
        self.present_count = 0
        self.close_count = 0
        self.shutdown_count = 0

    def present(self) -> None:
        self.present_count += 1

    def close(self) -> None:
        self.close_count += 1

    def begin_close_request_shutdown(self, *, force_quit: bool = False) -> None:
        del force_quit
        self.shutdown_count += 1


class FakeApplication:
    def __init__(self, *, window: FakeWindow | None = None) -> None:
        self.window = window
        self.quit_count = 0

    def quit(self) -> None:
        self.quit_count += 1

    def quit_fully(self) -> None:
        if self.window is not None and not self.window.ui_shutting_down:
            self.window.begin_close_request_shutdown(force_quit=True)
            return
        self.quit()


def test_window_present_idle_skips_window_during_shutdown() -> None:
    window = FakeWindow(ui_shutting_down=True)
    application = SimpleNamespace(window=window, window_present_source_id=123)

    assert app.MiniEqApplication.on_window_present_idle(application) is False
    assert application.window_present_source_id == 0
    assert window.present_count == 0


def test_window_present_idle_presents_active_window() -> None:
    window = FakeWindow(ui_shutting_down=False)
    calls: list[str] = []
    application = SimpleNamespace(
        window=window,
        window_present_source_id=123,
        finish_startup_notification=lambda: calls.append("startup-complete"),
    )

    assert app.MiniEqApplication.on_window_present_idle(application) is False
    assert application.window_present_source_id == 0
    assert window.present_count == 1
    assert calls == ["startup-complete"]


def test_ensure_window_defers_existing_window_present_until_startup_ready(monkeypatch) -> None:
    monkeypatch.setattr(app, "install_app_icon", lambda: None)
    calls: list[object] = []
    window = SimpleNamespace(
        ui_shutting_down=False,
        startup_ready=False,
        present_when_ready=False,
        set_visible=lambda visible: calls.append(("visible", visible)),
        present=lambda: calls.append("present"),
        schedule_startup_ready=lambda: calls.append("ready-scheduled"),
    )
    application = SimpleNamespace(
        window=window,
        emit_control_state_changed=lambda: calls.append("state"),
        finish_startup_notification=lambda: calls.append("startup-complete"),
    )

    app.MiniEqApplication.ensure_window(application, present=True)

    assert window.present_when_ready is True
    assert calls == ["ready-scheduled"]


def test_ensure_window_presents_existing_ready_window_immediately(monkeypatch) -> None:
    monkeypatch.setattr(app, "install_app_icon", lambda: None)
    calls: list[object] = []
    window = SimpleNamespace(
        ui_shutting_down=False,
        startup_ready=True,
        present_when_ready=False,
        set_visible=lambda visible: calls.append(("visible", visible)),
        present=lambda: calls.append("present"),
        schedule_startup_ready=lambda: calls.append("ready-scheduled"),
    )
    application = SimpleNamespace(
        window=window,
        emit_control_state_changed=lambda: calls.append("state"),
        finish_startup_notification=lambda: calls.append("startup-complete"),
    )

    app.MiniEqApplication.ensure_window(application, present=True)

    assert window.present_when_ready is True
    assert calls == [("visible", True), "present", "startup-complete", "state", "ready-scheduled"]


def test_finish_startup_notification_completes_current_gdk_startup_id(monkeypatch) -> None:
    calls: list[object] = []
    display = SimpleNamespace(
        get_startup_notification_id=lambda: "mini-eq-startup",
        notify_startup_complete=lambda startup_id: calls.append(("complete", startup_id)),
    )
    monkeypatch.setattr(app.Gdk.Display, "get_default", lambda: display)

    app.MiniEqApplication.finish_startup_notification(SimpleNamespace())

    assert calls == [("complete", "mini-eq-startup")]


def test_finish_startup_notification_ignores_missing_gdk_startup_id(monkeypatch) -> None:
    display = SimpleNamespace(
        get_startup_notification_id=lambda: None,
        notify_startup_complete=lambda _startup_id: (_ for _ in ()).throw(AssertionError("unexpected")),
    )
    monkeypatch.setattr(app.Gdk.Display, "get_default", lambda: display)

    app.MiniEqApplication.finish_startup_notification(SimpleNamespace())


def test_run_headless_skips_loop_after_synchronous_start_error(monkeypatch, capsys) -> None:
    calls: list[str] = []

    class FakeLoop:
        def run(self) -> None:
            calls.append("run")
            raise AssertionError("run should not be called after a synchronous startup error")

        def quit(self) -> None:
            calls.append("quit")

    class FakeController:
        def __init__(self, output_sink: str | None) -> None:
            calls.append(f"controller:{output_sink}")

        def start(self, *, on_ready=None, on_error=None) -> None:
            calls.append("start")
            on_error(RuntimeError("startup failed"))

        def shutdown(self) -> None:
            calls.append("shutdown")

    monkeypatch.setattr(app.GLib, "MainLoop", FakeLoop)
    monkeypatch.setattr(app, "install_unix_signal_handlers", lambda _callback: [])
    monkeypatch.setattr(app, "SystemWideEqController", FakeController)
    args = SimpleNamespace(duration=None, output_sink="speakers", import_apo=None, auto_route=False)

    assert app.run_headless(args) == 1
    assert calls == ["controller:speakers", "start", "quit", "shutdown"]
    assert "startup failed" in capsys.readouterr().err


def test_close_action_closes_active_window() -> None:
    window = FakeWindow(ui_shutting_down=False)
    application = FakeApplication(window=window)

    app.MiniEqApplication.on_close_action(application, None, None)

    assert window.close_count == 1
    assert application.quit_count == 0


def test_close_action_quits_without_active_window() -> None:
    application = FakeApplication()

    app.MiniEqApplication.on_close_action(application, None, None)

    assert application.quit_count == 1


def test_quit_action_quits_application() -> None:
    application = FakeApplication()

    app.MiniEqApplication.on_quit_action(application, None, None)

    assert application.quit_count == 1


def test_quit_action_closes_active_window_before_quitting() -> None:
    window = FakeWindow(ui_shutting_down=False)
    application = FakeApplication(window=window)

    app.MiniEqApplication.on_quit_action(application, None, None)

    assert window.shutdown_count == 1
    assert window.close_count == 0
    assert application.quit_count == 0


def test_disabling_start_at_login_clears_start_active_setting(monkeypatch) -> None:
    saved_start: list[bool] = []
    saved_active: list[bool] = []
    calls: list[str] = []
    application = SimpleNamespace(
        start_at_login=True,
        start_active_at_login=True,
        emit_control_state_changed=lambda: calls.append("state"),
    )
    monkeypatch.setattr(app, "save_start_at_login", lambda enabled: saved_start.append(enabled))
    monkeypatch.setattr(app, "save_start_active_at_login", lambda enabled: saved_active.append(enabled))

    app.MiniEqApplication.set_start_at_login(application, False)

    assert application.start_at_login is False
    assert application.start_active_at_login is False
    assert saved_start == [False]
    assert saved_active == [False]
    assert calls == ["state"]


def test_start_active_at_login_requires_start_at_login(monkeypatch) -> None:
    saved_active: list[bool] = []
    calls: list[str] = []
    application = SimpleNamespace(
        start_at_login=False,
        start_active_at_login=False,
        emit_control_state_changed=lambda: calls.append("state"),
    )
    monkeypatch.setattr(app, "save_start_active_at_login", lambda enabled: saved_active.append(enabled))

    app.MiniEqApplication.set_start_active_at_login(application, True)

    assert application.start_active_at_login is False
    assert saved_active == [False]
    assert calls == ["state"]


def test_start_active_at_login_can_be_saved_when_start_at_login_is_enabled(monkeypatch) -> None:
    saved_active: list[bool] = []
    calls: list[str] = []
    application = SimpleNamespace(
        start_at_login=True,
        start_active_at_login=False,
        emit_control_state_changed=lambda: calls.append("state"),
    )
    monkeypatch.setattr(app, "save_start_active_at_login", lambda enabled: saved_active.append(enabled))

    app.MiniEqApplication.set_start_active_at_login(application, True)

    assert application.start_active_at_login is True
    assert saved_active == [True]
    assert calls == ["state"]


def test_second_normal_launch_presents_running_instance(monkeypatch, capsys) -> None:
    calls: list[str] = []

    def fail_acquire():
        raise app.MiniEqAlreadyRunningError("Mini EQ is already running")

    monkeypatch.setattr(app.MiniEqInstanceGuard, "acquire", fail_acquire)
    monkeypatch.setattr(app, "call_present_window", lambda: calls.append("present"))
    args = SimpleNamespace(check_deps=False, install_desktop=False, background=False)

    assert app.run_from_args(args) == 0
    assert calls == ["present"]
    assert capsys.readouterr().err == ""


def test_second_background_launch_exits_without_presenting(monkeypatch, capsys) -> None:
    calls: list[str] = []

    def fail_acquire():
        raise app.MiniEqAlreadyRunningError("Mini EQ is already running")

    monkeypatch.setattr(app.MiniEqInstanceGuard, "acquire", fail_acquire)
    monkeypatch.setattr(app, "call_present_window", lambda: calls.append("present"))
    args = SimpleNamespace(check_deps=False, install_desktop=False, background=True)

    assert app.run_from_args(args) == 0
    assert calls == []
    assert capsys.readouterr().err == ""
