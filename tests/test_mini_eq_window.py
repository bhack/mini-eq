from __future__ import annotations

from types import MethodType, SimpleNamespace

from tests._mini_eq_imports import import_mini_eq_module

release_notes = import_mini_eq_module("release_notes")
window = import_mini_eq_module("window")
window_layout = import_mini_eq_module("window_layout")


class FakeSwitch:
    def __init__(self, active: bool) -> None:
        self.active = active
        self.state = active

    def get_active(self) -> bool:
        return self.active

    def set_active(self, active: bool) -> None:
        self.active = active

    def get_state(self) -> bool:
        return self.state

    def set_state(self, state: bool) -> None:
        self.state = state


class FakeStateLabel:
    def __init__(self) -> None:
        self.text = ""
        self.tooltip = None
        self.css_classes: set[str] = set()

    def set_text(self, text: str) -> None:
        self.text = text

    def set_tooltip_text(self, text: str | None) -> None:
        self.tooltip = text

    def add_css_class(self, css_class: str) -> None:
        self.css_classes.add(css_class)

    def remove_css_class(self, css_class: str) -> None:
        self.css_classes.discard(css_class)


class FakeFile:
    def __init__(self, path: str) -> None:
        self.path = path

    def get_path(self) -> str:
        return self.path


class FakeOpenDialog:
    def __init__(self, path: str) -> None:
        self.path = path

    def open_finish(self, _result: object) -> FakeFile:
        return FakeFile(self.path)


class FakeUtilityPaneButton:
    def __init__(self, *, visible: bool) -> None:
        self.visible = visible
        self.active = False

    def get_visible(self) -> bool:
        return self.visible

    def set_active(self, active: bool) -> None:
        self.active = active


class FakeAboutDialog:
    instances: list[FakeAboutDialog] = []

    def __init__(self, **properties: object) -> None:
        self.properties = properties
        self.presented_to = None
        self.instances.append(self)

    def present(self, parent: object) -> None:
        self.presented_to = parent


def bind_control_refresh_methods(fake_window: SimpleNamespace) -> None:
    fake_window.sync_control_switches_from_controller = MethodType(
        window.MiniEqWindow.sync_control_switches_from_controller,
        fake_window,
    )
    fake_window.refresh_after_route_state_changed = MethodType(
        window.MiniEqWindow.refresh_after_route_state_changed,
        fake_window,
    )
    fake_window.refresh_after_eq_state_changed = MethodType(
        window.MiniEqWindow.refresh_after_eq_state_changed,
        fake_window,
    )
    fake_window.schedule_startup_auto_route = MethodType(
        window.MiniEqWindow.schedule_startup_auto_route,
        fake_window,
    )
    fake_window.is_startup_auto_route_retryable_error = MethodType(
        window.MiniEqWindow.is_startup_auto_route_retryable_error,
        fake_window,
    )
    fake_window.schedule_startup_auto_route_retry_after_error = MethodType(
        window.MiniEqWindow.schedule_startup_auto_route_retry_after_error,
        fake_window,
    )
    fake_window.apply_startup_auto_route = MethodType(
        window.MiniEqWindow.apply_startup_auto_route,
        fake_window,
    )
    fake_window.on_startup_auto_route_idle = MethodType(
        window.MiniEqWindow.on_startup_auto_route_idle,
        fake_window,
    )


def test_about_dialog_includes_current_release_notes(monkeypatch) -> None:
    FakeAboutDialog.instances = []
    fake_window = SimpleNamespace()
    notes = release_notes.AboutReleaseNotes("1.2.3", "<p>Changed.</p>")
    monkeypatch.setattr(window_layout.Adw, "AboutDialog", FakeAboutDialog)
    monkeypatch.setattr(window_layout, "about_release_notes", lambda version: notes)

    window_layout.MiniEqWindowLayoutMixin.show_about_dialog(fake_window)

    dialog = FakeAboutDialog.instances[0]
    assert dialog.properties["release_notes"] == "<p>Changed.</p>"
    assert dialog.properties["release_notes_version"] == "1.2.3"
    assert dialog.properties["version"] == window_layout.__version__
    assert dialog.presented_to is fake_window


