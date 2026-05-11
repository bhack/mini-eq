from __future__ import annotations

import pytest

from tests._mini_eq_imports import core, routing
from tests._mini_eq_imports import pipewire_backend as pw_backend
from tests._mini_eq_imports import pipewire_routes as pw_routes


def make_node(
    bound_id: int,
    name: str | None,
    media_class: str = pw_backend.AUDIO_SINK,
    properties: dict[str, str] | None = None,
    device_id: int = 0,
) -> pw_backend.PipeWireNode:
    return pw_backend.PipeWireNode(
        bound_id=bound_id,
        object_serial=str(bound_id + 1000),
        media_class=media_class,
        node_name=name,
        node_description=None,
        application_name=None,
        node_dont_move=False,
        device_id=device_id,
        properties=properties or {},
    )


class FakeOutputBackend:
    def __init__(self, sinks: list[pw_backend.PipeWireNode]) -> None:
        self.sinks = sinks

    def list_audio_sinks(self) -> list[pw_backend.PipeWireNode]:
        return self.sinks

    def audio_sink_by_name(self, sink_name: str) -> pw_backend.PipeWireNode | None:
        for sink in self.sinks:
            if sink.node_name == sink_name:
                return sink

        return None


class FakeDefaultOutputBackend(FakeOutputBackend):
    def __init__(
        self,
        sinks: list[pw_backend.PipeWireNode],
        cached_defaults: pw_backend.PipeWireDefaults,
        refreshed_defaults: pw_backend.PipeWireDefaults,
    ) -> None:
        super().__init__(sinks)
        self.cached_defaults = cached_defaults
        self.refreshed_defaults = refreshed_defaults
        self.refresh_count = 0

    def defaults(self) -> pw_backend.PipeWireDefaults:
        return self.cached_defaults

    def refresh_defaults(self) -> pw_backend.PipeWireDefaults:
        self.refresh_count += 1
        return self.refreshed_defaults


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


def test_output_preset_target_is_cached_until_output_changes() -> None:
    controller = routing.SystemWideEqController.__new__(routing.SystemWideEqController)
    calls: list[str | None] = []

    class FakeBackend(FakeOutputBackend):
        def output_preset_target_for_sink_name(self, sink_name: str | None) -> pw_routes.PipeWireOutputPresetTarget:
            calls.append(sink_name)
            return pw_routes.PipeWireOutputPresetTarget(sink_name, None, (sink_name,) if sink_name else ())

    controller.output_backend = FakeBackend([make_node(1, "speakers"), make_node(2, "hdmi")])
    controller.output_sink = "speakers"

    assert routing.SystemWideEqController.output_preset_target(controller).keys == ("speakers",)
    assert routing.SystemWideEqController.output_preset_keys(controller) == ("speakers",)
    assert routing.SystemWideEqController.output_preset_link_key(controller) == "speakers"
    assert calls == ["speakers"]

    controller.output_sink = "hdmi"
    assert routing.SystemWideEqController.output_preset_target(controller).keys == ("hdmi",)
    assert calls == ["speakers", "hdmi"]

    routing.SystemWideEqController.invalidate_output_preset_target(controller)
    assert routing.SystemWideEqController.output_preset_target(controller).keys == ("hdmi",)
    assert calls == ["speakers", "hdmi", "hdmi"]


def test_get_default_output_sink_name_uses_cached_metadata_by_default() -> None:
    controller = routing.SystemWideEqController.__new__(routing.SystemWideEqController)
    backend = FakeDefaultOutputBackend(
        [make_node(1, "cached-speakers"), make_node(2, "fresh-speakers")],
        cached_defaults=pw_backend.PipeWireDefaults("cached-current", "cached-speakers"),
        refreshed_defaults=pw_backend.PipeWireDefaults("fresh-speakers", "fresh-configured"),
    )
    controller.output_backend = backend

    assert routing.SystemWideEqController.get_default_output_sink_name(controller) == "cached-speakers"
    assert backend.refresh_count == 0


def test_get_default_output_sink_name_skips_virtual_default_when_configured_sink_is_available() -> None:
    controller = routing.SystemWideEqController.__new__(routing.SystemWideEqController)
    controller.output_backend = FakeDefaultOutputBackend(
        [make_node(1, "speakers")],
        cached_defaults=pw_backend.PipeWireDefaults("mini_eq_sink", "speakers"),
        refreshed_defaults=pw_backend.PipeWireDefaults("fresh-speakers", None),
    )

    assert routing.SystemWideEqController.get_default_output_sink_name(controller) == "speakers"


