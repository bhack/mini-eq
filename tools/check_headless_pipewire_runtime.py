#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shutil
import signal
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
HOTPLUG_SINK_NAME = "ci_hotplug_sink"
ALSA_NULL_SINK_NAME = "ci_alsa_null_sink"
MAX_CONTEXT_DRAIN_ITERATIONS = 250


def format_command(command: list[str | Path]) -> str:
    return " ".join(str(part) for part in command)


def require_tool(name: str) -> str:
    return live.require_tool(name)


def ensure_source_path() -> None:
    src_path = str(REPO_ROOT / "src")
    if src_path not in sys.path:
        sys.path.insert(0, src_path)


def drain_main_context(context: Any, *, max_iterations: int = MAX_CONTEXT_DRAIN_ITERATIONS) -> None:
    for _ in range(max_iterations):
        if not context.pending():
            return
        context.iteration(False)


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
        drain_main_context(context)

        try:
            value = predicate()
        except Exception as exc:
            last_error = exc
        else:
            if value is not None and value is not False:
                return value

        time.sleep(interval_seconds)

    drain_main_context(context)

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


def dynamic_sink_properties(sink_name: str) -> str:
    return (
        "{ "
        "factory.name = support.null-audio-sink "
        f'node.name = "{sink_name}" '
        'node.description = "CI Hotplug Sink" '
        'media.class = "Audio/Sink" '
        "object.linger = true "
        'audio.position = "FL,FR" '
        "session.suspend-timeout-seconds = 1 "
        "adapter.auto-port-config = { "
        "mode = dsp "
        "monitor = true "
        "position = preserve "
        "} "
        "}"
    )


def alsa_null_sink_properties(sink_name: str) -> str:
    return (
        "{ "
        "factory.name = api.alsa.pcm.sink "
        f'node.name = "{sink_name}" '
        'node.description = "CI ALSA Null Sink" '
        'media.class = "Audio/Sink" '
        'api.alsa.path = "null" '
        'audio.format = "S16LE" '
        "audio.rate = 48000 "
        'audio.position = "FL,FR" '
        "object.linger = true "
        "session.suspend-timeout-seconds = 1 "
        "adapter.auto-port-config = { "
        "mode = dsp "
        "monitor = true "
        "position = preserve "
        "} "
        "}"
    )


def create_dynamic_sink(sink_name: str, timeout_seconds: float) -> dict[str, Any]:
    if live.node_by_name(sink_name) is not None:
        destroy_dynamic_sink(sink_name, timeout_seconds)

    command = ["pw-cli", "create-node", "adapter", dynamic_sink_properties(sink_name)]
    print(f"$ {format_command(command)}", flush=True)
    subprocess.run(command, check=True, text=True, stdout=subprocess.DEVNULL)
    return dispatch_until(sink_name, lambda: live.node_by_name(sink_name), timeout_seconds)


