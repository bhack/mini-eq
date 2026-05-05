from __future__ import annotations

import pytest

from tests._mini_eq_imports import wireplumber_backend as wp_backend


class FakeSpaPodBuilder:
    builders: list[FakeSpaPodBuilder] = []

    def __init__(self, kind: str, args: tuple[str, ...] = ()) -> None:
        self.kind = kind
        self.args = args
        self.calls: list[tuple[str, object]] = []
        FakeSpaPodBuilder.builders.append(self)

    @classmethod
    def new_struct(cls) -> FakeSpaPodBuilder:
        return cls("struct")

    @classmethod
    def new_object(cls, type_name: str, id_name: str) -> FakeSpaPodBuilder:
        return cls("object", (type_name, id_name))

    def add_string(self, value: str) -> None:
        self.calls.append(("string", value))

    def add_float(self, value: float) -> None:
        self.calls.append(("float", value))

    def add_property(self, value: str) -> None:
        self.calls.append(("property", value))

    def add_pod(self, pod) -> None:
        self.calls.append(("pod", pod))

    def end(self):
        return self


class FakeImplModule:
    load_calls: list[tuple[object, str, str, object | None]] = []
    result: object | None = object()

    @classmethod
    def load(cls, core, name: str, arguments: str, properties):
        cls.load_calls.append((core, name, arguments, properties))
        return cls.result


class FakeWp:
    SpaPodBuilder = FakeSpaPodBuilder
    ImplModule = FakeImplModule


class FakeProperties:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    @classmethod
    def new_empty(cls) -> FakeProperties:
        return cls()

    def set(self, key: str, value: str) -> None:
        self.values[key] = value


class FakeCore:
    calls: list[tuple[object | None, object | None, FakeProperties | None]] = []

    @classmethod
    def new(cls, context, conf, properties=None):
        cls.calls.append((context, conf, properties))
        return object()


class FakeCoreWp:
    Core = FakeCore
    Properties = FakeProperties


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

    def get_global_properties(self) -> FakeGlobalProperties:
        return self.properties


class FakeSource:
    def __init__(self) -> None:
        self.destroyed = False

    def destroy(self) -> None:
        self.destroyed = True


class FakeSyncCore:
    def __init__(self) -> None:
        self.callback = None

    def sync(self, _cancellable, callback, _user_data) -> bool:
        self.callback = callback
        return True

    def sync_finish(self, _result) -> bool:
        return True

    def complete_sync(self) -> None:
        assert self.callback is not None
        self.callback(self, object(), None)


class FakeMainContext:
    def __init__(self, source: FakeSource) -> None:
        self.source = source

    def default(self) -> FakeMainContext:
        return self

    def find_source_by_id(self, source_id: int) -> FakeSource | None:
        return self.source if source_id == 77 else None


class FakeSyncLoop:
    def __init__(self, core: FakeSyncCore) -> None:
        self.core = core
        self.quit_count = 0

    def run(self) -> None:
        self.core.complete_sync()

    def quit(self) -> None:
        self.quit_count += 1


class FakeSyncGLib:
    def __init__(self, core: FakeSyncCore) -> None:
        self.core = core
        self.source = FakeSource()
        self.MainContext = FakeMainContext(self.source)
        self.timeout_callback = None

    def MainLoop(self) -> FakeSyncLoop:
        return FakeSyncLoop(self.core)

    def timeout_add(self, _timeout_ms: int, callback) -> int:
        self.timeout_callback = callback
        return 77


def test_parse_metadata_node_name_reads_wireplumber_json_name() -> None:
    assert wp_backend.parse_metadata_node_name('{"name":"alsa_output.test"}') == "alsa_output.test"


def test_parse_metadata_node_name_accepts_plain_string() -> None:
    assert wp_backend.parse_metadata_node_name("mini_eq_sink") == "mini_eq_sink"


def test_parse_metadata_node_name_rejects_invalid_shape() -> None:
    assert wp_backend.parse_metadata_node_name("[1, 2, 3]") is None


