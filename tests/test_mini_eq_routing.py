from __future__ import annotations

import pytest

from tests._mini_eq_imports import core, routing
from tests._mini_eq_imports import wireplumber_backend as wp_backend


def make_node(
    bound_id: int,
    name: str | None,
    media_class: str = wp_backend.AUDIO_SINK,
    properties: dict[str, str] | None = None,
) -> wp_backend.WirePlumberNode:
    return wp_backend.WirePlumberNode(
        local_id=bound_id,
        bound_id=bound_id,
        object_serial=str(bound_id + 1000),
        media_class=media_class,
        node_name=name,
        node_description=None,
        application_name=None,
        node_dont_move=False,
        properties=properties or {},
    )


class FakeOutputBackend:
    def __init__(self, sinks: list[wp_backend.WirePlumberNode]) -> None:
        self.sinks = sinks

    def list_audio_sinks(self) -> list[wp_backend.WirePlumberNode]:
        return self.sinks

    def audio_sink_by_name(self, sink_name: str) -> wp_backend.WirePlumberNode | None:
        for sink in self.sinks:
            if sink.node_name == sink_name:
                return sink

        return None


def test_list_output_sink_names_uses_wireplumber_sinks_and_filters_internal_nodes() -> None:
    controller = routing.SystemWideEqController.__new__(routing.SystemWideEqController)
    controller.output_backend = FakeOutputBackend(
        [
            make_node(1, "speakers"),
            make_node(2, "mini_eq_sink"),
            make_node(3, None),
        ]
    )

    assert routing.SystemWideEqController.list_output_sink_names(controller) == ["speakers"]


def test_get_sink_uses_wireplumber_node_name() -> None:
    controller = routing.SystemWideEqController.__new__(routing.SystemWideEqController)
    sink = make_node(1, "speakers")
    controller.output_backend = FakeOutputBackend([sink])

    assert routing.SystemWideEqController.get_sink(controller, "speakers") is sink
    assert routing.SystemWideEqController.get_sink(controller, "missing") is None


def test_output_metadata_change_schedules_one_refresh(monkeypatch: pytest.MonkeyPatch) -> None:
    controller = routing.SystemWideEqController.__new__(routing.SystemWideEqController)
    controller.accept_output_events = True
    controller.output_event_source_id = 0
    controller.output_backend = type("Backend", (), {"remember_default_metadata_change": lambda *_args: True})()
    scheduled_callbacks: list[object] = []

    monkeypatch.setattr(
        routing.GLib,
        "idle_add",
        lambda callback: scheduled_callbacks.append(callback) or 321,
    )

    routing.SystemWideEqController.handle_output_metadata_changed(
        controller,
        None,
        0,
        wp_backend.DEFAULT_AUDIO_SINK_KEY,
        None,
        None,
    )
    routing.SystemWideEqController.handle_output_metadata_changed(
        controller,
        None,
        0,
        wp_backend.DEFAULT_CONFIGURED_AUDIO_SINK_KEY,
        None,
        None,
    )

    assert controller.output_event_source_id == 321
    assert len(scheduled_callbacks) == 1


def test_output_object_added_schedules_refresh_only_for_audio_sinks(monkeypatch: pytest.MonkeyPatch) -> None:
    controller = routing.SystemWideEqController.__new__(routing.SystemWideEqController)
    controller.accept_output_events = True
    controller.output_event_source_id = 0
    controller.output_backend = type("Backend", (), {"node_from_proxy": lambda _self, node: node})()
    scheduled_callbacks: list[object] = []

    monkeypatch.setattr(
        routing.GLib,
        "idle_add",
        lambda callback: scheduled_callbacks.append(callback) or 123,
    )

    routing.SystemWideEqController.handle_output_object_added(
        controller,
        None,
        make_node(1, "spotify", wp_backend.STREAM_OUTPUT_AUDIO),
    )
    routing.SystemWideEqController.handle_output_object_added(controller, None, make_node(2, "speakers"))

    assert controller.output_event_source_id == 123
    assert len(scheduled_callbacks) == 1


