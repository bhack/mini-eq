from __future__ import annotations

from types import SimpleNamespace

from tests._mini_eq_imports import core, import_mini_eq_module, routing

window = import_mini_eq_module("window")
window_presets = import_mini_eq_module("window_presets")


class FakeButton:
    def __init__(self) -> None:
        self.sensitive = True
        self.tooltip = ""

    def set_sensitive(self, sensitive: bool) -> None:
        self.sensitive = sensitive

    def set_tooltip_text(self, text: str) -> None:
        self.tooltip = text


class FakeSwitch(FakeButton):
    def __init__(self) -> None:
        super().__init__()
        self.active = False
        self.state = False

    def get_active(self) -> bool:
        return self.active

    def set_active(self, active: bool) -> None:
        self.active = active

    def get_state(self) -> bool:
        return self.state

    def set_state(self, state: bool) -> None:
        self.state = state


class FakeLabel:
    def __init__(self) -> None:
        self.text = ""
        self.tooltip = ""
        self.visible = True
        self.classes: set[str] = set()

    def set_text(self, text: str) -> None:
        self.text = text

    def set_tooltip_text(self, text: str) -> None:
        self.tooltip = text

    def set_visible(self, visible: bool) -> None:
        self.visible = visible

    def add_css_class(self, name: str) -> None:
        self.classes.add(name)

    def remove_css_class(self, name: str) -> None:
        self.classes.discard(name)


class FakeModel:
    def __init__(self) -> None:
        self.items: list[str] = []

    def get_n_items(self) -> int:
        return len(self.items)

    def splice(self, position: int, removed: int, added: list[str]) -> None:
        self.items[position : position + removed] = added


class FakeCombo:
    def __init__(self, selected: int = 0) -> None:
        self.selected = selected
        self.sensitive = True

    def get_selected(self) -> int:
        return self.selected

    def set_selected(self, selected: int) -> None:
        self.selected = selected

    def set_sensitive(self, sensitive: bool) -> None:
        self.sensitive = sensitive


class OutputPresetWindow(window_presets.MiniEqWindowPresetMixin):
    def __init__(self, controller) -> None:
        self.controller = controller
        self.current_preset_name: str | None = None
        self.saved_preset_signature = controller.state_signature()
        self.default_preset_signature = controller.default_state_signature()
        self.output_preset_auto_applied = False
        self.output_preset_curve_auto_loaded = False
        self.updating_output_preset_switch = False
        self.selected_band_index = None
        self.visible_band_count = core.DEFAULT_ACTIVE_BANDS
        self.preset_names: list[str] = []
        self.preset_model = FakeModel()
        self.preset_combo = FakeCombo()
        self.updating_preset_combo = False
        self.statuses: list[str] = []
        self.sync_count = 0
        self.state_count = 0
        self.presets_count = 0
        self.preset_state_label = FakeLabel()
        self.output_preset_state_label = FakeLabel()
        self.preset_delete_button = FakeButton()
        self.preset_export_button = FakeButton()
        self.preset_import_button = FakeButton()
        self.preset_revert_button = FakeButton()
        self.preset_save_button = FakeButton()
        self.preset_save_as_button = FakeButton()
        self.default_preset_set_button = FakeButton()
        self.default_preset_clear_button = FakeButton()
        self.output_preset_switch = FakeSwitch()
        self.default_preset_state_label = FakeLabel()
        self.set_curve_revert_baseline("Neutral")

    def set_visible_band_count(self, count: int) -> None:
        self.visible_band_count = count

    def sync_ui_from_state(self) -> None:
        self.sync_count += 1

    def set_status(self, message: str) -> None:
        self.statuses.append(message)

    def notify_control_state_changed(self) -> None:
        self.state_count += 1

    def notify_control_presets_changed(self) -> None:
        self.presets_count += 1


def make_controller(output_sink: str = "alsa_output.headphones"):
    controller = routing.SystemWideEqController.__new__(routing.SystemWideEqController)
    controller.output_sink = output_sink
    controller.eq_enabled = True
    controller.eq_mode = 0
    controller.preamp_db = 0.0
    controller.default_bands = core.default_eq_bands()
    controller.bands = core.default_eq_bands()
    controller.apply_state_to_engine = lambda: None
    return controller


def write_test_preset(name: str, gain_db: float) -> None:
    controller = make_controller()
    controller.bands[0].gain_db = gain_db
    payload = routing.SystemWideEqController.build_preset_payload(controller, name)
    core.write_mini_eq_preset_file(core.preset_path_for_name(name), payload)


