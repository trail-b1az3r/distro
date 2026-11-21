#!/usr/bin/env bash
# Installs the extra desktops chosen in Welcome or the installer (ML4W, HyDE, SekaiPop), each in a home of its own
# (profile-home.sh): the upstream installer runs with HOME there, and its login entry starts Hyprland with that home.
# Nothing an installer does may change Halcyon or another desktop:
#   - anything it still writes in the real home is moved into its own home, Halcyon's files put back (guard-home.py)
#   - it cannot swap hyprland-plus for the stock hyprland package (guard-bin/pacman and guard-bin/sudo)
#   - its gsettings go to its own home (a D-Bus session of its own), and it cannot reach the running Halcyon session
#   - login entries it adds or changes are set aside or put back, and the login screen, its configuration and your
#     login shell stay as they were
# Run as the logged-in user from a visible terminal: upstream installers are interactive and ask for sudo themselves.
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
    for candidate in /usr/share/*/packages/lists/desktop-ml4w.list /usr/share/*/packages/lists/desktop-work.list; do
        [[ -f "$candidate" ]] || continue
        DATA_ROOT="${candidate%/packages/lists/desktop-*.list}"
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
# The system's root, for the paths below (a test runs them in a folder).
SYSROOT="${DISTRO_SYSROOT:-}"
SESSION_DIR="$SYSROOT/usr/share/wayland-sessions"
SET_ASIDE="$SYSROOT/var/lib/$DISTRO_ID/set-aside"
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
    case "$id" in ml4w|hyde|sekaipop|work|macshell|frameshell|paperrice) valid+=("$id") ;;
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
echo "cannot change Halcyon's files. Your documents, keys, browsers (logins, history, cache) and app sign-ins are"
echo "shared with it."
echo "Packages are installed system-wide (once, for every desktop), but hyprland-plus stays: an installer cannot"
echo "replace it. Anything an installer writes in your real home goes to its own; your login shell, the login screen"
echo "and Halcyon's login entry stay as they are."
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
    local id="$1"
    local list="$LISTS/desktop-$id.list"
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
# It runs with the guard's pacman and sudo first in PATH, without the running Hyprland session's address (so it cannot
# reload, restyle or start bars in Halcyon), and in a D-Bus session of its own where there is one to start, so the
# gsettings it sets (GTK theme, icons, cursor, dark mode) are stored in its own home rather than Halcyon's.
run_installer() {
    local id="$1" url="$2" dir="$SOURCES/$1"
    # Up to date with upstream. A checkout that cannot simply move forward (upstream rewrote its history, or an
    # earlier run was interrupted) is set aside and cloned again, rather than failing the install.
    if [[ -d "$dir/.git" ]] && ! git -C "$dir" pull --ff-only; then
        echo "Could not update the $id sources; downloading them again."
        mv -- "$dir" "$dir.old-$(date +%Y%m%d-%H%M%S)" || return 1
    fi
    if [[ ! -d "$dir/.git" ]]; then
        git clone --depth 1 "$url" "$dir" || return $?
    fi
    # HyDE keeps a Python environment (uv, and its deez-dots deployer) in the desktop's home. One left half-made by an
    # install that failed stops the next with "deez-dots not found in Python environment": set aside, made again.
    local pyenv
    pyenv="$(profile_home hyde)/.local/state/hyde/python_env"
    if [[ "$id" == hyde && ! -f "$STATE/hyde.done" && -e "$pyenv" ]]; then
        mv -- "$pyenv" "$pyenv.old-$(date +%Y%m%d-%H%M%S)" || return 1
    fi
    (
        profile_env "$id"
        export PATH="$SCRIPT_DIR/guard-bin:$PATH"
        unset HYPRLAND_INSTANCE_SIGNATURE HYPRLAND_CMD SWAYSOCK NIRI_SOCKET
        cd "$HOME"
        local -a cmd
        case "$id" in
            ml4w)
                curl -fsSL https://ml4w.com/os/stable -o "$SOURCES/ml4w-install.sh" || exit $?
                cmd=(bash "$SOURCES/ml4w-install.sh")
                ;;
            hyde) cd "$dir/Scripts" || exit 1; cmd=(./install.sh) ;;
            sekaipop) cd "$dir" || exit 1; cmd=(./install.sh) ;;
            work) rsync -a --exclude=.git "$dir/dotfiles/" "$HOME/"; cmd=(true) ;;
            macshell) cd "$dir" || exit 1; cmd=(bash install.sh --yes --no-deps --no-services) ;;
            frameshell) cd "$dir" || exit 1; cmd=(./install.sh --yes --no-login --no-boot) ;;
            paperrice) cd "$dir" || exit 1; cmd=(bash ./setup-paper-theme.sh) ;;
            *) echo "Unknown desktop profile: $id" >&2; exit 2 ;;
        esac
        if command -v dbus-run-session >/dev/null; then
            exec dbus-run-session -- "${cmd[@]}"
        fi
        exec "${cmd[@]}"
    )
}

