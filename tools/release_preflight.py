#!/usr/bin/env python3
from __future__ import annotations

import fnmatch
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEAK_PATTERN = (
    r"(/home/|/Users/|secret|token|api[_-]?key|github_pat|"
    r"gh[pousr]_[A-Za-z0-9_]{20,}|pypi-[A-Za-z0-9_-]{20,}|sk-[A-Za-z0-9_-]{20,}|"
    r"AKIA[0-9A-Z]{16}|ASIA[0-9A-Z]{16}|BEGIN [A-Z0-9 ]*PRIVATE KEY)"
)
ALLOWED_LEAK_MATCHES = (
    "${{ github.token }}",
    "handle_token",  # XDG desktop portal public request identifier.
    "id-token: write",
)
EXTENSION_SOURCE_DIR = ROOT / "extensions" / "gnome-shell" / "mini-eq@bhack.github.io"
LEAK_SCAN_EXCLUDES = (
    ":(exclude)*.png",
    ":(exclude)AGENTS.md",
    ":(exclude)docs/release.md",
    ":(exclude)tools/release_preflight.py",
)
UNTRACKED_LEAK_SCAN_EXCLUDES = (
    "*.png",
    "AGENTS.md",
    "docs/release.md",
    "tools/release_preflight.py",
)
BACKGROUND_PORTAL_REVIEW_PATHS = (
    Path("io.github.bhack.mini-eq.yaml"),
    Path("src/mini_eq/app.py"),
    Path("src/mini_eq/background.py"),
    Path("src/mini_eq/cli.py"),
    Path("src/mini_eq/dbus_control.py"),
    Path("src/mini_eq/window.py"),
    Path("src/mini_eq/window_preferences.py"),
    Path("extensions/gnome-shell/mini-eq@bhack.github.io/extension.js"),
)
FLATPAK_RUNTIME_REVIEW_PATHS = (
    Path(".github/workflows/ci.yml"),
    Path("io.github.bhack.mini-eq.yaml"),
    Path("python3-dependencies.yaml"),
    Path("pyproject.toml"),
    Path("src/mini_eq/analyzer.py"),
    Path("src/mini_eq/cli.py"),
    Path("src/mini_eq/deps.py"),
    Path("src/mini_eq/filter_chain.py"),
    Path("src/mini_eq/routing.py"),
    Path("src/mini_eq/window.py"),
    Path("src/mini_eq/pipewire_backend.py"),
    Path("src/mini_eq/pipewire_stream_router.py"),
    Path("tools/check_flatpak_runtime.py"),
    Path("tools/check_live_ui_runtime.py"),
    Path("tools/run_flatpak_runtime_smoke_ci.sh"),
    Path("tests/test_mini_eq_live_ui_runtime.py"),
)
PIPEWIRE_GOBJECT_BUILD_TOOLS = ("g-ir-compiler", "g-ir-scanner", "pkg-config")
PIPEWIRE_GOBJECT_PKG_CONFIG_MODULES = ("glib-2.0", "gio-2.0", "gobject-2.0", "libpipewire-0.3")
PIPEWIRE_GOBJECT_DEBIAN_BUILD_PACKAGES = (
    "build-essential",
    "gobject-introspection",
    "libgirepository1.0-dev",
    "libglib2.0-dev",
    "libpipewire-0.3-dev",
    "pkg-config",
)


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


def allowed_leak_match(line: str) -> bool:
    return any(allowed in line for allowed in ALLOWED_LEAK_MATCHES)


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


def changed_paths_for_review(base_tag: str, paths: tuple[Path, ...]) -> list[str]:
    path_args = [path.as_posix() for path in paths]
    committed_changes = git_stdout("diff", "--name-only", f"{base_tag}..HEAD", "--", *path_args).splitlines()
    worktree_changes = git_stdout("status", "--short", "--", *path_args).splitlines()
    return [*committed_changes, *worktree_changes]


def run_background_portal_smoke_notice() -> None:
    base_tag = extension_comparison_base_tag()
    if base_tag is None:
        print("\nFlatpak background portal smoke notice skipped; no release tag found.")
        return

    changes = changed_paths_for_review(base_tag, BACKGROUND_PORTAL_REVIEW_PATHS)
    if not changes:
        print(f"\nFlatpak background portal smoke not indicated; background integration unchanged since {base_tag}.")
        return

    print(f"\nFlatpak background portal smoke may be needed; background integration changed since {base_tag}:")
    for path in changes:
        print(f"  {path}")
    print("Run one clean-permission Flatpak portal smoke in a real GNOME session before releasing this change.")


def run_flatpak_runtime_smoke_notice() -> None:
    base_tag = extension_comparison_base_tag()
    if base_tag is None:
        print("\nFlatpak runtime smoke notice skipped; no release tag found.")
        return

    changes = changed_paths_for_review(base_tag, FLATPAK_RUNTIME_REVIEW_PATHS)
    if not changes:
        print(f"\nFlatpak runtime smoke not indicated; runtime integration unchanged since {base_tag}.")
        return

    print(f"\nFlatpak runtime smoke may be needed; runtime integration changed since {base_tag}:")
    for path in changes:
        print(f"  {path}")
    print("Run the installed Flatpak runtime smoke and interactive audio check before releasing this change.")


