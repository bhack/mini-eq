from __future__ import annotations

import shutil
import subprocess

import pytest

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
    assert "StartupNotify=true" in desktop_file
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


def test_gsettings_schema_compiles(tmp_path) -> None:
    glib_compile_schemas = shutil.which("glib-compile-schemas")
    if glib_compile_schemas is None:
        pytest.skip("glib-compile-schemas is not installed")

    schema_path = tmp_path / desktop_integration.APP_SCHEMA_NAME
    schema_path.write_bytes(desktop_integration.APP_SCHEMA_SOURCE.read_bytes())

    result = subprocess.run([glib_compile_schemas, "--strict", "--dry-run", str(tmp_path)], check=True)

    assert result.returncode == 0


def test_install_gsettings_schema_copies_package_schema(monkeypatch, tmp_path) -> None:
    compiled_dirs = []
    monkeypatch.setattr(desktop_integration, "compile_gsettings_schemas", lambda path: compiled_dirs.append(path))

    target = desktop_integration.install_gsettings_schema(tmp_path)

    assert target == tmp_path / desktop_integration.APP_SCHEMA_NAME
    assert target.read_bytes() == desktop_integration.APP_SCHEMA_SOURCE.read_bytes()
    assert compiled_dirs == [tmp_path]


def test_compile_gsettings_schemas_raises_when_compiler_fails(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(desktop_integration.shutil, "which", lambda _name: "/usr/bin/glib-compile-schemas")

    def run(_command, *, check, capture_output, text):
        assert check is False
        assert capture_output is True
        assert text is True
        return subprocess.CompletedProcess(_command, 1, stdout="", stderr="schema failed")

    monkeypatch.setattr(desktop_integration.subprocess, "run", run)

    with pytest.raises(RuntimeError, match=f"could not compile GSettings schemas in {tmp_path}: schema failed"):
        desktop_integration.compile_gsettings_schemas(tmp_path)


def test_compile_gsettings_schemas_noops_without_compiler(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(desktop_integration.shutil, "which", lambda _name: None)
    monkeypatch.setattr(desktop_integration.subprocess, "run", lambda *_args, **_kwargs: pytest.fail("compiler used"))

    assert desktop_integration.compile_gsettings_schemas(tmp_path) is None
