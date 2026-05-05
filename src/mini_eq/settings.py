from __future__ import annotations

import json
from pathlib import Path
from typing import Final

from .core import app_config_dir

SETTINGS_FILE_NAME: Final = "settings.json"
MONITOR_ENABLED_KEY: Final = "monitor_enabled"


def settings_path() -> Path:
    return app_config_dir() / SETTINGS_FILE_NAME


def load_settings() -> dict[str, object]:
    path = settings_path()
    if not path.is_file():
        return {}

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}

    if not isinstance(payload, dict):
        return {}

    return payload


def save_settings(payload: dict[str, object]) -> None:
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def update_setting(key: str, value: object) -> None:
    payload = load_settings()
    payload[key] = value
    save_settings(payload)


def load_bool_setting(key: str, *, default: bool = False) -> bool:
    value = load_settings().get(key)
    if isinstance(value, bool):
        return value

    return default


def save_bool_setting(key: str, enabled: bool) -> None:
    update_setting(key, bool(enabled))


def load_monitor_enabled() -> bool:
    return load_bool_setting(MONITOR_ENABLED_KEY, default=True)


def save_monitor_enabled(enabled: bool) -> None:
    save_bool_setting(MONITOR_ENABLED_KEY, enabled)
