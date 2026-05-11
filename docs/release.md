# Release

Use this checklist before publishing a public Mini EQ release. Keep
owner-specific workflow dispatch commands, deployment approvals, and local
checkout paths in the ignored release skill, not in public documentation.

The examples use `python3`; use the repository virtualenv when your checkout
has one.

## Gate Map

Run the narrowest gate that covers the release risk:

- **Always:** version metadata, release preflight, GitHub release dry run or
  release workflow, TestPyPI install validation, PyPI publish, post-publish
  verification, then Flathub stable PR.
- **When application code, UI code, or runtime-sensitive packaging changed:**
  live GTK/AT-SPI/PipeWire smoke. Public release workflow dispatches run this
  as a blocking job for app-sensitive changes before building publishable
  artifacts.
- **When PipeWire, routing, analyzer, Flatpak permissions, runtime dependencies,
  or shutdown changed:** local Flatpak install, Flatpak runtime smoke, and
  interactive real-music testing before merge or release. Public release
  workflow dispatches also run the isolated Flatpak routing smoke as a blocking
  job when runtime-sensitive files changed since the previous release tag.
- **When background mode, Start at Login, hidden-window lifecycle, or Shell
  control changed:** one clean-permission Flatpak portal smoke in a real GNOME
  session.
- **When preset, output, startup, routing, monitor, or inspector UI behavior
  changed:** run the workflow usability gate below before release.
- **When the GNOME Shell extension source changed:** run the extension checker,
  build the review zip, test the supported Shell versions, and upload after the
  app release is ready.
- **Only for high-risk release candidates:** use TestPyPI plus the Flathub
  `beta` branch for broader install testing before final PyPI and Flathub
  stable.

TestPyPI is package-index validation. It is not a user beta channel. Flathub PR
test builds are the normal stable handoff validation. Flathub beta is a
temporary user-installable Flatpak beta, not a permanent second release line.

## Workflow Usability Gate

Before releasing UI or state-machine changes, review the workflows as state
transitions, not as isolated controls. Every changed workflow should have a
single obvious current state, a reversible path, and no first-frame state
change after the window is shown.

For preset and output changes, cover these cases with unit tests when possible
and with AT-SPI or live smoke when they require real GTK behavior:

- Load, edit, reset to neutral, then reload the same saved preset from the
  preset loader. Keep revert-style actions for unsaved sources that are not in
  the preset library.
- Verify the preset loader does not pretend to be the running state: the visible
  running-curve label must distinguish neutral, exact saved preset, modified
  preset, and unsaved/imported curves.
- Import or create an unsaved curve, save it, reset it, and recover a neutral
  curve without deleting the only route back.
- Delete the loaded preset, delete or modify it outside the app, and keep the
  current curve understandable as an unsaved copy.
- Link, unlink, miss, and modify auto presets for both port-scoped and
  output-scoped targets.
- Set, miss, and clear the unmatched-output fallback preset.
- Change output while a curve is clean, modified, auto-applied, missing, or
  unavailable.
- Turn Monitor on/off and freeze/unfreeze it without leaving hidden frozen
  state behind.
- Start the app with auto/fallback preset and auto-route inputs and verify the
  visible window appears only after startup state is applied.
- Check Shell extension/D-Bus state after preset, output, background, and
  window-visibility changes.

AT-SPI tests should assert externally visible behavior: accessible names, roles,
checked state, sensitivity, and critical status labels. They should not depend
on widget internals when a unit test can cover the state transition directly.
When in doubt, add a small state-level unit test first, then one AT-SPI smoke
assertion for the visible contract.

The automated release gates are confidence checks, not a proof that every user
graph behaves correctly. Treat their claims narrowly:

- Unit and seam tests verify deterministic model, routing, metadata, and UI
  state transitions.
- The release preflight verifies source cleanliness, package build/install,
  dependency importability, metadata, and the full default pytest suite.
- The Flatpak routing smoke verifies the installed Flatpak can route and
  restore a synthetic stream in an isolated PipeWire/WirePlumber graph.
- The live UI smoke verifies the real GTK app can be driven through AT-SPI
  while PipeWire routing, output following, monitor capture, preset reset, and
  shutdown are exercised.
- Manual real-session audio testing is still required for changes that depend
  on host devices, real music playback, WirePlumber policy, or analyzer
  behavior users can perceive.

## Prepare Version

Set the release version once for the shell session:

```bash
version=X.Y.Z
tag=v$version
```

For routine metadata bumps, use the prepare helper and then review the diff:

```bash
python3 tools/prepare_release.py "$version" \
  --note "First user-facing release note." \
  --note "Second user-facing release note."
```

The helper only updates public version metadata: `pyproject.toml`,
`CHANGELOG.md`, the top AppStream release entry, and AppStream screenshot tag
URLs. It does not commit, tag, publish, or touch maintainer-local release state.

Mini EQ is pre-`1.0.0`. Use patch releases for fixes and listing/package polish,
and minor releases for user-facing features or workflow changes. Do not claim
strict SemVer stability until the app behavior, D-Bus control state, preset
data, and Shell extension contract are stable enough to document as a public
API.

`mini_eq.__version__` is derived from release metadata and should not be bumped
manually. If you edit release metadata by hand, keep `pyproject.toml`,
`CHANGELOG.md`, and `data/io.github.bhack.mini-eq.metainfo.xml` in sync.

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

Use the read-only release status dashboard whenever you need to see what is
already done and what is still pending:

```bash
python3 tools/release_status.py "$version"
```

