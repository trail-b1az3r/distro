#!/usr/bin/env bash
# Prepare the distribution repository for hosting as GitHub release assets
# (DISTRO_REPO_SERVER in distro.conf points at a release named "repo").
#
#   scripts/publish-repo.sh build/repo out/repo-assets
#
# GitHub renames ':' in asset names, which package files with an epoch
# (1:2.0-1) contain, and cannot store symlinks. This copies the packages
# with ':' replaced, rebuilds the database for the new names (pacman only
# needs the name recorded in the database), and writes real files for
# <repo>.db and <repo>.files. With GPGKEY set, the database is signed.
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")/.."
src="${1:?usage: publish-repo.sh <repo-dir> <out-dir>}"
out="${2:?usage: publish-repo.sh <repo-dir> <out-dir>}"
# shellcheck disable=SC1091
repo="$(. ./distro.conf && echo "$DISTRO_REPO_NAME")"
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
((${#pkgs[@]})) || { echo "no packages in $src" >&2; exit 1; }
sign=()
[[ -n "${GPGKEY:-}" ]] && sign=(--sign --key "$GPGKEY")
repo-add "${sign[@]}" "$out/$repo.db.tar.gz" "${pkgs[@]}"
for db in "$repo.db" "$repo.files"; do
    rm -f "$out/$db" "$out/$db.sig"
    cp "$out/$db.tar.gz" "$out/$db"
    [[ -e "$out/$db.tar.gz.sig" ]] && cp "$out/$db.tar.gz.sig" "$out/$db.sig"
done
echo "$(find "$out" -maxdepth 1 -type f | wc -l) files ready in $out"
