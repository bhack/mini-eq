from __future__ import annotations

import math
import os
import sys
from array import array

import pytest

from tests._mini_eq_imports import import_mini_eq_module

analyzer = import_mini_eq_module("analyzer")


def test_normalize_spectrum_db_uses_dbfs_floor() -> None:
    assert analyzer.normalize_spectrum_db(-100.0) == pytest.approx(0.0)
    assert analyzer.normalize_spectrum_db(-50.0) == pytest.approx(0.5)
    assert analyzer.normalize_spectrum_db(0.0) == pytest.approx(1.0)


def test_spectrum_db_values_to_levels_normalizes_each_band() -> None:
    levels = analyzer.spectrum_db_values_to_levels([-100.0, -75.0, -50.0, 0.0, 12.0])

    assert levels == pytest.approx([0.0, 0.25, 0.5, 1.0, 1.0])


def test_spectrum_level_to_db_reverses_normalized_level() -> None:
    assert analyzer.spectrum_level_to_db(0.0) == pytest.approx(-100.0)
    assert analyzer.spectrum_level_to_db(0.5) == pytest.approx(-50.0)
    assert analyzer.spectrum_level_to_db(1.0) == pytest.approx(0.0)


def test_analyzer_display_mapping_uses_meter_style_deflection() -> None:
    assert analyzer.analyzer_db_to_display_norm(-80.0) == pytest.approx(0.0)
    assert analyzer.analyzer_db_to_display_norm(-60.0) == pytest.approx(2.5 / 115.0)
    assert analyzer.analyzer_db_to_display_norm(-40.0) == pytest.approx(15.0 / 115.0)
    assert analyzer.analyzer_db_to_display_norm(-20.0) == pytest.approx(50.0 / 115.0)
    assert analyzer.analyzer_db_to_display_norm(0.0) == pytest.approx(100.0 / 115.0)
    assert analyzer.analyzer_db_to_display_norm(6.0) == pytest.approx(1.0)


def test_analyzer_display_mapping_applies_visual_gain() -> None:
    quiet_level = analyzer.normalize_spectrum_db(-40.0)

    assert analyzer.analyzer_level_to_display_norm(quiet_level, 20.0) == pytest.approx(
        analyzer.analyzer_db_to_display_norm(-20.0)
    )


def test_analyzer_uses_third_octave_band_layout() -> None:
    centers = analyzer.analyzer_bin_center_frequencies()

    assert len(centers) == analyzer.ANALYZER_BIN_COUNT == 30
    assert centers[0] == pytest.approx(25.0)
    assert centers[-1] == pytest.approx(20_000.0)
    assert centers[16] == pytest.approx(1000.0)
    assert all(left < right for left, right in zip(centers, centers[1:], strict=False))


def test_analyzer_band_edges_wrap_centers_logarithmically() -> None:
    centers = analyzer.analyzer_bin_center_frequencies()
    edges = analyzer.analyzer_band_edges(centers)

    assert len(edges) == len(centers) + 1
    for index, center in enumerate(centers):
        assert edges[index] < center < edges[index + 1]

    assert edges[17] == pytest.approx((1000.0 * 1250.0) ** 0.5)


def test_analyzer_frame_count_uses_fixed_update_interval() -> None:
    assert analyzer.analyzer_frame_count() == int(analyzer.SAMPLE_RATE * analyzer.ANALYZER_INTERVAL_MS / 1000.0)
    assert analyzer.analyzer_frame_count(44100.0) == int(44100.0 * analyzer.ANALYZER_INTERVAL_MS / 1000.0)


def test_analyzer_fft_size_uses_power_of_two_window() -> None:
    assert analyzer.analyzer_fft_size() == 4096
    assert analyzer.analyzer_fft_size(44100.0) == 4096
    assert analyzer.analyzer_fft_size(96000.0) == 8192


def test_analyzer_smoothing_alpha_uses_sample_rate_time_constant() -> None:
    frame_count = analyzer.analyzer_frame_count()

    assert analyzer.analyzer_smoothing_alpha(1.0, frame_count) == pytest.approx(
        1.0 - math.exp(-2.0 * math.pi * frame_count / analyzer.SAMPLE_RATE)
    )
    assert analyzer.analyzer_smoothing_alpha(0.0, frame_count) == pytest.approx(
        1.0 - math.exp(-2.0 * math.pi * analyzer.ANALYZER_RESPONSE_MIN * frame_count / analyzer.SAMPLE_RATE)
    )


