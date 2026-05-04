from __future__ import annotations

import json

import pytest

from tests._mini_eq_imports import import_mini_eq_module

autoeq = import_mini_eq_module("autoeq")
window_autoeq = import_mini_eq_module("window_autoeq")


def make_entry(
    name: str = "Example",
    source: str = "Source",
    form: str = "in-ear",
    rig: str = "",
) -> autoeq.AutoEqEntry:
    return autoeq.AutoEqEntry(name=name, source=source, form=form, rig=rig)


def use_autoeq_cache(monkeypatch, tmp_path):
    cache_dir = tmp_path / "autoeq"
    (cache_dir / autoeq.AUTOEQ_PRESET_DIR).mkdir(parents=True)
    monkeypatch.setattr(autoeq, "autoeq_cache_dir", lambda: cache_dir)
    return cache_dir


def test_parse_autoeq_app_entries_deduplicates_profiles() -> None:
    text = json.dumps(
        {
            "Example": [
                {"source": "Source", "form": "in-ear"},
                {"source": "Source", "form": "in-ear"},
            ],
            "Other": [
                {"source": "Source", "form": "over-ear", "rig": "Rig"},
                {"source": "", "form": "over-ear"},
            ],
            "Broken": [None],
        }
    )

    assert autoeq.parse_autoeq_app_entries(text) == [
        make_entry(),
        make_entry(name="Other", form="over-ear", rig="Rig"),
    ]


def test_parse_autoeq_app_entries_rejects_changed_top_level_shape() -> None:
    with pytest.raises(RuntimeError, match="AutoEq profile list does not have the expected shape"):
        autoeq.parse_autoeq_app_entries("[]")


def test_search_autoeq_entries_matches_name_source_and_rig() -> None:
    entries = [
        make_entry(name="Example Reference Headphone", source="oratory1990", form="over-ear"),
        make_entry(name="Anker Soundcore", source="Other", form="over-ear"),
        make_entry(name="Sennheiser HD 650", source="Rtings", form="over-ear", rig="HATS"),
    ]

    assert autoeq.search_autoeq_entries(entries, "reference")[0].name == "Example Reference Headphone"
    assert autoeq.search_autoeq_entries(entries, "hd hats")[0].name == "Sennheiser HD 650"
    assert autoeq.search_autoeq_entries(entries, "missing") == []


def test_post_json_rejects_changed_response_shape(monkeypatch) -> None:
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def read(self) -> bytes:
            return b"[]"

    monkeypatch.setattr(autoeq, "urlopen", lambda _request, timeout: FakeResponse())

    with pytest.raises(RuntimeError, match="AutoEq response does not have the expected shape"):
        autoeq.post_json(autoeq.AUTOEQ_APP_EQUALIZE_URL, {})


def test_load_autoeq_entries_uses_cache_without_refresh(monkeypatch, tmp_path) -> None:
    cache_path = tmp_path / "entries.json"
    cache_path.write_text(json.dumps({"Cached": [{"source": "Source", "form": "in-ear"}]}), encoding="utf-8")
    monkeypatch.setattr(autoeq, "autoeq_entries_cache_path", lambda: cache_path)
    monkeypatch.setattr(autoeq, "fetch_text", lambda _url: (_ for _ in ()).throw(AssertionError("network used")))

    assert autoeq.load_autoeq_entries() == [make_entry(name="Cached")]


def test_autoeq_equalize_body_uses_preferred_target_bass_and_sample_rate() -> None:
    entry = make_entry(name="Example Reference Headphone", source="oratory1990", form="over-ear", rig="GRAS 45BC-10")
    targets = [
        {
            "label": "Harman over-ear 2018",
            "recommended": [{"source": "oratory1990", "form": "over-ear"}],
            "bassBoost": {"fc": 105, "q": 0.7, "gain": 6},
        }
    ]

    body = autoeq.autoeq_equalize_body(entry, targets)

    assert body["target"] == "Harman over-ear 2018"
    assert body["bass_boost_gain"] == 6.0
    assert body["fs"] == 48000
    assert body["name"] == "Example Reference Headphone"
    assert body["source"] == "oratory1990"
    assert body["rig"] == "GRAS 45BC-10"


