from __future__ import annotations

import re
import tomllib
import xml.etree.ElementTree as ET
from pathlib import Path

from mini_eq import __version__

ROOT = Path(__file__).resolve().parents[1]


def project_version() -> str:
    with (ROOT / "pyproject.toml").open("rb") as file:
        return tomllib.load(file)["project"]["version"]


def first_changelog_version() -> str:
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    match = re.search(r"^##\s+([0-9]+\.[0-9]+\.[0-9]+)\s+-\s+\d{4}-\d{2}-\d{2}\s*$", changelog, re.MULTILINE)
    assert match is not None
    return match.group(1)


def appstream_metadata() -> ET.Element:
    return ET.parse(ROOT / "data/io.github.bhack.mini-eq.metainfo.xml").getroot()


def first_appstream_release_version() -> str:
    release = appstream_metadata().find("./releases/release")
    assert release is not None
    return release.attrib["version"]


def appstream_screenshot_url() -> str:
    image = appstream_metadata().find("./screenshots/screenshot[@type='default']/image")
    assert image is not None
    assert image.text is not None
    return image.text


def test_release_versions_are_in_sync() -> None:
    version = project_version()

    assert __version__ == version
    assert first_changelog_version() == version
    assert first_appstream_release_version() == version


def test_appstream_screenshot_points_at_current_release_tag() -> None:
    version = project_version()

    assert f"/v{version}/" in appstream_screenshot_url()
