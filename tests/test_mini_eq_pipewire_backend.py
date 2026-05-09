from __future__ import annotations

import pytest

from tests._mini_eq_imports import pipewire_backend as pw_backend


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


def test_new_core_uses_pipewire_gobject_core_constructor() -> None:
    FakeCore.calls = 0

    core = pw_backend.PipeWireBackend._new_core(FakeCorePwg)

    assert FakeCore.calls == 1
    assert core.pipewire_properties == {
        "application.name": "Mini EQ",
        "media.category": "Manager",
    }


def test_sync_core_drains_pending_main_context_events() -> None:
    core = FakeSyncCore()
    glib = FakeSyncGLib(core)
    backend = pw_backend.PipeWireBackend()
    backend._core = core
    backend._GLib = glib

    backend._sync_core()

    assert glib.MainContext.iterations == 1


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
    backend._sync_core = lambda: syncs.append("sync")

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
    backend._sync_core = lambda: syncs.append("sync")

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
    monkeypatch.setattr(backend, "_sync_core", lambda: syncs.append(True))

    assert backend.refresh_defaults().default_audio_sink == "cached.default"
    assert syncs == [True]


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
