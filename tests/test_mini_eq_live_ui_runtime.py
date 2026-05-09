from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

if os.environ.get("MINI_EQ_RUN_LIVE_UI") != "1":
    pytestmark = pytest.mark.skip(reason="set MINI_EQ_RUN_LIVE_UI=1 to run live AT-SPI/PipeWire UI smoke")

HELPER_SKIP_EXIT_CODE = 77


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def test_live_ui_runtime_smoke_drives_real_app_with_synthetic_stream() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "tools/check_live_ui_runtime.py",
            "--timeout",
            "35",
            "--cycles",
            "2",
            "--audio-duration",
            "120",
        ],
        cwd=repo_root(),
        capture_output=True,
        text=True,
        timeout=300.0,
        check=False,
    )
    if result.returncode == HELPER_SKIP_EXIT_CODE:
        pytest.skip(result.stdout + result.stderr)
    assert result.returncode == 0, result.stdout + result.stderr
