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
`~/.local/share/distro-desktop-profiles/homes/<profile>`: its installer and its sessions run there. Your documents,
keys and fonts are linked in and shared.

Browsers and the apps you sign in to are carried over both ways, at every login of a desktop: Firefox (both
`~/.mozilla` and Firefox 147's `~/.config/mozilla`), LibreWolf, Zen, Chrome, Chromium, Brave, Vivaldi, Edge, Opera,
OyNIx and qutebrowser, with their caches, and Discord, Vesktop, Signal, Element, Telegram, Slack, Spotify, Obsidian,
Nextcloud, rclone, nexora-msg, KWallet, Docker, kubectl, AWS and gcloud. One used first in an extra desktop moves to
your real home; when both have one, the desktop's own copy is kept in its
`.local/state/distro-desktop-profiles/own/` and Halcyon's is used, so every desktop has the same logins.

Installing one changes no other desktop, even when its installer reaches past its home:

- `guard-home.py` copies Halcyon's desktop configuration first and puts it back afterwards; what the installer wrote
  in the real home is moved into the desktop's own home (or set aside in
  `~/.local/state/distro-desktop-profiles/set-aside/<profile>/`).
- `guard-bin/pacman` and `guard-bin/sudo` keep hyprland-plus installed: the stock `hyprland` package is left out.
- The installer runs in a D-Bus session of its own and without the running Hyprland session's address.
- Login entries it adds are set aside in `/var/lib/nexora/set-aside/`; Halcyon's entry and the login screen's
  configuration are put back.

If Halcyon was changed by an install made before this, `nexora reset-desktop` restores it.

Installer logs are stored at `~/.local/state/distro-desktop-profiles/install.log`.

## Notes

The upstream desktop installers are third-party scripts and may install additional packages or modify system-wide
themes and portal settings. Each desktop's own files stay in its home; system packages are shared by all of them.
If an installer changes your login shell it is put back, and the login screen stays Nexora's; system-wide changes
outside those (a bootloader theme, pacman.conf) are the installer's own and are not undone.
