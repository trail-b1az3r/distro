#!/usr/bin/env bash
# The power button in an extra desktop (started by run-session.sh, in the background, before the compositor):
# pressing it opens a power menu (log out, restart, shut down, sleep...) instead of switching the computer off.
#
# Once the desktop's Hyprland is up, its power key gets the distribution's power menu (<id>-power-menu) unless the
# desktop binds the key itself (its own power menu), and logind's power-key handling is held off with
# systemd-inhibit for as long as that Hyprland runs. When the desktop ends, the lock goes with it: at the login
# screen or on a text console the button powers off as usual. Off with ~/.config/<id>/power-button-off (real home).
#
#   power-button.sh WAYLAND_SOCKETS_BEFORE
set -u

runtime="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
id="${DISTRO_ID:-frontline}"
menu="${POWER_MENU:-$(command -v "$id-power-menu" 2>/dev/null || true)}"
[[ -e "${REAL_HOME:-$HOME}/.config/$id/power-button-off" ]] && exit 0
command -v hyprctl >/dev/null && command -v systemd-inhibit >/dev/null || exit 0
before="${1:-}"

# The new Hyprland instance: its folder in $XDG_RUNTIME_DIR/hypr that was not there before.
sock=""
for _ in $(seq 1 "${POWER_BUTTON_WAIT:-60}"); do
    for d in "$runtime"/hypr/*/; do
        [[ -S "$d.socket.sock" ]] || continue
        sig="$(basename "$d")"
        grep -qxF -- "$sig" <<< "$before" && continue
        sock="$d.socket.sock"
        break 2
    done
    sleep 1
done
[[ -n "$sock" ]] || exit 0
export HYPRLAND_INSTANCE_SIGNATURE="$sig"
sleep "${POWER_BUTTON_SETTLE:-2}"   # the desktop's own binds are in by then

if ! hyprctl binds -j 2>/dev/null | grep -q '"XF86PowerOff"'; then
    [[ -n "$menu" ]] || exit 0   # no menu to open: leave the button as it is
    hyprctl eval "hl.bind(\"XF86PowerOff\", hl.dsp.exec_cmd(\"$menu\"), { description = \"Power menu\" })" >/dev/null 2>&1 \
        || hyprctl keyword bind ",XF86PowerOff,exec,$menu" >/dev/null 2>&1 || exit 0
fi

exec systemd-inhibit --what=handle-power-key --who="${DISTRO_NAME:-$id}" --mode=block \
    --why="The power button opens the power menu" \
    sh -c 'while [ -S "$1" ]; do sleep 5; done' power-button "$sock"