def test_follow_system_default_output_enables_follow_mode_and_refreshes() -> None:
    controller = routing.SystemWideEqController.__new__(routing.SystemWideEqController)
    controller.follow_default_output = False
    calls: list[str] = []

    def fake_refresh() -> bool:
        calls.append("refresh")
        return True

    controller.refresh_followed_output_sink = fake_refresh

    routing.SystemWideEqController.follow_system_default_output(controller)

    assert controller.follow_default_output is True
    assert calls == ["refresh"]


def test_enabling_analyzer_while_engine_runs_opens_jack_before_restarting_engine() -> None:
    controller = routing.SystemWideEqController.__new__(routing.SystemWideEqController)
    controller.running = True
    controller.routed = True
    calls: list[str] = []

    class FakeAnalyzer:
        client = None

        def set_enabled(self, enabled: bool) -> bool:
            calls.append(f"analyzer:{enabled}:running={controller.running}")
            self.client = object() if enabled else None
            return True

    class FakeStreamRouter:
        def route_output_streams(self) -> None:
            calls.append("route")

    analyzer = FakeAnalyzer()
    controller.stream_router = FakeStreamRouter()
    controller.ensure_output_analyzer = lambda: analyzer

    def stop_engine(*, announce: bool = True) -> None:
        calls.append(f"stop:{announce}")
        controller.running = False

    def start_engine() -> None:
        calls.append("start")
        controller.running = True

    controller.stop_engine = stop_engine
    controller.start_engine = start_engine

    assert routing.SystemWideEqController.set_analyzer_enabled(controller, True) is True
    assert calls == [
        "stop:False",
        "analyzer:True:running=False",
        "start",
        "route",
    ]


def test_enabling_prepared_analyzer_does_not_restart_running_engine() -> None:
    controller = routing.SystemWideEqController.__new__(routing.SystemWideEqController)
    controller.running = True
    calls: list[str] = []

    class FakeAnalyzer:
        client = object()

        def set_enabled(self, enabled: bool) -> bool:
            calls.append(f"analyzer:{enabled}")
            return True

    controller.ensure_output_analyzer = lambda: FakeAnalyzer()
    controller.stop_engine = lambda *, announce=True: calls.append("stop")
    controller.start_engine = lambda: calls.append("start")

    assert routing.SystemWideEqController.set_analyzer_enabled(controller, True) is True
    assert calls == ["analyzer:True"]


def test_enabling_unprepared_analyzer_restores_engine_if_restart_fails() -> None:
    controller = routing.SystemWideEqController.__new__(routing.SystemWideEqController)
    controller.running = True
    controller.routed = False
    controller.stream_router = None
    controller.engine_module = None
    calls: list[str] = []

    class FakeAnalyzer:
        client = None

        def set_enabled(self, enabled: bool) -> bool:
            calls.append(f"analyzer:{enabled}")
            self.client = object() if enabled else self.client
            return True

    analyzer = FakeAnalyzer()
    controller.ensure_output_analyzer = lambda: analyzer

    def stop_engine(*, announce: bool = True) -> None:
        calls.append(f"stop:{announce}")
        controller.running = False

    start_attempts = 0

    def start_engine() -> None:
        nonlocal start_attempts
        start_attempts += 1
        calls.append("start")
        if start_attempts == 1:
            raise RuntimeError("virtual sink did not appear")
        controller.running = True

    controller.stop_engine = stop_engine
    controller.start_engine = start_engine
    controller.emit_status = lambda message: calls.append(f"status:{message}")

    with pytest.raises(RuntimeError, match="virtual sink did not appear"):
        routing.SystemWideEqController.set_analyzer_enabled(controller, True)

    assert calls == [
        "stop:False",
        "analyzer:True",
        "start",
        "analyzer:False",
        "start",
    ]
    assert controller.running is True


