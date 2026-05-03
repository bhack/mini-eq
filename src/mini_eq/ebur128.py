from __future__ import annotations

import ctypes
import ctypes.util
from dataclasses import dataclass
from typing import Self

import numpy as np

EBUR128_MODE_M = 1 << 0
EBUR128_MODE_S = (1 << 1) | EBUR128_MODE_M
EBUR128_MODE_I = (1 << 2) | EBUR128_MODE_M

EBUR128_UNUSED = 0
EBUR128_LEFT = 1
EBUR128_RIGHT = 2
EBUR128_CENTER = 3
EBUR128_LEFT_SURROUND = 4
EBUR128_RIGHT_SURROUND = 5

EBUR128_SUCCESS = 0
MAX_EBUR128_CHANNELS = 5


class Ebur128UnavailableError(RuntimeError):
    """Raised when the native libebur128 shared library cannot be loaded."""


class Ebur128Error(RuntimeError):
    """Raised when libebur128 rejects a meter operation."""


@dataclass(frozen=True)
class Ebur128Version:
    major: int
    minor: int
    patch: int

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"


_LIBRARY: ctypes.CDLL | None = None


def _load_library() -> ctypes.CDLL:
    global _LIBRARY

    if _LIBRARY is not None:
        return _LIBRARY

    candidates = [ctypes.util.find_library("ebur128"), "libebur128.so.1", "libebur128.so"]
    errors: list[str] = []
    for candidate in candidates:
        if not candidate:
            continue
        try:
            library = ctypes.CDLL(candidate)
        except OSError as exc:
            errors.append(f"{candidate}: {exc}")
            continue

        _configure_library(library)
        _LIBRARY = library
        return library

    detail = "; ".join(errors) if errors else "library lookup returned no candidates"
    raise Ebur128UnavailableError(f"libebur128 is not available: {detail}")


def _configure_library(library: ctypes.CDLL) -> None:
    state = ctypes.c_void_p
    state_pointer = ctypes.POINTER(state)

    library.ebur128_get_version.argtypes = [
        ctypes.POINTER(ctypes.c_int),
        ctypes.POINTER(ctypes.c_int),
        ctypes.POINTER(ctypes.c_int),
    ]
    library.ebur128_get_version.restype = None

    library.ebur128_init.argtypes = [ctypes.c_uint, ctypes.c_ulong, ctypes.c_int]
    library.ebur128_init.restype = state

    library.ebur128_destroy.argtypes = [state_pointer]
    library.ebur128_destroy.restype = None

    library.ebur128_set_channel.argtypes = [state, ctypes.c_uint, ctypes.c_int]
    library.ebur128_set_channel.restype = ctypes.c_int

    library.ebur128_add_frames_float.argtypes = [state, ctypes.POINTER(ctypes.c_float), ctypes.c_size_t]
    library.ebur128_add_frames_float.restype = ctypes.c_int

    library.ebur128_loudness_global.argtypes = [state, ctypes.POINTER(ctypes.c_double)]
    library.ebur128_loudness_global.restype = ctypes.c_int

    library.ebur128_loudness_momentary.argtypes = [state, ctypes.POINTER(ctypes.c_double)]
    library.ebur128_loudness_momentary.restype = ctypes.c_int

    library.ebur128_loudness_shortterm.argtypes = [state, ctypes.POINTER(ctypes.c_double)]
    library.ebur128_loudness_shortterm.restype = ctypes.c_int


def is_available() -> bool:
    try:
        _load_library()
    except Ebur128UnavailableError:
        return False
    return True


def version() -> Ebur128Version:
    library = _load_library()
    major = ctypes.c_int()
    minor = ctypes.c_int()
    patch = ctypes.c_int()
    library.ebur128_get_version(ctypes.byref(major), ctypes.byref(minor), ctypes.byref(patch))
    return Ebur128Version(major.value, minor.value, patch.value)


def _check_result(result: int, operation: str) -> None:
    if result != EBUR128_SUCCESS:
        raise Ebur128Error(f"{operation} failed with libebur128 error {result}")


