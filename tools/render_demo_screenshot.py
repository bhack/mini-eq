from __future__ import annotations

import argparse
import os
import tempfile
from pathlib import Path

import gi
from PIL import Image, ImageFilter

gi.require_version("Adw", "1")

from demo_runtime import DEMO_PRESET_NAME, DemoController, demo_analyzer_levels
from gi.repository import Adw, GLib

from mini_eq import core
from mini_eq.appearance import APPEARANCE_DARK, APPEARANCE_LIGHT, apply_appearance_preference
from mini_eq.desktop_integration import APP_ID, install_app_icon
from mini_eq.screenshot import capture_widget_to_png
from mini_eq.window import MiniEqWindow

SCREENSHOT_DELAY_MS = 1400
SCREENSHOT_WIDTH = 1360
SCREENSHOT_HEIGHT = 720
MAX_CONTENT_WIDTH = 900
WINDOW_SHADOW_BLUR = 14
WINDOW_SHADOW_MARGIN = 28
WINDOW_SHADOW_OPACITY = 90
WINDOW_SHADOW_OFFSET_Y = 8


def resize_image_if_needed(image: Image.Image, max_width: int) -> Image.Image:
    if max_width <= 0:
        return image.copy()

    if image.width <= max_width:
        return image.copy()

    height = round(image.height * (max_width / image.width))
    return image.resize((max_width, height), Image.Resampling.LANCZOS)


def add_window_shadow(image: Image.Image) -> Image.Image:
    window = image.convert("RGBA")
    width = window.width + WINDOW_SHADOW_MARGIN * 2
    height = window.height + WINDOW_SHADOW_MARGIN * 2

    alpha = window.getchannel("A")
    shadow_alpha = Image.new("L", (width, height), 0)
    shadow_alpha.paste(alpha, (WINDOW_SHADOW_MARGIN, WINDOW_SHADOW_MARGIN + WINDOW_SHADOW_OFFSET_Y))
    shadow_alpha = shadow_alpha.filter(ImageFilter.GaussianBlur(WINDOW_SHADOW_BLUR))
    shadow_alpha = shadow_alpha.point(lambda value: value * WINDOW_SHADOW_OPACITY // 255)

    shadow = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    shadow.putalpha(shadow_alpha)

    framed = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    framed.alpha_composite(shadow)
    framed.alpha_composite(window, (WINDOW_SHADOW_MARGIN, WINDOW_SHADOW_MARGIN))
    return framed


def finalize_store_screenshot(path: Path, max_content_width: int) -> None:
    with Image.open(path) as image:
        resized = resize_image_if_needed(image.convert("RGBA"), max_content_width)
        framed = add_window_shadow(resized)
        framed.save(path, optimize=True)


class DemoScreenshotApplication(Adw.Application):
    def __init__(
        self,
        output_path: Path,
        config_dir: Path,
        delay_ms: int,
        width: int,
        height: int,
        max_content_width: int,
        appearance: str,
    ) -> None:
        super().__init__(application_id=f"{APP_ID}.DemoScreenshot")
        self.output_path = output_path
        self.config_dir = config_dir
        self.delay_ms = delay_ms
        self.width = width
        self.height = height
        self.max_content_width = max_content_width
        self.appearance = appearance
        self.controller = DemoController()
        self.window: MiniEqWindow | None = None

    def do_startup(self) -> None:
        Adw.Application.do_startup(self)
        install_app_icon()
        apply_appearance_preference(self.appearance, self.get_style_manager())

    def do_activate(self) -> None:
        core.PRESET_STORAGE_DIR = self.config_dir / "mini-eq" / "output"
        core.write_mini_eq_preset_file(
            core.preset_path_for_name(DEMO_PRESET_NAME),
            self.controller.build_preset_payload(DEMO_PRESET_NAME),
        )

        self.window = MiniEqWindow(self, self.controller, auto_route=True)
        self.window.set_default_size(self.width, self.height)
        self.window.current_preset_name = DEMO_PRESET_NAME
        self.window.saved_preset_signature = self.controller.state_signature()
        self.window.analyzer_enabled = True
        self.window.analyzer_display_gain_db = 24.0
        self.window.analyzer_levels = demo_analyzer_levels()
        self.window.sync_ui_from_state()
        self.window.refresh_preset_list()
        self.window.set_visible(True)
        self.window.present()
        self.window.schedule_post_present_setup()
        GLib.timeout_add(self.delay_ms, self.on_capture_timeout)

    def on_capture_timeout(self) -> bool:
        if self.window is None:
            raise RuntimeError("window is not available")

        self.window.analyzer_enabled = True
        self.window.analyzer_levels = demo_analyzer_levels()
        self.window.queue_analyzer_draw(force=True)
        GLib.timeout_add(120, self.on_capture_ready_timeout)
        return False

    def on_capture_ready_timeout(self) -> bool:
        if self.window is None:
            raise RuntimeError("window is not available")

        capture_widget_to_png(self.window, self.output_path)
        finalize_store_screenshot(self.output_path, self.max_content_width)
        print(f"saved screenshot to {self.output_path}")
        self.window.prepare_for_shutdown()
        self.quit()
        return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render a neutral Mini EQ release screenshot.")
    parser.add_argument("output", nargs="?", default="docs/screenshots/mini-eq.png", help="PNG output path")
    parser.add_argument("--delay-ms", type=int, default=SCREENSHOT_DELAY_MS, help="delay before capture")
    parser.add_argument("--width", type=int, default=SCREENSHOT_WIDTH, help="screenshot window width")
    parser.add_argument("--height", type=int, default=SCREENSHOT_HEIGHT, help="screenshot window height")
    parser.add_argument(
        "--appearance",
        choices=(APPEARANCE_LIGHT, APPEARANCE_DARK),
        default=APPEARANCE_LIGHT,
        help="appearance to force for the rendered screenshot",
    )
    parser.add_argument(
        "--max-content-width",
        "--max-output-width",
        dest="max_content_width",
        type=int,
        default=MAX_CONTENT_WIDTH,
        help="resize the captured window content to this width before adding the window shadow; use 0 to keep native size",
    )
    args = parser.parse_args(argv)

    output_path = Path(args.output).expanduser()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    Adw.init()
    with tempfile.TemporaryDirectory(prefix="mini-eq-screenshot-") as config_dir:
        previous_xdg_config_home = os.environ.get("XDG_CONFIG_HOME")
        os.environ["XDG_CONFIG_HOME"] = str(Path(config_dir))
        app = DemoScreenshotApplication(
            output_path,
            Path(config_dir),
            args.delay_ms,
            args.width,
            args.height,
            args.max_content_width,
            args.appearance,
        )
        try:
            return app.run([])
        finally:
            if previous_xdg_config_home is None:
                os.environ.pop("XDG_CONFIG_HOME", None)
            else:
                os.environ["XDG_CONFIG_HOME"] = previous_xdg_config_home


if __name__ == "__main__":
    raise SystemExit(main())
