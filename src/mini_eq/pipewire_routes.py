from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import quote

OUTPUT_PRESET_ROUTE_KEY_PREFIX = "pipewire-route:v1:"
OUTPUT_ROUTE_DIRECTION = "output"
DEVICE_ROUTE_PARAM_NAME = "Route"
DEVICE_LABEL_PROPERTY_KEYS = ("device.description", "device.nick", "device.name")


@dataclass(frozen=True)
class PipeWireOutputRoute:
    device_bound_id: int
    device_name: str | None
    index: int
    route_device: int
    profile: int
    priority: int
    direction: str | None
    name: str | None
    description: str | None
    availability: str | None
    info: dict[str, str] = field(default_factory=dict)

    @property
    def output_preset_key(self) -> str | None:
        return build_output_route_preset_key(self.device_name, self.name, self.route_device)


@dataclass(frozen=True)
class PipeWireOutputPresetTarget:
    output_key: str | None
    route: PipeWireOutputRoute | None
    keys: tuple[str, ...]

    @property
    def link_key(self) -> str:
        return next(iter(self.keys), self.output_key or "")

    @property
    def has_route_key(self) -> bool:
        route_key = self.route.output_preset_key if self.route is not None else None
        return route_key is not None and route_key in self.keys


def build_output_route_preset_key(device_name: str | None, route_name: str | None, route_device: int) -> str | None:
    device = str(device_name or "").strip()
    route = str(route_name or "").strip()
    if not device or not route:
        return None

    encoded_device = quote(device, safe="")
    encoded_route = quote(route, safe="")
    return f"{OUTPUT_PRESET_ROUTE_KEY_PREFIX}device={encoded_device};route={encoded_route};route-device={int(route_device)}"


