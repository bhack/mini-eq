from __future__ import annotations

import time

import gi

gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
gi.require_version("Gtk", "4.0")

from gi.repository import Adw, Gdk, Gio, GLib, GObject, Gtk

from .analyzer import (
    ANALYZER_BIN_COUNT,
    ANALYZER_DB_FLOOR,
    ANALYZER_DISPLAY_GAIN_DEFAULT,
    ANALYZER_DISPLAY_GAIN_MAX,
    ANALYZER_DISPLAY_GAIN_MIN,
)
from .appearance import (
    apply_appearance_preference,
    load_appearance_preference,
    normalize_appearance,
    save_appearance_preference,
)
from .band_fader import EqBandFader
from .core import (
    APP_NAME,
    DEFAULT_ACTIVE_BANDS,
    EQ_GAIN_MAX_DB,
    EQ_GAIN_MIN_DB,
    EQ_MODES,
    MODE_ORDER,
    SAMPLE_RATE,
    AudioBackendError,
    ensure_preset_storage_dir,
    estimate_response_peak_db,
)
from .diagnostics import describe_output_preset_transition, trace_startup_event
from .glib_utils import destroy_glib_source
from .gtk_utils import create_dropdown_from_strings
from .pipewire_backend import PipeWireBackendError, PipeWireNode, node_sample_rate, parse_positive_int
from .routing import SystemWideEqController
from .settings import load_monitor_enabled
from .window_analyzer import MiniEqWindowAnalyzerMixin
from .window_autoeq import MiniEqWindowAutoEqMixin, initialize_autoeq_window_state
from .window_graph import MiniEqWindowGraphMixin
from .window_headroom import MiniEqWindowHeadroomMixin, format_headroom_peak_db
from .window_layout import MiniEqWindowLayoutMixin
from .window_preferences import MiniEqWindowPreferencesMixin
from .window_presets import MiniEqWindowPresetMixin, imported_apo_curve_label, imported_apo_curve_label_for_name
from .window_state import bind_window_state
from .window_utility import MiniEqWindowUtilityPaneMixin
from .window_utils import requested_switch_state, set_switch_confirmed_state

TOAST_TIMEOUT_SECONDS = 2
MIN_WINDOW_WIDTH = 980
MIN_WINDOW_HEIGHT = 600
DEFAULT_WINDOW_WIDTH = 1360
DEFAULT_WINDOW_HEIGHT = 720
DEFAULT_WINDOW_SCREEN_MARGIN = 32
ROUTING_CLOSE_SETTLE_MS = 300
STARTUP_AUTO_ROUTE_RETRY_INTERVAL_SECONDS = 1
STARTUP_AUTO_ROUTE_RETRY_TIMEOUT_US = 30_000_000
TOAST_IGNORED_PREFIXES = (
    "filter-chain PipeWire EQ ready:",
    "filter-chain PipeWire EQ stopped",
    "restored ",
    "routed ",
    "system audio routed",
    "system audio routing disabled",
)
COMPACT_WARNING_TITLES = {
    "Selected output sink is unavailable.": "No Output",
    "Bluetooth output is in headset mode. Switch back to A2DP for full-band music playback.": "Headset",
}


def compact_warning_title(message: str) -> str:
    return COMPACT_WARNING_TITLES.get(message, message)


def fit_window_default_size_to_monitor(
    width: int,
    height: int,
    *,
    monitor_width: int,
    monitor_height: int,
    min_width: int = MIN_WINDOW_WIDTH,
    min_height: int = MIN_WINDOW_HEIGHT,
    margin: int = DEFAULT_WINDOW_SCREEN_MARGIN,
) -> tuple[int, int]:
    available_width = max(min_width, monitor_width - margin)
    available_height = max(min_height, monitor_height - margin)
    return (max(min_width, min(width, available_width)), max(min_height, min(height, available_height)))


def initial_window_default_size() -> tuple[int, int]:
    display = Gdk.Display.get_default()
    if display is None:
        return (DEFAULT_WINDOW_WIDTH, DEFAULT_WINDOW_HEIGHT)

    monitors = display.get_monitors()
    monitor = monitors.get_item(0) if monitors.get_n_items() > 0 else None
    if monitor is None:
        return (DEFAULT_WINDOW_WIDTH, DEFAULT_WINDOW_HEIGHT)

    geometry = monitor.get_geometry()
    return fit_window_default_size_to_monitor(
        DEFAULT_WINDOW_WIDTH,
        DEFAULT_WINDOW_HEIGHT,
        monitor_width=geometry.width,
        monitor_height=geometry.height,
    )