def test_enabling_unprepared_analyzer_restores_engine_when_analyzer_is_unavailable() -> None:
    controller = routing.SystemWideEqController.__new__(routing.SystemWideEqController)
    controller.running = True
    controller.routed = False
    controller.stream_router = None
    controller.engine_module = None
    calls: list[str] = []

    class FakeAnalyzer:
        client = None

        def set_enabled(self, enabled: bool) -> bool:
            calls.append(f"analyzer:{enabled}")
            return False

    controller.ensure_output_analyzer = lambda: FakeAnalyzer()

    def stop_engine(*, announce: bool = True) -> None:
        calls.append(f"stop:{announce}")
        controller.running = False

    def start_engine() -> None:
        calls.append("start")
        controller.running = True

    controller.stop_engine = stop_engine
    controller.start_engine = start_engine

    assert routing.SystemWideEqController.set_analyzer_enabled(controller, True) is False
    assert calls == [
        "stop:False",
        "analyzer:True",
        "analyzer:False",
        "start",
    ]
    assert controller.running is True


def test_active_sample_rate_prefers_virtual_sink_then_output_sink() -> None:
    controller = routing.SystemWideEqController.__new__(routing.SystemWideEqController)
    controller.virtual_sink_name = "mini_eq_sink"
    controller.output_sink = "speakers"
    controller.output_backend = FakeOutputBackend(
        [
            make_node(1, "speakers", properties={"node.max-latency": "1024/44100"}),
            make_node(2, "mini_eq_sink", properties={"audio.rate": "96000"}),
        ]
    )

    assert routing.SystemWideEqController.active_sample_rate(controller) == pytest.approx(96000.0)


def test_active_sample_rate_uses_output_sink_when_virtual_sink_is_not_ready() -> None:
    controller = routing.SystemWideEqController.__new__(routing.SystemWideEqController)
    controller.virtual_sink_name = "mini_eq_sink"
    controller.output_sink = "speakers"
    controller.output_backend = FakeOutputBackend(
        [
            make_node(1, "speakers", properties={"node.max-latency": "1024/44100"}),
        ]
    )

    assert routing.SystemWideEqController.active_sample_rate(controller) == pytest.approx(44100.0)


def test_live_biquad_updates_use_active_sample_rate(monkeypatch: pytest.MonkeyPatch) -> None:
    controller = routing.SystemWideEqController.__new__(routing.SystemWideEqController)
    controller.bands = [core.EqBand(core.FILTER_TYPES["Bell"], 1000.0, 3.0, 1.0)]
    controller.eq_enabled = True
    captured: list[float] = []

    def fake_band_controls(_index, _band, _enabled, sample_rate, _solo_active=False):
        captured.append(sample_rate)
        return {"band_l_0:b0": 1.0}

    monkeypatch.setattr(routing, "builtin_biquad_band_control_values", fake_band_controls)
    controller.active_sample_rate = lambda: 96000.0
    controller.set_filter_controls = lambda _controls: None

    routing.SystemWideEqController.apply_band_to_engine(controller, 0)

    assert captured == [96000.0]


def test_full_state_biquad_updates_use_active_sample_rate(monkeypatch: pytest.MonkeyPatch) -> None:
    controller = routing.SystemWideEqController.__new__(routing.SystemWideEqController)
    controller.bands = [core.EqBand(core.FILTER_TYPES["Bell"], 1000.0, 3.0, 1.0)]
    controller.preamp_db = -2.0
    controller.eq_enabled = True
    captured: list[float] = []

    def fake_state_controls(_bands, _preamp_db, _enabled, sample_rate):
        captured.append(sample_rate)
        return {"band_l_0:b0": 1.0}

    monkeypatch.setattr(routing, "builtin_biquad_control_values", fake_state_controls)
    controller.active_sample_rate = lambda: 44100.0
    controller.set_filter_controls = lambda _controls: None

    routing.SystemWideEqController.apply_state_to_engine(controller)

    assert captured == [44100.0]


