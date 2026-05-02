// SPDX-License-Identifier: GPL-3.0-or-later

import Clutter from 'gi://Clutter';
import Gio from 'gi://Gio';
import GObject from 'gi://GObject';
import GLib from 'gi://GLib';
import Shell from 'gi://Shell';
import St from 'gi://St';

import {Extension, gettext as _} from 'resource:///org/gnome/shell/extensions/extension.js';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';

const BUS_NAME = 'io.github.bhack.mini-eq';
const OBJECT_PATH = '/io/github/bhack/mini_eq/Control';
const INTERFACE_NAME = 'io.github.bhack.MiniEq.Control';
const APP_DESKTOP_ID = 'io.github.bhack.mini-eq.desktop';
const PANEL_ANALYZER_BARS = 10;
const PANEL_ANALYZER_WIDTH = 2;
const PANEL_ANALYZER_HEIGHT = 14;
const PANEL_ANALYZER_GAP = 1;
const PANEL_ANALYZER_VISUAL_GAIN = 1.15;
const PANEL_ANALYZER_ACTIVE_THRESHOLD = 0.02;
const PANEL_ANALYZER_MIN_ACTIVE_HEIGHT = 3;
const PANEL_ANALYZER_ACTIVE_COLOR = 'rgba(127, 213, 232, 0.96)';
const PANEL_ANALYZER_DIM_COLOR = 'rgba(255, 255, 255, 0.24)';
const PANEL_ANALYZER_STANDBY_COLOR = 'rgba(255, 255, 255, 0.16)';
const SHELL_ICON_FILE = 'mini-eq-symbolic.svg';

function unpackValue(value) {
    if (value?.deepUnpack)
        return value.deepUnpack();
    return value;
}

function getEventTime(event) {
    if (event?.get_time)
        return event.get_time();
    return global.get_current_time();
}

function panelAnalyzerDisplayLevel(level) {
    const normalized = Math.max(0.0, Math.min(1.0, Number(level) || 0.0));
    if (normalized <= PANEL_ANALYZER_ACTIVE_THRESHOLD)
        return 0.0;
    return Math.min(1.0, normalized * PANEL_ANALYZER_VISUAL_GAIN);
}

