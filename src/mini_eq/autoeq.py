from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

import gi

gi.require_version("GLib", "2.0")
from gi.repository import GLib

from .core import SAMPLE_RATE

AUTOEQ_APP_ENTRIES_URL = "https://autoeq.app/entries"
AUTOEQ_APP_TARGETS_URL = "https://autoeq.app/targets"
AUTOEQ_APP_EQUALIZE_URL = "https://autoeq.app/equalize"
AUTOEQ_REQUEST_TIMEOUT_SECONDS = 20
AUTOEQ_ENTRIES_FILE = "entries.json"
AUTOEQ_TARGETS_FILE = "targets.json"
AUTOEQ_PRESET_DIR = "presets"
AUTOEQ_USER_AGENT = "Mini EQ"
AUTOEQ_PARAMETRIC_EQ_CONFIG = "8_PEAKING_WITH_SHELVES"
AUTOEQ_TARGET_COMMENT_PREFIX = "# AutoEq target: "
AUTOEQ_UNKNOWN_TARGET_LABEL = "Unknown"
RE_WHITESPACE = re.compile(r"\s+")


@dataclass(frozen=True)
class AutoEqEntry:
    name: str
    source: str
    form: str
    rig: str = ""

    @property
    def detail(self) -> str:
        parts = [part for part in (self.source, self.rig) if part]
        return " - ".join(parts)

    @property
    def cache_key(self) -> str:
        return f"autoeq.app/v1/{self.source}/{self.form}/{self.rig}/{self.name}"


@dataclass(frozen=True)
class AutoEqGeneratedPreset:
    text: str
    target_label: str


@dataclass(frozen=True)
class AutoEqDownloadedPreset:
    path: Path
    target_label: str | None = None


def user_cache_dir() -> Path:
    return Path(GLib.get_user_cache_dir())


def app_cache_dir() -> Path:
    return user_cache_dir() / "mini-eq"


def autoeq_cache_dir() -> Path:
    return app_cache_dir() / "autoeq"


def autoeq_entries_cache_path() -> Path:
    return autoeq_cache_dir() / AUTOEQ_ENTRIES_FILE


def autoeq_targets_cache_path() -> Path:
    return autoeq_cache_dir() / AUTOEQ_TARGETS_FILE


def parse_autoeq_app_entries(text: str) -> list[AutoEqEntry]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"AutoEq profile list is not valid JSON: {exc.msg}") from exc

    if not isinstance(data, dict):
        raise RuntimeError("AutoEq profile list does not have the expected shape")

    entries: list[AutoEqEntry] = []
    seen: set[tuple[str, str, str, str]] = set()
    for name, measurements in data.items():
        if not isinstance(name, str) or not isinstance(measurements, list):
            continue

        for measurement in measurements:
            if not isinstance(measurement, dict):
                continue

            source = str(measurement.get("source") or "").strip()
            form = str(measurement.get("form") or "").strip()
            rig = str(measurement.get("rig") or "").strip()
            if not source or not form:
                continue

            key = (name.casefold(), source.casefold(), form.casefold(), rig.casefold())
            if key in seen:
                continue

            seen.add(key)
            entries.append(
                AutoEqEntry(
                    name=name,
                    source=source,
                    form=form,
                    rig=rig,
                )
            )

    return entries


def fetch_text(url: str, *, timeout: int = AUTOEQ_REQUEST_TIMEOUT_SECONDS) -> str:
    request = Request(url, headers={"User-Agent": AUTOEQ_USER_AGENT})
    try:
        with urlopen(request, timeout=timeout) as response:
            return response.read().decode("utf-8", errors="replace")
    except URLError as exc:
        reason = getattr(exc, "reason", exc)
        raise RuntimeError(f"could not download AutoEq data: {reason}") from exc


def post_json(
    url: str,
    body: dict[str, object],
    *,
    timeout: int = AUTOEQ_REQUEST_TIMEOUT_SECONDS,
) -> dict[str, object]:
    request = Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "User-Agent": AUTOEQ_USER_AGENT,
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8", errors="replace"))
    except URLError as exc:
        reason = getattr(exc, "reason", exc)
        raise RuntimeError(f"could not download AutoEq data: {reason}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"AutoEq response is not valid JSON: {exc.msg}") from exc

    if not isinstance(data, dict):
        raise RuntimeError("AutoEq response does not have the expected shape")
    return data


def load_autoeq_entries_text(*, refresh: bool = False) -> str:
    path = autoeq_entries_cache_path()

    if not refresh and path.is_file():
        return path.read_text(encoding="utf-8", errors="replace")

    text = fetch_text(AUTOEQ_APP_ENTRIES_URL)
    parse_autoeq_app_entries(text)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return text


def parse_autoeq_targets_data(text: str) -> list[object]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"AutoEq target list is not valid JSON: {exc.msg}") from exc

    if not isinstance(data, list):
        raise RuntimeError("AutoEq target list does not have the expected shape")
    return data


