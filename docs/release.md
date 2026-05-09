# Release

Use this checklist before publishing a public Mini EQ release. Keep
owner-specific workflow dispatch commands, deployment approvals, and local
checkout paths in the ignored release skill, not in public documentation.

Use the repository virtualenv when it exists. The examples use `python3`, but
substitute `.venv/bin/python` in the local checkout when available.

## Gate Map

Run the narrowest gate that covers the release risk:

- **Always:** version metadata, release preflight, GitHub release dry run or
  release workflow, TestPyPI install validation, PyPI publish, post-publish
  verification, then Flathub stable PR.
- **When PipeWire, routing, analyzer, Flatpak permissions, runtime dependencies,
  or shutdown changed:** local Flatpak install, Flatpak runtime smoke, and
  interactive real-music testing before merge or release.
- **When background mode, Start at Login, hidden-window lifecycle, or Shell
  control changed:** one clean-permission Flatpak portal smoke in a real GNOME
  session.
- **When the GNOME Shell extension source changed:** run the extension checker,
  build the review zip, test the supported Shell versions, and upload after the
  app release is ready.
- **Only for high-risk release candidates:** use TestPyPI plus the Flathub
  `beta` branch for broader install testing before final PyPI and Flathub
  stable.

TestPyPI is package-index validation. It is not a user beta channel. Flathub PR
test builds are the normal stable handoff validation. Flathub beta is a
temporary user-installable Flatpak beta, not a permanent second release line.

## Prepare Version

Set the release version once for the shell session:

```bash
version=X.Y.Z
tag=v$version
```

Mini EQ is pre-`1.0.0`. Use patch releases for fixes and listing/package polish,
and minor releases for user-facing features or workflow changes. Do not claim
strict SemVer stability until the app behavior, D-Bus control state, preset
data, and Shell extension contract are stable enough to document as a public
API.

Update every version-bearing file:

- `pyproject.toml`
- `CHANGELOG.md`
- `data/io.github.bhack.mini-eq.metainfo.xml`

`mini_eq.__version__` is derived from release metadata and should not be bumped
manually.

If screenshots changed, keep `docs/screenshots/mini-eq.png` as the first/default
README and AppStream screenshot. It should be just the app window in the
platform-default light appearance. `docs/screenshots/mini-eq-dark.png` may be a
second screenshot. `docs/social-preview.png` is only for GitHub/social previews.

Run the version metadata check:

```bash
python3 -m pytest tests/test_version_metadata.py -q
```

If the app icon SVG changed, visually inspect its 128, 64, and 32 px renders on
light and dark backgrounds. Do not add generated PNG app icons unless a target
platform specifically needs them.

## Run Preflight

Prefer the containerized preflight. It keeps host machines clean while testing a
fresh venv, `pipewire-gobject` sdist build dependencies, package metadata, a
private PipeWire/WirePlumber session, the leak scan, and release smoke checks:

```bash
tools/run_release_preflight_container.sh
```

To include the Flathub handoff drift check, pass the publishing manifest path
explicitly:

```bash
MINI_EQ_FLATHUB_MANIFEST=/path/to/flathub/io.github.bhack.mini-eq.yaml \
  tools/run_release_preflight_container.sh
```

For dependency or Flatpak manifest migrations, stage the Flathub packaging
branch before final preflight; the drift check intentionally fails if the
Flathub manifest still has old bundled dependencies or permissions.

To run preflight directly on Debian/Ubuntu hosts, install the build stack needed
by the `pipewire-gobject` sdist first:

```bash
sudo apt install build-essential gobject-introspection libgirepository1.0-dev libglib2.0-dev libpipewire-0.3-dev pkg-config
python3 tools/release_preflight.py
```

The preflight prints change-aware notices for GNOME Shell extension upload,
Flatpak runtime smoke, and background portal smoke. Treat those notices as
release gates when they apply; the generic preflight deliberately does not
mutate the host audio graph.

## Runtime Checks

Run this after installing the local Flatpak build whenever PipeWire routing,
`pipewire-gobject` access, Flatpak permissions, runtime dependencies, or
shutdown behavior changed:

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

For background portal changes, run one clean-permission Flatpak smoke in a real
GNOME session:

```bash
flatpak permission-remove background background io.github.bhack.mini-eq || true
flatpak run --command=flathub-build org.flatpak.Builder --install io.github.bhack.mini-eq.yaml
flatpak run io.github.bhack.mini-eq//master
```

Then enable **Keep Running in Background**, approve the portal prompt, enable
**Start at Login**, close the window, and confirm the app stays available from
the GNOME Shell extension. Use the Shell extension's **Show Mini EQ** and
**Quit Mini EQ** actions to verify hidden-window recovery and full exit.

