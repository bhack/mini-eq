from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .pipewire_routes import DEVICE_ROUTE_PARAM_NAME, PipeWireOutputRoute, PipeWireRouteMixin

DEFAULT_METADATA_NAME = "default"
DEFAULT_AUDIO_SINK_KEY = "default.audio.sink"
DEFAULT_CONFIGURED_AUDIO_SINK_KEY = "default.configured.audio.sink"
TARGET_OBJECT_KEY = "target.object"
TARGET_NODE_KEY = "target.node"
SPA_ID_TYPE = "Spa:Id"
PIPEWIRE_NODE_INTERFACE = "PipeWire:Interface:Node"
PIPEWIRE_DEVICE_INTERFACE = "PipeWire:Interface:Device"
PIPEWIRE_LINK_INTERFACE = "PipeWire:Interface:Link"
STREAM_OUTPUT_AUDIO = "Stream/Output/Audio"
AUDIO_SINK = "Audio/Sink"
LINK_STATE_ACTIVE = "active"
FILTER_CHAIN_MODULE_NAME = "libpipewire-module-filter-chain"
PIPEWIRE_APPLICATION_NAME_KEY = "application.name"
PIPEWIRE_MEDIA_CATEGORY_KEY = "media.category"
PIPEWIRE_CLIENT_NAME = "Mini EQ"
PIPEWIRE_MEDIA_CATEGORY = "Manager"


@dataclass(frozen=True)
class PipeWireNode:
    bound_id: int
    object_serial: str | None
    media_class: str | None
    node_name: str | None
    node_description: str | None
    application_name: str | None
    node_dont_move: bool
    device_id: int = 0
    card_profile_device: int = 0
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
class PipeWireDefaults:
    default_audio_sink: str | None
    configured_audio_sink: str | None


@dataclass(frozen=True)
class PipeWireStreamTarget:
    target_node: str | None
    target_node_type: str | None
    target_object: str | None
    target_object_type: str | None


@dataclass(frozen=True)
class PipeWireLink:
    bound_id: int
    output_node_id: int
    input_node_id: int
    passive: bool
    feedback: bool


class PipeWireBackendError(RuntimeError):
    pass


class PipeWireNodeWatch:
    def __init__(self, cancel_callback: Callable[[], None]) -> None:
        self._cancel_callback = cancel_callback

    def cancel(self) -> None:
        cancel_callback = self._cancel_callback
        if cancel_callback is None:
            return

        self._cancel_callback = None
        cancel_callback()


def build_props_controls_param(Pwg, GLib, controls: dict[str, float]):
    variant = GLib.Variant("a{sd}", {name: float(value) for name, value in controls.items()})
    param = Pwg.Param.new_props_controls(variant)
    if param is None:
        raise PipeWireBackendError("failed to build PipeWire node control parameter")
    return param


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


def node_sample_rate(node: PipeWireNode | None) -> float:
    if node is None:
        return 0.0

    rate = parse_positive_int(node.property_value("audio.rate"))
    if rate <= 0:
        rate = parse_rate_from_latency(node.property_value("node.max-latency"))
    if rate <= 0:
        rate = parse_rate_from_latency(node.property_value("node.latency"))

    return float(rate) if rate > 0 else 0.0


