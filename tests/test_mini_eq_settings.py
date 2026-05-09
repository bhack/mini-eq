from __future__ import annotations

import json

import pytest

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
    assert json.loads(settings.settings_path().read_text(encoding="utf-8")) == {
        settings.SETTINGS_VERSION_KEY: settings.SETTINGS_VERSION,
        settings.MONITOR_ENABLED_KEY: True,
    }


def test_legacy_settings_without_version_still_load(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setattr(core, "PRESET_STORAGE_DIR", None)
    path = settings.settings_path()
    path.parent.mkdir(parents=True)
    legacy_payload = '{"monitor_enabled": false}\n'
    path.write_text(legacy_payload, encoding="utf-8")

    assert settings.load_monitor_enabled() is False
    assert settings.load_settings() == {
        settings.SETTINGS_VERSION_KEY: settings.SETTINGS_VERSION,
        settings.MONITOR_ENABLED_KEY: False,
    }
    assert path.read_text(encoding="utf-8") == legacy_payload

    settings.save_monitor_enabled(True)

    assert json.loads(path.read_text(encoding="utf-8")) == {
        settings.SETTINGS_VERSION_KEY: settings.SETTINGS_VERSION,
        settings.MONITOR_ENABLED_KEY: True,
    }


def test_newer_settings_version_uses_defaults(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setattr(core, "PRESET_STORAGE_DIR", None)
    path = settings.settings_path()
    path.parent.mkdir(parents=True)
    future_payload = (
        json.dumps(
            {
                settings.SETTINGS_VERSION_KEY: settings.SETTINGS_VERSION + 1,
                settings.MONITOR_ENABLED_KEY: False,
            },
        )
        + "\n"
    )
    path.write_text(future_payload, encoding="utf-8")

    assert settings.load_settings() == {}
    assert settings.load_monitor_enabled() is True
    assert path.read_text(encoding="utf-8") == future_payload


@pytest.mark.parametrize("version_value", [True, "1", -1, 1.0, None])
def test_corrupt_settings_version_uses_defaults(version_value, tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setattr(core, "PRESET_STORAGE_DIR", None)
    path = settings.settings_path()
    path.parent.mkdir(parents=True)
    corrupt_payload = (
        json.dumps(
            {
                settings.SETTINGS_VERSION_KEY: version_value,
                settings.MONITOR_ENABLED_KEY: False,
            },
        )
        + "\n"
    )
    path.write_text(corrupt_payload, encoding="utf-8")

    assert settings.load_settings() == {}
    assert settings.load_monitor_enabled() is True
    assert path.read_text(encoding="utf-8") == corrupt_payload


def test_corrupt_settings_values_are_dropped(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setattr(core, "PRESET_STORAGE_DIR", None)
    path = settings.settings_path()
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                settings.SETTINGS_VERSION_KEY: settings.SETTINGS_VERSION,
                settings.MONITOR_ENABLED_KEY: "false",
                settings.BACKGROUND_MODE_KEY: "true",
                settings.START_AT_LOGIN_KEY: True,
                settings.APPEARANCE_KEY: "sepia",
                "unknown": True,
            },
        )
        + "\n",
        encoding="utf-8",
    )

    assert settings.load_settings() == {
        settings.SETTINGS_VERSION_KEY: settings.SETTINGS_VERSION,
        settings.START_AT_LOGIN_KEY: True,
    }


def test_invalid_monitor_preference_uses_default(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setattr(core, "PRESET_STORAGE_DIR", None)
    path = settings.settings_path()
    path.parent.mkdir(parents=True)
    path.write_text('{"monitor_enabled": "false"}\n', encoding="utf-8")

    assert settings.load_monitor_enabled() is True
