#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
uuid="mini-eq@bhack.github.io"
extension_dir="$repo_root/extensions/gnome-shell/$uuid"
fake_control="$repo_root/tools/gnome-shell-extension/fake_mini_eq_control.py"
pack_extension="$repo_root/tools/pack_gnome_shell_extension.sh"
dev_home="${XDG_RUNTIME_DIR:-/tmp}/mini-eq-gnome-shell-dev"
dev_data_home="$dev_home/data"
dev_config_home="$dev_home/config"
dev_cache_home="$dev_home/cache"
bundle="$dev_home/$uuid.shell-extension.zip"
mode="fake"

usage() {
    cat >&2 <<EOF
Usage: $0 [--fake-control|--no-fake-control|--real-session-install]

  --fake-control          Start isolated devkit Shell with fake Mini EQ D-Bus control service. Default.
  --no-fake-control       Start isolated devkit Shell without a control service; tests disconnected UI.
  --real-session-install  Install/reload the extension in the real GNOME session for real app integration.
EOF
}

while (($# > 0)); do
    case "$1" in
        --fake-control)
            mode="fake"
            ;;
        --no-fake-control)
            mode="no-fake"
            ;;
        --real-session-install)
            mode="real-session"
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            usage
            exit 2
            ;;
    esac
    shift
done

if [[ ! -d "$extension_dir" ]]; then
    echo "Extension source not found: $extension_dir" >&2
    exit 1
fi

if [[ ! -x "$pack_extension" ]]; then
    echo "Extension pack helper not found or not executable: $pack_extension" >&2
    exit 1
fi

if [[ "$mode" == "fake" && ! -x "$fake_control" ]]; then
    echo "Fake control service not found or not executable: $fake_control" >&2
    exit 1
fi

rm -rf "$dev_home"
mkdir -p "$dev_home" "$dev_data_home/gnome-shell/extensions" "$dev_config_home" "$dev_cache_home"

"$pack_extension" "$dev_home" >/dev/null

if [[ "$mode" == "real-session" ]]; then
    gnome-extensions disable "$uuid" >/dev/null 2>&1 || true
    gnome-extensions install --force "$bundle" >/dev/null
    if gnome-extensions enable "$uuid" >/dev/null 2>&1; then
        echo "Installed and reloaded $uuid in the real GNOME session." >&2
        echo "If changed JavaScript or bundled assets are still not visible on Wayland, log out and back in once." >&2
    else
        python3 - "$uuid" <<'PY'
import ast
import subprocess
import sys

uuid = sys.argv[1]
enabled = ast.literal_eval(subprocess.check_output(
    ["gsettings", "get", "org.gnome.shell", "enabled-extensions"],
    text=True,
))
disabled = ast.literal_eval(subprocess.check_output(
    ["gsettings", "get", "org.gnome.shell", "disabled-extensions"],
    text=True,
))

if uuid not in enabled:
    enabled.append(uuid)
disabled = [extension for extension in disabled if extension != uuid]
subprocess.run(
    ["gsettings", "set", "org.gnome.shell", "enabled-extensions", repr(enabled)],
    check=True,
)
subprocess.run(
    ["gsettings", "set", "org.gnome.shell", "disabled-extensions", repr(disabled)],
    check=True,
)
PY
        echo "Installed $uuid and requested enablement in GNOME Shell settings." >&2
        echo "If the indicator is still missing, log out and back in once." >&2
    fi
    echo "Run Mini EQ from this checkout for real controls:" >&2
    echo "  PYTHONPATH=src .venv/bin/python -m mini_eq" >&2
    exit 0
fi

cp -a "$extension_dir" "$dev_data_home/gnome-shell/extensions/$uuid"

GSETTINGS_BACKEND=keyfile \
    XDG_CONFIG_HOME="$dev_config_home" \
    gsettings set org.gnome.shell enabled-extensions "['$uuid']"

export XDG_DATA_HOME="$dev_data_home"
export XDG_CONFIG_HOME="$dev_config_home"
export XDG_CACHE_HOME="$dev_cache_home"
export GSETTINGS_BACKEND=keyfile

echo "Using isolated GNOME Shell dev home: $dev_home" >&2
echo "Installed only extension: $uuid" >&2
echo "Mode: $mode" >&2
echo >&2
echo "When the nested Shell starts, look for a virtual monitor/devkit surface." >&2
echo "The top bar inside that nested Shell should show a 'Mini EQ' item." >&2
if [[ "$mode" == "fake" ]]; then
    echo "A fake Mini EQ D-Bus service is started inside the nested session." >&2
else
    echo "No Mini EQ D-Bus service is started; controls should show disconnected/disabled state." >&2
fi
echo "Stop this dev shell with Ctrl+C in this terminal." >&2
echo >&2

run_in_dev_bus() {
    local shell_command=("$@")
    if [[ "$mode" == "no-fake" ]]; then
        dbus-run-session -- "${shell_command[@]}"
        return
    fi

    dbus-run-session -- bash -euo pipefail -c '
        cleanup() {
            if [[ -n "${fake_pid:-}" ]]; then
                kill "$fake_pid" 2>/dev/null || true
                wait "$fake_pid" 2>/dev/null || true
            fi
        }
        trap cleanup EXIT INT TERM

        "$1" &
        fake_pid=$!
        sleep 0.5
        shift
        "$@"
    ' bash "$fake_control" "${shell_command[@]}"
}

if gnome-shell --help 2>&1 | grep -q -- '--devkit'; then
    if [[ ! -x /usr/libexec/mutter-devkit && ! -x /usr/lib/mutter-devkit ]] && ! command -v mutter-devkit >/dev/null 2>&1; then
        echo "gnome-shell supports --devkit, but mutter-devkit is missing." >&2
        echo "On Debian/Ubuntu-like systems, install: sudo apt install mutter-dev-bin" >&2
        exit 1
    fi

    echo "Starting nested GNOME Shell devkit." >&2
    run_in_dev_bus gnome-shell --devkit
    exit $?
fi

echo "Starting nested GNOME Shell Wayland session." >&2
run_in_dev_bus env MUTTER_DEBUG_DUMMY_MODE_SPECS=1280x800 gnome-shell --nested --wayland
