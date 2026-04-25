from __future__ import annotations

from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gsk", "4.0")
gi.require_version("Graphene", "1.0")

from gi.repository import Graphene, Gsk, Gtk


def capture_widget_to_png(widget: Gtk.Widget, path: str | Path) -> None:
    width = widget.get_width()
    height = widget.get_height()
    if width <= 0 or height <= 0:
        raise RuntimeError("cannot capture widget before it has a visible size")

    surface = widget.get_surface()
    if surface is None:
        raise RuntimeError("cannot capture widget before it has a GDK surface")

    paintable = Gtk.WidgetPaintable.new(widget)
    snapshot = Gtk.Snapshot()
    paintable.snapshot(snapshot, float(width), float(height))
    node = snapshot.to_node()
    if node is None:
        raise RuntimeError("widget did not produce a render node")

    output_path = Path(path).expanduser()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    renderer = Gsk.Renderer.new_for_surface(surface)
    try:
        rect = Graphene.Rect().init(0, 0, float(width), float(height))
        texture = renderer.render_texture(node, rect)
        if not texture.save_to_png(str(output_path)):
            raise RuntimeError(f"failed to save screenshot to {output_path}")
    finally:
        renderer.unrealize()
