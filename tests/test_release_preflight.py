from __future__ import annotations

import re

from tools import release_preflight

LEAK_RE = re.compile(release_preflight.LEAK_PATTERN)


def leak_match(text: str) -> bool:
    return LEAK_RE.search(text) is not None


def test_leak_pattern_matches_common_credential_prefixes() -> None:
    samples = ["value=" + "gh" + prefix + "_" + ("A" * 36) for prefix in ("p", "o", "u", "s", "r")]
    samples.extend(
        [
            "value=" + "github" + "_pat_" + ("A" * 40),
            "value=" + "py" + "pi-" + ("A" * 40),
            "value=" + "s" + "k-" + ("A" * 40),
            "value=" + "AK" + "IA" + ("A" * 16),
            "value=" + "AS" + "IA" + ("A" * 16),
            "api" + "_key=value",
            "/" + "home/user/project",
        ]
    )

    for sample in samples:
        assert leak_match(sample)


def test_leak_pattern_matches_common_key_headers() -> None:
    for prefix in ("", "RSA ", "OPENSSH ", "EC ", "ENCRYPTED "):
        marker = "-----BEGIN " + prefix + "PRIVATE KEY-----"

        assert leak_match(marker)


def test_allowed_matches_still_cover_public_release_references() -> None:
    word = "to" + "ken"
    lines = [
        "${{ github." + word + " }}",
        "handle_" + word,
        "id-" + word + ": write",
    ]

    for line in lines:
        assert release_preflight.allowed_leak_match(line)


def test_pipewire_gobject_build_environment_error_lists_missing_tools(monkeypatch) -> None:
    monkeypatch.setattr(release_preflight, "PIPEWIRE_GOBJECT_BUILD_TOOLS", ("definitely-missing-pwg-tool",))
    monkeypatch.setattr(release_preflight, "PIPEWIRE_GOBJECT_PKG_CONFIG_MODULES", ())

    try:
        release_preflight.check_pipewire_gobject_sdist_build_environment()
    except SystemExit as error:
        message = str(error)
        assert "pipewire-gobject from its sdist" in message
        assert "sudo apt install" in message
        assert "definitely-missing-pwg-tool" in message
    else:
        raise AssertionError("Expected missing pipewire-gobject build tool to fail")
