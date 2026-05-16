from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

if os.environ.get("MINI_EQ_RUN_ATSPI") != "1":
    pytestmark = pytest.mark.skip(reason="set MINI_EQ_RUN_ATSPI=1 to run nested AT-SPI widget checks")

HELPER_SKIP_EXIT_CODE = 77
NESTED_SESSION_SIGSEGV_EXIT_CODE = 139
NESTED_SESSION_RETRIES = 1

NESTED_ATSPI_HELPER = r"""
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

try:
    import pyatspi
except Exception as exc:
    print(f"pyatspi unavailable: {exc}")
    raise SystemExit(77)

APP_FRAME_NAME = "Mini EQ"
WAIT_TIMEOUT_SECONDS = 20.0
SOCKET_POLL_INTERVAL_SECONDS = 0.1
WAIT_EVENT_NAMES = (
    "window",
    "object:children-changed",
    "object:property-change",
    "object:state-changed",
)

repo_root = Path(os.environ["MINI_EQ_TEST_REPO_ROOT"])
config_dir = Path(sys.argv[1])
runtime_dir = Path(os.environ["XDG_RUNTIME_DIR"])
wayland_name = sys.argv[2]
shell_log_path = Path(sys.argv[3])
app_log_path = Path(sys.argv[4])


def require_tool(name):
    path = shutil.which(name)
    if path is None:
        print(f"{name} unavailable")
        raise SystemExit(77)
    return path


def terminate_process(process):
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5.0)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=2.0)


def wait_for_wayland_socket(shell_process):
    socket_path = runtime_dir / wayland_name
    deadline = time.monotonic() + WAIT_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if socket_path.is_socket():
            return
        if shell_process.poll() is not None:
            raise AssertionError(f"nested GNOME Shell exited early:\n{shell_log_path.read_text(errors='replace')}")
        time.sleep(SOCKET_POLL_INTERVAL_SECONDS)
    raise AssertionError(f"nested GNOME Shell did not create {socket_path}:\n{shell_log_path.read_text(errors='replace')}")


def iter_accessibles(root):
    stack = [root]
    visited = 0
    while stack and visited < 5000:
        node = stack.pop()
        visited += 1
        yield node

        try:
            child_count = node.childCount
        except Exception:
            child_count = 0

        for index in reversed(range(min(child_count, 600))):
            try:
                stack.append(node.getChildAtIndex(index))
            except Exception:
                continue


def accessible_name(node):
    try:
        return node.name or ""
    except Exception:
        return ""


def accessible_role(node):
    try:
        return node.getRoleName()
    except Exception:
        return ""


def state_contains(node, state):
    try:
        return node.getState().contains(state)
    except Exception:
        return False


def find_accessible(root, *, name, role=None, showing=None):
    for node in iter_accessibles(root):
        if accessible_name(node) != name:
            continue
        if role is not None and accessible_role(node) != role:
            continue
        if showing is not None and state_contains(node, pyatspi.STATE_SHOWING) != showing:
            continue
        return node
    return None


def find_accessible_with_roles(root, *, name, roles, showing=None):
    for node in iter_accessibles(root):
        if accessible_name(node) != name:
            continue
        if accessible_role(node) not in roles:
            continue
        if showing is not None and state_contains(node, pyatspi.STATE_SHOWING) != showing:
            continue
        return node
    return None


def has_descendant_name(root, name):
    for node in iter_accessibles(root):
        if node is root:
            continue
        if accessible_name(node) == name:
            return True
    return False


def find_list_item_with_descendant(root, *, descendant_name, showing=None):
    for node in iter_accessibles(root):
        if accessible_role(node) != "list item":
            continue
        if showing is not None and state_contains(node, pyatspi.STATE_SHOWING) != showing:
            continue
        if has_descendant_name(node, descendant_name):
            return node
    return None


def snapshot_frames(root):
    rows = []
    for node in iter_accessibles(root):
        role = accessible_role(node)
        if role in {"application", "frame"}:
            rows.append((role, accessible_name(node), state_contains(node, pyatspi.STATE_SHOWING)))
    return rows


def snapshot_showing_controls(root, limit=120):
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


ACCESSIBLE_EVENT = threading.Event()


def on_accessible_event(_event):
    ACCESSIBLE_EVENT.set()


def start_accessible_event_loop():
    pyatspi.Registry.registerEventListener(on_accessible_event, *WAIT_EVENT_NAMES)
    event_thread = threading.Thread(target=pyatspi.Registry.start, name="mini-eq-atspi-events", daemon=True)
    event_thread.start()
    return event_thread


def stop_accessible_event_loop(event_thread):
    try:
        pyatspi.Registry.deregisterEventListener(on_accessible_event, *WAIT_EVENT_NAMES)
    except Exception:
        pass
    pyatspi.Registry.stop()
    event_thread.join(timeout=2.0)


def wait_for(description, predicate, timeout_seconds=WAIT_TIMEOUT_SECONDS):
    deadline = time.monotonic() + timeout_seconds

    def timeout_error():
        desktop = pyatspi.Registry.getDesktop(0)
        return AssertionError(
            f"Timed out waiting for {description}; frames: {snapshot_frames(desktop)!r}\n"
            f"Showing controls: {snapshot_showing_controls(desktop)!r}\n"
            f"Mini EQ log:\n{app_log_path.read_text(errors='replace')}\n"
            f"Shell log:\n{shell_log_path.read_text(errors='replace')}"
        )

    while True:
        value = predicate()
        if value is not None and value is not False:
            return value

        if app_process is not None and app_process.poll() is not None:
            raise AssertionError(
                f"Mini EQ exited while waiting for {description}:\n{app_log_path.read_text(errors='replace')}"
            )

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise timeout_error()

        ACCESSIBLE_EVENT.wait(remaining)
        ACCESSIBLE_EVENT.clear()


def checked(node):
    return state_contains(node, pyatspi.STATE_CHECKED)


def sensitive(node):
    return state_contains(node, pyatspi.STATE_SENSITIVE)


def expanded(node):
    return state_contains(node, pyatspi.STATE_EXPANDED)


def visible_switch_with_state(root, *, name, expected_checked):
    node = find_accessible(root, name=name, role="switch", showing=True)
    if node is None or checked(node) != expected_checked:
        return None
    return node


def monitor_is_enabled(frame):
    node = visible_switch_with_state(frame, name="Monitor", expected_checked=True)
    if node is None:
        return None
    if find_accessible(frame, name="--", role="status bar", showing=True) is None:
        return None
    return node


def run_accessible_action(node, action_names):
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


def activate_control(node):
    run_accessible_action(node, ("press", "click", "activate", "toggle"))


def toggle_switch(node):
    run_accessible_action(node, ("toggle",))


def verify_dropdown_exposes_options(frame, *, combo_name, required_options):
    dropdown_timeout = 2.0
    combo = wait_for(
        f"{combo_name} combo box",
        lambda: find_accessible(frame, name=combo_name, role="combo box", showing=True),
    )
    if not sensitive(combo):
        raise AssertionError(f"{combo_name} combo box should be sensitive")

    toggle = wait_for(
        f"{combo_name} dropdown toggle",
        lambda: find_accessible(frame, name=combo_name, role="toggle button", showing=True),
    )
    if not sensitive(toggle):
        raise AssertionError(f"{combo_name} dropdown toggle should be sensitive")

    activate_control(toggle)
    wait_for(
        f"{combo_name} combo box to expand",
        lambda: expanded(combo),
        dropdown_timeout,
    )
    try:
        for option_name in required_options:
            wait_for(
                f"{option_name} dropdown list item",
                lambda option_name=option_name: find_list_item_with_descendant(
                    pyatspi.Registry.getDesktop(0),
                    descendant_name=option_name,
                    showing=True,
                ),
                dropdown_timeout,
            )
    finally:
        activate_control(toggle)

    wait_for(
        f"{combo_name} combo box to collapse",
        lambda: not expanded(combo),
        dropdown_timeout,
    )


gnome_shell = require_tool("gnome-shell")
shell_log = shell_log_path.open("w", encoding="utf-8")
app_log = app_log_path.open("w", encoding="utf-8")
shell_process = None
app_process = None
atspi_event_thread = None

try:
    shell_process = subprocess.Popen(
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
    wait_for_wayland_socket(shell_process)

    app_env = os.environ.copy()
    src_path = str(repo_root / "src")
    app_env["PYTHONPATH"] = f"{src_path}{os.pathsep}{app_env['PYTHONPATH']}" if app_env.get("PYTHONPATH") else src_path
    app_env["XDG_CONFIG_HOME"] = str(config_dir)
    app_env["GSETTINGS_BACKEND"] = "memory"
    app_env["GTK_A11Y"] = "atspi"
    app_env["GDK_BACKEND"] = "wayland"
    app_env["WAYLAND_DISPLAY"] = wayland_name
    app_env.pop("DISPLAY", None)

    module_flag = "-" + "m"
    module_name = "mini" + "_eq"
    app_process = subprocess.Popen(
        [sys.executable, module_flag, module_name],
        cwd=repo_root,
        env=app_env,
        stdout=app_log,
        stderr=subprocess.STDOUT,
        text=True,
    )
    atspi_event_thread = start_accessible_event_loop()

    frame = wait_for(
        "Mini EQ frame",
        lambda: find_accessible(
            pyatspi.Registry.getDesktop(0),
            name=APP_FRAME_NAME,
            role="frame",
            showing=True,
        ),
    )
    desktop = pyatspi.Registry.getDesktop(0)
    route_switch = wait_for(
        "System-wide EQ switch",
        lambda: find_accessible(frame, name="System-wide EQ", role="switch", showing=True),
    )
    compare_switch = wait_for(
        "A/B compare switch",
        lambda: find_accessible(frame, name="A/B", role="switch", showing=True),
    )
    monitor_switch = wait_for(
        "Monitor switch",
        lambda: find_accessible(frame, name="Monitor", role="switch", showing=True),
    )

    if not sensitive(route_switch):
        raise AssertionError("System-wide EQ switch is not sensitive")
    if checked(route_switch):
        raise AssertionError("System-wide EQ switch unexpectedly starts checked")
    if sensitive(compare_switch):
        raise AssertionError("Compare switch should be insensitive while system routing is off")
    if checked(monitor_switch):
        raise AssertionError("Monitor switch should start unchecked from the temporary test config")
    if find_accessible(frame, name="Not Applied", role="status bar", showing=True) is None:
        raise AssertionError("Not Applied status is missing")
    if find_accessible(frame, name="Off", role="status bar", showing=True) is None:
        raise AssertionError("Monitor Off status is missing")
    if find_accessible(frame, name="EQ output", role="combo box", showing=True) is None:
        raise AssertionError("EQ output combo box is missing")
    if (
        find_accessible_with_roles(
            frame,
            name="Load Preset",
            roles={"push button", "toggle button"},
            showing=True,
        )
        is None
    ):
        raise AssertionError("Load Preset menu button is missing")

    verify_dropdown_exposes_options(frame, combo_name="Type", required_options=("Notch", "Bell"))

    toggle_switch(monitor_switch)
    wait_for(
        "Monitor switch to turn on",
        lambda: monitor_is_enabled(frame),
    )

    settings_button = wait_for(
        "Monitor Settings button",
        lambda: find_accessible_with_roles(
            frame,
            name="Monitor Settings",
            roles={"toggle button"},
            showing=True,
        ),
    )
    activate_control(settings_button)
    freeze_switch = wait_for(
        "Freeze Monitor switch",
        lambda: find_accessible(desktop, name="Freeze Monitor", role="switch", showing=True),
    )
    if not sensitive(freeze_switch):
        raise AssertionError("Freeze Monitor switch should be sensitive while Monitor is on")
    if checked(freeze_switch):
        raise AssertionError("Freeze Monitor switch should start unchecked")
    if find_accessible(desktop, name="Monitor Smoothing", role="slider", showing=True) is None:
        raise AssertionError("Monitor Smoothing slider is missing from Monitor Settings")
    if find_accessible(desktop, name="Monitor Display Gain", role="slider", showing=True) is None:
        raise AssertionError("Monitor Display Gain slider is missing from Monitor Settings")

    toggle_switch(freeze_switch)
    wait_for(
        "Freeze Monitor switch to turn on",
        lambda: visible_switch_with_state(
            pyatspi.Registry.getDesktop(0),
            name="Freeze Monitor",
            expected_checked=True,
        ),
    )

    freeze_switch = wait_for(
        "Freeze Monitor switch after turning on",
        lambda: find_accessible(desktop, name="Freeze Monitor", role="switch", showing=True),
    )
    toggle_switch(freeze_switch)
    wait_for(
        "Freeze Monitor switch to turn off",
        lambda: visible_switch_with_state(
            pyatspi.Registry.getDesktop(0),
            name="Freeze Monitor",
            expected_checked=False,
        ),
    )

    monitor_switch = wait_for(
        "Monitor switch after turning on",
        lambda: find_accessible(frame, name="Monitor", role="switch", showing=True),
    )
    toggle_switch(monitor_switch)
    wait_for(
        "Monitor switch to turn off",
        lambda: (
            visible_switch_with_state(frame, name="Monitor", expected_checked=False)
            if find_accessible(frame, name="Off", role="status bar", showing=True) is not None
            else None
        ),
    )
    freeze_switch = wait_for(
        "Freeze Monitor switch after Monitor turns off",
        lambda: find_accessible(desktop, name="Freeze Monitor", role="switch", showing=True),
    )
    if sensitive(freeze_switch):
        raise AssertionError("Freeze Monitor switch should be insensitive while Monitor is off")
    if checked(freeze_switch):
        raise AssertionError("Freeze Monitor switch should clear when Monitor turns off")
finally:
    if atspi_event_thread is not None:
        stop_accessible_event_loop(atspi_event_thread)
    if app_process is not None:
        terminate_process(app_process)
    if shell_process is not None:
        terminate_process(shell_process)
    shell_log.close()
    app_log.close()
"""


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def write_test_settings(config_dir: Path) -> None:
    settings_dir = config_dir / "mini-eq"
    settings_dir.mkdir(parents=True)
    (settings_dir / "settings.json").write_text(
        json.dumps({"monitor_enabled": False, "background_mode": False}) + "\n",
        encoding="utf-8",
    )


