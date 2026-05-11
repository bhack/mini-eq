from __future__ import annotations

import json
from pathlib import Path
from typing import Final

from .core import app_config_file_path

SETTINGS_FILE_NAME: Final = "settings.json"
SETTINGS_VERSION_KEY: Final = "version"
SETTINGS_VERSION: Final = 1
MONITOR_ENABLED_KEY: Final = "monitor_enabled"
APPEARANCE_KEY: Final = "appearance"
BACKGROUND_MODE_KEY: Final = "background_mode"
START_AT_LOGIN_KEY: Final = "start_at_login"
START_ACTIVE_AT_LOGIN_KEY: Final = "start_active_at_login"
BOOL_SETTINGS_KEYS: Final = frozenset(
    (
        MONITOR_ENABLED_KEY,
        BACKGROUND_MODE_KEY,
        START_AT_LOGIN_KEY,
        START_ACTIVE_AT_LOGIN_KEY,
    ),
)
APPEARANCE_VALUES: Final = frozenset(("system", "light", "dark"))


def settings_path() -> Path:
    return app_config_file_path(SETTINGS_FILE_NAME)


def settings_payload_version(payload: dict[str, object]) -> int | None:
    if SETTINGS_VERSION_KEY not in payload:
        return 0

    raw_version = payload[SETTINGS_VERSION_KEY]
    if isinstance(raw_version, bool) or not isinstance(raw_version, int) or raw_version < 0:
        return None

    return raw_version


def normalize_settings_values(payload: dict[str, object]) -> dict[str, object]:
    normalized: dict[str, object] = {}

    for key in BOOL_SETTINGS_KEYS:
        value = payload.get(key)
        if isinstance(value, bool):
            normalized[key] = value

    appearance = payload.get(APPEARANCE_KEY)
    if isinstance(appearance, str) and appearance in APPEARANCE_VALUES:
        normalized[APPEARANCE_KEY] = appearance

    return normalized


def normalize_settings_payload(payload: dict[str, object]) -> dict[str, object]:
    version = settings_payload_version(payload)
    if version is None or version > SETTINGS_VERSION:
        return {}

    normalized = normalize_settings_values(payload)
    normalized[SETTINGS_VERSION_KEY] = SETTINGS_VERSION
    return normalized


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

    return normalize_settings_payload(payload)


def save_settings(payload: dict[str, object]) -> None:
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized = normalize_settings_values(payload)
    normalized[SETTINGS_VERSION_KEY] = SETTINGS_VERSION
    path.write_text(json.dumps(normalized, indent=2) + "\n", encoding="utf-8")


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
