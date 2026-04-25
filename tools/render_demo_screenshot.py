from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

import gi

gi.require_version("Adw", "1")

from gi.repository import Adw, GLib

from mini_eq import core
from mini_eq.core import EQ_MODES, FILTER_TYPES, PRESET_VERSION, EqBand, eq_band_to_dict
from mini_eq.desktop_integration import APP_ID
from mini_eq.screenshot import capture_widget_to_png
from mini_eq.window import MiniEqWindow
from mini_eq.wireplumber_backend import WirePlumberNode

SCREENSHOT_DELAY_MS = 1400
DEMO_PRESET_NAME = "Studio Reference"
DEMO_OUTPUT_NAME = "studio-monitor"
DEMO_OUTPUT_LABEL = "Studio Monitor"
DEMO_VIRTUAL_SINK_LABEL = "Mini EQ"


class DemoController:
    def __init__(self) -> None:
        self.output_sink = DEMO_OUTPUT_NAME
        self.virtual_sink_name = DEMO_VIRTUAL_SINK_LABEL
        self.follow_default_output = True
        self.eq_enabled = True
        self.eq_mode = EQ_MODES["Live PipeWire"]
        self.preamp_db = -4.5
        self.default_bands = core.default_eq_bands()
        self.bands = self.build_demo_bands()
        self.status_callback = None
        self.outputs_changed_callback = None
        self.analyzer_levels_callback = None
        self.analyzer_enabled = False
        self.route_enabled = False
        self.demo_sink = WirePlumberNode(
            local_id=1,
            bound_id=101,
            object_serial="101",
            media_class="Audio/Sink",
            node_name=DEMO_OUTPUT_NAME,
            node_description=DEMO_OUTPUT_LABEL,
            application_name=None,
            node_dont_move=False,
            properties={
                "audio.channels": "2",
                "audio.rate": "48000",
                "device.api": "alsa",
                "device.description": DEMO_OUTPUT_LABEL,
                "node.max-latency": "1024/48000",
            },
        )

    def build_demo_bands(self) -> list[EqBand]:
        bands = core.inactive_eq_bands()
        demo_points = (
            (32.0, 1.8, 0.80),
            (63.0, 2.7, 0.90),
            (125.0, 1.2, 1.00),
            (250.0, -1.8, 1.10),
            (500.0, -0.8, 1.20),
            (1000.0, 0.7, 1.10),
            (2000.0, 1.5, 1.00),
            (4000.0, -1.1, 1.15),
            (8000.0, 1.0, 1.00),
            (16000.0, 0.6, 0.90),
        )

        for index, (frequency, gain_db, q_value) in enumerate(demo_points):
            bands[index] = EqBand(
                filter_type=FILTER_TYPES["Bell"],
                frequency=frequency,
                gain_db=gain_db,
                q=q_value,
            )

        return bands

    def state_signature(self) -> str:
        return json.dumps(
            {
                "eq_enabled": self.eq_enabled,
                "eq_mode": self.eq_mode,
                "preamp_db": self.preamp_db,
                "bands": [eq_band_to_dict(band) for band in self.bands],
            },
            sort_keys=True,
            separators=(",", ":"),
        )

    def build_preset_payload(self, preset_name: str | None = None) -> dict[str, object]:
        payload: dict[str, object] = {
            "version": PRESET_VERSION,
            "eq_enabled": self.eq_enabled,
            "eq_mode": self.eq_mode,
            "preamp_db": self.preamp_db,
            "bands": [eq_band_to_dict(band) for band in self.bands],
        }
        if preset_name:
            payload["name"] = preset_name
        return payload

    def list_sinks(self) -> list[WirePlumberNode]:
        return [self.demo_sink]

    def list_output_sink_names(self) -> list[str]:
        return [DEMO_OUTPUT_NAME]

    def get_sink(self, sink_name: str | None) -> WirePlumberNode | None:
        return self.demo_sink if sink_name == DEMO_OUTPUT_NAME else None

    def get_default_output_sink_name(self) -> str:
        return DEMO_OUTPUT_NAME

    def is_valid_output_sink(self, sink_name: str) -> bool:
        return sink_name == DEMO_OUTPUT_NAME

    def set_status_callback(self, callback) -> None:
        self.status_callback = callback

    def set_outputs_changed_callback(self, callback) -> None:
        self.outputs_changed_callback = callback

    def set_analyzer_levels_callback(self, callback) -> None:
        self.analyzer_levels_callback = callback

    def set_analyzer_enabled(self, enabled: bool) -> None:
        self.analyzer_enabled = enabled

    def route_system_audio(self, enabled: bool) -> None:
        self.route_enabled = enabled

    def follow_system_default_output(self) -> None:
        self.follow_default_output = True

    def change_output_sink(self, sink_name: str) -> None:
        if sink_name != DEMO_OUTPUT_NAME:
            raise ValueError(f"unknown demo output: {sink_name}")
        self.output_sink = sink_name
        self.follow_default_output = False

    def reset_state(self) -> None:
        self.bands = self.build_demo_bands()

    def emit_status(self, message: str) -> None:
        if self.status_callback is not None:
            self.status_callback(message)

    def shutdown(self) -> None:
        pass


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
