from __future__ import annotations

import importlib
import os
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

Status = Literal["ok", "missing", "warning"]

PYGOBJECT_HINT = "Ubuntu/Debian: python3-gi; Fedora: python3-gobject; Arch: python-gobject"
PYCAIRO_HINT = "Ubuntu/Debian: python3-cairo; Fedora: python3-cairo; Arch: python-cairo"
GTK_HINT = "Ubuntu/Debian: gir1.2-gtk-4.0; Fedora: gtk4; Arch: gtk4. Requires GTK 4.12+."
ADW_HINT = "Ubuntu/Debian: gir1.2-adw-1; Fedora: libadwaita; Arch: libadwaita. Requires Libadwaita 1.7+."
WIREPLUMBER_GI_VERSIONS = ("0.5", "0.4")

WP_HINT = "Ubuntu 24.04: gir1.2-wp-0.4 wireplumber; newer Debian/Ubuntu: gir1.2-wp-0.5 wireplumber; Fedora: wireplumber wireplumber-libs; Arch: wireplumber libwireplumber"
PIPEWIRE_HINT = (
    "Ubuntu/Debian: pipewire pipewire-bin wireplumber; Fedora: pipewire wireplumber; Arch: pipewire wireplumber"
)
PIPEWIRE_FILTER_CHAIN_HINT = (
    "Ubuntu/Debian: pipewire; Fedora: pipewire; Arch: pipewire. "
    "Flatpak builds bundle only the filter-chain module and SPA builtin filter support."
)
JACK_HINT = (
    "Install the Python JACK client and PipeWire JACK support. "
    "For pip environments: python -m pip install JACK-Client; system packages must provide libjack."
)
NUMPY_HINT = (
    "Install the package with Python dependencies: python -m pip install mini-eq, or python -m pip install numpy."
)


@dataclass(frozen=True)
class DependencyCheck:
    name: str
    status: Status
    required: bool
    detail: str
    hint: str = ""

    @property
    def ok(self) -> bool:
        return self.status == "ok"


def check_python_version() -> DependencyCheck:
    required_version = (3, 11)
    current = sys.version_info[:3]
    ok = current >= required_version
    version = ".".join(str(part) for part in current)
    return DependencyCheck(
        name="Python 3.11+",
        status="ok" if ok else "missing",
        required=True,
        detail=f"running Python {version}",
        hint="Install Python 3.11 or newer.",
    )


def check_python_import(module_name: str, label: str, required: bool, hint: str) -> DependencyCheck:
    try:
        module = importlib.import_module(module_name)
    except Exception as exc:
        return DependencyCheck(label, "missing", required, str(exc), hint)

    module_file = getattr(module, "__file__", None)
    detail = f"imported from {module_file}" if module_file else "imported"
    return DependencyCheck(label, "ok", required, detail, hint)


def check_gi_repository(namespace: str, version: str, label: str, required: bool, hint: str) -> DependencyCheck:
    try:
        import gi

        gi.require_version(namespace, version)
        module = importlib.import_module(f"gi.repository.{namespace}")
    except Exception as exc:
        return DependencyCheck(label, "missing", required, str(exc), hint)

    actual_version = getattr(module, "_version", version)
    return DependencyCheck(label, "ok", required, f"GI namespace {namespace} {actual_version}", hint)


def check_gi_repository_attribute(
    namespace: str,
    version: str,
    attribute_name: str,
    label: str,
    required: bool,
    hint: str,
) -> DependencyCheck:
    namespace_check = check_gi_repository(namespace, version, label, required, hint)
    if not namespace_check.ok:
        return namespace_check

    module = importlib.import_module(f"gi.repository.{namespace}")
    current = module
    checked_path = namespace
    for path_part in attribute_name.split("."):
        checked_path = f"{checked_path}.{path_part}"
        if not hasattr(current, path_part):
            return DependencyCheck(
                label,
                "missing",
                required,
                f"GI namespace lacks {checked_path}",
                hint,
            )
        current = getattr(current, path_part)

    return DependencyCheck(label, "ok", required, f"{checked_path} is available", hint)


def check_first_available_gi_repository(
    namespace: str,
    versions: tuple[str, ...],
    label: str,
    required: bool,
    hint: str,
) -> DependencyCheck:
    failures: list[str] = []

    for version in versions:
        check = check_gi_repository(namespace, version, label, required, hint)
        if check.ok:
            return check
        failures.append(f"{namespace} {version}: {check.detail}")

    return DependencyCheck(label, "missing", required, "; ".join(failures), hint)


def split_env_paths(value: str | None) -> list[Path]:
    if not value:
        return []

    return [Path(path).expanduser() for path in value.split(os.pathsep) if path]


def pipewire_module_search_paths() -> list[Path]:
    paths = split_env_paths(os.environ.get("PIPEWIRE_MODULE_DIR"))
    paths.extend(
        [
            Path("/app/lib/pipewire-0.3"),
            Path("/usr/lib/pipewire-0.3"),
            Path("/usr/lib64/pipewire-0.3"),
            Path("/usr/lib/x86_64-linux-gnu/pipewire-0.3"),
        ]
    )
    return dedupe_existing_paths(paths)


def spa_plugin_search_paths() -> list[Path]:
    paths = split_env_paths(os.environ.get("SPA_PLUGIN_DIR"))
    paths.extend(
        [
            Path("/app/lib/spa-0.2"),
            Path("/usr/lib/spa-0.2"),
            Path("/usr/lib64/spa-0.2"),
            Path("/usr/lib/x86_64-linux-gnu/spa-0.2"),
        ]
    )
    return dedupe_existing_paths(paths)


def dedupe_existing_paths(paths: list[Path]) -> list[Path]:
    seen: set[str] = set()
    result: list[Path] = []

    for path in paths:
        key = str(path)
        if key in seen or not path.exists():
            continue
        seen.add(key)
        result.append(path)

    return result


