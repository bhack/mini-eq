from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHECK_SCRIPT = ROOT / "tools" / "check_gnome_shell_extension.py"

spec = importlib.util.spec_from_file_location("check_gnome_shell_extension", CHECK_SCRIPT)
assert spec is not None
check_gnome_shell_extension = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(check_gnome_shell_extension)


def test_gnome_shell_extension_metadata_is_publishable() -> None:
    check_gnome_shell_extension.check_metadata()


def test_gnome_shell_extension_dbus_contract_matches_app() -> None:
    check_gnome_shell_extension.check_dbus_contract()
