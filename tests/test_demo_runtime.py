from tools.demo_runtime import DemoController


def test_demo_routing_preserves_bypass_on_startup() -> None:
    controller = DemoController()
    controller.eq_enabled = False

    controller.route_system_audio(True, preserve_eq_state=True)

    assert controller.routed is True
    assert controller.eq_enabled is False

    controller.route_system_audio(True)
    assert controller.eq_enabled is True


def test_demo_output_transition_consumption() -> None:
    controller = DemoController()
    first = controller.output_preset_target_transition()
    assert not first.changed
    controller.output_sink = "other-demo-output"
    observed = controller.output_preset_target_transition(consume=False)
    assert observed.changed
    assert observed.previous == first.current
    assert controller.output_preset_target_transition().changed
    assert not controller.output_preset_target_transition().changed
