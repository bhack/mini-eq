from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tools import release_status


def write_release_files(root: Path, version: str, *, screenshot_version: str | None = None) -> None:
    screenshot_version = screenshot_version or version
    (root / "data").mkdir()
    (root / "pyproject.toml").write_text(f'[project]\nname = "mini-eq"\nversion = "{version}"\n', encoding="utf-8")
    (root / "CHANGELOG.md").write_text(f"# Changelog\n\n## {version} - 2026-05-10\n\n- Note.\n", encoding="utf-8")
    (root / "data/io.github.bhack.mini-eq.metainfo.xml").write_text(
        f"""<?xml version="1.0" encoding="UTF-8"?>
<component type="desktop-application">
  <screenshots>
    <screenshot type="default">
      <image>https://raw.githubusercontent.com/bhack/mini-eq/v{screenshot_version}/docs/screenshots/mini-eq.png</image>
    </screenshot>
  </screenshots>
  <releases>
    <release version="{version}" date="2026-05-10" />
  </releases>
</component>
""",
        encoding="utf-8",
    )


def test_local_metadata_checks_accept_synced_release_files(tmp_path: Path) -> None:
    write_release_files(tmp_path, "0.7.3")

    checks = release_status.local_metadata_checks(tmp_path, release_status.release_info("0.7.3"))

    assert {check.status for check in checks} == {release_status.PASS}


def test_local_metadata_checks_reject_stale_screenshot_urls(tmp_path: Path) -> None:
    write_release_files(tmp_path, "0.7.3", screenshot_version="0.7.2")

    checks = release_status.local_metadata_checks(tmp_path, release_status.release_info("0.7.3"))

    assert any(check.name == "AppStream screenshots" and check.status == release_status.FAIL for check in checks)


def test_release_info_accepts_optional_v_prefix() -> None:
    info = release_status.release_info("v0.7.3")

    assert info.version == "0.7.3"
    assert info.tag == "v0.7.3"


@pytest.mark.parametrize("version", ["0.7", "0.7.3.1", "--help", "0.7.3;gh"])
def test_release_info_rejects_non_semver_versions(version: str) -> None:
    with pytest.raises(ValueError, match="release version"):
        release_status.release_info(version)


def test_validate_github_repo_rejects_option_like_values() -> None:
    with pytest.raises(ValueError, match="owner/name"):
        release_status.validate_github_repo("--repo/other")


def test_run_rejects_unsupported_commands() -> None:
    with pytest.raises(ValueError, match="unsupported command"):
        release_status.run(["python3", "-c", "print('no')"])


def test_flathub_archive_source_reads_mini_eq_release_source(tmp_path: Path) -> None:
    manifest = tmp_path / "io.github.bhack.mini-eq.yaml"
    manifest.write_text(
        """
modules:
  - name: other
    sources:
      - type: archive
        url: https://example.invalid/other.tar.gz
  - name: mini-eq
    buildsystem: simple
    sources:
      - type: archive
        url: https://github.com/bhack/mini-eq/releases/download/v0.7.3/mini_eq-0.7.3.tar.gz
        sha256: release-sha
""",
        encoding="utf-8",
    )

    source = release_status.flathub_archive_source(manifest)

    assert source == {
        "type": "archive",
        "url": "https://github.com/bhack/mini-eq/releases/download/v0.7.3/mini_eq-0.7.3.tar.gz",
        "sha256": "release-sha",
        "path": None,
    }


def test_flathub_checks_compare_archive_source_with_github_asset_sha(tmp_path: Path) -> None:
    manifest = tmp_path / "io.github.bhack.mini-eq.yaml"
    manifest.write_text(
        """
modules:
  - name: mini-eq
    sources:
      - type: archive
        url: https://github.com/bhack/mini-eq/releases/download/v0.7.3/mini_eq-0.7.3.tar.gz
        sha256: release-sha
""",
        encoding="utf-8",
    )
    info = release_status.release_info("0.7.3")

    checks = release_status.flathub_checks(manifest, info, "bhack/mini-eq", {info.sdist_name: "release-sha"})

    assert {check.status for check in checks} == {release_status.PASS}


def test_git_checks_skip_remote_tag_lookup_when_network_is_disabled(monkeypatch, tmp_path: Path) -> None:
    commands: list[list[str]] = []

    monkeypatch.setattr(release_status.shutil, "which", lambda tool: f"/usr/bin/{tool}")

    def fake_run(command: list[str], *, cwd: Path = release_status.ROOT) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        if command[:2] == ["git", "status"]:
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        if command[:3] == ["git", "rev-parse", "-q"]:
            return subprocess.CompletedProcess(command, 1, stdout="", stderr="")
        raise AssertionError(f"unexpected command: {command}")

    monkeypatch.setattr(release_status, "run", fake_run)

    checks = release_status.git_checks(tmp_path, release_status.release_info("0.7.3"), include_remote=False)

    assert not any(command[:2] == ["git", "ls-remote"] for command in commands)
    assert any(check.name == "remote tag" and check.status == release_status.SKIP for check in checks)
