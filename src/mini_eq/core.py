from __future__ import annotations

import cmath
import json
import math
import os
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np

APP_NAME = "Mini EQ"
OUTPUT_CLIENT_NAME = "Mini EQ Output"
VIRTUAL_SINK_BASE = "mini_eq_sink"
VIRTUAL_SINK_DESCRIPTION = "Mini-EQ-Sink"
FILTER_OUTPUT_SUFFIX = "_output"
MAX_BANDS = 32
DEFAULT_ACTIVE_BANDS = 10
PRESET_VERSION = 1
PRESET_FILE_SUFFIX = ".json"
EQ_MODE_APO = 6
SAMPLE_RATE = 48000.0
GRAPH_FREQ_MIN = 20.0
GRAPH_FREQ_MAX = 20000.0
GRAPH_DB_MIN = -24.0
GRAPH_DB_MAX = 24.0
RESPONSE_PEAK_F_STEP = 1.02
EQ_FREQUENCY_MIN_HZ = 20.0
EQ_FREQUENCY_MAX_HZ = 20000.0
EQ_GAIN_MIN_DB = -20.0
EQ_GAIN_MAX_DB = 20.0
EQ_Q_MIN = 0.18248
EQ_Q_MAX = 6.0
EQ_PREAMP_MIN_DB = -24.0
EQ_PREAMP_MAX_DB = 6.0
PRESET_STORAGE_DIR: Path | None = None

EQ_MODES = {
    "Live PipeWire": 0,
}

FILTER_TYPES = {
    "Off": 0,
    "Bell": 1,
    "Hi-pass": 2,
    "Hi-shelf": 3,
    "Lo-pass": 4,
    "Lo-shelf": 5,
    "Notch": 6,
    "Resonance": 7,
    "Allpass": 8,
    "Bandpass": 9,
    "Ladder-pass": 10,
    "Ladder-rej": 11,
}

SELECTABLE_FILTER_TYPES = {
    name: FILTER_TYPES[name]
    for name in (
        "Off",
        "Bell",
        "Hi-pass",
        "Hi-shelf",
        "Lo-pass",
        "Lo-shelf",
        "Notch",
        "Allpass",
        "Bandpass",
    )
}
SUPPORTED_APO_FILTER_TYPE_VALUES = set(SELECTABLE_FILTER_TYPES.values())

APO_FILTER_TYPE_MAP = {
    "PK": "Bell",
    "MODAL": "Bell",
    "PEQ": "Bell",
    "LP": "Lo-pass",
    "LPQ": "Lo-pass",
    "HP": "Hi-pass",
    "HPQ": "Hi-pass",
    "LS": "Lo-shelf",
    "LSC": "Lo-shelf",
    "LS 6DB": "Lo-shelf",
    "LS 12DB": "Lo-shelf",
    "HS": "Hi-shelf",
    "HSC": "Hi-shelf",
    "HS 6DB": "Hi-shelf",
    "HS 12DB": "Hi-shelf",
    "NO": "Notch",
    "AP": "Allpass",
}

FILTER_TYPE_ORDER = list(SELECTABLE_FILTER_TYPES.keys())
MODE_ORDER = list(EQ_MODES.keys())
DEFAULT_BAND_Q = 1.0 / math.sqrt(2.0)
FILTER_TYPE_INDEX_BY_VALUE = {value: index for index, value in enumerate(SELECTABLE_FILTER_TYPES.values())}
MODE_INDEX_BY_VALUE = {value: index for index, value in enumerate(EQ_MODES.values())}

