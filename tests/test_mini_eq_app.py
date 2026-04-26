from __future__ import annotations

from importlib.resources import files
from types import SimpleNamespace

from tests._mini_eq_imports import import_mini_eq_module

app = import_mini_eq_module("app")


def test_style_resource_is_packaged_with_application_css() -> None:
    css = files("mini_eq").joinpath("style.css").read_text(encoding="utf-8")

    assert ".toolbar-row" in css
    assert ".headroom-panel" in css


class FakeWindow:
    def __init__(self, *, ui_shutting_down: bool) -> None:
        self.ui_shutting_down = ui_shutting_down
        self.present_count = 0
        self.close_count = 0

    def present(self) -> None:
        self.present_count += 1

    def close(self) -> None:
        self.close_count += 1


class FakeApplication:
    def __init__(self, *, window: FakeWindow | None = None) -> None:
        self.window = window
        self.quit_count = 0

    def quit(self) -> None:
        self.quit_count += 1


def test_window_present_idle_skips_window_during_shutdown() -> None:
    window = FakeWindow(ui_shutting_down=True)
    application = SimpleNamespace(window=window, window_present_source_id=123)

    assert app.MiniEqApplication.on_window_present_idle(application) is False
    assert application.window_present_source_id == 0
    assert window.present_count == 0


def test_window_present_idle_presents_active_window() -> None:
    window = FakeWindow(ui_shutting_down=False)
    application = SimpleNamespace(window=window, window_present_source_id=123)

    assert app.MiniEqApplication.on_window_present_idle(application) is False
    assert application.window_present_source_id == 0
    assert window.present_count == 1


def test_close_action_closes_active_window() -> None:
    window = FakeWindow(ui_shutting_down=False)
    application = FakeApplication(window=window)

    app.MiniEqApplication.on_close_action(application, None, None)

    assert window.close_count == 1
    assert application.quit_count == 0


def test_close_action_quits_without_active_window() -> None:
    application = FakeApplication()

    app.MiniEqApplication.on_close_action(application, None, None)

    assert application.quit_count == 1


def test_quit_action_quits_application() -> None:
    application = FakeApplication()

    app.MiniEqApplication.on_quit_action(application, None, None)

    assert application.quit_count == 1
