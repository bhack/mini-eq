from __future__ import annotations

import math
import sys
import threading
import time
from array import array
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache

from .core import GRAPH_FREQ_MAX, GRAPH_FREQ_MIN, SAMPLE_RATE, clamp

ANALYZER_BAND_FREQUENCIES = (
    25.0,
    31.5,
    40.0,
    50.0,
    63.0,
    80.0,
    100.0,
    125.0,
    160.0,
    200.0,
    250.0,
    315.0,
    400.0,
    500.0,
    630.0,
    800.0,
    1000.0,
    1250.0,
    1600.0,
    2000.0,
    2500.0,
    3150.0,
    4000.0,
    5000.0,
    6300.0,
    8000.0,
    10000.0,
    12500.0,
    16000.0,
    20000.0,
)
ANALYZER_BIN_COUNT = len(ANALYZER_BAND_FREQUENCIES)
ANALYZER_DB_FLOOR = -100.0
ANALYZER_INTERVAL_MS = 33
ANALYZER_FFT_WINDOW_SECONDS = 0.085
ANALYZER_FFT_MIN_SIZE = 8192
ANALYZER_FFT_MAX_SIZE = 32768
ANALYZER_SAMPLE_WIDTH_BYTES = 4
ANALYZER_QUEUE_WAIT_SECONDS = 0.005
ANALYZER_READER_JOIN_TIMEOUT_SECONDS = 0.2
ANALYZER_DISPLAY_GAIN_MIN = -12.0
ANALYZER_DISPLAY_GAIN_MAX = 32.0
ANALYZER_DISPLAY_GAIN_DEFAULT = 0.0
ANALYZER_CAPTURE_QUEUE_BLOCKS = 128
ANALYZER_NODE_NAME = "mini-eq-analyzer"
ANALYZER_NODE_DESCRIPTION = "Mini EQ Monitor"
ANALYZER_APPLICATION_ID = "io.github.bhack.mini-eq"
ANALYZER_MEDIA_CLASS = "Stream/Input/Audio/Internal"
ANALYZER_PIPEWIRE_PROPERTIES = (
    ("node.name", ANALYZER_NODE_NAME),
    ("node.description", ANALYZER_NODE_DESCRIPTION),
    ("application.name", "Mini EQ"),
    ("application.id", ANALYZER_APPLICATION_ID),
    ("media.name", ANALYZER_NODE_DESCRIPTION),
    ("media.class", ANALYZER_MEDIA_CLASS),
    ("media.category", "Monitor"),
    ("media.role", "DSP"),
    ("node.dont-move", "true"),
    ("stream.monitor", "true"),
    ("state.restore-props", "false"),
    ("state.restore-target", "false"),
)
ANALYZER_RESPONSE_MIN = 0.02
ANALYZER_RESPONSE_MAX = 15.0
ANALYZER_RESPONSE_DEFAULT = 2.0
ANALYZER_POWER_FLOOR = 10.0 ** (ANALYZER_DB_FLOOR / 10.0)
LOUDNESS_EMIT_INTERVAL_SECONDS = 0.25
_numpy_module = None


@dataclass(frozen=True)
class AnalyzerLoudnessSnapshot:
    momentary_lufs: float
    shortterm_lufs: float
    integrated_lufs: float


def require_numpy():
    global _numpy_module

    if _numpy_module is not None:
        return _numpy_module

    try:
        import numpy
    except Exception as exc:  # pragma: no cover - depends on installed Python deps
        raise RuntimeError("Mini EQ analyzer requires NumPy for FFT analysis") from exc

    _numpy_module = numpy
    return numpy


def normalize_spectrum_db(db_value: float) -> float:
    return clamp((db_value - ANALYZER_DB_FLOOR) / abs(ANALYZER_DB_FLOOR), 0.0, 1.0)


def spectrum_level_to_db(level: float) -> float:
    return ANALYZER_DB_FLOOR + (clamp(float(level), 0.0, 1.0) * abs(ANALYZER_DB_FLOOR))


def analyzer_db_to_display_norm(db_value: float, display_gain_db: float = 0.0) -> float:
    display_db = float(db_value) + float(display_gain_db)

    # Match the useful x42-style meter shape: hide very low noise, expand the musical range.
    if display_db < -70.0:
        deflection = 0.0
    elif display_db < -60.0:
        deflection = (display_db + 70.0) * 0.25
    elif display_db < -50.0:
        deflection = ((display_db + 60.0) * 0.5) + 2.5
    elif display_db < -40.0:
        deflection = ((display_db + 50.0) * 0.75) + 7.5
    elif display_db < -30.0:
        deflection = ((display_db + 40.0) * 1.5) + 15.0
    elif display_db < -20.0:
        deflection = ((display_db + 30.0) * 2.0) + 30.0
    elif display_db < 6.0:
        deflection = ((display_db + 20.0) * 2.5) + 50.0
    else:
        deflection = 115.0

    return clamp(deflection / 115.0, 0.0, 1.0)


