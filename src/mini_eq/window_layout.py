from __future__ import annotations

import gi

gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
gi.require_version("Gtk", "4.0")

from gi.repository import Adw, Gdk, Gtk, Pango

from .band_fader import EqBandFader
from .core import (
    APP_NAME,
    DEFAULT_ACTIVE_BANDS,
    EQ_PREAMP_MAX_DB,
    EQ_PREAMP_MIN_DB,
    MAX_BANDS,
)


def set_accessible_label(widget: Gtk.Widget, label: str) -> None:
    widget.update_property([Gtk.AccessibleProperty.LABEL], [label])


def set_accessible_description(widget: Gtk.Widget, description: str) -> None:
    widget.update_property([Gtk.AccessibleProperty.DESCRIPTION], [description])


class MiniEqWindowLayoutMixin:
    def build_window_content(self, auto_route: bool) -> None:
        toolbar_view = Adw.ToolbarView()
        header_bar = Adw.HeaderBar()
        header_bar.add_css_class("flat")
        header_bar.set_show_title(True)
        title_widget = Adw.WindowTitle(title=APP_NAME, subtitle="")
        header_bar.set_title_widget(title_widget)
        toolbar_view.add_top_bar(header_bar)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        root.set_margin_top(14)
        root.set_margin_bottom(14)
        root.set_margin_start(16)
        root.set_margin_end(16)
        root.set_valign(Gtk.Align.START)

        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        toolbar.add_css_class("toolbar-row")

        primary_tools = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        primary_tools.append(Gtk.Label(label="Output", xalign=0.0))
        self.output_combo.set_hexpand(True)
        self.output_combo.add_css_class("toolbar-select")
        set_accessible_label(self.output_combo, "Output")
        primary_tools.append(self.output_combo)
        toolbar.append(primary_tools)

        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        toolbar.append(spacer)

        tools_popover = Gtk.Popover()
        tools_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        tools_box.set_margin_top(8)
        tools_box.set_margin_bottom(8)
        tools_box.set_margin_start(8)
        tools_box.set_margin_end(8)

        def connect_tool_action(button: Gtk.Button, callback) -> None:
            def on_clicked(clicked_button: Gtk.Button) -> None:
                tools_popover.popdown()
                callback(clicked_button)

            button.connect("clicked", on_clicked)

        import_button = Gtk.Button(label="Import APO Preset…")
        import_button.add_css_class("popover-action")
        connect_tool_action(import_button, self.on_import_apo_clicked)
        tools_box.append(import_button)

        clear_button = Gtk.Button(label="Reset EQ")
        clear_button.add_css_class("popover-action")
        connect_tool_action(clear_button, self.on_clear_clicked)
        tools_box.append(clear_button)

        tools_popover.set_child(tools_box)
        tools_button = Gtk.MenuButton(label="Tools")
        tools_button.add_css_class("toolbar-button")
        tools_button.set_tooltip_text("Tools")
        set_accessible_label(tools_button, "Tools")
        tools_button.set_popover(tools_popover)

        utility_pane_button = Gtk.ToggleButton()
        utility_pane_button.set_icon_name("sidebar-show-right-symbolic")
        utility_pane_button.add_css_class("toolbar-icon-button")
        utility_pane_button.set_tooltip_text("Utility Pane")
        set_accessible_label(utility_pane_button, "Utility Pane")
        utility_pane_button.set_active(True)

        route_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        route_box.add_css_class("route-box")
        route_box.append(Gtk.Label(label="Audio Routing", xalign=0.0))
        set_accessible_label(self.route_switch, "Audio Routing")
        route_box.append(self.route_switch)

        bypass_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        bypass_box.add_css_class("route-box")
        bypass_box.append(Gtk.Label(label="EQ Bypass", xalign=0.0))
        self.bypass_state_label.add_css_class("toolbar-inline-state")
        self.bypass_state_label.set_accessible_role(Gtk.AccessibleRole.STATUS)
        set_accessible_label(self.bypass_state_label, "EQ Processing State")
        self.bypass_state_label.set_width_chars(8)
        self.bypass_state_label.set_xalign(0.5)
        bypass_box.append(self.bypass_state_label)
        set_accessible_label(self.bypass_switch, "EQ Bypass")
        bypass_box.append(self.bypass_switch)

        secondary_tools = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        secondary_tools.append(tools_button)
        secondary_tools.append(bypass_box)
        secondary_tools.append(route_box)
        secondary_tools.append(utility_pane_button)
        toolbar.append(secondary_tools)

        root.append(toolbar)

        workspace = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        workspace.set_hexpand(True)
        workspace.set_vexpand(False)
        workspace.set_valign(Gtk.Align.START)

        left_column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        left_column.set_hexpand(True)
        left_column.set_vexpand(False)

        right_column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        right_column.set_size_request(324, -1)
        right_column.set_vexpand(False)

        workspace.append(left_column)
        workspace.append(right_column)
        root.append(workspace)

        def on_utility_pane_toggled(button: Gtk.ToggleButton) -> None:
            right_column.set_visible(button.get_active())

        def on_utility_pane_visibility_changed(_column: Gtk.Box, _param: object) -> None:
            visible = right_column.get_visible()
            if utility_pane_button.get_active() != visible:
                utility_pane_button.set_active(visible)

        utility_pane_button.connect("toggled", on_utility_pane_toggled)
        right_column.connect("notify::visible", on_utility_pane_visibility_changed)

        utility_pane_key_controller = Gtk.EventControllerKey()

        def on_utility_pane_key_pressed(
            _controller: Gtk.EventControllerKey,
            keyval: int,
            _keycode: int,
            _state: Gdk.ModifierType,
        ) -> bool:
            if keyval != Gdk.KEY_F9:
                return False

            right_column.set_visible(not right_column.get_visible())
            return True

        utility_pane_key_controller.connect("key-pressed", on_utility_pane_key_pressed)
        self.add_controller(utility_pane_key_controller)

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

        self.preset_import_button = Gtk.Button(label="Import…")
        self.preset_import_button.add_css_class("popover-action")
        connect_preset_action(self.preset_import_button, self.on_preset_import_clicked)
        preset_more_box.append(self.preset_import_button)

        self.preset_export_button = Gtk.Button(label="Export…")
        self.preset_export_button.add_css_class("popover-action")
        connect_preset_action(self.preset_export_button, self.on_preset_export_clicked)
        preset_more_box.append(self.preset_export_button)

        self.preset_more_popover.set_child(preset_more_box)
        preset_more_button = Gtk.MenuButton(label="More")
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
        system_title = Gtk.Label(label="System", xalign=0.0)
        system_title.add_css_class("heading")
        system_header.append(system_title)
        system_header_spacer = Gtk.Box()
        system_header_spacer.set_hexpand(True)
        system_header.append(system_header_spacer)
        system_header_suffix = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)

        system_details_popover = Gtk.Popover()
        system_details_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        system_details_box.set_margin_top(10)
        system_details_box.set_margin_bottom(10)
        system_details_box.set_margin_start(12)
        system_details_box.set_margin_end(12)
        system_details_popover.set_child(system_details_box)
        system_details_button = Gtk.MenuButton(label="Details")
        system_details_button.add_css_class("toolbar-button")
        set_accessible_label(system_details_button, "System Details")
        system_details_button.set_popover(system_details_popover)
        system_header_suffix.append(system_details_button)

        self.system_state_label.add_css_class("system-state-chip")
        self.system_state_label.set_width_chars(10)
        system_header_suffix.append(self.system_state_label)
        system_header.append(system_header_suffix)
        system_section.append(system_header)

        route_row, self.route_value_label, self.route_detail_label = self.make_status_row("route", "Routing")
        output_row, self.output_value_label, self.output_detail_label = self.make_status_row("output", "Output")
        profile_row, self.profile_value_label, self.profile_detail_label = self.make_status_row("profile", "Profile")
        safety_row, self.safety_value_label, self.safety_detail_label = self.make_status_row("safety", "Headroom")
        self.status_card_frames = {
            "route": route_row,
            "output": output_row,
            "profile": profile_row,
            "safety": safety_row,
        }

        for row in (safety_row,):
            system_section.append(row)

        signal_path_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        signal_path_box.add_css_class("system-path")

        signal_path_title = Gtk.Label(label="Signal Path", xalign=0.0)
        signal_path_title.add_css_class("metric-title")
        signal_path_box.append(signal_path_title)

        chip_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        chip_row.add_css_class("signal-chip-row")

        apps_chip = Gtk.Label(label="Apps", xalign=0.0)
        apps_chip.add_css_class("signal-chip")
        chip_row.append(apps_chip)

        arrow_a = Gtk.Label(label="->", xalign=0.5)
        arrow_a.add_css_class("signal-arrow")
        chip_row.append(arrow_a)

        self.path_virtual_chip.add_css_class("signal-chip")
        self.path_virtual_chip.set_hexpand(True)
        self.path_virtual_chip.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        self.path_virtual_chip.set_max_width_chars(12)
        chip_row.append(self.path_virtual_chip)

        arrow_b = Gtk.Label(label="->", xalign=0.5)
        arrow_b.add_css_class("signal-arrow")
        chip_row.append(arrow_b)

        self.path_output_chip.add_css_class("signal-chip")
        self.path_output_chip.set_hexpand(True)
        self.path_output_chip.set_ellipsize(Pango.EllipsizeMode.END)
        self.path_output_chip.set_max_width_chars(14)
        chip_row.append(self.path_output_chip)

        signal_path_box.append(chip_row)

        self.path_detail_label.add_css_class("path-strip-detail")
        self.path_detail_label.add_css_class("dim-label")
        self.path_detail_label.set_wrap(True)
        signal_path_box.append(self.path_detail_label)
        system_details_box.append(route_row)
        system_details_box.append(output_row)
        system_details_box.append(profile_row)
        system_details_box.append(signal_path_box)

        right_column.append(system_section)

        self.warning_banner.add_css_class("warning-banner")
        right_column.append(self.warning_banner)

        analyzer_section = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=7)
        analyzer_section.add_css_class("utility-section")
        analyzer_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        analyzer_title = Gtk.Label(label="Analyzer", xalign=0.0)
        analyzer_title.add_css_class("heading")
        analyzer_header.append(analyzer_title)
        analyzer_header_spacer = Gtk.Box()
        analyzer_header_spacer.set_hexpand(True)
        analyzer_header.append(analyzer_header_spacer)
        analyzer_header_suffix = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.analyzer_state_label.add_css_class("graph-chip")
        self.analyzer_state_label.add_css_class("analyzer-state-chip")
        self.analyzer_state_label.set_width_chars(6)
        self.analyzer_state_label.set_xalign(0.5)
        self.analyzer_state_label.set_valign(Gtk.Align.CENTER)
        analyzer_header_suffix.append(self.analyzer_state_label)

        analyzer_settings_popover = Gtk.Popover()
        analyzer_settings_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=9)
        analyzer_settings_box.set_margin_top(10)
        analyzer_settings_box.set_margin_bottom(10)
        analyzer_settings_box.set_margin_start(12)
        analyzer_settings_box.set_margin_end(12)
        analyzer_settings_popover.set_child(analyzer_settings_box)
        analyzer_settings_button = Gtk.MenuButton()
        analyzer_settings_button.set_icon_name("preferences-system-symbolic")
        analyzer_settings_button.set_tooltip_text("Analyzer Settings")
        set_accessible_label(analyzer_settings_button, "Analyzer Settings")
        analyzer_settings_button.set_valign(Gtk.Align.CENTER)
        analyzer_settings_button.add_css_class("toolbar-icon-button")
        analyzer_settings_button.set_popover(analyzer_settings_popover)
        analyzer_header_suffix.append(analyzer_settings_button)

        self.analyzer_switch.set_valign(Gtk.Align.CENTER)
        set_accessible_label(self.analyzer_switch, "Analyzer")
        analyzer_header_suffix.append(self.analyzer_switch)
        analyzer_header.append(analyzer_header_suffix)
        analyzer_section.append(analyzer_header)

        self.analyzer_summary_label.add_css_class("dim-label")
        analyzer_section.append(self.analyzer_summary_label)

        smoothing_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        smoothing_box.append(Gtk.Label(label="Smoothing", xalign=0.0))
        set_accessible_label(self.analyzer_smoothing_scale, "Analyzer Smoothing")
        self.analyzer_smoothing_scale.set_size_request(116, -1)
        smoothing_box.append(self.analyzer_smoothing_scale)
        self.analyzer_smoothing_label.add_css_class("dim-label")
        smoothing_box.append(self.analyzer_smoothing_label)
        analyzer_settings_box.append(smoothing_box)

        display_gain_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        display_gain_label = Gtk.Label(label="Display gain", xalign=0.0)
        display_gain_label.set_tooltip_text("Visual Gain for Analyzer Bars")
        display_gain_box.append(display_gain_label)
        set_accessible_label(self.analyzer_display_gain_scale, "Analyzer Display Gain")
        self.analyzer_display_gain_scale.set_size_request(116, -1)
        display_gain_box.append(self.analyzer_display_gain_scale)
        self.analyzer_display_gain_label.add_css_class("dim-label")
        display_gain_box.append(self.analyzer_display_gain_label)
        analyzer_settings_box.append(display_gain_box)

        freeze_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        freeze_box.append(Gtk.Label(label="Freeze", xalign=0.0))
        freeze_spacer = Gtk.Box()
        freeze_spacer.set_hexpand(True)
        freeze_box.append(freeze_spacer)
        self.analyzer_freeze_switch.set_valign(Gtk.Align.CENTER)
        set_accessible_label(self.analyzer_freeze_switch, "Freeze Analyzer")
        freeze_box.append(self.analyzer_freeze_switch)
        analyzer_settings_box.append(freeze_box)

        right_column.append(analyzer_section)

        preamp_section = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        preamp_section.add_css_class("utility-section")
        preamp_title = Gtk.Label(label="Preamp", xalign=0.0)
        preamp_title.add_css_class("heading")
        preamp_section.append(preamp_title)

        preamp_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        preamp_box.add_css_class("utility-row")
        preamp_box.add_css_class("preamp-row")
        preamp_box.set_valign(Gtk.Align.CENTER)
        preamp_box.set_hexpand(True)

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
        preamp_box.append(self.preamp_scale)
        preamp_box.append(self.preamp_label)
        preamp_section.append(preamp_box)

        right_column.append(preamp_section)

        graph_shell = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        graph_shell.add_css_class("panel-card")
        graph_shell.add_css_class("graph-shell-panel")
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
        graph_frame.add_css_class("graph-stage")

        graph_overlay = Gtk.Overlay()
        graph_overlay.set_hexpand(True)

        self.graph_area = Gtk.DrawingArea()
        self.graph_area.set_content_width(900)
        self.graph_area.set_content_height(240)
        self.graph_area.set_hexpand(True)
        self.graph_area.set_vexpand(True)
        self.graph_area.set_accessible_role(Gtk.AccessibleRole.IMG)
        set_accessible_label(self.graph_area, "EQ Curve")
        set_accessible_description(self.graph_area, "Frequency response curve with optional analyzer levels")
        self.graph_area.set_draw_func(self.on_graph_draw)
        graph_click = Gtk.GestureClick()
        graph_click.connect("pressed", self.on_graph_pressed)
        self.graph_area.add_controller(graph_click)
        graph_overlay.set_child(self.graph_area)

        self.analyzer_area = Gtk.DrawingArea()
        self.analyzer_area.set_content_width(900)
        self.analyzer_area.set_content_height(240)
        self.analyzer_area.set_hexpand(True)
        self.analyzer_area.set_vexpand(True)
        self.analyzer_area.set_halign(Gtk.Align.FILL)
        self.analyzer_area.set_valign(Gtk.Align.FILL)
        self.analyzer_area.set_can_target(False)
        self.analyzer_area.set_accessible_role(Gtk.AccessibleRole.PRESENTATION)
        self.analyzer_area.set_draw_func(self.on_analyzer_draw)
        graph_overlay.add_overlay(self.analyzer_area)

        self.graph_response_area = Gtk.DrawingArea()
        self.graph_response_area.set_content_width(900)
        self.graph_response_area.set_content_height(240)
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

        graph_meta = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self.focus_label.add_css_class("heading")
        self.band_count_label.add_css_class("dim-label")
        graph_meta.append(self.focus_label)
        graph_meta.append(self.band_count_label)
        graph_shell.append(graph_meta)
        left_column.append(graph_shell)

        fader_shell = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        fader_shell.add_css_class("panel-card")
        fader_shell.add_css_class("quick-view-shell")

        fader_section = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        fader_section.set_margin_top(12)
        fader_section.set_margin_bottom(10)
        fader_section.set_margin_start(14)
        fader_section.set_margin_end(14)
        self.fader_title_label = Gtk.Label(label=f"{DEFAULT_ACTIVE_BANDS}-Band Fader Strip", xalign=0.0)
        self.fader_title_label.add_css_class("heading")
        self.fader_title_label.add_css_class("accent-heading")
        self.fader_title_label.set_tooltip_text("Drag Gain; Edit Frequency, Q, and Filter Type on the Selected Band")
        fader_section.append(self.fader_title_label)

        self.fader_scroller = Gtk.ScrolledWindow()
        self.fader_scroller.set_hexpand(True)
        self.fader_scroller.set_vexpand(False)
        self.fader_scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.NEVER)
        self.fader_scroller.set_min_content_height(230)
        self.fader_scroller.add_css_class("fader-scroller")

        fader_grid = Gtk.Grid(column_spacing=7, row_spacing=0)
        fader_grid.set_column_homogeneous(False)
        fader_grid.set_hexpand(False)
        fader_grid.set_margin_top(4)
        fader_grid.set_margin_bottom(4)
        fader_grid.set_margin_start(4)
        fader_grid.set_margin_end(4)

        for index in range(MAX_BANDS):
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            box.set_halign(Gtk.Align.CENTER)
            box.set_hexpand(True)
            box.set_size_request(76, -1)
            box.add_css_class("eq-band-box")
            band_click = Gtk.GestureClick()
            band_click.connect("pressed", self.on_band_card_pressed, index)
            box.add_controller(band_click)

            fader = EqBandFader(
                index,
                self.on_custom_band_fader_selected,
                self.on_custom_band_fader_changed,
                self.on_custom_band_frequency_changed,
                self.on_custom_band_q_changed,
                self.on_custom_band_mute_toggled,
                self.on_custom_band_solo_toggled,
                self.on_custom_band_edit_requested,
            )
            box.append(fader)

            self.band_fader_boxes.append(box)
            self.band_fader_widgets.append(fader)
            fader_grid.attach(box, index, 0, 1, 1)

        self.fader_scroller.set_child(fader_grid)
        fader_section.append(self.fader_scroller)
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
        self.bypass_switch.connect("notify::active", self.on_bypass_changed)
        self.route_switch.connect("notify::active", self.on_route_changed)
        self.connect("close-request", self.on_close_request)

        self.refresh_output_sinks()
        self.refresh_preset_list()
        self.sync_ui_from_state()

    def make_status_row(self, key: str, title: str) -> tuple[Gtk.Box, Gtk.Label, Gtk.Label]:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        row.add_css_class("system-row")

        text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        text_box.set_hexpand(True)

        title_label = Gtk.Label(label=title, xalign=0.0)
        title_label.add_css_class("metric-title")

        detail_label = Gtk.Label(xalign=0.0)
        detail_label.add_css_class("metric-detail")
        detail_label.add_css_class("dim-label")
        detail_label.set_wrap(True)
        detail_label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)

        value_label = Gtk.Label(xalign=1.0)
        value_label.set_halign(Gtk.Align.END)
        value_label.set_valign(Gtk.Align.CENTER)
        value_label.add_css_class("metric-value")
        value_label.set_ellipsize(Pango.EllipsizeMode.END)
        value_label.set_max_width_chars(15)

        text_box.append(title_label)
        text_box.append(detail_label)
        row.append(text_box)
        row.append(value_label)
        return row, value_label, detail_label

    def set_card_state(self, key: str, value: str, detail: str, warning: bool = False) -> None:
        labels = {
            "route": (self.route_value_label, self.route_detail_label),
            "output": (self.output_value_label, self.output_detail_label),
            "profile": (self.profile_value_label, self.profile_detail_label),
            "safety": (self.safety_value_label, self.safety_detail_label),
        }

        pair = labels.get(key)
        if pair is None:
            return

        value_label, detail_label = pair
        value_label.set_text(value)
        detail_label.set_text(detail)

        row = self.status_card_frames.get(key)
        if row is None:
            return

        if warning:
            row.add_css_class("system-row-warning")
        else:
            row.remove_css_class("system-row-warning")

    def install_css(self) -> None:
        css = b"""
        .toolbar-row {
            padding: 6px 10px;
            border-radius: 16px;
            border: 1px solid rgba(255, 255, 255, 0.06);
            background-color: rgba(30, 34, 40, 0.72);
        }

        .toolbar-button {
            padding: 3px 10px;
            min-height: 30px;
        }

        .toolbar-icon-button {
            padding: 0;
            min-width: 32px;
            min-height: 32px;
            border-radius: 999px;
        }

        .popover-action {
            min-width: 132px;
            padding: 6px 10px;
            border-radius: 10px;
        }

        .toolbar-select {
            min-height: 30px;
        }

        .route-box {
            padding: 2px 8px;
            border-radius: 999px;
            border: 1px solid rgba(255, 255, 255, 0.045);
            background-color: rgba(255, 255, 255, 0.04);
        }

        .toolbar-inline-state {
            min-width: 58px;
            padding: 3px 10px;
            border-radius: 999px;
            background-color: rgba(127, 145, 165, 0.14);
            color: rgba(223, 231, 239, 0.90);
            font-size: 9pt;
            font-weight: 700;
        }

        .toolbar-inline-state-live {
            background-color: rgba(78, 184, 109, 0.16);
            color: #75e493;
        }

        .toolbar-inline-state-bypass {
            background-color: rgba(127, 145, 165, 0.14);
            color: rgba(223, 231, 239, 0.86);
        }

        .utility-section {
            padding: 10px;
            border-radius: 18px;
            border: 1px solid rgba(255, 255, 255, 0.055);
            background-color: rgba(18, 24, 33, 0.66);
        }

        .utility-row {
            padding: 8px 10px;
            border-radius: 14px;
            background-color: rgba(255, 255, 255, 0.045);
        }

        .preset-row {
            margin-top: 2px;
        }

        .preset-state-chip {
            padding: 4px 10px;
            border-radius: 999px;
            font-size: 9pt;
            font-weight: 800;
        }

        .preset-state-saved {
            background-color: rgba(78, 184, 109, 0.14);
            color: #4eb86d;
        }

        .preset-state-modified {
            background-color: rgba(255, 178, 74, 0.16);
            color: #ffcb62;
        }

        .preset-state-unsaved {
            background-color: rgba(127, 145, 165, 0.14);
            color: rgba(223, 231, 239, 0.90);
        }

        .system-state-chip {
            padding: 4px 10px;
            border-radius: 999px;
            font-size: 9pt;
            font-weight: 800;
        }

        .system-state-live {
            background-color: rgba(78, 184, 109, 0.14);
            color: #62dc83;
        }

        .system-state-warning {
            background-color: rgba(255, 178, 74, 0.16);
            color: #ffcb62;
        }

        .system-state-bypass {
            background-color: rgba(127, 145, 165, 0.14);
            color: rgba(223, 231, 239, 0.88);
        }

        .system-row {
            padding: 8px 10px;
            border-radius: 14px;
            background-color: rgba(255, 255, 255, 0.045);
        }

        .preamp-row {
            padding-top: 7px;
            padding-bottom: 7px;
        }

        .system-row-warning {
            padding-left: 8px;
            border-left: 2px solid rgba(255, 178, 74, 0.75);
        }

        .system-row .metric-value {
            font-size: 10.5pt;
        }

        .system-path {
            margin-top: 2px;
            padding-top: 10px;
            border-top: 1px solid rgba(255, 255, 255, 0.06);
        }

        .metric-title {
            font-size: 9pt;
            font-weight: 700;
            letter-spacing: 0.06em;
            text-transform: uppercase;
            color: rgba(226, 233, 240, 0.72);
        }

        .metric-value {
            font-size: 13pt;
            font-weight: 800;
            color: #f7fbff;
        }

        .metric-detail {
            font-size: 9pt;
            color: rgba(219, 228, 236, 0.80);
        }

        .warning-banner {
            padding: 10px 12px;
            border-radius: 16px;
        }

        .warning-banner-alert {
            border: 1px solid rgba(255, 161, 72, 0.45);
            background-color: rgba(86, 50, 22, 0.55);
            color: #ffe0b2;
        }

        .panel-card {
            border-radius: 22px;
            border: 1px solid rgba(255, 255, 255, 0.08);
            background-image: linear-gradient(180deg, rgba(18, 27, 39, 0.98), rgba(12, 18, 28, 0.96));
        }

        .graph-shell-panel {
            padding: 12px;
            border-color: rgba(255, 255, 255, 0.06);
        }

        .graph-header {
            padding: 4px 2px 2px 2px;
        }

        .graph-header-title {
            color: #f7fbff;
        }

        .graph-chip {
            padding: 4px 10px;
            border-radius: 999px;
            background-color: rgba(82, 170, 214, 0.14);
            color: #9fe5ff;
            font-size: 9pt;
            font-weight: 700;
        }

        .graph-header scale trough {
            min-height: 4px;
        }

        .graph-header label {
            font-size: 9pt;
        }

        .graph-stage {
            border-radius: 18px;
            border: 1px solid rgba(255, 255, 255, 0.06);
            background-color: rgba(7, 12, 18, 0.80);
            padding: 8px;
        }

        .quick-view-shell {
            padding: 0;
        }

        .analyzer-state-chip {
            min-width: 42px;
        }

        .signal-chip-row {
            margin-top: 2px;
        }

        .signal-chip {
            padding: 6px 10px;
            border-radius: 11px;
            background-color: rgba(255, 255, 255, 0.05);
            border: 1px solid rgba(255, 255, 255, 0.07);
            color: #eef3f7;
        }

        .signal-arrow {
            color: rgba(225, 232, 239, 0.58);
        }

        .path-strip-detail {
            color: rgba(225, 232, 239, 0.70);
        }

        .accent-heading {
            color: #ffb24a;
        }

        .fader-scroller {
            min-height: 230px;
        }

        .eq-band-box {
            padding: 6px 5px 8px 5px;
            border-radius: 16px;
            background-color: rgba(255, 255, 255, 0.04);
            border: 1px solid rgba(255, 255, 255, 0.04);
        }

        """

        provider = Gtk.CssProvider()
        provider.load_from_data(css)
        display = Gdk.Display.get_default()
        if display is not None:
            Gtk.StyleContext.add_provider_for_display(
                display,
                provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
            )
