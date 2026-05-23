from __future__ import annotations

from importlib.resources import files
from types import MethodType, SimpleNamespace

import pytest

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
        self.startup_ids: list[str] = []

    def present(self) -> None:
        self.present_count += 1

    def set_startup_id(self, startup_id: str) -> None:
        self.startup_ids.append(startup_id)

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
    application = SimpleNamespace(
        window=window,
        window_present_source_id=123,
        pending_startup_notification_id="startup-token",
    )
    application.prepare_window_startup_notification = lambda window: (
        app.MiniEqApplication.prepare_window_startup_notification(application, window)
    )

    assert app.MiniEqApplication.on_window_present_idle(application) is False
    assert application.window_present_source_id == 0
    assert window.present_count == 1
    assert window.startup_ids == ["startup-token"]
    assert application.pending_startup_notification_id is None


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
        queue_startup_notification_id=lambda _startup_id: None,
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
        pending_startup_notification_id="startup-token",
        queue_startup_notification_id=lambda _startup_id: None,
        prepare_window_startup_notification=lambda window: calls.append(("startup-id", window)),
    )

    app.MiniEqApplication.ensure_window(application, present=True)

    assert window.present_when_ready is True
    assert calls == [("startup-id", window), ("visible", True), "present", "state", "ready-scheduled"]


def test_prepare_window_startup_notification_sets_id_once() -> None:
    window = FakeWindow(ui_shutting_down=False)
    application = SimpleNamespace(pending_startup_notification_id="startup-token")

    app.MiniEqApplication.prepare_window_startup_notification(application, window)
    app.MiniEqApplication.prepare_window_startup_notification(application, window)

    assert window.startup_ids == ["startup-token"]
    assert application.pending_startup_notification_id is None


def test_startup_notification_id_prefers_wayland_activation_token(monkeypatch) -> None:
    monkeypatch.setenv("XDG_ACTIVATION_TOKEN", "wayland-token")
    monkeypatch.setenv("DESKTOP_STARTUP_ID", "x11-token")

    assert app.startup_notification_id_from_environment() == "wayland-token"


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


def test_run_from_args_captures_startup_token_before_adw_init(monkeypatch) -> None:
    calls: list[object] = []

    class FakeInstanceGuard:
        cleaned_filter_chains = []

        def __enter__(self):
            calls.append("guard-enter")
            return self

        def __exit__(self, _exc_type, _exc, _tb) -> None:
            calls.append("guard-exit")

    class FakeMiniEqApplication:
        def __init__(self, args, *, startup_notification_id: str | None = None) -> None:
            del args
            calls.append(("app", startup_notification_id))

        def run(self, argv: list[str]) -> int:
            calls.append(("run", bool(argv)))
            return 0

    def read_startup_token() -> str:
        calls.append("read-token")
        return "startup-token"

    def init_adw() -> None:
        calls.append("adw-init")

    monkeypatch.setattr(app, "startup_notification_id_from_environment", read_startup_token)
    monkeypatch.setattr(app.MiniEqInstanceGuard, "acquire", lambda: FakeInstanceGuard())
    monkeypatch.setattr(app.Adw, "init", init_adw)
    monkeypatch.setattr(app, "MiniEqApplication", FakeMiniEqApplication)
    args = SimpleNamespace(check_deps=False, install_desktop=False, background=False, headless=False)

    assert app.run_from_args(args) == 0
    assert calls == [
        "read-token",
        "guard-enter",
        "adw-init",
        ("app", "startup-token"),
        ("run", True),
        "guard-exit",
    ]


