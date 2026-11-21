#!/usr/bin/env bash
# Publish a package repository under the distribution's former names too (distro.conf DISTRO_LEGACY_IDS), so
# systems installed under one, whose pacman.conf still says [nexora-experiments] or [nexora-surface], get the same
# packages: their next `pacman -Syu` then offers to replace the old-named packages with the renamed ones, and the
# renamed core package's hook moves pacman.conf over (lib/distrokit/system/legacy.py).
#
#   publish-legacy.sh ASSETS_DIR REPO [--prune]
#
# ASSETS_DIR is what publish-repo.sh made for REPO (packages and REPO.db/.files). For each former ID, the release
# named like REPO with the old ID in front (frontline-surface -> nexora-surface) gets the packages and the database
# under its own name. --prune also deletes that release's older assets the database no longer lists.
set -euo pipefail

assets="${1:?usage: publish-legacy.sh ASSETS_DIR REPO [--prune]}"
repo="${2:?usage: publish-legacy.sh ASSETS_DIR REPO [--prune]}"
prune="${3:-}"
repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
# shellcheck disable=SC1091
. "$repo_root/distro.conf"

prefix="$DISTRO_REPO_NAME"
case "$repo" in
    # The main repository's release ("repo") holds its former names' databases itself (publish-repo.sh).
    "$prefix") echo "[$repo]: its former names are published with it by publish-repo.sh"; exit 0 ;;
    "$prefix"-*) rest="${repo#"$prefix"}" ;;
    *) echo "publish-legacy.sh: $repo is not one of $prefix's repositories" >&2; exit 2 ;;
esac

for old in ${DISTRO_LEGACY_IDS:-}; do
    [[ "$old" =~ ^[a-z0-9-]+$ && "$old" != "$prefix" ]] || continue
    legacy="$old$rest"
    out="$(mktemp -d)"
    for f in "$assets"/*; do
        name="$(basename -- "$f")"
        case "$name" in
            "$repo".db*|"$repo".files*) cp -- "$f" "$out/$legacy${name#"$repo"}" ;;
            *.pkg.tar.*) cp -- "$f" "$out/$name" ;;
        esac
    done
    if [[ -z "$(find "$out" -name "$legacy.db*" -print -quit)" ]]; then
        echo "publish-legacy.sh: no $repo database in $assets" >&2
        exit 1
    fi
    if ! gh release view "$legacy" >/dev/null 2>&1; then
        gh release create "$legacy" --title "$legacy (former name of $repo)" --prerelease --latest=false \
            --notes "The packages of [$repo], under the name systems installed before the rename still use."
    fi
    gh release upload "$legacy" "$out"/* --clobber
    if [[ "$prune" == --prune ]]; then
        keep="$(cd "$out" && ls)"
        gh release view "$legacy" --json assets --jq '.assets[].name' | while read -r asset; do
            printf '%s\n' "$keep" | grep -qxF -- "$asset" || gh release delete-asset "$legacy" "$asset" --yes
        done
    fi
    echo "Also published as [$legacy] ($(find "$out" -name '*.pkg.tar.*' ! -name '*.sig' | wc -l) packages)"
    rm -r -- "$out"
done