def load_autoeq_targets_data(*, refresh: bool = False) -> list[object]:
    path = autoeq_targets_cache_path()

    if not refresh and path.is_file():
        text = path.read_text(encoding="utf-8", errors="replace")
    else:
        text = fetch_text(AUTOEQ_APP_TARGETS_URL)
        data = parse_autoeq_targets_data(text)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return data

    return parse_autoeq_targets_data(text)


def load_autoeq_entries(*, refresh: bool = False) -> list[AutoEqEntry]:
    return parse_autoeq_app_entries(load_autoeq_entries_text(refresh=refresh))


def normalize_search_query(query: str) -> list[str]:
    return [token.casefold() for token in RE_WHITESPACE.split(query.strip()) if token]


def autoeq_search_score(entry: AutoEqEntry, tokens: list[str]) -> tuple[int, int, int, str]:
    name = entry.name.casefold()
    detail = f"{entry.source} {entry.rig} {entry.form}".casefold()
    haystack = f"{name} {detail}"

    if any(token not in haystack for token in tokens):
        return (1_000_000, 1_000_000, len(entry.name), entry.name.casefold())

    first_token = tokens[0] if tokens else ""
    prefix_penalty = 0 if name.startswith(first_token) else 40
    token_distance = sum(max(haystack.find(token), 0) for token in tokens)
    source_bonus = 0 if entry.source.casefold() in {"oratory1990", "crinacle", "rtings"} else 8
    return (
        prefix_penalty + token_distance + source_bonus,
        len(entry.name),
        len(entry.cache_key),
        entry.name.casefold(),
    )


def search_autoeq_entries(entries: list[AutoEqEntry], query: str, *, limit: int = 80) -> list[AutoEqEntry]:
    tokens = normalize_search_query(query)
    if not tokens:
        return []

    matched = [entry for entry in entries if autoeq_search_score(entry, tokens)[0] < 1_000_000]
    matched.sort(key=lambda entry: autoeq_search_score(entry, tokens))
    return matched[:limit]


def autoeq_download_path(entry: AutoEqEntry) -> Path:
    directory = autoeq_cache_dir() / AUTOEQ_PRESET_DIR
    digest = f"{int.from_bytes(hashlib.sha256(entry.cache_key.encode('utf-8')).digest()[:6], 'big'):012x}"
    return directory / f"AutoEq-{digest}.txt"


def autoeq_metadata_line(label: str, value: str) -> str:
    normalized = RE_WHITESPACE.sub(" ", value).strip()
    return f"# AutoEq {label}: {normalized}\n" if normalized else ""


def read_cached_autoeq_target_label(entry: AutoEqEntry) -> str | None:
    path = autoeq_download_path(entry)
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None

    for line in lines:
        if line.startswith(AUTOEQ_TARGET_COMMENT_PREFIX):
            target_label = line.removeprefix(AUTOEQ_TARGET_COMMENT_PREFIX).strip()
            return target_label or None
    return None


def cached_autoeq_target_label(entry: AutoEqEntry) -> str:
    target_label = read_cached_autoeq_target_label(entry)
    if target_label is not None:
        return target_label

    try:
        target_label, _bass_boost = autoeq_target_and_bass_boost(entry, load_autoeq_targets_data())
    except Exception:
        return AUTOEQ_UNKNOWN_TARGET_LABEL
    return target_label


def autoeq_target_and_bass_boost(
    entry: AutoEqEntry,
    targets: list[object],
) -> tuple[str, dict[str, float]]:
    preferred_targets: dict[str, dict[str, object]] = {"unknown": {"unknown": {"unknown": "Flat"}}}
    bass_boosts: dict[str, dict[str, float]] = {}

    for target in targets:
        if not isinstance(target, dict):
            continue

        label = str(target.get("label") or "").strip()
        if not label:
            continue

        bass_boost = target.get("bassBoost")
        if isinstance(bass_boost, dict):
            bass_boosts[label] = {
                "fc": float(bass_boost.get("fc") or 105.0),
                "q": float(bass_boost.get("q") or 0.7),
                "gain": float(bass_boost.get("gain") or 0.0),
            }

        recommended = target.get("recommended") or []
        if not isinstance(recommended, list):
            continue

        for measurement_source in recommended:
            if not isinstance(measurement_source, dict):
                continue

            source = str(measurement_source.get("source") or "").strip()
            form = str(measurement_source.get("form") or "").strip()
            rig = str(measurement_source.get("rig") or "").strip()
            if not source or not form:
                continue

            source_targets = preferred_targets.setdefault(source, {})
            if form not in source_targets:
                source_targets[form] = {}

            if rig:
                form_targets = source_targets[form]
                if isinstance(form_targets, dict) and rig not in form_targets:
                    form_targets[rig] = label
            else:
                source_targets[form] = label

    target_label = "Flat"
    form_targets = preferred_targets.get(entry.source, {}).get(entry.form)
    if isinstance(form_targets, str):
        target_label = form_targets
    elif isinstance(form_targets, dict):
        target_label = str(form_targets.get(entry.rig) or target_label)

    bass_boost = bass_boosts.get(target_label, {"fc": 105.0, "q": 0.7, "gain": 0.0})
    return target_label, bass_boost