def test_get_default_output_sink_name_prefers_configured_sink_over_current_sink() -> None:
    controller = routing.SystemWideEqController.__new__(routing.SystemWideEqController)
    controller.output_backend = FakeDefaultOutputBackend(
        [make_node(1, "current-speakers"), make_node(2, "configured-speakers")],
        cached_defaults=pw_backend.PipeWireDefaults("current-speakers", "configured-speakers"),
        refreshed_defaults=pw_backend.PipeWireDefaults("fresh-speakers", None),
    )

    assert routing.SystemWideEqController.get_default_output_sink_name(controller) == "configured-speakers"


def test_resolve_default_output_sink_name_falls_back_to_first_real_sink_when_metadata_is_virtual() -> None:
    controller = routing.SystemWideEqController.__new__(routing.SystemWideEqController)
    controller.output_backend = FakeDefaultOutputBackend(
        [make_node(1, "speakers"), make_node(2, "mini_eq_sink")],
        cached_defaults=pw_backend.PipeWireDefaults("mini_eq_sink", None),
        refreshed_defaults=pw_backend.PipeWireDefaults("mini_eq_sink", None),
    )

    assert routing.SystemWideEqController.resolve_default_output_sink_name(controller) == "speakers"


def test_stream_router_reapplies_current_curve_after_pipewire_link_event(monkeypatch: pytest.MonkeyPatch) -> None:
    controller = routing.SystemWideEqController.__new__(routing.SystemWideEqController)
    controller.stream_router = None
    controller.virtual_sink_name = "mini_eq_sink"
    controller.filter_output_name = "mini_eq_sink_output"
    controller.output_sink = "speakers"
    controller.output_backend = object()
    calls: list[object] = []

    class FakeStreamRouter:
        def __init__(
            self,
            virtual_sink_name: str,
            filter_output_name: str,
            status_callback,
            output_backend,
            *,
            route_applied_callback,
        ) -> None:
            calls.append((virtual_sink_name, filter_output_name, status_callback, output_backend))
            self.route_applied_callback = route_applied_callback
            self.output_sink_names: list[str] = []

        def set_output_sink_name(self, sink_name: str) -> None:
            self.output_sink_names.append(sink_name)

    controller.emit_status = lambda message: calls.append(f"status:{message}")
    controller.apply_state_to_engine = lambda: calls.append("apply")
    monkeypatch.setattr(routing, "PipeWireStreamRouter", FakeStreamRouter)

    stream_router = routing.SystemWideEqController.ensure_stream_router(controller)
    stream_router.route_applied_callback()

    assert calls == [
        ("mini_eq_sink", "mini_eq_sink_output", controller.emit_status, controller.output_backend),
        "apply",
    ]
    assert stream_router.output_sink_names == ["speakers"]


def test_refresh_followed_output_sink_refreshes_metadata_and_skips_virtual_defaults() -> None:
    controller = routing.SystemWideEqController.__new__(routing.SystemWideEqController)
    backend = FakeDefaultOutputBackend(
        [make_node(1, "speakers")],
        cached_defaults=pw_backend.PipeWireDefaults("old-speakers", None),
        refreshed_defaults=pw_backend.PipeWireDefaults("mini_eq_sink", "speakers"),
    )
    controller.output_backend = backend
    controller.follow_default_output = True
    calls: list[object] = []

    controller.switch_output_sink = lambda sink_name, explicit: calls.append((sink_name, explicit))

    assert routing.SystemWideEqController.refresh_followed_output_sink(controller) is True
    assert backend.refresh_count == 1
    assert calls == [("speakers", False)]


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
        pw_backend.DEFAULT_AUDIO_SINK_KEY,
        None,
        None,
    )
    routing.SystemWideEqController.handle_output_metadata_changed(
        controller,
        None,
        0,
        pw_backend.DEFAULT_CONFIGURED_AUDIO_SINK_KEY,
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
        make_node(1, "spotify", pw_backend.STREAM_OUTPUT_AUDIO),
    )
    routing.SystemWideEqController.handle_output_object_added(controller, None, make_node(2, "speakers"))

    assert controller.output_event_source_id == 123
    assert len(scheduled_callbacks) == 1


def test_output_event_idle_invalidates_output_preset_target_cache() -> None:
    controller = routing.SystemWideEqController.__new__(routing.SystemWideEqController)
    controller.accept_output_events = True
    controller.output_event_source_id = 123
    controller._output_preset_target_sink = "speakers"
    controller._output_preset_target = pw_routes.PipeWireOutputPresetTarget("speakers", None, ("speakers",))
    calls: list[str] = []
    controller.refresh_followed_output_sink = lambda: calls.append("refresh")
    controller.outputs_changed_callback = lambda: calls.append("outputs")

    assert routing.SystemWideEqController.on_output_event_idle(controller) is False

    assert controller.output_event_source_id == 0
    assert controller._output_preset_target_sink is None
    assert controller._output_preset_target is None
    assert calls == ["refresh", "outputs"]


