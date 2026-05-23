from __future__ import annotations

import os
import signal
import sys
from argparse import Namespace

import gi

gi.require_version("Adw", "1")
gi.require_version("GLibUnix", "2.0")

from gi.repository import Adw, Gio, GLib, GLibUnix

from .appearance import apply_appearance_preference, load_appearance_preference
from .background import (
    load_background_mode,
    load_start_active_at_login,
    load_start_at_login,
    save_background_mode,
    save_start_active_at_login,
    save_start_at_login,
    set_background_status,
)
from .cli import parse_args
from .core import AudioBackendError
from .dbus_control import MiniEqDbusControl, call_present_window
from .desktop_integration import APP_ICON_NAME, APP_ID, install_app_icon, install_desktop_integration
from .glib_utils import destroy_glib_source
from .instance import MiniEqAlreadyRunningError, MiniEqInstanceGuard
from .pipewire_backend import PipeWireBackendError
from .routing import SystemWideEqController
from .window import MiniEqWindow
from .window_presets import imported_apo_curve_label

STARTUP_NOTIFICATION_ENV_KEYS = ("XDG_ACTIVATION_TOKEN", "DESKTOP_STARTUP_ID")
STARTUP_AUTO_ROUTE_RETRY_INTERVAL_SECONDS = 1
STARTUP_AUTO_ROUTE_RETRY_TIMEOUT_US = 30_000_000
STARTUP_AUTO_ROUTE_RETRYABLE_PIPEWIRE_PREFIXES = (
    "failed to connect to PipeWire",
    "failed to start PipeWire registry discovery",
    "failed to start PipeWire default metadata discovery",
    "PipeWire registry sync failed",
    "PipeWire metadata sync failed",
    "PipeWire core sync failed",
    "PipeWire initialization did not report:",
)