def test_smooth_power_values_mixes_per_band_power() -> None:
    smoothed = analyzer.smooth_power_values((0.0, 1.0), (1.0, 0.0), 0.25)

    assert smoothed == pytest.approx((0.25, 0.75))


def test_samples_to_log_band_powers_use_fft_log_band_energy() -> None:
    samples = array(
        "f",
        (
            math.sin(2.0 * math.pi * 1000.0 * index / analyzer.SAMPLE_RATE)
            for index in range(analyzer.analyzer_fft_size())
        ),
    )

    bands = analyzer.samples_to_log_band_powers(samples, fft_size=analyzer.analyzer_fft_size())
    loudest_index = max(range(len(bands)), key=lambda index: bands[index])

    assert len(bands) == analyzer.ANALYZER_BIN_COUNT
    assert analyzer.ANALYZER_BAND_FREQUENCIES[loudest_index] == pytest.approx(1000.0)
    assert bands[loudest_index] > bands[0] * 100.0


def test_samples_to_log_band_powers_match_direct_band_sums() -> None:
    fft_size = analyzer.analyzer_fft_size()
    samples = array(
        "f",
        (
            math.sin(2.0 * math.pi * 1000.0 * index / analyzer.SAMPLE_RATE)
            + (0.25 * math.sin(2.0 * math.pi * 2500.0 * index / analyzer.SAMPLE_RATE))
            for index in range(fft_size)
        ),
    )

    np = analyzer.require_numpy()
    fft_samples = analyzer.samples_to_numpy_window(samples, fft_size)
    window = analyzer.analyzer_fft_window(fft_size)
    amplitude_normalizer = max(float(window.sum()) / 2.0, 1e-12)
    bin_powers = (np.abs(np.fft.rfft(fft_samples * window)) / amplitude_normalizer) ** 2
    bin_powers[0] = 0.0
    expected = tuple(
        float(bin_powers[start:stop].sum())
        for start, stop in analyzer.analyzer_fft_band_bin_ranges(fft_size, analyzer.SAMPLE_RATE)
    )

    assert analyzer.samples_to_log_band_powers(samples, fft_size=fft_size) == pytest.approx(expected)


def test_samples_to_log_band_db_values_detects_sine_frequency() -> None:
    samples = array(
        "f",
        (
            math.sin(2.0 * math.pi * 1000.0 * index / analyzer.SAMPLE_RATE)
            for index in range(analyzer.analyzer_fft_size())
        ),
    )

    bands = analyzer.samples_to_log_band_db_values(samples, fft_size=analyzer.analyzer_fft_size())
    loudest_index = max(range(len(bands)), key=lambda index: bands[index])

    assert analyzer.ANALYZER_BAND_FREQUENCIES[loudest_index] == pytest.approx(1000.0)
    assert bands[loudest_index] > bands[0] + 20.0


@pytest.mark.parametrize("frequency", [5000.0, 8000.0, 12500.0, 16000.0])
def test_samples_to_log_band_db_values_detects_high_sine_frequencies(frequency: float) -> None:
    samples = array(
        "f",
        (
            math.sin(2.0 * math.pi * frequency * index / analyzer.SAMPLE_RATE)
            for index in range(analyzer.analyzer_fft_size())
        ),
    )

    bands = analyzer.samples_to_log_band_db_values(samples, fft_size=analyzer.analyzer_fft_size())
    loudest_index = max(range(len(bands)), key=lambda index: bands[index])

    assert analyzer.ANALYZER_BAND_FREQUENCIES[loudest_index] == pytest.approx(frequency)


def test_analyzer_response_speed_clamps_without_pipeline() -> None:
    spectrum = analyzer.OutputSpectrumAnalyzer("test_sink", None, lambda _message: None)

    spectrum.set_response_speed(100.0)
    assert spectrum.response_speed == pytest.approx(analyzer.ANALYZER_RESPONSE_MAX)

    spectrum.set_response_speed(0.0)
    assert spectrum.response_speed == pytest.approx(analyzer.ANALYZER_RESPONSE_MIN)


def test_pcm_f32le_bytes_to_samples_reads_float_samples() -> None:
    samples = array("f", [0.0, 0.5, -0.25])
    payload = samples.tobytes()

    decoded = analyzer.pcm_f32le_bytes_to_samples(payload)

    assert list(decoded) == pytest.approx([0.0, 0.5, -0.25])


def test_stereo_f32le_bytes_to_mono_samples_downmixes_channels() -> None:
    left = array("f", [1.0, 0.5, -0.25])
    right = array("f", [0.0, -0.5, 0.25])

    decoded = analyzer.stereo_f32le_bytes_to_mono_samples(left.tobytes(), right.tobytes())

    assert list(decoded) == pytest.approx([0.5, 0.0, 0.0])


