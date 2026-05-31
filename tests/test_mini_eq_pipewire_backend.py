from __future__ import annotations

from types import SimpleNamespace

import pytest

from tests._mini_eq_imports import pipewire_backend as pw_backend
from tests._mini_eq_imports import pipewire_routes as pw_routes


class FakeCore:
    calls: int = 0

    def __init__(self) -> None:
        self.pipewire_properties: dict[str, str | None] = {}

    @classmethod
    def new(cls):
        cls.calls += 1
        return cls()

    def set_pipewire_property(self, key: str, value: str | None) -> bool:
        self.pipewire_properties[key] = value
        return True


class FakeCorePwg:
    Core = FakeCore


class FakeNodeProxy:
    def __init__(self, bound_id: int, set_result: bool = True) -> None:
        self.bound_id = bound_id
        self.set_result = set_result
        self.set_calls: list[tuple[str, int, object]] = []

    def get_bound_id(self) -> int:
        return self.bound_id

    def set_param(self, param_id: str, flags: int, pod) -> bool:
        self.set_calls.append((param_id, flags, pod))
        return self.set_result


class FakePropertyItem:
    def __init__(self, key: str, value: str, *, undecodable: bool = False) -> None:
        self.key = key
        self.value = value
        self.undecodable = undecodable

    def get_key(self) -> str:
        return self.key

    def get_value(self) -> str:
        if self.undecodable:
            raise UnicodeDecodeError("utf-8", b"\x96", 0, 1, "invalid start byte")
        return self.value


class FakePropertyIterator:
    def __init__(self, items: list[FakePropertyItem]) -> None:
        self.items = items
        self.index = 0

    def next(self) -> tuple[bool, FakePropertyItem | None]:
        if self.index >= len(self.items):
            return False, None

        item = self.items[self.index]
        self.index += 1
        return True, item


class FakeGlobalProperties:
    def __init__(self, items: list[FakePropertyItem], values: dict[str, str] | None = None) -> None:
        self.items = items
        self.values = values or {}

    def new_iterator(self) -> FakePropertyIterator:
        return FakePropertyIterator(self.items)

    def get(self, key: str) -> str | None:
        return self.values.get(key)


class FakePropertyProxy:
    def __init__(self, properties: FakeGlobalProperties) -> None:
        self.properties = properties

    def get_properties(self) -> FakeGlobalProperties:
        return self.properties

    def get_global_properties(self) -> FakeGlobalProperties:
        return self.properties


def make_node_global(
    bound_id: int,
    name: str | None,
    media_class: str = pw_backend.AUDIO_SINK,
) -> FakePropertyProxy:
    properties = [
        FakePropertyItem("object.serial", str(bound_id + 1000)),
        FakePropertyItem("media.class", media_class),
    ]
    if name is not None:
        properties.append(FakePropertyItem("node.name", name))

    class FakeGlobal(FakePropertyProxy):
        def get_id(self) -> int:
            return bound_id

    return FakeGlobal(FakeGlobalProperties(properties))


class FakeModel:
    def __init__(self, items: list[object]) -> None:
        self.items = items

    def get_n_items(self) -> int:
        return len(self.items)

    def get_item(self, index: int) -> object:
        return self.items[index]


class FakeWaitRegistry:
    def __init__(self, globals_: list[object]) -> None:
        self.globals = globals_
        self.callbacks = {}
        self.disconnected: list[int] = []
        self.next_handler_id = 1

    def dup_globals_by_interface(self, interface_type: str) -> FakeModel:
        assert interface_type == pw_backend.PIPEWIRE_NODE_INTERFACE
        return FakeModel(self.globals)

    def connect(self, signal_name: str, callback) -> int:
        assert signal_name == "global-added"
        handler_id = self.next_handler_id
        self.next_handler_id += 1
        self.callbacks[handler_id] = callback
        return handler_id

    def disconnect(self, handler_id: int) -> None:
        self.disconnected.append(handler_id)
        self.callbacks.pop(handler_id, None)

    def emit_global_added(self, global_) -> None:
        for callback in list(self.callbacks.values()):
            callback(self, global_)


class FakeWaitObject:
    @staticmethod
    def connect(obj, signal_name: str, callback) -> int:
        return obj.connect(signal_name, callback)


class FakeWaitGObject:
    Object = FakeWaitObject


class FakeWaitGLib:
    def __init__(self) -> None:
        self.idle_callback = None
        self.removed_sources: list[int] = []
        self.timeout_callback = None
        self.timeout_ms: int | None = None

    def idle_add(self, callback) -> int:
        self.idle_callback = callback
        return 88

    def timeout_add(self, timeout_ms: int, callback) -> int:
        self.timeout_ms = timeout_ms
        self.timeout_callback = callback
        return 77

    def source_remove(self, source_id: int) -> bool:
        self.removed_sources.append(source_id)
        return True

    def run_idle(self) -> None:
        assert self.idle_callback is not None
        callback = self.idle_callback
        self.idle_callback = None
        callback()


class FakeSource:
    def __init__(self) -> None:
        self.destroyed = False

    def destroy(self) -> None:
        self.destroyed = True


class FakeSyncCore:
    def __init__(self) -> None:
        self.sync_calls: list[int] = []

    def sync(self, timeout_ms: int) -> bool:
        self.sync_calls.append(timeout_ms)
        return True


class FakeMainContext:
    def __init__(self, source: FakeSource) -> None:
        self.source = source
        self.pending_count = 1
        self.iterations = 0

    def default(self) -> FakeMainContext:
        return self

    def pending(self) -> bool:
        return self.pending_count > 0

    def iteration(self, _may_block: bool) -> None:
        self.iterations += 1
        self.pending_count -= 1

    def find_source_by_id(self, source_id: int) -> FakeSource | None:
        return self.source if source_id == 77 else None


class FakeSyncGLib:
    def __init__(self, core: FakeSyncCore) -> None:
        self.source = FakeSource()
        self.MainContext = FakeMainContext(self.source)
        self.timeout_callback = None

    def timeout_add(self, _timeout_ms: int, callback) -> int:
        self.timeout_callback = callback
        return 77


class FakeVariant:
    def __init__(self, signature: str, value: dict[str, float]) -> None:
        self.signature = signature
        self.value = value


class FakeGLib:
    Variant = FakeVariant


class FakePwgParam:
    calls: list[FakeVariant] = []

    @classmethod
    def new_props_controls(cls, variant: FakeVariant):
        cls.calls.append(variant)
        return ("param", variant)


class FakePwg:
    Param = FakePwgParam


class FakeDeviceApi:
    @staticmethod
    def enum_params_sync():
        return None

    @staticmethod
    def new():
        return None

    @staticmethod
    def subscribe_params():
        return None

    @staticmethod
    def sync():
        return None


