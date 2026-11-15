# Desktop profile installation

The ISO installer offers Halcyon, ML4W Dotfiles, SekaiPop and HyDE.

- Halcyon is retained as the bootstrap and fallback session.
- Select one external profile as the primary profile, then optionally select any of the others as additional profiles.
- External installers run on the first Halcyon login in a visible terminal and require the user to confirm before any upstream script runs.
- **Each extra desktop has a home of its own**, `~/.local/share/distro-desktop-profiles/homes/<profile>/`. Its upstream
  installer runs with `HOME` (and the XDG directories) there, and so does its login session, so nothing it writes
  (`~/.config`, `~/.local`, `~/.themes`, `~/.icons`, `~/.zshrc`, `~/.mydotfiles`...) touches Halcyon's home. What every
  desktop should share is linked in from your real home: Desktop, Documents, Downloads, Music, Pictures, Videos,
  Projects, and `.ssh`, `.gnupg`, browser and mail profiles, keyrings, `.var` (Flatpak app data), your Git config.
- Each installed desktop gets a login entry (`/usr/share/wayland-sessions/nexora-<profile>.desktop`, started by
  `/usr/bin/distro-desktop-session`).
- **Installing one changes no other desktop.** Every upstream installer is guarded:
  - Before it runs, Halcyon's desktop configuration in your real home is copied: the Hyprland, bar, launcher,
    terminal, shell and theme folders in `~/.config`, the dotfiles in your home, `~/.local/bin`, and your themes,
    icons, fonts and login entries (with reflinks on btrfs, so it costs nothing). Afterwards, anything the installer
    wrote there anyway (by a full path, `getent passwd` or a helper that resets `HOME`) is moved into the desktop's
    own home, and Halcyon's files are put back. If the desktop already has its own copy, the installer's is set aside
    in `~/.local/state/distro-desktop-profiles/set-aside/<profile>/`. What other programs keep in your home (browsers,
    editors, games) is not touched. `desktop/profiles/guard-home.py` does this.
  - It cannot replace hyprland-plus with the stock `hyprland` package: its `pacman` and `sudo pacman` leave `hyprland`
    out (hyprland-plus provides it) and a query for it answers for hyprland-plus (`desktop/profiles/guard-bin/`). If
    hyprland-plus is replaced all the same, it is installed again.
  - It runs in a D-Bus session of its own, so the gsettings it sets (GTK theme, icons, cursor, dark mode) go to its
    own home, and without the running Halcyon session's address, so it cannot reload or restyle Halcyon or start its
    bars there. Each desktop's session starts the user's services (dconf among them) in its own home, and Halcyon's
    login starts them in yours.
  - Login entries it adds are set aside in `/var/lib/nexora/set-aside/` (they would start with Halcyon's home), and
    any it changes, Halcyon's among them, are put back, as are the login screen's settings (`/etc/sddm.conf`,
    `/etc/sddm.conf.d/`). Your login shell is put back if it changes it.
- Packages are installed system-wide, once for every desktop.
- Desktops installed by the older helper (which installed over Halcyon's home and kept only a copy of `~/.config`)
  are installed again, in their own home, the next time the helper runs; their saved configuration is carried over.

## Selecting multiple profiles from Welcome

Open **Desktop environments** in Nexora Welcome to select any combination of ML4W, HyDE and SekaiPop. The selection is saved per-user at `~/.config/nexora/desktop-profiles.conf`; the first-login installer consumes this file and installs each selected profile as an independent session. The existing `/etc/distro-desktop-profiles.conf` remains supported as a system-wide fallback for ISO and administrator-provisioned selections. Halcyon remains the fallback session.

## Network choices

The installer keeps full nmx as a replacement network manager, or NetworkManager as the default. The optional **NetworkManager smart assist (nmx)** is a separate per-user service: it leaves NetworkManager in control, installs the configured browser, opens detected captive portals in it, and enables NetworkManager system-CA trust for saved 802.1X profiles with no explicit CA only when a server-domain suffix can be retained or derived from the identity realm. It is not enabled when full nmx is selected.

## Autocorrect

`nexora autocorrect TEXT...` corrects explicit text, `printf 'text' | nexora autocorrect` reads stdin, and `nexora autocorrect` prompts in a TTY. `nexora autocorrect --selection` is the separate graphical selected-text replacement mode; it continues to reject terminal windows.

## At the login screen

The login screen's left side is a desktop switcher: scroll the mouse wheel over it (or press Up/Down in the password
field) to choose Halcyon, ML4W, HyDE or SekaiPop. Each desktop shows a preview: a small screenshot its session saves
about ten seconds after you log in (in `/var/lib/nexora/session-previews/`, readable by the login screen); until a
desktop has been used once, a drawn card stands in. Create `~/.config/nexora/no-session-preview` to stop saving them.
The right side shows the system as `fastfetch` does with Nexora's config, written before the login screen starts by
`nexora-sddm-info.service`.

From a terminal: `distro-install-desktop-profiles hyde ml4w` installs desktops (as your user, not with sudo).