def test_start_prepares_analyzer_before_filter_chain_engine() -> None:
    controller = routing.SystemWideEqController.__new__(routing.SystemWideEqController)
    calls: list[str] = []

    controller.refresh_followed_output_sink = lambda: calls.append("refresh")
    controller.prepare_output_analyzer = lambda: calls.append("prepare") or True
    controller.start_engine = lambda: calls.append("engine")
    controller.start_output_event_monitoring = lambda: calls.append("monitor")
    controller.stream_router = None
    controller.stop_engine = lambda: calls.append("stop-engine")
    controller.stop_output_event_monitoring = lambda: calls.append("stop-monitor")

    routing.SystemWideEqController.start(controller)

    assert calls == ["refresh", "prepare", "engine", "monitor"]


def test_shutdown_skips_route_restore_when_routing_is_inactive() -> None:
    controller = routing.SystemWideEqController.__new__(routing.SystemWideEqController)
    calls: list[str] = []

    class FakeBackend:
        def close(self) -> None:
            raise AssertionError("controller shutdown should not explicitly disconnect WirePlumber")

    controller.routed = False
    controller.stream_router = None
    controller.output_analyzer = None
    controller.output_backend = FakeBackend()
    controller.route_system_audio = lambda *_args, **_kwargs: calls.append("route")
    controller.stop_output_event_monitoring = lambda: calls.append("stop-monitor")
    controller.engine_module = object()
    controller.filter_node_id = 42
    controller.running = True

    routing.SystemWideEqController.shutdown(controller)

    assert calls == ["stop-monitor"]
    assert controller.engine_module is None
    assert controller.filter_node_id is None
    assert controller.running is False


def test_shutdown_restores_routed_streams_without_refreshing_followed_output() -> None:
    controller = routing.SystemWideEqController.__new__(routing.SystemWideEqController)
    calls: list[object] = []

    class FakeBackend:
        def close(self) -> None:
            raise AssertionError("controller shutdown should not explicitly disconnect WirePlumber")

    class FakeStreamRouter:
        def set_output_sink_name(self, sink_name: str) -> None:
            calls.append(("target", sink_name))

        def disable(self, announce: bool = True) -> None:
            calls.append(("disable", announce))

        def close(self) -> None:
            calls.append("close-router")

    controller.routed = True
    controller.output_sink = "speakers"
    controller.stream_router = FakeStreamRouter()
    controller.output_analyzer = None
    controller.output_backend = FakeBackend()
    controller.refresh_followed_output_sink = lambda: calls.append("refresh")
    controller.stop_output_event_monitoring = lambda: calls.append("stop-monitor")
    controller.engine_module = object()
    controller.filter_node_id = 42
    controller.running = True

    routing.SystemWideEqController.shutdown(controller)

    assert calls == [
        "stop-monitor",
        ("target", "speakers"),
        ("disable", False),
        "close-router",
    ]
    assert controller.routed is False
    assert controller.engine_module is None
    assert controller.filter_node_id is None
    assert controller.running is False


def test_route_system_audio_does_not_enable_during_shutdown() -> None:
    controller = routing.SystemWideEqController.__new__(routing.SystemWideEqController)
    controller.shutting_down = True
    controller.routed = False
    calls: list[str] = []

    controller.refresh_followed_output_sink = lambda: calls.append("refresh")
    controller.ensure_stream_router = lambda: calls.append("router")

    routing.SystemWideEqController.route_system_audio(controller, True)

    assert calls == []
    assert controller.routed is False


def test_emit_status_is_silent_during_shutdown(capsys: pytest.CaptureFixture[str]) -> None:
    controller = routing.SystemWideEqController.__new__(routing.SystemWideEqController)
    controller.shutting_down = True
    calls: list[str] = []
    controller.status_callback = calls.append

    routing.SystemWideEqController.emit_status(controller, "late route")

    assert calls == []
    assert capsys.readouterr().err == ""