def test_visual_layout_height_uses_startup_height_before_first_allocation() -> None:
    fake_window = SimpleNamespace(
        initial_layout_height=720,
        default_min_window_height=600,
        compact_min_window_height=600,
        get_allocated_height=lambda: 0,
    )

    assert window_layout.visual_layout_height(fake_window, None) == 720


def test_visual_layout_height_prefers_real_allocation() -> None:
    fake_window = SimpleNamespace(
        initial_layout_height=720,
        default_min_window_height=600,
        compact_min_window_height=600,
        get_allocated_height=lambda: 840,
    )

    assert window_layout.visual_layout_height(fake_window, None) == 840
    assert window_layout.visual_layout_height(fake_window, 960) == 960


def test_fit_window_default_size_keeps_preferred_size_on_roomy_monitor() -> None:
    assert window.fit_window_default_size_to_monitor(1360, 720, monitor_width=1920, monitor_height=1080) == (
        1360,
        720,
    )


def test_fit_window_default_size_leaves_margin_on_small_monitor() -> None:
    assert window.fit_window_default_size_to_monitor(1360, 720, monitor_width=1366, monitor_height=736) == (
        1334,
        704,
    )


def test_on_close_request_starts_custom_shutdown_sequence() -> None:
    calls: list[str] = []
    fake_window = SimpleNamespace(
        ui_shutting_down=False,
        begin_close_request_shutdown=lambda: calls.append("begin"),
    )

    handled = window.MiniEqWindow.on_close_request(fake_window, None)

    assert handled is True
    assert calls == ["begin"]


def test_compact_warning_title_keeps_bluetooth_warning_glanceable() -> None:
    assert (
        window.compact_warning_title(
            "Bluetooth output is in headset mode. Switch back to A2DP for full-band music playback."
        )
        == "Headset"
    )


def test_bluetooth_profile_summary_handles_missing_profile() -> None:
    fake_window = SimpleNamespace(format_sample_spec=lambda _sink: "48 kHz stereo")
    sink = SimpleNamespace(property_value=lambda key: {"device.api": "bluez5"}.get(key))

    assert window.MiniEqWindow.profile_summary(fake_window, sink) == (
        "Bluetooth",
        "48 kHz stereo | profile unknown",
        False,
        [],
    )


def test_preset_directory_refresh_notifies_control_clients() -> None:
    calls: list[str] = []
    fake_window = SimpleNamespace(
        ui_shutting_down=False,
        preset_refresh_source_id=42,
        refresh_preset_list=lambda: calls.append("refresh"),
        notify_control_presets_changed=lambda: calls.append("presets"),
        notify_control_state_changed=lambda: calls.append("state"),
    )

    keep_source = window.MiniEqWindow.on_preset_dir_changed_idle(fake_window)

    assert keep_source is False
    assert fake_window.preset_refresh_source_id == 0
    assert calls == ["refresh", "presets", "state"]


def test_begin_close_request_shutdown_restores_routing_before_delayed_quit(monkeypatch) -> None:
    scheduled: list[tuple[int, object]] = []
    application = SimpleNamespace(quit_count=0)
    application.quit = lambda: setattr(application, "quit_count", application.quit_count + 1)
    calls: list[object] = []

    monkeypatch.setattr(
        window.GLib,
        "timeout_add",
        lambda delay_ms, callback: scheduled.append((delay_ms, callback)) or 321,
    )

    fake_window = SimpleNamespace(
        ui_shutting_down=False,
        close_finish_source_id=0,
        updating_ui=False,
        route_switch=FakeSwitch(True),
        controller=SimpleNamespace(
            route_system_audio=lambda enabled, announce=True, refresh_output=True: calls.append(
                ("route", enabled, announce, refresh_output)
            )
        ),
        is_system_routed=lambda: True,
        update_info_label=lambda: calls.append("info"),
        update_status_summary=lambda: calls.append("summary"),
        set_visible=lambda visible: calls.append(("visible", visible)),
        prepare_for_shutdown=lambda: calls.append("prepare"),
        get_application=lambda: application,
    )
    fake_window.finish_close_request = MethodType(window.MiniEqWindow.finish_close_request, fake_window)

    window.MiniEqWindow.begin_close_request_shutdown(fake_window)

    assert fake_window.route_switch.get_active() is False
    assert fake_window.updating_ui is False
    assert fake_window.close_finish_source_id == 321
    assert calls == [
        ("route", False, False, False),
        "info",
        "summary",
        ("visible", False),
        "prepare",
    ]
    assert scheduled[0][0] == window.ROUTING_CLOSE_SETTLE_MS

    scheduled[0][1]()

    assert fake_window.close_finish_source_id == 0
    assert application.quit_count == 1


