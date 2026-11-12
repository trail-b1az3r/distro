#!/usr/bin/env bash
set -Eeuo pipefail

CONFIG="${XDG_CONFIG_HOME:-$HOME/.config}/nexora/desktop-profiles.conf"
[[ -f "$CONFIG" ]] || CONFIG=/etc/distro-desktop-profiles.conf
STATE="${XDG_STATE_HOME:-$HOME/.local/state}/distro-desktop-profiles"
LOG="$STATE/install.log"
WORK="$HOME/.local/share/distro-desktop-profiles"
CONFIGS="$WORK/configs"
mkdir -p "$STATE" "$WORK" "$CONFIGS"
touch "$LOG"
exec > >(tee -a "$LOG") 2>&1

if [[ ! -f "$CONFIG" ]]; then echo "No desktop profile selection found."; exit 0; fi
read -r -a selected < "$CONFIG"
if (( ${#selected[@]} == 0 )); then echo "No external desktop profiles selected."; exit 0; fi
echo "Selected external desktop profiles: ${selected[*]}"
echo "Upstream installers may alter shared system themes, SDDM and packages."
echo "This helper snapshots each profile config separately so you can select it at the login screen."
read -r -p "Continue with upstream installers? [y/N] " answer
[[ "$answer" =~ ^[Yy]$ ]] || { echo "Cancelled. Run this helper again when ready."; exit 0; }
BASE="$CONFIGS/.base"
if [[ ! -d "$BASE" ]]; then mkdir -p "$BASE"; [[ ! -d "$HOME/.config" ]] || cp -a "$HOME/.config/." "$BASE/"; fi
restore_base() { rm -rf "$HOME/.config"; mkdir -p "$HOME/.config"; cp -a "$BASE/." "$HOME/.config/" 2>/dev/null || true; rm -f "$HOME/.config/autostart/distro-desktop-profiles.desktop"; }
run_repo() {
    local id="$1" url="$2" dir="$WORK/$1"
    if [[ ! -d "$dir/.git" ]]; then git clone --depth 1 "$url" "$dir" || return $?; else git -C "$dir" pull --ff-only || return $?; fi
    case "$id" in
        ml4w) curl -fsSL https://ml4w.com/os/stable -o "$WORK/ml4w-install.sh" || return $?; bash "$WORK/ml4w-install.sh" ;;
        hyde) (cd "$dir/Scripts" && ./install.sh) ;;
        sekaipop) (cd "$dir" && ./install.sh) ;;
        *) echo "Unknown desktop profile: $id" >&2; return 2 ;;
    esac
}
failed=0
for id in "${selected[@]}"; do
    case "$id" in
        ml4w) url=https://github.com/mylinuxforwork/dotfiles.git ;;
        hyde) url=https://github.com/HyDE-Project/HyDE.git ;;
        sekaipop) url=https://github.com/Blapples/SekaiPop.git ;;
        *) echo "Ignoring unknown profile: $id"; continue ;;
    esac
    if [[ -f "$STATE/$id.done" ]]; then echo "=== $id already installed; skipping ==="; continue; fi
    echo "=== Installing $id ==="
    restore_base
    if run_repo "$id" "$url"; then
        rm -f "$HOME/.config/autostart/distro-desktop-profiles.desktop"
        rm -rf "$CONFIGS/$id"; mkdir -p "$CONFIGS/$id"
        [[ ! -d "$HOME/.config" ]] || cp -a "$HOME/.config/." "$CONFIGS/$id/"
        touch "$STATE/$id.done"
    else
        echo "Installation failed for $id; see $LOG"
        failed=1
    fi
    restore_base
done
if (( failed == 0 )); then
    rm -f "$HOME/.config/autostart/distro-desktop-profiles.desktop"
    touch "$STATE/completed"
    echo "Profiles are available as separate sessions in the login-screen session menu."
else
    echo "One or more installers failed. Review $LOG and rerun this helper."
fi
