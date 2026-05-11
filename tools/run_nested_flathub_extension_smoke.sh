#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
uuid="mini-eq@bhack.github.io"
extension_dir="$repo_root/extensions/gnome-shell/$uuid"
app_ref="io.github.bhack.mini-eq//master"
log_file="${TMPDIR:-/tmp}/mini-eq-nested-flathub.log"
replace_running=false

usage() {
    cat >&2 <<EOF
Usage: $0 [--replace-running] [--app-ref APP_REF] [--log LOG_FILE]

  --replace-running  Stop an already running Mini EQ Flatpak before starting the nested smoke.
  --app-ref APP_REF  Installed Flatpak ref to run. Default: io.github.bhack.mini-eq//master.
  --log LOG_FILE     Log file for the nested Shell and app. Default: $log_file.

This starts an isolated GNOME Shell devkit with the extension from this checkout,
then launches the installed Flatpak app into that nested display and session bus.
Stop the smoke with Ctrl+C in this terminal.
EOF
}

while (($# > 0)); do
    case "$1" in
        --replace-running)
            replace_running=true
            ;;
        --app-ref)
            if (($# < 2)); then
                usage
                exit 2
            fi
            app_ref="$2"
            shift
            ;;
        --log)
            if (($# < 2)); then
                usage
                exit 2
            fi
            log_file="$2"
            shift
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

app_id="${app_ref%%//*}"
runtime_dir="${XDG_RUNTIME_DIR:-/tmp}"
dev_home="$(mktemp -d "$runtime_dir/mini-eq-nested-flathub.XXXXXX")"
dev_data_home="$dev_home/data"
dev_config_home="$dev_home/config"
dev_cache_home="$dev_home/cache"

cleanup() {
    rm -rf "$dev_home"
}
trap cleanup EXIT

if [[ ! -d "$extension_dir" ]]; then
    echo "Extension source not found: $extension_dir" >&2
    exit 1
fi

if ! gnome-shell --help 2>&1 | grep -q -- '--devkit'; then
    echo "This GNOME Shell does not support --devkit." >&2
    exit 1
fi

if [[ ! -x /usr/libexec/mutter-devkit && ! -x /usr/lib/mutter-devkit ]] && ! command -v mutter-devkit >/dev/null 2>&1; then
    echo "gnome-shell supports --devkit, but mutter-devkit is missing." >&2
    echo "On Debian/Ubuntu-like systems, install: sudo apt install mutter-dev-bin" >&2
    exit 1
fi

if ! flatpak --user info "$app_ref" >/dev/null 2>&1; then
    echo "Flatpak app ref is not installed in the user installation: $app_ref" >&2
    echo "Install or reinstall it first, for example:" >&2
    echo "  flatpak --user install -y --reinstall mini-eq-local $app_ref" >&2
    exit 1
fi

if flatpak ps --columns=application | grep -Fxq "$app_id"; then
    if [[ "$replace_running" != true ]]; then
        echo "$app_id is already running. Stop it first or pass --replace-running." >&2
        exit 1
    fi
    flatpak kill "$app_id" || true
fi

rm -f "$log_file"
mkdir -p "$dev_data_home/gnome-shell/extensions" "$dev_config_home" "$dev_cache_home" "$runtime_dir/doc/by-app/$app_id"
cp -a "$extension_dir" "$dev_data_home/gnome-shell/extensions/$uuid"

GSETTINGS_BACKEND=keyfile \
    XDG_CONFIG_HOME="$dev_config_home" \
    gsettings set org.gnome.shell enabled-extensions "['$uuid']"

export XDG_DATA_HOME="$dev_data_home"
export XDG_CONFIG_HOME="$dev_config_home"
export XDG_CACHE_HOME="$dev_cache_home"
export GSETTINGS_BACKEND=keyfile
export MINI_EQ_NESTED_APP_ID="$app_id"
export MINI_EQ_NESTED_APP_REF="$app_ref"
export MINI_EQ_NESTED_LOG="$log_file"

echo "Using isolated GNOME Shell dev home: $dev_home" >&2
echo "Installed extension source: $dev_data_home/gnome-shell/extensions/$uuid" >&2
echo "Launching Flatpak app ref: $app_ref" >&2
echo "Log: $log_file" >&2
echo "Stop with Ctrl+C in this terminal." >&2
echo >&2

dbus-run-session -- bash <<'INNER'
set -euo pipefail

log_file="$MINI_EQ_NESTED_LOG"
app_id="$MINI_EQ_NESTED_APP_ID"
app_ref="$MINI_EQ_NESTED_APP_REF"

cleanup_inner() {
    flatpak kill "$app_id" >/dev/null 2>&1 || true
    if [[ -n "${shell_pid:-}" ]]; then
        kill "$shell_pid" >/dev/null 2>&1 || true
        wait "$shell_pid" >/dev/null 2>&1 || true
    fi
}
trap cleanup_inner EXIT INT TERM

gnome-shell --devkit >>"$log_file" 2>&1 &
shell_pid=$!

nested_display=""
for _ in $(seq 1 160); do
    nested_display="$(sed -n "s/.*Using Wayland display name '\([^']*\)'.*/\1/p" "$log_file" | tail -1)"
    if [[ -n "$nested_display" && -S "${XDG_RUNTIME_DIR:-/tmp}/$nested_display" ]]; then
        break
    fi
    sleep 0.1
done

if [[ -z "$nested_display" || ! -S "${XDG_RUNTIME_DIR:-/tmp}/$nested_display" ]]; then
    echo "Nested Wayland display did not become ready." >&2
    tail -120 "$log_file" >&2 || true
    exit 1
fi

echo "Nested display: $nested_display" | tee -a "$log_file" >&2
sleep 2
echo "Launching $app_ref into nested display." | tee -a "$log_file" >&2
env -u XDG_DATA_HOME -u XDG_CONFIG_HOME -u XDG_CACHE_HOME \
    WAYLAND_DISPLAY="$nested_display" \
    flatpak --user run "$app_ref" >>"$log_file" 2>&1 &
app_launcher_pid=$!
echo "Flatpak launcher PID: $app_launcher_pid" | tee -a "$log_file" >&2

wait "$shell_pid"
INNER
