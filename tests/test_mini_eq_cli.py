from __future__ import annotations

import builtins
from types import SimpleNamespace

import pytest

from tests._mini_eq_imports import import_mini_eq_module


def block_app_import(monkeypatch: pytest.MonkeyPatch) -> None:
    real_import = builtins.__import__

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "mini_eq.app" or (name == "app" and level == 1):
            raise AssertionError("mini_eq.app should not be imported")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", guarded_import)


def test_console_help_does_not_import_gtk_app(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    block_app_import(monkeypatch)
    entrypoint = import_mini_eq_module("__main__")

    with pytest.raises(SystemExit) as exc_info:
        entrypoint.console_main(["--help"])

    assert exc_info.value.code == 0
    assert "check Mini EQ runtime dependencies" in capsys.readouterr().out


def test_console_check_deps_does_not_import_gtk_app(monkeypatch: pytest.MonkeyPatch) -> None:
    deps = import_mini_eq_module("deps")
    monkeypatch.setattr(deps, "main", lambda: 0)
    block_app_import(monkeypatch)
    entrypoint = import_mini_eq_module("__main__")

    assert entrypoint.console_main(["--check-deps"]) == 0


def test_console_normal_launch_parses_once(monkeypatch: pytest.MonkeyPatch) -> None:
    app = import_mini_eq_module("app")
    cli = import_mini_eq_module("cli")
    entrypoint = import_mini_eq_module("__main__")
    args = SimpleNamespace(check_deps=False)
    parse_calls: list[list[str]] = []
    run_calls: list[object] = []

    def fake_parse_args(argv: list[str]):
        parse_calls.append(argv)
        return args

    def fake_run_from_args(parsed_args: object) -> int:
        run_calls.append(parsed_args)
        return 7

    monkeypatch.setattr(cli, "parse_args", fake_parse_args)
    monkeypatch.setattr(app, "run_from_args", fake_run_from_args)

    assert entrypoint.console_main(["--headless"]) == 7
    assert parse_calls == [["--headless"]]
    assert run_calls == [args]
