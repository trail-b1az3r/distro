#!/usr/bin/env bash
set -Eeuo pipefail

profile="${1:-}"
case "$profile" in ml4w|hyde|sekaipop) ;; *) echo "Unknown desktop profile: $profile" >&2; exit 2 ;; esac
shift || true

root="$HOME/.local/share/distro-desktop-profiles"
configs="$root/configs"
snapshot="$configs/$profile"
base="$HOME/.config"
state="$HOME/.local/state/distro-desktop-profiles"
active="$state/active-profile"
lock="$state/session.lock"
mkdir -p "$state"

[[ -d "$snapshot" ]] || { echo "No saved config for $profile. Install it first with distro-install-desktop-profiles $profile." >&2; exit 1; }
if [[ -e "$lock" ]]; then
    echo "A desktop profile switch/recovery is already in progress ($lock)." >&2
    exit 1
fi
: > "$lock"
backup="$(mktemp -d "$HOME/.config.distro-session.XXXXXX")"
had_base=0
if [[ -e "$base" || -L "$base" ]]; then
    cp -a "$base/." "$backup/"
    had_base=1
fi
previous=""
[[ ! -f "$active" ]] || previous="$(cat "$active")"

restore() {
    status=$?
    trap - EXIT INT TERM
    # Save any changes made in this session back to its own profile snapshot.
    if [[ -f "$active" ]]; then
        running="$(cat "$active")"
        case "$running" in
            ml4w|hyde|sekaipop)
                if [[ -d "$base" ]]; then
                    staging="$(mktemp -d "$configs/.save-$running.XXXXXX")"
                    cp -a "$base/." "$staging/"
                    old="$configs/.$running.old"
                    rm -rf "$old"
                    [[ ! -d "$snapshot" ]] || mv "$configs/$running" "$old"
                    mv "$staging" "$configs/$running"
                    rm -rf "$old"
                fi
                ;;
        esac
    fi
    rm -rf "$base"
    mkdir -p "$base"
    if (( had_base )); then cp -a "$backup/." "$base/"; fi
    rm -rf "$backup"
    rm -f "$active" "$lock"
    exit "$status"
}
trap restore EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# Persist the previous profile's latest state before switching. Its snapshot
# remains isolated; no other profile's config directory is touched.
if [[ "$previous" =~ ^(ml4w|hyde|sekaipop)$ && -d "$base" ]]; then
    staging="$(mktemp -d "$configs/.save-$previous.XXXXXX")"
    cp -a "$base/." "$staging/"
    rm -rf "$configs/.$previous.old"
    [[ ! -d "$configs/$previous" ]] || mv "$configs/$previous" "$configs/.$previous.old"
    mv "$staging" "$configs/$previous"
    rm -rf "$configs/.$previous.old"
fi

# Install the requested profile as the active XDG config tree. Restore the
# original Halcyon/user config after Hyprland exits; the profile snapshot is
# saved independently by the EXIT trap above.
rm -rf "$base"
mkdir -p "$base"
cp -a "$snapshot/." "$base/"
printf "%s\n" "$profile" > "$active"

# A preview of this desktop for the login screen's desktop switcher: a small screenshot a few seconds after it starts
# (before apps are open), in the shared previews folder. Off with ~/.config/nexora/no-session-preview.
previews=/var/lib/nexora/session-previews
if [[ -d "$previews" && -w "$previews" && ! -e "$HOME/.config/nexora/no-session-preview" ]] && command -v grim >/dev/null; then
    (
        runtime="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
        before="$(ls "$runtime"/wayland-* 2>/dev/null | grep -v '\.lock$' || true)"
        for _ in {1..30}; do
            sleep 1
            socket="$(ls "$runtime"/wayland-* 2>/dev/null | grep -v '\.lock$' | grep -vxF -- "$before" | head -n1 || true)"
            [[ -n "$socket" ]] && break
        done
        [[ -n "$socket" ]] || exit 0
        sleep 8
        WAYLAND_DISPLAY="$(basename "$socket")" grim -s 0.5 -t png "$previews/.nexora-$profile.png.tmp" 2>/dev/null \
            && mv -f "$previews/.nexora-$profile.png.tmp" "$previews/nexora-$profile.png" \
            && chmod 0644 "$previews/nexora-$profile.png"
    ) &
fi

# start-hyprland (Hyprland 0.57+) watches Hyprland and is how a login manager should start it.
if command -v start-hyprland >/dev/null; then
    if (( $# )); then start-hyprland -- "$@"; else start-hyprland; fi
else
    Hyprland "$@"
fi
