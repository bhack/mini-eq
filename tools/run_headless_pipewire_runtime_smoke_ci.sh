#!/bin/sh
set -eu

venv="${MINI_EQ_HEADLESS_PIPEWIRE_VENV:-${RUNNER_TEMP:-/tmp}/mini-eq-headless-pipewire-venv}"
timeout="${MINI_EQ_HEADLESS_PIPEWIRE_TIMEOUT:-35}"
cycles="${MINI_EQ_HEADLESS_PIPEWIRE_CYCLES:-3}"
audio_duration="${MINI_EQ_HEADLESS_PIPEWIRE_AUDIO_DURATION:-120}"

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

rm -rf "$venv"
python3 -m venv --system-site-packages "$venv"
PATH="$venv/bin:$PATH"
export PATH
"$venv/bin/python" -m pip install --upgrade pip
pwg_requirement="$("$venv/bin/python" - <<'PY'
import tomllib
from pathlib import Path

project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))["project"]
for dependency in project["dependencies"]:
    if dependency.lower().startswith("pipewire-gobject"):
        print(dependency)
        break
else:
    raise SystemExit("pyproject.toml does not declare a pipewire-gobject dependency")
PY
)"
"$venv/bin/python" -m pip install "meson-python>=0.18" "meson>=1.2" ninja packaging
"$venv/bin/python" -m pip install --no-build-isolation "$pwg_requirement"
"$venv/bin/python" -m pip install -e .
"$venv/bin/python" tools/check_headless_pipewire_runtime.py \
  --timeout "$timeout" \
  --cycles "$cycles" \
  --audio-duration "$audio_duration"
