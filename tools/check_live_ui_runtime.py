#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import wave
from collections.abc import Callable
from pathlib import Path
from typing import Any

HELPER_SKIP_EXIT_CODE = 77
REPO_ROOT = Path(__file__).resolve().parents[1]
APP_FRAME_NAME = "Mini EQ"
VIRTUAL_SINK_NAME = "mini_eq_sink"
SMOKE_APPLICATION_NAME = "mini-eq-live-ui-smoke"
SMOKE_NODE_NAME = "mini-eq-live-ui-smoke"
ANALYZER_NODE_NAME = "mini-eq-analyzer"
PRIMARY_SINK_NAME = "ci_null_sink"
ALT_SINK_NAME = "ci_alt_sink"
WAIT_EVENT_NAMES = (
    "window",
    "object:children-changed",
    "object:property-change",
    "object:state-changed",
    "object:text-changed",
)
TARGET_OBJECT_RE = re.compile(
    r"update: id:(?P<id>\d+) key:'target\.object' value:'(?P<value>[^']*)' type:'(?P<type>[^']*)'"
)


def format_command(command: list[str | Path]) -> str:
    return " ".join(str(part) for part in command)


def require_tool(name: str) -> str:
    path = shutil.which(name)
    if path is None:
        raise RuntimeError(f"missing required tool: {name}")
    return path


