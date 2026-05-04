from __future__ import annotations

from tests._mini_eq_imports import import_mini_eq_module

window_state = import_mini_eq_module("window_state")


class FakeSettings:
    def __init__(self) -> None:
        self.bindings: list[tuple[str, object, str, object]] = []

    def bind(self, key: str, window: object, property_name: str, flags: object) -> None:
        self.bindings.append((key, window, property_name, flags))


def test_bind_window_state_binds_size_and_maximized(monkeypatch) -> None:
    fake_settings = FakeSettings()
    fake_window = object()
    monkeypatch.setattr(window_state, "create_window_state_settings", lambda: fake_settings)

    assert window_state.bind_window_state(fake_window) is fake_settings
    assert [(key, property_name) for key, _window, property_name, _flags in fake_settings.bindings] == [
        ("window-width", "default-width"),
        ("window-height", "default-height"),
        ("window-maximized", "maximized"),
    ]
    assert all(window is fake_window for _key, window, _property_name, _flags in fake_settings.bindings)


def test_bind_window_state_noops_when_schema_is_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(window_state, "create_window_state_settings", lambda: None)

    assert window_state.bind_window_state(object()) is None