def test_revert_action_explains_missing_loaded_preset() -> None:
    controller = make_controller()
    controller.bands[0].gain_db = 2.0
    test_window = OutputPresetWindow(controller)
    test_window.clear_curve_revert_baseline()

    test_window.refresh_preset_actions()

    assert test_window.preset_revert_button.sensitive is False
    assert test_window.preset_revert_button.tooltip == "Load or import a preset first"


def test_revert_action_tracks_initial_neutral_baseline() -> None:
    controller = make_controller()
    test_window = OutputPresetWindow(controller)

    test_window.refresh_preset_actions()

    assert test_window.preset_revert_button.sensitive is False
    assert test_window.preset_revert_button.tooltip == "No curve changes to revert"

    controller.bands[0].gain_db = 2.0
    test_window.refresh_preset_actions()

    assert test_window.preset_revert_button.sensitive is True
    assert test_window.preset_revert_button.tooltip == "Revert to Neutral"


def test_revert_action_updates_for_named_preset_changes() -> None:
    controller = make_controller()
    test_window = OutputPresetWindow(controller)
    test_window.current_preset_name = "Headphones"
    test_window.saved_preset_signature = controller.state_signature()

    test_window.refresh_preset_actions()

    assert test_window.preset_revert_button.sensitive is False
    assert test_window.preset_revert_button.tooltip == "No curve changes to revert"

    controller.bands[0].gain_db = 2.0
    test_window.refresh_preset_actions()

    assert test_window.preset_revert_button.sensitive is True
    assert test_window.preset_revert_button.tooltip == "Revert to Headphones"


def test_revert_action_tracks_unsaved_import_baseline() -> None:
    controller = make_controller()
    controller.bands[0].gain_db = 2.0
    test_window = OutputPresetWindow(controller)
    test_window.set_curve_revert_baseline("Imported APO Preset")

    test_window.refresh_preset_actions()

    assert test_window.preset_revert_button.sensitive is False
    assert test_window.preset_revert_button.tooltip == "No curve changes to revert"

    controller.bands[0].gain_db = 4.0
    test_window.update_preset_state()

    assert test_window.preset_state_label.text == "Modified"
    assert test_window.preset_revert_button.sensitive is True
    assert test_window.preset_revert_button.tooltip == "Revert to Imported APO Preset"

    test_window.on_preset_revert_clicked(FakeButton())
    test_window.update_preset_state()

    assert test_window.current_preset_name is None
    assert controller.bands[0].gain_db == 2.0
    assert test_window.preset_revert_button.sensitive is False
    assert test_window.statuses[-1] == "Reverted to Imported APO Preset"