RE_COMMENT = re.compile(r"^[ \t]*#")
RE_PREAMP = re.compile(r"preamp\s*:\s*([+-]?\d+(?:\.\d+)?)\s*db", re.IGNORECASE)
RE_FILTER = re.compile(r"filter\s*\d*\s*:\s*on\s+([a-z]+(?:\s+(?:6|12)db)?)", re.IGNORECASE)
RE_FREQ = re.compile(r"fc\s+(\d+(?:,\d+)?(?:\.\d+)?)\s*hz", re.IGNORECASE)
RE_GAIN = re.compile(r"gain\s+([+-]?\d+(?:\.\d+)?)\s*db", re.IGNORECASE)
RE_QUALITY = re.compile(r"q\s+(\d+(?:\.\d+)?)", re.IGNORECASE)
RE_INVALID_PRESET_NAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')


class AudioBackendError(RuntimeError):
    pass


@dataclass
class EqBand:
    filter_type: int
    frequency: float
    gain_db: float = 0.0
    q: float = DEFAULT_BAND_Q
    mode: int = EQ_MODE_APO
    slope: int = 0
    mute: bool = False
    solo: bool = False


@dataclass
class ApoBand:
    filter_type: str
    frequency: float = 1000.0
    gain_db: float = 0.0
    q: float = 1.0 / math.sqrt(2.0)


@dataclass(frozen=True)
class BiquadCoefficients:
    b0: float
    b1: float
    b2: float
    a0: float
    a1: float
    a2: float

    def scaled_for_control_range(self, limit: float = 10.0) -> BiquadCoefficients:
        max_abs = max(abs(value) for value in self.as_tuple())
        if max_abs <= limit:
            return self

        scale = limit / max_abs
        return BiquadCoefficients(
            b0=self.b0 * scale,
            b1=self.b1 * scale,
            b2=self.b2 * scale,
            a0=self.a0 * scale,
            a1=self.a1 * scale,
            a2=self.a2 * scale,
        )

    def as_tuple(self) -> tuple[float, float, float, float, float, float]:
        return (self.b0, self.b1, self.b2, self.a0, self.a1, self.a2)

    def as_dict(self) -> dict[str, float]:
        return {
            "b0": self.b0,
            "b1": self.b1,
            "b2": self.b2,
            "a0": self.a0,
            "a1": self.a1,
            "a2": self.a2,
        }


