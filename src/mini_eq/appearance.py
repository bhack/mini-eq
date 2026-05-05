from __future__ import annotations

from pathlib import Path
from typing import Final

import gi

gi.require_version("Adw", "1")

from gi.repository import Adw

from .settings import load_settings, update_setting
from .settings import settings_path as _settings_path

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
    return _settings_path()


def load_appearance_preference() -> str:
    return normalize_appearance(load_settings().get(APPEARANCE_KEY))


def save_appearance_preference(appearance: str) -> None:
    update_setting(APPEARANCE_KEY, normalize_appearance(appearance))


def color_scheme_for_appearance(appearance: str):
    normalized = normalize_appearance(appearance)
    if normalized == APPEARANCE_LIGHT:
        return Adw.ColorScheme.FORCE_LIGHT
    if normalized == APPEARANCE_DARK:
        return Adw.ColorScheme.FORCE_DARK

    return Adw.ColorScheme.DEFAULT


def apply_appearance_preference(appearance: str, style_manager=None) -> str:
    normalized = normalize_appearance(appearance)
    manager = style_manager or Adw.StyleManager.get_default()
    manager.set_color_scheme(color_scheme_for_appearance(normalized))
    return normalized


def style_manager_is_dark(style_manager=None) -> bool:
    manager = style_manager or Adw.StyleManager.get_default()
    return bool(manager.get_dark())
