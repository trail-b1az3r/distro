#!/usr/bin/env bash
# The login entry of an extra desktop (ML4W, HyDE, SekaiPop): Hyprland with that desktop's own home
# (profile-home.sh), so its configuration, and anything it writes, never mixes with Halcyon's.
set -Eeuo pipefail

profile="${1:-}"
case "$profile" in ml4w|hyde|sekaipop) ;; *) echo "Unknown desktop profile: $profile" >&2; exit 2 ;; esac
shift || true

REAL_HOME="${REAL_HOME:-$HOME}"
SCRIPT_DIR="$(cd -- "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}")")" && pwd)"
# shellcheck source=profile-home.sh
. "$SCRIPT_DIR/profile-home.sh"

home="$(profile_home "$profile")"
if [[ ! -d "$home" && ! -d "$PROFILE_ROOT/configs/$profile" ]]; then
    echo "$profile is not installed. Install it with distro-install-desktop-profiles $profile." >&2
    exit 1
fi
profile_home_setup "$profile"

# A preview of this desktop for the login screen's desktop switcher: a small screenshot a few seconds after it starts
# (before apps are open), in the shared previews folder. Off with ~/.config/nexora/no-session-preview (in the real
# home).
previews=/var/lib/nexora/session-previews
if [[ -d "$previews" && -w "$previews" && ! -e "$REAL_HOME/.config/nexora/no-session-preview" ]] && command -v grim >/dev/null; then
    (
        runtime="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
        before="$(ls "$runtime"/wayland-* 2>/dev/null | grep -v '\.lock$' || true)"
        socket=""
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

# The user's systemd and D-Bus services follow the session's environment while it runs (desktops export it); set
# the real home back for them when it ends, so the next Halcyon session's services are Halcyon's.
reset_services() {
    systemctl --user unset-environment XDG_CONFIG_HOME XDG_DATA_HOME XDG_STATE_HOME XDG_CACHE_HOME 2>/dev/null || true
    systemctl --user set-environment HOME="$REAL_HOME" 2>/dev/null || true
    dbus-update-activation-environment --systemd HOME="$REAL_HOME" 2>/dev/null || true
}
trap reset_services EXIT

profile_env "$profile"
cd "$HOME"
# start-hyprland (Hyprland 0.57+) watches Hyprland and is how a login manager should start it.
if command -v start-hyprland >/dev/null; then
    if (( $# )); then start-hyprland -- "$@"; else start-hyprland; fi
else
    Hyprland "$@"
fi
