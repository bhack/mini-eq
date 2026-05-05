from __future__ import annotations

import gi

gi.require_version("Adw", "1")

from gi.repository import Adw

from .background import request_background_permission, request_start_at_login


class MiniEqWindowPreferencesMixin:
    background_portal_request = None

    def show_preferences_dialog(self) -> None:
        application = self.get_application()
        background_mode = bool(getattr(application, "background_mode", False))
        start_at_login = bool(getattr(application, "start_at_login", False))
        updating_rows = False

        dialog = Adw.PreferencesDialog(title="Preferences")
        page = Adw.PreferencesPage()
        group = Adw.PreferencesGroup(title="Background")

        background_row = Adw.SwitchRow(
            title="Keep Running in Background",
            subtitle="Closing the window keeps Mini EQ active for this session.",
        )
        background_row.set_active(background_mode)
        group.add(background_row)

        start_row = Adw.SwitchRow(
            title="Start at Login",
            subtitle="Start Mini EQ hidden when you sign in.",
        )
        start_row.set_active(start_at_login)
        start_row.set_sensitive(background_mode)
        group.add(start_row)

        page.add(group)
        dialog.add(page)

        def sync_rows(background_enabled: bool, start_enabled: bool) -> None:
            nonlocal updating_rows
            updating_rows = True
            try:
                background_row.set_active(background_enabled)
                start_row.set_active(start_enabled)
                start_row.set_sensitive(background_enabled)
            finally:
                updating_rows = False

        def set_busy(busy: bool) -> None:
            background_row.set_sensitive(not busy)
            start_row.set_sensitive(not busy and background_row.get_active())

        def show_error(message: str) -> None:
            self.set_status(message)

        def on_background_changed(row: Adw.SwitchRow, _param: object) -> None:
            if updating_rows:
                return

            desired = row.get_active()
            previous_background = bool(getattr(application, "background_mode", False))
            previous_start = bool(getattr(application, "start_at_login", False))
            set_busy(True)

            def finish_background_change(_background_allowed: bool, _autostart_enabled: bool, error: Exception | None):
                self.background_portal_request = None
                if error is not None:
                    sync_rows(previous_background, previous_start)
                    set_busy(False)
                    show_error(str(error))
                    return

                application.set_background_mode(desired)
                if not desired and previous_start:
                    application.set_start_at_login(False)
                sync_rows(
                    bool(getattr(application, "background_mode", False)),
                    bool(getattr(application, "start_at_login", False)),
                )
                set_busy(False)

            if not desired and previous_start:

                def finish_autostart_disable(
                    _background_allowed: bool,
                    _autostart_enabled: bool,
                    error: Exception | None,
                ) -> None:
                    if error is not None:
                        self.background_portal_request = None
                        sync_rows(previous_background, previous_start)
                        set_busy(False)
                        show_error(str(error))
                        return
                    self.background_portal_request = request_background_permission(False, finish_background_change)

                self.background_portal_request = request_start_at_login(False, finish_autostart_disable)
                return

            self.background_portal_request = request_background_permission(desired, finish_background_change)

        def on_start_at_login_changed(row: Adw.SwitchRow, _param: object) -> None:
            if updating_rows:
                return

            desired = row.get_active()
            previous_start = bool(getattr(application, "start_at_login", False))
            if desired and not bool(getattr(application, "background_mode", False)):
                sync_rows(False, False)
                show_error("Enable background mode before Start at Login")
                return

            set_busy(True)

            def finish_start_at_login_change(
                _background_allowed: bool,
                autostart_enabled: bool,
                error: Exception | None,
            ) -> None:
                self.background_portal_request = None
                if error is not None or (desired and not autostart_enabled):
                    sync_rows(bool(getattr(application, "background_mode", False)), previous_start)
                    set_busy(False)
                    show_error(str(error) if error is not None else "Start at Login was not enabled")
                    return

                application.set_start_at_login(desired)
                sync_rows(
                    bool(getattr(application, "background_mode", False)),
                    bool(getattr(application, "start_at_login", False)),
                )
                set_busy(False)

            self.background_portal_request = request_start_at_login(desired, finish_start_at_login_change)

        background_row.connect("notify::active", on_background_changed)
        start_row.connect("notify::active", on_start_at_login_changed)

        dialog.present(self)
