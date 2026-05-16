#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    from tools import check_flathub_manifest_drift, release_status
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    import check_flathub_manifest_drift
    import release_status


def release_source_url(info: release_status.ReleaseInfo, repo: str) -> str:
    return f"https://github.com/{repo}/releases/download/{info.tag}/{info.sdist_name}"


def replacement_source_block(url: str, sha256: str) -> list[str]:
    return [
        "    sources:\n",
        "      - type: archive\n",
        f"        url: {url}\n",
        f"        sha256: {sha256}\n",
    ]


def update_manifest_source(manifest: Path, *, url: str, sha256: str) -> bool:
    lines = manifest.read_text(encoding="utf-8").splitlines(keepends=True)
    source_start, source_end, current_source = check_flathub_manifest_drift.mini_eq_source_block(lines, manifest)
    replacement = replacement_source_block(url, sha256)
    if current_source == replacement:
        return False
    manifest.write_text("".join(lines[:source_start] + replacement + lines[source_end:]), encoding="utf-8")
    return True


def pr_body(version: str, *, release_url: str, url: str, sha256: str) -> str:
    return f"""Updates Mini EQ to {version}.

Upstream release: {release_url}
Source archive: {url}
SHA-256: {sha256}

Validation:
- [ ] `flatpak-builder-lint manifest`
- [ ] `flatpak-builder --download-only`
- [ ] Mini EQ release status
- [ ] Manifest drift check
"""


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare the Flathub Mini EQ manifest for a published release.")
    parser.add_argument("version", help="release version, for example 0.8.2 or v0.8.2")
    parser.add_argument("flathub_manifest", type=Path, help="path to the Flathub io.github.bhack.mini-eq.yaml")
    parser.add_argument("--repo", default=release_status.DEFAULT_REPO, help="GitHub repo, default: bhack/mini-eq")
    parser.add_argument("--sha256", help="known source archive SHA-256; otherwise the release asset is downloaded")
    parser.add_argument("--pr-body", type=Path, help="optional path to write a Flathub PR body")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    info = release_status.release_info(args.version)
    repo = release_status.validate_github_repo(args.repo)
    url = release_source_url(info, repo)
    sha256 = args.sha256 or release_status.sha256_url(url)
    upstream_release_url = f"https://github.com/{repo}/releases/tag/{info.tag}"

    changed = update_manifest_source(args.flathub_manifest, url=url, sha256=sha256)
    body = pr_body(info.version, release_url=upstream_release_url, url=url, sha256=sha256)
    if args.pr_body is not None:
        args.pr_body.write_text(body, encoding="utf-8")

    print(f"Flathub manifest: {args.flathub_manifest}")
    print(f"Mini EQ source URL: {url}")
    print(f"Mini EQ source SHA-256: {sha256}")
    print(f"Updated: {str(changed).lower()}")
    if args.pr_body is not None:
        print(f"PR body: {args.pr_body}")
    else:
        print("\nPR body:\n")
        print(body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
