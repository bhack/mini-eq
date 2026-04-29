# Mini EQ GNOME Shell Extension

This is the companion GNOME Shell extension for quick panel access to Mini EQ.
It is developed in this repository because it depends on the Mini EQ D-Bus
control API and should change with the app when that API changes.

The publishable extension source is:

```text
extensions/gnome-shell/mini-eq@bhack.github.io/
```

Current scope:

- Show a Mini EQ indicator in the GNOME Shell panel.
- Show a compact analyzer while system-wide EQ is active.
- Focus or present the Mini EQ app from the panel menu.
- Control Mini EQ system-wide routing and equalized/original audio state.
- List and load saved Mini EQ presets over the Mini EQ D-Bus control API.

Install for local testing:

```bash
mkdir -p ~/.local/share/gnome-shell/extensions
rm -rf ~/.local/share/gnome-shell/extensions/mini-eq@bhack.github.io
cp -a extensions/gnome-shell/mini-eq@bhack.github.io ~/.local/share/gnome-shell/extensions/
gnome-extensions enable mini-eq@bhack.github.io
```

Reload after edits:

```bash
gnome-extensions disable mini-eq@bhack.github.io
gnome-extensions enable mini-eq@bhack.github.io
```

On Wayland, if GNOME Shell does not pick up a new extension cleanly, log out and
log back in. On X11, `Alt+F2`, `r`, Enter restarts GNOME Shell.

For faster iteration, use a nested development Shell instead of the real desktop:

```bash
tools/run_gnome_extension_dev_shell.sh
```

GNOME 49 and newer use `gnome-shell --devkit` for this workflow. If the command
logs `Failed to launch devkit: ... mutter-devkit ... No such file or directory`,
install the distro package that provides `mutter-devkit` before relying on the
nested development session.

For live control testing, run Mini EQ from this checkout so the app exposes the
control API:

```bash
PYTHONPATH=src .venv/bin/python -m mini_eq
```

Build the upload bundle:

```bash
python3 tools/check_gnome_shell_extension.py
tools/pack_gnome_shell_extension.sh
```

The generated zip is written under `dist/gnome-shell-extension/`, which is
ignored by Git.

Capture a privacy-safe screenshot for extensions.gnome.org from the nested
development Shell when EGO asks for one:

```bash
tools/run_gnome_extension_dev_shell.sh --fake-control
```

In the nested Shell window, open the Mini EQ indicator menu, use the normal GNOME
screenshot UI, crop to the nested Shell panel/menu only, and save the image under
`dist/gnome-shell-extension/`. Keep the screenshot free of personal device names,
accounts, usernames, hostnames, local paths, and real desktop content. The fake
control service supplies deterministic demo state for this purpose.

Before uploading to extensions.gnome.org:

- Test on every GNOME Shell version listed in `metadata.json`.
- Do not list future Shell versions.
- Keep the extension bundle small and reviewable.
- Keep app behavior graceful when Mini EQ is not running or the D-Bus name is
  unavailable.
