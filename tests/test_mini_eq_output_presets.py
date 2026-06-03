from __future__ import annotations

import json
from types import SimpleNamespace

from tests._mini_eq_imports import core, import_mini_eq_module, routing

diagnostics = import_mini_eq_module("diagnostics")
window = import_mini_eq_module("window")
window_presets = import_mini_eq_module("window_presets")


class FakeButton:
    def __init__(self) -> None:
        self.sensitive = True
        self.tooltip = ""
        self.visible = True
        self.label = ""

    def set_sensitive(self, sensitive: bool) -> None:
        self.sensitive = sensitive

    def set_tooltip_text(self, text: str) -> None:
        self.tooltip = text

    def set_visible(self, visible: bool) -> None:
        self.visible = visible

    def set_label(self, text: str) -> None:
        self.label = text


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


class FakeOutputTransitionController(SimpleNamespace):
    def __init__(
        self,
        *,
        output_sink: str,
        observed_identity: str | None,
        current_identity: str,
        follow_default_output: bool = True,
    ) -> None:
        super().__init__(
            output_sink=output_sink,
            follow_default_output=follow_default_output,
            get_default_output_sink_name=lambda: output_sink,
            get_sink=lambda _sink_name: None,
        )
        self.observed_identity = observed_identity
        self.current_identity = current_identity
        self.transition_consumes: list[bool] = []

    def output_preset_target_transition(self, *, consume: bool = True) -> SimpleNamespace:
        self.transition_consumes.append(consume)
        changed = self.observed_identity is not None and self.observed_identity != self.current_identity
        if consume or self.observed_identity is None:
            self.observed_identity = self.current_identity
        return SimpleNamespace(changed=changed)


class FakeDeleteDialog:
    def __init__(self, response: str = "delete") -> None:
        self.response = response

    def choose_finish(self, _result: object) -> str:
        return self.response


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


class OutputPresetWindow(window_presets.MiniEqWindowPresetMixin):
    def __init__(self, controller) -> None:
        self.controller = controller
        self.current_preset_name: str | None = None
        self.saved_preset_signature = controller.state_signature()
        self.default_preset_signature = controller.default_state_signature()
        self.output_preset_auto_applied = False
        self.output_preset_curve_auto_loaded = False
        self.updating_output_preset_switch = False
        self.fallback_preset_row_visible = False
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
        self.replace_confirmations: list[SimpleNamespace] = []
        self.preset_state_label = FakeLabel()
        self.current_curve_state_label = FakeLabel()
        self.current_curve_row = FakeButton()
        self.output_scope_state_label = FakeLabel()
        self.output_preset_state_label = FakeLabel()
        self.output_preset_scope_label = FakeLabel()
        self.preset_delete_button = FakeButton()
        self.preset_export_button = FakeButton()
        self.preset_import_button = FakeButton()
        self.preset_revert_button = FakeButton()
        self.preset_reset_to_neutral_button = FakeButton()
        self.preset_save_button = FakeButton()
        self.preset_save_as_button = FakeButton()
        self.preset_default_separator = FakeButton()
        self.preset_file_separator = FakeButton()
        self.preset_library_separator = FakeButton()
        self.preset_default_heading = FakeButton()
        self.default_preset_set_button = FakeButton()
        self.default_preset_clear_button = FakeButton()
        self.default_preset_row = FakeButton()
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

    def confirm_preset_replacement(
        self,
        preset_name: str,
        body: str,
        replace_callback,
    ) -> None:
        self.replace_confirmations.append(
            SimpleNamespace(
                preset_name=preset_name,
                body=body,
                replace_callback=replace_callback,
            )
        )


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


class FakeSink:
    def __init__(
        self,
        *,
        node_name: str,
        node_description: str | None,
        properties: dict[str, str],
    ) -> None:
        self.node_name = node_name
        self.node_description = node_description
        self.properties = properties

    def property_value(self, key: str) -> str | None:
        return self.properties.get(key)


def test_output_dropdown_uses_device_first_labels() -> None:
    fake_window = SimpleNamespace(controller=SimpleNamespace(output_sink="alsa_output.fallback"))
    sink = FakeSink(
        node_name="alsa_output.hdmi",
        node_description="Audio interno Stereo digitale HDMI",
        properties={"device.description": "Audio interno"},
    )

    assert window.MiniEqWindow.output_display_name(fake_window, sink) == "Audio interno"
    assert window.MiniEqWindow.output_sink_detail_name(fake_window, sink, "Audio interno") == "Stereo digitale HDMI"


def test_output_dropdown_detail_preserves_nested_parentheses() -> None:
    fake_window = SimpleNamespace(controller=SimpleNamespace(output_sink="alsa_output.fallback"))
    sink = FakeSink(
        node_name="alsa_output.hdmi",
        node_description="Audio interno Stereo digitale (HDMI)",
        properties={"device.description": "Audio interno"},
    )

    assert window.MiniEqWindow.output_sink_detail_name(fake_window, sink, "Audio interno") == "Stereo digitale (HDMI)"


def test_output_dropdown_disambiguates_duplicate_device_labels() -> None:
    fake_window = SimpleNamespace(controller=SimpleNamespace(output_sink="alsa_output.fallback"))
    fake_window.output_display_name = lambda sink: window.MiniEqWindow.output_display_name(fake_window, sink)
    fake_window.output_sink_detail_name = lambda sink, label: window.MiniEqWindow.output_sink_detail_name(
        fake_window,
        sink,
        label,
    )
    fake_window.format_sample_spec = lambda _sink: "48 kHz stereo"
    fake_window.transport_label_for_sink = lambda _sink: "ALSA"
    sinks = [
        FakeSink(
            node_name="alsa_output.hdmi",
            node_description="Audio interno HDMI",
            properties={"device.description": "Audio interno"},
        ),
        FakeSink(
            node_name="alsa_output.speakers",
            node_description="Audio interno Speakers",
            properties={"device.description": "Audio interno"},
        ),
    ]

    assert window.MiniEqWindow.build_output_sink_labels(fake_window, sinks) == [
        "Audio interno (HDMI • 48 kHz stereo)",
        "Audio interno (Speakers • 48 kHz stereo)",
    ]


