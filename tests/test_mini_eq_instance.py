from __future__ import annotations

from pathlib import Path

import pytest

from tests._mini_eq_imports import instance


def test_detects_mini_eq_python_cmdline() -> None:
    assert instance.is_mini_eq_python_cmdline(("python3", "-m", "mini_eq", "--auto-route"))
    assert instance.is_mini_eq_python_cmdline(("/usr/bin/python3", "/tmp/repo/.venv/bin/mini-eq"))
    assert not instance.is_mini_eq_python_cmdline(("pytest", "tests/test_mini_eq_instance.py"))
    assert not instance.is_mini_eq_python_cmdline(("pipewire", "-c", "/tmp/mini-eq-a/filter-chain.conf"))


def test_detects_filter_chain_config_path() -> None:
    assert instance.filter_chain_config_path(("pipewire", "-c", "/tmp/mini-eq-a/filter-chain.conf")) == (
        "/tmp/mini-eq-a/filter-chain.conf"
    )
    assert instance.filter_chain_config_path(("pipewire", "-c", "/tmp/other/filter-chain.conf")) is None
    assert instance.filter_chain_config_path(("python3", "-m", "mini_eq")) is None


def test_stale_filter_chain_skips_child_of_active_python() -> None:
    process = instance.ProcessInfo(
        pid=20,
        ppid=10,
        pgid=20,
        cmdline=("pipewire", "-c", "/tmp/mini-eq-a/filter-chain.conf"),
    )

    assert not instance.is_stale_filter_chain(process, {10})
    assert instance.is_stale_filter_chain(process, {99})


def test_runtime_lock_path_uses_xdg_runtime_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))

    assert instance.runtime_lock_path() == tmp_path / instance.LOCK_FILE_NAME


def test_instance_lock_is_exclusive(tmp_path: Path) -> None:
    lock_path = tmp_path / "mini-eq.lock"
    first = instance.InstanceLock(lock_path)
    second = instance.InstanceLock(lock_path)

    first.acquire()
    try:
        with pytest.raises(instance.MiniEqAlreadyRunningError):
            second.acquire()
    finally:
        first.release()

    assert not lock_path.exists()
