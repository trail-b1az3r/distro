#!/usr/bin/env bash
# Installs the extra desktops chosen in Welcome or the installer (ML4W, HyDE, SekaiPop), each in a home of its own
# (profile-home.sh): the upstream installer runs with HOME there, so it cannot write over Halcyon's files, and its
# login entry starts Hyprland with that home. Run as the logged-in user from a visible terminal: upstream installers
# are interactive and ask for sudo themselves.
set -Eeuo pipefail

REAL_HOME="$HOME"
CONFIG="${XDG_CONFIG_HOME:-$HOME/.config}/nexora/desktop-profiles.conf"
[[ -f "$CONFIG" ]] || CONFIG=/etc/distro-desktop-profiles.conf
STATE="${XDG_STATE_HOME:-$HOME/.local/state}/distro-desktop-profiles"
LOG="$STATE/install.log"
SCRIPT_DIR="$(cd -- "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}")")" && pwd)"
# shellcheck source=profile-home.sh
. "$SCRIPT_DIR/profile-home.sh"
SOURCES="$PROFILE_ROOT/src"

# The distribution's data (package lists), found from the packaged lists.
DATA_ROOT="${DISTRO_DATA_ROOT:-}"
if [[ -z "$DATA_ROOT" ]]; then
    for candidate in /usr/share/*/packages/lists/desktop-ml4w.list; do
        [[ -f "$candidate" ]] || continue
        DATA_ROOT="${candidate%/packages/lists/desktop-ml4w.list}"
        break
    done
fi
if [[ -z "$DATA_ROOT" || ! -d "$DATA_ROOT/packages/lists" ]]; then
    echo "Could not locate the installed desktop package lists under /usr/share." >&2
    echo "Set DISTRO_DATA_ROOT to the distribution data directory and retry." >&2
    exit 1
fi
DISTRO_ID="$(basename "$DATA_ROOT")"
LISTS="$DATA_ROOT/packages/lists"
SESSION_DIR="/usr/share/wayland-sessions"
# The packaged session wrapper (nexora-desktop installs it in /usr/bin); an ISO-era copy in /usr/local/bin, or the
# script next to this one, otherwise. The login entry must point at something SDDM can execute.
SESSION_RUNNER=""
for candidate in /usr/bin/distro-desktop-session /usr/local/bin/distro-desktop-session "$SCRIPT_DIR/run-session.sh"; do
    if [[ -x "$candidate" ]]; then SESSION_RUNNER="$candidate"; break; fi
done
if [[ -z "$SESSION_RUNNER" ]]; then
    echo "The desktop session wrapper (distro-desktop-session) is missing; reinstall the desktop package." >&2
    exit 1
fi

mkdir -p "$STATE" "$PROFILE_HOMES" "$SOURCES"
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
echo "Each one is installed in a home of its own (~/.local/share/distro-desktop-profiles/homes/<name>), so it"
echo "cannot change Halcyon's files. Your documents, keys and browser profiles are shared with it."
echo "Packages are installed system-wide (once, for every desktop); your login shell and the login screen's theme"
echo "are put back if an installer changes them."
read -r -p "Continue? [y/N] " answer
[[ "$answer" =~ ^[Yy]$ ]] || { echo "Cancelled. Run this helper again when ready."; exit 0; }

# What the installers may change for everyone, to put back afterwards.
LOGIN_SHELL="$(getent passwd "$(id -un)" | cut -d: -f7)"

register_session() {
    local id="$1" name="$2" desktop_file
    desktop_file="$(mktemp)"
    cat > "$desktop_file" <<EOF
[Desktop Entry]
Name=$name
Comment=$name, in its own home (Nexora)
Exec=$SESSION_RUNNER $id
TryExec=Hyprland
Type=Application
DesktopNames=Hyprland
X-Nexora-Profile=$id
EOF
    sudo install -D -m 0644 "$desktop_file" "$SESSION_DIR/$DISTRO_ID-$id.desktop"
    rm -f "$desktop_file"
}

install_packages() {
    local id="$1" list="$LISTS/desktop-$id.list"
    [[ -f "$list" ]] || { echo "Missing package list: $list" >&2; return 1; }
    local -a packages=()
    while IFS= read -r line || [[ -n "$line" ]]; do
        # Strip comments, then split on shell whitespace (spaces and tabs).
        line="${line%%#*}"
        [[ -z "${line//[[:space:]]/}" ]] && continue
        read -r -a entries <<< "$line"
        packages+=("${entries[@]}")
    done < "$list"
    if (( ${#packages[@]} )); then
        sudo pacman -S --needed --noconfirm -- "${packages[@]}"
    fi
}

# The upstream installer, in the desktop's home (a subshell, so this script's own environment stays the real one).
run_installer() {
    local id="$1" url="$2" dir="$SOURCES/$1"
    if [[ ! -d "$dir/.git" ]]; then
        git clone --depth 1 "$url" "$dir" || return $?
    else
        git -C "$dir" pull --ff-only || return $?
    fi
    (
        profile_env "$id"
        cd "$HOME"
        case "$id" in
            ml4w)
                curl -fsSL https://ml4w.com/os/stable -o "$SOURCES/ml4w-install.sh" || exit $?
                bash "$SOURCES/ml4w-install.sh"
                ;;
            hyde) cd "$dir/Scripts" && ./install.sh ;;
            sekaipop) cd "$dir" && ./install.sh ;;
            *) echo "Unknown desktop profile: $id" >&2; exit 2 ;;
        esac
    )
}

# Put back what an installer changed for every desktop.
restore_shared() {
    local shell_now
    shell_now="$(getent passwd "$(id -un)" | cut -d: -f7)"
    if [[ -n "$LOGIN_SHELL" && "$shell_now" != "$LOGIN_SHELL" ]]; then
        echo "The installer changed your login shell to $shell_now; putting back $LOGIN_SHELL."
        sudo chsh -s "$LOGIN_SHELL" "$(id -un)" || echo "Could not put back your login shell (chsh -s $LOGIN_SHELL)."
    fi
    # The login screen stays the distribution's (its desktop switcher lists every desktop); a later file in
    # sddm.conf.d wins over an installer's.
    if [[ -d "/usr/share/sddm/themes/$DISTRO_ID" ]]; then
        printf '[Theme]\nCurrent=%s\n' "$DISTRO_ID" | sudo tee "/etc/sddm.conf.d/99-$DISTRO_ID-theme.conf" >/dev/null || true
    fi
}

# Anything an installer still wrote into the real home (one that ignores HOME), to report.
report_strays() {
    local marker="$1" strays
    strays="$(find "$REAL_HOME" -mindepth 1 -maxdepth 3 -newer "$marker" \
                \( -path "$PROFILE_ROOT" -o -path "$REAL_HOME/.cache" -o -path "$STATE" \) -prune -o -print 2>/dev/null \
              | head -n 20 || true)"
    if [[ -n "$strays" ]]; then
        echo "Note: the installer also wrote these in your real home (it did not follow HOME):"
        while IFS= read -r stray; do printf '  %s\n' "$stray"; done <<< "$strays"
        echo "If Halcyon looks different, \`$DISTRO_ID reset-desktop\` restores it (your changes are backed up first)."
    fi
}

failed=0
for id in "${selected[@]}"; do
    case "$id" in
        ml4w) url=https://github.com/mylinuxforwork/dotfiles.git; name="ML4W" ;;
        hyde) url=https://github.com/HyDE-Project/HyDE.git; name="HyDE" ;;
        sekaipop) url=https://github.com/Blapples/SekaiPop.git; name="SekaiPop" ;;
    esac

    profile_home_setup "$id"
    # Installed in its own home before: just make sure its login entry exists and points at the session wrapper. One
    # installed by the older helper (which put it over Halcyon's home and kept only a copy of ~/.config) is installed
    # again, in its own home this time.
    if [[ -f "$STATE/$id.done" && -f "$(profile_home "$id")/.installed-here" ]]; then
        echo "=== $name is already installed; ensuring its login session exists ==="
        register_session "$id" "$name" || failed=1
        continue
    fi

    echo "=== Installing $name in $(profile_home "$id") ==="
    if ! install_packages "$id"; then
        echo "Could not install prerequisite packages for $name; see $LOG"
        failed=1
        continue
    fi

    marker="$(mktemp "$STATE/.before-$id.XXXXXX")"
    if run_installer "$id" "$url"; then
        if register_session "$id" "$name"; then
            touch "$STATE/$id.done" "$(profile_home "$id")/.installed-here"
            echo "$name installed in its own home and registered as a login session."
        else
            echo "Could not register the $name login session."
            failed=1
        fi
    else
        echo "Installation failed for $name; see $LOG"
        failed=1
    fi
    restore_shared
    report_strays "$marker"
    rm -f "$marker"
done

rm -f "$REAL_HOME/.config/autostart/distro-desktop-profiles.desktop"
if (( failed == 0 )); then
    touch "$STATE/completed"
    echo "All requested desktops are ready. Choose one on the login screen (scroll over the desktop previews)."
else
    echo "One or more desktops failed. Review $LOG and rerun this helper; installed desktops are kept."
    exit 1
fi
