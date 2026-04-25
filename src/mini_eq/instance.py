from __future__ import annotations

import fcntl
import os
import signal
import tempfile
import time
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

LOCK_FILE_NAME = "mini-eq.lock"
FILTER_CHAIN_CONFIG_SUFFIX = "/filter-chain.conf"
FILTER_CHAIN_TEMP_MARKER = "/mini-eq-"
SHUTDOWN_TIMEOUT_SECONDS = 1.5


class MiniEqAlreadyRunningError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProcessInfo:
    pid: int
    ppid: int
    pgid: int
    cmdline: tuple[str, ...]


@dataclass(frozen=True)
class StaleFilterChain:
    pid: int
    pgid: int
    config_path: str


class InstanceLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.handle = None

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("w", encoding="utf-8")

        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            handle.close()
            raise MiniEqAlreadyRunningError("Mini EQ is already running") from exc

        handle.write(f"{os.getpid()}\n")
        handle.flush()
        self.handle = handle

    def release(self) -> None:
        if self.handle is None:
            return

        try:
            fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        finally:
            self.handle.close()
            self.handle = None

        try:
            self.path.unlink()
        except FileNotFoundError:
            pass


class MiniEqInstanceGuard:
    def __init__(self, lock: InstanceLock, cleaned_filter_chains: list[StaleFilterChain]) -> None:
        self.lock = lock
        self.cleaned_filter_chains = cleaned_filter_chains

    @classmethod
    def acquire(cls) -> MiniEqInstanceGuard:
        lock = InstanceLock(runtime_lock_path())
        lock.acquire()

        try:
            active_instances = find_active_mini_eq_python_processes(exclude_pid=os.getpid())
            if active_instances:
                active_pids = ", ".join(str(process.pid) for process in active_instances)
                raise MiniEqAlreadyRunningError(f"Mini EQ is already running as pid(s): {active_pids}")

            cleaned_filter_chains = cleanup_stale_filter_chains(active_python_pids={os.getpid()})
            return cls(lock, cleaned_filter_chains)
        except Exception:
            lock.release()
            raise

    def release(self) -> None:
        self.lock.release()

    def __enter__(self) -> MiniEqInstanceGuard:
        return self

    def __exit__(self, _exc_type, _exc, _tb) -> None:
        self.release()


def runtime_lock_path() -> Path:
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
    if runtime_dir:
        return Path(runtime_dir) / LOCK_FILE_NAME

    return Path(tempfile.gettempdir()) / f"mini-eq-{os.getuid()}" / LOCK_FILE_NAME


def is_mini_eq_python_cmdline(cmdline: Iterable[str]) -> bool:
    args = tuple(cmdline)
    if not args:
        return False

    has_python = any(Path(arg).name.startswith("python") for arg in args[:2])
    if not has_python:
        return False

    has_module_invocation = any(
        args[index] == "-m" and index + 1 < len(args) and args[index + 1] == "mini_eq" for index in range(len(args) - 1)
    )
    has_standalone_script = any(Path(arg).name in {"mini_eq.py", "mini-eq"} for arg in args)
    return has_module_invocation or has_standalone_script


def filter_chain_config_path(cmdline: Iterable[str]) -> str | None:
    args = tuple(cmdline)
    if len(args) < 3:
        return None

    if Path(args[0]).name != "pipewire":
        return None

    for index, arg in enumerate(args[:-1]):
        if arg != "-c":
            continue

        config_path = args[index + 1]
        if FILTER_CHAIN_TEMP_MARKER in config_path and config_path.endswith(FILTER_CHAIN_CONFIG_SUFFIX):
            return config_path

    return None


def is_stale_filter_chain(process: ProcessInfo, active_python_pids: set[int]) -> bool:
    if filter_chain_config_path(process.cmdline) is None:
        return False

    return process.ppid not in active_python_pids


def find_active_mini_eq_python_processes(exclude_pid: int | None = None) -> list[ProcessInfo]:
    excluded = {exclude_pid} if exclude_pid is not None else set()
    return [
        process
        for process in iter_processes()
        if process.pid not in excluded and is_mini_eq_python_cmdline(process.cmdline)
    ]


def cleanup_stale_filter_chains(active_python_pids: set[int]) -> list[StaleFilterChain]:
    cleaned: list[StaleFilterChain] = []

    for process in iter_processes():
        config_path = filter_chain_config_path(process.cmdline)
        if config_path is None or not is_stale_filter_chain(process, active_python_pids):
            continue

        if terminate_process_group(process.pgid):
            cleaned.append(StaleFilterChain(process.pid, process.pgid, config_path))

    return cleaned


def terminate_process_group(pgid: int, timeout_seconds: float = SHUTDOWN_TIMEOUT_SECONDS) -> bool:
    if pgid <= 0 or pgid == os.getpgrp():
        return False

    try:
        os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        return False
    except PermissionError:
        return False

    if wait_for_process_group_exit(pgid, timeout_seconds):
        return True

    try:
        os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        return True
    except PermissionError:
        return False

    return wait_for_process_group_exit(pgid, timeout_seconds)


def wait_for_process_group_exit(pgid: int, timeout_seconds: float) -> bool:
    deadline = time.monotonic() + timeout_seconds

    while time.monotonic() < deadline:
        try:
            os.killpg(pgid, 0)
        except ProcessLookupError:
            return True
        except PermissionError:
            return False

        time.sleep(0.05)

    return False


def iter_processes(proc_root: Path = Path("/proc")) -> list[ProcessInfo]:
    processes: list[ProcessInfo] = []

    for entry in proc_root.iterdir():
        if not entry.name.isdigit():
            continue

        pid = int(entry.name)
        process = read_process_info(pid, entry)
        if process is not None:
            processes.append(process)

    return processes


def read_process_info(pid: int, proc_entry: Path) -> ProcessInfo | None:
    try:
        cmdline = tuple(arg for arg in (proc_entry / "cmdline").read_text(encoding="utf-8").split("\0") if arg)
    except (FileNotFoundError, ProcessLookupError, PermissionError, UnicodeDecodeError):
        return None

    if not cmdline:
        return None

    ppid = read_ppid(proc_entry / "status")
    if ppid is None:
        return None

    try:
        pgid = os.getpgid(pid)
    except ProcessLookupError:
        return None
    except PermissionError:
        return None

    return ProcessInfo(pid=pid, ppid=ppid, pgid=pgid, cmdline=cmdline)


def read_ppid(status_path: Path) -> int | None:
    try:
        for line in status_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("PPid:"):
                return int(line.split(":", 1)[1].strip())
    except (FileNotFoundError, ProcessLookupError, PermissionError, ValueError):
        return None

    return None