def test_output_route_param_change_schedules_output_refresh(monkeypatch: pytest.MonkeyPatch) -> None:
    controller = routing.SystemWideEqController.__new__(routing.SystemWideEqController)
    sink = make_node(1, "speakers", device_id=72)
    route_callback = None
    calls: list[object] = []

    class FakeBackend(FakeOutputBackend):
        def connect_device_route_changed(self, device_id: int, callback) -> int:
            nonlocal route_callback
            calls.append(("connect-route", device_id))
            route_callback = callback
            return 77

        def disconnect_device_handler(self, handler_id: int) -> None:
            calls.append(("disconnect-route", handler_id))

    controller.output_backend = FakeBackend([sink])
    controller.output_sink = "speakers"
    controller.accept_output_events = True
    controller.output_event_source_id = 0
    controller.output_route_param_handler_id = 0
    controller.output_route_param_device_id = 0
    scheduled_callbacks: list[object] = []
    monkeypatch.setattr(
        routing.GLib,
        "idle_add",
        lambda callback: scheduled_callbacks.append(callback) or 321,
    )

    routing.SystemWideEqController.refresh_output_route_param_monitor(controller)

    assert controller.output_route_param_handler_id == 77
    assert controller.output_route_param_device_id == 72
    assert calls == [("connect-route", 72)]

    assert route_callback is not None
    route_callback()

    assert controller.output_event_source_id == 321
    assert len(scheduled_callbacks) == 1


def test_output_route_param_change_refreshes_same_sink_route_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller = routing.SystemWideEqController.__new__(routing.SystemWideEqController)
    sink = make_node(1, "alsa_output.internal", device_id=72)
    route_callback = None
    calls: list[object] = []

    class FakeBackend(FakeOutputBackend):
        route_key = "pipewire-route:v1:device=alsa_card.test;route=analog-output-headphones;route-device=6"

        def output_preset_target_for_sink_name(
            self,
            sink_name: str | None,
        ) -> pw_routes.PipeWireOutputPresetTarget:
            return pw_routes.PipeWireOutputPresetTarget(
                sink_name,
                None,
                (self.route_key, sink_name) if sink_name else (),
            )

        def connect_device_route_changed(self, device_id: int, callback) -> int:
            nonlocal route_callback
            assert device_id == 72
            route_callback = callback
            return 77

        def disconnect_device_handler(self, handler_id: int) -> None:
            calls.append(("disconnect-route", handler_id))

    backend = FakeBackend([sink])
    controller.output_backend = backend
    controller.output_sink = "alsa_output.internal"
    controller.accept_output_events = True
    controller.output_event_source_id = 0
    controller.output_route_param_handler_id = 0
    controller.output_route_param_device_id = 0
    controller.follow_default_output = False
    controller.refresh_followed_output_sink = lambda: calls.append("refresh")
    controller.outputs_changed_callback = lambda: calls.append("outputs")

    monkeypatch.setattr(routing.GLib, "idle_add", lambda callback: calls.append(("idle", callback)) or 321)

    assert routing.SystemWideEqController.output_preset_link_key(controller) == backend.route_key
    routing.SystemWideEqController.refresh_output_route_param_monitor(controller)

    backend.route_key = "pipewire-route:v1:device=alsa_card.test;route=analog-output-speaker;route-device=6"
    assert route_callback is not None
    route_callback()

    assert controller.output_event_source_id == 321
    assert routing.SystemWideEqController.output_preset_link_key(controller).endswith(
        "route=analog-output-headphones;route-device=6"
    )

    assert routing.SystemWideEqController.on_output_event_idle(controller) is False

    assert routing.SystemWideEqController.output_preset_link_key(controller).endswith(
        "route=analog-output-speaker;route-device=6"
    )
    assert calls == [("idle", controller.on_output_event_idle), "refresh", "outputs"]


def test_output_route_param_monitor_moves_with_active_output() -> None:
    controller = routing.SystemWideEqController.__new__(routing.SystemWideEqController)
    calls: list[object] = []

    class FakeBackend(FakeOutputBackend):
        def connect_device_route_changed(self, device_id: int, _callback) -> int:
            calls.append(("connect-route", device_id))
            return device_id + 1000

        def disconnect_device_handler(self, handler_id: int) -> None:
            calls.append(("disconnect-route", handler_id))

    controller.output_backend = FakeBackend(
        [
            make_node(1, "speakers", device_id=72),
            make_node(2, "hdmi", device_id=84),
        ]
    )
    controller.accept_output_events = True
    controller.output_sink = "speakers"
    controller.output_route_param_handler_id = 1072
    controller.output_route_param_device_id = 72

    controller.output_sink = "hdmi"
    routing.SystemWideEqController.refresh_output_route_param_monitor(controller)

    assert controller.output_route_param_handler_id == 1084
    assert controller.output_route_param_device_id == 84
    assert calls == [("disconnect-route", 1072), ("connect-route", 84)]


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


