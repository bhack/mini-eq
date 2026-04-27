from __future__ import annotations

from types import SimpleNamespace

from tests._mini_eq_imports import import_mini_eq_module

deps = import_mini_eq_module("deps")


def test_dependency_exit_code_fails_only_required_missing_checks() -> None:
    checks = [
        deps.DependencyCheck("required ok", "ok", True, "ready"),
        deps.DependencyCheck("optional missing", "missing", False, "not installed"),
    ]

    assert deps.dependency_exit_code(checks) == 0

    checks.append(deps.DependencyCheck("required missing", "missing", True, "not installed"))

    assert deps.dependency_exit_code(checks) == 1


def test_dependency_report_includes_hints_for_failed_checks() -> None:
    report = deps.format_dependency_report(
        [
            deps.DependencyCheck("required missing", "missing", True, "not installed", "install required package"),
            deps.DependencyCheck("optional ok", "ok", False, "ready"),
        ]
    )

    assert "[MISSING] required missing: not installed" in report
    assert "install hint: install required package" in report
    assert "[OK] optional ok: ready" in report
    assert "One or more required dependencies are missing" in report


def test_first_available_gi_repository_accepts_later_version(monkeypatch) -> None:
    def fake_check(namespace: str, version: str, label: str, required: bool, hint: str) -> deps.DependencyCheck:
        if version == "0.4":
            return deps.DependencyCheck(label, "ok", required, f"GI namespace {namespace} {version}", hint)
        return deps.DependencyCheck(label, "missing", required, f"{namespace} {version} missing", hint)

    monkeypatch.setattr(deps, "check_gi_repository", fake_check)

    check = deps.check_first_available_gi_repository("Wp", ("0.5", "0.4"), "WirePlumber GI namespace", True, "hint")

    assert check.ok
    assert check.detail == "GI namespace Wp 0.4"


def test_first_available_gi_repository_reports_all_failures(monkeypatch) -> None:
    def fake_check(namespace: str, version: str, label: str, required: bool, hint: str) -> deps.DependencyCheck:
        return deps.DependencyCheck(label, "missing", required, f"{namespace} {version} missing", hint)

    monkeypatch.setattr(deps, "check_gi_repository", fake_check)

    check = deps.check_first_available_gi_repository("Wp", ("0.5", "0.4"), "WirePlumber GI namespace", True, "hint")

    assert not check.ok
    assert "Wp 0.5: Wp 0.5 missing" in check.detail
    assert "Wp 0.4: Wp 0.4 missing" in check.detail


def test_gi_repository_attribute_requires_named_attribute(monkeypatch) -> None:
    def fake_check(namespace: str, version: str, label: str, required: bool, hint: str) -> deps.DependencyCheck:
        return deps.DependencyCheck(label, "ok", required, f"GI namespace {namespace} {version}", hint)

    monkeypatch.setattr(deps, "check_gi_repository", fake_check)
    monkeypatch.setattr(
        deps.importlib,
        "import_module",
        lambda _name: SimpleNamespace(Button=SimpleNamespace(set_can_shrink=object())),
    )

    check = deps.check_gi_repository_attribute("Gtk", "4.0", "Button.set_can_shrink", "GTK", True, "hint")

    assert check.ok
    assert check.detail == "Gtk.Button.set_can_shrink is available"


def test_gi_repository_attribute_reports_missing_attribute(monkeypatch) -> None:
    def fake_check(namespace: str, version: str, label: str, required: bool, hint: str) -> deps.DependencyCheck:
        return deps.DependencyCheck(label, "ok", required, f"GI namespace {namespace} {version}", hint)

    monkeypatch.setattr(deps, "check_gi_repository", fake_check)
    monkeypatch.setattr(deps.importlib, "import_module", lambda _name: SimpleNamespace(Button=SimpleNamespace()))

    check = deps.check_gi_repository_attribute("Gtk", "4.0", "Button.set_can_shrink", "GTK", True, "hint")

    assert not check.ok
    assert check.detail == "GI namespace lacks Gtk.Button.set_can_shrink"
