from __future__ import annotations

import pytest

from tests._mini_eq_imports import pipewire_backend as pw_backend
from tests._mini_eq_imports import pipewire_stream_router as pw_router


def make_node(
    bound_id: int,
    media_class: str,
    node_name: str,
    application_name: str | None = None,
    properties: dict[str, str] | None = None,
) -> pw_backend.PipeWireNode:
    return pw_backend.PipeWireNode(
        bound_id=bound_id,
        object_serial=str(bound_id + 1000),
        media_class=media_class,
        node_name=node_name,
        node_description=None,
        application_name=application_name,
        node_dont_move=False,
        properties=properties or {},
    )


def no_stream_target() -> pw_backend.PipeWireStreamTarget:
    return pw_backend.PipeWireStreamTarget(None, None, None, None)


def make_link(bound_id: int, output_node_id: int, input_node_id: int) -> pw_backend.PipeWireLink:
    return pw_backend.PipeWireLink(
        bound_id=bound_id,
        output_node_id=output_node_id,
        input_node_id=input_node_id,
        passive=False,
        feedback=False,
    )


class FakePipeWireBackend:
    def __init__(
        self,
        streams: list[pw_backend.PipeWireNode],
        sinks: list[pw_backend.PipeWireNode] | None = None,
        target_nodes: dict[int, str] | None = None,
        stream_targets: dict[int, pw_backend.PipeWireStreamTarget] | None = None,
    ) -> None:
        self.streams = streams
        self.sinks = sinks or []
        self.target_nodes = target_nodes or {}
        self.stream_targets = stream_targets or {}
        self.moves: list[tuple[int, str]] = []
        self.restores: list[tuple[int, pw_backend.PipeWireStreamTarget]] = []
        self.connected = False
        self.closed = False
        self.disconnected_handlers: list[int] = []
        self.missing_stream_ids: set[int] = set()
        self.move_failures: dict[int, Exception] = {}

    def connect(self) -> None:
        self.connected = True

    def close(self) -> None:
        self.closed = True

    def list_output_streams(self) -> list[pw_backend.PipeWireNode]:
        return self.streams

    def audio_sink_by_name(self, node_name: str) -> pw_backend.PipeWireNode | None:
        for sink in self.sinks:
            if sink.node_name == node_name:
                return sink
        return None

    def stream_target(self, stream_bound_id: int) -> pw_backend.PipeWireStreamTarget:
        if stream_bound_id in self.missing_stream_ids:
            raise pw_backend.PipeWireBackendError(f"output stream not found: {stream_bound_id}")

        return self.stream_targets.get(stream_bound_id, no_stream_target())

    def move_stream_to_target(self, stream_bound_id: int, target_node_name: str) -> None:
        if stream_bound_id in self.missing_stream_ids:
            raise pw_backend.PipeWireBackendError(f"output stream not found: {stream_bound_id}")
        if stream_bound_id in self.move_failures:
            raise self.move_failures[stream_bound_id]

        self.moves.append((stream_bound_id, target_node_name))
        self.target_nodes[stream_bound_id] = target_node_name

    def restore_stream_target(self, stream_bound_id: int, target: pw_backend.PipeWireStreamTarget) -> None:
        if stream_bound_id in self.missing_stream_ids:
            raise pw_backend.PipeWireBackendError(f"output stream not found: {stream_bound_id}")

        self.restores.append((stream_bound_id, target))
        self.stream_targets[stream_bound_id] = target
        if target.target_node is None and target.target_object is None:
            self.target_nodes.pop(stream_bound_id, None)
        else:
            self.target_nodes[stream_bound_id] = target.target_object or target.target_node or ""

    def node_from_proxy(self, node):
        if isinstance(node, pw_backend.PipeWireLink):
            raise pw_backend.PipeWireBackendError("not a node")
        return node

    def link_from_proxy(self, link):
        if not isinstance(link, pw_backend.PipeWireLink):
            raise pw_backend.PipeWireBackendError("not a link")
        return link

    def connect_object_added(self, _callback) -> int:
        return 42

    def disconnect_node_manager_handler(self, handler_id: int) -> None:
        self.disconnected_handlers.append(handler_id)


