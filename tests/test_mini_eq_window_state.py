from __future__ import annotations

from tests._mini_eq_imports import import_mini_eq_module

window_state = import_mini_eq_module("window_state")


class FakeSettings:
    def __init__(self, values: dict[str, object] | None = None, user_keys: set[str] | None = None) -> None:
        self.values = values or {}
        self.user_keys = user_keys or set()
        self.writes: list[tuple[str, str, object]] = []

    def get_user_value(self, key: str) -> object | None:
        return object() if key in self.user_keys else None

    def get_int(self, key: str) -> int:
        return int(self.values[key])

    def get_boolean(self, key: str) -> bool:
        return bool(self.values[key])

    def set_int(self, key: str, value: int) -> bool:
        self.values[key] = value
        self.writes.append(("int", key, value))
        return True

    def set_boolean(self, key: str, value: bool) -> bool:
        self.values[key] = value
        self.writes.append(("boolean", key, value))
        return True


class FakeWindow:
    def __init__(self) -> None:
        self.default_size = (1360, 720)
        self.maximize_count = 0
        self.maximized = False
        self.connections: list[tuple[str, object, object]] = []

    def get_default_size(self) -> tuple[int, int]:
        return self.default_size

    def set_default_size(self, width: int, height: int) -> None:
        self.default_size = (width, height)

    def maximize(self) -> None:
        self.maximize_count += 1
        self.maximized = True

    def is_maximized(self) -> bool:
        return self.maximized

    def connect(self, signal_name: str, callback: object, user_data: object) -> int:
        self.connections.append((signal_name, callback, user_data))
        return len(self.connections)

    def emit_notify(self, signal_name: str) -> None:
        for connected_signal, callback, user_data in self.connections:
            if connected_signal == signal_name:
                callback(self, object(), user_data)


def test_bind_window_state_listens_without_loading_schema_defaults(monkeypatch) -> None:
    fake_settings = FakeSettings()
    fake_window = FakeWindow()
    monkeypatch.setattr(window_state, "create_window_state_settings", lambda: fake_settings)

    assert window_state.bind_window_state(fake_window) is fake_settings
    assert [(signal_name, user_data) for signal_name, _callback, user_data in fake_window.connections] == [
        ("notify::default-width", fake_settings),
        ("notify::default-height", fake_settings),
        ("notify::maximized", fake_settings),
    ]
    assert fake_window.default_size == (1360, 720)
    assert fake_window.maximize_count == 0
    assert fake_settings.writes == []


def test_bind_window_state_restores_user_size_and_maximized(monkeypatch) -> None:
    fake_settings = FakeSettings(
        {
            "window-width": 1280,
            "window-height": 700,
            "window-maximized": True,
        },
        user_keys={"window-width", "window-height", "window-maximized"},
    )
    fake_window = FakeWindow()
    monkeypatch.setattr(window_state, "create_window_state_settings", lambda: fake_settings)

    assert window_state.bind_window_state(fake_window) is fake_settings
    assert fake_window.default_size == (1280, 700)
    assert fake_window.maximize_count == 1
    assert fake_settings.writes == []


def test_bound_window_state_saves_size_after_notify(monkeypatch) -> None:
    fake_settings = FakeSettings()
    fake_window = FakeWindow()
    monkeypatch.setattr(window_state, "create_window_state_settings", lambda: fake_settings)

    assert window_state.bind_window_state(fake_window) is fake_settings

    fake_window.set_default_size(1200, 640)
    fake_window.emit_notify("notify::default-width")

    assert fake_settings.writes == [
        ("int", "window-width", 1200),
        ("int", "window-height", 640),
    ]


def test_bound_window_state_saves_maximized_after_notify(monkeypatch) -> None:
    fake_settings = FakeSettings()
    fake_window = FakeWindow()
    monkeypatch.setattr(window_state, "create_window_state_settings", lambda: fake_settings)

    assert window_state.bind_window_state(fake_window) is fake_settings

    fake_window.maximized = True
    fake_window.emit_notify("notify::maximized")

    assert fake_settings.writes == [("boolean", "window-maximized", True)]


def test_bind_window_state_noops_when_schema_is_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(window_state, "create_window_state_settings", lambda: None)

    assert window_state.bind_window_state(object()) is None