def test_stereo_f32le_bytes_to_interleaved_float32_preserves_channels() -> None:
    left = array("f", [1.0, 0.5, -0.25])
    right = array("f", [0.0, -0.5, 0.25])

    decoded = analyzer.stereo_f32le_bytes_to_interleaved_float32(left.tobytes(), right.tobytes())

    assert decoded.dtype == analyzer.require_numpy().float32
    assert decoded.tolist() == pytest.approx([1.0, 0.0, 0.5, -0.5, -0.25, 0.25])


class FakeJackPort:
    def __init__(self, name: str) -> None:
        self.name = name
        self.shortname = name.rsplit(":", 1)[-1]


def test_jack_audio_output_ports_for_sink_matches_description() -> None:
    ports = [
        FakeJackPort("Other Sink:monitor_FL"),
        FakeJackPort("Test Sink:monitor_FL"),
        FakeJackPort("Test Sink:monitor_FR"),
    ]

    selected = analyzer.jack_audio_output_ports_for_sink(ports, "alsa_output.test", "Test Sink")

    assert [port.name for port in selected] == ["Test Sink:monitor_FL", "Test Sink:monitor_FR"]


def test_jack_pipewire_props_marks_analyzer_as_monitor() -> None:
    props = analyzer.jack_pipewire_props("node.latency = 512/48000")

    assert "node.latency = 512/48000" in props
    assert "node.autoconnect = false" in props
    assert "stream.monitor = true" in props
    assert "media.category = Monitor" in props


def test_jack_audio_output_ports_for_sink_matches_description_with_pipewire_suffix() -> None:
    ports = [
        FakeJackPort("Test Sink-114:monitor_MONO"),
        FakeJackPort("Bluetooth internal capture stream for Test Sink:monitor_MONO"),
    ]

    selected = analyzer.jack_audio_output_ports_for_sink(ports, "bluez_output.test", "Test Sink")

    assert [port.name for port in selected] == ["Test Sink-114:monitor_MONO"]


def test_select_jack_stereo_output_ports_prefers_monitor_pair() -> None:
    ports = [
        FakeJackPort("Test Sink:playback_FL"),
        FakeJackPort("Test Sink:monitor_FR"),
        FakeJackPort("Test Sink:monitor_FL"),
    ]

    left, right = analyzer.select_jack_stereo_output_ports(ports)

    assert left.name == "Test Sink:monitor_FL"
    assert right.name == "Test Sink:monitor_FR"


def test_select_jack_stereo_output_ports_accepts_aux_monitor_pair() -> None:
    ports = [
        FakeJackPort("Test Sink:monitor_AUX1"),
        FakeJackPort("Test Sink:monitor_AUX0"),
    ]

    left, right = analyzer.select_jack_stereo_output_ports(ports)

    assert left.name == "Test Sink:monitor_AUX0"
    assert right.name == "Test Sink:monitor_AUX1"


def test_select_jack_stereo_output_ports_ignores_capture_ports() -> None:
    ports = [
        FakeJackPort("Test Sink:capture_MONO"),
        FakeJackPort("Test Sink:capture_FL"),
        FakeJackPort("Test Sink:capture_FR"),
    ]

    left, right = analyzer.select_jack_stereo_output_ports(ports)

    assert left is None
    assert right is None


def test_disconnect_jack_input_port_connections_removes_autoconnections() -> None:
    class FakeJackClient:
        def __init__(self) -> None:
            self.disconnected: list[tuple[str, str]] = []

        def get_all_connections(self, port: str) -> list[str]:
            return [f"source-for-{port}"]

        def disconnect(self, source: str, destination: str) -> None:
            self.disconnected.append((source, destination))

    client = FakeJackClient()

    analyzer.disconnect_jack_input_port_connections(client, ("input_FL", "input_FR", None))

    assert client.disconnected == [
        ("source-for-input_FL", "input_FL"),
        ("source-for-input_FR", "input_FR"),
    ]


