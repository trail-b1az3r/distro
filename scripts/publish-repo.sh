#!/usr/bin/env bash
# Prepare a pacman repository for GitHub Releases (regular files, no symlinks).
set -euo pipefail
src="${1:?usage: publish-repo.sh <repo-dir> <out-dir> [repo-name]}"
out="${2:?usage: publish-repo.sh <repo-dir> <out-dir> [repo-name]}"
cd "$(dirname "$(readlink -f "$0")")/.."
repo="${3:-$(. ./distro.conf && echo "$DISTRO_REPO_NAME")}"
rm -rf "$out"
mkdir -p "$out"
shopt -s nullglob
pkgs=()
for f in "$src"/*.pkg.tar.*; do
    [[ $f == *.sig ]] && continue
    name="$(basename "$f")"
    safe="${name//:/.}"
    cp "$f" "$out/$safe"
    [[ -e "$f.sig" ]] && cp "$f.sig" "$out/$safe.sig"
    pkgs+=("$out/$safe")
done
(("${#pkgs[@]}")) || { echo "no packages in $src" >&2; exit 1; }
sign=()
[[ -n "${GPGKEY:-}" ]] && sign=(--sign --key "$GPGKEY")
repo-add "${sign[@]}" "$out/$repo.db.tar.gz" "${pkgs[@]}"
for db in "$repo.db" "$repo.files"; do
    rm -f "$out/$db" "$out/$db.sig"
    cp "$out/$db.tar.gz" "$out/$db"
    [[ -e "$out/$db.tar.gz.sig" ]] && cp "$out/$db.tar.gz.sig" "$out/$db.sig"
done
echo "$(find "$out" -maxdepth 1 -type f | wc -l) files ready in $out"
