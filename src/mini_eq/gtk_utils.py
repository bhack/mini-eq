from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")

from gi.repository import Gtk


def create_dropdown_from_strings(items: list[str]) -> Gtk.DropDown:
    return Gtk.DropDown(model=Gtk.StringList.new(items))


def get_dropdown_selected_text(dropdown: Gtk.DropDown) -> str | None:
    item = dropdown.get_selected_item()
    return item.get_string() if item is not None else None