def test_parse_bool_property_accepts_wireplumber_truthy_values() -> None:
    assert wp_backend.parse_bool_property("true") is True
    assert wp_backend.parse_bool_property("1") is True
    assert wp_backend.parse_bool_property("false") is False
    assert wp_backend.parse_bool_property(None) is False


def test_node_sample_rate_uses_audio_rate_and_latency_fallbacks() -> None:
    direct_rate = wp_backend.WirePlumberNode(
        bound_id=39,
        object_serial="67",
        media_class=wp_backend.AUDIO_SINK,
        node_name="alsa_output.direct",
        node_description=None,
        application_name=None,
        node_dont_move=False,
        properties={"audio.rate": "48000", "node.max-latency": "1024/44100"},
    )
    max_latency_rate = wp_backend.WirePlumberNode(
        bound_id=40,
        object_serial="68",
        media_class=wp_backend.AUDIO_SINK,
        node_name="alsa_output.max_latency",
        node_description=None,
        application_name=None,
        node_dont_move=False,
        properties={"node.max-latency": "1024/44100"},
    )
    latency_rate = wp_backend.WirePlumberNode(
        bound_id=41,
        object_serial="69",
        media_class=wp_backend.AUDIO_SINK,
        node_name="alsa_output.latency",
        node_description=None,
        application_name=None,
        node_dont_move=False,
        properties={"node.latency": "1024/96000"},
    )

    assert wp_backend.node_sample_rate(direct_rate) == 48000.0
    assert wp_backend.node_sample_rate(max_latency_rate) == 44100.0
    assert wp_backend.node_sample_rate(latency_rate) == 96000.0
    assert wp_backend.node_sample_rate(None) == 0.0


