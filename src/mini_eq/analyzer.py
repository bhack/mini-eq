from __future__ import annotations

import math
import os
import sys
import threading
from array import array
from collections import deque
from collections.abc import Callable
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
ANALYZER_FFT_MIN_SIZE = 4096
ANALYZER_FFT_MAX_SIZE = 16384
ANALYZER_SAMPLE_WIDTH_BYTES = 4
ANALYZER_QUEUE_WAIT_SECONDS = 0.005
ANALYZER_READER_JOIN_TIMEOUT_SECONDS = 0.2
ANALYZER_DISPLAY_GAIN_MIN = -12.0
ANALYZER_DISPLAY_GAIN_MAX = 32.0
ANALYZER_DISPLAY_GAIN_DEFAULT = 0.0
JACK_CLIENT_NAME = "mini-eq-analyzer"
JACK_LEFT_INPUT_PORT = "input_FL"
JACK_RIGHT_INPUT_PORT = "input_FR"
JACK_CAPTURE_QUEUE_BLOCKS = 128
JACK_PIPEWIRE_PROPS = (
    "node.autoconnect = false node.dont-move = true stream.monitor = true media.category = Monitor media.role = DSP"
)
ANALYZER_RESPONSE_MIN = 0.02
ANALYZER_RESPONSE_MAX = 15.0
ANALYZER_RESPONSE_DEFAULT = 2.0
ANALYZER_POWER_FLOOR = 10.0 ** (ANALYZER_DB_FLOOR / 10.0)
_numpy_module = None


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
def analyzer_fft_band_bin_ranges(
    fft_size: int,
    sample_rate: float,
    center_frequencies: tuple[float, ...] = ANALYZER_BAND_FREQUENCIES,
) -> tuple[tuple[int, int], ...]:
    np = require_numpy()
    size = max(2, int(fft_size))
    frequencies = np.fft.rfftfreq(size, 1.0 / max(1.0, float(sample_rate)))
    edges = analyzer_band_edges(center_frequencies)
    ranges: list[tuple[int, int]] = []

    for index, center in enumerate(center_frequencies):
        left = edges[index]
        right = edges[index + 1]
        start = int(np.searchsorted(frequencies, left, side="left"))
        stop_side = "right" if index == len(center_frequencies) - 1 else "left"
        stop = int(np.searchsorted(frequencies, right, side=stop_side))
        start = max(1, start)

        if stop <= start:
            nearest = int(np.abs(frequencies - center).argmin())
            start = max(1, nearest)
            stop = min(len(frequencies), start + 1)

        ranges.append((start, stop))

    return tuple(ranges)


@lru_cache(maxsize=64)
def analyzer_fft_band_reduce_indexes(
    fft_size: int,
    sample_rate: float,
    center_frequencies: tuple[float, ...] = ANALYZER_BAND_FREQUENCIES,
):
    np = require_numpy()
    ranges = analyzer_fft_band_bin_ranges(fft_size, sample_rate, center_frequencies)
    if not ranges:
        indexes = np.array([], dtype=np.intp)
        offsets = np.array([], dtype=np.intp)
    else:
        lengths = np.array([stop - start for start, stop in ranges], dtype=np.intp)
        offsets = np.empty(len(lengths), dtype=np.intp)
        offsets[0] = 0
        if len(lengths) > 1:
            np.cumsum(lengths[:-1], out=offsets[1:])
        indexes = np.concatenate([np.arange(start, stop, dtype=np.intp) for start, stop in ranges])

    indexes.setflags(write=False)
    offsets.setflags(write=False)
    return indexes, offsets


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

    indexes, offsets = analyzer_fft_band_reduce_indexes(size, sample_rate, center_frequencies)
    if len(indexes) == 0:
        return ()

    band_powers = np.add.reduceat(bin_powers[indexes], offsets)
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


def jack_port_name(port) -> str:
    return str(getattr(port, "name", port))


def jack_port_short_name(port) -> str:
    return str(getattr(port, "shortname", jack_port_name(port).rsplit(":", 1)[-1]))


def jack_port_client_name(port) -> str:
    return jack_port_name(port).rsplit(":", 1)[0]


def jack_sink_name_candidates(sink_name: str, sink_description: str | None = None) -> tuple[str, ...]:
    candidates: list[str] = []

    for candidate in (sink_description, sink_name):
        if candidate and candidate not in candidates:
            candidates.append(candidate)

    return tuple(candidates)


