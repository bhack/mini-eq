from __future__ import annotations

from collections.abc import Callable

from gi.repository import GLib

from .core import OUTPUT_CLIENT_NAME, VIRTUAL_SINK_BASE
from .glib_utils import destroy_glib_source
from .wireplumber_backend import STREAM_OUTPUT_AUDIO, WirePlumberBackend, WirePlumberError, WirePlumberNode


class WirePlumberStreamRouter:
    def __init__(
        self,
        virtual_sink_name: str,
        internal_output_name: str,
        status_callback: Callable[[str], None],
        backend: WirePlumberBackend | None = None,
    ) -> None:
        self.virtual_sink_name = virtual_sink_name
        self.internal_output_name = internal_output_name
        self.status_callback = status_callback
        self.backend = backend or WirePlumberBackend()
        self.owns_backend = backend is None
        self.enabled = False
        self.accept_stream_events = False
        self.event_source_id = 0
        self.object_added_handler_id = 0
        self.routed_stream_ids: set[int] = set()
        self.output_sink_name: str | None = None

    def emit_status(self, message: str) -> None:
        self.status_callback(message)

    def set_output_sink_name(self, sink_name: str) -> None:
        self.output_sink_name = sink_name

    def _is_internal_stream(self, stream: WirePlumberNode) -> bool:
        node_name = stream.node_name or ""
        app_name = stream.application_name or ""
        return (
            app_name == OUTPUT_CLIENT_NAME
            or node_name == self.internal_output_name
            or node_name.startswith(VIRTUAL_SINK_BASE)
            or node_name.startswith(f"{self.virtual_sink_name}.")
        )

    def iter_routable_output_streams(self) -> list[WirePlumberNode]:
        return [stream for stream in self.backend.list_output_streams() if not self._is_internal_stream(stream)]

    def stream_targets_node(self, stream_id: int, target_node_name: str) -> bool:
        try:
            return self.backend.stream_targets_node(stream_id, target_node_name)
        except Exception:
            return False

    def is_stale_stream_error(self, exc: Exception, stream_id: int) -> bool:
        return isinstance(exc, WirePlumberError) and str(exc) == f"output stream not found: {stream_id}"

    def route_output_streams(self) -> int:
        routed_now = 0

        for stream in self.iter_routable_output_streams():
            was_tracked = stream.bound_id in self.routed_stream_ids

            if not was_tracked or not self.stream_targets_node(stream.bound_id, self.virtual_sink_name):
                try:
                    self.backend.move_stream_to_target(stream.bound_id, self.virtual_sink_name)
                except Exception as exc:
                    if self.is_stale_stream_error(exc, stream.bound_id):
                        self.routed_stream_ids.discard(stream.bound_id)
                        continue
                    raise

                if not was_tracked:
                    routed_now += 1

            self.routed_stream_ids.add(stream.bound_id)

        return routed_now

    def restore_output_streams(self) -> int:
        if not self.output_sink_name:
            self.routed_stream_ids.clear()
            return 0

        streams = {stream.bound_id: stream for stream in self.backend.list_output_streams()}
        restored = 0

        for stream_id in list(self.routed_stream_ids):
            stream = streams.get(stream_id)
            if stream is None or self._is_internal_stream(stream):
                continue

            try:
                self.backend.move_stream_to_target(stream_id, self.output_sink_name)
            except Exception as exc:
                if self.is_stale_stream_error(exc, stream_id):
                    self.routed_stream_ids.discard(stream_id)
                    continue
                raise
            restored += 1

        self.routed_stream_ids.clear()
        return restored

    def refresh(self) -> bool:
        if not self.enabled:
            return False

        try:
            routed_now = self.route_output_streams()
            if routed_now > 0:
                self.emit_status(f"routed {routed_now} stream(s) to {self.virtual_sink_name}")
        except Exception as exc:
            self.emit_status(f"routing warning: {exc}")

        return False

    def on_stream_event_idle(self) -> bool:
        self.event_source_id = 0

        if not self.accept_stream_events:
            return False

        return self.refresh()

    def handle_object_added(self, _manager, node) -> None:
        if not self.accept_stream_events:
            return

        try:
            stream = self.backend.node_from_proxy(node)
        except Exception:
            stream = None

        if stream is not None and stream.media_class != STREAM_OUTPUT_AUDIO:
            return

        if self.event_source_id == 0:
            self.event_source_id = GLib.idle_add(self.on_stream_event_idle)

    def start_monitoring(self) -> None:
        self.backend.connect()
        self.accept_stream_events = True

        if self.object_added_handler_id == 0:
            self.object_added_handler_id = self.backend.connect_object_added(self.handle_object_added)

        self.refresh()

    def stop_monitoring(self) -> None:
        self.accept_stream_events = False

        if self.event_source_id > 0:
            destroy_glib_source(self.event_source_id)
            self.event_source_id = 0

        if self.object_added_handler_id > 0:
            self.backend.disconnect_node_manager_handler(self.object_added_handler_id)
            self.object_added_handler_id = 0

    def enable(self) -> None:
        self.enabled = True
        self.start_monitoring()

    def disable(self, announce: bool = True) -> None:
        if not self.enabled and not self.routed_stream_ids:
            return

        self.enabled = False
        self.stop_monitoring()
        restored = self.restore_output_streams()
        if announce and restored > 0:
            self.emit_status(f"restored {restored} stream(s)")

    def close(self) -> None:
        self.stop_monitoring()
        if self.owns_backend:
            self.backend.close()