def test_follow_system_default_output_schedules_refresh_when_output_changes(monkeypatch: pytest.MonkeyPatch) -> None:
    controller = routing.SystemWideEqController.__new__(routing.SystemWideEqController)
    controller.follow_default_output = False
    controller.output_sink = "speakers"
    controller.accept_output_events = True
    controller.output_event_source_id = 0
    scheduled_callbacks: list[object] = []

    def fake_refresh() -> bool:
        controller.output_sink = "hdmi"
        return True

    controller.refresh_followed_output_sink = fake_refresh
    monkeypatch.setattr(routing.GLib, "idle_add", lambda callback: scheduled_callbacks.append(callback) or 321)

    routing.SystemWideEqController.follow_system_default_output(controller)

    assert controller.follow_default_output is True
    assert controller.output_event_source_id == 321
    assert len(scheduled_callbacks) == 1


def test_switch_output_sink_retargets_running_filter_output_without_restart() -> None:
    controller = routing.SystemWideEqController.__new__(routing.SystemWideEqController)
    calls: list[object] = []

    class FakeBackend(FakeOutputBackend):
        def move_named_output_stream_to_target(self, stream_node_name: str, target_node_name: str) -> None:
            calls.append(("retarget", stream_node_name, target_node_name))

    class FakeRouter:
        def set_output_sink_name(self, sink_name: str) -> None:
            calls.append(("router-target", sink_name))

    controller.output_backend = FakeBackend([make_node(1, "speakers"), make_node(2, "hdmi")])
    controller.output_sink = "speakers"
    controller.follow_default_output = True
    controller.running = True
    controller.filter_node_id = 42
    controller.filter_output_name = "mini_eq_sink_output"
    controller.virtual_sink_name = "mini_eq_sink"
    controller.stream_router = FakeRouter()
    controller.output_analyzer = None
    controller.apply_state_to_engine = lambda: calls.append("apply")
    controller.emit_status = lambda message: calls.append(("status", message))
    controller.stop_engine = lambda *_args, **_kwargs: calls.append("stop")
    controller.start_engine = lambda: calls.append("start")

    routing.SystemWideEqController.switch_output_sink(controller, "hdmi", explicit=True)

    assert controller.output_sink == "hdmi"
    assert controller.follow_default_output is False
    assert calls == [
        ("router-target", "hdmi"),
        ("retarget", "mini_eq_sink_output", "hdmi"),
        "apply",
        ("status", "filter-chain PipeWire EQ ready: mini_eq_sink -> hdmi"),
    ]


def test_explicit_output_change_schedules_coalesced_output_refresh(monkeypatch: pytest.MonkeyPatch) -> None:
    controller = routing.SystemWideEqController.__new__(routing.SystemWideEqController)
    scheduled_callbacks: list[object] = []

    class FakeBackend(FakeOutputBackend):
        def move_named_output_stream_to_target(self, _stream_node_name: str, _target_node_name: str) -> None:
            return

    controller.output_backend = FakeBackend([make_node(1, "speakers"), make_node(2, "hdmi")])
    controller.output_sink = "speakers"
    controller.follow_default_output = True
    controller.accept_output_events = True
    controller.output_event_source_id = 0
    controller.running = True
    controller.filter_node_id = 42
    controller.filter_output_name = "mini_eq_sink_output"
    controller.virtual_sink_name = "mini_eq_sink"
    controller.stream_router = None
    controller.output_analyzer = None
    controller.apply_state_to_engine = lambda: None
    controller.emit_status = lambda _message: None
    monkeypatch.setattr(routing.GLib, "idle_add", lambda callback: scheduled_callbacks.append(callback) or 321)

    routing.SystemWideEqController.switch_output_sink(controller, "hdmi", explicit=True)

    assert controller.output_sink == "hdmi"
    assert controller.output_event_source_id == 321
    assert len(scheduled_callbacks) == 1


