from __future__ import annotations

import json
import math

from mini_eq import core
from mini_eq.analyzer import ANALYZER_BIN_COUNT
from mini_eq.core import EQ_MODES, FILTER_TYPES, PRESET_VERSION, EqBand, eq_band_to_dict
from mini_eq.wireplumber_backend import WirePlumberNode

DEMO_PRESET_NAME = "Studio Reference"
DEMO_OUTPUT_NAME = "studio-monitor"
DEMO_OUTPUT_LABEL = "Studio Monitor"
DEMO_VIRTUAL_SINK_LABEL = "Mini EQ"


def demo_analyzer_levels(count: int = ANALYZER_BIN_COUNT) -> list[float]:
    levels: list[float] = []
    for index in range(count):
        phase = (index / max(count - 1, 1)) * math.pi * 4.0
        envelope = 0.58 + (0.34 * (0.5 + 0.5 * math.sin(phase + 1.2)))
        tilt = 1.0 - (index / max(count - 1, 1)) * 0.30
        levels.append(max(0.08, envelope * tilt))
    return levels


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

    def default_state_signature(self) -> str:
        return self.state_signature()

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

    def set_analyzer_enabled(self, enabled: bool) -> bool:
        self.analyzer_enabled = enabled
        return True

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