def _default_channel_map(channels: int) -> tuple[int, ...]:
    match channels:
        case 1:
            return (EBUR128_LEFT,)
        case 2:
            return (EBUR128_LEFT, EBUR128_RIGHT)
        case 3:
            return (EBUR128_LEFT, EBUR128_RIGHT, EBUR128_CENTER)
        case 4:
            return (EBUR128_LEFT, EBUR128_RIGHT, EBUR128_LEFT_SURROUND, EBUR128_RIGHT_SURROUND)
        case 5:
            return (
                EBUR128_LEFT,
                EBUR128_RIGHT,
                EBUR128_CENTER,
                EBUR128_LEFT_SURROUND,
                EBUR128_RIGHT_SURROUND,
            )
        case _:
            raise ValueError("libebur128 meter supports one to five channels")


class Ebur128Meter:
    def __init__(
        self,
        *,
        sample_rate: int,
        channels: int,
        channel_map: tuple[int, ...] | None = None,
        mode: int = EBUR128_MODE_I | EBUR128_MODE_S,
    ) -> None:
        if sample_rate <= 0:
            raise ValueError("sample rate must be positive")
        if not 1 <= channels <= MAX_EBUR128_CHANNELS:
            raise ValueError("libebur128 meter supports one to five channels")

        self.sample_rate = sample_rate
        self.channels = channels
        self.channel_map = channel_map or _default_channel_map(channels)
        if len(self.channel_map) != channels:
            raise ValueError("channel map length must match channel count")

        self._library: ctypes.CDLL | None = None
        self._state = ctypes.c_void_p()
        self._library = _load_library()
        self._mode = mode
        self._state = ctypes.c_void_p(self._library.ebur128_init(channels, sample_rate, mode))
        if not self._state:
            raise Ebur128Error("ebur128_init failed")

        for index, channel in enumerate(self.channel_map):
            _check_result(self._library.ebur128_set_channel(self._state, index, channel), "ebur128_set_channel")

    def close(self) -> None:
        if self._library is None or not self._state:
            return

        state = ctypes.c_void_p(self._state.value)
        self._library.ebur128_destroy(ctypes.byref(state))
        self._state = ctypes.c_void_p()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def __del__(self) -> None:
        self.close()

    def reset(self) -> None:
        if self._library is None:
            raise Ebur128Error("meter is closed")

        self.close()
        self._state = ctypes.c_void_p(self._library.ebur128_init(self.channels, self.sample_rate, self._mode))
        if not self._state:
            raise Ebur128Error("ebur128_init failed")
        for index, channel in enumerate(self.channel_map):
            _check_result(self._library.ebur128_set_channel(self._state, index, channel), "ebur128_set_channel")

    def add_frames_float32(self, audio: np.ndarray) -> int:
        if self._library is None or not self._state:
            raise Ebur128Error("meter is closed")

        samples = _as_interleaved_float32(audio, self.channels)
        frames = samples.size // self.channels
        if frames == 0:
            return 0

        pointer = samples.ctypes.data_as(ctypes.POINTER(ctypes.c_float))
        _check_result(self._library.ebur128_add_frames_float(self._state, pointer, frames), "ebur128_add_frames_float")
        return frames

    def integrated_lufs(self) -> float:
        return self._read_loudness(self._library.ebur128_loudness_global, "ebur128_loudness_global")

    def momentary_lufs(self) -> float:
        return self._read_loudness(self._library.ebur128_loudness_momentary, "ebur128_loudness_momentary")

    def shortterm_lufs(self) -> float:
        return self._read_loudness(self._library.ebur128_loudness_shortterm, "ebur128_loudness_shortterm")

    def _read_loudness(self, function: object, operation: str) -> float:
        if self._library is None or not self._state:
            raise Ebur128Error("meter is closed")

        value = ctypes.c_double()
        _check_result(function(self._state, ctypes.byref(value)), operation)
        return float(value.value)


def _as_interleaved_float32(audio: np.ndarray, channels: int) -> np.ndarray:
    samples = np.asarray(audio)
    if not np.issubdtype(samples.dtype, np.floating):
        raise ValueError("audio must contain floating point samples")

    if samples.ndim == 1:
        if samples.size % channels != 0:
            raise ValueError("interleaved audio length must be divisible by channel count")
        return np.ascontiguousarray(samples, dtype=np.float32)

    if samples.ndim == 2:
        if samples.shape[1] != channels:
            raise ValueError("audio channel count must match the meter")
        return np.ascontiguousarray(samples.reshape(-1), dtype=np.float32)

    raise ValueError("audio must have shape (samples,) or (samples, channels)")
