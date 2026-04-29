# Agent Guide

These notes apply to the whole repository.

## Project Context

Mini EQ is a small system-wide parametric equalizer for PipeWire desktops. It
uses GTK/Libadwaita for the UI, WirePlumber for routing and default-output
monitoring, PipeWire filter-chain with builtin biquad filters for DSP, and the
PipeWire JACK compatibility layer plus NumPy for spectrum analysis.

This is a public-facing repository. Treat every committed file, screenshot,
artifact, and log snippet as public. Keep user-facing documentation focused on
using the app, and keep maintainer-only process notes in this file or under
`docs/`.

## Code Map

- `src/mini_eq/core.py`: EQ data models, preset JSON, biquad math, APO import.
- `src/mini_eq/filter_chain.py`: PipeWire filter-chain config generation.
- `src/mini_eq/wireplumber_backend.py`: WirePlumber GI compatibility layer.
- `src/mini_eq/wireplumber_stream_router.py`: stream routing helpers.
- `src/mini_eq/routing.py`: system-wide EQ lifecycle and routing controller.
- `src/mini_eq/app.py` and `src/mini_eq/window*.py`: GTK/Libadwaita app and UI.
- `src/mini_eq/analyzer.py`: JACK/NumPy analyzer runtime.
- `src/mini_eq/screenshot.py` and `tools/render_demo_screenshot.py`: maintainer
  screenshot tooling, not user-facing CLI.
- `data/`: desktop and AppStream metadata.
- `extensions/gnome-shell/mini-eq@bhack.github.io/`: companion GNOME Shell
  extension source. Keep this publishable and reviewable as an extension
  bundle; keep helper scripts under `tools/`.
- `io.github.bhack.mini-eq.yaml`: local Flatpak manifest.
- `python3-dependencies.yaml`: generated Flatpak Python dependencies.
- `tests/`: pytest suite for core behavior and non-visual integration seams.

## Development Commands

Use the repo virtualenv when it exists:

```bash
.venv/bin/python -m ruff check .
.venv/bin/python -m ruff format --check .
.venv/bin/python -m pytest -q
.venv/bin/python tools/check_gnome_shell_extension.py --no-package
```

For release/package checks:

```bash
appstreamcli validate --no-net data/io.github.bhack.mini-eq.metainfo.xml
desktop-file-validate data/io.github.bhack.mini-eq.desktop
.venv/bin/python tools/check_gnome_shell_extension.py
.venv/bin/python -m build
.venv/bin/python -m twine check dist/*
```

The app depends on system GI/audio packages that Python packaging cannot
install: GTK4, Libadwaita, WirePlumber introspection, PipeWire, and PipeWire
JACK compatibility. Some tests skip automatically when optional runtime tools
are unavailable.

## Change Guidelines

- Prefer existing patterns and small, targeted patches.
- Do not move logic between the large modules just to tidy them; split modules
  only when the user asked for that refactor or the change needs it.
- Keep WirePlumber 0.4 and 0.5 compatibility in mind. Do not use a newer GI API
  without checking the compatibility layer and tests.
- Keep the `mini-eq` CLI user-oriented. Maintainer automation belongs in
  `tools/`, `docs/`, or this file.
- Keep the GNOME Shell extension source in `extensions/gnome-shell/`; do not
  move development helpers or fake services into the publishable UUID
  directory.
- If you add packaged files, update `MANIFEST.in` when they must appear in the
  source distribution.
- Do not add generated build outputs, local config, cache directories, or
  machine-specific files.

## Flatpak And Flathub

- Keep the upstream Flatpak manifest as a local development and CI manifest
  using the checked-out source tree. The sibling Flathub repository uses a
  release archive URL and SHA-256 for publishing.
- Before opening a Flathub PR, compare the upstream and sibling Flathub
  manifests. The only expected manifest difference is the Mini EQ source block:
  local `type: dir` upstream, release archive URL and SHA-256 in Flathub.
- Put user-facing Flatpak install information in `README.md`; keep Flathub
  release workflow and repository split notes in `docs/flathub.md`.
- Do not hand-edit bundled Mini EQ source files in the Flathub repository. Fix
  application code, metadata, desktop files, icons, and screenshots upstream,
  then update the Flathub manifest to a new release archive.

## Screenshot Rules

The README should show the public screenshot, not instructions for generating
release assets.

Generate the public release screenshot with deterministic demo data:

```bash
PYTHONPATH=src python3 tools/render_demo_screenshot.py docs/screenshots/mini-eq.png
```

When the public screenshot changes materially, refresh `docs/social-preview.png`
so repository/package presentation stays visually consistent.

Do not commit screenshots that show personal device names, Bluetooth device
names, usernames, hostnames, local paths, or private preset names. Prefer
`tools/render_demo_screenshot.py` over desktop screenshots because it renders
only the Mini EQ window from deterministic demo data.

## Release And Security

Use `docs/release.md` as the release checklist. Before publishing release
artifacts or changing repository/package visibility, verify the rendered README,
package URLs, issue tracker, license, screenshots, and AppStream metadata.
During release preparation, verify that version-bearing files agree:
`pyproject.toml`, `CHANGELOG.md`, and the AppStream release entry and screenshot
URL. The package `__version__` is derived from release metadata and should not
be hardcoded separately.

Before publishing artifacts or changing repository visibility, run a focused
leak scan:

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

Do not push local scratch branches or local safety tags.
Do not rewrite public history unless the user explicitly asks for it and accepts
the impact.
