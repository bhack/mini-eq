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
        if version == "1.0":
            return deps.DependencyCheck(label, "ok", required, f"GI namespace {namespace} {version}", hint)
        return deps.DependencyCheck(label, "missing", required, f"{namespace} {version} missing", hint)

    monkeypatch.setattr(deps, "check_gi_repository", fake_check)

    check = deps.check_first_available_gi_repository("Example", ("2.0", "1.0"), "Example GI namespace", True, "hint")

    assert check.ok
    assert check.detail == "GI namespace Example 1.0"


def test_first_available_gi_repository_reports_all_failures(monkeypatch) -> None:
    def fake_check(namespace: str, version: str, label: str, required: bool, hint: str) -> deps.DependencyCheck:
        return deps.DependencyCheck(label, "missing", required, f"{namespace} {version} missing", hint)

    monkeypatch.setattr(deps, "check_gi_repository", fake_check)

    check = deps.check_first_available_gi_repository("Example", ("2.0", "1.0"), "Example GI namespace", True, "hint")

    assert not check.ok
    assert "Example 2.0: Example 2.0 missing" in check.detail
    assert "Example 1.0: Example 1.0 missing" in check.detail


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


def test_pipewire_gobject_check_requires_current_library_version(monkeypatch) -> None:
    fake_pwg = SimpleNamespace(
        get_library_version=lambda: "0.3.2",
        Core=SimpleNamespace(set_pipewire_property=object()),
        Param=SimpleNamespace(new_props_controls=object()),
        Stream=SimpleNamespace(set_pipewire_property=object()),
    )

    monkeypatch.setattr(
        deps,
        "check_python_import",
        lambda _module, label, required, hint: deps.DependencyCheck(label, "ok", required, "shim ok", hint),
    )
    monkeypatch.setattr(
        deps,
        "check_gi_repository",
        lambda _namespace, _version, label, required, hint: deps.DependencyCheck(label, "ok", required, "Pwg ok", hint),
    )
    monkeypatch.setattr(deps.importlib, "import_module", lambda _name: fake_pwg)

    check = deps.check_pipewire_gobject()

    assert not check.ok
    assert "older than required 0.3.4" in check.detail


def test_pipewire_gobject_check_requires_property_override_symbols(monkeypatch) -> None:
    fake_pwg = SimpleNamespace(
        get_library_version=lambda: "0.3.4",
        Core=SimpleNamespace(),
        Param=SimpleNamespace(new_props_controls=object()),
        Stream=SimpleNamespace(set_pipewire_property=object()),
    )

    monkeypatch.setattr(
        deps,
        "check_python_import",
        lambda _module, label, required, hint: deps.DependencyCheck(label, "ok", required, "shim ok", hint),
    )
    monkeypatch.setattr(
        deps,
        "check_gi_repository",
        lambda _namespace, _version, label, required, hint: deps.DependencyCheck(label, "ok", required, "Pwg ok", hint),
    )
    monkeypatch.setattr(deps.importlib, "import_module", lambda _name: fake_pwg)

    check = deps.check_pipewire_gobject()

    assert not check.ok
    assert "Pwg.Core.set_pipewire_property" in check.detail


def test_native_ebur128_check_is_optional_when_library_is_missing(monkeypatch) -> None:
    ebur128 = import_mini_eq_module("ebur128")

    monkeypatch.setattr(ebur128, "version", lambda: (_ for _ in ()).throw(RuntimeError("missing lib")))

    check = deps.check_native_ebur128()

    assert check.name == "libebur128 loudness meter"
    assert check.required is False
    assert check.status == "missing"
    assert "missing lib" in check.detail
