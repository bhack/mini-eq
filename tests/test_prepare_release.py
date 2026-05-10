from __future__ import annotations

from pathlib import Path

import pytest

from tools import prepare_release


def write_release_files(root: Path) -> None:
    (root / "data").mkdir()
    (root / "pyproject.toml").write_text('[project]\nname = "mini-eq"\nversion = "0.7.2"\n', encoding="utf-8")
    (root / "CHANGELOG.md").write_text("# Changelog\n\n## 0.7.2 - 2026-05-10\n\n- Old note.\n", encoding="utf-8")
    (root / "data/io.github.bhack.mini-eq.metainfo.xml").write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<component type="desktop-application">
  <screenshots>
    <screenshot type="default">
      <image>https://raw.githubusercontent.com/bhack/mini-eq/v0.7.2/docs/screenshots/mini-eq.png</image>
    </screenshot>
  </screenshots>
  <releases>
    <release version="0.7.2" date="2026-05-10" />
  </releases>
</component>
""",
        encoding="utf-8",
    )


def test_prepare_release_updates_public_version_metadata(tmp_path: Path) -> None:
    write_release_files(tmp_path)

    edits = prepare_release.prepare_release(
        tmp_path,
        "0.7.3",
        "2026-05-11",
        ["Fix launch behavior.", "Improve release checks."],
        "bhack/mini-eq",
    )
    for edit in edits:
        edit.path.write_text(edit.after, encoding="utf-8")

    assert 'version = "0.7.3"' in (tmp_path / "pyproject.toml").read_text(encoding="utf-8")
    assert "## 0.7.3 - 2026-05-11" in (tmp_path / "CHANGELOG.md").read_text(encoding="utf-8")

    appstream = (tmp_path / "data/io.github.bhack.mini-eq.metainfo.xml").read_text(encoding="utf-8")
    assert '<release version="0.7.3" date="2026-05-11">' in appstream
    assert "https://raw.githubusercontent.com/bhack/mini-eq/v0.7.3/docs/screenshots/mini-eq.png" in appstream
    assert "<li>Fix launch behavior.</li>" in appstream


def test_prepare_release_refuses_to_prepare_current_version(tmp_path: Path) -> None:
    write_release_files(tmp_path)

    with pytest.raises(ValueError, match="already uses 0.7.2"):
        prepare_release.prepare_release(tmp_path, "0.7.2", "2026-05-10", ["Note."], "bhack/mini-eq")
