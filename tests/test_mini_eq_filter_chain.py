from __future__ import annotations

import pytest

from tests._mini_eq_imports import core, filter_chain


def test_pipewire_quote_escapes_module_argument_strings() -> None:
    assert filter_chain.pipewire_quote('a"b\\c') == '"a\\"b\\\\c"'


def test_stable_input_has_no_hardware_fallback_or_fixed_sample_rate() -> None:
    args = filter_chain.build_eq_input_module_args("mini_eq_sink", "mini_eq_sink.dsp")
    assert 'node.name = "mini_eq_sink"' in args
    assert 'target.object = "mini_eq_sink.dsp"' in args
    assert "media.class = Audio/Sink" in args
    assert "node.dont-fallback = true" in args
    assert "node.linger = true" in args
    assert "node.passive = true" in args
    assert "audio.rate" not in args


def test_dsp_input_is_a_stream_not_a_removable_device() -> None:
    args = filter_chain.build_native_biquad_filter_chain_module_args(
        bands=core.default_eq_bands(),
        preamp_db=0,
        eq_enabled=True,
        virtual_sink_name="mini_eq_sink.dsp",
        filter_output_name="mini_eq_sink_output",
        output_sink="speakers",
        capture_as_stream=True,
    )
    assert "media.class = Stream/Input/Audio" in args
    assert "media.class = Audio/Sink" not in args
    assert "node.autoconnect = false" in args
    assert 'target.object = "speakers"' in args
    assert "audio.rate" not in args


def test_native_biquads_follow_graph_rate_and_have_true_bypass() -> None:
    bands = [core.EqBand(core.FILTER_TYPES["Lo-pass"], 1000.0, 0.0, 1.4)]
    args = filter_chain.build_native_biquad_filter_chain_module_args(
        bands=bands,
        preamp_db=0.0,
        eq_enabled=True,
        virtual_sink_name="mini_eq_sink",
        filter_output_name="mini_eq_sink_output",
        output_sink="test",
    )
    assert "audio.rate" not in args
    assert "label = bq_lowpass" in args
    assert 'input = "band_l_0:In 2"' in args
    assert 'output = "band_l_0_filter:Out" input = "band_l_0:In 1"' in args
    enabled = filter_chain.native_biquad_band_control_values(0, bands[0], True, 192000)
    bypass = filter_chain.native_biquad_band_control_values(0, bands[0], False, 192000)
    assert enabled["band_l_0:Gain 1"] == 1
    assert enabled["band_l_0:Gain 2"] == 0
    assert bypass["band_l_0:Gain 1"] == 0
    assert bypass["band_l_0:Gain 2"] == 1
    assert enabled["band_l_0_filter:Freq"] == 1000
    assert enabled == filter_chain.native_biquad_band_control_values(0, bands[0], True, 48000)


def test_native_biquad_solo_and_mute_use_dry_path() -> None:
    bands = [
        core.EqBand(core.FILTER_TYPES["Bell"], 1000, 6, 1),
        core.EqBand(core.FILTER_TYPES["Bell"], 2000, 3, 1, solo=True),
    ]
    controls = filter_chain.native_biquad_control_values(bands, 0, True)
    assert controls["band_l_0:Gain 1"] == 0
    assert controls["band_l_1:Gain 1"] == 1
    bands[1].mute = True
    assert filter_chain.native_biquad_control_values(bands, 0, True)["band_r_1:Gain 1"] == 0


def test_native_graph_skips_off_slots_without_renumbering() -> None:
    bands = core.inactive_eq_bands()
    bands[2] = core.EqBand(core.FILTER_TYPES["Lo-pass"], 1000, 0, 1)
    bands[7] = core.EqBand(core.FILTER_TYPES["Bell"], 2000, 3, 1, mute=True)
    args = filter_chain.build_native_biquad_filter_chain_module_args(
        bands=bands,
        preamp_db=-3,
        eq_enabled=True,
        virtual_sink_name="mini_eq_sink",
        filter_output_name="mini_eq_sink_output",
        output_sink="test",
    )
    for side in ("l", "r"):
        assert f'output = "preamp_{side}:Out" input = "band_{side}_2_filter:In"' in args
        assert f'output = "band_{side}_2:Out" input = "band_{side}_7_filter:In"' in args
        assert f'"band_{side}_7:Out"' in args
        assert f"name = band_{side}_7_filter" in args
    assert "band_l_0" not in args
    assert "band_l_31" not in args
    controls = filter_chain.native_biquad_control_values(bands, -3, True)
    assert controls["band_l_2:Gain 1"] == 1
    assert controls["band_l_7:Gain 1"] == 0
    assert not any("band_l_0" in key or "band_l_31" in key for key in controls)
    assert filter_chain.native_biquad_band_control_values(31, bands[31], True) == {}
    assert len(bands) == core.MAX_BANDS


