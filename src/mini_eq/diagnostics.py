from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

from gi.repository import GLib

STARTUP_TRACE_ENV = "MINI_EQ_STARTUP_TRACE"
STARTUP_TRACE_DIR_NAME = "mini-eq"
STARTUP_TRACE_FILE_NAME = "startup-trace.log"


def startup_trace_enabled() -> bool:
    value = os.environ.get(STARTUP_TRACE_ENV, "")
    return value.strip().lower() not in {"", "0", "false", "no", "off"}


def startup_trace_path() -> Path:
    return Path(GLib.get_user_state_dir()) / STARTUP_TRACE_DIR_NAME / STARTUP_TRACE_FILE_NAME


def describe_output_preset_target(target: object | None) -> dict[str, object] | None:
    if target is None:
        return None

    route = getattr(target, "route", None)
    route_info = None
    if route is not None:
        route_info = {
            "description": _json_safe(getattr(route, "description", None)),
            "device_name": _json_safe(getattr(route, "device_name", None)),
            "name": _json_safe(getattr(route, "name", None)),
            "output_preset_key": _json_safe(getattr(route, "output_preset_key", None)),
            "route_device": _json_safe(getattr(route, "route_device", None)),
        }

    return {
        "has_route_key": bool(getattr(target, "has_route_key", False)),
        "keys": _json_safe(tuple(getattr(target, "keys", ()) or ())),
        "link_key": _json_safe(getattr(target, "link_key", "")),
        "output_key": _json_safe(getattr(target, "output_key", None)),
        "route": route_info,
    }


def describe_output_preset_snapshot(snapshot: object | None) -> dict[str, object] | None:
    if snapshot is None:
        return None

    return {
        "identity": _json_safe(getattr(snapshot, "identity", None)),
        "sink_name": _json_safe(getattr(snapshot, "sink_name", None)),
        "target": describe_output_preset_target(getattr(snapshot, "target", None)),
    }


def describe_output_preset_transition(transition: object | None) -> dict[str, object] | None:
    if transition is None:
        return None

    return {
        "changed": bool(getattr(transition, "changed", False)),
        "current": describe_output_preset_snapshot(getattr(transition, "current", None)),
        "previous": describe_output_preset_snapshot(getattr(transition, "previous", None)),
    }


def trace_startup_event(event: str, **fields: object) -> None:
    if not startup_trace_enabled():
        return

    path = startup_trace_path()
    record = {
        "event": event,
        "timestamp": datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
    }
    record.update({key: _json_safe(value) for key, value in fields.items()})

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as trace_file:
            trace_file.write(json.dumps(record, sort_keys=True, separators=(",", ":")))
            trace_file.write("\n")
    except Exception:
        return


def _json_safe(value: object) -> object:
    if value is None or isinstance(value, str | int | float | bool):
        return value

    if isinstance(value, tuple | list | set):
        return [_json_safe(item) for item in value]

    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}

    return str(value)
