# Flathub Maintenance

Use this note when maintaining the Mini EQ Flathub package.

## Current Status

- Mini EQ is accepted on Flathub as `io.github.bhack.mini-eq`.
- The app ID is verified through the GitHub login provider for `bhack`.
- The Flathub publishing repository is
  `https://github.com/flathub/io.github.bhack.mini-eq`.
- The upstream local Flatpak manifest is `io.github.bhack.mini-eq.yaml`. It is
  for local development and CI.
- Python Flatpak dependencies are generated in `python3-dependencies.yaml`
  with `flatpak-pip-generator`.
- The manifest builds in project CI and installs the desktop file, AppStream
  metadata, icons, licenses, PipeWire filter-chain module, WirePlumber
  introspection, JACK client bindings, and NumPy.
- `flatpak-builder-lint manifest io.github.bhack.mini-eq.yaml` passes locally.

## Repository Split

Keep the Flatpak packaging in both repositories, but keep the roles separate:

- In this upstream repository, `io.github.bhack.mini-eq.yaml` is a development
  and CI manifest. It builds the checked-out source tree directly.
- In the Flathub repository, `io.github.bhack.mini-eq.yaml` is the publishing
  manifest. It must point at an immutable public release archive and include
  the archive SHA-256.
- `python3-dependencies.yaml` and `flatpak/patches/` should normally stay in
  sync between the two repositories.
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

## Release Update Checklist

1. Finish the upstream release and confirm the GitHub release is not a draft.
2. Confirm the release is suitable for Flathub stable, not a nightly snapshot.
3. Download the published release source archive and compute or confirm its
   SHA-256.
4. In the Flathub repository, update the `mini-eq` module source to the new
   release URL and hash.
5. If the screenshot changed, update the MetaInfo screenshot URL to a release
   tag or commit URL before publishing.
6. Keep `python3-dependencies.yaml` unchanged unless Python dependencies
   changed. If dependencies changed, regenerate it and update both repositories.
7. Keep `flatpak/patches/wireplumber-0.5.14-tools-disabled-po.patch` available
   in the Flathub repository when the manifest references it.
8. Run the validation commands below.
9. Open a pull request against the Flathub repository's `master` branch.
10. Install and test the temporary PR build posted by Flathub when practical.
11. Merge only after the Flathub PR build and checks pass.
12. Watch the official build. Successful official builds are published
    automatically, but publication can lag depending on Flathub's backlog.
13. If the official build is held for moderation, answer the bot issue or
    moderator questions. Permission changes and critical AppStream field changes
    can trigger moderation.
14. Recheck the public listing and banner preview:
   - `https://flathub.org/en/apps/io.github.bhack.mini-eq`
   - `https://flathub.org/en/apps/io.github.bhack.mini-eq/bannerpreview`
15. If quality fixes landed, use the listing quality panel to request a
    re-review.

GitHub draft releases expose assets under temporary `untagged-*` URLs. Publish
the upstream GitHub release first, then use the stable asset URL:

```bash
curl -fsSL \
  https://github.com/bhack/mini-eq/releases/download/vX.Y.Z/mini_eq-X.Y.Z.tar.gz \
  | sha256sum
```

Before opening the PR, compare the upstream and Flathub manifests from the
upstream checkout:

```bash
python3 tools/check_flathub_manifest_drift.py
```

The command should report that the manifests match outside the Mini EQ source
stanza. Any other difference should be intentional and usually belongs in both
repositories.

The Flathub `master` branch is protected, so direct pushes are rejected. Push an
update branch and open a PR:

```bash
git switch -c update-X.Y.Z
git push -u origin update-X.Y.Z
gh pr create --repo flathub/io.github.bhack.mini-eq \
  --base master \
  --head update-X.Y.Z \
  --title 'Update mini-eq to X.Y.Z'
```

## Validation

Run upstream AppStream and desktop-file validation:

```bash
appstreamcli validate --no-net data/io.github.bhack.mini-eq.metainfo.xml
desktop-file-validate data/io.github.bhack.mini-eq.desktop
flatpak run --command=flatpak-builder-lint org.flatpak.Builder appstream data/io.github.bhack.mini-eq.metainfo.xml
```

Run manifest lint in whichever repository you are changing:

```bash
flatpak run --command=flatpak-builder-lint org.flatpak.Builder manifest io.github.bhack.mini-eq.yaml
```

Build with Flathub tooling and run the app:

```bash
flatpak remote-add --if-not-exists --user flathub https://dl.flathub.org/repo/flathub.flatpakrepo
flatpak run --command=flathub-build org.flatpak.Builder --install io.github.bhack.mini-eq.yaml
flatpak run io.github.bhack.mini-eq --check-deps
```

For a local source and full build check without installing the app:

```bash
flatpak run --command=flatpak-builder org.flatpak.Builder \
  --force-clean \
  --download-only \
  --install-deps-from=flathub \
  build-dir io.github.bhack.mini-eq.yaml
flatpak run --command=flatpak-builder org.flatpak.Builder \
  --force-clean \
  --install-deps-from=flathub \
  --repo=repo \
  build-dir io.github.bhack.mini-eq.yaml
```

If a `repo/` is produced, run:

```bash
flatpak run --command=flatpak-builder-lint org.flatpak.Builder repo repo
```

## Packaging Notes

- Mini EQ is an upstream-maintained GTK/Libadwaita graphical application.
- The app ID `io.github.bhack.mini-eq` matches the GitHub repository ownership.
- The app requires `xdg-run/pipewire-0` to create and use PipeWire audio nodes.
- The Flatpak bundles only the PipeWire filter-chain module and SPA builtin
  filter graph plugin needed inside the app process; it does not bundle or run
  a PipeWire daemon or session manager.
- WirePlumber is built for introspection compatibility, not as a bundled session
  daemon.
- Runtime licenses for bundled modules are installed under
  `/app/share/licenses/io.github.bhack.mini-eq`.
