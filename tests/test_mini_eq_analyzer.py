from __future__ import annotations

import math
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
    assert analyzer.analyzer_fft_size() == 8192
    assert analyzer.analyzer_fft_size(44100.0) == 8192
    assert analyzer.analyzer_fft_size(96000.0) == 8192
    assert analyzer.analyzer_fft_size(192000.0) == 16384
    assert analyzer.analyzer_fft_size(384000.0) == 32768


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


def test_analyzer_fft_band_overlap_weights_split_boundary_bins() -> None:
    band_indexes, bin_indexes, weights, band_count = analyzer.analyzer_fft_band_overlap_weights(
        8,
        8.0,
        (2.0,),
    )

    assert band_count == 1
    assert band_indexes.tolist() == [0, 0, 0]
    assert bin_indexes.tolist() == [1, 2, 3]
    assert weights.tolist() == pytest.approx(
        [
            1.5 - (2.0 / math.sqrt(2.0)),
            1.0,
            (2.0 * math.sqrt(2.0)) - 2.5,
        ]
    )


def test_samples_to_log_band_powers_match_weighted_band_overlap() -> None:
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
    band_indexes, bin_indexes, weights, band_count = analyzer.analyzer_fft_band_overlap_weights(
        fft_size,
        analyzer.SAMPLE_RATE,
    )
    expected = np.bincount(
        band_indexes,
        weights=bin_powers[bin_indexes] * weights,
        minlength=band_count,
    )

    assert analyzer.samples_to_log_band_powers(samples, fft_size=fft_size) == pytest.approx(tuple(expected))


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


def test_interleaved_f32le_bytes_to_channel_payloads_splits_stereo() -> None:
    interleaved = array("f", [1.0, 0.0, 0.5, -0.5, -0.25, 0.25])

    left, right = analyzer.interleaved_f32le_bytes_to_channel_payloads(interleaved.tobytes(), 2)

    assert list(analyzer.pcm_f32le_bytes_to_samples(left)) == pytest.approx([1.0, 0.5, -0.25])
    assert list(analyzer.pcm_f32le_bytes_to_samples(right)) == pytest.approx([0.0, -0.5, 0.25])


def test_interleaved_f32le_bytes_to_channel_payloads_duplicates_mono() -> None:
    mono = array("f", [0.25, -0.25])

    left, right = analyzer.interleaved_f32le_bytes_to_channel_payloads(mono.tobytes(), 1)

    assert left == mono.tobytes()
    assert right == mono.tobytes()


class FakePwgStream:
    def __init__(self, target_object: str | None, monitor: bool) -> None:
        self.target_object = target_object
        self.monitor = monitor
        self.requested_format = None
        self.pipewire_properties: dict[str, str] = {}
        self.deliver_audio_blocks = False
        self.signal_handlers: list[tuple[str, object]] = []
        self.disconnected: list[int] = []
        self.start_count = 0
        self.stop_count = 0
        self.rate = 44100

    def set_requested_format(self, sample_format: str, rate: int, channels: int) -> None:
        self.requested_format = (sample_format, rate, channels)

    def set_pipewire_property(self, key: str, value: str) -> None:
        self.pipewire_properties[key] = value

    def set_deliver_audio_blocks(self, deliver_audio_blocks: bool) -> None:
        self.deliver_audio_blocks = deliver_audio_blocks

    def connect(self, signal_name: str, callback) -> int:
        self.signal_handlers.append((signal_name, callback))
        return len(self.signal_handlers)

    def disconnect(self, handler_id: int) -> None:
        self.disconnected.append(handler_id)

    def start(self) -> bool:
        self.start_count += 1
        return True

    def stop(self) -> None:
        self.stop_count += 1

    def get_requested_rate(self) -> int:
        return self.requested_format[1] if self.requested_format is not None else analyzer.SAMPLE_RATE

    def get_rate(self) -> int:
        return self.rate


class FakePwg:
    init_count = 0
    streams: list[FakePwgStream] = []

    class Stream:
        @staticmethod
        def new_audio_capture(target_object: str | None, monitor: bool) -> FakePwgStream:
            stream = FakePwgStream(target_object, monitor)
            FakePwg.streams.append(stream)
            return stream

    @staticmethod
    def init() -> None:
        FakePwg.init_count += 1


