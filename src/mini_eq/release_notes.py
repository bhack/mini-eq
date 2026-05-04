from __future__ import annotations

import os
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

APPSTREAM_ID = "io.github.bhack.mini-eq"
APPSTREAM_FILE_NAME = f"{APPSTREAM_ID}.metainfo.xml"


@dataclass(frozen=True)
class AboutReleaseNotes:
    version: str
    markup: str


def unique_paths(paths: list[Path]) -> list[Path]:
    seen: set[Path] = set()
    unique: list[Path] = []
    for path in paths:
        resolved = path.expanduser()
        if resolved in seen:
            continue

        seen.add(resolved)
        unique.append(resolved)
    return unique


def xdg_data_dirs() -> list[Path]:
    data_home = os.environ.get("XDG_DATA_HOME")
    if data_home and Path(data_home).is_absolute():
        dirs = [Path(data_home)]
    else:
        dirs = [Path.home() / ".local" / "share"]

    data_dirs = os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share"
    dirs.extend(Path(path) for path in data_dirs.split(":") if path)
    return dirs


def appstream_metainfo_paths() -> list[Path]:
    source_tree_path = Path(__file__).resolve().parents[2] / "data" / APPSTREAM_FILE_NAME
    paths = [
        source_tree_path,
        Path(sys.prefix) / "share" / "metainfo" / APPSTREAM_FILE_NAME,
        Path("/app/share/metainfo") / APPSTREAM_FILE_NAME,
    ]
    paths.extend(data_dir / "metainfo" / APPSTREAM_FILE_NAME for data_dir in xdg_data_dirs())
    return unique_paths(paths)


def xml_local_name(tag: str) -> str:
    if tag.startswith("{"):
        return tag.rsplit("}", 1)[1]
    return tag


def child_elements(element: ET.Element, name: str) -> list[ET.Element]:
    return [child for child in list(element) if xml_local_name(child.tag) == name]


def appstream_release_notes_markup(description: ET.Element) -> str:
    parts: list[str] = []
    if description.text and description.text.strip():
        parts.append(description.text.strip())

    for child in list(description):
        text = ET.tostring(child, encoding="unicode", method="xml").strip()
        if text:
            parts.append(text)

    return "\n".join(parts).strip()


def release_notes_from_metainfo(path: Path, version: str) -> AboutReleaseNotes | None:
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError):
        return None

    releases = next(iter(child_elements(root, "releases")), None)
    if releases is None:
        return None

    for release in child_elements(releases, "release"):
        release_version = release.attrib.get("version")
        if release_version != version:
            continue

        description = next(iter(child_elements(release, "description")), None)
        if description is None:
            return None

        markup = appstream_release_notes_markup(description)
        if not markup:
            return None

        return AboutReleaseNotes(version=release_version, markup=markup)

    return None


def about_release_notes(version: str) -> AboutReleaseNotes | None:
    for path in appstream_metainfo_paths():
        release_notes = release_notes_from_metainfo(path, version)
        if release_notes is not None:
            return release_notes

    return None
