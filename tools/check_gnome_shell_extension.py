#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from types import SimpleNamespace
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

EXTENSION_UUID = "mini-eq@bhack.github.io"
EXTENSION_DIR = ROOT / "extensions" / "gnome-shell" / EXTENSION_UUID
EXTENSION_JS = EXTENSION_DIR / "extension.js"
METADATA_JSON = EXTENSION_DIR / "metadata.json"
PACK_SCRIPT = ROOT / "tools" / "pack_gnome_shell_extension.sh"
EXPECTED_ZIP_NAMES = {"extension.js", "metadata.json", "mini-eq-symbolic.svg"}

DBUS_CALL_RE = re.compile(r"\bthis\._call\(\s*(['\"])(?P<method>[A-Za-z][A-Za-z0-9_]*)\1")
DBUS_SIGNAL_SUBSCRIBE_RE = re.compile(
    r"\bsignal_subscribe\([^)]*?(['\"])(?P<signal>[A-Za-z][A-Za-z0-9_]*)\1",
    re.DOTALL,
)
STATE_FIELD_RE = re.compile(r"\bstate\.(?P<field>[A-Za-z_][A-Za-z0-9_]*)\b")
STABLE_SHELL_VERSION_RE = re.compile(r"^\d+(?:\.\d+)?$")


class ExtensionCheckError(RuntimeError):
    pass


def extension_source() -> str:
    return EXTENSION_JS.read_text(encoding="utf-8")


def extension_called_methods(source: str | None = None) -> set[str]:
    source = extension_source() if source is None else source
    return {match.group("method") for match in DBUS_CALL_RE.finditer(source)}


def extension_subscribed_signals(source: str | None = None) -> set[str]:
    source = extension_source() if source is None else source
    return {match.group("signal") for match in DBUS_SIGNAL_SUBSCRIBE_RE.finditer(source)}


def extension_state_fields(source: str | None = None) -> set[str]:
    source = extension_source() if source is None else source
    return {match.group("field") for match in STATE_FIELD_RE.finditer(source)}


def dbus_exported_methods() -> set[str]:
    from mini_eq import dbus_control

    node = ElementTree.fromstring(dbus_control.INTROSPECTION_XML)
    return {method.attrib["name"] for method in node.findall("./interface/method")}


def dbus_exported_signals() -> set[str]:
    from mini_eq import dbus_control

    node = ElementTree.fromstring(dbus_control.INTROSPECTION_XML)
    return {signal.attrib["name"] for signal in node.findall("./interface/signal")}


def dbus_exported_state_fields() -> set[str]:
    from mini_eq import dbus_control

    controller = SimpleNamespace(eq_enabled=True, routed=True, output_sink="alsa_output.test")
    window = SimpleNamespace(
        current_preset_name="Flat",
        analyzer_enabled=True,
        analyzer_levels=[0.0] * dbus_control.PANEL_ANALYZER_BINS,
    )
    app = SimpleNamespace(controller=controller, window=window)
    return set(dbus_control.MiniEqDbusControl(app).state())


def check_dbus_contract() -> None:
    missing_methods = extension_called_methods() - dbus_exported_methods()
    if missing_methods:
        raise ExtensionCheckError(
            "GNOME Shell extension calls D-Bus method(s) not exported by Mini EQ: " + ", ".join(sorted(missing_methods))
        )

    missing_signals = extension_subscribed_signals() - dbus_exported_signals()
    if missing_signals:
        raise ExtensionCheckError(
            "GNOME Shell extension subscribes to D-Bus signal(s) not exported by Mini EQ: "
            + ", ".join(sorted(missing_signals))
        )

    missing_state_fields = extension_state_fields() - dbus_exported_state_fields()
    if missing_state_fields:
        raise ExtensionCheckError(
            "GNOME Shell extension reads D-Bus state field(s) not exported by Mini EQ: "
            + ", ".join(sorted(missing_state_fields))
        )


def metadata() -> dict[str, object]:
    return json.loads(METADATA_JSON.read_text(encoding="utf-8"))


def check_metadata() -> None:
    data = metadata()
    if data.get("uuid") != EXTENSION_UUID:
        raise ExtensionCheckError(f"metadata.json uuid must be {EXTENSION_UUID!r}")

    for key in ("name", "description", "url"):
        if not isinstance(data.get(key), str) or not data[key]:
            raise ExtensionCheckError(f"metadata.json must contain a non-empty {key!r} string")

    shell_versions = data.get("shell-version")
    if not isinstance(shell_versions, list) or not shell_versions:
        raise ExtensionCheckError("metadata.json must contain a non-empty 'shell-version' list")

    invalid_versions = [
        version
        for version in shell_versions
        if not isinstance(version, str) or not STABLE_SHELL_VERSION_RE.fullmatch(version)
    ]
    if invalid_versions:
        raise ExtensionCheckError(
            "metadata.json shell-version entries must be stable GNOME Shell releases: "
            + ", ".join(repr(version) for version in invalid_versions)
        )


def pack_extension(out_dir: Path) -> Path:
    subprocess.run([PACK_SCRIPT, out_dir], cwd=ROOT, check=True)
    return out_dir / f"{EXTENSION_UUID}.shell-extension.zip"


def check_zip(zip_path: Path) -> None:
    with zipfile.ZipFile(zip_path) as archive:
        names = set(archive.namelist())

    if names != EXPECTED_ZIP_NAMES:
        unexpected = names - EXPECTED_ZIP_NAMES
        missing = EXPECTED_ZIP_NAMES - names
        details: list[str] = []
        if missing:
            details.append("missing " + ", ".join(sorted(missing)))
        if unexpected:
            details.append("unexpected " + ", ".join(sorted(unexpected)))
        raise ExtensionCheckError("GNOME Shell extension zip has wrong contents: " + "; ".join(details))


def check_packaging() -> None:
    with tempfile.TemporaryDirectory(prefix="mini-eq-gnome-shell-extension-") as temp_dir:
        zip_path = pack_extension(Path(temp_dir))
        check_zip(zip_path)


def run_checks(*, package: bool) -> None:
    check_metadata()
    check_dbus_contract()
    if package:
        check_packaging()


def main() -> int:
    parser = argparse.ArgumentParser(description="Check the Mini EQ GNOME Shell extension package and D-Bus contract.")
    parser.add_argument(
        "--no-package",
        action="store_true",
        help="skip invoking gnome-extensions pack; still check metadata and the D-Bus contract",
    )
    args = parser.parse_args()

    try:
        run_checks(package=not args.no_package)
    except ExtensionCheckError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print("GNOME Shell extension checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
