#!/bin/sh
set -eu

venv="${MINI_EQ_LIVE_UI_VENV:-${RUNNER_TEMP:-/tmp}/mini-eq-live-ui-venv}"
timeout="${MINI_EQ_LIVE_UI_TIMEOUT:-35}"
cycles="${MINI_EQ_LIVE_UI_CYCLES:-3}"
audio_duration="${MINI_EQ_LIVE_UI_AUDIO_DURATION:-180}"

rm -rf "$venv"
python3 -m venv --system-site-packages "$venv"
"$venv/bin/python" -m pip install --upgrade pip
"$venv/bin/python" -m pip install -e '.[dev]'
"$venv/bin/python" tools/check_live_ui_runtime.py \
  --timeout "$timeout" \
  --cycles "$cycles" \
  --audio-duration "$audio_duration"
