# Release

Use this checklist before publishing a public release.

Use the repository virtualenv when it exists. The examples use `python3`, but
substitute `.venv/bin/python` in the local checkout when available.

## Verify Metadata

Confirm the repository URLs in `pyproject.toml` match the actual GitHub repository.

```bash
git remote -v
gh auth status
```

## Prepare Version Metadata

Set the release version once for the shell session:

```bash
version=X.Y.Z
tag=v$version
```

Mini EQ uses SemVer-style `X.Y.Z` versions, but it is still pre-`1.0.0`.
Use patch releases for fixes and listing/package polish, and minor releases
for user-facing features or workflow changes. Do not claim strict SemVer
stability until the app behavior, D-Bus control state, preset data, and Shell
extension contract are stable enough to document as a public API.

Update every version-bearing file before building artifacts:

- `pyproject.toml`
- `CHANGELOG.md`
- `data/io.github.bhack.mini-eq.metainfo.xml`

`mini_eq.__version__` is derived from release metadata and should not be bumped
manually.

If the public app screenshot changed, make the AppStream screenshot URL point at
the same release tag. `docs/screenshots/mini-eq.png` is the README and
AppStream/Flathub screenshot, so it should remain a light/default app-window
screenshot. `docs/screenshots/mini-eq-dark.png` may be listed as a second
AppStream/Flathub screenshot to preview dark style support, but it should not
replace the light/default screenshot as the first/default image.
`docs/social-preview.png` is only for GitHub/social previews and may use branded
promotional styling. Then run the version metadata test:

```bash
python3 -m pytest tests/test_version_metadata.py -q
```

If the app icon SVG changed, visually inspect its 128, 64, and 32 px renders
on light and dark backgrounds before building the release.

The app icon is installed as a scalable SVG plus a symbolic SVG. Do not add
generated PNG app icons unless a target platform specifically needs them.

For the full local release preflight, run:

```bash
python3 tools/release_preflight.py
```

The preflight prints a GNOME Shell extension upload notice when the publishable
extension source changed since the relevant release tag. If it reports that an
upload may be needed, test the extension and upload the generated zip to
extensions.gnome.org after the release is ready.

## Check Locally

```bash
python3 -m pip install -e '.[dev]'
python3 -m ruff check .
python3 -m ruff format --check .
python3 -m pytest -q
python3 -m mini_eq --check-deps
```

If the GNOME Shell extension changed, check the app/extension D-Bus contract
and build the review/upload bundle:

```bash
python3 tools/check_gnome_shell_extension.py
tools/pack_gnome_shell_extension.sh
```

Only upload the generated extension zip after testing every GNOME Shell version
listed in `extensions/gnome-shell/mini-eq@bhack.github.io/metadata.json`. Do
not list future Shell versions.

If extensions.gnome.org asks for an extension screenshot, capture it from the
nested fake-control Shell documented in `extensions/gnome-shell/README.md` so no
real desktop, device, account, or path details are exposed.

## Flatpak Runtime Smoke

Run this after installing the local Flatpak build, and before release
publication or Flathub handoff, whenever PipeWire routing, WirePlumber access,
Flatpak permissions, runtime dependencies, or shutdown behavior changed. This
check temporarily routes a silent host PipeWire stream through Mini EQ and then
verifies that the stream is restored when the app exits, so keep it separate
from the generic preflight.

```bash
flatpak remote-add --if-not-exists --user flathub https://dl.flathub.org/repo/flathub.flatpakrepo
flatpak install --user -y flathub org.flatpak.Builder//stable
flatpak run --command=flathub-build org.flatpak.Builder --install io.github.bhack.mini-eq.yaml
python3 tools/check_flatpak_runtime.py --app-ref io.github.bhack.mini-eq//master
```

For shutdown changes, also run the installed Flatpak interactively, enable
system-wide EQ, close the GTK window, and confirm that the app exits without a
crash and streams are restored:

```bash
flatpak run io.github.bhack.mini-eq//master --auto-route
```

There is also an experimental non-blocking GitHub Actions path for this check:
manually dispatch the `CI` workflow with `flatpak_runtime_smoke=true` and, when
iterating only on the smoke harness, `smoke_only=true`. For quick harness
iterations against the published Flathub app, use `flatpak_runtime_build=false`,
`flatpak_runtime_install_remote=true`, and the default blank
`flatpak_runtime_app_ref` so the harness runs the installed Flathub ref. Set
`flatpak_runtime_expected_version` when using the published app, because Flathub
metadata can lag after an update. Leave `flatpak_runtime_build=true` for any
release check that must test current source or the local manifest. Use hosted
smoke as the validation for harness-only CI changes and as extra release signal;
keep the local runtime smoke as the release check when app/runtime routing
behavior changed.

## Build

```bash
rm -rf dist/
python3 -m build
python3 -m twine check dist/*
```

## GitHub Release Automation

Use the `Release` workflow from GitHub Actions after the local checks pass.
The default `dry_run=true` mode builds the wheel and sdist, runs
`twine check dist/*`, and uploads `dist/*` as workflow artifacts without
creating a GitHub release or publishing to a package index.

