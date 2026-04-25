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


def test_node_classification_and_display_name() -> None:
    sink = wp_backend.WirePlumberNode(
        local_id=1,
        bound_id=39,
        object_serial="67",
        media_class=wp_backend.AUDIO_SINK,
        node_name="alsa_output.test",
        node_description="Test Sink",
        application_name=None,
        node_dont_move=False,
    )
    stream = wp_backend.WirePlumberNode(
        local_id=2,
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


def test_sync_core_removes_timeout_source_after_success() -> None:
    core = FakeSyncCore()
    glib = FakeSyncGLib(core)
    backend = wp_backend.WirePlumberBackend()
    backend._core = core
    backend._GLib = glib

    backend._sync_core()

    assert glib.source.destroyed is True
    assert glib.timeout_callback is not None


def test_stream_targets_node_matches_target_object_metadata() -> None:
    backend = wp_backend.WirePlumberBackend()
    sink = wp_backend.WirePlumberNode(
        local_id=1,
        bound_id=39,
        object_serial="67",
        media_class=wp_backend.AUDIO_SINK,
        node_name="alsa_output.test",
        node_description="Test Sink",
        application_name=None,
        node_dont_move=False,
    )

    backend.audio_sink_by_name = lambda _name: sink
    backend.stream_target_object = lambda _bound_id: ("67", wp_backend.SPA_ID_TYPE)

    assert backend.stream_targets_node(126, "alsa_output.test") is True


def test_stream_targets_node_rejects_different_target_object_metadata() -> None:
    backend = wp_backend.WirePlumberBackend()
    sink = wp_backend.WirePlumberNode(
        local_id=1,
        bound_id=39,
        object_serial="67",
        media_class=wp_backend.AUDIO_SINK,
        node_name="alsa_output.test",
        node_description="Test Sink",
        application_name=None,
        node_dont_move=False,
    )

    backend.audio_sink_by_name = lambda _name: sink
    backend.stream_target_object = lambda _bound_id: ("68", wp_backend.SPA_ID_TYPE)

    assert backend.stream_targets_node(126, "alsa_output.test") is False


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