def test_install_unix_signal_handlers_uses_exported_glib_unix_source_api(monkeypatch) -> None:
    class FakeSource:
        def __init__(self, signum: int) -> None:
            self.signum = signum
            self.priority: int | None = None
            self.handler = None
            self.user_data = object()
            self.context = object()

        def set_priority(self, priority: int) -> None:
            self.priority = priority

        def set_callback(self, handler, user_data) -> None:
            self.handler = handler
            self.user_data = user_data

        def attach(self, context) -> int:
            self.context = context
            return len(sources)

    sources: list[FakeSource] = []
    callback_calls: list[str] = []

    def fake_signal_source_new(signum: int) -> FakeSource:
        source = FakeSource(signum)
        sources.append(source)
        return source

    monkeypatch.setattr(app.GLibUnix, "signal_source_new", fake_signal_source_new)

    source_ids = app.install_unix_signal_handlers(lambda: callback_calls.append("quit"))

    assert source_ids == [1, 2]
    assert [source.signum for source in sources] == [app.signal.SIGINT, app.signal.SIGTERM]
    assert [source.priority for source in sources] == [app.GLib.PRIORITY_DEFAULT, app.GLib.PRIORITY_DEFAULT]
    assert [source.user_data for source in sources] == [None, None]
    assert [source.context for source in sources] == [None, None]
    assert sources[0].handler() is False
    assert callback_calls == ["quit"]


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


def bind_window_start_methods(application: SimpleNamespace) -> None:
    for name in (
        "begin_window_start",
        "release_window_start_hold",
        "should_retry_startup_auto_route",
        "is_startup_auto_route_retryable_error",
        "retry_startup_auto_route_after_error",
        "on_window_start_retry_timeout",
        "fail_window_start",
        "raise_window_start_error",
        "start_window_controller",
    ):
        setattr(application, name, MethodType(getattr(app.MiniEqApplication, name), application))


def test_hidden_auto_route_startup_retries_until_output_is_ready(monkeypatch) -> None:
    calls: list[object] = []
    scheduled_callbacks = []
    attempts = 0

    class FakeController:
        def __init__(self, output_sink: str | None) -> None:
            nonlocal attempts
            attempts += 1
            calls.append(("controller", attempts, output_sink))
            if attempts == 1:
                raise app.AudioBackendError("output sink not found: ci_null_sink")

        def start(self, *, on_ready=None, on_error=None) -> None:
            del on_error
            calls.append("start")
            on_ready()

        def shutdown(self) -> None:
            calls.append("shutdown")

    class FakeMiniEqWindow:
        def __init__(self, application, controller, auto_route, initial_curve_label=None) -> None:
            del application, controller, initial_curve_label
            self.auto_route = auto_route
            self.startup_ready = False
            self.ui_shutting_down = False
            calls.append(("window", auto_route))

        def set_icon_name(self, icon_name: str) -> None:
            calls.append(("icon", icon_name))

        def set_visible(self, visible: bool) -> None:
            calls.append(("visible", visible))

        def schedule_startup_ready(self) -> None:
            calls.append("ready")

    def timeout_add_seconds(interval_seconds: int, callback):
        scheduled_callbacks.append(callback)
        calls.append(("timeout", interval_seconds))
        return 123

    monkeypatch.setattr(app, "install_app_icon", lambda: calls.append("icon-install"))
    monkeypatch.setattr(app, "SystemWideEqController", FakeController)
    monkeypatch.setattr(app, "MiniEqWindow", FakeMiniEqWindow)
    monkeypatch.setattr(app.GLib, "get_monotonic_time", lambda: 1_000)
    monkeypatch.setattr(app.GLib, "timeout_add_seconds", timeout_add_seconds)

    application = SimpleNamespace(
        args=SimpleNamespace(output_sink="ci_null_sink", import_apo=None, background=True, auto_route=True),
        controller=None,
        window=None,
        window_starting=False,
        window_start_hold=False,
        window_start_retry_source_id=0,
        window_start_retry_deadline_us=0,
        pending_present_when_ready=False,
        hold=lambda: calls.append("hold"),
        release=lambda: calls.append("release"),
        quit=lambda: calls.append("quit"),
        queue_startup_notification_id=lambda _startup_id: None,
        update_background_status=lambda: calls.append("background-status"),
        emit_control_state_changed=lambda: calls.append("state"),
    )
    bind_window_start_methods(application)

    app.MiniEqApplication.ensure_window(application, present=False)

    assert application.window is None
    assert application.window_starting is True
    assert application.window_start_retry_source_id == 123
    assert calls == [
        "icon-install",
        "hold",
        ("controller", 1, "ci_null_sink"),
        ("timeout", app.STARTUP_AUTO_ROUTE_RETRY_INTERVAL_SECONDS),
    ]

    assert scheduled_callbacks[0]() is False

    assert application.window is not None
    assert application.window.auto_route is True
    assert application.window_starting is False
    assert application.window_start_retry_source_id == 0
    assert calls[-9:] == [
        ("controller", 2, "ci_null_sink"),
        "start",
        ("window", True),
        ("icon", app.APP_ICON_NAME),
        ("visible", False),
        "ready",
        "background-status",
        "state",
        "release",
    ]
    assert calls[-1] == "release"
    assert "quit" not in calls


