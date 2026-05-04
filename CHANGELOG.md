# Changelog

## 0.3.2 - 2026-05-04

- Fix Flatpak system-wide routing by requesting PipeWire manager access from the WirePlumber client.
- Restore partially routed streams when initial routing fails and reset the routing switch after failures.
- Avoid restarting output routing during GTK close shutdown.
- Add a local Flatpak runtime smoke test and an experimental manual CI job for routing checks.

## 0.3.1 - 2026-05-04

- Improve adaptive layout spacing across compact, tall, and wide windows.
- Remove unnecessary utility-pane scrolling at the minimum window height.
- Lighten the utility pane presentation so tall windows keep focus on the controls.

## 0.3.0 - 2026-05-03

- Add optional live LUFS loudness metering through libebur128 and the existing JACK monitor stream.
- Bundle libebur128 in the local Flatpak manifest for the live loudness readout.

## 0.2.0 - 2026-05-02

- Add per-output preset links so headphones, speakers, HDMI, and other outputs can automatically use different saved presets.
- Add preset actions to use the current preset for the selected output or clear that output link.
- Protect unsaved curve edits when an output changes instead of replacing them with an automatic preset.
- Show output preset link status in the GNOME Shell extension.
- Keep the SVG icon and package asset cleanup from the post-0.1.8 review work.

## 0.1.8 - 2026-05-02

- Improve Flathub presentation metadata, screenshots, and SVG app icon assets.
- Switch local and packaged app icon installation to scalable SVG plus symbolic SVG.
- Add a second dark-style screenshot while keeping the default light screenshot first.
- Refine graph, analyzer, fader, and utility-pane spacing for the public screenshot.

## 0.1.7 - 2026-04-30

- Add System, Light, and Dark appearance modes.
- Improve light-theme readability for the graph, analyzer, faders, and signal controls.
- Replace the persistent output warning banner with compact Signal state chips.
- Refresh the public screenshot and social preview assets.

## 0.1.6 - 2026-04-30

- Improve compact window sizing so the minimum layout uses available vertical space.
- Add release preflight guidance for deciding when a GNOME Shell extension upload is needed.
- Move owner-specific release runbook details out of public documentation.
- Refresh the public screenshot and social preview assets.

## 0.1.5 - 2026-04-30

- Improve analyzer rendering responsiveness by moving spectrum drawing into a dedicated snapshot widget.
- Improve GNOME Shell extension controls, packaging checks, and demo tooling for review screenshots.
- Clarify Equalizer APO and AutoEq preset import guidance in the README.
- Remove unused legacy code and document repeatable cleanup checks for maintainers.

## 0.1.4 - 2026-04-30

- Add the Mini EQ Controls GNOME Shell extension for panel routing, EQ, preset, and analyzer controls.
- Add the Mini EQ D-Bus control API used by the companion GNOME Shell extension.
- Improve system-wide EQ compare controls and refresh the public screenshot and social preview assets.
- Add release checks and packaging helpers for the GNOME Shell extension bundle.

## 0.1.3 - 2026-04-29

- Redesign the signal inspector with compact headroom, preamp, and monitor controls.
- Replace the large peak warning with inline headroom status and a quick safe-preamp action.
- Add a local symbolic monitor settings icon and refresh public screenshots.
- Require Libadwaita 1.7+ for the updated adaptive layout.

## 0.1.2 - 2026-04-28

- Refine the main workspace layout, graph sizing, and compact adaptive behavior.
- Polish the compact selected-band editor and bottom-sheet workflow.
- Improve band fader rendering, selected-band editor stability, and graph presentation.
- Improve dependency diagnostics and add coverage for app startup, dependency checks, and window behavior.
- Switch the local Flatpak manifest to YAML and add generated Flatpak Python dependencies.
- Add Flathub maintenance notes, the Flathub install badge, and updated install guidance.
- Improve PyPI and GitHub discoverability metadata.
- Refresh the public screenshot and add a generated social preview image.
- Tighten CI scope detection so unchanged jobs can skip their heavy work.

## 0.1.1 - 2026-04-27

- Fix PyPI classifier metadata for package-index publishing.
- Add production PyPI publishing automation using trusted publishing.

## 0.1.0 - 2026-04-26

- Initial standalone Mini EQ source package.
- GTK/Libadwaita system-wide parametric equalizer UI.
- PipeWire filter-chain builtin biquad processing through WirePlumber.
- Output routing, default-output following, preset import/export, and analyzer support.
- Runtime dependency diagnostics through `mini-eq --check-deps`.
