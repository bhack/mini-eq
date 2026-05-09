#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tomllib
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPO = "bhack/mini-eq"
PYPI_JSON_URL = "https://pypi.org/pypi/mini-eq/json"
PYPI_VERSION_JSON_URL = "https://pypi.org/pypi/mini-eq/{version}/json"
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


def check_github_release(version: str, tag: str, repo: str) -> dict[str, str]:
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
    asset_shas: dict[str, str] = {}
    for name in expected_names:
        asset = asset_by_name(release, name)
        url = asset["url"]
        if f"/download/{tag}/" not in url:
            raise SystemExit(f"GitHub release asset still has an unstable URL: {url}")
        asset_sha = sha256_url(url)
        asset_shas[name] = asset_sha
        expected_digest = asset.get("digest")
        if expected_digest and expected_digest != f"sha256:{asset_sha}":
            raise SystemExit(
                f"Downloaded GitHub release asset SHA-256 does not match the asset digest: "
                f"{name}: {asset_sha} != {expected_digest}"
            )

    tag_lookup = run(["git", "ls-remote", "--tags", "origin", tag])
    if not tag_lookup.stdout.strip():
        raise SystemExit(f"Remote tag not found on origin: {tag}")

    print(f"GitHub release is published: {release['url']}")
    print(f"Remote tag exists: {tag_lookup.stdout.strip()}")
    print(f"Flathub source archive SHA-256: {asset_shas[expected_names[0]]}")
    return asset_shas


def check_pypi(version: str, github_shas: dict[str, str], *, strict_artifact_match: bool) -> None:
    version_json = json.loads(fetch_url(PYPI_VERSION_JSON_URL.format(version=version)))
    version_json_version = version_json["info"]["version"]
    if version_json_version != version:
        raise SystemExit(f"PyPI version JSON mismatch: expected {version}, got {version_json_version}")

    pypi_files = {file["filename"]: file for file in version_json["urls"]}
    expected_names = (SDIST_NAME.format(version=version), WHEEL_NAME.format(version=version))
    for name in expected_names:
        if name not in pypi_files:
            raise SystemExit(f"PyPI is missing artifact: {name}")
        pypi_sha = pypi_files[name]["digests"]["sha256"]
        print(f"PyPI artifact: {name} sha256:{pypi_sha}")

        github_sha = github_shas.get(name)
        if github_sha and github_sha != pypi_sha:
            message = (
                f"PyPI and GitHub release artifact SHA-256 differ for {name}: "
                f"pypi={pypi_sha} github={github_sha}. Publish both channels from the same release workflow run "
                "when artifact parity is required."
            )
            if strict_artifact_match:
                raise SystemExit(message)
            print(f"WARNING: {message}", file=sys.stderr)

    print(f"PyPI version JSON reports: {version_json_version}")

    project_json = json.loads(fetch_url(PYPI_JSON_URL))
    json_version = project_json["info"]["version"]
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
    parser.add_argument(
        "--strict-artifact-match",
        action="store_true",
        help="fail when GitHub release asset SHA-256 values differ from PyPI artifact SHA-256 values",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    version = args.version.removeprefix("v")
    tag = f"v{version}"

    require_tools("gh", "git")
    github_shas = check_github_release(version, tag, args.repo)
    check_pypi(version, github_shas, strict_artifact_match=args.strict_artifact_match)
    print("Post-publish checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
