from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_flatpak_manifest_installs_gsettings_schema() -> None:
    manifest = (ROOT / "io.github.bhack.mini-eq.yaml").read_text(encoding="utf-8")

    assert "src/mini_eq/assets/schemas/io.github.bhack.mini-eq.gschema.xml" in manifest
    assert "glib-compile-schemas --strict ${FLATPAK_DEST}/share/glib-2.0/schemas" in manifest
