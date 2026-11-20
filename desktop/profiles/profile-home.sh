# Each extra desktop (ML4W, HyDE, SekaiPop) lives in a home of its own: its installer and its sessions run with HOME
# (and the XDG directories) there, so nothing they write lands in Halcyon's home, ~/.config or not: ~/.local, ~/.themes,
# ~/.icons, ~/.zshrc, ~/.mydotfiles... What every desktop should share is linked in from the real home: your files
# (Documents, Downloads, Pictures...), SSH and GPG keys, browser and mail profiles, keyrings, Flatpak app data.
#
#   ~/.local/share/distro-desktop-profiles/homes/<profile>/
#
# Sourced by install-selected.sh and run-session.sh; needs REAL_HOME set to the user's real home.

PROFILE_ROOT="$REAL_HOME/.local/share/distro-desktop-profiles"
PROFILE_HOMES="$PROFILE_ROOT/homes"

# Things in the real home a desktop's home links to (made in the real home when missing, for the user directories).
PROFILE_SHARED_DIRS=(Desktop Documents Downloads Music Pictures Videos Public Templates Projects)
PROFILE_SHARED_OPTIONAL=(.ssh .gnupg .thunderbird .pki .password-store .var .local/share/keyrings
                         .local/share/Steam .steam .gitconfig .config/git .config/gh .config/user-dirs.dirs
                         .config/user-dirs.locale .face .face.icon .local/share/fonts)
# Browsers (profiles, so your logins, history, extensions and passwords, and their caches) and apps you sign in to:
# carried over both ways. Whichever desktop first makes one, it ends up in the real home and every desktop links to it
# (profile_carry). Firefox keeps profiles in ~/.mozilla, or since Firefox 147 in ~/.config/mozilla for new ones: both.
PROFILE_SHARED_APPS=(
    .mozilla .config/mozilla .cache/mozilla
    .librewolf .cache/librewolf .zen .cache/zen .floorp .cache/floorp .waterfox .cache/waterfox
    .config/google-chrome .cache/google-chrome .config/google-chrome-beta .cache/google-chrome-beta
    .config/chromium .cache/chromium .config/BraveSoftware .cache/BraveSoftware .config/vivaldi .cache/vivaldi
    .config/microsoft-edge .cache/microsoft-edge .config/opera .cache/opera .config/thorium .cache/thorium
    .config/net.imput.helium .cache/net.imput.helium
    .config/oynix .local/share/oynix .cache/oynix .local/share/OyNIx .cache/OyNIx
    .config/qutebrowser .local/share/qutebrowser .cache/qutebrowser
    .config/discord .config/vesktop .config/Signal .config/Element .local/share/TelegramDesktop .config/Slack
    .config/spotify .cache/spotify .config/obsidian .config/Nextcloud .local/share/Nextcloud .config/rclone
    .local/share/nexora-msg .local/share/kwalletd .config/kwalletrc .docker .kube .aws .config/gcloud
)

profile_home() { printf '%s/%s\n' "$PROFILE_HOMES" "$1"; }

# Make (or repair) a desktop's home. An older install kept only a copy of ~/.config (configs/<profile>): it becomes
# this home's .config.
profile_home_setup() {
    local id="$1" home name target
    home="$(profile_home "$id")"
    mkdir -p "$home/.config" "$home/.local/share" "$home/.local/state" "$home/.local/bin" "$home/.cache"
    chmod 700 "$home"
    if [[ -d "$PROFILE_ROOT/configs/$id" && ! -e "$home/.migrated-config" ]]; then
        cp -an "$PROFILE_ROOT/configs/$id/." "$home/.config/" 2>/dev/null || true
        : > "$home/.migrated-config"
    fi
    for name in "${PROFILE_SHARED_DIRS[@]}"; do
        mkdir -p "$REAL_HOME/$name"
        profile_link "$home" "$name"
    done
    for name in "${PROFILE_SHARED_OPTIONAL[@]}"; do
        [[ -e "$REAL_HOME/$name" ]] && profile_link "$home" "$name"
    done
    for name in "${PROFILE_SHARED_APPS[@]}"; do
        profile_carry "$home" "$name"
    done
    return 0
}

