#!/usr/bin/env python3
from __future__ import annotations

import argparse
import difflib
import re
import sys
import textwrap
import tomllib
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPO = "bhack/mini-eq"


@dataclass(frozen=True)
class FileEdit:
    path: Path
    before: str
    after: str

    @property
    def changed(self) -> bool:
        return self.before != self.after


def current_version(root: Path) -> str:
    with (root / "pyproject.toml").open("rb") as pyproject_file:
        return tomllib.load(pyproject_file)["project"]["version"]


def set_pyproject_version(text: str, version: str) -> str:
    updated, count = re.subn(r'(?m)^version = "[^"]+"$', f'version = "{version}"', text, count=1)
    if count != 1:
        raise ValueError("could not find a single pyproject version field")
    return updated


def markdown_notes(notes: list[str]) -> str:
    wrapper = textwrap.TextWrapper(width=79, initial_indent="- ", subsequent_indent="  ")
    return "\n".join(wrapper.fill(note) for note in notes)


def insert_changelog_release(text: str, version: str, release_date: str, notes: list[str]) -> str:
    first_release = re.search(r"^##\s+[0-9]+\.[0-9]+\.[0-9]+\s+-\s+\d{4}-\d{2}-\d{2}\s*$", text, re.MULTILINE)
    if first_release is None:
        raise ValueError("could not find the first changelog release heading")
    if first_release.group(0).startswith(f"## {version} - "):
        raise ValueError(f"CHANGELOG.md already starts with {version}")

    section = f"## {version} - {release_date}\n\n{markdown_notes(notes)}\n\n"
    return f"{text[: first_release.start()]}{section}{text[first_release.start() :]}"


def appstream_release_xml(version: str, release_date: str, notes: list[str]) -> str:
    if len(notes) == 1:
        return (
            f'    <release version="{escape(version)}" date="{escape(release_date)}">\n'
            "      <description>\n"
            f"        <p>{escape(notes[0])}</p>\n"
            "      </description>\n"
            "    </release>\n"
        )

    items = "\n".join(f"          <li>{escape(note)}</li>" for note in notes)
    return (
        f'    <release version="{escape(version)}" date="{escape(release_date)}">\n'
        "      <description>\n"
        "        <ul>\n"
        f"{items}\n"
        "        </ul>\n"
        "      </description>\n"
        "    </release>\n"
    )


def update_appstream(text: str, version: str, release_date: str, notes: list[str], repo: str) -> str:
    if re.search(rf'<release version="{re.escape(version)}"\s', text):
        raise ValueError(f"AppStream metadata already contains release {version}")

    screenshot_base = f"https://raw.githubusercontent.com/{repo}/v{version}/docs/screenshots/"
    text = re.sub(
        rf"https://raw\.githubusercontent\.com/{re.escape(repo)}/v[0-9]+\.[0-9]+\.[0-9]+/docs/screenshots/",
        screenshot_base,
        text,
    )

    release_marker = "  <releases>\n"
    if release_marker not in text:
        raise ValueError("could not find AppStream <releases> marker")
    return text.replace(release_marker, f"{release_marker}{appstream_release_xml(version, release_date, notes)}", 1)


def prepare_release(root: Path, version: str, release_date: str, notes: list[str], repo: str) -> list[FileEdit]:
    version = version.removeprefix("v")
    if current_version(root) == version:
        raise ValueError(f"pyproject.toml already uses {version}")

    pyproject = root / "pyproject.toml"
    changelog = root / "CHANGELOG.md"
    appstream = root / "data/io.github.bhack.mini-eq.metainfo.xml"

    pyproject_text = pyproject.read_text(encoding="utf-8")
    changelog_text = changelog.read_text(encoding="utf-8")
    appstream_text = appstream.read_text(encoding="utf-8")

    return [
        FileEdit(pyproject, pyproject_text, set_pyproject_version(pyproject_text, version)),
        FileEdit(changelog, changelog_text, insert_changelog_release(changelog_text, version, release_date, notes)),
        FileEdit(appstream, appstream_text, update_appstream(appstream_text, version, release_date, notes, repo)),
    ]


def print_diff(edit: FileEdit) -> None:
    before_lines = edit.before.splitlines(keepends=True)
    after_lines = edit.after.splitlines(keepends=True)
    sys.stdout.writelines(
        difflib.unified_diff(
            before_lines,
            after_lines,
            fromfile=str(edit.path),
            tofile=str(edit.path),
        )
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare Mini EQ version metadata for a new release.")
    parser.add_argument("version", help="new release version, for example 0.7.3")
    parser.add_argument("--date", default=date.today().isoformat(), help="release date; defaults to today")
    parser.add_argument("--repo", default=DEFAULT_REPO, help=f"screenshot repository path; defaults to {DEFAULT_REPO}")
    parser.add_argument("--root", type=Path, default=ROOT, help="Mini EQ checkout root; defaults to this repository")
    parser.add_argument("--note", action="append", required=True, help="release note; repeat for multiple bullets")
    parser.add_argument("--dry-run", action="store_true", help="print the patch without writing files")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        edits = prepare_release(args.root.resolve(), args.version, args.date, args.note, args.repo)
    except ValueError as error:
        raise SystemExit(str(error)) from error

    changed = [edit for edit in edits if edit.changed]
    if args.dry_run:
        for edit in changed:
            print_diff(edit)
        return 0

    for edit in changed:
        edit.path.write_text(edit.after, encoding="utf-8")
        print(f"updated {edit.path}")
    print("Run tests/test_version_metadata.py and review the generated release notes before committing.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