# What an installer may change on the system that every desktop shares: the login entries, the login screen's
# configuration, and hyprland-plus. Copied before it runs (sys_snapshot) and put back after (sys_restore).
SYS_FILES=("$SYSROOT/etc/sddm.conf" "$SYSROOT/etc/sddm.conf.d" "$SESSION_DIR")
sys_snapshot() {
    local snap="$1" path f
    mkdir -p "$snap"
    for path in "${SYS_FILES[@]}"; do
        if [[ -d "$path" ]]; then
            for f in "$path"/*; do
                [[ -f "$f" ]] || continue
                install -D -m 0644 "$f" "$snap$f" 2>/dev/null || sudo install -D -m 0644 "$f" "$snap$f" || true
            done
        elif [[ -f "$path" ]]; then
            install -D -m 0644 "$path" "$snap$path" 2>/dev/null || sudo install -D -m 0644 "$path" "$snap$path" || true
        fi
    done
    HAD_PLUS=0
    pacman -Q hyprland-plus >/dev/null 2>&1 && HAD_PLUS=1
    return 0
}
ours() {
    case "$(basename "$1")" in "$DISTRO_ID"-*.desktop|"99-$DISTRO_ID-theme.conf") return 0 ;; esac
    return 1
}
sys_restore() {
    local snap="$1" path f saved
    local -a now=()
    for path in "${SYS_FILES[@]}"; do
        if [[ -d "$path" ]]; then
            for f in "$path"/*; do [[ -f "$f" ]] || continue; now+=("$f"); done
        elif [[ -f "$path" ]]; then
            now+=("$path")
        fi
    done
    # Added or changed by the installer.
    for f in "${now[@]}"; do
        ours "$f" && continue
        saved="$snap$f"
        if [[ ! -f "$saved" ]]; then
            echo "The installer added $f; setting it aside in $SET_ASIDE (it would start with Halcyon's home)."
            sudo mkdir -p "$SET_ASIDE" && sudo mv -f -- "$f" "$SET_ASIDE/" || echo "Could not set aside $f."
        elif ! cmp -s "$saved" "$f"; then
            echo "The installer changed $f; putting it back."
            sudo install -m 0644 "$saved" "$f" || echo "Could not put back $f."
        fi
    done
    # Removed by the installer.
    if [[ -d "$snap" ]]; then
        while IFS= read -r -d '' saved; do
            f="${saved#"$snap"}"
            [[ -e "$f" ]] && continue
            echo "The installer removed $f; putting it back."
            sudo install -D -m 0644 "$saved" "$f" || echo "Could not put back $f."
        done < <(find "$snap" -type f -print0)
    fi
    # hyprland-plus replaced after all (an installer that called pacman by its full path): put it back.
    if (( HAD_PLUS )) && ! pacman -Q hyprland-plus >/dev/null 2>&1; then
        echo "The installer replaced hyprland-plus; installing it again."
        sudo pacman -S --needed --noconfirm --ask 4 hyprland-plus || echo "Could not reinstall hyprland-plus: sudo pacman -S hyprland-plus"
    fi
    return 0
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
    if [[ -d "$SYSROOT/usr/share/sddm/themes/$DISTRO_ID" ]]; then
        printf '[Theme]\nCurrent=%s\n' "$DISTRO_ID" | sudo tee "$SYSROOT/etc/sddm.conf.d/99-$DISTRO_ID-theme.conf" >/dev/null || true
    fi
}

# What every desktop shares with Halcyon (profile-home.sh): the guard leaves those alone.
GUARD_SHARED="${PROFILE_SHARED_DIRS[*]} ${PROFILE_SHARED_OPTIONAL[*]} ${PROFILE_SHARED_APPS[*]}"
guard_home() {
    SHARED="$GUARD_SHARED" python3 "$SCRIPT_DIR/guard-home.py" "$@"
}

failed=0
for id in "${selected[@]}"; do
    case "$id" in
        ml4w) url=https://github.com/mylinuxforwork/dotfiles.git; name="ML4W" ;;
        work) url=https://github.com/trail-b1az3r/dotfiles.git; name="My Linux for Work" ;;
        macshell) url=https://github.com/0-ss/MacShell.git; name="MacShell" ;;
        frameshell) url=https://github.com/Swapy-y/Frameshell.git; name="Frameshell" ;;
        paperrice) url=https://github.com/mahaveergurjar/PaperRice.git; name="PaperRice" ;;
        hyde) url=https://github.com/HyDE-Project/HyDE.git; name="HyDE" ;;
        sekaipop) url=https://github.com/Blapples/SekaiPop.git; name="SekaiPop" ;;
    esac

    profile_home_setup "$id"
    # Installed in its own home before: just make sure its login entry exists and points at the session wrapper. One
    # installed by the older helper (which put it over Halcyon's home and kept only a copy of ~/.config) is installed
    # again, in its own home this time.
    if [[ -f "$STATE/$id.done" && -f "$(profile_home "$id")/.installed-here" ]] && profile_config_ok "$id"; then
        echo "=== $name is already installed; ensuring its login session exists ==="
        register_session "$id" "$name" || failed=1
        continue
    fi
    if [[ -f "$STATE/$id.done" ]]; then
        echo "$name was installed, but $(profile_config_problem "$id"): installing it again."
        rm -f "$STATE/$id.done" "$(profile_home "$id")/.installed-here"
    fi
    profile_config_clear "$id"

    echo "=== Installing $name in $(profile_home "$id") ==="
    if ! install_packages "$id"; then
        echo "Could not install prerequisite packages for $name; see $LOG"
        failed=1
        continue
    fi

    snap="$STATE/guard-$id"
    if ! guard_home snapshot "$REAL_HOME" "$snap/home"; then
        echo "Could not take a copy of Halcyon's configuration first; not installing $name."
        failed=1
        continue
    fi
    sys_snapshot "$snap/system"
    status=0
    run_installer "$id" "$url" || status=$?
    problem="$(profile_config_problem "$id")"
    if [[ -n "$problem" ]]; then
        # Not registered: its session would open as plain Hyprland.
        if (( status == 0 )); then
            echo "$name's installer finished, but $problem. It was not registered; the installer's output is in $LOG."
        else
            echo "Installation failed for $name (the installer exited with $status), and $problem; see $LOG"
        fi
        echo "--- the end of $name's installer output ---"
        tail -n 25 "$LOG" | sed 's/^/    /'
        echo "---"
        failed=1
    else
        (( status == 0 )) || echo "$name's installer exited with $status, but its configuration is in place: registering it."
        if register_session "$id" "$name"; then
            touch "$STATE/$id.done" "$(profile_home "$id")/.installed-here"
            echo "$name installed in its own home and registered as a login session."
        else
            echo "Could not register the $name login session."
            failed=1
        fi
    fi
    guard_home restore "$REAL_HOME" "$snap/home" "$(profile_home "$id")" "$STATE/set-aside/$id" \
        || echo "Could not check Halcyon's home after the installer; \`$DISTRO_ID reset-desktop\` restores it."
    sys_restore "$snap/system"
    restore_shared
    python3 -c 'import shutil, sys; shutil.rmtree(sys.argv[1], ignore_errors=True)' "$snap"
done

rm -f "$REAL_HOME/.config/autostart/distro-desktop-profiles.desktop"
if (( failed == 0 )); then
    touch "$STATE/completed"
    echo "All requested desktops are ready. Choose one on the login screen (scroll over the desktop previews)."
else
    echo "One or more desktops failed. Review $LOG and rerun this helper; installed desktops are kept."
    exit 1
fi