def analyzer_level_to_display_norm(level: float, display_gain_db: float = 0.0) -> float:
    return analyzer_db_to_display_norm(spectrum_level_to_db(level), display_gain_db)


def spectrum_db_values_to_levels(db_values: tuple[float, ...] | list[float]) -> list[float]:
    return [normalize_spectrum_db(float(value)) for value in db_values]


def analyzer_frame_count(sample_rate: float = SAMPLE_RATE) -> int:
    return max(1, int(max(1.0, float(sample_rate)) * ANALYZER_INTERVAL_MS / 1000.0))


def next_power_of_two(value: int) -> int:
    return 1 << max(0, int(value) - 1).bit_length()


def analyzer_fft_size(sample_rate: float = SAMPLE_RATE) -> int:
    target = int(max(1.0, float(sample_rate)) * ANALYZER_FFT_WINDOW_SECONDS)
    return int(clamp(next_power_of_two(target), ANALYZER_FFT_MIN_SIZE, ANALYZER_FFT_MAX_SIZE))


def analyzer_smoothing_alpha(
    response_speed: float,
    frame_count: int,
    sample_rate: float = SAMPLE_RATE,
) -> float:
    speed = clamp(float(response_speed), ANALYZER_RESPONSE_MIN, ANALYZER_RESPONSE_MAX)
    return 1.0 - math.exp(-2.0 * math.pi * speed * max(1, int(frame_count)) / max(1.0, float(sample_rate)))


@lru_cache(maxsize=32)
def analyzer_bin_center_frequencies(
    level_count: int = ANALYZER_BIN_COUNT,
    freq_min: float = GRAPH_FREQ_MIN,
    freq_max: float = GRAPH_FREQ_MAX,
) -> tuple[float, ...]:
    if level_count == ANALYZER_BIN_COUNT and freq_min == GRAPH_FREQ_MIN and freq_max == GRAPH_FREQ_MAX:
        return ANALYZER_BAND_FREQUENCIES

    log_min = math.log(freq_min)
    log_span = math.log(freq_max / freq_min)
    return tuple(math.exp(log_min + (log_span * (index + 0.5) / level_count)) for index in range(level_count))


@lru_cache(maxsize=32)
def analyzer_band_edges(
    center_frequencies: tuple[float, ...] = ANALYZER_BAND_FREQUENCIES,
) -> tuple[float, ...]:
    if not center_frequencies:
        return ()
    if len(center_frequencies) == 1:
        center = center_frequencies[0]
        return (center / math.sqrt(2.0), center * math.sqrt(2.0))

    middle_edges = [
        math.sqrt(left * right) for left, right in zip(center_frequencies, center_frequencies[1:], strict=False)
    ]
    first_edge = center_frequencies[0] * center_frequencies[0] / middle_edges[0]
    last_edge = center_frequencies[-1] * center_frequencies[-1] / middle_edges[-1]
    return (first_edge, *middle_edges, last_edge)


def pcm_f32le_bytes_to_samples(payload: bytes) -> array:
    usable_size = len(payload) - (len(payload) % ANALYZER_SAMPLE_WIDTH_BYTES)
    samples = array("f")
    samples.frombytes(payload[:usable_size])
    if sys.byteorder != "little":
        samples.byteswap()
    return samples


def stereo_f32le_bytes_to_mono_samples(left_payload: bytes, right_payload: bytes | None = None) -> array:
    left_samples = pcm_f32le_bytes_to_samples(left_payload)
    if right_payload is None:
        return left_samples

    usable_size = min(len(left_payload), len(right_payload))
    usable_size -= usable_size % ANALYZER_SAMPLE_WIDTH_BYTES
    sample_count = usable_size // ANALYZER_SAMPLE_WIDTH_BYTES
    if sample_count == 0:
        return array("f")

    np = require_numpy()
    left_values = np.frombuffer(left_payload[:usable_size], dtype="<f4")
    right_values = np.frombuffer(right_payload[:usable_size], dtype="<f4")
    mono_values = ((left_values + right_values) * np.float32(0.5)).astype(np.float32, copy=False)
    samples = array("f")
    samples.frombytes(mono_values.tobytes())
    return samples


