#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import time
import wave
from collections.abc import Callable
from pathlib import Path
from typing import Any

APP_ID = "io.github.bhack.mini-eq"
DEFAULT_APP_REF = f"{APP_ID}//master"
STABLE_APP_REF = f"{APP_ID}//stable"
TEST_APP_REF = f"{APP_ID}//test"
FULL_AARCH64_MASTER_REF = f"app/{APP_ID}/aarch64/master"
FULL_AARCH64_STABLE_REF = f"app/{APP_ID}/aarch64/stable"
FULL_AARCH64_TEST_REF = f"app/{APP_ID}/aarch64/test"
FULL_X86_64_MASTER_REF = f"app/{APP_ID}/x86_64/master"
FULL_X86_64_STABLE_REF = f"app/{APP_ID}/x86_64/stable"
FULL_X86_64_TEST_REF = f"app/{APP_ID}/x86_64/test"
FLATPAK_APP_REFS = (
    APP_ID,
    DEFAULT_APP_REF,
    STABLE_APP_REF,
    TEST_APP_REF,
    FULL_AARCH64_MASTER_REF,
    FULL_AARCH64_STABLE_REF,
    FULL_AARCH64_TEST_REF,
    FULL_X86_64_MASTER_REF,
    FULL_X86_64_STABLE_REF,
    FULL_X86_64_TEST_REF,
)
SMOKE_APPLICATION_NAME = "mini-eq-flatpak-smoke"
SMOKE_MEDIA_ROLE = "MiniEQSmoke"
SMOKE_NODE_NAME = "mini-eq-flatpak-smoke"
VIRTUAL_SINK_NAME = "mini_eq_sink"
FILTER_OUTPUT_NAME = f"{VIRTUAL_SINK_NAME}_output"
PIPEWIRE_MANAGER_ACCESS = "flatpak-manager"
TARGET_OBJECT_RE = re.compile(
    r"update: id:(?P<id>\d+) key:'target\.object' value:'(?P<value>[^']*)' type:'(?P<type>[^']*)'"
)
PIPEWIRE_TARGET_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]*\Z")


def format_command(command: list[str | Path]) -> str:
    return " ".join(str(part) for part in command)


