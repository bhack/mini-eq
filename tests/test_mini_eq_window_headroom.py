from __future__ import annotations

import pytest

from tests._mini_eq_imports import import_mini_eq_module

window_headroom = import_mini_eq_module("window_headroom")


def test_headroom_meter_red_range_leaves_preamp_correction_margin_visible() -> None:
    assert window_headroom.headroom_meter_norm(0.0) == pytest.approx(1.0 / 3.0)
    assert window_headroom.headroom_meter_norm(6.0) == pytest.approx(0.5)
    assert window_headroom.headroom_meter_norm(24.0) == pytest.approx(1.0)


def test_headroom_meter_clamps_out_of_range_peaks() -> None:
    assert window_headroom.headroom_meter_norm(-48.0) == 0.0
    assert window_headroom.headroom_meter_norm(48.0) == 1.0


def test_format_headroom_peak_marks_values_above_meter_range() -> None:
    assert window_headroom.format_headroom_peak_db(24.0) == "+24.0 dB"
    assert window_headroom.format_headroom_peak_db(24.1) == ">+24 dB"
    assert window_headroom.format_headroom_peak_db(48.0) == ">+24 dB"


def test_format_headroom_peak_keeps_safe_margin_positive_text() -> None:
    assert window_headroom.format_headroom_peak_db(-6.5) == "6.5 dB"
    assert window_headroom.format_headroom_peak_db(-48.0) == "<12 dB"