def stereo_f32le_bytes_to_interleaved_float32(left_payload: bytes, right_payload: bytes) -> object:
    usable_size = min(len(left_payload), len(right_payload))
    usable_size -= usable_size % ANALYZER_SAMPLE_WIDTH_BYTES
    if usable_size == 0:
        return require_numpy().array([], dtype=require_numpy().float32)

    np = require_numpy()
    left_values = np.frombuffer(left_payload[:usable_size], dtype="<f4")
    right_values = np.frombuffer(right_payload[:usable_size], dtype="<f4")
    interleaved = np.empty(left_values.size * 2, dtype=np.float32)
    interleaved[0::2] = left_values
    interleaved[1::2] = right_values
    return interleaved


def interleaved_f32le_bytes_to_channel_payloads(payload: bytes, channels: int) -> tuple[bytes, bytes]:
    channel_count = max(1, int(channels))
    frame_size = ANALYZER_SAMPLE_WIDTH_BYTES * channel_count
    usable_size = len(payload) - (len(payload) % frame_size)
    if usable_size == 0:
        return b"", b""

    if channel_count == 1:
        mono_payload = payload[:usable_size]
        return mono_payload, mono_payload

    np = require_numpy()
    frames = np.frombuffer(payload[:usable_size], dtype="<f4").reshape(-1, channel_count)
    left = np.ascontiguousarray(frames[:, 0]).astype(np.float32, copy=False).tobytes()
    right = np.ascontiguousarray(frames[:, 1]).astype(np.float32, copy=False).tobytes()
    return left, right


def samples_to_numpy_window(samples: array, fft_size: int):
    np = require_numpy()
    size = max(2, int(fft_size))
    try:
        sample_values = np.frombuffer(samples, dtype=np.float32)
    except TypeError:
        sample_values = np.asarray(samples, dtype=np.float32)

    if len(sample_values) >= size:
        return sample_values[-size:]

    fft_samples = np.zeros(size, dtype=np.float32)
    if len(sample_values) > 0:
        fft_samples[-len(sample_values) :] = sample_values
    return fft_samples


@lru_cache(maxsize=16)
def analyzer_fft_window(fft_size: int):
    np = require_numpy()
    return np.hanning(max(2, int(fft_size))).astype(np.float32)


@lru_cache(maxsize=16)
def analyzer_fft_amplitude_normalizer(fft_size: int) -> float:
    return max(float(analyzer_fft_window(fft_size).sum()) / 2.0, 1e-12)


@lru_cache(maxsize=64)
def analyzer_fft_band_overlap_weights(
    fft_size: int,
    sample_rate: float,
    center_frequencies: tuple[float, ...] = ANALYZER_BAND_FREQUENCIES,
):
    np = require_numpy()
    size = max(2, int(fft_size))
    sample_rate_hz = max(1.0, float(sample_rate))
    band_count = len(center_frequencies)
    frequencies = np.fft.rfftfreq(size, 1.0 / sample_rate_hz)
    if band_count == 0 or len(frequencies) == 0:
        band_indexes = np.array([], dtype=np.intp)
        bin_indexes = np.array([], dtype=np.intp)
        weights = np.array([], dtype=np.float64)
        band_indexes.setflags(write=False)
        bin_indexes.setflags(write=False)
        weights.setflags(write=False)
        return band_indexes, bin_indexes, weights, band_count

    bin_width = max(sample_rate_hz / size, 1e-12)
    bin_left = frequencies - (bin_width * 0.5)
    bin_right = frequencies + (bin_width * 0.5)
    bin_left[0] = 0.0
    bin_right[-1] = min(sample_rate_hz * 0.5, bin_right[-1])
    bin_widths = np.maximum(bin_right - bin_left, 1e-12)

    edges = np.asarray(analyzer_band_edges(center_frequencies), dtype=np.float64)
    nyquist = sample_rate_hz * 0.5
    band_left = np.clip(edges[:-1], 0.0, nyquist)
    band_right = np.clip(edges[1:], 0.0, nyquist)

    overlap_left = np.maximum(band_left[:, None], bin_left[None, :])
    overlap_right = np.minimum(band_right[:, None], bin_right[None, :])
    overlaps = np.maximum(0.0, overlap_right - overlap_left)
    band_indexes, bin_indexes = np.nonzero(overlaps > 0.0)
    weights = overlaps[band_indexes, bin_indexes] / bin_widths[bin_indexes]

    band_indexes = band_indexes.astype(np.intp, copy=False)
    bin_indexes = bin_indexes.astype(np.intp, copy=False)
    weights = weights.astype(np.float64, copy=False)
    band_indexes.setflags(write=False)
    bin_indexes.setflags(write=False)
    weights.setflags(write=False)
    return band_indexes, bin_indexes, weights, band_count


