#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
uuid="mini-eq@bhack.github.io"
extension_dir="$repo_root/extensions/gnome-shell/$uuid"
out_dir="${1:-$repo_root/dist/gnome-shell-extension}"
shell_icon_file="mini-eq-symbolic.svg"

if [[ "$out_dir" != /* ]]; then
    out_dir="$PWD/$out_dir"
fi

if [[ ! -d "$extension_dir" ]]; then
    echo "Extension source not found: $extension_dir" >&2
    exit 1
fi

mkdir -p "$out_dir"

(
    cd "$extension_dir"
    gnome-extensions pack \
        --force \
        --out-dir "$out_dir" \
        --extra-source "$shell_icon_file" \
        .
)

echo "$out_dir/$uuid.shell-extension.zip"
