from __future__ import annotations

from gi.repository import GLib


def destroy_glib_source(source_id: int) -> None:
    source = GLib.MainContext.default().find_source_by_id(source_id)
    if source is not None:
        source.destroy()
