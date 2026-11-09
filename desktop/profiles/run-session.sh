#!/usr/bin/env bash
set -Eeuo pipefail
profile="${1:-}"
case "$profile" in ml4w|hyde|sekaipop) ;; *) echo "Unknown desktop profile: $profile" >&2; exit 2 ;; esac
root="$HOME/.local/share/distro-desktop-profiles"
snapshot="$root/configs/$profile"
[[ -d "$snapshot" ]] || { echo "No saved config for $profile. Run the profile installer first." >&2; exit 1; }
base="$HOME/.config"
backup="$HOME/.config.distro-session-backup"
had_base=0
# Recover the base config if the previous session was killed before its EXIT trap ran.
if [[ -e "$backup" || -L "$backup" ]]; then
    if [[ -d "$base" ]]; then
        rm -rf "$snapshot"
        mkdir -p "$snapshot"
        cp -a "$base/." "$snapshot/"
    fi
    rm -rf "$base"
    mv "$backup" "$base"
fi
if [[ -e "$base" || -L "$base" ]]; then mv "$base" "$backup"; had_base=1; fi
mkdir -p "$base"
cp -a "$snapshot/." "$base/"
restore() {
    status=$?
    trap - EXIT INT TERM
    rm -rf "$snapshot"
    mkdir -p "$snapshot"
    cp -a "$base/." "$snapshot/" 2>/dev/null || true
    rm -rf "$base"
    if (( had_base )); then mv "$backup" "$base"; fi
    exit "$status"
}
trap restore EXIT INT TERM
Hyprland "$@"
