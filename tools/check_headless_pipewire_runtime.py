#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

try:
    from tools import check_live_ui_runtime as live
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    import check_live_ui_runtime as live

HELPER_SKIP_EXIT_CODE = live.HELPER_SKIP_EXIT_CODE
REPO_ROOT = Path(__file__).resolve().parents[1]


def format_command(command: list[str | Path]) -> str:
    return " ".join(str(part) for part in command)


def require_tool(name: str) -> str:
    return live.require_tool(name)


def ensure_source_path() -> None:
    src_path = str(REPO_ROOT / "src")
    if src_path not in sys.path:
        sys.path.insert(0, src_path)


def dispatch_until(
    label: str,
    predicate: Callable[[], Any],
    timeout_seconds: float,
    interval_seconds: float = 0.05,
) -> Any:
    from gi.repository import GLib

    context = GLib.MainContext.default()
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None

    while time.monotonic() < deadline:
        while context.pending():
            context.iteration(False)

        try:
            value = predicate()
        except Exception as exc:
            last_error = exc
        else:
            if value is not None and value is not False:
                return value

        time.sleep(interval_seconds)

    while context.pending():
        context.iteration(False)

    detail = f": {last_error}" if last_error is not None else ""
    raise RuntimeError(f"timed out waiting for {label}{detail}")


def route_to_current_virtual(
    smoke_id: int,
    virtual_sink_name: str,
) -> str | None:
    virtual_sink = live.node_by_name(virtual_sink_name)
    if virtual_sink is None:
        return None

    serial = live.object_serial(virtual_sink)
    if live.metadata_targets().get(smoke_id) == (serial, "Spa:Id"):
        return serial
    return None


def node_targets_serial(node_name: str, target_serial: str) -> bool:
    node = live.node_by_name(node_name)
    return node is not None and live.metadata_targets().get(live.node_id(node)) == (target_serial, "Spa:Id")


def processing_path_has_active_links(virtual_sink_name: str, filter_output_name: str) -> bool:
    virtual_sink = live.node_by_name(virtual_sink_name)
    filter_output = live.node_by_name(filter_output_name)
    if virtual_sink is None or filter_output is None:
        return False

    required_ids = {live.node_id(virtual_sink): False, live.node_id(filter_output): False}
    for link in live.link_items():
        if live.link_state(link) != "active":
            continue
        endpoints = live.link_endpoint_ids(link)
        for required_id in tuple(required_ids):
            if required_id in endpoints:
                required_ids[required_id] = True

    return all(required_ids.values())


def wait_for_processing_path_active(
    virtual_sink_name: str,
    filter_output_name: str,
    timeout_seconds: float,
) -> None:
    dispatch_until(
        "Mini EQ processing path links to become active",
        lambda: processing_path_has_active_links(virtual_sink_name, filter_output_name),
        timeout_seconds,
    )


def bad_monitor_source_nodes() -> list[dict[str, Any]]:
    return [
        live.item_props(node)
        for node in live.node_items()
        if live.item_props(node).get("application.name") == "Mini EQ"
        and live.item_props(node).get("media.class") == "Audio/Source"
    ]


def wait_for_controller_ready(controller, timeout_seconds: float) -> None:
    state = {"ready": False, "error": None}

    def on_ready() -> None:
        try:
            controller.route_system_audio(True)
            state["ready"] = True
        except Exception as exc:
            state["error"] = exc

    def on_error(exc: Exception) -> None:
        state["error"] = exc

    controller.start(on_ready=on_ready, on_error=on_error)

    def ready() -> bool:
        if state["error"] is not None:
            raise RuntimeError(f"Mini EQ controller failed: {state['error']}")
        return bool(state["ready"])

    dispatch_until("Mini EQ controller ready and routed", ready, timeout_seconds)


