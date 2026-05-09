#!/bin/sh
set -eu

workdir="${MINI_EQ_PREFLIGHT_WORKDIR:-/work}"
venv="${MINI_EQ_PREFLIGHT_VENV:-/tmp/mini-eq-preflight-venv}"
runtime="${MINI_EQ_PREFLIGHT_RUNTIME:-/tmp/mini-eq-runtime}"

cd "$workdir"
git config --global --add safe.directory "$workdir" 2>/dev/null || true

rm -rf "$venv" "$runtime"
python3 -m venv --system-site-packages "$venv"
"$venv/bin/python" -m pip install --upgrade pip
"$venv/bin/python" -m pip install -e '.[dev]'

mkdir -p "$runtime"
chmod 700 "$runtime"

export MINI_EQ_PREFLIGHT_PYTHON="$venv/bin/python"
export XDG_RUNTIME_DIR="$runtime"

dbus-run-session -- sh -eu -c '
pipewire >/tmp/mini-eq-pipewire.log 2>&1 &
pipewire_pid=$!
wireplumber >/tmp/mini-eq-wireplumber.log 2>&1 &
wireplumber_pid=$!

cleanup() {
  kill "$wireplumber_pid" "$pipewire_pid" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

for _ in $(seq 1 50); do
  if wpctl status >/dev/null 2>&1; then
    break
  fi
  sleep 0.2
done

wpctl status >/dev/null
"$MINI_EQ_PREFLIGHT_PYTHON" tools/release_preflight.py "$@"
if [ -n "${MINI_EQ_FLATHUB_MANIFEST:-}" ]; then
  "$MINI_EQ_PREFLIGHT_PYTHON" tools/check_flathub_manifest_drift.py \
    io.github.bhack.mini-eq.yaml \
    "$MINI_EQ_FLATHUB_MANIFEST"
fi
' sh "$@"