class FakeRouteInfoApi:
    @staticmethod
    def new_from_param(_param):
        return None


def test_parse_metadata_node_name_reads_wireplumber_json_name() -> None:
    assert pw_backend.parse_metadata_node_name('{"name":"alsa_output.test"}') == "alsa_output.test"


def test_parse_metadata_node_name_accepts_plain_string() -> None:
    assert pw_backend.parse_metadata_node_name("mini_eq_sink") == "mini_eq_sink"


def test_parse_metadata_node_name_rejects_invalid_shape() -> None:
    assert pw_backend.parse_metadata_node_name("[1, 2, 3]") is None


def test_parse_bool_property_accepts_wireplumber_truthy_values() -> None:
    assert pw_backend.parse_bool_property("true") is True
    assert pw_backend.parse_bool_property("1") is True
    assert pw_backend.parse_bool_property("false") is False
    assert pw_backend.parse_bool_property(None) is False


def test_node_sample_rate_uses_audio_rate_and_latency_fallbacks() -> None:
    direct_rate = pw_backend.PipeWireNode(
        bound_id=39,
        object_serial="67",
        media_class=pw_backend.AUDIO_SINK,
        node_name="alsa_output.direct",
        node_description=None,
        application_name=None,
        node_dont_move=False,
        properties={"audio.rate": "48000", "node.max-latency": "1024/44100"},
    )
    max_latency_rate = pw_backend.PipeWireNode(
        bound_id=40,
        object_serial="68",
        media_class=pw_backend.AUDIO_SINK,
        node_name="alsa_output.max_latency",
        node_description=None,
        application_name=None,
        node_dont_move=False,
        properties={"node.max-latency": "1024/44100"},
    )
    latency_rate = pw_backend.PipeWireNode(
        bound_id=41,
        object_serial="69",
        media_class=pw_backend.AUDIO_SINK,
        node_name="alsa_output.latency",
        node_description=None,
        application_name=None,
        node_dont_move=False,
        properties={"node.latency": "1024/96000"},
    )

    assert pw_backend.node_sample_rate(direct_rate) == 48000.0
    assert pw_backend.node_sample_rate(max_latency_rate) == 44100.0
    assert pw_backend.node_sample_rate(latency_rate) == 96000.0
    assert pw_backend.node_sample_rate(None) == 0.0


def test_node_classification_and_display_name() -> None:
    sink = pw_backend.PipeWireNode(
        bound_id=39,
        object_serial="67",
        media_class=pw_backend.AUDIO_SINK,
        node_name="alsa_output.test",
        node_description="Test Sink",
        application_name=None,
        node_dont_move=False,
    )
    stream = pw_backend.PipeWireNode(
        bound_id=126,
        object_serial="300",
        media_class=pw_backend.STREAM_OUTPUT_AUDIO,
        node_name="spotify",
        node_description=None,
        application_name="spotify",
        node_dont_move=False,
    )

    assert sink.is_audio_sink is True
    assert sink.is_output_stream is False
    assert sink.display_name == "Test Sink"
    assert stream.is_audio_sink is False
    assert stream.is_output_stream is True
    assert stream.display_name == "spotify"


def test_node_from_global_copies_device_route_properties() -> None:
    backend = pw_backend.PipeWireBackend()

    class FakeGlobal(FakePropertyProxy):
        def get_id(self) -> int:
            return 39

    node = backend._node_from_global(
        FakeGlobal(
            FakeGlobalProperties(
                [
                    FakePropertyItem("object.serial", "67"),
                    FakePropertyItem("media.class", pw_backend.AUDIO_SINK),
                    FakePropertyItem("node.name", "alsa_output.test"),
                    FakePropertyItem("device.id", "72"),
                    FakePropertyItem("card.profile.device", "8"),
                ]
            )
        )
    )

    assert node.device_id == 72
    assert node.card_profile_device == 8


def test_node_from_global_enriches_device_label_properties() -> None:
    backend = pw_backend.PipeWireBackend()

    class FakeNodeGlobal(FakePropertyProxy):
        def get_id(self) -> int:
            return 39

    class FakeDeviceGlobal(FakePropertyProxy):
        def is_device(self) -> bool:
            return True

    class FakeRegistry:
        def __init__(self) -> None:
            self.device = FakeDeviceGlobal(
                FakeGlobalProperties(
                    [
                        FakePropertyItem("device.name", "alsa_card.pci-0000_00_1f.3"),
                        FakePropertyItem("device.description", "Audio interno"),
                        FakePropertyItem("device.nick", "HDA Intel PCH"),
                    ]
                )
            )

        def lookup_global(self, bound_id: int) -> FakeDeviceGlobal | None:
            return self.device if bound_id == 72 else None

    backend._registry = FakeRegistry()
    node = backend._node_from_global(
        FakeNodeGlobal(
            FakeGlobalProperties(
                [
                    FakePropertyItem("object.serial", "67"),
                    FakePropertyItem("media.class", pw_backend.AUDIO_SINK),
                    FakePropertyItem("node.name", "alsa_output.hdmi"),
                    FakePropertyItem("node.description", "Audio interno Stereo digitale (HDMI)"),
                    FakePropertyItem("device.id", "72"),
                    FakePropertyItem("card.profile.device", "8"),
                ]
            )
        )
    )

    assert node.node_description == "Audio interno Stereo digitale (HDMI)"
    assert node.property_value("device.description") == "Audio interno"
    assert node.property_value("device.nick") == "HDA Intel PCH"
    assert node.property_value("device.name") == "alsa_card.pci-0000_00_1f.3"


def test_link_from_global_copies_pipewire_link_identity() -> None:
    backend = pw_backend.PipeWireBackend()

    class FakeLinkInfo:
        def get_id(self) -> int:
            return 90

        def dup_output_node_id(self) -> str:
            return "12"

        def dup_input_node_id(self) -> str:
            return "34"

        def get_passive(self) -> bool:
            return True

        def get_feedback(self) -> bool:
            return False

    class FakeLinkInfoApi:
        @staticmethod
        def new_from_global(global_):
            assert global_ == "global"
            return FakeLinkInfo()

    backend._Pwg = SimpleNamespace(LinkInfo=FakeLinkInfoApi)

    link = backend._link_from_global("global")

    assert link == pw_backend.PipeWireLink(
        bound_id=90,
        output_node_id=12,
        input_node_id=34,
        passive=True,
        feedback=False,
    )


