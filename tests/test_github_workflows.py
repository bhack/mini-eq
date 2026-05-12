from __future__ import annotations

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def workflow_text(path: str) -> str:
    return (ROOT / ".github/workflows" / path).read_text(encoding="utf-8")


def pipewire_gobject_requirement() -> str:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    for dependency in pyproject["project"]["dependencies"]:
        if dependency.lower().startswith("pipewire-gobject"):
            return dependency
    raise AssertionError("pyproject.toml does not declare pipewire-gobject")


def pipewire_gobject_floor_version() -> str:
    match = re.search(r">=\s*([0-9]+\.[0-9]+\.[0-9]+)", pipewire_gobject_requirement())
    if match is None:
        raise AssertionError("pipewire-gobject dependency does not have a minimum version")
    return match.group(1)


def test_workflow_expressions_use_bracket_access_for_hyphenated_needs() -> None:
    offenders: list[str] = []
    pattern = re.compile(r"needs\.[A-Za-z0-9_]*-[A-Za-z0-9_-]*")

    for workflow in (ROOT / ".github/workflows").glob("*.yml"):
        for line_number, line in enumerate(workflow.read_text(encoding="utf-8").splitlines(), start=1):
            if pattern.search(line):
                offenders.append(f"{workflow.relative_to(ROOT)}:{line_number}:{line.strip()}")

    assert offenders == []


def test_release_workflow_blocks_publish_on_runtime_gate() -> None:
    release_yml = workflow_text("release.yml")

    assert "tools/release_runtime_gate.py" in release_yml
    assert "flatpak-runtime-smoke:" in release_yml
    assert "runtime-gate:" in release_yml
    assert "needs['flatpak-runtime-smoke'].result != 'success'" in release_yml
    assert "runtime-gate" in release_yml.partition("build:")[2].partition("runs-on:")[0]


def test_ci_pipewire_gobject_requirement_tracks_current_floor() -> None:
    ci_yml = workflow_text("ci.yml")
    requirement = pipewire_gobject_requirement()
    floor_version = pipewire_gobject_floor_version()

    assert f'PWG_VERSION: "{floor_version}"' in ci_yml
    assert f'PWG_REQUIREMENT: "{requirement}"' in ci_yml


def test_release_workflow_does_not_block_publish_on_native_live_ui_gate() -> None:
    release_yml = workflow_text("release.yml")

    assert "force_live_ui_runtime_smoke" not in release_yml
    assert "--scope live-ui" not in release_yml
    assert "live-ui-runtime-smoke:" not in release_yml
    assert "live-ui-gate:" not in release_yml
    assert "tools/run_live_ui_runtime_smoke_ci.sh" not in release_yml


def test_release_workflow_blocks_publish_on_release_preflight() -> None:
    release_yml = workflow_text("release.yml")

    assert "preflight:" in release_yml
    assert "tools/run_release_preflight_container.sh" in release_yml
    assert "preflight" in release_yml.partition("build:")[2].partition("runs-on:")[0]


def test_ci_scope_treats_release_workflow_and_release_gate_tools_as_tested_changes() -> None:
    ci_yml = workflow_text("ci.yml")

    assert ".github/workflows/*.yml)" in ci_yml
    assert "tools/release_gates.py" in ci_yml
    assert "tools/release_runtime_gate.py" in ci_yml
    assert "tools/check_headless_pipewire_runtime.py" in ci_yml
    assert "tools/run_headless_pipewire_runtime_smoke_ci.sh" in ci_yml
    assert "live_ui_runtime_smoke" in ci_yml
    assert "tools/run_live_ui_runtime_smoke_ci.sh" in ci_yml


def test_headless_pipewire_runtime_smoke_is_optional_ci_gate_without_nested_gnome() -> None:
    ci_yml = workflow_text("ci.yml")
    job = ci_yml.partition("headless-pipewire-runtime-smoke:")[2].partition("live-ui-runtime-smoke:")[0]

    assert "headless_pipewire_runtime_smoke" in ci_yml
    assert "tools/run_headless_pipewire_runtime_smoke_ci.sh" in job
    assert "gnome-shell" not in job
    assert "python3-pyatspi" not in job


def test_live_ui_runtime_smoke_uses_host_gir_build_environment() -> None:
    ci_yml = workflow_text("ci.yml")
    script = (ROOT / "tools/run_live_ui_runtime_smoke_ci.sh").read_text(encoding="utf-8")

    assert "patchelf" in ci_yml
    assert "pipewire-gobject" in script
    assert "--no-build-isolation" in script
    assert "pip install -e ." in script
    assert ".[dev]" not in script


def test_flatpak_runtime_smoke_tolerates_pipewire_startup_race() -> None:
    script = (ROOT / "tools/run_flatpak_runtime_smoke_ci.sh").read_text(encoding="utf-8")

    assert "{ pw-dump 2>/dev/null || true; }" in script
    assert "first(.[] | select(" in script
    assert "| head -n 1" not in script
