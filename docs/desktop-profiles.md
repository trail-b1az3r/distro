# Desktop profile installation

The ISO installer offers Halcyon, Noctalia Shell, ML4W Dotfiles, SekaiPop, HyDE, MacShell, Frameshell, PaperRice and no dotfiles.

- Halcyon is retained as the bootstrap and fallback session.
- Noctalia is a native Wayland shell, installed from Arch's `noctalia` package. Halcyon runs it in place of its own shell, with Halcyon's Hyprland config, keys and themes.

## Noctalia and the other Halcyon shells

Halcyon can run another desktop shell: Halcyon Glass (its own shell over hyprland-plus's liquid glass), Summit,
MacShell or Noctalia Shell. Pick it in the installer's **Halcyon shell** choice (Noctalia Shell as the primary desktop
picks Noctalia), later in Settings > Halcyon > Desktop shell, or with
`distro-install-w-halcyon_desktop_shell-theme SHELL`, which installs its packages first. There is no separate login
session: the Halcyon session starts the chosen shell.

## Selecting multiple profiles from Welcome

Open **Desktop environments** in Frontline Welcome to select any combination of ML4W, HyDE and SekaiPop. The selection is saved per-user at `~/.config/frontline/desktop-profiles.conf`; the first-login installer consumes this file and installs each selected profile as an independent session. The existing `/etc/distro-desktop-profiles.conf` remains supported as a system-wide fallback for ISO and administrator-provisioned selections. Halcyon remains the fallback session.

## Network choices

The installer keeps full nmx as a replacement network manager, or NetworkManager as the default. The optional **NetworkManager smart assist (nmx)** is a separate per-user service: it leaves NetworkManager in control, installs the configured browser, opens detected captive portals in it, and enables NetworkManager system-CA trust for saved 802.1X profiles with no explicit CA only when a server-domain suffix can be retained or derived from the identity realm. It is not enabled when full nmx is selected.

## Autocorrect

`frontline autocorrect TEXT...` corrects explicit text, `printf 'text' | frontline autocorrect` reads stdin, and `frontline autocorrect` prompts in a TTY. `frontline autocorrect --selection` is the separate graphical selected-text replacement mode; it continues to reject terminal windows.

## At the login screen

The login screen's left side is a desktop switcher: scroll the mouse wheel over it (or press Up/Down in the password
field) to choose Halcyon, ML4W, HyDE or SekaiPop. Each desktop shows a preview: a small screenshot its session saves
about ten seconds after you log in (in `/var/lib/frontline/session-previews/`, readable by the login screen); until a
desktop has been used once, a drawn card stands in. Create `~/.config/frontline/no-session-preview` to stop saving them.
The right side shows the system as `fastfetch` does with Frontline's config, written before the login screen starts by
`frontline-sddm-info.service`.

From a terminal: `distro-install-desktop-profiles hyde ml4w` installs desktops (as your user, not with sudo).