def test_list_links_reads_pipewire_link_globals() -> None:
    link_global = object()
    parsed_link = pw_backend.PipeWireLink(
        bound_id=90,
        output_node_id=12,
        input_node_id=34,
        passive=False,
        feedback=False,
    )

    class FakeRegistry:
        def dup_globals_by_interface(self, interface_type: str) -> FakeModel:
            assert interface_type == pw_backend.PIPEWIRE_LINK_INTERFACE
            return FakeModel([link_global])

    backend = pw_backend.PipeWireBackend()
    backend._ensure_connected = lambda: None
    backend._registry = FakeRegistry()
    backend._link_from_global = lambda global_: parsed_link if global_ is link_global else None

    assert backend.list_links() == [parsed_link]


def test_connect_link_state_changed_binds_and_dispatches_state() -> None:
    class FakeLinkGlobal:
        def is_link(self) -> bool:
            return True

    class FakeRegistry:
        def __init__(self) -> None:
            self.global_ = FakeLinkGlobal()

        def lookup_global(self, bound_id: int) -> FakeLinkGlobal | None:
            return self.global_ if bound_id == 92 else None

    class FakeLiveLink:
        def __init__(self) -> None:
            self.state = "paused"
            self.running = False
            self.start_calls = 0
            self.sync_calls: list[int] = []
            self.disconnected: list[int] = []
            self.state_callback = None

        def get_running(self) -> bool:
            return self.running

        def start(self) -> bool:
            self.running = True
            self.start_calls += 1
            return True

        def sync(self, timeout_ms: int) -> bool:
            self.sync_calls.append(timeout_ms)
            return True

        def get_state(self) -> str:
            return self.state

        def disconnect(self, handler_id: int) -> None:
            self.disconnected.append(handler_id)

        def emit_state(self, state: str) -> None:
            assert self.state_callback is not None
            self.state = state
            self.state_callback(self, None)

    class FakeLinkApi:
        created: list[FakeLiveLink] = []

        @classmethod
        def new(cls, _core, _global) -> FakeLiveLink:
            link = FakeLiveLink()
            cls.created.append(link)
            return link

    class FakeGObjectObject:
        @staticmethod
        def connect(link: FakeLiveLink, signal_name: str, callback) -> int:
            assert signal_name == "notify::state"
            link.state_callback = callback
            return 77

    backend = pw_backend.PipeWireBackend(timeout_ms=1234)
    backend._ensure_connected = lambda: None
    backend._core = object()
    backend._registry = FakeRegistry()
    backend._Pwg = SimpleNamespace(Link=FakeLinkApi)
    backend._GObject = SimpleNamespace(Object=FakeGObjectObject)
    states: list[str | None] = []

    handler_id = backend.connect_link_state_changed(92, states.append)
    link = FakeLinkApi.created[0]
    link.emit_state("active")
    backend.disconnect_link_handler(handler_id)

    assert handler_id == 77
    assert link.start_calls == 1
    assert link.sync_calls == [1234]
    assert states == ["paused", "active"]
    assert link.disconnected == [77]


def test_connect_node_state_changed_binds_and_dispatches_state_and_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeLiveNode:
        def __init__(self) -> None:
            self.state = "suspended"
            self.error: str | None = None
            self.disconnected: list[int] = []
            self.state_callback = None
            self.error_callback = None

        def get_state(self) -> str | None:
            return self.state

        def dup_error(self) -> str | None:
            return self.error

        def disconnect(self, handler_id: int) -> None:
            self.disconnected.append(handler_id)

        def emit_state(self, state: str, error: str | None = None) -> None:
            assert self.state_callback is not None
            self.state = state
            self.error = error
            self.state_callback(self, None)

        def emit_error(self, error: str | None) -> None:
            assert self.error_callback is not None
            self.error = error
            self.error_callback(self, None)

    class FakeNodeApi:
        @staticmethod
        def get_state():
            return None

        @staticmethod
        def dup_error():
            return None

    class FakeGObjectObject:
        @staticmethod
        def connect(node: FakeLiveNode, signal_name: str, callback) -> int:
            if signal_name == "notify::state":
                node.state_callback = callback
                return 77
            if signal_name == "notify::error":
                node.error_callback = callback
                return 78
            raise AssertionError(f"unexpected signal: {signal_name}")

    node = FakeLiveNode()
    backend = pw_backend.PipeWireBackend()
    backend._Pwg = SimpleNamespace(Node=FakeNodeApi)
    backend._GObject = SimpleNamespace(Object=FakeGObjectObject)
    backend._ensure_connected = lambda: None
    monkeypatch.setattr(backend, "_node_proxy_by_bound_id", lambda _bound_id: node)
    states: list[tuple[str | None, str | None]] = []

    handler_id = backend.connect_node_state_changed(42, lambda state, error: states.append((state, error)))
    node.emit_state("running")
    node.emit_error("device suspended")
    backend.disconnect_node_state_handler(handler_id)

    assert handler_id == 77
    assert states == [
        ("suspended", None),
        ("running", None),
        ("running", "device suspended"),
    ]
    assert node.disconnected == [78, 77]