def test_revert_action_explains_missing_loaded_preset() -> None:
    controller = make_controller()
    controller.bands[0].gain_db = 2.0
    test_window = OutputPresetWindow(controller)
    test_window.clear_curve_revert_baseline()

    test_window.refresh_preset_actions()

    assert test_window.preset_revert_button.visible is False
    assert test_window.preset_revert_button.sensitive is False
    assert test_window.preset_reset_to_neutral_button.visible is True
    assert test_window.preset_save_button.label == "Save As…"
    assert test_window.preset_save_as_button.visible is False


def test_neutral_curve_uses_neutral_state_and_contextual_menu(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(core, "OUTPUT_PRESET_LINKS_PATH", tmp_path / "output-presets.json")
    controller = make_controller()
    test_window = OutputPresetWindow(controller)

    test_window.update_preset_state()

    assert test_window.preset_state_label.text == "Neutral"
    assert test_window.preset_state_label.tooltip == "Current curve is neutral"
    assert test_window.preset_state_label.classes == {"preset-state-neutral"}
    assert test_window.current_curve_row.visible is True
    assert test_window.current_curve_state_label.text == "Neutral"
    assert test_window.current_curve_state_label.tooltip == "Neutral curve."
    assert test_window.preset_save_button.label == "Save As…"
    assert test_window.preset_save_as_button.visible is False
    assert test_window.preset_revert_button.visible is False
    assert test_window.preset_reset_to_neutral_button.visible is False
    assert test_window.default_preset_row.visible is False
    assert test_window.default_preset_set_button.visible is False
    assert test_window.default_preset_clear_button.visible is False
    assert test_window.preset_default_heading.visible is False
    assert test_window.default_preset_state_label.text == "Bypass"
    assert test_window.default_preset_state_label.tooltip == "Unmatched outputs use no fallback preset."
    assert test_window.preset_default_separator.visible is False
    assert test_window.preset_file_separator.visible is False
    assert test_window.preset_delete_button.visible is False
    assert test_window.preset_export_button.label == "Export Current Curve…"


def test_revert_action_tracks_initial_neutral_baseline() -> None:
    controller = make_controller()
    test_window = OutputPresetWindow(controller)

    test_window.refresh_preset_actions()

    assert test_window.preset_revert_button.visible is False
    assert test_window.preset_revert_button.sensitive is False
    assert test_window.preset_reset_to_neutral_button.visible is False

    controller.bands[0].gain_db = 2.0
    test_window.refresh_preset_actions()

    assert test_window.preset_revert_button.visible is False
    assert test_window.preset_revert_button.sensitive is False
    assert test_window.preset_reset_to_neutral_button.visible is True
    assert test_window.preset_reset_to_neutral_button.sensitive is True


def test_reset_to_neutral_action_tracks_current_curve() -> None:
    controller = make_controller()
    test_window = OutputPresetWindow(controller)

    test_window.refresh_preset_actions()

    assert test_window.preset_reset_to_neutral_button.visible is False
    assert test_window.preset_reset_to_neutral_button.sensitive is False
    assert test_window.preset_reset_to_neutral_button.tooltip == "Curve is already neutral"

    controller.bands[0].gain_db = 2.0
    test_window.refresh_preset_actions()

    assert test_window.preset_revert_button.visible is False
    assert test_window.preset_revert_button.sensitive is False
    assert test_window.preset_reset_to_neutral_button.visible is True
    assert test_window.preset_reset_to_neutral_button.sensitive is True
    assert test_window.preset_reset_to_neutral_button.tooltip == "Reset all bands and preamp to neutral"

    test_window.on_preset_reset_to_neutral_clicked(FakeButton())

    assert test_window.current_preset_name is None
    assert controller.state_signature() == controller.default_state_signature()
    assert test_window.visible_band_count == core.DEFAULT_ACTIVE_BANDS
    assert test_window.output_preset_auto_applied is False
    assert test_window.output_preset_curve_auto_loaded is False
    assert test_window.statuses[-1] == "Reset to neutral"


def test_revert_action_updates_for_named_preset_changes() -> None:
    controller = make_controller()
    test_window = OutputPresetWindow(controller)
    test_window.current_preset_name = "Headphones"
    test_window.saved_preset_signature = controller.state_signature()

    test_window.refresh_preset_actions()

    assert test_window.preset_save_button.label == "Save"
    assert test_window.preset_save_as_button.visible is True
    assert test_window.preset_revert_button.visible is False
    assert test_window.preset_revert_button.sensitive is False
    assert test_window.default_preset_set_button.visible is True
    assert test_window.preset_default_heading.visible is True
    assert test_window.preset_export_button.label == "Export Preset…"
    assert test_window.preset_delete_button.visible is True

    controller.bands[0].gain_db = 2.0
    test_window.refresh_preset_actions()

    assert test_window.preset_revert_button.visible is True
    assert test_window.preset_revert_button.sensitive is True
    assert test_window.preset_revert_button.tooltip == "Revert to Headphones"
    assert test_window.preset_revert_button.label == "Revert to Headphones"
    assert test_window.preset_reset_to_neutral_button.visible is True


def test_reset_to_neutral_clears_loaded_preset_selection(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(core, "PRESET_STORAGE_DIR", tmp_path / "presets")
    write_test_preset("Headphones", 2.5)
    controller = make_controller()
    test_window = OutputPresetWindow(controller)
    test_window.refresh_preset_list()
    test_window.load_library_preset("Headphones")
    controller.bands[0].frequency = 80.0

    test_window.on_preset_reset_to_neutral_clicked(FakeButton())

    assert test_window.current_preset_name is None
    assert test_window.preset_combo.selected == window_presets.Gtk.INVALID_LIST_POSITION
    assert controller.state_signature() == controller.default_state_signature()
    assert test_window.current_curve_state_label.text == "Neutral"
    assert test_window.current_curve_state_label.tooltip == "Neutral. Load Headphones to restore."
    assert test_window.preset_save_button.label == "Save As…"
    assert test_window.preset_save_as_button.visible is False
    assert test_window.preset_revert_button.visible is False

    test_window.load_library_preset("Headphones")

    assert test_window.current_preset_name == "Headphones"
    assert test_window.preset_combo.selected == 0
    assert controller.bands[0].gain_db == 2.5
    assert test_window.statuses[-1] == "Preset loaded"


def test_reset_to_neutral_keeps_auto_preset_link_but_marks_it_unapplied(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(core, "PRESET_STORAGE_DIR", tmp_path / "presets")
    monkeypatch.setattr(core, "OUTPUT_PRESET_LINKS_PATH", tmp_path / "output-presets.json")
    write_test_preset("Headphones", 2.5)
    core.set_output_preset_link("alsa_output.headphones", "Headphones")
    controller = make_controller()
    test_window = OutputPresetWindow(controller)
    test_window.refresh_preset_list()
    test_window.load_library_preset("Headphones")

    test_window.on_preset_reset_to_neutral_clicked(FakeButton())

    assert core.get_output_preset_link("alsa_output.headphones") == "Headphones"
    assert test_window.current_preset_name is None
    assert test_window.output_preset_switch.active is True
    assert test_window.output_preset_state_label.text == "Linked"


def test_revert_action_tracks_unsaved_import_baseline() -> None:
    controller = make_controller()
    controller.bands[0].gain_db = 2.0
    test_window = OutputPresetWindow(controller)
    test_window.set_curve_revert_baseline("Imported APO Preset")

    test_window.refresh_preset_actions()

    assert test_window.preset_revert_button.visible is False
    assert test_window.preset_revert_button.sensitive is False
    assert test_window.preset_revert_button.tooltip == "No curve changes to revert"

    controller.bands[0].gain_db = 4.0
    test_window.update_preset_state()

    assert test_window.preset_state_label.text == "Modified"
    assert test_window.preset_revert_button.visible is True
    assert test_window.preset_revert_button.sensitive is True
    assert test_window.preset_revert_button.tooltip == "Revert to Imported APO Preset"

    test_window.on_preset_revert_clicked(FakeButton())
    test_window.update_preset_state()

    assert test_window.current_preset_name is None
    assert controller.bands[0].gain_db == 2.0
    assert test_window.preset_revert_button.sensitive is False
    assert test_window.statuses[-1] == "Curve restored"


def test_unsaved_apo_import_is_shown_as_current_curve(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(core, "PRESET_STORAGE_DIR", tmp_path / "presets")
    controller = make_controller()
    controller.bands[0].gain_db = 2.0
    test_window = OutputPresetWindow(controller)
    test_window.set_curve_revert_baseline("Imported APO: HD 650")

    test_window.refresh_preset_list()

    assert test_window.preset_model.items == []
    assert test_window.preset_combo.selected == window_presets.Gtk.INVALID_LIST_POSITION
    assert test_window.current_curve_row.visible is True
    assert test_window.current_curve_state_label.text == "Imported curve"
    assert test_window.current_curve_state_label.tooltip == "Imported from HD 650."
    assert test_window.suggested_save_as_name() == "HD 650"

    test_window.on_preset_selected(test_window.preset_combo, None)

    assert test_window.current_preset_name is None


def test_saved_preset_selection_ignores_current_curve_label(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(core, "PRESET_STORAGE_DIR", tmp_path / "presets")
    write_test_preset("Headphones", 4.0)
    controller = make_controller()
    controller.bands[0].gain_db = 2.0
    test_window = OutputPresetWindow(controller)
    test_window.set_curve_revert_baseline("Imported APO: HD 650")

    test_window.refresh_preset_list()

    assert test_window.preset_model.items == ["Headphones"]
    assert test_window.current_curve_state_label.text == "Imported curve"

    test_window.preset_combo.selected = 0
    test_window.on_preset_selected(test_window.preset_combo, None)

    assert test_window.current_preset_name == "Headphones"
    assert controller.bands[0].gain_db == 4.0

    controller.bands[0].gain_db = 5.0
    test_window.update_preset_state()

    assert test_window.preset_combo.selected == window_presets.Gtk.INVALID_LIST_POSITION
    assert test_window.preset_state_label.text == "Modified"
    assert test_window.current_curve_state_label.text == "Headphones"
    assert test_window.current_curve_state_label.tooltip == "Unsaved edits from Headphones."


def test_save_as_existing_preset_requires_replace_confirmation(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(core, "PRESET_STORAGE_DIR", tmp_path / "presets")
    write_test_preset("Headphones", 4.0)
    controller = make_controller()
    controller.bands[0].gain_db = 2.0
    test_window = OutputPresetWindow(controller)

    test_window.save_current_state_to_preset_as("Headphones")

    assert len(test_window.replace_confirmations) == 1
    confirmation = test_window.replace_confirmations[0]
    assert confirmation.preset_name == "Headphones"
    assert confirmation.body == "Headphones already exists. Replace it with the current curve?"
    assert core.load_mini_eq_preset_file(core.preset_path_for_name("Headphones"))["bands"][0]["gain_db"] == 4.0

    confirmation.replace_callback()

    assert test_window.current_preset_name == "Headphones"
    assert core.load_mini_eq_preset_file(core.preset_path_for_name("Headphones"))["bands"][0]["gain_db"] == 2.0


def test_save_as_current_preset_overwrites_without_replace_confirmation(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(core, "PRESET_STORAGE_DIR", tmp_path / "presets")
    write_test_preset("Headphones", 4.0)
    controller = make_controller()
    test_window = OutputPresetWindow(controller)
    test_window.load_library_preset("Headphones")
    controller.bands[0].gain_db = 2.0

    test_window.save_current_state_to_preset_as("Headphones")

    assert test_window.replace_confirmations == []
    assert core.load_mini_eq_preset_file(core.preset_path_for_name("Headphones"))["bands"][0]["gain_db"] == 2.0


def test_importing_existing_preset_requires_replace_confirmation(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(core, "PRESET_STORAGE_DIR", tmp_path / "presets")
    write_test_preset("Headphones", 4.0)
    import_controller = make_controller()
    import_controller.bands[0].gain_db = 6.0
    import_path = tmp_path / "headphones.json"
    core.write_mini_eq_preset_file(import_path, import_controller.build_preset_payload("Headphones"))
    controller = make_controller()
    test_window = OutputPresetWindow(controller)

    test_window.on_preset_import_done(FakeOpenDialog(str(import_path)), None)

    assert len(test_window.replace_confirmations) == 1
    confirmation = test_window.replace_confirmations[0]
    assert confirmation.preset_name == "Headphones"
    assert confirmation.body == "Headphones already exists. Replace it with the imported preset?"
    assert controller.bands[0].gain_db == 0.0
    assert core.load_mini_eq_preset_file(core.preset_path_for_name("Headphones"))["bands"][0]["gain_db"] == 4.0

    confirmation.replace_callback()

    assert test_window.current_preset_name == "Headphones"
    assert controller.bands[0].gain_db == 6.0
    assert core.load_mini_eq_preset_file(core.preset_path_for_name("Headphones"))["bands"][0]["gain_db"] == 6.0


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
    assert test_window.output_preset_state_label.text == "Applied"
    assert test_window.output_scope_state_label.text == "Output-wide"
    assert test_window.output_preset_switch.active is True


def test_output_preset_auto_load_trace_records_linked_decision(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv(diagnostics.STARTUP_TRACE_ENV, "1")
    trace_path = tmp_path / "state" / "mini-eq" / "startup-trace.log"
    monkeypatch.setattr(diagnostics, "startup_trace_path", lambda: trace_path)
    monkeypatch.setattr(core, "PRESET_STORAGE_DIR", tmp_path / "presets")
    monkeypatch.setattr(core, "OUTPUT_PRESET_LINKS_PATH", tmp_path / "output-presets.json")
    write_test_preset("Headphones", 2.5)
    core.set_output_preset_link("alsa_output.headphones", "Headphones")
    controller = make_controller()
    test_window = OutputPresetWindow(controller)

    assert test_window.apply_output_preset_for_current_output() is True

    events = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()]
    assert [event["event"] for event in events] == [
        "output-preset-apply-start",
        "output-preset-link-selected",
        "output-preset-linked-applied",
    ]
    assert events[0]["output_sink"] == "alsa_output.headphones"
    assert events[0]["target_keys"] == ["alsa_output.headphones"]
    assert events[1]["linked_preset"] == "Headphones"
    assert events[2]["current_preset_after"] == "Headphones"


def test_auto_apply_remembers_route_identity_for_followup_refresh(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(core, "PRESET_STORAGE_DIR", tmp_path / "presets")
    monkeypatch.setattr(core, "OUTPUT_PRESET_LINKS_PATH", tmp_path / "output-presets.json")
    write_test_preset("Headphones", 2.5)
    route_key = "pipewire-route:v1:device=alsa_card.test;route=analog-output-headphones;route-device=8"
    core.set_output_preset_link(route_key, "Headphones")
    controller = make_controller("alsa_output.internal")
    route = SimpleNamespace(
        description="Headphones",
        name="analog-output-headphones",
        output_preset_key=route_key,
    )
    target = SimpleNamespace(
        output_key=controller.output_sink,
        route=route,
        keys=(route_key, controller.output_sink),
        link_key=route_key,
        has_route_key=True,
    )
    controller.output_preset_target = lambda *, refresh=False: target
    test_window = OutputPresetWindow(controller)

    assert test_window.apply_output_preset_for_current_output() is True

    assert test_window.current_preset_name == "Headphones"
    assert test_window.output_preset_curve_auto_loaded is True
    assert controller._observed_output_preset_target_snapshot.sink_name == controller.output_sink
    assert controller._observed_output_preset_target_snapshot.identity == route_key

    output_wide_target = SimpleNamespace(
        output_key=controller.output_sink,
        route=None,
        keys=(controller.output_sink,),
        link_key=controller.output_sink,
        has_route_key=False,
    )
    controller.output_preset_target = lambda *, refresh=False: output_wide_target
    controller.follow_default_output = True
    test_window.ui_shutting_down = False
    test_window.startup_ready = True
    test_window.list_visible_output_sinks = lambda: []
    test_window.build_output_sink_labels = lambda _sinks: []
    test_window.follow_default_output_label = lambda: "Follow system output"
    test_window.output_sink_names = []
    test_window.output_sink_labels = []
    test_window.output_sink_model = FakeModel()
    test_window.output_combo = FakeCombo()
    test_window.update_info_label = lambda: None
    test_window.update_status_summary = lambda: None

    window.MiniEqWindow.refresh_output_sinks(test_window)

    assert test_window.current_preset_name is None
    assert controller.state_signature() == controller.default_state_signature()
    assert test_window.statuses[-1] == "Unmatched output bypassed"


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
    assert test_window.statuses[-1] == "Current curve kept"


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
    assert test_window.statuses[-1] == "Unmatched output bypassed"


def test_output_change_without_link_applies_fallback_preset(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(core, "PRESET_STORAGE_DIR", tmp_path / "presets")
    monkeypatch.setattr(core, "OUTPUT_PRESET_LINKS_PATH", tmp_path / "output-presets.json")
    write_test_preset("Neutral", -1.5)
    core.set_output_preset_fallback_name("Neutral")
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
    assert test_window.statuses[-1] == "Fallback preset applied"


def test_fallback_preset_loads_for_initial_unlinked_output(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(core, "PRESET_STORAGE_DIR", tmp_path / "presets")
    monkeypatch.setattr(core, "OUTPUT_PRESET_LINKS_PATH", tmp_path / "output-presets.json")
    write_test_preset("Neutral", -1.5)
    core.set_output_preset_fallback_name("Neutral")
    controller = make_controller("alsa_output.speakers")
    test_window = OutputPresetWindow(controller)

    assert test_window.apply_output_preset_for_current_output() is True

    assert test_window.current_preset_name == "Neutral"
    assert controller.bands[0].gain_db == -1.5
    assert test_window.statuses[-1] == "Fallback preset applied"


def test_auto_apply_uses_saved_route_device_link_when_route_key_is_missing(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(core, "PRESET_STORAGE_DIR", tmp_path / "presets")
    monkeypatch.setattr(core, "OUTPUT_PRESET_LINKS_PATH", tmp_path / "output-presets.json")
    speaker_route_key = (
        "pipewire-route:v1:device=alsa_card.usb-Generic_USB_Audio-00;route=%5BOut%5D%20Speaker;route-device=11"
    )
    write_test_preset("Speakers Profile", -1.5)
    write_test_preset("Headset Profile", 2.5)
    core.set_output_preset_link(speaker_route_key, "Speakers Profile")
    controller = make_controller("alsa_output.usb-Generic_USB_Audio-00.HiFi__Speaker__sink")
    target = SimpleNamespace(
        output_key=controller.output_sink,
        route=None,
        keys=(controller.output_sink,),
        link_key=controller.output_sink,
        has_route_key=False,
        device_name="alsa_card.usb-Generic_USB_Audio-00",
        route_device=11,
    )
    controller.output_preset_target = lambda *, refresh=False: target
    test_window = OutputPresetWindow(controller)
    test_window.refresh_preset_list()
    test_window.load_library_preset("Headset Profile")

    assert test_window.apply_output_preset_for_current_output() is True

    assert test_window.current_preset_name == "Speakers Profile"
    assert controller.bands[0].gain_db == -1.5
    assert test_window.output_preset_auto_applied is True
    assert test_window.output_preset_curve_auto_loaded is True
    assert test_window.statuses[-1] == "Auto preset applied"


def test_clear_output_preset_removes_recovered_route_device_link(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(core, "PRESET_STORAGE_DIR", tmp_path / "presets")
    monkeypatch.setattr(core, "OUTPUT_PRESET_LINKS_PATH", tmp_path / "output-presets.json")
    speaker_route_key = (
        "pipewire-route:v1:device=alsa_card.usb-Generic_USB_Audio-00;route=%5BOut%5D%20Speaker;route-device=11"
    )
    write_test_preset("Speakers Profile", -1.5)
    core.set_output_preset_link(speaker_route_key, "Speakers Profile")
    controller = make_controller("alsa_output.usb-Generic_USB_Audio-00.HiFi__Speaker__sink")
    target = SimpleNamespace(
        output_key=controller.output_sink,
        route=None,
        keys=(controller.output_sink,),
        link_key=controller.output_sink,
        has_route_key=False,
        device_name="alsa_card.usb-Generic_USB_Audio-00",
        route_device=11,
    )
    controller.output_preset_target = lambda *, refresh=False: target
    test_window = OutputPresetWindow(controller)

    test_window.on_clear_output_preset_link_clicked(FakeButton())

    assert core.get_output_preset_link(speaker_route_key) is None
    assert test_window.statuses[-1] == "Auto preset cleared"


def test_missing_fallback_preset_reports_unavailable(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(core, "PRESET_STORAGE_DIR", tmp_path / "presets")
    monkeypatch.setattr(core, "OUTPUT_PRESET_LINKS_PATH", tmp_path / "output-presets.json")
    core.set_output_preset_fallback_name("Missing")
    controller = make_controller("alsa_output.speakers")
    test_window = OutputPresetWindow(controller)

    assert test_window.apply_output_preset_for_current_output() is False

    assert test_window.default_preset_row.visible is True
    assert test_window.default_preset_state_label.text == "Missing"
    assert test_window.statuses[-1] == "Fallback preset unavailable"


def test_output_change_without_link_keeps_manual_preset(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(core, "PRESET_STORAGE_DIR", tmp_path / "presets")
    monkeypatch.setattr(core, "OUTPUT_PRESET_LINKS_PATH", tmp_path / "output-presets.json")
    write_test_preset("Neutral", -1.5)
    core.set_output_preset_fallback_name("Neutral")
    controller = make_controller("alsa_output.speakers")
    controller.bands[0].gain_db = 2.5
    test_window = OutputPresetWindow(controller)
    test_window.current_preset_name = "Manual"
    test_window.saved_preset_signature = controller.state_signature()

    assert test_window.apply_output_preset_for_current_output(announce_no_output_preset=True) is False

    assert test_window.current_preset_name == "Manual"
    assert controller.bands[0].gain_db == 2.5
    assert test_window.sync_count == 0
    assert test_window.statuses == []


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
    assert test_window.statuses[-1] == "Current curve kept"


def test_deleted_output_preset_link_is_left_clearable(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(core, "PRESET_STORAGE_DIR", tmp_path / "presets")
    monkeypatch.setattr(core, "OUTPUT_PRESET_LINKS_PATH", tmp_path / "output-presets.json")
    core.set_output_preset_link("alsa_output.headphones", "Missing")
    controller = make_controller()
    test_window = OutputPresetWindow(controller)

    assert test_window.apply_output_preset_for_current_output() is True

    assert core.get_output_preset_link("alsa_output.headphones") == "Missing"
    assert test_window.output_preset_state_label.text == "Missing"
    assert test_window.output_preset_state_label.visible is True
    assert test_window.output_preset_switch.active is True
    assert test_window.output_preset_switch.sensitive is True
    assert test_window.statuses[-1] == "Auto preset unavailable"


def test_output_preset_actions_link_and_clear_current_output(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(core, "PRESET_STORAGE_DIR", tmp_path / "presets")
    monkeypatch.setattr(core, "OUTPUT_PRESET_LINKS_PATH", tmp_path / "output-presets.json")
    write_test_preset("Headphones", 2.5)
    controller = make_controller()
    test_window = OutputPresetWindow(controller)
    test_window.load_library_preset("Headphones")

    test_window.on_use_preset_for_output_clicked(FakeButton())

    assert core.get_output_preset_link("alsa_output.headphones") == "Headphones"
    assert test_window.output_preset_state_label.text == "Applied"
    assert test_window.output_preset_scope_label.text == "Auto Preset"
    assert test_window.output_preset_switch.active is True

    test_window.output_preset_curve_auto_loaded = True
    test_window.on_clear_output_preset_link_clicked(FakeButton())

    assert core.get_output_preset_link("alsa_output.headphones") is None
    assert test_window.output_preset_curve_auto_loaded is False
    assert test_window.output_preset_state_label.text == ""
    assert test_window.output_preset_switch.active is False


def test_output_preset_actions_use_route_key_when_available(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(core, "PRESET_STORAGE_DIR", tmp_path / "presets")
    monkeypatch.setattr(core, "OUTPUT_PRESET_LINKS_PATH", tmp_path / "output-presets.json")
    write_test_preset("Headphones", 2.0)
    route_key = "pipewire-route:v1:device=alsa_card.test;route=analog-output-headphones;route-device=8"
    controller = make_controller()
    route = SimpleNamespace(
        description="Headphones",
        name="analog-output-headphones",
        output_preset_key=route_key,
    )
    target = SimpleNamespace(
        output_key=controller.output_sink,
        route=route,
        keys=(route_key, controller.output_sink),
        link_key=route_key,
        has_route_key=True,
    )
    controller.output_preset_target = lambda *, refresh=False: target
    controller.output_preset_keys = lambda: (route_key, controller.output_sink)
    controller.output_preset_link_key = lambda: route_key
    test_window = OutputPresetWindow(controller)
    test_window.load_library_preset("Headphones")

    test_window.on_use_preset_for_output_clicked(FakeButton())

    assert core.get_output_preset_link(route_key) == "Headphones"
    assert core.get_output_preset_link(controller.output_sink) is None
    assert test_window.output_scope_state_label.text == "Headphones"
    assert test_window.output_preset_scope_label.text == "Auto Preset"
    assert test_window.statuses[-1] == "Auto preset linked"

    core.set_output_preset_link(controller.output_sink, "Legacy Output")
    test_window.on_clear_output_preset_link_clicked(FakeButton())

    assert core.get_output_preset_link(route_key) is None
    assert core.get_output_preset_link(controller.output_sink) is None
    assert test_window.statuses[-1] == "Auto preset cleared"


def test_output_scope_state_follows_same_sink_route_change(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(core, "PRESET_STORAGE_DIR", tmp_path / "presets")
    monkeypatch.setattr(core, "OUTPUT_PRESET_LINKS_PATH", tmp_path / "output-presets.json")
    controller = make_controller("alsa_output.internal")
    route = SimpleNamespace(
        description="Headphones",
        name="analog-output-headphones",
        output_preset_key="pipewire-route:v1:device=alsa_card.test;route=analog-output-headphones;route-device=6",
    )

    def output_preset_target():
        return SimpleNamespace(
            output_key=controller.output_sink,
            route=route,
            keys=(route.output_preset_key, controller.output_sink),
            link_key=route.output_preset_key,
            has_route_key=True,
        )

    controller.output_preset_target = output_preset_target
    test_window = OutputPresetWindow(controller)

    test_window.update_output_preset_state()
    assert test_window.output_scope_state_label.text == "Headphones"

    route.description = "Speakers"
    route.name = "analog-output-speaker"
    route.output_preset_key = "pipewire-route:v1:device=alsa_card.test;route=analog-output-speaker;route-device=6"

    test_window.update_output_preset_state()
    assert test_window.output_scope_state_label.text == "Speakers"


def test_deleting_only_loaded_preset_keeps_curve_and_allows_neutral_reset(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(core, "PRESET_STORAGE_DIR", tmp_path / "presets")
    monkeypatch.setattr(core, "OUTPUT_PRESET_LINKS_PATH", tmp_path / "output-presets.json")
    write_test_preset("Headphones", 2.5)
    controller = make_controller()
    test_window = OutputPresetWindow(controller)
    test_window.refresh_preset_list()
    test_window.load_library_preset("Headphones")

    test_window.on_preset_delete_dialog_done(FakeDeleteDialog(), None, "Headphones")

    assert core.list_preset_names() == []
    assert test_window.preset_names == []
    assert test_window.current_preset_name is None
    assert controller.bands[0].gain_db == 2.5
    assert test_window.preset_state_label.text == "Unsaved"
    assert test_window.current_curve_row.visible is True
    assert test_window.current_curve_state_label.text == "Deleted preset copy"
    assert test_window.current_curve_state_label.tooltip == "Deleted preset: Headphones. Curve is kept."
    assert test_window.suggested_save_as_name() == "Headphones"
    assert test_window.preset_revert_button.visible is False
    assert test_window.preset_revert_button.sensitive is False
    assert test_window.preset_revert_button.tooltip == "No curve changes to revert"
    assert test_window.preset_reset_to_neutral_button.visible is True
    assert test_window.preset_reset_to_neutral_button.sensitive is True
    assert test_window.statuses[-1] == "Preset deleted; curve kept"

    test_window.on_preset_reset_to_neutral_clicked(FakeButton())

    assert controller.state_signature() == controller.default_state_signature()
    assert test_window.current_preset_name is None
    assert test_window.statuses[-1] == "Reset to neutral"


def test_deleting_modified_loaded_preset_keeps_revert_baseline(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(core, "PRESET_STORAGE_DIR", tmp_path / "presets")
    write_test_preset("Headphones", 2.5)
    controller = make_controller()
    test_window = OutputPresetWindow(controller)
    test_window.refresh_preset_list()
    test_window.load_library_preset("Headphones")
    controller.bands[0].gain_db = 4.0

    test_window.on_preset_delete_dialog_done(FakeDeleteDialog(), None, "Headphones")

    assert test_window.current_preset_name is None
    assert test_window.preset_state_label.text == "Modified"
    assert test_window.current_curve_state_label.text == "Deleted preset copy"
    assert test_window.preset_revert_button.visible is True

    test_window.on_preset_revert_clicked(FakeButton())

    assert test_window.current_preset_name is None
    assert controller.bands[0].gain_db == 2.5
    assert test_window.statuses[-1] == "Curve restored"


def test_external_loaded_preset_delete_keeps_reselectable_unsaved_copy(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(core, "PRESET_STORAGE_DIR", tmp_path / "presets")
    write_test_preset("Headphones", 2.5)
    controller = make_controller()
    test_window = OutputPresetWindow(controller)
    test_window.refresh_preset_list()
    test_window.load_library_preset("Headphones")

    core.delete_preset_file("Headphones")
    test_window.refresh_preset_list()

    assert test_window.preset_names == []
    assert test_window.preset_combo.selected == window_presets.Gtk.INVALID_LIST_POSITION
    assert test_window.current_preset_name is None
    assert test_window.preset_state_label.text == "Unsaved"
    assert test_window.current_curve_state_label.text == "Deleted preset copy"
    assert test_window.suggested_save_as_name() == "Headphones"
    assert test_window.preset_delete_button.visible is False


def test_external_modified_preset_delete_keeps_revert_baseline(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(core, "PRESET_STORAGE_DIR", tmp_path / "presets")
    write_test_preset("Headphones", 2.5)
    controller = make_controller()
    test_window = OutputPresetWindow(controller)
    test_window.refresh_preset_list()
    test_window.load_library_preset("Headphones")
    controller.bands[0].gain_db = 4.0

    core.delete_preset_file("Headphones")
    test_window.refresh_preset_list()

    assert test_window.current_preset_name is None
    assert test_window.preset_state_label.text == "Modified"
    assert test_window.current_curve_state_label.text == "Deleted preset copy"
    assert test_window.preset_revert_button.visible is True
    assert test_window.preset_revert_button.label == "Revert to Deleted preset copy"

    test_window.on_preset_revert_clicked(FakeButton())

    assert test_window.current_preset_name is None
    assert controller.bands[0].gain_db == 2.5
    assert test_window.statuses[-1] == "Curve restored"


def test_external_current_preset_overwrite_marks_curve_modified(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(core, "PRESET_STORAGE_DIR", tmp_path / "presets")
    write_test_preset("Headphones", 2.5)
    controller = make_controller()
    test_window = OutputPresetWindow(controller)
    test_window.refresh_preset_list()
    test_window.load_library_preset("Headphones")

    write_test_preset("Headphones", -3.0)
    test_window.refresh_preset_list()

    assert test_window.current_preset_name == "Headphones"
    assert controller.bands[0].gain_db == 2.5
    assert test_window.preset_state_label.text == "Modified"
    assert test_window.preset_revert_button.visible is False
    assert test_window.preset_combo.selected == window_presets.Gtk.INVALID_LIST_POSITION

    test_window.load_library_preset("Headphones")

    assert test_window.current_preset_name == "Headphones"
    assert controller.bands[0].gain_db == -3.0
    assert test_window.statuses[-1] == "Preset loaded"


def test_external_current_preset_corruption_keeps_curve_as_unsaved_copy(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(core, "PRESET_STORAGE_DIR", tmp_path / "presets")
    write_test_preset("Headphones", 2.5)
    controller = make_controller()
    test_window = OutputPresetWindow(controller)
    test_window.refresh_preset_list()
    test_window.load_library_preset("Headphones")

    core.preset_path_for_name("Headphones").write_text("{}", encoding="utf-8")
    test_window.refresh_preset_list()

    assert test_window.current_preset_name is None
    assert test_window.preset_combo.selected == window_presets.Gtk.INVALID_LIST_POSITION
    assert controller.bands[0].gain_db == 2.5
    assert test_window.current_curve_state_label.text == "Deleted preset copy"
    assert test_window.statuses[-1] == "Preset unavailable"


def test_fallback_preset_actions_set_and_clear(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(core, "PRESET_STORAGE_DIR", tmp_path / "presets")
    monkeypatch.setattr(core, "OUTPUT_PRESET_LINKS_PATH", tmp_path / "output-presets.json")
    write_test_preset("Headphones", 2.5)
    controller = make_controller()
    test_window = OutputPresetWindow(controller)
    test_window.refresh_preset_list()
    test_window.load_library_preset("Headphones")

    test_window.on_use_preset_as_fallback_clicked(FakeButton())

    assert core.get_output_preset_fallback_name() == "Headphones"
    assert test_window.output_preset_curve_auto_loaded is False
    assert test_window.default_preset_row.visible is True
    assert test_window.default_preset_state_label.text == "Headphones"
    assert test_window.default_preset_clear_button.sensitive is True
    assert test_window.statuses[-1] == "Fallback preset set"

    test_window.output_preset_curve_auto_loaded = True
    test_window.on_bypass_unmatched_outputs_clicked(FakeButton())

    assert core.get_output_preset_fallback_name() is None
    assert test_window.output_preset_curve_auto_loaded is False
    assert test_window.default_preset_row.visible is False
    assert test_window.default_preset_state_label.text == "Bypass"
    assert test_window.default_preset_clear_button.sensitive is False
    assert test_window.statuses[-1] == "Unmatched outputs bypassed"


def test_preset_pane_hides_empty_fallback_policy(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(core, "OUTPUT_PRESET_LINKS_PATH", tmp_path / "output-presets.json")
    controller = make_controller()
    test_window = OutputPresetWindow(controller)

    test_window.update_preset_state()

    assert test_window.default_preset_row.visible is False
    assert test_window.default_preset_state_label.text == "Bypass"


def test_preset_pane_keeps_configured_fallback_row(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(core, "PRESET_STORAGE_DIR", tmp_path / "presets")
    monkeypatch.setattr(core, "OUTPUT_PRESET_LINKS_PATH", tmp_path / "output-presets.json")
    write_test_preset("Speakers", -1.5)
    core.set_output_preset_fallback_name("Speakers")
    controller = make_controller()
    test_window = OutputPresetWindow(controller)
    test_window.refresh_preset_list()

    test_window.update_preset_state()

    assert test_window.default_preset_row.visible is True
    assert test_window.default_preset_state_label.text == "Speakers"


def test_output_preset_link_state_shows_different_selected_preset(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(core, "PRESET_STORAGE_DIR", tmp_path / "presets")
    monkeypatch.setattr(core, "OUTPUT_PRESET_LINKS_PATH", tmp_path / "output-presets.json")
    write_test_preset("Headphones", 2.5)
    controller = make_controller()
    test_window = OutputPresetWindow(controller)
    test_window.current_preset_name = "Speakers"
    core.set_output_preset_link("alsa_output.headphones", "Headphones")

    test_window.update_output_preset_state()

    assert test_window.output_preset_state_label.text == "Different"
    assert test_window.output_preset_state_label.visible is True
    assert test_window.output_preset_switch.active is True
    assert test_window.output_preset_switch.tooltip == "Clear auto preset for EQ output"


def test_output_preset_link_state_shows_modified_linked_preset(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(core, "PRESET_STORAGE_DIR", tmp_path / "presets")
    monkeypatch.setattr(core, "OUTPUT_PRESET_LINKS_PATH", tmp_path / "output-presets.json")
    write_test_preset("Headphones", 2.5)
    core.set_output_preset_link("alsa_output.headphones", "Headphones")
    controller = make_controller()
    test_window = OutputPresetWindow(controller)
    test_window.load_library_preset("Headphones")
    controller.bands[0].gain_db = 4.0

    test_window.update_output_preset_state()

    assert test_window.output_preset_state_label.text == "Modified"
    assert test_window.output_preset_switch.active is True


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


def test_manual_output_change_defers_output_preset_handling_to_pipewire_refresh() -> None:
    calls: list[object] = []
    fake_window = SimpleNamespace(
        updating_output_combo=False,
        output_preset_auto_applied=True,
        output_preset_curve_auto_loaded=True,
        output_sink_names=[None, "alsa_output.headphones"],
        controller=SimpleNamespace(change_output_sink=lambda sink: calls.append(("change", sink))),
        refresh_output_sinks=lambda *, handle_observed_output_change=True: calls.append(
            ("refresh", handle_observed_output_change)
        ),
        apply_output_preset_for_current_output=lambda **kwargs: calls.append(("auto", kwargs)) or True,
        set_status=lambda message: calls.append(("status", message)),
    )

    window.MiniEqWindow.on_output_changed(fake_window, FakeCombo(selected=1), None)

    assert calls == [
        ("change", "alsa_output.headphones"),
        ("refresh", False),
    ]


def test_manual_output_change_to_follow_default_defers_output_preset_handling() -> None:
    calls: list[object] = []
    fake_window = SimpleNamespace(
        updating_output_combo=False,
        output_preset_auto_applied=True,
        output_preset_curve_auto_loaded=False,
        output_sink_names=[None, "alsa_output.headphones"],
        controller=SimpleNamespace(follow_system_default_output=lambda: calls.append("follow")),
        refresh_output_sinks=lambda *, handle_observed_output_change=True: calls.append(
            ("refresh", handle_observed_output_change)
        ),
        apply_output_preset_for_current_output=lambda **kwargs: calls.append(("auto", kwargs)) or True,
        set_status=lambda message: calls.append(("status", message)),
    )

    window.MiniEqWindow.on_output_changed(fake_window, FakeCombo(selected=0), None)

    assert calls == [
        "follow",
        ("refresh", False),
    ]


def test_pipewire_observed_output_change_runs_output_preset_handling() -> None:
    calls: list[object] = []
    fake_window = SimpleNamespace(
        ui_shutting_down=False,
        controller=FakeOutputTransitionController(
            output_sink="alsa_output.usb",
            observed_identity="alsa_output.speakers",
            current_identity="alsa_output.usb",
        ),
        output_preset_auto_applied=True,
        output_preset_curve_auto_loaded=True,
        startup_ready=True,
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
    assert fake_window.controller.observed_identity == "alsa_output.usb"
    assert fake_window.controller.transition_consumes == [True]


def test_pipewire_observed_port_scope_change_runs_output_preset_handling() -> None:
    calls: list[object] = []
    old_route_key = "pipewire-route:v1:device=alsa_card.test;route=analog-output-headphones;route-device=6"
    new_route_key = "pipewire-route:v1:device=alsa_card.test;route=analog-output-speaker;route-device=6"
    target = SimpleNamespace(
        link_key=new_route_key,
        keys=(new_route_key, "alsa_output.internal"),
    )
    fake_window = SimpleNamespace(
        ui_shutting_down=False,
        controller=FakeOutputTransitionController(
            output_sink="alsa_output.internal",
            observed_identity=old_route_key,
            current_identity=new_route_key,
        ),
        output_preset_auto_applied=True,
        output_preset_curve_auto_loaded=True,
        startup_ready=True,
        list_visible_output_sinks=lambda: [],
        build_output_sink_labels=lambda _sinks: [],
        follow_default_output_label=lambda: "Follow system output",
        output_sink_names=[],
        output_sink_labels=[],
        output_sink_model=FakeModel(),
        output_combo=FakeCombo(),
        updating_output_combo=False,
        output_preset_target=lambda: target,
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
    assert fake_window.controller.observed_identity == new_route_key
    assert fake_window.controller.transition_consumes == [True]


def test_manual_output_refresh_updates_selector_without_handling_observed_output_change() -> None:
    calls: list[object] = []
    fake_window = SimpleNamespace(
        ui_shutting_down=False,
        controller=FakeOutputTransitionController(
            output_sink="alsa_output.usb",
            observed_identity="alsa_output.speakers",
            current_identity="alsa_output.usb",
            follow_default_output=False,
        ),
        output_preset_auto_applied=True,
        output_preset_curve_auto_loaded=False,
        startup_ready=True,
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

    window.MiniEqWindow.refresh_output_sinks(
        fake_window,
        handle_observed_output_change=False,
    )

    assert calls == ["preset-state", "info", "summary"]
    assert fake_window.controller.observed_identity == "alsa_output.speakers"
    assert fake_window.controller.transition_consumes == [False]

    calls.clear()
    window.MiniEqWindow.refresh_output_sinks(fake_window)

    assert calls == [
        "preset-state",
        "info",
        "summary",
        ("auto", {"reset_auto_preset_without_link": False, "announce_no_output_preset": True}),
    ]
    assert fake_window.controller.observed_identity == "alsa_output.usb"
    assert fake_window.controller.transition_consumes == [False, True]


def test_missing_manual_output_stays_visible_in_selector() -> None:
    calls: list[object] = []
    visible_sink = SimpleNamespace(node_name="alsa_output.usb")
    fake_window = SimpleNamespace(
        ui_shutting_down=False,
        controller=FakeOutputTransitionController(
            output_sink="alsa_output.missing",
            observed_identity=None,
            current_identity="alsa_output.missing",
            follow_default_output=False,
        ),
        output_preset_auto_applied=False,
        output_preset_curve_auto_loaded=False,
        startup_ready=True,
        list_visible_output_sinks=lambda: [visible_sink],
        build_output_sink_labels=lambda _sinks: ["USB DAC"],
        follow_default_output_label=lambda: "Follow system output (USB DAC)",
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

    assert fake_window.output_sink_names == [None, "alsa_output.usb", "alsa_output.missing"]
    assert fake_window.output_sink_labels == ["Follow system output (USB DAC)", "USB DAC", "Unavailable output"]
    assert fake_window.output_combo.selected == 2
    assert calls == ["preset-state", "info", "summary"]
