from __future__ import annotations

import array
import subprocess
import sys
import wave
from pathlib import Path

import pytest

from tools import check_headless_pipewire_runtime as headless


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


class AlwaysPendingContext:
    def __init__(self) -> None:
        self.iterations = 0

    def pending(self) -> bool:
        return True

    def iteration(self, may_block: bool) -> None:
        assert may_block is False
        self.iterations += 1


def test_drain_main_context_limits_continuous_pending_events() -> None:
    context = AlwaysPendingContext()

    headless.drain_main_context(context, max_iterations=3)

    assert context.iterations == 3


def test_headless_runtime_recognizes_active_processing_path(monkeypatch) -> None:
    monkeypatch.setattr(
        headless.live,
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

    assert headless.processing_path_has_active_links("mini_eq_sink", "mini_eq_sink_output") is True


def test_headless_runtime_rejects_inactive_processing_path(monkeypatch) -> None:
    monkeypatch.setattr(
        headless.live,
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

    assert headless.processing_path_has_active_links("mini_eq_sink", "mini_eq_sink_output") is False


def test_headless_runtime_matches_current_virtual_route(monkeypatch) -> None:
    monkeypatch.setattr(headless.live, "node_by_name", lambda _name: node_item(10, "mini_eq_sink"))
    monkeypatch.setattr(headless.live, "metadata_targets", lambda: {42: ("1010", "Spa:Id")})

    assert headless.route_to_current_virtual(42, "mini_eq_sink") == "1010"


def test_headless_runtime_rejects_stale_virtual_route(monkeypatch) -> None:
    monkeypatch.setattr(headless.live, "node_by_name", lambda _name: node_item(10, "mini_eq_sink"))
    monkeypatch.setattr(headless.live, "metadata_targets", lambda: {42: ("old-serial", "Spa:Id")})

    assert headless.route_to_current_virtual(42, "mini_eq_sink") is None


def test_raw_s16le_rms_skips_initial_frames(tmp_path) -> None:
    samples = array.array("h", [0, 0] * 4 + [1000, -1000] * 4)
    if sys.byteorder != "little":
        samples.byteswap()

    raw_path = tmp_path / "capture.raw"
    raw_path.write_bytes(samples.tobytes())

    assert headless.raw_s16le_rms(raw_path, skip_frames=4, channels=2) == pytest.approx(1000 / 32768.0)


def test_raw_stdout_capture_is_binary_safe(tmp_path) -> None:
    capture_path = tmp_path / "capture.raw"
    payload = b"\xff\x7f\x00\x80"

    headless.materialize_raw_stdout_capture(capture_path, payload)

    assert capture_path.read_bytes() == payload
    assert headless.signal_capture_output_text(payload, b"status ok\n", raw_stdout=True) == "status ok"


def test_wav_s16le_rms_skips_initial_frames(tmp_path) -> None:
    samples = array.array("h", [0, 0] * 4 + [1000, -1000] * 4)
    if sys.byteorder != "little":
        samples.byteswap()

    wav_path = tmp_path / "capture.wav"
    with wave.open(str(wav_path), "wb") as wav_file:
        wav_file.setnchannels(2)
        wav_file.setsampwidth(2)
        wav_file.setframerate(48_000)
        wav_file.writeframes(samples.tobytes())

    assert headless.wav_s16le_rms(wav_path, skip_frames=4, channels=2) == pytest.approx(1000 / 32768.0)


def test_pw_record_sample_count_support_detection(monkeypatch) -> None:
    def fake_run(command, **kwargs):
        assert command == ["pw-record", "--help"]
        assert kwargs["check"] is False
        return subprocess.CompletedProcess(command, 0, stdout="usage\n  --sample-count 24000\n")

    monkeypatch.setattr(headless.subprocess, "run", fake_run)

    assert headless.pw_record_supports_sample_count() is True


def test_pw_record_capture_uses_raw_only_with_sample_count() -> None:
    assert headless.pw_record_capture_features("usage\n--raw\n--sample-count COUNT\n") == (True, True)
    assert headless.pw_record_capture_features("usage\n--raw\n") == (False, False)


def test_pw_record_capture_command_omits_sample_count_for_old_pipewire() -> None:
    command = headless.build_pw_record_capture_command(
        Path("/tmp/capture.raw"),
        sample_count=24000,
        include_sample_count=False,
        raw_output=False,
    )

    assert "--sample-count" not in command
    assert "--raw" not in command
    assert command[-1:] == ["/tmp/capture.raw"]


def test_signal_processing_check_rejects_unattenuated_resume() -> None:
    headless.assert_signal_is_attenuated(
        "attenuated",
        baseline_rms=0.10,
        measured_rms=0.012,
    )

    with pytest.raises(RuntimeError, match="signal processing check failed"):
        headless.assert_signal_is_attenuated(
            "unattenuated",
            baseline_rms=0.10,
            measured_rms=0.09,
        )


def test_dynamic_sink_properties_create_hotplug_audio_sink() -> None:
    properties = headless.dynamic_sink_properties("ci_hotplug_sink")

    assert 'node.name = "ci_hotplug_sink"' in properties
    assert 'media.class = "Audio/Sink"' in properties
    assert "object.linger = true" in properties
    assert "factory.name = support.null-audio-sink" in properties
    assert "session.suspend-timeout-seconds = 1" in properties


def test_alsa_null_sink_properties_create_alsa_pcm_audio_sink() -> None:
    properties = headless.alsa_null_sink_properties("ci_alsa_null_sink")

    assert 'node.name = "ci_alsa_null_sink"' in properties
    assert 'media.class = "Audio/Sink"' in properties
    assert "object.linger = true" in properties
    assert "factory.name = api.alsa.pcm.sink" in properties
    assert 'api.alsa.path = "null"' in properties
    assert 'audio.format = "S16LE"' in properties
    assert "session.suspend-timeout-seconds = 1" in properties
