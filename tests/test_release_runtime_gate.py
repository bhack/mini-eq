from __future__ import annotations

import subprocess
from pathlib import Path

from tools import release_runtime_gate


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, stdout=subprocess.PIPE, text=True)


def commit(root: Path, message: str) -> None:
    git(root, "add", ".")
    git(root, "commit", "-m", message)


def init_repo(root: Path) -> None:
    git(root, "init", "-q")
    git(root, "config", "user.name", "Mini EQ Test")
    git(root, "config", "user.email", "mini-eq@example.invalid")


def write_file(root: Path, relative: str, text: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_flatpak_runtime_gate_requires_smoke_for_runtime_changes(tmp_path: Path) -> None:
    init_repo(tmp_path)
    write_file(tmp_path, "src/mini_eq/pipewire_backend.py", "old\n")
    commit(tmp_path, "base")
    git(tmp_path, "tag", "v0.7.3")
    write_file(tmp_path, "src/mini_eq/pipewire_backend.py", "new\n")
    commit(tmp_path, "runtime change")

    gate = release_runtime_gate.flatpak_runtime_gate(
        tmp_path,
        current_tag="v0.7.4",
        release_requested=True,
        force=False,
    )

    assert gate.required is True
    assert gate.base_tag == "v0.7.3"
    assert gate.changes == ("src/mini_eq/pipewire_backend.py",)


def test_flatpak_runtime_gate_skips_non_runtime_changes(tmp_path: Path) -> None:
    init_repo(tmp_path)
    write_file(tmp_path, "CHANGELOG.md", "old\n")
    commit(tmp_path, "base")
    git(tmp_path, "tag", "v0.7.3")
    write_file(tmp_path, "CHANGELOG.md", "new\n")
    commit(tmp_path, "docs change")

    gate = release_runtime_gate.flatpak_runtime_gate(
        tmp_path,
        current_tag="v0.7.4",
        release_requested=True,
        force=False,
    )

    assert gate.required is False
    assert gate.base_tag == "v0.7.3"
    assert gate.changes == ()


def test_flatpak_runtime_gate_can_be_forced(tmp_path: Path) -> None:
    init_repo(tmp_path)
    write_file(tmp_path, "CHANGELOG.md", "old\n")
    commit(tmp_path, "base")
    git(tmp_path, "tag", "v0.7.3")

    gate = release_runtime_gate.flatpak_runtime_gate(
        tmp_path,
        current_tag="v0.7.4",
        release_requested=True,
        force=True,
    )

    assert gate.required is True
    assert gate.reason == "forced by dispatch input"


def test_flatpak_runtime_gate_skips_dry_run_dispatch(tmp_path: Path) -> None:
    init_repo(tmp_path)
    write_file(tmp_path, "src/mini_eq/pipewire_backend.py", "old\n")
    commit(tmp_path, "base")
    git(tmp_path, "tag", "v0.7.3")
    write_file(tmp_path, "src/mini_eq/pipewire_backend.py", "new\n")
    commit(tmp_path, "runtime change")

    gate = release_runtime_gate.flatpak_runtime_gate(
        tmp_path,
        current_tag="v0.7.4",
        release_requested=False,
        force=False,
    )

    assert gate.required is False
    assert gate.reason == "dry-run/package-only dispatch"


def test_flatpak_runtime_gate_force_overrides_dry_run_dispatch(tmp_path: Path) -> None:
    init_repo(tmp_path)
    write_file(tmp_path, "CHANGELOG.md", "old\n")
    commit(tmp_path, "base")
    git(tmp_path, "tag", "v0.7.3")

    gate = release_runtime_gate.flatpak_runtime_gate(
        tmp_path,
        current_tag="v0.7.4",
        release_requested=False,
        force=True,
    )

    assert gate.required is True
    assert gate.reason == "forced by dispatch input"


def test_live_ui_runtime_gate_requires_smoke_for_app_changes(tmp_path: Path) -> None:
    init_repo(tmp_path)
    write_file(tmp_path, "src/mini_eq/window.py", "old\n")
    commit(tmp_path, "base")
    git(tmp_path, "tag", "v0.7.3")
    write_file(tmp_path, "src/mini_eq/window.py", "new\n")
    commit(tmp_path, "ui change")

    gate = release_runtime_gate.live_ui_runtime_gate(
        tmp_path,
        current_tag="v0.7.4",
        release_requested=True,
        force=False,
    )

    assert gate.required is True
    assert gate.base_tag == "v0.7.3"
    assert gate.changes == ("src/mini_eq/window.py",)
    assert gate.reason == "app or UI runtime-sensitive changes"


def test_live_ui_runtime_gate_skips_docs_only_changes(tmp_path: Path) -> None:
    init_repo(tmp_path)
    write_file(tmp_path, "README.md", "old\n")
    commit(tmp_path, "base")
    git(tmp_path, "tag", "v0.7.3")
    write_file(tmp_path, "README.md", "new\n")
    commit(tmp_path, "docs change")

    gate = release_runtime_gate.live_ui_runtime_gate(
        tmp_path,
        current_tag="v0.7.4",
        release_requested=True,
        force=False,
    )

    assert gate.required is False
    assert gate.base_tag == "v0.7.3"
    assert gate.changes == ()


def test_live_ui_runtime_gate_can_be_forced(tmp_path: Path) -> None:
    init_repo(tmp_path)
    write_file(tmp_path, "README.md", "old\n")
    commit(tmp_path, "base")
    git(tmp_path, "tag", "v0.7.3")

    gate = release_runtime_gate.live_ui_runtime_gate(
        tmp_path,
        current_tag="v0.7.4",
        release_requested=False,
        force=True,
    )

    assert gate.required is True
    assert gate.reason == "forced by dispatch input"
