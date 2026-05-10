from __future__ import annotations

from typing import Protocol

from gi.repository import Gio, GLib

from . import __version__
from .analyzer import analyzer_level_to_display_norm
from .core import list_preset_names, sanitize_preset_name

BUS_NAME = "io.github.bhack.mini-eq"
OBJECT_PATH = "/io/github/bhack/mini_eq/Control"
INTERFACE_NAME = "io.github.bhack.MiniEq.Control"
PANEL_ANALYZER_BINS = 10
API_VERSION = 1
CAPABILITIES = (
    "present-window",
    "quit",
    "background-mode",
    "start-at-login",
    "start-active-at-login",
    "set-routing",
    "set-preset",
    "output-presets",
    "analyzer-levels",
)

INTROSPECTION_XML = f"""
<node>
  <interface name="{INTERFACE_NAME}">
    <method name="GetState">
      <arg name="state" type="a{{sv}}" direction="out"/>
    </method>
    <method name="ListPresets">
      <arg name="presets" type="as" direction="out"/>
    </method>
    <method name="SetEqEnabled">
      <arg name="enabled" type="b" direction="in"/>
    </method>
    <method name="SetRoutingEnabled">
      <arg name="enabled" type="b" direction="in"/>
    </method>
    <method name="SetPreset">
      <arg name="name" type="s" direction="in"/>
    </method>
    <method name="PresentWindow"/>
    <method name="Quit"/>
    <signal name="StateChanged">
      <arg name="state" type="a{{sv}}"/>
    </signal>
    <signal name="AnalyzerLevelsChanged">
      <arg name="levels" type="ad"/>
    </signal>
    <signal name="PresetsChanged"/>
  </interface>
</node>
"""


class ControllerProtocol(Protocol):
    eq_enabled: bool
    routed: bool
    output_sink: str | None

    def set_eq_enabled(self, enabled: bool) -> None: ...

    def route_system_audio(self, enabled: bool) -> None: ...


class WindowProtocol(Protocol):
    current_preset_name: str | None
    ui_shutting_down: bool
    analyzer_enabled: bool
    analyzer_levels: list[float]
    analyzer_display_gain_db: float
    controller: ControllerProtocol

    def load_library_preset(self, name: str) -> None: ...

    def present(self) -> None: ...

    def get_visible(self) -> bool: ...

    def sync_control_switches_from_controller(self, *, route: bool = True, eq: bool = True) -> None: ...

    def refresh_after_route_state_changed(
        self,
        *,
        eq_was_enabled: bool,
        announce_enabled: bool | None = None,
        notify: bool = True,
    ) -> None: ...

    def refresh_after_eq_state_changed(
        self,
        *,
        announce_enabled: bool | None = None,
        notify: bool = True,
    ) -> None: ...

    def output_preset_link_name(self) -> str | None: ...


class ApplicationProtocol(Protocol):
    controller: ControllerProtocol | None
    window: WindowProtocol | None
    background_mode: bool
    start_at_login: bool
    start_active_at_login: bool

    def activate(self) -> None: ...

    def present_main_window(self) -> None: ...

    def quit_fully(self) -> None: ...

    def get_dbus_connection(self) -> Gio.DBusConnection | None: ...


