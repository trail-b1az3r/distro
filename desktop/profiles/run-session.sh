#!/usr/bin/env bash
set -Eeuo pipefail
profile="${1:-}"
case "$profile" in ml4w|hyde|sekaipop) ;; *) echo "Unknown desktop profile: $profile" >&2; exit 2 ;; esac
root="$HOME/.local/share/distro-desktop-profiles"
snapshot="$root/configs/$profile"
backup="$HOME/.config.distro-session-backup"
active="$root/.active-profile"
base="$HOME/.config"
[[ -d "$snapshot" ]] || { echo "No saved config for $profile. Run the profile installer first." >&2; exit 1; }
had_base=0
# Recover a previous session only if its config copy had completed.
if [[ -e "$backup" || -L "$backup" ]]; then
    previous=""
    [[ ! -f "$active" ]] || previous="$(cat "$active")"
    case "$previous" in ml4w|hyde|sekaipop)
        if [[ -d "$base/hypr" ]]; then
            previous_snapshot="$root/configs/$previous"
            rm -rf "$previous_snapshot"
            mkdir -p "$previous_snapshot"
            cp -a "$base/." "$previous_snapshot/"
        fi ;;
    esac
    rm -rf "$base"
    mv "$backup" "$base"
    rm -f "$active"
fi
if [[ -e "$base" || -L "$base" ]]; then mv "$base" "$backup"; had_base=1; fi
mkdir -p "$base"
cp -a "$snapshot/." "$base/"
printf "%s\n" "$profile" > "$active"
restore() {
    status=$?
    trap - EXIT INT TERM
    rm -rf "$snapshot"
    mkdir -p "$snapshot"
    cp -a "$base/." "$snapshot/" 2>/dev/null || true
    rm -rf "$base"
    if (( had_base )); then mv "$backup" "$base"; fi
    rm -f "$active"
    exit "$status"
}
trap restore EXIT INT TERM
Hyprland "$@"
