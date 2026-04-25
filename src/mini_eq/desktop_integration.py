from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import gi

gi.require_version("Gdk", "4.0")
gi.require_version("Gtk", "4.0")

from gi.repository import Gdk, GLib, Gtk

APP_ID = "io.github.bhack.mini-eq"
APP_ICON_NAME = APP_ID
APP_ICON_SEARCH_PATH = Path(__file__).resolve().parent / "assets" / "icons"
APP_DISPLAY_NAME = "Mini EQ"


def install_app_icon() -> None:
    Gtk.Window.set_default_icon_name(APP_ICON_NAME)

    display = Gdk.Display.get_default()
    if display is None:
        return

    icon_theme = Gtk.IconTheme.get_for_display(display)
    icon_theme.add_search_path(str(APP_ICON_SEARCH_PATH))


def install_desktop_integration() -> None:
    data_home = Path(GLib.get_user_data_dir())
    applications_dir = data_home / "applications"
    hicolor_source_dir = APP_ICON_SEARCH_PATH / "hicolor"
    hicolor_target_dir = data_home / "icons" / "hicolor"

    applications_dir.mkdir(parents=True, exist_ok=True)

    desktop_file = applications_dir / f"{APP_ID}.desktop"
    desktop_file.write_text(build_desktop_file(), encoding="utf-8")
    desktop_file.chmod(0o644)

    for source_icon in hicolor_source_dir.glob(f"*/apps/{APP_ICON_NAME}.png"):
        target_icon = hicolor_target_dir / source_icon.relative_to(hicolor_source_dir)
        target_icon.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_icon, target_icon)

    refresh_desktop_database(applications_dir)
    refresh_icon_cache(hicolor_target_dir)

    print(f"desktop entry installed: {desktop_file}")
    print(f"icons installed under: {hicolor_target_dir}")


def build_desktop_file() -> str:
    exec_line = " ".join(
        [
            quote_desktop_exec_arg(sys.executable),
            "-m",
            "mini_eq",
        ],
    )

    return "\n".join(
        [
            "[Desktop Entry]",
            f"Name={APP_DISPLAY_NAME}",
            "GenericName=System-wide Equalizer",
            "Comment=Minimal system-wide parametric equalizer for PipeWire",
            "Keywords=equalizer;audio;pipewire;jack;",
            "Categories=GTK;AudioVideo;Audio;",
            f"Exec={exec_line}",
            f"Icon={APP_ICON_NAME}",
            "StartupNotify=true",
            "Terminal=false",
            "Type=Application",
            f"StartupWMClass={APP_ID}",
            "",
        ],
    )


def quote_desktop_exec_arg(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%")
    return f'"{escaped}"'


def refresh_desktop_database(applications_dir: Path) -> None:
    update_desktop_database = shutil.which("update-desktop-database")
    if update_desktop_database is None:
        return

    subprocess.run(
        [update_desktop_database, str(applications_dir)],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def refresh_icon_cache(hicolor_dir: Path) -> None:
    gtk_update_icon_cache = shutil.which("gtk-update-icon-cache")
    if gtk_update_icon_cache is None or not (hicolor_dir / "index.theme").exists():
        return

    subprocess.run(
        [gtk_update_icon_cache, "-q", "-f", "-t", str(hicolor_dir)],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
