from __future__ import annotations

from pathlib import Path

from tools import check_flathub_manifest_drift

UPSTREAM_MANIFEST = """app-id: io.github.bhack.mini-eq
runtime: org.gnome.Platform
runtime-version: "50"
sdk: org.gnome.Sdk
modules:
  - name: python3-dependencies
  - name: mini-eq
    buildsystem: simple
    sources:
      - type: dir
        path: .
"""

FLATHUB_MANIFEST = """app-id: io.github.bhack.mini-eq
runtime: org.gnome.Platform
runtime-version: "50"
sdk: org.gnome.Sdk
modules:
  - name: python3-dependencies
  - name: mini-eq
    buildsystem: simple
    sources:
      - type: archive
        url: https://github.com/bhack/mini-eq/releases/download/v0.5.1/mini_eq-0.5.1.tar.gz
        sha256: abc123
"""


def write_manifest_tree(path: Path, manifest: str, dependencies: str) -> Path:
    path.mkdir()
    manifest_path = path / "io.github.bhack.mini-eq.yaml"
    manifest_path.write_text(manifest, encoding="utf-8")
    (path / "python3-dependencies.yaml").write_text(dependencies, encoding="utf-8")
    return manifest_path


def test_flathub_drift_allows_only_mini_eq_source_difference(tmp_path: Path) -> None:
    dependencies = "name: python3-dependencies\nmodules: []\n"
    upstream_manifest = write_manifest_tree(tmp_path / "upstream", UPSTREAM_MANIFEST, dependencies)
    flathub_manifest = write_manifest_tree(tmp_path / "flathub", FLATHUB_MANIFEST, dependencies)

    result = check_flathub_manifest_drift.main([str(upstream_manifest), str(flathub_manifest)])

    assert result == 0


def test_flathub_drift_detects_python_dependency_manifest_difference(tmp_path: Path, capsys) -> None:
    upstream_manifest = write_manifest_tree(
        tmp_path / "upstream",
        UPSTREAM_MANIFEST,
        "name: python3-dependencies\nmodules: []\n",
    )
    flathub_manifest = write_manifest_tree(
        tmp_path / "flathub",
        FLATHUB_MANIFEST,
        "name: python3-dependencies\nmodules:\n  - name: python3-JACK-Client\n",
    )

    result = check_flathub_manifest_drift.main([str(upstream_manifest), str(flathub_manifest)])

    assert result == 1
    assert "python3-dependencies.yaml" in capsys.readouterr().out
