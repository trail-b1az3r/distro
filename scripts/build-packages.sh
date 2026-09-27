#!/usr/bin/env bash
# Build the distribution repository (build/repo) without building an ISO.
#
#   scripts/build-packages.sh               build everything that is not built yet
#   scripts/build-packages.sh --plan        show what would be built, in order
#   scripts/build-packages.sh --update-lock re-resolve AUR packages and pin them
#                                           to their current AUR commits (review the diff!)
#   scripts/build-packages.sh --render      only write the distribution's PKGBUILDs
#   Extra options go to `python3 -m distrokit.build.packages` (--only, --force, --sign).
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")/.."
action=build
args=()
for arg in "$@"; do
    case "$arg" in
        --plan) action=plan ;;
        --update-lock) action=lock ;;
        --render) action=render ;;
        -h | --help) sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) args+=("$arg") ;;
    esac
done
if [[ $action != render ]] && ((EUID != 0)); then
    exec sudo --preserve-env=SOURCE_DATE_EPOCH,ARCHIVE_DATE,GPGKEY,BUILD_USER,AUR_GIT_MIRROR "$0" "$@"
fi
export BUILD_USER="${BUILD_USER:-${SUDO_USER:-builder}}"
PYTHONPATH=lib exec python3 -m distrokit.build.packages "$action" --user "$BUILD_USER" "${args[@]}"
