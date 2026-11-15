#!/usr/bin/env python3
"""Keeps an extra desktop's upstream installer out of Halcyon's home.

The installer runs with HOME set to the desktop's own home (profile-home.sh), but some write into the real home all
the same: through an absolute path, `getent passwd`, `~user`, or a helper that resets HOME. Before it runs, this
takes a copy of what a desktop installer writes there (the desktop's configuration: ~/.config's Hyprland, bar,
launcher, terminal, shell and theme folders, the dotfiles in the home, ~/.local/bin, the user's themes, icons, fonts
and login entries); afterwards it puts every one of those back as it was, and moves what the installer wrote there
into the desktop's own home, where it belongs, so the desktop still has it. Folders and files that are new in the
real home are moved there too. What other programs keep in the home (browsers, editors, games) is left alone: the
copy is not taken of it, so nothing a running program writes in the meantime is undone.

    guard-home.py snapshot REAL_HOME SNAPSHOT_DIR
    guard-home.py restore REAL_HOME SNAPSHOT_DIR PROFILE_HOME STRAYS_DIR

SHARED (environment, space-separated paths relative to the home) names what every desktop shares with Halcyon
(profile-home.sh): those are never touched. The copy is made with reflinks where the filesystem has them (btrfs).
"""

import json
import os
import shutil
import subprocess
import sys

# The folders whose entries are looked at one by one ("units"): the home itself and these.
CONTAINERS = [".", ".config", ".local", ".local/share"]

# What a desktop installer writes, and is put back afterwards. Anything at the top of the home that is a file (the
# dotfiles) is in it too, except the histories that shells keep writing.
GUARDED = {
    ".": {".themes", ".icons", ".fonts", ".oh-my-zsh", ".zsh", ".zplug", ".zinit", ".p10k.zsh", ".mydotfiles",
          ".ml4w", ".hyde", ".sekaipop", ".dotfiles", ".wallpapers"},
    ".config": {"hypr", "waybar", "rofi", "wofi", "fuzzel", "tofi", "walker", "anyrun", "wlogout", "swaync", "dunst",
                "mako", "kitty", "alacritty", "foot", "wezterm", "ghostty", "fish", "zsh", "starship.toml",
                "fastfetch", "neofetch", "cava", "btop", "htop", "nwg-look", "nwg-dock-hyprland", "nwg-dock",
                "nwg-drawer", "gtk-2.0", "gtk-3.0", "gtk-4.0", "qt5ct", "qt6ct", "Kvantum", "kdeglobals",
                "dolphinrc", "xsettingsd", "swappy", "satty", "swaylock", "ags", "eww", "quickshell", "matugen",
                "wal", "wallust", "swww", "waypaper", "hyprpanel", "nvim", "environment.d", "systemd", "uwsm",
                "xdg-desktop-portal", "mimeapps.list", "menus", "dconf", "ml4w", "ml4w-hyprland-settings", "hyde",
                "sekaipop", "illogical-impulse", "halcyon", "nexora", "Thunar", "xfce4", "electron-flags.conf",
                "code-flags.conf", "chrome-flags.conf", "MangoHud", "spicetify", "vesktop/themes", "zshrc",
                "bashrc", "lsd", "eza", "yazi", "ranger", "pipewire", "wireplumber", "autostart"},
    ".local": {"bin"},
    ".local/share": {"applications", "icons", "themes", "fonts", "wayland-sessions", "backgrounds", "wallpapers",
                     "color-schemes", "nwg-look", "nwg-dock-hyprland", "rofi", "hyde", "ml4w", "sekaipop", "waybar",
                     "fastfetch", "dbus-1", "hyprland", "quickshell", "illogical-impulse", "halcyon"},
}