def autoeq_equalize_body(entry: AutoEqEntry, targets: list[object]) -> dict[str, object]:
    target_label, bass_boost = autoeq_target_and_bass_boost(entry, targets)
    return {
        "target": target_label,
        "sound_signature": None,
        "sound_signature_smoothing_window_size": 1.0,
        "bass_boost_gain": bass_boost["gain"],
        "bass_boost_fc": bass_boost["fc"],
        "bass_boost_q": bass_boost["q"],
        "treble_boost_gain": 0.0,
        "treble_boost_fc": 10000.0,
        "treble_boost_q": 0.7,
        "tilt": 0.0,
        "fs": int(SAMPLE_RATE),
        "bit_depth": 16,
        "phase": "minimum",
        "f_res": 16.0,
        "preamp": 0.0,
        "max_gain": 12.0,
        "max_slope": 18,
        "window_size": 0.08,
        "treble_window_size": 2.0,
        "treble_f_lower": 6000.0,
        "treble_f_upper": 8000.0,
        "treble_gain_k": 1.0,
        "graphic_eq": False,
        "parametric_eq": True,
        "fixed_band_eq": False,
        "convolution_eq": False,
        "response": {
            "fr_f_step": 1.02,
            "fr_fields": [
                "frequency",
                "smoothed",
                "error_smoothed",
                "target",
                "equalization",
                "equalized_smoothed",
            ],
            "base64fp16": True,
        },
        "name": entry.name,
        "source": entry.source,
        "rig": entry.rig,
        "parametric_eq_config": AUTOEQ_PARAMETRIC_EQ_CONFIG,
    }


def format_autoeq_parametric_eq(parametric_eq: object) -> str:
    if not isinstance(parametric_eq, dict):
        raise RuntimeError("AutoEq response did not include a parametric EQ preset")

    preamp = parametric_eq.get("preamp")
    filters = parametric_eq.get("filters")
    if not isinstance(preamp, int | float) or not isinstance(filters, list):
        raise RuntimeError("AutoEq response did not include a parametric EQ preset")

    filter_type_map = {"LOW_SHELF": "LSC", "PEAKING": "PK", "HIGH_SHELF": "HSC"}
    lines = [f"Preamp: {float(preamp):.2f} dB"]
    for index, filter_data in enumerate(filters, start=1):
        if not isinstance(filter_data, dict):
            raise RuntimeError("AutoEq response included an invalid filter")

        filter_type = filter_type_map.get(str(filter_data.get("type") or ""))
        fc = filter_data.get("fc")
        gain = filter_data.get("gain")
        q = filter_data.get("q")
        if filter_type is None or not all(isinstance(value, int | float) for value in (fc, gain, q)):
            raise RuntimeError("AutoEq response included an invalid filter")

        lines.append(
            f"Filter {index}: ON {filter_type} Fc {float(fc):.1f} Hz Gain {float(gain):.1f} dB Q {float(q):.2f}"
        )

    return "\n".join(lines) + "\n"


def download_autoeq_app_preset_info(entry: AutoEqEntry, *, refresh: bool = False) -> AutoEqGeneratedPreset:
    targets = load_autoeq_targets_data(refresh=refresh)
    body = autoeq_equalize_body(entry, targets)
    target_label = str(body.get("target") or "Flat")
    data = post_json(AUTOEQ_APP_EQUALIZE_URL, body)
    return AutoEqGeneratedPreset(
        text=format_autoeq_parametric_eq(data.get("parametric_eq")),
        target_label=target_label,
    )


def download_autoeq_app_preset(entry: AutoEqEntry, *, refresh: bool = False) -> str:
    return download_autoeq_app_preset_info(entry, refresh=refresh).text


def download_autoeq_preset(entry: AutoEqEntry, *, refresh: bool = False) -> Path:
    return download_autoeq_preset_info(entry, refresh=refresh).path


def download_autoeq_preset_info(
    entry: AutoEqEntry,
    *,
    refresh: bool = False,
) -> AutoEqDownloadedPreset:
    path = autoeq_download_path(entry)
    if not refresh and path.is_file():
        return AutoEqDownloadedPreset(path=path, target_label=cached_autoeq_target_label(entry))

    generated = download_autoeq_app_preset_info(entry, refresh=refresh)
    text = generated.text
    if "Filter " not in text and "Preamp:" not in text:
        raise RuntimeError("downloaded AutoEq preset does not look like an Equalizer APO preset")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(autoeq_metadata_line("target", generated.target_label) + text, encoding="utf-8")
    return AutoEqDownloadedPreset(path=path, target_label=generated.target_label)
