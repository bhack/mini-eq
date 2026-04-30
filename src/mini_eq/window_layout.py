from __future__ import annotations

from importlib.resources import files

import gi

gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
gi.require_version("Gtk", "4.0")

from gi.repository import Adw, Gdk, Gio, GObject, Gtk, Pango

from .analyzer_widget import AnalyzerPlotWidget
from .band_fader import EqBandFader
from .core import (
    APP_NAME,
    DEFAULT_ACTIVE_BANDS,
    EQ_FREQUENCY_MAX_HZ,
    EQ_FREQUENCY_MIN_HZ,
    EQ_PREAMP_MAX_DB,
    EQ_PREAMP_MIN_DB,
    EQ_Q_MAX,
    EQ_Q_MIN,
    FILTER_TYPE_ORDER,
    MAX_BANDS,
    clamp,
)
from .window_graph import GRAPH_PLOT_BOTTOM, GRAPH_PLOT_LEFT, GRAPH_PLOT_RIGHT, GRAPH_PLOT_TOP

ADAPTIVE_NARROW_BREAKPOINT_SP = 1320
COMPACT_BREAKPOINT_SP = 1080
DEFAULT_GRAPH_CONTENT_WIDTH = 900
COMPACT_GRAPH_CONTENT_WIDTH = 760
DEFAULT_GRAPH_CONTENT_HEIGHT = 196
COMPACT_GRAPH_CONTENT_HEIGHT = 142
GRAPH_PLOT_HORIZONTAL_MARGINS = int(GRAPH_PLOT_LEFT + GRAPH_PLOT_RIGHT)
GRAPH_PLOT_VERTICAL_MARGINS = int(GRAPH_PLOT_TOP + GRAPH_PLOT_BOTTOM)
DEFAULT_ANALYZER_CONTENT_WIDTH = max(1, DEFAULT_GRAPH_CONTENT_WIDTH - GRAPH_PLOT_HORIZONTAL_MARGINS)
COMPACT_ANALYZER_CONTENT_WIDTH = max(1, COMPACT_GRAPH_CONTENT_WIDTH - GRAPH_PLOT_HORIZONTAL_MARGINS)
DEFAULT_ANALYZER_CONTENT_HEIGHT = max(1, DEFAULT_GRAPH_CONTENT_HEIGHT - GRAPH_PLOT_VERTICAL_MARGINS)
COMPACT_ANALYZER_CONTENT_HEIGHT = max(1, COMPACT_GRAPH_CONTENT_HEIGHT - GRAPH_PLOT_VERTICAL_MARGINS)
DEFAULT_FADER_SECTION_SPACING = 6
COMPACT_FADER_SECTION_SPACING = 3
DEFAULT_FADER_WIDGET_HEIGHT = 182
COMPACT_FADER_WIDGET_HEIGHT = 146
DEFAULT_FADER_SCROLLER_MIN_HEIGHT = 174
COMPACT_FADER_SCROLLER_MIN_HEIGHT = 132


def set_accessible_label(widget: Gtk.Widget, label: str) -> None:
    widget.update_property([Gtk.AccessibleProperty.LABEL], [label])


def set_accessible_description(widget: Gtk.Widget, description: str) -> None:
    widget.update_property([Gtk.AccessibleProperty.DESCRIPTION], [description])


def constrain_editor_label(label: Gtk.Label, width_chars: int) -> None:
    label.set_width_chars(width_chars)
    label.set_max_width_chars(width_chars)
    label.set_ellipsize(Pango.EllipsizeMode.END)
    label.set_single_line_mode(True)


