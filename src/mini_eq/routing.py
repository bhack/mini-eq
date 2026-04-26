from __future__ import annotations

import json
import sys
import time
from collections.abc import Callable
from dataclasses import replace

from gi.repository import GLib

from .analyzer import ANALYZER_RESPONSE_DEFAULT, ANALYZER_RESPONSE_MAX, ANALYZER_RESPONSE_MIN, OutputSpectrumAnalyzer
from .core import (
    EQ_FREQUENCY_MAX_HZ,
    EQ_FREQUENCY_MIN_HZ,
    EQ_GAIN_MAX_DB,
    EQ_GAIN_MIN_DB,
    EQ_MODES,
    EQ_PREAMP_MAX_DB,
    EQ_PREAMP_MIN_DB,
    EQ_Q_MAX,
    EQ_Q_MIN,
    FILTER_OUTPUT_SUFFIX,
    MAX_BANDS,
    PRESET_VERSION,
    SAMPLE_RATE,
    VIRTUAL_SINK_BASE,
    AudioBackendError,
    EqBand,
    bands_have_solo,
    clamp,
    default_eq_bands,
    eq_band_from_dict,
    eq_band_to_dict,
    inactive_eq_bands,
    parse_apo_file,
    sanitize_preset_name,
)
from .filter_chain import (
    build_builtin_biquad_filter_chain_module_args,
    builtin_biquad_band_control_values,
    builtin_biquad_control_values,
    builtin_biquad_preamp_control_values,
)
from .glib_utils import destroy_glib_source
from .wireplumber_backend import (
    DEFAULT_AUDIO_SINK_KEY,
    DEFAULT_CONFIGURED_AUDIO_SINK_KEY,
    WirePlumberBackend,
    WirePlumberNode,
    node_sample_rate,
)
from .wireplumber_stream_router import WirePlumberStreamRouter


