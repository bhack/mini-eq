# Changelog

## Unreleased

- Add direct AutoEq search, curve preview, and on-demand preset import from the app.
- Show current AppStream release notes in the About dialog.
- Request Flatpak network access so AutoEq.app profile search and preset generation work in sandboxed builds.
- Keep the Flatpak display permission Wayland-only, avoiding the X11 screen-contents access grant.

## 0.7.4 - 2026-05-11

- Run filter-chain readiness callbacks from the GLib main context when PipeWire
  reports the virtual sink asynchronously, avoiding thread-loop sync failures
  during system-wide EQ startup.
- Require pipewire-gobject 0.3.7 and re-apply the active filter controls when
  PipeWire creates or activates links on the Mini EQ processing path, so audio
  resumed after silence starts processing without requiring an A/B toggle.
- Refresh port-aware output preset scope when PipeWire reports route parameter
  serial changes on the active output device.

## 0.7.3 - 2026-05-11

- Require pipewire-gobject 0.3.6 and use its synchronous PipeWire registry,
  metadata, node, and device APIs for startup and routing state.
- Replace Mini EQ's PipeWire startup and routing sleep loops with bounded sync
  or registry-event waits for route params, virtual sink creation, and stream
  routing.
- Avoid a headless startup hang when system-wide EQ fails synchronously before
  the GLib main loop starts.
- Hide the GNOME Shell extension's mini analyzer while monitoring is turned
  off, keeping the panel item available without showing stale meter bars.

## 0.7.2 - 2026-05-10

- Finish GNOME Shell startup notification after Mini EQ's delayed first-window
  setup, avoiding a stuck busy cursor when launching from the app icon.
- Rename the delayed startup setup path in code to make the readiness barrier
  clearer for future maintenance.
- Clarify the unmatched-output fallback action so it refers to the loaded saved
  preset instead of the ambiguous current curve.

## 0.7.1 - 2026-05-09

- Fix port-aware auto presets when the active port changes on the same
  hardware output, such as switching between built-in speakers and headphones.
- Avoid guessing a port when PipeWire exposes ambiguous route data for one
  output, and refresh preset handling from the observed PipeWire change.
- Clarify unmatched-output fallback preset wording and tighten the compact
  utility-pane layout.
- Improve the app icon's small-size readability without changing its
  GNOME/Flathub footprint.

## 0.7.0 - 2026-05-09

- Replace the direct WirePlumber Python integration with pipewire-gobject for
  app-facing PipeWire registry, metadata, routing, and monitor-capture access.
- Use pipewire-gobject device route params so auto preset links follow the
  detected output port when available while preserving output-node links as a
  fallback.
- Bundle pipewire-gobject 0.3.5 in Flatpak and require
  `pipewire-gobject>=0.3.5,<0.4` for PyPI installs.
- Keep system-wide EQ, monitor capture, output changes, and shutdown behavior
  covered by a live nested-GNOME/AT-SPI runtime smoke test.
- Remove the old WirePlumber 0.4 compatibility build path and tighten release
  preflight around the new PipeWire dependency boundary.

## 0.5.1 - 2026-05-07

- Keep routing, EQ, analyzer, and output-preset switches synchronized with
  confirmed state after errors and D-Bus control calls.
- Retarget the running PipeWire filter-chain output when the selected output
  changes, avoiding a full engine restart when WirePlumber can move the stream.
- Pause routed stream monitoring during engine restarts and restore streams
  before routing them through the restarted EQ path.
- Improve headroom meter range, peak formatting, and compact label stability.

## 0.5.0 - 2026-05-06

- Add a Default Preset fallback for outputs that do not have their own linked
  preset.
- Reset to neutral only when changing away from an auto-applied output preset
  and the new output has no linked preset or default fallback.
- Keep manual preset choices and unsaved curve edits when the selected output
  has no linked preset.
- Add a Start Active at Login option so startup routing can automatically apply
  the EQ path.
- Improve analyzer band resolution and preset-state refresh after preamp edits.

## 0.4.0 - 2026-05-05

- Add opt-in background mode so closing the window can keep Mini EQ active.
- Add Start at Login support through the Background portal in Flatpak and XDG
  autostart for native installs.
- Add D-Bus state fields and a Quit method for Shell extension compatibility.
- Keep GNOME event sounds, notifications, and other system streams out of
  system-wide EQ routing.
- Route streams by writing both PipeWire `target.node` and `target.object`
  metadata, avoiding metadata readback as a routing acknowledgement.

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