def samples_to_log_band_powers(
    samples: array,
    *,
    sample_rate: float = SAMPLE_RATE,
    center_frequencies: tuple[float, ...] = ANALYZER_BAND_FREQUENCIES,
    fft_size: int | None = None,
) -> tuple[float, ...]:
    if not samples:
        return ()

    np = require_numpy()
    size = fft_size or len(samples)
    fft_samples = samples_to_numpy_window(samples, size)
    window = analyzer_fft_window(size)
    windowed_samples = fft_samples * window
    spectrum = np.fft.rfft(windowed_samples)
    amplitude_normalizer = analyzer_fft_amplitude_normalizer(size)
    bin_powers = (np.abs(spectrum) / amplitude_normalizer) ** 2
    if len(bin_powers) > 0:
        bin_powers[0] = 0.0

    band_indexes, bin_indexes, weights, band_count = analyzer_fft_band_overlap_weights(
        size,
        sample_rate,
        center_frequencies,
    )
    if band_count == 0:
        return ()

    if len(bin_indexes) == 0:
        return (0.0,) * band_count

    weighted_bin_powers = bin_powers[bin_indexes] * weights
    band_powers = np.bincount(band_indexes, weights=weighted_bin_powers, minlength=band_count)
    return tuple(float(power) for power in band_powers)


def smooth_power_values(
    previous: tuple[float, ...],
    current: tuple[float, ...],
    alpha: float,
) -> tuple[float, ...]:
    if not current:
        return previous
    if len(previous) != len(current):
        previous = (0.0,) * len(current)

    mix = clamp(float(alpha), 0.0, 1.0)
    return tuple(old + (mix * (new - old)) for old, new in zip(previous, current, strict=True))


def power_values_to_db_values(power_values: tuple[float, ...]) -> tuple[float, ...]:
    return tuple(
        max(10.0 * math.log10(max(float(power), ANALYZER_POWER_FLOOR)), ANALYZER_DB_FLOOR) for power in power_values
    )


def samples_to_log_band_db_values(
    samples: array,
    *,
    sample_rate: float = SAMPLE_RATE,
    center_frequencies: tuple[float, ...] = ANALYZER_BAND_FREQUENCIES,
    fft_size: int | None = None,
) -> tuple[float, ...]:
    return power_values_to_db_values(
        samples_to_log_band_powers(
            samples,
            sample_rate=sample_rate,
            center_frequencies=center_frequencies,
            fft_size=fft_size,
        )
    )