# Carry a browser or app profile over between the real home and a desktop's home (both ways), then link it:
#   only in the desktop's home    moved to the real home (you signed in there first), then linked
#   in both                       the desktop's own copy is kept aside, in .local/state/distro-desktop-profiles/own,
#                                 and the real home's (Halcyon's) is used, so every desktop has the same one
#   only in the real home         linked
# Run at each login of the desktop (run-session.sh) and at its install, never while that desktop's apps run.
profile_carry() {
    local home="$1" name="$2" target="$1/$2" real="$REAL_HOME/$2" aside
    if [[ -L "$target" ]]; then
        # Linked already (to the real home, or something else the user chose): left as it is.
        return 0
    fi
    if [[ -e "$target" ]]; then
        if [[ ! -e "$real" && ! -L "$real" ]]; then
            mkdir -p "$(dirname -- "$real")"
            mv -- "$target" "$real" || return 0
        elif ! rmdir "$target" 2>/dev/null; then
            aside="$home/.local/state/distro-desktop-profiles/own/$name.$(date +%Y%m%d-%H%M%S)"
            mkdir -p "$(dirname -- "$aside")"
            mv -- "$target" "$aside" || return 0
            echo "Kept this desktop's own $name in $aside; using the one from your real home." >&2
        fi
    fi
    [[ -e "$real" ]] || return 0
    mkdir -p "$(dirname -- "$target")"
    ln -s "$real" "$target"
}

# Link one shared thing into a desktop's home, unless the desktop already has its own there.
profile_link() {
    local home="$1" name="$2" target="$1/$2"
    if [[ -L "$target" ]]; then return 0; fi
    if [[ -e "$target" ]]; then
        # An empty directory a desktop made before the link existed: replace it with the link.
        rmdir "$target" 2>/dev/null || return 0
    fi
    mkdir -p "$(dirname -- "$target")"
    ln -s "$REAL_HOME/$name" "$target"
}

# Whether a desktop's home has its own Hyprland configuration: hyprland.lua (Hyprland 0.57 reads nothing else), readable
# (not a link left dangling), and not the example Hyprland writes when it finds none (autogenerated). An install that
# left none must not count as installed: the desktop would open as plain Hyprland.
profile_config_ok() {
    local config
    config="$(profile_home "$1")/.config/hypr/hyprland.lua"
    [[ -r "$config" ]] || return 1
    ! grep -Eq '^[^-]*autogenerated[[:space:]]*=[[:space:]]*true' "$config"
}

# What is wrong with a desktop's configuration, in words (empty when it is fine).
profile_config_problem() {
    local hypr
    hypr="$(profile_home "$1")/.config/hypr"
    if [[ -L "$hypr/hyprland.lua" && ! -e "$hypr/hyprland.lua" ]]; then
        echo "its hyprland.lua is a link to something that is not there"
    elif [[ -L "$hypr" && ! -e "$hypr" ]]; then
        echo "its ~/.config/hypr is a link to something that is not there"
    elif [[ ! -e "$hypr/hyprland.lua" && -e "$hypr/hyprland.conf" ]]; then
        echo "it has only hyprland.conf, which Hyprland 0.57 no longer reads (it needs hyprland.lua)"
    elif [[ ! -e "$hypr/hyprland.lua" ]]; then
        echo "it has no Hyprland configuration (~/.config/hypr/hyprland.lua)"
    elif ! profile_config_ok "$1"; then
        echo "its hyprland.lua is Hyprland's generated example, not the desktop's"
    fi
}

# Put a generated example (or a dangling link) aside, so an install starts from nothing and is not mistaken for one.
profile_config_clear() {
    local hypr stamp
    hypr="$(profile_home "$1")/.config/hypr"
    stamp="$(date +%Y%m%d-%H%M%S)"
    if [[ -L "$hypr" && ! -e "$hypr" ]]; then
        mv -- "$hypr" "$hypr.broken-$stamp"
    elif [[ -e "$hypr/hyprland.lua" || -L "$hypr/hyprland.lua" ]] && ! profile_config_ok "$1"; then
        mv -- "$hypr/hyprland.lua" "$hypr/hyprland.lua.not-installed-$stamp"
    fi
    return 0
}

# The environment a desktop runs in: its home, its XDG directories, its ~/.local/bin first.
profile_env() {
    local home
    home="$(profile_home "$1")"
    export HOME="$home"
    export XDG_CONFIG_HOME="$home/.config" XDG_DATA_HOME="$home/.local/share"
    export XDG_STATE_HOME="$home/.local/state" XDG_CACHE_HOME="$home/.cache"
    local entry path="$home/.local/bin"
    local IFS=:
    for entry in $PATH; do
        [[ "$entry" == "$REAL_HOME/.local/bin" || "$entry" == "$home/.local/bin" ]] || path="$path:$entry"
    done
    export PATH="$path"
    unset ZDOTDIR
}
