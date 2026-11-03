#!/usr/bin/env bash
# Prepare a pacman repository for GitHub Releases (regular files, no symlinks).
set -Eeuo pipefail

stage="startup"
on_error() {
    local status=$?
    local line="${BASH_LINENO[0]:-unknown}"
    local source="${BASH_SOURCE[1]:-${BASH_SOURCE[0]}}"
    local command="${BASH_COMMAND:-unknown command}"

    # Prevent recursive ERR handling while reporting the original failure.
    trap - ERR
    printf 'publish-repo.sh: ERROR: stage="%s" failed with exit status %d at %s:%s\n' \
        "$stage" "$status" "$source" "$line" >&2
    printf 'publish-repo.sh: command: %s\n' "$command" >&2
    exit "$status"
}
trap on_error ERR

fail() {
    printf 'publish-repo.sh: ERROR: stage="%s": %s\n' "$stage" "$*" >&2
    exit 1
}

src_arg="${1:?usage: publish-repo.sh <repo-dir> <out-dir> [repo-name]}"
out_arg="${2:?usage: publish-repo.sh <repo-dir> <out-dir> [repo-name]}"

stage="resolve paths"
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

stage="validate inputs"
if [[ -z "$repo" ]]; then
    # shellcheck disable=SC1091
    . "$repo_root/distro.conf"
    repo="$DISTRO_REPO_NAME"
fi
[[ "$repo" =~ ^[A-Za-z0-9._-]+$ ]] || fail "invalid repository name: $repo"
[[ -d "$src" ]] || fail "package input directory does not exist: $src"
command -v repo-add >/dev/null 2>&1 || fail "repo-add is missing; install the pacman package before publishing"

stage="prepare package files"
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

(( ${#pkgs[@]} > 0 )) || fail "no package archives found in $src"
printf 'Prepared %d package(s) for repository %s\n' "${#pkgs[@]}" "$repo"

sign_args=()
if [[ -n "${GPGKEY:-}" ]]; then
    sign_args=(--sign --key "$GPGKEY")
fi

stage="repo-add"
db_archive="$out/$repo.db.tar.gz"
printf 'Running repo-add; database: %s; package count: %d\n' "$db_archive" "${#pkgs[@]}"
# repo-add does not support --wait-for-lock; pass only its supported options.
# Keep repo-add's stdout/stderr visible in the Actions log for diagnosis.
repo-add "${sign_args[@]}" "$db_archive" "${pkgs[@]}"
[[ -s "$db_archive" ]] || fail "repo-add returned success but did not create the required database: $db_archive"

# Pacman may create .db/.files aliases itself (often as symlinks to the
# corresponding .tar.gz archive). Only copy when the alias is not already the
# same underlying file; cp rejects copying a file onto its own symlink.
stage="publish database aliases"
for kind in db files; do
    archive="$out/$repo.$kind.tar.gz"
    alias="$out/$repo.$kind"

    if [[ -s "$archive" ]]; then
        if [[ ! -e "$alias" ]] || [[ ! "$archive" -ef "$alias" ]]; then
            cp -f -- "$archive" "$alias"
        fi
        if [[ -f "$archive.sig" ]]; then
            if [[ ! -e "$alias.sig" ]] || [[ ! "$archive.sig" -ef "$alias.sig" ]]; then
                cp -f -- "$archive.sig" "$alias.sig"
            fi
        fi
    elif [[ "$kind" == db ]]; then
        fail "required pacman database was not generated: $archive"
    else
        printf 'publish-repo.sh: warning: repo-add did not emit optional file-list database %s; continuing\n' "$archive" >&2
    fi
done

stage="count published files"
count="$(find "$out" -maxdepth 1 -type f | wc -l)"
printf '%s files ready in %s\n' "$count" "$out"
