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


def test_remove_legacy_raster_app_icons_only_removes_mini_eq_pngs(tmp_path) -> None:
    mini_eq_png = tmp_path / "64x64/apps/io.github.bhack.mini-eq.png"
    other_png = tmp_path / "64x64/apps/other-app.png"
    mini_eq_svg = tmp_path / "scalable/apps/io.github.bhack.mini-eq.svg"
    mini_eq_png.parent.mkdir(parents=True)
    mini_eq_svg.parent.mkdir(parents=True)
    mini_eq_png.write_bytes(b"png")
    other_png.write_bytes(b"png")
    mini_eq_svg.write_text("<svg/>", encoding="utf-8")

    desktop_integration.remove_legacy_raster_app_icons(tmp_path)

    assert not mini_eq_png.exists()
    assert other_png.exists()
    assert mini_eq_svg.exists()
