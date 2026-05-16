from __future__ import annotations

from pathlib import Path

from tools import ci_scope, release_gates


def test_ci_scope_marks_workflow_changes_as_all_scopes() -> None:
    scopes = release_gates.classify_ci_scopes([".github/workflows/ci.yml"])

    assert all(scopes.values())


def test_ci_scope_classifies_tooling_and_release_metadata_changes() -> None:
    scopes = release_gates.classify_ci_scopes(["tools/prepare_flathub_release.py", "CHANGELOG.md"])

    assert scopes == {
        "test": True,
        "tooling": True,
        "pwg": False,
        "flatpak": False,
        "release_metadata": True,
    }


def test_ci_scope_classifies_flatpak_runtime_paths() -> None:
    scopes = release_gates.classify_ci_scopes(["src/mini_eq/routing.py", "tools/release_gates.py"])

    assert scopes["test"] is True
    assert scopes["tooling"] is True
    assert scopes["pwg"] is True
    assert scopes["flatpak"] is True


def test_ci_scope_cli_writes_github_output_and_summary(tmp_path: Path) -> None:
    paths = tmp_path / "paths.txt"
    output = tmp_path / "output.txt"
    summary = tmp_path / "summary.md"
    paths.write_text("tools/ci_scope.py\n", encoding="utf-8")

    result = ci_scope.main(
        [
            str(paths),
            "--github-output",
            str(output),
            "--github-summary",
            str(summary),
        ]
    )

    assert result == 0
    assert "test=true" in output.read_text(encoding="utf-8")
    assert "tooling=true" in output.read_text(encoding="utf-8")
    assert "Runtime smoke policy" in summary.read_text(encoding="utf-8")