def run_controller_flow(*, tmp_dir: Path, timeout_seconds: float, cycles: int, audio_duration: float) -> None:
    ensure_source_path()

    from mini_eq.routing import SystemWideEqController

    live.set_configured_default_sink_name(live.PRIMARY_SINK_NAME, timeout_seconds)
    live.verify_pipewire_gobject_probe(timeout_seconds)

    audio_file = live.create_sine_wav(tmp_dir / "mini-eq-headless-pipewire-smoke.wav", audio_duration)
    smoke = live.start_smoke_stream(audio_file)
    controller = None
    statuses: list[str] = []

    try:
        smoke_node = dispatch_until(
            "synthetic PipeWire playback stream",
            lambda: live.smoke_stream_node() if smoke.poll() is None else None,
            timeout_seconds,
        )
        smoke_id = live.node_id(smoke_node)

        controller = SystemWideEqController(None)
        controller.set_status_callback(statuses.append)
        wait_for_controller_ready(controller, timeout_seconds)

        virtual_sink_name = controller.virtual_sink_name
        filter_output_name = controller.filter_output_name
        virtual_serial = dispatch_until(
            "synthetic stream routed to current Mini EQ virtual sink",
            lambda: route_to_current_virtual(smoke_id, virtual_sink_name),
            timeout_seconds,
        )
        wait_for_processing_path_active(virtual_sink_name, filter_output_name, timeout_seconds)

        for cycle in range(cycles):
            print(f"## headless route toggle cycle {cycle + 1}/{cycles}", flush=True)
            controller.route_system_audio(False, announce=False)
            dispatch_until(
                "synthetic stream restored away from Mini EQ virtual sink",
                lambda serial=virtual_serial: live.metadata_targets().get(smoke_id) != (serial, "Spa:Id"),
                timeout_seconds,
            )

            controller.route_system_audio(True, announce=False)
            virtual_serial = dispatch_until(
                "synthetic stream rerouted to current Mini EQ virtual sink",
                lambda: route_to_current_virtual(smoke_id, virtual_sink_name),
                timeout_seconds,
            )
            wait_for_processing_path_active(virtual_sink_name, filter_output_name, timeout_seconds)

        alt_sink = dispatch_until(
            live.ALT_SINK_NAME,
            lambda: live.node_by_name(live.ALT_SINK_NAME),
            timeout_seconds,
        )
        alt_serial = live.object_serial(alt_sink)
        live.set_configured_default_sink_name(live.ALT_SINK_NAME, timeout_seconds)
        dispatch_until(
            f"Mini EQ controller followed {live.ALT_SINK_NAME}",
            lambda: controller.output_sink == live.ALT_SINK_NAME,
            timeout_seconds,
        )
        dispatch_until(
            f"{filter_output_name} target.object metadata to point at {alt_serial}",
            lambda: node_targets_serial(filter_output_name, alt_serial),
            timeout_seconds,
        )
        virtual_serial = dispatch_until(
            "synthetic stream stayed routed to current Mini EQ virtual sink after output move",
            lambda: route_to_current_virtual(smoke_id, virtual_sink_name),
            timeout_seconds,
        )
        wait_for_processing_path_active(virtual_sink_name, filter_output_name, timeout_seconds)

        primary_sink = dispatch_until(
            live.PRIMARY_SINK_NAME,
            lambda: live.node_by_name(live.PRIMARY_SINK_NAME),
            timeout_seconds,
        )
        primary_serial = live.object_serial(primary_sink)
        live.set_configured_default_sink_name(live.PRIMARY_SINK_NAME, timeout_seconds)
        dispatch_until(
            f"Mini EQ controller followed {live.PRIMARY_SINK_NAME}",
            lambda: controller.output_sink == live.PRIMARY_SINK_NAME,
            timeout_seconds,
        )
        dispatch_until(
            f"{filter_output_name} target.object metadata to point at {primary_serial}",
            lambda: node_targets_serial(filter_output_name, primary_serial),
            timeout_seconds,
        )
        virtual_serial = dispatch_until(
            "synthetic stream stayed routed to current Mini EQ virtual sink after output restore",
            lambda: route_to_current_virtual(smoke_id, virtual_sink_name),
            timeout_seconds,
        )
        wait_for_processing_path_active(virtual_sink_name, filter_output_name, timeout_seconds)

        controller.set_analyzer_enabled(False)
        for cycle in range(cycles):
            print(f"## headless monitor toggle cycle {cycle + 1}/{cycles}", flush=True)
            if not controller.set_analyzer_enabled(True):
                raise RuntimeError("Mini EQ analyzer monitor did not start")
            dispatch_until(
                "Mini EQ monitor PipeWire stream",
                lambda: live.node_by_name(live.ANALYZER_NODE_NAME),
                timeout_seconds,
            )
            if bad_sources := bad_monitor_source_nodes():
                raise RuntimeError(f"Monitor exposed Audio/Source nodes: {bad_sources!r}")
            virtual_serial = dispatch_until(
                "synthetic stream stayed routed while monitor was enabled",
                lambda: route_to_current_virtual(smoke_id, virtual_sink_name),
                timeout_seconds,
            )
            wait_for_processing_path_active(virtual_sink_name, filter_output_name, timeout_seconds)

            controller.set_analyzer_enabled(False)
            virtual_serial = dispatch_until(
                "synthetic stream stayed routed while monitor was disabled",
                lambda: route_to_current_virtual(smoke_id, virtual_sink_name),
                timeout_seconds,
            )
            wait_for_processing_path_active(virtual_sink_name, filter_output_name, timeout_seconds)

        live.terminate_process(smoke, "pw-cat synthetic stream")
        smoke = None
        dispatch_until("synthetic stream to disappear", lambda: live.smoke_stream_node() is None, timeout_seconds)

        print(
            "Headless PipeWire runtime smoke passed: synthetic stream routing, route toggles, "
            "default-output moves, active processing links, monitor toggles, and stream cleanup verified."
        )
        if statuses:
            print("Controller status trace:", flush=True)
            for status in statuses:
                print(f"  {status}", flush=True)
    finally:
        if controller is not None:
            controller.shutdown()
        live.terminate_process(smoke, "pw-cat synthetic stream")


