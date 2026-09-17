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
    assert check_gnome_shell_extension.check_metadata() is None


def test_gnome_shell_extension_dbus_contract_matches_app() -> None:
    assert check_gnome_shell_extension.check_dbus_contract() is None


def test_gnome_shell_extension_fake_control_matches_shell_usage() -> None:
    assert check_gnome_shell_extension.check_fake_control_contract() is None


def test_gnome_shell_extension_fake_control_can_expose_large_preset_library() -> None:
    fake_control = check_gnome_shell_extension.fake_control_module()
    presets = fake_control.demo_presets(35)

    assert len(presets) == 35
    assert presets[:3] == ["Studio Reference", "Flat", "Voice Focus"]
    assert presets[-1].startswith("Preset 35 - ")