class MiniEqDbusControl:
    def __init__(self, app: ApplicationProtocol) -> None:
        self.app = app
        self.connection: Gio.DBusConnection | None = None
        self.registration_id = 0
        self.interface_info = Gio.DBusNodeInfo.new_for_xml(INTROSPECTION_XML).interfaces[0]

    def register(self) -> None:
        if self.registration_id:
            return

        connection = self.app.get_dbus_connection() or Gio.bus_get_sync(Gio.BusType.SESSION, None)
        self.registration_id = connection.register_object(
            OBJECT_PATH,
            self.interface_info,
            self.on_method_call,
            None,
            None,
        )
        self.connection = connection

    def unregister(self) -> None:
        if self.connection is not None and self.registration_id:
            self.connection.unregister_object(self.registration_id)

        self.registration_id = 0
        self.connection = None

    def state(self) -> dict[str, GLib.Variant]:
        controller = self.app.controller
        window = self.app.window
        output_preset_name = ""
        if window is not None:
            output_preset_link_name = getattr(window, "output_preset_link_name", None)
            if output_preset_link_name is not None:
                output_preset_name = output_preset_link_name() or ""

        return {
            "api_version": GLib.Variant("u", API_VERSION),
            "app_version": GLib.Variant("s", __version__),
            "capabilities": GLib.Variant("as", CAPABILITIES),
            "running": GLib.Variant("b", controller is not None),
            "eq_enabled": GLib.Variant("b", bool(controller and controller.eq_enabled)),
            "routed": GLib.Variant("b", bool(controller and controller.routed)),
            "preset_name": GLib.Variant(
                "s", window.current_preset_name if window and window.current_preset_name else ""
            ),
            "output_sink": GLib.Variant("s", controller.output_sink if controller and controller.output_sink else ""),
            "output_preset_name": GLib.Variant("s", output_preset_name),
            "output_preset_auto_applied": GLib.Variant(
                "b",
                bool(window and getattr(window, "output_preset_auto_applied", False)),
            ),
            "analyzer_enabled": GLib.Variant("b", bool(window and getattr(window, "analyzer_enabled", False))),
            "background_mode": GLib.Variant("b", bool(getattr(self.app, "background_mode", False))),
            "start_at_login": GLib.Variant("b", bool(getattr(self.app, "start_at_login", False))),
            "start_active_at_login": GLib.Variant(
                "b",
                bool(getattr(self.app, "start_active_at_login", False)),
            ),
            "window_visible": GLib.Variant(
                "b",
                bool(
                    window
                    and not getattr(window, "ui_shutting_down", False)
                    and getattr(window, "get_visible", lambda: False)()
                ),
            ),
        }

    def list_presets(self) -> list[str]:
        return list_preset_names()

    def analyzer_levels(self) -> list[float]:
        return panel_analyzer_levels(self.app.window)

    def _connection_is_closed(self, connection: Gio.DBusConnection) -> bool:
        is_closed = getattr(connection, "is_closed", None)
        if is_closed is None:
            return False

        return bool(is_closed())

    def _drop_closed_connection(self, connection: Gio.DBusConnection) -> None:
        if self.connection is connection:
            self.registration_id = 0
            self.connection = None

    def _is_closed_connection_error(self, exc: GLib.GError) -> bool:
        return bool(exc.matches(Gio.io_error_quark(), Gio.IOErrorEnum.CLOSED))

    def _emit_signal(self, signal_name: str, parameters: GLib.Variant | None) -> None:
        connection = self.connection
        if connection is None:
            return
        if self._connection_is_closed(connection):
            self._drop_closed_connection(connection)
            return

        try:
            connection.emit_signal(
                None,
                OBJECT_PATH,
                INTERFACE_NAME,
                signal_name,
                parameters,
            )
        except GLib.GError as exc:
            if self._is_closed_connection_error(exc) or self._connection_is_closed(connection):
                self._drop_closed_connection(connection)
                return
            raise

    def emit_state_changed(self) -> None:
        self._emit_signal(
            "StateChanged",
            GLib.Variant("(a{sv})", (self.state(),)),
        )

    def emit_analyzer_levels_changed(self) -> None:
        self._emit_signal(
            "AnalyzerLevelsChanged",
            GLib.Variant("(ad)", (self.analyzer_levels(),)),
        )

    def emit_presets_changed(self) -> None:
        self._emit_signal(
            "PresetsChanged",
            None,
        )

    def set_eq_enabled(self, enabled: bool) -> None:
        if self.app.controller is None:
            self.app.activate()

        controller = self.app.controller
        window = self.app.window
        if controller is None:
            raise ValueError("Mini EQ is not running")

        controller.set_eq_enabled(enabled)
        if window is not None and not window.ui_shutting_down:
            window.refresh_after_eq_state_changed(notify=False)

        self.emit_state_changed()

    def set_routing_enabled(self, enabled: bool) -> None:
        if self.app.controller is None:
            self.app.activate()

        controller = self.app.controller
        window = self.app.window
        if controller is None:
            raise ValueError("Mini EQ is not running")

        eq_was_enabled = controller.eq_enabled
        try:
            controller.route_system_audio(enabled)
        except Exception:
            if window is not None and not window.ui_shutting_down:
                window.sync_control_switches_from_controller()
            raise

        if window is not None and not window.ui_shutting_down:
            window.refresh_after_route_state_changed(eq_was_enabled=eq_was_enabled, notify=False)

        self.emit_state_changed()

    def set_preset(self, name: str) -> None:
        preset_name = sanitize_preset_name(name)
        if not preset_name:
            raise ValueError("preset name is empty")

        if self.app.window is None:
            self.app.activate()

        window = self.app.window
        if window is None or window.ui_shutting_down:
            raise ValueError("Mini EQ window is not available")

        window.load_library_preset(preset_name)
        self.emit_state_changed()

    def present_window(self) -> None:
        present_main_window = getattr(self.app, "present_main_window", None)
        if present_main_window is not None:
            present_main_window()
            return

        self.app.activate()
        window = self.app.window
        if window is not None and not window.ui_shutting_down:
            window.present()

    def quit(self) -> None:
        quit_fully = getattr(self.app, "quit_fully", None)
        if quit_fully is not None:
            quit_fully()
            return

        window = self.app.window
        if window is not None and not window.ui_shutting_down:
            window.close()
            return

        self.app.quit()

    def on_method_call(
        self,
        _connection: Gio.DBusConnection,
        _sender: str,
        _object_path: str,
        _interface_name: str,
        method_name: str,
        parameters: GLib.Variant,
        invocation: Gio.DBusMethodInvocation,
    ) -> None:
        try:
            if method_name == "GetState":
                invocation.return_value(GLib.Variant("(a{sv})", (self.state(),)))
            elif method_name == "ListPresets":
                invocation.return_value(GLib.Variant("(as)", (self.list_presets(),)))
            elif method_name == "SetEqEnabled":
                (enabled,) = parameters.unpack()
                self.set_eq_enabled(enabled)
                invocation.return_value(None)
            elif method_name == "SetRoutingEnabled":
                (enabled,) = parameters.unpack()
                self.set_routing_enabled(enabled)
                invocation.return_value(None)
            elif method_name == "SetPreset":
                (preset_name,) = parameters.unpack()
                self.set_preset(preset_name)
                invocation.return_value(None)
            elif method_name == "PresentWindow":
                self.present_window()
                invocation.return_value(None)
            elif method_name == "Quit":
                invocation.return_value(None)
                self.quit()
            else:
                invocation.return_dbus_error(f"{INTERFACE_NAME}.UnknownMethod", f"Unknown method: {method_name}")
        except Exception as exc:
            invocation.return_dbus_error(f"{INTERFACE_NAME}.Error", str(exc))


def call_present_window(timeout_ms: int = 3000) -> None:
    connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    connection.call_sync(
        BUS_NAME,
        OBJECT_PATH,
        INTERFACE_NAME,
        "PresentWindow",
        None,
        None,
        Gio.DBusCallFlags.NONE,
        timeout_ms,
        None,
    )


def panel_analyzer_levels(window: WindowProtocol | None, target_count: int = PANEL_ANALYZER_BINS) -> list[float]:
    if target_count <= 0:
        return []

    if window is None or not window.analyzer_enabled:
        return [0.0] * target_count

    display_gain_db = float(getattr(window, "analyzer_display_gain_db", 0.0))
    source_levels = [clamp_level(level) for level in window.analyzer_levels]
    if not source_levels:
        return [0.0] * target_count

    compacted: list[float] = []
    source_count = len(source_levels)
    for index in range(target_count):
        start = int(index * source_count / target_count)
        end = int((index + 1) * source_count / target_count)
        if end <= start:
            end = min(source_count, start + 1)
        compacted.append(analyzer_level_to_display_norm(max(source_levels[start:end]), display_gain_db))

    return compacted


def clamp_level(level: float) -> float:
    return max(0.0, min(1.0, float(level)))
