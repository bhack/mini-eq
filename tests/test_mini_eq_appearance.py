from __future__ import annotations

import json
from types import SimpleNamespace

from tests._mini_eq_imports import core, import_mini_eq_module

appearance = import_mini_eq_module("appearance")


def test_appearance_preference_round_trips_through_app_config(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setattr(core, "PRESET_STORAGE_DIR", None)

    appearance.save_appearance_preference(appearance.APPEARANCE_DARK)

    assert appearance.load_appearance_preference() == appearance.APPEARANCE_DARK
    assert json.loads(appearance.settings_path().read_text(encoding="utf-8")) == {
        appearance.APPEARANCE_KEY: appearance.APPEARANCE_DARK,
    }


def test_invalid_appearance_preference_falls_back_to_system(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setattr(core, "PRESET_STORAGE_DIR", None)
    settings_path = appearance.settings_path()
    settings_path.parent.mkdir(parents=True)
    settings_path.write_text(json.dumps({appearance.APPEARANCE_KEY: "sepia"}) + "\n", encoding="utf-8")

    assert appearance.load_appearance_preference() == appearance.APPEARANCE_SYSTEM


def test_style_switcher_uses_libadwaita_recommended_color_schemes(monkeypatch) -> None:
    selected_scheme = None
    prefer_light = object()
    force_light = object()
    force_dark = object()

    class FakeStyleManager:
        def set_color_scheme(self, color_scheme) -> None:
            nonlocal selected_scheme
            selected_scheme = color_scheme

    fake_adw = SimpleNamespace(
        StyleManager=SimpleNamespace(get_default=lambda: FakeStyleManager()),
        ColorScheme=SimpleNamespace(
            PREFER_LIGHT=prefer_light,
            FORCE_LIGHT=force_light,
            FORCE_DARK=force_dark,
        ),
    )
    monkeypatch.setattr(appearance, "Adw", fake_adw)

    assert appearance.apply_appearance_preference(appearance.APPEARANCE_SYSTEM) == appearance.APPEARANCE_SYSTEM
    assert selected_scheme is prefer_light

    assert appearance.apply_appearance_preference(appearance.APPEARANCE_LIGHT) == appearance.APPEARANCE_LIGHT
    assert selected_scheme is force_light

    assert appearance.apply_appearance_preference(appearance.APPEARANCE_DARK) == appearance.APPEARANCE_DARK
    assert selected_scheme is force_dark