# Never looked at: caches, state, the desktops' own homes and this guard's copy, and the folders programs that may be
# running keep busy (a browser writing its profile while a desktop installs must not have it undone or moved).
SKIP = {
    ".": {".cache", ".local", ".config", ".var", ".steam", ".mozilla", ".thunderbird", ".pki", ".npm", ".cargo",
          ".rustup", ".gradle", ".m2", ".vscode", ".vscode-oss", ".java", ".dbus", ".nv", ".android", ".wine",
          ".gnupg", ".ssh", ".password-store", ".lesshst", ".viminfo", ".wget-hsts", ".python_history",
          ".node_repl_history", ".sudo_as_admin_successful", ".xsession-errors", ".xsession-errors.old",
          ".ICEauthority", ".Xauthority", ".pulse-cookie", ".esd_auth", ".zcompdump"},
    ".config": {"chromium", "google-chrome", "google-chrome-beta", "google-chrome-unstable", "BraveSoftware",
                "vivaldi", "microsoft-edge", "opera", "discord", "discordcanary", "vesktop", "Code", "Code - OSS",
                "VSCodium", "Cursor", "Slack", "obsidian", "spotify", "Signal", "Element", "teams-for-linux",
                "JetBrains", "unity3d", "pulse", "kdeconnect", "evolution", "libreoffice", "gh", "git",
                "user-dirs.dirs", "user-dirs.locale", "monitors.xml", "QtProject.conf", "Electron"},
    ".local": {"state", "share", "lib", "pipx"},
    ".local/share": {"distro-desktop-profiles", "keyrings", "Steam", "flatpak", "Trash", "containers",
                     "recently-used.xbel", "gvfs-metadata", "baloo", "zeitgeist", "akonadi", "gnome-boxes",
                     "libvirt", "docker", "waydroid", "bottles", "lutris", "PrismLauncher", "nvim", "zoxide",
                     "fish", "mime", "Anki2", "Mumble"},
}

# Larger than this, a unit is not copied (and so not put back): on a filesystem without reflinks the copy would be
# slow and take the space twice. It is still reported if it changes.
COPY_LIMIT = 300 * 1024 * 1024


def shared() -> set[str]:
    return {p.strip("/") for p in os.environ.get("SHARED", "").split() if p.strip("/")}


def rel_join(container: str, name: str) -> str:
    return name if container == "." else f"{container}/{name}"


def history_like(name: str) -> bool:
    return name.endswith("history") or name.endswith("_history") or name.endswith(".swp")


def skipped(container: str, name: str, share: set[str]) -> bool:
    rel = rel_join(container, name)
    return (name in SKIP.get(container, set()) or rel in share or rel in CONTAINERS or history_like(name)
            or any(s.startswith(rel + "/") for s in share))


def guarded(home: str, container: str, name: str) -> bool:
    if name in GUARDED.get(container, set()):
        return True
    # The dotfiles at the top of the home: .zshrc, .bashrc, .profile, .gtkrc-2.0, .Xresources...
    path = os.path.join(home, rel_join(container, name))
    return container == "." and name.startswith(".") and (os.path.islink(path) or os.path.isfile(path))


def listing(home: str, container: str) -> list[str]:
    try:
        return sorted(os.listdir(os.path.join(home, container)))
    except OSError:
        return []


def signature(path: str) -> list:
    st = os.lstat(path)
    if os.path.islink(path):
        return ["link", os.readlink(path)]
    if os.path.isdir(path):
        return ["dir", st.st_mode & 0o7777]
    return ["file", st.st_size, st.st_mtime_ns, st.st_mode & 0o7777]


def walk(home: str, rel: str) -> tuple[dict, int]:
    """Every path under one unit (the unit itself included), and their total size."""
    sigs, total = {}, 0
    top = os.path.join(home, rel)
    if not os.path.lexists(top):
        return sigs, 0
    sigs[rel] = signature(top)
    if os.path.isdir(top) and not os.path.islink(top):
        for root, dirs, files in os.walk(top):
            for name in dirs + files:
                full = os.path.join(root, name)
                r = os.path.relpath(full, home)
                try:
                    sigs[r] = signature(full)
                    if sigs[r][0] == "file":
                        total += sigs[r][1]
                except OSError:
                    pass
    elif sigs[rel][0] == "file":
        total = sigs[rel][1]
    return sigs, total


def copy(src: str, dst: str) -> None:
    """A copy keeping modes, times and links, with reflinks where the filesystem has them."""
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if subprocess.run(["cp", "-a", "--reflink=auto", "--", src, dst], capture_output=True).returncode == 0:
        return
    if os.path.isdir(src) and not os.path.islink(src):
        shutil.copytree(src, dst, symlinks=True, dirs_exist_ok=True)
    else:
        shutil.copy2(src, dst, follow_symlinks=False)


