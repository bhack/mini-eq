from __future__ import annotations

from tools import check_headless_pipewire_runtime as headless


def node_item(item_id: int, name: str) -> dict:
    return {
        "id": item_id,
        "type": "PipeWire:Interface:Node",
        "info": {"props": {"node.name": name, "object.serial": str(item_id + 1000)}},
    }


def link_item(item_id: int, output_node: int, input_node: int, state: str) -> dict:
    return {
        "id": item_id,
        "type": "PipeWire:Interface:Link",
        "info": {
            "state": state,
            "props": {
                "link.output.node": str(output_node),
                "link.input.node": str(input_node),
            },
        },
    }


class AlwaysPendingContext:
    def __init__(self) -> None:
        self.iterations = 0

    def pending(self) -> bool:
        return True

    def iteration(self, may_block: bool) -> None:
        assert may_block is False
        self.iterations += 1


def test_drain_main_context_limits_continuous_pending_events() -> None:
    context = AlwaysPendingContext()

    headless.drain_main_context(context, max_iterations=3)

    assert context.iterations == 3


def test_headless_runtime_recognizes_active_processing_path(monkeypatch) -> None:
    monkeypatch.setattr(
        headless.live,
        "read_pw_dump",
        lambda: [
            node_item(10, "mini_eq_sink"),
            node_item(20, "mini_eq_sink_output"),
            node_item(30, "ci_null_sink"),
            node_item(40, "browser"),
            link_item(90, 40, 10, "active"),
            link_item(91, 20, 30, "active"),
        ],
    )

    assert headless.processing_path_has_active_links("mini_eq_sink", "mini_eq_sink_output") is True


def test_headless_runtime_rejects_inactive_processing_path(monkeypatch) -> None:
    monkeypatch.setattr(
        headless.live,
        "read_pw_dump",
        lambda: [
            node_item(10, "mini_eq_sink"),
            node_item(20, "mini_eq_sink_output"),
            node_item(30, "ci_null_sink"),
            node_item(40, "browser"),
            link_item(90, 40, 10, "active"),
            link_item(91, 20, 30, "paused"),
        ],
    )

    assert headless.processing_path_has_active_links("mini_eq_sink", "mini_eq_sink_output") is False


def test_headless_runtime_matches_current_virtual_route(monkeypatch) -> None:
    monkeypatch.setattr(headless.live, "node_by_name", lambda _name: node_item(10, "mini_eq_sink"))
    monkeypatch.setattr(headless.live, "metadata_targets", lambda: {42: ("1010", "Spa:Id")})

    assert headless.route_to_current_virtual(42, "mini_eq_sink") == "1010"


def test_headless_runtime_rejects_stale_virtual_route(monkeypatch) -> None:
    monkeypatch.setattr(headless.live, "node_by_name", lambda _name: node_item(10, "mini_eq_sink"))
    monkeypatch.setattr(headless.live, "metadata_targets", lambda: {42: ("old-serial", "Spa:Id")})

    assert headless.route_to_current_virtual(42, "mini_eq_sink") is None


def test_dynamic_sink_properties_create_hotplug_audio_sink() -> None:
    properties = headless.dynamic_sink_properties("ci_hotplug_sink")

    assert 'node.name = "ci_hotplug_sink"' in properties
    assert 'media.class = "Audio/Sink"' in properties
    assert "object.linger = true" in properties
    assert "factory.name = support.null-audio-sink" in properties
    assert "session.suspend-timeout-seconds = 1" in properties


def test_alsa_null_sink_properties_create_alsa_pcm_audio_sink() -> None:
    properties = headless.alsa_null_sink_properties("ci_alsa_null_sink")

    assert 'node.name = "ci_alsa_null_sink"' in properties
    assert 'media.class = "Audio/Sink"' in properties
    assert "object.linger = true" in properties
    assert "factory.name = api.alsa.pcm.sink" in properties
    assert 'api.alsa.path = "null"' in properties
    assert 'audio.format = "S16LE"' in properties
    assert "session.suspend-timeout-seconds = 1" in properties
