#!/usr/bin/env bash
set -euo pipefail

manifest="${MINI_EQ_FLATPAK_MANIFEST:-io.github.bhack.mini-eq.yaml}"
duration="${MINI_EQ_FLATPAK_SMOKE_DURATION:-8}"
timeout="${MINI_EQ_FLATPAK_SMOKE_TIMEOUT:-20}"
build_flatpak="${MINI_EQ_FLATPAK_BUILD:-1}"
install_remote="${MINI_EQ_FLATPAK_INSTALL_REMOTE:-0}"
install_ref="${MINI_EQ_FLATPAK_INSTALL_REF:-io.github.bhack.mini-eq}"
app_ref="${MINI_EQ_FLATPAK_APP_REF:-}"
expect_version="${MINI_EQ_FLATPAK_EXPECT_VERSION:-}"
flathub_url="${MINI_EQ_FLATHUB_URL:-https://flathub.org/repo/flathub.flatpakrepo}"
builder_ref="${MINI_EQ_FLATPAK_BUILDER_REF:-org.flatpak.Builder//stable}"

if [[ -z "$app_ref" ]]; then
  if [[ "$build_flatpak" == "1" ]]; then
    app_ref="io.github.bhack.mini-eq//master"
  elif [[ "$install_remote" == "1" ]]; then
    app_ref="$install_ref"
  else
    app_ref="io.github.bhack.mini-eq//master"
  fi
fi

runtime_dir="${MINI_EQ_RUNTIME_DIR:-/run/user/$(id -u)}"
config_home="${MINI_EQ_CONFIG_HOME:-$(mktemp -d -t mini-eq-config.XXXXXX)}"
cleanup_config=false

if [[ -z "${MINI_EQ_CONFIG_HOME:-}" ]]; then
  cleanup_config=true
fi

cleanup_dirs() {
  if [[ "$cleanup_config" == true ]]; then
    rm -rf "$config_home"
  fi
}
trap cleanup_dirs EXIT

require_tool() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "missing required tool: $1" >&2
    exit 127
  fi
}

for tool in dbus-run-session flatpak jq pipewire pw-cat pw-dump pw-metadata python3 wpctl wireplumber; do
  require_tool "$tool"
done

if [[ -S "$runtime_dir/pipewire-0" && "${MINI_EQ_ALLOW_EXISTING_PIPEWIRE:-0}" != "1" ]]; then
  echo "$runtime_dir already has a PipeWire socket; run this in an isolated runner." >&2
  exit 1
fi

if ! mkdir -p "$runtime_dir" 2>/dev/null; then
  require_tool sudo
  sudo -n mkdir -p "$runtime_dir"
  sudo -n chown "$(id -u):$(id -g)" "$runtime_dir"
fi

mkdir -p "$config_home/pipewire/pipewire.conf.d"
chmod 700 "$runtime_dir"

cat > "$config_home/pipewire/pipewire.conf.d/10-mini-eq-ci-null-sink.conf" <<'EOF'
context.objects = [
    { factory = adapter
        args = {
            factory.name     = support.null-audio-sink
            node.name        = "ci_null_sink"
            node.description = "CI Null Sink"
            media.class      = "Audio/Sink"
            audio.position   = "FL,FR"
            adapter.auto-port-config = {
                mode     = dsp
                monitor  = true
                position = preserve
            }
        }
    }
]
EOF

export XDG_RUNTIME_DIR="$runtime_dir"
export XDG_CONFIG_HOME="$config_home"
export MINI_EQ_FLATPAK_MANIFEST="$manifest"
export MINI_EQ_FLATPAK_APP_REF="$app_ref"
export MINI_EQ_FLATPAK_SMOKE_DURATION="$duration"
export MINI_EQ_FLATPAK_SMOKE_TIMEOUT="$timeout"
export MINI_EQ_FLATPAK_BUILD="$build_flatpak"
export MINI_EQ_FLATPAK_INSTALL_REMOTE="$install_remote"
export MINI_EQ_FLATPAK_INSTALL_REF="$install_ref"
export MINI_EQ_FLATPAK_EXPECT_VERSION="$expect_version"
export MINI_EQ_FLATHUB_URL="$flathub_url"
export MINI_EQ_FLATPAK_BUILDER_REF="$builder_ref"

