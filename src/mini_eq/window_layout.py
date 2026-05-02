from __future__ import annotations

from importlib.resources import files

import gi

gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
gi.require_version("Gtk", "4.0")

from gi.repository import Adw, Gdk, Gio, GLib, GObject, Gtk

from .analyzer_widget import AnalyzerPlotWidget
from .band_fader import EqBandFader
from .core import (
    APP_NAME,
    DEFAULT_ACTIVE_BANDS,
    EQ_FREQUENCY_MAX_HZ,
    EQ_FREQUENCY_MIN_HZ,
    EQ_Q_MAX,
    EQ_Q_MIN,
    FILTER_TYPE_ORDER,
    MAX_BANDS,
    clamp,
)
from .window_graph import GRAPH_PLOT_BOTTOM, GRAPH_PLOT_LEFT, GRAPH_PLOT_RIGHT, GRAPH_PLOT_TOP
from .window_utils import constrain_editor_label, set_accessible_description, set_accessible_label

ADAPTIVE_NARROW_BREAKPOINT_SP = 1320
RESPONSIVE_COMFORTABLE_HEIGHT = 720
RESPONSIVE_ROOMY_HEIGHT = 960
COMPACT_BREAKPOINT_SP = 1080
DEFAULT_GRAPH_CONTENT_WIDTH = 900
COMPACT_GRAPH_CONTENT_WIDTH = 760
DEFAULT_GRAPH_CONTENT_HEIGHT = 196
COMPACT_GRAPH_CONTENT_HEIGHT = 156
ROOMY_GRAPH_CONTENT_HEIGHT = 280
WORKSPACE_MAX_WIDTH = 1760
GRAPH_PLOT_HORIZONTAL_MARGINS = int(GRAPH_PLOT_LEFT + GRAPH_PLOT_RIGHT)
GRAPH_PLOT_VERTICAL_MARGINS = int(GRAPH_PLOT_TOP + GRAPH_PLOT_BOTTOM)
DEFAULT_ANALYZER_CONTENT_WIDTH = max(1, DEFAULT_GRAPH_CONTENT_WIDTH - GRAPH_PLOT_HORIZONTAL_MARGINS)
COMPACT_ANALYZER_CONTENT_WIDTH = max(1, COMPACT_GRAPH_CONTENT_WIDTH - GRAPH_PLOT_HORIZONTAL_MARGINS)
DEFAULT_ANALYZER_CONTENT_HEIGHT = max(1, DEFAULT_GRAPH_CONTENT_HEIGHT - GRAPH_PLOT_VERTICAL_MARGINS)
COMPACT_ANALYZER_CONTENT_HEIGHT = max(1, COMPACT_GRAPH_CONTENT_HEIGHT - GRAPH_PLOT_VERTICAL_MARGINS)
DEFAULT_FADER_SECTION_SPACING = 6
COMPACT_FADER_SECTION_SPACING = 3
DEFAULT_FADER_WIDGET_HEIGHT = 208
COMPACT_FADER_WIDGET_HEIGHT = 164
ROOMY_FADER_WIDGET_HEIGHT = 300
DEFAULT_FADER_SCROLLER_MIN_HEIGHT = 200
COMPACT_FADER_SCROLLER_MIN_HEIGHT = 150
ROOMY_FADER_SCROLLER_MIN_HEIGHT = 290


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
        self.appearance_root = root
        self.sync_appearance_css_class()

        content_clamp = Adw.Clamp()
        content_clamp.set_orientation(Gtk.Orientation.HORIZONTAL)
        content_clamp.set_maximum_size(WORKSPACE_MAX_WIDTH)
        content_clamp.set_tightening_threshold(WORKSPACE_MAX_WIDTH)
        content_clamp.set_hexpand(True)
        content_clamp.set_vexpand(True)
        content_clamp.set_valign(Gtk.Align.FILL)

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
        self.appearance_action = Gio.SimpleAction.new_stateful(
            "appearance",
            GLib.VariantType.new("s"),
            GLib.Variant.new_string(self.appearance_preference),
        )
        self.appearance_action.connect("change-state", self.on_appearance_action_state_changed)
        self.add_action(self.appearance_action)

        tools_menu = Gio.Menu()
        tools_menu.append("Import Equalizer APO…", "win.import-apo")
        tools_menu.append("Reset EQ", "win.reset-eq")

        appearance_menu = Gio.Menu()
        appearance_menu.append("System", "win.appearance::system")
        appearance_menu.append("Light", "win.appearance::light")
        appearance_menu.append("Dark", "win.appearance::dark")
        tools_menu.append_submenu("Appearance", appearance_menu)

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
        self.route_switch.set_valign(Gtk.Align.CENTER)
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
        workspace.set_min_sidebar_width(268.0)
        workspace.set_max_sidebar_width(320.0)

        left_column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        left_column.set_hexpand(True)
        left_column.set_vexpand(True)
        left_column.set_margin_end(8)

        left_scroller = Gtk.ScrolledWindow()
        left_scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        left_scroller.set_propagate_natural_height(False)
        left_scroller.set_hexpand(True)
        left_scroller.set_vexpand(True)
        left_scroller.set_child(left_column)

        right_column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        right_column.set_size_request(292, -1)
        right_column.set_vexpand(False)
        right_column.set_valign(Gtk.Align.START)
        right_column.set_margin_top(4)
        right_column.set_margin_bottom(2)
        right_column.set_margin_start(14)
        right_column.set_margin_end(10)
        right_column.add_css_class("utility-pane-shell")

        right_scroller = Gtk.ScrolledWindow()
        right_scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        right_scroller.set_propagate_natural_height(False)
        right_scroller.set_size_request(310, -1)
        right_scroller.set_vexpand(True)
        right_scroller.set_child(right_column)

        workspace.set_content(left_scroller)
        workspace.set_sidebar(right_scroller)
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
        self.add_breakpoint(adaptive_breakpoint)
        adaptive_breakpoint.add_setter(workspace, "collapsed", True)
        adaptive_breakpoint.add_setter(workspace, "pin-sidebar", False)
        adaptive_breakpoint.add_setter(workspace, "show-sidebar", False)
        adaptive_breakpoint.add_setter(utility_pane_button, "visible", True)
        adaptive_breakpoint.add_setter(secondary_tools, "halign", Gtk.Align.END)

        def sync_compact_toolbar(_widget: Gtk.Widget | None = None, _param: object | None = None) -> None:
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
            self.set_size_request(self.min_window_width, self.default_min_window_height)

        workspace.connect("notify::collapsed", sync_compact_toolbar)
        self.connect("notify::current-breakpoint", sync_compact_toolbar)
        sync_compact_toolbar()

        preset_section = self.make_preset_section()
        right_column.append(preset_section)

        system_section, monitor_panel = self.make_system_section()
        right_column.append(system_section)

        graph_shell = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        graph_shell.add_css_class("graph-shell-panel")
        graph_shell.set_vexpand(False)
        graph_shell.set_valign(Gtk.Align.START)
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
        graph_frame.set_vexpand(False)
        graph_frame.set_valign(Gtk.Align.START)
        graph_frame.add_css_class("graph-stage")

        graph_overlay = Gtk.Overlay()
        graph_overlay.set_hexpand(True)
        graph_overlay.set_vexpand(False)
        graph_overlay.set_valign(Gtk.Align.START)

        self.graph_area = Gtk.DrawingArea()
        self.graph_area.set_content_width(DEFAULT_GRAPH_CONTENT_WIDTH)
        self.graph_area.set_content_height(DEFAULT_GRAPH_CONTENT_HEIGHT)
        self.graph_area.set_hexpand(True)
        self.graph_area.set_vexpand(False)
        self.graph_area.set_valign(Gtk.Align.START)
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
        self.analyzer_area.set_vexpand(False)
        self.analyzer_area.set_halign(Gtk.Align.FILL)
        self.analyzer_area.set_valign(Gtk.Align.START)
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
        self.graph_response_area.set_vexpand(False)
        self.graph_response_area.set_halign(Gtk.Align.FILL)
        self.graph_response_area.set_valign(Gtk.Align.START)
        self.graph_response_area.set_can_target(False)
        self.graph_response_area.set_accessible_role(Gtk.AccessibleRole.PRESENTATION)
        self.graph_response_area.set_draw_func(self.on_graph_response_draw)
        graph_overlay.add_overlay(self.graph_response_area)

        graph_meta = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.focus_label.add_css_class("heading")
        self.band_count_label.add_css_class("dim-label")
        self.band_count_label.add_css_class("numeric")
        graph_meta.append(self.focus_label)
        graph_meta.append(self.band_count_label)
        graph_meta.set_margin_start(12)
        graph_meta.set_margin_end(12)
        graph_meta.set_margin_bottom(2)

        graph_stage_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        graph_stage_box.append(graph_overlay)
        graph_stage_box.append(graph_meta)

        graph_frame.set_child(graph_stage_box)
        graph_shell.append(graph_frame)
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

        def responsive_value(dense_value: int, roomy_value: int, height: int) -> int:
            dense_height = self.compact_min_window_height
            progress = clamp(
                (height - dense_height) / max(RESPONSIVE_ROOMY_HEIGHT - dense_height, 1),
                0.0,
                1.0,
            )
            return round(dense_value + ((roomy_value - dense_value) * progress))

        def sync_visual_layout(height: int | None = None) -> None:
            compact = workspace.get_collapsed()
            layout_height = height if height is not None and height > 0 else self.get_allocated_height()

            graph_height = responsive_value(
                COMPACT_GRAPH_CONTENT_HEIGHT,
                ROOMY_GRAPH_CONTENT_HEIGHT,
                layout_height,
            )
            analyzer_height = max(1, graph_height - GRAPH_PLOT_VERTICAL_MARGINS)
            fader_height = responsive_value(
                COMPACT_FADER_WIDGET_HEIGHT,
                ROOMY_FADER_WIDGET_HEIGHT,
                layout_height,
            )
            fader_scroller_height = responsive_value(
                COMPACT_FADER_SCROLLER_MIN_HEIGHT,
                ROOMY_FADER_SCROLLER_MIN_HEIGHT,
                layout_height,
            )
            dense = layout_height < RESPONSIVE_COMFORTABLE_HEIGHT
            right_column.set_spacing(8 if dense else 12)
            right_column.set_margin_top(2 if dense else 4)
            right_column.set_margin_bottom(0 if dense else 2)
            preset_section.set_spacing(6 if dense else 8)
            system_section.set_spacing(6 if dense else 8)
            self.headroom_panel.set_spacing(4 if dense else 7)
            self.headroom_meter_area.set_content_height(10 if dense else 14)
            monitor_panel.set_spacing(2 if dense else 4)
            if dense:
                right_column.add_css_class("utility-pane-dense")
            else:
                right_column.remove_css_class("utility-pane-dense")

            if compact:
                right_column.set_margin_start(18)
                right_column.set_margin_end(12)
                graph_shell.set_spacing(4 if not dense else 2)
                self.graph_area.set_content_height(graph_height)
                self.analyzer_area.set_content_height(analyzer_height)
                self.graph_response_area.set_content_height(graph_height)
                fader_section.set_spacing(COMPACT_FADER_SECTION_SPACING)
                fader_section.set_vexpand(False)
                fader_section.set_valign(Gtk.Align.START)
                fader_section.set_margin_top(6 if not dense else 4)
                fader_section.set_margin_bottom(4 if not dense else 3)
                self.fader_scroller.set_vexpand(False)
                self.fader_scroller.set_valign(Gtk.Align.START)
                self.fader_scroller.set_min_content_height(fader_scroller_height)
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
                    fader.set_content_height(fader_height)
                    fader.set_size_request(-1, -1)
                    fader.queue_resize()
                self.fader_scroller.queue_resize()
                band_editor.add_css_class("band-editor-inline-compact")
                move_if_needed(band_editor, fader_section)
                return

            right_column.set_margin_start(14)
            right_column.set_margin_end(10)
            graph_shell.set_spacing(2 if dense else 6)
            self.graph_area.set_content_height(graph_height)
            self.analyzer_area.set_content_height(analyzer_height)
            self.graph_response_area.set_content_height(graph_height)
            fader_section.set_spacing(COMPACT_FADER_SECTION_SPACING if dense else DEFAULT_FADER_SECTION_SPACING)
            fader_section.set_vexpand(False)
            fader_section.set_valign(Gtk.Align.START)
            fader_section.set_margin_top(4 if dense else 8)
            fader_section.set_margin_bottom(3 if dense else 6)
            self.fader_scroller.set_vexpand(False)
            self.fader_scroller.set_valign(Gtk.Align.START)
            self.fader_scroller.set_min_content_height(fader_scroller_height)
            self.fader_scroller.remove_css_class("fader-scroller-compact")
            fader_grid.set_margin_top(2 if dense else 4)
            fader_grid.set_margin_bottom(2 if dense else 4)
            band_editor.remove_css_class("band-editor-compact-active")
            band_editor.remove_css_class("band-editor-inline-compact")
            band_editor.set_child_spacing(8)
            band_editor.set_line_spacing(6)
            band_editor.set_natural_line_length(820)
            for fader in self.band_fader_widgets:
                fader.set_content_height(fader_height)
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

        def sync_compact_band_editor(_widget: Gtk.Widget | None = None, _param: object | None = None) -> None:
            sync_visual_layout()

        self.sync_responsive_layout_for_size = lambda _width, height: sync_visual_layout(height)

        workspace.connect("notify::collapsed", sync_compact_band_editor)
        self.connect("notify::current-breakpoint", sync_compact_band_editor)
        sync_compact_band_editor()

        if band_editor.get_parent() is None:
            fader_section.append(band_editor)
        fader_shell.append(fader_section)
        left_column.append(fader_shell)

        self.toast_overlay = Adw.ToastOverlay()
        content_clamp.set_child(root)
        self.toast_overlay.set_child(content_clamp)
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