def remove(path: str) -> None:
    if os.path.isdir(path) and not os.path.islink(path):
        shutil.rmtree(path)
    elif os.path.lexists(path):
        os.unlink(path)


def snapshot(home: str, snap: str) -> None:
    share = shared()
    if os.path.lexists(snap):
        remove(snap)
    os.makedirs(os.path.join(snap, "copy"))
    manifest = {"listing": {}, "units": {}, "files": {}}
    for container in CONTAINERS:
        names = listing(home, container)
        manifest["listing"][container] = names
        for name in names:
            if skipped(container, name, share) or not guarded(home, container, name):
                continue
            rel = rel_join(container, name)
            sigs, total = walk(home, rel)
            copied = total <= COPY_LIMIT
            if copied:
                copy(os.path.join(home, rel), os.path.join(snap, "copy", rel))
            manifest["units"][rel] = copied
            manifest["files"].update(sigs)
    with open(os.path.join(snap, "manifest.json"), "w") as f:
        json.dump(manifest, f)


def move_out(home: str, rel: str, profile: str, strays: str, notes: list) -> None:
    """Move what an installer wrote in the real home into the desktop's own home (or, if it has its own there
    already, aside into the strays folder)."""
    src = os.path.join(home, rel)
    dst = os.path.join(profile, rel)
    if os.path.lexists(dst):
        dst = os.path.join(strays, rel)
        if os.path.lexists(dst):
            remove(dst)
        where = "set aside in " + strays
    else:
        where = "moved to the desktop's own home"
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.move(src, dst)
    notes.append(f"  ~/{rel}: {where}")


def restore(home: str, snap: str, profile: str, strays: str) -> int:
    share = shared()
    with open(os.path.join(snap, "manifest.json")) as f:
        manifest = json.load(f)
    before = manifest["files"]
    notes: list[str] = []

    # New in the real home: whole folders and files an installer made there.
    for container in CONTAINERS:
        was = set(manifest["listing"].get(container, []))
        for name in listing(home, container):
            if name in was or skipped(container, name, share):
                continue
            move_out(home, rel_join(container, name), profile, strays, notes)

    # Changed inside what was copied: put back as it was, the installer's version kept for the desktop.
    for rel, copied in manifest["units"].items():
        now, _ = walk(home, rel)
        if not copied:
            if now != {k: v for k, v in before.items() if k == rel or k.startswith(rel + "/")}:
                notes.append(f"  ~/{rel}: changed, too large to have been copied first (left as it is)")
            continue
        # New paths, outermost first, so a new folder moves whole.
        moved: list[str] = []
        for path in sorted(p for p in now if p not in before):
            if any(path.startswith(m + "/") for m in moved):
                continue
            move_out(home, path, profile, strays, notes)
            moved.append(path)
        # Changed or gone: the installer's version goes to the desktop, the copy comes back.
        for path in sorted(p for p, sig in before.items() if p == rel or p.startswith(rel + "/")):
            sig = before[path]
            full = os.path.join(home, path)
            current = signature(full) if os.path.lexists(full) else None
            if current == sig or (sig[0] == "dir" and current and current[0] == "dir"):
                continue
            if current is not None:
                if current[0] == "dir" and sig[0] != "dir":
                    move_out(home, path, profile, strays, notes)
                elif current[0] != "dir":
                    move_out(home, path, profile, strays, notes)
                    notes[-1] += ", Halcyon's put back"
                else:
                    remove(full)
            else:
                notes.append(f"  ~/{path}: removed by the installer, put back")
            if sig[0] != "dir":
                copy(os.path.join(snap, "copy", path), full)
            else:
                os.makedirs(full, exist_ok=True)

    remove(snap)
    if notes:
        print("The installer also wrote in your real home; Halcyon's files are as they were:")
        for line in notes[:40]:
            print(line)
        if len(notes) > 40:
            print(f"  ... and {len(notes) - 40} more")
    return 0


def main(argv: list[str]) -> int:
    if len(argv) == 3 and argv[0] == "snapshot":
        snapshot(os.path.realpath(argv[1]), argv[2])
        return 0
    if len(argv) == 5 and argv[0] == "restore":
        return restore(os.path.realpath(argv[1]), argv[2], argv[3], argv[4])
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
