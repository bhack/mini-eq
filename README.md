# Mini EQ

Mini EQ is a small system-wide parametric equalizer for PipeWire desktops.
It uses GTK/Libadwaita for the UI, WirePlumber for routing/default-output
control, PipeWire filter-chain with builtin biquad filters for the equalizer,
and the JACK API on PipeWire plus NumPy FFT analysis for the analyzer.

## Install

Mini EQ depends on system desktop/audio packages that are not installed by
Python packaging: GTK4/Libadwaita 1.4+ GI bindings, WirePlumber introspection,
PipeWire, and PipeWire JACK compatibility.

Package names vary by distro release. Mini EQ prefers WirePlumber 0.5
introspection when available and falls back to WirePlumber 0.4, which is what
Ubuntu 24.04 provides.

These are good starting points:

```bash
# Ubuntu / Debian
sudo apt install \
  gir1.2-adw-1 \
  gir1.2-gtk-4.0 \
  gir1.2-wp-0.4 \
  pipewire \
  pipewire-jack \
  python3-cairo \
  python3-gi \
  wireplumber

# Fedora
sudo dnf install \
  gtk4 \
  libadwaita \
  pipewire \
  pipewire-jack-audio-connection-kit \
  python3-cairo \
  python3-gobject \
  wireplumber \
  wireplumber-libs

# Arch Linux
sudo pacman -S \
  gtk4 \
  libadwaita \
  libwireplumber \
  pipewire \
  pipewire-jack \
  python-cairo \
  python-gobject \
  wireplumber
```

Use `gir1.2-wp-0.5` instead of `gir1.2-wp-0.4` on distro releases that package
WirePlumber 0.5 introspection.

Install the Python package after the system packages are present:

```bash
python3 -m pip install mini-eq
mini-eq --check-deps
mini-eq
```

For a source checkout:

```bash
python3 -m pip install -e .
mini-eq --check-deps
mini-eq
```

For a source checkout without installing the package:

```bash
PYTHONPATH=src python3 -m mini_eq --check-deps
PYTHONPATH=src python3 -m mini_eq
```

Install the desktop launcher and icon for the current user:

```bash
mini-eq --install-desktop
```

## Screenshot

![Mini EQ screenshot](https://raw.githubusercontent.com/bhack/mini-eq/main/docs/screenshots/mini-eq.png)

## Test

```bash
python3 -m pip install -e '.[dev]'
python3 -m ruff check .
python3 -m ruff format --check .
python3 -m pytest -q
```

Some integration tests are skipped automatically when optional PipeWire runtime
tools are not installed.

Check the Ubuntu 24.04 WirePlumber 0.4 GI compatibility surface in Docker:

```bash
docker build -f docker/ubuntu-24.04-wp04.Dockerfile -t mini-eq:wp04 .
docker run --rm mini-eq:wp04
```

## Flatpak

The Flatpak manifest uses the GNOME runtime. It does not ship a full PipeWire
daemon or session manager; it builds only the local PipeWire filter-chain module
and SPA builtin filter-graph support that Mini EQ loads inside the app process.
The analyzer uses the runtime JACK compatibility library with bundled Python
JACK and NumPy dependencies.

Install the local build tools:

```bash
flatpak --user install flathub org.flatpak.Builder org.gnome.Sdk//50
```

Build and install the local Flatpak:

```bash
flatpak run org.flatpak.Builder --user --install --force-clean --install-deps-from=flathub \
  flatpak-build io.github.bhack.mini-eq.json
flatpak run io.github.bhack.mini-eq --check-deps
flatpak run io.github.bhack.mini-eq
```

## Notes

Runtime data is stored under `~/.config/mini-eq`.

`pip install mini-eq` installs only the Python package. The system packages
above are still required for the app to connect to GTK, WirePlumber, PipeWire,
and PipeWire JACK.

## Acknowledgements

Mini EQ is inspired in part by EasyEffects and the broader Linux PipeWire audio
tooling ecosystem. Mini EQ is a separate project focused on a compact
system-wide parametric EQ workflow.
