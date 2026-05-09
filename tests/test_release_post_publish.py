from __future__ import annotations

import json
import subprocess

import pytest

from tools import release_post_publish


def pypi_version_payload(version: str, *, sdist_sha: str, wheel_sha: str) -> bytes:
    return json.dumps(
        {
            "info": {"version": version},
            "urls": [
                {
                    "filename": release_post_publish.SDIST_NAME.format(version=version),
                    "digests": {"sha256": sdist_sha},
                },
                {
                    "filename": release_post_publish.WHEEL_NAME.format(version=version),
                    "digests": {"sha256": wheel_sha},
                },
            ],
        }
    ).encode()


def test_post_publish_checks_exact_pypi_version_and_warns_on_artifact_mismatch(monkeypatch, capsys) -> None:
    version = "0.7.0"
    sdist_name = release_post_publish.SDIST_NAME.format(version=version)
    wheel_name = release_post_publish.WHEEL_NAME.format(version=version)

    def fake_fetch_url(url: str, *, method: str = "GET") -> bytes:
        assert method == "GET"
        if url == release_post_publish.PYPI_VERSION_JSON_URL.format(version=version):
            return pypi_version_payload(version, sdist_sha="pypi-sdist", wheel_sha="same-wheel")
        if url == release_post_publish.PYPI_JSON_URL:
            return json.dumps({"info": {"version": version}}).encode()
        raise AssertionError(f"unexpected URL: {url}")

    monkeypatch.setattr(release_post_publish, "fetch_url", fake_fetch_url)

    release_post_publish.check_pypi(
        version,
        {sdist_name: "github-sdist", wheel_name: "same-wheel"},
        strict_artifact_match=False,
    )

    captured = capsys.readouterr()
    assert "PyPI version JSON reports: 0.7.0" in captured.out
    assert "WARNING: PyPI and GitHub release artifact SHA-256 differ" in captured.err


def test_post_publish_can_require_pypi_and_github_artifact_match(monkeypatch) -> None:
    version = "0.7.0"
    sdist_name = release_post_publish.SDIST_NAME.format(version=version)
    wheel_name = release_post_publish.WHEEL_NAME.format(version=version)

    def fake_fetch_url(url: str, *, method: str = "GET") -> bytes:
        assert method == "GET"
        if url == release_post_publish.PYPI_VERSION_JSON_URL.format(version=version):
            return pypi_version_payload(version, sdist_sha="pypi-sdist", wheel_sha="same-wheel")
        raise AssertionError(f"unexpected URL: {url}")

    monkeypatch.setattr(release_post_publish, "fetch_url", fake_fetch_url)

    with pytest.raises(SystemExit, match="PyPI and GitHub release artifact SHA-256 differ"):
        release_post_publish.check_pypi(
            version,
            {sdist_name: "github-sdist", wheel_name: "same-wheel"},
            strict_artifact_match=True,
        )


def test_post_publish_reads_stable_github_release_asset_hashes(monkeypatch) -> None:
    version = "0.7.0"
    tag = f"v{version}"
    sdist_name = release_post_publish.SDIST_NAME.format(version=version)
    wheel_name = release_post_publish.WHEEL_NAME.format(version=version)

    monkeypatch.setattr(
        release_post_publish,
        "gh_json",
        lambda _command: {
            "tagName": tag,
            "isDraft": False,
            "isPrerelease": False,
            "url": f"https://github.com/bhack/mini-eq/releases/tag/{tag}",
            "assets": [
                {
                    "name": sdist_name,
                    "url": f"https://github.com/bhack/mini-eq/releases/download/{tag}/{sdist_name}",
                    "digest": "sha256:sdist-sha",
                },
                {
                    "name": wheel_name,
                    "url": f"https://github.com/bhack/mini-eq/releases/download/{tag}/{wheel_name}",
                    "digest": "sha256:wheel-sha",
                },
            ],
        },
    )
    monkeypatch.setattr(
        release_post_publish,
        "sha256_url",
        lambda url: "sdist-sha" if url.endswith(".tar.gz") else "wheel-sha",
    )
    monkeypatch.setattr(
        release_post_publish,
        "run",
        lambda command: subprocess.CompletedProcess(command, 0, stdout=f"abc123\trefs/tags/{tag}\n", stderr=""),
    )

    assert release_post_publish.check_github_release(version, tag, "bhack/mini-eq") == {
        sdist_name: "sdist-sha",
        wheel_name: "wheel-sha",
    }
