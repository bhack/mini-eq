from __future__ import annotations

from types import SimpleNamespace

import pytest

from tests._mini_eq_imports import import_mini_eq_module

core = import_mini_eq_module("core")
window_graph = import_mini_eq_module("window_graph")


class FakeLabel:
    def __init__(self) -> None:
        self.text = ""
        self.tooltip = ""
        self.visible = True
        self.css_classes: set[str] = set()

    def set_text(self, text: str) -> None:
        self.text = text

    def set_tooltip_text(self, text: str) -> None:
        self.tooltip = text

    def set_visible(self, visible: bool) -> None:
        self.visible = visible

    def add_css_class(self, css_class: str) -> None:
        self.css_classes.add(css_class)

    def remove_css_class(self, css_class: str) -> None:
        self.css_classes.discard(css_class)


class FakeSwitch:
    def __init__(self, active: bool) -> None:
        self.active = active
        self.sensitive = True
        self.tooltip = ""

    def get_active(self) -> bool:
        return self.active

    def set_sensitive(self, sensitive: bool) -> None:
        self.sensitive = sensitive

    def set_tooltip_text(self, text: str) -> None:
        self.tooltip = text


class FakeControl:
    def __init__(self) -> None:
        self.sensitive = True
        self.visible = True

    def set_sensitive(self, sensitive: bool) -> None:
        self.sensitive = sensitive

    def set_visible(self, visible: bool) -> None:
        self.visible = visible


class FakeSpin(FakeControl):
    def __init__(self) -> None:
        super().__init__()
        self.value = 0.0

    def set_value(self, value: float) -> None:
        self.value = value


class FakeDropDown(FakeControl):
    def __init__(self) -> None:
        super().__init__()
        self.selected = 0

    def set_selected(self, selected: int) -> None:
        self.selected = selected


class FakeToggle(FakeControl):
    def __init__(self) -> None:
        super().__init__()
        self.active = False

    def set_active(self, active: bool) -> None:
        self.active = active


class FakeScale:
    def __init__(self, value: float) -> None:
        self.value = value

    def get_value(self) -> float:
        return self.value


class FakeGraphArea:
    def __init__(self, width: int = 640, height: int = 240) -> None:
        self.width = width
        self.height = height

    def get_allocated_width(self) -> int:
        return self.width

    def get_allocated_height(self) -> int:
        return self.height


class FakeGraphDragGesture:
    def __init__(self, start_x: float, start_y: float, state=0) -> None:
        self.start_x = start_x
        self.start_y = start_y
        self.state = state

    def get_start_point(self) -> tuple[bool, float, float]:
        return True, self.start_x, self.start_y

    def get_current_event_state(self):
        return self.state


class FakeGraphController:
    def __init__(self, bands: list[core.EqBand], preamp_db: float = 0.0) -> None:
        self.bands = bands
        self.preamp_db = preamp_db
        self.frequency_updates: list[tuple[int, float]] = []
        self.gain_updates: list[tuple[int, float]] = []
        self.q_updates: list[tuple[int, float]] = []

    def set_band_frequency(self, index: int, frequency: float, *, apply: bool = True) -> bool:
        self.frequency_updates.append((index, frequency))
        if self.bands[index].frequency == frequency:
            return False
        self.bands[index].frequency = frequency
        return True

    def set_band_gain(self, index: int, gain_db: float, *, apply: bool = True) -> bool:
        self.gain_updates.append((index, gain_db))
        if self.bands[index].gain_db == gain_db:
            return False
        self.bands[index].gain_db = gain_db
        return True

    def set_band_q(self, index: int, q_value: float, *, apply: bool = True) -> bool:
        self.q_updates.append((index, q_value))
        if self.bands[index].q == q_value:
            return False
        self.bands[index].q = q_value
        return True