def test_preset_payload_excludes_runtime_state_and_load_preserves_it() -> None:
    default_band = core.EqBand(
        filter_type=core.FILTER_TYPES["Bell"],
        frequency=1000.0,
        gain_db=0.0,
        q=1.0,
        mode=core.EQ_MODE_APO,
        slope=0,
        mute=True,
        solo=False,
    )
    controller = routing.SystemWideEqController.__new__(routing.SystemWideEqController)
    controller.eq_enabled = False
    controller.eq_mode = 0
    controller.preamp_db = -3.5
    controller.bands = [default_band]
    controller.default_bands = [default_band]
    applied: list[bool] = []
    controller.apply_state_to_engine = lambda: applied.append(True)

    payload = routing.SystemWideEqController.build_preset_payload(controller, "Bypass Test")

    assert "enabled" not in payload
    assert "eq_mode" not in payload
    assert payload["name"] == "Bypass Test"
    assert set(payload["bands"][0]) == {"filter_type", "frequency", "gain_db", "q", "mute", "solo"}

    payload["preamp_db"] = 1.5
    payload["bands"] = [
        {
            "filter_type": core.FILTER_TYPES["Notch"],
            "frequency": 250.0,
            "gain_db": -2.0,
            "q": 3.0,
            "mute": False,
            "solo": True,
        }
    ]
    routing.SystemWideEqController.apply_preset_payload(controller, payload)

    assert controller.eq_enabled is False
    assert controller.eq_mode == 0
    assert controller.preamp_db == pytest.approx(1.5)
    assert controller.bands[0].filter_type == core.FILTER_TYPES["Notch"]
    assert controller.bands[0].mute is False
    assert controller.bands[0].solo is True
    assert applied == [True]


def test_compact_preset_leaves_missing_bands_inactive() -> None:
    controller = routing.SystemWideEqController.__new__(routing.SystemWideEqController)
    controller.eq_enabled = True
    controller.eq_mode = 0
    controller.preamp_db = 0.0
    controller.default_bands = core.default_eq_bands()
    applied: list[bool] = []
    controller.apply_state_to_engine = lambda: applied.append(True)

    routing.SystemWideEqController.apply_preset_payload(
        controller,
        {
            "version": core.PRESET_VERSION,
            "preamp_db": 0.0,
            "bands": [
                {
                    "filter_type": core.FILTER_TYPES["Bell"],
                    "frequency": 250.0,
                    "gain_db": 1.0,
                    "q": 1.0,
                },
                {
                    "filter_type": core.FILTER_TYPES["Bell"],
                    "frequency": 1000.0,
                    "gain_db": -2.0,
                    "q": 1.5,
                },
            ],
        },
    )

    assert controller.bands[0].filter_type == core.FILTER_TYPES["Bell"]
    assert controller.bands[1].filter_type == core.FILTER_TYPES["Bell"]
    assert all(band.filter_type == core.FILTER_TYPES["Off"] for band in controller.bands[2:])
    assert applied == [True]


def test_apo_import_leaves_missing_bands_inactive(tmp_path) -> None:
    apo_path = tmp_path / "two-bands.txt"
    apo_path.write_text(
        "\n".join(
            [
                "Filter 1: ON PK Fc 250 Hz Gain 1 dB Q 1",
                "Filter 2: ON PK Fc 1000 Hz Gain -2 dB Q 1.5",
            ]
        ),
        encoding="utf-8",
    )
    controller = routing.SystemWideEqController.__new__(routing.SystemWideEqController)
    controller.default_bands = core.default_eq_bands()
    controller.eq_mode = 0
    controller.apply_state_to_engine = lambda: None
    controller.emit_status = lambda _message: None

    imported_count = routing.SystemWideEqController.import_apo_preset(controller, str(apo_path))

    assert imported_count == 2
    assert controller.bands[0].filter_type == core.FILTER_TYPES["Bell"]
    assert controller.bands[1].filter_type == core.FILTER_TYPES["Bell"]
    assert all(band.filter_type == core.FILTER_TYPES["Off"] for band in controller.bands[2:])