def test_pipewire_router_moves_only_external_output_streams() -> None:
    backend = FakePipeWireBackend(
        [
            make_node(1, pw_backend.STREAM_OUTPUT_AUDIO, "spotify", "Spotify"),
            make_node(2, pw_backend.STREAM_OUTPUT_AUDIO, "mini_eq_sink_output"),
            make_node(3, pw_backend.STREAM_OUTPUT_AUDIO, "control", pw_router.OUTPUT_CLIENT_NAME),
            make_node(4, pw_backend.STREAM_OUTPUT_AUDIO, "mini_eq_sink_1_output"),
        ]
    )
    router = pw_router.PipeWireStreamRouter("mini_eq_sink", "mini_eq_sink_output", lambda _message: None, backend)

    routed_now = router.route_output_streams()

    assert routed_now == 1
    assert backend.moves == [(1, "mini_eq_sink")]
    assert router.routed_stream_ids == {1}
    assert router.routed_stream_targets == {1: no_stream_target()}


def test_pipewire_router_skips_notification_and_system_event_streams() -> None:
    backend = FakePipeWireBackend(
        [
            make_node(1, pw_backend.STREAM_OUTPUT_AUDIO, "spotify", "Spotify"),
            make_node(2, pw_backend.STREAM_OUTPUT_AUDIO, "bell", "libcanberra", {"media.role": "event"}),
            make_node(3, pw_backend.STREAM_OUTPUT_AUDIO, "GNOME Shell", "GNOME Shell"),
        ]
    )
    router = pw_router.PipeWireStreamRouter("mini_eq_sink", "mini_eq_sink_output", lambda _message: None, backend)

    routed_now = router.route_output_streams()

    assert routed_now == 1
    assert backend.moves == [(1, "mini_eq_sink")]
    assert router.routed_stream_ids == {1}


def test_pipewire_router_skips_stream_targeting_different_output_device() -> None:
    backend = FakePipeWireBackend(
        [make_node(1, pw_backend.STREAM_OUTPUT_AUDIO, "spotify", "Spotify", {"target.object": "hdmi"})],
        sinks=[
            make_node(10, pw_backend.AUDIO_SINK, "speakers"),
            make_node(11, pw_backend.AUDIO_SINK, "mini_eq_sink"),
        ],
    )
    router = pw_router.PipeWireStreamRouter("mini_eq_sink", "mini_eq_sink_output", lambda _message: None, backend)
    router.set_output_sink_name("speakers")

    routed_now = router.route_output_streams()

    assert routed_now == 0
    assert backend.moves == []
    assert router.routed_stream_ids == set()


def test_pipewire_router_routes_stream_targeting_selected_output_device() -> None:
    output_sink = make_node(10, pw_backend.AUDIO_SINK, "speakers")
    backend = FakePipeWireBackend(
        [
            make_node(
                1, pw_backend.STREAM_OUTPUT_AUDIO, "spotify", "Spotify", {"target.object": output_sink.object_serial}
            )
        ],
        sinks=[
            output_sink,
            make_node(11, pw_backend.AUDIO_SINK, "mini_eq_sink"),
        ],
    )
    router = pw_router.PipeWireStreamRouter("mini_eq_sink", "mini_eq_sink_output", lambda _message: None, backend)
    router.set_output_sink_name("speakers")

    routed_now = router.route_output_streams()

    assert routed_now == 1
    assert backend.moves == [(1, "mini_eq_sink")]
    assert router.routed_stream_ids == {1}


def test_pipewire_router_restores_tracked_external_streams() -> None:
    original_target = pw_backend.PipeWireStreamTarget("23", "Spa:Id", "1001", "Spa:Id")
    backend = FakePipeWireBackend(
        [
            make_node(1, pw_backend.STREAM_OUTPUT_AUDIO, "spotify", "Spotify"),
            make_node(2, pw_backend.STREAM_OUTPUT_AUDIO, "mini_eq_sink_output"),
        ]
    )
    router = pw_router.PipeWireStreamRouter("mini_eq_sink", "mini_eq_sink_output", lambda _message: None, backend)
    router.set_output_sink_name("speakers")
    router.routed_stream_ids = {1, 2, 99}
    router.routed_stream_targets = {1: original_target}

    restored = router.restore_output_streams()

    assert restored == 1
    assert backend.restores == [(1, original_target)]
    assert router.routed_stream_ids == set()
    assert router.routed_stream_targets == {}