To include a Flathub publishing manifest without documenting local checkout
layout, pass the manifest path explicitly:

```bash
python3 tools/release_status.py "$version" \
  --flathub-manifest /path/to/flathub/io.github.bhack.mini-eq.yaml
```

The dashboard is intentionally state-aware: unpublished GitHub/PyPI artifacts
are reported as pending, while metadata mismatches and artifact hash mismatches
are reported as failures.

The `CI` workflow runs `tools/release_status.py --no-network` when release
metadata, release docs, or release helper tests change. That catches local
version and AppStream drift without depending on GitHub, PyPI, or Flathub
network state. Networked artifact checks remain part of the explicit release
preflight and post-publish checks.

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

The preflight prints change-aware notices for GNOME Shell extension upload,
Flatpak runtime smoke, and background portal smoke. Treat those notices as
release gates when they apply; the generic preflight deliberately does not
mutate the host audio graph.

## Runtime Checks

Run a Flatpak runtime smoke whenever PipeWire routing, `pipewire-gobject`
access, Flatpak permissions, runtime dependencies, or shutdown behavior changed:

```bash
python3 tools/check_flatpak_runtime.py --app-ref <installed-app-ref>
```

For background portal changes, run one clean-permission Flatpak smoke in a real
GNOME session. Enable **Keep Running in Background**, approve the portal
prompt, enable **Start at Login**, close the window, and confirm the app stays
available from the GNOME Shell extension. Use the Shell extension's **Show Mini
EQ** and **Quit Mini EQ** actions to verify hidden-window recovery and full
exit.

For PipeWire routing, analyzer capture, or filter-chain runtime changes, also
run the app interactively with real music before release. Exercise
enable/disable, output switching, preset changes, analyzer display, shutdown,
and stream restoration against the actual desktop audio graph.

Before the manual real-music pass, run the live UI smoke. It starts a private
PipeWire/WirePlumber graph, synthetic playback, nested headless GNOME Shell,
the real Mini EQ GTK process, and AT-SPI UI controls:

```bash
python3 tools/check_live_ui_runtime.py --timeout 35 --cycles 1
MINI_EQ_RUN_LIVE_UI=1 python3 -m pytest tests/test_mini_eq_live_ui_runtime.py -q
```

The `Release` workflow runs this live UI smoke as a blocking job for app and UI
runtime-sensitive publish dispatches. The pytest wrapper remains opt-in for
local development so ordinary unit test runs stay fast and do not require
nested GNOME Shell or AT-SPI services.

There is an optional hosted Flatpak runtime smoke path in the `CI` workflow.
Use it as extra signal or for smoke-harness work; keep the local runtime smoke
as the release check when app/runtime routing behavior changed. The `Release`
workflow also runs release preflight as a blocking job and has its own blocking
copy of the Flatpak routing smoke and live UI smoke gates for public TestPyPI,
PyPI, and GitHub release dispatches.

## Package Channels

Use the `Release` workflow from GitHub Actions after local checks pass. Keep a
dry run for packaging workflow changes. Every package-index or release dispatch
must pass a tag that matches `pyproject.toml`.

For real releases, keep the GitHub release as a draft first, review generated
notes and assets, and publish the draft only after package-index checks pass.
After TestPyPI validation, prefer one production workflow dispatch that creates
the draft GitHub release and publishes to PyPI from the same built artifacts.
That keeps the GitHub release files and PyPI files byte-for-byte comparable.
Use a separate PyPI-only dispatch only as a recovery path, and document that it
creates a second build.

Use Trusted Publishing/OIDC for TestPyPI and PyPI. Do not use long-lived PyPI
API tokens. Keep the `pypi` environment protected with required review before
production publishing.

Install-check TestPyPI artifacts with PyPI enabled for dependencies and pin the
exact version being validated. Run this in an environment that has the
`pipewire-gobject` sdist build dependencies, distro GI bindings, and a reachable
PipeWire session. The release preflight container satisfies those requirements.

PyPI JSON and project pages can become visible before the Simple API used by
`pip` has fully propagated. If a just-published version is visible through
`https://pypi.org/pypi/mini-eq/<version>/json` but `pip install` still reports
only older versions, wait briefly and retry before treating it as a release
failure.

Do not add PyGObject as a Mini EQ PyPI dependency. Keep it a distro/runtime
requirement (`python3-gi`, `python3-gobject`, etc.) so it matches the host
GObject-Introspection and GTK stack.

## Post-Publish

After publishing the GitHub release:

```bash
python3 tools/release_status.py "$version"
python3 tools/release_post_publish.py "$version"
```

`tools/release_post_publish.py` verifies that the GitHub release is no longer a
draft, asset URLs use the stable tag instead of temporary `untagged-*` draft
URLs, the remote tag exists, PyPI can see the exact version, the expected PyPI
files exist, and downloaded GitHub release assets match their GitHub digest
metadata. It also compares GitHub release asset hashes with PyPI artifact
hashes and warns when they differ. Use `--strict-artifact-match` for releases
that were intentionally published from a single workflow build and should have
matching artifacts across channels.

Do not use draft release asset URLs for Flathub; use the printed source archive
SHA-256 after the GitHub release is published.

## Flathub Handoff

Keep the detailed Flathub packaging procedure in `docs/flathub.md` and in the
Flathub packaging repository. The release handoff is maintainer-owned:

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

6. Open the Flathub PR, wait for `success / Build ready`, and install the
   temporary PR build when runtime behavior changed.

Use the Flathub `beta` branch only when a release candidate needs broader
Flatpak testing before the stable update.

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
