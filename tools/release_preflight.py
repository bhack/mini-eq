#!/usr/bin/env python3
from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEAK_PATTERN = r"(/home/|/Users/|secret|token|api[_-]?key|github_pat|BEGIN (RSA|OPENSSH|PRIVATE) KEY)"
ALLOWED_LEAK_MATCHES = ("${{ github.token }}", "id-token: write")
EXTENSION_SOURCE_DIR = ROOT / "extensions" / "gnome-shell" / "mini-eq@bhack.github.io"


def format_command(command: list[str | Path]) -> str:
    return " ".join(shlex.quote(str(part)) for part in command)


def run(command: list[str | Path], *, cwd: Path = ROOT) -> None:
    print(f"\n$ {format_command(command)}", flush=True)
    subprocess.run([str(part) for part in command], cwd=cwd, check=True)


def git_stdout(*args: str | Path) -> str:
    result = subprocess.run(
        ["git", *(str(arg) for arg in args)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def require_tools(*tools: str) -> None:
    missing = [tool for tool in tools if shutil.which(tool) is None]
    if missing:
        raise SystemExit(f"Missing required release tool(s): {', '.join(missing)}")


def current_release_tag() -> str:
    with (ROOT / "pyproject.toml").open("rb") as pyproject_file:
        project = tomllib.load(pyproject_file)["project"]
    return f"v{project['version']}"


def git_tag_exists(tag: str) -> bool:
    result = subprocess.run(
        ["git", "rev-parse", "-q", "--verify", f"refs/tags/{tag}"],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


def extension_comparison_base_tag() -> str | None:
    current_tag = current_release_tag()
    if git_tag_exists(current_tag):
        return current_tag

    tags = git_stdout("tag", "--list", "v[0-9]*", "--sort=-v:refname").splitlines()
    return tags[0] if tags else None


def run_gnome_shell_extension_upload_notice() -> None:
    base_tag = extension_comparison_base_tag()
    if base_tag is None:
        print("\nGNOME Shell extension upload notice skipped; no release tag found.")
        return

    extension_path = EXTENSION_SOURCE_DIR.relative_to(ROOT)
    committed_changes = git_stdout("diff", "--name-only", f"{base_tag}..HEAD", "--", extension_path).splitlines()
    worktree_changes = git_stdout("status", "--short", "--", extension_path).splitlines()

    if not committed_changes and not worktree_changes:
        print(f"\nGNOME Shell extension upload not indicated; no publishable extension changes since {base_tag}.")
        return

    print(f"\nGNOME Shell extension upload may be needed; publishable extension source changed since {base_tag}:")
    for path in committed_changes:
        print(f"  {path}")
    for status_line in worktree_changes:
        print(f"  {status_line}")
    print("Build and test the extension zip before uploading it to extensions.gnome.org.")


def run_leak_scan() -> None:
    run(["git", "rev-list", "--count", "HEAD"])
    run(["git", "ls-remote", "--heads", "origin"])
    run(["git", "ls-remote", "--tags", "origin"])

    command = [
        "git",
        "grep",
        "-n",
        "-I",
        "-E",
        LEAK_PATTERN,
        "HEAD",
        "--",
        ".",
        ":(exclude)*.png",
        ":(exclude)AGENTS.md",
        ":(exclude)docs/release.md",
        ":(exclude)tools/release_preflight.py",
    ]
    print(f"\n$ {format_command(command)}", flush=True)
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)

    if result.returncode not in (0, 1):
        sys.stderr.write(result.stderr)
        raise SystemExit(result.returncode)

    matches = result.stdout.splitlines()
    unexpected = [line for line in matches if not any(allowed in line for allowed in ALLOWED_LEAK_MATCHES)]
    if unexpected:
        print("\nUnexpected leak-scan matches:", file=sys.stderr)
        for line in unexpected:
            print(line, file=sys.stderr)
        raise SystemExit(1)

    if matches:
        print("Leak scan found only allowed GitHub Actions token/id-token references.")
    else:
        print("Leak scan found no matches.")


def run_wheel_smoke_test(python: Path, wheel: Path, scratch: Path) -> None:
    venv = scratch / "wheel-test"
    run([python, "-m", "venv", "--system-site-packages", venv])

    bin_dir = venv / ("Scripts" if os.name == "nt" else "bin")
    venv_python = bin_dir / "python"
    mini_eq = bin_dir / ("mini-eq.exe" if os.name == "nt" else "mini-eq")

    run([venv_python, "-m", "pip", "install", "--upgrade", "pip"])
    run([venv_python, "-m", "pip", "install", wheel])
    run([mini_eq, "--check-deps"])
    run([mini_eq, "--help"])


def run_build_checks(python: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="mini-eq-release-preflight-") as temp_dir:
        scratch = Path(temp_dir)
        dist = scratch / "dist"

        run([python, "-m", "build", "--outdir", dist])

        artifacts = sorted(dist.iterdir())
        run([python, "-m", "twine", "check", *artifacts])

        wheels = sorted(dist.glob("*.whl"))
        if not wheels:
            raise SystemExit("Build did not produce a wheel")
        run_wheel_smoke_test(python, wheels[0], scratch)


def run_flathub_drift_check(python: Path) -> None:
    flathub_manifest = ROOT.parent / "io.github.bhack.mini-eq" / "io.github.bhack.mini-eq.yaml"
    if not flathub_manifest.exists():
        print("\nSkipping Flathub manifest drift check; sibling Flathub checkout not found.")
        return

    run(
        [
            python,
            ROOT / "tools/check_flathub_manifest_drift.py",
            ROOT / "io.github.bhack.mini-eq.yaml",
            flathub_manifest,
        ]
    )


def main() -> int:
    python = Path(sys.executable)
    require_tools("appstreamcli", "desktop-file-validate", "git", "gnome-extensions")

    run(["git", "diff", "--check"])
    run([python, "-m", "pytest", "tests/test_version_metadata.py", "-q"])
    run([python, ROOT / "tools/check_gnome_shell_extension.py"])
    run_gnome_shell_extension_upload_notice()
    run([python, "-m", "ruff", "check", "."])
    run([python, "-m", "ruff", "format", "--check", "."])
    run([python, "-m", "pytest", "-q"])
    run([python, "-m", "mini_eq", "--check-deps"])
    run(["appstreamcli", "validate", "--no-net", ROOT / "data/io.github.bhack.mini-eq.metainfo.xml"])
    run(["desktop-file-validate", ROOT / "data/io.github.bhack.mini-eq.desktop"])
    run_build_checks(python)
    run_leak_scan()
    run_flathub_drift_check(python)

    print("\nRelease preflight completed successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