def test_begin_close_request_shutdown_uses_controller_route_state(monkeypatch) -> None:
    scheduled: list[tuple[int, object]] = []
    application = SimpleNamespace(quit_count=0)
    application.quit = lambda: setattr(application, "quit_count", application.quit_count + 1)
    calls: list[object] = []

    monkeypatch.setattr(
        window.GLib,
        "timeout_add",
        lambda delay_ms, callback: scheduled.append((delay_ms, callback)) or 321,
    )

    fake_window = SimpleNamespace(
        ui_shutting_down=False,
        close_finish_source_id=0,
        updating_ui=False,
        route_switch=FakeSwitch(False),
        controller=SimpleNamespace(
            routed=True,
            route_system_audio=lambda enabled, announce=True, refresh_output=True: calls.append(
                ("route", enabled, announce, refresh_output)
            ),
        ),
        is_system_routed=lambda: True,
        update_info_label=lambda: calls.append("info"),
        update_status_summary=lambda: calls.append("summary"),
        set_visible=lambda visible: calls.append(("visible", visible)),
        prepare_for_shutdown=lambda: calls.append("prepare"),
        get_application=lambda: application,
    )
    fake_window.finish_close_request = MethodType(window.MiniEqWindow.finish_close_request, fake_window)

    window.MiniEqWindow.begin_close_request_shutdown(fake_window)

    assert fake_window.route_switch.get_active() is False
    assert calls == [
        ("route", False, False, False),
        "info",
        "summary",
        ("visible", False),
        "prepare",
    ]
    assert scheduled[0][0] == window.ROUTING_CLOSE_SETTLE_MS


def test_begin_close_request_shutdown_hides_when_background_mode_is_enabled() -> None:
    calls: list[object] = []
    application = SimpleNamespace(background_mode=True)

    fake_window = SimpleNamespace(
        ui_shutting_down=False,
        close_finish_source_id=0,
        updating_ui=False,
        route_switch=FakeSwitch(True),
        controller=SimpleNamespace(
            route_system_audio=lambda enabled, announce=True, refresh_output=True: calls.append(
                ("route", enabled, announce, refresh_output)
            )
        ),
        set_visible=lambda visible: calls.append(("visible", visible)),
        notify_control_state_changed=lambda: calls.append("notify"),
        get_application=lambda: application,
    )
    application.update_background_status = lambda: calls.append("background-status")

    window.MiniEqWindow.begin_close_request_shutdown(fake_window)

    assert fake_window.route_switch.get_active() is True
    assert fake_window.close_finish_source_id == 0
    assert calls == [
        ("visible", False),
        "notify",
        "background-status",
    ]


def test_startup_ready_applies_startup_state_before_presenting() -> None:
    calls: list[object] = []
    controller = SimpleNamespace(eq_enabled=True, routed=False)
    application = SimpleNamespace(prepare_window_startup_notification=lambda _window: calls.append("startup-id"))

    def route_system_audio(enabled: bool) -> None:
        calls.append(("route", enabled))
        controller.routed = enabled

    controller.route_system_audio = route_system_audio
    controller.output_preset_target_transition = lambda: SimpleNamespace(changed=False)

    fake_window = SimpleNamespace(
        startup_ready_source_id=99,
        startup_auto_route_source_id=0,
        ui_shutting_down=False,
        startup_ready=False,
        auto_route_on_startup=True,
        updating_ui=False,
        present_when_ready=True,
        route_switch=FakeSwitch(False),
        controller=controller,
        start_preset_monitoring=lambda: calls.append("preset-monitor"),
        apply_output_preset_for_current_output=lambda: calls.append("output-preset"),
        update_eq_power_indicator=lambda: calls.append(("power", fake_window.route_switch.get_active())),
        update_info_label=lambda: calls.append(("info", fake_window.route_switch.get_active())),
        update_status_summary=lambda: calls.append(("summary", fake_window.route_switch.get_active())),
        update_focus_summary=lambda: calls.append("focus"),
        start_analyzer_preview=lambda: calls.append("monitor"),
        notify_control_state_changed=lambda: calls.append("notify"),
        set_status=lambda message: calls.append(("status", message)),
        set_visible=lambda visible: calls.append(("visible", visible)),
        present=lambda: calls.append("present"),
        get_application=lambda: application,
    )
    fake_window.bypass_switch = FakeSwitch(True)
    bind_control_refresh_methods(fake_window)

    keep_source = window.MiniEqWindow.on_startup_ready_idle(fake_window)

    assert keep_source is False
    assert fake_window.startup_ready_source_id == 0
    assert fake_window.startup_ready is True
    assert fake_window.route_switch.get_active() is True
    assert fake_window.route_switch.get_state() is True
    assert calls == [
        "preset-monitor",
        "output-preset",
        "monitor",
        ("route", True),
        ("power", True),
        ("info", True),
        ("summary", True),
        "focus",
        "notify",
        "startup-id",
        ("visible", True),
        "present",
        "notify",
    ]