class GraphInteractionWindow(window_graph.MiniEqWindowGraphMixin):
    def __init__(self, bands: list[core.EqBand]) -> None:
        self.controller = FakeGraphController(bands)
        self.graph_area = FakeGraphArea()
        self.visible_band_count = len(bands)
        self.selected_band_index = None
        self.updating_ui = False
        self.drag_band_index = None
        self.drag_start_q = None
        self.drag_start_point_x = None
        self.drag_start_point_y = None
        self.drag_edit_active = False
        self.engine_updates: list[int] = []
        self.ui_updates: list[object] = []

    def select_band(self, index: int) -> None:
        self.selected_band_index = index

    def schedule_band_engine_update(self, index: int) -> None:
        self.engine_updates.append(index)

    def update_band_fader(self, index: int, solo_active: bool | None = None) -> None:
        self.ui_updates.append(("fader", index))

    def update_focus_summary(self) -> None:
        self.ui_updates.append("focus")

    def update_selected_band_editor(self) -> None:
        self.ui_updates.append("editor")

    def invalidate_graph_response_cache(self) -> None:
        self.ui_updates.append("invalidate")

    def queue_response_draw(self) -> None:
        self.ui_updates.append("draw")

    def schedule_curve_metadata_refresh(self) -> None:
        self.ui_updates.append("metadata")

    def band_point(self, index: int) -> tuple[float, float]:
        width = self.graph_area.get_allocated_width()
        height = self.graph_area.get_allocated_height()
        width_f, height_f, left, right, top, bottom = self.graph_plot_bounds(width, height)
        band = self.controller.bands[index]
        x = self.frequency_to_x(band.frequency, width_f, left, right)
        y = self.db_to_y(
            window_graph.total_response_db(
                self.controller.bands,
                self.controller.preamp_db,
                core.SAMPLE_RATE,
                band.frequency,
            ),
            height_f,
            top,
            bottom,
        )
        return x, y


class FocusSummaryWindow(window_graph.MiniEqWindowGraphMixin):
    def __init__(
        self,
        *,
        route_active: bool,
        selected_band_index: int | None = 0,
        controller_routed: bool | None = None,
        eq_enabled: bool = True,
    ) -> None:
        self.selected_band_index = selected_band_index
        controller_state = {
            "bands": [core.EqBand(core.FILTER_TYPES["Bell"], 32.0, gain_db=1.8)],
            "eq_enabled": eq_enabled,
        }
        if controller_routed is not None:
            controller_state["routed"] = controller_routed
        self.controller = type("Controller", (), controller_state)()
        self.route_switch = FakeSwitch(route_active)
        self.bypass_switch = FakeSwitch(False)
        self.focus_label = FakeLabel()
        self.band_count_label = FakeLabel()
        self.inspector_summary_label = FakeLabel()


class SelectedBandEditorWindow(window_graph.MiniEqWindowGraphMixin):
    def __init__(self, selected_band_index: int | None) -> None:
        self.selected_band_index = selected_band_index
        self.controller = SimpleNamespace(
            bands=[
                core.EqBand(core.FILTER_TYPES["Bell"], 1000.0, gain_db=2.5),
            ]
        )
        self.selected_band_label = FakeLabel()
        self.selected_band_state_box = FakeControl()
        self.selected_band_type_box = FakeControl()
        self.selected_band_frequency_box = FakeControl()
        self.selected_band_q_box = FakeControl()
        self.selected_band_gain_box = FakeControl()
        self.selected_band_type_combo = FakeDropDown()
        self.selected_band_frequency_spin = FakeSpin()
        self.selected_band_q_spin = FakeSpin()
        self.selected_band_gain_spin = FakeSpin()
        self.selected_band_mute_button = FakeToggle()
        self.selected_band_solo_button = FakeToggle()

    def editor_groups(self) -> list[FakeControl]:
        return [
            self.selected_band_state_box,
            self.selected_band_type_box,
            self.selected_band_frequency_box,
            self.selected_band_q_box,
            self.selected_band_gain_box,
        ]

    def editor_controls(self) -> list[FakeControl]:
        return [
            self.selected_band_type_combo,
            self.selected_band_frequency_spin,
            self.selected_band_q_spin,
            self.selected_band_gain_spin,
            self.selected_band_mute_button,
            self.selected_band_solo_button,
        ]


def test_filter_type_label_handles_non_contiguous_filter_values() -> None:
    assert window_graph.filter_type_label(core.FILTER_TYPES["Allpass"]) == "Allpass"
    assert window_graph.filter_type_label(core.FILTER_TYPES["Bandpass"]) == "Bandpass"


