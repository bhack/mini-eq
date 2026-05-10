#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import tomllib
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPO = "bhack/mini-eq"
PYPI_JSON_URL = "https://pypi.org/pypi/mini-eq/json"
PYPI_VERSION_JSON_URL = "https://pypi.org/pypi/mini-eq/{version}/json"
SDIST_NAME = "mini_eq-{version}.tar.gz"
WHEEL_NAME = "mini_eq-{version}-py3-none-any.whl"

PASS = "PASS"
PENDING = "PENDING"
WARN = "WARN"
FAIL = "FAIL"
SKIP = "SKIP"


@dataclass(frozen=True)
class Check:
    name: str
    status: str
    detail: str = ""


@dataclass(frozen=True)
class ReleaseInfo:
    version: str
    tag: str
    sdist_name: str
    wheel_name: str


def current_version(root: Path = ROOT) -> str:
    with (root / "pyproject.toml").open("rb") as pyproject_file:
        return tomllib.load(pyproject_file)["project"]["version"]


def release_info(version: str) -> ReleaseInfo:
    normalized = version.removeprefix("v")
    return ReleaseInfo(
        version=normalized,
        tag=f"v{normalized}",
        sdist_name=SDIST_NAME.format(version=normalized),
        wheel_name=WHEEL_NAME.format(version=normalized),
    )


def first_changelog_version(root: Path) -> str | None:
    changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    match = re.search(r"^##\s+([0-9]+\.[0-9]+\.[0-9]+)\s+-\s+\d{4}-\d{2}-\d{2}\s*$", changelog, re.MULTILINE)
    return match.group(1) if match else None


def appstream_metadata(root: Path) -> ET.Element:
    return ET.parse(root / "data/io.github.bhack.mini-eq.metainfo.xml").getroot()


def first_appstream_release_version(root: Path) -> str | None:
    release = appstream_metadata(root).find("./releases/release")
    return None if release is None else release.attrib.get("version")


def appstream_screenshot_urls(root: Path) -> list[str]:
    urls: list[str] = []
    for image in appstream_metadata(root).findall("./screenshots/screenshot/image"):
        if image.text:
            urls.append(image.text)
    return urls


def run(command: list[str], *, cwd: Path = ROOT) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, capture_output=True, text=True, check=False)


def fetch_url(url: str, *, method: str = "GET") -> bytes:
    request = urllib.request.Request(url, method=method)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.read()
    except urllib.error.HTTPError as error:
        if method == "HEAD" and error.code == 405:
            return fetch_url(url)
        raise


def fetch_json(url: str) -> dict[str, Any]:
    return json.loads(fetch_url(url))


def sha256_url(url: str) -> str:
    digest = hashlib.sha256()
    digest.update(fetch_url(url))
    return digest.hexdigest()


def local_metadata_checks(root: Path, info: ReleaseInfo) -> list[Check]:
    checks: list[Check] = []

    project_version = current_version(root)
    if project_version == info.version:
        checks.append(Check("pyproject version", PASS, project_version))
    else:
        checks.append(Check("pyproject version", FAIL, f"expected {info.version}, found {project_version}"))

    changelog_version = first_changelog_version(root)
    if changelog_version == info.version:
        checks.append(Check("changelog top entry", PASS, changelog_version))
    else:
        checks.append(
            Check("changelog top entry", FAIL, f"expected {info.version}, found {changelog_version or 'missing'}")
        )

    release_version = first_appstream_release_version(root)
    if release_version == info.version:
        checks.append(Check("AppStream top release", PASS, release_version))
    else:
        checks.append(
            Check("AppStream top release", FAIL, f"expected {info.version}, found {release_version or 'missing'}")
        )

    screenshot_urls = appstream_screenshot_urls(root)
    mismatched = [url for url in screenshot_urls if f"/{info.tag}/" not in url]
    if not screenshot_urls:
        checks.append(Check("AppStream screenshots", FAIL, "no screenshot URLs found"))
    elif mismatched:
        checks.append(Check("AppStream screenshots", FAIL, f"{len(mismatched)} URL(s) do not point at {info.tag}"))
    else:
        checks.append(Check("AppStream screenshots", PASS, f"{len(screenshot_urls)} URL(s) point at {info.tag}"))

    return checks


