#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
from dataclasses import dataclass
from pathlib import Path

try:
    from tools.release_gates import FLATPAK_RUNTIME_REVIEW_PATHS
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    from release_gates import FLATPAK_RUNTIME_REVIEW_PATHS

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class RuntimeGate:
    required: bool
    base_tag: str | None
    changes: tuple[str, ...]
    reason: str


def str_to_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise argparse.ArgumentTypeError(f"expected a boolean value, got {value!r}")


def git_stdout(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        stdout=subprocess.PIPE,
        text=True,
    )
    return result.stdout.strip()


def previous_release_tag(root: Path, current_tag: str | None) -> str | None:
    tags = git_stdout(root, "tag", "--list", "v[0-9]*", "--sort=-v:refname").splitlines()
    for tag in tags:
        if tag != current_tag:
            return tag
    return None


def changed_runtime_paths(root: Path, base_tag: str) -> tuple[str, ...]:
    paths = [path.as_posix() for path in FLATPAK_RUNTIME_REVIEW_PATHS]
    output = git_stdout(root, "diff", "--name-only", f"{base_tag}..HEAD", "--", *paths)
    return tuple(line for line in output.splitlines() if line)


def flatpak_runtime_gate(
    root: Path,
    *,
    current_tag: str | None,
    release_requested: bool,
    force: bool,
) -> RuntimeGate:
    base_tag = previous_release_tag(root, current_tag)
    changes = changed_runtime_paths(root, base_tag) if base_tag is not None else ()

    if force:
        return RuntimeGate(True, base_tag, changes, "forced by dispatch input")

    if not release_requested:
        return RuntimeGate(False, None, (), "dry-run/package-only dispatch")

    if base_tag is None:
        return RuntimeGate(True, None, (), "no previous release tag")

    if changes:
        return RuntimeGate(True, base_tag, changes, "runtime-sensitive changes")

    return RuntimeGate(False, base_tag, (), "runtime integration unchanged")


def append_github_output(path: Path, gate: RuntimeGate) -> None:
    with path.open("a", encoding="utf-8") as output:
        output.write(f"required={str(gate.required).lower()}\n")
        output.write(f"base_tag={gate.base_tag or ''}\n")


def append_github_summary(path: Path, gate: RuntimeGate) -> None:
    lines = [
        "### Flatpak runtime smoke gate",
        "",
        f"- base tag: `{gate.base_tag or 'none'}`",
        f"- required: `{str(gate.required).lower()}`",
        f"- reason: {gate.reason}",
    ]
    if gate.changes:
        lines.extend(["", "Runtime-sensitive changes:"])
        lines.extend(f"- `{change}`" for change in gate.changes)

    with path.open("a", encoding="utf-8") as summary:
        summary.write("\n".join(lines))
        summary.write("\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Decide whether release dispatch must run Flatpak runtime smoke.")
    parser.add_argument("--root", type=Path, default=ROOT, help="repository root; defaults to this checkout")
    parser.add_argument("--tag", default="", help="current release tag, for example v0.7.4")
    parser.add_argument("--release-requested", type=str_to_bool, required=True)
    parser.add_argument("--force", type=str_to_bool, default=False)
    parser.add_argument("--github-output", type=Path, help="optional GitHub Actions output file")
    parser.add_argument("--github-summary", type=Path, help="optional GitHub Actions summary file")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    gate = flatpak_runtime_gate(
        args.root.resolve(),
        current_tag=args.tag or None,
        release_requested=args.release_requested,
        force=args.force,
    )

    print(f"required={str(gate.required).lower()}")
    print(f"base_tag={gate.base_tag or ''}")
    print(f"reason={gate.reason}")
    for change in gate.changes:
        print(f"change={change}")

    if args.github_output is not None:
        append_github_output(args.github_output, gate)
    if args.github_summary is not None:
        append_github_summary(args.github_summary, gate)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