def test_native_all_off_graph_connects_preamp_to_outputs() -> None:
    args = filter_chain.build_native_biquad_filter_chain_module_args(
        bands=core.inactive_eq_bands(),
        preamp_db=-6,
        eq_enabled=True,
        virtual_sink_name="mini_eq_sink",
        filter_output_name="mini_eq_sink_output",
        output_sink="test",
    )
    assert "band_l_" not in args
    assert 'outputs = [ "preamp_l:Out" "preamp_r:Out" ]' in args


def test_builtin_biquad_filter_chain_uses_pipewire_raw_biquads() -> None:
    bands = [
        core.EqBand(core.FILTER_TYPES["Bell"], 1000.0, 6.0, 1.4),
        core.EqBand(core.FILTER_TYPES["Hi-shelf"], 8000.0, -3.0, 0.707),
    ]

    args = filter_chain.build_builtin_biquad_filter_chain_module_args(
        bands=bands,
        preamp_db=-2.0,
        eq_enabled=True,
        virtual_sink_name="mini_eq_sink",
        filter_output_name="mini_eq_sink_output",
        output_sink="alsa_output.test",
    )

    assert "context.modules" not in args
    assert "libpipewire-module-filter-chain" not in args
    assert "type = lv2" not in args
    assert "plugin =" not in args
    assert "label = bq_raw" in args
    assert "audio.rate = 48000" in args
    assert "name = preamp_l" in args
    assert "name = band_l_0" in args
    assert "name = band_r_1" in args
    assert '{ output = "preamp_l:Out" input = "band_l_0:In" }' in args
    assert 'inputs = [ "preamp_l:In" "preamp_r:In" ]' in args
    assert 'outputs = [ "band_l_1:Out" "band_r_1:Out" ]' in args
    assert 'target.object = "alsa_output.test"' in args
    assert args.count("state.restore-props = false") == 2
    assert args.count("state.restore-target = false") == 2


def test_builtin_biquad_controls_cover_both_channels() -> None:
    band = core.EqBand(core.FILTER_TYPES["Bell"], 1000.0, 6.0, 1.4)

    controls = filter_chain.builtin_biquad_band_control_values(3, band, eq_enabled=True)

    assert set(controls) == {
        "band_l_3:b0",
        "band_l_3:b1",
        "band_l_3:b2",
        "band_l_3:a0",
        "band_l_3:a1",
        "band_l_3:a2",
        "band_r_3:b0",
        "band_r_3:b1",
        "band_r_3:b2",
        "band_r_3:a0",
        "band_r_3:a1",
        "band_r_3:a2",
    }
    assert controls["band_l_3:b0"] == pytest.approx(controls["band_r_3:b0"])


def test_disabled_builtin_biquad_controls_are_identity() -> None:
    band = core.EqBand(core.FILTER_TYPES["Bell"], 1000.0, 6.0, 1.4)

    controls = filter_chain.builtin_biquad_control_values([band], preamp_db=6.0, eq_enabled=False)

    assert controls["preamp_l:b0"] == pytest.approx(1.0)
    assert controls["band_l_0:b0"] == pytest.approx(1.0)
    assert controls["band_l_0:b1"] == pytest.approx(0.0)
    assert controls["band_l_0:a0"] == pytest.approx(1.0)


def test_muted_builtin_biquad_controls_are_identity() -> None:
    band = core.EqBand(core.FILTER_TYPES["Bell"], 1000.0, 6.0, 1.4, mute=True)

    controls = filter_chain.builtin_biquad_band_control_values(0, band, eq_enabled=True)

    assert controls["band_l_0:b0"] == pytest.approx(1.0)
    assert controls["band_l_0:b1"] == pytest.approx(0.0)
    assert controls["band_l_0:a0"] == pytest.approx(1.0)


def test_soloed_builtin_biquad_controls_suppress_other_bands() -> None:
    boost = core.EqBand(core.FILTER_TYPES["Bell"], 1000.0, 6.0, 1.4)
    solo_cut = core.EqBand(core.FILTER_TYPES["Bell"], 1000.0, -4.5, 1.4, solo=True)

    controls = filter_chain.builtin_biquad_control_values([boost, solo_cut], preamp_db=0.0, eq_enabled=True)

    assert controls["band_l_0:b0"] == pytest.approx(1.0)
    assert controls["band_l_0:b1"] == pytest.approx(0.0)
    assert controls["band_l_1:b0"] != pytest.approx(1.0)


def test_scaled_biquad_coefficients_preserve_response_inside_pipewire_control_limits() -> None:
    band = core.EqBand(core.FILTER_TYPES["Hi-shelf"], 10.0, 36.0, 100.0)
    coefficients = core.band_biquad_coefficients(band, core.SAMPLE_RATE)
    scaled = filter_chain.active_band_biquad_coefficients(band, core.SAMPLE_RATE, eq_enabled=True)

    assert max(abs(value) for value in scaled.as_tuple()) <= 10.0

    original_response = core.biquad_response_at_frequency(coefficients, core.SAMPLE_RATE, 20_000.0)
    scaled_response = core.biquad_response_at_frequency(scaled, core.SAMPLE_RATE, 20_000.0)
    assert abs(scaled_response) == pytest.approx(abs(original_response))
