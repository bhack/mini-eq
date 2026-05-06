from __future__ import annotations

import os
import shutil
import sys
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Final

from gi.repository import Gio, GLib

from .desktop_integration import APP_DISPLAY_NAME, APP_ICON_NAME, APP_ID, quote_desktop_exec_arg
from .settings import load_settings, update_setting

BACKGROUND_MODE_KEY: Final = "background_mode"
START_AT_LOGIN_KEY: Final = "start_at_login"
START_ACTIVE_AT_LOGIN_KEY: Final = "start_active_at_login"
BACKGROUND_PORTAL_REASON: Final = "Keep equalizer settings active for desktop audio."
BACKGROUND_PORTAL_BUS_NAME: Final = "org.freedesktop.portal.Desktop"
BACKGROUND_PORTAL_OBJECT_PATH: Final = "/org/freedesktop/portal/desktop"
BACKGROUND_PORTAL_IFACE: Final = "org.freedesktop.portal.Background"
PORTAL_REQUEST_IFACE: Final = "org.freedesktop.portal.Request"
PORTAL_CALL_TIMEOUT_MS: Final = 120_000
PORTAL_RESPONSE_SUCCESS: Final = 0
AUTOSTART_FILE_NAME: Final = f"{APP_ID}.desktop"

PortalCallback = Callable[[bool, bool, Exception | None], None]


class BackgroundPortalError(RuntimeError):
    pass


def normalize_bool(value: object) -> bool:
    return value is True


def load_background_mode() -> bool:
    return normalize_bool(load_settings().get(BACKGROUND_MODE_KEY))


def save_background_mode(enabled: bool) -> None:
    update_setting(BACKGROUND_MODE_KEY, bool(enabled))


def load_start_at_login() -> bool:
    return normalize_bool(load_settings().get(START_AT_LOGIN_KEY))


def save_start_at_login(enabled: bool) -> None:
    update_setting(START_AT_LOGIN_KEY, bool(enabled))


def load_start_active_at_login() -> bool:
    return normalize_bool(load_settings().get(START_ACTIVE_AT_LOGIN_KEY))


def save_start_active_at_login(enabled: bool) -> None:
    update_setting(START_ACTIVE_AT_LOGIN_KEY, bool(enabled))


def running_in_flatpak() -> bool:
    return Path("/.flatpak-info").exists()


def autostart_dir() -> Path:
    return Path(GLib.get_user_config_dir()) / "autostart"


def autostart_desktop_path() -> Path:
    return autostart_dir() / AUTOSTART_FILE_NAME


def resolve_mini_eq_executable(argv0: str | None = None) -> str:
    executable = shutil.which("mini-eq")
    if executable:
        return executable

    candidate = argv0 or sys.argv[0]
    if candidate:
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
        path = Path(candidate).expanduser()
        if path.is_absolute() and path.is_file() and os.access(path, os.X_OK):
            return str(path)

    raise FileNotFoundError("Could not resolve the mini-eq executable")


def mini_eq_background_command(executable: str, *, auto_route: bool = False) -> list[str]:
    command = [executable, "--background"]
    if auto_route:
        command.append("--auto-route")
    return command


def native_autostart_command(executable: str | None = None, *, auto_route: bool = False) -> list[str]:
    return mini_eq_background_command(executable or resolve_mini_eq_executable(), auto_route=auto_route)


def build_native_autostart_desktop_file(command: list[str] | None = None, *, auto_route: bool = False) -> str:
    exec_line = " ".join(
        quote_desktop_exec_arg(part) for part in (command or native_autostart_command(auto_route=auto_route))
    )
    return "\n".join(
        [
            "[Desktop Entry]",
            "Type=Application",
            f"Name={APP_DISPLAY_NAME}",
            "GenericName=System-wide Equalizer",
            "Comment=Keep Mini EQ available in the background",
            f"Exec={exec_line}",
            f"Icon={APP_ICON_NAME}",
            "Terminal=false",
            "NoDisplay=true",
            f"X-GNOME-Autostart-enabled={'true'}",
            "",
        ],
    )


def set_native_start_at_login(enabled: bool, executable: str | None = None, *, auto_route: bool = False) -> None:
    path = autostart_desktop_path()
    if not enabled:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        build_native_autostart_desktop_file(native_autostart_command(executable, auto_route=auto_route)),
        encoding="utf-8",
    )
    path.chmod(0o644)


def set_background_status(message: str) -> None:
    if not running_in_flatpak():
        return

    connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    options = {"message": GLib.Variant("s", message)}
    connection.call(
        BACKGROUND_PORTAL_BUS_NAME,
        BACKGROUND_PORTAL_OBJECT_PATH,
        BACKGROUND_PORTAL_IFACE,
        "SetStatus",
        GLib.Variant("(a{sv})", (options,)),
        None,
        Gio.DBusCallFlags.NONE,
        PORTAL_CALL_TIMEOUT_MS,
        None,
        None,
    )


