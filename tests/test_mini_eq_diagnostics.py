from __future__ import annotations

import json
from types import SimpleNamespace

from tests._mini_eq_imports import import_mini_eq_module

diagnostics = import_mini_eq_module("diagnostics")


def test_startup_trace_is_disabled_by_default(monkeypatch, tmp_path) -> None:
    trace_path = tmp_path / "state" / "mini-eq" / "startup-trace.log"
    monkeypatch.delenv(diagnostics.STARTUP_TRACE_ENV, raising=False)
    monkeypatch.setattr(diagnostics, "startup_trace_path", lambda: trace_path)

    diagnostics.trace_startup_event("startup-ready-begin", output_sink="speakers")

    assert not trace_path.exists()


def test_startup_trace_writes_json_lines_when_enabled(monkeypatch, tmp_path) -> None:
    trace_path = tmp_path / "state" / "mini-eq" / "startup-trace.log"
    monkeypatch.setenv(diagnostics.STARTUP_TRACE_ENV, "1")
    monkeypatch.setattr(diagnostics, "startup_trace_path", lambda: trace_path)

    diagnostics.trace_startup_event(
        "output-preset-apply-start",
        output_sink="speakers",
        target_keys=("route-key", "speakers"),
    )

    record = json.loads(trace_path.read_text(encoding="utf-8"))
    assert record["event"] == "output-preset-apply-start"
    assert record["output_sink"] == "speakers"
    assert record["target_keys"] == ["route-key", "speakers"]
    assert record["timestamp"].endswith("Z")


def test_describe_output_preset_target_records_route_identity() -> None:
    route = SimpleNamespace(
        description="Speakers",
        device_name="alsa_card.test",
        name="analog-output-speaker",
        output_preset_key="pipewire-route:v1:speakers",
        route_device=11,
    )
    target = SimpleNamespace(
        device_name="alsa_card.test",
        output_key="alsa_output.speakers",
        route=route,
        route_device=11,
        keys=("pipewire-route:v1:speakers", "alsa_output.speakers"),
        link_key="pipewire-route:v1:speakers",
        has_route_key=True,
    )

    description = diagnostics.describe_output_preset_target(target)

    assert description == {
        "device_name": "alsa_card.test",
        "has_route_key": True,
        "keys": ["pipewire-route:v1:speakers", "alsa_output.speakers"],
        "link_key": "pipewire-route:v1:speakers",
        "output_key": "alsa_output.speakers",
        "route": {
            "description": "Speakers",
            "device_name": "alsa_card.test",
            "name": "analog-output-speaker",
            "output_preset_key": "pipewire-route:v1:speakers",
            "route_device": 11,
        },
        "route_device": 11,
    }
