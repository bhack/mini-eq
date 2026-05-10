# Agent Guide

These notes apply to the whole repository.

## Project Context

Mini EQ is a small system-wide parametric equalizer for PipeWire desktops. It
uses GTK/Libadwaita for the UI, pipewire-gobject for app-facing PipeWire
routing, metadata, and monitor capture, PipeWire filter-chain with builtin
biquad filters for DSP, and NumPy for spectrum analysis.

This is a public-facing repository. Treat every committed file, screenshot,
artifact, and log snippet as public. Keep user-facing documentation focused on
using the app. Keep public maintainer guidance in this file or under `docs/`;
keep owner-only local runbooks, credentials-dependent steps, and machine-local
paths in ignored repo-local skills under `.agents/skills/`.

## Code Map

- `src/mini_eq/core.py`: EQ data models, preset JSON, biquad math, APO import.
- `src/mini_eq/filter_chain.py`: PipeWire filter-chain config generation.
- `src/mini_eq/pipewire_backend.py`: pipewire-gobject-backed PipeWire registry,
  metadata, and node-control layer.
- `src/mini_eq/pipewire_stream_router.py`: stream routing helpers.
- `src/mini_eq/routing.py`: system-wide EQ lifecycle and routing controller.
- `src/mini_eq/app.py` and `src/mini_eq/window*.py`: GTK/Libadwaita app and UI.
- `src/mini_eq/analyzer.py`: pipewire-gobject monitor stream and NumPy analyzer runtime.
- `src/mini_eq/screenshot.py` and `tools/render_demo_screenshot.py`: maintainer
  screenshot tooling, not user-facing CLI.
- `data/`: desktop and AppStream metadata.
- `extensions/gnome-shell/mini-eq@bhack.github.io/`: companion GNOME Shell
  extension source. Keep this publishable and reviewable as an extension
  bundle; keep helper scripts under `tools/`.
- `io.github.bhack.mini-eq.yaml`: local Flatpak manifest.
- `python3-dependencies.yaml`: generated Flatpak Python dependencies.
- `tests/`: pytest suite for core behavior and non-visual integration seams.
- `docs/development.md`: source checkout, PyPI, local Flatpak, and extended
  development test commands.

## Development Commands

Use the repo virtualenv when it exists:

```bash
.venv/bin/python -m ruff check .
.venv/bin/python -m ruff format --check .
.venv/bin/python -m pytest -q
.venv/bin/python tools/check_gnome_shell_extension.py --no-package
```

For periodic cleanup and legacy-code checks, use:

```bash
.venv/bin/python -m vulture src tests tools --min-confidence 80
.venv/bin/python -m pytest --dead-fixtures -q
.venv/bin/python tools/check_test_hygiene.py
.venv/bin/python -m pytest --cov=mini_eq --cov-report=term-missing:skip-covered -q
```

Treat Vulture reports below 80% confidence as review prompts, not automatic
deletions. Treat test hygiene reports the same way: exact duplicate test bodies
and no-assert tests are candidates for human review, not automatic removals.
GTK virtual methods, signal callbacks, property bindings, and other framework
entry points often look unused to static analysis.

For source install, PyPI package validation, local Flatpak builds, and extended
runtime smoke commands, use `docs/development.md`.

The app depends on system GI/audio packages that Python packaging cannot fully
install: GTK4, Libadwaita, PipeWire, a WirePlumber-managed session, and the
native libraries used by pipewire-gobject. PyGObject is a distro/runtime
dependency, not a Mini EQ PyPI dependency. Some tests skip automatically when
optional runtime tools are unavailable.

For real GTK widget behavior, run the opt-in AT-SPI smoke test inside its
nested headless GNOME Shell session:

```bash
MINI_EQ_RUN_ATSPI=1 .venv/bin/python -m pytest tests/test_mini_eq_atspi_widgets.py -q
```

For a deeper live runtime smoke, run the real GTK app in a private
PipeWire/WirePlumber graph with synthetic playback and AT-SPI UI driving:

```bash
.venv/bin/python tools/check_live_ui_runtime.py --timeout 35 --cycles 1
MINI_EQ_RUN_LIVE_UI=1 .venv/bin/python -m pytest tests/test_mini_eq_live_ui_runtime.py -q
```

When creating a fresh venv for pip/package validation, follow
`docs/development.md` so pipewire-gobject is built in a plain wheel-build venv
before being installed into a `--system-site-packages` Mini EQ venv.

## Change Guidelines

- Prefer existing patterns and small, targeted patches.
- Do not move logic between the large modules just to tidy them; split modules
  only when the user asked for that refactor or the change needs it.
