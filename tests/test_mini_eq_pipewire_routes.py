from __future__ import annotations

from tests._mini_eq_imports import pipewire_routes as pw_routes


def test_output_route_preset_key_encodes_device_and_route_names() -> None:
    assert (
        pw_routes.build_output_route_preset_key("alsa_card.pci 0000:00:1f.3", "analog-output-headphones", 8)
        == "pipewire-route:v1:device=alsa_card.pci%200000%3A00%3A1f.3;route=analog-output-headphones;route-device=8"
    )
    assert pw_routes.build_output_route_preset_key("", "analog-output-headphones", 8) is None
    assert pw_routes.build_output_route_preset_key("alsa_card.test", None, 8) is None


def test_output_preset_target_uses_route_key_when_present() -> None:
    route = pw_routes.PipeWireOutputRoute(
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
    route_key = route.output_preset_key

    target = pw_routes.PipeWireOutputPresetTarget("alsa_output.test", route, (route_key, "alsa_output.test"))

    assert route_key == "pipewire-route:v1:device=alsa_card.test;route=analog-output-headphones;route-device=8"
    assert target.link_key == route_key
    assert target.has_route_key is True


def test_output_preset_target_falls_back_to_output_key_without_route() -> None:
    target = pw_routes.PipeWireOutputPresetTarget("alsa_output.test", None, ("alsa_output.test",))

    assert target.link_key == "alsa_output.test"
    assert target.has_route_key is False