For PipeWire routing, analyzer capture, or filter-chain runtime changes, also
run the app interactively with real music before merging the PR to `main` or
publishing a release. Exercise enable/disable, output switching, preset
changes, analyzer display, shutdown, and stream restoration against the actual
desktop audio graph.

Before the manual real-music pass, run the opt-in live UI smoke. It starts a
private PipeWire/WirePlumber graph, synthetic playback, nested headless GNOME
Shell, the real Mini EQ GTK process, and AT-SPI UI controls:

```bash
.venv/bin/python tools/check_live_ui_runtime.py --timeout 35 --cycles 1
MINI_EQ_RUN_LIVE_UI=1 .venv/bin/python -m pytest tests/test_mini_eq_live_ui_runtime.py -q
```

There is an optional hosted Flatpak runtime smoke path in the `CI` workflow.
Use it as extra signal or for smoke-harness work; keep the local runtime smoke
as the release check when app/runtime routing behavior changed.

## Package Channels

Use the `Release` workflow from GitHub Actions after local checks pass. Keep
`dry_run=true` for packaging workflow changes. For real releases, keep the
GitHub release as a draft first, review generated notes and assets, and publish
the draft only after package-index checks pass.

Use Trusted Publishing/OIDC for TestPyPI and PyPI. Do not use long-lived PyPI
API tokens. Keep the `pypi` environment protected with required review before
production publishing.

Install-check TestPyPI artifacts with PyPI enabled for dependencies and pin the
exact version being validated:

```bash
python3 -m venv --system-site-packages /tmp/mini-eq-testpypi
/tmp/mini-eq-testpypi/bin/python -m pip install --upgrade pip
/tmp/mini-eq-testpypi/bin/python -m pip install \
  --index-url https://test.pypi.org/simple/ \
  --extra-index-url https://pypi.org/simple/ \
  "mini-eq==$version"
/tmp/mini-eq-testpypi/bin/mini-eq --check-deps
```

Do not add PyGObject as a Mini EQ PyPI dependency. Keep it a distro/runtime
requirement (`python3-gi`, `python3-gobject`, etc.) so it matches the host
GObject-Introspection and GTK stack.

## Post-Publish

After publishing the GitHub release:

```bash
gh release view "$tag" --repo bhack/mini-eq --json tagName,isDraft,isPrerelease,assets,url
git fetch --tags origin
curl -fsSL https://pypi.org/pypi/mini-eq/json | jq -r '.info.version'
git ls-remote --tags origin "$tag"
python3 tools/release_post_publish.py "$version"
```

`tools/release_post_publish.py` verifies that the GitHub release is no longer a
draft, asset URLs use the stable tag instead of temporary `untagged-*` draft
URLs, the remote tag exists, PyPI can see the version, and the downloaded source
archive SHA-256 matches the GitHub release asset digest. Use the printed source
archive SHA-256 for the Flathub repository update.

## Flathub Handoff

Keep the detailed Flathub packaging procedure in `docs/flathub.md` and in the
Flathub packaging repository. From this upstream repository, the release handoff
is maintainer-owned:

1. Confirm the GitHub release is published, not draft.
2. Compute or verify the release source archive SHA-256.
3. Update the Flathub packaging repository manifest to the published release URL
   and SHA-256.
4. Run Flathub manifest lint and a download-only build in the Flathub
   repository.
5. Compare the two manifests and synced dependency files for unintended drift:

   ```bash
   python3 tools/check_flathub_manifest_drift.py \
     io.github.bhack.mini-eq.yaml \
     /path/to/flathub/io.github.bhack.mini-eq.yaml
   ```

6. As the maintainer, open a Flathub PR against
   `flathub/io.github.bhack.mini-eq`.
7. Wait for the PR status to reach `success / Build ready` before merging. A
   temporary `pending / Committing build...` status after the build pipeline
   succeeds is normal while Flathub commits the test build.
8. Install and run the temporary Flathub PR build when runtime behavior changed.

Use the Flathub `beta` branch only when a release candidate needs broader
Flatpak testing before the stable update:

```bash
flatpak remote-add --if-not-exists flathub-beta https://flathub.org/beta-repo/flathub-beta.flatpakrepo
flatpak install flathub-beta io.github.bhack.mini-eq
flatpak run --branch=beta io.github.bhack.mini-eq
```

## Security

The release preflight includes a focused privacy and credential scan across
`HEAD`, tracked worktree changes, and untracked non-ignored text files. It does
not replace GitHub secret scanning, push protection, or a deeper local scanner
when release history or generated artifacts look suspicious:

```bash
gitleaks git --no-banner --redact .
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

Protect `main` with a branch protection rule or ruleset that requires the
`test`, `tooling`, `flatpak`, `dependency-review`, and CodeQL status checks
before merging.
