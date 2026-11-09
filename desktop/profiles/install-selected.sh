#!/usr/bin/env bash
set -Eeuo pipefail

CONFIG=/etc/distro-desktop-profiles.conf
STATE="$HOME/.local/state/distro-desktop-profiles"
LOG="$STATE/install.log"
WORK="$HOME/.local/share/distro-desktop-profiles"
mkdir -p "$STATE" "$WORK"
touch "$LOG"
exec > >(tee -a "$LOG") 2>&1

if [[ ! -f "$CONFIG" ]]; then echo "No desktop profile selection found."; exit 0; fi
read -r -a selected < "$CONFIG"
if (( ${#selected[@]} == 0 )); then echo "No external desktop profiles selected."; exit 0; fi
echo "Selected external desktop profiles: ${selected[*]}"
echo "Upstream installers can alter shared Hyprland, GTK, SDDM, portal and theme settings."
echo "They run as your user, not silently as root."
read -r -p "Continue with upstream installers? [y/N] " answer
[[ "$answer" =~ ^[Yy]$ ]] || { echo "Cancelled. Run this helper again when ready."; exit 0; }

run_repo() {
    local id="$1" url="$2" dir="$WORK/$1"
    if [[ ! -d "$dir/.git" ]]; then git clone --depth 1 "$url" "$dir"; else git -C "$dir" pull --ff-only; fi
    case "$id" in
        ml4w) bash <(curl -fsSL https://ml4w.com/os/stable) ;;
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
    echo "=== Installing $id ==="
    if run_repo "$id" "$url"; then touch "$STATE/$id.done"; else echo "Installation failed for $id; see $LOG"; failed=1; fi
done
if (( failed == 0 )); then rm -f "$HOME/.config/autostart/distro-desktop-profiles.desktop"; echo "Selected desktop setup finished."; else echo "Retry with: alacritty -e /usr/local/bin/distro-install-desktop-profiles"; fi