def git_checks(root: Path, info: ReleaseInfo, *, include_remote: bool = True) -> list[Check]:
    if shutil.which("git") is None:
        return [Check("git", SKIP, "git is not installed")]

    checks: list[Check] = []
    status = run(["git", "status", "--porcelain"], cwd=root)
    if status.returncode != 0:
        checks.append(Check("git worktree", WARN, status.stderr.strip() or "could not read worktree state"))
    elif status.stdout.strip():
        checks.append(Check("git worktree", WARN, "uncommitted changes present"))
    else:
        checks.append(Check("git worktree", PASS, "clean"))

    local_tag = run(["git", "rev-parse", "-q", "--verify", f"refs/tags/{info.tag}"], cwd=root)
    if local_tag.returncode == 0:
        checks.append(Check("local tag", PASS, info.tag))
    else:
        checks.append(Check("local tag", PENDING, f"{info.tag} is not present locally"))

    if not include_remote:
        checks.append(Check("remote tag", SKIP, "--no-network was used"))
        return checks

    remote_tag = run(["git", "ls-remote", "--tags", "origin", info.tag], cwd=root)
    if remote_tag.returncode != 0:
        checks.append(Check("remote tag", WARN, remote_tag.stderr.strip() or "could not query origin"))
    elif remote_tag.stdout.strip():
        checks.append(Check("remote tag", PASS, remote_tag.stdout.strip()))
    else:
        checks.append(Check("remote tag", PENDING, f"{info.tag} is not present on origin"))

    return checks


def github_release_checks(info: ReleaseInfo, repo: str, *, download_assets: bool) -> tuple[list[Check], dict[str, str]]:
    if shutil.which("gh") is None:
        return [Check("GitHub release", SKIP, "gh is not installed")], {}

    result = run(
        [
            "gh",
            "release",
            "view",
            info.tag,
            "--repo",
            repo,
            "--json",
            "tagName,isDraft,isPrerelease,assets,url",
        ]
    )
    if result.returncode != 0:
        return [Check("GitHub release", PENDING, f"{info.tag} is not published yet")], {}

    release = json.loads(result.stdout)
    checks = [Check("GitHub release", PENDING if release["isDraft"] else PASS, release["url"])]
    if release["isPrerelease"]:
        checks.append(Check("GitHub prerelease flag", WARN, f"{info.tag} is marked as a prerelease"))
    else:
        checks.append(Check("GitHub prerelease flag", PASS, "false"))

    assets = {asset.get("name"): asset for asset in release.get("assets", [])}
    asset_shas: dict[str, str] = {}
    for name in (info.sdist_name, info.wheel_name):
        asset = assets.get(name)
        if asset is None:
            checks.append(Check(f"GitHub asset {name}", FAIL, "missing"))
            continue

        url = asset.get("url", "")
        if release["isDraft"]:
            checks.append(Check(f"GitHub asset {name}", PENDING, "release is still draft"))
            continue
        if f"/download/{info.tag}/" not in url:
            checks.append(Check(f"GitHub asset {name}", FAIL, f"unstable URL: {url}"))
            continue

        if not download_assets:
            checks.append(Check(f"GitHub asset {name}", PASS, "stable URL"))
            continue

        try:
            asset_sha = sha256_url(url)
        except OSError as error:
            checks.append(Check(f"GitHub asset {name}", WARN, f"could not download asset: {error}"))
            continue

        asset_shas[name] = asset_sha
        digest = asset.get("digest")
        if digest and digest != f"sha256:{asset_sha}":
            checks.append(Check(f"GitHub asset {name}", FAIL, f"download sha256:{asset_sha} != {digest}"))
        else:
            checks.append(Check(f"GitHub asset {name}", PASS, f"sha256:{asset_sha}"))

    return checks, asset_shas


def pypi_checks(info: ReleaseInfo, github_shas: dict[str, str]) -> list[Check]:
    checks: list[Check] = []

    try:
        version_json = fetch_json(PYPI_VERSION_JSON_URL.format(version=info.version))
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return [Check("PyPI version", PENDING, f"{info.version} is not visible on PyPI yet")]
        return [Check("PyPI version", WARN, f"HTTP {error.code}")]
    except OSError as error:
        return [Check("PyPI version", WARN, f"could not query PyPI: {error}")]

    json_version = version_json.get("info", {}).get("version")
    if json_version != info.version:
        checks.append(Check("PyPI version", FAIL, f"expected {info.version}, found {json_version or 'missing'}"))
    else:
        checks.append(Check("PyPI version", PASS, info.version))

    pypi_files = {file.get("filename"): file for file in version_json.get("urls", [])}
    for name in (info.sdist_name, info.wheel_name):
        file_info = pypi_files.get(name)
        if file_info is None:
            checks.append(Check(f"PyPI artifact {name}", FAIL, "missing"))
            continue

        pypi_sha = file_info.get("digests", {}).get("sha256")
        github_sha = github_shas.get(name)
        if github_sha and pypi_sha != github_sha:
            checks.append(Check(f"PyPI artifact {name}", FAIL, f"sha256:{pypi_sha} != GitHub sha256:{github_sha}"))
        elif pypi_sha:
            checks.append(Check(f"PyPI artifact {name}", PASS, f"sha256:{pypi_sha}"))
        else:
            checks.append(Check(f"PyPI artifact {name}", WARN, "missing SHA-256 digest"))

    try:
        latest_json = fetch_json(PYPI_JSON_URL)
    except OSError as error:
        checks.append(Check("PyPI latest", WARN, f"could not query PyPI latest: {error}"))
    else:
        latest_version = latest_json.get("info", {}).get("version")
        if latest_version == info.version:
            checks.append(Check("PyPI latest", PASS, latest_version))
        else:
            checks.append(
                Check("PyPI latest", WARN, f"latest is {latest_version or 'unknown'}, target is {info.version}")
            )

    return checks


