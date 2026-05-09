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

PWG_REQUIRED_VERSION = "0.3.5"
PWG_REQUIRED_VERSION_PARTS = (0, 3, 5)
PWG_REQUIRED_SYMBOLS = (
    "Core.set_pipewire_property",
    "Device.enum_all_params",
    "Device.enum_params",
    "Device.new",
    "Device.subscribe_params",
    "Param.new_props_controls",
    "RouteInfo.new_from_param",
    "Stream.set_pipewire_property",
)
PYGOBJECT_HINT = "Ubuntu/Debian: python3-gi; Fedora: python3-gobject; Arch: python-gobject"
PYCAIRO_HINT = "Ubuntu/Debian: python3-cairo; Fedora: python3-cairo; Arch: python-cairo"
GTK_HINT = "Ubuntu/Debian: gir1.2-gtk-4.0; Fedora: gtk4; Arch: gtk4. Requires GTK 4.12+."
ADW_HINT = "Ubuntu/Debian: gir1.2-adw-1; Fedora: libadwaita; Arch: libadwaita. Requires Libadwaita 1.7+."
PWG_HINT = (
    "Install pipewire-gobject from PyPI or your distribution. "
    "It also needs system libpipewire-0.3, GLib, GObject, GIO, and PyGObject."
)
PIPEWIRE_HINT = (
    "Ubuntu/Debian: pipewire pipewire-bin wireplumber; Fedora: pipewire wireplumber; Arch: pipewire wireplumber"
)
PIPEWIRE_FILTER_CHAIN_HINT = (
    "Ubuntu/Debian: pipewire; Fedora: pipewire; Arch: pipewire. "
    "Flatpak builds bundle only the filter-chain module and SPA builtin filter support."
)
NUMPY_HINT = (
    "Install the package with Python dependencies: python -m pip install mini-eq, or python -m pip install numpy."
)
LIBEBUR128_HINT = (
    "Ubuntu/Debian: libebur128-1; Fedora: libebur128; Arch: libebur128. "
    "Flatpak builds should bundle libebur128 when live LUFS is enabled."
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


def check_native_ebur128() -> DependencyCheck:
    try:
        from . import ebur128

        detected_version = ebur128.version()
    except Exception as exc:
        return DependencyCheck("libebur128 loudness meter", "missing", False, str(exc), LIBEBUR128_HINT)

    return DependencyCheck(
        "libebur128 loudness meter",
        "ok",
        False,
        f"libebur128 {detected_version}",
        LIBEBUR128_HINT,
    )


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


def parse_dotted_version(value: str) -> tuple[int, int, int]:
    parts: list[int] = []
    for raw_part in value.split("."):
        digits = ""
        for char in raw_part:
            if not char.isdigit():
                break
            digits += char
        if not digits:
            break
        parts.append(int(digits))

    while len(parts) < 3:
        parts.append(0)

    return tuple(parts[:3])


def check_pipewire_gobject() -> DependencyCheck:
    shim_check = check_python_import("pipewire_gobject", "pipewire-gobject Python shim", True, PWG_HINT)
    namespace_check = check_gi_repository("Pwg", "0.1", "pipewire-gobject Pwg GI namespace", True, PWG_HINT)

    if not shim_check.ok or not namespace_check.ok:
        detail = f"Python shim: {shim_check.detail}; Pwg GI: {namespace_check.detail}"
        return DependencyCheck("pipewire-gobject", "missing", True, detail, PWG_HINT)

    module = importlib.import_module("gi.repository.Pwg")
    missing_symbols: list[str] = []
    for symbol in PWG_REQUIRED_SYMBOLS:
        current = module
        checked_path = "Pwg"
        for path_part in symbol.split("."):
            checked_path = f"{checked_path}.{path_part}"
            if not hasattr(current, path_part):
                missing_symbols.append(checked_path)
                break
            current = getattr(current, path_part)

    try:
        actual_version = str(module.get_library_version())
    except Exception as exc:
        return DependencyCheck(
            "pipewire-gobject", "missing", True, f"could not read Pwg library version: {exc}", PWG_HINT
        )

    if parse_dotted_version(actual_version) < PWG_REQUIRED_VERSION_PARTS:
        return DependencyCheck(
            "pipewire-gobject",
            "missing",
            True,
            f"Pwg library {actual_version} is older than required {PWG_REQUIRED_VERSION}",
            PWG_HINT,
        )

    if missing_symbols:
        return DependencyCheck(
            "pipewire-gobject",
            "missing",
            True,
            f"Pwg library {actual_version} lacks required symbol(s): {', '.join(missing_symbols)}",
            PWG_HINT,
        )

    return DependencyCheck(
        "pipewire-gobject",
        "ok",
        True,
        f"{shim_check.detail}; {namespace_check.detail}; Pwg library {actual_version}",
        PWG_HINT,
    )


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


def check_pipewire_session() -> DependencyCheck:
    command_check = check_command("wpctl", ["status"], "PipeWire session", True, PIPEWIRE_HINT)
    if command_check.ok:
        return command_check

    try:
        from .pipewire_backend import PipeWireBackend

        with PipeWireBackend(timeout_ms=1000):
            pass
    except Exception as exc:
        detail = f"{command_check.detail}; Pwg PipeWire connection failed: {exc}"
        return DependencyCheck("PipeWire session", "missing", True, detail, PIPEWIRE_HINT)

    return DependencyCheck(
        "PipeWire session",
        "ok",
        True,
        "connected to PipeWire through Pwg",
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
        check_pipewire_gobject(),
        check_pipewire_session(),
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
        check_native_ebur128(),
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
