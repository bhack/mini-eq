#!/usr/bin/env python3
"""Check preset rebuilds against WirePlumber's real MPRIS pause policy."""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

try:
    from tools import check_headless_pipewire_runtime as head
    from tools import check_live_ui_runtime as live
except ModuleNotFoundError:  # direct script execution
    import check_headless_pipewire_runtime as head
    import check_live_ui_runtime as live

MPRIS_XML = """<node>
  <interface name="org.mpris.MediaPlayer2">
    <property name="Identity" type="s" access="read"/>
    <property name="DesktopEntry" type="s" access="read"/>
    <property name="CanQuit" type="b" access="read"/>
    <property name="CanRaise" type="b" access="read"/>
    <property name="HasTrackList" type="b" access="read"/>
    <property name="SupportedUriSchemes" type="as" access="read"/>
    <property name="SupportedMimeTypes" type="as" access="read"/>
  </interface>
  <interface name="org.mpris.MediaPlayer2.Player">
    <method name="Pause"/>
    <property name="PlaybackStatus" type="s" access="read"/>
    <property name="CanPause" type="b" access="read"/>
    <property name="CanControl" type="b" access="read"/>
    <property name="PauseCount" type="u" access="read"/>
  </interface>
</node>"""


class MprisPlayer:
    def __init__(self) -> None:
        from gi.repository import Gio

        self.pause_calls = 0
        self.bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        self.registrations = [
            self.bus.register_object("/org/mpris/MediaPlayer2", interface, self.method, self.property, None)
            for interface in Gio.DBusNodeInfo.new_for_xml(MPRIS_XML).interfaces
        ]
        self.owner = Gio.bus_own_name_on_connection(
            self.bus, "org.mpris.MediaPlayer2.minieqtest", Gio.BusNameOwnerFlags.NONE, None, None
        )

    def method(self, _connection, _sender, _path, _interface, name, _parameters, invocation):
        from gi.repository import GLib

        if name == "Pause":
            self.pause_calls += 1
        invocation.return_value(GLib.Variant("()", ()))

    def property(self, _connection, _sender, _path, _interface, name):
        from gi.repository import GLib

        if name in ("Identity", "DesktopEntry"):
            return GLib.Variant("s", "mini-eq-mpris-test")
        if name == "PlaybackStatus":
            return GLib.Variant("s", "Playing")
        if name == "PauseCount":
            return GLib.Variant("u", self.pause_calls)
        if name in ("SupportedUriSchemes", "SupportedMimeTypes"):
            return GLib.Variant("as", [])
        return GLib.Variant("b", name in ("CanPause", "CanControl"))

    def close(self) -> None:
        from gi.repository import Gio

        Gio.bus_unown_name(self.owner)
        for registration in self.registrations:
            self.bus.unregister_object(registration)


class PlayerProbe:
    """Query a player in a separate process, never Mini EQ's own PID tree."""

    def __init__(self):
        from gi.repository import Gio

        self.bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)

    @property
    def pause_calls(self) -> int:
        from gi.repository import Gio, GLib

        return self.bus.call_sync(
            "org.mpris.MediaPlayer2.minieqtest",
            "/org/mpris/MediaPlayer2",
            "org.freedesktop.DBus.Properties",
            "Get",
            GLib.Variant("(ss)", ("org.mpris.MediaPlayer2.Player", "PauseCount")),
            GLib.VariantType.new("(v)"),
            Gio.DBusCallFlags.NONE,
            1000,
            None,
        ).unpack()[0]


def run_player_helper(audio: str) -> int:
    from gi.repository import GLib

    player = MprisPlayer()
    playback = subprocess.Popen(["paplay", "--client-name=mini-eq-mpris-test", audio])
    loop = GLib.MainLoop()
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, lambda: loop.quit() or False)
    try:
        loop.run()
    finally:
        live.terminate_process(playback, "Pulse playback")
        player.close()
    return 0


def observe(seconds: float) -> None:
    from gi.repository import GLib

    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        head.drain_main_context(GLib.MainContext.default())
        time.sleep(0.02)