def test_startup_ready_without_presenting_does_not_force_startup_notification() -> None:
    calls: list[object] = []
    application = SimpleNamespace(
        finish_startup_notification=lambda: (_ for _ in ()).throw(AssertionError("unexpected")),
        prepare_window_startup_notification=lambda _window: (_ for _ in ()).throw(AssertionError("unexpected")),
    )
    fake_window = SimpleNamespace(
        startup_ready_source_id=99,
        startup_auto_route_source_id=0,
        ui_shutting_down=False,
        startup_ready=False,
        auto_route_on_startup=False,
        present_when_ready=False,
        start_preset_monitoring=lambda: calls.append("preset-monitor"),
        apply_output_preset_for_current_output=lambda: calls.append("output-preset"),
        start_analyzer_preview=lambda: calls.append("monitor"),
        notify_control_state_changed=lambda: calls.append("notify"),
        get_application=lambda: application,
    )

    keep_source = window.MiniEqWindow.on_startup_ready_idle(fake_window)

    assert keep_source is False
    assert fake_window.startup_ready is True
    assert calls == [
        "preset-monitor",
        "output-preset",
        "monitor",
        "notify",
    ]


def test_startup_auto_route_idle_routes_after_startup_work() -> None:
    calls: list[object] = []
    controller = SimpleNamespace(eq_enabled=True, routed=False)

    def route_system_audio(enabled: bool) -> None:
        calls.append(("route", enabled))
        controller.routed = enabled

    controller.route_system_audio = route_system_audio
    controller.output_preset_target_transition = lambda: SimpleNamespace(changed=False)

    fake_window = SimpleNamespace(
        startup_auto_route_source_id=321,
        ui_shutting_down=False,
        auto_route_on_startup=True,
        updating_ui=False,
        route_switch=FakeSwitch(False),
        bypass_switch=FakeSwitch(True),
        controller=controller,
        update_eq_power_indicator=lambda: calls.append(("power", fake_window.route_switch.get_active())),
        update_info_label=lambda: calls.append(("info", fake_window.route_switch.get_active())),
        update_status_summary=lambda: calls.append(("summary", fake_window.route_switch.get_active())),
        update_focus_summary=lambda: calls.append("focus"),
        set_status=lambda message: calls.append(("status", message)),
        notify_control_state_changed=lambda: calls.append("notify"),
    )
    bind_control_refresh_methods(fake_window)

    keep_source = window.MiniEqWindow.on_startup_auto_route_idle(fake_window)

    assert keep_source is False
    assert fake_window.startup_auto_route_source_id == 0
    assert fake_window.route_switch.get_active() is True
    assert fake_window.route_switch.get_state() is True
    assert calls == [
        ("route", True),
        ("power", True),
        ("info", True),
        ("summary", True),
        "focus",
        "notify",
    ]


