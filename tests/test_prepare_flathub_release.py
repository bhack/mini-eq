from __future__ import annotations

from pathlib import Path

from tools import prepare_flathub_release


def flathub_manifest() -> str:
    return """app-id: io.github.bhack.mini-eq
modules:
  - name: other
    sources:
      - type: archive
        url: https://example.invalid/other.tar.gz
  - name: mini-eq
    buildsystem: simple
    sources:
      - type: archive
        url: https://github.com/bhack/mini-eq/releases/download/v0.8.1/mini_eq-0.8.1.tar.gz
        sha256: old-sha
"""


def test_prepare_flathub_release_updates_only_mini_eq_source(tmp_path: Path) -> None:
    manifest = tmp_path / "io.github.bhack.mini-eq.yaml"
    manifest.write_text(flathub_manifest(), encoding="utf-8")

    changed = prepare_flathub_release.update_manifest_source(
        manifest,
        url="https://github.com/bhack/mini-eq/releases/download/v0.8.2/mini_eq-0.8.2.tar.gz",
        sha256="new-sha",
    )

    text = manifest.read_text(encoding="utf-8")
    assert changed is True
    assert "https://example.invalid/other.tar.gz" in text
    assert "mini_eq-0.8.2.tar.gz" in text
    assert "sha256: new-sha" in text
    assert "old-sha" not in text


def test_prepare_flathub_release_reports_no_change_for_current_source(tmp_path: Path) -> None:
    manifest = tmp_path / "io.github.bhack.mini-eq.yaml"
    url = "https://github.com/bhack/mini-eq/releases/download/v0.8.2/mini_eq-0.8.2.tar.gz"
    manifest.write_text(
        """modules:
  - name: mini-eq
    sources:
      - type: archive
        url: https://github.com/bhack/mini-eq/releases/download/v0.8.2/mini_eq-0.8.2.tar.gz
        sha256: current-sha
""",
        encoding="utf-8",
    )

    assert prepare_flathub_release.update_manifest_source(manifest, url=url, sha256="current-sha") is False


def test_prepare_flathub_release_cli_can_use_known_sha(tmp_path: Path, capsys) -> None:
    manifest = tmp_path / "io.github.bhack.mini-eq.yaml"
    pr_body = tmp_path / "body.md"
    manifest.write_text(flathub_manifest(), encoding="utf-8")

    result = prepare_flathub_release.main(
        [
            "0.8.2",
            str(manifest),
            "--sha256",
            "known-sha",
            "--pr-body",
            str(pr_body),
        ]
    )

    assert result == 0
    assert "Updated: true" in capsys.readouterr().out
    assert "mini_eq-0.8.2.tar.gz" in manifest.read_text(encoding="utf-8")
    assert "SHA-256: known-sha" in pr_body.read_text(encoding="utf-8")