class BackgroundPortalRequest:
    def __init__(self, autostart: bool, callback: PortalCallback, *, auto_route: bool = False) -> None:
        self.autostart = autostart
        self.callback = callback
        self.auto_route = auto_route
        self.connection: Gio.DBusConnection | None = None
        self.handle_path = ""
        self.response_subscription_id = 0
        self.timeout_source_id = 0
        self.finished = False

    def start(self) -> None:
        try:
            self.connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        except GLib.Error as exc:
            self.finish(False, False, exc)
            return

        handle_token = f"mini_eq_{uuid.uuid4().hex}"
        sender_id = self.connection.get_unique_name().lstrip(":").replace(".", "_")
        self.handle_path = f"/org/freedesktop/portal/desktop/request/{sender_id}/{handle_token}"
        self.response_subscription_id = self.connection.signal_subscribe(
            BACKGROUND_PORTAL_BUS_NAME,
            PORTAL_REQUEST_IFACE,
            "Response",
            self.handle_path,
            None,
            Gio.DBusSignalFlags.NONE,
            self.on_response,
        )

        options: dict[str, GLib.Variant] = {
            "reason": GLib.Variant("s", BACKGROUND_PORTAL_REASON),
            "autostart": GLib.Variant("b", self.autostart),
            "handle_token": GLib.Variant("s", handle_token),
        }
        if self.autostart:
            options["commandline"] = GLib.Variant(
                "as",
                mini_eq_background_command("mini-eq", auto_route=self.auto_route),
            )

        self.timeout_source_id = GLib.timeout_add(PORTAL_CALL_TIMEOUT_MS, self.on_timeout)
        self.connection.call(
            BACKGROUND_PORTAL_BUS_NAME,
            BACKGROUND_PORTAL_OBJECT_PATH,
            BACKGROUND_PORTAL_IFACE,
            "RequestBackground",
            GLib.Variant("(sa{sv})", ("", options)),
            GLib.VariantType.new("(o)"),
            Gio.DBusCallFlags.NONE,
            PORTAL_CALL_TIMEOUT_MS,
            None,
            self.on_request_background_done,
        )

    def on_request_background_done(self, connection: Gio.DBusConnection, result: Gio.AsyncResult) -> None:
        if self.finished:
            return

        try:
            reply = connection.call_finish(result)
            (handle_path,) = reply.unpack()
        except GLib.Error as exc:
            self.finish(False, False, exc)
            return

        if handle_path != self.handle_path:
            self.finish(False, False, BackgroundPortalError("Background portal returned an unexpected request handle"))

    def on_response(
        self,
        _connection: Gio.DBusConnection,
        _sender: str,
        _object_path: str,
        _interface_name: str,
        _signal_name: str,
        parameters: GLib.Variant,
    ) -> None:
        if self.finished:
            return

        response, results = parameters.unpack()
        background_allowed = bool(results.get("background", False))
        autostart_enabled = bool(results.get("autostart", False))
        if response != PORTAL_RESPONSE_SUCCESS or not background_allowed:
            self.finish(False, autostart_enabled, BackgroundPortalError("Background permission was not granted"))
            return

        self.finish(True, autostart_enabled, None)

    def on_timeout(self) -> bool:
        self.timeout_source_id = 0
        self.finish(False, False, BackgroundPortalError("Background portal did not respond"))
        return False

    def finish(self, background_allowed: bool, autostart_enabled: bool, error: Exception | None) -> None:
        if self.finished:
            return

        self.finished = True
        if self.timeout_source_id > 0:
            GLib.source_remove(self.timeout_source_id)
            self.timeout_source_id = 0
        if self.connection is not None and self.response_subscription_id > 0:
            self.connection.signal_unsubscribe(self.response_subscription_id)
            self.response_subscription_id = 0

        self.callback(background_allowed, autostart_enabled, error)


def request_background_portal(
    autostart: bool,
    callback: PortalCallback,
    *,
    auto_route: bool = False,
) -> BackgroundPortalRequest:
    request = BackgroundPortalRequest(autostart, callback, auto_route=auto_route)
    request.start()
    return request


def request_background_permission(enabled: bool, callback: PortalCallback) -> BackgroundPortalRequest | None:
    if not enabled or not running_in_flatpak():
        callback(True, False, None)
        return None

    return request_background_portal(False, callback)


def request_start_at_login(
    enabled: bool,
    callback: PortalCallback,
    *,
    executable: str | None = None,
    auto_route: bool = False,
) -> BackgroundPortalRequest | None:
    if running_in_flatpak():
        return request_background_portal(enabled, callback, auto_route=auto_route)

    try:
        set_native_start_at_login(enabled, executable=executable, auto_route=auto_route)
    except Exception as exc:
        callback(False, False, exc)
        return None

    callback(True, enabled, None)
    return None
