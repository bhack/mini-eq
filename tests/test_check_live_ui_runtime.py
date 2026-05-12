from __future__ import annotations

from tools import check_live_ui_runtime


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


def test_live_ui_runtime_recognizes_active_processing_path(monkeypatch) -> None:
    monkeypatch.setattr(
        check_live_ui_runtime,
        "read_pw_dump",
        lambda: [
            node_item(10, check_live_ui_runtime.VIRTUAL_SINK_NAME),
            node_item(20, check_live_ui_runtime.FILTER_OUTPUT_NAME),
            node_item(30, "ci_null_sink"),
            node_item(40, "browser"),
            link_item(90, 40, 10, "active"),
            link_item(91, 20, 30, "active"),
        ],
    )

    assert check_live_ui_runtime.processing_path_has_active_links() is True


def test_live_ui_runtime_rejects_inactive_processing_path(monkeypatch) -> None:
    monkeypatch.setattr(
        check_live_ui_runtime,
        "read_pw_dump",
        lambda: [
            node_item(10, check_live_ui_runtime.VIRTUAL_SINK_NAME),
            node_item(20, check_live_ui_runtime.FILTER_OUTPUT_NAME),
            node_item(30, "ci_null_sink"),
            node_item(40, "browser"),
            link_item(90, 40, 10, "active"),
            link_item(91, 20, 30, "paused"),
        ],
    )

    assert check_live_ui_runtime.processing_path_has_active_links() is False