class MiniEqWindowLayoutMixin:
    def build_window_content(self, auto_route: bool) -> None:
        toolbar_view = Adw.ToolbarView()
        header_bar = Adw.HeaderBar()
        header_bar.set_show_title(True)
        title_widget = Adw.WindowTitle(title=APP_NAME, subtitle="")
        header_bar.set_title_widget(title_widget)
        toolbar_view.add_top_bar(header_bar)

        default_root_spacing = 10
        compact_root_spacing = 6
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=default_root_spacing)
        root.set_margin_top(6)
        root.set_margin_bottom(6)
        root.set_margin_start(10)
        root.set_margin_end(10)
        root.set_vexpand(True)
        root.set_valign(Gtk.Align.FILL)

        toolbar_stack = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        toolbar_stack.set_hexpand(True)
        toolbar_stack.set_valign(Gtk.Align.START)

        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        toolbar.add_css_class("toolbar-row")
        toolbar.set_hexpand(True)
        toolbar.set_valign(Gtk.Align.START)

        primary_tools = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        primary_tools.set_hexpand(True)
        primary_tools.set_halign(Gtk.Align.START)

        output_inline = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        output_label = Gtk.Label(label="Output", xalign=0.0)
        output_inline.append(output_label)
        self.output_combo.set_hexpand(False)
        self.output_combo.set_size_request(300, -1)
        self.output_combo.add_css_class("toolbar-select")
        set_accessible_label(self.output_combo, "Output")
        output_inline.append(self.output_combo)
        primary_tools.append(output_inline)
        toolbar.append(primary_tools)

        tools_button = Gtk.MenuButton()
        tools_button.set_can_shrink(True)
        tools_button.set_icon_name("open-menu-symbolic")
        tools_button.add_css_class("toolbar-icon-button")
        tools_button.set_tooltip_text("App Menu")
        set_accessible_label(tools_button, "App Menu")

        def add_window_action(action_name: str, callback) -> None:
            action = Gio.SimpleAction.new(action_name, None)
            action.connect("activate", lambda _action, _parameter: callback())
            self.add_action(action)

        add_window_action("import-apo", lambda: self.on_import_apo_clicked(tools_button))
        add_window_action("reset-eq", lambda: self.on_clear_clicked(tools_button))

        tools_menu = Gio.Menu()
        tools_menu.append("Import Equalizer APO…", "win.import-apo")
        tools_menu.append("Reset EQ", "win.reset-eq")

        app_menu = Gio.Menu()
        app_menu.append("Quit", "app.quit")
        tools_menu.append_section(None, app_menu)

        tools_button.set_menu_model(tools_menu)
        header_bar.pack_start(tools_button)

        route_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        route_box.add_css_class("route-box")
        route_box.set_tooltip_text("Apply this curve to system audio")
        route_label = Gtk.Label(label="System-wide EQ", xalign=0.0)
        route_box.append(route_label)
        self.route_switch.set_tooltip_text("Apply this curve to system audio")
        set_accessible_label(self.route_switch, "System-wide EQ")
        route_box.append(self.route_switch)

        utility_pane_button = Gtk.ToggleButton()
        utility_pane_button.set_can_shrink(True)
        utility_pane_button.set_icon_name("sidebar-show-right-symbolic")
        utility_pane_button.add_css_class("toolbar-icon-button")
        utility_pane_button.set_tooltip_text("Inspector Pane")
        set_accessible_label(utility_pane_button, "Inspector Pane")
        utility_pane_button.set_active(False)
        utility_pane_button.set_visible(False)
        self.utility_pane_button = utility_pane_button

        secondary_tools = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        secondary_tools.set_halign(Gtk.Align.END)
        secondary_tools.append(route_box)
        secondary_tools.append(utility_pane_button)
        toolbar.append(secondary_tools)

        toolbar_stack.append(toolbar)
        root.append(toolbar_stack)

        workspace = Adw.OverlaySplitView()
        workspace.set_hexpand(True)
        workspace.set_vexpand(True)
        workspace.set_valign(Gtk.Align.FILL)
        workspace.set_pin_sidebar(True)
        workspace.set_show_sidebar(True)
        workspace.set_enable_show_gesture(True)
        workspace.set_enable_hide_gesture(True)
        workspace.set_sidebar_position(Gtk.PackType.END)
        workspace.set_sidebar_width_fraction(0.24)
        workspace.set_min_sidebar_width(248.0)
        workspace.set_max_sidebar_width(300.0)
        self.utility_split_view = workspace

        left_column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        left_column.set_hexpand(True)
        left_column.set_vexpand(True)

        right_column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        right_column.set_size_request(286, -1)
        right_column.set_vexpand(True)
        right_column.set_valign(Gtk.Align.FILL)
        right_column.set_margin_top(4)
        right_column.set_margin_bottom(2)
        right_column.set_margin_start(8)
        right_column.set_margin_end(6)
        right_column.add_css_class("utility-pane-shell")
        self.utility_pane_column = right_column

        workspace.set_content(left_column)
        workspace.set_sidebar(right_column)
        root.append(workspace)

        self.utility_pane_binding = workspace.bind_property(
            "show-sidebar",
            utility_pane_button,
            "active",
            GObject.BindingFlags.BIDIRECTIONAL | GObject.BindingFlags.SYNC_CREATE,
        )

        utility_pane_key_controller = Gtk.EventControllerKey()

        def on_utility_pane_key_pressed(
            _controller: Gtk.EventControllerKey,
            keyval: int,
            _keycode: int,
            _state: Gdk.ModifierType,
        ) -> bool:
            if keyval != Gdk.KEY_F9:
                return False

            workspace.set_show_sidebar(not workspace.get_show_sidebar())
            return True

        utility_pane_key_controller.connect("key-pressed", on_utility_pane_key_pressed)
        self.add_controller(utility_pane_key_controller)

        adaptive_breakpoint = Adw.Breakpoint.new(
            Adw.BreakpointCondition.parse(f"max-width: {ADAPTIVE_NARROW_BREAKPOINT_SP}sp")
        )
        self.adaptive_narrow_breakpoint = adaptive_breakpoint
        self.add_breakpoint(adaptive_breakpoint)
        adaptive_breakpoint.add_setter(workspace, "collapsed", True)
        adaptive_breakpoint.add_setter(workspace, "pin-sidebar", False)
        adaptive_breakpoint.add_setter(workspace, "show-sidebar", False)
        adaptive_breakpoint.add_setter(utility_pane_button, "visible", True)
        adaptive_breakpoint.add_setter(secondary_tools, "halign", Gtk.Align.END)

        def sync_compact_toolbar(_split_view: Adw.OverlaySplitView | None = None, _param: object | None = None) -> None:
            compact = workspace.get_collapsed()

            if compact:
                root.set_spacing(compact_root_spacing)
                root.set_margin_top(3)
                root.set_margin_bottom(3)
                output_label.set_visible(False)
                self.output_combo.set_size_request(240, -1)
                secondary_tools.add_css_class("toolbar-compact-actions")
                self.set_size_request(self.min_window_width, self.compact_min_window_height)
                return

            root.set_spacing(default_root_spacing)
            root.set_margin_top(6)
            root.set_margin_bottom(6)
            output_label.set_visible(True)
            self.output_combo.set_size_request(300, -1)
            secondary_tools.remove_css_class("toolbar-compact-actions")
            self.set_size_request(self.min_window_width, self.wide_min_window_height)

        workspace.connect("notify::collapsed", sync_compact_toolbar)
        sync_compact_toolbar()

        preset_section = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        preset_section.add_css_class("utility-section")

        preset_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        preset_title = Gtk.Label(label="Presets", xalign=0.0)
        preset_title.add_css_class("heading")
        preset_header.append(preset_title)
        preset_header_spacer = Gtk.Box()
        preset_header_spacer.set_hexpand(True)
        preset_header.append(preset_header_spacer)
        self.preset_state_label.add_css_class("preset-state-chip")
        self.preset_state_label.set_width_chars(8)
        self.preset_state_label.set_xalign(0.5)
        self.preset_state_label.set_accessible_role(Gtk.AccessibleRole.STATUS)
        preset_header.append(self.preset_state_label)
        preset_section.append(preset_header)

        self.preset_combo.set_hexpand(True)
        self.preset_combo.add_css_class("toolbar-select")
        set_accessible_label(self.preset_combo, "Preset")

        preset_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        preset_row.add_css_class("utility-row")
        preset_row.append(Gtk.Label(label="Preset", xalign=0.0))
        preset_row.append(self.preset_combo)
        preset_section.append(preset_row)

        self.preset_save_button = Gtk.Button(label="Save")
        self.preset_save_button.set_can_shrink(True)
        self.preset_save_button.add_css_class("toolbar-button")
        self.preset_save_button.connect("clicked", self.on_preset_save_clicked)

        self.preset_more_popover = Gtk.Popover()
        preset_more_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        preset_more_box.set_margin_top(8)
        preset_more_box.set_margin_bottom(8)
        preset_more_box.set_margin_start(8)
        preset_more_box.set_margin_end(8)

        def connect_preset_action(button: Gtk.Button, callback) -> None:
            def on_clicked(clicked_button: Gtk.Button) -> None:
                self.preset_more_popover.popdown()
                callback(clicked_button)

            button.connect("clicked", on_clicked)

        self.preset_save_as_button = Gtk.Button(label="Save As…")
        self.preset_save_as_button.add_css_class("popover-action")
        connect_preset_action(self.preset_save_as_button, self.on_preset_save_as_clicked)
        preset_more_box.append(self.preset_save_as_button)

        self.preset_revert_button = Gtk.Button(label="Revert")
        self.preset_revert_button.add_css_class("popover-action")
        self.preset_revert_button.set_tooltip_text("Reset to Loaded Preset")
        connect_preset_action(self.preset_revert_button, self.on_preset_revert_clicked)
        preset_more_box.append(self.preset_revert_button)

        self.preset_delete_button = Gtk.Button(label="Delete")
        self.preset_delete_button.add_css_class("popover-action")
        connect_preset_action(self.preset_delete_button, self.on_preset_delete_clicked)
        preset_more_box.append(self.preset_delete_button)

        self.preset_import_button = Gtk.Button(label="Import Mini EQ Preset…")
        self.preset_import_button.add_css_class("popover-action")
        connect_preset_action(self.preset_import_button, self.on_preset_import_clicked)
        preset_more_box.append(self.preset_import_button)

        self.preset_export_button = Gtk.Button(label="Export Mini EQ Preset…")
        self.preset_export_button.add_css_class("popover-action")
        connect_preset_action(self.preset_export_button, self.on_preset_export_clicked)
        preset_more_box.append(self.preset_export_button)

        self.preset_more_popover.set_child(preset_more_box)
        preset_more_button = Gtk.MenuButton(label="More")
        preset_more_button.set_can_shrink(True)
        preset_more_button.add_css_class("toolbar-button")
        set_accessible_label(preset_more_button, "More Preset Actions")
        preset_more_button.set_popover(self.preset_more_popover)

        preset_action_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        preset_action_row.add_css_class("preset-row")
        preset_action_row.set_homogeneous(True)
        preset_action_row.append(self.preset_save_button)
        preset_action_row.append(preset_more_button)
        preset_section.append(preset_action_row)

        right_column.append(preset_section)

        system_section = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        system_section.add_css_class("utility-section")
        system_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        system_title = Gtk.Label(label="Signal", xalign=0.0)
        system_title.add_css_class("heading")
        system_header.append(system_title)
        system_header_spacer = Gtk.Box()
        system_header_spacer.set_hexpand(True)
        system_header.append(system_header_spacer)
        self.system_state_label.add_css_class("system-state-chip")
        self.system_state_label.set_width_chars(11)
        set_accessible_label(self.system_state_label, "Signal State")
        system_header_suffix = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        system_header_suffix.append(self.system_state_label)
        system_header.append(system_header_suffix)
        system_section.append(system_header)

        compare_panel = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        compare_panel.add_css_class("compare-row")
        compare_title = Gtk.Label(label="Compare", xalign=0.0)
        compare_title.add_css_class("metric-title")
        compare_panel.append(compare_title)
        compare_spacer = Gtk.Box()
        compare_spacer.set_hexpand(True)
        compare_panel.append(compare_spacer)
        self.bypass_state_label.add_css_class("compare-state-chip")
        self.bypass_state_label.set_accessible_role(Gtk.AccessibleRole.STATUS)
        set_accessible_label(self.bypass_state_label, "Compare State")
        self.bypass_state_label.set_width_chars(9)
        self.bypass_state_label.set_size_request(92, -1)
        self.bypass_state_label.set_xalign(0.5)
        compare_panel.append(self.bypass_state_label)
        self.bypass_switch.set_tooltip_text("Compare equalized audio with the original")
        set_accessible_label(self.bypass_switch, "Equalized Audio")
        compare_panel.append(self.bypass_switch)
        system_section.append(compare_panel)

        headroom_panel = self.make_headroom_panel()
        system_section.append(headroom_panel)

        analyzer_settings_popover = Gtk.Popover()
        analyzer_settings_group = Adw.PreferencesGroup()
        analyzer_settings_group.set_margin_top(8)
        analyzer_settings_group.set_margin_bottom(8)
        analyzer_settings_group.set_margin_start(8)
        analyzer_settings_group.set_margin_end(8)
        analyzer_settings_popover.set_child(analyzer_settings_group)
        analyzer_settings_button = Gtk.MenuButton()
        analyzer_settings_button.set_can_shrink(True)
        analyzer_settings_button.set_icon_name("mini-eq-monitor-settings-symbolic")
        analyzer_settings_button.set_tooltip_text("Monitor Settings")
        set_accessible_label(analyzer_settings_button, "Monitor Settings")
        analyzer_settings_button.set_valign(Gtk.Align.CENTER)
        analyzer_settings_button.add_css_class("toolbar-icon-button")
        analyzer_settings_button.add_css_class("monitor-settings-button")
        analyzer_settings_button.set_popover(analyzer_settings_popover)

        monitor_panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        monitor_panel.add_css_class("monitor-strip")
        monitor_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        monitor_title = Gtk.Label(label="Monitor", xalign=0.0)
        monitor_title.add_css_class("metric-title")
        monitor_header.append(monitor_title)
        monitor_header_spacer = Gtk.Box()
        monitor_header_spacer.set_hexpand(True)
        monitor_header.append(monitor_header_spacer)

        self.analyzer_switch.set_valign(Gtk.Align.CENTER)
        set_accessible_label(self.analyzer_switch, "Monitor")
        monitor_header.append(self.analyzer_switch)
        monitor_panel.append(monitor_header)

        monitor_detail_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        monitor_detail_row.add_css_class("monitor-detail-row")

        self.analyzer_summary_label.add_css_class("dim-label")
        self.analyzer_summary_label.add_css_class("numeric")
        self.analyzer_summary_label.set_ellipsize(Pango.EllipsizeMode.END)
        self.analyzer_summary_label.set_hexpand(True)
        monitor_detail_row.append(self.analyzer_summary_label)
        monitor_detail_row.append(analyzer_settings_button)
        monitor_panel.append(monitor_detail_row)

        system_section.append(monitor_panel)

        smoothing_row = Adw.ActionRow(title="Smoothing")
        set_accessible_label(self.analyzer_smoothing_scale, "Monitor Smoothing")
        self.analyzer_smoothing_scale.set_size_request(116, -1)
        smoothing_row.add_suffix(self.analyzer_smoothing_scale)
        self.analyzer_smoothing_label.add_css_class("dim-label")
        smoothing_row.add_suffix(self.analyzer_smoothing_label)
        analyzer_settings_group.add(smoothing_row)

        display_gain_row = Adw.ActionRow(title="Display Gain")
        display_gain_row.set_tooltip_text("Visual Gain for Monitor Bars")
        set_accessible_label(self.analyzer_display_gain_scale, "Monitor Display Gain")
        self.analyzer_display_gain_scale.set_size_request(116, -1)
        display_gain_row.add_suffix(self.analyzer_display_gain_scale)
        self.analyzer_display_gain_label.add_css_class("dim-label")
        display_gain_row.add_suffix(self.analyzer_display_gain_label)
        analyzer_settings_group.add(display_gain_row)

        freeze_row = Adw.ActionRow(title="Freeze")
        self.analyzer_freeze_switch.set_valign(Gtk.Align.CENTER)
        set_accessible_label(self.analyzer_freeze_switch, "Freeze Monitor")
        freeze_row.add_suffix(self.analyzer_freeze_switch)
        analyzer_settings_group.add(freeze_row)

        right_column.append(system_section)

        self.warning_banner.add_css_class("warning-banner")
        right_column.append(self.warning_banner)

        graph_shell = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        graph_shell.add_css_class("panel-card")
        graph_shell.add_css_class("graph-shell-panel")
        graph_shell.set_vexpand(True)
        graph_shell.set_valign(Gtk.Align.FILL)
        graph_shell.set_margin_top(2)
        graph_shell.set_margin_bottom(0)
        graph_shell.set_margin_start(0)
        graph_shell.set_margin_end(0)

        graph_header = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        graph_header.add_css_class("graph-header")

        graph_header_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        graph_header_row.set_hexpand(True)
        self.graph_title_label.add_css_class("heading")
        self.graph_title_label.add_css_class("graph-header-title")
        self.graph_title_label.set_hexpand(True)
        graph_header_row.append(self.graph_title_label)

        graph_header.append(graph_header_row)
        graph_shell.append(graph_header)

        graph_frame = Gtk.Frame()
        graph_frame.set_hexpand(True)
        graph_frame.set_vexpand(True)
        graph_frame.set_valign(Gtk.Align.FILL)
        graph_frame.add_css_class("graph-stage")

        graph_overlay = Gtk.Overlay()
        graph_overlay.set_hexpand(True)
        graph_overlay.set_vexpand(True)
        graph_overlay.set_valign(Gtk.Align.FILL)

        self.graph_area = Gtk.DrawingArea()
        self.graph_area.set_content_width(DEFAULT_GRAPH_CONTENT_WIDTH)
        self.graph_area.set_content_height(DEFAULT_GRAPH_CONTENT_HEIGHT)
        self.graph_area.set_hexpand(True)
        self.graph_area.set_vexpand(True)
        self.graph_area.set_valign(Gtk.Align.FILL)
        self.graph_area.set_accessible_role(Gtk.AccessibleRole.IMG)
        set_accessible_label(self.graph_area, "Curve")
        set_accessible_description(self.graph_area, "Frequency response curve with optional monitor levels")
        self.graph_area.set_draw_func(self.on_graph_draw)
        graph_click = Gtk.GestureClick()
        graph_click.connect("pressed", self.on_graph_pressed)
        self.graph_area.add_controller(graph_click)
        graph_overlay.set_child(self.graph_area)

        self.analyzer_area = AnalyzerPlotWidget()
        self.analyzer_area.set_content_width(DEFAULT_ANALYZER_CONTENT_WIDTH)
        self.analyzer_area.set_content_height(DEFAULT_ANALYZER_CONTENT_HEIGHT)
        self.analyzer_area.set_hexpand(True)
        self.analyzer_area.set_vexpand(True)
        self.analyzer_area.set_halign(Gtk.Align.FILL)
        self.analyzer_area.set_valign(Gtk.Align.FILL)
        self.analyzer_area.set_margin_start(int(GRAPH_PLOT_LEFT))
        self.analyzer_area.set_margin_end(int(GRAPH_PLOT_RIGHT))
        self.analyzer_area.set_margin_top(int(GRAPH_PLOT_TOP))
        self.analyzer_area.set_margin_bottom(int(GRAPH_PLOT_BOTTOM))
        self.analyzer_area.set_can_target(False)
        self.analyzer_area.set_accessible_role(Gtk.AccessibleRole.PRESENTATION)
        graph_overlay.add_overlay(self.analyzer_area)

        self.graph_response_area = Gtk.DrawingArea()
        self.graph_response_area.set_content_width(DEFAULT_GRAPH_CONTENT_WIDTH)
        self.graph_response_area.set_content_height(DEFAULT_GRAPH_CONTENT_HEIGHT)
        self.graph_response_area.set_hexpand(True)
        self.graph_response_area.set_vexpand(True)
        self.graph_response_area.set_halign(Gtk.Align.FILL)
        self.graph_response_area.set_valign(Gtk.Align.FILL)
        self.graph_response_area.set_can_target(False)
        self.graph_response_area.set_accessible_role(Gtk.AccessibleRole.PRESENTATION)
        self.graph_response_area.set_draw_func(self.on_graph_response_draw)
        graph_overlay.add_overlay(self.graph_response_area)

        graph_frame.set_child(graph_overlay)
        graph_shell.append(graph_frame)

        graph_meta = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.focus_label.add_css_class("heading")
        self.band_count_label.add_css_class("dim-label")
        self.band_count_label.add_css_class("numeric")
        graph_meta.append(self.focus_label)
        graph_meta.append(self.band_count_label)
        graph_shell.append(graph_meta)
        left_column.append(graph_shell)

        fader_shell = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        fader_shell.add_css_class("panel-card")
        fader_shell.add_css_class("quick-view-shell")
        fader_shell.set_vexpand(False)
        fader_shell.set_valign(Gtk.Align.START)

        fader_section = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=DEFAULT_FADER_SECTION_SPACING)
        fader_section.set_vexpand(False)
        fader_section.set_valign(Gtk.Align.START)
        fader_section.set_margin_top(8)
        fader_section.set_margin_bottom(6)
        fader_section.set_margin_start(12)
        fader_section.set_margin_end(12)
        self.fader_title_label = Gtk.Label(label=f"{DEFAULT_ACTIVE_BANDS} Bands", xalign=0.0)
        self.fader_title_label.add_css_class("heading")
        self.fader_title_label.set_tooltip_text("Drag Gain; Edit the Selected Band Below")
        fader_section.append(self.fader_title_label)

        self.fader_scroller = Gtk.ScrolledWindow()
        self.fader_scroller.set_hexpand(True)
        self.fader_scroller.set_vexpand(False)
        self.fader_scroller.set_valign(Gtk.Align.START)
        self.fader_scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.NEVER)
        self.fader_scroller.set_min_content_height(DEFAULT_FADER_SCROLLER_MIN_HEIGHT)
        self.fader_scroller.add_css_class("fader-scroller")

        fader_grid = Gtk.Grid(column_spacing=7, row_spacing=0)
        fader_grid.set_column_homogeneous(False)
        fader_grid.set_hexpand(False)
        fader_grid.set_vexpand(False)
        fader_grid.set_valign(Gtk.Align.START)
        fader_grid.set_margin_top(4)
        fader_grid.set_margin_bottom(4)
        fader_grid.set_margin_start(4)
        fader_grid.set_margin_end(4)

        for index in range(MAX_BANDS):
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            box.set_halign(Gtk.Align.CENTER)
            box.set_hexpand(False)
            box.set_vexpand(False)
            box.set_valign(Gtk.Align.START)
            box.set_size_request(76, -1)
            box.add_css_class("eq-band-box")
            band_click = Gtk.GestureClick()
            band_click.connect("released", self.on_band_card_pressed, index)
            box.add_controller(band_click)

            fader = EqBandFader(
                index,
                self.on_custom_band_fader_selected,
                self.on_custom_band_fader_changed,
                self.on_custom_band_fader_activated,
            )
            fader.set_content_height(DEFAULT_FADER_WIDGET_HEIGHT)
            fader.set_vexpand(False)
            fader.set_valign(Gtk.Align.START)
            box.append(fader)

            self.band_fader_boxes.append(box)
            self.band_fader_widgets.append(fader)
            fader_grid.attach(box, index, 0, 1, 1)

        fader_center_shell = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        fader_center_shell.set_hexpand(True)
        fader_center_shell.set_vexpand(False)
        fader_center_shell.set_valign(Gtk.Align.START)

        fader_left_spacer = Gtk.Box()
        fader_left_spacer.set_hexpand(True)
        fader_center_shell.append(fader_left_spacer)
        fader_center_shell.append(fader_grid)

        fader_right_spacer = Gtk.Box()
        fader_right_spacer.set_hexpand(True)
        fader_center_shell.append(fader_right_spacer)

        self.fader_scroller.set_child(fader_center_shell)
        fader_section.append(self.fader_scroller)

        band_editor = Adw.WrapBox()
        band_editor.add_css_class("band-editor")
        band_editor.set_hexpand(True)
        band_editor.set_valign(Gtk.Align.START)
        band_editor.set_child_spacing(8)
        band_editor.set_line_spacing(6)
        band_editor.set_natural_line_length(820)
        band_editor.set_wrap_policy(Adw.WrapPolicy.NATURAL)
        self.band_editor = band_editor

        selected_band_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        selected_band_box.add_css_class("band-editor-selected")
        selected_band_box.set_size_request(88, -1)
        selected_band_box.set_hexpand(False)
        self.selected_band_label = Gtk.Label(label="Band 1", xalign=0.0)
        constrain_editor_label(self.selected_band_label, 8)
        self.selected_band_label.add_css_class("band-editor-title")
        selected_band_box.append(self.selected_band_label)

        band_editor.append(selected_band_box)

        state_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        state_box.add_css_class("band-editor-state")
        state_box.set_valign(Gtk.Align.CENTER)
        self.band_editor_state_box = state_box

        self.selected_band_mute_button = Gtk.ToggleButton(label="M")
        self.selected_band_mute_button.add_css_class("band-editor-toggle")
        self.selected_band_mute_button.set_tooltip_text("Mute Selected Band")
        set_accessible_label(self.selected_band_mute_button, "Mute Selected Band")
        state_box.append(self.selected_band_mute_button)

        self.selected_band_solo_button = Gtk.ToggleButton(label="S")
        self.selected_band_solo_button.add_css_class("band-editor-toggle")
        self.selected_band_solo_button.set_tooltip_text("Solo Selected Band")
        set_accessible_label(self.selected_band_solo_button, "Solo Selected Band")
        state_box.append(self.selected_band_solo_button)
        band_editor.append(state_box)

        type_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        type_box.add_css_class("band-editor-field")
        type_box.set_valign(Gtk.Align.CENTER)
        type_label = Gtk.Label(label="Type", xalign=0.0)
        type_label.add_css_class("metric-title")
        type_box.append(type_label)
        self.selected_band_type_combo = Gtk.DropDown(model=Gtk.StringList.new(FILTER_TYPE_ORDER))
        self.selected_band_type_combo.set_size_request(118, -1)
        self.selected_band_type_combo.add_css_class("toolbar-select")
        self.selected_band_type_combo.add_css_class("band-editor-input")
        set_accessible_label(self.selected_band_type_combo, "Selected Band Filter Type")
        type_box.append(self.selected_band_type_combo)
        band_editor.append(type_box)

        frequency_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        frequency_box.add_css_class("band-editor-field")
        frequency_box.set_valign(Gtk.Align.CENTER)
        frequency_label = Gtk.Label(label="Frequency", xalign=0.0)
        frequency_label.add_css_class("metric-title")
        frequency_box.append(frequency_label)
        self.selected_band_frequency_spin = Gtk.SpinButton.new_with_range(
            EQ_FREQUENCY_MIN_HZ,
            EQ_FREQUENCY_MAX_HZ,
            0.1,
        )
        self.selected_band_frequency_spin.set_digits(1)
        self.selected_band_frequency_spin.set_size_request(110, -1)
        self.selected_band_frequency_spin.add_css_class("band-editor-input")
        set_accessible_label(self.selected_band_frequency_spin, "Selected Band Frequency")
        frequency_box.append(self.selected_band_frequency_spin)
        band_editor.append(frequency_box)

        q_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        q_box.add_css_class("band-editor-field")
        q_box.set_valign(Gtk.Align.CENTER)
        q_label = Gtk.Label(label="Q", xalign=0.0)
        q_label.add_css_class("metric-title")
        q_box.append(q_label)
        self.selected_band_q_spin = Gtk.SpinButton.new_with_range(EQ_Q_MIN, EQ_Q_MAX, 0.001)
        self.selected_band_q_spin.set_digits(3)
        self.selected_band_q_spin.set_size_request(82, -1)
        self.selected_band_q_spin.add_css_class("band-editor-input")
        set_accessible_label(self.selected_band_q_spin, "Selected Band Q")
        q_box.append(self.selected_band_q_spin)
        band_editor.append(q_box)

        gain_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        gain_box.add_css_class("band-editor-field")
        gain_box.set_valign(Gtk.Align.CENTER)
        gain_label = Gtk.Label(label="Gain", xalign=0.0)
        gain_label.add_css_class("metric-title")
        gain_box.append(gain_label)
        self.selected_band_gain_spin.set_digits(1)
        self.selected_band_gain_spin.set_size_request(96, -1)
        self.selected_band_gain_spin.add_css_class("band-editor-input")
        set_accessible_label(self.selected_band_gain_spin, "Selected Band Gain")
        gain_box.append(self.selected_band_gain_spin)
        band_editor.append(gain_box)

        compact_breakpoint = Adw.Breakpoint.new(Adw.BreakpointCondition.parse(f"max-width: {COMPACT_BREAKPOINT_SP}sp"))
        self.add_breakpoint(compact_breakpoint)
        compact_breakpoint.add_setter(workspace, "collapsed", True)
        compact_breakpoint.add_setter(workspace, "pin-sidebar", False)
        compact_breakpoint.add_setter(workspace, "show-sidebar", False)
        compact_breakpoint.add_setter(utility_pane_button, "visible", True)
        compact_breakpoint.add_setter(self.graph_area, "content-width", COMPACT_GRAPH_CONTENT_WIDTH)
        compact_breakpoint.add_setter(self.analyzer_area, "content-width", COMPACT_ANALYZER_CONTENT_WIDTH)
        compact_breakpoint.add_setter(self.graph_response_area, "content-width", COMPACT_GRAPH_CONTENT_WIDTH)

        def move_if_needed(child: Gtk.Widget, parent: Gtk.Box) -> None:
            current_parent = child.get_parent()
            if current_parent is parent:
                return
            if isinstance(current_parent, Gtk.Box):
                current_parent.remove(child)
            parent.append(child)

        def sync_compact_band_editor(
            _split_view: Adw.OverlaySplitView | None = None, _param: object | None = None
        ) -> None:
            compact = workspace.get_collapsed()

            if compact:
                graph_shell.set_spacing(2)
                self.graph_area.set_content_height(COMPACT_GRAPH_CONTENT_HEIGHT)
                self.analyzer_area.set_content_height(COMPACT_ANALYZER_CONTENT_HEIGHT)
                self.graph_response_area.set_content_height(COMPACT_GRAPH_CONTENT_HEIGHT)
                fader_section.set_spacing(COMPACT_FADER_SECTION_SPACING)
                fader_section.set_vexpand(False)
                fader_section.set_valign(Gtk.Align.START)
                fader_section.set_margin_top(4)
                fader_section.set_margin_bottom(3)
                self.fader_scroller.set_vexpand(False)
                self.fader_scroller.set_valign(Gtk.Align.START)
                self.fader_scroller.set_min_content_height(COMPACT_FADER_SCROLLER_MIN_HEIGHT)
                self.fader_scroller.add_css_class("fader-scroller-compact")
                fader_grid.set_margin_top(2)
                fader_grid.set_margin_bottom(2)
                band_editor.add_css_class("band-editor-compact-active")
                band_editor.remove_css_class("band-editor-inline-compact")
                selected_band_box.set_size_request(72, -1)
                state_box.set_spacing(4)
                type_box.set_spacing(4)
                frequency_box.set_spacing(4)
                q_box.set_spacing(4)
                gain_box.set_spacing(4)

                band_editor.set_child_spacing(6)
                band_editor.set_line_spacing(4)
                band_editor.set_natural_line_length(720)
                self.selected_band_type_combo.set_size_request(96, -1)
                self.selected_band_frequency_spin.set_size_request(88, -1)
                self.selected_band_q_spin.set_size_request(68, -1)
                self.selected_band_gain_spin.set_size_request(80, -1)
                for fader in self.band_fader_widgets:
                    fader.set_content_height(COMPACT_FADER_WIDGET_HEIGHT)
                    fader.set_size_request(-1, -1)
                    fader.queue_resize()
                self.fader_scroller.queue_resize()
                band_editor.add_css_class("band-editor-inline-compact")
                move_if_needed(band_editor, fader_section)
                return

            graph_shell.set_spacing(6)
            self.graph_area.set_content_height(DEFAULT_GRAPH_CONTENT_HEIGHT)
            self.analyzer_area.set_content_height(DEFAULT_ANALYZER_CONTENT_HEIGHT)
            self.graph_response_area.set_content_height(DEFAULT_GRAPH_CONTENT_HEIGHT)
            fader_section.set_spacing(DEFAULT_FADER_SECTION_SPACING)
            fader_section.set_vexpand(False)
            fader_section.set_valign(Gtk.Align.START)
            fader_section.set_margin_top(8)
            fader_section.set_margin_bottom(6)
            self.fader_scroller.set_vexpand(False)
            self.fader_scroller.set_valign(Gtk.Align.START)
            self.fader_scroller.set_min_content_height(DEFAULT_FADER_SCROLLER_MIN_HEIGHT)
            self.fader_scroller.remove_css_class("fader-scroller-compact")
            fader_grid.set_margin_top(4)
            fader_grid.set_margin_bottom(4)
            band_editor.remove_css_class("band-editor-compact-active")
            band_editor.remove_css_class("band-editor-inline-compact")
            band_editor.set_child_spacing(8)
            band_editor.set_line_spacing(6)
            band_editor.set_natural_line_length(820)
            for fader in self.band_fader_widgets:
                fader.set_content_height(DEFAULT_FADER_WIDGET_HEIGHT)
                fader.set_size_request(-1, -1)
                fader.queue_resize()
            self.fader_scroller.queue_resize()
            selected_band_box.set_size_request(88, -1)
            state_box.set_spacing(6)
            type_box.set_spacing(6)
            frequency_box.set_spacing(6)
            q_box.set_spacing(6)
            gain_box.set_spacing(6)
            self.selected_band_type_combo.set_size_request(118, -1)
            self.selected_band_frequency_spin.set_size_request(110, -1)
            self.selected_band_q_spin.set_size_request(82, -1)
            self.selected_band_gain_spin.set_size_request(96, -1)
            move_if_needed(band_editor, fader_section)

        workspace.connect("notify::collapsed", sync_compact_band_editor)
        sync_compact_band_editor()

        if band_editor.get_parent() is None:
            fader_section.append(band_editor)
        fader_shell.append(fader_section)
        left_column.append(fader_shell)

        self.toast_overlay = Adw.ToastOverlay()
        self.toast_overlay.set_child(root)
        toolbar_view.set_content(self.toast_overlay)
        self.set_content(toolbar_view)

        self.preset_combo.connect("notify::selected", self.on_preset_selected)
        self.output_combo.connect("notify::selected", self.on_output_changed)
        self.mode_combo.connect("notify::selected", self.on_mode_changed)
        self.analyzer_switch.connect("notify::active", self.on_analyzer_changed)
        self.analyzer_freeze_switch.connect("notify::active", self.on_analyzer_freeze_changed)
        self.analyzer_smoothing_scale.connect("value-changed", self.on_analyzer_smoothing_changed)
        self.analyzer_display_gain_scale.connect("value-changed", self.on_analyzer_display_gain_changed)
        self.selected_band_type_combo.connect("notify::selected", self.on_selected_band_type_changed)
        self.selected_band_frequency_spin.connect("value-changed", self.on_selected_band_frequency_changed)
        self.selected_band_q_spin.connect("value-changed", self.on_selected_band_q_changed)
        self.selected_band_gain_spin.connect("value-changed", self.on_selected_band_gain_changed)
        self.selected_band_mute_button.connect("notify::active", self.on_selected_band_mute_changed)
        self.selected_band_solo_button.connect("notify::active", self.on_selected_band_solo_changed)
        self.bypass_switch.connect("notify::active", self.on_bypass_changed)
        self.route_switch.connect("notify::active", self.on_route_changed)
        self.connect("close-request", self.on_close_request)

        self.refresh_output_sinks()
        self.refresh_preset_list()
        self.sync_ui_from_state()

    def make_headroom_panel(self) -> Gtk.Box:
        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=7)
        panel.add_css_class("headroom-panel")
        self.headroom_panel = panel

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        title = Gtk.Label(label="Headroom", xalign=0.0)
        title.add_css_class("metric-title")
        header.append(title)

        header_spacer = Gtk.Box()
        header_spacer.set_hexpand(True)
        header.append(header_spacer)

        self.headroom_fix_button = Gtk.Button(label="Set Safe")
        self.headroom_fix_button.add_css_class("headroom-fix-button")
        self.headroom_fix_button.set_tooltip_text("Lower Preamp to Restore Headroom")
        self.headroom_fix_button.set_visible(False)
        self.headroom_fix_button.connect("clicked", self.on_set_safe_preamp_clicked)
        header.append(self.headroom_fix_button)

        self.headroom_peak_label = Gtk.Label(label="Peak --", xalign=1.0)
        self.headroom_peak_label.add_css_class("headroom-peak-chip")
        self.headroom_peak_label.add_css_class("numeric")
        header.append(self.headroom_peak_label)
        panel.append(header)

        self.headroom_state_label = Gtk.Label(label="EQ off", xalign=0.0)
        self.headroom_state_label.add_css_class("headroom-state")
        self.headroom_state_label.add_css_class("numeric")
        self.headroom_state_label.set_wrap(True)
        self.headroom_state_label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        panel.append(self.headroom_state_label)

        self.headroom_meter_area = Gtk.DrawingArea()
        self.headroom_meter_area.set_content_width(260)
        self.headroom_meter_area.set_content_height(14)
        self.headroom_meter_area.set_hexpand(True)
        self.headroom_meter_area.set_accessible_role(Gtk.AccessibleRole.IMG)
        set_accessible_label(self.headroom_meter_area, "Headroom Meter")
        self.headroom_meter_area.set_draw_func(self.on_headroom_meter_draw)
        panel.append(self.headroom_meter_area)

        self.headroom_detail_label = Gtk.Label(xalign=0.0)
        self.headroom_detail_label.add_css_class("headroom-detail")
        self.headroom_detail_label.add_css_class("dim-label")
        self.headroom_detail_label.set_wrap(True)
        self.headroom_detail_label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        panel.append(self.headroom_detail_label)

        preamp_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        preamp_row.add_css_class("headroom-preamp-row")
        preamp_title = Gtk.Label(label="Preamp", xalign=0.0)
        preamp_title.add_css_class("metric-title")
        preamp_row.append(preamp_title)

        self.preamp_scale = Gtk.Scale.new_with_range(
            Gtk.Orientation.HORIZONTAL,
            EQ_PREAMP_MIN_DB,
            EQ_PREAMP_MAX_DB,
            0.5,
        )
        self.preamp_scale.set_draw_value(False)
        self.preamp_scale.set_hexpand(True)
        set_accessible_label(self.preamp_scale, "Preamp")
        self.preamp_scale.connect("value-changed", self.on_preamp_changed)
        preamp_row.append(self.preamp_scale)

        self.preamp_label.add_css_class("numeric")
        preamp_row.append(self.preamp_label)
        panel.append(preamp_row)

        return panel

    def set_headroom_state(
        self,
        *,
        state: str,
        peak_text: str,
        detail: str,
        peak_db: float | None,
        kind: str,
    ) -> None:
        self.headroom_peak_db = peak_db
        self.headroom_state_kind = kind
        self.headroom_state_label.set_text(state)
        self.headroom_peak_label.set_text(peak_text)
        self.headroom_detail_label.set_text(detail)

        for css_class in ("headroom-safe", "headroom-tight", "headroom-risk", "headroom-bypass"):
            self.headroom_state_label.remove_css_class(css_class)
            self.headroom_peak_label.remove_css_class(css_class)

        state_class = f"headroom-{kind}"
        self.headroom_state_label.add_css_class(state_class)
        self.headroom_peak_label.add_css_class(state_class)

        if self.headroom_panel is not None:
            for css_class in (
                "headroom-panel-safe",
                "headroom-panel-tight",
                "headroom-panel-risk",
                "headroom-panel-bypass",
            ):
                self.headroom_panel.remove_css_class(css_class)
            self.headroom_panel.add_css_class(f"headroom-panel-{kind}")

        if self.headroom_fix_button is not None:
            self.headroom_fix_button.set_visible(kind == "risk")

        self.headroom_meter_area.queue_draw()

    def on_set_safe_preamp_clicked(self, _button: Gtk.Button) -> None:
        peak = self.estimate_curve_peak_db()
        if peak <= 0.5:
            return

        target_preamp = self.controller.preamp_db - peak - 1.0
        self.preamp_scale.set_value(target_preamp)
        self.set_status("Preamp Lowered for Safe Headroom")

    def on_headroom_meter_draw(self, _area: Gtk.DrawingArea, cr, width: int, height: int) -> None:
        width_f = float(max(width, 1))
        height_f = float(max(height, 1))
        track_y = max(2.0, (height_f - 8.0) / 2.0)
        track_height = min(8.0, height_f - 4.0)
        radius = track_height / 2.0
        peak = self.headroom_peak_db
        kind = getattr(self, "headroom_state_kind", "bypass")

        def rounded_rect(x: float, y: float, rect_width: float, rect_height: float, rect_radius: float) -> None:
            cr.new_sub_path()
            cr.arc(x + rect_width - rect_radius, y + rect_radius, rect_radius, -1.5708, 0.0)
            cr.arc(x + rect_width - rect_radius, y + rect_height - rect_radius, rect_radius, 0.0, 1.5708)
            cr.arc(x + rect_radius, y + rect_height - rect_radius, rect_radius, 1.5708, 3.1416)
            cr.arc(x + rect_radius, y + rect_radius, rect_radius, 3.1416, 4.7124)
            cr.close_path()

        def x_for_db(value: float) -> float:
            return width_f * clamp((value + 12.0) / 18.0, 0.0, 1.0)

        rounded_rect(0.0, track_y, width_f, track_height, radius)
        cr.set_source_rgba(1.0, 1.0, 1.0, 0.06)
        cr.fill()

        if kind == "bypass" or peak is None:
            cr.set_source_rgba(1.0, 1.0, 1.0, 0.20)
            cr.set_line_width(1.0)
            cr.move_to(x_for_db(0.0), track_y - 1.0)
            cr.line_to(x_for_db(0.0), track_y + track_height + 1.0)
            cr.stroke()
            return

        segments = (
            (-12.0, -3.0, (0.38, 0.78, 0.50, 0.78)),
            (-3.0, 0.0, (0.58, 0.66, 0.76, 0.64)),
            (0.0, 6.0, (1.0, 0.35, 0.28, 0.86)),
        )
        cr.save()
        rounded_rect(0.0, track_y, width_f, track_height, radius)
        cr.clip()
        for left_db, right_db, color in segments:
            left = x_for_db(left_db)
            right = x_for_db(right_db)
            cr.rectangle(left, track_y, max(right - left, 1.0), track_height)
            cr.set_source_rgba(*color)
            cr.fill()
        cr.restore()

        zero_x = x_for_db(0.0)
        cr.set_source_rgba(0.05, 0.07, 0.10, 0.62)
        cr.set_line_width(1.0)
        cr.move_to(zero_x, track_y - 1.0)
        cr.line_to(zero_x, track_y + track_height + 1.0)
        cr.stroke()

        marker_x = x_for_db(peak)
        cr.set_source_rgba(0.96, 0.98, 1.0, 0.98)
        cr.arc(marker_x, track_y + (track_height / 2.0), 3.2, 0.0, 6.2832)
        cr.fill()

    def install_css(self) -> None:
        css = files("mini_eq").joinpath("style.css").read_bytes()

        provider = Gtk.CssProvider()
        provider.load_from_data(css)
        display = Gdk.Display.get_default()
        if display is not None:
            Gtk.StyleContext.add_provider_for_display(
                display,
                provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
            )
