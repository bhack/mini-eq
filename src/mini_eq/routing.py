from __future__ import annotations

import json
import sys
from collections.abc import Callable
from dataclasses import replace

from gi.repository import GLib

from .analyzer import ANALYZER_RESPONSE_DEFAULT, AnalyzerLoudnessSnapshot, OutputSpectrumAnalyzer
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
from .pipewire_backend import (
    DEFAULT_AUDIO_SINK_KEY,
    DEFAULT_CONFIGURED_AUDIO_SINK_KEY,
    PipeWireBackend,
    PipeWireNode,
    node_sample_rate,
    parse_metadata_node_name,
)
from .pipewire_routes import PipeWireOutputPresetTarget
from .pipewire_stream_router import PipeWireStreamRouter


class SystemWideEqController:
    def __init__(self, output_sink: str | None) -> None:
        self.output_backend = PipeWireBackend()
        self.output_backend.connect()
        self.virtual_sink_name = self.pick_virtual_sink_name()
        self.original_default_sink = self.resolve_default_output_sink_name()
        self.follow_default_output = output_sink is None
        self.output_sink = output_sink or self.original_default_sink
        self._output_preset_target_sink: str | None = None
        self._output_preset_target: PipeWireOutputPresetTarget | None = None
        self.filter_output_name = f"{self.virtual_sink_name}{FILTER_OUTPUT_SUFFIX}"
        self.engine_module = None
        self.engine_start_watch = None
        self.engine_start_pending = False
        self.filter_node_id: int | None = None
        self.output_event_source_id = 0
        self.pending_followed_output_sink: str | None = None
        self.pending_current_output_sink_refresh = False
        self.output_object_added_handler_id = 0
        self.output_object_removed_handler_id = 0
        self.output_metadata_changed_handler_id = 0
        self.output_route_param_handler_id = 0
        self.output_route_param_device_id = 0
        self.accept_output_events = False
        self.routed = False
        self.running = False
        self.shutting_down = False
        self.status_callback: Callable[[str], None] | None = None
        self.outputs_changed_callback: Callable[[], None] | None = None
        self.analyzer_levels_callback: Callable[[list[float]], None] | None = None
        self.analyzer_loudness_callback: Callable[[AnalyzerLoudnessSnapshot | None], None] | None = None
        self.eq_enabled = True
        self.eq_mode = next(iter(EQ_MODES.values()))
        self.preamp_db = 0.0
        self.default_bands: list[EqBand] = self.build_default_bands()
        self.bands: list[EqBand] = [replace(band) for band in self.default_bands]
        self.stream_router: PipeWireStreamRouter | None = None
        self.output_analyzer: OutputSpectrumAnalyzer | None = None
        self.analyzer_response_speed = ANALYZER_RESPONSE_DEFAULT

        if not self.is_valid_output_sink(self.output_sink):
            raise AudioBackendError("output sink cannot be a Mini EQ virtual sink")

        if not self.output_sink or self.get_sink(self.output_sink) is None:
            raise AudioBackendError(f"output sink not found: {self.output_sink}")

    def emit_status(self, message: str) -> None:
        if getattr(self, "shutting_down", False):
            return

        status_callback = getattr(self, "status_callback", None)
        if status_callback is not None:
            status_callback(message)

        print(message, file=sys.stderr)

    def set_status_callback(self, callback: Callable[[str], None] | None) -> None:
        self.status_callback = callback

    def set_outputs_changed_callback(self, callback: Callable[[], None] | None) -> None:
        self.outputs_changed_callback = callback

    def set_analyzer_levels_callback(self, callback: Callable[[list[float]], None] | None) -> None:
        self.analyzer_levels_callback = callback

        if self.output_analyzer is not None:
            self.output_analyzer.set_levels_callback(callback)

    def set_analyzer_loudness_callback(
        self,
        callback: Callable[[AnalyzerLoudnessSnapshot | None], None] | None,
    ) -> None:
        self.analyzer_loudness_callback = callback

        if self.output_analyzer is not None:
            self.output_analyzer.set_loudness_callback(callback)

    def list_sinks(self) -> list[PipeWireNode]:
        return self.output_backend.list_audio_sinks()

    def list_output_sink_names(self) -> list[str]:
        return [
            sink.node_name
            for sink in self.list_sinks()
            if sink.node_name is not None and not sink.node_name.startswith(VIRTUAL_SINK_BASE)
        ]

    def first_available_output_sink_name(self) -> str:
        return next(iter(self.list_output_sink_names()), "")

    def get_sink(self, sink_name: str) -> PipeWireNode | None:
        if not sink_name:
            return None

        return self.output_backend.audio_sink_by_name(sink_name)

    def filter_output_already_targets_sink(self, sink: PipeWireNode) -> bool:
        if not self.running or self.filter_node_id is None or not sink.object_serial:
            return False

        try:
            filter_output = self.output_backend.output_stream_by_name(self.filter_output_name)
            if filter_output is None:
                return False
            target = self.output_backend.stream_target(filter_output.bound_id)
        except Exception:
            return False

        return target.target_object == sink.object_serial

    def output_preset_keys(self) -> tuple[str, ...]:
        return self.output_preset_target().keys

    def output_preset_link_key(self) -> str:
        return self.output_preset_target().link_key

    def invalidate_output_preset_target(self) -> None:
        self._output_preset_target_sink = None
        self._output_preset_target = None

    def output_preset_target(self, *, refresh: bool = False) -> PipeWireOutputPresetTarget:
        cached_target = getattr(self, "_output_preset_target", None)
        cached_sink = getattr(self, "_output_preset_target_sink", None)
        if not refresh and cached_target is not None and cached_sink == self.output_sink:
            return cached_target

        target = self.output_backend.output_preset_target_for_sink_name(self.output_sink)
        self._output_preset_target_sink = self.output_sink
        self._output_preset_target = target
        return target

    def default_output_sink_candidates(self, *, refresh: bool = False, snapshot: bool = False) -> tuple[str, ...]:
        defaults = (
            self.output_backend.refresh_defaults(snapshot=snapshot) if refresh else self.output_backend.defaults()
        )
        return tuple(
            sink_name for sink_name in (defaults.configured_audio_sink, defaults.default_audio_sink) if sink_name
        )

    def get_default_output_sink_name(self, *, refresh: bool = False, snapshot: bool = False) -> str:
        candidates = self.default_output_sink_candidates(refresh=refresh, snapshot=snapshot)

        for sink_name in candidates:
            if self.is_valid_output_sink(sink_name) and self.get_sink(sink_name) is not None:
                return sink_name

        return next(iter(candidates), "")

    def resolve_default_output_sink_name(self) -> str:
        default_sink = self.get_default_output_sink_name(refresh=True)
        if self.is_valid_output_sink(default_sink) and self.get_sink(default_sink) is not None:
            return default_sink

        return self.first_available_output_sink_name()

    def is_valid_output_sink(self, sink_name: str) -> bool:
        return bool(sink_name) and not sink_name.startswith(VIRTUAL_SINK_BASE)

    def ensure_stream_router(self) -> PipeWireStreamRouter:
        if self.stream_router is None:
            self.stream_router = PipeWireStreamRouter(
                self.virtual_sink_name,
                self.filter_output_name,
                self.emit_status,
                self.output_backend,
                route_applied_callback=self.apply_state_to_engine,
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
                self.analyzer_loudness_callback,
            )

        self.output_analyzer.set_output_sink_name(self.output_sink, output_sink_description)
        self.output_analyzer.set_levels_callback(self.analyzer_levels_callback)
        self.output_analyzer.set_loudness_callback(self.analyzer_loudness_callback)
        self.output_analyzer.set_response_speed(self.analyzer_response_speed)
        return self.output_analyzer

    def prepare_output_analyzer(self) -> bool:
        analyzer = self.ensure_output_analyzer()
        return analyzer.prepare()

    def set_analyzer_enabled(self, enabled: bool) -> bool:
        self.refresh_followed_output_sink(snapshot=True)
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

                def on_ready() -> None:
                    if self.routed and self.stream_router is not None:
                        self.stream_router.route_output_streams()

                def on_error(exc: Exception) -> None:
                    analyzer.set_enabled(False)
                    self.emit_status(f"filter-chain restart after analyzer enable failed: {exc}")
                    self.restore_engine_after_analyzer_failure()

                self.start_engine(on_ready=on_ready, on_error=on_error)
            except Exception:
                analyzer.set_enabled(False)
                try:
                    self.restore_engine_after_analyzer_failure()
                except Exception as restore_exc:
                    self.emit_status(f"filter-chain restore after analyzer failure failed: {restore_exc}")
                raise

            return started

        return analyzer.set_enabled(enabled)

    def switch_output_sink(self, sink_name: str, explicit: bool) -> None:
        if not sink_name:
            if explicit:
                self.follow_default_output = False
            return

        if sink_name == self.output_sink:
            if explicit:
                self.follow_default_output = False

            output_sink = self.get_sink(sink_name)
            if output_sink is None:
                return

            self.refresh_output_route_param_monitor()
            if self.stream_router is not None:
                self.stream_router.set_output_sink_name(sink_name)
            if self.output_analyzer is not None:
                output_sink_description = output_sink.node_description if output_sink is not None else None
                self.output_analyzer.set_output_sink_name(sink_name, output_sink_description)

            if self.filter_output_already_targets_sink(output_sink):
                return

            if self.retarget_filter_output():
                return

            self.restart_engine()
            return

        if not self.is_valid_output_sink(sink_name):
            raise AudioBackendError("output sink cannot point to a Mini EQ virtual sink")

        if self.get_sink(sink_name) is None:
            raise AudioBackendError(f"output sink not found: {sink_name}")

        if explicit:
            self.follow_default_output = False

        self.output_sink = sink_name
        self.invalidate_output_preset_target()
        self.refresh_output_route_param_monitor()
        if self.stream_router is not None:
            self.stream_router.set_output_sink_name(sink_name)
        if self.output_analyzer is not None:
            output_sink = self.get_sink(sink_name)
            output_sink_description = output_sink.node_description if output_sink is not None else None
            self.output_analyzer.set_output_sink_name(sink_name, output_sink_description)

        if self.retarget_filter_output():
            if explicit:
                self.schedule_output_event_refresh()
            return

        self.restart_engine()
        if explicit:
            self.schedule_output_event_refresh()

    def follow_system_default_output(self) -> None:
        previous_output_sink = getattr(self, "output_sink", None)
        self.follow_default_output = True
        self.refresh_followed_output_sink(snapshot=True)
        if getattr(self, "output_sink", None) != previous_output_sink:
            self.schedule_output_event_refresh()

    def refresh_followed_output_sink(self, *, snapshot: bool = False) -> bool:
        if not getattr(self, "follow_default_output", False):
            return False

        for default_sink in self.default_output_sink_candidates(refresh=True, snapshot=snapshot):
            if not self.is_valid_output_sink(default_sink) or self.get_sink(default_sink) is None:
                continue
            try:
                self.switch_output_sink(default_sink, explicit=False)
            except Exception as exc:
                self.emit_status(f"default output follow warning: {exc}")
            break

        return True

    def refresh_followed_output_sink_from_event(self, sink_name: str | None) -> bool:
        if not self.follow_default_output:
            return False

        if sink_name and self.is_valid_output_sink(sink_name) and self.get_sink(sink_name) is not None:
            try:
                self.switch_output_sink(sink_name, explicit=False)
            except Exception as exc:
                self.emit_status(f"default output follow warning: {exc}")
            return True

        return self.refresh_followed_output_sink(snapshot=True)

    def schedule_output_event_refresh(self) -> None:
        if not getattr(self, "accept_output_events", False):
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
            if node.node_name == getattr(self, "output_sink", ""):
                self.pending_current_output_sink_refresh = True
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
            if getattr(self, "follow_default_output", False):
                sink_name = parse_metadata_node_name(_value)
                if sink_name and self.is_valid_output_sink(sink_name):
                    self.pending_followed_output_sink = sink_name
            self.schedule_output_event_refresh()

    def handle_output_route_param_changed(self) -> None:
        self.schedule_output_event_refresh()

    def refresh_output_route_param_monitor(self) -> None:
        if not getattr(self, "accept_output_events", False):
            return

        output_sink_name = getattr(self, "output_sink", "")
        if not output_sink_name:
            self.disconnect_output_route_param_monitor()
            return

        output_sink = self.get_sink(output_sink_name)
        device_id = output_sink.device_id if output_sink is not None else 0
        if device_id == getattr(self, "output_route_param_device_id", 0):
            return

        self.disconnect_output_route_param_monitor()
        self.output_route_param_device_id = device_id
        if device_id <= 0:
            return

        self.output_route_param_handler_id = self.output_backend.connect_device_route_changed(
            device_id,
            self.handle_output_route_param_changed,
        )
        if self.output_route_param_handler_id == 0:
            self.output_route_param_device_id = 0

    def disconnect_output_route_param_monitor(self) -> None:
        if getattr(self, "output_route_param_handler_id", 0) > 0:
            self.output_backend.disconnect_device_handler(self.output_route_param_handler_id)
            self.output_route_param_handler_id = 0

        self.output_route_param_device_id = 0

    def on_output_event_idle(self) -> bool:
        self.output_event_source_id = 0

        if not self.accept_output_events:
            return False

        self.invalidate_output_preset_target()
        pending_followed_output_sink = getattr(self, "pending_followed_output_sink", None)
        pending_current_output_sink_refresh = getattr(self, "pending_current_output_sink_refresh", False)
        self.pending_followed_output_sink = None
        self.pending_current_output_sink_refresh = False
        followed_output_refreshed = False
        if pending_followed_output_sink is not None:
            followed_output_refreshed = self.refresh_followed_output_sink_from_event(pending_followed_output_sink)
        else:
            followed_output_refreshed = self.refresh_followed_output_sink(snapshot=True)
        if (
            pending_current_output_sink_refresh
            and not followed_output_refreshed
            and self.get_sink(getattr(self, "output_sink", "")) is not None
        ):
            try:
                self.switch_output_sink(self.output_sink, explicit=False)
            except Exception as exc:
                self.emit_status(f"output refresh warning: {exc}")
        self.refresh_output_route_param_monitor()

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

        self.invalidate_output_preset_target()
        self.refresh_followed_output_sink(snapshot=True)
        self.refresh_output_route_param_monitor()

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

        self.disconnect_output_route_param_monitor()

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

        eq_enabled_for_route = False
        try:
            if enabled:
                if not self.running or self.filter_node_id is None:
                    raise RuntimeError("filter-chain PipeWire EQ is not ready")
                if not self.eq_enabled:
                    eq_enabled_for_route = True
                    self.set_eq_enabled(True)

            stream_router = self.ensure_stream_router()

            if enabled and not self.routed:
                stream_router.enable()
                self.routed = True
                self.apply_state_to_engine()
                if announce:
                    self.emit_status(f"system audio routed to {self.virtual_sink_name}")
                return

            if enabled and self.routed:
                self.apply_state_to_engine()
                return

            if not enabled and self.routed:
                stream_router.disable(announce=announce)
                self.routed = False
                if announce:
                    self.emit_status("system audio routing disabled")
                return
        except Exception:
            if eq_enabled_for_route:
                try:
                    self.set_eq_enabled(False)
                except Exception:
                    pass
            raise

    def build_default_bands(self) -> list[EqBand]:
        return default_eq_bands()

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

    def cancel_pending_engine_start(self) -> None:
        watch = getattr(self, "engine_start_watch", None)
        self.engine_start_watch = None
        self.engine_start_pending = False
        if watch is not None:
            watch.cancel()

    def start_engine(
        self,
        *,
        on_ready: Callable[[], None] | None = None,
        on_error: Callable[[Exception], None] | None = None,
    ) -> None:
        if self.running:
            if on_ready is not None:
                on_ready()
            return

        if getattr(self, "engine_start_pending", False):
            return

        self.engine_module = self.output_backend.load_filter_chain_module(self.build_filter_chain_module_args())
        self.engine_start_pending = True

        def fail(exc: Exception) -> None:
            self.engine_start_watch = None
            self.engine_start_pending = False
            self.engine_module = None
            self.filter_node_id = None
            try:
                self.output_backend.sync()
            except Exception:
                pass
            if on_error is not None:
                on_error(exc)
            else:
                self.emit_status(str(exc))

        def on_sink_ready(sink: PipeWireNode | None) -> None:
            self.engine_start_watch = None
            self.engine_start_pending = False

            if getattr(self, "shutting_down", False) or self.engine_module is None:
                return

            if sink is None:
                fail(RuntimeError(f"filter-chain did not create {self.virtual_sink_name}"))
                return

            self.filter_node_id = sink.bound_id
            self.running = True
            self.emit_status(f"filter-chain PipeWire EQ ready: {self.virtual_sink_name} -> {self.output_sink}")
            self.apply_state_to_engine()
            if on_ready is not None:
                on_ready()

        try:
            self.engine_start_watch = self.output_backend.watch_for_audio_sink(
                self.virtual_sink_name,
                on_sink_ready,
                timeout_ms=3000,
            )
        except Exception as exc:
            fail(exc)

    def retarget_filter_output(self) -> bool:
        if not self.running or self.filter_node_id is None:
            return False

        try:
            self.output_backend.move_named_output_stream_to_target(self.filter_output_name, self.output_sink)
            self.apply_state_to_engine()
            self.emit_status(f"filter-chain PipeWire EQ ready: {self.virtual_sink_name} -> {self.output_sink}")
            return True
        except Exception as exc:
            self.emit_status(f"filter-chain output retarget warning: {exc}")
            return False

    def restore_engine_after_analyzer_failure(self) -> None:
        if self.running or getattr(self, "engine_module", None) is not None:
            return

        def on_ready() -> None:
            if self.routed and self.stream_router is not None:
                self.stream_router.route_output_streams()

        self.start_engine(on_ready=on_ready, on_error=lambda exc: self.emit_status(str(exc)))

    def stop_engine(self, announce: bool = True) -> None:
        self.cancel_pending_engine_start()
        module = getattr(self, "engine_module", None)
        if module is None:
            self.filter_node_id = None
            self.running = False
            return

        self.engine_module = None
        self.filter_node_id = None

        try:
            self.output_backend.unload_filter_chain_module(module)
        except Exception as exc:
            self.emit_status(f"filter-chain PipeWire EQ unload warning: {exc}")

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

        stream_router = self.stream_router if self.routed else None
        if stream_router is not None:
            stream_router.stop_monitoring()
            try:
                stream_router.restore_output_streams()
            except Exception as exc:
                stream_router.emit_warning(exc)

        self.stop_engine(announce=False)

        def on_ready() -> None:
            if stream_router is not None:
                stream_router.start_monitoring(require_initial_route=True)

        def on_error(exc: Exception) -> None:
            if stream_router is not None:
                stream_router.emit_warning(exc)
            else:
                self.emit_status(str(exc))

        self.start_engine(on_ready=on_ready, on_error=on_error)

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

    def start(
        self,
        *,
        on_ready: Callable[[], None] | None = None,
        on_error: Callable[[Exception], None] | None = None,
    ) -> None:
        try:
            self.refresh_followed_output_sink()
            self.prepare_output_analyzer()
        except Exception as exc:
            if self.stream_router is not None:
                self.stream_router.stop_monitoring()
            self.stop_engine()
            self.stop_output_event_monitoring()
            if on_error is not None:
                on_error(exc)
                return
            raise

        def on_engine_ready() -> None:
            try:
                self.start_output_event_monitoring()
            except Exception as exc:
                if self.stream_router is not None:
                    self.stream_router.stop_monitoring()
                self.stop_engine()
                self.stop_output_event_monitoring()
                if on_error is not None:
                    on_error(exc)
                    return
                raise
            if on_ready is not None:
                on_ready()

        def on_engine_error(exc: Exception) -> None:
            if self.stream_router is not None:
                self.stream_router.stop_monitoring()
            self.stop_engine()
            self.stop_output_event_monitoring()
            if on_error is not None:
                on_error(exc)
            else:
                self.emit_status(str(exc))

        try:
            self.start_engine(on_ready=on_engine_ready, on_error=on_engine_error)
        except Exception as exc:
            on_engine_error(exc)
            if on_error is None:
                raise

    def shutdown(self) -> None:
        self.shutting_down = True
        self.status_callback = None
        self.outputs_changed_callback = None
        self.analyzer_levels_callback = None
        self.analyzer_loudness_callback = None

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
                try:
                    self.stop_engine(announce=False)
                except Exception:
                    pass
                try:
                    self.output_backend.close()
                except Exception:
                    pass
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

    def default_state_signature(self) -> str:
        payload = {
            "version": PRESET_VERSION,
            "preamp_db": 0.0,
            "bands": [eq_band_to_dict(band) for band in self.default_bands],
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))

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
