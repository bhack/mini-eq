FROM debian:trixie-slim

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      appstream \
      build-essential \
      ca-certificates \
      dbus \
      desktop-file-utils \
      gir1.2-adw-1 \
      gir1.2-gtk-4.0 \
      git \
      gnome-shell \
      gobject-introspection \
      libebur128-1 \
      libgirepository1.0-dev \
      libglib2.0-dev \
      libpipewire-0.3-dev \
      libspa-0.2-modules \
      meson \
      ninja-build \
      pipewire \
      pkg-config \
      python3 \
      python3-cairo \
      python3-dev \
      python3-gi \
      python3-numpy \
      python3-pip \
      python3-setuptools \
      python3-venv \
      wireplumber \
 && rm -rf /var/lib/apt/lists/*

COPY docker/run-release-preflight.sh /usr/local/bin/mini-eq-release-preflight
RUN chmod +x /usr/local/bin/mini-eq-release-preflight

WORKDIR /work
ENTRYPOINT ["mini-eq-release-preflight"]