IDENTITY_BIQUAD_COEFFICIENTS = BiquadCoefficients(1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def eq_band_to_dict(band: EqBand) -> dict[str, object]:
    return {
        "filter_type": int(band.filter_type),
        "frequency": float(band.frequency),
        "gain_db": float(band.gain_db),
        "q": float(band.q),
        "mute": bool(band.mute),
        "solo": bool(band.solo),
    }


def eq_band_from_dict(data: dict[str, object], fallback: EqBand) -> EqBand:
    filter_type = int(clamp(float(data.get("filter_type", fallback.filter_type)), 0.0, 11.0))
    if filter_type not in SUPPORTED_APO_FILTER_TYPE_VALUES:
        filter_type = FILTER_TYPES["Off"]

    return EqBand(
        filter_type=filter_type,
        frequency=clamp(float(data.get("frequency", fallback.frequency)), EQ_FREQUENCY_MIN_HZ, EQ_FREQUENCY_MAX_HZ),
        gain_db=clamp(float(data.get("gain_db", fallback.gain_db)), EQ_GAIN_MIN_DB, EQ_GAIN_MAX_DB),
        q=clamp(float(data.get("q", fallback.q)), EQ_Q_MIN, EQ_Q_MAX),
        mode=fallback.mode,
        slope=fallback.slope,
        mute=bool(data.get("mute", fallback.mute)),
        solo=bool(data.get("solo", fallback.solo)),
    )


def inactive_eq_bands() -> list[EqBand]:
    bands: list[EqBand] = []

    for frequency, q_value in compute_log_spaced_band_defaults(MAX_BANDS):
        bands.append(
            EqBand(
                filter_type=FILTER_TYPES["Off"],
                frequency=frequency,
                gain_db=0.0,
                q=q_value,
                mode=EQ_MODE_APO,
                slope=0,
            )
        )

    return bands


def default_eq_bands() -> list[EqBand]:
    bands = inactive_eq_bands()

    for index, (frequency, q_value) in enumerate(compute_log_spaced_band_defaults(DEFAULT_ACTIVE_BANDS)):
        bands[index].filter_type = FILTER_TYPES["Bell"]
        bands[index].frequency = frequency
        bands[index].q = q_value
        bands[index].mode = EQ_MODE_APO

    return bands


def profile_band_count(bands: list[EqBand]) -> int:
    last_active_index = -1

    for index, band in enumerate(bands[:MAX_BANDS]):
        if band.filter_type != FILTER_TYPES["Off"]:
            last_active_index = index

    return last_active_index + 1


def fader_band_count_for_profile(bands: list[EqBand]) -> int:
    return max(1, min(profile_band_count(bands), MAX_BANDS))


def bands_have_solo(bands: list[EqBand]) -> bool:
    return any(band.solo for band in bands)


def band_is_effective(band: EqBand, solo_active: bool = False) -> bool:
    return band.filter_type != FILTER_TYPES["Off"] and not band.mute and (not solo_active or band.solo)


def ensure_preset_storage_dir() -> Path:
    storage_dir = preset_storage_dir()
    storage_dir.mkdir(parents=True, exist_ok=True)
    return storage_dir


def user_config_dir() -> Path:
    xdg_config_home = os.environ.get("XDG_CONFIG_HOME")
    if xdg_config_home:
        return Path(xdg_config_home)

    return Path.home() / ".config"


def app_config_dir() -> Path:
    return user_config_dir() / "mini-eq"


def default_preset_storage_dir() -> Path:
    return app_config_dir() / "output"


def preset_storage_dir() -> Path:
    return PRESET_STORAGE_DIR or default_preset_storage_dir()


def sanitize_preset_name(name: str) -> str:
    cleaned = RE_INVALID_PRESET_NAME.sub(" ", name).strip()
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    return cleaned[:100]


def ensure_json_suffix(path: Path) -> Path:
    if path.suffix.lower() == PRESET_FILE_SUFFIX:
        return path

    return path.with_suffix(PRESET_FILE_SUFFIX)


def preset_path_for_name(name: str) -> Path:
    preset_name = sanitize_preset_name(name)
    if not preset_name:
        raise ValueError("preset name is empty")

    return ensure_preset_storage_dir() / f"{preset_name}{PRESET_FILE_SUFFIX}"


def delete_preset_file(name: str) -> None:
    preset_name = sanitize_preset_name(name)
    if not preset_name:
        raise ValueError("preset name is empty")

    storage_dir = ensure_preset_storage_dir()
    dir_fd = os.open(storage_dir, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        try:
            os.unlink(f"{preset_name}{PRESET_FILE_SUFFIX}", dir_fd=dir_fd)
        except FileNotFoundError:
            return
    finally:
        os.close(dir_fd)


def list_preset_names() -> list[str]:
    names = [
        path.stem
        for path in ensure_preset_storage_dir().iterdir()
        if path.is_file() and path.suffix.lower() == PRESET_FILE_SUFFIX
    ]
    return sorted(dict.fromkeys(names), key=str.casefold)


def load_mini_eq_preset_file(path: str | Path) -> dict[str, object]:
    file_path = Path(path)
    if not file_path.is_file():
        raise ValueError("preset file not found")

    try:
        payload = json.loads(file_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid preset JSON: {exc.msg}") from exc

    if not isinstance(payload, dict):
        raise ValueError("preset file must contain a JSON object")

    version = int(payload.get("version", 0))
    if version > PRESET_VERSION:
        raise ValueError(f"preset version {version} is newer than this Mini EQ build")

    bands = payload.get("bands")
    if not isinstance(bands, list):
        raise ValueError("preset file does not contain a valid bands list")

    return payload


def write_mini_eq_preset_file(path: str | Path, payload: dict[str, object]) -> None:
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def db_to_linear(value_db: float) -> float:
    return math.pow(10.0, value_db / 20.0)


def format_frequency(value: float) -> str:
    if value >= 1000.0:
        return f"{value / 1000.0:.1f}k"

    return f"{int(round(value))}"


def parse_number(match: re.Match[str] | None) -> float | None:
    if match is None:
        return None

    return float(match.group(1).replace(",", ""))


def parse_apo_preamp(line: str) -> float | None:
    return parse_number(RE_PREAMP.search(line))


def parse_apo_filter(line: str, band: ApoBand) -> str:
    match = RE_FILTER.search(line)

    if match is None:
        return ""

    filter_name = " ".join(match.group(1).split()).upper()
    band.filter_type = APO_FILTER_TYPE_MAP.get(filter_name, "Off")
    return filter_name


def parse_apo_frequency(line: str, band: ApoBand) -> bool:
    value = parse_number(RE_FREQ.search(line))

    if value is None:
        return False

    band.frequency = value
    return True


def parse_apo_gain(line: str, band: ApoBand) -> bool:
    value = parse_number(RE_GAIN.search(line))

    if value is None:
        return False

    band.gain_db = value
    return True


def parse_apo_quality(line: str, band: ApoBand) -> bool:
    value = parse_number(RE_QUALITY.search(line))

    if value is None:
        return False

    band.q = value
    return True


def parse_apo_config_line(line: str) -> ApoBand | None:
    band = ApoBand(filter_type="Off")
    filter_name = parse_apo_filter(line, band)

    if not filter_name:
        return None

    parse_apo_frequency(line, band)

    if filter_name in {"PK", "MODAL", "PEQ"}:
        parse_apo_gain(line, band)
        parse_apo_quality(line, band)
    elif filter_name in {"LP", "LPQ", "HP", "HPQ"}:
        parse_apo_quality(line, band)
    elif filter_name in {"LS", "LSC", "HS", "HSC"}:
        parse_apo_gain(line, band)

        if not parse_apo_quality(line, band):
            band.q = 2.0 / 3.0
    elif filter_name == "LS 6DB":
        band.frequency = band.frequency * 2.0 / 3.0
        band.q = math.sqrt(2.0) / 3.0
        parse_apo_gain(line, band)
    elif filter_name == "LS 12DB":
        band.frequency = band.frequency * 3.0 / 2.0
        parse_apo_gain(line, band)
    elif filter_name == "HS 6DB":
        band.frequency = band.frequency * math.sqrt(2.0)
        band.q = math.sqrt(2.0) / 3.0
        parse_apo_gain(line, band)
    elif filter_name == "HS 12DB":
        band.frequency = band.frequency / math.sqrt(2.0)
        parse_apo_gain(line, band)
    elif filter_name == "NO":
        if not parse_apo_quality(line, band):
            band.q = 100.0 / 3.0
    elif filter_name == "AP":
        parse_apo_quality(line, band)

    return band


def parse_apo_file(path: str) -> tuple[float, list[EqBand]]:
    file_path = Path(path)

    if not file_path.is_file():
        raise ValueError("APO preset file not found")

    preamp = 0.0
    apo_bands: list[ApoBand] = []

    for line in file_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if RE_COMMENT.search(line):
            continue

        parsed_band = parse_apo_config_line(line)

        if parsed_band is not None:
            apo_bands.append(parsed_band)
            continue

        parsed_preamp = parse_apo_preamp(line)

        if parsed_preamp is not None:
            preamp = clamp(parsed_preamp, EQ_PREAMP_MIN_DB, EQ_PREAMP_MAX_DB)

    if not apo_bands:
        raise ValueError("APO preset did not contain any supported filter")

    apo_bands.sort(key=lambda band: band.frequency)

    eq_bands: list[EqBand] = []

    for band in apo_bands[:MAX_BANDS]:
        eq_bands.append(
            EqBand(
                filter_type=FILTER_TYPES.get(band.filter_type, FILTER_TYPES["Off"]),
                frequency=clamp(band.frequency, EQ_FREQUENCY_MIN_HZ, EQ_FREQUENCY_MAX_HZ),
                gain_db=clamp(band.gain_db, EQ_GAIN_MIN_DB, EQ_GAIN_MAX_DB),
                q=clamp(band.q, EQ_Q_MIN, EQ_Q_MAX),
                mode=EQ_MODE_APO,
                slope=0,
            )
        )

    return preamp, eq_bands


def compute_log_spaced_band_defaults(num_bands: int) -> list[tuple[float, float]]:
    freq_min = GRAPH_FREQ_MIN
    freq_max = GRAPH_FREQ_MAX
    freq0 = freq_min
    step = math.pow(freq_max / freq_min, 1.0 / float(num_bands))
    defaults: list[tuple[float, float]] = []

    for _ in range(num_bands):
        freq1 = freq0 * step
        freq = freq0 + 0.5 * (freq1 - freq0)
        width = freq1 - freq0
        q_value = freq / width
        defaults.append((freq, q_value))
        freq0 = freq1

    return defaults


def identity_biquad_coefficients(gain: float = 1.0) -> BiquadCoefficients:
    if gain == 1.0:
        return IDENTITY_BIQUAD_COEFFICIENTS
    return BiquadCoefficients(float(gain), 0.0, 0.0, 1.0, 0.0, 0.0)


def band_biquad_coefficients(band: EqBand, sample_rate: float, solo_active: bool = False) -> BiquadCoefficients:
    if not band_is_effective(band, solo_active):
        return identity_biquad_coefficients()

    filter_type = band.filter_type
    if band.mode == EQ_MODE_APO and filter_type not in SUPPORTED_APO_FILTER_TYPE_VALUES:
        return identity_biquad_coefficients()

    center = clamp(band.frequency, EQ_FREQUENCY_MIN_HZ, min(EQ_FREQUENCY_MAX_HZ, (sample_rate * 0.5) - 1.0))
    q_value = max(band.q, 0.0001)
    w0 = 2.0 * math.pi * center / sample_rate
    cos_w0 = math.cos(w0)
    sin_w0 = math.sin(w0)
    alpha = sin_w0 / (2.0 * q_value)
    gain_a = math.pow(10.0, band.gain_db / 40.0)

    if filter_type == FILTER_TYPES["Bell"]:
        b0 = 1.0 + alpha * gain_a
        b1 = -2.0 * cos_w0
        b2 = 1.0 - alpha * gain_a
        a0 = 1.0 + alpha / gain_a
        a1 = -2.0 * cos_w0
        a2 = 1.0 - alpha / gain_a
    elif filter_type == FILTER_TYPES["Lo-pass"]:
        b0 = (1.0 - cos_w0) * 0.5
        b1 = 1.0 - cos_w0
        b2 = (1.0 - cos_w0) * 0.5
        a0 = 1.0 + alpha
        a1 = -2.0 * cos_w0
        a2 = 1.0 - alpha
    elif filter_type == FILTER_TYPES["Hi-pass"]:
        b0 = (1.0 + cos_w0) * 0.5
        b1 = -(1.0 + cos_w0)
        b2 = (1.0 + cos_w0) * 0.5
        a0 = 1.0 + alpha
        a1 = -2.0 * cos_w0
        a2 = 1.0 - alpha
    elif filter_type == FILTER_TYPES["Notch"]:
        b0 = 1.0
        b1 = -2.0 * cos_w0
        b2 = 1.0
        a0 = 1.0 + alpha
        a1 = -2.0 * cos_w0
        a2 = 1.0 - alpha
    elif filter_type == FILTER_TYPES["Allpass"]:
        b0 = 1.0 - alpha
        b1 = -2.0 * cos_w0
        b2 = 1.0 + alpha
        a0 = 1.0 + alpha
        a1 = -2.0 * cos_w0
        a2 = 1.0 - alpha
    elif filter_type == FILTER_TYPES["Bandpass"]:
        b0 = alpha
        b1 = 0.0
        b2 = -alpha
        a0 = 1.0 + alpha
        a1 = -2.0 * cos_w0
        a2 = 1.0 - alpha
    elif filter_type == FILTER_TYPES["Lo-shelf"]:
        beta = 2.0 * math.sqrt(gain_a) * alpha
        b0 = gain_a * ((gain_a + 1.0) - ((gain_a - 1.0) * cos_w0) + beta)
        b1 = 2.0 * gain_a * ((gain_a - 1.0) - ((gain_a + 1.0) * cos_w0))
        b2 = gain_a * ((gain_a + 1.0) - ((gain_a - 1.0) * cos_w0) - beta)
        a0 = (gain_a + 1.0) + ((gain_a - 1.0) * cos_w0) + beta
        a1 = -2.0 * ((gain_a - 1.0) + ((gain_a + 1.0) * cos_w0))
        a2 = (gain_a + 1.0) + ((gain_a - 1.0) * cos_w0) - beta
    elif filter_type == FILTER_TYPES["Hi-shelf"]:
        beta = 2.0 * math.sqrt(gain_a) * alpha
        b0 = gain_a * ((gain_a + 1.0) + ((gain_a - 1.0) * cos_w0) + beta)
        b1 = -2.0 * gain_a * ((gain_a - 1.0) + ((gain_a + 1.0) * cos_w0))
        b2 = gain_a * ((gain_a + 1.0) + ((gain_a - 1.0) * cos_w0) - beta)
        a0 = (gain_a + 1.0) - ((gain_a - 1.0) * cos_w0) + beta
        a1 = 2.0 * ((gain_a - 1.0) - ((gain_a + 1.0) * cos_w0))
        a2 = (gain_a + 1.0) - ((gain_a - 1.0) * cos_w0) - beta
    else:
        return identity_biquad_coefficients()

    return BiquadCoefficients(b0, b1, b2, a0, a1, a2)


def biquad_response_at_frequency(
    coefficients: BiquadCoefficients,
    sample_rate: float,
    frequency: float,
) -> complex:
    frequency = clamp(frequency, 1.0, (sample_rate * 0.5) - 1.0)
    omega = 2.0 * math.pi * frequency / sample_rate

    z1 = cmath.exp(-1j * omega)
    z2 = z1 * z1
    numerator = coefficients.b0 + (coefficients.b1 * z1) + (coefficients.b2 * z2)
    denominator = coefficients.a0 + (coefficients.a1 * z1) + (coefficients.a2 * z2)

    if abs(denominator) < 1e-12:
        return 1.0 + 0.0j

    return numerator / denominator


def total_response_db(bands: list[EqBand], preamp_db: float, sample_rate: float, frequency: float) -> float:
    response = 1.0 + 0.0j
    solo_active = bands_have_solo(bands)

    for band in bands:
        coefficients = band_biquad_coefficients(band, sample_rate, solo_active)
        response *= biquad_response_at_frequency(coefficients, sample_rate, frequency)

    magnitude = max(abs(response), 1e-12)
    return clamp(preamp_db + (20.0 * math.log10(magnitude)), GRAPH_DB_MIN - 12.0, GRAPH_DB_MAX + 12.0)


@lru_cache(maxsize=32)
def log_response_frequencies(sample_rate: float = SAMPLE_RATE, f_step: float = RESPONSE_PEAK_F_STEP) -> np.ndarray:
    max_frequency = min(GRAPH_FREQ_MAX, (float(sample_rate) * 0.5) - 1.0)
    if max_frequency <= GRAPH_FREQ_MIN:
        return np.array([max(1.0, max_frequency)], dtype=np.float64)

    f_step = max(float(f_step), 1.0001)
    frequencies: list[float] = []
    frequency = GRAPH_FREQ_MIN
    while frequency <= max_frequency:
        frequencies.append(frequency)
        frequency *= f_step

    if frequencies[-1] < max_frequency:
        frequencies.append(max_frequency)

    return np.array(frequencies, dtype=np.float64)


@lru_cache(maxsize=32)
def stepped_response_frequencies(sample_rate: float = SAMPLE_RATE, steps: int = 192) -> np.ndarray:
    max_frequency = min(GRAPH_FREQ_MAX, (float(sample_rate) * 0.5) - 1.0)
    if max_frequency <= GRAPH_FREQ_MIN:
        return np.array([max(1.0, max_frequency)], dtype=np.float64)

    return np.geomspace(GRAPH_FREQ_MIN, max_frequency, max(2, int(steps)), dtype=np.float64)


def response_peak_frequencies(
    bands: list[EqBand],
    sample_rate: float = SAMPLE_RATE,
    *,
    steps: int | None = None,
    f_step: float = RESPONSE_PEAK_F_STEP,
) -> np.ndarray:
    frequencies = (
        stepped_response_frequencies(float(sample_rate), max(2, int(steps)))
        if steps is not None
        else log_response_frequencies(float(sample_rate), float(f_step))
    )

    solo_active = bands_have_solo(bands)
    max_frequency = min(GRAPH_FREQ_MAX, (float(sample_rate) * 0.5) - 1.0)
    center_frequencies = [
        clamp(band.frequency, GRAPH_FREQ_MIN, max_frequency) for band in bands if band_is_effective(band, solo_active)
    ]
    if not center_frequencies:
        return frequencies

    return np.unique(np.concatenate([frequencies, np.array(center_frequencies, dtype=np.float64)]))


def total_response_db_at_frequencies(
    bands: list[EqBand],
    preamp_db: float,
    sample_rate: float,
    frequencies: np.ndarray,
    *,
    clamp_output: bool = True,
) -> np.ndarray:
    frequency_values = np.atleast_1d(np.asarray(frequencies, dtype=np.float64))
    if frequency_values.size == 0:
        return np.array([], dtype=np.float64)

    frequency_values = np.clip(frequency_values, 1.0, (float(sample_rate) * 0.5) - 1.0)
    omega = 2.0 * np.pi * frequency_values / float(sample_rate)
    z1 = np.exp(-1j * omega)
    z2 = z1 * z1
    response = np.ones(frequency_values.shape, dtype=np.complex128)
    solo_active = bands_have_solo(bands)

    for band in bands:
        coefficients = band_biquad_coefficients(band, sample_rate, solo_active)
        if coefficients == IDENTITY_BIQUAD_COEFFICIENTS:
            continue

        numerator = coefficients.b0 + (coefficients.b1 * z1) + (coefficients.b2 * z2)
        denominator = coefficients.a0 + (coefficients.a1 * z1) + (coefficients.a2 * z2)
        valid = np.abs(denominator) >= 1e-12
        band_response = np.ones(frequency_values.shape, dtype=np.complex128)
        band_response[valid] = numerator[valid] / denominator[valid]
        response *= band_response

    db_values = float(preamp_db) + (20.0 * np.log10(np.maximum(np.abs(response), 1e-12)))
    if clamp_output:
        return np.clip(db_values, GRAPH_DB_MIN - 12.0, GRAPH_DB_MAX + 12.0)
    return db_values


def estimate_response_peak_db(
    bands: list[EqBand],
    preamp_db: float,
    sample_rate: float = SAMPLE_RATE,
    *,
    steps: int | None = None,
    f_step: float = RESPONSE_PEAK_F_STEP,
) -> float:
    frequencies = response_peak_frequencies(bands, sample_rate, steps=steps, f_step=f_step)
    response = total_response_db_at_frequencies(bands, preamp_db, sample_rate, frequencies, clamp_output=False)
    if response.size == 0:
        return float(preamp_db)
    return float(np.max(response))
