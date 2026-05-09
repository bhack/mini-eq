from __future__ import annotations

import pytest

from tools import check_flatpak_runtime


@pytest.mark.parametrize(
    "app_ref",
    [
        "io.github.bhack.mini-eq//test",
        "app/io.github.bhack.mini-eq/aarch64/test",
        "app/io.github.bhack.mini-eq/x86_64/test",
    ],
)
def test_flatpak_runtime_smoke_accepts_flathub_test_refs(app_ref: str) -> None:
    assert check_flatpak_runtime.flatpak_app_ref(app_ref) == app_ref
    assert check_flatpak_runtime.flatpak_run_command(app_ref, "--check-deps") == [
        "flatpak",
        "run",
        app_ref,
        "--check-deps",
    ]