def test_focus_summary_keeps_selected_band_visible_when_system_eq_is_off() -> None:
    window = FocusSummaryWindow(route_active=False)

    window.update_focus_summary()

    assert window.focus_label.text == "Band 1 • 32 • +1.8 dB"
    assert window.band_count_label.text == "Bell"
    assert window.band_count_label.visible is True
    assert "System-wide EQ is off." in window.focus_label.tooltip


def test_focus_summary_uses_controller_route_state_over_stale_switch() -> None:
    window = FocusSummaryWindow(route_active=False, controller_routed=True)

    window.update_focus_summary()

    assert "System-wide EQ is off." not in window.focus_label.tooltip


def test_compare_switch_uses_controller_route_state_over_stale_switch() -> None:
    window = FocusSummaryWindow(route_active=False, controller_routed=True, eq_enabled=True)

    window.update_eq_power_indicator()

    assert window.bypass_switch.sensitive is True
    assert window.bypass_switch.tooltip == "A/B Compare: equalized audio is playing"


def test_focus_summary_handles_no_selected_band() -> None:
    window = FocusSummaryWindow(route_active=True, selected_band_index=None)

    window.update_focus_summary()

    assert window.focus_label.text == "No band selected"
    assert window.band_count_label.visible is False
    assert window.inspector_summary_label.text == "No Band"


def test_selected_band_editor_keeps_parameter_space_visible_without_selection() -> None:
    window = SelectedBandEditorWindow(selected_band_index=None)
    window.selected_band_type_combo.selected = 1
    window.selected_band_frequency_spin.value = 640.0
    window.selected_band_q_spin.value = 1.4
    window.selected_band_gain_spin.value = -3.0
    window.selected_band_mute_button.active = True
    window.selected_band_solo_button.active = True

    window.update_selected_band_editor()

    assert window.selected_band_label.text == "No Band"
    assert window.selected_band_label.tooltip == "No band selected"
    assert all(group.visible for group in window.editor_groups())
    assert all(not control.sensitive for control in window.editor_controls())
    assert window.selected_band_type_combo.selected == core.FILTER_TYPE_INDEX_BY_VALUE[core.FILTER_TYPES["Off"]]
    assert window.selected_band_frequency_spin.value == window_graph.SELECTED_BAND_PLACEHOLDER_FREQUENCY_HZ
    assert window.selected_band_q_spin.value == core.DEFAULT_BAND_Q
    assert window.selected_band_gain_spin.value == 0.0
    assert window.selected_band_mute_button.active is False
    assert window.selected_band_solo_button.active is False


def test_selected_band_editor_enables_parameter_controls_after_selection() -> None:
    window = SelectedBandEditorWindow(selected_band_index=0)

    window.update_selected_band_editor()

    assert window.selected_band_label.text == "Band 1"
    assert all(group.visible for group in window.editor_groups())
    assert all(control.sensitive for control in window.editor_controls())
    assert window.selected_band_frequency_spin.value == 1000.0
    assert window.selected_band_gain_spin.value == 2.5


def test_preamp_change_refreshes_preset_metadata() -> None:
    calls: list[object] = []
    controller = SimpleNamespace(set_preamp_db=lambda value: calls.append(("preamp", value)))
    test_window = SimpleNamespace(
        updating_ui=False,
        preamp_label=FakeLabel(),
        controller=controller,
        invalidate_graph_response_cache=lambda: calls.append("invalidate"),
        queue_response_draw=lambda: calls.append("draw"),
        schedule_curve_metadata_refresh=lambda: calls.append("metadata"),
    )

    window_graph.MiniEqWindowGraphMixin.on_preamp_changed(test_window, FakeScale(-3.5))

    assert test_window.preamp_label.text == "-3.5 dB"
    assert calls == [("preamp", -3.5), "invalidate", "draw", "metadata"]


