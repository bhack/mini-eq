from __future__ import annotations

import argparse
import sys

from mini_eq.wireplumber_backend import WirePlumberBackend, build_spa_params_pod

REQUIRED_WP_SYMBOLS = (
    "InitFlags.PIPEWIRE",
    "InitFlags.SPA_TYPES",
    "Core.new",
    "ObjectManager.new",
    "ObjectInterest.new_type",
    "Properties.new_empty",
    "Node",
    "Metadata",
    "ProxyFeatures.PIPEWIRE_OBJECT_FEATURE_INFO",
    "ProxyFeatures.PROXY_FEATURE_BOUND",
    "PipewireObject.get_property",
    "ImplModule.load",
    "SpaPodBuilder.new_struct",
    "SpaPodBuilder.new_object",
)


def resolve_symbol(root, dotted_name: str):
    value = root
    for part in dotted_name.split("."):
        value = getattr(value, part)
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check WirePlumber GI symbols used by Mini EQ.")
    parser.add_argument("--expect-version", help="fail unless the loaded Wp GI namespace reports this version")
    args = parser.parse_args(argv)

    _glib, _gobject, Wp = WirePlumberBackend._import_wireplumber()
    actual_version = str(getattr(Wp, "_version", "unknown"))

    if args.expect_version and actual_version != args.expect_version:
        print(f"expected Wp {args.expect_version}, got Wp {actual_version}", file=sys.stderr)
        return 1

    missing: list[str] = []
    for symbol in REQUIRED_WP_SYMBOLS:
        try:
            resolve_symbol(Wp, symbol)
        except Exception as exc:
            missing.append(f"{symbol}: {exc}")

    if missing:
        print(f"Wp {actual_version} is missing symbols required by Mini EQ:", file=sys.stderr)
        for item in missing:
            print(f"  {item}", file=sys.stderr)
        return 1

    Wp.init(Wp.InitFlags.PIPEWIRE | Wp.InitFlags.SPA_TYPES)
    backend = WirePlumberBackend()
    core = backend._new_core(Wp)
    node_manager = backend._build_node_manager(Wp)
    metadata_manager = backend._build_metadata_manager(Wp)
    props_pod = build_spa_params_pod(Wp, {"eq:enabled": 1.0, "eq:g_out": 0.0})

    for label, value in (
        ("core", core),
        ("node manager", node_manager),
        ("metadata manager", metadata_manager),
        ("Props pod", props_pod),
    ):
        if value is None:
            print(f"failed to construct {label}", file=sys.stderr)
            return 1

    print(f"Wp {actual_version} exposes the Mini EQ WirePlumber GI surface.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
