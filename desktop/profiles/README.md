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

After installation, log out. On the login screen, scroll over the desktop previews on the left to choose
Halcyon, ML4W, HyDE or SekaiPop.

## Configuration safety

Each additional desktop has a home of its own under
`~/.local/share/distro-desktop-profiles/homes/<profile>`: its installer and its sessions run there, so it cannot
overwrite Halcyon's files. Your documents, keys and browser profiles are linked in and shared. If Halcyon was changed
by an install made before this, `nexora reset-desktop` restores it.

Installer logs are stored at `~/.local/state/distro-desktop-profiles/install.log`.

## Notes

The upstream desktop installers are third-party scripts and may install additional packages or modify system-wide
themes and portal settings. Each desktop's own files stay in its home; system packages are shared by all of them.
If an installer changes your login shell it is put back, and the login screen stays Nexora's.
