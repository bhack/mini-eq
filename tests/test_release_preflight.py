from __future__ import annotations

import os
import re
from pathlib import Path

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
            "to" + "ken=" + ("A" * 40),
            "sec" + "ret=" + ("A" * 40),
            "sec" + "ret_key=" + ("A" * 40),
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


def test_leak_pattern_ignores_regular_token_identifiers() -> None:
    assert not leak_match("tokens = normalize_search_query(query)")
    assert not leak_match("first_token = tokens[0]")
    assert not leak_match("def score(tokens: list[str]) -> int:")


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


def test_release_preflight_source_tree_python_env_prepends_src(monkeypatch) -> None:
    monkeypatch.setenv("PYTHONPATH", "/already-there")

    env = release_preflight.source_tree_python_env()

    assert env["PYTHONPATH"].split(os.pathsep) == [str(release_preflight.ROOT / "src"), "/already-there"]


def test_release_preflight_runs_headless_pipewire_runtime_smoke(monkeypatch) -> None:
    commands: list[list[str | Path]] = []

    monkeypatch.setenv("MINI_EQ_HEADLESS_PIPEWIRE_TIMEOUT", "12")
    monkeypatch.setenv("MINI_EQ_HEADLESS_PIPEWIRE_CYCLES", "4")
    monkeypatch.setenv("MINI_EQ_HEADLESS_PIPEWIRE_AUDIO_DURATION", "34")
    monkeypatch.setattr(release_preflight, "run", lambda command, **_kwargs: commands.append(command))

    release_preflight.run_headless_pipewire_runtime_smoke(Path("/python"))

    assert commands == [
        [
            Path("/python"),
            release_preflight.ROOT / "tools/check_headless_pipewire_runtime.py",
            "--timeout",
            "12",
            "--cycles",
            "4",
            "--audio-duration",
            "34",
        ]
    ]


def test_release_preflight_autoeq_live_notice_tracks_autoeq_paths(monkeypatch, capsys) -> None:
    observed_paths: list[Path] = []

    monkeypatch.setattr(release_preflight, "extension_comparison_base_tag", lambda: "v0.7.4")

    def changed_paths(_base_tag: str, paths: tuple[Path, ...]) -> list[str]:
        observed_paths.extend(paths)
        return ["src/mini_eq/autoeq.py"]

    monkeypatch.setattr(release_preflight, "changed_paths_for_review", changed_paths)

    release_preflight.run_autoeq_live_check_notice()

    output = capsys.readouterr().out
    assert Path("src/mini_eq/autoeq.py") in observed_paths
    assert Path("tools/check_autoeq_live.py") in observed_paths
    assert "AutoEQ.app live compatibility check may be needed" in output
    assert "python3 tools/check_autoeq_live.py" in output


def test_release_preflight_uses_hosted_headless_pipewire_defaults(monkeypatch) -> None:
    commands: list[list[str | Path]] = []

    monkeypatch.delenv("MINI_EQ_HEADLESS_PIPEWIRE_TIMEOUT", raising=False)
    monkeypatch.delenv("MINI_EQ_HEADLESS_PIPEWIRE_CYCLES", raising=False)
    monkeypatch.delenv("MINI_EQ_HEADLESS_PIPEWIRE_AUDIO_DURATION", raising=False)
    monkeypatch.setattr(release_preflight, "run", lambda command, **_kwargs: commands.append(command))

    release_preflight.run_headless_pipewire_runtime_smoke(Path("/python"))

    assert commands == [
        [
            Path("/python"),
            release_preflight.ROOT / "tools/check_headless_pipewire_runtime.py",
            "--timeout",
            "90",
            "--cycles",
            "2",
            "--audio-duration",
            "180",
        ]
    ]


def test_release_preflight_rejects_invalid_headless_pipewire_runtime_env(monkeypatch) -> None:
    def fail_run(_command, **_kwargs) -> None:
        raise AssertionError("Headless runtime smoke should not run with invalid environment")

    monkeypatch.setenv("MINI_EQ_HEADLESS_PIPEWIRE_CYCLES", "2; touch unexpected")
    monkeypatch.setattr(release_preflight, "run", fail_run)

    try:
        release_preflight.run_headless_pipewire_runtime_smoke(Path("/python"))
    except SystemExit as error:
        message = str(error)
        assert "MINI_EQ_HEADLESS_PIPEWIRE_CYCLES" in message
        assert "integer between 1 and 20" in message
    else:
        raise AssertionError("Expected invalid headless runtime smoke environment to fail")


def test_flatpak_pipewire_gobject_pin_accepts_matching_floor(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\ndependencies = ["pipewire-gobject>=0.3.7,<0.4"]\n',
        encoding="utf-8",
    )
    (tmp_path / "io.github.bhack.mini-eq.yaml").write_text(
        "modules:\n  - name: pipewire-gobject\n    sources:\n      - type: git\n        tag: 0.3.7\n",
        encoding="utf-8",
    )

    release_preflight.check_flatpak_pipewire_gobject_pin(tmp_path)


def test_flatpak_pipewire_gobject_pin_rejects_stale_manifest(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\ndependencies = ["pipewire-gobject>=0.3.7,<0.4"]\n',
        encoding="utf-8",
    )
    (tmp_path / "io.github.bhack.mini-eq.yaml").write_text(
        "modules:\n  - name: pipewire-gobject\n    sources:\n      - type: git\n        tag: 0.3.6\n",
        encoding="utf-8",
    )

    try:
        release_preflight.check_flatpak_pipewire_gobject_pin(tmp_path)
    except SystemExit as error:
        message = str(error)
        assert "pipewire-gobject>=0.3.7" in message
        assert "bundles tag 0.3.6" in message
    else:
        raise AssertionError("Expected stale Flatpak pipewire-gobject tag to fail")
