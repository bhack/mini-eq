# Development

This page collects source checkout, Python package, local Flatpak, and test
commands. The README stays focused on using Mini EQ.

## System Dependencies

Mini EQ depends on system desktop/audio packages that Python packaging cannot
fully install: GTK 4.12+ and Libadwaita 1.7+ GI bindings, PyGObject, PipeWire,
WirePlumber as the session manager, and the native libraries required by
pipewire-gobject. Install PyGObject from your distro, such as `python3-gi` or
`python3-gobject`, rather than adding a PyPI PyGObject dependency to Mini EQ.

If your distro ships older GTK or Libadwaita builds, prefer the Flatpak build.

Package names vary by distro release. If pip builds pipewire-gobject from its
source distribution, install the GLib, GObject-Introspection, and PipeWire
development packages first. Virtual environments that need distro GI bindings
should use `--system-site-packages`; on Ubuntu/Debian, build the
pipewire-gobject wheel in a plain venv first, then install that wheel into the
system-site Mini EQ venv.

Good starting points:

```bash
# Ubuntu / Debian
sudo apt install \
  gir1.2-adw-1 \
  gir1.2-gtk-4.0 \
  gobject-introspection \
  libgirepository1.0-dev \
  libglib2.0-dev \
  libpipewire-0.3-dev \
  meson \
  ninja-build \
  pkg-config \
  pipewire \
  python3-cairo \
  python3-pip \
  python3-gi \
  python3-setuptools \
  python3-venv \
  wireplumber \
  libebur128-1

# Fedora
sudo dnf install \
  gtk4 \
  libadwaita \
  gobject-introspection-devel \
  glib2-devel \
  meson \
  ninja-build \
  pkgconf-pkg-config \
  pipewire \
  pipewire-devel \
  python3-cairo \
  python3-gobject \
  python3-pip \
  wireplumber \
  libebur128

# Arch Linux
sudo pacman -S \
  gtk4 \
  libadwaita \
  gobject-introspection \
  glib2 \
  meson \
  ninja \
  pkgconf \
  pipewire \
  python-cairo \
  python-gobject \
  python-pip \
  wireplumber \
  libebur128
```

## PyPI Install

Install the Python package after the system packages are present:

```bash
python3 -m venv /tmp/mini-eq-pwg-build
/tmp/mini-eq-pwg-build/bin/python -m pip install --upgrade pip
/tmp/mini-eq-pwg-build/bin/python -m pip wheel 'pipewire-gobject>=0.3.5,<0.4' -w /tmp/mini-eq-wheelhouse

python3 -m venv --system-site-packages ~/.local/share/mini-eq/venv
~/.local/share/mini-eq/venv/bin/python -m pip install --upgrade pip
~/.local/share/mini-eq/venv/bin/python -m pip install --no-index --find-links /tmp/mini-eq-wheelhouse 'pipewire-gobject>=0.3.5,<0.4'
~/.local/share/mini-eq/venv/bin/python -m pip install mini-eq
~/.local/share/mini-eq/venv/bin/mini-eq --check-deps
~/.local/share/mini-eq/venv/bin/mini-eq
```

Install the desktop launcher and icon for the current user:

```bash
mini-eq --install-desktop
```

## Source Checkout

For an editable source checkout:

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

## Tests

```bash
python3 -m pip install -e '.[dev]'
python3 -m ruff check .
python3 -m ruff format --check .
python3 -m pytest -q
```

Some integration tests are skipped automatically when optional PipeWire runtime
tools are not installed.

Check the pipewire-gobject GI compatibility surface:

```bash
PYTHONPATH=src python3 tools/check_pipewire_gobject.py
```

For real GTK widget behavior, run the opt-in AT-SPI smoke test:

```bash
MINI_EQ_RUN_ATSPI=1 python3 -m pytest tests/test_mini_eq_atspi_widgets.py -q
```

For a deeper live runtime smoke, run the real GTK app in a private
PipeWire/WirePlumber graph with synthetic playback and AT-SPI UI driving:

```bash
python3 tools/check_live_ui_runtime.py --timeout 35 --cycles 1
MINI_EQ_RUN_LIVE_UI=1 python3 -m pytest tests/test_mini_eq_live_ui_runtime.py -q
```

## Local Flatpak Build

The Flatpak manifest uses the GNOME runtime. It does not ship a full PipeWire
daemon or session manager; it builds only the local PipeWire filter-chain module
and SPA builtin filter-graph support that Mini EQ loads inside the app process.
It also builds pipewire-gobject for Mini EQ's app-facing PipeWire access and
bundles NumPy and libebur128 for analyzer and live LUFS support.

Install the local build tools:

```bash
flatpak --user install flathub org.flatpak.Builder org.gnome.Sdk//50
```

Build and install the local Flatpak:

```bash
flatpak run org.flatpak.Builder --user --install --force-clean --install-deps-from=flathub \
  flatpak-build io.github.bhack.mini-eq.yaml
flatpak run io.github.bhack.mini-eq --check-deps
flatpak run io.github.bhack.mini-eq
```