class MiniEqApplication(Adw.Application):
    def __init__(self, args: Namespace, startup_notification_id: str | None = None) -> None:
        super().__init__(application_id=APP_ID)
        self.args = args
        self.controller: SystemWideEqController | None = None
        self.window: MiniEqWindow | None = None
        self.dbus_control: MiniEqDbusControl | None = None
        self.signal_source_ids: list[int] = []
        self.window_present_source_id = 0
        self.window_starting = False
        self.window_start_hold = False
        self.window_start_retry_source_id = 0
        self.window_start_retry_deadline_us = 0
        self.window_start_last_error: Exception | None = None
        self.pending_present_when_ready = False
        self.pending_startup_notification_id = (
            None if bool(getattr(args, "background", False)) else startup_notification_id
        )
        self.background_mode = load_background_mode() or bool(getattr(args, "background", False))
        self.start_at_login = load_start_at_login()
        self.start_active_at_login = load_start_active_at_login() and self.start_at_login

    def do_startup(self) -> None:
        Adw.Application.do_startup(self)
        apply_appearance_preference(load_appearance_preference(), self.get_style_manager())
        install_app_icon()
        self.install_standard_actions()
        self.dbus_control = MiniEqDbusControl(self)
        self.dbus_control.register()
        self.signal_source_ids = install_unix_signal_handlers(self.quit_fully)

    def install_standard_actions(self) -> None:
        quit_action = Gio.SimpleAction.new("quit", None)
        quit_action.connect("activate", self.on_quit_action)
        self.add_action(quit_action)
        self.set_accels_for_action("app.quit", ["<primary>q"])

        close_action = Gio.SimpleAction.new("close", None)
        close_action.connect("activate", self.on_close_action)
        self.add_action(close_action)
        self.set_accels_for_action("app.close", ["<primary>w"])

    def on_quit_action(self, _action: Gio.SimpleAction, _parameter: GLib.Variant | None) -> None:
        self.quit_fully()

    def on_close_action(self, _action: Gio.SimpleAction, _parameter: GLib.Variant | None) -> None:
        if self.window is not None and not self.window.ui_shutting_down:
            self.window.close()
            return

        self.quit()

    def do_activate(self) -> None:
        self.ensure_window(present=not bool(getattr(self.args, "background", False)))

    def ensure_window(self, *, present: bool, startup_id: str | None = None) -> None:
        install_app_icon()
        self.queue_startup_notification_id(startup_id)

        if self.window is not None:
            if self.window.ui_shutting_down:
                return
            if present:
                self.window.present_when_ready = True
                if self.window.startup_ready:
                    self.prepare_window_startup_notification(self.window)
                    self.window.set_visible(True)
                    self.window.present()
                    self.emit_control_state_changed()
            self.window.schedule_startup_ready()
            return

        if self.window_starting:
            self.pending_present_when_ready = self.pending_present_when_ready or present
            return

        self.begin_window_start(present)
        self.start_window_controller()

    def begin_window_start(self, present: bool) -> None:
        self.window_starting = True
        self.window_start_hold = True
        self.pending_present_when_ready = present
        if self.should_retry_startup_auto_route():
            self.window_start_retry_deadline_us = GLib.get_monotonic_time() + STARTUP_AUTO_ROUTE_RETRY_TIMEOUT_US
        else:
            self.window_start_retry_deadline_us = 0
        self.hold()

    def release_window_start_hold(self) -> None:
        if not self.window_start_hold:
            return

        self.window_start_hold = False
        self.release()

    def should_retry_startup_auto_route(self) -> bool:
        return bool(getattr(self.args, "auto_route", False))

    def is_startup_auto_route_retryable_error(self, exc: Exception) -> bool:
        message = str(exc)
        if isinstance(exc, AudioBackendError):
            return message.startswith("output sink not found:")

        if isinstance(exc, PipeWireBackendError):
            return message.startswith(STARTUP_AUTO_ROUTE_RETRYABLE_PIPEWIRE_PREFIXES)

        return False

    def retry_startup_auto_route_after_error(self, exc: Exception) -> bool:
        if not self.should_retry_startup_auto_route() or not self.is_startup_auto_route_retryable_error(exc):
            return False

        deadline_us = getattr(self, "window_start_retry_deadline_us", 0)
        if deadline_us <= 0 or GLib.get_monotonic_time() >= deadline_us:
            return False

        self.window_start_last_error = exc
        if self.window_start_retry_source_id == 0:
            self.window_start_retry_source_id = GLib.timeout_add_seconds(
                STARTUP_AUTO_ROUTE_RETRY_INTERVAL_SECONDS,
                self.on_window_start_retry_timeout,
            )
        return True

    def on_window_start_retry_timeout(self) -> bool:
        self.window_start_retry_source_id = 0
        if not self.window_starting or self.window is not None:
            return False

        self.start_window_controller()
        return False

    def fail_window_start(self, exc: Exception) -> None:
        self.window_starting = False
        self.pending_present_when_ready = False
        print(str(exc), file=sys.stderr)
        self.release_window_start_hold()
        self.quit()

    def raise_window_start_error(self, exc: Exception) -> None:
        self.window_starting = False
        self.pending_present_when_ready = False
        self.release_window_start_hold()
        raise SystemExit(str(exc)) from exc

    def start_window_controller(self) -> None:
        controller: SystemWideEqController | None = None
        initial_curve_label: str | None = None

        try:
            controller = SystemWideEqController(self.args.output_sink)
            if self.args.import_apo:
                controller.import_apo_preset(self.args.import_apo)
                initial_curve_label = imported_apo_curve_label(self.args.import_apo)
        except Exception as exc:
            if controller is not None:
                controller.shutdown()
            if self.retry_startup_auto_route_after_error(exc):
                return
            if self.should_retry_startup_auto_route() and self.is_startup_auto_route_retryable_error(exc):
                self.fail_window_start(exc)
                return
            self.raise_window_start_error(exc)
            return

        self.controller = controller

        def on_ready() -> None:
            if self.controller is not controller:
                return

            try:
                self.window_starting = False
                present_when_ready = self.pending_present_when_ready
                self.pending_present_when_ready = False
                self.window = MiniEqWindow(
                    self, self.controller, self.args.auto_route, initial_curve_label=initial_curve_label
                )
                self.window.set_icon_name(APP_ICON_NAME)
                self.window.present_when_ready = present_when_ready
                self.window.set_visible(False)
                self.window.schedule_startup_ready()
                if not present_when_ready:
                    self.update_background_status()
                    self.emit_control_state_changed()
            finally:
                self.release_window_start_hold()

        def on_error(exc: Exception) -> None:
            try:
                controller.shutdown()
            finally:
                if self.controller is controller:
                    self.controller = None
            if self.retry_startup_auto_route_after_error(exc):
                return
            self.fail_window_start(exc)

        controller.start(on_ready=on_ready, on_error=on_error)

    def present_main_window(self, startup_id: str | None = None) -> None:
        self.ensure_window(present=True, startup_id=startup_id)

    def quit_fully(self) -> None:
        if self.window is not None and not self.window.ui_shutting_down:
            self.window.begin_close_request_shutdown(force_quit=True)
            return

        self.quit()

    def set_background_mode(self, enabled: bool) -> None:
        self.background_mode = bool(enabled)
        save_background_mode(self.background_mode)
        self.emit_control_state_changed()

    def set_start_at_login(self, enabled: bool) -> None:
        self.start_at_login = bool(enabled)
        save_start_at_login(self.start_at_login)
        if not self.start_at_login and self.start_active_at_login:
            self.start_active_at_login = False
            save_start_active_at_login(False)
        self.emit_control_state_changed()

    def set_start_active_at_login(self, enabled: bool) -> None:
        self.start_active_at_login = bool(enabled) and self.start_at_login
        save_start_active_at_login(self.start_active_at_login)
        self.emit_control_state_changed()

    def update_background_status(self) -> None:
        if self.controller is not None and self.controller.routed and self.controller.eq_enabled:
            message = "System-wide EQ active"
        else:
            message = "Mini EQ ready"

        try:
            set_background_status(message)
        except Exception:
            pass

    def on_window_present_idle(self) -> bool:
        self.window_present_source_id = 0
        if self.window is None or self.window.ui_shutting_down:
            return False

        self.prepare_window_startup_notification(self.window)
        self.window.present()
        return False

    def queue_startup_notification_id(self, startup_id: str | None) -> None:
        if startup_id:
            self.pending_startup_notification_id = startup_id

    def prepare_window_startup_notification(self, window: object) -> None:
        startup_id = self.pending_startup_notification_id
        if not startup_id:
            return

        self.pending_startup_notification_id = None
        set_startup_id = getattr(window, "set_startup_id", None)
        if callable(set_startup_id):
            set_startup_id(startup_id)

    def emit_control_state_changed(self) -> None:
        if self.window is not None and not self.window.get_visible():
            self.update_background_status()
        if self.dbus_control is not None:
            self.dbus_control.emit_state_changed()

    def emit_control_analyzer_levels_changed(self) -> None:
        if self.dbus_control is not None:
            self.dbus_control.emit_analyzer_levels_changed()

    def emit_control_presets_changed(self) -> None:
        if self.dbus_control is not None:
            self.dbus_control.emit_presets_changed()

    def do_shutdown(self) -> None:
        for source_id in self.signal_source_ids:
            destroy_glib_source(source_id)
        self.signal_source_ids = []
        if self.window_start_retry_source_id > 0:
            destroy_glib_source(self.window_start_retry_source_id)
        self.window_start_retry_source_id = 0
        if self.window_present_source_id > 0:
            destroy_glib_source(self.window_present_source_id)
        self.window_present_source_id = 0

        if self.window is not None:
            self.window.prepare_for_shutdown()

        if self.controller is not None:
            self.controller.shutdown()

        if self.dbus_control is not None:
            self.dbus_control.unregister()
            self.dbus_control = None

        Adw.Application.do_shutdown(self)