def test_curve_metadata_refresh_updates_preset_state_immediately(monkeypatch) -> None:
    calls: list[object] = []
    test_window = SimpleNamespace(
        curve_metadata_refresh_source_id=0,
        ui_shutting_down=False,
        update_preset_state=lambda: calls.append("preset-state"),
        on_curve_metadata_refresh_idle=lambda: False,
    )
    monkeypatch.setattr(
        window_graph.GLib,
        "idle_add",
        lambda callback: calls.append(("idle", callback)) or 42,
    )

    window_graph.MiniEqWindowGraphMixin.schedule_curve_metadata_refresh(test_window)

    assert calls == [("preset-state"), ("idle", test_window.on_curve_metadata_refresh_idle)]
    assert test_window.curve_metadata_refresh_source_id == 42


def test_curve_metadata_refresh_updates_preset_state_with_pending_idle(monkeypatch) -> None:
    calls: list[object] = []
    test_window = SimpleNamespace(
        curve_metadata_refresh_source_id=42,
        ui_shutting_down=False,
        update_preset_state=lambda: calls.append("preset-state"),
        on_curve_metadata_refresh_idle=lambda: False,
    )
    monkeypatch.setattr(window_graph.GLib, "idle_add", lambda _callback: calls.append("unexpected-idle"))

    window_graph.MiniEqWindowGraphMixin.schedule_curve_metadata_refresh(test_window)

    assert calls == ["preset-state"]
    assert test_window.curve_metadata_refresh_source_id == 42


def test_curve_metadata_refresh_idle_notifies_control_clients() -> None:
    calls: list[str] = []
    test_window = SimpleNamespace(
        curve_metadata_refresh_source_id=42,
        ui_shutting_down=False,
        update_status_summary=lambda: calls.append("status"),
        update_preset_state=lambda: calls.append("preset-state"),
        notify_control_state_changed=lambda: calls.append("control-state"),
    )

    keep_source = window_graph.MiniEqWindowGraphMixin.on_curve_metadata_refresh_idle(test_window)

    assert keep_source is False
    assert test_window.curve_metadata_refresh_source_id == 0
    assert calls == ["status", "preset-state", "control-state"]


def test_graph_press_uses_shared_plot_bounds_for_frequency_mapping() -> None:
    window = GraphInteractionWindow(
        [
            core.EqBand(core.FILTER_TYPES["Bell"], 100.0),
            core.EqBand(core.FILTER_TYPES["Bell"], 1000.0),
        ]
    )
    calls: list[tuple[float, float, float, float]] = []

    def graph_plot_bounds(width: int, height: int) -> tuple[float, float, float, float, float, float]:
        assert (width, height) == (640, 240)
        return 640.0, 240.0, 11.0, 77.0, 13.0, 17.0

    def x_to_frequency(x: float, width: float, left: float, right: float) -> float:
        calls.append((x, width, left, right))
        return 1000.0

    window.graph_plot_bounds = graph_plot_bounds
    window.x_to_frequency = x_to_frequency

    window.on_graph_pressed(None, 1, 240.0, 120.0)

    assert calls == [(240.0, 640.0, 11.0, 77.0)]
    assert window.selected_band_index == 1


def test_graph_zero_offset_drag_selects_without_modifying_band() -> None:
    window = GraphInteractionWindow(
        [
            core.EqBand(core.FILTER_TYPES["Bell"], 1000.0, gain_db=3.0),
        ]
    )
    start_x, start_y = window.band_point(0)

    window.on_graph_drag_begin(FakeGraphDragGesture(start_x, start_y), start_x, start_y)
    window.on_graph_drag_update(FakeGraphDragGesture(start_x, start_y), 0.0, 0.0)

    assert window.selected_band_index == 0
    assert window.controller.frequency_updates == []
    assert window.controller.gain_updates == []
    assert window.controller.q_updates == []
    assert window.engine_updates == []
    assert window.ui_updates == []


def test_graph_drag_uses_precision_threshold_before_modifying_band() -> None:
    window = GraphInteractionWindow(
        [
            core.EqBand(core.FILTER_TYPES["Bell"], 1000.0, gain_db=3.0),
        ]
    )
    start_x, start_y = window.band_point(0)

    window.on_graph_drag_begin(FakeGraphDragGesture(start_x, start_y), start_x, start_y)
    window.on_graph_drag_update(FakeGraphDragGesture(start_x, start_y), 1.0, 1.0)

    assert window.drag_edit_active is False
    assert window.controller.frequency_updates == []
    assert window.controller.gain_updates == []
    assert window.engine_updates == []


