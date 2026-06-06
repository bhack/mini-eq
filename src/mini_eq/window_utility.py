from __future__ import annotations

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")

from gi.repository import Adw, Gtk, Pango

from .window_utils import (
    bind_label_to_control,
    make_ellipsizing_string_list_factory,
    set_accessible_description,
    set_accessible_label,
)


class MiniEqWindowUtilityPaneMixin:
    def make_preset_section(self) -> Gtk.Box:
        preset_section = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        preset_section.add_css_class("utility-section")

        preset_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        preset_title = Gtk.Label(label="Current Curve", xalign=0.0)
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

        self.current_curve_state_label = Gtk.Label(xalign=0.0)
        self.current_curve_state_label.set_hexpand(True)
        self.current_curve_state_label.set_width_chars(1)
        self.current_curve_state_label.set_max_width_chars(28)
        self.current_curve_state_label.add_css_class("dim-label")
        self.current_curve_state_label.add_css_class("current-curve-label")
        self.current_curve_state_label.set_ellipsize(Pango.EllipsizeMode.END)
        set_accessible_label(self.current_curve_state_label, "Running Curve")

        self.current_curve_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.current_curve_row.add_css_class("utility-row")
        current_curve_label = Gtk.Label(label="Running", xalign=0.0)
        self.current_curve_row.append(current_curve_label)
        self.current_curve_row.append(self.current_curve_state_label)
        preset_section.append(self.current_curve_row)

        self.preset_combo.set_hexpand(True)
        self.preset_combo.set_enable_search(True)
        self.preset_combo.add_css_class("toolbar-select")
        self.preset_combo.set_factory(make_ellipsizing_string_list_factory(28))
        self.preset_combo.set_list_factory(make_ellipsizing_string_list_factory(42))
        set_accessible_label(self.preset_combo, "Load Preset")
        set_accessible_description(self.preset_combo, "Load a saved preset")

        preset_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        preset_row.add_css_class("utility-row")
        preset_label = Gtk.Label(label="Load Preset", xalign=0.0)
        bind_label_to_control(preset_label, self.preset_combo)
        preset_row.append(preset_label)
        preset_row.append(self.preset_combo)
        preset_section.append(preset_row)

        self.output_scope_state_label.set_hexpand(True)
        self.output_scope_state_label.add_css_class("dim-label")
        self.output_scope_state_label.add_css_class("output-scope-state-label")
        self.output_scope_state_label.set_ellipsize(Pango.EllipsizeMode.END)
        set_accessible_label(self.output_scope_state_label, "Auto Preset Scope")

        output_scope_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        output_scope_row.add_css_class("utility-row")
        output_scope_label = Gtk.Label(label="Scope", xalign=0.0)
        output_scope_row.append(output_scope_label)
        output_scope_row.append(self.output_scope_state_label)
        preset_section.append(output_scope_row)

        self.output_preset_state_label.set_hexpand(True)
        self.output_preset_state_label.add_css_class("dim-label")
        self.output_preset_state_label.set_ellipsize(Pango.EllipsizeMode.END)
        set_accessible_label(self.output_preset_state_label, "Auto Preset Status")

        output_preset_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        output_preset_row.add_css_class("utility-row")
        self.output_preset_scope_label = Gtk.Label(label="Auto Preset", xalign=0.0)
        bind_label_to_control(self.output_preset_scope_label, self.output_preset_switch)
        output_preset_row.append(self.output_preset_scope_label)
        output_preset_row.append(self.output_preset_state_label)
        self.output_preset_switch.set_valign(Gtk.Align.CENTER)
        set_accessible_label(self.output_preset_switch, "Auto Preset")
        self.output_preset_switch.connect("state-set", self.on_output_preset_switch_changed)
        output_preset_row.append(self.output_preset_switch)
        preset_section.append(output_preset_row)

        self.default_preset_state_label.set_hexpand(True)
        self.default_preset_state_label.add_css_class("dim-label")
        self.default_preset_state_label.set_ellipsize(Pango.EllipsizeMode.END)
        set_accessible_label(self.default_preset_state_label, "Unmatched Output Fallback Status")

        default_preset_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        default_preset_row.add_css_class("utility-row")
        default_preset_row.set_visible(False)
        self.default_preset_row = default_preset_row
        default_preset_label = Gtk.Label(label="Fallback", xalign=0.0)
        default_preset_row.append(default_preset_label)
        default_preset_row.append(self.default_preset_state_label)
        preset_section.append(default_preset_row)

        self.preset_save_button = Gtk.Button(label="Save")
        self.preset_save_button.set_can_shrink(True)
        self.preset_save_button.add_css_class("toolbar-button")
        self.preset_save_button.connect("clicked", self.on_preset_save_clicked)

        self.preset_more_popover = Gtk.Popover()
        self.preset_more_popover.add_css_class("preset-more-popover")
        preset_more_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        preset_more_box.add_css_class("preset-more-menu")
        preset_more_box.set_margin_top(6)
        preset_more_box.set_margin_bottom(6)
        preset_more_box.set_margin_start(6)
        preset_more_box.set_margin_end(6)

        def append_preset_separator() -> Gtk.Separator:
            separator = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
            separator.add_css_class("preset-menu-separator")
            preset_more_box.append(separator)
            return separator

        def connect_preset_action(button: Gtk.Button, callback) -> None:
            def on_clicked(clicked_button: Gtk.Button) -> None:
                self.preset_more_popover.popdown()
                callback(clicked_button)

            button.connect("clicked", on_clicked)

        def make_preset_action(label: str, callback, *, destructive: bool = False) -> tuple[Gtk.Button, Gtk.Label]:
            button = Gtk.Button()
            button.set_can_shrink(True)
            button.set_hexpand(True)
            button.add_css_class("popover-action")
            button.add_css_class("flat")
            if destructive:
                button.add_css_class("destructive-action")
            action_label = Gtk.Label(label=label, xalign=0.0)
            action_label.set_hexpand(True)
            action_label.set_ellipsize(Pango.EllipsizeMode.END)
            button.set_child(action_label)
            connect_preset_action(button, callback)
            preset_more_box.append(button)
            return button, action_label

        self.preset_save_as_button, self.preset_save_as_button_label = make_preset_action(
            "Save As…",
            self.on_preset_save_as_clicked,
        )

        self.preset_revert_button, self.preset_revert_button_label = make_preset_action(
            "Revert",
            self.on_preset_revert_clicked,
        )
        self.preset_revert_button.set_tooltip_text("Loaded Preset")

        self.preset_reset_to_neutral_button, self.preset_reset_to_neutral_button_label = make_preset_action(
            "Reset to Neutral",
            self.on_preset_reset_to_neutral_clicked,
        )

        self.preset_default_separator = append_preset_separator()

        self.preset_default_heading = Gtk.Label(label="Unmatched Outputs", xalign=0.0)
        self.preset_default_heading.add_css_class("popover-section-heading")
        preset_more_box.append(self.preset_default_heading)

        self.default_preset_set_button, self.default_preset_set_button_label = make_preset_action(
            "Use Loaded as Fallback",
            self.on_use_preset_as_fallback_clicked,
        )

        self.default_preset_clear_button, self.default_preset_clear_button_label = make_preset_action(
            "Bypass Unmatched Outputs",
            self.on_bypass_unmatched_outputs_clicked,
        )

        self.preset_file_separator = append_preset_separator()

        self.preset_import_button, self.preset_import_button_label = make_preset_action(
            "Import Preset…",
            self.on_preset_import_clicked,
        )

        self.preset_export_button, self.preset_export_button_label = make_preset_action(
            "Export Preset…",
            self.on_preset_export_clicked,
        )

        self.preset_library_separator = append_preset_separator()

        self.preset_delete_button, self.preset_delete_button_label = make_preset_action(
            "Delete Preset",
            self.on_preset_delete_clicked,
            destructive=True,
        )

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

        return preset_section

    def make_system_section(self) -> tuple[Gtk.Box, Gtk.Box]:
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
        compare_title = Gtk.Label(label="A/B", xalign=0.0)
        compare_title.add_css_class("metric-title")
        bind_label_to_control(compare_title, self.bypass_switch)
        compare_panel.append(compare_title)
        compare_spacer = Gtk.Box()
        compare_spacer.set_hexpand(True)
        compare_panel.append(compare_spacer)
        self.bypass_switch.set_tooltip_text("A/B Compare")
        self.bypass_switch.set_valign(Gtk.Align.CENTER)
        set_accessible_label(self.bypass_switch, "A/B Compare")
        compare_panel.append(self.bypass_switch)
        system_section.append(compare_panel)

        system_section.append(self.make_headroom_panel())

        analyzer_settings_popover = Gtk.Popover()
        analyzer_settings_group = Adw.PreferencesGroup()
        analyzer_settings_group.set_margin_top(8)
        analyzer_settings_group.set_margin_bottom(8)
        analyzer_settings_group.set_margin_start(8)
        analyzer_settings_group.set_margin_end(8)
        analyzer_settings_popover.set_child(analyzer_settings_group)
        analyzer_settings_button = Gtk.MenuButton()
        analyzer_settings_button.set_can_shrink(True)
        analyzer_settings_button.set_icon_name("preferences-system-symbolic")
        analyzer_settings_button.set_tooltip_text("Monitor Settings")
        set_accessible_label(analyzer_settings_button, "Monitor Settings")
        analyzer_settings_button.set_valign(Gtk.Align.CENTER)
        analyzer_settings_button.add_css_class("toolbar-icon-button")
        analyzer_settings_button.add_css_class("monitor-settings-button")
        analyzer_settings_button.set_popover(analyzer_settings_popover)

        monitor_panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.monitor_panel = monitor_panel
        monitor_panel.add_css_class("monitor-strip")
        monitor_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.monitor_header = monitor_header
        monitor_title = Gtk.Label(label="Monitor", xalign=0.0)
        self.monitor_title_label = monitor_title
        monitor_title.add_css_class("metric-title")
        bind_label_to_control(monitor_title, self.analyzer_switch)
        monitor_header.append(monitor_title)
        monitor_header_spacer = Gtk.Box()
        monitor_header_spacer.set_hexpand(True)
        monitor_header.append(monitor_header_spacer)

        monitor_header.append(analyzer_settings_button)
        self.analyzer_switch.set_valign(Gtk.Align.CENTER)
        set_accessible_label(self.analyzer_switch, "Monitor")
        monitor_header.append(self.analyzer_switch)
        monitor_panel.append(monitor_header)

        monitor_detail_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.monitor_detail_row = monitor_detail_row
        monitor_detail_row.add_css_class("monitor-detail-row")

        self.analyzer_summary_label.add_css_class("dim-label")
        self.analyzer_summary_label.add_css_class("numeric")
        self.analyzer_summary_label.set_ellipsize(Pango.EllipsizeMode.END)
        self.analyzer_loudness_meter_area.add_css_class("loudness-meter-area")
        self.analyzer_loudness_meter_area.set_content_width(104)
        self.analyzer_loudness_meter_area.set_content_height(16)
        self.analyzer_loudness_meter_area.set_hexpand(True)
        self.analyzer_loudness_meter_area.set_valign(Gtk.Align.CENTER)
        self.analyzer_loudness_meter_area.set_accessible_role(Gtk.AccessibleRole.IMG)
        set_accessible_label(self.analyzer_loudness_meter_area, "Loudness Meter")
        set_accessible_description(
            self.analyzer_loudness_meter_area,
            "Current LUFS meter with peak marker",
        )
        self.analyzer_loudness_meter_area.set_draw_func(self.on_loudness_meter_draw)
        monitor_detail_row.append(self.analyzer_loudness_meter_area)

        self.analyzer_loudness_value_label.add_css_class("numeric")
        self.analyzer_loudness_value_label.add_css_class("loudness-value-label")
        self.analyzer_loudness_value_label.set_width_chars(8)
        set_accessible_label(self.analyzer_loudness_value_label, "Loudness Value")
        monitor_detail_row.append(self.analyzer_loudness_value_label)
        monitor_panel.append(monitor_detail_row)
        self.monitor_tooltip_widgets = (
            monitor_panel,
            monitor_header,
            monitor_title,
            monitor_detail_row,
            self.analyzer_loudness_meter_area,
            self.analyzer_loudness_value_label,
        )

        system_section.append(monitor_panel)

        smoothing_row = Adw.ActionRow(title="Smoothing")
        set_accessible_label(self.analyzer_smoothing_scale, "Monitor Smoothing")
        self.analyzer_smoothing_scale.set_size_request(116, -1)
        smoothing_row.add_suffix(self.analyzer_smoothing_scale)
        self.analyzer_smoothing_label.add_css_class("dim-label")
        smoothing_row.add_suffix(self.analyzer_smoothing_label)
        analyzer_settings_group.add(smoothing_row)

        display_gain_row = Adw.ActionRow(title="Display Gain")
        display_gain_row.set_tooltip_text("Monitor Bar Gain")
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

        return system_section, monitor_panel