def run(command: list[str | Path], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    print(f"$ {format_command(command)}", flush=True)
    return subprocess.run(
        [str(part) for part in command],
        check=check,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )


def require_tools(*tools: str) -> None:
    missing = [tool for tool in tools if shutil.which(tool) is None]
    if missing:
        raise RuntimeError(f"Missing required tool(s): {', '.join(missing)}")


def flatpak_app_ref(value: str) -> str:
    for supported_ref in FLATPAK_APP_REFS:
        if value == supported_ref:
            return supported_ref
    raise argparse.ArgumentTypeError(f"unsupported Flatpak app ref: {value}")


def pipewire_node_target(value: str) -> str:
    if PIPEWIRE_TARGET_RE.fullmatch(value):
        return value
    raise argparse.ArgumentTypeError(f"invalid PipeWire node target: {value}")


def flatpak_run_extra_args() -> list[str]:
    return shlex.split(os.environ.get("MINI_EQ_FLATPAK_RUN_ARGS", ""))


def flatpak_run_command(app_ref: str, *app_args: str) -> list[str]:
    extra_args = flatpak_run_extra_args()
    if app_ref == APP_ID:
        return ["flatpak", "run", *extra_args, APP_ID, *app_args]
    if app_ref == DEFAULT_APP_REF:
        return ["flatpak", "run", *extra_args, DEFAULT_APP_REF, *app_args]
    if app_ref == STABLE_APP_REF:
        return ["flatpak", "run", *extra_args, STABLE_APP_REF, *app_args]
    if app_ref == TEST_APP_REF:
        return ["flatpak", "run", *extra_args, TEST_APP_REF, *app_args]
    if app_ref == FULL_AARCH64_MASTER_REF:
        return ["flatpak", "run", *extra_args, FULL_AARCH64_MASTER_REF, *app_args]
    if app_ref == FULL_AARCH64_STABLE_REF:
        return ["flatpak", "run", *extra_args, FULL_AARCH64_STABLE_REF, *app_args]
    if app_ref == FULL_AARCH64_TEST_REF:
        return ["flatpak", "run", *extra_args, FULL_AARCH64_TEST_REF, *app_args]
    if app_ref == FULL_X86_64_MASTER_REF:
        return ["flatpak", "run", *extra_args, FULL_X86_64_MASTER_REF, *app_args]
    if app_ref == FULL_X86_64_STABLE_REF:
        return ["flatpak", "run", *extra_args, FULL_X86_64_STABLE_REF, *app_args]
    if app_ref == FULL_X86_64_TEST_REF:
        return ["flatpak", "run", *extra_args, FULL_X86_64_TEST_REF, *app_args]
    raise RuntimeError(f"unsupported Flatpak app ref: {app_ref}")


def read_pw_dump() -> list[dict[str, Any]]:
    result = subprocess.run(["pw-dump"], check=True, text=True, stdout=subprocess.PIPE)
    payload, _end = json.JSONDecoder().raw_decode(result.stdout.lstrip())
    if not isinstance(payload, list):
        raise RuntimeError("pw-dump returned an unexpected JSON shape")
    return payload


def item_props(item: dict[str, Any]) -> dict[str, Any]:
    props = item.get("info", {}).get("props", {})
    return props if isinstance(props, dict) else {}


def node_items() -> list[dict[str, Any]]:
    return [item for item in read_pw_dump() if item.get("type") == "PipeWire:Interface:Node"]


def link_items() -> list[dict[str, Any]]:
    return [item for item in read_pw_dump() if item.get("type") == "PipeWire:Interface:Link"]


def client_items() -> list[dict[str, Any]]:
    return [item for item in read_pw_dump() if item.get("type") == "PipeWire:Interface:Client"]


def node_by_name(node_name: str) -> dict[str, Any] | None:
    for node in node_items():
        if item_props(node).get("node.name") == node_name:
            return node
    return None


def smoke_stream_node() -> dict[str, Any] | None:
    for node in node_items():
        props = item_props(node)
        if props.get("media.class") == "Stream/Output/Audio" and (
            props.get("application.name") == SMOKE_APPLICATION_NAME or props.get("node.name") == SMOKE_NODE_NAME
        ):
            return node
    return None


def object_serial(node: dict[str, Any]) -> str:
    serial = item_props(node).get("object.serial")
    if serial is None:
        raise RuntimeError(f"PipeWire node has no object.serial: {item_props(node).get('node.name')}")
    return str(serial)


def bound_id(node: dict[str, Any]) -> int:
    node_id = node.get("id")
    if not isinstance(node_id, int):
        raise RuntimeError(f"PipeWire node has no integer id: {item_props(node).get('node.name')}")
    return node_id


def link_endpoint_ids(link: dict[str, Any]) -> set[int]:
    endpoints: set[int] = set()
    props = item_props(link)
    for key in ("link.output.node", "link.input.node"):
        try:
            endpoints.add(int(props.get(key)))
        except (TypeError, ValueError):
            pass
    return endpoints


def link_state(link: dict[str, Any]) -> str | None:
    info_state = link.get("info", {}).get("state")
    if isinstance(info_state, str):
        return info_state
    prop_state = item_props(link).get("link.state")
    return str(prop_state) if prop_state is not None else None


def metadata_targets() -> dict[int, tuple[str, str]]:
    result = subprocess.run(["pw-metadata", "-n", "default"], check=True, text=True, stdout=subprocess.PIPE)
    targets: dict[int, tuple[str, str]] = {}

    for line in result.stdout.splitlines():
        match = TARGET_OBJECT_RE.search(line)
        if match is not None:
            targets[int(match.group("id"))] = (match.group("value"), match.group("type"))

    return targets


def wait_for(label: str, predicate: Callable[[], Any], timeout_seconds: float) -> Any:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None

    while time.monotonic() < deadline:
        try:
            value = predicate()
        except Exception as exc:
            last_error = exc
        else:
            if value:
                return value

        time.sleep(0.1)

    detail = f": {last_error}" if last_error is not None else ""
    raise RuntimeError(f"Timed out waiting for {label}{detail}")


def route_to_current_virtual(smoke_id: int, virtual_serial: str) -> bool:
    return metadata_targets().get(smoke_id) == (virtual_serial, "Spa:Id")


def force_stream_target(smoke_id: int, target_sink_name: str, timeout_seconds: float) -> str:
    target_sink = wait_for(
        f"PipeWire sink {target_sink_name}",
        lambda: node_by_name(target_sink_name),
        timeout_seconds,
    )
    target_id = bound_id(target_sink)
    target_serial = object_serial(target_sink)
    for key, value in (("target.node", str(target_id)), ("target.object", target_serial)):
        subprocess.run(
            ["pw-metadata", "-n", "default", str(smoke_id), key, value, "Spa:Id"],
            check=True,
            text=True,
            stdout=subprocess.DEVNULL,
        )
    return target_serial


def processing_path_has_active_links() -> bool:
    virtual_sink = node_by_name(VIRTUAL_SINK_NAME)
    filter_output = node_by_name(FILTER_OUTPUT_NAME)
    if virtual_sink is None or filter_output is None:
        return False

    required_ids = {bound_id(virtual_sink): False, bound_id(filter_output): False}
    for link in link_items():
        if link_state(link) != "active":
            continue
        endpoints = link_endpoint_ids(link)
        for required_id in tuple(required_ids):
            if required_id in endpoints:
                required_ids[required_id] = True

    return all(required_ids.values())


def mini_eq_has_manager_access() -> bool:
    for client in client_items():
        props = item_props(client)
        if (
            props.get("application.name") == "Mini EQ"
            and props.get("media.category") == "Manager"
            and props.get("pipewire.access.effective") == PIPEWIRE_MANAGER_ACCESS
        ):
            return True
    return False


def create_silent_wav(duration_seconds: float) -> Path:
    path = Path("/tmp/mini-eq-flatpak-smoke.wav")
    frame_count = max(1, math.ceil(duration_seconds * 48_000))
    silence = b"\0" * 2 * 2 * 48_000

    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(48_000)
        for _ in range(math.ceil(frame_count / 48_000)):
            wav.writeframes(silence)

    return path


def start_smoke_stream(target: str | None, audio_file: Path) -> subprocess.Popen[str]:
    command = [
        "pw-cat",
        "--playback",
        "--media-role",
        SMOKE_MEDIA_ROLE,
        "--properties",
        ",".join(
            [
                f"application.name={SMOKE_APPLICATION_NAME}",
                f"node.name={SMOKE_NODE_NAME}",
                "state.restore-props=false",
                "state.restore-target=false",
            ]
        ),
    ]
    if target is not None:
        command.extend(["--target", target])
    command.append(audio_file)
    print(f"$ {format_command(command)}", flush=True)
    return subprocess.Popen(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)


def stop_process(process: subprocess.Popen[str], label: str, timeout_seconds: float = 5.0) -> str:
    if process.poll() is not None:
        output = process.stdout.read() if process.stdout is not None and not process.stdout.closed else ""
        if output:
            print(f"{label} output:\n{output.rstrip()}", flush=True)
        return output

    process.terminate()
    try:
        output, _stderr = process.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        process.kill()
        output, _stderr = process.communicate(timeout=timeout_seconds)

    if output:
        print(f"{label} output:\n{output.rstrip()}", flush=True)
    return output or ""


def stop_smoke_stream(smoke: subprocess.Popen[str], timeout_seconds: float) -> None:
    stop_process(smoke, "pw-cat smoke stream", timeout_seconds)
    wait_for("smoke stream to disappear", lambda: smoke_stream_node() is None, timeout_seconds)


def wait_for_smoke_stream(smoke: subprocess.Popen[str], timeout_seconds: float) -> int:
    def live_smoke_stream_node() -> dict[str, Any] | None:
        if smoke.poll() is not None:
            output = stop_process(smoke, "pw-cat smoke stream")
            detail = f": {output.strip()}" if output.strip() else ""
            raise RuntimeError(f"pw-cat exited before its PipeWire stream appeared{detail}")
        return smoke_stream_node()

    return bound_id(wait_for("silent PipeWire smoke stream", live_smoke_stream_node, timeout_seconds))


def smoke_stream_still_present(smoke_id: int) -> bool:
    smoke_node = smoke_stream_node()
    return smoke_node is not None and bound_id(smoke_node) == smoke_id


def wait_for_idle_gap(label: str, idle_gap_seconds: float) -> None:
    deadline = time.monotonic() + idle_gap_seconds
    wait_for(label, lambda: time.monotonic() >= deadline, idle_gap_seconds + 1.0)


def pause_smoke_stream_for_idle(
    smoke: subprocess.Popen[str],
    smoke_id: int,
    idle_gap_seconds: float,
    timeout_seconds: float,
) -> None:
    if smoke.poll() is not None:
        raise RuntimeError("pw-cat exited before it could be paused")

    smoke.send_signal(signal.SIGSTOP)
    try:
        wait_for(
            "paused smoke stream to remain registered", lambda: smoke_stream_still_present(smoke_id), timeout_seconds
        )
        wait_for_idle_gap("idle gap with paused smoke stream", idle_gap_seconds)
    finally:
        if smoke.poll() is None:
            smoke.send_signal(signal.SIGCONT)


def assert_no_existing_virtual_sink() -> None:
    if node_by_name(VIRTUAL_SINK_NAME) is not None:
        raise RuntimeError(
            f"{VIRTUAL_SINK_NAME} already exists. Close Mini EQ and remove stale filter-chain state before rerunning."
        )


def run_runtime_smoke(
    app_ref: str,
    duration_seconds: float,
    timeout_seconds: float,
    smoke_target: str | None,
    idle_gap_seconds: float,
) -> None:
    assert_no_existing_virtual_sink()

    deps = run(flatpak_run_command(app_ref, "--check-deps"))
    print(deps.stdout.rstrip(), flush=True)

    # Keep the Flatpak alive across every post-start transition this smoke can wait for.
    post_start_transition_count = 9 if smoke_target is not None else 7
    app_duration = max(
        duration_seconds,
        timeout_seconds * post_start_transition_count + idle_gap_seconds * 2.0 + 10.0,
    )

    # Keep pw-cat alive across stream discovery, app startup, routing, idle phases, and restore waits.
    smoke_audio_duration = max(app_duration + timeout_seconds * 4.0 + idle_gap_seconds * 2.0 + 15.0, 60.0)
    smoke_audio = create_silent_wav(smoke_audio_duration)
    smoke = start_smoke_stream(smoke_target, smoke_audio)
    app: subprocess.Popen[str] | None = None
    relink_recovery_checked = False

    try:
        smoke_id = wait_for_smoke_stream(smoke, timeout_seconds)
        original_target = metadata_targets().get(smoke_id)

        command = flatpak_run_command(
            app_ref,
            "--headless",
            "--auto-route",
            "--duration",
            str(app_duration),
        )
        print(f"$ {format_command(command)}", flush=True)
        app = subprocess.Popen(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        manager_access_seen = False

        def note_manager_access() -> None:
            nonlocal manager_access_seen
            manager_access_seen = manager_access_seen or mini_eq_has_manager_access()

        def require_mini_eq_running(label: str) -> None:
            if app is not None and app.poll() is not None:
                output = stop_process(app, "Mini EQ Flatpak")
                detail = f": {output.strip()}" if output.strip() else f" with status {app.returncode}"
                raise RuntimeError(f"Mini EQ Flatpak exited before {label}{detail}")

        def live_virtual_sink() -> dict[str, Any] | None:
            note_manager_access()
            require_mini_eq_running(f"{VIRTUAL_SINK_NAME} appeared")
            return node_by_name(VIRTUAL_SINK_NAME)

        virtual_sink = wait_for(
            f"{VIRTUAL_SINK_NAME} PipeWire node",
            live_virtual_sink,
            timeout_seconds,
        )
        virtual_serial = object_serial(virtual_sink)

        def smoke_stream_targets_virtual_sink() -> bool:
            note_manager_access()
            require_mini_eq_running("the smoke stream was routed")
            return route_to_current_virtual(smoke_id, virtual_serial)

        wait_for("smoke stream routed through Mini EQ", smoke_stream_targets_virtual_sink, timeout_seconds)
        wait_for("Mini EQ processing path links to become active", processing_path_has_active_links, timeout_seconds)

        print("## Flatpak idle stream recreation", flush=True)
        stop_smoke_stream(smoke, timeout_seconds)
        wait_for_idle_gap("idle gap after smoke stream cleanup", idle_gap_seconds)
        smoke = start_smoke_stream(smoke_target, smoke_audio)
        smoke_id = wait_for_smoke_stream(smoke, timeout_seconds)
        original_target = None
        wait_for("recreated smoke stream routed through Mini EQ", smoke_stream_targets_virtual_sink, timeout_seconds)
        wait_for(
            "Mini EQ processing path links to become active after stream recreation",
            processing_path_has_active_links,
            timeout_seconds,
        )

        print("## Flatpak paused stream resume", flush=True)
        pause_smoke_stream_for_idle(smoke, smoke_id, idle_gap_seconds, timeout_seconds)
        wait_for(
            "resumed smoke stream to remain registered", lambda: smoke_stream_still_present(smoke_id), timeout_seconds
        )
        wait_for(
            "resumed smoke stream still routed through Mini EQ", smoke_stream_targets_virtual_sink, timeout_seconds
        )
        wait_for(
            "Mini EQ processing path links to become active after paused resume",
            processing_path_has_active_links,
            timeout_seconds,
        )

        if smoke_target is not None:
            print("## Flatpak tracked stream relink recovery", flush=True)
            force_stream_target(smoke_id, smoke_target, timeout_seconds)
            wait_for(
                "relinked smoke stream routed back through Mini EQ", smoke_stream_targets_virtual_sink, timeout_seconds
            )
            wait_for(
                "Mini EQ processing path links to become active after tracked stream relink",
                processing_path_has_active_links,
                timeout_seconds,
            )
            relink_recovery_checked = True

        output, _stderr = app.communicate(timeout=max(app_duration + timeout_seconds, timeout_seconds))
        print(output.rstrip(), flush=True)
        if app.returncode != 0:
            raise RuntimeError(f"Mini EQ Flatpak exited with status {app.returncode}")

        def smoke_stream_restored() -> bool:
            restored_target = metadata_targets().get(smoke_id)
            if original_target is not None:
                return restored_target == original_target
            return restored_target != (virtual_serial, "Spa:Id")

        wait_for("smoke stream restored after Mini EQ exits", smoke_stream_restored, timeout_seconds)

        if original_target is not None:
            restored_target = metadata_targets().get(smoke_id)
            print(f"Smoke stream restored to {restored_target}.", flush=True)

        if manager_access_seen:
            print("Mini EQ PipeWire manager access client observed.", flush=True)
        else:
            print("Mini EQ PipeWire manager access client was not observed; routing behavior was verified.", flush=True)

        relink_summary = "tracked stream relink recovery, " if relink_recovery_checked else ""
        print(
            "Flatpak runtime smoke passed: stream routing, idle stream recreation, "
            f"paused stream resume, {relink_summary}active processing links, and restore behavior verified."
        )
    finally:
        if app is not None:
            stop_process(app, "Mini EQ Flatpak")
        stop_process(smoke, "pw-cat smoke stream")
        smoke_audio.unlink(missing_ok=True)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Smoke-test Mini EQ Flatpak runtime routing against the live PipeWire session.",
    )
    parser.add_argument(
        "--app-ref",
        type=flatpak_app_ref,
        default=DEFAULT_APP_REF,
        help=f"Flatpak app ref to test (default: {DEFAULT_APP_REF})",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=8.0,
        help="Minimum seconds to keep the headless Mini EQ app running; idle phases may extend this.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=20.0,
        help="Timeout in seconds for each PipeWire state transition.",
    )
    parser.add_argument(
        "--smoke-target",
        type=pipewire_node_target,
        default=None,
        help="Optional PipeWire node target for the silent smoke stream; enables tracked relink recovery coverage.",
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
        require_tools("flatpak", "pw-cat", "pw-dump", "pw-metadata")
        run_runtime_smoke(args.app_ref, args.duration, args.timeout, args.smoke_target, args.idle_gap)
    except subprocess.CalledProcessError as exc:
        if exc.stdout:
            sys.stderr.write(exc.stdout)
        return exc.returncode
    except Exception as exc:
        print(exc, file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
