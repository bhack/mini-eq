from __future__ import annotations

import json
from pathlib import Path
from typing import Final

import gi

gi.require_version("Adw", "1")

from gi.repository import Adw

from .core import app_config_dir

APPEARANCE_SYSTEM: Final = "system"
APPEARANCE_LIGHT: Final = "light"
APPEARANCE_DARK: Final = "dark"
APPEARANCE_MODES: Final = (APPEARANCE_SYSTEM, APPEARANCE_LIGHT, APPEARANCE_DARK)
DEFAULT_APPEARANCE: Final = APPEARANCE_SYSTEM
SETTINGS_FILE_NAME: Final = "settings.json"
APPEARANCE_KEY: Final = "appearance"


def normalize_appearance(value: object) -> str:
    if isinstance(value, str) and value in APPEARANCE_MODES:
        return value

    return DEFAULT_APPEARANCE


def settings_path() -> Path:
    return app_config_dir() / SETTINGS_FILE_NAME


def load_appearance_preference() -> str:
    path = settings_path()
    if not path.is_file():
        return DEFAULT_APPEARANCE

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return DEFAULT_APPEARANCE

    if not isinstance(payload, dict):
        return DEFAULT_APPEARANCE

    return normalize_appearance(payload.get(APPEARANCE_KEY))


def save_appearance_preference(appearance: str) -> None:
    path = settings_path()
    payload: dict[str, object] = {}

    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            loaded = {}
        if isinstance(loaded, dict):
            payload = loaded

    payload[APPEARANCE_KEY] = normalize_appearance(appearance)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def color_scheme_for_appearance(appearance: str):
    normalized = normalize_appearance(appearance)
    if normalized == APPEARANCE_LIGHT:
        return Adw.ColorScheme.FORCE_LIGHT
    if normalized == APPEARANCE_DARK:
        return Adw.ColorScheme.FORCE_DARK

    return Adw.ColorScheme.PREFER_LIGHT


def apply_appearance_preference(appearance: str, style_manager=None) -> str:
    normalized = normalize_appearance(appearance)
    manager = style_manager or Adw.StyleManager.get_default()
    manager.set_color_scheme(color_scheme_for_appearance(normalized))
    return normalized


def style_manager_is_dark(style_manager=None) -> bool:
    manager = style_manager or Adw.StyleManager.get_default()
    return bool(manager.get_dark())
