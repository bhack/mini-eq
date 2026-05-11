from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def workflow_text(path: str) -> str:
    return (ROOT / ".github/workflows" / path).read_text(encoding="utf-8")


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


def test_release_workflow_blocks_publish_on_live_ui_gate() -> None:
    release_yml = workflow_text("release.yml")

    assert "force_live_ui_runtime_smoke" in release_yml
    assert "--scope live-ui" in release_yml
    assert "live-ui-risk:" in release_yml
    assert "live-ui-runtime-smoke:" in release_yml
    assert "live-ui-gate:" in release_yml
    assert "tools/run_live_ui_runtime_smoke_ci.sh" in release_yml
    assert "needs['live-ui-runtime-smoke'].result != 'success'" in release_yml
    assert "live-ui-gate" in release_yml.partition("build:")[2].partition("runs-on:")[0]


def test_release_workflow_blocks_publish_on_release_preflight() -> None:
    release_yml = workflow_text("release.yml")

    assert "preflight:" in release_yml
    assert "docker/run-release-preflight.sh" in release_yml
    assert "preflight" in release_yml.partition("build:")[2].partition("runs-on:")[0]


def test_ci_scope_treats_release_workflow_and_release_gate_tools_as_tested_changes() -> None:
    ci_yml = workflow_text("ci.yml")

    assert ".github/workflows/*.yml)" in ci_yml
    assert "tools/release_gates.py" in ci_yml
    assert "tools/release_runtime_gate.py" in ci_yml
    assert "live_ui_runtime_smoke" in ci_yml
    assert "tools/run_live_ui_runtime_smoke_ci.sh" in ci_yml
