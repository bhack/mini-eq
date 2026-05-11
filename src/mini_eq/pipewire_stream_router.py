from __future__ import annotations

from collections.abc import Callable

from gi.repository import GLib

from .core import OUTPUT_CLIENT_NAME, VIRTUAL_SINK_BASE
from .glib_utils import destroy_glib_source
from .pipewire_backend import (
    STREAM_OUTPUT_AUDIO,
    PipeWireBackend,
    PipeWireBackendError,
    PipeWireLink,
    PipeWireNode,
    PipeWireStreamTarget,
)

BLOCKLIST_MEDIA_ROLES = {"event", "Notification"}
BLOCKLIST_STREAM_NAMES = {
    "GNOME Shell",
    "Mutter",
    "gsd-media-keys",
    "libcanberra",
    "speech-dispatcher",
    "speech-dispatcher-dummy",
    "speech-dispatcher-espeak-ng",
}


class PipeWireStreamRouter:
    def __init__(
        self,
        virtual_sink_name: str,
        internal_output_name: str,
        status_callback: Callable[[str], None],
        backend: PipeWireBackend | None = None,
        route_applied_callback: Callable[[], None] | None = None,
    ) -> None:
        self.virtual_sink_name = virtual_sink_name
        self.internal_output_name = internal_output_name
        self.status_callback = status_callback
        self.backend = backend or PipeWireBackend()
        self.route_applied_callback = route_applied_callback
        self.owns_backend = backend is None
        self.enabled = False
        self.accept_stream_events = False
        self.event_source_id = 0
        self.pending_route_applied_callback = False
        self.object_added_handler_id = 0
        self.routed_stream_ids: set[int] = set()
        self.routed_stream_targets: dict[int, PipeWireStreamTarget] = {}
        self.output_sink_name: str | None = None
        self.last_warning_message = ""

    def emit_status(self, message: str) -> None:
        self.status_callback(message)

    def emit_warning(self, exc: Exception) -> None:
        message = f"routing warning: {exc}"
        if message == self.last_warning_message:
            return

        self.last_warning_message = message
        self.emit_status(message)

    def set_output_sink_name(self, sink_name: str) -> None:
        self.output_sink_name = sink_name

    def _is_internal_stream(self, stream: PipeWireNode) -> bool:
        node_name = stream.node_name or ""
        app_name = stream.application_name or ""
        media_role = stream.property_value("media.role")
        return (
            app_name == OUTPUT_CLIENT_NAME
            or media_role in BLOCKLIST_MEDIA_ROLES
            or node_name in BLOCKLIST_STREAM_NAMES
            or app_name in BLOCKLIST_STREAM_NAMES
            or node_name == self.internal_output_name
            or node_name.startswith(VIRTUAL_SINK_BASE)
            or node_name.startswith(f"{self.virtual_sink_name}.")
        )

    def _target_object_matches_processing_path(self, target_object: str) -> bool:
        allowed_targets = {self.virtual_sink_name}
        if self.output_sink_name:
            allowed_targets.add(self.output_sink_name)

        for node_name in tuple(allowed_targets):
            try:
                node = self.backend.audio_sink_by_name(node_name)
            except Exception:
                node = None

            if node is None:
                continue
            if node.node_name:
                allowed_targets.add(node.node_name)
            if node.object_serial:
                allowed_targets.add(str(node.object_serial))

        return target_object in allowed_targets

    def _has_foreign_target_object(self, stream: PipeWireNode) -> bool:
        target_object = stream.property_value("target.object")
        return bool(target_object) and not self._target_object_matches_processing_path(target_object)

    def _virtual_sink_target_values(self) -> set[str]:
        values = {self.virtual_sink_name}
        try:
            virtual_sink = self.backend.audio_sink_by_name(self.virtual_sink_name)
        except Exception:
            virtual_sink = None

        if virtual_sink is not None:
            if virtual_sink.node_name:
                values.add(virtual_sink.node_name)
            if virtual_sink.object_serial:
                values.add(str(virtual_sink.object_serial))
            values.add(str(virtual_sink.bound_id))

        return values

    def _target_points_to_virtual_sink(self, target: PipeWireStreamTarget) -> bool:
        target_values = {value for value in (target.target_node, target.target_object) if value}
        return bool(target_values & self._virtual_sink_target_values())

    def _link_touches_virtual_sink(self, link: PipeWireLink) -> bool:
        try:
            virtual_sink = self.backend.audio_sink_by_name(self.virtual_sink_name)
        except Exception:
            virtual_sink = None

        if virtual_sink is None:
            return False

        return virtual_sink.bound_id in {link.output_node_id, link.input_node_id}

    def _stream_target_before_route(self, stream_bound_id: int) -> PipeWireStreamTarget:
        target = self.backend.stream_target(stream_bound_id)
        if self._target_points_to_virtual_sink(target):
            return PipeWireStreamTarget(None, None, None, None)
        return target

    def iter_routable_output_streams(self) -> list[PipeWireNode]:
        streams: list[PipeWireNode] = []
        for stream in self.backend.list_output_streams():
            if not self._is_internal_stream(stream) and not self._has_foreign_target_object(stream):
                streams.append(stream)

        return streams

    def is_stale_stream_error(self, exc: Exception, stream_id: int) -> bool:
        return isinstance(exc, PipeWireBackendError) and str(exc) == f"output stream not found: {stream_id}"

    def route_output_streams(self) -> int:
        routed_now = 0
        failures: list[Exception] = []

        for stream in self.iter_routable_output_streams():
            was_tracked = stream.bound_id in self.routed_stream_ids
            original_target = self.routed_stream_targets.get(stream.bound_id)

            try:
                if original_target is None:
                    original_target = self._stream_target_before_route(stream.bound_id)
                self.backend.move_stream_to_target(stream.bound_id, self.virtual_sink_name)
            except Exception as exc:
                if self.is_stale_stream_error(exc, stream.bound_id):
                    self.routed_stream_ids.discard(stream.bound_id)
                    self.routed_stream_targets.pop(stream.bound_id, None)
                    continue
                failures.append(exc)
                continue

            if not was_tracked:
                routed_now += 1

            self.routed_stream_ids.add(stream.bound_id)
            self.routed_stream_targets[stream.bound_id] = original_target

        if failures:
            raise failures[0]

        return routed_now

    def restore_output_streams(self) -> int:
        if not self.output_sink_name and not self.routed_stream_targets:
            self.routed_stream_ids.clear()
            self.routed_stream_targets.clear()
            return 0

        streams = {stream.bound_id: stream for stream in self.iter_routable_output_streams()}
        failures: list[Exception] = []
        restored = 0

        for stream_id in list(self.routed_stream_ids):
            stream = streams.get(stream_id)
            if stream is None:
                continue

            try:
                target = self.routed_stream_targets.get(stream_id)
                if target is not None:
                    self.backend.restore_stream_target(stream_id, target)
                elif self.output_sink_name:
                    self.backend.move_stream_to_target(stream_id, self.output_sink_name)
            except Exception as exc:
                if self.is_stale_stream_error(exc, stream_id):
                    self.routed_stream_ids.discard(stream_id)
                    self.routed_stream_targets.pop(stream_id, None)
                    continue
                failures.append(exc)
                continue
            restored += 1

        if failures:
            raise failures[0]

        self.routed_stream_ids.clear()
        self.routed_stream_targets.clear()
        return restored

    def refresh(self, *, raise_errors: bool = False) -> bool:
        if not self.enabled:
            return False

        try:
            routed_now = self.route_output_streams()
            if routed_now > 0:
                self.last_warning_message = ""
                self.emit_status(f"routed {routed_now} stream(s) to {self.virtual_sink_name}")
        except Exception as exc:
            self.emit_warning(exc)
            if raise_errors:
                raise

        return False

    def schedule_refresh(self, *, route_applied: bool = False) -> None:
        self.pending_route_applied_callback = self.pending_route_applied_callback or route_applied
        if self.event_source_id == 0:
            self.event_source_id = GLib.idle_add(self.on_stream_event_idle)

    def on_stream_event_idle(self) -> bool:
        self.event_source_id = 0

        if not self.accept_stream_events:
            self.pending_route_applied_callback = False
            return False

        route_applied = self.pending_route_applied_callback
        self.pending_route_applied_callback = False
        self.refresh()
        if route_applied and self.route_applied_callback is not None:
            self.route_applied_callback()
        return False

    def handle_object_added(self, _manager, node) -> None:
        if not self.accept_stream_events:
            return

        try:
            stream = self.backend.node_from_proxy(node)
        except Exception:
            stream = None

        if stream is not None:
            if stream.media_class == STREAM_OUTPUT_AUDIO:
                self.schedule_refresh()
            return

        try:
            link = self.backend.link_from_proxy(node)
        except Exception:
            return

        if self._link_touches_virtual_sink(link):
            self.schedule_refresh(route_applied=True)

    def start_monitoring(self, *, require_initial_route: bool = False) -> None:
        self.backend.connect()
        self.accept_stream_events = True

        if self.object_added_handler_id == 0:
            self.object_added_handler_id = self.backend.connect_object_added(self.handle_object_added)

        self.refresh(raise_errors=require_initial_route)

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
        try:
            self.start_monitoring(require_initial_route=True)
        except Exception:
            self.enabled = False
            self.stop_monitoring()
            self.restore_output_streams()
            raise

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