def run_nested_atspi_helper(tmp_path: Path, attempt: int) -> subprocess.CompletedProcess[str]:
    if not shutil.which("dbus-run-session"):
        pytest.skip("dbus-run-session is unavailable")

    attempt_dir = tmp_path / f"attempt-{attempt}"
    config_dir = attempt_dir / "config"
    data_dir = attempt_dir / "data"
    cache_dir = attempt_dir / "cache"
    attempt_dir.mkdir()
    config_dir.mkdir()
    data_dir.mkdir()
    cache_dir.mkdir()
    write_test_settings(config_dir)

    env = os.environ.copy()
    env["XDG_CONFIG_HOME"] = str(config_dir)
    env["XDG_DATA_HOME"] = str(data_dir)
    env["XDG_CACHE_HOME"] = str(cache_dir)
    env["GSETTINGS_BACKEND"] = "memory"
    env["MINI_EQ_TEST_REPO_ROOT"] = str(repo_root())
    env.pop("WAYLAND_DISPLAY", None)
    env.pop("DISPLAY", None)

    return subprocess.run(
        [
            "dbus-run-session",
            "--",
            sys.executable,
            "-c",
            NESTED_ATSPI_HELPER,
            str(config_dir),
            f"mini-eq-atspi-{os.getpid()}-{attempt}",
            str(attempt_dir / "gnome-shell.log"),
            str(attempt_dir / "mini-eq.log"),
        ],
        cwd=repo_root(),
        env=env,
        capture_output=True,
        text=True,
        timeout=60.0,
        check=False,
    )


def test_real_app_widgets_expose_and_update_accessible_state(tmp_path: Path) -> None:
    attempts = NESTED_SESSION_RETRIES + 1
    for attempt in range(1, attempts + 1):
        result = run_nested_atspi_helper(tmp_path, attempt)
        if result.returncode == HELPER_SKIP_EXIT_CODE:
            pytest.skip(result.stdout.strip())
        if result.returncode != NESTED_SESSION_SIGSEGV_EXIT_CODE or attempt >= attempts:
            assert result.returncode == 0, result.stdout + result.stderr
            return