def jack_port_client_matches_sink(port, sink_candidates: set[str]) -> bool:
    client_name = jack_port_client_name(port)
    return any(client_name == candidate or client_name.startswith(f"{candidate}-") for candidate in sink_candidates)


def jack_pipewire_props(existing_props: str | None = None) -> str:
    if existing_props and not existing_props.lstrip().startswith("{"):
        return f"{existing_props} {JACK_PIPEWIRE_PROPS}"

    return JACK_PIPEWIRE_PROPS


def jack_audio_output_ports_for_sink(
    ports: list,
    sink_name: str,
    sink_description: str | None = None,
) -> list:
    candidates = set(jack_sink_name_candidates(sink_name, sink_description))
    return [port for port in ports if jack_port_client_matches_sink(port, candidates)]


def select_jack_stereo_output_ports(ports: list) -> tuple[object | None, object | None]:
    left_suffixes = ("monitor_FL", "monitor_AUX0")
    right_suffixes = ("monitor_FR", "monitor_AUX1")
    mono_suffixes = ("monitor_MONO",)

    def find_by_suffix(suffixes: tuple[str, ...]):
        for suffix in suffixes:
            for port in ports:
                if jack_port_short_name(port) == suffix or jack_port_short_name(port).endswith(f"_{suffix}"):
                    return port
        return None

    left = find_by_suffix(left_suffixes)
    right = find_by_suffix(right_suffixes)
    mono = find_by_suffix(mono_suffixes)

    if left is None and right is None and mono is not None:
        return mono, mono

    if left is None and right is not None:
        left = right
    if right is None and left is not None:
        right = left

    return left, right


def disconnect_jack_input_port_connections(client, input_ports: tuple[object | None, ...]) -> None:
    for input_port in input_ports:
        if input_port is None:
            continue

        try:
            connections = client.get_all_connections(input_port)
        except Exception:
            continue

        for source_port in connections:
            try:
                client.disconnect(source_port, input_port)
            except Exception:
                pass


