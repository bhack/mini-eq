from __future__ import annotations

from types import SimpleNamespace

from tests._mini_eq_imports import import_mini_eq_module

band_fader = import_mini_eq_module("band_fader")


class FakeDragGesture:
    def __init__(self, start_x: float = 12.0, start_y: float = 80.0, state=0) -> None:
        self.start_x = start_x
        self.start_y = start_y
        self.state = state

    def get_start_point(self) -> tuple[bool, float, float]:
        return True, self.start_x, self.start_y

    def get_current_event_state(self):
        return self.state


def make_fader(gain_db: float = 0.0):
    selected: list[int] = []
    gains: list[tuple[int, float]] = []
    activated: list[int] = []
    fader = band_fader.EqBandFader.__new__(band_fader.EqBandFader)
    fader.index = 2
    fader.select_callback = selected.append
    fader.gain_changed_callback = lambda index, gain: gains.append((index, gain))
    fader.activate_callback = activated.append
    fader.gain_db = gain_db
    fader.grab_focus = lambda: None
    fader.queue_draw = lambda: None
    fader.get_allocated_height = lambda: 220
    fader.dragging_gain = False
    fader.drag_start_gain_db = gain_db
    return fader, selected, gains, activated


def test_band_fader_gain_geometry_clamps_to_slider_range() -> None:
    fader, _selected, _gains, _activated = make_fader()

    assert fader.gain_to_y(band_fader.GAIN_MAX_DB + 12.0, 10.0, 210.0) == 10.0
    assert fader.gain_to_y(band_fader.GAIN_MIN_DB - 12.0, 10.0, 210.0) == 210.0
    assert fader.gain_to_y(0.0, 10.0, 210.0) == 110.0
    assert fader.track_bounds(160.0) == (56.0, 128.0)
    assert fader.track_bounds(220.0) == (56.0, 176.0)


def test_band_fader_compact_labels_fit_small_tiles() -> None:
    fader, _selected, _gains, _activated = make_fader()
    fader.frequency = 1200.0
    fader.q_value = 0.707
    fader.filter_type_label = "Hi-pass"

    assert fader.selected_frequency_label() == "1.2 kHz"
    assert fader.compact_filter_type_label() == "HP"
    assert fader.compact_q_label() == "0.71"
    assert fader.show_q_in_tile(169.0) is False
    assert fader.show_q_in_tile(170.0) is True


def test_band_fader_accessible_range_values_are_doubles() -> None:
    fader, _selected, _gains, _activated = make_fader(gain_db=-4)
    fader.frequency_label = "32 Hz"
    fader.filter_type_label = "Bell"
    fader.q_label = "0.80"
    fader.selected = False
    fader.active = True
    fader.muted = False
    fader.soloed = False
    fader.solo_active = False
    captured = {}

    def update_property(properties, values) -> None:
        captured["properties"] = properties
        captured["values"] = values

    fader.update_property = update_property
    fader.update_state = lambda _states, _values: None

    fader.update_accessible_state()

    values = captured["values"]
    assert isinstance(values[2], float)
    assert isinstance(values[3], float)
    assert isinstance(values[4], float)
    assert values[4] == -4.0


def test_band_fader_keyboard_steps_select_and_clamp_gain() -> None:
    fader, selected, gains, activated = make_fader(gain_db=19.8)

    assert fader.on_key_pressed(None, band_fader.Gdk.KEY_Up, 0, band_fader.Gdk.ModifierType(0)) is True
    assert selected == [2]
    assert gains == [(2, 20.0)]

    fader.gain_db = 1.0
    assert fader.on_key_pressed(None, band_fader.Gdk.KEY_Down, 0, band_fader.Gdk.ModifierType.SHIFT_MASK) is True
    assert gains[-1] == (2, 0.9)

    assert fader.on_key_pressed(None, band_fader.Gdk.KEY_Page_Up, 0, band_fader.Gdk.ModifierType.SHIFT_MASK) is True
    assert gains[-1] == (2, 4.0)

    fader.gain_db = 4.0
    assert fader.on_key_pressed(None, band_fader.Gdk.KEY_Home, 0, band_fader.Gdk.ModifierType(0)) is True
    assert gains[-1] == (2, 0.0)

    assert fader.on_key_pressed(None, band_fader.Gdk.KEY_Return, 0, band_fader.Gdk.ModifierType(0)) is True
    assert activated == [2]

    assert fader.on_key_pressed(None, band_fader.Gdk.KEY_Escape, 0, band_fader.Gdk.ModifierType(0)) is False


def test_band_fader_scroll_uses_modifier_steps() -> None:
    fader, selected, gains, _activated = make_fader(gain_db=0.0)

    controller = SimpleNamespace(get_current_event_state=lambda: band_fader.Gdk.ModifierType.CONTROL_MASK)

    assert fader.on_scroll(controller, 0.0, -1.0) is True
    assert selected == [2]
    assert gains == [(2, 3.0)]

    fader.gain_db = 3.0
    assert fader.on_scroll(controller, 0.0, 1.0) is True
    assert gains[-1] == (2, 0.0)

    assert fader.on_scroll(controller, 0.0, 0.0) is False


def test_band_fader_drag_uses_precision_threshold_before_gain_change() -> None:
    fader, selected, gains, _activated = make_fader(gain_db=0.0)
    gesture = FakeDragGesture()

    fader.on_drag_begin(gesture, 12.0, 80.0)
    fader.on_drag_update(gesture, 1.0, 1.0)

    assert selected == [2]
    assert fader.dragging_gain is False
    assert gains == []


def test_band_fader_drag_threshold_only_gates_activation() -> None:
    fader, _selected, gains, _activated = make_fader(gain_db=0.0)
    gesture = FakeDragGesture()

    fader.on_drag_begin(gesture, 12.0, 80.0)
    fader.on_drag_update(gesture, 2.0, 10.0)
    fader.on_drag_update(gesture, 1.0, 1.0)

    assert fader.dragging_gain is True
    assert gains == [(2, -3.3), (2, -0.3)]
