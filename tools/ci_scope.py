#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    from tools.release_gates import CI_SCOPE_LABELS, CI_SCOPE_NAMES, classify_ci_scopes
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    from release_gates import CI_SCOPE_LABELS, CI_SCOPE_NAMES, classify_ci_scopes


def read_paths(path_file: Path) -> list[str]:
    return [line.strip() for line in path_file.read_text(encoding="utf-8").splitlines() if line.strip()]


def all_scopes(value: bool) -> dict[str, bool]:
    return {name: value for name in CI_SCOPE_NAMES}


def write_github_output(path: Path, scopes: dict[str, bool]) -> None:
    with path.open("a", encoding="utf-8") as output:
        for name in CI_SCOPE_NAMES:
            output.write(f"{name}={str(scopes[name]).lower()}\n")


def write_github_summary(path: Path, scopes: dict[str, bool]) -> None:
    lines = ["### CI scope", ""]
    lines.extend(f"- {CI_SCOPE_LABELS[name]}: `{str(scopes[name]).lower()}`" for name in CI_SCOPE_NAMES)
    lines.extend(
        [
            "",
            "Runtime smoke policy:",
            "- Pull request and push CI do not run the PipeWire/Flatpak runtime smokes automatically.",
            "- Use manual CI dispatch inputs for smoke-harness iteration or extra PR signal.",
            "- Release dispatches recompute the runtime gate and block publishing on required Flatpak routing smoke.",
        ]
    )
    with path.open("a", encoding="utf-8") as summary:
        summary.write("\n".join(lines))
        summary.write("\n")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Classify changed files into Mini EQ CI scopes.")
    parser.add_argument("paths", nargs="?", type=Path, help="newline-delimited changed-path file")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--all", action="store_true", help="mark every CI scope as changed")
    group.add_argument("--none", action="store_true", help="mark every CI scope as unchanged")
    parser.add_argument("--github-output", type=Path, help="optional GitHub Actions output file")
    parser.add_argument("--github-summary", type=Path, help="optional GitHub Actions step summary file")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if args.all:
        scopes = all_scopes(True)
    elif args.none:
        scopes = all_scopes(False)
    elif args.paths is not None:
        scopes = classify_ci_scopes(read_paths(args.paths))
    else:
        raise SystemExit("provide a path file, --all, or --none")

    for name in CI_SCOPE_NAMES:
        print(f"{name}={str(scopes[name]).lower()}")

    if args.github_output is not None:
        write_github_output(args.github_output, scopes)
    if args.github_summary is not None:
        write_github_summary(args.github_summary, scopes)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