def test_pipewire_router_rewrites_tracked_route_target_without_metadata_readback() -> None:
    backend = FakePipeWireBackend(
        [make_node(1, pw_backend.STREAM_OUTPUT_AUDIO, "spotify", "Spotify")],
        {1: "mini_eq_sink"},
    )
    router = pw_router.PipeWireStreamRouter("mini_eq_sink", "mini_eq_sink_output", lambda _message: None, backend)
    router.routed_stream_ids = {1}

    routed_now = router.route_output_streams()

    assert routed_now == 0
    assert backend.moves == [(1, "mini_eq_sink")]
    assert router.routed_stream_ids == {1}
    assert router.routed_stream_targets == {1: no_stream_target()}


def test_pipewire_router_routes_without_target_metadata_preflight() -> None:
    backend = FakePipeWireBackend(
        [make_node(1, pw_backend.STREAM_OUTPUT_AUDIO, "spotify", "Spotify")],
        {1: "mini_eq_sink"},
    )
    router = pw_router.PipeWireStreamRouter("mini_eq_sink", "mini_eq_sink_output", lambda _message: None, backend)

    routed_now = router.route_output_streams()

    assert routed_now == 1
    assert backend.moves == [(1, "mini_eq_sink")]
    assert router.routed_stream_ids == {1}
    assert router.routed_stream_targets == {1: no_stream_target()}


def test_pipewire_router_snapshots_existing_stream_target_before_routing() -> None:
    original_target = pw_backend.PipeWireStreamTarget("23", "Spa:Id", "1001", "Spa:Id")
    backend = FakePipeWireBackend(
        [make_node(1, pw_backend.STREAM_OUTPUT_AUDIO, "spotify", "Spotify")],
        stream_targets={1: original_target},
    )
    router = pw_router.PipeWireStreamRouter("mini_eq_sink", "mini_eq_sink_output", lambda _message: None, backend)

    routed_now = router.route_output_streams()

    assert routed_now == 1
    assert backend.moves == [(1, "mini_eq_sink")]
    assert router.routed_stream_targets == {1: original_target}


def test_pipewire_router_treats_existing_virtual_sink_target_as_own_override() -> None:
    virtual_sink = make_node(11, pw_backend.AUDIO_SINK, "mini_eq_sink")
    stale_target = pw_backend.PipeWireStreamTarget(
        str(virtual_sink.bound_id),
        "Spa:Id",
        virtual_sink.object_serial,
        "Spa:Id",
    )
    backend = FakePipeWireBackend(
        [make_node(1, pw_backend.STREAM_OUTPUT_AUDIO, "spotify", "Spotify")],
        sinks=[virtual_sink],
        stream_targets={1: stale_target},
    )
    router = pw_router.PipeWireStreamRouter("mini_eq_sink", "mini_eq_sink_output", lambda _message: None, backend)

    routed_now = router.route_output_streams()

    assert routed_now == 1
    assert backend.moves == [(1, "mini_eq_sink")]
    assert router.routed_stream_targets == {1: no_stream_target()}


def test_pipewire_router_drops_stream_that_disappears_during_route() -> None:
    backend = FakePipeWireBackend(
        [make_node(92, pw_backend.STREAM_OUTPUT_AUDIO, "spotify", "Spotify")],
    )
    backend.missing_stream_ids = {92}
    router = pw_router.PipeWireStreamRouter("mini_eq_sink", "mini_eq_sink_output", lambda _message: None, backend)
    router.routed_stream_ids = {92}

    routed_now = router.route_output_streams()

    assert routed_now == 0
    assert backend.moves == []
    assert router.routed_stream_ids == set()
    assert router.routed_stream_targets == {}


