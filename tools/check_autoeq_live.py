#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mini_eq import autoeq  # noqa: E402
from mini_eq.core import EqBand, parse_apo_file  # noqa: E402


@dataclass(frozen=True)
class AutoEqLiveCheckResult:
    entry: autoeq.AutoEqEntry
    entry_count: int
    target_count: int
    preamp_db: float
    band_count: int


def profile_description(name: str, source: str | None, form: str | None, rig: str | None) -> str:
    parts = [part for part in (name, source, form) if part]
    if rig:
        parts.append(rig)
    return " / ".join(parts)


def validate_entries(entries: list[autoeq.AutoEqEntry]) -> None:
    if not entries:
        raise RuntimeError("AutoEq profile list is empty after parsing")

    for entry in entries:
        if not entry.name.strip() or not entry.source.strip() or not entry.form.strip():
            raise RuntimeError("AutoEq profile list includes an entry without name, source, or form")


def validate_targets(targets: list[object]) -> int:
    if not targets:
        raise RuntimeError("AutoEq target list is empty")

    labeled_targets = 0
    for target in targets:
        if not isinstance(target, dict):
            continue
        label = str(target.get("label") or "").strip()
        if label:
            labeled_targets += 1

    if labeled_targets == 0:
        raise RuntimeError("AutoEq target list does not include any labeled targets")
    return labeled_targets


def entry_matches_probe(
    entry: autoeq.AutoEqEntry,
    *,
    name: str,
    source: str | None,
    form: str | None,
    rig: str | None,
) -> bool:
    if entry.name.casefold() != name.casefold():
        return False
    if source and entry.source.casefold() != source.casefold():
        return False
    if form and entry.form.casefold() != form.casefold():
        return False
    return not rig or entry.rig.casefold() == rig.casefold()


def select_probe_entry(
    entries: list[autoeq.AutoEqEntry],
    *,
    name: str | None,
    source: str | None,
    form: str | None,
    rig: str | None,
) -> autoeq.AutoEqEntry:
    if not entries:
        raise RuntimeError("AutoEq profile list is empty after parsing")

    if name is None:
        return entries[0]

    for entry in entries:
        if entry_matches_probe(entry, name=name, source=source, form=form, rig=rig):
            return entry

    candidates = autoeq.search_autoeq_entries(entries, name, limit=8)
    if source:
        candidates = [entry for entry in candidates if entry.source.casefold() == source.casefold()]
    if form:
        candidates = [entry for entry in candidates if entry.form.casefold() == form.casefold()]
    if rig:
        candidates = [entry for entry in candidates if entry.rig.casefold() == rig.casefold()]

    if candidates:
        return candidates[0]

    sample = ", ".join(
        profile_description(entry.name, entry.source, entry.form, entry.rig or None)
        for entry in autoeq.search_autoeq_entries(entries, name, limit=5)
    )
    if not sample:
        sample = "no nearby profile matches"

    raise RuntimeError(
        f"AutoEq profile probe could not find {profile_description(name, source, form, rig)}; nearest matches: {sample}"
    )


def parse_generated_apo(text: str) -> tuple[float, list[EqBand]]:
    if "Preamp:" not in text or "Filter " not in text:
        raise RuntimeError("AutoEq generated text does not look like an Equalizer APO preset")

    with tempfile.TemporaryDirectory(prefix="mini-eq-autoeq-live-") as temp_dir:
        path = Path(temp_dir) / "autoeq-live.txt"
        path.write_text(text, encoding="utf-8")
        preamp_db, bands = parse_apo_file(str(path))

    if not bands:
        raise RuntimeError("Mini EQ APO parser did not import any AutoEq filters")
    return preamp_db, bands


def check_autoeq_live(
    *,
    profile_name: str | None = None,
    profile_source: str | None = None,
    profile_form: str | None = None,
    profile_rig: str | None = None,
    timeout: int = autoeq.AUTOEQ_REQUEST_TIMEOUT_SECONDS,
) -> AutoEqLiveCheckResult:
    entries_text = autoeq.fetch_text(autoeq.AUTOEQ_APP_ENTRIES_URL, timeout=timeout)
    entries = autoeq.parse_autoeq_app_entries(entries_text)
    validate_entries(entries)

    targets_text = autoeq.fetch_text(autoeq.AUTOEQ_APP_TARGETS_URL, timeout=timeout)
    targets = autoeq.parse_autoeq_targets_data(targets_text)
    target_count = validate_targets(targets)

    entry = select_probe_entry(
        entries,
        name=profile_name,
        source=profile_source,
        form=profile_form,
        rig=profile_rig,
    )
    data = autoeq.post_json(
        autoeq.AUTOEQ_APP_EQUALIZE_URL,
        autoeq.autoeq_equalize_body(entry, targets),
        timeout=timeout,
    )
    apo_text = autoeq.format_autoeq_parametric_eq(data.get("parametric_eq"))
    preamp_db, bands = parse_generated_apo(apo_text)

    return AutoEqLiveCheckResult(
        entry=entry,
        entry_count=len(entries),
        target_count=target_count,
        preamp_db=preamp_db,
        band_count=len(bands),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a live AutoEQ.app compatibility smoke test.")
    parser.add_argument(
        "--profile",
        default=None,
        help="specific AutoEQ profile name to equalize; defaults to the first parsed profile",
    )
    parser.add_argument("--source", default=None, help="expected AutoEQ measurement source when --profile is set")
    parser.add_argument("--form", default=None, help="expected AutoEQ profile form when --profile is set")
    parser.add_argument("--rig", default=None, help="optional expected AutoEQ measurement rig")
    parser.add_argument(
        "--timeout",
        type=int,
        default=autoeq.AUTOEQ_REQUEST_TIMEOUT_SECONDS,
        help="network timeout in seconds for each AutoEQ request",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.timeout <= 0:
        parser.error("--timeout must be greater than zero")

    try:
        result = check_autoeq_live(
            profile_name=args.profile,
            profile_source=args.source,
            profile_form=args.form,
            profile_rig=args.rig,
            timeout=args.timeout,
        )
    except Exception as exc:
        print(f"AutoEQ live check failed: {exc}", file=sys.stderr)
        return 1

    print("AutoEQ live check passed.")
    print(f"Profiles parsed: {result.entry_count}")
    print(f"Targets parsed: {result.target_count}")
    print(
        "Probe profile: "
        f"{profile_description(result.entry.name, result.entry.source, result.entry.form, result.entry.rig or None)}"
    )
    print(f"Imported APO filters: {result.band_count}")
    print(f"Imported preamp: {result.preamp_db:.2f} dB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
