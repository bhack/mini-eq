from __future__ import annotations

from pathlib import Path

from mini_eq import __version__
from tests._mini_eq_imports import import_mini_eq_module

release_notes = import_mini_eq_module("release_notes")


def write_metainfo(path: Path) -> None:
    path.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<component type="desktop-application">
  <releases>
    <release version="1.2.3" date="2026-05-13">
      <description><ul><li>Fix &amp; tune output handling.</li><li><em>Add</em> presets.</li></ul></description>
    </release>
    <release version="1.2.2" date="2026-05-12">
      <description><p>Older release.</p></description>
    </release>
  </releases>
</component>
""",
        encoding="utf-8",
    )


def test_release_notes_from_metainfo_extracts_matching_release_markup(tmp_path: Path) -> None:
    path = tmp_path / "io.github.bhack.mini-eq.metainfo.xml"
    write_metainfo(path)

    notes = release_notes.release_notes_from_metainfo(path, "1.2.3")

    assert notes == release_notes.AboutReleaseNotes(
        version="1.2.3",
        markup="<ul><li>Fix &amp; tune output handling.</li><li><em>Add</em> presets.</li></ul>",
    )


def test_release_notes_from_metainfo_ignores_missing_version(tmp_path: Path) -> None:
    path = tmp_path / "io.github.bhack.mini-eq.metainfo.xml"
    write_metainfo(path)

    assert release_notes.release_notes_from_metainfo(path, "9.9.9") is None


def test_current_appstream_release_notes_are_available() -> None:
    notes = release_notes.about_release_notes(__version__)

    assert notes is not None
    assert notes.version == __version__
    assert notes.markup.startswith("<")