def test_visible_auto_route_startup_retries_until_output_is_ready(monkeypatch) -> None:
    calls: list[object] = []
    scheduled_callbacks = []
    attempts = 0

    class FakeController:
        def __init__(self, output_sink: str | None) -> None:
            nonlocal attempts
            attempts += 1
            calls.append(("controller", attempts, output_sink))
            if attempts == 1:
                raise app.PipeWireBackendError("PipeWire core sync failed: PipeWire core sync timed out")

        def start(self, *, on_ready=None, on_error=None) -> None:
            del on_error
            calls.append("start")
            on_ready()

        def shutdown(self) -> None:
            calls.append("shutdown")

    class FakeMiniEqWindow:
        def __init__(self, application, controller, auto_route, initial_curve_label=None) -> None:
            del application, controller, initial_curve_label
            self.auto_route = auto_route
            self.startup_ready = False
            self.ui_shutting_down = False
            calls.append(("window", auto_route))

        def set_icon_name(self, icon_name: str) -> None:
            calls.append(("icon", icon_name))

        def set_visible(self, visible: bool) -> None:
            calls.append(("visible", visible))

        def schedule_startup_ready(self) -> None:
            calls.append("ready")

    def timeout_add_seconds(interval_seconds: int, callback):
        scheduled_callbacks.append(callback)
        calls.append(("timeout", interval_seconds))
        return 123

    monkeypatch.setattr(app, "install_app_icon", lambda: calls.append("icon-install"))
    monkeypatch.setattr(app, "SystemWideEqController", FakeController)
    monkeypatch.setattr(app, "MiniEqWindow", FakeMiniEqWindow)
    monkeypatch.setattr(app.GLib, "get_monotonic_time", lambda: 1_000)
    monkeypatch.setattr(app.GLib, "timeout_add_seconds", timeout_add_seconds)

    application = SimpleNamespace(
        args=SimpleNamespace(output_sink=None, import_apo=None, background=False, auto_route=True),
        controller=None,
        window=None,
        window_starting=False,
        window_start_hold=False,
        window_start_retry_source_id=0,
        window_start_retry_deadline_us=0,
        pending_present_when_ready=False,
        hold=lambda: calls.append("hold"),
        release=lambda: calls.append("release"),
        quit=lambda: calls.append("quit"),
        queue_startup_notification_id=lambda _startup_id: None,
        update_background_status=lambda: calls.append("background-status"),
        emit_control_state_changed=lambda: calls.append("state"),
    )
    bind_window_start_methods(application)

    app.MiniEqApplication.ensure_window(application, present=True)

    assert application.window is None
    assert application.window_starting is True
    assert application.window_start_retry_source_id == 123
    assert calls == [
        "icon-install",
        "hold",
        ("controller", 1, None),
        ("timeout", app.STARTUP_AUTO_ROUTE_RETRY_INTERVAL_SECONDS),
    ]

    assert scheduled_callbacks[0]() is False

    assert application.window is not None
    assert application.window.auto_route is True
    assert application.window_starting is False
    assert application.window_start_retry_source_id == 0
    assert calls[-7:] == [
        ("controller", 2, None),
        "start",
        ("window", True),
        ("icon", app.APP_ICON_NAME),
        ("visible", False),
        "ready",
        "release",
    ]
    assert "quit" not in calls


