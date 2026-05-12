from __future__ import annotations

from pathlib import Path

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
