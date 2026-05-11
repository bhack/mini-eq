#!/bin/sh
set -eu

venv="${MINI_EQ_LIVE_UI_VENV:-${RUNNER_TEMP:-/tmp}/mini-eq-live-ui-venv}"
timeout="${MINI_EQ_LIVE_UI_TIMEOUT:-35}"
cycles="${MINI_EQ_LIVE_UI_CYCLES:-3}"
audio_duration="${MINI_EQ_LIVE_UI_AUDIO_DURATION:-180}"

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
"$venv/bin/python" tools/check_live_ui_runtime.py \
  --timeout "$timeout" \
  --cycles "$cycles" \
  --audio-duration "$audio_duration"
