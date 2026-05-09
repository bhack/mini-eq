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


def requested_switch_state(switch: Gtk.Switch, state: object | None) -> bool:
    if state is None:
        return bool(switch.get_active())

    return bool(state)


def set_switch_confirmed_state(switch: Gtk.Switch, active: bool) -> None:
    switch.set_active(active)
    switch.set_state(active)


def constrain_editor_label(label: Gtk.Label, width_chars: int) -> None:
    label.set_width_chars(width_chars)
    label.set_max_width_chars(width_chars)
    label.set_ellipsize(Pango.EllipsizeMode.END)
    label.set_single_line_mode(True)


def make_ellipsizing_string_list_factory(max_width_chars: int) -> Gtk.SignalListItemFactory:
    factory = Gtk.SignalListItemFactory()

    def setup(_factory: Gtk.SignalListItemFactory, list_item: Gtk.ListItem) -> None:
        label = Gtk.Label(xalign=0.0)
        label.set_hexpand(True)
        label.set_width_chars(1)
        label.set_max_width_chars(max_width_chars)
        label.set_ellipsize(Pango.EllipsizeMode.END)
        label.set_single_line_mode(True)
        list_item.set_child(label)

    def bind(_factory: Gtk.SignalListItemFactory, list_item: Gtk.ListItem) -> None:
        item = list_item.get_item()
        child = list_item.get_child()
        if not isinstance(child, Gtk.Label):
            return

        text = item.get_string() if isinstance(item, Gtk.StringObject) else ""
        child.set_text(text)
        child.set_tooltip_text(text)

    factory.connect("setup", setup)
    factory.connect("bind", bind)
    return factory