def test_startup_auto_route_reapplies_preset_when_followed_output_changes() -> None:
    calls: list[object] = []
    controller = SimpleNamespace(
        eq_enabled=True,
        routed=False,
        output_sink="alsa_output.headset",
    )

    def route_system_audio(enabled: bool) -> None:
        calls.append(("route", enabled))
        controller.routed = enabled
        controller.output_sink = "alsa_output.speakers"

    controller.route_system_audio = route_system_audio
    controller.output_preset_target_transition = lambda: SimpleNamespace(changed=True)

    fake_window = SimpleNamespace(
        startup_auto_route_source_id=0,
        startup_auto_route_deadline_us=123,
        ui_shutting_down=False,
        auto_route_on_startup=True,
        updating_ui=False,
        output_preset_curve_auto_loaded=True,
        route_switch=FakeSwitch(False),
        bypass_switch=FakeSwitch(True),
        controller=controller,
        apply_output_preset_for_current_output=lambda **kwargs: calls.append(("output-preset", kwargs)) or True,
        update_eq_power_indicator=lambda: calls.append(("power", fake_window.route_switch.get_active())),
        update_info_label=lambda: calls.append(("info", fake_window.route_switch.get_active())),
        update_status_summary=lambda: calls.append(("summary", fake_window.route_switch.get_active())),
        update_focus_summary=lambda: calls.append("focus"),
        set_status=lambda message: calls.append(("status", message)),
        notify_control_state_changed=lambda: calls.append("notify"),
    )
    bind_control_refresh_methods(fake_window)

    window.MiniEqWindow.apply_startup_auto_route(fake_window)

    assert fake_window.startup_auto_route_deadline_us == 0
    assert calls == [
        ("route", True),
        (
            "output-preset",
            {"reset_auto_preset_without_link": True, "announce_no_output_preset": True},
        ),
        ("power", True),
        ("info", True),
        ("summary", True),
        "focus",
        "notify",
    ]


def test_startup_auto_route_retries_until_filter_chain_is_ready(monkeypatch) -> None:
    calls: list[object] = []
    scheduled_callbacks = []
    controller = SimpleNamespace(eq_enabled=True, routed=False)
    attempts = 0

    def route_system_audio(enabled: bool) -> None:
        nonlocal attempts
        attempts += 1
        calls.append(("route", attempts, enabled))
        if attempts == 1:
            raise RuntimeError("filter-chain PipeWire EQ is not ready")
        controller.routed = enabled

    def timeout_add_seconds(interval_seconds: int, callback):
        scheduled_callbacks.append(callback)
        calls.append(("timeout", interval_seconds))
        return 777

    controller.route_system_audio = route_system_audio
    controller.output_preset_target_transition = lambda: SimpleNamespace(changed=False)
    monkeypatch.setattr(window.GLib, "get_monotonic_time", lambda: 1_000)
    monkeypatch.setattr(window.GLib, "timeout_add_seconds", timeout_add_seconds)

    fake_window = SimpleNamespace(
        startup_auto_route_source_id=0,
        startup_auto_route_deadline_us=0,
        ui_shutting_down=False,
        auto_route_on_startup=True,
        updating_ui=False,
        route_switch=FakeSwitch(False),
        bypass_switch=FakeSwitch(True),
        controller=controller,
        update_eq_power_indicator=lambda: calls.append(("power", fake_window.route_switch.get_active())),
        update_info_label=lambda: calls.append(("info", fake_window.route_switch.get_active())),
        update_status_summary=lambda: calls.append(("summary", fake_window.route_switch.get_active())),
        update_focus_summary=lambda: calls.append("focus"),
        set_status=lambda message: calls.append(("status", message)),
        notify_control_state_changed=lambda: calls.append("notify"),
    )
    bind_control_refresh_methods(fake_window)

    window.MiniEqWindow.apply_startup_auto_route(fake_window)

    assert fake_window.startup_auto_route_source_id == 777
    assert fake_window.route_switch.get_active() is False
    assert ("status", "filter-chain PipeWire EQ is not ready") not in calls

    assert scheduled_callbacks[0]() is False

    assert fake_window.startup_auto_route_source_id == 0
    assert fake_window.startup_auto_route_deadline_us == 0
    assert fake_window.route_switch.get_active() is True
    assert fake_window.route_switch.get_state() is True
    assert calls == [
        ("route", 1, True),
        ("timeout", window.STARTUP_AUTO_ROUTE_RETRY_INTERVAL_SECONDS),
        ("power", False),
        ("info", False),
        ("summary", False),
        "focus",
        "notify",
        ("route", 2, True),
        ("power", True),
        ("info", True),
        ("summary", True),
        "focus",
        "notify",
    ]