def test_switch_output_sink_falls_back_to_restart_when_filter_retarget_fails() -> None:
    controller = routing.SystemWideEqController.__new__(routing.SystemWideEqController)
    calls: list[object] = []

    class FakeBackend(FakeOutputBackend):
        def move_named_output_stream_to_target(self, stream_node_name: str, target_node_name: str) -> None:
            calls.append(("retarget", stream_node_name, target_node_name))
            raise RuntimeError("filter output missing")

    def stop_engine(*, announce: bool = True) -> None:
        calls.append(("stop", announce))
        controller.running = False

    def start_engine(*, on_ready=None, on_error=None) -> None:
        calls.append("start")
        controller.running = True
        if on_ready is not None:
            on_ready()

    controller.output_backend = FakeBackend([make_node(1, "speakers"), make_node(2, "hdmi")])
    controller.output_sink = "speakers"
    controller.follow_default_output = True
    controller.running = True
    controller.routed = False
    controller.filter_node_id = 42
    controller.filter_output_name = "mini_eq_sink_output"
    controller.virtual_sink_name = "mini_eq_sink"
    controller.stream_router = None
    controller.output_analyzer = None
    controller.apply_state_to_engine = lambda: calls.append("apply")
    controller.emit_status = lambda message: calls.append(("status", message))
    controller.stop_engine = stop_engine
    controller.start_engine = start_engine

    routing.SystemWideEqController.switch_output_sink(controller, "hdmi", explicit=True)

    assert calls == [
        ("retarget", "mini_eq_sink_output", "hdmi"),
        ("status", "filter-chain output retarget warning: filter output missing"),
        ("stop", False),
        "start",
    ]


def test_enabling_analyzer_while_engine_runs_opens_stream_before_restarting_engine() -> None:
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

    def start_engine(*, on_ready=None, on_error=None) -> None:
        calls.append("start")
        controller.running = True
        if on_ready is not None:
            on_ready()

    controller.stop_engine = stop_engine
    controller.start_engine = start_engine

    assert routing.SystemWideEqController.set_analyzer_enabled(controller, True) is True
    assert calls == [
        "stop:False",
        "analyzer:True:running=False",
        "start",
        "route",
    ]


def test_set_analyzer_loudness_callback_updates_existing_analyzer() -> None:
    controller = routing.SystemWideEqController.__new__(routing.SystemWideEqController)
    callbacks: list[object] = []

    class FakeAnalyzer:
        def set_loudness_callback(self, callback) -> None:
            callbacks.append(callback)

    callback = object()
    controller.output_analyzer = FakeAnalyzer()

    routing.SystemWideEqController.set_analyzer_loudness_callback(controller, callback)

    assert controller.analyzer_loudness_callback is callback
    assert callbacks == [callback]


def test_ensure_output_analyzer_passes_loudness_callback(monkeypatch: pytest.MonkeyPatch) -> None:
    controller = routing.SystemWideEqController.__new__(routing.SystemWideEqController)
    controller.output_sink = "speakers"
    controller.output_backend = FakeOutputBackend([make_node(1, "speakers")])
    controller.analyzer_levels_callback = object()
    controller.analyzer_loudness_callback = object()
    controller.analyzer_response_speed = routing.ANALYZER_RESPONSE_DEFAULT
    controller.output_analyzer = None
    created: list[object] = []

    class FakeAnalyzer:
        def __init__(
            self,
            output_sink_name,
            levels_callback,
            status_callback,
            output_sink_description=None,
            loudness_callback=None,
        ) -> None:
            self.output_sink_name = output_sink_name
            self.levels_callback = levels_callback
            self.status_callback = status_callback
            self.output_sink_description = output_sink_description
            self.loudness_callback = loudness_callback
            created.append(self)

        def set_output_sink_name(self, sink_name, sink_description=None) -> None:
            self.output_sink_name = sink_name
            self.output_sink_description = sink_description

        def set_levels_callback(self, callback) -> None:
            self.levels_callback = callback

        def set_loudness_callback(self, callback) -> None:
            self.loudness_callback = callback

        def set_response_speed(self, speed: float) -> None:
            self.response_speed = speed

    monkeypatch.setattr(routing, "OutputSpectrumAnalyzer", FakeAnalyzer)
    controller.emit_status = lambda _message: None

    analyzer_instance = routing.SystemWideEqController.ensure_output_analyzer(controller)

    assert analyzer_instance is created[0]
    assert analyzer_instance.output_sink_name == "speakers"
    assert analyzer_instance.levels_callback is controller.analyzer_levels_callback
    assert analyzer_instance.loudness_callback is controller.analyzer_loudness_callback


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

    def start_engine(*, on_ready=None, on_error=None) -> None:
        nonlocal start_attempts
        start_attempts += 1
        calls.append("start")
        if start_attempts == 1:
            raise RuntimeError("virtual sink did not appear")
        controller.running = True
        if on_ready is not None:
            on_ready()

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

    def start_engine(*, on_ready=None, on_error=None) -> None:
        calls.append("start")
        controller.running = True
        if on_ready is not None:
            on_ready()

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