def check_pipewire_module(filename: str, label: str, required: bool, hint: str) -> DependencyCheck:
    searched = pipewire_module_search_paths()

    for base_path in searched:
        module_path = base_path / filename
        if module_path.exists():
            return DependencyCheck(label, "ok", required, f"module found at {module_path}", hint)

    detail = "searched: " + ", ".join(str(path) for path in searched) if searched else "no module paths exist"
    return DependencyCheck(label, "missing", required, detail, hint)


def check_spa_plugin(relative_path: str, label: str, required: bool, hint: str) -> DependencyCheck:
    searched = spa_plugin_search_paths()

    for base_path in searched:
        plugin_path = base_path / relative_path
        if plugin_path.exists():
            return DependencyCheck(label, "ok", required, f"SPA plugin found at {plugin_path}", hint)

    detail = "searched: " + ", ".join(str(path) for path in searched) if searched else "no SPA plugin paths exist"
    return DependencyCheck(label, "missing", required, detail, hint)


def check_wireplumber_session() -> DependencyCheck:
    command_check = check_command("wpctl", ["status"], "WirePlumber session", True, PIPEWIRE_HINT)
    if command_check.ok:
        return command_check

    try:
        from .wireplumber_backend import WirePlumberBackend

        with WirePlumberBackend(timeout_ms=1000):
            pass
    except Exception as exc:
        detail = f"{command_check.detail}; WirePlumber GI connection failed: {exc}"
        return DependencyCheck("WirePlumber session", "missing", True, detail, PIPEWIRE_HINT)

    return DependencyCheck(
        "WirePlumber session",
        "ok",
        True,
        "connected to PipeWire through WirePlumber GI",
        PIPEWIRE_HINT,
    )


def check_command(
    command: str,
    args: list[str],
    label: str,
    required: bool,
    hint: str,
    *,
    timeout_seconds: float = 2.0,
) -> DependencyCheck:
    executable = shutil.which(command)
    if executable is None:
        return DependencyCheck(label, "missing", required, f"{command} is not on PATH", hint)

    try:
        completed = subprocess.run(
            [executable, *args],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout_seconds,
        )
    except Exception as exc:
        return DependencyCheck(label, "warning", required, str(exc), hint)

    if completed.returncode == 0:
        return DependencyCheck(label, "ok", required, f"{command} is available and responsive", hint)

    detail = (
        completed.stderr.strip().splitlines()[0] if completed.stderr.strip() else f"exit code {completed.returncode}"
    )
    return DependencyCheck(label, "warning", required, detail, hint)


def collect_dependency_checks() -> list[DependencyCheck]:
    checks = [
        check_python_version(),
        check_python_import("gi", "PyGObject", True, PYGOBJECT_HINT),
        check_python_import("cairo", "pycairo", True, PYCAIRO_HINT),
        check_gi_repository_attribute("Gtk", "4.0", "Button.set_can_shrink", "GTK 4.12+ GI namespace", True, GTK_HINT),
        check_gi_repository("Gdk", "4.0", "GDK 4 GI namespace", True, GTK_HINT),
        check_gi_repository("Gsk", "4.0", "GSK 4 GI namespace", True, GTK_HINT),
        check_gi_repository("Graphene", "1.0", "Graphene GI namespace", True, GTK_HINT),
        check_gi_repository_attribute("Adw", "1", "WrapBox", "Libadwaita 1.7+ GI namespace", True, ADW_HINT),
        check_first_available_gi_repository("Wp", WIREPLUMBER_GI_VERSIONS, "WirePlumber GI namespace", True, WP_HINT),
        check_wireplumber_session(),
        check_pipewire_module(
            "libpipewire-module-filter-chain.so",
            "PipeWire filter-chain module",
            True,
            PIPEWIRE_FILTER_CHAIN_HINT,
        ),
        check_spa_plugin(
            "filter-graph/libspa-filter-graph-plugin-builtin.so",
            "PipeWire SPA builtin filter graph plugin",
            True,
            PIPEWIRE_FILTER_CHAIN_HINT,
        ),
        check_python_import("numpy", "NumPy FFT analyzer", False, NUMPY_HINT),
        check_python_import("jack", "Python JACK analyzer client", False, JACK_HINT),
    ]

    if platform.system() != "Linux":
        checks.append(
            DependencyCheck(
                "Linux desktop runtime",
                "warning",
                True,
                f"current platform is {platform.system()}",
                "Mini EQ targets Linux PipeWire desktops.",
            )
        )

    return checks


def dependency_exit_code(checks: list[DependencyCheck]) -> int:
    return 1 if any(check.required and not check.ok for check in checks) else 0


def status_marker(check: DependencyCheck) -> str:
    if check.status == "ok":
        return "OK"
    if check.status == "warning":
        return "WARN"
    return "MISSING"


def format_dependency_report(checks: list[DependencyCheck]) -> str:
    lines = ["Mini EQ dependency check", ""]

    for required, title in ((True, "Required"), (False, "Optional features")):
        group = [check for check in checks if check.required is required]
        if not group:
            continue

        lines.append(f"{title}:")
        for check in group:
            lines.append(f"  [{status_marker(check)}] {check.name}: {check.detail}")
            if not check.ok and check.hint:
                lines.append(f"      install hint: {check.hint}")
        lines.append("")

    exit_code = dependency_exit_code(checks)
    if exit_code == 0:
        lines.append("All required dependencies are available.")
    else:
        lines.append("One or more required dependencies are missing or not reachable.")

    return "\n".join(lines)


def main() -> int:
    checks = collect_dependency_checks()
    print(format_dependency_report(checks))
    return dependency_exit_code(checks)
