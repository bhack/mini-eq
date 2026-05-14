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


def save_window_size(settings: Gio.Settings, window: Gtk.Window) -> None:
    width, height = window.get_default_size()
    if width > 0:
        settings.set_int(WINDOW_WIDTH_KEY, width)
    if height > 0:
        settings.set_int(WINDOW_HEIGHT_KEY, height)


def on_window_size_changed(window: Gtk.Window, _pspec: object, settings: Gio.Settings) -> None:
    save_window_size(settings, window)


def on_window_maximized_changed(window: Gtk.Window, _pspec: object, settings: Gio.Settings) -> None:
    settings.set_boolean(WINDOW_MAXIMIZED_KEY, window.is_maximized())


def bind_window_state(window: Gtk.Window) -> Gio.Settings | None:
    settings = create_window_state_settings()
    if settings is None:
        return None

    width = settings.get_int(WINDOW_WIDTH_KEY) if settings.get_user_value(WINDOW_WIDTH_KEY) is not None else None
    height = settings.get_int(WINDOW_HEIGHT_KEY) if settings.get_user_value(WINDOW_HEIGHT_KEY) is not None else None
    if width is not None or height is not None:
        current_width, current_height = window.get_default_size()
        window.set_default_size(
            width if width is not None else current_width, height if height is not None else current_height
        )

    if settings.get_user_value(WINDOW_MAXIMIZED_KEY) is not None and settings.get_boolean(WINDOW_MAXIMIZED_KEY):
        window.maximize()

    window.connect("notify::default-width", on_window_size_changed, settings)
    window.connect("notify::default-height", on_window_size_changed, settings)
    window.connect("notify::maximized", on_window_maximized_changed, settings)
    return settings