def flathub_archive_source(manifest: Path) -> dict[str, str | None] | None:
    lines = manifest.read_text(encoding="utf-8").splitlines()
    start = next((index for index, line in enumerate(lines) if line.strip() == "- name: mini-eq"), None)
    if start is None:
        return None

    end = len(lines)
    for index in range(start + 1, len(lines)):
        if lines[index].startswith("  - name: "):
            end = index
            break

    values: dict[str, str | None] = {"type": None, "url": None, "sha256": None, "path": None}
    for line in lines[start:end]:
        match = re.match(r"\s+(?:-\s+)?(type|url|sha256|path):\s*(.+?)\s*$", line)
        if match:
            values[match.group(1)] = match.group(2).strip('"')

    return values


def flathub_checks(manifest: Path, info: ReleaseInfo, repo: str, github_shas: dict[str, str]) -> list[Check]:
    if not manifest.exists():
        return [Check("Flathub manifest", FAIL, f"not found: {manifest}")]

    source = flathub_archive_source(manifest)
    if source is None:
        return [Check("Flathub manifest", FAIL, "could not find the mini-eq module source")]

    source_type = source["type"]
    if source_type == "dir":
        return [Check("Flathub source", SKIP, "manifest uses the local checked-out source")]
    if source_type != "archive":
        return [Check("Flathub source", WARN, f"unexpected source type: {source_type or 'missing'}")]

    checks: list[Check] = []
    expected_url = f"https://github.com/{repo}/releases/download/{info.tag}/{info.sdist_name}"
    if source["url"] == expected_url:
        checks.append(Check("Flathub source URL", PASS, expected_url))
    else:
        checks.append(Check("Flathub source URL", FAIL, f"expected {expected_url}, found {source['url'] or 'missing'}"))

    expected_sha = github_shas.get(info.sdist_name)
    if expected_sha is None:
        checks.append(Check("Flathub source SHA-256", PENDING, "GitHub source archive SHA-256 unavailable"))
    elif source["sha256"] == expected_sha:
        checks.append(Check("Flathub source SHA-256", PASS, expected_sha))
    else:
        checks.append(
            Check("Flathub source SHA-256", FAIL, f"expected {expected_sha}, found {source['sha256'] or 'missing'}")
        )

    return checks


def status_counts(checks: list[Check]) -> dict[str, int]:
    return {
        status: sum(1 for check in checks if check.status == status) for status in (PASS, PENDING, WARN, FAIL, SKIP)
    }


def print_checks(checks: list[Check]) -> None:
    width = max((len(check.name) for check in checks), default=0)
    for check in checks:
        detail = f"  {check.detail}" if check.detail else ""
        print(f"[{check.status:<7}] {check.name:<{width}}{detail}")

    counts = status_counts(checks)
    summary = ", ".join(f"{status.lower()}={counts[status]}" for status in (PASS, PENDING, WARN, FAIL, SKIP))
    print(f"\nSummary: {summary}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Show the current Mini EQ release publication state.")
    parser.add_argument("version", nargs="?", help="release version to inspect; defaults to pyproject.toml")
    parser.add_argument("--repo", default=DEFAULT_REPO, help=f"GitHub repository; defaults to {DEFAULT_REPO}")
    parser.add_argument("--root", type=Path, default=ROOT, help="Mini EQ checkout root; defaults to this repository")
    parser.add_argument("--flathub-manifest", type=Path, help="optional Flathub publishing manifest to inspect")
    parser.add_argument("--no-network", action="store_true", help="only run local metadata and git worktree checks")
    parser.add_argument(
        "--no-downloads", action="store_true", help="do not download GitHub release assets for SHA-256 checks"
    )
    parser.add_argument(
        "--strict-pending", action="store_true", help="return a non-zero exit status for pending checks"
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = args.root.resolve()
    info = release_info(args.version or current_version(root))

    checks = [
        *local_metadata_checks(root, info),
        *git_checks(root, info, include_remote=not args.no_network),
    ]
    github_shas: dict[str, str] = {}

    if args.no_network:
        checks.append(Check("network checks", SKIP, "--no-network was used"))
    else:
        github_checks, github_shas = github_release_checks(
            info,
            args.repo,
            download_assets=not args.no_downloads,
        )
        checks.extend(github_checks)
        checks.extend(pypi_checks(info, github_shas))

    if args.flathub_manifest is not None:
        checks.extend(flathub_checks(args.flathub_manifest, info, args.repo, github_shas))

    print(f"Mini EQ release status for {info.tag}\n")
    print_checks(checks)

    counts = status_counts(checks)
    if counts[FAIL] or (args.strict_pending and counts[PENDING]):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