def test_initial_output_preset_auto_loads_linked_preset(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(core, "PRESET_STORAGE_DIR", tmp_path / "presets")
    monkeypatch.setattr(core, "OUTPUT_PRESET_LINKS_PATH", tmp_path / "output-presets.json")
    write_test_preset("Headphones", 2.5)
    core.set_output_preset_link("alsa_output.headphones", "Headphones")
    controller = make_controller()
    test_window = OutputPresetWindow(controller)

    assert test_window.apply_output_preset_for_current_output() is True

    assert test_window.current_preset_name == "Headphones"
    assert test_window.output_preset_auto_applied is True
    assert test_window.output_preset_curve_auto_loaded is True
    assert controller.bands[0].gain_db == 2.5
    assert test_window.output_preset_state_label.text == ""
    assert test_window.output_preset_switch.active is True


def test_output_preset_auto_apply_protects_unsaved_edits(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(core, "PRESET_STORAGE_DIR", tmp_path / "presets")
    monkeypatch.setattr(core, "OUTPUT_PRESET_LINKS_PATH", tmp_path / "output-presets.json")
    write_test_preset("Headphones", 2.5)
    core.set_output_preset_link("alsa_output.headphones", "Headphones")
    controller = make_controller()
    controller.bands[0].gain_db = -4.0
    test_window = OutputPresetWindow(controller)

    assert test_window.apply_output_preset_for_current_output() is True

    assert test_window.current_preset_name is None
    assert test_window.output_preset_auto_applied is False
    assert controller.bands[0].gain_db == -4.0
    assert test_window.statuses[-1] == "Kept Unsaved Changes"


def test_output_change_without_link_resets_previous_auto_preset(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(core, "PRESET_STORAGE_DIR", tmp_path / "presets")
    monkeypatch.setattr(core, "OUTPUT_PRESET_LINKS_PATH", tmp_path / "output-presets.json")
    controller = make_controller("alsa_output.speakers")
    controller.bands[0].gain_db = 2.5
    test_window = OutputPresetWindow(controller)
    test_window.current_preset_name = "Headphones"
    test_window.saved_preset_signature = controller.state_signature()
    test_window.visible_band_count = core.MAX_BANDS

    assert test_window.apply_output_preset_for_current_output(reset_auto_preset_without_link=True) is True

    assert test_window.current_preset_name is None
    assert controller.state_signature() == controller.default_state_signature()
    assert test_window.visible_band_count == core.DEFAULT_ACTIVE_BANDS
    assert test_window.output_preset_auto_applied is False
    assert test_window.output_preset_curve_auto_loaded is False
    assert test_window.sync_count == 1
    assert test_window.statuses[-1] == "Reset to Neutral"


def test_output_change_without_link_applies_default_preset(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(core, "PRESET_STORAGE_DIR", tmp_path / "presets")
    monkeypatch.setattr(core, "OUTPUT_PRESET_LINKS_PATH", tmp_path / "output-presets.json")
    write_test_preset("Neutral", -1.5)
    core.set_default_preset_name("Neutral")
    controller = make_controller("alsa_output.speakers")
    controller.bands[0].gain_db = 2.5
    test_window = OutputPresetWindow(controller)
    test_window.current_preset_name = "Headphones"
    test_window.saved_preset_signature = controller.state_signature()

    assert test_window.apply_output_preset_for_current_output(reset_auto_preset_without_link=True) is True

    assert test_window.current_preset_name == "Neutral"
    assert controller.bands[0].gain_db == -1.5
    assert test_window.output_preset_auto_applied is False
    assert test_window.output_preset_curve_auto_loaded is True
    assert test_window.statuses[-1] == "Applied Default Preset"


def test_default_preset_loads_for_initial_unlinked_output(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(core, "PRESET_STORAGE_DIR", tmp_path / "presets")
    monkeypatch.setattr(core, "OUTPUT_PRESET_LINKS_PATH", tmp_path / "output-presets.json")
    write_test_preset("Neutral", -1.5)
    core.set_default_preset_name("Neutral")
    controller = make_controller("alsa_output.speakers")
    test_window = OutputPresetWindow(controller)

    assert test_window.apply_output_preset_for_current_output() is True

    assert test_window.current_preset_name == "Neutral"
    assert controller.bands[0].gain_db == -1.5
    assert test_window.statuses[-1] == "Applied Default Preset"


def test_output_change_without_link_keeps_manual_preset(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(core, "PRESET_STORAGE_DIR", tmp_path / "presets")
    monkeypatch.setattr(core, "OUTPUT_PRESET_LINKS_PATH", tmp_path / "output-presets.json")
    write_test_preset("Neutral", -1.5)
    core.set_default_preset_name("Neutral")
    controller = make_controller("alsa_output.speakers")
    controller.bands[0].gain_db = 2.5
    test_window = OutputPresetWindow(controller)
    test_window.current_preset_name = "Manual"
    test_window.saved_preset_signature = controller.state_signature()

    assert test_window.apply_output_preset_for_current_output(announce_no_output_preset=True) is True

    assert test_window.current_preset_name == "Manual"
    assert controller.bands[0].gain_db == 2.5
    assert test_window.sync_count == 0
    assert test_window.statuses[-1] == "Kept Current Curve"


def test_output_change_without_link_keeps_unsaved_auto_preset_edits(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(core, "PRESET_STORAGE_DIR", tmp_path / "presets")
    monkeypatch.setattr(core, "OUTPUT_PRESET_LINKS_PATH", tmp_path / "output-presets.json")
    controller = make_controller("alsa_output.speakers")
    controller.bands[0].gain_db = 2.5
    test_window = OutputPresetWindow(controller)
    test_window.current_preset_name = "Headphones"
    test_window.saved_preset_signature = controller.state_signature()
    controller.bands[0].gain_db = 3.5

    assert (
        test_window.apply_output_preset_for_current_output(
            reset_auto_preset_without_link=True,
            announce_no_output_preset=True,
        )
        is True
    )

    assert test_window.current_preset_name == "Headphones"
    assert controller.bands[0].gain_db == 3.5
    assert test_window.sync_count == 0
    assert test_window.statuses[-1] == "Kept Unsaved Changes"


def test_deleted_output_preset_link_is_left_clearable(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(core, "PRESET_STORAGE_DIR", tmp_path / "presets")
    monkeypatch.setattr(core, "OUTPUT_PRESET_LINKS_PATH", tmp_path / "output-presets.json")
    core.set_output_preset_link("alsa_output.headphones", "Missing")
    controller = make_controller()
    test_window = OutputPresetWindow(controller)

    assert test_window.apply_output_preset_for_current_output() is True

    assert core.get_output_preset_link("alsa_output.headphones") == "Missing"
    assert test_window.output_preset_state_label.text == "Linked"
    assert test_window.output_preset_state_label.visible is True
    assert test_window.output_preset_switch.active is True
    assert test_window.output_preset_switch.sensitive is True
    assert test_window.statuses[-1] == "Output Preset Unavailable: Missing"


def test_output_preset_actions_link_and_clear_current_output(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(core, "PRESET_STORAGE_DIR", tmp_path / "presets")
    monkeypatch.setattr(core, "OUTPUT_PRESET_LINKS_PATH", tmp_path / "output-presets.json")
    controller = make_controller()
    test_window = OutputPresetWindow(controller)
    test_window.current_preset_name = "Headphones"

    test_window.on_use_preset_for_output_clicked(FakeButton())

    assert core.get_output_preset_link("alsa_output.headphones") == "Headphones"
    assert test_window.output_preset_state_label.text == ""
    assert test_window.output_preset_switch.active is True

    test_window.output_preset_curve_auto_loaded = True
    test_window.on_clear_output_preset_link_clicked(FakeButton())

    assert core.get_output_preset_link("alsa_output.headphones") is None
    assert test_window.output_preset_curve_auto_loaded is False
    assert test_window.output_preset_state_label.text == ""
    assert test_window.output_preset_switch.active is False


def test_default_preset_actions_set_and_clear(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(core, "PRESET_STORAGE_DIR", tmp_path / "presets")
    monkeypatch.setattr(core, "OUTPUT_PRESET_LINKS_PATH", tmp_path / "output-presets.json")
    write_test_preset("Headphones", 2.5)
    controller = make_controller()
    test_window = OutputPresetWindow(controller)
    test_window.refresh_preset_list()
    test_window.load_library_preset("Headphones")

    test_window.on_use_preset_as_default_clicked(FakeButton())

    assert core.get_default_preset_name() == "Headphones"
    assert test_window.output_preset_curve_auto_loaded is False
    assert test_window.default_preset_state_label.text == "Headphones"
    assert test_window.default_preset_clear_button.sensitive is True
    assert test_window.statuses[-1] == "Default Preset Set: Headphones"

    test_window.output_preset_curve_auto_loaded = True
    test_window.on_clear_default_preset_clicked(FakeButton())

    assert core.get_default_preset_name() is None
    assert test_window.output_preset_curve_auto_loaded is False
    assert test_window.default_preset_state_label.text == "None"
    assert test_window.default_preset_clear_button.sensitive is False
    assert test_window.statuses[-1] == "Cleared Default Preset: Headphones"


def test_output_preset_link_state_shows_different_selected_preset(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(core, "PRESET_STORAGE_DIR", tmp_path / "presets")
    monkeypatch.setattr(core, "OUTPUT_PRESET_LINKS_PATH", tmp_path / "output-presets.json")
    controller = make_controller()
    test_window = OutputPresetWindow(controller)
    test_window.current_preset_name = "Speakers"
    core.set_output_preset_link("alsa_output.headphones", "Headphones")

    test_window.update_output_preset_state()

    assert test_window.output_preset_state_label.text == "Different"
    assert test_window.output_preset_state_label.visible is True
    assert test_window.output_preset_switch.active is True
    assert test_window.output_preset_switch.tooltip == "Clear Output Preset"


def test_output_preset_link_toggle_clears_different_selected_preset(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(core, "PRESET_STORAGE_DIR", tmp_path / "presets")
    monkeypatch.setattr(core, "OUTPUT_PRESET_LINKS_PATH", tmp_path / "output-presets.json")
    controller = make_controller()
    test_window = OutputPresetWindow(controller)
    test_window.current_preset_name = "Speakers"
    core.set_output_preset_link("alsa_output.headphones", "Headphones")
    test_window.update_output_preset_state()

    test_window.output_preset_switch.set_active(False)
    handled = test_window.on_output_preset_switch_changed(test_window.output_preset_switch)

    assert handled is True
    assert core.get_output_preset_link("alsa_output.headphones") is None
    assert test_window.output_preset_switch.active is False
    assert test_window.output_preset_switch.state is False


def test_output_preset_link_toggle_links_and_clears_current_output(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(core, "PRESET_STORAGE_DIR", tmp_path / "presets")
    monkeypatch.setattr(core, "OUTPUT_PRESET_LINKS_PATH", tmp_path / "output-presets.json")
    controller = make_controller()
    test_window = OutputPresetWindow(controller)
    test_window.current_preset_name = "Headphones"

    test_window.output_preset_switch.set_active(True)
    handled = test_window.on_output_preset_switch_changed(test_window.output_preset_switch)

    assert handled is True
    assert core.get_output_preset_link("alsa_output.headphones") == "Headphones"
    assert test_window.output_preset_switch.state is True

    test_window.output_preset_switch.set_active(False)
    test_window.on_output_preset_switch_changed(test_window.output_preset_switch)

    assert core.get_output_preset_link("alsa_output.headphones") is None
    assert test_window.output_preset_switch.state is False


def test_manual_output_change_runs_output_preset_auto_apply() -> None:
    calls: list[object] = []
    fake_window = SimpleNamespace(
        updating_output_combo=False,
        output_preset_auto_applied=True,
        output_preset_curve_auto_loaded=True,
        output_sink_names=[None, "alsa_output.headphones"],
        controller=SimpleNamespace(change_output_sink=lambda sink: calls.append(("change", sink))),
        refresh_output_sinks=lambda *, auto_apply_output_preset=True: calls.append(
            ("refresh", auto_apply_output_preset)
        ),
        apply_output_preset_for_current_output=lambda **kwargs: calls.append(("auto", kwargs)) or True,
        set_status=lambda message: calls.append(("status", message)),
    )

    window.MiniEqWindow.on_output_changed(fake_window, FakeCombo(selected=1), None)

    assert calls == [
        ("change", "alsa_output.headphones"),
        ("refresh", False),
        ("auto", {"reset_auto_preset_without_link": True, "announce_no_output_preset": True}),
    ]


def test_manual_output_change_uses_auto_loaded_source_for_reset_decision() -> None:
    calls: list[object] = []
    fake_window = SimpleNamespace(
        updating_output_combo=False,
        output_preset_auto_applied=True,
        output_preset_curve_auto_loaded=False,
        output_sink_names=[None, "alsa_output.headphones"],
        controller=SimpleNamespace(change_output_sink=lambda sink: calls.append(("change", sink))),
        refresh_output_sinks=lambda *, auto_apply_output_preset=True: calls.append(
            ("refresh", auto_apply_output_preset)
        ),
        apply_output_preset_for_current_output=lambda **kwargs: calls.append(("auto", kwargs)) or True,
        set_status=lambda message: calls.append(("status", message)),
    )

    window.MiniEqWindow.on_output_changed(fake_window, FakeCombo(selected=1), None)

    assert calls == [
        ("change", "alsa_output.headphones"),
        ("refresh", False),
        ("auto", {"reset_auto_preset_without_link": False, "announce_no_output_preset": True}),
    ]


def test_system_default_output_change_runs_output_preset_auto_apply() -> None:
    calls: list[object] = []
    fake_window = SimpleNamespace(
        ui_shutting_down=False,
        controller=SimpleNamespace(
            output_sink="alsa_output.usb",
            follow_default_output=True,
            get_default_output_sink_name=lambda: "alsa_output.usb",
            get_sink=lambda _sink_name: None,
        ),
        last_output_preset_sink_name="alsa_output.speakers",
        output_preset_auto_applied=True,
        output_preset_curve_auto_loaded=True,
        post_present_ready=True,
        list_visible_output_sinks=lambda: [],
        build_output_sink_labels=lambda _sinks: [],
        follow_default_output_label=lambda: "Follow system output",
        output_sink_names=[],
        output_sink_labels=[],
        output_sink_model=FakeModel(),
        output_combo=FakeCombo(),
        updating_output_combo=False,
        update_preset_state=lambda: calls.append("preset-state"),
        update_info_label=lambda: calls.append("info"),
        update_status_summary=lambda: calls.append("summary"),
        apply_output_preset_for_current_output=lambda **kwargs: calls.append(("auto", kwargs)),
    )

    window.MiniEqWindow.refresh_output_sinks(fake_window)

    assert calls == [
        "preset-state",
        "info",
        "summary",
        ("auto", {"reset_auto_preset_without_link": True, "announce_no_output_preset": True}),
    ]
    assert fake_window.last_output_preset_sink_name == "alsa_output.usb"