def test_band_gain_update_skips_engine_when_value_is_unchanged() -> None:
    controller = routing.SystemWideEqController.__new__(routing.SystemWideEqController)
    controller.bands = [core.EqBand(core.FILTER_TYPES["Bell"], 1000.0, 3.0, 1.0)]
    calls: list[int] = []
    controller.apply_band_to_engine = lambda index: calls.append(index)

    assert routing.SystemWideEqController.set_band_gain(controller, 0, 3.0) is False
    assert routing.SystemWideEqController.set_band_gain(controller, 0, 3.1) is True

    assert calls == [0]
    assert controller.bands[0].gain_db == pytest.approx(3.1)


def test_band_gain_update_can_defer_engine_apply() -> None:
    controller = routing.SystemWideEqController.__new__(routing.SystemWideEqController)
    controller.bands = [core.EqBand(core.FILTER_TYPES["Bell"], 1000.0, 3.0, 1.0)]
    calls: list[int] = []
    controller.apply_band_to_engine = lambda index: calls.append(index)

    assert routing.SystemWideEqController.set_band_gain(controller, 0, 3.1, apply=False) is True

    assert calls == []
    assert controller.bands[0].gain_db == pytest.approx(3.1)


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
    controller.start_engine = lambda *, on_ready=None, on_error=None: (calls.append("engine"), on_ready and on_ready())
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
        def unload_filter_chain_module(self, _module) -> None:
            calls.append("unload-engine")

        def sync(self) -> None:
            calls.append("sync-engine")

        def close(self) -> None:
            calls.append("close-backend")

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

    assert calls == ["stop-monitor", "unload-engine", "sync-engine", "close-backend"]
    assert controller.engine_module is None
    assert controller.filter_node_id is None
    assert controller.running is False


def test_shutdown_restores_routed_streams_without_refreshing_followed_output() -> None:
    controller = routing.SystemWideEqController.__new__(routing.SystemWideEqController)
    calls: list[object] = []

    class FakeBackend:
        def unload_filter_chain_module(self, _module) -> None:
            calls.append("unload-engine")

        def sync(self) -> None:
            calls.append("sync-engine")

        def close(self) -> None:
            calls.append("close-backend")

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
        "unload-engine",
        "sync-engine",
        "close-backend",
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


def test_route_system_audio_requires_ready_engine_before_enabling() -> None:
    controller = routing.SystemWideEqController.__new__(routing.SystemWideEqController)
    controller.shutting_down = False
    controller.running = False
    controller.filter_node_id = None
    controller.routed = False
    controller.eq_enabled = True
    calls: list[str] = []

    controller.refresh_followed_output_sink = lambda: calls.append("refresh")
    controller.ensure_stream_router = lambda: calls.append("router")

    with pytest.raises(RuntimeError, match="filter-chain PipeWire EQ is not ready"):
        routing.SystemWideEqController.route_system_audio(controller, True)

    assert calls == ["refresh"]
    assert controller.routed is False


def test_route_system_audio_enables_eq_before_routing() -> None:
    controller = routing.SystemWideEqController.__new__(routing.SystemWideEqController)
    controller.shutting_down = False
    controller.running = True
    controller.filter_node_id = 42
    controller.routed = False
    controller.eq_enabled = False
    controller.virtual_sink_name = "mini_eq_sink"
    calls: list[str] = []

    class FakeRouter:
        def enable(self) -> None:
            calls.append("enable")

    def set_eq_enabled(enabled: bool) -> None:
        calls.append(f"eq:{enabled}")
        controller.eq_enabled = enabled

    controller.refresh_followed_output_sink = lambda: calls.append("refresh")
    controller.set_eq_enabled = set_eq_enabled
    controller.ensure_stream_router = lambda: calls.append("router") or FakeRouter()
    controller.apply_state_to_engine = lambda: calls.append("apply")
    controller.emit_status = lambda message: calls.append(f"status:{message}")

    routing.SystemWideEqController.route_system_audio(controller, True)

    assert calls == [
        "refresh",
        "eq:True",
        "router",
        "enable",
        "apply",
        "status:system audio routed to mini_eq_sink",
    ]
    assert controller.eq_enabled is True
    assert controller.routed is True


def test_route_system_audio_reapplies_current_curve_after_routing() -> None:
    controller = routing.SystemWideEqController.__new__(routing.SystemWideEqController)
    controller.shutting_down = False
    controller.running = True
    controller.filter_node_id = 42
    controller.routed = False
    controller.eq_enabled = True
    controller.virtual_sink_name = "mini_eq_sink"
    calls: list[str] = []

    class FakeRouter:
        def enable(self) -> None:
            calls.append("enable")

    controller.refresh_followed_output_sink = lambda: calls.append("refresh")
    controller.ensure_stream_router = lambda: calls.append("router") or FakeRouter()
    controller.apply_state_to_engine = lambda: calls.append("apply")
    controller.emit_status = lambda message: calls.append(f"status:{message}")

    routing.SystemWideEqController.route_system_audio(controller, True)

    assert calls == [
        "refresh",
        "router",
        "enable",
        "apply",
        "status:system audio routed to mini_eq_sink",
    ]
    assert controller.routed is True


