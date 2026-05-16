from __future__ import annotations

from types import SimpleNamespace

from tests._mini_eq_imports import import_mini_eq_module

band_fader = import_mini_eq_module("band_fader")


def make_fader(gain_db: float = 0.0):
    selected: list[int] = []
    gains: list[tuple[int, float]] = []
    activated: list[int] = []
    fader = band_fader.EqBandFader(
        2,
        selected.append,
        lambda index, gain: gains.append((index, gain)),
        activated.append,
    )
    fader.gain_db = gain_db
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
