#!/usr/bin/env python3
from __future__ import annotations

import math
import signal
import warnings

import gi

gi.require_version("Gio", "2.0")
gi.require_version("GLib", "2.0")

from gi.repository import Gio, GLib

warnings.filterwarnings("ignore", category=DeprecationWarning)

BUS_NAME = "io.github.bhack.mini-eq"
OBJECT_PATH = "/io/github/bhack/mini_eq/Control"
INTERFACE_NAME = "io.github.bhack.MiniEq.Control"

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
    <signal name="StateChanged">
      <arg name="state" type="a{{sv}}"/>
    </signal>
    <signal name="PresetsChanged"/>
  </interface>
</node>
"""


class FakeMiniEqControl:
    def __init__(self) -> None:
        self.eq_enabled = True
        self.routed = True
        self.preset_name = "HIFIMAN Ananda Nano"
        self.presets = ["HIFIMAN Ananda Nano", "Flat", "Late Night"]
        self.analyzer_levels = [0.0] * 10
        self.animation_step = 0
        self.loop = GLib.MainLoop()
        self.connection: Gio.DBusConnection | None = None
        self.registration_id = 0
        self.owner_id = 0
        self.animation_source_id = 0
        self.interface_info = Gio.DBusNodeInfo.new_for_xml(INTROSPECTION_XML).interfaces[0]

    def state(self) -> dict[str, GLib.Variant]:
        return {
            "running": GLib.Variant("b", True),
            "eq_enabled": GLib.Variant("b", self.eq_enabled),
            "routed": GLib.Variant("b", self.routed),
            "preset_name": GLib.Variant("s", self.preset_name),
            "output_sink": GLib.Variant("s", "devkit-output"),
            "analyzer_levels": GLib.Variant(
                "ad", self.analyzer_levels if self.eq_enabled and self.routed else [0.0] * 10
            ),
        }

    def emit_state_changed(self) -> None:
        if self.connection is None:
            return

        self.connection.emit_signal(
            None,
            OBJECT_PATH,
            INTERFACE_NAME,
            "StateChanged",
            GLib.Variant("(a{sv})", (self.state(),)),
        )

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
        if method_name == "GetState":
            invocation.return_value(GLib.Variant("(a{sv})", (self.state(),)))
        elif method_name == "ListPresets":
            invocation.return_value(GLib.Variant("(as)", (self.presets,)))
        elif method_name == "SetEqEnabled":
            (enabled,) = parameters.unpack()
            self.eq_enabled = enabled
            invocation.return_value(None)
            self.emit_state_changed()
        elif method_name == "SetRoutingEnabled":
            (enabled,) = parameters.unpack()
            self.routed = enabled
            self.eq_enabled = True
            invocation.return_value(None)
            self.emit_state_changed()
        elif method_name == "SetPreset":
            (preset_name,) = parameters.unpack()
            if preset_name in self.presets:
                self.preset_name = preset_name
            invocation.return_value(None)
            self.emit_state_changed()
        elif method_name == "PresentWindow":
            invocation.return_value(None)
        else:
            invocation.return_dbus_error(f"{INTERFACE_NAME}.UnknownMethod", method_name)

    def update_analyzer_levels(self) -> bool:
        self.animation_step += 1
        phase = self.animation_step / 3.5
        self.analyzer_levels = [
            max(0.04, min(1.0, 0.18 + (0.72 * ((math.sin(phase + (index * 0.72)) + 1.0) / 2.0)))) for index in range(10)
        ]
        self.emit_state_changed()
        return True

    def on_bus_acquired(self, connection: Gio.DBusConnection, _name: str) -> None:
        self.connection = connection
        self.registration_id = connection.register_object(
            OBJECT_PATH,
            self.interface_info,
            self.on_method_call,
            None,
            None,
        )
        self.animation_source_id = GLib.timeout_add(100, self.update_analyzer_levels)
        print(f"Fake Mini EQ D-Bus control ready on {BUS_NAME}", flush=True)

    def stop(self, *_args: object) -> None:
        self.loop.quit()

    def run(self) -> None:
        self.owner_id = Gio.bus_own_name(
            Gio.BusType.SESSION,
            BUS_NAME,
            Gio.BusNameOwnerFlags.NONE,
            self.on_bus_acquired,
            None,
            None,
        )
        signal.signal(signal.SIGTERM, self.stop)
        signal.signal(signal.SIGINT, self.stop)
        try:
            self.loop.run()
        finally:
            if self.animation_source_id:
                GLib.source_remove(self.animation_source_id)
                self.animation_source_id = 0
            if self.connection is not None and self.registration_id:
                self.connection.unregister_object(self.registration_id)
            if self.owner_id:
                Gio.bus_unown_name(self.owner_id)


if __name__ == "__main__":
    FakeMiniEqControl().run()