def run_helper() -> int:
    for tool in ("pipewire", "pipewire-pulse", "wireplumber", "paplay", "pw-dump", "wpctl", "pw-metadata"):
        live.require_tool(tool)
    head.ensure_source_path()
    from mini_eq.core import FILTER_TYPES, inactive_eq_bands
    from mini_eq.routing import SystemWideEqController

    pw = wp = pulse = playback = controller = player = None
    with tempfile.TemporaryDirectory(prefix="mini-eq-mpris-runtime-") as directory:
        root = Path(directory)
        for name in ("runtime", "config", "data", "cache"):
            (root / name).mkdir(mode=0o700)
        for key, name in (
            ("XDG_RUNTIME_DIR", "runtime"),
            ("XDG_CONFIG_HOME", "config"),
            ("XDG_DATA_HOME", "data"),
            ("XDG_CACHE_HOME", "cache"),
        ):
            os.environ[key] = str(root / name)
        os.environ["PULSE_SERVER"] = "unix:" + str(root / "runtime/pulse/native")
        live.write_pipewire_config(root / "config")
        # The private graph must not enumerate or compete with host devices.
        wp_config = root / "config/wireplumber/wireplumber.conf.d"
        wp_config.mkdir(parents=True)
        (wp_config / "10-private-audio.conf").write_text(
            "wireplumber.profiles = { main = { "
            "monitor.alsa = disabled monitor.bluez = disabled "
            "monitor.v4l2 = disabled monitor.libcamera = disabled } }\n",
            encoding="utf-8",
        )
        with (root / "pulse.log").open("w") as pulse_log, (root / "player.log").open("w") as player_log:
            try:
                pw, wp = head.start_pipewire_session(root, 15)
                pulse = subprocess.Popen(["pipewire-pulse"], stdout=pulse_log, stderr=subprocess.STDOUT)
                live.wait_for("private Pulse socket", lambda: (root / "runtime/pulse/native").exists(), 15)
                subprocess.run(["wpctl", "settings", "linking.pause-playback", "true"], check=True)
                audio = live.create_sine_wav(root / "signal.wav", 90)
                playback = subprocess.Popen(
                    [sys.executable, str(Path(__file__).resolve()), "--player-helper", str(audio)],
                    stdout=player_log,
                    stderr=subprocess.STDOUT,
                )
                player = PlayerProbe()
                head.dispatch_until("MPRIS player ready", lambda: player.pause_calls == 0, 15)
                node = live.wait_for(
                    "Pulse player node",
                    lambda: next(
                        (
                            n
                            for n in live.node_items()
                            if n.get("info", {}).get("props", {}).get("application.name") == "mini-eq-mpris-test"
                        ),
                        None,
                    ),
                    15,
                )
                stream_id = live.node_id(node)
                controller = SystemWideEqController(live.PRIMARY_SINK_NAME)
                controller.bands = inactive_eq_bands()
                head.wait_for_controller_ready(controller, 15)
                head.wait_for_smoke_routed(stream_id, controller.virtual_sink_name, 15)
                observe(2)
                serial = live.object_serial(live.node_by_name(controller.virtual_sink_name))
                for name in ("Bell", "Lo-pass", "Off"):
                    controller.set_band_type(0, FILTER_TYPES[name])
                    head.dispatch_until("DSP replacement ready", lambda: controller.running, 15)
                    head.wait_for_processing_path_active(
                        controller.virtual_sink_name, controller.filter_output_name, 15
                    )
                    observe(2)
                    if live.object_serial(live.node_by_name(controller.virtual_sink_name)) != serial:
                        raise RuntimeError("Preset change replaced the player-facing device")
                    if player.pause_calls:
                        raise RuntimeError(f"WirePlumber paused the player after {name}")
                    if playback.poll() is not None:
                        raise RuntimeError("Pulse playback disconnected")
                print("Preset/type replacements: stable sink, active audio path, zero MPRIS Pause calls", flush=True)
                controller.shutdown()
                controller = None
                observe(2)
                if player.pause_calls:
                    raise RuntimeError("WirePlumber paused the player on normal shutdown")
                print("Normal shutdown: zero MPRIS Pause calls", flush=True)
                # A positive control prevents a broken/unmatched MPRIS fixture
                # from making the zero-pause assertions pass vacuously.
                controller = SystemWideEqController(live.PRIMARY_SINK_NAME)
                head.wait_for_controller_ready(controller, 15)
                head.wait_for_smoke_routed(stream_id, controller.virtual_sink_name, 15)
                observe(2)
                controller.stream_router.stop_monitoring()
                controller.output_backend.unload_filter_chain_module(controller.input_module)
                controller.input_module = None
                head.dispatch_until("device-removal MPRIS positive control", lambda: player.pause_calls > 0, 15)
                print("Positive control: device removal invokes MPRIS Pause", flush=True)
            finally:
                try:
                    if controller is not None:
                        controller.shutdown()
                finally:
                    for process, label in (
                        (playback, "Pulse player"),
                        (pulse, "Pulse server"),
                        (wp, "WirePlumber"),
                        (pw, "PipeWire"),
                    ):
                        live.terminate_process(process, label)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--helper", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--player-helper", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.player_helper:
        return run_player_helper(args.player_helper)
    if args.helper:
        return run_helper()
    return subprocess.run(
        ["dbus-run-session", "--", sys.executable, str(Path(__file__).resolve()), "--helper"]
    ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