def test_download_autoeq_preset_writes_equalizer_apo_text(monkeypatch, tmp_path) -> None:
    entry = make_entry()
    bodies: list[dict[str, object]] = []
    use_autoeq_cache(monkeypatch, tmp_path)

    monkeypatch.setattr(
        autoeq,
        "load_autoeq_targets_data",
        lambda *, refresh=False: [
            {
                "label": "Target",
                "recommended": [{"source": "Source", "form": "in-ear"}],
                "bassBoost": {"fc": 105, "q": 0.7, "gain": 6},
            }
        ],
    )

    def post_json(url: str, body: dict[str, object]) -> dict[str, object]:
        bodies.append(body)
        assert url == autoeq.AUTOEQ_APP_EQUALIZE_URL
        return {
            "parametric_eq": {
                "preamp": -4.62,
                "filters": [{"type": "LOW_SHELF", "fc": 105.0, "gain": 3.8, "q": 0.7}],
            }
        }

    monkeypatch.setattr(autoeq, "post_json", post_json)

    path = autoeq.download_autoeq_preset(entry)

    assert path.is_file()
    assert path.name.startswith("AutoEq-")
    assert path.read_text(encoding="utf-8") == (
        "# AutoEq target: Target\nPreamp: -4.62 dB\nFilter 1: ON LSC Fc 105.0 Hz Gain 3.8 dB Q 0.70\n"
    )
    assert bodies[0]["target"] == "Target"


def test_download_autoeq_app_preset_rejects_changed_preset_shape(monkeypatch) -> None:
    monkeypatch.setattr(autoeq, "load_autoeq_targets_data", lambda *, refresh=False: [])
    monkeypatch.setattr(autoeq, "post_json", lambda _url, _body: {"parametric_eq": {"filters": []}})

    with pytest.raises(RuntimeError, match="AutoEq response did not include a parametric EQ preset"):
        autoeq.download_autoeq_app_preset(make_entry())


def test_download_autoeq_preset_reuses_cached_file(monkeypatch, tmp_path) -> None:
    entry = make_entry()
    use_autoeq_cache(monkeypatch, tmp_path)
    path = autoeq.autoeq_download_path(entry)
    path.write_text("Preamp: -1.0 dB\nFilter 1: ON PK Fc 100 Hz Gain 1 dB Q 1\n", encoding="utf-8")
    monkeypatch.setattr(autoeq, "load_autoeq_targets_data", lambda *, refresh=False: [])
    monkeypatch.setattr(autoeq, "post_json", lambda _url, _body: (_ for _ in ()).throw(AssertionError("network used")))

    assert autoeq.download_autoeq_preset(entry) == path