- Keep the pipewire-gobject API boundary small, general-purpose, and
  app-facing. Mini EQ may validate new pipewire-gobject API in a real GTK app,
  but do not add Mini EQ-shaped concepts, preset/filter-chain policy, or
  hardware-selection policy to pipewire-gobject. WirePlumber stays the host
  session manager, not a bundled GI dependency.
- Treat the Mini EQ D-Bus control interface as a project-internal app/Shell
  extension contract with version-skew tolerance. Keep `api_version = 1`
  additive only: add state fields, methods, and capabilities when needed, but do
  not remove or rename existing v1 members. Gate optional Shell extension
  behavior on `capabilities`. Bump the API version only for semantic breaks, and
  support the old version for a short, documented release window before removing
  it.
- Keep app-owned JSON documents explicitly versioned with a top-level
  `version` field plus migration, unsupported-version, and corrupted-schema
  normalization tests. Presets and output preset links are JSON documents; do
  not move them to GSettings. Valid legacy documents should load without being
  rewritten on startup, then be written in the current schema only when the
  user changes related state. Future-version or corrupted documents should not
  be overwritten just because the app started. If GSettings is introduced
  later, keep it to small typed preferences such as appearance, monitor, and
  background/startup choices, and update the schema install, Flatpak, and test
  paths in the same change.
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
  using the checked-out source tree. The Flathub packaging repository uses a
  release archive URL and SHA-256 for publishing.
- Before opening a Flathub PR, compare the upstream and Flathub manifests and
  synced dependency files. The only expected manifest difference is the Mini EQ
  source block: local `type: dir` upstream, release archive URL and SHA-256 in
  Flathub.
- Treat Flathub publishing PRs as maintainer-owned. Agents may prepare local
  diffs, validation output, and handoff notes, but should not open, submit, or
  merge Flathub PRs.
- Put user-facing Flatpak install information in `README.md`; keep Flathub
  release workflow and repository split notes in `docs/flathub.md`.
- Do not hand-edit bundled Mini EQ source files in the Flathub repository. Fix
  application code, metadata, desktop files, icons, and screenshots upstream,
  then update the Flathub manifest to a new release archive.

## Screenshot Rules

The README should show the public app screenshot, not instructions for
generating release assets. Use `docs/screenshots/mini-eq.png` as the primary
README and default AppStream/Flathub screenshot. Keep it as just the app window
in the platform-default light appearance. Use `docs/screenshots/mini-eq-dark.png`
only as an optional second AppStream/Flathub screenshot to demonstrate dark style
support.

Use `docs/social-preview.png` for GitHub and social link previews. This is not a
Flathub quality-check input, so it may use branded/dark promotional composition,
but it should be refreshed when the public screenshot changes materially.

Do not commit screenshots that show personal device names, Bluetooth device
names, usernames, hostnames, local paths, or private preset names. Prefer
`tools/render_demo_screenshot.py` over desktop screenshots because it renders
only the Mini EQ window from deterministic demo data. Keep the public release
screenshot in the platform-default light appearance unless you are adding
additional screenshots that intentionally demonstrate other appearance modes.
Use `docs/screenshots/README.md` for the generation commands.

For visual or adaptive-layout changes, inspect deterministic screenshot
matrices before considering the work done. Cover the minimum, default, narrow,
wide, short, tall, and breakpoint-adjacent sizes that the change can affect.
Check the actual PNG dimensions as well as the rendered image, because GTK can
raise a requested size to the current minimum. Pay particular attention to
collapsed/expanded transitions, clipped controls, wasted space, and whether the
graph, analyzer, faders, and utility pane still share space deliberately.

## Icon Asset Rules

Use `src/mini_eq/assets/icons/hicolor/scalable/apps/io.github.bhack.mini-eq.svg`
as the full-color app icon. Do not add generated PNG app icons unless a target
platform specifically needs them; GNOME and Flathub can use the scalable SVG.

Keep `src/mini_eq/assets/icons/hicolor/symbolic/apps/io.github.bhack.mini-eq-symbolic.svg`
as the symbolic app icon. Before considering icon changes done, inspect the
full-color icon against the GNOME app icon template and check 128, 64, and 32 px
renders on light and dark backgrounds.

## Release And Security

Use `docs/release.md` as the public release checklist. Use
`tools/prepare_release.py`, `tools/release_status.py`,
`tools/run_release_preflight_container.sh`, and
`tools/release_post_publish.py` for repeatable release checks. Keep
owner-specific workflow dispatch, deployment approval, and local Flathub merge
steps in ignored repo-local skills under `.agents/skills/`.

The preflight owns the focused leak scan for `HEAD`, tracked worktree changes,
and untracked non-ignored text files. Use Gitleaks as an extra check when
release history or generated artifacts look suspicious.

Do not push local scratch branches or local safety tags.
Do not rewrite public history unless the user explicitly asks for it and accepts
the impact.
