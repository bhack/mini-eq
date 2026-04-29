# Changelog

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
