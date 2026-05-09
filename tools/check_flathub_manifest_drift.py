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
SYNCED_SIBLING_FILES = ("python3-dependencies.yaml",)


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


def file_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines(keepends=True)


def sibling_file_diffs(upstream_manifest: Path, flathub_manifest: Path) -> list[str]:
    diffs: list[str] = []
    for relative_path in SYNCED_SIBLING_FILES:
        upstream_file = upstream_manifest.parent / relative_path
        flathub_file = flathub_manifest.parent / relative_path
        upstream_lines = file_lines(upstream_file)
        flathub_lines = file_lines(flathub_file)
        if upstream_lines == flathub_lines:
            continue
        diffs.extend(
            difflib.unified_diff(
                upstream_lines,
                flathub_lines,
                fromfile=str(upstream_file),
                tofile=str(flathub_file),
            )
        )
    return diffs


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare the upstream and Flathub manifests while allowing the Mini EQ source stanza to differ.",
    )
    parser.add_argument(
        "upstream_manifest",
        type=Path,
        help="Path to the upstream development manifest.",
    )
    parser.add_argument(
        "flathub_manifest",
        type=Path,
        help="Path to the Flathub publishing manifest.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)

    try:
        upstream, upstream_source = normalize_manifest(args.upstream_manifest)
        flathub, flathub_source = normalize_manifest(args.flathub_manifest)
        assert_source_kind(args.upstream_manifest, upstream_source, "local")
        assert_source_kind(args.flathub_manifest, flathub_source, "archive")
        diffs = sibling_file_diffs(args.upstream_manifest, args.flathub_manifest)
    except OSError as exc:
        print(exc, file=sys.stderr)
        return 2
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2

    if upstream != flathub:
        diffs.extend(
            difflib.unified_diff(
                upstream,
                flathub,
                fromfile=str(args.upstream_manifest),
                tofile=str(args.flathub_manifest),
            )
        )

    if diffs:
        sys.stdout.writelines(diffs)
        return 1

    print("Flatpak manifests and dependency files match outside the expected Mini EQ source stanza.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