def test_node_classification_and_display_name() -> None:
    sink = wp_backend.WirePlumberNode(
        bound_id=39,
        object_serial="67",
        media_class=wp_backend.AUDIO_SINK,
        node_name="alsa_output.test",
        node_description="Test Sink",
        application_name=None,
        node_dont_move=False,
    )
    stream = wp_backend.WirePlumberNode(
        bound_id=126,
        object_serial="300",
        media_class=wp_backend.STREAM_OUTPUT_AUDIO,
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


def test_new_core_requests_pipewire_manager_access() -> None:
    FakeCore.calls = []

    wp_backend.WirePlumberBackend._new_core(FakeCoreWp)

    assert len(FakeCore.calls) == 1
    _context, _conf, properties = FakeCore.calls[0]
    assert properties is not None
    assert properties.values == {
        "application.name": wp_backend.PIPEWIRE_CLIENT_NAME,
        "media.category": wp_backend.PIPEWIRE_MEDIA_CATEGORY,
    }


def test_sync_core_removes_timeout_source_after_success() -> None:
    core = FakeSyncCore()
    glib = FakeSyncGLib(core)
    backend = wp_backend.WirePlumberBackend()
    backend._core = core
    backend._GLib = glib

    backend._sync_core()

    assert glib.source.destroyed is True
    assert glib.timeout_callback is not None


def test_move_stream_to_target_sets_stream_target_without_metadata_readback() -> None:
    backend = wp_backend.WirePlumberBackend()
    stream = wp_backend.WirePlumberNode(
        bound_id=126,
        object_serial="300",
        media_class=wp_backend.STREAM_OUTPUT_AUDIO,
        node_name="spotify",
        node_description=None,
        application_name="spotify",
        node_dont_move=False,
    )
    sink = wp_backend.WirePlumberNode(
        bound_id=39,
        object_serial="67",
        media_class=wp_backend.AUDIO_SINK,
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


def test_move_stream_to_target_skips_metadata_read_after_acknowledged_change() -> None:
    backend = wp_backend.WirePlumberBackend()
    stream = wp_backend.WirePlumberNode(
        bound_id=126,
        object_serial="300",
        media_class=wp_backend.STREAM_OUTPUT_AUDIO,
        node_name="spotify",
        node_description=None,
        application_name="spotify",
        node_dont_move=False,
    )
    sink = wp_backend.WirePlumberNode(
        bound_id=39,
        object_serial="67",
        media_class=wp_backend.AUDIO_SINK,
        node_name="alsa_output.test",
        node_description="Test Sink",
        application_name=None,
        node_dont_move=False,
    )

    backend.output_stream_by_bound_id = lambda _bound_id: stream
    backend.audio_sink_by_name = lambda _name: sink
    backend.set_stream_target = lambda *_args: None

    backend.move_stream_to_target(126, "alsa_output.test")


def test_move_stream_to_target_accepts_already_updated_metadata() -> None:
    backend = wp_backend.WirePlumberBackend()
    stream = wp_backend.WirePlumberNode(
        bound_id=126,
        object_serial="300",
        media_class=wp_backend.STREAM_OUTPUT_AUDIO,
        node_name="spotify",
        node_description=None,
        application_name="spotify",
        node_dont_move=False,
    )
    sink = wp_backend.WirePlumberNode(
        bound_id=39,
        object_serial="67",
        media_class=wp_backend.AUDIO_SINK,
        node_name="alsa_output.test",
        node_description="Test Sink",
        application_name=None,
        node_dont_move=False,
    )

    backend.output_stream_by_bound_id = lambda _bound_id: stream
    backend.audio_sink_by_name = lambda _name: sink
    backend.set_stream_target = lambda *_args: None

    backend.move_stream_to_target(126, "alsa_output.test")


def test_set_stream_target_writes_node_and_object_metadata() -> None:
    backend = wp_backend.WirePlumberBackend()

    class FakeMetadata:
        def __init__(self) -> None:
            self.calls: list[tuple[int, str, str, str]] = []

        def set(self, subject: int, key: str, type_name: str, value: str) -> None:
            self.calls.append((subject, key, type_name, value))

    metadata = FakeMetadata()
    syncs: list[str] = []
    backend._default_metadata = lambda: metadata
    backend._sync_core = lambda: syncs.append("sync")

    backend.set_stream_target(126, 39, "67")

    assert metadata.calls == [
        (126, wp_backend.TARGET_NODE_KEY, wp_backend.SPA_ID_TYPE, "39"),
        (126, wp_backend.TARGET_OBJECT_KEY, wp_backend.SPA_ID_TYPE, "67"),
    ]
    assert syncs == ["sync"]


def test_properties_dict_skips_undecodable_property_values() -> None:
    backend = wp_backend.WirePlumberBackend()
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
    backend = wp_backend.WirePlumberBackend()

    class FakePipewireObject:
        @staticmethod
        def get_property(_proxy, _key: str):
            raise UnicodeDecodeError("utf-8", b"\x96", 0, 1, "invalid start byte")

    class FakeWirePlumber:
        PipewireObject = FakePipewireObject

    backend._Wp = FakeWirePlumber
    proxy = FakePropertyProxy(FakeGlobalProperties([], {"node.name": "spotify"}))

    assert backend._pw_property(proxy, "node.name") == "spotify"


def test_list_nodes_skips_proxy_with_undecodable_identity() -> None:
    backend = wp_backend.WirePlumberBackend()
    good_node = object()
    bad_node = object()
    parsed_node = wp_backend.WirePlumberNode(
        bound_id=1,
        object_serial="1001",
        media_class=wp_backend.STREAM_OUTPUT_AUDIO,
        node_name="spotify",
        node_description=None,
        application_name="Spotify",
        node_dont_move=False,
    )

    def node_from_proxy(node):
        if node is bad_node:
            raise UnicodeDecodeError("utf-8", b"\xea", 3, 4, "invalid continuation byte")
        return parsed_node

    backend._ensure_connected = lambda: None
    backend._node_manager = object()
    backend._iterate_manager = lambda _manager: [bad_node, good_node]
    backend._node_from_proxy = node_from_proxy

    assert backend.list_nodes() == [parsed_node]


def test_defaults_returns_cached_value_without_metadata_read(monkeypatch) -> None:
    backend = wp_backend.WirePlumberBackend()
    backend._cached_defaults = wp_backend.WirePlumberDefaults("cached.default", "cached.configured")
    reads: list[bool] = []

    monkeypatch.setattr(backend, "_read_defaults", lambda: reads.append(True))

    assert backend.defaults().default_audio_sink == "cached.default"
    assert reads == []


def test_refresh_defaults_falls_back_to_cache_on_undecodable_metadata(monkeypatch) -> None:
    backend = wp_backend.WirePlumberBackend()
    backend._cached_defaults = wp_backend.WirePlumberDefaults("cached.default", None)
    syncs: list[bool] = []

    def raise_decode_error():
        raise UnicodeDecodeError("utf-8", b"\xb1", 0, 1, "invalid start byte")

    monkeypatch.setattr(backend, "_read_defaults", raise_decode_error)
    monkeypatch.setattr(backend, "_sync_core", lambda: syncs.append(True))

    assert backend.refresh_defaults().default_audio_sink == "cached.default"
    assert syncs == [True]


def test_remember_default_metadata_change_updates_cache() -> None:
    backend = wp_backend.WirePlumberBackend()

    assert backend.remember_default_metadata_change(
        wp_backend.DEFAULT_AUDIO_SINK_KEY,
        '{"name":"alsa_output.new"}',
    )
    assert backend.defaults().default_audio_sink == "alsa_output.new"


def test_build_spa_params_pod_uses_filter_chain_props_shape() -> None:
    FakeSpaPodBuilder.builders = []

    pod = wp_backend.build_spa_params_pod(FakeWp, {"eq:enabled": 0.0, "eq:g_out": 1.0})

    struct_builder, object_builder = FakeSpaPodBuilder.builders
    assert pod is object_builder
    assert struct_builder.kind == "struct"
    assert struct_builder.calls == [
        ("string", "eq:enabled"),
        ("float", 0.0),
        ("string", "eq:g_out"),
        ("float", 1.0),
    ]
    assert object_builder.kind == "object"
    assert object_builder.args == ("Spa:Pod:Object:Param:Props", "Props")
    assert object_builder.calls == [("property", "params"), ("pod", struct_builder)]


def test_set_node_params_uses_wireplumber_set_param(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeSpaPodBuilder.builders = []
    node = FakeNodeProxy(42)
    backend = wp_backend.WirePlumberBackend()
    backend._Wp = FakeWp
    backend._node_manager = object()

    monkeypatch.setattr(backend, "_ensure_connected", lambda: None)
    monkeypatch.setattr(backend, "_iterate_manager", lambda _manager: [node])

    backend.set_node_params(42, {"eq:enabled": 1.0})

    assert node.set_calls == [("Props", 0, FakeSpaPodBuilder.builders[-1])]


def test_set_node_params_raises_when_node_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    backend = wp_backend.WirePlumberBackend()
    backend._Wp = FakeWp
    backend._node_manager = object()

    monkeypatch.setattr(backend, "_ensure_connected", lambda: None)
    monkeypatch.setattr(backend, "_iterate_manager", lambda _manager: [])

    with pytest.raises(wp_backend.WirePlumberError, match="node not found"):
        backend.set_node_params(42, {"eq:enabled": 1.0})


def test_load_filter_chain_module_uses_wireplumber_impl_module(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeImplModule.load_calls = []
    FakeImplModule.result = object()
    backend = wp_backend.WirePlumberBackend()
    backend._Wp = FakeWp
    backend._core = object()

    monkeypatch.setattr(backend, "_ensure_connected", lambda: None)

    module = backend.load_filter_chain_module("{ node.name = test }")

    assert module is FakeImplModule.result
    assert FakeImplModule.load_calls == [
        (
            backend._core,
            wp_backend.FILTER_CHAIN_MODULE_NAME,
            "{ node.name = test }",
            None,
        )
    ]


def test_load_filter_chain_module_raises_on_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeImplModule.load_calls = []
    FakeImplModule.result = None
    backend = wp_backend.WirePlumberBackend()
    backend._Wp = FakeWp
    backend._core = object()

    monkeypatch.setattr(backend, "_ensure_connected", lambda: None)

    with pytest.raises(wp_backend.WirePlumberError, match="failed to load PipeWire module"):
        backend.load_filter_chain_module("{}")
