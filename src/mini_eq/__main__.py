from __future__ import annotations

import sys


def console_main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    from .cli import parse_args

    args = parse_args(argv)

    if args.check_deps:
        from .deps import main as check_deps_main

        return check_deps_main()

    from .app import run_from_args

    return run_from_args(args)


if __name__ == "__main__":
    raise SystemExit(console_main())
