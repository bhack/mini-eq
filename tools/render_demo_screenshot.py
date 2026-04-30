from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

import gi
from PIL import Image

gi.require_version("Adw", "1")

from demo_runtime import DEMO_PRESET_NAME, DemoController, demo_analyzer_levels
from gi.repository import Adw, GLib

from mini_eq import core
from mini_eq.desktop_integration import APP_ID, install_app_icon
from mini_eq.screenshot import capture_widget_to_png
from mini_eq.window import MiniEqWindow

SCREENSHOT_DELAY_MS = 1400
SCREENSHOT_WIDTH = 1360
SCREENSHOT_HEIGHT = 720
MAX_OUTPUT_WIDTH = 1000


def resize_png_if_needed(path: Path, max_width: int) -> None:
    if max_width <= 0:
        return

    image = Image.open(path)
    try:
        if image.width <= max_width:
            return

        height = round(image.height * (max_width / image.width))
        resized = image.resize((max_width, height), Image.Resampling.LANCZOS)
        resized.save(path, optimize=True)
    finally:
        image.close()


class DemoScreenshotApplication(Adw.Application):
    def __init__(
        self,
        output_path: Path,
        config_dir: Path,
        delay_ms: int,
        width: int,
        height: int,
        max_output_width: int,
    ) -> None:
        super().__init__(application_id=f"{APP_ID}.DemoScreenshot")
        self.output_path = output_path
        self.config_dir = config_dir
        self.delay_ms = delay_ms
        self.width = width
        self.height = height
        self.max_output_width = max_output_width
        self.controller = DemoController()
        self.window: MiniEqWindow | None = None

    def do_startup(self) -> None:
        Adw.Application.do_startup(self)
        install_app_icon()

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
        resize_png_if_needed(self.output_path, self.max_output_width)
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
        "--max-output-width",
        type=int,
        default=MAX_OUTPUT_WIDTH,
        help="resize the saved PNG to this width; use 0 to keep native size",
    )
    args = parser.parse_args(argv)

    output_path = Path(args.output).expanduser()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    Adw.init()
    with tempfile.TemporaryDirectory(prefix="mini-eq-screenshot-") as config_dir:
        app = DemoScreenshotApplication(
            output_path,
            Path(config_dir),
            args.delay_ms,
            args.width,
            args.height,
            args.max_output_width,
        )
        return app.run([])


if __name__ == "__main__":
    raise SystemExit(main())
