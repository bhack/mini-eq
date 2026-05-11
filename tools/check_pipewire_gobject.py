from __future__ import annotations

import argparse
import sys

from mini_eq.pipewire_backend import build_props_controls_param

REQUIRED_PWG_SYMBOLS = (
    "Core.new",
    "Core.load_module",
    "Core.set_pipewire_property",
    "Core.sync",
    "Device.enum_all_params",
    "Device.enum_params",
    "Device.enum_params_sync",
    "Device.new",
    "Device.sync",
    "Global.dup_property",
    "get_library_version",
    "LinkInfo.get_feedback",
    "LinkInfo.get_id",
    "LinkInfo.get_passive",
    "LinkInfo.new_from_global",
    "Metadata.new",
    "Metadata.set",
    "Metadata.sync",
    "Node.new",
    "Node.set_param",
    "Node.sync",
    "Param.new_props_controls",
    "Registry.new",
    "Registry.dup_globals_by_interface",
    "Registry.sync",
    "RouteInfo.new_from_param",
    "Stream.new_audio_capture",
    "Stream.set_deliver_audio_blocks",
    "Stream.set_pipewire_property",
)


def resolve_symbol(root, dotted_name: str):
    value = root
    for part in dotted_name.split("."):
        value = getattr(value, part)
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check pipewire-gobject symbols used by Mini EQ.")
    parser.add_argument("--expect-version", help="fail unless the loaded Pwg library reports this version")
    args = parser.parse_args(argv)

    try:
        import gi
        import pipewire_gobject  # noqa: F401

        gi.require_version("Pwg", "0.1")
        from gi.repository import GLib, Pwg
    except Exception as exc:
        print(f"failed to import pipewire-gobject/Pwg: {exc}", file=sys.stderr)
        return 1

    Pwg.init()
    try:
        actual_version = str(Pwg.get_library_version())
    except Exception as exc:
        print(f"failed to read Pwg library version: {exc}", file=sys.stderr)
        return 1
    if args.expect_version and actual_version != args.expect_version:
        print(f"expected Pwg {args.expect_version}, got Pwg {actual_version}", file=sys.stderr)
        return 1

    missing: list[str] = []
    for symbol in REQUIRED_PWG_SYMBOLS:
        try:
            resolve_symbol(Pwg, symbol)
        except Exception as exc:
            missing.append(f"{symbol}: {exc}")

    if missing:
        print(f"Pwg {actual_version} is missing symbols required by Mini EQ:", file=sys.stderr)
        for item in missing:
            print(f"  {item}", file=sys.stderr)
        return 1

    core = Pwg.Core.new()
    props_param = build_props_controls_param(Pwg, GLib, {"eq:enabled": 1.0, "eq:g_out": 0.0})
    stream = Pwg.Stream.new_audio_capture("alsa_output.test", True)

    for label, value in (
        ("core", core),
        ("Props controls param", props_param),
        ("monitor capture stream", stream),
    ):
        if value is None:
            print(f"failed to construct {label}", file=sys.stderr)
            return 1

    print(f"Pwg {actual_version} exposes the Mini EQ pipewire-gobject surface.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
