from __future__ import annotations

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")

from gi.repository import Adw, Gtk, Pango

from .window_utils import set_accessible_label


class MiniEqWindowUtilityPaneMixin:
    def make_preset_section(self) -> Gtk.Box:
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
        self.bypass_switch.set_valign(Gtk.Align.CENTER)
        set_accessible_label(self.bypass_switch, "Equalized Audio")
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

        return system_section, monitor_panel