class PipeWireRouteMixin:
    def output_preset_keys_for_sink_name(self, sink_name: str | None) -> tuple[str, ...]:
        return self.output_preset_target_for_sink_name(sink_name).keys

    def output_preset_target_for_sink_name(self, sink_name: str | None) -> PipeWireOutputPresetTarget:
        node_name = str(sink_name or "").strip()
        if not node_name:
            return PipeWireOutputPresetTarget(None, None, ())

        keys: list[str] = []
        sink = self.audio_sink_by_name(node_name)
        route = self.output_route_for_sink(sink)
        route_key = route.output_preset_key if route is not None else None
        if route_key:
            keys.append(route_key)
        keys.append(node_name)

        return PipeWireOutputPresetTarget(node_name, route, tuple(dict.fromkeys(keys)))

    def output_route_for_sink(self, sink) -> PipeWireOutputRoute | None:
        if sink is None or sink.device_id <= 0:
            return None

        route = self._cached_output_route_for_sink(sink)
        if route is not None:
            return route

        if not self._has_device_route_api():
            return None

        device = self._device_proxy_by_bound_id(sink.device_id)
        if device is None:
            return None

        routes = self._enumerate_device_routes(device, sink.device_id)
        output_routes = [
            route
            for route in routes
            if str(route.direction or "").casefold() == OUTPUT_ROUTE_DIRECTION
            and (route.availability or "unknown").casefold() != "no"
        ]
        return self._select_output_route_for_sink(sink, output_routes)

    def _cached_output_route_for_sink(self, sink) -> PipeWireOutputRoute | None:
        try:
            output_routes = tuple(self._device_active_output_routes.get(int(sink.device_id), {}).values())
        except Exception:
            output_routes = ()
        return self._select_output_route_for_sink(sink, output_routes)

    def _select_output_route_for_sink(
        self, sink, output_routes: list[PipeWireOutputRoute] | tuple[PipeWireOutputRoute, ...]
    ) -> PipeWireOutputRoute | None:
        if not output_routes:
            return None

        if sink.card_profile_device > 0:
            matching_device_routes = [
                route for route in output_routes if route.route_device == sink.card_profile_device
            ]
            if len(matching_device_routes) == 1:
                return matching_device_routes[0]
            if len(matching_device_routes) > 1:
                return None

        if len(output_routes) == 1:
            return output_routes[0]

        return None

    def _remember_device_route_param(self, device_bound_id: int, param) -> bool:
        if not self._has_device_route_api():
            return False

        try:
            route_info = self._Pwg.RouteInfo.new_from_param(param)
        except Exception:
            return False

        if route_info is None:
            return False

        route = self._output_route_from_info(
            route_info,
            device_bound_id,
            self._device_name_by_bound_id(device_bound_id),
        )
        if str(route.direction or "").casefold() != OUTPUT_ROUTE_DIRECTION:
            return False

        device_bound_id = int(device_bound_id)
        cached_routes = self._device_active_output_routes.get(device_bound_id, {})
        previous_routes = dict(cached_routes)
        if (route.availability or "unknown").casefold() == "no":
            if route.route_device not in cached_routes:
                return False

            cached_routes = dict(cached_routes)
            cached_routes.pop(route.route_device, None)
            if cached_routes:
                self._device_active_output_routes[device_bound_id] = cached_routes
            else:
                self._device_active_output_routes.pop(device_bound_id, None)
            return True

        current_routes = {route.route_device: route}
        self._device_active_output_routes[device_bound_id] = current_routes
        return previous_routes != current_routes

    def _has_device_route_api(self) -> bool:
        return (
            self._Pwg is not None
            and hasattr(self._Pwg, "Device")
            and hasattr(self._Pwg, "RouteInfo")
            and hasattr(self._Pwg.Device, "enum_params_sync")
            and hasattr(self._Pwg.Device, "new")
            and hasattr(self._Pwg.Device, "sync")
            and hasattr(self._Pwg.RouteInfo, "new_from_param")
        )

    def _has_device_route_subscription_api(self) -> bool:
        return (
            self._has_device_route_api()
            and self._GLib is not None
            and self._GObject is not None
            and hasattr(self._Pwg.Device, "subscribe_params")
        )

    def _device_name_by_bound_id(self, bound_id: int) -> str | None:
        return self._device_properties_by_bound_id(bound_id).get("device.name")

    def _properties_with_device_labels(self, node_properties: dict[str, str], device_bound_id: int) -> dict[str, str]:
        device_properties = self._device_properties_by_bound_id(device_bound_id)
        if not device_properties:
            return node_properties

        merged = dict(node_properties)
        for key in DEVICE_LABEL_PROPERTY_KEYS:
            value = device_properties.get(key)
            if value and not merged.get(key):
                merged[key] = value

        return merged

    def _device_properties_by_bound_id(self, bound_id: int) -> dict[str, str]:
        if self._registry is None:
            return {}

        try:
            global_ = self._registry.lookup_global(int(bound_id))
        except Exception:
            return {}

        try:
            if global_ is None or not global_.is_device():
                return {}
        except Exception:
            return {}

        return self._properties_dict(global_)

    def _enumerate_device_routes(self, device, device_bound_id: int) -> list[PipeWireOutputRoute]:
        route_param_id = self._device_route_param_id(device)
        if route_param_id is None:
            return []

        bound_id = int(device_bound_id)
        self._device_route_refreshing_bound_ids.add(bound_id)
        try:
            params = device.enum_params_sync(route_param_id, 0, 0, max(int(self.timeout_ms), 1))
            if params is None:
                return []

            device_name = self._device_name_by_bound_id(device_bound_id)
            routes: list[PipeWireOutputRoute] = []
            for param in self._iterate_model(params):
                try:
                    param_name = param.dup_name()
                except Exception:
                    param_name = None
                if param_name != DEVICE_ROUTE_PARAM_NAME:
                    continue

                try:
                    route_info = self._Pwg.RouteInfo.new_from_param(param)
                except Exception:
                    continue

                if route_info is None:
                    continue

                routes.append(self._output_route_from_info(route_info, device_bound_id, device_name))

            return routes
        except Exception:
            return []
        finally:
            self._device_route_refreshing_bound_ids.discard(bound_id)

    def _device_route_param_id(self, device) -> int | None:
        route_param_id = self._device_param_id_by_name(device, DEVICE_ROUTE_PARAM_NAME)
        if route_param_id is None:
            self._sync_proxy(device, "device")
            route_param_id = self._device_param_id_by_name(device, DEVICE_ROUTE_PARAM_NAME)
        return route_param_id

    def _device_param_id_by_name(self, device, name: str) -> int | None:
        for param_info in self._iterate_model(device.get_param_infos()):
            try:
                param_name = param_info.dup_name()
                param_id = int(param_info.get_id())
            except Exception:
                continue

            if param_name == name:
                return param_id

        return None

    def _output_route_from_info(
        self,
        route_info,
        device_bound_id: int,
        device_name: str | None,
    ) -> PipeWireOutputRoute:
        return PipeWireOutputRoute(
            device_bound_id=device_bound_id,
            device_name=device_name,
            index=int(route_info.get_index()),
            route_device=int(route_info.get_device()),
            profile=int(route_info.get_profile()),
            priority=int(route_info.get_priority()),
            direction=route_info.dup_direction(),
            name=route_info.dup_name(),
            description=route_info.dup_description(),
            availability=route_info.dup_availability(),
            info=self._variant_to_string_dict(route_info.get_info()),
        )

    @staticmethod
    def _variant_to_string_dict(variant) -> dict[str, str]:
        if variant is None:
            return {}

        try:
            values = variant.unpack()
        except AttributeError:
            values = variant
        except Exception:
            return {}

        try:
            items = values.items()
        except AttributeError:
            return {}

        result: dict[str, str] = {}
        for key, value in items:
            if key is not None and value is not None:
                result[str(key)] = str(value)
        return result