def test_download_autoeq_preset_info_reads_cached_target_without_network(monkeypatch, tmp_path) -> None:
    entry = make_entry()
    use_autoeq_cache(monkeypatch, tmp_path)
    path = autoeq.autoeq_download_path(entry)
    path.write_text(
        "# AutoEq target: Target\nPreamp: -1.0 dB\nFilter 1: ON PK Fc 100 Hz Gain 1 dB Q 1\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(autoeq, "post_json", lambda _url, _body: (_ for _ in ()).throw(AssertionError("network used")))

    preset = autoeq.download_autoeq_preset_info(entry)

    assert preset.path == path
    assert preset.target_label == "Target"


def test_download_autoeq_preset_info_computes_target_for_older_cached_file(monkeypatch, tmp_path) -> None:
    entry = make_entry()
    use_autoeq_cache(monkeypatch, tmp_path)
    path = autoeq.autoeq_download_path(entry)
    path.write_text("Preamp: -1.0 dB\nFilter 1: ON PK Fc 100 Hz Gain 1 dB Q 1\n", encoding="utf-8")
    monkeypatch.setattr(
        autoeq,
        "load_autoeq_targets_data",
        lambda *, refresh=False: [
            {
                "label": "Target",
                "recommended": [{"source": "Source", "form": "in-ear"}],
                "bassBoost": {"fc": 105, "q": 0.7, "gain": 6},
            }
        ],
    )
    monkeypatch.setattr(autoeq, "post_json", lambda _url, _body: (_ for _ in ()).throw(AssertionError("network used")))

    preset = autoeq.download_autoeq_preset_info(entry)

    assert preset.path == path
    assert preset.target_label == "Target"


def test_download_autoeq_preset_info_keeps_older_cached_file_when_target_lookup_fails(monkeypatch, tmp_path) -> None:
    entry = make_entry()
    use_autoeq_cache(monkeypatch, tmp_path)
    path = autoeq.autoeq_download_path(entry)
    path.write_text("Preamp: -1.0 dB\nFilter 1: ON PK Fc 100 Hz Gain 1 dB Q 1\n", encoding="utf-8")
    monkeypatch.setattr(
        autoeq,
        "load_autoeq_targets_data",
        lambda *, refresh=False: (_ for _ in ()).throw(RuntimeError("could not download AutoEq data")),
    )
    monkeypatch.setattr(autoeq, "post_json", lambda _url, _body: (_ for _ in ()).throw(AssertionError("network used")))

    preset = autoeq.download_autoeq_preset_info(entry)

    assert preset.path == path
    assert preset.target_label == autoeq.AUTOEQ_UNKNOWN_TARGET_LABEL


class FakeLabel:
    def __init__(self) -> None:
        self.text = ""

    def set_text(self, text: str) -> None:
        self.text = text


class FakeArea:
    def __init__(self) -> None:
        self.draw_count = 0
        self.accessible_updates: list[tuple[list[object], list[str]]] = []

    def queue_draw(self) -> None:
        self.draw_count += 1

    def update_property(self, properties: list[object], values: list[str]) -> None:
        self.accessible_updates.append((properties, values))


class FakeButton:
    def __init__(self) -> None:
        self.sensitive = True
        self.focused = False
        self.text = ""

    def set_sensitive(self, sensitive: bool) -> None:
        self.sensitive = sensitive

    def grab_focus(self) -> None:
        self.focused = True

    def get_text(self) -> str:
        return self.text


class FakeSpinner(FakeButton):
    def __init__(self) -> None:
        super().__init__()
        self.visible = False
        self.started = False

    def set_visible(self, visible: bool) -> None:
        self.visible = visible

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.started = False


class FakeDialog:
    def __init__(self) -> None:
        self.can_close_history: list[bool] = []
        self.force_closed = False
        self.visible = True
        self.handlers: list[tuple[str, object]] = []

    def connect(self, signal_name: str, callback) -> int:
        self.handlers.append((signal_name, callback))
        return len(self.handlers)

    def get_visible(self) -> bool:
        return self.visible

    def set_can_close(self, can_close: bool) -> None:
        self.can_close_history.append(can_close)

    def force_close(self) -> None:
        self.force_closed = True
        self.visible = False


class FakeRow:
    def __init__(self, entry: autoeq.AutoEqEntry) -> None:
        self.autoeq_entry = entry


class FakePlaceholderRow:
    def __init__(self, message: str) -> None:
        self.message = message


class FakeActionRow:
    def __init__(self) -> None:
        self.title = ""
        self.subtitle = ""
        self.tooltip = ""
        self.title_lines = 0
        self.subtitle_lines = 0
        self.selectable = False
        self.activatable = False

    def set_title(self, title: str) -> None:
        self.title = title

    def set_title_lines(self, title_lines: int) -> None:
        self.title_lines = title_lines

    def set_subtitle(self, subtitle: str) -> None:
        self.subtitle = subtitle

    def set_subtitle_lines(self, subtitle_lines: int) -> None:
        self.subtitle_lines = subtitle_lines

    def set_tooltip_text(self, tooltip: str) -> None:
        self.tooltip = tooltip

    def set_selectable(self, selectable: bool) -> None:
        self.selectable = selectable

    def set_activatable(self, activatable: bool) -> None:
        self.activatable = activatable


class FakeResultsList(FakeButton):
    def __init__(self, row: FakeRow | None) -> None:
        super().__init__()
        self.row = row
        self.rows = []

    def get_selected_row(self) -> FakeRow | None:
        return self.row

    def get_sensitive(self) -> bool:
        return self.sensitive

    def get_row_at_index(self, index: int):
        return self.rows[index] if index < len(self.rows) else None

    def append(self, row) -> None:
        self.rows.append(row)

    def remove(self, row) -> None:
        self.rows.remove(row)


def cached_autoeq_import_window(tmp_path, entry: autoeq.AutoEqEntry):
    import_window = AutoEqImportWindow(entry)
    path = tmp_path / "example.txt"
    path.write_text("Preamp: -1 dB\nFilter 1: ON PK Fc 100 Hz Gain 1 dB Q 1\n", encoding="utf-8")
    import_window.autoeq_selected_entry = entry
    import_window.autoeq_preview_path = path
    import_window.autoeq_preview_target_label = "Target"
    return import_window, path


class AutoEqPreviewWindow(window_autoeq.MiniEqWindowAutoEqMixin):
    def __init__(self) -> None:
        self.autoeq_selected_entry = None
        self.autoeq_preview_path = None
        self.autoeq_preview_preamp_db = None
        self.autoeq_preview_target_label = None
        self.autoeq_preview_bands = []
        self.autoeq_preview_error = None
        self.autoeq_preview_loading = False
        self.autoeq_preview_source_id = 0
        self.autoeq_preview_request_id = 0
        self.autoeq_dialog_closed = False
        self.autoeq_preview_title = FakeLabel()
        self.autoeq_preview_count_label = FakeLabel()
        self.autoeq_preview_detail = FakeLabel()
        self.autoeq_preview_area = FakeArea()


class AutoEqImportWindow(window_autoeq.MiniEqWindowAutoEqMixin):
    def __init__(self, entry: autoeq.AutoEqEntry) -> None:
        self.autoeq_dialog = FakeDialog()
        self.autoeq_cancel_button = FakeButton()
        self.autoeq_status_label = FakeLabel()
        self.autoeq_spinner = FakeSpinner()
        self.autoeq_refresh_button = FakeButton()
        self.autoeq_search_entry = FakeButton()
        self.autoeq_results_list = FakeResultsList(FakeRow(entry))
        self.autoeq_import_button = FakeButton()
        self.autoeq_selected_entry = None
        self.autoeq_preview_path = None
        self.autoeq_entries: list[autoeq.AutoEqEntry] = []
        self.autoeq_profiles_request_id = 0
        self.autoeq_preview_title = FakeLabel()
        self.autoeq_preview_count_label = FakeLabel()
        self.autoeq_preview_detail = FakeLabel()
        self.autoeq_preview_area = FakeArea()
        self.autoeq_preview_preamp_db = None
        self.autoeq_preview_target_label = None
        self.autoeq_preview_bands = []
        self.autoeq_preview_error = None
        self.autoeq_preview_loading = False
        self.autoeq_preview_source_id = 0
        self.autoeq_preview_request_id = 0
        self.autoeq_import_in_progress = False
        self.autoeq_dialog_closed = False
        self.autoeq_import_request_id = 0
        self.imported: list[tuple[str, str | None]] = []
        self.statuses: list[str] = []
        self.placeholders: list[str] = []

    def import_apo_preset_path(self, path: str, *, imported_name: str | None = None) -> int:
        self.imported.append((path, imported_name))
        return 10

    def set_status(self, status: str) -> None:
        self.statuses.append(status)

    def show_autoeq_placeholder(self, message: str) -> None:
        self.placeholders.append(message)
        self.autoeq_results_list.append(FakePlaceholderRow(message))


def test_autoeq_result_row_escapes_markup_text(monkeypatch) -> None:
    entry = make_entry(
        name="crinacle - Bruel & Kjaer 4620",
        source="crinacle",
        form="over-ear",
        rig="Bruel & Kjaer 4620",
    )
    import_window = AutoEqImportWindow(entry)
    monkeypatch.setattr(window_autoeq.Adw, "ActionRow", FakeActionRow)

    row = import_window.make_autoeq_result_row(entry)

    assert row.title == "crinacle - Bruel &amp; Kjaer 4620"
    assert row.subtitle == "crinacle - Bruel &amp; Kjaer 4620"
    assert row.tooltip == "crinacle - Bruel & Kjaer 4620\ncrinacle - Bruel & Kjaer 4620"
    assert row.autoeq_entry is entry


def test_preview_selection_is_debounced_and_stale_requests_are_ignored(monkeypatch) -> None:
    scheduled: list[tuple[int, object, tuple[object, ...]]] = []
    removed: list[int] = []
    started: list[tuple[autoeq.AutoEqEntry, int | None]] = []
    first = make_entry(name="First")
    second = make_entry(name="Second")
    preview_window = AutoEqPreviewWindow()

    def timeout_add(delay_ms, callback, *args):
        scheduled.append((delay_ms, callback, args))
        return len(scheduled)

    def start_preview(self, entry, *, request_id=None):
        started.append((entry, request_id))

    monkeypatch.setattr(window_autoeq.GLib, "timeout_add", timeout_add)
    monkeypatch.setattr(window_autoeq, "destroy_glib_source", lambda source_id: removed.append(source_id))
    monkeypatch.setattr(window_autoeq.MiniEqWindowAutoEqMixin, "start_autoeq_preview_load", start_preview)

    preview_window.schedule_autoeq_preview_load(first)
    preview_window.schedule_autoeq_preview_load(second)

    assert removed == [1]
    assert preview_window.autoeq_selected_entry == second
    assert preview_window.autoeq_preview_count_label.text == "Preview"
    assert scheduled[0][0] == window_autoeq.AUTOEQ_PREVIEW_DEBOUNCE_MS

    assert scheduled[0][1](*scheduled[0][2]) is False
    assert started == []

    assert scheduled[1][1](*scheduled[1][2]) is False
    assert started == [(second, 2)]


def test_autoeq_dialog_focuses_search_entry() -> None:
    entry = make_entry()
    import_window = AutoEqImportWindow(entry)

    assert import_window.focus_autoeq_search_entry() is False

    assert import_window.autoeq_search_entry.focused is True


def test_finish_profiles_load_ignores_stale_request(monkeypatch) -> None:
    idle_calls: list[object] = []
    entry = make_entry()
    import_window = AutoEqImportWindow(entry)
    import_window.autoeq_profiles_request_id = 2

    monkeypatch.setattr(window_autoeq.GLib, "idle_add", lambda callback, *args: idle_calls.append((callback, args)))

    assert import_window.finish_autoeq_profiles_load(1, [entry], None) is False

    assert import_window.autoeq_entries == []
    assert import_window.autoeq_status_label.text == ""
    assert idle_calls == []


def test_cleanup_autoeq_dialog_invalidates_pending_work(monkeypatch) -> None:
    removed: list[int] = []
    entry = make_entry()
    import_window = AutoEqImportWindow(entry)
    import_window.autoeq_profiles_request_id = 3
    import_window.autoeq_import_request_id = 4
    import_window.autoeq_preview_request_id = 5
    import_window.autoeq_preview_source_id = 88
    import_window.autoeq_import_in_progress = True

    monkeypatch.setattr(window_autoeq, "destroy_glib_source", lambda source_id: removed.append(source_id))

    import_window.cleanup_autoeq_dialog()

    assert removed == [88]
    assert import_window.autoeq_dialog_closed is True
    assert import_window.autoeq_dialog is None
    assert import_window.autoeq_import_in_progress is False
    assert import_window.autoeq_preview_source_id == 0
    assert import_window.autoeq_profiles_request_id == 4
    assert import_window.autoeq_import_request_id == 5
    assert import_window.autoeq_preview_request_id == 6


def test_closed_dialog_signal_runs_autoeq_cleanup(monkeypatch) -> None:
    removed: list[int] = []
    entry = make_entry()
    import_window = AutoEqImportWindow(entry)
    dialog = import_window.autoeq_dialog
    import_window.autoeq_preview_source_id = 88

    monkeypatch.setattr(window_autoeq, "destroy_glib_source", lambda source_id: removed.append(source_id))

    import_window.on_autoeq_dialog_closed(dialog)

    assert removed == [88]
    assert import_window.autoeq_dialog_closed is True
    assert import_window.autoeq_dialog is None


def test_finish_profiles_load_ignores_closed_dialog(monkeypatch) -> None:
    idle_calls: list[object] = []
    entry = make_entry()
    import_window = AutoEqImportWindow(entry)
    import_window.autoeq_profiles_request_id = 1
    import_window.autoeq_dialog_closed = True

    monkeypatch.setattr(window_autoeq.GLib, "idle_add", lambda callback, *args: idle_calls.append((callback, args)))

    assert import_window.finish_autoeq_profiles_load(1, [entry], None) is False

    assert import_window.autoeq_entries == []
    assert import_window.autoeq_status_label.text == ""
    assert idle_calls == []


def test_finish_profiles_load_refocuses_search_after_success(monkeypatch) -> None:
    idle_calls: list[object] = []
    entry = make_entry()
    import_window = AutoEqImportWindow(entry)
    import_window.autoeq_profiles_request_id = 1

    def idle_add(callback, *args):
        idle_calls.append((callback, args))
        return len(idle_calls)

    monkeypatch.setattr(window_autoeq.GLib, "idle_add", idle_add)

    assert import_window.finish_autoeq_profiles_load(1, [entry], None) is False

    assert import_window.autoeq_entries == [entry]
    assert import_window.autoeq_status_label.text == "Search by headphone model"
    assert idle_calls == [(import_window.focus_autoeq_search_entry, ())]


def test_profiles_load_failure_stays_inside_dialog(monkeypatch) -> None:
    idle_calls: list[tuple[object, tuple[object, ...]]] = []
    entry = make_entry()
    import_window = AutoEqImportWindow(entry)

    class FakeThread:
        def __init__(self, target, *, daemon) -> None:
            self.target = target
            self.daemon = daemon

        def start(self) -> None:
            self.target()

    def idle_add(callback, *args):
        idle_calls.append((callback, args))
        return len(idle_calls)

    def load_autoeq_entries(*, refresh):
        raise RuntimeError("AutoEq profile list is not valid JSON")

    monkeypatch.setattr(window_autoeq.threading, "Thread", FakeThread)
    monkeypatch.setattr(window_autoeq.GLib, "idle_add", idle_add)
    monkeypatch.setattr(window_autoeq, "load_autoeq_entries", load_autoeq_entries)

    import_window.start_autoeq_profiles_load(refresh=True)
    assert idle_calls

    callback, args = idle_calls.pop(0)
    assert callback(*args) is False

    assert import_window.autoeq_entries == []
    assert import_window.autoeq_status_label.text == "AutoEq profile list is not valid JSON"
    assert import_window.autoeq_spinner.started is False
    assert import_window.autoeq_refresh_button.sensitive is True
    assert import_window.autoeq_dialog.force_closed is False


def test_search_entry_enter_imports_selected_profile_from_cache(tmp_path) -> None:
    entry = make_entry()
    import_window, path = cached_autoeq_import_window(tmp_path, entry)

    import_window.on_autoeq_search_entry_activated(import_window.autoeq_search_entry)

    assert import_window.imported == [(str(path), "Example")]
    assert import_window.autoeq_dialog.force_closed is True
    assert import_window.autoeq_import_request_id == 1


def test_results_enter_imports_selected_profile_from_cache(tmp_path) -> None:
    entry = make_entry()
    import_window, path = cached_autoeq_import_window(tmp_path, entry)

    handled = import_window.on_autoeq_results_key_pressed(
        None,
        window_autoeq.Gdk.KEY_Return,
        0,
        window_autoeq.Gdk.ModifierType(0),
    )

    assert handled is True
    assert import_window.imported == [(str(path), "Example")]
    assert import_window.autoeq_dialog.force_closed is True
    assert import_window.autoeq_import_request_id == 1


def test_results_non_enter_key_does_not_import(tmp_path) -> None:
    entry = make_entry()
    import_window, _path = cached_autoeq_import_window(tmp_path, entry)

    handled = import_window.on_autoeq_results_key_pressed(
        None,
        window_autoeq.Gdk.KEY_space,
        0,
        window_autoeq.Gdk.ModifierType(0),
    )

    assert handled is False
    assert import_window.imported == []


def test_preview_accessible_description_tracks_selection_and_result(monkeypatch) -> None:
    scheduled: list[tuple[int, object, tuple[object, ...]]] = []
    entry = make_entry(rig="Rig")
    preview_window = AutoEqPreviewWindow()
    preview_window.autoeq_dialog = FakeDialog()

    def timeout_add(delay_ms, callback, *args):
        scheduled.append((delay_ms, callback, args))
        return len(scheduled)

    monkeypatch.setattr(window_autoeq.GLib, "timeout_add", timeout_add)

    preview_window.clear_autoeq_preview()
    preview_window.schedule_autoeq_preview_load(entry)
    preview_window.finish_autoeq_preview_load(2, entry, "/tmp/example.txt", -1.5, [], "AutoEq in-ear", None)

    descriptions = [values[0] for _properties, values in preview_window.autoeq_preview_area.accessible_updates]
    assert descriptions == [
        "No AutoEq profile selected",
        "AutoEq curve preview for Example",
        "AutoEq curve preview for Example: 0 filters, preamp -1.5 dB, target AutoEq in-ear",
    ]
    assert preview_window.autoeq_preview_detail.text == "Target: AutoEq in-ear - Preamp -1.5 dB - Source - Rig"


def test_preview_success_enables_import_after_target_is_visible(tmp_path) -> None:
    entry = make_entry(rig="Rig")
    import_window = AutoEqImportWindow(entry)
    import_window.autoeq_selected_entry = entry
    import_window.autoeq_preview_request_id = 1
    import_window.autoeq_import_button.set_sensitive(False)
    path = tmp_path / "example.txt"
    path.write_text("Preamp: -1 dB\nFilter 1: ON PK Fc 100 Hz Gain 1 dB Q 1\n", encoding="utf-8")

    assert import_window.finish_autoeq_preview_load(1, entry, str(path), -1.5, [], "AutoEq in-ear", None) is False

    assert import_window.autoeq_preview_detail.text == "Target: AutoEq in-ear - Preamp -1.5 dB - Source - Rig"
    assert import_window.autoeq_import_button.sensitive is True


def test_preview_success_keeps_import_disabled_while_results_are_busy(tmp_path) -> None:
    entry = make_entry(rig="Rig")
    import_window = AutoEqImportWindow(entry)
    import_window.autoeq_selected_entry = entry
    import_window.autoeq_preview_request_id = 1
    import_window.autoeq_results_list.set_sensitive(False)
    path = tmp_path / "example.txt"
    path.write_text("Preamp: -1 dB\nFilter 1: ON PK Fc 100 Hz Gain 1 dB Q 1\n", encoding="utf-8")

    assert import_window.finish_autoeq_preview_load(1, entry, str(path), -1.5, [], "AutoEq in-ear", None) is False

    assert import_window.autoeq_preview_detail.text == "Target: AutoEq in-ear - Preamp -1.5 dB - Source - Rig"
    assert import_window.autoeq_import_button.sensitive is False


def test_preview_chart_scale_keeps_small_curves_readable() -> None:
    preview_window = AutoEqPreviewWindow()

    assert preview_window.autoeq_preview_db_limit([]) == 15.0
    assert preview_window.autoeq_preview_db_limit([2.0, -14.8]) == 15.0
    assert preview_window.autoeq_preview_db_limit([15.1]) == 20.0
    assert preview_window.autoeq_preview_db_limit([99.0]) == window_autoeq.GRAPH_DB_MAX


def test_preview_frequency_ticks_keep_import_preview_compact() -> None:
    assert window_autoeq.AUTOEQ_PREVIEW_MAJOR_FREQ_TICKS == (20.0, 100.0, 1000.0, 10000.0, 20000.0)
    assert window_autoeq.AUTOEQ_PREVIEW_MINOR_FREQ_TICKS == (50.0, 200.0, 500.0, 2000.0, 5000.0)
    assert window_autoeq.AUTOEQ_PREVIEW_FREQ_TICKS == (
        20.0,
        50.0,
        100.0,
        200.0,
        500.0,
        1000.0,
        2000.0,
        5000.0,
        10000.0,
        20000.0,
    )


def test_preview_generation_failure_stays_inside_dialog(monkeypatch) -> None:
    idle_calls: list[tuple[object, tuple[object, ...]]] = []
    entry = make_entry()
    preview_window = AutoEqPreviewWindow()
    preview_window.autoeq_dialog = FakeDialog()

    class FakeThread:
        def __init__(self, target, *, daemon) -> None:
            self.target = target
            self.daemon = daemon

        def start(self) -> None:
            self.target()

    def idle_add(callback, *args):
        idle_calls.append((callback, args))
        return len(idle_calls)

    def download_autoeq_preset_info(_entry):
        raise RuntimeError("AutoEq response format changed")

    monkeypatch.setattr(window_autoeq.threading, "Thread", FakeThread)
    monkeypatch.setattr(window_autoeq.GLib, "idle_add", idle_add)
    monkeypatch.setattr(window_autoeq, "download_autoeq_preset_info", download_autoeq_preset_info)

    preview_window.start_autoeq_preview_load(entry)
    assert idle_calls

    callback, args = idle_calls.pop(0)
    assert callback(*args) is False

    assert preview_window.autoeq_preview_error == "AutoEq response format changed"
    assert preview_window.autoeq_preview_count_label.text == "Unavailable"
    assert preview_window.autoeq_preview_detail.text == "AutoEq response format changed"
    assert preview_window.autoeq_preview_path is None


def test_import_waits_for_preview_target_before_applying(monkeypatch, tmp_path) -> None:
    started: list[object] = []
    entry = make_entry()
    import_window = AutoEqImportWindow(entry)
    path = tmp_path / "example.txt"
    path.write_text("Preamp: -1 dB\nFilter 1: ON PK Fc 100 Hz Gain 1 dB Q 1\n", encoding="utf-8")
    import_window.autoeq_selected_entry = entry
    import_window.autoeq_preview_path = path
    import_window.autoeq_preview_target_label = None

    class FakeThread:
        def __init__(self, target, *, daemon) -> None:
            self.target = target
            self.daemon = daemon

        def start(self) -> None:
            started.append(self.target)

    monkeypatch.setattr(window_autoeq.threading, "Thread", FakeThread)

    import_window.on_autoeq_import_clicked(FakeButton())

    assert started == []
    assert import_window.autoeq_import_in_progress is False


def test_import_applies_previewed_preset_without_downloading_again(monkeypatch, tmp_path) -> None:
    started: list[object] = []
    entry = make_entry()
    import_window = AutoEqImportWindow(entry)
    path = tmp_path / "example.txt"
    path.write_text("Preamp: -1 dB\nFilter 1: ON PK Fc 100 Hz Gain 1 dB Q 1\n", encoding="utf-8")
    import_window.autoeq_selected_entry = entry
    import_window.autoeq_preview_path = path
    import_window.autoeq_preview_target_label = "Target"

    class FakeThread:
        def __init__(self, target, *, daemon) -> None:
            self.target = target
            self.daemon = daemon

        def start(self) -> None:
            started.append(self.target)

    monkeypatch.setattr(window_autoeq.threading, "Thread", FakeThread)

    import_window.on_autoeq_import_clicked(FakeButton())

    assert started == []
    assert import_window.imported == [(str(path), "Example")]
    assert import_window.autoeq_dialog.force_closed is True


def test_successful_import_force_closes_dialog_after_applying_preset() -> None:
    entry = make_entry()
    import_window = AutoEqImportWindow(entry)
    import_window.set_autoeq_import_in_progress(True)
    import_window.autoeq_import_request_id = 1

    assert import_window.finish_autoeq_import(1, entry, "/tmp/example.txt", None) is False

    assert import_window.imported == [("/tmp/example.txt", "Example")]
    assert import_window.statuses == ["Imported AutoEq Preset: Example"]
    assert import_window.autoeq_import_in_progress is False
    assert import_window.autoeq_dialog.force_closed is True


def test_finish_import_ignores_stale_request() -> None:
    entry = make_entry()
    import_window = AutoEqImportWindow(entry)
    import_window.autoeq_import_request_id = 2

    assert import_window.finish_autoeq_import(1, entry, "/tmp/example.txt", None) is False

    assert import_window.imported == []
    assert import_window.statuses == []
    assert import_window.autoeq_dialog.force_closed is False


def test_finish_preview_ignores_closed_dialog() -> None:
    entry = make_entry()
    preview_window = AutoEqPreviewWindow()
    preview_window.autoeq_dialog = FakeDialog()
    preview_window.autoeq_dialog_closed = True
    preview_window.autoeq_selected_entry = entry
    preview_window.autoeq_preview_request_id = 1

    assert preview_window.finish_autoeq_preview_load(1, entry, "/tmp/example.txt", -1.0, [], "Target", None) is False

    assert preview_window.autoeq_preview_path is None
    assert preview_window.autoeq_preview_count_label.text == ""