def test_graph_drag_threshold_only_gates_activation() -> None:
    window = GraphInteractionWindow(
        [
            core.EqBand(core.FILTER_TYPES["Hi-pass"], 1000.0, gain_db=3.0),
        ]
    )
    point_x, point_y = window.band_point(0)

    window.on_graph_drag_begin(FakeGraphDragGesture(point_x, point_y), point_x, point_y)
    window.on_graph_drag_update(FakeGraphDragGesture(point_x, point_y), 2.0, 0.0)
    window.on_graph_drag_update(FakeGraphDragGesture(point_x, point_y), 1.0, 0.0)

    assert window.drag_edit_active is True
    assert len(window.controller.frequency_updates) == 2
    assert window.controller.gain_updates == []


def test_graph_drag_uses_band_point_as_anchor_to_avoid_click_jump() -> None:
    window = GraphInteractionWindow(
        [
            core.EqBand(core.FILTER_TYPES["Hi-pass"], 1000.0, gain_db=3.0),
        ]
    )
    point_x, point_y = window.band_point(0)
    captured_x: list[float] = []

    def x_to_frequency(x: float, _width: float, _left: float, _right: float) -> float:
        captured_x.append(x)
        return 1200.0

    window.x_to_frequency = x_to_frequency

    window.on_graph_drag_begin(FakeGraphDragGesture(point_x + 20.0, point_y), point_x + 20.0, point_y)
    window.on_graph_drag_update(FakeGraphDragGesture(point_x + 20.0, point_y), 10.0, 0.0)

    assert captured_x == [pytest.approx(point_x + 10.0)]
    assert window.controller.frequency_updates == [(0, 1200.0)]
    assert window.controller.gain_updates == []


def test_graph_drag_preserves_solo_context_when_calculating_other_response() -> None:
    window = GraphInteractionWindow(
        [
            core.EqBand(core.FILTER_TYPES["Bell"], 1000.0, gain_db=6.0, solo=True),
            core.EqBand(core.FILTER_TYPES["Bell"], 1000.0, gain_db=6.0),
        ]
    )
    start_x, start_y = window.band_point(0)
    window.drag_band_index = 0
    window.drag_start_q = window.controller.bands[0].q

    window.on_graph_drag_update(FakeGraphDragGesture(start_x, start_y), 12.0, 0.0)

    assert window.controller.gain_updates
    assert window.controller.bands[0].gain_db == pytest.approx(6.0)


def test_graph_drag_does_not_change_gain_for_non_gain_filters() -> None:
    window = GraphInteractionWindow(
        [
            core.EqBand(core.FILTER_TYPES["Hi-pass"], 1000.0, gain_db=3.0),
        ]
    )
    start_x, start_y = window.band_point(0)
    window.drag_band_index = 0
    window.drag_start_q = window.controller.bands[0].q

    window.on_graph_drag_update(FakeGraphDragGesture(start_x, start_y), 40.0, 80.0)

    assert window.controller.frequency_updates
    assert window.controller.gain_updates == []
    assert window.controller.bands[0].gain_db == 3.0


def test_graph_shift_drag_changes_q_without_changing_frequency_or_gain() -> None:
    window = GraphInteractionWindow(
        [
            core.EqBand(core.FILTER_TYPES["Bell"], 1000.0, gain_db=3.0, q=1.0),
        ]
    )
    start_x, start_y = window.band_point(0)
    window.drag_band_index = 0
    window.drag_start_q = 1.0

    window.on_graph_drag_update(
        FakeGraphDragGesture(start_x, start_y, window_graph.Gdk.ModifierType.SHIFT_MASK),
        90.0,
        -100.0,
    )

    assert window.controller.frequency_updates == []
    assert window.controller.gain_updates == []
    assert window.controller.q_updates == [(0, pytest.approx(1.5))]
    assert window.controller.bands[0].frequency == 1000.0
    assert window.controller.bands[0].gain_db == 3.0
    assert window.controller.bands[0].q == pytest.approx(1.5)
