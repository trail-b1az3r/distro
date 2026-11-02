#!/usr/bin/env bash
# Prepare a pacman repository for GitHub Releases (regular files, no symlinks).
set -Eeuo pipefail

src_arg="${1:?usage: publish-repo.sh <repo-dir> <out-dir> [repo-name]}"
out_arg="${2:?usage: publish-repo.sh <repo-dir> <out-dir> [repo-name]}"

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
repo_root="$(cd -- "$script_dir/.." && pwd -P)"
cd "$repo_root"

resolve_path() {
    case "$1" in
        /*) printf '%s\n' "$1" ;;
        *)  printf '%s/%s\n' "$repo_root" "$1" ;;
    esac
}

src="$(resolve_path "$src_arg")"
out="$(resolve_path "$out_arg")"
repo="${3:-}"

if [[ -z "$repo" ]]; then
    # shellcheck disable=SC1091
    . "$repo_root/distro.conf"
    repo="$DISTRO_REPO_NAME"
fi
[[ "$repo" =~ ^[A-Za-z0-9._-]+$ ]] || {
    echo "invalid repository name: $repo" >&2
    exit 1
}
[[ -d "$src" ]] || {
    echo "package input directory does not exist: $src" >&2
    exit 1
}
command -v repo-add >/dev/null 2>&1 || {
    echo "repo-add is missing; install the pacman package before publishing" >&2
    exit 1
}

stage="prepare package files"
on_error() {
    local status=$?
    printf 'publish-repo.sh: failed during %s (exit %s): %s\n' \
        "$stage" "$status" "$BASH_COMMAND" >&2
    exit "$status"
}
trap on_error ERR

rm -rf -- "$out"
mkdir -p -- "$out"

shopt -s nullglob
pkgs=()
for f in "$src"/*.pkg.tar.*; do
    [[ -f "$f" ]] || continue
    [[ "$f" == *.sig ]] && continue

    name="$(basename -- "$f")"
    safe="${name//:/.}"
    cp -- "$f" "$out/$safe"
    if [[ -f "$f.sig" ]]; then
        cp -- "$f.sig" "$out/$safe.sig"
    fi
    pkgs+=("$out/$safe")
done

if (( ${#pkgs[@]} == 0 )); then
    echo "no package archives found in $src" >&2
    exit 1
fi

printf 'Preparing %d package(s) for repository %s\n' "${#pkgs[@]}" "$repo"

sign_args=()
if [[ -n "${GPGKEY:-}" ]]; then
    sign_args=(--sign --key "$GPGKEY")
fi

stage="repo-add"
db_archive="$out/$repo.db.tar.gz"
# repo-add does not support --wait-for-lock; pass only its supported options.
repo-add "${sign_args[@]}" "$db_archive" "${pkgs[@]}"
[[ -s "$db_archive" ]] || {
    echo "repo-add completed without creating the required database: $db_archive" >&2
    exit 1
}

# Pacman needs the .db database. The .files database is useful to optional
# clients, but is not required to install packages; do not fail publication
# when a pacman version does not emit it.
stage="publish database aliases"
for kind in db files; do
    archive="$out/$repo.$kind.tar.gz"
    alias="$out/$repo.$kind"

    if [[ -s "$archive" ]]; then
        cp -f -- "$archive" "$alias"
        if [[ -f "$archive.sig" ]]; then
            cp -f -- "$archive.sig" "$alias.sig"
        fi
    elif [[ "$kind" == db ]]; then
        echo "required pacman database was not generated: $archive" >&2
        exit 1
    else
        echo "repo-add did not emit the optional file-list database; continuing" >&2
    fi
done

stage="count published files"
count="$(find "$out" -maxdepth 1 -type f | wc -l)"
echo "$count files ready in $out"