class SystemWideEqController:
    def __init__(self, output_sink: str | None) -> None:
        self.output_backend = WirePlumberBackend()
        self.output_backend.connect()
        self.virtual_sink_name = self.pick_virtual_sink_name()
        self.original_default_sink = self.get_default_output_sink_name()
        self.follow_default_output = output_sink is None
        self.output_sink = output_sink or self.original_default_sink
        self.filter_output_name = f"{self.virtual_sink_name}{FILTER_OUTPUT_SUFFIX}"
        self.engine_module = None
        self.filter_node_id: int | None = None
        self.output_event_source_id = 0
        self.output_object_added_handler_id = 0
        self.output_object_removed_handler_id = 0
        self.output_metadata_changed_handler_id = 0
        self.accept_output_events = False
        self.routed = False
        self.running = False
        self.shutting_down = False
        self.status_callback: Callable[[str], None] | None = None
        self.outputs_changed_callback: Callable[[], None] | None = None
        self.analyzer_levels_callback: Callable[[list[float]], None] | None = None
        self.eq_enabled = True
        self.eq_mode = next(iter(EQ_MODES.values()))
        self.preamp_db = 0.0
        self.default_bands: list[EqBand] = self.build_default_bands()
        self.bands: list[EqBand] = [replace(band) for band in self.default_bands]
        self.stream_router: WirePlumberStreamRouter | None = None
        self.output_analyzer: OutputSpectrumAnalyzer | None = None
        self.analyzer_response_speed = ANALYZER_RESPONSE_DEFAULT

        if not self.is_valid_output_sink(self.output_sink):
            raise AudioBackendError("output sink cannot be a Mini EQ virtual sink")

        if not self.output_sink or self.get_sink(self.output_sink) is None:
            raise AudioBackendError(f"output sink not found: {self.output_sink}")

    def emit_status(self, message: str) -> None:
        if getattr(self, "shutting_down", False):
            return

        if self.status_callback is not None:
            self.status_callback(message)

        print(message, file=sys.stderr)

    def set_status_callback(self, callback: Callable[[str], None] | None) -> None:
        self.status_callback = callback

    def set_outputs_changed_callback(self, callback: Callable[[], None] | None) -> None:
        self.outputs_changed_callback = callback

    def set_analyzer_levels_callback(self, callback: Callable[[list[float]], None] | None) -> None:
        self.analyzer_levels_callback = callback

        if self.output_analyzer is not None:
            self.output_analyzer.set_levels_callback(callback)

    def list_sinks(self) -> list[WirePlumberNode]:
        return self.output_backend.list_audio_sinks()

    def list_output_sink_names(self) -> list[str]:
        return [
            sink.node_name
            for sink in self.list_sinks()
            if sink.node_name is not None and not sink.node_name.startswith(VIRTUAL_SINK_BASE)
        ]

    def get_sink(self, sink_name: str) -> WirePlumberNode | None:
        if not sink_name:
            return None

        return self.output_backend.audio_sink_by_name(sink_name)

    def get_default_output_sink_name(self) -> str:
        defaults = self.output_backend.defaults()
        return defaults.default_audio_sink or defaults.configured_audio_sink or ""

    def is_valid_output_sink(self, sink_name: str) -> bool:
        return bool(sink_name) and not sink_name.startswith(VIRTUAL_SINK_BASE)

    def ensure_stream_router(self) -> WirePlumberStreamRouter:
        if self.stream_router is None:
            self.stream_router = WirePlumberStreamRouter(
                self.virtual_sink_name,
                self.filter_output_name,
                self.emit_status,
                self.output_backend,
            )

        self.stream_router.set_output_sink_name(self.output_sink)
        return self.stream_router

    def ensure_output_analyzer(self) -> OutputSpectrumAnalyzer:
        output_sink = self.get_sink(self.output_sink)
        output_sink_description = output_sink.node_description if output_sink is not None else None

        if self.output_analyzer is None:
            self.output_analyzer = OutputSpectrumAnalyzer(
                self.output_sink,
                self.analyzer_levels_callback,
                self.emit_status,
                output_sink_description,
            )

        self.output_analyzer.set_output_sink_name(self.output_sink, output_sink_description)
        self.output_analyzer.set_levels_callback(self.analyzer_levels_callback)
        self.output_analyzer.set_response_speed(self.analyzer_response_speed)
        return self.output_analyzer

    def prepare_output_analyzer(self) -> bool:
        analyzer = self.ensure_output_analyzer()
        return analyzer.prepare()

    def set_analyzer_enabled(self, enabled: bool) -> bool:
        analyzer = self.ensure_output_analyzer()

        if not enabled:
            return analyzer.set_enabled(False)

        if self.running and analyzer.client is None:
            self.stop_engine(announce=False)
            try:
                started = analyzer.set_enabled(True)
                if not started:
                    analyzer.set_enabled(False)
                    self.restore_engine_after_analyzer_failure()
                    return False
                self.start_engine()
            except Exception:
                analyzer.set_enabled(False)
                try:
                    self.restore_engine_after_analyzer_failure()
                except Exception as restore_exc:
                    self.emit_status(f"filter-chain restore after analyzer failure failed: {restore_exc}")
                raise

            if self.routed and self.stream_router is not None:
                self.stream_router.route_output_streams()

            return started

        return analyzer.set_enabled(enabled)

    def set_analyzer_response_speed(self, speed: float) -> None:
        self.analyzer_response_speed = clamp(float(speed), ANALYZER_RESPONSE_MIN, ANALYZER_RESPONSE_MAX)
        if self.output_analyzer is not None:
            self.output_analyzer.set_response_speed(self.analyzer_response_speed)

    def switch_output_sink(self, sink_name: str, explicit: bool) -> None:
        if not sink_name or sink_name == self.output_sink:
            if explicit:
                self.follow_default_output = False
            return

        if not self.is_valid_output_sink(sink_name):
            raise AudioBackendError("output sink cannot point to a Mini EQ virtual sink")

        if self.get_sink(sink_name) is None:
            raise AudioBackendError(f"output sink not found: {sink_name}")

        if explicit:
            self.follow_default_output = False

        self.output_sink = sink_name
        if self.stream_router is not None:
            self.stream_router.set_output_sink_name(sink_name)
        if self.output_analyzer is not None:
            output_sink = self.get_sink(sink_name)
            output_sink_description = output_sink.node_description if output_sink is not None else None
            self.output_analyzer.set_output_sink_name(sink_name, output_sink_description)

        self.restart_engine()

        if self.stream_router is not None and self.routed:
            self.stream_router.start_monitoring()

    def follow_system_default_output(self) -> None:
        self.follow_default_output = True
        self.refresh_followed_output_sink()

    def refresh_followed_output_sink(self) -> bool:
        if not self.follow_default_output:
            return False

        default_sink = self.get_default_output_sink_name()

        if self.is_valid_output_sink(default_sink) and self.get_sink(default_sink) is not None:
            try:
                self.switch_output_sink(default_sink, explicit=False)
            except Exception as exc:
                self.emit_status(f"default output follow warning: {exc}")

        return True

    def schedule_output_event_refresh(self) -> None:
        if not self.accept_output_events:
            return

        if self.output_event_source_id == 0:
            self.output_event_source_id = GLib.idle_add(self.on_output_event_idle)

    def handle_output_object_added(self, _manager, proxy) -> None:
        if not self.accept_output_events:
            return

        try:
            node = self.output_backend.node_from_proxy(proxy)
        except Exception:
            return

        if node.is_audio_sink:
            self.schedule_output_event_refresh()

    def handle_output_object_removed(self, _manager, _proxy) -> None:
        # Removed proxies may no longer expose stable properties. Refreshing the
        # output list is cheap enough and keeps the selector accurate.
        self.schedule_output_event_refresh()

    def handle_output_metadata_changed(
        self,
        _metadata,
        subject: int,
        key: str,
        _type_name: str | None,
        _value: str | None,
    ) -> None:
        if subject == 0 and key in {DEFAULT_AUDIO_SINK_KEY, DEFAULT_CONFIGURED_AUDIO_SINK_KEY}:
            self.output_backend.remember_default_metadata_change(key, _value)
            self.schedule_output_event_refresh()

    def on_output_event_idle(self) -> bool:
        self.output_event_source_id = 0

        if not self.accept_output_events:
            return False

        self.refresh_followed_output_sink()

        if self.outputs_changed_callback is not None:
            self.outputs_changed_callback()

        return False

    def start_output_event_monitoring(self) -> None:
        self.accept_output_events = True

        if self.output_object_added_handler_id == 0:
            self.output_object_added_handler_id = self.output_backend.connect_object_added(
                self.handle_output_object_added
            )

        if self.output_object_removed_handler_id == 0:
            self.output_object_removed_handler_id = self.output_backend.connect_object_removed(
                self.handle_output_object_removed
            )

        if self.output_metadata_changed_handler_id == 0:
            self.output_metadata_changed_handler_id = self.output_backend.connect_metadata_changed(
                self.handle_output_metadata_changed
            )

        self.refresh_followed_output_sink()

        if self.outputs_changed_callback is not None:
            self.outputs_changed_callback()

    def stop_output_event_monitoring(self) -> None:
        self.accept_output_events = False

        if self.output_event_source_id > 0:
            destroy_glib_source(self.output_event_source_id)
            self.output_event_source_id = 0

        if self.output_object_added_handler_id > 0:
            self.output_backend.disconnect_node_manager_handler(self.output_object_added_handler_id)
            self.output_object_added_handler_id = 0

        if self.output_object_removed_handler_id > 0:
            self.output_backend.disconnect_node_manager_handler(self.output_object_removed_handler_id)
            self.output_object_removed_handler_id = 0

        if self.output_metadata_changed_handler_id > 0:
            self.output_backend.disconnect_metadata_handler(self.output_metadata_changed_handler_id)
            self.output_metadata_changed_handler_id = 0

    def pick_virtual_sink_name(self) -> str:
        existing = {sink.node_name for sink in self.list_sinks() if sink.node_name is not None}

        if VIRTUAL_SINK_BASE not in existing:
            return VIRTUAL_SINK_BASE

        index = 1

        while f"{VIRTUAL_SINK_BASE}_{index}" in existing:
            index += 1

        return f"{VIRTUAL_SINK_BASE}_{index}"

    def route_system_audio(self, enabled: bool, announce: bool = True, *, refresh_output: bool = True) -> None:
        if enabled and getattr(self, "shutting_down", False):
            return

        if refresh_output:
            self.refresh_followed_output_sink()

        stream_router = self.ensure_stream_router()

        if enabled and not self.routed:
            stream_router.enable()
            self.routed = True
            if announce:
                self.emit_status(f"system audio routed to {self.virtual_sink_name}")
            return

        if not enabled and self.routed:
            stream_router.disable(announce=announce)
            self.routed = False
            if announce:
                self.emit_status("system audio routing disabled")
            return

    def build_default_bands(self) -> list[EqBand]:
        return default_eq_bands()

    def wait_for_virtual_sink(self, timeout_seconds: float = 3.0) -> None:
        deadline = time.monotonic() + timeout_seconds

        while time.monotonic() < deadline:
            try:
                self.output_backend.sync()
            except Exception:
                pass

            if self.get_sink(self.virtual_sink_name) is not None:
                return

            time.sleep(0.05)

        raise RuntimeError(f"virtual sink did not appear: {self.virtual_sink_name}")

    def wait_for_filter_node(self, timeout_seconds: float = 3.0) -> None:
        deadline = time.monotonic() + timeout_seconds

        while time.monotonic() < deadline:
            node_id = self.find_filter_node_id()

            if node_id is not None:
                self.filter_node_id = node_id
                return

            time.sleep(0.05)

        raise RuntimeError(f"filter-chain did not create {self.virtual_sink_name}")

    def find_filter_node_id(self) -> int | None:
        sink = self.get_sink(self.virtual_sink_name)
        return sink.bound_id if sink is not None else None

    def active_sample_rate(self) -> float:
        for sink_name in (self.virtual_sink_name, self.output_sink):
            rate = node_sample_rate(self.get_sink(sink_name))
            if rate > 0:
                return rate

        return SAMPLE_RATE

    def build_filter_chain_module_args(self) -> str:
        return build_builtin_biquad_filter_chain_module_args(
            bands=self.bands,
            preamp_db=self.preamp_db,
            eq_enabled=self.eq_enabled,
            virtual_sink_name=self.virtual_sink_name,
            filter_output_name=self.filter_output_name,
            output_sink=self.output_sink,
        )

    def start_engine(self) -> None:
        if self.engine_module is not None:
            return

        self.engine_module = self.output_backend.load_filter_chain_module(self.build_filter_chain_module_args())

        try:
            self.wait_for_virtual_sink()
            self.wait_for_filter_node()
            self.running = True
            self.emit_status(f"filter-chain PipeWire EQ ready: {self.virtual_sink_name} -> {self.output_sink}")
        except Exception:
            self.engine_module = None
            self.filter_node_id = None
            try:
                self.output_backend.sync()
            except Exception:
                pass
            raise

    def restore_engine_after_analyzer_failure(self) -> None:
        if self.running or self.engine_module is not None:
            return

        self.start_engine()
        if self.routed and self.stream_router is not None:
            self.stream_router.route_output_streams()

    def stop_engine(self, announce: bool = True) -> None:
        if self.engine_module is None:
            self.filter_node_id = None
            self.running = False
            return

        self.engine_module = None
        self.filter_node_id = None

        try:
            self.output_backend.sync()
        except Exception:
            pass

        self.running = False
        if announce:
            self.emit_status("filter-chain PipeWire EQ stopped")

    def restart_engine(self) -> None:
        was_running = self.running
        if not was_running:
            return

        self.stop_engine()
        self.start_engine()

        if self.routed and self.stream_router is not None:
            self.stream_router.route_output_streams()

    def set_filter_controls(self, controls: dict[str, float]) -> None:
        if self.filter_node_id is None or not self.running:
            return

        try:
            self.output_backend.set_node_params(self.filter_node_id, controls)
        except Exception as exc:
            self.emit_status(f"PipeWire EQ control update failed: {exc}")

    def apply_preamp_to_engine(self) -> None:
        self.set_filter_controls(builtin_biquad_preamp_control_values(self.preamp_db, self.eq_enabled))

    def apply_enabled_to_engine(self) -> None:
        self.apply_state_to_engine()

    def apply_band_to_engine(self, index: int) -> None:
        solo_active = bands_have_solo(self.bands)
        self.set_filter_controls(
            builtin_biquad_band_control_values(
                index,
                self.bands[index],
                self.eq_enabled,
                self.active_sample_rate(),
                solo_active,
            )
        )

    def apply_state_to_engine(self) -> None:
        controls = builtin_biquad_control_values(self.bands, self.preamp_db, self.eq_enabled, self.active_sample_rate())
        self.set_filter_controls(controls)

    def start(self) -> None:
        try:
            self.refresh_followed_output_sink()
            self.prepare_output_analyzer()
            self.start_engine()
            self.start_output_event_monitoring()
        except Exception:
            if self.stream_router is not None:
                self.stream_router.stop_monitoring()
            self.stop_engine()
            self.stop_output_event_monitoring()
            raise

    def shutdown(self) -> None:
        self.shutting_down = True
        self.status_callback = None
        self.outputs_changed_callback = None
        self.analyzer_levels_callback = None

        try:
            try:
                self.stop_output_event_monitoring()
            except Exception:
                pass
            if self.routed:
                try:
                    self.route_system_audio(False, announce=False, refresh_output=False)
                except Exception:
                    pass
        finally:
            try:
                if self.stream_router is not None:
                    self.stream_router.close()
                if self.output_analyzer is not None:
                    self.output_analyzer.close()
            finally:
                # Avoid explicit wp_core_disconnect() on shutdown. With WirePlumber 0.5
                # this can intermittently double-destroy PipeWire proxies after
                # restoring routed streams; process exit still tears the graph down.
                self.engine_module = None
                self.filter_node_id = None
                self.running = False

    def change_output_sink(self, sink_name: str) -> None:
        self.switch_output_sink(sink_name, explicit=True)

    def set_eq_mode(self, mode: int) -> None:
        self.eq_mode = int(mode)

    def set_preamp_db(self, value_db: float) -> None:
        preamp_db = clamp(value_db, EQ_PREAMP_MIN_DB, EQ_PREAMP_MAX_DB)
        if self.preamp_db == preamp_db:
            return
        self.preamp_db = preamp_db
        self.apply_preamp_to_engine()

    def set_eq_enabled(self, enabled: bool) -> None:
        eq_enabled = bool(enabled)
        if self.eq_enabled == eq_enabled:
            return
        self.eq_enabled = eq_enabled
        self.apply_enabled_to_engine()

    def set_band_type(self, index: int, filter_type: int) -> None:
        if self.bands[index].filter_type == filter_type:
            return
        self.bands[index].filter_type = filter_type
        self.apply_band_to_engine(index)

    def set_band_frequency(self, index: int, frequency: float, *, apply: bool = True) -> bool:
        frequency = clamp(frequency, EQ_FREQUENCY_MIN_HZ, EQ_FREQUENCY_MAX_HZ)
        if self.bands[index].frequency == frequency:
            return False
        self.bands[index].frequency = frequency
        if apply:
            self.apply_band_to_engine(index)
        return True

    def set_band_gain(self, index: int, gain_db: float, *, apply: bool = True) -> bool:
        gain_db = clamp(gain_db, EQ_GAIN_MIN_DB, EQ_GAIN_MAX_DB)
        if self.bands[index].gain_db == gain_db:
            return False
        self.bands[index].gain_db = gain_db
        if apply:
            self.apply_band_to_engine(index)
        return True

    def set_band_q(self, index: int, q_value: float, *, apply: bool = True) -> bool:
        q_value = clamp(q_value, EQ_Q_MIN, EQ_Q_MAX)
        if self.bands[index].q == q_value:
            return False
        self.bands[index].q = q_value
        if apply:
            self.apply_band_to_engine(index)
        return True

    def set_band_mute(self, index: int, muted: bool) -> None:
        muted = bool(muted)
        if self.bands[index].mute == muted:
            return
        self.bands[index].mute = muted
        self.apply_state_to_engine()

    def set_band_solo(self, index: int, solo: bool) -> None:
        solo = bool(solo)
        if self.bands[index].solo == solo:
            return
        self.bands[index].solo = solo
        self.apply_state_to_engine()

    def build_preset_payload(self, preset_name: str | None = None) -> dict[str, object]:
        payload: dict[str, object] = {
            "version": PRESET_VERSION,
            "preamp_db": float(self.preamp_db),
            "bands": [eq_band_to_dict(band) for band in self.bands],
        }
        if preset_name:
            payload["name"] = sanitize_preset_name(preset_name)

        return payload

    def state_signature(self) -> str:
        return json.dumps(self.build_preset_payload(), sort_keys=True, separators=(",", ":"))

    def apply_preset_payload(self, payload: dict[str, object]) -> None:
        version = int(payload.get("version", 0))
        if version > PRESET_VERSION:
            raise ValueError(f"preset version {version} is newer than this Mini EQ build")

        bands_data = payload.get("bands")
        if not isinstance(bands_data, list):
            raise ValueError("preset file does not contain a valid bands list")

        self.preamp_db = clamp(float(payload.get("preamp_db", 0.0)), EQ_PREAMP_MIN_DB, EQ_PREAMP_MAX_DB)
        self.bands = inactive_eq_bands()

        for index, band_data in enumerate(bands_data[:MAX_BANDS]):
            if not isinstance(band_data, dict):
                raise ValueError("preset bands must be JSON objects")

            self.bands[index] = eq_band_from_dict(band_data, self.bands[index])

        self.apply_state_to_engine()

    def reset_state(self) -> None:
        self.preamp_db = 0.0
        self.bands = [replace(band) for band in self.default_bands]
        self.apply_state_to_engine()

    def import_apo_preset(self, path: str) -> int:
        preamp, imported_bands = parse_apo_file(path)

        self.bands = inactive_eq_bands()
        self.eq_enabled = True
        self.preamp_db = clamp(preamp, EQ_PREAMP_MIN_DB, EQ_PREAMP_MAX_DB)

        for index, band in enumerate(imported_bands):
            self.bands[index] = band

        self.apply_state_to_engine()

        imported_count = len(imported_bands)
        self.emit_status(f"loaded APO preset: {imported_count} band(s), preamp {preamp:.1f} dB")
        return imported_count