class MiniEqWindow(
    MiniEqWindowPresetMixin,
    MiniEqWindowAnalyzerMixin,
    MiniEqWindowAutoEqMixin,
    MiniEqWindowGraphMixin,
    MiniEqWindowHeadroomMixin,
    MiniEqWindowUtilityPaneMixin,
    MiniEqWindowPreferencesMixin,
    MiniEqWindowLayoutMixin,
    Adw.ApplicationWindow,
):
    def __init__(
        self,
        app: Adw.Application,
        controller: SystemWideEqController,
        auto_route: bool,
        initial_curve_label: str | None = None,
    ) -> None:
        super().__init__(application=app, title=APP_NAME)
        self.add_css_class("mini-eq-window")
        self.controller = controller
        self.auto_route_on_startup = auto_route
        self.startup_ready_source_id = 0
        self.startup_auto_route_source_id = 0
        self.startup_auto_route_deadline_us = 0
        self.startup_ready = False
        self.present_when_ready = True
        self.responsive_layout_source_id = 0
        self.responsive_layout_size = (0, 0)
        self.toast_overlay: Adw.ToastOverlay | None = None
        self.min_window_width = MIN_WINDOW_WIDTH
        self.compact_min_window_height = MIN_WINDOW_HEIGHT
        self.default_min_window_height = MIN_WINDOW_HEIGHT
        self.set_default_size(*initial_window_default_size())
        self.window_state_settings = bind_window_state(self)
        _default_width, default_height = self.get_default_size()
        self.initial_layout_height = default_height if default_height > 0 else DEFAULT_WINDOW_HEIGHT
        self.set_size_request(self.min_window_width, self.compact_min_window_height)
        self.updating_ui = False
        self.selected_band_index: int | None = 0
        self.visible_band_count = DEFAULT_ACTIVE_BANDS
        self.band_fader_boxes: list[Gtk.Box] = []
        self.band_fader_widgets: list[EqBandFader] = []
        self.output_sink_names: list[str | None] = []
        self.output_sink_labels: list[str] = []
        self.output_sink_model = Gtk.StringList.new([])
        self.preset_names: list[str] = []
        self.preset_model = Gtk.StringList.new([])
        self.updating_output_combo = False
        self.updating_preset_combo = False
        self.ui_shutting_down = False
        self.current_preset_name: str | None = None
        self.saved_preset_signature = self.controller.state_signature()
        self.default_preset_signature = self.controller.default_state_signature()
        self.curve_revert_baseline_label: str | None = None
        self.curve_revert_baseline_signature: str | None = None
        self.curve_revert_baseline_payload: dict[str, object] | None = None
        self.set_curve_revert_baseline(initial_curve_label or "Neutral")
        self.output_preset_auto_applied = False
        self.output_preset_curve_auto_loaded = False
        self.updating_output_preset_switch = False
        self.preset_monitor: Gio.FileMonitor | None = None
        self.preset_refresh_source_id = 0
        self.analyzer_enabled = load_monitor_enabled()
        self.analyzer_frozen = False
        self.analyzer_smoothing = 0.40
        self.analyzer_preview_source_id = 0
        self.analyzer_preview_uses_tick_callback = False
        self.analyzer_preview_last_tick_time = 0.0
        self.analyzer_levels = [0.0] * ANALYZER_BIN_COUNT
        self.analyzer_db_floor = ANALYZER_DB_FLOOR
        self.analyzer_display_gain_db = ANALYZER_DISPLAY_GAIN_DEFAULT
        self.analyzer_loudness_snapshot = None
        self.analyzer_session_max_shortterm_lufs: float | None = None
        self.analyzer_last_redraw_time = 0.0
        self.control_analyzer_last_emit_time = 0.0
        self.curve_metadata_refresh_source_id = 0
        self.engine_control_refresh_source_id = 0
        self.pending_engine_band_indexes: set[int] = set()
        self.graph_background_revision = 0
        self.graph_response_revision = 0
        self.graph_response_cache_key = None
        self.graph_response_cache_points: list[tuple[float, float]] = []
        self.graph_selected_response_cache_key = None
        self.graph_selected_response_cache_points: list[tuple[float, float]] = []
        self.analyzer_last_frame_time = time.monotonic()
        self.utility_pane_button: Gtk.ToggleButton | None = None
        self.utility_pane_binding: GObject.Binding | None = None
        initialize_autoeq_window_state(self)
        self.fallback_preset_row_visible = False
        self.default_preset_row: Gtk.Box | None = None
        self.preset_default_heading: Gtk.Label | None = None
        self.headroom_panel: Gtk.Box | None = None
        self.headroom_fix_button: Gtk.Button | None = None
        self.close_finish_source_id = 0
        self.appearance_preference = load_appearance_preference()
        self.appearance_action: Gio.SimpleAction | None = None
        self.appearance_root: Gtk.Widget | None = None
        self.style_manager = app.get_style_manager()
        self.style_dark_notify_handler_id = 0

        self.system_state_label = Gtk.Label(xalign=0.5)

        self.output_combo = Gtk.DropDown(model=self.output_sink_model)
        self.preset_combo = Gtk.DropDown(model=self.preset_model)
        self.default_preset_state_label = Gtk.Label(xalign=1.0)
        self.mode_combo = create_dropdown_from_strings(MODE_ORDER)
        self.mode_combo.set_sensitive(False)
        self.route_switch = Gtk.Switch()
        self.bypass_switch = Gtk.Switch()
        self.selected_band_gain_spin = Gtk.SpinButton.new_with_range(EQ_GAIN_MIN_DB, EQ_GAIN_MAX_DB, 0.1)
        self.analyzer_switch = Gtk.Switch()
        self.analyzer_freeze_switch = Gtk.Switch()
        self.analyzer_mode_combo = create_dropdown_from_strings(["Monitor"])
        self.analyzer_mode_combo.set_sensitive(False)
        self.analyzer_state_label = Gtk.Label(xalign=1.0)
        self.analyzer_summary_label = Gtk.Label(xalign=0.0)
        self.analyzer_loudness_value_label = Gtk.Label(label="--", xalign=1.0)
        self.analyzer_loudness_meter_area = Gtk.DrawingArea()
        self.analyzer_smoothing_label = Gtk.Label(xalign=1.0)
        self.analyzer_smoothing_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 15.0, 95.0, 1.0)
        self.analyzer_smoothing_scale.set_draw_value(False)
        self.analyzer_smoothing_scale.set_hexpand(True)
        self.analyzer_display_gain_label = Gtk.Label(xalign=1.0)
        self.analyzer_display_gain_scale = Gtk.Scale.new_with_range(
            Gtk.Orientation.HORIZONTAL,
            ANALYZER_DISPLAY_GAIN_MIN,
            ANALYZER_DISPLAY_GAIN_MAX,
            1.0,
        )
        self.analyzer_display_gain_scale.set_draw_value(False)
        self.analyzer_display_gain_scale.set_hexpand(True)
        self.preamp_label = Gtk.Label(label="0.0 dB")
        self.focus_label = Gtk.Label(xalign=0.0)
        self.band_count_label = Gtk.Label(xalign=1.0)
        self.inspector_summary_label = Gtk.Label(xalign=1.0)
        self.graph_title_label = Gtk.Label(xalign=0.0)
        self.graph_title_label.set_wrap(True)
        self.preset_state_label = Gtk.Label(xalign=1.0)
        self.output_scope_state_label = Gtk.Label(xalign=0.0)
        self.output_preset_state_label = Gtk.Label(xalign=0.0)
        self.output_preset_switch = Gtk.Switch()
        self.headroom_peak_db: float | None = None
        self.headroom_state_kind = "bypass"

        self.controller.set_status_callback(self.set_status)
        self.controller.set_analyzer_levels_callback(self.on_analyzer_levels)
        self.controller.set_analyzer_loudness_callback(self.on_analyzer_loudness)
        self.install_css()
        self.sync_appearance_css_class()
        self.build_window_content(auto_route)
        self.style_dark_notify_handler_id = self.style_manager.connect(
            "notify::dark", self.on_style_manager_dark_changed
        )
        self.controller.set_outputs_changed_callback(self.refresh_output_sinks)

    def do_size_allocate(self, width: int, height: int, baseline: int) -> None:
        Adw.ApplicationWindow.do_size_allocate(self, width, height, baseline)
        if self.ui_shutting_down or self.responsive_layout_size == (width, height):
            return
        self.responsive_layout_size = (width, height)
        if self.responsive_layout_source_id == 0:
            self.responsive_layout_source_id = GLib.idle_add(self.on_responsive_layout_idle)

    def on_responsive_layout_idle(self) -> bool:
        self.responsive_layout_source_id = 0
        if self.ui_shutting_down:
            return False
        sync_responsive_layout = getattr(self, "sync_responsive_layout_for_size", None)
        if sync_responsive_layout is not None:
            sync_responsive_layout(*self.responsive_layout_size)
        return False

    def schedule_startup_ready(self) -> None:
        if self.startup_ready or self.startup_ready_source_id != 0:
            return

        self.startup_ready_source_id = GLib.idle_add(self.on_startup_ready_idle)

    def on_startup_ready_idle(self) -> bool:
        self.startup_ready_source_id = 0

        if self.ui_shutting_down or self.startup_ready:
            return False

        controller = getattr(self, "controller", None)
        trace_startup_event(
            "startup-ready-begin",
            auto_route_on_startup=self.auto_route_on_startup,
            current_preset=getattr(self, "current_preset_name", None),
            output_preset_auto_applied=bool(getattr(self, "output_preset_auto_applied", False)),
            output_preset_curve_auto_loaded=bool(getattr(self, "output_preset_curve_auto_loaded", False)),
            output_sink=getattr(controller, "output_sink", None),
        )
        self.startup_ready = True
        self.start_preset_monitoring()
        initial_output_preset_applied = self.apply_output_preset_for_current_output()
        trace_startup_event(
            "startup-ready-initial-output-preset-done",
            applied=initial_output_preset_applied,
            current_preset=getattr(self, "current_preset_name", None),
            output_preset_auto_applied=bool(getattr(self, "output_preset_auto_applied", False)),
            output_preset_curve_auto_loaded=bool(getattr(self, "output_preset_curve_auto_loaded", False)),
            output_sink=getattr(controller, "output_sink", None),
        )

        if self.ui_shutting_down:
            return False

        self.start_analyzer_preview()
        if self.auto_route_on_startup:
            trace_startup_event(
                "startup-ready-auto-route-begin",
                current_preset=getattr(self, "current_preset_name", None),
                output_preset_auto_applied=bool(getattr(self, "output_preset_auto_applied", False)),
                output_preset_curve_auto_loaded=bool(getattr(self, "output_preset_curve_auto_loaded", False)),
                output_sink=getattr(controller, "output_sink", None),
            )
            self.apply_startup_auto_route()

        if not self.ui_shutting_down:
            if self.present_when_ready:
                application = self.get_application()
                prepare_startup_notification = getattr(application, "prepare_window_startup_notification", None)
                if callable(prepare_startup_notification):
                    prepare_startup_notification(self)
                self.set_visible(True)
                self.present()
        trace_startup_event(
            "startup-ready-complete",
            current_preset=getattr(self, "current_preset_name", None),
            output_preset_auto_applied=bool(getattr(self, "output_preset_auto_applied", False)),
            output_preset_curve_auto_loaded=bool(getattr(self, "output_preset_curve_auto_loaded", False)),
            output_sink=getattr(controller, "output_sink", None),
        )
        self.notify_control_state_changed()
        return False

    def schedule_startup_auto_route(self, *, retry: bool = False) -> None:
        if self.startup_auto_route_source_id != 0:
            return

        if retry:
            self.startup_auto_route_source_id = GLib.timeout_add_seconds(
                STARTUP_AUTO_ROUTE_RETRY_INTERVAL_SECONDS,
                self.on_startup_auto_route_idle,
            )
            return

        self.startup_auto_route_source_id = GLib.idle_add(self.on_startup_auto_route_idle)

    def is_startup_auto_route_retryable_error(self, exc: Exception) -> bool:
        if isinstance(exc, PipeWireBackendError | AudioBackendError):
            return True

        return str(exc) == "filter-chain PipeWire EQ is not ready"

    def schedule_startup_auto_route_retry_after_error(self, exc: Exception) -> bool:
        if (
            self.ui_shutting_down
            or not self.auto_route_on_startup
            or not self.is_startup_auto_route_retryable_error(exc)
        ):
            return False

        deadline_us = getattr(self, "startup_auto_route_deadline_us", 0)
        if deadline_us <= 0:
            deadline_us = GLib.get_monotonic_time() + STARTUP_AUTO_ROUTE_RETRY_TIMEOUT_US
            self.startup_auto_route_deadline_us = deadline_us
        if GLib.get_monotonic_time() >= deadline_us:
            return False

        self.schedule_startup_auto_route(retry=True)
        return True

    def apply_startup_auto_route(self) -> None:
        eq_was_enabled = self.controller.eq_enabled
        previous_output_preset_auto_loaded = bool(getattr(self, "output_preset_curve_auto_loaded", False))
        route_applied = False
        trace_startup_event(
            "startup-auto-route-start",
            current_preset=getattr(self, "current_preset_name", None),
            eq_enabled_before=eq_was_enabled,
            output_preset_auto_applied=bool(getattr(self, "output_preset_auto_applied", False)),
            output_preset_curve_auto_loaded=previous_output_preset_auto_loaded,
            output_sink=getattr(self.controller, "output_sink", None),
        )
        try:
            self.controller.route_system_audio(True)
        except Exception as exc:
            retry_scheduled = self.schedule_startup_auto_route_retry_after_error(exc)
            trace_startup_event(
                "startup-auto-route-error",
                current_preset=getattr(self, "current_preset_name", None),
                error=str(exc),
                output_sink=getattr(self.controller, "output_sink", None),
                retry_scheduled=retry_scheduled,
            )
            if not retry_scheduled:
                self.set_status(str(exc))
        else:
            route_applied = True
            self.startup_auto_route_deadline_us = 0
            trace_startup_event(
                "startup-auto-route-routed",
                current_preset=getattr(self, "current_preset_name", None),
                output_sink=getattr(self.controller, "output_sink", None),
            )
        if route_applied:
            target_transition = self.controller.output_preset_target_transition()
            trace_startup_event(
                "startup-auto-route-transition",
                current_preset=getattr(self, "current_preset_name", None),
                output_sink=getattr(self.controller, "output_sink", None),
                transition=describe_output_preset_transition(target_transition),
            )
            if target_transition.changed:
                applied = self.apply_output_preset_for_current_output(
                    reset_auto_preset_without_link=previous_output_preset_auto_loaded,
                    announce_no_output_preset=True,
                )
                trace_startup_event(
                    "startup-auto-route-reapply-done",
                    applied=applied,
                    current_preset=getattr(self, "current_preset_name", None),
                    output_preset_auto_applied=bool(getattr(self, "output_preset_auto_applied", False)),
                    output_preset_curve_auto_loaded=bool(getattr(self, "output_preset_curve_auto_loaded", False)),
                    output_sink=getattr(self.controller, "output_sink", None),
                )
            else:
                trace_startup_event(
                    "startup-auto-route-reapply-skipped",
                    current_preset=getattr(self, "current_preset_name", None),
                    output_sink=getattr(self.controller, "output_sink", None),
                )
        self.refresh_after_route_state_changed(eq_was_enabled=eq_was_enabled)

    def on_startup_auto_route_idle(self) -> bool:
        self.startup_auto_route_source_id = 0

        if self.ui_shutting_down or not self.auto_route_on_startup:
            return False

        self.apply_startup_auto_route()
        return False

    def prepare_for_shutdown(self) -> None:
        if self.ui_shutting_down:
            return

        self.ui_shutting_down = True
        self.controller.shutting_down = True
        if self.startup_ready_source_id > 0:
            destroy_glib_source(self.startup_ready_source_id)
            self.startup_ready_source_id = 0
        if self.startup_auto_route_source_id > 0:
            destroy_glib_source(self.startup_auto_route_source_id)
            self.startup_auto_route_source_id = 0
        if self.responsive_layout_source_id > 0:
            destroy_glib_source(self.responsive_layout_source_id)
            self.responsive_layout_source_id = 0
        if self.curve_metadata_refresh_source_id > 0:
            destroy_glib_source(self.curve_metadata_refresh_source_id)
            self.curve_metadata_refresh_source_id = 0
        if self.engine_control_refresh_source_id > 0:
            destroy_glib_source(self.engine_control_refresh_source_id)
            self.engine_control_refresh_source_id = 0
        if self.style_dark_notify_handler_id > 0:
            self.style_manager.disconnect(self.style_dark_notify_handler_id)
            self.style_dark_notify_handler_id = 0
        self.pending_engine_band_indexes.clear()
        self.controller.set_status_callback(None)
        self.controller.set_outputs_changed_callback(None)
        self.controller.set_analyzer_levels_callback(None)
        self.controller.set_analyzer_loudness_callback(None)
        self.stop_preset_monitoring()
        self.stop_analyzer_preview(stop_backend=False)

    def finish_close_request(self) -> bool:
        self.close_finish_source_id = 0
        application = self.get_application()
        if application is not None:
            application.quit()
        return False

    def queue_theme_sensitive_redraw(self) -> None:
        self.sync_appearance_css_class()
        self.invalidate_graph_background_cache()
        self.invalidate_graph_response_cache()
        self.queue_graph_draw()
        self.queue_analyzer_draw(force=True)
        for fader in self.band_fader_widgets:
            fader.queue_draw()
        if self.headroom_meter_area is not None:
            self.headroom_meter_area.queue_draw()

    def on_style_manager_dark_changed(self, _style_manager, _param: object) -> None:
        self.queue_theme_sensitive_redraw()

    def sync_appearance_css_class(self) -> None:
        targets = [self]
        if self.appearance_root is not None:
            targets.append(self.appearance_root)

        if self.style_manager.get_dark():
            for target in targets:
                target.add_css_class("mini-eq-dark")
                target.remove_css_class("mini-eq-light")
        else:
            for target in targets:
                target.add_css_class("mini-eq-light")
                target.remove_css_class("mini-eq-dark")

    def on_appearance_action_state_changed(
        self,
        action: Gio.SimpleAction,
        value: GLib.Variant | None,
    ) -> None:
        if value is None:
            return

        appearance = normalize_appearance(value.get_string())
        application = self.get_application()
        style_manager = application.get_style_manager() if application is not None else None
        self.appearance_preference = apply_appearance_preference(appearance, style_manager)
        save_appearance_preference(self.appearance_preference)
        action.set_state(GLib.Variant.new_string(self.appearance_preference))
        self.queue_theme_sensitive_redraw()

    def begin_close_request_shutdown(self, *, force_quit: bool = False) -> None:
        if self.ui_shutting_down or self.close_finish_source_id > 0:
            return

        application = self.get_application()
        background_mode = bool(getattr(application, "background_mode", False))
        if background_mode and not force_quit:
            self.set_visible(False)
            self.notify_control_state_changed()
            update_background_status = getattr(application, "update_background_status", None)
            if update_background_status is not None:
                update_background_status()
            return

        routed = self.is_system_routed()
        if routed:
            self.updating_ui = True
            try:
                set_switch_confirmed_state(self.route_switch, False)
            finally:
                self.updating_ui = False

            try:
                self.controller.route_system_audio(False, announce=False, refresh_output=False)
            except Exception:
                pass
            finally:
                self.update_info_label()
                self.update_status_summary()

        self.set_visible(False)
        self.prepare_for_shutdown()

        if routed:
            self.close_finish_source_id = GLib.timeout_add(ROUTING_CLOSE_SETTLE_MS, self.finish_close_request)
            return

        if application is not None:
            GLib.idle_add(application.quit)

    def set_status(self, message: str) -> None:
        if self.ui_shutting_down:
            return

        GLib.idle_add(self.on_status_idle, message)

    def on_status_idle(self, message: str) -> bool:
        if self.ui_shutting_down:
            return False

        if not self.startup_ready or message.startswith(TOAST_IGNORED_PREFIXES) or self.toast_overlay is None:
            return False

        toast = Adw.Toast.new(self.status_toast_title(message))
        toast.set_timeout(TOAST_TIMEOUT_SECONDS)
        self.toast_overlay.add_toast(toast)
        return False

    def status_toast_title(self, message: str) -> str:
        if not message:
            return ""

        return message[:1].upper() + message[1:]

    def notify_control_state_changed(self) -> None:
        app = self.get_application()
        callback = getattr(app, "emit_control_state_changed", None)
        if callback is not None:
            callback()

    def notify_control_presets_changed(self) -> None:
        app = self.get_application()
        callback = getattr(app, "emit_control_presets_changed", None)
        if callback is not None:
            callback()

    def sync_control_switches_from_controller(self, *, route: bool = True, eq: bool = True) -> None:
        self.updating_ui = True
        try:
            if route:
                set_switch_confirmed_state(self.route_switch, self.controller.routed)
            if eq:
                set_switch_confirmed_state(self.bypass_switch, self.controller.eq_enabled)
        finally:
            self.updating_ui = False

    def refresh_after_route_state_changed(
        self,
        *,
        eq_was_enabled: bool,
        announce_enabled: bool | None = None,
        notify: bool = True,
    ) -> None:
        self.sync_control_switches_from_controller()
        self.update_eq_power_indicator()
        self.update_info_label()
        self.update_status_summary()
        self.update_focus_summary()
        if not eq_was_enabled and self.controller.eq_enabled:
            self.invalidate_graph_response_cache()
            self.queue_graph_draw()
            self.update_preset_state()
        if announce_enabled is not None:
            self.set_status("System-wide EQ On" if announce_enabled else "System-wide EQ Off")
        if notify:
            self.notify_control_state_changed()

    def refresh_after_eq_state_changed(
        self,
        *,
        announce_enabled: bool | None = None,
        notify: bool = True,
    ) -> None:
        self.sync_control_switches_from_controller(route=False)
        self.update_eq_power_indicator()
        self.update_info_label()
        self.update_status_summary()
        self.invalidate_graph_response_cache()
        self.queue_graph_draw()
        self.update_preset_state()
        if announce_enabled is not None:
            self.set_status("Equalizer On" if announce_enabled else "Equalizer Off")
        if notify:
            self.notify_control_state_changed()

    def start_preset_monitoring(self) -> None:
        if self.preset_monitor is not None:
            return

        preset_dir = ensure_preset_storage_dir()
        preset_root = Gio.File.new_for_path(str(preset_dir))
        self.preset_monitor = preset_root.monitor_directory(Gio.FileMonitorFlags.NONE, None)
        self.preset_monitor.connect("changed", self.on_preset_dir_changed)

    def stop_preset_monitoring(self) -> None:
        if self.preset_refresh_source_id > 0:
            destroy_glib_source(self.preset_refresh_source_id)
            self.preset_refresh_source_id = 0

        if self.preset_monitor is not None:
            self.preset_monitor.cancel()
            self.preset_monitor = None

    def on_preset_dir_changed(
        self,
        monitor: Gio.FileMonitor,
        file: Gio.File,
        other_file: Gio.File | None,
        event_type: Gio.FileMonitorEvent,
    ) -> None:
        del monitor, file, other_file

        if self.ui_shutting_down:
            return

        interesting_events = {
            Gio.FileMonitorEvent.CREATED,
            Gio.FileMonitorEvent.DELETED,
            Gio.FileMonitorEvent.CHANGED,
            Gio.FileMonitorEvent.CHANGES_DONE_HINT,
        }
        for event_name in ("MOVED", "MOVED_IN", "MOVED_OUT"):
            event_value = getattr(Gio.FileMonitorEvent, event_name, None)
            if event_value is not None:
                interesting_events.add(event_value)

        if event_type not in interesting_events or self.preset_refresh_source_id != 0:
            return

        self.preset_refresh_source_id = GLib.idle_add(self.on_preset_dir_changed_idle)

    def on_preset_dir_changed_idle(self) -> bool:
        self.preset_refresh_source_id = 0

        if self.ui_shutting_down:
            return False

        self.refresh_preset_list()
        self.notify_control_presets_changed()
        self.notify_control_state_changed()
        return False

    def on_close_request(self, window: Gtk.Window) -> bool:
        del window

        if self.ui_shutting_down:
            return False

        self.begin_close_request_shutdown()
        return True

    def output_sink_info(self) -> PipeWireNode | None:
        return self.controller.get_sink(self.controller.output_sink)

    def format_sample_spec(self, sink: PipeWireNode | None) -> str:
        if sink is None:
            return "Unavailable"

        rate = node_sample_rate(sink)
        channels = parse_positive_int(sink.property_value("audio.channels"))

        channel_text = {1: "mono", 2: "stereo"}.get(channels, f"{channels} ch" if channels > 0 else "unknown channels")

        if rate > 0:
            return f"{rate / 1000.0:g} kHz {channel_text}"

        return channel_text

    def transport_label_for_sink(self, sink: PipeWireNode | None) -> str:
        if sink is None:
            return "Unavailable"

        api = sink.property_value("device.api")
        sink_name = (sink.node_name or "").lower()

        if api == "bluez5":
            return "Bluetooth"
        if "hdmi" in sink_name:
            return "HDMI"
        if "usb" in sink_name or sink.property_value("device.bus") == "usb":
            return "USB"
        if api == "alsa":
            return "ALSA"

        return api.upper() if api else "Audio output"

    def output_display_name(self, sink: PipeWireNode | None) -> str:
        if sink is None:
            return self.controller.output_sink

        return (
            sink.property_value("device.description")
            or sink.property_value("device.nick")
            or sink.property_value("device.name")
            or sink.node_description
            or sink.node_name
            or self.controller.output_sink
        )

    def output_sink_detail_name(self, sink: PipeWireNode | None, base_label: str) -> str:
        if sink is None:
            return "Unavailable"

        node_description = str(sink.node_description or "").strip()
        if node_description and node_description != base_label:
            detail = node_description
            if detail.casefold().startswith(base_label.casefold()):
                detail = detail[len(base_label) :].strip().lstrip("-:").strip()
                if (detail.startswith("(") and detail.endswith(")")) or (
                    detail.startswith("[") and detail.endswith("]")
                ):
                    detail = detail[1:-1].strip()
            if detail:
                return detail

        return self.transport_label_for_sink(sink)

    def list_visible_output_sinks(self) -> list[PipeWireNode]:
        return [
            sink
            for sink in self.controller.list_sinks()
            if sink.node_name is not None and self.controller.is_valid_output_sink(sink.node_name)
        ]

    def build_output_sink_labels(self, sinks: list[PipeWireNode]) -> list[str]:
        labels = [self.output_display_name(sink) for sink in sinks]
        counts: dict[str, int] = {}

        for label in labels:
            counts[label] = counts.get(label, 0) + 1

        resolved: list[str] = []
        for sink, label in zip(sinks, labels, strict=True):
            if counts[label] == 1:
                resolved.append(label)
                continue

            resolved.append(f"{label} ({self.output_sink_detail_name(sink, label)} • {self.format_sample_spec(sink)})")

        return resolved

    def follow_default_output_label(self) -> str:
        default_sink_name = self.controller.get_default_output_sink_name()
        default_sink = self.controller.get_sink(default_sink_name)
        if default_sink is None:
            return "Follow system output"

        return f"Follow system output ({self.output_display_name(default_sink)})"

    def profile_summary(self, sink: PipeWireNode | None) -> tuple[str, str, bool, list[str]]:
        if sink is None:
            return "No output", "The selected sink is not available.", True, ["Selected output sink is unavailable."]

        warnings: list[str] = []
        sample_text = self.format_sample_spec(sink)
        api = sink.property_value("device.api")
        profile = sink.property_value("api.bluez5.profile")

        if api == "bluez5":
            if profile == "a2dp-sink":
                return "Bluetooth A2DP", f"{sample_text} music profile", False, warnings

            if profile and "headset" in profile:
                warnings.append(
                    "Bluetooth output is in headset mode. Switch back to A2DP for full-band music playback."
                )
                return "Bluetooth headset", f"{sample_text} voice profile", True, warnings

            return "Bluetooth", f"{sample_text} | profile {profile or 'unknown'}", False, warnings

        return f"{self.transport_label_for_sink(sink)} output", sample_text, False, warnings

    def estimate_curve_peak_db(self) -> float:
        return estimate_response_peak_db(self.controller.bands, self.controller.preamp_db, SAMPLE_RATE)

    def update_status_summary(self) -> None:
        sink = self.output_sink_info()
        route_enabled = self.is_system_routed()

        warnings = self.profile_summary(sink)[3]
        headroom_needs_attention = False

        if not self.controller.eq_enabled:
            self.set_headroom_state(
                state="EQ off",
                peak_text="EQ off",
                detail="Curve is loaded but not applied.",
                peak_db=None,
                kind="bypass",
            )
        else:
            peak = self.estimate_curve_peak_db()
            if peak > 0.5:
                headroom_needs_attention = True
                self.set_headroom_state(
                    state="Clipping risk",
                    peak_text=format_headroom_peak_db(peak),
                    detail=f"Lower preamp by {peak + 1.0:.1f} dB.",
                    peak_db=peak,
                    kind="risk",
                )
            elif peak > -0.5:
                self.set_headroom_state(
                    state="Tight",
                    peak_text=format_headroom_peak_db(peak),
                    detail="Small boosts may clip.",
                    peak_db=peak,
                    kind="tight",
                )
            else:
                self.set_headroom_state(
                    state="Safe margin",
                    peak_text=format_headroom_peak_db(peak),
                    detail="Curve stays below 0 dBFS.",
                    peak_db=peak,
                    kind="safe",
                )

        self.system_state_label.remove_css_class("system-state-live")
        self.system_state_label.remove_css_class("system-state-warning")
        self.system_state_label.remove_css_class("system-state-bypass")
        self.system_state_label.remove_css_class("system-state-idle")
        self.system_state_label.set_tooltip_text(None)

        if not route_enabled:
            self.system_state_label.set_text("Not Applied")
            self.system_state_label.add_css_class("system-state-idle")
        elif not self.controller.eq_enabled:
            self.system_state_label.set_text("Original")
            self.system_state_label.add_css_class("system-state-bypass")
        elif warnings:
            self.system_state_label.set_text(compact_warning_title(warnings[0]))
            self.system_state_label.set_tooltip_text("\n".join(warnings))
            self.system_state_label.add_css_class("system-state-warning")
        elif headroom_needs_attention:
            self.system_state_label.set_text("Clipping")
            self.system_state_label.set_tooltip_text("Lower preamp to avoid clipping.")
            self.system_state_label.add_css_class("system-state-warning")
        elif route_enabled:
            self.system_state_label.set_text("Applied")
            self.system_state_label.add_css_class("system-state-live")
        else:
            self.system_state_label.set_text("Standby")
            self.system_state_label.add_css_class("system-state-idle")

    def refresh_output_sinks(self, *, handle_observed_output_change: bool = True) -> None:
        if self.ui_shutting_down:
            return

        active = self.controller.output_sink
        target_transition = self.controller.output_preset_target_transition(consume=handle_observed_output_change)
        previous_output_preset_auto_loaded = self.output_preset_curve_auto_loaded
        trace_startup_event(
            "output-refresh-transition",
            consume_transition=handle_observed_output_change,
            current_preset=getattr(self, "current_preset_name", None),
            output_preset_auto_applied=bool(getattr(self, "output_preset_auto_applied", False)),
            output_preset_curve_auto_loaded=previous_output_preset_auto_loaded,
            output_sink=active,
            startup_ready=bool(getattr(self, "startup_ready", False)),
            transition=describe_output_preset_transition(target_transition),
        )
        visible_sinks = self.list_visible_output_sinks()
        visible_sink_names = [sink.node_name for sink in visible_sinks if sink.node_name is not None]
        visible_sink_labels = self.build_output_sink_labels(visible_sinks)
        self.output_sink_names = [None, *visible_sink_names]
        self.output_sink_labels = [self.follow_default_output_label(), *visible_sink_labels]
        selected_index = 0

        if not self.controller.follow_default_output:
            if active in visible_sink_names:
                selected_index = visible_sink_names.index(active) + 1
            elif active:
                self.output_sink_names.append(active)
                self.output_sink_labels.append("Unavailable output")
                selected_index = len(self.output_sink_names) - 1

        self.output_sink_model.splice(0, self.output_sink_model.get_n_items(), self.output_sink_labels)

        self.output_combo.set_sensitive(len(self.output_sink_names) > 1)

        self.updating_output_combo = True
        try:
            self.output_combo.set_selected(selected_index)
        finally:
            self.updating_output_combo = False

        self.update_preset_state()
        self.update_info_label()
        self.update_status_summary()

        if self.startup_ready and handle_observed_output_change and target_transition.changed:
            applied = self.apply_output_preset_for_current_output(
                reset_auto_preset_without_link=previous_output_preset_auto_loaded,
                announce_no_output_preset=True,
            )
            trace_startup_event(
                "output-refresh-reapply-done",
                applied=applied,
                current_preset=getattr(self, "current_preset_name", None),
                output_preset_auto_applied=bool(getattr(self, "output_preset_auto_applied", False)),
                output_preset_curve_auto_loaded=bool(getattr(self, "output_preset_curve_auto_loaded", False)),
                output_sink=getattr(self.controller, "output_sink", None),
            )

    def update_info_label(self) -> None:
        return

    def on_import_apo_clicked(self, button: Gtk.Button) -> None:
        dialog = Gtk.FileDialog(title="Import APO Preset")
        filters = Gio.ListStore.new(Gtk.FileFilter)
        file_filter = Gtk.FileFilter()
        file_filter.set_name("APO Presets")
        file_filter.add_pattern("*.txt")
        filters.append(file_filter)
        dialog.set_filters(filters)
        dialog.set_default_filter(file_filter)
        dialog.open(self, None, self.on_import_apo_done)

    def on_import_apo_done(self, dialog: Gtk.FileDialog, result: Gio.AsyncResult) -> None:
        try:
            file = dialog.open_finish(result)
        except GLib.Error:
            return

        path = file.get_path()

        if path is None:
            self.set_status("Could not open APO preset")
            return

        try:
            self.import_apo_preset_path(path)
            self.set_status("Imported APO curve")
        except Exception as exc:
            self.set_status(str(exc))

    def import_apo_preset_path(self, path: str, *, imported_name: str | None = None) -> int:
        imported_count = self.controller.import_apo_preset(path)
        if imported_name is not None:
            curve_label = imported_apo_curve_label_for_name(imported_name)
        else:
            curve_label = imported_apo_curve_label(path)
        self.selected_band_index = None
        self.set_visible_band_count(imported_count)
        self.current_preset_name = None
        self.saved_preset_signature = self.controller.state_signature()
        self.set_curve_revert_baseline(curve_label)
        self.output_preset_auto_applied = False
        self.output_preset_curve_auto_loaded = False
        self.refresh_preset_list()
        utility_pane_button = getattr(self, "utility_pane_button", None)
        if utility_pane_button is not None and utility_pane_button.get_visible():
            utility_pane_button.set_active(True)
        self.sync_ui_from_state()
        self.notify_control_state_changed()
        return imported_count

    def on_output_changed(self, combo: Gtk.DropDown, _param: object) -> None:
        if self.updating_output_combo:
            return

        selected = combo.get_selected()
        if selected >= len(self.output_sink_names):
            return

        sink_name = self.output_sink_names[selected]

        try:
            if sink_name is None:
                self.controller.follow_system_default_output()
                self.refresh_output_sinks(handle_observed_output_change=False)
                return

            self.controller.change_output_sink(sink_name)
            self.refresh_output_sinks(handle_observed_output_change=False)
        except Exception as exc:
            self.set_status(str(exc))

    def on_mode_changed(self, combo: Gtk.DropDown, _param: object) -> None:
        if self.updating_ui:
            return

        selected = combo.get_selected()
        if selected >= len(MODE_ORDER):
            return

        self.controller.set_eq_mode(EQ_MODES[MODE_ORDER[selected]])
        self.invalidate_graph_response_cache()
        self.queue_graph_draw()

    def on_route_changed(self, switch: Gtk.Switch, state: object | None) -> bool:
        enabled = requested_switch_state(switch, state)

        if self.updating_ui:
            return False

        eq_was_enabled = self.controller.eq_enabled
        route_changed = False

        try:
            self.controller.route_system_audio(enabled)
            route_changed = True
        except Exception as exc:
            self.set_status(str(exc))
        finally:
            self.refresh_after_route_state_changed(
                eq_was_enabled=eq_was_enabled,
                announce_enabled=enabled if route_changed else None,
            )
        return True

    def on_bypass_changed(self, switch: Gtk.Switch, state: object | None) -> bool:
        enabled = requested_switch_state(switch, state)

        if self.updating_ui:
            self.update_eq_power_indicator()
            return False

        try:
            self.controller.set_eq_enabled(enabled)
            self.refresh_after_eq_state_changed(announce_enabled=enabled)
        except Exception as exc:
            self.sync_control_switches_from_controller(route=False)
            self.update_eq_power_indicator()
            self.set_status(str(exc))
        return True
