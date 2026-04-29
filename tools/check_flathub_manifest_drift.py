#!/usr/bin/env python3
from __future__ import annotations

import argparse
import difflib
import sys
from pathlib import Path

SOURCE_SENTINEL = [
    "    sources:\n",
    "      - <mini-eq-source-intentionally-different>\n",
]


def mini_eq_source_block(lines: list[str], path: Path) -> tuple[int, int, list[str]]:
    try:
        module_start = lines.index("  - name: mini-eq\n")
    except ValueError as exc:
        raise ValueError(f"{path}: missing mini-eq module") from exc

    try:
        source_start = next(index for index in range(module_start + 1, len(lines)) if lines[index] == "    sources:\n")
    except StopIteration as exc:
        raise ValueError(f"{path}: missing mini-eq sources block") from exc

    source_end = len(lines)
    for index in range(source_start + 1, len(lines)):
        if lines[index].startswith("  - "):
            source_end = index
            break

    return source_start, source_end, lines[source_start:source_end]


def normalize_manifest(path: Path) -> tuple[list[str], list[str]]:
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    source_start, source_end, source_block = mini_eq_source_block(lines, path)
    return lines[:source_start] + SOURCE_SENTINEL + lines[source_end:], source_block


def assert_source_kind(path: Path, source_block: list[str], expected: str) -> None:
    source_text = "".join(source_block)
    if expected == "local" and "type: dir" in source_text and "path: ." in source_text:
        return
    if expected == "archive" and "type: archive" in source_text and "url:" in source_text and "sha256:" in source_text:
        return
    raise ValueError(f"{path}: mini-eq source block is not the expected {expected} source")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare the upstream and Flathub manifests while allowing the Mini EQ source stanza to differ.",
    )
    parser.add_argument(
        "upstream_manifest",
        nargs="?",
        type=Path,
        default=Path("io.github.bhack.mini-eq.yaml"),
    )
    parser.add_argument(
        "flathub_manifest",
        nargs="?",
        type=Path,
        default=Path("../io.github.bhack.mini-eq/io.github.bhack.mini-eq.yaml"),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)

    try:
        upstream, upstream_source = normalize_manifest(args.upstream_manifest)
        flathub, flathub_source = normalize_manifest(args.flathub_manifest)
        assert_source_kind(args.upstream_manifest, upstream_source, "local")
        assert_source_kind(args.flathub_manifest, flathub_source, "archive")
    except OSError as exc:
        print(exc, file=sys.stderr)
        return 2
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2

    if upstream != flathub:
        diff = difflib.unified_diff(
            upstream,
            flathub,
            fromfile=str(args.upstream_manifest),
            tofile=str(args.flathub_manifest),
        )
        sys.stdout.writelines(diff)
        return 1

    print("Flatpak manifests match outside the expected Mini EQ source stanza.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