def test_status_summary_uses_controller_route_state_over_stale_switch() -> None:
    headroom_states: list[dict[str, object]] = []
    state_label = FakeStateLabel()
    fake_window = SimpleNamespace(
        route_switch=FakeSwitch(False),
        controller=SimpleNamespace(eq_enabled=True),
        system_state_label=state_label,
        output_sink_info=lambda: object(),
        is_system_routed=lambda: True,
        profile_summary=lambda _sink: ("USB output", "48 kHz", False, []),
        estimate_curve_peak_db=lambda: -3.0,
        set_headroom_state=lambda **kwargs: headroom_states.append(kwargs),
    )

    window.MiniEqWindow.update_status_summary(fake_window)

    assert state_label.text == "Applied"
    assert "system-state-live" in state_label.css_classes
    assert headroom_states[-1]["kind"] == "safe"


def test_on_route_changed_resets_switch_when_routing_fails() -> None:
    calls: list[object] = []
    route_switch = FakeSwitch(True)

    def fail_route(_enabled: bool) -> None:
        raise RuntimeError("metadata permission denied")

    fake_window = SimpleNamespace(
        updating_ui=False,
        controller=SimpleNamespace(
            eq_enabled=True,
            routed=False,
            route_system_audio=fail_route,
        ),
        route_switch=route_switch,
        bypass_switch=FakeSwitch(True),
        update_eq_power_indicator=lambda: calls.append("power"),
        update_info_label=lambda: calls.append("info"),
        update_status_summary=lambda: calls.append("summary"),
        update_focus_summary=lambda: calls.append("focus"),
        set_status=lambda message: calls.append(("status", message)),
        notify_control_state_changed=lambda: calls.append("notify"),
    )
    bind_control_refresh_methods(fake_window)

    handled = window.MiniEqWindow.on_route_changed(fake_window, route_switch, None)

    assert handled is True
    assert route_switch.get_active() is False
    assert route_switch.get_state() is False
    assert fake_window.updating_ui is False
    assert ("status", "metadata permission denied") in calls


def test_on_route_changed_syncs_bypass_when_controller_enables_eq() -> None:
    calls: list[object] = []
    controller = SimpleNamespace(eq_enabled=False, routed=False)
    route_switch = FakeSwitch(True)

    def route_system_audio(enabled: bool) -> None:
        calls.append(("route", enabled))
        controller.eq_enabled = True
        controller.routed = enabled

    controller.route_system_audio = route_system_audio

    fake_window = SimpleNamespace(
        updating_ui=False,
        controller=controller,
        route_switch=route_switch,
        bypass_switch=FakeSwitch(False),
        update_eq_power_indicator=lambda: calls.append("power"),
        update_info_label=lambda: calls.append("info"),
        update_status_summary=lambda: calls.append("summary"),
        update_focus_summary=lambda: calls.append("focus"),
        invalidate_graph_response_cache=lambda: calls.append("invalidate"),
        queue_graph_draw=lambda: calls.append("draw"),
        update_preset_state=lambda: calls.append("preset-state"),
        set_status=lambda message: calls.append(("status", message)),
        notify_control_state_changed=lambda: calls.append("notify"),
    )
    bind_control_refresh_methods(fake_window)

    handled = window.MiniEqWindow.on_route_changed(fake_window, route_switch, None)

    assert handled is True
    assert fake_window.bypass_switch.get_active() is True
    assert fake_window.bypass_switch.get_state() is True
    assert route_switch.get_state() is True
    assert fake_window.updating_ui is False
    assert calls == [
        ("route", True),
        "power",
        "info",
        "summary",
        "focus",
        "invalidate",
        "draw",
        "preset-state",
        ("status", "System-wide EQ On"),
        "notify",
    ]