def test_enabled_analyzer_reconnects_existing_jack_client_on_output_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spectrum = analyzer.OutputSpectrumAnalyzer("old-sink", None, lambda _message: None)
    spectrum.enabled = True
    spectrum.client = object()
    spectrum.left_input_port = "input_FL"
    spectrum.right_input_port = "input_FR"
    calls: list[tuple[str, object]] = []

    monkeypatch.setattr(
        analyzer,
        "disconnect_jack_input_port_connections",
        lambda client, ports: calls.append(("disconnect", ports)),
    )
    spectrum.connect_jack_monitor_ports = lambda client: calls.append(("connect", client))

    spectrum.set_output_sink_name("new-sink", "New Sink")

    assert spectrum.output_sink_name == "new-sink"
    assert spectrum.output_sink_description == "New Sink"
    assert calls == [
        ("disconnect", ("input_FL", "input_FR")),
        ("connect", spectrum.client),
    ]


def test_open_jack_client_sets_pipewire_props_temporarily(monkeypatch: pytest.MonkeyPatch) -> None:
    opened_with_props: list[str | None] = []

    class FakeJackClient:
        def __init__(self, _name: str, no_start_server: bool) -> None:
            assert no_start_server is True
            opened_with_props.append(os.environ.get("PIPEWIRE_PROPS"))
            self.samplerate = 44100

    class FakeJackModule:
        Client = FakeJackClient

    monkeypatch.setitem(sys.modules, "jack", FakeJackModule)
    monkeypatch.setenv("PIPEWIRE_PROPS", "node.latency = 512/48000")
    spectrum = analyzer.OutputSpectrumAnalyzer("test_sink", None, lambda _message: None)

    client = spectrum.open_jack_client()

    assert client.samplerate == 44100
    assert opened_with_props
    assert "node.latency = 512/48000" in opened_with_props[0]
    assert "node.autoconnect = false" in opened_with_props[0]
    assert "stream.monitor = true" in opened_with_props[0]
    assert os.environ["PIPEWIRE_PROPS"] == "node.latency = 512/48000"


def test_prepare_opens_jack_client_without_activating_ports() -> None:
    spectrum = analyzer.OutputSpectrumAnalyzer("test_sink", None, lambda _message: None)
    client = object()
    calls: list[str] = []

    def open_client():
        calls.append("open")
        return client

    spectrum.open_jack_client = open_client

    assert spectrum.prepare() is True
    assert spectrum.client is client
    assert spectrum.left_input_port is None
    assert spectrum.right_input_port is None
    assert calls == ["open"]

    assert spectrum.prepare() is True
    assert calls == ["open"]


def test_stop_uses_short_reader_thread_join_timeout() -> None:
    spectrum = analyzer.OutputSpectrumAnalyzer("test_sink", None, lambda _message: None)
    join_timeouts: list[float] = []

    class FakeReaderThread:
        def join(self, timeout: float) -> None:
            join_timeouts.append(timeout)

    spectrum.reader_thread = FakeReaderThread()

    spectrum.stop()

    assert join_timeouts == [analyzer.ANALYZER_READER_JOIN_TIMEOUT_SECONDS]


def test_close_deactivates_jack_client_once_before_close() -> None:
    spectrum = analyzer.OutputSpectrumAnalyzer("test_sink", None, lambda _message: None)
    calls: list[str] = []

    class FakeClient:
        def deactivate(self) -> None:
            calls.append("deactivate")

        def close(self) -> None:
            calls.append("close")

    spectrum.client = FakeClient()
    spectrum.client_active = True

    spectrum.close()

    assert calls == ["deactivate", "close"]
    assert spectrum.client is None
    assert spectrum.client_active is False


def test_analyzer_registers_terminal_jack_input_ports(monkeypatch: pytest.MonkeyPatch) -> None:
    registered: list[tuple[str, bool]] = []

    class FakeInputPorts:
        def register(self, name: str, is_terminal: bool = False):
            registered.append((name, is_terminal))
            return name

    class FakeJackClient:
        inports = FakeInputPorts()

        def set_process_callback(self, _callback) -> None:
            pass

        def activate(self) -> None:
            pass

    spectrum = analyzer.OutputSpectrumAnalyzer("test_sink", None, lambda _message: None)
    spectrum.connect_jack_monitor_ports = lambda _client: None
    monkeypatch.setattr(analyzer, "disconnect_jack_input_port_connections", lambda _client, _ports: None)

    spectrum.activate_jack_client(FakeJackClient())

    assert registered == [
        (analyzer.JACK_LEFT_INPUT_PORT, True),
        (analyzer.JACK_RIGHT_INPUT_PORT, True),
    ]