def create_alsa_null_sink(sink_name: str, timeout_seconds: float) -> dict[str, Any] | None:
    if live.node_by_name(sink_name) is not None:
        destroy_dynamic_sink(sink_name, timeout_seconds)

    command = ["pw-cli", "create-node", "adapter", alsa_null_sink_properties(sink_name)]
    print(f"$ {format_command(command)}", flush=True)
    result = subprocess.run(command, check=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if result.returncode != 0:
        output = result.stdout.strip()
        detail = f": {output}" if output else ""
        print(f"## skipping ALSA null output phase; api.alsa.pcm.sink is unavailable{detail}", flush=True)
        return None

    return dispatch_until(sink_name, lambda: live.node_by_name(sink_name), timeout_seconds)


def destroy_dynamic_sink(sink_name: str, timeout_seconds: float) -> None:
    sink = live.node_by_name(sink_name)
    if sink is None:
        return

    sink_id = live.node_id(sink)
    command = ["pw-cli", "destroy", str(sink_id)]
    print(f"$ {format_command(command)}", flush=True)
    subprocess.run(command, check=True, text=True, stdout=subprocess.DEVNULL)
    dispatch_until(f"{sink_name} to disappear", lambda: live.node_by_name(sink_name) is None, timeout_seconds)


def switch_default_output_and_wait(
    controller,
    sink_name: str,
    filter_output_name: str,
    timeout_seconds: float,
) -> str:
    sink = dispatch_until(
        sink_name,
        lambda: live.node_by_name(sink_name),
        timeout_seconds,
    )
    sink_serial = live.object_serial(sink)
    live.set_configured_default_sink_name(sink_name, timeout_seconds)
    try:
        dispatch_until(
            f"Mini EQ controller followed {sink_name}",
            lambda: controller.output_sink == sink_name,
            timeout_seconds,
        )
    except RuntimeError:
        print(
            f"Controller default-follow state after {sink_name} default move: "
            f"{describe_controller_default_follow_state(controller)}",
            flush=True,
        )
        raise
    dispatch_until(
        f"{filter_output_name} target.object metadata to point at {sink_serial}",
        lambda: node_targets_serial(filter_output_name, sink_serial),
        timeout_seconds,
    )
    return sink_serial


def wait_for_stream_routed_and_processing(
    smoke_id: int,
    virtual_sink_name: str,
    filter_output_name: str,
    timeout_seconds: float,
    label: str,
) -> str:
    virtual_serial = dispatch_until(
        f"synthetic stream routed to current Mini EQ virtual sink {label}",
        lambda: route_to_current_virtual(smoke_id, virtual_sink_name),
        timeout_seconds,
    )
    wait_for_processing_path_active(virtual_sink_name, filter_output_name, timeout_seconds)
    return virtual_serial


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


def wait_for_smoke_stream(smoke: subprocess.Popen[str], timeout_seconds: float) -> int:
    smoke_node = dispatch_until(
        "synthetic PipeWire playback stream",
        lambda: live.smoke_stream_node() if smoke.poll() is None else None,
        timeout_seconds,
    )
    return live.node_id(smoke_node)


def wait_for_smoke_routed(smoke_id: int, virtual_sink_name: str, timeout_seconds: float) -> str:
    return dispatch_until(
        "synthetic stream routed to current Mini EQ virtual sink",
        lambda: route_to_current_virtual(smoke_id, virtual_sink_name),
        timeout_seconds,
    )


def force_stream_target(smoke_id: int, target_sink_name: str, timeout_seconds: float) -> str:
    target_sink = dispatch_until(
        f"PipeWire sink {target_sink_name}",
        lambda: live.node_by_name(target_sink_name),
        timeout_seconds,
    )
    target_id = live.node_id(target_sink)
    target_serial = live.object_serial(target_sink)
    for key, value in (("target.node", str(target_id)), ("target.object", target_serial)):
        subprocess.run(
            ["pw-metadata", "-n", "default", str(smoke_id), key, value, "Spa:Id"],
            check=True,
            text=True,
            stdout=subprocess.DEVNULL,
        )
    return target_serial


def stop_smoke_stream(smoke: subprocess.Popen[str], timeout_seconds: float) -> None:
    live.terminate_process(smoke, "pw-cat synthetic stream")
    dispatch_until("synthetic stream to disappear", lambda: live.smoke_stream_node() is None, timeout_seconds)


def smoke_stream_still_present(smoke_id: int) -> bool:
    smoke_node = live.smoke_stream_node()
    return smoke_node is not None and live.node_id(smoke_node) == smoke_id


def wait_for_idle_gap(label: str, idle_gap_seconds: float) -> None:
    idle_deadline = time.monotonic() + idle_gap_seconds
    dispatch_until(label, lambda: time.monotonic() >= idle_deadline, idle_gap_seconds + 1.0)


def pause_smoke_stream_for_idle(
    smoke: subprocess.Popen[str],
    smoke_id: int,
    idle_gap_seconds: float,
    timeout_seconds: float,
    during_idle: Callable[[], None] | None = None,
) -> None:
    if smoke.poll() is not None:
        raise RuntimeError("synthetic stream exited before it could be paused")

    smoke.send_signal(signal.SIGSTOP)
    try:
        dispatch_until(
            "paused synthetic stream to remain registered",
            lambda: smoke_stream_still_present(smoke_id),
            timeout_seconds,
        )
        wait_for_idle_gap("idle gap with paused synthetic stream", idle_gap_seconds)
        if during_idle is not None:
            during_idle()
    finally:
        if smoke.poll() is None:
            smoke.send_signal(signal.SIGCONT)


def describe_controller_default_follow_state(controller) -> str:
    try:
        cached_defaults = controller.output_backend.defaults()
    except Exception as exc:
        cached_defaults = f"error:{exc}"
    try:
        refreshed_defaults = controller.output_backend.refresh_defaults()
    except Exception as exc:
        refreshed_defaults = f"error:{exc}"
    try:
        sinks = controller.list_output_sink_names()
    except Exception as exc:
        sinks = f"error:{exc}"
    try:
        alt_seen = controller.get_sink(live.ALT_SINK_NAME) is not None
    except Exception as exc:
        alt_seen = f"error:{exc}"

    return (
        f"output_sink={getattr(controller, 'output_sink', None)!r}, "
        f"follow_default_output={getattr(controller, 'follow_default_output', None)!r}, "
        f"pending_followed_output_sink={getattr(controller, 'pending_followed_output_sink', None)!r}, "
        f"output_event_source_id={getattr(controller, 'output_event_source_id', None)!r}, "
        f"cached_defaults={cached_defaults!r}, "
        f"refreshed_defaults={refreshed_defaults!r}, "
        f"configured_metadata={live.configured_default_sink_name()!r}, "
        f"default_metadata={live.default_sink_name()!r}, "
        f"alt_seen_by_backend={alt_seen!r}, "
        f"output_sinks={sinks!r}"
    )


def run_dynamic_hotplug_recovery_phase(
    *,
    controller,
    smoke: subprocess.Popen[str],
    smoke_id: int,
    virtual_sink_name: str,
    filter_output_name: str,
    idle_gap_seconds: float,
    timeout_seconds: float,
) -> str:
    controller.set_analyzer_enabled(False)
    print("## headless dynamic output hotplug recovery with monitor off", flush=True)

    hotplug_sink = create_dynamic_sink(HOTPLUG_SINK_NAME, timeout_seconds)
    first_hotplug_serial = live.object_serial(hotplug_sink)
    switch_default_output_and_wait(controller, HOTPLUG_SINK_NAME, filter_output_name, timeout_seconds)
    virtual_serial = wait_for_stream_routed_and_processing(
        smoke_id,
        virtual_sink_name,
        filter_output_name,
        timeout_seconds,
        "after dynamic output move",
    )

    def remove_hotplug_and_select_primary() -> None:
        destroy_dynamic_sink(HOTPLUG_SINK_NAME, timeout_seconds)
        switch_default_output_and_wait(controller, live.PRIMARY_SINK_NAME, filter_output_name, timeout_seconds)

    pause_smoke_stream_for_idle(
        smoke,
        smoke_id,
        idle_gap_seconds,
        timeout_seconds,
        during_idle=remove_hotplug_and_select_primary,
    )
    dispatch_until(
        "resumed synthetic stream to remain registered after dynamic output removal",
        lambda: smoke_stream_still_present(smoke_id),
        timeout_seconds,
    )
    virtual_serial = wait_for_stream_routed_and_processing(
        smoke_id,
        virtual_sink_name,
        filter_output_name,
        timeout_seconds,
        "after dynamic output removal with monitor off",
    )

    hotplug_sink = create_dynamic_sink(HOTPLUG_SINK_NAME, timeout_seconds)
    second_hotplug_serial = live.object_serial(hotplug_sink)
    if second_hotplug_serial == first_hotplug_serial:
        raise RuntimeError(f"{HOTPLUG_SINK_NAME} was recreated without a new object.serial")

    switch_default_output_and_wait(controller, HOTPLUG_SINK_NAME, filter_output_name, timeout_seconds)
    virtual_serial = wait_for_stream_routed_and_processing(
        smoke_id,
        virtual_sink_name,
        filter_output_name,
        timeout_seconds,
        "after dynamic output reappeared with new serial",
    )
    switch_default_output_and_wait(controller, live.PRIMARY_SINK_NAME, filter_output_name, timeout_seconds)
    virtual_serial = wait_for_stream_routed_and_processing(
        smoke_id,
        virtual_sink_name,
        filter_output_name,
        timeout_seconds,
        "after restoring primary from dynamic output",
    )
    destroy_dynamic_sink(HOTPLUG_SINK_NAME, timeout_seconds)
    return virtual_serial


def run_alsa_null_output_phase(
    *,
    controller,
    smoke: subprocess.Popen[str],
    smoke_id: int,
    virtual_sink_name: str,
    filter_output_name: str,
    idle_gap_seconds: float,
    timeout_seconds: float,
) -> tuple[str, bool]:
    controller.set_analyzer_enabled(False)
    print("## headless ALSA-backed null output recovery with monitor off", flush=True)

    alsa_sink = create_alsa_null_sink(ALSA_NULL_SINK_NAME, timeout_seconds)
    if alsa_sink is None:
        virtual_serial = wait_for_stream_routed_and_processing(
            smoke_id,
            virtual_sink_name,
            filter_output_name,
            timeout_seconds,
            "after skipped ALSA-backed null output phase",
        )
        return virtual_serial, False

    try:
        switch_default_output_and_wait(controller, ALSA_NULL_SINK_NAME, filter_output_name, timeout_seconds)
        virtual_serial = wait_for_stream_routed_and_processing(
            smoke_id,
            virtual_sink_name,
            filter_output_name,
            timeout_seconds,
            "after ALSA-backed null output move",
        )

        pause_smoke_stream_for_idle(smoke, smoke_id, idle_gap_seconds, timeout_seconds)
        dispatch_until(
            "resumed synthetic stream to remain registered after ALSA-backed output idle",
            lambda: smoke_stream_still_present(smoke_id),
            timeout_seconds,
        )
        virtual_serial = wait_for_stream_routed_and_processing(
            smoke_id,
            virtual_sink_name,
            filter_output_name,
            timeout_seconds,
            "after ALSA-backed null output idle",
        )

        def remove_alsa_and_select_primary() -> None:
            destroy_dynamic_sink(ALSA_NULL_SINK_NAME, timeout_seconds)
            switch_default_output_and_wait(controller, live.PRIMARY_SINK_NAME, filter_output_name, timeout_seconds)

        pause_smoke_stream_for_idle(
            smoke,
            smoke_id,
            idle_gap_seconds,
            timeout_seconds,
            during_idle=remove_alsa_and_select_primary,
        )
        dispatch_until(
            "resumed synthetic stream to remain registered after ALSA-backed output removal",
            lambda: smoke_stream_still_present(smoke_id),
            timeout_seconds,
        )
        virtual_serial = wait_for_stream_routed_and_processing(
            smoke_id,
            virtual_sink_name,
            filter_output_name,
            timeout_seconds,
            "after ALSA-backed null output removal",
        )
        return virtual_serial, True
    finally:
        destroy_dynamic_sink(ALSA_NULL_SINK_NAME, timeout_seconds)


def run_controller_flow(
    *,
    tmp_dir: Path,
    timeout_seconds: float,
    cycles: int,
    audio_duration: float,
    idle_gap_seconds: float,
) -> None:
    ensure_source_path()

    from mini_eq.routing import SystemWideEqController

    live.set_configured_default_sink_name(live.PRIMARY_SINK_NAME, timeout_seconds)
    live.verify_pipewire_gobject_probe(timeout_seconds)

    audio_file = live.create_sine_wav(tmp_dir / "mini-eq-headless-pipewire-smoke.wav", audio_duration)
    smoke: subprocess.Popen[str] | None = live.start_smoke_stream(audio_file)
    controller = None
    statuses: list[str] = []

    try:
        smoke_id = wait_for_smoke_stream(smoke, timeout_seconds)

        controller = SystemWideEqController(None)
        controller.set_status_callback(statuses.append)
        wait_for_controller_ready(controller, timeout_seconds)

        virtual_sink_name = controller.virtual_sink_name
        filter_output_name = controller.filter_output_name
        virtual_serial = wait_for_smoke_routed(smoke_id, virtual_sink_name, timeout_seconds)
        wait_for_processing_path_active(virtual_sink_name, filter_output_name, timeout_seconds)

        print("## headless idle stream recreation", flush=True)
        stop_smoke_stream(smoke, timeout_seconds)
        smoke = None
        wait_for_idle_gap("idle gap after synthetic stream cleanup", idle_gap_seconds)
        smoke = live.start_smoke_stream(audio_file)
        smoke_id = wait_for_smoke_stream(smoke, timeout_seconds)
        virtual_serial = wait_for_smoke_routed(smoke_id, virtual_sink_name, timeout_seconds)
        wait_for_processing_path_active(virtual_sink_name, filter_output_name, timeout_seconds)

        print("## headless paused stream resume", flush=True)
        pause_smoke_stream_for_idle(smoke, smoke_id, idle_gap_seconds, timeout_seconds)
        dispatch_until(
            "resumed synthetic stream to remain registered",
            lambda: smoke_stream_still_present(smoke_id),
            timeout_seconds,
        )
        virtual_serial = wait_for_stream_routed_and_processing(
            smoke_id,
            virtual_sink_name,
            filter_output_name,
            timeout_seconds,
            "after paused resume",
        )

        print("## headless tracked stream relink recovery", flush=True)
        force_stream_target(smoke_id, live.PRIMARY_SINK_NAME, timeout_seconds)
        virtual_serial = wait_for_stream_routed_and_processing(
            smoke_id,
            virtual_sink_name,
            filter_output_name,
            timeout_seconds,
            "after tracked stream relink",
        )

        controller.set_analyzer_enabled(False)
        print("## headless paused output switch recovery with monitor off", flush=True)

        def switch_to_alt_output() -> None:
            switch_default_output_and_wait(
                controller,
                live.ALT_SINK_NAME,
                filter_output_name,
                timeout_seconds,
            )

        pause_smoke_stream_for_idle(
            smoke,
            smoke_id,
            idle_gap_seconds,
            timeout_seconds,
            during_idle=switch_to_alt_output,
        )
        dispatch_until(
            "resumed synthetic stream to remain registered after paused output move",
            lambda: smoke_stream_still_present(smoke_id),
            timeout_seconds,
        )
        virtual_serial = wait_for_stream_routed_and_processing(
            smoke_id,
            virtual_sink_name,
            filter_output_name,
            timeout_seconds,
            "after paused output move with monitor off",
        )

        def switch_to_primary_output() -> None:
            switch_default_output_and_wait(
                controller,
                live.PRIMARY_SINK_NAME,
                filter_output_name,
                timeout_seconds,
            )

        pause_smoke_stream_for_idle(
            smoke,
            smoke_id,
            idle_gap_seconds,
            timeout_seconds,
            during_idle=switch_to_primary_output,
        )
        dispatch_until(
            "resumed synthetic stream to remain registered after paused output restore",
            lambda: smoke_stream_still_present(smoke_id),
            timeout_seconds,
        )
        virtual_serial = wait_for_stream_routed_and_processing(
            smoke_id,
            virtual_sink_name,
            filter_output_name,
            timeout_seconds,
            "after paused output restore with monitor off",
        )

        virtual_serial = run_dynamic_hotplug_recovery_phase(
            controller=controller,
            smoke=smoke,
            smoke_id=smoke_id,
            virtual_sink_name=virtual_sink_name,
            filter_output_name=filter_output_name,
            idle_gap_seconds=idle_gap_seconds,
            timeout_seconds=timeout_seconds,
        )

        virtual_serial, alsa_null_phase_verified = run_alsa_null_output_phase(
            controller=controller,
            smoke=smoke,
            smoke_id=smoke_id,
            virtual_sink_name=virtual_sink_name,
            filter_output_name=filter_output_name,
            idle_gap_seconds=idle_gap_seconds,
            timeout_seconds=timeout_seconds,
        )

        for cycle in range(cycles):
            print(f"## headless route toggle cycle {cycle + 1}/{cycles}", flush=True)
            controller.route_system_audio(False, announce=False)
            dispatch_until(
                "synthetic stream restored away from Mini EQ virtual sink",
                lambda serial=virtual_serial: live.metadata_targets().get(smoke_id) != (serial, "Spa:Id"),
                timeout_seconds,
            )

            controller.route_system_audio(True, announce=False)
            virtual_serial = wait_for_stream_routed_and_processing(
                smoke_id,
                virtual_sink_name,
                filter_output_name,
                timeout_seconds,
                "after route toggle",
            )

        switch_default_output_and_wait(
            controller,
            live.ALT_SINK_NAME,
            filter_output_name,
            timeout_seconds,
        )
        virtual_serial = wait_for_stream_routed_and_processing(
            smoke_id,
            virtual_sink_name,
            filter_output_name,
            timeout_seconds,
            "after output move",
        )

        switch_default_output_and_wait(
            controller,
            live.PRIMARY_SINK_NAME,
            filter_output_name,
            timeout_seconds,
        )
        virtual_serial = wait_for_stream_routed_and_processing(
            smoke_id,
            virtual_sink_name,
            filter_output_name,
            timeout_seconds,
            "after output restore",
        )

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

        stop_smoke_stream(smoke, timeout_seconds)
        smoke = None

        optional_phase_labels = []
        if alsa_null_phase_verified:
            optional_phase_labels.append("ALSA-backed null output recovery")
        optional_phases = f"{', '.join(optional_phase_labels)}, " if optional_phase_labels else ""

        print(
            "Headless PipeWire runtime smoke passed: synthetic stream routing, route toggles, "
            "idle stream recreation, paused stream resume, tracked stream relink recovery, "
            "paused default-output moves with monitor off, dynamic output hotplug recovery, "
            f"{optional_phases}active processing links, "
            "monitor toggles, and stream cleanup verified."
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
    live.wait_for("WirePlumber default metadata", live.default_metadata_is_ready, timeout_seconds)
    live.set_configured_default_sink_name(live.PRIMARY_SINK_NAME, timeout_seconds)
    return pipewire, wireplumber


def run_helper(_args: argparse.Namespace) -> int:
    try:
        for tool in ("pipewire", "wireplumber", "wpctl", "pw-cat", "pw-cli", "pw-dump", "pw-metadata"):
            require_tool(tool)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return HELPER_SKIP_EXIT_CODE

    timeout_seconds = float(os.environ["MINI_EQ_HEADLESS_PIPEWIRE_TIMEOUT"])
    cycles = int(os.environ["MINI_EQ_HEADLESS_PIPEWIRE_CYCLES"])
    audio_duration = float(os.environ["MINI_EQ_HEADLESS_PIPEWIRE_AUDIO_DURATION"])
    idle_gap_seconds = float(os.environ["MINI_EQ_HEADLESS_PIPEWIRE_IDLE_GAP"])
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
            idle_gap_seconds=idle_gap_seconds,
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
    env["MINI_EQ_HEADLESS_PIPEWIRE_IDLE_GAP"] = str(args.idle_gap)
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
    parser.add_argument(
        "--idle-gap",
        type=float,
        default=8.0,
        help=("Seconds to keep Mini EQ routed during the streamless recreation and paused persistent-stream phases."),
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
