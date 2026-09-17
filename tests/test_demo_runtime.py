from tools.demo_runtime import DemoController


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
