from __future__ import annotations

import json

import pytest

from mini_eq import autoeq
from tools import check_autoeq_live


def make_entry(
    name: str = "First AutoEQ Profile",
    source: str = "oratory1990",
    form: str = "over-ear",
    rig: str = "",
) -> autoeq.AutoEqEntry:
    return autoeq.AutoEqEntry(name=name, source=source, form=form, rig=rig)


def test_select_probe_entry_prefers_exact_profile_identity() -> None:
    entries = [
        make_entry(name="First AutoEQ Profile", source="other"),
        make_entry(),
    ]

    entry = check_autoeq_live.select_probe_entry(
        entries,
        name="First AutoEQ Profile",
        source="oratory1990",
        form="over-ear",
        rig=None,
    )

    assert entry.source == "oratory1990"


def test_select_probe_entry_defaults_to_first_parsed_profile() -> None:
    entries = [
        make_entry(name="First"),
        make_entry(name="Second"),
    ]

    entry = check_autoeq_live.select_probe_entry(entries, name=None, source=None, form=None, rig=None)

    assert entry.name == "First"


def test_validate_targets_rejects_changed_target_shape() -> None:
    with pytest.raises(RuntimeError, match="labeled targets"):
        check_autoeq_live.validate_targets([{"name": "Missing label"}])


def test_parse_generated_apo_rejects_non_apo_text() -> None:
    with pytest.raises(RuntimeError, match="does not look like an Equalizer APO preset"):
        check_autoeq_live.parse_generated_apo("not an apo preset")


def test_live_check_downloads_equalizes_and_imports_apo(monkeypatch: pytest.MonkeyPatch) -> None:
    entries_text = json.dumps(
        {
            "First AutoEQ Profile": [
                {"source": "oratory1990", "form": "over-ear"},
            ]
        }
    )
    targets_text = json.dumps(
        [
            {
                "label": "Harman over-ear 2018",
                "recommended": [{"source": "oratory1990", "form": "over-ear"}],
                "bassBoost": {"fc": 105, "q": 0.7, "gain": 6},
            }
        ]
    )
    requested_urls: list[str] = []
    equalize_bodies: list[dict[str, object]] = []

    def fetch_text(url: str, *, timeout: int) -> str:
        requested_urls.append(url)
        assert timeout == 7
        if url == autoeq.AUTOEQ_APP_ENTRIES_URL:
            return entries_text
        if url == autoeq.AUTOEQ_APP_TARGETS_URL:
            return targets_text
        raise AssertionError(f"unexpected URL: {url}")

    def post_json(url: str, body: dict[str, object], *, timeout: int) -> dict[str, object]:
        assert url == autoeq.AUTOEQ_APP_EQUALIZE_URL
        assert timeout == 7
        equalize_bodies.append(body)
        return {
            "parametric_eq": {
                "preamp": -5.5,
                "filters": [
                    {"type": "LOW_SHELF", "fc": 105.0, "gain": 3.0, "q": 0.7},
                    {"type": "PEAKING", "fc": 1000.0, "gain": -2.0, "q": 1.2},
                ],
            }
        }

    monkeypatch.setattr(check_autoeq_live.autoeq, "fetch_text", fetch_text)
    monkeypatch.setattr(check_autoeq_live.autoeq, "post_json", post_json)

    result = check_autoeq_live.check_autoeq_live(timeout=7)

    assert requested_urls == [autoeq.AUTOEQ_APP_ENTRIES_URL, autoeq.AUTOEQ_APP_TARGETS_URL]
    assert equalize_bodies[0]["target"] == "Harman over-ear 2018"
    assert result.entry == make_entry()
    assert result.entry_count == 1
    assert result.target_count == 1
    assert result.band_count == 2
    assert result.preamp_db == -5.5
