from __future__ import annotations

import pytest

from tools import check_flatpak_runtime


def node_item(item_id: int, name: str) -> dict:
    return {
        "id": item_id,
        "type": "PipeWire:Interface:Node",
        "info": {"props": {"node.name": name, "object.serial": str(item_id + 1000)}},
    }


def link_item(item_id: int, output_node: int, input_node: int, state: str) -> dict:
    return {
        "id": item_id,
        "type": "PipeWire:Interface:Link",
        "info": {
            "state": state,
            "props": {
                "link.output.node": str(output_node),
                "link.input.node": str(input_node),
            },
        },
    }


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


def test_flatpak_runtime_smoke_includes_extra_flatpak_run_args(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "MINI_EQ_FLATPAK_RUN_ARGS",
        "--filesystem=/tmp/mini-eq-runtime/pipewire-0:ro --env=PIPEWIRE_RUNTIME_DIR=/tmp/mini-eq-runtime",
    )

    assert check_flatpak_runtime.flatpak_run_command("io.github.bhack.mini-eq//master", "--check-deps") == [
        "flatpak",
        "run",
        "--filesystem=/tmp/mini-eq-runtime/pipewire-0:ro",
        "--env=PIPEWIRE_RUNTIME_DIR=/tmp/mini-eq-runtime",
        "io.github.bhack.mini-eq//master",
        "--check-deps",
    ]


def test_flatpak_runtime_recognizes_active_processing_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        check_flatpak_runtime,
        "read_pw_dump",
        lambda: [
            node_item(10, "mini_eq_sink"),
            node_item(20, "mini_eq_sink_output"),
            node_item(30, "ci_null_sink"),
            node_item(40, "browser"),
            link_item(90, 40, 10, "active"),
            link_item(91, 20, 30, "active"),
        ],
    )

    assert check_flatpak_runtime.processing_path_has_active_links() is True


def test_flatpak_runtime_rejects_inactive_processing_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        check_flatpak_runtime,
        "read_pw_dump",
        lambda: [
            node_item(10, "mini_eq_sink"),
            node_item(20, "mini_eq_sink_output"),
            node_item(30, "ci_null_sink"),
            node_item(40, "browser"),
            link_item(90, 40, 10, "active"),
            link_item(91, 20, 30, "paused"),
        ],
    )

    assert check_flatpak_runtime.processing_path_has_active_links() is False
