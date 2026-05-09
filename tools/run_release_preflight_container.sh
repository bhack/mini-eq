#!/bin/sh
set -eu

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

container_cli="${CONTAINER_CLI:-docker}"
image="${MINI_EQ_PREFLIGHT_IMAGE:-mini-eq-release-preflight:trixie}"

"$container_cli" build -f docker/preflight.Dockerfile -t "$image" .

if [ -n "${MINI_EQ_FLATHUB_MANIFEST:-}" ]; then
  flathub_manifest="$(realpath "$MINI_EQ_FLATHUB_MANIFEST")"
  flathub_dir="$(dirname "$flathub_manifest")"
  flathub_file="$(basename "$flathub_manifest")"
  "$container_cli" run --rm \
    -v "$repo_root:/work" \
    -v "$flathub_dir:/flathub:ro" \
    -e "MINI_EQ_FLATHUB_MANIFEST=/flathub/$flathub_file" \
    -w /work \
    "$image" "$@"
else
  "$container_cli" run --rm -v "$repo_root:/work" -w /work "$image" "$@"
fi