class OutputSpectrumAnalyzer:
    def __init__(
        self,
        output_sink_name: str,
        levels_callback: Callable[[list[float]], None] | None,
        status_callback: Callable[[str], None],
        output_sink_description: str | None = None,
        loudness_callback: Callable[[AnalyzerLoudnessSnapshot | None], None] | None = None,
    ) -> None:
        self.output_sink_name = output_sink_name
        self.output_sink_description = output_sink_description
        self.levels_callback = levels_callback
        self.loudness_callback = loudness_callback
        self.status_callback = status_callback
        self.enabled = False
        self.stream = None
        self.stream_active = False
        self.stream_signal_handler_ids: list[int] = []
        self.reader_thread: threading.Thread | None = None
        self.stop_event = threading.Event()
        self.stop_event.set()
        self.audio_blocks = deque(maxlen=ANALYZER_CAPTURE_QUEUE_BLOCKS)
        self.sample_rate = SAMPLE_RATE
        self.response_speed = ANALYZER_RESPONSE_DEFAULT

    @property
    def client(self):
        return self.stream

    def set_levels_callback(self, callback: Callable[[list[float]], None] | None) -> None:
        self.levels_callback = callback

    def set_loudness_callback(self, callback: Callable[[AnalyzerLoudnessSnapshot | None], None] | None) -> None:
        self.loudness_callback = callback

    def set_response_speed(self, speed: float) -> None:
        self.response_speed = clamp(float(speed), ANALYZER_RESPONSE_MIN, ANALYZER_RESPONSE_MAX)

    def set_output_sink_name(self, sink_name: str, sink_description: str | None = None) -> None:
        if sink_name == self.output_sink_name and sink_description == self.output_sink_description:
            return

        self.output_sink_name = sink_name
        self.output_sink_description = sink_description
        if self.stream is not None:
            self.stop(close_stream=True)

        if not self.enabled:
            return

        self.restart()

    def set_enabled(self, enabled: bool) -> bool:
        self.enabled = bool(enabled)

        if not self.enabled:
            self.stop()
            return True

        return self.start()

    def start(self) -> bool:
        if self.reader_thread is not None:
            return True

        self.audio_blocks.clear()
        self.stop_event.clear()

        try:
            if self.stream is None:
                self.stream = self.open_pwg_stream()
            self.activate_pwg_stream(self.stream)
        except Exception as exc:
            self.stop_event.set()
            self.status_callback(f"Analyzer Unavailable: {exc}")
            return False

        self.reader_thread = threading.Thread(target=self.read_audio_levels, name="mini-eq-analyzer", daemon=True)
        self.reader_thread.start()
        return True

    def prepare(self) -> bool:
        if self.stream is not None:
            return True

        try:
            self.stream = self.open_pwg_stream()
        except Exception:
            return False

        return True

    def stop(self, *, close_stream: bool = False, close_client: bool | None = None) -> None:
        if close_client is not None:
            close_stream = close_client

        stream = self.stream
        reader_thread = self.reader_thread

        self.reader_thread = None
        self.stop_event.set()
        self.audio_blocks.clear()
        self.emit_loudness_snapshot(None)

        if stream is not None and self.stream_active:
            self.deactivate_pwg_stream(stream)

        if reader_thread is not None and reader_thread is not threading.current_thread():
            reader_thread.join(timeout=ANALYZER_READER_JOIN_TIMEOUT_SECONDS)

        if close_stream and stream is not None:
            self.close_pwg_stream(stream)
            self.stream = None

    def close(self) -> None:
        self.stop(close_stream=True)

    def restart(self) -> bool:
        self.stop(close_stream=True)
        if not self.enabled:
            return True

        return self.start()

    def open_pwg_stream(self):
        _GLib, Pwg = self._import_pipewire_gobject()
        Pwg.init()
        stream = Pwg.Stream.new_audio_capture(self.output_sink_name, True)
        set_pipewire_property = getattr(stream, "set_pipewire_property", None)
        if callable(set_pipewire_property):
            for key, value in ANALYZER_PIPEWIRE_PROPERTIES:
                set_pipewire_property(key, value)
        stream.set_requested_format("F32", int(SAMPLE_RATE), 2)
        stream.set_deliver_audio_blocks(True)
        handler_id = stream.connect("audio-block", self.process_audio_block)
        self.stream_signal_handler_ids = [handler_id]
        self.sample_rate = float(stream.get_requested_rate() or SAMPLE_RATE)
        return stream

    def activate_pwg_stream(self, stream) -> None:
        if self.stream_active:
            return

        try:
            if not stream.start():
                raise RuntimeError("PipeWire analyzer stream failed to start")
            self.stream_active = True
            self.sample_rate = float(stream.get_rate() or stream.get_requested_rate() or SAMPLE_RATE)
        except Exception:
            self.deactivate_pwg_stream(stream)
            raise

    def deactivate_pwg_stream(self, stream) -> None:
        try:
            stream.stop()
        except Exception:
            pass

        self.stream_active = False

    def close_pwg_stream(self, stream) -> None:
        if self.stream_active:
            self.deactivate_pwg_stream(stream)

        for handler_id in self.stream_signal_handler_ids:
            try:
                stream.disconnect(handler_id)
            except Exception:
                pass
        self.stream_signal_handler_ids = []

        try:
            stream.stop()
        except Exception:
            pass

    def create_loudness_meter(self):
        try:
            from .ebur128 import EBUR128_MODE_I, EBUR128_MODE_S, Ebur128Meter

            return Ebur128Meter(
                sample_rate=int(round(self.sample_rate)),
                channels=2,
                mode=EBUR128_MODE_I | EBUR128_MODE_S,
            )
        except Exception as exc:
            self.status_callback(f"Loudness Unavailable: {exc}")
            return None

    def emit_loudness_snapshot(self, snapshot: AnalyzerLoudnessSnapshot | None) -> None:
        callback = self.loudness_callback
        if callback is not None:
            callback(snapshot)

    def feed_loudness_meter(self, meter, left_payload: bytes, right_payload: bytes) -> bool:
        interleaved = stereo_f32le_bytes_to_interleaved_float32(left_payload, right_payload)
        if len(interleaved) == 0:
            return False

        meter.add_frames_float32(interleaved)
        return True

    def read_loudness_snapshot(self, meter) -> AnalyzerLoudnessSnapshot:
        return AnalyzerLoudnessSnapshot(
            momentary_lufs=meter.momentary_lufs(),
            shortterm_lufs=meter.shortterm_lufs(),
            integrated_lufs=meter.integrated_lufs(),
        )

    def close_loudness_meter(self, meter) -> None:
        if meter is None:
            return

        try:
            meter.close()
        except Exception:
            pass

    def process_audio_block(self, _stream, block) -> None:
        if self.stop_event.is_set():
            return

        audio_format = block.get_format()
        sample_format = audio_format.get_sample_format()
        if sample_format != "F32":
            return

        self.sample_rate = float(audio_format.get_rate() or self.sample_rate or SAMPLE_RATE)
        data = block.get_data().get_data()
        self.audio_blocks.append(interleaved_f32le_bytes_to_channel_payloads(data, audio_format.get_channels()))

    def read_audio_levels(self) -> None:
        pending_samples = array("f")
        fft_samples = array("f")
        fft_size = analyzer_fft_size(self.sample_rate)
        smoothed_powers: tuple[float, ...] = ()
        loudness_meter = None
        loudness_stopped = False
        last_loudness_emit_time = 0.0

        try:
            while not self.stop_event.is_set():
                try:
                    left_payload, right_payload = self.audio_blocks.popleft()
                except IndexError:
                    self.stop_event.wait(ANALYZER_QUEUE_WAIT_SECONDS)
                    continue

                if self.loudness_callback is None:
                    if loudness_meter is not None:
                        self.close_loudness_meter(loudness_meter)
                        loudness_meter = None
                    loudness_stopped = False
                elif loudness_meter is None and not loudness_stopped:
                    loudness_meter = self.create_loudness_meter()
                    if loudness_meter is None:
                        self.emit_loudness_snapshot(None)
                        loudness_stopped = True

                if loudness_meter is not None:
                    try:
                        if self.feed_loudness_meter(loudness_meter, left_payload, right_payload):
                            now = time.monotonic()
                            if now - last_loudness_emit_time >= LOUDNESS_EMIT_INTERVAL_SECONDS:
                                self.emit_loudness_snapshot(self.read_loudness_snapshot(loudness_meter))
                                last_loudness_emit_time = now
                    except Exception as exc:
                        self.status_callback(f"Loudness stopped: {exc}")
                        self.emit_loudness_snapshot(None)
                        self.close_loudness_meter(loudness_meter)
                        loudness_meter = None
                        loudness_stopped = True

                pending_samples.extend(stereo_f32le_bytes_to_mono_samples(left_payload, right_payload))
                frame_count = analyzer_frame_count(self.sample_rate)

                while len(pending_samples) >= frame_count:
                    samples = pending_samples[:frame_count]
                    del pending_samples[:frame_count]

                    fft_samples.extend(samples)
                    if len(fft_samples) > fft_size:
                        del fft_samples[: len(fft_samples) - fft_size]

                    band_powers = samples_to_log_band_powers(
                        fft_samples,
                        sample_rate=self.sample_rate,
                        fft_size=fft_size,
                    )
                    alpha = analyzer_smoothing_alpha(self.response_speed, len(samples), self.sample_rate)
                    smoothed_powers = smooth_power_values(smoothed_powers, band_powers, alpha)
                    levels = spectrum_db_values_to_levels(power_values_to_db_values(smoothed_powers))
                    callback = self.levels_callback
                    if callback is not None and levels:
                        callback(levels)
        finally:
            self.close_loudness_meter(loudness_meter)
            if self.reader_thread is threading.current_thread():
                self.reader_thread = None

    @staticmethod
    def _import_pipewire_gobject():
        shim_error: Exception | None = None
        try:
            import pipewire_gobject  # noqa: F401
        except Exception as exc:  # pragma: no cover - depends on installed packaging layout
            shim_error = exc

        try:
            import gi

            gi.require_version("Pwg", "0.1")
            from gi.repository import GLib, Pwg
        except Exception as exc:
            if shim_error is not None:
                raise RuntimeError(
                    f"pipewire-gobject is not available: Python shim failed with {shim_error}; "
                    f"Pwg GI import failed with {exc}"
                ) from exc
            raise

        return GLib, Pwg
