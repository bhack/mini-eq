# Flathub Maintenance

Use this note when maintaining the Mini EQ Flathub package.

## Current Status

- Mini EQ is accepted on Flathub as `io.github.bhack.mini-eq`.
- The Flathub publishing repository is
  `https://github.com/flathub/io.github.bhack.mini-eq`.
- The upstream local Flatpak manifest is `io.github.bhack.mini-eq.yaml`. It is
  for local development and CI.
- Python Flatpak dependencies are generated in `python3-dependencies.yaml`
  with `flatpak-pip-generator`.
- The manifest builds in project CI and installs the desktop file, AppStream
  metadata, icons, licenses, PipeWire filter-chain module, pipewire-gobject,
  NumPy, and libebur128.
- PyGObject is supplied by the GNOME runtime's system Python/GI stack. Do not
  add it to `python3-dependencies.yaml`; that file is for bundled PyPI
  dependencies such as NumPy.
- `flatpak-builder-lint manifest io.github.bhack.mini-eq.yaml` passes locally.

## Repository Split

Keep the Flatpak packaging in both repositories, but keep the roles separate:

- In this upstream repository, `io.github.bhack.mini-eq.yaml` is a development
  and CI manifest. It builds the checked-out source tree directly.
- In the Flathub repository, `io.github.bhack.mini-eq.yaml` is the publishing
  manifest. It must point at an immutable public release archive and include
  the archive SHA-256.
- `python3-dependencies.yaml` should normally stay in sync between the two
  repositories.
- The Flathub repository's `master` branch is the source for the published
  `stable` Flatpak ref. Use pull requests for changes to protected publishing
  branches.

The upstream manifest uses:

```yaml
- type: dir
  path: .
```

That is correct for local CI. The Flathub manifest should use a release source
instead:

```yaml
- type: archive
  url: https://github.com/bhack/mini-eq/releases/download/vX.Y.Z/mini_eq-X.Y.Z.tar.gz
  sha256: <release archive sha256>
```

Do not hand-edit bundled application source files in the Flathub repository.
Fix application metadata, desktop files, icons, and source code upstream, cut a
release, then update the Flathub manifest to the new release archive.

Flathub publishing PRs are maintainer-owned. Automated tools may prepare local
diffs, validation output, and handoff notes, but a maintainer should review the
packaging branch and open, submit, and merge the Flathub PR manually.

## Release Handoff

Use `docs/release.md` for the upstream release sequence. For Flathub, publish
the GitHub release first, then update the Flathub manifest to the stable
release archive and SHA-256.

Before opening the PR, compare the upstream and Flathub manifests and synced
dependency files:

```bash
python3 tools/check_flathub_manifest_drift.py \
  io.github.bhack.mini-eq.yaml \
  /path/to/flathub/io.github.bhack.mini-eq.yaml
```

The command should report that the manifests and dependency files match outside
the Mini EQ source stanza. Any other difference should be intentional and
usually belongs in both repositories.

The release status dashboard can also verify the Flathub manifest's release URL
and SHA-256 once the GitHub release assets are published:

```bash
python3 tools/release_status.py X.Y.Z \
  --flathub-manifest /path/to/flathub/io.github.bhack.mini-eq.yaml
```

The containerized release preflight runs the same drift check when
`MINI_EQ_FLATHUB_MANIFEST` points at the Flathub publishing manifest. For
dependency or permission migrations, keep the Flathub packaging checkout on the
staged update branch before final upstream preflight; otherwise the drift check
will correctly fail against the older stable manifest.

The Flathub `master` branch is protected, so use a branch and pull request for
publishing manifest updates. Keep local checkout paths, branch naming habits,
and owner-specific PR commands in ignored repo-local runbooks.

## Validation

Run upstream metadata validation:

```bash
appstreamcli validate --no-net data/io.github.bhack.mini-eq.metainfo.xml
desktop-file-validate data/io.github.bhack.mini-eq.desktop
```

Run manifest lint in whichever repository you are changing:

```bash
flatpak run --command=flatpak-builder-lint org.flatpak.Builder manifest io.github.bhack.mini-eq.yaml
```

Build with Flathub tooling and run the app when packaging or runtime behavior
changed:

```bash
flatpak remote-add --if-not-exists --user flathub https://dl.flathub.org/repo/flathub.flatpakrepo
flatpak run --command=flathub-build org.flatpak.Builder --install io.github.bhack.mini-eq.yaml
flatpak run io.github.bhack.mini-eq --check-deps
```

When routing, PipeWire access, Flatpak permissions, runtime dependencies, or
shutdown behavior changed, also run the upstream runtime smoke test against the
installed local build before opening or merging the Flathub PR:

```bash
python3 tools/check_flatpak_runtime.py --app-ref io.github.bhack.mini-eq//master
```

Use Flathub PR test builds for normal release handoff validation. They install
as the Flatpak `test` branch, so target that branch explicitly:

```bash
python3 tools/check_flatpak_runtime.py --app-ref io.github.bhack.mini-eq//test
```

Use the Flathub `beta` branch only for release-candidate or high-risk changes
that need a user-installable Flatpak before the stable update. Keep it
temporary and move successful candidates to stable after the test period.

Local repo lint can report screenshot mirroring errors when the generated repo
does not include Flathub's mirrored screenshot refs. If those are the only repo
lint errors, confirm the AppStream screenshot URLs point at an immutable tag or
commit and are reachable; then treat the Flathub PR build's `Build ready`
status as the authoritative screenshot-mirroring check.

## Packaging Notes

- Mini EQ is an upstream-maintained GTK/Libadwaita graphical application.
- The app ID `io.github.bhack.mini-eq` matches the GitHub repository ownership.
- The Flatpak is Wayland-only. Do not add X11 fallback permissions unless the
  release intentionally trades the extra screen-contents access warning for X11
  session support.
- The app requires `xdg-run/pipewire-0` to create and use PipeWire audio nodes.
- PyGObject comes from `org.gnome.Platform`; bundling it from PyPI would risk
  mismatches with the runtime GLib, GTK, and GObject-Introspection stack.
- The Flatpak bundles only the PipeWire filter-chain module and SPA builtin
  filter graph plugin needed inside the app process; it does not bundle or run
  a PipeWire daemon or session manager.
- pipewire-gobject is bundled for app-facing PipeWire access; WirePlumber remains
  a host session manager, not a bundled Flatpak daemon.
- When updating bundled pipewire-gobject, pin a published upstream tag plus its
  peeled commit in the upstream manifest, then keep the Flathub manifest in sync
  during the release handoff.
- Runtime licenses for bundled modules are installed under
  `/app/share/licenses/io.github.bhack.mini-eq`.
