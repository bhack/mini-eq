from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")

from gi.repository import Gtk, Pango


def set_accessible_label(widget: Gtk.Widget, label: str) -> None:
    widget.update_property([Gtk.AccessibleProperty.LABEL], [label])


def set_accessible_description(widget: Gtk.Widget, description: str) -> None:
    widget.update_property([Gtk.AccessibleProperty.DESCRIPTION], [description])


def bind_label_to_control(label: Gtk.Label, widget: Gtk.Widget) -> None:
    label.set_mnemonic_widget(widget)


def constrain_editor_label(label: Gtk.Label, width_chars: int) -> None:
    label.set_width_chars(width_chars)
    label.set_max_width_chars(width_chars)
    label.set_ellipsize(Pango.EllipsizeMode.END)
    label.set_single_line_mode(True)