def run_headless(args: Namespace) -> int:
    if args.duration is not None and args.duration > 0:
        duration_ms = int(args.duration * 1000)
    else:
        duration_ms = 0

    controller: SystemWideEqController | None = None
    exit_code = 0
    loop = GLib.MainLoop()
    signal_source_ids = install_unix_signal_handlers(loop.quit)

    try:
        controller = SystemWideEqController(args.output_sink)

        if args.import_apo:
            controller.import_apo_preset(args.import_apo)

        if duration_ms > 0:
            GLib.timeout_add(duration_ms, lambda: (loop.quit(), False)[1])

        def on_ready() -> None:
            nonlocal exit_code

            try:
                if args.auto_route:
                    controller.route_system_audio(True)
            except Exception as exc:
                exit_code = 1
                print(str(exc), file=sys.stderr)
                loop.quit()

        def on_error(exc: Exception) -> None:
            nonlocal exit_code

            exit_code = 1
            print(str(exc), file=sys.stderr)
            loop.quit()

        controller.start(on_ready=on_ready, on_error=on_error)

        try:
            if exit_code == 0:
                loop.run()
        except KeyboardInterrupt:
            pass
    finally:
        signal_source_ids.clear()
        if controller is not None:
            controller.shutdown()

    return exit_code


def install_unix_signal_handlers(callback) -> list[int]:
    def on_signal(_data=None) -> bool:
        callback()
        return False

    def add_signal_source(signum: signal.Signals) -> int:
        source = GLibUnix.signal_source_new(signum)
        source.set_priority(GLib.PRIORITY_DEFAULT)
        source.set_callback(on_signal, None)
        return source.attach(None)

    return [
        add_signal_source(signal.SIGINT),
        add_signal_source(signal.SIGTERM),
    ]


def run_from_args(args: Namespace) -> int:
    if args.check_deps:
        from .deps import main as check_deps_main

        return check_deps_main()

    if args.install_desktop:
        install_desktop_integration()
        return 0

    startup_notification_id = None if getattr(args, "background", False) else startup_notification_id_from_environment()

    try:
        instance_guard = MiniEqInstanceGuard.acquire()
    except MiniEqAlreadyRunningError as exc:
        if getattr(args, "background", False):
            return 0

        try:
            call_present_window(startup_id=startup_notification_id)
            return 0
        except Exception:
            pass

        print(str(exc), file=sys.stderr)
        return 2

    with instance_guard:
        for stale in instance_guard.cleaned_filter_chains:
            print(f"removed stale Mini EQ filter-chain pid {stale.pid}", file=sys.stderr)

        Adw.init()

        if args.headless:
            return run_headless(args)

        app = MiniEqApplication(args, startup_notification_id=startup_notification_id)
        return app.run([sys.argv[0]])


def main(argv: list[str]) -> int:
    return run_from_args(parse_args(argv))


def startup_notification_id_from_environment() -> str | None:
    for key in STARTUP_NOTIFICATION_ENV_KEYS:
        startup_id = os.environ.get(key, "").strip()
        if startup_id:
            return startup_id

    return None


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
