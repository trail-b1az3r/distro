# Desktop profile installation

The ISO installer offers Halcyon, ML4W Dotfiles, SekaiPop and HyDE.

- Halcyon is retained as the bootstrap and fallback session.
- Select one external profile as the primary profile, then optionally select any of the others as additional profiles.
- External installers run on the first Halcyon login in a visible terminal and require the user to confirm before any upstream script runs.
- Each external profile's `~/.config` is saved independently under `~/.local/share/distro-desktop-profiles/configs/`.
- The installer adds an SDDM Wayland session entry for each selected external profile. The session wrapper swaps in that profile's saved configuration while Hyprland runs, saves changes when you log out, and restores the Halcyon config.

Upstream installers still install packages and may change system-wide themes, SDDM settings, portals or other shared files. The profile wrapper isolates the user's config tree; it cannot sandbox arbitrary upstream system changes. Review the upstream prompts, especially when installing more than one profile.

## Network choices

The installer keeps full nmx as a replacement network manager, or NetworkManager as the default. The optional **NetworkManager smart assist (nmx)** is a separate per-user service: it leaves NetworkManager in control, opens detected captive portals in the desktop browser, and enables NetworkManager system-CA trust for saved 802.1X profiles that do not specify a CA. It is not enabled when full nmx is selected.

## Autocorrect

`nexora autocorrect TEXT...` corrects explicit text, `printf 'text' | nexora autocorrect` reads stdin, and `nexora autocorrect` prompts in a TTY. `nexora autocorrect --selection` is the separate graphical selected-text replacement mode; it continues to reject terminal windows.
