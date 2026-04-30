from __future__ import annotations

import pytest

from tests._mini_eq_imports import wireplumber_backend as wp_backend
from tests._mini_eq_imports import wireplumber_stream_router as wp_router


def make_node(
    bound_id: int,
    media_class: str,
    node_name: str,
    application_name: str | None = None,
) -> wp_backend.WirePlumberNode:
    return wp_backend.WirePlumberNode(
        bound_id=bound_id,
        object_serial=str(bound_id + 1000),
        media_class=media_class,
        node_name=node_name,
        node_description=None,
        application_name=application_name,
        node_dont_move=False,
    )


class FakeWirePlumberBackend:
    def __init__(
        self,
        streams: list[wp_backend.WirePlumberNode],
        target_nodes: dict[int, str] | None = None,
    ) -> None:
        self.streams = streams
        self.target_nodes = target_nodes or {}
        self.moves: list[tuple[int, str]] = []
        self.connected = False
        self.closed = False
        self.disconnected_handlers: list[int] = []
        self.missing_stream_ids: set[int] = set()

    def connect(self) -> None:
        self.connected = True

    def close(self) -> None:
        self.closed = True

    def list_output_streams(self) -> list[wp_backend.WirePlumberNode]:
        return self.streams

    def move_stream_to_target(self, stream_bound_id: int, target_node_name: str) -> None:
        if stream_bound_id in self.missing_stream_ids:
            raise wp_backend.WirePlumberError(f"output stream not found: {stream_bound_id}")

        self.moves.append((stream_bound_id, target_node_name))
        self.target_nodes[stream_bound_id] = target_node_name

    def stream_targets_node(self, stream_bound_id: int, target_node_name: str) -> bool:
        return self.target_nodes.get(stream_bound_id) == target_node_name

    def node_from_proxy(self, node):
        return node

    def connect_object_added(self, _callback) -> int:
        return 42

    def disconnect_node_manager_handler(self, handler_id: int) -> None:
        self.disconnected_handlers.append(handler_id)


def test_wireplumber_router_moves_only_external_output_streams() -> None:
    backend = FakeWirePlumberBackend(
        [
            make_node(1, wp_backend.STREAM_OUTPUT_AUDIO, "spotify", "Spotify"),
            make_node(2, wp_backend.STREAM_OUTPUT_AUDIO, "mini_eq_sink_output"),
            make_node(3, wp_backend.STREAM_OUTPUT_AUDIO, "control", wp_router.OUTPUT_CLIENT_NAME),
            make_node(4, wp_backend.STREAM_OUTPUT_AUDIO, "mini_eq_sink_1_output"),
        ]
    )
    router = wp_router.WirePlumberStreamRouter("mini_eq_sink", "mini_eq_sink_output", lambda _message: None, backend)

    routed_now = router.route_output_streams()

    assert routed_now == 1
    assert backend.moves == [(1, "mini_eq_sink")]
    assert router.routed_stream_ids == {1}


def test_wireplumber_router_restores_tracked_external_streams() -> None:
    backend = FakeWirePlumberBackend(
        [
            make_node(1, wp_backend.STREAM_OUTPUT_AUDIO, "spotify", "Spotify"),
            make_node(2, wp_backend.STREAM_OUTPUT_AUDIO, "mini_eq_sink_output"),
        ]
    )
    router = wp_router.WirePlumberStreamRouter("mini_eq_sink", "mini_eq_sink_output", lambda _message: None, backend)
    router.set_output_sink_name("speakers")
    router.routed_stream_ids = {1, 2, 99}

    restored = router.restore_output_streams()

    assert restored == 1
    assert backend.moves == [(1, "speakers")]
    assert router.routed_stream_ids == set()


def test_wireplumber_router_skips_redundant_route_move() -> None:
    backend = FakeWirePlumberBackend(
        [make_node(1, wp_backend.STREAM_OUTPUT_AUDIO, "spotify", "Spotify")],
        {1: "mini_eq_sink"},
    )
    router = wp_router.WirePlumberStreamRouter("mini_eq_sink", "mini_eq_sink_output", lambda _message: None, backend)
    router.routed_stream_ids = {1}

    routed_now = router.route_output_streams()

    assert routed_now == 0
    assert backend.moves == []
    assert router.routed_stream_ids == {1}