def test_pipewire_router_enable_raises_and_stops_monitoring_on_initial_route_error() -> None:
    backend = FakePipeWireBackend(
        [make_node(1, pw_backend.STREAM_OUTPUT_AUDIO, "spotify", "Spotify")],
    )
    statuses: list[str] = []
    router = pw_router.PipeWireStreamRouter("mini_eq_sink", "mini_eq_sink_output", statuses.append, backend)

    def fail_move(_stream_bound_id: int, _target_node_name: str) -> None:
        raise RuntimeError("metadata permission denied")

    backend.move_stream_to_target = fail_move

    with pytest.raises(RuntimeError, match="metadata permission denied"):
        router.enable()

    assert router.enabled is False
    assert router.accept_stream_events is False
    assert backend.disconnected_handlers == [42]
    assert statuses == ["routing warning: metadata permission denied"]


def test_pipewire_router_enable_restores_partial_initial_route_failure() -> None:
    backend = FakePipeWireBackend(
        [
            make_node(1, pw_backend.STREAM_OUTPUT_AUDIO, "spotify", "Spotify"),
            make_node(2, pw_backend.STREAM_OUTPUT_AUDIO, "browser", "Browser"),
        ]
    )
    backend.move_failures = {2: RuntimeError("metadata permission denied")}
    statuses: list[str] = []
    router = pw_router.PipeWireStreamRouter("mini_eq_sink", "mini_eq_sink_output", statuses.append, backend)
    router.set_output_sink_name("speakers")

    with pytest.raises(RuntimeError, match="metadata permission denied"):
        router.enable()

    assert router.enabled is False
    assert router.routed_stream_ids == set()
    assert backend.moves == [(1, "mini_eq_sink")]
    assert backend.restores == [(1, no_stream_target())]
    assert 1 not in backend.target_nodes
    assert statuses == ["routing warning: metadata permission denied"]


def test_pipewire_router_falls_back_to_output_sink_when_original_target_is_unknown() -> None:
    backend = FakePipeWireBackend(
        [make_node(1, pw_backend.STREAM_OUTPUT_AUDIO, "spotify", "Spotify")],
        {1: "speakers"},
    )
    router = pw_router.PipeWireStreamRouter("mini_eq_sink", "mini_eq_sink_output", lambda _message: None, backend)
    router.set_output_sink_name("speakers")
    router.routed_stream_ids = {1}

    restored = router.restore_output_streams()

    assert restored == 1
    assert backend.moves == [(1, "speakers")]
    assert router.routed_stream_ids == set()


def test_pipewire_router_clears_target_when_stream_had_no_original_target() -> None:
    backend = FakePipeWireBackend(
        [make_node(1, pw_backend.STREAM_OUTPUT_AUDIO, "spotify", "Spotify")],
        {1: "mini_eq_sink"},
    )
    router = pw_router.PipeWireStreamRouter("mini_eq_sink", "mini_eq_sink_output", lambda _message: None, backend)
    router.set_output_sink_name("speakers")
    router.routed_stream_ids = {1}
    router.routed_stream_targets = {1: no_stream_target()}

    restored = router.restore_output_streams()

    assert restored == 1
    assert backend.moves == []
    assert backend.restores == [(1, no_stream_target())]
    assert 1 not in backend.target_nodes
    assert router.routed_stream_ids == set()
    assert router.routed_stream_targets == {}


def test_pipewire_router_drops_stream_that_disappears_during_restore() -> None:
    backend = FakePipeWireBackend(
        [make_node(92, pw_backend.STREAM_OUTPUT_AUDIO, "spotify", "Spotify")],
    )
    backend.missing_stream_ids = {92}
    router = pw_router.PipeWireStreamRouter("mini_eq_sink", "mini_eq_sink_output", lambda _message: None, backend)
    router.set_output_sink_name("speakers")
    router.routed_stream_ids = {92}

    restored = router.restore_output_streams()

    assert restored == 0
    assert backend.moves == []
    assert router.routed_stream_ids == set()
    assert router.routed_stream_targets == {}


