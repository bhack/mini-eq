from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests._mini_eq_imports import core


def test_core_import_does_not_require_gi() -> None:
    script = """
import builtins

real_import = builtins.__import__

def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
    if name == "gi" or name.startswith("gi."):
        raise AssertionError("mini_eq.core should not import gi")
    return real_import(name, globals, locals, fromlist, level)

builtins.__import__ = guarded_import
import mini_eq.core
"""
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(["src", env.get("PYTHONPATH", "")])
    subprocess.run([sys.executable, "-c", script], check=True, env=env)


def test_default_preset_storage_uses_standalone_config_namespace(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_dir = tmp_path / "config"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_dir))
    monkeypatch.setattr(core, "PRESET_STORAGE_DIR", None)

    assert core.app_config_dir() == config_dir / "mini-eq"
    assert core.default_preset_storage_dir() == config_dir / "mini-eq" / "output"
    assert core.preset_storage_dir() == core.default_preset_storage_dir()


def test_sanitize_preset_name_removes_invalid_chars_and_trims() -> None:
    assert core.sanitize_preset_name('  bad<>:"/\\\\|?* name...  ') == "bad name"


def test_preset_roundtrip_and_listing_uses_storage_dir(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    storage_dir = tmp_path / "mini-eq-presets"
    monkeypatch.setattr(core, "PRESET_STORAGE_DIR", storage_dir)

    alpha_payload = {"version": core.PRESET_VERSION, "name": "Alpha", "bands": []}
    beta_payload = {"version": core.PRESET_VERSION, "name": "beta", "bands": [{}]}

    core.write_mini_eq_preset_file(core.preset_path_for_name("beta"), beta_payload)
    core.write_mini_eq_preset_file(core.preset_path_for_name("Alpha"), alpha_payload)

    assert core.list_preset_names() == ["Alpha", "beta"]
    assert core.load_mini_eq_preset_file(core.preset_path_for_name("beta")) == beta_payload


def test_load_mini_eq_preset_file_rejects_invalid_shape(tmp_path) -> None:
    preset_path = tmp_path / "broken.json"
    preset_path.write_text('{"version": 1, "bands": "nope"}', encoding="utf-8")

    with pytest.raises(ValueError, match="bands list"):
        core.load_mini_eq_preset_file(preset_path)


def test_eq_band_from_dict_clamps_out_of_range_values() -> None:
    fallback = core.EqBand(
        filter_type=core.FILTER_TYPES["Bell"],
        frequency=1000.0,
        gain_db=0.0,
        q=1.0,
        mode=core.EQ_MODES["Live PipeWire"],
        slope=2,
        mute=False,
        solo=True,
    )

    band = core.eq_band_from_dict(
        {
            "filter_type": 999,
            "frequency": 999999.0,
            "gain_db": -999.0,
            "q": 0.0,
            "mode": 999,
            "slope": -1,
            "mute": 1,
            "solo": "",
        },
        fallback,
    )

    assert band.filter_type == core.FILTER_TYPES["Off"]
    assert band.frequency == core.EQ_FREQUENCY_MAX_HZ
    assert band.gain_db == core.EQ_GAIN_MIN_DB
    assert band.q == core.EQ_Q_MIN
    assert band.mode == fallback.mode
    assert band.slope == fallback.slope
    assert band.mute is True
    assert band.solo is False


def test_eq_band_default_q_is_valid_and_round_trips() -> None:
    band = core.EqBand(filter_type=core.FILTER_TYPES["Bell"], frequency=1000.0)
    fallback = core.EqBand(filter_type=core.FILTER_TYPES["Off"], frequency=100.0, q=1.0)

    loaded = core.eq_band_from_dict(core.eq_band_to_dict(band), fallback)

    assert core.EQ_Q_MIN <= band.q <= core.EQ_Q_MAX
    assert loaded.q == pytest.approx(band.q)


def test_selectable_filter_types_match_supported_apo_response_types() -> None:
    assert core.FILTER_TYPE_ORDER == [
        "Off",
        "Bell",
        "Hi-pass",
        "Hi-shelf",
        "Lo-pass",
        "Lo-shelf",
        "Notch",
        "Allpass",
        "Bandpass",
    ]
    assert core.FILTER_TYPES["Resonance"] not in core.SUPPORTED_APO_FILTER_TYPE_VALUES
    assert core.FILTER_TYPES["Ladder-pass"] not in core.SUPPORTED_APO_FILTER_TYPE_VALUES
    assert core.FILTER_TYPES["Ladder-rej"] not in core.SUPPORTED_APO_FILTER_TYPE_VALUES


def test_unsupported_apo_filter_types_are_flat_and_load_as_off() -> None:
    fallback = core.EqBand(filter_type=core.FILTER_TYPES["Bell"], frequency=1000.0)

    loaded = core.eq_band_from_dict(
        {
            "filter_type": core.FILTER_TYPES["Resonance"],
            "frequency": 1000.0,
            "gain_db": 6.0,
            "q": 3.0,
        },
        fallback,
    )

    assert loaded.filter_type == core.FILTER_TYPES["Off"]

    unsupported = core.EqBand(
        filter_type=core.FILTER_TYPES["Resonance"],
        frequency=1000.0,
        gain_db=6.0,
        q=3.0,
        mode=core.EQ_MODE_APO,
    )
    assert core.total_response_db([unsupported], 0.0, 48000.0, 1000.0) == pytest.approx(0.0)


def test_fader_band_count_for_profile_uses_active_profile_band_count() -> None:
    bands = core.inactive_eq_bands()
    bands[2].filter_type = core.FILTER_TYPES["Bell"]

    assert core.profile_band_count(bands) == 3
    assert core.fader_band_count_for_profile(bands) == 3

    bands[14].filter_type = core.FILTER_TYPES["Bell"]
    assert core.profile_band_count(bands) == 15
    assert core.fader_band_count_for_profile(bands) == 15


def test_parse_apo_file_reads_preamp_and_sorts_filters(tmp_path) -> None:
    apo_path = tmp_path / "example.txt"
    apo_path.write_text(
        "\n".join(
            [
                "# comment",
                "Filter 2: ON HS Fc 4000 Hz Gain 2.5 dB",
                "Preamp: -6 dB",
                "Filter 1: ON PK Fc 200 Hz Gain -3 dB Q 1.5",
            ]
        ),
        encoding="utf-8",
    )

    preamp_db, bands = core.parse_apo_file(str(apo_path))

    assert preamp_db == pytest.approx(-6.0)
    assert [band.frequency for band in bands] == pytest.approx([200.0, 4000.0])
    assert bands[0].filter_type == core.FILTER_TYPES["Bell"]
    assert bands[0].gain_db == pytest.approx(-3.0)
    assert bands[0].q == pytest.approx(1.5)
    assert bands[1].filter_type == core.FILTER_TYPES["Hi-shelf"]
    assert bands[1].gain_db == pytest.approx(2.5)
    assert bands[1].q == pytest.approx(2.0 / 3.0)


def test_total_response_db_stays_near_preamp_for_flat_curve() -> None:
    flat_band = core.EqBand(filter_type=core.FILTER_TYPES["Off"], frequency=1000.0)
    response_db = core.total_response_db([flat_band], 3.0, 48000.0, 1000.0)
    assert response_db == pytest.approx(3.0, abs=1e-6)


def test_muted_band_is_not_part_of_response() -> None:
    band = core.EqBand(filter_type=core.FILTER_TYPES["Bell"], frequency=1000.0, gain_db=6.0, q=1.4, mute=True)

    response_db = core.total_response_db([band], 0.0, 48000.0, 1000.0)

    assert response_db == pytest.approx(0.0, abs=1e-6)


def test_soloed_band_suppresses_non_solo_bands() -> None:
    boost = core.EqBand(filter_type=core.FILTER_TYPES["Bell"], frequency=1000.0, gain_db=6.0, q=1.4)
    solo_cut = core.EqBand(
        filter_type=core.FILTER_TYPES["Bell"],
        frequency=1000.0,
        gain_db=-4.5,
        q=1.4,
        solo=True,
    )

    response_db = core.total_response_db([boost, solo_cut], 0.0, 48000.0, 1000.0)

    assert response_db == pytest.approx(-4.5, abs=0.01)


def test_estimate_response_peak_uses_combined_transfer_function() -> None:
    bands = [
        core.EqBand(filter_type=core.FILTER_TYPES["Bell"], frequency=1000.0, gain_db=6.0, q=2.0),
        core.EqBand(filter_type=core.FILTER_TYPES["Bell"], frequency=1000.0, gain_db=6.0, q=2.0),
    ]

    peak = core.estimate_response_peak_db(bands, -3.0, 48000.0, steps=256)

    assert peak == pytest.approx(9.0, abs=0.2)


def test_estimate_response_peak_samples_filter_centers() -> None:
    bands = [
        core.EqBand(filter_type=core.FILTER_TYPES["Bell"], frequency=1234.5, gain_db=8.0, q=6.0),
    ]

    peak = core.estimate_response_peak_db(bands, -1.0, 48000.0)

    assert peak == pytest.approx(7.0, abs=0.05)


def test_estimate_response_peak_is_not_display_clamped() -> None:
    bands = [
        core.EqBand(filter_type=core.FILTER_TYPES["Bell"], frequency=1000.0, gain_db=20.0, q=2.0),
        core.EqBand(filter_type=core.FILTER_TYPES["Bell"], frequency=1000.0, gain_db=20.0, q=2.0),
    ]

    peak = core.estimate_response_peak_db(bands, 0.0, 48000.0)

    assert peak > core.GRAPH_DB_MAX + 12.0
    assert peak == pytest.approx(40.0, abs=0.1)


def test_vectorized_response_matches_scalar_response() -> None:
    bands = [
        core.EqBand(filter_type=core.FILTER_TYPES["Bell"], frequency=800.0, gain_db=4.0, q=1.2),
        core.EqBand(filter_type=core.FILTER_TYPES["Hi-shelf"], frequency=5000.0, gain_db=-3.0, q=0.7),
    ]

    vector_response = core.total_response_db_at_frequencies(bands, -2.0, 48000.0, [1000.0])[0]
    scalar_response = core.total_response_db(bands, -2.0, 48000.0, 1000.0)

    assert vector_response == pytest.approx(scalar_response, abs=1e-9)


def test_bell_response_uses_gain_db_at_center_frequency() -> None:
    boost = core.EqBand(filter_type=core.FILTER_TYPES["Bell"], frequency=1000.0, gain_db=6.0, q=1.4)
    cut = core.EqBand(filter_type=core.FILTER_TYPES["Bell"], frequency=1000.0, gain_db=-4.5, q=1.4)

    assert core.total_response_db([boost], 0.0, 48000.0, 1000.0) == pytest.approx(6.0, abs=0.01)
    assert core.total_response_db([cut], 0.0, 48000.0, 1000.0) == pytest.approx(-4.5, abs=0.01)


def test_bell_response_uses_q_for_bandwidth() -> None:
    wide = core.EqBand(filter_type=core.FILTER_TYPES["Bell"], frequency=1000.0, gain_db=6.0, q=0.5)
    narrow = core.EqBand(filter_type=core.FILTER_TYPES["Bell"], frequency=1000.0, gain_db=6.0, q=5.0)

    wide_off_center = core.total_response_db([wide], 0.0, 48000.0, 1600.0)
    narrow_off_center = core.total_response_db([narrow], 0.0, 48000.0, 1600.0)

    assert wide_off_center > narrow_off_center
    assert narrow_off_center < 1.0


def test_compute_log_spaced_band_defaults_returns_monotonic_bands() -> None:
    defaults = core.compute_log_spaced_band_defaults(10)

    assert len(defaults) == 10
    assert all(freq > 0.0 and q_value > 0.0 for freq, q_value in defaults)
    assert [freq for freq, _ in defaults] == sorted(freq for freq, _ in defaults)
    assert defaults[0][0] >= core.GRAPH_FREQ_MIN
    assert defaults[-1][0] <= core.GRAPH_FREQ_MAX
