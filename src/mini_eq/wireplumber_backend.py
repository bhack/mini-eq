from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

DEFAULT_METADATA_NAME = "default"
DEFAULT_AUDIO_SINK_KEY = "default.audio.sink"
DEFAULT_CONFIGURED_AUDIO_SINK_KEY = "default.configured.audio.sink"
TARGET_OBJECT_KEY = "target.object"
SPA_ID_TYPE = "Spa:Id"
STREAM_OUTPUT_AUDIO = "Stream/Output/Audio"
AUDIO_SINK = "Audio/Sink"
FILTER_CHAIN_MODULE_NAME = "libpipewire-module-filter-chain"


@dataclass(frozen=True)
class WirePlumberNode:
    bound_id: int
    object_serial: str | None
    media_class: str | None
    node_name: str | None
    node_description: str | None
    application_name: str | None
    node_dont_move: bool
    properties: dict[str, str] = field(default_factory=dict)

    @property
    def is_audio_sink(self) -> bool:
        return self.media_class == AUDIO_SINK

    @property
    def is_output_stream(self) -> bool:
        return self.media_class == STREAM_OUTPUT_AUDIO

    @property
    def display_name(self) -> str:
        return self.node_description or self.application_name or self.node_name or f"node {self.bound_id}"

    def property_value(self, key: str, default: str = "") -> str:
        return self.properties.get(key, default)


@dataclass(frozen=True)
class WirePlumberDefaults:
    default_audio_sink: str | None
    configured_audio_sink: str | None


class WirePlumberError(RuntimeError):
    pass


def build_spa_params_pod(Wp, controls: dict[str, float]):
    inner = Wp.SpaPodBuilder.new_struct()
    for name, value in controls.items():
        inner.add_string(name)
        inner.add_float(float(value))

    inner_pod = inner.end()
    outer = Wp.SpaPodBuilder.new_object("Spa:Pod:Object:Param:Props", "Props")
    outer.add_property("params")
    outer.add_pod(inner_pod)
    return outer.end()


def parse_metadata_node_name(value: str | None) -> str | None:
    if not value:
        return None

    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        return value

    if not isinstance(payload, dict):
        return None

    name = payload.get("name")
    return str(name) if name else None


def parse_bool_property(value: str | None) -> bool:
    return str(value).lower() in {"1", "true", "yes", "on"}


def parse_positive_int(value: str | None) -> int:
    try:
        parsed = int(value or "")
    except (TypeError, ValueError):
        return 0

    return parsed if parsed > 0 else 0


def parse_rate_from_latency(value: str | None) -> int:
    if not value or "/" not in value:
        return 0

    _frames, rate = value.rsplit("/", 1)
    return parse_positive_int(rate)


def node_sample_rate(node: WirePlumberNode | None) -> float:
    if node is None:
        return 0.0

    rate = parse_positive_int(node.property_value("audio.rate"))
    if rate <= 0:
        rate = parse_rate_from_latency(node.property_value("node.max-latency"))
    if rate <= 0:
        rate = parse_rate_from_latency(node.property_value("node.latency"))

    return float(rate) if rate > 0 else 0.0