def test_pipewire_router_schedules_one_refresh_for_new_output_stream(monkeypatch: pytest.MonkeyPatch) -> None:
    backend = FakePipeWireBackend([])
    router = pw_router.PipeWireStreamRouter("mini_eq_sink", "mini_eq_sink_output", lambda _message: None, backend)
    scheduled_callbacks: list[object] = []

    monkeypatch.setattr(
        pw_router.GLib,
        "idle_add",
        lambda callback: scheduled_callbacks.append(callback) or 321,
    )

    router.accept_stream_events = True
    stream = make_node(1, pw_backend.STREAM_OUTPUT_AUDIO, "spotify", "Spotify")
    router.handle_object_added(None, stream)
    router.handle_object_added(None, stream)

    assert router.event_source_id == 321
    assert len(scheduled_callbacks) == 1


def test_pipewire_router_ignores_new_non_output_stream(monkeypatch: pytest.MonkeyPatch) -> None:
    backend = FakePipeWireBackend([])
    router = pw_router.PipeWireStreamRouter("mini_eq_sink", "mini_eq_sink_output", lambda _message: None, backend)
    scheduled_callbacks: list[object] = []

    monkeypatch.setattr(
        pw_router.GLib,
        "idle_add",
        lambda callback: scheduled_callbacks.append(callback) or 321,
    )

    router.accept_stream_events = True
    sink = make_node(1, pw_backend.AUDIO_SINK, "speakers")
    router.handle_object_added(None, sink)

    assert router.event_source_id == 0
    assert scheduled_callbacks == []


def test_pipewire_router_reapplies_controls_when_virtual_sink_link_appears(monkeypatch: pytest.MonkeyPatch) -> None:
    virtual_sink = make_node(11, pw_backend.AUDIO_SINK, "mini_eq_sink")
    backend = FakePipeWireBackend(
        [make_node(1, pw_backend.STREAM_OUTPUT_AUDIO, "spotify", "Spotify")],
        sinks=[virtual_sink],
    )
    applied: list[str] = []
    router = pw_router.PipeWireStreamRouter(
        "mini_eq_sink",
        "mini_eq_sink_output",
        lambda _message: None,
        backend,
        route_applied_callback=lambda: applied.append("apply"),
    )
    scheduled_callbacks: list[object] = []

    monkeypatch.setattr(
        pw_router.GLib,
        "idle_add",
        lambda callback: scheduled_callbacks.append(callback) or 321,
    )

    router.enabled = True
    router.accept_stream_events = True
    router.handle_object_added(None, make_link(92, output_node_id=1, input_node_id=virtual_sink.bound_id))

    assert router.event_source_id == 321
    assert len(scheduled_callbacks) == 1

    keep_source = scheduled_callbacks[0]()

    assert keep_source is False
    assert backend.moves == [(1, "mini_eq_sink")]
    assert applied == ["apply"]


def test_pipewire_router_ignores_unrelated_links(monkeypatch: pytest.MonkeyPatch) -> None:
    virtual_sink = make_node(11, pw_backend.AUDIO_SINK, "mini_eq_sink")
    backend = FakePipeWireBackend([], sinks=[virtual_sink])
    router = pw_router.PipeWireStreamRouter("mini_eq_sink", "mini_eq_sink_output", lambda _message: None, backend)
    scheduled_callbacks: list[object] = []

    monkeypatch.setattr(
        pw_router.GLib,
        "idle_add",
        lambda callback: scheduled_callbacks.append(callback) or 321,
    )

    router.enabled = True
    router.accept_stream_events = True
    router.handle_object_added(None, make_link(92, output_node_id=1, input_node_id=2))

    assert router.event_source_id == 0
    assert scheduled_callbacks == []


def test_pipewire_router_close_does_not_close_shared_backend() -> None:
    backend = FakePipeWireBackend([])
    router = pw_router.PipeWireStreamRouter("mini_eq_sink", "mini_eq_sink_output", lambda _message: None, backend)

    router.enable()

    assert backend.connected is True
    assert router.object_added_handler_id == 42

    router.close()

    assert backend.disconnected_handlers == [42]
    assert backend.closed is False
