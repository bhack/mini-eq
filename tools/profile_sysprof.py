from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run Mini EQ or its deterministic benchmark under sysprof-cli.",
        epilog=(
            "Examples:\n"
            "  .venv/bin/python tools/profile_sysprof.py -- --auto-route\n"
            "  .venv/bin/python tools/profile_sysprof.py --target benchmark -- --iterations 80 --warmup 20"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--capture-out", default="/tmp/mini-eq.syscap", help="Sysprof capture output path")
    parser.add_argument(
        "--target",
        choices=("app", "benchmark"),
        default="app",
        help="profile the live app or the deterministic fader benchmark",
    )
    parser.add_argument("--no-gtk-trace", action="store_true", help="do not pass --gtk to sysprof-cli")
    parser.add_argument("--no-speedtrack", action="store_true", help="do not pass --speedtrack to sysprof-cli")
    parser.add_argument("--gnome-shell", action="store_true", help="also ask GNOME Shell for profiler statistics")
    parser.add_argument(
        "target_args", nargs=argparse.REMAINDER, help="arguments passed to the selected target after --"
    )
    args = parser.parse_args(argv)

    sysprof_cli = shutil.which("sysprof-cli")
    if sysprof_cli is None:
        print("sysprof-cli is not installed; install the system Sysprof package first", file=sys.stderr)
        return 1

    target_args = list(args.target_args)
    if target_args and target_args[0] == "--":
        target_args = target_args[1:]

    repo_root = Path(__file__).resolve().parent.parent
    src_dir = repo_root / "src"
    capture_path = Path(args.capture_out).expanduser()
    capture_path.parent.mkdir(parents=True, exist_ok=True)

    sysprof_args = [sysprof_cli, "--force", f"--env=PYTHONPATH={src_dir}"]
    if not args.no_gtk_trace:
        sysprof_args.extend(("--gtk", "--use-trace-fd"))
    if not args.no_speedtrack:
        sysprof_args.append("--speedtrack")
    if args.gnome_shell:
        sysprof_args.append("--gnome-shell")

    if args.target == "app":
        target_command = [sys.executable, "-m", "mini_eq", *target_args]
    else:
        target_command = [sys.executable, str(repo_root / "tools" / "benchmark_fader_drag.py"), *target_args]

    command = [*sysprof_args, str(capture_path), "--", *target_command]
    result = subprocess.run(command, cwd=repo_root, check=False)
    if result.returncode == 0:
        print(f"saved Sysprof capture to {capture_path}")
    return int(result.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