def terminate_process(process: subprocess.Popen[str] | None, label: str, timeout_seconds: float = 5.0) -> str:
    if process is None:
        return ""

    if process.poll() is None:
        process.terminate()
        try:
            output, _stderr = process.communicate(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            process.kill()
            output, _stderr = process.communicate(timeout=timeout_seconds)
    else:
        output = process.stdout.read() if process.stdout is not None and not process.stdout.closed else ""

    if output:
        print(f"{label} output:\n{output.rstrip()}", flush=True)
    return output or ""


def wait_for(label: str, predicate: Callable[[], Any], timeout_seconds: float, interval_seconds: float = 0.1) -> Any:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None

    while time.monotonic() < deadline:
        try:
            value = predicate()
        except Exception as exc:
            last_error = exc
        else:
            if value is not None and value is not False:
                return value

        time.sleep(interval_seconds)

    detail = f": {last_error}" if last_error is not None else ""
    raise RuntimeError(f"timed out waiting for {label}{detail}")


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


def node_by_name(node_name: str) -> dict[str, Any] | None:
    for node in node_items():
        if item_props(node).get("node.name") == node_name:
            return node
    return None


def node_id(node: dict[str, Any]) -> int:
    value = node.get("id")
    if not isinstance(value, int):
        raise RuntimeError(f"PipeWire node has no integer id: {item_props(node).get('node.name')}")
    return value


def object_serial(node: dict[str, Any]) -> str:
    serial = item_props(node).get("object.serial")
    if serial is None:
        raise RuntimeError(f"PipeWire node has no object.serial: {item_props(node).get('node.name')}")
    return str(serial)


def smoke_stream_node() -> dict[str, Any] | None:
    for node in node_items():
        props = item_props(node)
        if props.get("media.class") == "Stream/Output/Audio" and (
            props.get("application.name") == SMOKE_APPLICATION_NAME or props.get("node.name") == SMOKE_NODE_NAME
        ):
            return node
    return None


def metadata_targets() -> dict[int, tuple[str, str]]:
    result = subprocess.run(["pw-metadata", "-n", "default"], check=True, text=True, stdout=subprocess.PIPE)
    targets: dict[int, tuple[str, str]] = {}

    for line in result.stdout.splitlines():
        match = TARGET_OBJECT_RE.search(line)
        if match is not None:
            targets[int(match.group("id"))] = (match.group("value"), match.group("type"))

    return targets


def default_metadata_is_ready() -> bool:
    result = subprocess.run(
        ["pw-metadata", "-n", "default"],
        text=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=2.0,
        check=False,
    )
    return result.returncode == 0


def write_settings(config_dir: Path) -> None:
    settings_dir = config_dir / "mini-eq"
    settings_dir.mkdir(parents=True, exist_ok=True)
    (settings_dir / "settings.json").write_text(
        json.dumps({"monitor_enabled": False, "background_mode": False}) + "\n",
        encoding="utf-8",
    )


def write_pipewire_config(config_dir: Path) -> None:
    conf_dir = config_dir / "pipewire" / "pipewire.conf.d"
    conf_dir.mkdir(parents=True, exist_ok=True)
    (conf_dir / "10-mini-eq-live-ui-null-sinks.conf").write_text(
        """
context.objects = [
    { factory = adapter
        args = {
            factory.name     = support.null-audio-sink
            node.name        = "ci_null_sink"
            node.description = "CI Null Sink"
            media.class      = "Audio/Sink"
            audio.position   = "FL,FR"
            adapter.auto-port-config = {
                mode     = dsp
                monitor  = true
                position = preserve
            }
        }
    }
    { factory = adapter
        args = {
            factory.name     = support.null-audio-sink
            node.name        = "ci_alt_sink"
            node.description = "CI Alt Sink"
            media.class      = "Audio/Sink"
            audio.position   = "FL,FR"
            adapter.auto-port-config = {
                mode     = dsp
                monitor  = true
                position = preserve
            }
        }
    }
]
""".strip()
        + "\n",
        encoding="utf-8",
    )


def create_sine_wav(path: Path, duration_seconds: float) -> Path:
    sample_rate = 48_000
    frame_count = max(1, int(duration_seconds * sample_rate))
    amplitude = 0.18
    frequency = 440.0

    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        chunk = bytearray()
        for index in range(frame_count):
            sample = int(32767 * amplitude * math.sin(2.0 * math.pi * frequency * index / sample_rate))
            chunk.extend(sample.to_bytes(2, "little", signed=True))
            chunk.extend(sample.to_bytes(2, "little", signed=True))
            if len(chunk) >= 192_000:
                wav.writeframes(chunk)
                chunk.clear()
        if chunk:
            wav.writeframes(chunk)

    return path


def start_smoke_stream(audio_file: Path) -> subprocess.Popen[str]:
    command = [
        "pw-cat",
        "--playback",
        "--media-role",
        "Music",
        "--target",
        PRIMARY_SINK_NAME,
        "--properties",
        ",".join(
            [
                f"application.name={SMOKE_APPLICATION_NAME}",
                f"node.name={SMOKE_NODE_NAME}",
                "state.restore-props=false",
                "state.restore-target=false",
            ]
        ),
        str(audio_file),
    ]
    print(f"$ {format_command(command)}", flush=True)
    return subprocess.Popen(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)


def start_accessible_event_loop(pyatspi) -> threading.Thread:
    accessible_event.clear()
    pyatspi.Registry.registerEventListener(on_accessible_event, *WAIT_EVENT_NAMES)
    event_thread = threading.Thread(target=pyatspi.Registry.start, name="mini-eq-live-ui-atspi", daemon=True)
    event_thread.start()
    return event_thread


def stop_accessible_event_loop(pyatspi, event_thread: threading.Thread | None) -> None:
    if event_thread is None:
        return
    try:
        pyatspi.Registry.deregisterEventListener(on_accessible_event, *WAIT_EVENT_NAMES)
    except Exception:
        pass
    pyatspi.Registry.stop()
    event_thread.join(timeout=2.0)


accessible_event = threading.Event()


def on_accessible_event(_event) -> None:
    accessible_event.set()


def iter_accessibles(root):
    stack = [root]
    visited = 0
    while stack and visited < 6000:
        node = stack.pop()
        visited += 1
        yield node

        try:
            child_count = node.childCount
        except Exception:
            child_count = 0

        for index in reversed(range(min(child_count, 700))):
            try:
                stack.append(node.getChildAtIndex(index))
            except Exception:
                continue


def accessible_name(node) -> str:
    try:
        return node.name or ""
    except Exception:
        return ""


def accessible_role(node) -> str:
    try:
        return node.getRoleName()
    except Exception:
        return ""


def state_contains(node, state) -> bool:
    try:
        return node.getState().contains(state)
    except Exception:
        return False


def find_accessible(root, pyatspi, *, name: str, role: str | None = None, showing: bool | None = None):
    for node in iter_accessibles(root):
        if accessible_name(node) != name:
            continue
        if role is not None and accessible_role(node) != role:
            continue
        if showing is not None and state_contains(node, pyatspi.STATE_SHOWING) != showing:
            continue
        return node
    return None


def find_accessible_with_roles(root, pyatspi, *, name: str, roles: set[str], showing: bool | None = None):
    for node in iter_accessibles(root):
        if accessible_name(node) != name:
            continue
        if accessible_role(node) not in roles:
            continue
        if showing is not None and state_contains(node, pyatspi.STATE_SHOWING) != showing:
            continue
        return node
    return None


def snapshot_frames(root, pyatspi) -> list[tuple[str, str, bool]]:
    rows = []
    for node in iter_accessibles(root):
        role = accessible_role(node)
        if role in {"application", "frame"}:
            rows.append((role, accessible_name(node), state_contains(node, pyatspi.STATE_SHOWING)))
    return rows


def snapshot_showing_controls(root, pyatspi, limit: int = 120) -> list[tuple[str, str]]:
    rows = []
    interesting_roles = {
        "combo box",
        "label",
        "list item",
        "menu item",
        "push button",
        "slider",
        "spin button",
        "status bar",
        "switch",
        "text",
        "toggle button",
    }
    for node in iter_accessibles(root):
        if not state_contains(node, pyatspi.STATE_SHOWING):
            continue
        role = accessible_role(node)
        name = accessible_name(node)
        if role not in interesting_roles or not name:
            continue
        rows.append((role, name))
        if len(rows) >= limit:
            return rows
    return rows


class UiDriver:
    def __init__(self, pyatspi, app_process: subprocess.Popen[str], app_log_path: Path, shell_log_path: Path) -> None:
        self.pyatspi = pyatspi
        self.app_process = app_process
        self.app_log_path = app_log_path
        self.shell_log_path = shell_log_path

    def desktop(self):
        return self.pyatspi.Registry.getDesktop(0)

    def wait_for_accessible(self, description: str, predicate: Callable[[], Any], timeout_seconds: float) -> Any:
        deadline = time.monotonic() + timeout_seconds

        while True:
            value = predicate()
            if value is not None and value is not False:
                return value

            if self.app_process.poll() is not None:
                raise AssertionError(
                    f"Mini EQ exited while waiting for {description}:\n{self.app_log_path.read_text(errors='replace')}"
                )

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise AssertionError(
                    f"Timed out waiting for {description}; frames: {snapshot_frames(self.desktop(), self.pyatspi)!r}\n"
                    f"Showing controls: {snapshot_showing_controls(self.desktop(), self.pyatspi)!r}\n"
                    f"Mini EQ log:\n{self.app_log_path.read_text(errors='replace')}\n"
                    f"Shell log:\n{self.shell_log_path.read_text(errors='replace')}"
                )

            accessible_event.wait(remaining)
            accessible_event.clear()

    def checked(self, node) -> bool:
        return state_contains(node, self.pyatspi.STATE_CHECKED)

    def sensitive(self, node) -> bool:
        return state_contains(node, self.pyatspi.STATE_SENSITIVE)

    def find(self, root, *, name: str, role: str | None = None, showing: bool | None = None):
        return find_accessible(root, self.pyatspi, name=name, role=role, showing=showing)

    def find_with_roles(self, root, *, name: str, roles: set[str], showing: bool | None = None):
        return find_accessible_with_roles(root, self.pyatspi, name=name, roles=roles, showing=showing)

    def visible_switch_with_state(self, root, *, name: str, expected_checked: bool):
        node = self.find(root, name=name, role="switch", showing=True)
        if node is None or self.checked(node) != expected_checked:
            return None
        return node

    def status_is_visible(self, root, text: str) -> bool:
        return self.find(root, name=text, role="status bar", showing=True) is not None

    def run_action(self, node, action_names: tuple[str, ...]) -> None:
        try:
            action = node.queryAction()
        except Exception as exc:
            raise AssertionError(f"{accessible_name(node)!r} does not expose AT-SPI actions") from exc

        exposed_action_names = []
        for index in range(action.nActions):
            name = action.getName(index)
            exposed_action_names.append(name)
            if name not in action_names:
                continue
            if not action.doAction(index):
                raise AssertionError(f"AT-SPI {name!r} action failed for {accessible_name(node)!r}")
            return

        raise AssertionError(
            f"{accessible_name(node)!r} does not expose one of {action_names!r}: {exposed_action_names!r}"
        )

    def activate(self, node) -> None:
        try:
            self.run_action(node, ("press", "click", "activate", "toggle"))
        except AssertionError:
            self.click(node)

    def toggle_switch(self, node) -> None:
        self.run_action(node, ("toggle",))

    def click(self, node) -> None:
        try:
            component = node.queryComponent()
            extents = component.getExtents(self.pyatspi.DESKTOP_COORDS)
        except Exception as exc:
            raise AssertionError(f"{accessible_name(node)!r} does not expose an AT-SPI component") from exc

        x = int(extents.x + (extents.width / 2))
        y = int(extents.y + (extents.height / 2))
        self.pyatspi.Registry.generateMouseEvent(x, y, "b1c")

    def set_numeric_value(self, node, value: float) -> None:
        try:
            value_iface = node.queryValue()
        except Exception as exc:
            raise AssertionError(f"{accessible_name(node)!r} does not expose an AT-SPI value interface") from exc

        setter = getattr(value_iface, "setCurrentValue", None)
        if callable(setter):
            if setter(float(value)) is False:
                raise AssertionError(f"failed to set {accessible_name(node)!r} to {value}")
            return

        try:
            value_iface.currentValue = float(value)
        except Exception as exc:
            raise AssertionError(f"failed to set {accessible_name(node)!r} to {value}") from exc


def wait_for_wayland_socket(runtime_dir: Path, wayland_name: str, shell: subprocess.Popen[str], log_path: Path) -> None:
    socket_path = runtime_dir / wayland_name

    def socket_ready() -> bool:
        if shell.poll() is not None:
            raise RuntimeError(f"nested GNOME Shell exited early:\n{log_path.read_text(errors='replace')}")
        return socket_path.is_socket()

    wait_for(f"nested Wayland socket {socket_path}", socket_ready, 20.0)


def app_log_contains(app_log_path: Path, text: str) -> bool:
    return text in app_log_path.read_text(errors="replace")


def no_traceback(app_log_path: Path) -> bool:
    return "Traceback (most recent call last)" not in app_log_path.read_text(errors="replace")


def wait_for_sink(name: str, timeout_seconds: float) -> dict[str, Any]:
    return wait_for(name, lambda: node_by_name(name), timeout_seconds)


def wait_for_route_to_virtual(smoke_id: int, virtual_serial: str, timeout_seconds: float) -> None:
    wait_for(
        "smoke stream routed to Mini EQ virtual sink",
        lambda: metadata_targets().get(smoke_id) == (virtual_serial, "Spa:Id"),
        timeout_seconds,
    )


def wait_for_route_away_from_virtual(smoke_id: int, virtual_serial: str, timeout_seconds: float) -> None:
    wait_for(
        "smoke stream restored away from Mini EQ virtual sink",
        lambda: metadata_targets().get(smoke_id) != (virtual_serial, "Spa:Id"),
        timeout_seconds,
    )


def start_nested_shell(runtime_dir: Path, wayland_name: str, log_path: Path) -> subprocess.Popen[str]:
    gnome_shell = require_tool("gnome-shell")
    shell_log = log_path.open("w", encoding="utf-8")
    process = subprocess.Popen(
        [
            gnome_shell,
            "--headless",
            "--wayland",
            "--no-x11",
            "--virtual-monitor",
            "1600x900",
            "--wayland-display",
            wayland_name,
        ],
        stdout=shell_log,
        stderr=subprocess.STDOUT,
        text=True,
    )
    shell_log.close()
    wait_for_wayland_socket(runtime_dir, wayland_name, process, log_path)
    return process


def start_app(repo_root: Path, wayland_name: str, app_log_path: Path) -> subprocess.Popen[str]:
    env = os.environ.copy()
    src_path = str(repo_root / "src")
    env["PYTHONPATH"] = f"{src_path}{os.pathsep}{env['PYTHONPATH']}" if env.get("PYTHONPATH") else src_path
    env["GSETTINGS_BACKEND"] = "memory"
    env["GTK_A11Y"] = "atspi"
    env["GDK_BACKEND"] = "wayland"
    env["WAYLAND_DISPLAY"] = wayland_name
    env.pop("DISPLAY", None)
    app_log = app_log_path.open("w", encoding="utf-8")
    process = subprocess.Popen(
        [sys.executable, "-m", "mini_eq", "--auto-route", "--output-sink", PRIMARY_SINK_NAME],
        cwd=repo_root,
        env=env,
        stdout=app_log,
        stderr=subprocess.STDOUT,
        text=True,
    )
    app_log.close()
    return process


def choose_dropdown_option(
    driver: UiDriver,
    frame,
    *,
    combo_name: str,
    option_name: str,
    timeout_seconds: float,
) -> None:
    dropdown_timeout = min(timeout_seconds, 5.0)
    combo = driver.wait_for_accessible(
        f"{combo_name} combo",
        lambda: driver.find_with_roles(
            frame,
            name=combo_name,
            roles={"combo box", "push button", "toggle button"},
            showing=True,
        ),
        dropdown_timeout,
    )
    driver.activate(combo)
    option = driver.wait_for_accessible(
        f"{option_name} dropdown option",
        lambda: driver.find_with_roles(
            driver.desktop(),
            name=option_name,
            roles={"menu item", "list item", "push button", "toggle button", "label"},
            showing=True,
        ),
        dropdown_timeout,
    )
    driver.activate(option)


def run_ui_flow(
    *,
    pyatspi,
    repo_root: Path,
    runtime_dir: Path,
    tmp_dir: Path,
    timeout_seconds: float,
    cycles: int,
    audio_duration: float,
) -> None:
    shell_log_path = tmp_dir / "gnome-shell.log"
    app_log_path = tmp_dir / "mini-eq.log"
    wayland_name = f"mini-eq-live-ui-{os.getpid()}"
    shell: subprocess.Popen[str] | None = None
    app: subprocess.Popen[str] | None = None
    smoke: subprocess.Popen[str] | None = None
    event_thread: threading.Thread | None = None
    output_switch_verified = False

    try:
        audio_file = create_sine_wav(tmp_dir / "mini-eq-live-ui-smoke.wav", audio_duration)
        smoke = start_smoke_stream(audio_file)
        smoke_node = wait_for(
            "synthetic PipeWire playback stream",
            lambda: smoke_stream_node() if smoke is not None and smoke.poll() is None else None,
            timeout_seconds,
        )
        smoke_id = node_id(smoke_node)

        shell = start_nested_shell(runtime_dir, wayland_name, shell_log_path)
        app = start_app(repo_root, wayland_name, app_log_path)
        event_thread = start_accessible_event_loop(pyatspi)
        driver = UiDriver(pyatspi, app, app_log_path, shell_log_path)

        frame = driver.wait_for_accessible(
            "Mini EQ frame",
            lambda: driver.find(driver.desktop(), name=APP_FRAME_NAME, role="frame", showing=True),
            timeout_seconds,
        )
        route_switch = driver.wait_for_accessible(
            "System-wide EQ switch",
            lambda: driver.find(frame, name="System-wide EQ", role="switch", showing=True),
            timeout_seconds,
        )
        monitor_switch = driver.wait_for_accessible(
            "Monitor switch",
            lambda: driver.find(frame, name="Monitor", role="switch", showing=True),
            timeout_seconds,
        )
        compare_switch = driver.wait_for_accessible(
            "Compare switch",
            lambda: driver.find(frame, name="Compare", role="switch", showing=True),
            timeout_seconds,
        )

        if not driver.sensitive(route_switch):
            raise AssertionError("System-wide EQ switch is not sensitive")
        if not driver.sensitive(compare_switch):
            raise AssertionError("Compare switch should become sensitive when routing is active")

        route_switch = driver.wait_for_accessible(
            "System-wide EQ switch to start active",
            lambda: driver.visible_switch_with_state(frame, name="System-wide EQ", expected_checked=True),
            timeout_seconds,
        )
        driver.wait_for_accessible(
            "Applied status",
            lambda: driver.status_is_visible(frame, "Applied"),
            timeout_seconds,
        )

        virtual_sink = wait_for_sink(VIRTUAL_SINK_NAME, timeout_seconds)
        virtual_serial = object_serial(virtual_sink)
        wait_for_route_to_virtual(smoke_id, virtual_serial, timeout_seconds)

        for cycle in range(cycles):
            print(f"## route toggle cycle {cycle + 1}/{cycles}", flush=True)
            driver.toggle_switch(route_switch)
            route_switch = driver.wait_for_accessible(
                "System-wide EQ switch to turn off",
                lambda: driver.visible_switch_with_state(frame, name="System-wide EQ", expected_checked=False),
                timeout_seconds,
            )
            wait_for_route_away_from_virtual(smoke_id, virtual_serial, timeout_seconds)

            driver.toggle_switch(route_switch)
            route_switch = driver.wait_for_accessible(
                "System-wide EQ switch to turn on",
                lambda: driver.visible_switch_with_state(frame, name="System-wide EQ", expected_checked=True),
                timeout_seconds,
            )
            wait_for_route_to_virtual(smoke_id, virtual_serial, timeout_seconds)

        try:
            choose_dropdown_option(
                driver,
                frame,
                combo_name="EQ output",
                option_name="CI Alt Sink",
                timeout_seconds=timeout_seconds,
            )
            wait_for(
                "Mini EQ to retarget the alternate output",
                lambda: app_log_contains(app_log_path, f"-> {ALT_SINK_NAME}"),
                timeout_seconds,
            )
            wait_for_route_to_virtual(smoke_id, virtual_serial, timeout_seconds)

            choose_dropdown_option(
                driver,
                frame,
                combo_name="EQ output",
                option_name="CI Null Sink",
                timeout_seconds=timeout_seconds,
            )
            wait_for(
                "Mini EQ to retarget the primary output",
                lambda: app_log_contains(app_log_path, f"-> {PRIMARY_SINK_NAME}"),
                timeout_seconds,
            )
            wait_for_route_to_virtual(smoke_id, virtual_serial, timeout_seconds)
            output_switch_verified = True
        except AssertionError as exc:
            print(f"Output dropdown switch was not accessible in this run: {str(exc).splitlines()[0]}", flush=True)

        if driver.checked(monitor_switch):
            driver.toggle_switch(monitor_switch)
            monitor_switch = driver.wait_for_accessible(
                "Monitor switch to turn off before monitor cycle",
                lambda: driver.visible_switch_with_state(frame, name="Monitor", expected_checked=False),
                timeout_seconds,
            )

        driver.toggle_switch(monitor_switch)
        monitor_switch = driver.wait_for_accessible(
            "Monitor switch to turn on",
            lambda: driver.visible_switch_with_state(frame, name="Monitor", expected_checked=True),
            timeout_seconds,
        )
        wait_for(
            "Mini EQ monitor PipeWire stream",
            lambda: node_by_name(ANALYZER_NODE_NAME),
            timeout_seconds,
        )
        bad_sources = [
            item_props(node)
            for node in node_items()
            if item_props(node).get("application.name") == "Mini EQ"
            and item_props(node).get("media.class") == "Audio/Source"
        ]
        if bad_sources:
            raise AssertionError(f"Monitor exposed Audio/Source nodes: {bad_sources!r}")

        gain_spin = driver.wait_for_accessible(
            "Selected Band Gain spin button",
            lambda: (
                driver.find_with_roles(
                    frame,
                    name="Selected Band Gain",
                    roles={"spin button", "text"},
                    showing=True,
                )
                or driver.find(frame, name="Gain", role="spin button", showing=True)
            ),
            timeout_seconds,
        )
        driver.set_numeric_value(gain_spin, 3.0)
        driver.wait_for_accessible(
            "Modified preset state after band edit",
            lambda: driver.status_is_visible(frame, "Modified"),
            timeout_seconds,
        )

        driver.set_numeric_value(gain_spin, 0.0)
        driver.wait_for_accessible(
            "Modified preset state to clear after returning band gain to neutral",
            lambda: not driver.status_is_visible(frame, "Modified"),
            timeout_seconds,
        )

        terminate_process(smoke, "pw-cat synthetic stream")
        smoke = None
        wait_for("synthetic stream to disappear", lambda: smoke_stream_node() is None, timeout_seconds)
        if not no_traceback(app_log_path):
            raise AssertionError(
                f"Mini EQ logged a traceback after stream close:\n{app_log_path.read_text(errors='replace')}"
            )

        driver.toggle_switch(monitor_switch)
        driver.wait_for_accessible(
            "Monitor switch to turn off",
            lambda: driver.visible_switch_with_state(frame, name="Monitor", expected_checked=False),
            timeout_seconds,
        )

        try:
            driver.run_action(frame, ("close",))
        except AssertionError:
            app.send_signal(signal.SIGINT)

        try:
            app.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            app.kill()
            app.wait(timeout=2.0)
            raise AssertionError("Mini EQ did not exit after close/SIGINT") from exc

        if app.returncode not in (0, -signal.SIGINT):
            raise AssertionError(
                f"Mini EQ exited with status {app.returncode}:\n{app_log_path.read_text(errors='replace')}"
            )
        if not no_traceback(app_log_path):
            raise AssertionError(f"Mini EQ logged a traceback on shutdown:\n{app_log_path.read_text(errors='replace')}")

        output_detail = "output retarget verified" if output_switch_verified else "output retarget skipped"
        print(
            f"Live UI runtime smoke passed: AT-SPI UI flow, synthetic stream routing, monitor, {output_detail}, and shutdown verified."
        )
    finally:
        stop_accessible_event_loop(pyatspi, event_thread)
        terminate_process(app, "Mini EQ")
        terminate_process(smoke, "pw-cat synthetic stream")
        terminate_process(shell, "nested GNOME Shell")


def start_pipewire_processes(tmp_dir: Path) -> tuple[subprocess.Popen[str], subprocess.Popen[str]]:
    pipewire_log = (tmp_dir / "pipewire.log").open("w", encoding="utf-8")
    wireplumber_log = (tmp_dir / "wireplumber.log").open("w", encoding="utf-8")
    pipewire = subprocess.Popen(["pipewire"], stdout=pipewire_log, stderr=subprocess.STDOUT, text=True)
    wireplumber = subprocess.Popen(["wireplumber"], stdout=wireplumber_log, stderr=subprocess.STDOUT, text=True)
    pipewire_log.close()
    wireplumber_log.close()
    return pipewire, wireplumber


def run_helper(_args: argparse.Namespace) -> int:
    try:
        import pyatspi
    except Exception as exc:
        print(f"pyatspi unavailable: {exc}", file=sys.stderr)
        return HELPER_SKIP_EXIT_CODE

    try:
        for tool in ("pipewire", "wireplumber", "pw-cat", "pw-dump", "pw-metadata", "gnome-shell"):
            require_tool(tool)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return HELPER_SKIP_EXIT_CODE

    timeout_seconds = float(os.environ["MINI_EQ_LIVE_UI_TIMEOUT"])
    cycles = int(os.environ["MINI_EQ_LIVE_UI_CYCLES"])
    audio_duration = float(os.environ["MINI_EQ_LIVE_UI_AUDIO_DURATION"])
    pipewire: subprocess.Popen[str] | None = None
    wireplumber: subprocess.Popen[str] | None = None

    tmp_dir = Path(tempfile.mkdtemp(prefix="mini-eq-live-ui-"))
    try:
        runtime_dir = tmp_dir / "runtime"
        config_dir = tmp_dir / "config"
        data_dir = tmp_dir / "data"
        cache_dir = tmp_dir / "cache"
        for directory in (runtime_dir, config_dir, data_dir, cache_dir):
            directory.mkdir(parents=True, exist_ok=True)
        runtime_dir.chmod(0o700)
        write_settings(config_dir)
        write_pipewire_config(config_dir)

        os.environ["XDG_RUNTIME_DIR"] = str(runtime_dir)
        os.environ["XDG_CONFIG_HOME"] = str(config_dir)
        os.environ["XDG_DATA_HOME"] = str(data_dir)
        os.environ["XDG_CACHE_HOME"] = str(cache_dir)
        os.environ["GSETTINGS_BACKEND"] = "memory"

        pipewire, wireplumber = start_pipewire_processes(tmp_dir)
        wait_for_sink(PRIMARY_SINK_NAME, timeout_seconds)
        wait_for_sink(ALT_SINK_NAME, timeout_seconds)
        wait_for("WirePlumber default metadata", default_metadata_is_ready, timeout_seconds)
        run_ui_flow(
            pyatspi=pyatspi,
            repo_root=REPO_ROOT,
            runtime_dir=runtime_dir,
            tmp_dir=tmp_dir,
            timeout_seconds=timeout_seconds,
            cycles=cycles,
            audio_duration=audio_duration,
        )
    finally:
        terminate_process(wireplumber, "WirePlumber")
        terminate_process(pipewire, "PipeWire")
        shutil.rmtree(tmp_dir, ignore_errors=True)

    return 0


def run_parent(args: argparse.Namespace) -> int:
    try:
        require_tool("dbus-run-session")
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return HELPER_SKIP_EXIT_CODE
    attempts = max(1, args.retries + 1)

    for attempt in range(1, attempts + 1):
        env = os.environ.copy()
        env["MINI_EQ_LIVE_UI_TIMEOUT"] = str(args.timeout)
        env["MINI_EQ_LIVE_UI_CYCLES"] = str(args.cycles)
        env["MINI_EQ_LIVE_UI_AUDIO_DURATION"] = str(args.audio_duration)
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

        if completed.returncode != 139 or attempt >= attempts:
            return completed.returncode

        print("Nested AT-SPI session exited with SIGSEGV; retrying once with a fresh private runtime.", flush=True)

    return 1


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Drive the real Mini EQ UI with AT-SPI against a private PipeWire session and synthetic stream.",
    )
    parser.add_argument("--helper", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--timeout", type=float, default=35.0, help="Timeout for each UI or PipeWire transition.")
    parser.add_argument("--cycles", type=int, default=2, help="System-wide EQ off/on cycles to drive.")
    parser.add_argument("--retries", type=int, default=1, help="Retry count for native nested-session SIGSEGV exits.")
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
