#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import subprocess
import sys
import time
import wave
from collections.abc import Callable
from pathlib import Path
from typing import Any

APP_ID = "io.github.bhack.mini-eq"
DEFAULT_APP_REF = f"{APP_ID}//master"
FLATPAK_APP_REFS = tuple(
    sorted(
        {
            APP_ID,
            f"{APP_ID}//master",
            f"{APP_ID}//stable",
            *(f"app/{APP_ID}/{arch}/{branch}" for arch in ("aarch64", "x86_64") for branch in ("master", "stable")),
        }
    )
)
SMOKE_APPLICATION_NAME = "mini-eq-flatpak-smoke"
SMOKE_NODE_NAME = "mini-eq-flatpak-smoke"
VIRTUAL_SINK_NAME = "mini_eq_sink"
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
        "--volume",
        "0",
        "--properties",
        f"application.name={SMOKE_APPLICATION_NAME}",
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
) -> None:
    assert_no_existing_virtual_sink()

    deps = run(["flatpak", "run", app_ref, "--check-deps"])
    print(deps.stdout.rstrip(), flush=True)

    # Keep pw-cat alive across stream discovery, app startup, routing, app runtime, and restore waits.
    smoke_audio_duration = max(duration_seconds + timeout_seconds * 4.0 + 15.0, 60.0)
    smoke_audio = create_silent_wav(smoke_audio_duration)
    smoke = start_smoke_stream(smoke_target, smoke_audio)
    app: subprocess.Popen[str] | None = None

    try:

        def live_smoke_stream_node() -> dict[str, Any] | None:
            if smoke.poll() is not None:
                output = stop_process(smoke, "pw-cat smoke stream")
                detail = f": {output.strip()}" if output.strip() else ""
                raise RuntimeError(f"pw-cat exited before its PipeWire stream appeared{detail}")
            return smoke_stream_node()

        smoke_node = wait_for("silent PipeWire smoke stream", live_smoke_stream_node, timeout_seconds)
        smoke_id = bound_id(smoke_node)
        original_target = metadata_targets().get(smoke_id)

        command = [
            "flatpak",
            "run",
            app_ref,
            "--headless",
            "--auto-route",
            "--duration",
            str(duration_seconds),
        ]
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
            target = metadata_targets().get(smoke_id)
            return target == (virtual_serial, "Spa:Id")

        wait_for("smoke stream routed through Mini EQ", smoke_stream_targets_virtual_sink, timeout_seconds)

        output, _stderr = app.communicate(timeout=max(duration_seconds + timeout_seconds, timeout_seconds))
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

        print("Flatpak runtime smoke passed: stream routing and restore behavior verified.")
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
        help="How long to keep the headless Mini EQ app running during the routing check.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=8.0,
        help="Timeout in seconds for each PipeWire state transition.",
    )
    parser.add_argument(
        "--smoke-target",
        type=pipewire_node_target,
        default=None,
        help="Optional PipeWire node target for the silent smoke stream.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)

    try:
        require_tools("flatpak", "pw-cat", "pw-dump", "pw-metadata")
        run_runtime_smoke(args.app_ref, args.duration, args.timeout, args.smoke_target)
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
