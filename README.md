# Mini EQ

[![CI](https://github.com/bhack/mini-eq/actions/workflows/ci.yml/badge.svg)](https://github.com/bhack/mini-eq/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/mini-eq.svg?cacheSeconds=3600)](https://pypi.org/project/mini-eq/)
[![GitHub release](https://img.shields.io/github/v/release/bhack/mini-eq?sort=semver)](https://github.com/bhack/mini-eq/releases)
[![License](https://img.shields.io/github/license/bhack/mini-eq.svg)](https://github.com/bhack/mini-eq/blob/main/LICENSE)

<a href="https://flathub.org/apps/io.github.bhack.mini-eq"><img width="240" alt="Get it on Flathub" src="https://flathub.org/api/badge?locale=en"/></a>

Mini EQ is a small system-wide parametric equalizer for PipeWire desktops.
It uses GTK/Libadwaita for the UI, pipewire-gobject for app-facing PipeWire
routing, metadata, and monitor streams, and PipeWire filter-chain with builtin
biquad filters for the equalizer. When libebur128 is available, the monitor can
also show live LUFS loudness.

![Mini EQ screenshot](https://raw.githubusercontent.com/bhack/mini-eq/main/docs/screenshots/mini-eq.png)

## Features

- System-wide parametric EQ for PipeWire desktop playback.
- GTK/Libadwaita interface with a compact 10-band fader workflow.
- PipeWire routing and default-output tracking through pipewire-gobject.
- PipeWire filter-chain DSP using builtin biquad filters.
- Optional spectrum analyzer and LUFS loudness readout through a PipeWire monitor
  capture stream.
- Auto preset links can follow the detected PipeWire port when available and
  fall back to the selected EQ output when a port is not reported.
- Optional background mode keeps the EQ active after closing the window, with a
  separate Start at Login preference and optional active-at-login routing.
- Optional GNOME Shell extension for quick panel access to routing, EQ,
  analyzer status, presets, and auto preset links.
- Equalizer APO preset import from the UI or `--import-apo`, including
  compatible presets exported by [AutoEq](https://autoeq.app/).

## AutoEq And APO Presets

Mini EQ can import Equalizer APO-style parametric EQ text presets. This makes it
usable with headphone correction presets exported by
[AutoEq](https://autoeq.app/): export an Equalizer APO/parametric EQ preset from
AutoEq, then use **Import Equalizer APO...** in Mini EQ or start the app with
`mini-eq --import-apo path/to/ParametricEQ.txt`. The
[AutoEq project](https://github.com/jaakkopasanen/AutoEq) provides the source,
headphone measurement data, targets, and optimizer behind the web app.

## Install

Recommended install paths:

1. Flathub, the preferred desktop install path.
2. PyPI, after the system desktop/audio dependencies below are installed.
3. Source checkout, for development or testing unreleased changes.

Install from Flathub:

```bash
flatpak install flathub io.github.bhack.mini-eq
flatpak run io.github.bhack.mini-eq
```

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

These are good starting points:

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

## GNOME Shell Extension

Mini EQ also has an optional GNOME Shell extension for quick panel access to
routing, EQ, analyzer status, presets, and auto preset links.

Install it from GNOME Shell Extensions:
https://extensions.gnome.org/extension/9803/mini-eq-controls/

## Test

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

## Flatpak

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

## Notes

Runtime data is stored under `~/.config/mini-eq`.

`pip install mini-eq` installs only the Python package. The system packages
above are still required for the app to connect to GTK, PipeWire, and the host
WirePlumber-managed session.

## Acknowledgements

Mini EQ is inspired in part by [EasyEffects](https://github.com/wwmm/easyeffects)
and the broader [PipeWire](https://pipewire.org/) audio tooling ecosystem.
Mini EQ is a separate project focused on a compact system-wide parametric EQ
workflow.