def test_import_apo_updates_provisional_curve_status_and_control_state(tmp_path) -> None:
    calls: list[object] = []
    statuses: list[str] = []
    apo_path = tmp_path / "HD 650.txt"
    apo_path.write_text("Preamp: 0 dB\n", encoding="utf-8")

    fake_window = SimpleNamespace(
        controller=SimpleNamespace(
            import_apo_preset=lambda path: calls.append(("import", path)) or 7,
            state_signature=lambda: "imported-signature",
            build_preset_payload=lambda label: {"name": label},
        ),
        selected_band_index=0,
        current_preset_name="Old",
        saved_preset_signature="old-signature",
        output_preset_curve_auto_loaded=True,
        set_visible_band_count=lambda count: calls.append(("visible-bands", count)),
        set_curve_revert_baseline=lambda label: calls.append(("baseline", label)),
        refresh_preset_list=lambda: calls.append("presets"),
        sync_ui_from_state=lambda: calls.append("sync"),
        set_status=lambda message: statuses.append(message),
        notify_control_state_changed=lambda: calls.append("notify"),
    )
    fake_window.import_apo_preset_path = MethodType(window.MiniEqWindow.import_apo_preset_path, fake_window)

    window.MiniEqWindow.on_import_apo_done(fake_window, FakeOpenDialog(str(apo_path)), None)

    assert fake_window.selected_band_index is None
    assert fake_window.current_preset_name is None
    assert fake_window.saved_preset_signature == "imported-signature"
    assert fake_window.output_preset_auto_applied is False
    assert fake_window.output_preset_curve_auto_loaded is False
    assert statuses == ["Imported APO curve"]
    assert calls == [
        ("import", str(apo_path)),
        ("visible-bands", 7),
        ("baseline", "Imported APO: HD 650"),
        "presets",
        "sync",
        "notify",
    ]


def test_import_apo_preset_path_uses_autoeq_name_and_reveals_utility_pane() -> None:
    calls: list[object] = []
    utility_button = FakeUtilityPaneButton(visible=True)
    fake_window = SimpleNamespace(
        controller=SimpleNamespace(
            import_apo_preset=lambda path: calls.append(("import", path)) or 10,
            state_signature=lambda: "imported-signature",
            build_preset_payload=lambda label: {"name": label},
        ),
        selected_band_index=3,
        current_preset_name="Studio Reference",
        saved_preset_signature="old-signature",
        output_preset_auto_applied=True,
        output_preset_curve_auto_loaded=True,
        utility_pane_button=utility_button,
        set_visible_band_count=lambda count: calls.append(("visible-bands", count)),
        set_curve_revert_baseline=lambda label: calls.append(("baseline", label)),
        refresh_preset_list=lambda: calls.append("presets"),
        sync_ui_from_state=lambda: calls.append("sync"),
        notify_control_state_changed=lambda: calls.append("notify"),
    )

    count = window.MiniEqWindow.import_apo_preset_path(
        fake_window,
        "/tmp/Example Reference Headphone ParametricEQ.txt",
        imported_name="Example Reference Headphone",
    )

    assert count == 10
    assert fake_window.selected_band_index is None
    assert fake_window.current_preset_name is None
    assert fake_window.saved_preset_signature == "imported-signature"
    assert fake_window.output_preset_auto_applied is False
    assert fake_window.output_preset_curve_auto_loaded is False
    assert utility_button.active is True
    assert calls == [
        ("import", "/tmp/Example Reference Headphone ParametricEQ.txt"),
        ("visible-bands", 10),
        ("baseline", "Imported APO: Example Reference Headphone"),
        "presets",
        "sync",
        "notify",
    ]


def test_on_bypass_changed_resets_switch_when_engine_update_fails() -> None:
    calls: list[object] = []
    bypass_switch = FakeSwitch(False)

    def fail_enabled(_enabled: bool) -> None:
        raise RuntimeError("control update failed")

    fake_window = SimpleNamespace(
        updating_ui=False,
        controller=SimpleNamespace(eq_enabled=True, set_eq_enabled=fail_enabled),
        route_switch=FakeSwitch(False),
        bypass_switch=bypass_switch,
        update_eq_power_indicator=lambda: calls.append("power"),
        update_info_label=lambda: calls.append("info"),
        update_status_summary=lambda: calls.append("summary"),
        invalidate_graph_response_cache=lambda: calls.append("invalidate"),
        queue_graph_draw=lambda: calls.append("draw"),
        update_preset_state=lambda: calls.append("preset-state"),
        set_status=lambda message: calls.append(("status", message)),
        notify_control_state_changed=lambda: calls.append("notify"),
    )
    bind_control_refresh_methods(fake_window)

    handled = window.MiniEqWindow.on_bypass_changed(fake_window, bypass_switch, None)

    assert handled is True
    assert bypass_switch.get_active() is True
    assert bypass_switch.get_state() is True
    assert fake_window.updating_ui is False
    assert calls == ["power", ("status", "control update failed")]