When creating a release, update the project version first, then dispatch the
workflow with `dry_run=false`, `create_github_release=true`, and
`tag_name=vX.Y.Z`. The workflow creates a GitHub release with generated notes
and attaches the built wheel and sdist. Keep `draft=true` for the first run,
review the generated notes and assets on GitHub, then publish the draft
manually.

Draft GitHub release assets use temporary `untagged-*` download URLs. Publish
the draft before using release asset URLs in the Flathub manifest or other
public metadata.

Generated GitHub release notes can be sparse for direct release commits. Review
and edit the draft notes before publishing the GitHub release.

Set `publish_testpypi=true` only after the `testpypi` GitHub environment and
TestPyPI trusted publisher are configured. The TestPyPI job uses
`pypa/gh-action-pypi-publish` with OIDC and does not use API tokens. Keep PyPI
publishing separate until TestPyPI installs have been validated. For a
TestPyPI-only validation run, use `dry_run=false`,
`create_github_release=false`, and `publish_testpypi=true`.

Set `publish_pypi=true` only after the `pypi` GitHub environment and PyPI
trusted publisher are configured. The PyPI job also uses
`pypa/gh-action-pypi-publish` with OIDC and does not use API tokens. Keep the
`pypi` environment protected with required review before publishing production
packages.

Keep owner-specific workflow dispatch commands, environment approvals, and
local release sequencing in an ignored repo-local skill rather than in public
documentation.

## Security

Before publishing release artifacts, run a focused leak scan:

```bash
git rev-list --count HEAD
git ls-remote --heads origin
git ls-remote --tags origin
leak_pattern='(/home/|/Users/|secret|token|api[_-]?key|github_pat|BEGIN (RSA|OPENSSH|PRIVATE) KEY)'
git grep -n -I -E "$leak_pattern" HEAD -- . \
  ':(exclude)*.png' \
  ':(exclude)AGENTS.md' \
  ':(exclude)docs/release.md' \
  ':(exclude)tools/release_preflight.py'
```

Keep these GitHub security features enabled in Settings > Advanced Security:

- Dependency graph
- Dependabot alerts
- Dependabot security updates
- Dependabot version updates
- Secret scanning
- Push protection
- Private vulnerability reporting
- CodeQL code scanning

Then protect `main` with a branch protection rule or ruleset that requires the
`test`, `wireplumber-0-4-compat`, `flatpak`, and `dependency-review` status
checks before merging.

## Test The Wheel

Use `--system-site-packages` so the test environment can see distro-provided GI bindings.

```bash
python3 -m venv --system-site-packages /tmp/mini-eq-wheel-test
/tmp/mini-eq-wheel-test/bin/python -m pip install --upgrade pip
/tmp/mini-eq-wheel-test/bin/python -m pip install dist/*.whl
/tmp/mini-eq-wheel-test/bin/mini-eq --check-deps
/tmp/mini-eq-wheel-test/bin/mini-eq --help
```

## Publish

For GitHub releases, dispatch the `Release` workflow after the local checks
above pass. Verify that the README, package URLs, issue tracker, license, and
screenshots render correctly without a logged-in GitHub session.

Validate package-index publishing on TestPyPI before enabling PyPI publishing.
For production PyPI publishing, dispatch the workflow with `dry_run=false`,
`create_github_release=true`, `tag_name=vX.Y.Z`, and `publish_pypi=true`.
Use Trusted Publishing/OIDC and the separate `pypi` environment rather than
long-lived API tokens.

After the workflow completes:

```bash
gh release view vX.Y.Z --repo bhack/mini-eq --json tagName,isDraft,isPrerelease,assets,url
curl -fsSL https://pypi.org/pypi/mini-eq/json | jq -r '.info.version'
git ls-remote --tags origin vX.Y.Z
```

Publish the draft GitHub release after reviewing its notes and assets. Fetch
tags after publishing if the workflow created the release tag remotely:

```bash
git fetch --tags origin
```

Then run the post-publish verifier:

```bash
python3 tools/release_post_publish.py X.Y.Z
```

This confirms that the GitHub release is no longer a draft, asset URLs use the
stable `vX.Y.Z` tag instead of temporary `untagged-*` draft URLs, the remote tag
exists, PyPI can see the version, and the downloaded source archive SHA-256
matches the GitHub release asset digest. Use the printed source archive SHA-256
for the Flathub repository update.

## Flathub Handoff

Keep the detailed Flathub packaging procedure in `docs/flathub.md` and in the
Flathub packaging repository. From this upstream repository, the public release
handoff is:

1. Confirm the GitHub release is published, not draft.
2. Compute or verify the release source archive SHA-256.
3. Update the sibling Flathub repository manifest to the published release URL
   and SHA-256.
4. Run Flathub manifest lint and a download-only build in the Flathub
   repository.
5. Compare the two manifests for unintended drift:

   ```bash
   python3 tools/check_flathub_manifest_drift.py
   ```

6. Open a Flathub PR against `flathub/io.github.bhack.mini-eq`.
7. Wait for the PR status to reach `success / Build ready` before merging. A
   temporary `pending / Committing build...` status after the build pipeline
   succeeds is normal while Flathub commits the test build.
