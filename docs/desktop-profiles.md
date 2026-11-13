# Desktop profile installation

The ISO installer offers Halcyon, ML4W Dotfiles, SekaiPop and HyDE.

- Halcyon is retained as the bootstrap and fallback session.
- Select one external profile as the primary profile, then optionally select any of the others as additional profiles.
- External installers run on the first Halcyon login in a visible terminal and require the user to confirm before any upstream script runs.
- Each external profile's `~/.config` is saved independently under `~/.local/share/distro-desktop-profiles/configs/`.
- Each installed profile gets its own login entry (`/usr/share/wayland-sessions/nexora-<profile>.desktop`, started by `/usr/bin/distro-desktop-session`). The session wrapper swaps in that profile's saved configuration while Hyprland runs, saves changes when you log out, and restores the Halcyon config.

Upstream installers still install packages and may change system-wide themes, SDDM settings, portals or other shared files. The profile wrapper isolates the user's config tree; it cannot sandbox arbitrary upstream system changes. Review the upstream prompts, especially when installing more than one profile.

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