const MiniEqIndicator = GObject.registerClass(
class MiniEqIndicator extends PanelMenu.Button {
    constructor(extensionPath) {
        super(0.5, _('Mini EQ'));

        this._disposed = false;
        this._updating = false;
        this._refreshSourceId = 0;
        this._watchId = 0;
        this._signalId = 0;
        this._analyzerSignalId = 0;
        this._presetsSignalId = 0;
        this.connect('destroy', () => this._beginDispose());
        this._presetItems = [];
        this._analyzerBars = [];
        this._analyzerBarHeights = [];
        this._analyzerBarStyles = [];
        this._panelAnalyzerDimColor = PANEL_ANALYZER_STANDBY_COLOR;
        this._running = false;
        this._routed = false;
        this._eqEnabled = false;
        this.visible = false;

        const box = new St.BoxLayout({
            style_class: 'panel-status-menu-box',
            y_align: Clutter.ActorAlign.CENTER,
        });
        const iconPath = GLib.build_filenamev([extensionPath, SHELL_ICON_FILE]);
        this._icon = new St.Icon({
            gicon: Gio.icon_new_for_string(iconPath),
            style_class: 'system-status-icon',
            y_align: Clutter.ActorAlign.CENTER,
        });
        box.add_child(this._icon);
        box.add_child(this._buildPanelAnalyzer());
        this.add_child(box);

        this._statusItem = new PopupMenu.PopupMenuItem(_('Mini EQ is not running'));
        this._statusItem.setSensitive(false);
        this.menu.addMenuItem(this._statusItem);

        this._outputPresetItem = new PopupMenu.PopupMenuItem(_('Output preset: None'));
        this._outputPresetItem.setSensitive(false);
        this.menu.addMenuItem(this._outputPresetItem);

        this._routingItem = new PopupMenu.PopupSwitchMenuItem(_('System-wide EQ'), false);
        this._routingItem.connect('toggled', (_item, state) => {
            if (!this._updating)
                this._setRoutingEnabled(state);
        });
        this.menu.addMenuItem(this._routingItem);

        this._eqItem = new PopupMenu.PopupSwitchMenuItem(_('Equalized Audio'), false);
        this._eqItem.connect('toggled', (_item, state) => {
            if (!this._updating)
                this._setEqEnabled(state);
        });
        this.menu.addMenuItem(this._eqItem);

        this._presetsItem = new PopupMenu.PopupSubMenuMenuItem(_('Presets'));
        this.menu.addMenuItem(this._presetsItem);

        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

        const openItem = new PopupMenu.PopupMenuItem(_('Show Mini EQ'));
        openItem.connect('activate', (_item, event) => {
            this._showWindow(event);
            this._scheduleRefresh(1000);
        });
        this.menu.addMenuItem(openItem);

        this._signalId = Gio.DBus.session.signal_subscribe(
            BUS_NAME,
            INTERFACE_NAME,
            'StateChanged',
            OBJECT_PATH,
            null,
            Gio.DBusSignalFlags.NONE,
            (_connection, _sender, _objectPath, _interfaceName, _signalName, parameters) => {
                if (this._disposed)
                    return;
                const [state] = parameters.deepUnpack();
                this._applyState(state);
            });

        this._analyzerSignalId = Gio.DBus.session.signal_subscribe(
            BUS_NAME,
            INTERFACE_NAME,
            'AnalyzerLevelsChanged',
            OBJECT_PATH,
            null,
            Gio.DBusSignalFlags.NONE,
            (_connection, _sender, _objectPath, _interfaceName, _signalName, parameters) => {
                if (this._disposed)
                    return;
                const [levels] = parameters.deepUnpack();
                this._applyAnalyzerLevels(levels);
            });

        this._presetsSignalId = Gio.DBus.session.signal_subscribe(
            BUS_NAME,
            INTERFACE_NAME,
            'PresetsChanged',
            OBJECT_PATH,
            null,
            Gio.DBusSignalFlags.NONE,
            () => {
                if (!this._disposed)
                    this._refreshPresets();
            });

        this._setDisconnectedState();
        this._watchId = Gio.bus_watch_name(
            Gio.BusType.SESSION,
            BUS_NAME,
            Gio.BusNameWatcherFlags.NONE,
            () => {
                this._refreshState();
                this._refreshPresets();
            },
            () => this._setDisconnectedState());
    }

    _beginDispose() {
        if (this._disposed)
            return;

        this._disposed = true;

        if (this._refreshSourceId) {
            GLib.source_remove(this._refreshSourceId);
            this._refreshSourceId = 0;
        }

        if (this._signalId) {
            Gio.DBus.session.signal_unsubscribe(this._signalId);
            this._signalId = 0;
        }

        if (this._analyzerSignalId) {
            Gio.DBus.session.signal_unsubscribe(this._analyzerSignalId);
            this._analyzerSignalId = 0;
        }

        if (this._presetsSignalId) {
            Gio.DBus.session.signal_unsubscribe(this._presetsSignalId);
            this._presetsSignalId = 0;
        }

        if (this._watchId) {
            Gio.bus_unwatch_name(this._watchId);
            this._watchId = 0;
        }

        this._analyzerBars = [];
        this._analyzerBarHeights = [];
        this._analyzerBarStyles = [];
    }

    destroy() {
        this._beginDispose();
        super.destroy();
    }

    _scheduleRefresh(delayMs) {
        if (this._disposed)
            return;

        if (this._refreshSourceId)
            GLib.source_remove(this._refreshSourceId);

        this._refreshSourceId = GLib.timeout_add(GLib.PRIORITY_DEFAULT, delayMs, () => {
            this._refreshSourceId = 0;
            if (this._disposed)
                return GLib.SOURCE_REMOVE;

            this._refreshState();
            this._refreshPresets();
            return GLib.SOURCE_REMOVE;
        });
    }

    _call(method, parameters, replyType, callback, onError = null) {
        Gio.DBus.session.call(
            BUS_NAME,
            OBJECT_PATH,
            INTERFACE_NAME,
            method,
            parameters,
            replyType,
            Gio.DBusCallFlags.NONE,
            -1,
            null,
            (_connection, result) => {
                if (this._disposed) {
                    try {
                        Gio.DBus.session.call_finish(result);
                    } catch (_error) {
                    }
                    return;
                }

                try {
                    const reply = Gio.DBus.session.call_finish(result);
                    callback?.(reply);
                } catch (_error) {
                    if (onError)
                        onError();
                    else
                        this._scheduleRefresh(500);
                }
            });
    }

    _refreshState() {
        this._call('GetState', null, new GLib.VariantType('(a{sv})'), reply => {
            const [state] = reply.deepUnpack();
            this._applyState(state);
        }, () => this._setDisconnectedState());
    }

    _refreshPresets() {
        this._call('ListPresets', null, new GLib.VariantType('(as)'), reply => {
            const [presets] = reply.deepUnpack();
            this._setPresets(presets);
        }, () => this._setPresets([]));
    }

    _setEqEnabled(enabled) {
        this._call('SetEqEnabled', new GLib.Variant('(b)', [enabled]), null, () => {
            this._refreshState();
        });
    }

    _setRoutingEnabled(enabled) {
        this._call('SetRoutingEnabled', new GLib.Variant('(b)', [enabled]), null, () => {
            this._refreshState();
        });
    }

    _presentWindow() {
        this._call('PresentWindow', null, null, () => {});
    }

    _showWindow(event) {
        const app = Shell.AppSystem.get_default().lookup_app(APP_DESKTOP_ID);
        const windows = app?.get_windows().filter(window => !window.skip_taskbar) ?? [];
        const activeWorkspace = global.workspace_manager.get_active_workspace();
        const window = windows.find(candidate => candidate.get_workspace() === activeWorkspace) ?? windows[0];

        if (window) {
            Main.activateWindow(window, getEventTime(event));
            return;
        }

        this._presentWindow();
    }

    _setPreset(name) {
        this._call('SetPreset', new GLib.Variant('(s)', [name]), null, () => {
            this._refreshState();
            this._refreshPresets();
        });
    }

    _applyState(state) {
        if (this._disposed)
            return;

        const running = Boolean(unpackValue(state.running));
        const eqEnabled = Boolean(unpackValue(state.eq_enabled));
        const routed = Boolean(unpackValue(state.routed));
        const presetName = unpackValue(state.preset_name) || _('Current State');
        const outputPresetName = unpackValue(state.output_preset_name) || '';

        this._running = running;
        this._routed = routed;
        this._eqEnabled = eqEnabled;
        this.visible = running;
        this._syncPanelStateStyle(running, routed, eqEnabled);
        this._updating = true;
        try {
            this._routingItem.setToggleState(routed);
            this._eqItem.setToggleState(eqEnabled);
        } finally {
            this._updating = false;
        }

        if (!running || !routed || !eqEnabled)
            this._setAnalyzerLevels([]);

        this._routingItem.setSensitive(running);
        this._eqItem.setSensitive(running && routed);
        this._presetsItem.setSensitive(running);
        this._presetsItem.label.text = running ? _('Preset: %s').format(presetName) : _('Presets');
        this._statusItem.label.text = this._statusText(running, routed, eqEnabled);
        this._outputPresetItem.label.text = this._outputPresetText(running, outputPresetName);
    }

    _setDisconnectedState() {
        this._running = false;
        this._routed = false;
        this._eqEnabled = false;
        this.visible = false;
        this._syncPanelStateStyle(false, false, false);
        this._updating = true;
        try {
            this._routingItem.setToggleState(false);
            this._eqItem.setToggleState(false);
        } finally {
            this._updating = false;
        }

        this._routingItem.setSensitive(false);
        this._eqItem.setSensitive(false);
        this._presetsItem.setSensitive(false);
        this._presetsItem.label.text = _('Presets');
        this._statusItem.label.text = _('Mini EQ is not running');
        this._outputPresetItem.label.text = _('Output preset: None');
        this._setAnalyzerLevels([]);
        this._setPresets([]);
    }

    _statusText(running, routed, eqEnabled) {
        if (!running)
            return _('Mini EQ is not running');
        if (routed && eqEnabled)
            return _('System-wide EQ on');
        if (routed)
            return _('Original audio selected');
        return _('System-wide EQ off');
    }

    _outputPresetText(running, presetName) {
        if (!running || !presetName)
            return _('Output preset: None');
        return _('Output preset: %s').format(presetName);
    }

    _applyAnalyzerLevels(levels) {
        if (this._disposed)
            return;

        this._setAnalyzerLevels(this._running && this._routed && this._eqEnabled ? levels : []);
    }

    _syncPanelStateStyle(running, routed, eqEnabled) {
        if (!running) {
            this._icon.opacity = 0;
            this._panelAnalyzerDimColor = PANEL_ANALYZER_STANDBY_COLOR;
        } else if (routed && eqEnabled) {
            this._icon.opacity = 255;
            this._panelAnalyzerDimColor = PANEL_ANALYZER_DIM_COLOR;
        } else if (routed) {
            this._icon.opacity = 190;
            this._panelAnalyzerDimColor = PANEL_ANALYZER_STANDBY_COLOR;
        } else {
            this._icon.opacity = 160;
            this._panelAnalyzerDimColor = PANEL_ANALYZER_STANDBY_COLOR;
        }
    }

    _buildPanelAnalyzer() {
        const analyzer = new St.BoxLayout({
            y_align: Clutter.ActorAlign.CENTER,
            style: `height: ${PANEL_ANALYZER_HEIGHT}px; spacing: ${PANEL_ANALYZER_GAP}px;`,
        });
        analyzer.set_height(PANEL_ANALYZER_HEIGHT);
        analyzer.set_width((PANEL_ANALYZER_WIDTH * PANEL_ANALYZER_BARS) + (PANEL_ANALYZER_GAP * (PANEL_ANALYZER_BARS - 1)));

        for (let index = 0; index < PANEL_ANALYZER_BARS; index++) {
            const bar = new St.Widget({
                y_align: Clutter.ActorAlign.END,
                style: this._barStyle(false),
            });
            bar.set_size(PANEL_ANALYZER_WIDTH, 2);
            analyzer.add_child(bar);
            this._analyzerBars.push(bar);
            this._analyzerBarHeights.push(2);
            this._analyzerBarStyles.push(this._barStyle(false));
        }

        return analyzer;
    }

    _setAnalyzerLevels(levels) {
        if (this._disposed)
            return;

        for (let index = 0; index < this._analyzerBars.length; index++) {
            const normalized = panelAnalyzerDisplayLevel(levels[index] ?? 0.0);
            const active = normalized > 0.0;
            const height = active
                ? Math.max(PANEL_ANALYZER_MIN_ACTIVE_HEIGHT, Math.round(PANEL_ANALYZER_HEIGHT * normalized))
                : 2;
            const style = this._barStyle(active);

            if (this._analyzerBarHeights[index] !== height) {
                this._analyzerBars[index].set_size(PANEL_ANALYZER_WIDTH, height);
                this._analyzerBarHeights[index] = height;
            }

            if (this._analyzerBarStyles[index] !== style) {
                this._analyzerBars[index].set_style(style);
                this._analyzerBarStyles[index] = style;
            }
        }
    }

    _barStyle(active) {
        const color = active ? PANEL_ANALYZER_ACTIVE_COLOR : this._panelAnalyzerDimColor;
        return [
            `width: ${PANEL_ANALYZER_WIDTH}px`,
            `background-color: ${color}`,
            'border-radius: 1px',
        ].join('; ');
    }

    _setPresets(presets) {
        this._presetsItem.menu.removeAll();
        this._presetItems = [];

        if (!presets.length) {
            const item = new PopupMenu.PopupMenuItem(_('No saved presets'));
            item.setSensitive(false);
            this._presetsItem.menu.addMenuItem(item);
            return;
        }

        for (const preset of presets) {
            const item = new PopupMenu.PopupMenuItem(preset);
            item.connect('activate', () => this._setPreset(preset));
            this._presetsItem.menu.addMenuItem(item);
            this._presetItems.push(item);
        }
    }
});

export default class MiniEqControlsExtension extends Extension {
    enable() {
        this._indicator = new MiniEqIndicator(this.path);
        Main.panel.addToStatusArea(this.uuid, this._indicator, 0, 'right');
    }

    disable() {
        this._indicator?.destroy();
        this._indicator = null;
    }
}