def test_visible_startup_constructor_error_raises_system_exit(monkeypatch) -> None:
    calls: list[str] = []

    class FakeController:
        def __init__(self, output_sink: str | None) -> None:
            calls.append(f"controller:{output_sink}")
            raise RuntimeError("output sink not found: missing")

    monkeypatch.setattr(app, "install_app_icon", lambda: calls.append("icon-install"))
    monkeypatch.setattr(app, "SystemWideEqController", FakeController)

    application = SimpleNamespace(
        args=SimpleNamespace(output_sink="missing", import_apo=None, background=False, auto_route=False),
        controller=None,
        window=None,
        window_starting=False,
        window_start_hold=False,
        window_start_retry_source_id=0,
        window_start_retry_deadline_us=0,
        pending_present_when_ready=False,
        hold=lambda: calls.append("hold"),
        release=lambda: calls.append("release"),
        quit=lambda: calls.append("quit"),
        queue_startup_notification_id=lambda _startup_id: None,
    )
    bind_window_start_methods(application)

    with pytest.raises(SystemExit, match="output sink not found: missing"):
        app.MiniEqApplication.ensure_window(application, present=True)

    assert application.window is None
    assert application.window_starting is False
    assert application.pending_present_when_ready is False
    assert calls == ["icon-install", "hold", "controller:missing", "release"]


def test_auto_route_import_error_does_not_retry(monkeypatch) -> None:
    calls: list[object] = []

    class FakeController:
        def __init__(self, output_sink: str | None) -> None:
            calls.append(("controller", output_sink))

        def import_apo_preset(self, path: str) -> int:
            calls.append(("import", path))
            raise ValueError("invalid APO preset")

        def shutdown(self) -> None:
            calls.append("shutdown")

    def timeout_add_seconds(_interval_seconds: int, _callback):
        raise AssertionError("permanent startup errors should not schedule a retry")

    monkeypatch.setattr(app, "install_app_icon", lambda: calls.append("icon-install"))
    monkeypatch.setattr(app, "SystemWideEqController", FakeController)
    monkeypatch.setattr(app.GLib, "get_monotonic_time", lambda: 1_000)
    monkeypatch.setattr(app.GLib, "timeout_add_seconds", timeout_add_seconds)

    application = SimpleNamespace(
        args=SimpleNamespace(
            output_sink="ci_null_sink",
            import_apo="/tmp/broken.txt",
            background=False,
            auto_route=True,
        ),
        controller=None,
        window=None,
        window_starting=False,
        window_start_hold=False,
        window_start_retry_source_id=0,
        window_start_retry_deadline_us=0,
        pending_present_when_ready=False,
        hold=lambda: calls.append("hold"),
        release=lambda: calls.append("release"),
        quit=lambda: calls.append("quit"),
        queue_startup_notification_id=lambda _startup_id: None,
    )
    bind_window_start_methods(application)

    with pytest.raises(SystemExit, match="invalid APO preset"):
        app.MiniEqApplication.ensure_window(application, present=True)

    assert application.window_starting is False
    assert application.window_start_retry_source_id == 0
    assert application.pending_present_when_ready is False
    assert calls == [
        "icon-install",
        "hold",
        ("controller", "ci_null_sink"),
        ("import", "/tmp/broken.txt"),
        "shutdown",
        "release",
    ]


def test_second_normal_launch_presents_running_instance(monkeypatch, capsys) -> None:
    calls: list[str] = []

    def fail_acquire():
        raise app.MiniEqAlreadyRunningError("Mini EQ is already running")

    monkeypatch.setattr(app.MiniEqInstanceGuard, "acquire", fail_acquire)
    monkeypatch.setattr(app, "startup_notification_id_from_environment", lambda: "startup-token")
    monkeypatch.setattr(app, "call_present_window", lambda *, startup_id=None: calls.append(f"present:{startup_id}"))
    args = SimpleNamespace(check_deps=False, install_desktop=False, background=False)

    assert app.run_from_args(args) == 0
    assert calls == ["present:startup-token"]
    assert capsys.readouterr().err == ""


def test_second_background_launch_exits_without_presenting(monkeypatch, capsys) -> None:
    calls: list[str] = []

    def fail_acquire():
        raise app.MiniEqAlreadyRunningError("Mini EQ is already running")

    monkeypatch.setattr(app.MiniEqInstanceGuard, "acquire", fail_acquire)
    monkeypatch.setattr(app, "call_present_window", lambda: calls.append("present"))
    monkeypatch.setattr(
        app,
        "startup_notification_id_from_environment",
        lambda: (_ for _ in ()).throw(AssertionError("unexpected")),
    )
    args = SimpleNamespace(check_deps=False, install_desktop=False, background=True)

    assert app.run_from_args(args) == 0
    assert calls == []
    assert capsys.readouterr().err == ""
