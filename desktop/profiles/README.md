# Additional desktop profiles

Halcyon remains installed as the default desktop. ML4W, HyDE and SekaiPop are
optional Hyprland-based profiles. They are installed as additional SDDM
sessions; installing one does not replace Halcyon.

## Install after the OS is already set up

Run this from a terminal as the normal desktop user (not with sudo):

```bash
distro-install-desktop-profiles ml4w
distro-install-desktop-profiles hyde
distro-install-desktop-profiles sekaipop
```

Pass more than one profile to install several in one run. The helper uses
pacman to install shared system packages with `--needed`, so applications
are installed once for the whole system and are available in every desktop.
It does not create separate application installations per profile.

After installation, log out. In SDDM, open the session selector and choose
Halcyon, ML4W, HyDE or SekaiPop.

## Configuration safety

Each additional desktop has its own snapshot under
`~/.local/share/distro-desktop-profiles/configs/<profile>`. The active
profile's configuration is copied into `~/.config` only while that session
runs, then saved back to that profile when the session exits. The user's
normal `~/.config` is restored afterwards.

Switching sessions therefore does not copy one desktop's settings over
another desktop's settings. Existing profile snapshots are not deleted or
replaced by a repeat install. Re-running the helper for an already installed
profile only repairs its SDDM session entry.

Installer logs are stored at
`~/.local/state/distro-desktop-profiles/install.log`.

## Notes

The upstream desktop installers are third-party scripts and may install
additional packages or modify system-wide themes and portal settings. The
profile configurations themselves remain isolated, but shared system
components are necessarily shared across sessions.