def test_open_pwg_stream_configures_monitor_capture(monkeypatch: pytest.MonkeyPatch) -> None:
    FakePwg.init_count = 0
    FakePwg.streams = []
    monkeypatch.setattr(
        analyzer.OutputSpectrumAnalyzer,
        "_import_pipewire_gobject",
        staticmethod(lambda: (object(), FakePwg)),
    )
    spectrum = analyzer.OutputSpectrumAnalyzer("alsa_output.test", None, lambda _message: None)

    stream = spectrum.open_pwg_stream()

    assert stream is FakePwg.streams[0]
    assert FakePwg.init_count == 1
    assert stream.target_object == "alsa_output.test"
    assert stream.monitor is True
    assert stream.pipewire_properties["node.name"] == "mini-eq-analyzer"
    assert stream.pipewire_properties["application.name"] == "Mini EQ"
    assert stream.pipewire_properties["media.class"] == analyzer.ANALYZER_MEDIA_CLASS
    assert stream.pipewire_properties["media.category"] == "Monitor"
    assert stream.pipewire_properties["media.role"] == "DSP"
    assert stream.pipewire_properties["node.dont-move"] == "true"
    assert stream.pipewire_properties["stream.monitor"] == "true"
    assert stream.pipewire_properties["state.restore-props"] == "false"
    assert stream.pipewire_properties["state.restore-target"] == "false"
    assert stream.requested_format == ("F32", analyzer.SAMPLE_RATE, 2)
    assert stream.deliver_audio_blocks is True
    assert stream.signal_handlers[0][0] == "audio-block"
    assert spectrum.sample_rate == analyzer.SAMPLE_RATE


def test_enabled_analyzer_recreates_existing_pwg_stream_on_output_change() -> None:
    spectrum = analyzer.OutputSpectrumAnalyzer("old-sink", None, lambda _message: None)
    spectrum.enabled = True
    spectrum.stream = object()
    calls: list[tuple[str, dict[str, object]]] = []

    def stop(**kwargs) -> None:
        calls.append(("stop", kwargs))
        spectrum.stream = None

    def restart() -> bool:
        calls.append(("restart", {}))
        return True

    spectrum.stop = stop
    spectrum.restart = restart

    spectrum.set_output_sink_name("new-sink", "New Sink")

    assert spectrum.output_sink_name == "new-sink"
    assert spectrum.output_sink_description == "New Sink"
    assert calls == [("stop", {"close_stream": True}), ("restart", {})]


def test_prepare_opens_pwg_stream_without_start() -> None:
    spectrum = analyzer.OutputSpectrumAnalyzer("test_sink", None, lambda _message: None)
    stream = FakePwgStream("test_sink", True)
    calls: list[str] = []

    def open_stream():
        calls.append("open")
        return stream

    spectrum.open_pwg_stream = open_stream

    assert spectrum.prepare() is True
    assert spectrum.stream is stream
    assert stream.start_count == 0
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


def test_close_stops_pwg_stream_and_disconnects_signal() -> None:
    spectrum = analyzer.OutputSpectrumAnalyzer("test_sink", None, lambda _message: None)
    stream = FakePwgStream("test_sink", True)
    spectrum.stream = stream
    spectrum.stream_active = True
    spectrum.stream_signal_handler_ids = [7]

    spectrum.close()

    assert stream.stop_count >= 1
    assert stream.disconnected == [7]
    assert spectrum.stream is None
    assert spectrum.stream_active is False


def test_activate_pwg_stream_starts_stream_and_updates_sample_rate() -> None:
    spectrum = analyzer.OutputSpectrumAnalyzer("test_sink", None, lambda _message: None)
    stream = FakePwgStream("test_sink", True)

    spectrum.activate_pwg_stream(stream)

    assert stream.start_count == 1
    assert spectrum.stream_active is True
    assert spectrum.sample_rate == 44100.0


def test_process_audio_block_queues_interleaved_audio() -> None:
    spectrum = analyzer.OutputSpectrumAnalyzer("test_sink", None, lambda _message: None)
    spectrum.stop_event.clear()
    payload = array("f", [1.0, 0.0, 0.5, -0.5]).tobytes()

    class FakeFormat:
        def get_sample_format(self) -> str:
            return "F32"

        def get_rate(self) -> int:
            return 44100

        def get_channels(self) -> int:
            return 2

    class FakeBytes:
        def get_data(self) -> bytes:
            return payload

    class FakeBlock:
        def get_format(self) -> FakeFormat:
            return FakeFormat()

        def get_data(self) -> FakeBytes:
            return FakeBytes()

    spectrum.process_audio_block(None, FakeBlock())

    left, right = spectrum.audio_blocks.pop()
    assert list(analyzer.pcm_f32le_bytes_to_samples(left)) == pytest.approx([1.0, 0.5])
    assert list(analyzer.pcm_f32le_bytes_to_samples(right)) == pytest.approx([0.0, -0.5])
    assert spectrum.sample_rate == 44100.0


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

    spectrum.read_audio_levels()

    assert snapshots == [analyzer.AnalyzerLoudnessSnapshot(-20.0, -18.0, -17.0)]
    assert len(created_meters) == 1
    assert created_meters[0].closed is True