def test_analyzer_feeds_loudness_meter_with_interleaved_stereo() -> None:
    left = array("f", [1.0, 0.5])
    right = array("f", [0.25, -0.25])
    spectrum = analyzer.OutputSpectrumAnalyzer("test_sink", None, lambda _message: None)

    class FakeMeter:
        def __init__(self) -> None:
            self.audio = None

        def add_frames_float32(self, audio) -> None:
            self.audio = audio.copy()

    meter = FakeMeter()

    assert spectrum.feed_loudness_meter(meter, left.tobytes(), right.tobytes()) is True

    assert meter.audio.tolist() == pytest.approx([1.0, 0.25, 0.5, -0.25])


def test_analyzer_reads_loudness_snapshot_from_native_meter() -> None:
    spectrum = analyzer.OutputSpectrumAnalyzer("test_sink", None, lambda _message: None)

    class FakeMeter:
        def momentary_lufs(self) -> float:
            return -18.0

        def shortterm_lufs(self) -> float:
            return -16.5

        def integrated_lufs(self) -> float:
            return -15.0

    snapshot = spectrum.read_loudness_snapshot(FakeMeter())

    assert snapshot == analyzer.AnalyzerLoudnessSnapshot(-18.0, -16.5, -15.0)


def test_analyzer_create_loudness_meter_reports_optional_runtime_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    ebur128 = import_mini_eq_module("ebur128")
    messages: list[str] = []
    spectrum = analyzer.OutputSpectrumAnalyzer("test_sink", None, messages.append)

    def unavailable_meter(**_kwargs):
        raise ebur128.Ebur128UnavailableError("missing lib")

    monkeypatch.setattr(ebur128, "Ebur128Meter", unavailable_meter)

    assert spectrum.create_loudness_meter() is None
    assert messages == ["Loudness Unavailable: missing lib"]


def test_analyzer_create_loudness_meter_uses_shortterm_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    ebur128 = import_mini_eq_module("ebur128")
    kwargs_seen = None
    spectrum = analyzer.OutputSpectrumAnalyzer("test_sink", None, lambda _message: None)

    class FakeMeter:
        def __init__(self, **kwargs) -> None:
            nonlocal kwargs_seen
            kwargs_seen = kwargs

    monkeypatch.setattr(ebur128, "Ebur128Meter", FakeMeter)

    assert isinstance(spectrum.create_loudness_meter(), FakeMeter)
    assert kwargs_seen == {
        "sample_rate": 48_000,
        "channels": 2,
        "mode": ebur128.EBUR128_MODE_I | ebur128.EBUR128_MODE_S,
    }


def test_analyzer_starts_loudness_meter_when_callback_is_added_late(monkeypatch: pytest.MonkeyPatch) -> None:
    left = array("f", [0.2]).tobytes()
    right = array("f", [0.1]).tobytes()
    snapshots: list[analyzer.AnalyzerLoudnessSnapshot | None] = []
    created_meters = []
    spectrum = analyzer.OutputSpectrumAnalyzer("test_sink", None, lambda _message: None)
    spectrum.stop_event.clear()
    spectrum.audio_blocks.append((left, right))

    class FakeMeter:
        def __init__(self) -> None:
            self.closed = False

        def add_frames_float32(self, _audio) -> None:
            pass

        def momentary_lufs(self) -> float:
            return -20.0

        def shortterm_lufs(self) -> float:
            return -18.0

        def integrated_lufs(self) -> float:
            return -17.0

        def close(self) -> None:
            self.closed = True

    def create_loudness_meter():
        meter = FakeMeter()
        created_meters.append(meter)
        return meter

    def levels_callback(_levels: list[float]) -> None:
        if spectrum.loudness_callback is None:
            spectrum.set_loudness_callback(snapshots.append)
            spectrum.audio_blocks.append((left, right))
        else:
            spectrum.stop_event.set()

    monkeypatch.setattr(spectrum, "create_loudness_meter", create_loudness_meter)
    monkeypatch.setattr(analyzer, "analyzer_frame_count", lambda _sample_rate=analyzer.SAMPLE_RATE: 1)
    monkeypatch.setattr(analyzer, "analyzer_fft_size", lambda _sample_rate=analyzer.SAMPLE_RATE: 2)
    monkeypatch.setattr(analyzer, "samples_to_log_band_powers", lambda *_args, **_kwargs: (1.0,))
    monkeypatch.setattr(analyzer, "power_values_to_db_values", lambda _powers: (-12.0,))
    monkeypatch.setattr(analyzer, "spectrum_db_values_to_levels", lambda _db_values: [0.5])
    spectrum.set_levels_callback(levels_callback)

    spectrum.read_jack_levels()

    assert snapshots == [analyzer.AnalyzerLoudnessSnapshot(-20.0, -18.0, -17.0)]
    assert len(created_meters) == 1
    assert created_meters[0].closed is True
