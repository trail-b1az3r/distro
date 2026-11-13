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
PROFILE_SHARED_OPTIONAL=(.ssh .gnupg .mozilla .thunderbird .pki .password-store .var .local/share/keyrings
                         .local/share/Steam .steam .gitconfig .config/git .config/gh .config/user-dirs.dirs
                         .config/user-dirs.locale .face .face.icon)

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
    return 0
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
