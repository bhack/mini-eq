from __future__ import annotations

import math
import os
import subprocess
import sys
from unittest import mock

import numpy as np
import pytest

from tests._mini_eq_imports import import_mini_eq_module

ebur128 = import_mini_eq_module("ebur128")


def require_native_ebur128() -> None:
    if not ebur128.is_available():
        pytest.skip("libebur128 is not available")


def test_ebur128_import_does_not_require_gi_scipy_or_cffi() -> None:
    script = """
import builtins

real_import = builtins.__import__

def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
    blocked = ("gi", "scipy", "cffi", "pybind11")
    if name in blocked or any(name.startswith(f"{prefix}.") for prefix in blocked):
        raise AssertionError("mini_eq.ebur128 should not import GI, SciPy, CFFI, or pybind11")
    return real_import(name, globals, locals, fromlist, level)

builtins.__import__ = guarded_import
import mini_eq.ebur128
"""
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(["src", env.get("PYTHONPATH", "")])
    subprocess.run([sys.executable, "-c", script], check=True, env=env)


def test_ebur128_reports_unavailable_when_library_cannot_load() -> None:
    with (
        mock.patch.object(ebur128, "_LIBRARY", None),
        mock.patch("ctypes.util.find_library", return_value=None),
        mock.patch("ctypes.CDLL", side_effect=OSError("missing")),
    ):
        assert not ebur128.is_available()
        with pytest.raises(ebur128.Ebur128UnavailableError, match="libebur128 is not available"):
            ebur128.version()


def test_ebur128_version_loads_from_native_library() -> None:
    require_native_ebur128()

    version = ebur128.version()

    assert version.major >= 1
    assert str(version).count(".") == 2


def test_ebur128_meter_reports_expected_loudness_for_stereo_audio() -> None:
    require_native_ebur128()
    sample_rate = 48_000
    duration_seconds = 10
    time = np.arange(sample_rate * duration_seconds, dtype=np.float64) / sample_rate
    left = 0.1 * np.sin(2.0 * np.pi * 1000.0 * time)
    right = 0.08 * np.sin(2.0 * np.pi * 1000.0 * time + 0.3)
    audio = np.column_stack([left, right])

    with ebur128.Ebur128Meter(sample_rate=sample_rate, channels=2) as meter:
        assert meter.add_frames_float32(audio.astype(np.float32)) == sample_rate * duration_seconds
        measured = meter.integrated_lufs()

    assert measured == pytest.approx(-20.86, abs=0.15)


def test_ebur128_meter_provides_live_loudness_values() -> None:
    require_native_ebur128()
    sample_rate = 48_000
    rng = np.random.default_rng(123)
    audio = (0.04 * rng.standard_normal((sample_rate * 4, 2))).astype(np.float32)

    with ebur128.Ebur128Meter(sample_rate=sample_rate, channels=2) as meter:
        meter.add_frames_float32(audio)

        assert math.isfinite(meter.momentary_lufs())
        assert math.isfinite(meter.shortterm_lufs())
        assert math.isfinite(meter.integrated_lufs())


def test_ebur128_meter_reset_clears_integrated_state() -> None:
    require_native_ebur128()
    sample_rate = 48_000
    time = np.arange(sample_rate * 3, dtype=np.float64) / sample_rate
    loud = np.column_stack(
        [
            0.2 * np.sin(2.0 * np.pi * 1000.0 * time),
            0.2 * np.sin(2.0 * np.pi * 1000.0 * time),
        ]
    ).astype(np.float32)
    quiet = (loud * 0.01).astype(np.float32)

    with ebur128.Ebur128Meter(sample_rate=sample_rate, channels=2) as meter:
        meter.add_frames_float32(loud)
        loud_lufs = meter.integrated_lufs()

        meter.reset()
        meter.add_frames_float32(quiet)
        quiet_lufs = meter.integrated_lufs()

    assert quiet_lufs < loud_lufs - 35.0


def test_ebur128_meter_rejects_mismatched_audio_shape() -> None:
    require_native_ebur128()

    with ebur128.Ebur128Meter(sample_rate=48_000, channels=2) as meter:
        with pytest.raises(ValueError, match="channel count"):
            meter.add_frames_float32(np.zeros((48_000, 1), dtype=np.float32))

        with pytest.raises(ValueError, match="divisible"):
            meter.add_frames_float32(np.zeros(3, dtype=np.float32))

        with pytest.raises(ValueError, match="floating point"):
            meter.add_frames_float32(np.zeros((48_000, 2), dtype=np.int16))
