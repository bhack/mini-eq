from __future__ import annotations

from tests._mini_eq_imports import core, import_mini_eq_module

settings = import_mini_eq_module("settings")


def test_monitor_preference_defaults_to_on(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setattr(core, "PRESET_STORAGE_DIR", None)

    assert settings.load_monitor_enabled() is True


def test_monitor_preference_round_trip(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setattr(core, "PRESET_STORAGE_DIR", None)

    settings.save_monitor_enabled(False)

    assert settings.load_monitor_enabled() is False

    settings.save_monitor_enabled(True)

    assert settings.load_monitor_enabled() is True


def test_invalid_monitor_preference_uses_default(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setattr(core, "PRESET_STORAGE_DIR", None)
    path = settings.settings_path()
    path.parent.mkdir(parents=True)
    path.write_text('{"monitor_enabled": "false"}\n', encoding="utf-8")

    assert settings.load_monitor_enabled() is True
