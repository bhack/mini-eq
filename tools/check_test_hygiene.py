#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

DEFAULT_TEST_ROOT = Path("tests")


@dataclass(frozen=True)
class TestFunction:
    path: Path
    line: int
    name: str
    node: ast.FunctionDef

    @property
    def location(self) -> str:
        return f"{self.path}:{self.line}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Report advisory pytest hygiene candidates such as exact duplicate test bodies "
            "and tests without explicit assertions."
        )
    )
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        default=[DEFAULT_TEST_ROOT],
        help="test files or directories to scan; defaults to tests/",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="return a non-zero exit status when any finding is reported",
    )
    return parser.parse_args()


def iter_python_files(paths: list[Path]) -> list[Path]:
    files: set[Path] = set()
    for path in paths:
        if path.is_dir():
            files.update(candidate for candidate in path.rglob("test_*.py") if candidate.is_file())
        elif path.is_file():
            files.add(path)

    return sorted(files)


def collect_tests(paths: list[Path]) -> list[TestFunction]:
    tests: list[TestFunction] = []
    for path in iter_python_files(paths):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
                tests.append(TestFunction(path, node.lineno, node.name, node))
    return tests


def normalized_test_body(test: TestFunction) -> str:
    args = ast.arguments(
        posonlyargs=[],
        args=test.node.args.args,
        vararg=test.node.args.vararg,
        kwonlyargs=test.node.args.kwonlyargs,
        kw_defaults=test.node.args.kw_defaults,
        kwarg=test.node.args.kwarg,
        defaults=test.node.args.defaults,
    )
    clone = ast.FunctionDef(
        name="test_",
        args=args,
        body=test.node.body,
        decorator_list=[],
        returns=None,
        type_comment=None,
    )
    return ast.dump(clone, include_attributes=False)


def duplicate_body_groups(tests: list[TestFunction]) -> list[list[TestFunction]]:
    groups: defaultdict[str, list[TestFunction]] = defaultdict(list)
    for test in tests:
        groups[normalized_test_body(test)].append(test)

    return [matches for matches in groups.values() if len(matches) > 1]


def has_explicit_assertion(test: TestFunction) -> bool:
    for node in ast.walk(test.node):
        if isinstance(node, ast.Assert):
            return True
        if isinstance(node, ast.Call) and call_name(node.func) in {"pytest.raises", "raises", "assertRaises"}:
            return True
        if isinstance(node, ast.Call) and call_name(node.func).startswith("self.assert"):
            return True

    return False


def call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = call_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""


def no_assertion_tests(tests: list[TestFunction]) -> list[TestFunction]:
    return [test for test in tests if not has_explicit_assertion(test)]


def print_findings(tests: list[TestFunction]) -> int:
    duplicate_groups = duplicate_body_groups(tests)
    no_assertions = no_assertion_tests(tests)
    finding_count = len(duplicate_groups) + len(no_assertions)

    print(f"Scanned {len(tests)} test functions.")

    if duplicate_groups:
        print("\nExact duplicate test bodies:")
        for group in duplicate_groups:
            print("  - Duplicate group:")
            for test in group:
                print(f"    {test.location} {test.name}")

    if no_assertions:
        print("\nTests without explicit assertions or pytest.raises:")
        for test in no_assertions:
            print(f"  - {test.location} {test.name}")
        print("    Review only: raise-only smoke tests can be intentional.")

    if finding_count == 0:
        print("No test hygiene candidates found.")
    else:
        print(
            "\nReported "
            f"{len(duplicate_groups)} duplicate body group(s) and "
            f"{len(no_assertions)} no-assert test candidate(s)."
        )

    return finding_count


def main() -> int:
    args = parse_args()
    try:
        tests = collect_tests(args.paths)
    except SyntaxError as exc:
        print(f"error: failed to parse {exc.filename}: {exc}", file=sys.stderr)
        return 2

    finding_count = print_findings(tests)
    return 1 if args.strict and finding_count else 0


if __name__ == "__main__":
    raise SystemExit(main())
