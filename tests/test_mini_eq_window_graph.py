from __future__ import annotations

from tests._mini_eq_imports import import_mini_eq_module

core = import_mini_eq_module("core")
window_graph = import_mini_eq_module("window_graph")


def test_filter_type_label_handles_non_contiguous_filter_values() -> None:
    assert window_graph.filter_type_label(core.FILTER_TYPES["Allpass"]) == "Allpass"
    assert window_graph.filter_type_label(core.FILTER_TYPES["Bandpass"]) == "Bandpass"
