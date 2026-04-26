from __future__ import annotations

import argparse
import cProfile
import io
import pstats
import sys
from pathlib import Path

from mini_eq.__main__ import console_main as mini_eq_main


def print_stats(profile_path: Path, limit: int) -> None:
    stream = io.StringIO()
    stats = pstats.Stats(str(profile_path), stream=stream).strip_dirs().sort_stats("cumulative")
    stats.print_stats(limit)
    print(stream.getvalue())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run Mini EQ under cProfile for a manual live interaction session.",
        epilog="Example: PYTHONPATH=src python3 tools/profile_live_app.py -- --auto-route",
    )
    parser.add_argument("--profile-out", default="/tmp/mini-eq-live.prof", help="cProfile output path")
    parser.add_argument("--stats-limit", type=int, default=40, help="number of cumulative stats to print")
    parser.add_argument("app_args", nargs=argparse.REMAINDER, help="arguments passed to mini-eq after --")
    args = parser.parse_args(argv)

    app_args = list(args.app_args)
    if app_args and app_args[0] == "--":
        app_args = app_args[1:]

    profile_path = Path(args.profile_out).expanduser()
    profile_path.parent.mkdir(parents=True, exist_ok=True)

    profiler = cProfile.Profile()
    exit_code = 0
    try:
        profiler.enable()
        exit_code = int(mini_eq_main(app_args) or 0)
    except SystemExit as exc:
        if isinstance(exc.code, int):
            exit_code = exc.code
        elif exc.code is None:
            exit_code = 0
        else:
            print(exc.code, file=sys.stderr)
            exit_code = 1
    finally:
        profiler.disable()
        profiler.dump_stats(str(profile_path))

    print(f"saved cProfile data to {profile_path}")
    print_stats(profile_path, max(1, int(args.stats_limit)))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