def test_route_system_audio_restores_eq_when_route_enable_fails() -> None:
    controller = routing.SystemWideEqController.__new__(routing.SystemWideEqController)
    controller.shutting_down = False
    controller.running = True
    controller.filter_node_id = 42
    controller.routed = False
    controller.eq_enabled = False
    calls: list[str] = []

    class FailingRouter:
        def enable(self) -> None:
            calls.append("enable")
            raise RuntimeError("route failed")

    def set_eq_enabled(enabled: bool) -> None:
        calls.append(f"eq:{enabled}")
        controller.eq_enabled = enabled

    controller.refresh_followed_output_sink = lambda: calls.append("refresh")
    controller.set_eq_enabled = set_eq_enabled
    controller.ensure_stream_router = lambda: calls.append("router") or FailingRouter()

    with pytest.raises(RuntimeError, match="route failed"):
        routing.SystemWideEqController.route_system_audio(controller, True)

    assert calls == ["refresh", "eq:True", "router", "enable", "eq:False"]
    assert controller.eq_enabled is False
    assert controller.routed is False


def test_route_system_audio_restores_eq_when_engine_enable_fails() -> None:
    controller = routing.SystemWideEqController.__new__(routing.SystemWideEqController)
    controller.shutting_down = False
    controller.running = True
    controller.filter_node_id = 42
    controller.routed = False
    controller.eq_enabled = False
    calls: list[str] = []

    def set_eq_enabled(enabled: bool) -> None:
        calls.append(f"eq:{enabled}")
        controller.eq_enabled = enabled
        if enabled:
            raise RuntimeError("control update failed")

    controller.refresh_followed_output_sink = lambda: calls.append("refresh")
    controller.set_eq_enabled = set_eq_enabled
    controller.ensure_stream_router = lambda: calls.append("router")

    with pytest.raises(RuntimeError, match="control update failed"):
        routing.SystemWideEqController.route_system_audio(controller, True)

    assert calls == ["refresh", "eq:True", "eq:False"]
    assert controller.eq_enabled is False
    assert controller.routed is False


def test_route_system_audio_can_disable_when_engine_is_not_ready() -> None:
    controller = routing.SystemWideEqController.__new__(routing.SystemWideEqController)
    controller.shutting_down = False
    controller.running = False
    controller.filter_node_id = None
    controller.routed = True
    calls: list[str] = []

    class FakeRouter:
        def disable(self, announce: bool = True) -> None:
            calls.append(f"disable:{announce}")

    controller.refresh_followed_output_sink = lambda: calls.append("refresh")
    controller.ensure_stream_router = lambda: calls.append("router") or FakeRouter()
    controller.emit_status = lambda message: calls.append(f"status:{message}")

    routing.SystemWideEqController.route_system_audio(controller, False)

    assert calls == ["refresh", "router", "disable:True", "status:system audio routing disabled"]
    assert controller.routed is False


def test_start_engine_waits_for_filter_chain_node_from_registry() -> None:
    controller = routing.SystemWideEqController.__new__(routing.SystemWideEqController)
    module = object()
    calls: list[str] = []

    class FakeWatch:
        def cancel(self) -> None:
            calls.append("cancel")

    class FakeBackend:
        def __init__(self) -> None:
            self.callback = None

        def load_filter_chain_module(self, arguments: str):
            calls.append(f"load:{arguments}")
            return module

        def watch_for_audio_sink(self, sink_name: str, callback, *, timeout_ms: int):
            calls.append(f"wait:{sink_name}:{timeout_ms}")
            self.callback = callback
            return FakeWatch()

    backend = FakeBackend()
    controller.engine_module = None
    controller.engine_start_pending = False
    controller.engine_start_watch = None
    controller.filter_node_id = None
    controller.running = False
    controller.output_backend = backend
    controller.virtual_sink_name = "mini_eq_sink"
    controller.output_sink = "speakers"
    controller.build_filter_chain_module_args = lambda: "module args"
    controller.emit_status = lambda message: calls.append(f"status:{message}")
    controller.apply_state_to_engine = lambda: calls.append("apply")

    routing.SystemWideEqController.start_engine(controller)
    assert backend.callback is not None
    backend.callback(make_node(42, "mini_eq_sink"))

    assert calls == [
        "load:module args",
        "wait:mini_eq_sink:3000",
        "status:filter-chain PipeWire EQ ready: mini_eq_sink -> speakers",
        "apply",
    ]
    assert controller.engine_module is module
    assert controller.filter_node_id == 42
    assert controller.running is True