class OutputSpectrumAnalyzer:
    def __init__(
        self,
        output_sink_name: str,
        levels_callback: Callable[[list[float]], None] | None,
        status_callback: Callable[[str], None],
        output_sink_description: str | None = None,
    ) -> None:
        self.output_sink_name = output_sink_name
        self.output_sink_description = output_sink_description
        self.levels_callback = levels_callback
        self.status_callback = status_callback
        self.enabled = False
        self.client = None
        self.client_active = False
        self.left_input_port = None
        self.right_input_port = None
        self.reader_thread: threading.Thread | None = None
        self.stop_event = threading.Event()
        self.stop_event.set()
        self.audio_blocks = deque(maxlen=JACK_CAPTURE_QUEUE_BLOCKS)
        self.sample_rate = SAMPLE_RATE
        self.response_speed = ANALYZER_RESPONSE_DEFAULT

    def set_levels_callback(self, callback: Callable[[list[float]], None] | None) -> None:
        self.levels_callback = callback

    def set_response_speed(self, speed: float) -> None:
        self.response_speed = clamp(float(speed), ANALYZER_RESPONSE_MIN, ANALYZER_RESPONSE_MAX)

    def set_output_sink_name(self, sink_name: str, sink_description: str | None = None) -> None:
        if sink_name == self.output_sink_name and sink_description == self.output_sink_description:
            return

        self.output_sink_name = sink_name
        self.output_sink_description = sink_description
        if not self.enabled:
            return

        if self.client is None:
            self.restart()
            return

        try:
            disconnect_jack_input_port_connections(self.client, (self.left_input_port, self.right_input_port))
            self.connect_jack_monitor_ports(self.client)
        except Exception as exc:
            self.status_callback(f"analyzer output reconnect failed: {exc}")

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
            if self.client is None:
                self.client = self.open_jack_client()
            self.activate_jack_client(self.client)
        except Exception as exc:
            self.stop_event.set()
            self.status_callback(f"Analyzer Unavailable: {exc}")
            return False

        self.reader_thread = threading.Thread(target=self.read_jack_levels, name="mini-eq-analyzer", daemon=True)
        self.reader_thread.start()
        return True

    def prepare(self) -> bool:
        if self.client is not None:
            return True

        try:
            self.client = self.open_jack_client()
        except Exception:
            return False

        return True

    def stop(self, *, close_client: bool = False) -> None:
        client = self.client
        reader_thread = self.reader_thread

        self.reader_thread = None
        self.stop_event.set()
        self.audio_blocks.clear()

        if client is not None and self.client_active and not close_client:
            self.deactivate_jack_client(client)

        if reader_thread is not None and reader_thread is not threading.current_thread():
            reader_thread.join(timeout=ANALYZER_READER_JOIN_TIMEOUT_SECONDS)

        if close_client and client is not None:
            self.close_jack_client(client)
            self.client = None
            self.left_input_port = None
            self.right_input_port = None

    def close(self) -> None:
        self.stop(close_client=True)

    def restart(self) -> bool:
        self.stop(close_client=True)
        if not self.enabled:
            return True

        return self.start()

    def open_jack_client(self):
        try:
            import jack
        except Exception as exc:
            raise RuntimeError("Python JACK client is not available") from exc

        old_pipewire_props = os.environ.get("PIPEWIRE_PROPS")
        os.environ["PIPEWIRE_PROPS"] = jack_pipewire_props(old_pipewire_props)
        try:
            client = jack.Client(JACK_CLIENT_NAME, no_start_server=True)
        finally:
            if old_pipewire_props is None:
                os.environ.pop("PIPEWIRE_PROPS", None)
            else:
                os.environ["PIPEWIRE_PROPS"] = old_pipewire_props

        self.sample_rate = float(client.samplerate or SAMPLE_RATE)
        return client

    def activate_jack_client(self, client) -> None:
        if self.client_active:
            disconnect_jack_input_port_connections(client, (self.left_input_port, self.right_input_port))
            self.connect_jack_monitor_ports(client)
            return

        if self.left_input_port is None:
            self.left_input_port = client.inports.register(JACK_LEFT_INPUT_PORT, is_terminal=True)
        if self.right_input_port is None:
            self.right_input_port = client.inports.register(JACK_RIGHT_INPUT_PORT, is_terminal=True)

        try:
            client.set_process_callback(self.process_jack_audio)
            client.activate()
            self.client_active = True
            disconnect_jack_input_port_connections(client, (self.left_input_port, self.right_input_port))
            self.connect_jack_monitor_ports(client)
        except Exception:
            self.deactivate_jack_client(client)
            raise

    def deactivate_jack_client(self, client) -> None:
        try:
            client.deactivate()
        except Exception:
            pass

        self.client_active = False

    def close_jack_client(self, client) -> None:
        if self.client_active:
            self.deactivate_jack_client(client)

        try:
            client.close()
        except Exception:
            pass

    def connect_jack_monitor_ports(self, client) -> None:
        output_ports = jack_audio_output_ports_for_sink(
            client.get_ports(is_audio=True, is_output=True),
            self.output_sink_name,
            self.output_sink_description,
        )
        left_output_port, right_output_port = select_jack_stereo_output_ports(output_ports)

        if left_output_port is None or right_output_port is None:
            sink_label = self.output_sink_description or self.output_sink_name
            raise RuntimeError(f"JACK monitor ports not found for {sink_label}")

        client.connect(jack_port_name(left_output_port), jack_port_name(self.left_input_port))
        client.connect(jack_port_name(right_output_port), jack_port_name(self.right_input_port))

    def process_jack_audio(self, _frames: int) -> None:
        if self.stop_event.is_set() or self.left_input_port is None or self.right_input_port is None:
            return

        self.audio_blocks.append(
            (
                bytes(self.left_input_port.get_buffer()),
                bytes(self.right_input_port.get_buffer()),
            )
        )

    def read_jack_levels(self) -> None:
        pending_samples = array("f")
        fft_samples = array("f")
        fft_size = analyzer_fft_size(self.sample_rate)
        smoothed_powers: tuple[float, ...] = ()

        try:
            while not self.stop_event.is_set():
                try:
                    left_payload, right_payload = self.audio_blocks.popleft()
                except IndexError:
                    self.stop_event.wait(ANALYZER_QUEUE_WAIT_SECONDS)
                    continue

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
            if self.reader_thread is threading.current_thread():
                self.reader_thread = None
