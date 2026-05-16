from __future__ import annotations

import fnmatch
from pathlib import Path

CI_SCOPE_NAMES = ("test", "tooling", "pwg", "flatpak", "release_metadata")

CI_SCOPE_LABELS = {
    "test": "test",
    "tooling": "tooling",
    "pwg": "pipewire-gobject",
    "flatpak": "flatpak",
    "release_metadata": "release metadata",
}

CI_WORKFLOW_PATTERNS = (".github/workflows/*.yml",)

CI_SCOPE_PATTERNS = {
    "test": (
        "README.md",
        "pyproject.toml",
        "MANIFEST.in",
        "src/*",
        "tests/*",
        "data/*",
        "extensions/*",
        "tools/ci_scope.py",
        "tools/check_autoeq_live.py",
        "tools/check_gnome_shell_extension.py",
        "tools/check_headless_pipewire_runtime.py",
        "tools/pack_gnome_shell_extension.sh",
        "tools/prepare_flathub_release.py",
        "tools/prepare_release.py",
        "tools/release_gates.py",
        "tools/release_preflight.py",
        "tools/release_runtime_gate.py",
        "tools/release_status.py",
        "tools/run_headless_pipewire_runtime_smoke_ci.sh",
        "tools/run_live_ui_runtime_smoke_ci.sh",
    ),
    "tooling": ("tools/*",),
    "pwg": (
        "tools/check_headless_pipewire_runtime.py",
        "tools/check_pipewire_gobject.py",
        "tools/release_gates.py",
        "tools/release_runtime_gate.py",
        "tools/run_headless_pipewire_runtime_smoke_ci.sh",
        "src/mini_eq/pipewire_backend.py",
        "src/mini_eq/analyzer.py",
    ),
    "flatpak": (
        "io.github.bhack.mini-eq.yaml",
        "python3-dependencies.yaml",
        "flatpak/*",
        "src/*",
        "data/*",
        "pyproject.toml",
        "MANIFEST.in",
        "tools/check_pipewire_gobject.py",
        "tools/release_gates.py",
        "tools/release_runtime_gate.py",
    ),
    "release_metadata": (
        "CHANGELOG.md",
        "README.md",
        "MANIFEST.in",
        "pyproject.toml",
        "data/io.github.bhack.mini-eq.metainfo.xml",
        "docs/development.md",
        "docs/flathub.md",
        "docs/release.md",
        "docs/screenshots/README.md",
        "tools/prepare_flathub_release.py",
        "tools/prepare_release.py",
        "tools/release_status.py",
        "tests/test_prepare_flathub_release.py",
        "tests/test_prepare_release.py",
        "tests/test_release_status.py",
    ),
}

FLATPAK_RUNTIME_REVIEW_PATHS = (
    Path(".github/workflows/ci.yml"),
    Path(".github/workflows/release.yml"),
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
    Path("tools/check_headless_pipewire_runtime.py"),
    Path("tools/check_flatpak_runtime.py"),
    Path("tools/check_live_ui_runtime.py"),
    Path("tools/release_gates.py"),
    Path("tools/release_runtime_gate.py"),
    Path("tools/run_flatpak_runtime_smoke_ci.sh"),
    Path("tools/run_headless_pipewire_runtime_smoke_ci.sh"),
    Path("tests/test_github_workflows.py"),
    Path("tests/test_mini_eq_live_ui_runtime.py"),
    Path("tests/test_release_runtime_gate.py"),
)


def normalized_repo_path(path: str | Path) -> str:
    normalized = Path(path).as_posix()
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def path_matches(path: str, patterns: tuple[str, ...]) -> bool:
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)


def classify_ci_scopes(paths: list[str] | tuple[str, ...]) -> dict[str, bool]:
    scopes = {name: False for name in CI_SCOPE_NAMES}

    for raw_path in paths:
        path = normalized_repo_path(raw_path)
        if not path:
            continue

        if path_matches(path, CI_WORKFLOW_PATTERNS):
            for name in scopes:
                scopes[name] = True
            continue

        for name, patterns in CI_SCOPE_PATTERNS.items():
            if path_matches(path, patterns):
                scopes[name] = True

    return scopes


LIVE_UI_RUNTIME_REVIEW_PATHS = (
    Path(".github/workflows/ci.yml"),
    Path(".github/workflows/release.yml"),
    Path("io.github.bhack.mini-eq.yaml"),
    Path("pyproject.toml"),
    Path("python3-dependencies.yaml"),
    Path("src/mini_eq"),
    Path("tools/check_headless_pipewire_runtime.py"),
    Path("tools/check_live_ui_runtime.py"),
    Path("tools/release_gates.py"),
    Path("tools/release_runtime_gate.py"),
    Path("tools/run_headless_pipewire_runtime_smoke_ci.sh"),
    Path("tools/run_live_ui_runtime_smoke_ci.sh"),
    Path("tests/test_github_workflows.py"),
    Path("tests/test_mini_eq_live_ui_runtime.py"),
    Path("tests/test_release_runtime_gate.py"),
)