def test_start_engine_clears_module_when_filter_chain_node_times_out() -> None:
    controller = routing.SystemWideEqController.__new__(routing.SystemWideEqController)
    module = object()
    calls: list[str] = []

    class FakeWatch:
        def cancel(self) -> None:
            calls.append("cancel")

    class FakeBackend:
        def __init__(self) -> None:
            self.callback = None

        def load_filter_chain_module(self, arguments: str):
            calls.append(f"load:{arguments}")
            return module

        def watch_for_audio_sink(self, sink_name: str, callback, *, timeout_ms: int):
            calls.append(f"wait:{sink_name}:{timeout_ms}")
            self.callback = callback
            return FakeWatch()

        def sync(self) -> None:
            calls.append("sync")

    backend = FakeBackend()
    controller.engine_module = None
    controller.engine_start_pending = False
    controller.engine_start_watch = None
    controller.filter_node_id = None
    controller.running = False
    controller.output_backend = backend
    controller.virtual_sink_name = "mini_eq_sink"
    controller.output_sink = "speakers"
    controller.build_filter_chain_module_args = lambda: "module args"
    errors: list[str] = []

    routing.SystemWideEqController.start_engine(controller, on_error=lambda exc: errors.append(str(exc)))
    assert backend.callback is not None
    backend.callback(None)

    assert calls == ["load:module args", "wait:mini_eq_sink:3000", "sync"]
    assert errors == ["filter-chain did not create mini_eq_sink"]
    assert controller.engine_module is None
    assert controller.filter_node_id is None
    assert controller.running is False


def test_stop_engine_unloads_filter_chain_module_before_clearing_state() -> None:
    controller = routing.SystemWideEqController.__new__(routing.SystemWideEqController)
    module = object()
    calls: list[str] = []

    class FakeBackend:
        def unload_filter_chain_module(self, loaded_module) -> None:
            assert loaded_module is module
            calls.append("unload")

        def sync(self) -> None:
            calls.append("sync")

    controller.engine_module = module
    controller.filter_node_id = 42
    controller.running = True
    controller.output_backend = FakeBackend()
    controller.emit_status = lambda message: calls.append(f"status:{message}")

    routing.SystemWideEqController.stop_engine(controller, announce=False)

    assert calls == ["unload", "sync"]
    assert controller.engine_module is None
    assert controller.filter_node_id is None
    assert controller.running is False


def test_restart_engine_pauses_stream_router_monitoring_during_restart() -> None:
    controller = routing.SystemWideEqController.__new__(routing.SystemWideEqController)
    controller.running = True
    controller.routed = True
    calls: list[str] = []

    class FakeRouter:
        def stop_monitoring(self) -> None:
            calls.append("stop-monitoring")

        def restore_output_streams(self) -> None:
            calls.append("restore")

        def emit_warning(self, exc: Exception) -> None:
            calls.append(f"warning:{exc}")

        def start_monitoring(self, *, require_initial_route: bool = False) -> None:
            calls.append(f"start-monitoring:{require_initial_route}")

    controller.stream_router = FakeRouter()
    controller.stop_engine = lambda *, announce=True: calls.append(f"stop-engine:{announce}")
    controller.start_engine = lambda *, on_ready=None, on_error=None: (
        calls.append("start-engine"),
        on_ready and on_ready(),
    )

    routing.SystemWideEqController.restart_engine(controller)

    assert calls == [
        "stop-monitoring",
        "restore",
        "stop-engine:False",
        "start-engine",
        "start-monitoring:True",
    ]


def test_restart_engine_continues_when_routed_stream_restore_fails() -> None:
    controller = routing.SystemWideEqController.__new__(routing.SystemWideEqController)
    controller.running = True
    controller.routed = True
    calls: list[str] = []

    class FakeRouter:
        def stop_monitoring(self) -> None:
            calls.append("stop-monitoring")

        def restore_output_streams(self) -> None:
            calls.append("restore")
            raise RuntimeError("restore failed")

        def emit_warning(self, exc: Exception) -> None:
            calls.append(f"warning:{exc}")

        def start_monitoring(self, *, require_initial_route: bool = False) -> None:
            calls.append(f"start-monitoring:{require_initial_route}")

    controller.stream_router = FakeRouter()
    controller.stop_engine = lambda *, announce=True: calls.append(f"stop-engine:{announce}")
    controller.start_engine = lambda *, on_ready=None, on_error=None: (
        calls.append("start-engine"),
        on_ready and on_ready(),
    )

    routing.SystemWideEqController.restart_engine(controller)

    assert calls == [
        "stop-monitoring",
        "restore",
        "warning:restore failed",
        "stop-engine:False",
        "start-engine",
        "start-monitoring:True",
    ]


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