def test_wireplumber_router_does_not_read_target_metadata_before_first_route() -> None:
    backend = FakeWirePlumberBackend(
        [make_node(1, wp_backend.STREAM_OUTPUT_AUDIO, "spotify", "Spotify")],
        {1: "mini_eq_sink"},
    )
    router = wp_router.WirePlumberStreamRouter("mini_eq_sink", "mini_eq_sink_output", lambda _message: None, backend)

    def fail_stream_targets_node(_stream_bound_id: int, _target_node_name: str) -> bool:
        raise AssertionError("first route should move directly without metadata preflight")

    backend.stream_targets_node = fail_stream_targets_node

    routed_now = router.route_output_streams()

    assert routed_now == 1
    assert backend.moves == [(1, "mini_eq_sink")]
    assert router.routed_stream_ids == {1}


def test_wireplumber_router_drops_stream_that_disappears_during_route() -> None:
    backend = FakeWirePlumberBackend(
        [make_node(92, wp_backend.STREAM_OUTPUT_AUDIO, "spotify", "Spotify")],
    )
    backend.missing_stream_ids = {92}
    router = wp_router.WirePlumberStreamRouter("mini_eq_sink", "mini_eq_sink_output", lambda _message: None, backend)
    router.routed_stream_ids = {92}

    routed_now = router.route_output_streams()

    assert routed_now == 0
    assert backend.moves == []
    assert router.routed_stream_ids == set()


def test_wireplumber_router_always_writes_restore_move_for_tracked_streams() -> None:
    backend = FakeWirePlumberBackend(
        [make_node(1, wp_backend.STREAM_OUTPUT_AUDIO, "spotify", "Spotify")],
        {1: "speakers"},
    )
    router = wp_router.WirePlumberStreamRouter("mini_eq_sink", "mini_eq_sink_output", lambda _message: None, backend)
    router.set_output_sink_name("speakers")
    router.routed_stream_ids = {1}

    restored = router.restore_output_streams()

    assert restored == 1
    assert backend.moves == [(1, "speakers")]
    assert router.routed_stream_ids == set()


def test_wireplumber_router_drops_stream_that_disappears_during_restore() -> None:
    backend = FakeWirePlumberBackend(
        [make_node(92, wp_backend.STREAM_OUTPUT_AUDIO, "spotify", "Spotify")],
    )
    backend.missing_stream_ids = {92}
    router = wp_router.WirePlumberStreamRouter("mini_eq_sink", "mini_eq_sink_output", lambda _message: None, backend)
    router.set_output_sink_name("speakers")
    router.routed_stream_ids = {92}

    restored = router.restore_output_streams()

    assert restored == 0
    assert backend.moves == []
    assert router.routed_stream_ids == set()


def test_wireplumber_router_schedules_one_refresh_for_new_output_stream(monkeypatch: pytest.MonkeyPatch) -> None:
    backend = FakeWirePlumberBackend([])
    router = wp_router.WirePlumberStreamRouter("mini_eq_sink", "mini_eq_sink_output", lambda _message: None, backend)
    scheduled_callbacks: list[object] = []

    monkeypatch.setattr(
        wp_router.GLib,
        "idle_add",
        lambda callback: scheduled_callbacks.append(callback) or 321,
    )

    router.accept_stream_events = True
    stream = make_node(1, wp_backend.STREAM_OUTPUT_AUDIO, "spotify", "Spotify")
    router.handle_object_added(None, stream)
    router.handle_object_added(None, stream)

    assert router.event_source_id == 321
    assert len(scheduled_callbacks) == 1


def test_wireplumber_router_ignores_new_non_output_stream(monkeypatch: pytest.MonkeyPatch) -> None:
    backend = FakeWirePlumberBackend([])
    router = wp_router.WirePlumberStreamRouter("mini_eq_sink", "mini_eq_sink_output", lambda _message: None, backend)
    scheduled_callbacks: list[object] = []

    monkeypatch.setattr(
        wp_router.GLib,
        "idle_add",
        lambda callback: scheduled_callbacks.append(callback) or 321,
    )

    router.accept_stream_events = True
    sink = make_node(1, wp_backend.AUDIO_SINK, "speakers")
    router.handle_object_added(None, sink)

    assert router.event_source_id == 0
    assert scheduled_callbacks == []


def test_wireplumber_router_close_does_not_close_shared_backend() -> None:
    backend = FakeWirePlumberBackend([])
    router = wp_router.WirePlumberStreamRouter("mini_eq_sink", "mini_eq_sink_output", lambda _message: None, backend)

    router.enable()

    assert backend.connected is True
    assert router.object_added_handler_id == 42

    router.close()

    assert backend.disconnected_handlers == [42]
    assert backend.closed is False
