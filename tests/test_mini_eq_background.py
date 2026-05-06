from __future__ import annotations

import json

from tests._mini_eq_imports import core, import_mini_eq_module

background = import_mini_eq_module("background")
settings = import_mini_eq_module("settings")


def test_background_preferences_default_to_off(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setattr(core, "PRESET_STORAGE_DIR", None)

    assert background.load_background_mode() is False
    assert background.load_start_at_login() is False
    assert background.load_start_active_at_login() is False


def test_background_preferences_round_trip_in_settings_file(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setattr(core, "PRESET_STORAGE_DIR", None)

    background.save_background_mode(True)
    background.save_start_at_login(True)
    background.save_start_active_at_login(True)

    assert background.load_background_mode() is True
    assert background.load_start_at_login() is True
    assert background.load_start_active_at_login() is True
    assert json.loads(settings.settings_path().read_text(encoding="utf-8")) == {
        background.BACKGROUND_MODE_KEY: True,
        background.START_AT_LOGIN_KEY: True,
        background.START_ACTIVE_AT_LOGIN_KEY: True,
    }


def test_invalid_settings_json_keeps_background_preferences_off(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setattr(core, "PRESET_STORAGE_DIR", None)
    path = settings.settings_path()
    path.parent.mkdir(parents=True)
    path.write_text("{invalid", encoding="utf-8")

    assert background.load_background_mode() is False
    assert background.load_start_at_login() is False
    assert background.load_start_active_at_login() is False


def test_native_autostart_file_creation_and_removal(tmp_path, monkeypatch) -> None:
    autostart_file = tmp_path / "autostart" / "io.github.bhack.mini-eq.desktop"
    monkeypatch.setattr(background, "autostart_desktop_path", lambda: autostart_file)

    background.set_native_start_at_login(True, executable="/opt/mini-eq/bin/mini-eq")

    contents = autostart_file.read_text(encoding="utf-8")
    assert "Name=Mini EQ" in contents
    assert 'Exec="/opt/mini-eq/bin/mini-eq" "--background"' in contents
    assert "NoDisplay=true" in contents

    background.set_native_start_at_login(True, executable="/opt/mini-eq/bin/mini-eq", auto_route=True)

    contents = autostart_file.read_text(encoding="utf-8")
    assert 'Exec="/opt/mini-eq/bin/mini-eq" "--background" "--auto-route"' in contents

    background.set_native_start_at_login(False)

    assert not autostart_file.exists()


def test_background_command_can_start_active() -> None:
    assert background.mini_eq_background_command("mini-eq") == ["mini-eq", "--background"]
    assert background.mini_eq_background_command("mini-eq", auto_route=True) == [
        "mini-eq",
        "--background",
        "--auto-route",
    ]


def test_resolve_mini_eq_executable_prefers_path_lookup(monkeypatch) -> None:
    monkeypatch.setattr(background.shutil, "which", lambda name: "/usr/bin/mini-eq" if name == "mini-eq" else None)

    assert background.resolve_mini_eq_executable() == "/usr/bin/mini-eq"


def test_resolve_mini_eq_executable_accepts_absolute_executable(tmp_path, monkeypatch) -> None:
    executable = tmp_path / "mini-eq"
    executable.write_text("#!/bin/sh\n", encoding="utf-8")
    executable.chmod(0o755)
    monkeypatch.setattr(background.shutil, "which", lambda _name: None)

    assert background.resolve_mini_eq_executable(str(executable)) == str(executable)
