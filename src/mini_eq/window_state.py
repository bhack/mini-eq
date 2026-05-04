from __future__ import annotations

import gi

gi.require_version("Gio", "2.0")
gi.require_version("Gtk", "4.0")

from gi.repository import Gio, Gtk

from .desktop_integration import APP_ID

WINDOW_STATE_SCHEMA_ID = APP_ID
WINDOW_WIDTH_KEY = "window-width"
WINDOW_HEIGHT_KEY = "window-height"
WINDOW_MAXIMIZED_KEY = "window-maximized"


def window_state_schema_available() -> bool:
    schema_source = Gio.SettingsSchemaSource.get_default()
    return schema_source is not None and schema_source.lookup(WINDOW_STATE_SCHEMA_ID, True) is not None


def create_window_state_settings() -> Gio.Settings | None:
    if not window_state_schema_available():
        return None

    return Gio.Settings.new(WINDOW_STATE_SCHEMA_ID)


def bind_window_state(window: Gtk.Window) -> Gio.Settings | None:
    settings = create_window_state_settings()
    if settings is None:
        return None

    flags = Gio.SettingsBindFlags.DEFAULT
    settings.bind(WINDOW_WIDTH_KEY, window, "default-width", flags)
    settings.bind(WINDOW_HEIGHT_KEY, window, "default-height", flags)
    settings.bind(WINDOW_MAXIMIZED_KEY, window, "maximized", flags)
    return settings
