#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import tomllib
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPO = "bhack/mini-eq"
PYPI_JSON_URL = "https://pypi.org/pypi/mini-eq/json"
PYPI_VERSION_URL = "https://pypi.org/project/mini-eq/{version}/"
SDIST_NAME = "mini_eq-{version}.tar.gz"
WHEEL_NAME = "mini_eq-{version}-py3-none-any.whl"


def current_version() -> str:
    with (ROOT / "pyproject.toml").open("rb") as pyproject_file:
        return tomllib.load(pyproject_file)["project"]["version"]


def require_tools(*tools: str) -> None:
    missing = [tool for tool in tools if shutil.which(tool) is None]
    if missing:
        raise SystemExit(f"Missing required release tool(s): {', '.join(missing)}")


def run(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=check,
    )


def gh_json(command: list[str]) -> dict[str, Any]:
    result = run(command)
    return json.loads(result.stdout)


def fetch_url(url: str, *, method: str = "GET") -> bytes:
    request = urllib.request.Request(url, method=method)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.read()
    except urllib.error.HTTPError as error:
        if method == "HEAD" and error.code == 405:
            return fetch_url(url)
        raise


def sha256_url(url: str) -> str:
    digest = hashlib.sha256()
    digest.update(fetch_url(url))
    return digest.hexdigest()


def asset_by_name(release: dict[str, Any], name: str) -> dict[str, Any]:
    for asset in release.get("assets", []):
        if asset.get("name") == name:
            return asset
    raise SystemExit(f"GitHub release is missing asset: {name}")


def check_github_release(version: str, tag: str, repo: str) -> str:
    release = gh_json(
        [
            "gh",
            "release",
            "view",
            tag,
            "--repo",
            repo,
            "--json",
            "tagName,isDraft,isPrerelease,assets,url",
        ]
    )

    if release["tagName"] != tag:
        raise SystemExit(f"GitHub release tag mismatch: expected {tag}, got {release['tagName']}")
    if release["isDraft"]:
        raise SystemExit(f"GitHub release {tag} is still a draft")

    expected_names = (SDIST_NAME.format(version=version), WHEEL_NAME.format(version=version))
    for name in expected_names:
        asset = asset_by_name(release, name)
        url = asset["url"]
        if f"/download/{tag}/" not in url:
            raise SystemExit(f"GitHub release asset still has an unstable URL: {url}")

    tag_lookup = run(["git", "ls-remote", "--tags", "origin", tag])
    if not tag_lookup.stdout.strip():
        raise SystemExit(f"Remote tag not found on origin: {tag}")

    sdist = asset_by_name(release, expected_names[0])
    sdist_sha = sha256_url(sdist["url"])
    expected_digest = sdist.get("digest")
    if expected_digest and expected_digest != f"sha256:{sdist_sha}":
        raise SystemExit(
            f"Downloaded sdist SHA-256 does not match the GitHub release asset digest: {sdist_sha} != {expected_digest}"
        )

    print(f"GitHub release is published: {release['url']}")
    print(f"Remote tag exists: {tag_lookup.stdout.strip()}")
    print(f"Flathub source archive SHA-256: {sdist_sha}")
    return sdist_sha


def check_pypi(version: str) -> None:
    pypi_json = json.loads(fetch_url(PYPI_JSON_URL))
    json_version = pypi_json["info"]["version"]
    version_url = PYPI_VERSION_URL.format(version=version)

    if json_version == version:
        print(f"PyPI JSON reports: {json_version}")
        return

    try:
        fetch_url(version_url, method="HEAD")
    except urllib.error.HTTPError as error:
        raise SystemExit(
            f"PyPI JSON reports {json_version}, and the {version} version page returned HTTP {error.code}"
        ) from error

    print(f"PyPI JSON still reports {json_version}, but the {version} version page is reachable.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify a published Mini EQ release.")
    parser.add_argument(
        "version",
        nargs="?",
        default=current_version(),
        help="release version to verify; defaults to pyproject.toml",
    )
    parser.add_argument("--repo", default=DEFAULT_REPO, help=f"GitHub repository; defaults to {DEFAULT_REPO}")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    version = args.version.removeprefix("v")
    tag = f"v{version}"

    require_tools("gh", "git")
    check_github_release(version, tag, args.repo)
    check_pypi(version)
    print("Post-publish checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