def start_pipewire_session(
    tmp_dir: Path, timeout_seconds: float
) -> tuple[subprocess.Popen[str], subprocess.Popen[str]]:
    pipewire, wireplumber = live.start_pipewire_processes(tmp_dir)
    live.wait_for_sink(live.PRIMARY_SINK_NAME, timeout_seconds)
    live.wait_for_sink(live.ALT_SINK_NAME, timeout_seconds)
    live.wait_for("WirePlumber default output metadata", live.default_output_metadata_is_ready, timeout_seconds)
    return pipewire, wireplumber


def run_helper(_args: argparse.Namespace) -> int:
    try:
        for tool in ("pipewire", "wireplumber", "pw-cat", "pw-dump", "pw-metadata"):
            require_tool(tool)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return HELPER_SKIP_EXIT_CODE

    timeout_seconds = float(os.environ["MINI_EQ_HEADLESS_PIPEWIRE_TIMEOUT"])
    cycles = int(os.environ["MINI_EQ_HEADLESS_PIPEWIRE_CYCLES"])
    audio_duration = float(os.environ["MINI_EQ_HEADLESS_PIPEWIRE_AUDIO_DURATION"])
    pipewire: subprocess.Popen[str] | None = None
    wireplumber: subprocess.Popen[str] | None = None

    tmp_dir = Path(tempfile.mkdtemp(prefix="mini-eq-headless-pipewire-"))
    try:
        runtime_dir = tmp_dir / "runtime"
        config_dir = tmp_dir / "config"
        data_dir = tmp_dir / "data"
        cache_dir = tmp_dir / "cache"
        for directory in (runtime_dir, config_dir, data_dir, cache_dir):
            directory.mkdir(parents=True, exist_ok=True)
        runtime_dir.chmod(0o700)
        live.write_settings(config_dir)
        live.write_pipewire_config(config_dir)

        os.environ["XDG_RUNTIME_DIR"] = str(runtime_dir)
        os.environ["XDG_CONFIG_HOME"] = str(config_dir)
        os.environ["XDG_DATA_HOME"] = str(data_dir)
        os.environ["XDG_CACHE_HOME"] = str(cache_dir)
        os.environ["GSETTINGS_BACKEND"] = "memory"

        pipewire, wireplumber = start_pipewire_session(tmp_dir, timeout_seconds)
        run_controller_flow(
            tmp_dir=tmp_dir,
            timeout_seconds=timeout_seconds,
            cycles=cycles,
            audio_duration=audio_duration,
        )
    finally:
        live.terminate_process(wireplumber, "WirePlumber")
        live.terminate_process(pipewire, "PipeWire")
        shutil.rmtree(tmp_dir, ignore_errors=True)

    return 0


def run_parent(args: argparse.Namespace) -> int:
    try:
        require_tool("dbus-run-session")
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return HELPER_SKIP_EXIT_CODE

    env = os.environ.copy()
    env["MINI_EQ_HEADLESS_PIPEWIRE_TIMEOUT"] = str(args.timeout)
    env["MINI_EQ_HEADLESS_PIPEWIRE_CYCLES"] = str(args.cycles)
    env["MINI_EQ_HEADLESS_PIPEWIRE_AUDIO_DURATION"] = str(args.audio_duration)
    env["PYTHONUNBUFFERED"] = "1"
    env.pop("DISPLAY", None)
    env.pop("WAYLAND_DISPLAY", None)

    command = [
        "dbus-run-session",
        "--",
        sys.executable,
        str(Path(__file__).resolve()),
        "--helper",
    ]
    print(f"$ {format_command(command)}", flush=True)
    completed = subprocess.run(command, env=env, text=True)
    return completed.returncode


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Drive Mini EQ's headless controller against a private PipeWire/WirePlumber graph "
            "and synthetic playback stream."
        ),
    )
    parser.add_argument("--helper", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--timeout", type=float, default=35.0, help="Timeout for each PipeWire transition.")
    parser.add_argument("--cycles", type=int, default=3, help="Route and monitor toggle cycles to drive.")
    parser.add_argument(
        "--audio-duration",
        type=float,
        default=120.0,
        help="Duration of the generated sine-wave playback stream.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        if args.helper:
            return run_helper(args)
        return run_parent(args)
    except subprocess.CalledProcessError as exc:
        if exc.stdout:
            sys.stderr.write(exc.stdout)
        return exc.returncode
    except Exception as exc:
        print(exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
