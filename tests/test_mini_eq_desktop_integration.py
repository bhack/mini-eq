from __future__ import annotations

from tests._mini_eq_imports import import_mini_eq_module

desktop_integration = import_mini_eq_module("desktop_integration")


def test_app_id_uses_github_account_namespace() -> None:
    assert desktop_integration.APP_ID == "io.github.bhack.mini-eq"
    assert desktop_integration.APP_ICON_NAME == desktop_integration.APP_ID


def test_desktop_file_launches_installed_module(monkeypatch) -> None:
    monkeypatch.setattr(desktop_integration.sys, "executable", "/opt/Mini EQ/python")

    desktop_file = desktop_integration.build_desktop_file()

    assert 'Exec="/opt/Mini EQ/python" -m mini_eq' in desktop_file
    assert "Icon=io.github.bhack.mini-eq" in desktop_file
    assert "StartupWMClass=io.github.bhack.mini-eq" in desktop_file
