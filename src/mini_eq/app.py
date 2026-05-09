from __future__ import annotations

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
from .dbus_control import MiniEqDbusControl, call_present_window
from .desktop_integration import APP_ICON_NAME, APP_ID, install_app_icon, install_desktop_integration
from .glib_utils import destroy_glib_source
from .instance import MiniEqAlreadyRunningError, MiniEqInstanceGuard
from .routing import SystemWideEqController
from .window import MiniEqWindow


class MiniEqApplication(Adw.Application):
    def __init__(self, args: Namespace) -> None:
        super().__init__(application_id=APP_ID)
        self.args = args
        self.controller: SystemWideEqController | None = None
        self.window: MiniEqWindow | None = None
        self.dbus_control: MiniEqDbusControl | None = None
        self.signal_source_ids: list[int] = []
        self.window_present_source_id = 0
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

    def ensure_window(self, *, present: bool) -> None:
        install_app_icon()

        if self.window is not None:
            if self.window.ui_shutting_down:
                return
            if present:
                self.window.present_after_setup = True
                self.window.set_visible(True)
                self.window.present()
                self.emit_control_state_changed()
            self.window.schedule_post_present_setup()
            return

        controller: SystemWideEqController | None = None

        try:
            controller = SystemWideEqController(self.args.output_sink)
            controller.start()

            if self.args.import_apo:
                controller.import_apo_preset(self.args.import_apo)
        except Exception as exc:
            if controller is not None:
                controller.shutdown()
            raise SystemExit(str(exc)) from exc

        self.controller = controller
        self.window = MiniEqWindow(self, self.controller, self.args.auto_route)
        self.window.set_icon_name(APP_ICON_NAME)
        self.window.present_after_setup = present
        self.window.set_visible(present)
        if present:
            self.window.present()
        self.window.schedule_post_present_setup()
        if present:
            self.window_present_source_id = GLib.idle_add(self.on_window_present_idle)
        else:
            self.update_background_status()
            self.emit_control_state_changed()

    def present_main_window(self) -> None:
        self.ensure_window(present=True)

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

        self.window.present()
        return False

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

    try:
        controller = SystemWideEqController(args.output_sink)
        controller.start()

        if args.import_apo:
            controller.import_apo_preset(args.import_apo)

        if args.auto_route:
            controller.route_system_audio(True)

        loop = GLib.MainLoop()
        signal_source_ids = install_unix_signal_handlers(loop.quit)

        if duration_ms > 0:
            GLib.timeout_add(duration_ms, lambda: (loop.quit(), False)[1])

        try:
            loop.run()
        except KeyboardInterrupt:
            pass
        finally:
            signal_source_ids.clear()
    finally:
        if controller is not None:
            controller.shutdown()

    return 0


def install_unix_signal_handlers(callback) -> list[int]:
    def on_signal(_data=None) -> bool:
        callback()
        return False

    return [
        GLibUnix.signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, on_signal, None),
        GLibUnix.signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, on_signal, None),
    ]


def run_from_args(args: Namespace) -> int:
    if args.check_deps:
        from .deps import main as check_deps_main

        return check_deps_main()

    if args.install_desktop:
        install_desktop_integration()
        return 0

    try:
        instance_guard = MiniEqInstanceGuard.acquire()
    except MiniEqAlreadyRunningError as exc:
        if getattr(args, "background", False):
            return 0

        try:
            call_present_window()
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

        app = MiniEqApplication(args)
        return app.run([sys.argv[0]])


def main(argv: list[str]) -> int:
    return run_from_args(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
