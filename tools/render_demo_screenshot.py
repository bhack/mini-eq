from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

import gi

gi.require_version("Adw", "1")

from demo_runtime import DEMO_PRESET_NAME, DemoController
from gi.repository import Adw, GLib

from mini_eq import core
from mini_eq.desktop_integration import APP_ID
from mini_eq.screenshot import capture_widget_to_png
from mini_eq.window import MiniEqWindow

SCREENSHOT_DELAY_MS = 1400


class DemoScreenshotApplication(Adw.Application):
    def __init__(self, output_path: Path, config_dir: Path, delay_ms: int) -> None:
        super().__init__(application_id=f"{APP_ID}.DemoScreenshot")
        self.output_path = output_path
        self.config_dir = config_dir
        self.delay_ms = delay_ms
        self.controller = DemoController()
        self.window: MiniEqWindow | None = None

    def do_startup(self) -> None:
        Adw.Application.do_startup(self)

    def do_activate(self) -> None:
        core.PRESET_STORAGE_DIR = self.config_dir / "mini-eq" / "output"
        core.write_mini_eq_preset_file(
            core.preset_path_for_name(DEMO_PRESET_NAME),
            self.controller.build_preset_payload(DEMO_PRESET_NAME),
        )

        self.window = MiniEqWindow(self, self.controller, auto_route=True)
        self.window.current_preset_name = DEMO_PRESET_NAME
        self.window.saved_preset_signature = self.controller.state_signature()
        self.window.refresh_preset_list()
        self.window.set_visible(True)
        self.window.present()
        self.window.schedule_post_present_setup()
        GLib.timeout_add(self.delay_ms, self.on_capture_timeout)

    def on_capture_timeout(self) -> bool:
        if self.window is None:
            raise RuntimeError("window is not available")

        capture_widget_to_png(self.window, self.output_path)
        print(f"saved screenshot to {self.output_path}")
        self.window.prepare_for_shutdown()
        self.quit()
        return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render a neutral Mini EQ release screenshot.")
    parser.add_argument("output", nargs="?", default="docs/screenshots/mini-eq.png", help="PNG output path")
    parser.add_argument("--delay-ms", type=int, default=SCREENSHOT_DELAY_MS, help="delay before capture")
    args = parser.parse_args(argv)

    output_path = Path(args.output).expanduser()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    Adw.init()
    with tempfile.TemporaryDirectory(prefix="mini-eq-screenshot-") as config_dir:
        app = DemoScreenshotApplication(output_path, Path(config_dir), args.delay_ms)
        return app.run([])


if __name__ == "__main__":
    raise SystemExit(main())