def test_connect_node_param_changed_subscribes_and_dispatches_matching_param(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeParam:
        def __init__(self, param_id: int) -> None:
            self.param_id = param_id

        def get_id(self) -> int:
            return self.param_id

    class FakeParamInfo:
        def __init__(self, param_id: int, name: str) -> None:
            self.param_id = param_id
            self.name = name

        def get_id(self) -> int:
            return self.param_id

        def dup_name(self) -> str:
            return self.name

    class FakeLiveNode:
        def __init__(self) -> None:
            self.param_infos = FakeModel([FakeParamInfo(13, "Props"), FakeParamInfo(14, "Format")])
            self.subscriptions: list[FakeVariant] = []
            self.disconnected: list[int] = []
            self.param_callback = None
            self.param_infos_callback = None

        def get_param_infos(self) -> FakeModel:
            return self.param_infos

        def subscribe_params(self, ids: FakeVariant) -> None:
            self.subscriptions.append(ids)

        def disconnect(self, handler_id: int) -> None:
            self.disconnected.append(handler_id)

        def emit_param(self, param_id: int) -> None:
            assert self.param_callback is not None
            self.param_callback(self, FakeParam(param_id))

        def emit_param_infos_changed(self) -> None:
            assert self.param_infos_callback is not None
            self.param_infos_callback(self, None)

    class FakeNodeApi:
        @staticmethod
        def enum_params_sync():
            return None

        @staticmethod
        def new():
            return None

        @staticmethod
        def subscribe_params():
            return None

        @staticmethod
        def sync():
            return None

    class FakeGObjectObject:
        @staticmethod
        def connect(node: FakeLiveNode, signal_name: str, callback) -> int:
            if signal_name == "param":
                node.param_callback = callback
                return 77
            if signal_name == "notify::param-infos":
                node.param_infos_callback = callback
                return 78
            raise AssertionError(f"unexpected signal: {signal_name}")

    node = FakeLiveNode()
    backend = pw_backend.PipeWireBackend()
    backend._Pwg = SimpleNamespace(Node=FakeNodeApi)
    backend._GLib = FakeGLib
    backend._GObject = SimpleNamespace(Object=FakeGObjectObject)
    backend._ensure_connected = lambda: None
    backend._sync_proxy = lambda _proxy, _label: None
    monkeypatch.setattr(backend, "_node_proxy_by_bound_id", lambda _bound_id: node)
    calls: list[str] = []

    handler_id = backend.connect_node_param_changed(42, "Props", lambda: calls.append("props"))

    assert handler_id == 77
    assert [(variant.signature, variant.value) for variant in node.subscriptions] == [("au", [13])]

    node.emit_param(14)
    assert calls == []

    node.emit_param(13)
    node.emit_param_infos_changed()

    assert calls == ["props", "props"]

    backend.disconnect_node_param_handler(handler_id)

    assert [(variant.signature, variant.value) for variant in node.subscriptions] == [("au", [13]), ("au", [])]
    assert node.disconnected == [78, 77]


def test_new_core_uses_pipewire_gobject_core_constructor() -> None:
    FakeCore.calls = 0

    core = pw_backend.PipeWireBackend._new_core(FakeCorePwg)

    assert FakeCore.calls == 1
    assert core.pipewire_properties == {
        "application.name": "Mini EQ",
        "media.category": "Manager",
    }


def test_sync_core_uses_roundtrip() -> None:
    core = FakeSyncCore()
    backend = pw_backend.PipeWireBackend()
    backend._core = core

    backend._sync_core()

    assert core.sync_calls == [2000]


def test_watch_for_audio_sink_reports_existing_registry_node_on_idle() -> None:
    registry = FakeWaitRegistry([make_node_global(42, "mini_eq_sink")])
    glib = FakeWaitGLib()
    backend = pw_backend.PipeWireBackend()
    backend._ensure_connected = lambda: None
    backend._registry = registry
    backend._GLib = glib
    backend._GObject = FakeWaitGObject
    nodes: list[pw_backend.PipeWireNode | None] = []

    backend.watch_for_audio_sink("mini_eq_sink", nodes.append, timeout_ms=1234)

    assert nodes == []
    glib.run_idle()
    assert nodes[0] is not None
    assert nodes[0].bound_id == 42
    assert glib.timeout_ms is None
    assert registry.disconnected == [1]


def test_watch_for_audio_sink_resolves_from_global_added_signal() -> None:
    registry = FakeWaitRegistry([make_node_global(1, "speakers")])
    glib = FakeWaitGLib()
    backend = pw_backend.PipeWireBackend()
    backend._ensure_connected = lambda: None
    backend._registry = registry
    backend._GLib = glib
    backend._GObject = FakeWaitGObject
    nodes: list[pw_backend.PipeWireNode | None] = []

    backend.watch_for_audio_sink("mini_eq_sink", nodes.append, timeout_ms=1234)
    registry.emit_global_added(make_node_global(42, "mini_eq_sink"))

    assert nodes == []
    glib.run_idle()
    assert nodes[0] is not None
    assert nodes[0].bound_id == 42
    assert glib.timeout_ms == 1234
    assert glib.removed_sources == [77]
    assert registry.disconnected == [1]


def test_watch_for_audio_sink_reports_none_on_timeout() -> None:
    registry = FakeWaitRegistry([make_node_global(1, "speakers")])
    glib = FakeWaitGLib()
    backend = pw_backend.PipeWireBackend()
    backend._ensure_connected = lambda: None
    backend._registry = registry
    backend._GLib = glib
    backend._GObject = FakeWaitGObject
    nodes: list[pw_backend.PipeWireNode | None] = []

    backend.watch_for_audio_sink("mini_eq_sink", nodes.append, timeout_ms=1234)
    glib.timeout_callback()

    assert nodes == [None]
    assert glib.timeout_ms == 1234
    assert glib.removed_sources == []
    assert registry.disconnected == [1]


def test_move_stream_to_target_sets_stream_target_without_metadata_readback() -> None:
    backend = pw_backend.PipeWireBackend()
    stream = pw_backend.PipeWireNode(
        bound_id=126,
        object_serial="300",
        media_class=pw_backend.STREAM_OUTPUT_AUDIO,
        node_name="spotify",
        node_description=None,
        application_name="spotify",
        node_dont_move=False,
    )
    sink = pw_backend.PipeWireNode(
        bound_id=39,
        object_serial="67",
        media_class=pw_backend.AUDIO_SINK,
        node_name="alsa_output.test",
        node_description="Test Sink",
        application_name=None,
        node_dont_move=False,
    )

    backend.output_stream_by_bound_id = lambda _bound_id: stream
    backend.audio_sink_by_name = lambda _name: sink
    calls: list[tuple[int, int, str]] = []
    backend.set_stream_target = lambda *args: calls.append(args)

    backend.move_stream_to_target(126, "alsa_output.test")

    assert calls == [(126, 39, "67")]


def test_output_preset_keys_prefer_matching_active_route(monkeypatch: pytest.MonkeyPatch) -> None:
    backend = pw_backend.PipeWireBackend()
    backend._Pwg = SimpleNamespace(Device=FakeDeviceApi, RouteInfo=FakeRouteInfoApi)
    sink = pw_backend.PipeWireNode(
        bound_id=39,
        object_serial="67",
        media_class=pw_backend.AUDIO_SINK,
        node_name="alsa_output.test",
        node_description="Test Sink",
        application_name=None,
        node_dont_move=False,
        device_id=72,
        card_profile_device=8,
    )
    line_out = pw_routes.PipeWireOutputRoute(
        device_bound_id=72,
        device_name="alsa_card.test",
        index=0,
        route_device=7,
        profile=0,
        priority=100,
        direction="Output",
        name="analog-output-lineout",
        description="Line Out",
        availability="yes",
    )
    headphones = pw_routes.PipeWireOutputRoute(
        device_bound_id=72,
        device_name="alsa_card.test",
        index=1,
        route_device=8,
        profile=0,
        priority=200,
        direction="Output",
        name="analog-output-headphones",
        description="Headphones",
        availability="yes",
    )

    monkeypatch.setattr(backend, "audio_sink_by_name", lambda _name: sink)
    monkeypatch.setattr(backend, "_device_proxy_by_bound_id", lambda _bound_id: object())
    monkeypatch.setattr(backend, "_enumerate_device_routes", lambda _device, _bound_id: [line_out, headphones])

    assert backend.output_preset_keys_for_sink_name("alsa_output.test") == (
        "pipewire-route:v1:device=alsa_card.test;route=analog-output-headphones;route-device=8",
        "alsa_output.test",
    )


def test_output_preset_keys_use_single_route_even_when_profile_device_is_stale(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = pw_backend.PipeWireBackend()
    backend._Pwg = SimpleNamespace(Device=FakeDeviceApi, RouteInfo=FakeRouteInfoApi)
    sink = pw_backend.PipeWireNode(
        bound_id=39,
        object_serial="67",
        media_class=pw_backend.AUDIO_SINK,
        node_name="alsa_output.test",
        node_description="Test Sink",
        application_name=None,
        node_dont_move=False,
        device_id=72,
        card_profile_device=8,
    )
    speakers = pw_routes.PipeWireOutputRoute(
        device_bound_id=72,
        device_name="alsa_card.test",
        index=0,
        route_device=6,
        profile=0,
        priority=100,
        direction="Output",
        name="analog-output-speaker",
        description="Speakers",
        availability="unknown",
    )

    monkeypatch.setattr(backend, "audio_sink_by_name", lambda _name: sink)
    monkeypatch.setattr(backend, "_device_proxy_by_bound_id", lambda _bound_id: object())
    monkeypatch.setattr(backend, "_enumerate_device_routes", lambda _device, _bound_id: [speakers])

    assert backend.output_preset_keys_for_sink_name("alsa_output.test") == (
        "pipewire-route:v1:device=alsa_card.test;route=analog-output-speaker;route-device=6",
        "alsa_output.test",
    )


def test_output_preset_keys_do_not_guess_between_routes_sharing_profile_device(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = pw_backend.PipeWireBackend()
    backend._Pwg = SimpleNamespace(Device=FakeDeviceApi, RouteInfo=FakeRouteInfoApi)
    sink = pw_backend.PipeWireNode(
        bound_id=39,
        object_serial="67",
        media_class=pw_backend.AUDIO_SINK,
        node_name="alsa_output.test",
        node_description="Test Sink",
        application_name=None,
        node_dont_move=False,
        device_id=72,
        card_profile_device=6,
    )
    speakers = pw_routes.PipeWireOutputRoute(
        device_bound_id=72,
        device_name="alsa_card.test",
        index=0,
        route_device=6,
        profile=0,
        priority=100,
        direction="Output",
        name="analog-output-speaker",
        description="Speakers",
        availability="unknown",
    )
    headphones = pw_routes.PipeWireOutputRoute(
        device_bound_id=72,
        device_name="alsa_card.test",
        index=1,
        route_device=6,
        profile=0,
        priority=200,
        direction="Output",
        name="analog-output-headphones",
        description="Headphones",
        availability="yes",
    )

    monkeypatch.setattr(backend, "audio_sink_by_name", lambda _name: sink)
    monkeypatch.setattr(backend, "_device_proxy_by_bound_id", lambda _bound_id: object())
    monkeypatch.setattr(backend, "_enumerate_device_routes", lambda _device, _bound_id: [speakers, headphones])

    assert backend.output_preset_keys_for_sink_name("alsa_output.test") == ("alsa_output.test",)


def test_output_preset_keys_fall_back_to_sink_name_without_route_api(monkeypatch: pytest.MonkeyPatch) -> None:
    backend = pw_backend.PipeWireBackend()
    backend._Pwg = SimpleNamespace()
    sink = pw_backend.PipeWireNode(
        bound_id=39,
        object_serial="67",
        media_class=pw_backend.AUDIO_SINK,
        node_name="alsa_output.test",
        node_description="Test Sink",
        application_name=None,
        node_dont_move=False,
        device_id=72,
        card_profile_device=8,
    )

    monkeypatch.setattr(backend, "audio_sink_by_name", lambda _name: sink)

    assert backend.output_preset_keys_for_sink_name("alsa_output.test") == ("alsa_output.test",)


def test_enumerate_device_routes_ignores_enum_route_params(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeParam:
        def __init__(self, name: str, *, seq: int = 12, next_index: int = 0) -> None:
            self.name = name
            self.seq = seq
            self.next_index = next_index

        def get_seq(self) -> int:
            return self.seq

        def get_next(self) -> int:
            return self.next_index

        def dup_name(self) -> str:
            return self.name

    class FakeParamInfo:
        def get_id(self) -> int:
            return 13

        def dup_name(self) -> str:
            return "Route"

    class FakeModel:
        def __init__(self, items: list[object]) -> None:
            self.items = items

        def get_n_items(self) -> int:
            return len(self.items)

        def get_item(self, index: int) -> object:
            return self.items[index]

    class FakeDevice:
        def __init__(self) -> None:
            self.params = FakeModel([FakeParam("EnumRoute"), FakeParam("Route")])
            self.param_infos = FakeModel([FakeParamInfo()])
            self.enum_calls: list[tuple[int, int, int]] = []

        def enum_params_sync(self, param_id: int, start: int, num: int, _timeout_ms: int) -> FakeModel:
            self.enum_calls.append((param_id, start, num))
            return self.params

        def get_params(self) -> FakeModel:
            return self.params

        def get_param_infos(self) -> FakeModel:
            return self.param_infos

    class FakeRouteInfo:
        def get_index(self) -> int:
            return 1

        def get_device(self) -> int:
            return 8

        def get_profile(self) -> int:
            return 0

        def get_priority(self) -> int:
            return 200

        def dup_direction(self) -> str:
            return "output"

        def dup_name(self) -> str:
            return "analog-output-headphones"

        def dup_description(self) -> str:
            return "Headphones"

        def dup_availability(self) -> str:
            return "yes"

        def get_info(self) -> dict[str, str]:
            return {}

    created_from: list[str] = []

    def new_from_param(param: FakeParam) -> FakeRouteInfo:
        created_from.append(param.name)
        return FakeRouteInfo()

    backend = pw_backend.PipeWireBackend()
    backend._Pwg = SimpleNamespace(RouteInfo=SimpleNamespace(new_from_param=new_from_param))
    monkeypatch.setattr(backend, "_device_name_by_bound_id", lambda _bound_id: "alsa_card.test")

    device = FakeDevice()
    routes = backend._enumerate_device_routes(device, 72)

    assert device.enum_calls == [(13, 0, 0)]
    assert created_from == ["Route"]
    assert [route.name for route in routes] == ["analog-output-headphones"]
    assert backend._device_route_refreshing_bound_ids == set()


def test_enumerate_device_routes_uses_request_scoped_params(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeParam:
        def __init__(self, name: str, *, seq: int, route_name: str) -> None:
            self.name = name
            self.seq = seq
            self.route_name = route_name

        def get_seq(self) -> int:
            return self.seq

        def get_next(self) -> int:
            return 0

        def dup_name(self) -> str:
            return self.name

    class FakeParamInfo:
        def get_id(self) -> int:
            return 13

        def dup_name(self) -> str:
            return "Route"

    class FakeModel:
        def __init__(self, items: list[object]) -> None:
            self.items = items

        def get_n_items(self) -> int:
            return len(self.items)

        def get_item(self, index: int) -> object:
            return self.items[index]

    class FakeDevice:
        def __init__(self) -> None:
            self.params = FakeModel(
                [
                    FakeParam("Route", seq=12, route_name="analog-output-headphones"),
                ]
            )
            self.param_infos = FakeModel([FakeParamInfo()])

        def enum_params_sync(self, _param_id: int, _start: int, _num: int, _timeout_ms: int) -> FakeModel:
            return self.params

        def get_params(self) -> FakeModel:
            return self.params

        def get_param_infos(self) -> FakeModel:
            return self.param_infos

    class FakeRouteInfo:
        def __init__(self, param: FakeParam) -> None:
            self.param = param

        def get_index(self) -> int:
            return 1

        def get_device(self) -> int:
            return 6

        def get_profile(self) -> int:
            return 0

        def get_priority(self) -> int:
            return 200

        def dup_direction(self) -> str:
            return "output"

        def dup_name(self) -> str:
            return self.param.route_name

        def dup_description(self) -> str:
            return self.param.route_name

        def dup_availability(self) -> str:
            return "yes"

        def get_info(self) -> dict[str, str]:
            return {}

    backend = pw_backend.PipeWireBackend()
    backend._Pwg = SimpleNamespace(RouteInfo=SimpleNamespace(new_from_param=FakeRouteInfo))
    monkeypatch.setattr(backend, "_device_name_by_bound_id", lambda _bound_id: "alsa_card.test")

    routes = backend._enumerate_device_routes(FakeDevice(), 72)

    assert [route.name for route in routes] == ["analog-output-headphones"]


def test_connect_device_route_changed_subscribes_to_route_event_params(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeParam:
        def __init__(
            self,
            param_id: int,
            *,
            route_device: int = 6,
            direction: str = "output",
            route_name: str = "analog-output-headphones",
        ) -> None:
            self.param_id = param_id
            self.route_device = route_device
            self.direction = direction
            self.route_name = route_name

        def get_id(self) -> int:
            return self.param_id

    class FakeParamInfo:
        def __init__(self, param_id: int, name: str) -> None:
            self.param_id = param_id
            self.name = name

        def get_id(self) -> int:
            return self.param_id

        def dup_name(self) -> str:
            return self.name

    class FakeModel:
        def __init__(self, items: list[object]) -> None:
            self.items = items

        def get_n_items(self) -> int:
            return len(self.items)

        def get_item(self, index: int) -> object:
            return self.items[index]

    class FakeDevice:
        def __init__(self) -> None:
            self.param_infos = FakeModel([FakeParamInfo(13, "Route"), FakeParamInfo(14, "EnumRoute")])
            self.subscriptions: list[FakeVariant] = []
            self.disconnected: list[int] = []
            self.param_callback = None
            self.param_infos_callback = None

        def get_param_infos(self) -> FakeModel:
            return self.param_infos

        def subscribe_params(self, ids: FakeVariant) -> None:
            self.subscriptions.append(ids)

        def disconnect(self, handler_id: int) -> None:
            self.disconnected.append(handler_id)

        def emit_param(self, param_id: int, **kwargs) -> None:
            assert self.param_callback is not None
            self.param_callback(self, FakeParam(param_id, **kwargs))

        def emit_param_infos_changed(self) -> None:
            assert self.param_infos_callback is not None
            self.param_infos_callback(self, None)

    class FakeRouteInfo:
        def __init__(self, param: FakeParam) -> None:
            self.param = param

        def get_index(self) -> int:
            return 1

        def get_device(self) -> int:
            return self.param.route_device

        def get_profile(self) -> int:
            return 0

        def get_priority(self) -> int:
            return 200

        def dup_direction(self) -> str:
            return self.param.direction

        def dup_name(self) -> str:
            return self.param.route_name

        def dup_description(self) -> str:
            return self.param.route_name

        def dup_availability(self) -> str:
            return "yes"

        def get_info(self) -> dict[str, str]:
            return {}

    class FakeGObjectObject:
        @staticmethod
        def connect(device: FakeDevice, signal_name: str, callback) -> int:
            if signal_name == "param":
                device.param_callback = callback
                return 77
            if signal_name == "notify::param-infos":
                device.param_infos_callback = callback
                return 78
            raise AssertionError(f"unexpected signal: {signal_name}")

    backend = pw_backend.PipeWireBackend()
    device = FakeDevice()
    backend._Pwg = SimpleNamespace(Device=FakeDeviceApi, RouteInfo=SimpleNamespace(new_from_param=FakeRouteInfo))
    backend._GLib = FakeGLib
    backend._GObject = SimpleNamespace(Object=FakeGObjectObject)
    backend._ensure_connected = lambda: None
    monkeypatch.setattr(backend, "_device_proxy_by_bound_id", lambda _bound_id: device)
    monkeypatch.setattr(backend, "_device_name_by_bound_id", lambda _bound_id: "alsa_card.test")
    calls: list[str] = []

    handler_id = backend.connect_device_route_changed(72, lambda: calls.append("route"))

    assert handler_id == 77
    assert [(variant.signature, variant.value) for variant in device.subscriptions] == [("au", [13, 14])]

    device.emit_param(12)
    assert calls == []

    device.emit_param(13, direction="input")
    assert calls == []

    device.emit_param(13, route_name="analog-output-headphones")
    assert calls == ["route"]
    assert backend._device_active_output_routes[72][6].name == "analog-output-headphones"

    device.emit_param(14, route_device=7, route_name="analog-output-speaker")
    assert calls == ["route", "route"]
    assert backend._device_active_output_routes[72][6].name == "analog-output-headphones"

    device.emit_param(13, route_device=7, route_name="analog-output-speaker")
    assert calls == ["route", "route", "route"]
    assert tuple(backend._device_active_output_routes[72]) == (7,)
    assert backend._device_active_output_routes[72][7].name == "analog-output-speaker"

    device.emit_param_infos_changed()
    assert calls == ["route", "route", "route", "route"]
    assert tuple(backend._device_active_output_routes[72]) == (7,)
    assert backend._device_active_output_routes[72][7].name == "analog-output-speaker"

    device.emit_param(13, route_device=7, route_name="analog-output-speaker")
    assert calls == ["route", "route", "route", "route"]
    assert tuple(backend._device_active_output_routes[72]) == (7,)

    backend._device_route_refreshing_bound_ids.add(72)
    device.emit_param(13, route_device=6, route_name="analog-output-headphones")
    device.emit_param_infos_changed()
    assert calls == ["route", "route", "route", "route"]
    assert tuple(backend._device_active_output_routes[72]) == (7,)
    assert backend._device_active_output_routes[72][7].name == "analog-output-speaker"

    backend.disconnect_device_handler(handler_id)
    assert [(variant.signature, variant.value) for variant in device.subscriptions] == [("au", [13, 14]), ("au", [])]
    assert device.disconnected == [78, 77]


def test_output_preset_keys_use_subscribed_active_route_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    backend = pw_backend.PipeWireBackend()
    route = pw_routes.PipeWireOutputRoute(
        device_bound_id=72,
        device_name="alsa_card.test",
        index=1,
        route_device=7,
        profile=0,
        priority=200,
        direction="output",
        name="analog-output-speaker",
        description="Speakers",
        availability="yes",
    )
    sink = pw_backend.PipeWireNode(
        bound_id=39,
        object_serial="67",
        media_class=pw_backend.AUDIO_SINK,
        node_name="alsa_output.test",
        node_description="Test Sink",
        application_name=None,
        node_dont_move=False,
        device_id=72,
        card_profile_device=6,
    )
    backend._device_active_output_routes = {72: {7: route}}
    backend._Pwg = SimpleNamespace()
    monkeypatch.setattr(backend, "audio_sink_by_name", lambda _name: sink)

    assert backend.output_preset_keys_for_sink_name("alsa_output.test") == (
        "pipewire-route:v1:device=alsa_card.test;route=analog-output-speaker;route-device=7",
        "alsa_output.test",
    )


def test_move_named_output_stream_to_target_uses_matching_stream() -> None:
    backend = pw_backend.PipeWireBackend()
    stream = pw_backend.PipeWireNode(
        bound_id=126,
        object_serial="300",
        media_class=pw_backend.STREAM_OUTPUT_AUDIO,
        node_name="mini_eq_sink_output",
        node_description=None,
        application_name=None,
        node_dont_move=False,
    )
    calls: list[tuple[int, str]] = []

    backend.output_stream_by_name = lambda _name: stream
    backend.move_stream_to_target = lambda *args: calls.append(args)

    backend.move_named_output_stream_to_target("mini_eq_sink_output", "alsa_output.test")

    assert calls == [(126, "alsa_output.test")]


def test_move_named_output_stream_to_target_requires_existing_stream() -> None:
    backend = pw_backend.PipeWireBackend()
    backend.output_stream_by_name = lambda _name: None

    with pytest.raises(pw_backend.PipeWireBackendError, match="output stream not found: mini_eq_sink_output"):
        backend.move_named_output_stream_to_target("mini_eq_sink_output", "alsa_output.test")


def test_set_stream_target_writes_node_and_object_metadata() -> None:
    backend = pw_backend.PipeWireBackend()

    class FakeMetadata:
        def __init__(self) -> None:
            self.calls: list[tuple[int, str, str, str]] = []

        def set(self, subject: int, key: str, type_name: str, value: str) -> bool:
            self.calls.append((subject, key, type_name, value))
            return True

    metadata = FakeMetadata()
    syncs: list[str] = []
    backend._default_metadata = lambda: metadata
    backend._sync_metadata = lambda: syncs.append("sync")

    backend.set_stream_target(126, 39, "67")

    assert metadata.calls == [
        (126, pw_backend.TARGET_NODE_KEY, pw_backend.SPA_ID_TYPE, "39"),
        (126, pw_backend.TARGET_OBJECT_KEY, pw_backend.SPA_ID_TYPE, "67"),
    ]
    assert syncs == ["sync"]


def test_stream_target_reads_node_and_object_metadata() -> None:
    backend = pw_backend.PipeWireBackend()

    class FakeMetadata:
        def dup_value(self, subject: int, key: str) -> str | None:
            values = {
                (126, pw_backend.TARGET_NODE_KEY): "39",
                (126, pw_backend.TARGET_OBJECT_KEY): "67",
            }
            return values.get((subject, key))

        def dup_value_type(self, subject: int, key: str) -> str | None:
            values = {
                (126, pw_backend.TARGET_NODE_KEY): pw_backend.SPA_ID_TYPE,
                (126, pw_backend.TARGET_OBJECT_KEY): pw_backend.SPA_ID_TYPE,
            }
            return values.get((subject, key))

    backend._default_metadata = lambda: FakeMetadata()

    target = backend.stream_target(126)

    assert target == pw_backend.PipeWireStreamTarget("39", pw_backend.SPA_ID_TYPE, "67", pw_backend.SPA_ID_TYPE)


def test_restore_stream_target_writes_saved_metadata() -> None:
    backend = pw_backend.PipeWireBackend()

    class FakeMetadata:
        def __init__(self) -> None:
            self.calls: list[tuple[int, str, str | None, str | None]] = []

        def set(self, subject: int, key: str, type_name: str | None, value: str | None) -> bool:
            self.calls.append((subject, key, type_name, value))
            return True

    metadata = FakeMetadata()
    syncs: list[str] = []
    backend._default_metadata = lambda: metadata
    backend._sync_metadata = lambda: syncs.append("sync")

    backend.restore_stream_target(
        126,
        pw_backend.PipeWireStreamTarget(
            target_node=None,
            target_node_type=None,
            target_object=None,
            target_object_type=None,
        ),
    )

    assert metadata.calls == [
        (126, pw_backend.TARGET_NODE_KEY, None, None),
        (126, pw_backend.TARGET_OBJECT_KEY, None, None),
    ]
    assert syncs == ["sync"]


def test_properties_dict_skips_undecodable_property_values() -> None:
    backend = pw_backend.PipeWireBackend()
    proxy = FakePropertyProxy(
        FakeGlobalProperties(
            [
                FakePropertyItem("node.description", "", undecodable=True),
                FakePropertyItem("node.name", "spotify"),
            ]
        )
    )

    assert backend._properties_dict(proxy) == {"node.name": "spotify"}


def test_pw_property_falls_back_when_pipewire_property_is_undecodable() -> None:
    backend = pw_backend.PipeWireBackend()

    class FakeGlobal(FakePropertyProxy):
        def dup_property(self, _key: str):
            raise UnicodeDecodeError("utf-8", b"\x96", 0, 1, "invalid start byte")

    proxy = FakeGlobal(FakeGlobalProperties([FakePropertyItem("node.name", "spotify")]))

    assert backend._pw_property(proxy, "node.name") == "spotify"


def test_list_nodes_skips_proxy_with_undecodable_identity() -> None:
    backend = pw_backend.PipeWireBackend()
    good_node = object()
    bad_node = object()
    parsed_node = pw_backend.PipeWireNode(
        bound_id=1,
        object_serial="1001",
        media_class=pw_backend.STREAM_OUTPUT_AUDIO,
        node_name="spotify",
        node_description=None,
        application_name="Spotify",
        node_dont_move=False,
    )

    class FakeModel:
        def __init__(self, items: list[object]) -> None:
            self.items = items

        def get_n_items(self) -> int:
            return len(self.items)

        def get_item(self, index: int):
            return self.items[index]

    class FakeRegistry:
        def dup_globals_by_interface(self, interface_type: str) -> FakeModel:
            assert interface_type == pw_backend.PIPEWIRE_NODE_INTERFACE
            return FakeModel([bad_node, good_node])

    def node_from_global(node):
        if node is bad_node:
            raise UnicodeDecodeError("utf-8", b"\xea", 3, 4, "invalid continuation byte")
        return parsed_node

    backend._ensure_connected = lambda: None
    backend._registry = FakeRegistry()
    backend._node_from_global = node_from_global

    assert backend.list_nodes() == [parsed_node]


def test_defaults_returns_cached_value_without_metadata_read(monkeypatch) -> None:
    backend = pw_backend.PipeWireBackend()
    backend._cached_defaults = pw_backend.PipeWireDefaults("cached.default", "cached.configured")
    reads: list[bool] = []

    monkeypatch.setattr(backend, "_read_defaults", lambda: reads.append(True))

    assert backend.defaults().default_audio_sink == "cached.default"
    assert reads == []


def test_refresh_defaults_falls_back_to_cache_on_undecodable_metadata(monkeypatch) -> None:
    backend = pw_backend.PipeWireBackend()
    backend._cached_defaults = pw_backend.PipeWireDefaults("cached.default", None)
    syncs: list[bool] = []

    def raise_decode_error():
        raise UnicodeDecodeError("utf-8", b"\xb1", 0, 1, "invalid start byte")

    monkeypatch.setattr(backend, "_read_defaults", raise_decode_error)
    monkeypatch.setattr(backend, "_sync_metadata", lambda: syncs.append(True))

    assert backend.refresh_defaults().default_audio_sink == "cached.default"
    assert syncs == [True]


def test_refresh_defaults_can_resnapshot_metadata_before_read(monkeypatch) -> None:
    backend = pw_backend.PipeWireBackend()
    calls: list[str] = []

    class FakeMetadata:
        def stop(self) -> None:
            calls.append("stop")

        def start(self) -> bool:
            calls.append("start")
            return True

    backend._metadata = FakeMetadata()
    backend._cached_defaults = pw_backend.PipeWireDefaults("stale.default", "stale.configured")
    monkeypatch.setattr(backend, "_sync_metadata", lambda: calls.append("sync"))
    monkeypatch.setattr(
        backend,
        "_read_defaults",
        lambda: calls.append("read") or pw_backend.PipeWireDefaults("fresh.default", "fresh.configured"),
    )

    assert backend.refresh_defaults(snapshot=True) == pw_backend.PipeWireDefaults(
        "fresh.default",
        "fresh.configured",
    )
    assert calls == ["stop", "start", "sync", "read"]


def test_remember_default_metadata_change_updates_cache() -> None:
    backend = pw_backend.PipeWireBackend()

    assert backend.remember_default_metadata_change(
        pw_backend.DEFAULT_AUDIO_SINK_KEY,
        '{"name":"alsa_output.new"}',
    )
    assert backend.defaults().default_audio_sink == "alsa_output.new"


def test_build_props_controls_param_uses_variant_control_map() -> None:
    FakePwgParam.calls = []

    param = pw_backend.build_props_controls_param(FakePwg, FakeGLib, {"eq:enabled": 0.0, "eq:g_out": 1.0})

    variant = FakePwgParam.calls[0]
    assert param == ("param", variant)
    assert variant.signature == "a{sd}"
    assert variant.value == {"eq:enabled": 0.0, "eq:g_out": 1.0}


def test_set_node_params_uses_pwg_node_set_param(monkeypatch: pytest.MonkeyPatch) -> None:
    FakePwgParam.calls = []

    class FakeLiveNode:
        def __init__(self) -> None:
            self.set_calls: list[object] = []

        def set_param(self, param) -> bool:
            self.set_calls.append(param)
            return True

    node = FakeLiveNode()
    backend = pw_backend.PipeWireBackend()
    backend._Pwg = FakePwg
    backend._GLib = FakeGLib

    monkeypatch.setattr(backend, "_ensure_connected", lambda: None)
    monkeypatch.setattr(backend, "_node_proxy_by_bound_id", lambda _bound_id: node)

    backend.set_node_params(42, {"eq:enabled": 1.0})

    assert node.set_calls == [("param", FakePwgParam.calls[-1])]


def test_set_node_params_raises_when_node_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    backend = pw_backend.PipeWireBackend()
    backend._Pwg = FakePwg
    backend._GLib = FakeGLib

    monkeypatch.setattr(backend, "_ensure_connected", lambda: None)
    monkeypatch.setattr(backend, "_node_proxy_by_bound_id", lambda _bound_id: None)

    with pytest.raises(pw_backend.PipeWireBackendError, match="node not found"):
        backend.set_node_params(42, {"eq:enabled": 1.0})


def test_load_filter_chain_module_uses_pwg_core_load_module(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeLoadCore:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str]] = []
            self.result = object()

        def load_module(self, name: str, arguments: str):
            self.calls.append((name, arguments))
            return self.result

    core = FakeLoadCore()
    backend = pw_backend.PipeWireBackend()
    backend._core = core

    monkeypatch.setattr(backend, "_ensure_connected", lambda: None)

    module = backend.load_filter_chain_module("{ node.name = test }")

    assert module is core.result
    assert core.calls == [(pw_backend.FILTER_CHAIN_MODULE_NAME, "{ node.name = test }")]
    assert backend._loaded_modules == [module]


def test_unload_filter_chain_module_unloads_and_forgets_loaded_module() -> None:
    calls: list[str] = []

    class FakeModule:
        def unload(self) -> None:
            calls.append("unload")

    module = FakeModule()
    backend = pw_backend.PipeWireBackend()
    backend._loaded_modules = [module]

    backend.unload_filter_chain_module(module)

    assert calls == ["unload"]
    assert backend._loaded_modules == []


def test_load_filter_chain_module_raises_on_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeLoadCore:
        def load_module(self, _name: str, _arguments: str):
            return None

    backend = pw_backend.PipeWireBackend()
    backend._core = FakeLoadCore()

    monkeypatch.setattr(backend, "_ensure_connected", lambda: None)

    with pytest.raises(pw_backend.PipeWireBackendError, match="failed to load PipeWire module"):
        backend.load_filter_chain_module("{}")