class WirePlumberBackend:
    def __init__(self, timeout_ms: int = 2000) -> None:
        self.timeout_ms = timeout_ms
        self._connected = False
        self._GLib: Any = None
        self._GObject: Any = None
        self._Wp: Any = None
        self._core: Any = None
        self._node_manager: Any = None
        self._metadata_manager: Any = None
        self._metadata_signal_objects: dict[int, Any] = {}
        self._cached_defaults = WirePlumberDefaults(None, None)

    def __enter__(self) -> WirePlumberBackend:
        self.connect()
        return self

    def __exit__(self, _exc_type, _exc, _tb) -> None:
        self.close()

    def connect(self) -> None:
        if self._connected:
            return

        GLib, GObject, Wp = self._import_wireplumber()
        self._GLib = GLib
        self._GObject = GObject
        self._Wp = Wp

        init_flags = Wp.InitFlags.PIPEWIRE | Wp.InitFlags.SPA_TYPES
        Wp.init(init_flags)

        self._core = self._new_core(Wp)
        self._node_manager = self._build_node_manager(Wp)
        self._metadata_manager = self._build_metadata_manager(Wp)

        pending = {"core", "nodes", "metadata"}
        errors: list[BaseException] = []
        loop = GLib.MainLoop()
        init_signal_handlers: list[tuple[Any, int]] = []
        timeout_id = 0

        def mark_ready(name: str) -> None:
            pending.discard(name)
            if not pending:
                loop.quit()

        def on_connected(_core) -> None:
            mark_ready("core")

        def on_installed(_manager, name: str) -> None:
            mark_ready(name)

        def on_timeout() -> bool:
            loop.quit()
            return False

        def safe_callback(callback):
            def wrapper(*args):
                try:
                    callback(*args)
                except BaseException as exc:
                    errors.append(exc)
                    loop.quit()

            return wrapper

        init_signal_handlers.append(
            (self._core, GObject.Object.connect(self._core, "connected", safe_callback(on_connected)))
        )
        init_signal_handlers.append(
            (
                self._node_manager,
                GObject.Object.connect(
                    self._node_manager, "installed", safe_callback(lambda manager: on_installed(manager, "nodes"))
                ),
            )
        )
        init_signal_handlers.append(
            (
                self._metadata_manager,
                GObject.Object.connect(
                    self._metadata_manager,
                    "installed",
                    safe_callback(lambda manager: on_installed(manager, "metadata")),
                ),
            )
        )

        try:
            self._core.install_object_manager(self._node_manager)
            self._core.install_object_manager(self._metadata_manager)

            if not self._core.connect():
                raise WirePlumberError("failed to connect to PipeWire through WirePlumber")

            timeout_id = GLib.timeout_add(self.timeout_ms, on_timeout)
            loop.run()
        finally:
            if timeout_id > 0:
                source = GLib.MainContext.default().find_source_by_id(timeout_id)
                if source is not None:
                    source.destroy()
            for obj, handler_id in init_signal_handlers:
                try:
                    obj.disconnect(handler_id)
                except Exception:
                    pass

        if errors:
            raise WirePlumberError(f"WirePlumber initialization failed: {errors[0]}") from errors[0]

        if pending:
            missing = ", ".join(sorted(pending))
            raise WirePlumberError(f"WirePlumber initialization timed out waiting for: {missing}")

        self._connected = True

    def close(self) -> None:
        for handler_id, metadata in list(self._metadata_signal_objects.items()):
            try:
                metadata.disconnect(handler_id)
            except Exception:
                pass
        self._metadata_signal_objects.clear()

        if self._core is not None:
            try:
                self._core.disconnect()
            except Exception:
                pass

        self._connected = False
        self._core = None
        self._node_manager = None
        self._metadata_manager = None
        self._cached_defaults = WirePlumberDefaults(None, None)

    def list_nodes(self) -> list[WirePlumberNode]:
        self._ensure_connected()
        return [self._node_from_proxy(node) for node in self._iterate_manager(self._node_manager)]

    def list_audio_sinks(self) -> list[WirePlumberNode]:
        return [node for node in self.list_nodes() if node.is_audio_sink]

    def list_output_streams(self) -> list[WirePlumberNode]:
        return [node for node in self.list_nodes() if node.is_output_stream]

    def node_from_proxy(self, node) -> WirePlumberNode:
        return self._node_from_proxy(node)

    def connect_object_added(self, callback) -> int:
        self._ensure_connected()
        return self._GObject.Object.connect(self._node_manager, "object-added", callback)

    def connect_object_removed(self, callback) -> int:
        self._ensure_connected()
        return self._GObject.Object.connect(self._node_manager, "object-removed", callback)

    def disconnect_node_manager_handler(self, handler_id: int) -> None:
        if self._node_manager is not None and handler_id > 0:
            self._node_manager.disconnect(handler_id)

    def connect_metadata_changed(self, callback) -> int:
        metadata = self._default_metadata()
        handler_id = self._GObject.Object.connect(metadata, "changed", callback)
        self._metadata_signal_objects[handler_id] = metadata
        return handler_id

    def disconnect_metadata_handler(self, handler_id: int) -> None:
        if handler_id <= 0:
            return

        metadata = self._metadata_signal_objects.pop(handler_id, None)
        if metadata is None:
            return

        try:
            metadata.disconnect(handler_id)
        except Exception:
            pass

    def sync(self) -> None:
        self._ensure_connected()
        self._sync_core()

    def defaults(self) -> WirePlumberDefaults:
        if self._has_cached_defaults():
            return self._cached_defaults

        return self.refresh_defaults()

    def refresh_defaults(self) -> WirePlumberDefaults:
        try:
            self._cached_defaults = self._read_defaults()
            return self._cached_defaults
        except UnicodeDecodeError:
            try:
                self._sync_core()
                self._cached_defaults = self._read_defaults()
                return self._cached_defaults
            except UnicodeDecodeError as retry_exc:
                if self._has_cached_defaults():
                    return self._cached_defaults
                raise WirePlumberError("WirePlumber metadata contains an undecodable default sink value") from retry_exc
            except Exception as retry_exc:
                if self._has_cached_defaults():
                    return self._cached_defaults
                raise WirePlumberError(f"failed to refresh WirePlumber defaults: {retry_exc}") from retry_exc
        except Exception:
            if self._has_cached_defaults():
                return self._cached_defaults
            raise

    def remember_default_metadata_change(self, key: str, value: str | None) -> bool:
        if key not in {DEFAULT_AUDIO_SINK_KEY, DEFAULT_CONFIGURED_AUDIO_SINK_KEY}:
            return False

        node_name = parse_metadata_node_name(value)
        if key == DEFAULT_AUDIO_SINK_KEY:
            self._cached_defaults = WirePlumberDefaults(node_name, self._cached_defaults.configured_audio_sink)
        else:
            self._cached_defaults = WirePlumberDefaults(self._cached_defaults.default_audio_sink, node_name)

        return True

    def _read_defaults(self) -> WirePlumberDefaults:
        metadata = self._default_metadata()
        default_sink, _default_type = metadata.find(0, DEFAULT_AUDIO_SINK_KEY)
        configured_sink, _configured_type = metadata.find(0, DEFAULT_CONFIGURED_AUDIO_SINK_KEY)
        return WirePlumberDefaults(
            default_audio_sink=parse_metadata_node_name(default_sink),
            configured_audio_sink=parse_metadata_node_name(configured_sink),
        )

    def _has_cached_defaults(self) -> bool:
        return bool(self._cached_defaults.default_audio_sink or self._cached_defaults.configured_audio_sink)

    def move_stream_to_target(self, stream_bound_id: int, target_node_name: str) -> None:
        stream = self.output_stream_by_bound_id(stream_bound_id)
        if stream is None:
            raise WirePlumberError(f"output stream not found: {stream_bound_id}")

        if stream.node_dont_move:
            raise WirePlumberError(f"stream is marked node.dont-move: {stream.display_name}")

        target = self.audio_sink_by_name(target_node_name)
        if target is None:
            raise WirePlumberError(f"audio sink not found: {target_node_name}")

        if not target.object_serial:
            raise WirePlumberError(f"audio sink has no object.serial: {target_node_name}")

        self.set_metadata_and_wait(stream.bound_id, TARGET_OBJECT_KEY, SPA_ID_TYPE, target.object_serial)

    def stream_targets_node(self, stream_bound_id: int, target_node_name: str) -> bool:
        target = self.audio_sink_by_name(target_node_name)
        if target is None:
            raise WirePlumberError(f"audio sink not found: {target_node_name}")

        if not target.object_serial:
            raise WirePlumberError(f"audio sink has no object.serial: {target_node_name}")

        target_object, target_type = self.stream_target_object(stream_bound_id)
        return target_object == target.object_serial and target_type in {None, SPA_ID_TYPE}

    def stream_target_object(self, stream_bound_id: int) -> tuple[str | None, str | None]:
        # WpMetadata reads from a cache. The upstream C API documents that this
        # cache is updated on a later PipeWire round-trip after set(). In Python
        # GI, repeated set()+find() on the same proxy can also expose stale
        # internal strings. Use set_metadata_and_wait() for write acks.
        value, type_name = self._default_metadata().find(stream_bound_id, TARGET_OBJECT_KEY)
        return value, type_name

    def set_metadata_and_wait(self, subject: int, key: str, type_name: str | None, value: str | None) -> bool:
        metadata = self._default_metadata()
        loop = self._GLib.MainLoop()
        matched = False

        def on_changed(_metadata, changed_subject, changed_key, changed_type, changed_value) -> None:
            nonlocal matched
            if changed_subject != subject or changed_key != key:
                return
            if changed_value != value:
                return
            if type_name is not None and changed_type != type_name:
                return

            matched = True
            loop.quit()

        def on_timeout() -> bool:
            loop.quit()
            return False

        handler_id = self._GObject.Object.connect(metadata, "changed", on_changed)
        timeout_id = self._GLib.timeout_add(self.timeout_ms, on_timeout)

        try:
            metadata.set(subject, key, type_name, value)
            self._sync_core()
            if not matched:
                loop.run()
        finally:
            metadata.disconnect(handler_id)
            source = self._GLib.MainContext.default().find_source_by_id(timeout_id)
            if source is not None:
                source.destroy()

        return matched

    def output_stream_by_bound_id(self, bound_id: int) -> WirePlumberNode | None:
        for stream in self.list_output_streams():
            if stream.bound_id == bound_id:
                return stream

        return None

    def audio_sink_by_name(self, node_name: str) -> WirePlumberNode | None:
        for sink in self.list_audio_sinks():
            if sink.node_name == node_name:
                return sink

        return None

    def set_node_params(self, node_bound_id: int, controls: dict[str, float]) -> None:
        self._ensure_connected()

        node = self._node_proxy_by_bound_id(node_bound_id)
        if node is None:
            raise WirePlumberError(f"node not found: {node_bound_id}")

        params_pod = build_spa_params_pod(self._Wp, controls)
        if not node.set_param("Props", 0, params_pod):
            raise WirePlumberError(f"failed to set node params: {node_bound_id}")

    def load_filter_chain_module(self, arguments: str):
        self._ensure_connected()

        module = self._Wp.ImplModule.load(self._core, FILTER_CHAIN_MODULE_NAME, arguments, None)
        if module is None:
            raise WirePlumberError(f"failed to load PipeWire module: {FILTER_CHAIN_MODULE_NAME}")

        return module

    def _build_node_manager(self, Wp):
        manager = Wp.ObjectManager.new()
        manager.add_interest_full(Wp.ObjectInterest.new_type(Wp.Node))
        features = Wp.ProxyFeatures.PIPEWIRE_OBJECT_FEATURE_INFO | Wp.ProxyFeatures.PROXY_FEATURE_BOUND
        manager.request_object_features(Wp.Node, features)
        return manager

    @staticmethod
    def _new_core(Wp):
        try:
            return Wp.Core.new(None, None, None)
        except TypeError:
            return Wp.Core.new(None, None)

    def _build_metadata_manager(self, Wp):
        manager = Wp.ObjectManager.new()
        manager.add_interest_full(Wp.ObjectInterest.new_type(Wp.Metadata))
        manager.request_object_features(Wp.Metadata, Wp.ProxyFeatures.PROXY_FEATURE_BOUND)
        return manager

    def _default_metadata(self):
        self._ensure_connected()

        for metadata in self._iterate_manager(self._metadata_manager):
            props = metadata.get_global_properties()
            if props.get("metadata.name") == DEFAULT_METADATA_NAME:
                return metadata

        raise WirePlumberError("default WirePlumber metadata object not found")

    def _node_from_proxy(self, node) -> WirePlumberNode:
        properties = self._properties_dict(node)
        return WirePlumberNode(
            bound_id=int(node.get_bound_id()),
            object_serial=self._pw_property(node, "object.serial", properties),
            media_class=self._pw_property(node, "media.class", properties),
            node_name=self._pw_property(node, "node.name", properties),
            node_description=self._pw_property(node, "node.description", properties),
            application_name=self._pw_property(node, "application.name", properties),
            node_dont_move=parse_bool_property(self._pw_property(node, "node.dont-move", properties)),
            properties=properties,
        )

    def _node_proxy_by_bound_id(self, bound_id: int):
        for node in self._iterate_manager(self._node_manager):
            if int(node.get_bound_id()) == int(bound_id):
                return node

        return None

    def _pw_property(self, proxy, key: str, properties: dict[str, str] | None = None) -> str | None:
        if properties is not None and key in properties:
            return properties[key]

        try:
            value = self._Wp.PipewireObject.get_property(proxy, key)
            if value is not None:
                return str(value)
        except TypeError:
            pass

        try:
            props = proxy.get_global_properties()
            value = props.get(key)
            return str(value) if value is not None else None
        except Exception:
            return None

    def _properties_dict(self, proxy) -> dict[str, str]:
        try:
            props = proxy.get_global_properties()
            iterator = props.new_iterator()
        except Exception:
            return {}

        result: dict[str, str] = {}

        while True:
            try:
                ok, item = iterator.next()
            except TypeError:
                break

            if not ok or item is None:
                break

            key = item.get_key()
            value = item.get_value()
            if key is not None and value is not None:
                result[str(key)] = str(value)

        return result

    def _iterate_manager(self, manager) -> list[Any]:
        iterator = manager.new_iterator()
        items: list[Any] = []

        while True:
            try:
                ok, item = iterator.next()
            except TypeError:
                break

            if not ok:
                break
            if item is not None:
                items.append(item)

        return items

    def _ensure_connected(self) -> None:
        if not self._connected:
            self.connect()

    def _sync_core(self) -> None:
        errors: list[BaseException] = []
        loop = self._GLib.MainLoop()
        timeout_id = 0

        def on_sync_done(core, result, _user_data=None) -> None:
            try:
                if not core.sync_finish(result):
                    errors.append(WirePlumberError("WirePlumber core sync failed"))
            except BaseException as exc:
                errors.append(exc)
            finally:
                loop.quit()

        def on_timeout() -> bool:
            errors.append(WirePlumberError("WirePlumber core sync timed out"))
            loop.quit()
            return False

        if not self._core.sync(None, on_sync_done, None):
            raise WirePlumberError("failed to start WirePlumber core sync")

        try:
            timeout_id = self._GLib.timeout_add(self.timeout_ms, on_timeout)
            loop.run()
        finally:
            if timeout_id > 0:
                source = self._GLib.MainContext.default().find_source_by_id(timeout_id)
                if source is not None:
                    source.destroy()

        if errors:
            raise WirePlumberError(f"WirePlumber core sync failed: {errors[0]}") from errors[0]

    @staticmethod
    def _import_wireplumber():
        import gi

        last_error: Exception | None = None
        for version in ("0.5", "0.4"):
            try:
                gi.require_version("Wp", version)
                break
            except ValueError as exc:
                last_error = exc
        else:
            if last_error is not None:
                raise last_error
            raise WirePlumberError("WirePlumber GI namespace is not available")

        from gi.repository import GLib, GObject, Wp

        return GLib, GObject, Wp
