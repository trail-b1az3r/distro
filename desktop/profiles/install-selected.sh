#!/usr/bin/env bash
set -Eeuo pipefail

# This script is intentionally run as the logged-in user from a visible
# terminal: upstream desktop installers need an interactive session.
CONFIG="${XDG_CONFIG_HOME:-$HOME/.config}/nexora/desktop-profiles.conf"
[[ -f "$CONFIG" ]] || CONFIG=/etc/distro-desktop-profiles.conf
STATE="${XDG_STATE_HOME:-$HOME/.local/state}/distro-desktop-profiles"
LOG="$STATE/install.log"
WORK="$HOME/.local/share/distro-desktop-profiles"
CONFIGS="$WORK/configs"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DISTRO_ID="$(basename "$(dirname "$(dirname "$SCRIPT_DIR")")")"
# Installed layout: /usr/share/<id>/desktop/profiles. During development,
# permit an explicit override and locate the package list relative to it.
DATA_ROOT="${DISTRO_DATA_ROOT:-/usr/share/$DISTRO_ID}"
LISTS="$DATA_ROOT/packages/lists"
SESSION_DIR="/usr/share/wayland-sessions"

mkdir -p "$STATE" "$WORK" "$CONFIGS"
touch "$LOG"
exec > >(tee -a "$LOG") 2>&1

declare -a selected=()
if (( $# )); then
    for id in "$@"; do selected+=("$id"); done
elif [[ -f "$CONFIG" ]]; then
    read -r -a selected < "$CONFIG"
else
    echo "No desktop profile selection found. Select desktops in Nexora Welcome first."
    exit 0
fi

valid=()
for id in "${selected[@]}"; do
    case "$id" in ml4w|hyde|sekaipop) valid+=("$id") ;;
        *) echo "Ignoring unsupported desktop profile: $id" >&2 ;;
    esac
done
if (( ${#valid[@]} == 0 )); then
    echo "No supported desktop profiles selected."
    exit 2
fi
selected=("${valid[@]}")

echo "Desktop profiles requested: ${selected[*]}"
echo "Already-installed profiles are kept. New profiles are installed alongside Halcyon."
echo "Upstream installers may change shared themes, portals, SDDM settings and packages."
echo "Each profile's user configuration is isolated and selectable at the login screen."
read -r -p "Continue? [y/N] " answer
[[ "$answer" =~ ^[Yy]$ ]] || { echo "Cancelled. Run this helper again when ready."; exit 0; }

BASE="$CONFIGS/.base"
if [[ ! -d "$BASE" ]]; then
    mkdir -p "$BASE"
    [[ ! -d "$HOME/.config" ]] || cp -a "$HOME/.config/." "$BASE/"
fi

restore_base() {
    rm -rf "$HOME/.config"
    mkdir -p "$HOME/.config"
    cp -a "$BASE/." "$HOME/.config/" 2>/dev/null || true
    rm -f "$HOME/.config/autostart/distro-desktop-profiles.desktop"
}

register_session() {
    local id="$1" name="$2" desktop_file
    desktop_file="$(mktemp)"
    cat > "$desktop_file" <<EOF
[Desktop Entry]
Name=$name
Comment=$name desktop profile for Nexora
Exec=$SCRIPT_DIR/run-session.sh $id
TryExec=Hyprland
Type=Application
DesktopNames=$name
EOF
    sudo install -D -m 0644 "$desktop_file" "$SESSION_DIR/nexora-$id.desktop"
    rm -f "$desktop_file"
}

install_packages() {
    local id="$1" list="$LISTS/desktop-$id.list"
    [[ -f "$list" ]] || { echo "Missing package list: $list" >&2; return 1; }
    local -a packages=()
    while IFS= read -r line || [[ -n "$line" ]]; do
        line="${line%%#*}"
        line="${line//[$'\\t\\r']/ }"
        [[ -z "${line// /}" ]] || packages+=("$line")
    done < "$list"
    if (( ${#packages[@]} )); then
        sudo pacman -S --needed --noconfirm -- "${packages[@]}"
    fi
}

run_repo() {
    local id="$1" url="$2" dir="$WORK/$1"
    if [[ ! -d "$dir/.git" ]]; then
        git clone --depth 1 "$url" "$dir" || return $?
    else
        git -C "$dir" pull --ff-only || return $?
    fi
    case "$id" in
        ml4w)
            curl -fsSL https://ml4w.com/os/stable -o "$WORK/ml4w-install.sh" || return $?
            bash "$WORK/ml4w-install.sh"
            ;;
        hyde) (cd "$dir/Scripts" && ./install.sh) ;;
        sekaipop) (cd "$dir" && ./install.sh) ;;
        *) echo "Unknown desktop profile: $id" >&2; return 2 ;;
    esac
}

failed=0
for id in "${selected[@]}"; do
    case "$id" in
        ml4w) url=https://github.com/mylinuxforwork/dotfiles.git; name="ML4W Dotfiles" ;;
        hyde) url=https://github.com/HyDE-Project/HyDE.git; name="HyDE" ;;
        sekaipop) url=https://github.com/Blapples/SekaiPop.git; name="SekaiPop" ;;
    esac

    # Always repair/recreate the login entry, even when the upstream profile
    # was installed by an earlier run.
    if [[ -f "$STATE/$id.done" && -d "$CONFIGS/$id" ]]; then
        echo "=== $id is already installed; ensuring its login session exists ==="
        if register_session "$id" "$name"; then continue; else failed=1; continue; fi
    fi

    echo "=== Installing $id ==="
    if ! install_packages "$id"; then
        echo "Could not install prerequisite packages for $id; see $LOG"
        failed=1
        continue
    fi

    restore_base
    if run_repo "$id" "$url"; then
        rm -f "$HOME/.config/autostart/distro-desktop-profiles.desktop"
        rm -rf "$CONFIGS/$id"
        mkdir -p "$CONFIGS/$id"
        [[ ! -d "$HOME/.config" ]] || cp -a "$HOME/.config/." "$CONFIGS/$id/"
        if register_session "$id" "$name"; then
            touch "$STATE/$id.done"
            echo "$name installed and registered as a separate login session."
        else
            echo "Could not register the $name login session."
            failed=1
        fi
    else
        echo "Installation failed for $id; see $LOG"
        failed=1
    fi
    restore_base
done

if (( failed == 0 )); then
    rm -f "$HOME/.config/autostart/distro-desktop-profiles.desktop"
    touch "$STATE/completed"
    echo "All requested desktop profiles are ready. Choose one from the SDDM session menu."
else
    echo "One or more profiles failed. Review $LOG and rerun this helper; completed profiles will be retained."
    exit 1
fi