dbus-run-session -- bash <<'SH'
set -euo pipefail

flatpak remote-add --if-not-exists --user flathub "$MINI_EQ_FLATHUB_URL"

if [[ "$MINI_EQ_FLATPAK_BUILD" == "1" ]]; then
  flatpak install --user -y flathub "$MINI_EQ_FLATPAK_BUILDER_REF"
  flatpak run --command=flathub-build org.flatpak.Builder \
    --install "$MINI_EQ_FLATPAK_MANIFEST"
elif [[ "$MINI_EQ_FLATPAK_INSTALL_REMOTE" == "1" ]]; then
  flatpak install --user -y flathub "$MINI_EQ_FLATPAK_INSTALL_REF"
else
  flatpak info --user "$MINI_EQ_FLATPAK_APP_REF" >/dev/null
fi

echo "## installed Mini EQ Flatpak"
flatpak info --user "$MINI_EQ_FLATPAK_APP_REF"
if [[ -n "$MINI_EQ_FLATPAK_EXPECT_VERSION" ]]; then
  actual_version="$(
    flatpak info --user "$MINI_EQ_FLATPAK_APP_REF" \
      | awk -F: '/^[[:space:]]*Version:/ {gsub(/^[[:space:]]+|[[:space:]]+$/, "", $2); print $2; exit}'
  )"
  if [[ "$actual_version" != "$MINI_EQ_FLATPAK_EXPECT_VERSION" ]]; then
    echo "expected Flatpak version $MINI_EQ_FLATPAK_EXPECT_VERSION, got ${actual_version:-unknown}" >&2
    exit 1
  fi
fi

pipewire >"$XDG_RUNTIME_DIR/pipewire.log" 2>&1 &
pipewire_pid=$!
wireplumber >"$XDG_RUNTIME_DIR/wireplumber.log" 2>&1 &
wireplumber_pid=$!

cleanup_processes() {
  kill "$wireplumber_pid" "$pipewire_pid" 2>/dev/null || true
  wait "$wireplumber_pid" 2>/dev/null || true
  wait "$pipewire_pid" 2>/dev/null || true
}

dump_logs() {
  echo "## wpctl status"
  wpctl status 2>/dev/null || true
  echo "## pipewire.log"
  sed -n '1,240p' "$XDG_RUNTIME_DIR/pipewire.log" 2>/dev/null || true
  echo "## wireplumber.log"
  sed -n '1,240p' "$XDG_RUNTIME_DIR/wireplumber.log" 2>/dev/null || true
}

trap cleanup_processes EXIT
trap dump_logs ERR

ci_sink_id=""
default_set=false
for _ in $(seq 1 200); do
  ci_sink_id="$(
    pw-dump 2>/dev/null \
      | jq -r '.[] | select(.type=="PipeWire:Interface:Node" and .info.props["node.name"]=="ci_null_sink") | .id' \
      | head -n 1
  )"
  if [[ -n "$ci_sink_id" ]] && wpctl set-default "$ci_sink_id" >/dev/null 2>&1; then
    default_set=true
    break
  fi
  sleep 0.1
done

if [[ "$default_set" != true ]]; then
  echo "failed to set ci_null_sink as the default PipeWire sink"
  exit 1
fi

python3 tools/check_flatpak_runtime.py \
  --app-ref "$MINI_EQ_FLATPAK_APP_REF" \
  --duration "$MINI_EQ_FLATPAK_SMOKE_DURATION" \
  --timeout "$MINI_EQ_FLATPAK_SMOKE_TIMEOUT" \
  --smoke-target ci_null_sink
SH
