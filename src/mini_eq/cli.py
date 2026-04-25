from __future__ import annotations

import argparse


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="System-wide parametric EQ using GTK, WirePlumber routing and PipeWire filter-chain.",
    )
    parser.add_argument(
        "--install-desktop",
        action="store_true",
        help="install the desktop launcher and app icon for the current user, then exit",
    )
    parser.add_argument(
        "--check-deps",
        action="store_true",
        help="check Mini EQ runtime dependencies and exit",
    )
    parser.add_argument(
        "--auto-route",
        action="store_true",
        help="route current and future output streams to the virtual sink on startup",
    )
    parser.add_argument(
        "--output-sink",
        help="explicit PipeWire Audio/Sink node.name for the processed output",
    )
    parser.add_argument(
        "--import-apo",
        help="load an Equalizer APO preset file at startup",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="run without the GTK window",
    )
    parser.add_argument(
        "--duration",
        type=float,
        help="exit automatically after N seconds when running headless",
    )
    args = parser.parse_args(argv)

    return args