def run_leak_scan() -> None:
    run(["git", "rev-list", "--count", "HEAD"])
    run(["git", "ls-remote", "--heads", "origin"])
    run(["git", "ls-remote", "--tags", "origin"])

    matches = [
        *git_leak_matches(
            [
                "git",
                "grep",
                "-n",
                "-I",
                "-E",
                LEAK_PATTERN,
                "HEAD",
                "--",
                ".",
                *LEAK_SCAN_EXCLUDES,
            ]
        ),
        *git_leak_matches(
            [
                "git",
                "grep",
                "-n",
                "-I",
                "-E",
                LEAK_PATTERN,
                "--",
                ".",
                *LEAK_SCAN_EXCLUDES,
            ]
        ),
        *untracked_leak_matches(),
    ]
    unexpected = [line for line in matches if not allowed_leak_match(line)]
    if unexpected:
        print("\nUnexpected leak-scan matches:", file=sys.stderr)
        for line in unexpected:
            print(line, file=sys.stderr)
        raise SystemExit(1)

    if matches:
        print("Leak scan found only allowed non-secret references.")
    else:
        print("Leak scan found no matches.")


def git_leak_matches(command: list[str]) -> list[str]:
    print(f"\n$ {format_command(command)}", flush=True)
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)

    if result.returncode not in (0, 1):
        sys.stderr.write(result.stderr)
        raise SystemExit(result.returncode)

    return result.stdout.splitlines()


def untracked_leak_matches() -> list[str]:
    command = ["git", "ls-files", "--others", "--exclude-standard", "-z", "--", "."]
    print(f"\n$ {format_command(command)}", flush=True)
    result = subprocess.run(command, cwd=ROOT, capture_output=True, check=True)
    paths = [Path(os.fsdecode(path)) for path in result.stdout.split(b"\0") if path]
    leak_re = re.compile(LEAK_PATTERN)
    matches: list[str] = []

    for relative_path in paths:
        path_text = relative_path.as_posix()
        if any(fnmatch.fnmatch(path_text, pattern) for pattern in UNTRACKED_LEAK_SCAN_EXCLUDES):
            continue

        path = ROOT / relative_path
        try:
            payload = path.read_bytes()
        except OSError:
            continue

        if b"\0" in payload:
            continue

        for line_number, line in enumerate(payload.decode("utf-8", errors="ignore").splitlines(), start=1):
            if leak_re.search(line):
                matches.append(f"{path_text}:{line_number}:{line}")

    return matches


def missing_pkg_config_modules(modules: tuple[str, ...]) -> list[str]:
    missing: list[str] = []
    for module in modules:
        result = subprocess.run(
            ["pkg-config", "--exists", module],
            cwd=ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if result.returncode != 0:
            missing.append(module)
    return missing


def check_pipewire_gobject_sdist_build_environment() -> None:
    missing_tools = [tool for tool in PIPEWIRE_GOBJECT_BUILD_TOOLS if shutil.which(tool) is None]
    missing_modules = (
        list(PIPEWIRE_GOBJECT_PKG_CONFIG_MODULES)
        if shutil.which("pkg-config") is None
        else missing_pkg_config_modules(PIPEWIRE_GOBJECT_PKG_CONFIG_MODULES)
    )
    if not missing_tools and not missing_modules:
        return

    details: list[str] = [
        "The release wheel smoke installs Mini EQ in a fresh venv and must be able to build "
        "pipewire-gobject from its sdist.",
        "Install the PipeWire/GObject build dependencies first.",
        "",
        "Debian/Ubuntu:",
        f"  sudo apt install {' '.join(PIPEWIRE_GOBJECT_DEBIAN_BUILD_PACKAGES)}",
    ]
    if missing_tools:
        details.append(f"Missing tools: {', '.join(missing_tools)}")
    if missing_modules:
        details.append(f"Missing pkg-config modules: {', '.join(missing_modules)}")
    raise SystemExit("\n".join(details))


def run_wheel_smoke_test(python: Path, wheel: Path, scratch: Path) -> None:
    venv = scratch / "wheel-test"
    run([python, "-m", "venv", "--system-site-packages", venv])

    bin_dir = venv / ("Scripts" if os.name == "nt" else "bin")
    venv_python = bin_dir / "python"
    mini_eq = bin_dir / ("mini-eq.exe" if os.name == "nt" else "mini-eq")

    run([venv_python, "-m", "pip", "install", "--upgrade", "pip"])
    check_pipewire_gobject_sdist_build_environment()
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


def main() -> int:
    python = Path(sys.executable)
    require_tools("appstreamcli", "desktop-file-validate", "git", "gnome-extensions")

    run(["git", "diff", "--check"])
    run([python, "-m", "pytest", "tests/test_version_metadata.py", "-q"])
    run([python, ROOT / "tools/check_gnome_shell_extension.py"])
    run_gnome_shell_extension_upload_notice()
    run_flatpak_runtime_smoke_notice()
    run_background_portal_smoke_notice()
    run([python, "-m", "ruff", "check", "."])
    run([python, "-m", "ruff", "format", "--check", "."])
    run([python, "-m", "pytest", "-q"])
    run([python, "-m", "mini_eq", "--check-deps"])
    run(["appstreamcli", "validate", "--no-net", ROOT / "data/io.github.bhack.mini-eq.metainfo.xml"])
    run(["desktop-file-validate", ROOT / "data/io.github.bhack.mini-eq.desktop"])
    run_build_checks(python)
    run_leak_scan()

    print("\nRelease preflight completed successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