class PipeWireBackend(PipeWireRouteMixin):
    def __init__(self, timeout_ms: int = 2000) -> None:
        self.timeout_ms = timeout_ms
        self._connected = False
        self._GLib: Any = None
        self._GObject: Any = None
        self._Pwg: Any = None
        self._core: Any = None
        self._registry: Any = None
        self._metadata: Any = None
        self._metadata_signal_objects: dict[int, Any] = {}
        self._node_signal_objects: dict[int, Any] = {}
        self._link_signal_objects: dict[int, Any] = {}
        self._device_signal_objects: dict[int, Any] = {}
        self._device_related_signal_handler_ids: dict[int, list[int]] = {}
        self._node_proxies: dict[int, Any] = {}
        self._link_proxies: dict[int, Any] = {}
        self._device_proxies: dict[int, Any] = {}
        self._loaded_modules: list[Any] = []
        self._cached_defaults = PipeWireDefaults(None, None)
        self._device_route_refreshing_bound_ids: set[int] = set()
        self._device_active_output_routes: dict[int, dict[int, PipeWireOutputRoute]] = {}

    def __enter__(self) -> PipeWireBackend:
        self.connect()
        return self

    def __exit__(self, _exc_type, _exc, _tb) -> None:
        self.close()

    def connect(self) -> None:
        if self._connected:
            return

        GLib, GObject, Pwg = self._import_pipewire_gobject()
        self._GLib = GLib
        self._GObject = GObject
        self._Pwg = Pwg

        Pwg.init()
        self._core = self._new_core(Pwg)
        if not self._core.connect():
            raise PipeWireBackendError("failed to connect to PipeWire")

        self._registry = Pwg.Registry.new(self._core)
        if not self._registry.start():
            raise PipeWireBackendError("failed to start PipeWire registry discovery")

        self._metadata = Pwg.Metadata.new(self._core, DEFAULT_METADATA_NAME)
        if not self._metadata.start():
            raise PipeWireBackendError("failed to start PipeWire default metadata discovery")

        self._sync_initial_state()
        self._connected = True

    def close(self) -> None:
        for handler_id, obj in list(self._metadata_signal_objects.items()):
            try:
                obj.disconnect(handler_id)
            except Exception:
                pass
        self._metadata_signal_objects.clear()

        for handler_id, obj in list(self._node_signal_objects.items()):
            try:
                obj.disconnect(handler_id)
            except Exception:
                pass
        self._node_signal_objects.clear()

        for handler_id, obj in list(self._link_signal_objects.items()):
            try:
                obj.disconnect(handler_id)
            except Exception:
                pass
        self._link_signal_objects.clear()

        for handler_id in list(self._device_signal_objects):
            self.disconnect_device_handler(handler_id)

        for node in list(self._node_proxies.values()):
            try:
                node.stop()
            except Exception:
                pass
        self._node_proxies.clear()

        for link in list(self._link_proxies.values()):
            try:
                link.stop()
            except Exception:
                pass
        self._link_proxies.clear()

        for device in list(self._device_proxies.values()):
            try:
                device.stop()
            except Exception:
                pass
        self._device_proxies.clear()

        for module in list(self._loaded_modules):
            try:
                module.unload()
            except Exception:
                pass
        self._loaded_modules.clear()

        if self._metadata is not None:
            try:
                self._metadata.stop()
            except Exception:
                pass
        if self._registry is not None:
            try:
                self._registry.stop()
            except Exception:
                pass
        if self._core is not None:
            try:
                self._core.disconnect()
            except Exception:
                pass

        self._connected = False
        self._core = None
        self._registry = None
        self._metadata = None
        self._cached_defaults = PipeWireDefaults(None, None)
        self._device_active_output_routes.clear()

    def list_nodes(self) -> list[PipeWireNode]:
        self._ensure_connected()
        nodes: list[PipeWireNode] = []

        for global_ in self._iterate_model(self._registry.dup_globals_by_interface(PIPEWIRE_NODE_INTERFACE)):
            try:
                nodes.append(self._node_from_global(global_))
            except UnicodeDecodeError:
                continue

        return nodes

    def list_audio_sinks(self) -> list[PipeWireNode]:
        return [node for node in self.list_nodes() if node.is_audio_sink]

    def list_output_streams(self) -> list[PipeWireNode]:
        return [node for node in self.list_nodes() if node.is_output_stream]

    def list_links(self) -> list[PipeWireLink]:
        self._ensure_connected()
        links: list[PipeWireLink] = []

        for global_ in self._iterate_model(self._registry.dup_globals_by_interface(PIPEWIRE_LINK_INTERFACE)):
            try:
                links.append(self._link_from_global(global_))
            except PipeWireBackendError:
                continue

        return links

    def node_from_proxy(self, node) -> PipeWireNode:
        if hasattr(node, "is_node") and not node.is_node():
            raise PipeWireBackendError("PipeWire global is not a node")
        return self._node_from_global(node)

    def link_from_proxy(self, link) -> PipeWireLink:
        return self._link_from_global(link)

    def node_by_name(self, node_name: str) -> PipeWireNode | None:
        for node in self.list_nodes():
            if node.node_name == node_name:
                return node

        return None

    def watch_for_node(
        self,
        predicate: Callable[[PipeWireNode], bool],
        callback: Callable[[PipeWireNode | None], None],
        timeout_ms: int | None = None,
    ) -> PipeWireNodeWatch:
        self._ensure_connected()

        if self._GLib is None or self._GObject is None or self._registry is None:
            raise PipeWireBackendError("PipeWire registry is not connected")

        deadline_ms = max(int(self.timeout_ms if timeout_ms is None else timeout_ms), 1)
        state = {
            "done": False,
            "scheduled": False,
            "handler_id": 0,
            "timeout_id": 0,
            "idle_id": 0,
        }

        def maybe_match(global_) -> PipeWireNode | None:
            try:
                node = self._node_from_global(global_)
            except UnicodeDecodeError:
                return None
            except Exception:
                return None

            return node if predicate(node) else None

        def cleanup(*, remove_idle: bool) -> None:
            handler_id = int(state["handler_id"])
            state["handler_id"] = 0
            if handler_id > 0:
                try:
                    self._registry.disconnect(handler_id)
                except Exception:
                    pass

            timeout_id = int(state["timeout_id"])
            state["timeout_id"] = 0
            if timeout_id > 0:
                try:
                    self._GLib.source_remove(timeout_id)
                except Exception:
                    pass

            idle_id = int(state["idle_id"])
            if remove_idle and idle_id > 0:
                state["idle_id"] = 0
                try:
                    self._GLib.source_remove(idle_id)
                except Exception:
                    pass

        def complete(node: PipeWireNode | None) -> bool:
            if state["done"] or state["scheduled"]:
                return False

            state["done"] = True
            cleanup(remove_idle=False)
            callback(node)
            return False

        def complete_from_idle(node: PipeWireNode) -> bool:
            state["idle_id"] = 0
            if state["done"]:
                return False

            state["done"] = True
            callback(node)
            return False

        def schedule_complete(node: PipeWireNode) -> None:
            if state["done"] or state["scheduled"]:
                return

            state["scheduled"] = True
            cleanup(remove_idle=False)
            state["idle_id"] = self._GLib.idle_add(lambda: complete_from_idle(node))

        def on_global_added(_registry, global_) -> None:
            node = maybe_match(global_)
            if node is not None:
                schedule_complete(node)

        def on_timeout() -> bool:
            state["timeout_id"] = 0
            return complete(None)

        def cancel() -> None:
            if state["done"]:
                return

            state["done"] = True
            cleanup(remove_idle=True)

        state["handler_id"] = self._GObject.Object.connect(self._registry, "global-added", on_global_added)
        watch = PipeWireNodeWatch(cancel)
        for global_ in self._iterate_model(self._registry.dup_globals_by_interface(PIPEWIRE_NODE_INTERFACE)):
            node = maybe_match(global_)
            if node is not None:
                schedule_complete(node)
                return watch

        state["timeout_id"] = self._GLib.timeout_add(deadline_ms, on_timeout)
        return watch

    def watch_for_audio_sink(
        self,
        sink_name: str,
        callback: Callable[[PipeWireNode | None], None],
        timeout_ms: int | None = None,
    ) -> PipeWireNodeWatch:
        return self.watch_for_node(
            lambda node: node.is_audio_sink and node.node_name == sink_name,
            callback,
            timeout_ms=timeout_ms,
        )

    def connect_object_added(self, callback) -> int:
        self._ensure_connected()
        handler_id = self._GObject.Object.connect(self._registry, "global-added", callback)
        self._node_signal_objects[handler_id] = self._registry
        return handler_id

    def connect_object_removed(self, callback) -> int:
        self._ensure_connected()
        handler_id = self._GObject.Object.connect(self._registry, "global-removed", callback)
        self._node_signal_objects[handler_id] = self._registry
        return handler_id

    def disconnect_node_manager_handler(self, handler_id: int) -> None:
        if handler_id <= 0:
            return

        obj = self._node_signal_objects.pop(handler_id, None)
        if obj is None:
            return

        try:
            obj.disconnect(handler_id)
        except Exception:
            pass

    def connect_link_state_changed(self, link_bound_id: int, callback: Callable[[str | None], None]) -> int:
        self._ensure_connected()

        link = self._link_proxy_by_bound_id(link_bound_id)
        if link is None:
            return 0

        def on_state_changed(changed_link, _pspec) -> None:
            callback(changed_link.get_state())

        handler_id = self._GObject.Object.connect(link, "notify::state", on_state_changed)
        self._link_signal_objects[handler_id] = link
        callback(link.get_state())
        return handler_id

    def disconnect_link_handler(self, handler_id: int) -> None:
        if handler_id <= 0:
            return

        link = self._link_signal_objects.pop(handler_id, None)
        if link is None:
            return

        try:
            link.disconnect(handler_id)
        except Exception:
            pass

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

    def connect_device_route_changed(self, device_bound_id: int, callback) -> int:
        self._ensure_connected()

        if not self._has_device_route_subscription_api():
            return 0

        device = self._device_proxy_by_bound_id(device_bound_id)
        if device is None:
            return 0

        route_param_ids = self._device_route_event_param_ids(device)
        if not route_param_ids:
            return 0
        route_param_id = route_param_ids.get(DEVICE_ROUTE_PARAM_NAME)
        route_event_param_ids = set(route_param_ids.values())
        subscribed_param_ids = list(dict.fromkeys(route_param_ids.values()))

        def on_device_param(_device, param) -> None:
            try:
                param_id = int(param.get_id())
            except Exception:
                return

            if param_id not in route_event_param_ids or int(device_bound_id) in self._device_route_refreshing_bound_ids:
                return

            if route_param_id is not None and param_id == route_param_id:
                if self._remember_device_route_param(device_bound_id, param):
                    callback()
                return

            self._device_active_output_routes.pop(int(device_bound_id), None)
            callback()

        def on_device_param_infos_changed(_device, _pspec) -> None:
            if int(device_bound_id) in self._device_route_refreshing_bound_ids:
                return

            self._device_active_output_routes.pop(int(device_bound_id), None)
            callback()

        handler_id = self._GObject.Object.connect(device, "param", on_device_param)
        related_handler_ids = [
            self._GObject.Object.connect(device, "notify::param-infos", on_device_param_infos_changed)
        ]
        self._device_signal_objects[handler_id] = device
        self._device_related_signal_handler_ids[handler_id] = related_handler_ids

        try:
            device.subscribe_params(self._GLib.Variant("au", subscribed_param_ids))
        except Exception:
            self.disconnect_device_handler(handler_id)
            return 0

        return handler_id

    def disconnect_device_handler(self, handler_id: int) -> None:
        if handler_id <= 0:
            return

        device = self._device_signal_objects.pop(handler_id, None)
        related_handler_ids = self._device_related_signal_handler_ids.pop(handler_id, [])
        if device is None:
            return

        try:
            if self._GLib is not None and hasattr(device, "subscribe_params"):
                device.subscribe_params(self._GLib.Variant("au", []))
        except Exception:
            pass

        for related_handler_id in related_handler_ids:
            try:
                device.disconnect(related_handler_id)
            except Exception:
                pass

        try:
            device.disconnect(handler_id)
        except Exception:
            pass

    def sync(self) -> None:
        self._ensure_connected()
        self._sync_registry()
        self._sync_metadata()

    def defaults(self) -> PipeWireDefaults:
        if self._has_cached_defaults():
            return self._cached_defaults

        return self.refresh_defaults()

    def refresh_defaults(self) -> PipeWireDefaults:
        try:
            self._cached_defaults = self._read_defaults()
            return self._cached_defaults
        except UnicodeDecodeError:
            try:
                self._sync_metadata()
                self._cached_defaults = self._read_defaults()
                return self._cached_defaults
            except UnicodeDecodeError as retry_exc:
                if self._has_cached_defaults():
                    return self._cached_defaults
                raise PipeWireBackendError(
                    "PipeWire metadata contains an undecodable default sink value"
                ) from retry_exc
            except Exception as retry_exc:
                if self._has_cached_defaults():
                    return self._cached_defaults
                raise PipeWireBackendError(f"failed to refresh PipeWire defaults: {retry_exc}") from retry_exc
        except Exception:
            if self._has_cached_defaults():
                return self._cached_defaults
            raise

    def remember_default_metadata_change(self, key: str, value: str | None) -> bool:
        if key not in {DEFAULT_AUDIO_SINK_KEY, DEFAULT_CONFIGURED_AUDIO_SINK_KEY}:
            return False

        node_name = parse_metadata_node_name(value)
        if key == DEFAULT_AUDIO_SINK_KEY:
            self._cached_defaults = PipeWireDefaults(node_name, self._cached_defaults.configured_audio_sink)
        else:
            self._cached_defaults = PipeWireDefaults(self._cached_defaults.default_audio_sink, node_name)

        return True

    def _read_defaults(self) -> PipeWireDefaults:
        metadata = self._default_metadata()
        return PipeWireDefaults(
            default_audio_sink=metadata.dup_default_audio_sink_name(),
            configured_audio_sink=metadata.dup_configured_audio_sink_name(),
        )

    def _has_cached_defaults(self) -> bool:
        return bool(self._cached_defaults.default_audio_sink or self._cached_defaults.configured_audio_sink)

    def move_stream_to_target(self, stream_bound_id: int, target_node_name: str) -> None:
        stream = self.output_stream_by_bound_id(stream_bound_id)
        if stream is None:
            raise PipeWireBackendError(f"output stream not found: {stream_bound_id}")

        if stream.node_dont_move:
            raise PipeWireBackendError(f"stream is marked node.dont-move: {stream.display_name}")

        target = self.audio_sink_by_name(target_node_name)
        if target is None:
            raise PipeWireBackendError(f"audio sink not found: {target_node_name}")

        if not target.object_serial:
            raise PipeWireBackendError(f"audio sink has no object.serial: {target_node_name}")

        self.set_stream_target(stream.bound_id, target.bound_id, target.object_serial)

    def stream_target(self, stream_bound_id: int) -> PipeWireStreamTarget:
        metadata = self._default_metadata()
        return PipeWireStreamTarget(
            target_node=metadata.dup_value(stream_bound_id, TARGET_NODE_KEY),
            target_node_type=metadata.dup_value_type(stream_bound_id, TARGET_NODE_KEY),
            target_object=metadata.dup_value(stream_bound_id, TARGET_OBJECT_KEY),
            target_object_type=metadata.dup_value_type(stream_bound_id, TARGET_OBJECT_KEY),
        )

    def set_stream_target(self, stream_bound_id: int, target_bound_id: int, target_serial: str) -> None:
        metadata = self._default_metadata()

        # target.node keeps compatibility with older session-manager behavior,
        # while target.object is the stable serial-based target used by modern
        # WirePlumber policy. Pwg owns only the metadata write, not routing
        # policy or acknowledgement semantics.
        for key, value in ((TARGET_NODE_KEY, str(target_bound_id)), (TARGET_OBJECT_KEY, target_serial)):
            if not metadata.set(stream_bound_id, key, SPA_ID_TYPE, value):
                raise PipeWireBackendError(f"failed to set stream target metadata: {stream_bound_id}")
        self._sync_metadata()

    def restore_stream_target(self, stream_bound_id: int, target: PipeWireStreamTarget) -> None:
        metadata = self._default_metadata()
        for key, type_name, value in (
            (TARGET_NODE_KEY, target.target_node_type, target.target_node),
            (TARGET_OBJECT_KEY, target.target_object_type, target.target_object),
        ):
            if not metadata.set(stream_bound_id, key, type_name, value):
                raise PipeWireBackendError(f"failed to restore stream target metadata: {stream_bound_id}")
        self._sync_metadata()

    def output_stream_by_bound_id(self, bound_id: int) -> PipeWireNode | None:
        for stream in self.list_output_streams():
            if stream.bound_id == bound_id:
                return stream

        return None

    def output_stream_by_name(self, node_name: str) -> PipeWireNode | None:
        for stream in self.list_output_streams():
            if stream.node_name == node_name:
                return stream

        return None

    def move_named_output_stream_to_target(self, stream_node_name: str, target_node_name: str) -> None:
        stream = self.output_stream_by_name(stream_node_name)
        if stream is None:
            raise PipeWireBackendError(f"output stream not found: {stream_node_name}")

        self.move_stream_to_target(stream.bound_id, target_node_name)

    def audio_sink_by_name(self, node_name: str) -> PipeWireNode | None:
        for sink in self.list_audio_sinks():
            if sink.node_name == node_name:
                return sink

        return None

    def set_node_params(self, node_bound_id: int, controls: dict[str, float]) -> None:
        self._ensure_connected()

        node = self._node_proxy_by_bound_id(node_bound_id)
        if node is None:
            raise PipeWireBackendError(f"node not found: {node_bound_id}")

        param = build_props_controls_param(self._Pwg, self._GLib, controls)
        if not node.set_param(param):
            raise PipeWireBackendError(f"failed to set node params: {node_bound_id}")

    def load_filter_chain_module(self, arguments: str):
        self._ensure_connected()

        module = self._core.load_module(FILTER_CHAIN_MODULE_NAME, arguments)
        if module is None:
            raise PipeWireBackendError(f"failed to load PipeWire module: {FILTER_CHAIN_MODULE_NAME}")

        self._loaded_modules.append(module)
        return module

    def unload_filter_chain_module(self, module) -> None:
        if module is None:
            return

        try:
            module.unload()
        finally:
            try:
                self._loaded_modules.remove(module)
            except ValueError:
                pass

    @staticmethod
    def _new_core(Pwg):
        core = Pwg.Core.new()
        set_pipewire_property = getattr(core, "set_pipewire_property", None)
        if set_pipewire_property is not None:
            set_pipewire_property(PIPEWIRE_APPLICATION_NAME_KEY, PIPEWIRE_CLIENT_NAME)
            set_pipewire_property(PIPEWIRE_MEDIA_CATEGORY_KEY, PIPEWIRE_MEDIA_CATEGORY)
        return core

    def _default_metadata(self):
        self._ensure_connected()

        if self._metadata is None or not self._metadata.get_bound():
            raise PipeWireBackendError("default PipeWire metadata object not found")
        return self._metadata

    def _node_from_global(self, global_) -> PipeWireNode:
        properties = self._properties_dict(global_)
        device_id = parse_positive_int(self._pw_property(global_, "device.id", properties))
        if device_id > 0:
            properties = self._properties_with_device_labels(properties, device_id)

        return PipeWireNode(
            bound_id=int(global_.get_id()),
            object_serial=self._pw_property(global_, "object.serial", properties),
            media_class=self._pw_property(global_, "media.class", properties),
            node_name=self._pw_property(global_, "node.name", properties),
            node_description=self._pw_property(global_, "node.description", properties),
            application_name=self._pw_property(global_, "application.name", properties),
            node_dont_move=parse_bool_property(self._pw_property(global_, "node.dont-move", properties)),
            device_id=device_id,
            card_profile_device=parse_positive_int(self._pw_property(global_, "card.profile.device", properties)),
            properties=properties,
        )

    def _link_from_global(self, global_) -> PipeWireLink:
        link_info = self._Pwg.LinkInfo.new_from_global(global_)
        if link_info is None:
            raise PipeWireBackendError("PipeWire global is not a link")

        return PipeWireLink(
            bound_id=int(link_info.get_id()),
            output_node_id=parse_positive_int(link_info.dup_output_node_id()),
            input_node_id=parse_positive_int(link_info.dup_input_node_id()),
            passive=bool(link_info.get_passive()),
            feedback=bool(link_info.get_feedback()),
        )

    def _node_proxy_by_bound_id(self, bound_id: int):
        global_ = self._registry.lookup_global(int(bound_id))
        if global_ is None or not global_.is_node():
            return None

        node = self._node_proxies.get(int(bound_id))
        if node is not None and node.get_running():
            return node

        node = self._Pwg.Node.new(self._core, global_)
        if node is None:
            return None
        if not node.start():
            raise PipeWireBackendError(f"failed to bind node: {bound_id}")
        self._sync_proxy(node, "node")

        self._node_proxies[int(bound_id)] = node
        return node

    def _link_proxy_by_bound_id(self, bound_id: int):
        global_ = self._registry.lookup_global(int(bound_id))
        if global_ is None or not global_.is_link():
            return None

        link = self._link_proxies.get(int(bound_id))
        if link is not None and link.get_running():
            return link

        link = self._Pwg.Link.new(self._core, global_)
        if link is None:
            return None
        if not link.start():
            raise PipeWireBackendError(f"failed to bind link: {bound_id}")
        self._sync_proxy(link, "link")

        self._link_proxies[int(bound_id)] = link
        return link

    def _device_proxy_by_bound_id(self, bound_id: int):
        global_ = self._registry.lookup_global(int(bound_id))
        if global_ is None or not global_.is_device():
            return None

        device = self._device_proxies.get(int(bound_id))
        if device is not None and device.get_running():
            return device

        device = self._Pwg.Device.new(self._core, global_)
        if device is None:
            return None
        if not device.start():
            raise PipeWireBackendError(f"failed to bind device: {bound_id}")
        self._sync_proxy(device, "device")

        self._device_proxies[int(bound_id)] = device
        return device

    def _pw_property(self, global_, key: str, properties: dict[str, str] | None = None) -> str | None:
        if properties is not None and key in properties:
            return properties[key]

        try:
            value = global_.dup_property(key)
            return str(value) if value is not None else None
        except (AttributeError, TypeError, UnicodeDecodeError):
            pass

        try:
            props = self._properties_dict(global_)
            return props.get(key)
        except Exception:
            return None

    def _properties_dict(self, global_) -> dict[str, str]:
        try:
            props = global_.get_properties()
        except Exception:
            return {}

        result: dict[str, str] = {}
        if hasattr(props, "new_iterator"):
            iterator = props.new_iterator()
            while True:
                try:
                    ok, item = iterator.next()
                except TypeError:
                    break

                if not ok or item is None:
                    break

                try:
                    key = item.get_key()
                    value = item.get_value()
                    key_text = str(key) if key is not None else None
                    value_text = str(value) if value is not None else None
                except UnicodeDecodeError:
                    continue

                if key_text is not None and value_text is not None:
                    result[key_text] = value_text
            return result

        try:
            values = props.unpack()
        except AttributeError:
            values = props
        except Exception:
            return {}

        try:
            items = values.items()
        except AttributeError:
            return result

        for key, value in items:
            try:
                key_text = str(key) if key is not None else None
                value_text = str(value) if value is not None else None
            except UnicodeDecodeError:
                continue

            if key_text is not None and value_text is not None:
                result[key_text] = value_text

        return result

    def _iterate_model(self, model) -> list[Any]:
        if model is None:
            return []

        try:
            count = int(model.get_n_items())
        except Exception:
            return []

        return [item for index in range(count) if (item := model.get_item(index)) is not None]

    def _ensure_connected(self) -> None:
        if not self._connected:
            self.connect()

    def _sync_initial_state(self) -> None:
        self._sync_registry()
        self._sync_metadata()

        missing = []
        if self._registry.get_globals().get_n_items() <= 0:
            missing.append("registry")
        if not self._metadata.get_bound():
            missing.append("metadata")
        if not missing:
            return

        raise PipeWireBackendError(f"PipeWire initialization did not report: {', '.join(missing)}")

    def _sync_registry(self) -> None:
        if self._registry is None:
            return

        try:
            synced = self._registry.sync(max(int(self.timeout_ms), 1))
        except Exception as exc:
            raise PipeWireBackendError(f"PipeWire registry sync failed: {exc}") from exc
        if synced is False:
            raise PipeWireBackendError("PipeWire registry sync failed")

    def _sync_metadata(self) -> None:
        if self._metadata is None:
            return

        try:
            synced = self._metadata.sync(max(int(self.timeout_ms), 1))
        except Exception as exc:
            raise PipeWireBackendError(f"PipeWire metadata sync failed: {exc}") from exc
        if synced is False:
            raise PipeWireBackendError("PipeWire metadata sync failed")

    def _sync_proxy(self, proxy, label: str) -> None:
        try:
            synced = proxy.sync(max(int(self.timeout_ms), 1))
        except Exception as exc:
            raise PipeWireBackendError(f"PipeWire {label} sync failed: {exc}") from exc
        if synced is False:
            raise PipeWireBackendError(f"PipeWire {label} sync failed")

    def _sync_core(self) -> None:
        if self._core is not None:
            try:
                synced = self._core.sync(max(int(self.timeout_ms), 1))
            except Exception as exc:
                raise PipeWireBackendError(f"PipeWire core sync failed: {exc}") from exc
            if synced is False:
                raise PipeWireBackendError("PipeWire core sync failed")

    @staticmethod
    def _import_pipewire_gobject():
        shim_error: Exception | None = None
        try:
            import pipewire_gobject  # noqa: F401
        except Exception as exc:  # pragma: no cover - depends on installed packaging layout
            shim_error = exc

        try:
            import gi

            gi.require_version("Pwg", "0.1")
            from gi.repository import GLib, GObject, Pwg
        except Exception as exc:
            if shim_error is not None:
                raise PipeWireBackendError(
                    f"pipewire-gobject is not available: Python shim failed with {shim_error}; "
                    f"Pwg GI import failed with {exc}"
                ) from exc
            raise

        return GLib, GObject, Pwg
