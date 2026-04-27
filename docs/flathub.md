# Flathub Preparation

Use this note when preparing a Flathub submission for Mini EQ.

## Current Status

- The upstream Flatpak manifest is `io.github.bhack.mini-eq.json`.
- The manifest builds in project CI and installs the desktop file, AppStream
  metadata, icons, licenses, PipeWire filter-chain module, WirePlumber
  introspection, JACK client bindings, and NumPy.
- `flatpak-builder-lint manifest io.github.bhack.mini-eq.json` passes locally.
- The GitHub `v0.1.1` release is published, and PyPI has `mini-eq==0.1.1`.

## Submission Constraints

Do not open or automate the Flathub submission pull request from Codex or other
AI tooling. Flathub's author requirements prohibit AI-generated or automated
submission pull requests and warn that excessive AI-generated content may close
a review without normal review.

Flathub submissions should contain only the manifest and required packaging
files. Do not include Mini EQ source code or generated build artifacts in the
Flathub submission repository.

The upstream manifest currently uses:

```json
{
  "type": "dir",
  "path": "."
}
```

That is correct for local CI, but the Flathub submission copy should point at a
public source release instead, for example a `v0.1.1` GitHub archive with its
SHA-256 hash.

Mini EQ also needs a clear review note because it is a graphical desktop audio
application with host PipeWire/WirePlumber integration. Flathub policy calls out
system utilities and host-dependent applications as review risks. The submission
should explain that Mini EQ is a user-facing GTK equalizer, why PipeWire access
is required, and which functionality is expected to work inside the sandbox.

## Pre-Submission Checklist

1. Confirm the latest GitHub release is not marked as a draft.
2. Confirm the release is suitable for Flathub stable, not a nightly snapshot.
3. Prepare a Flathub submission manifest from `io.github.bhack.mini-eq.json`.
4. Replace the `mini-eq` module source with the public release archive and hash.
5. Include `flatpak/patches/wireplumber-0.5.14-tools-disabled-po.patch` in the
   submission, preserving the manifest's patch path or adjusting it consistently.
6. Run:

```bash
appstreamcli validate --no-net data/io.github.bhack.mini-eq.metainfo.xml
desktop-file-validate data/io.github.bhack.mini-eq.desktop
flatpak run --command=flatpak-builder-lint org.flatpak.Builder manifest io.github.bhack.mini-eq.json
```

7. Build with Flathub tooling and run the app:

```bash
flatpak remote-add --if-not-exists --user flathub https://dl.flathub.org/repo/flathub.flatpakrepo
flatpak run --command=flathub-build org.flatpak.Builder --install io.github.bhack.mini-eq.json
flatpak run io.github.bhack.mini-eq --check-deps
```

8. If a `repo/` is produced, run:

```bash
flatpak run --command=flatpak-builder-lint org.flatpak.Builder repo repo
```

## Review Notes To Include

- Mini EQ is an upstream-maintained GTK/Libadwaita graphical application.
- The app ID `io.github.bhack.mini-eq` matches the GitHub repository ownership
  and can use Flathub's GitHub verification flow.
- The app requires `xdg-run/pipewire-0` to create and use PipeWire audio nodes.
- The Flatpak bundles only the PipeWire filter-chain module and SPA builtin
  filter graph plugin needed inside the app process; it does not bundle or run
  a PipeWire daemon or session manager.
- WirePlumber is built for introspection compatibility, not as a bundled session
  daemon.
- Runtime licenses for bundled modules are installed under
  `/app/share/licenses/io.github.bhack.mini-eq`.
