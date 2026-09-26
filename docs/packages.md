# Packages and updates

## Where packages come from

1. **Arch Linux** (`core`, `extra`, `multilib`) — almost everything.
2. **EndeavourOS** (`[endeavouros]`) — its keyring, mirror list and tools.
3. **The distribution repository** (`[nexora]`) — this distribution's own
   packages (`nexora-core`, `-desktop`, `-branding`, `-welcome`, `-installer`,
   `-ai`, the Google Sans Flex font) and prebuilt AUR packages the desktop and
   drivers need (the illogical-impulse meta packages, Quickshell, fonts,
   themes, the NVIDIA 580 legacy driver, llama.cpp). Built reproducibly from
   this repository (see [iso-building.md](iso-building.md)).
4. **The AUR** through `yay`, for anything else.

`pacman` stays the package manager; nothing replaces it.

```bash
sudo pacman -S firefox         # official repositories
yay -S some-aur-package        # AUR (review PKGBUILDs before building)
nexora install office docker   # features from the installer, by name
flatpak install flathub org.gimp.GIMP
```

## Updating

* **The updater** (Super + Shift + U, or *System Update*): shows what each
  source would update — packages, AUR, Flatpak, the desktop configuration,
  AI tools, GPU configuration — and Arch news posts that may need manual
  steps, then updates what you select.
* **The command line:**

```bash
nexora update             # everything, asking pacman/yay's usual questions
nexora update --check     # list only (exit code 100 when updates exist)
nexora update --no-aur --no-flatpak
sudo pacman -Syu          # still works exactly as on Arch
```

Tips: update regularly (at least monthly), read the Arch news the updater
shows, and keep a snapshot (Btrfs) before big updates — with snapper, one is
taken automatically before and after every pacman transaction (snap-pac).

The desktop configuration is updated separately from packages, only when the
pinned dots version or the distribution layer changes, and never touches
`~/.config/hypr/custom/`.

## Pacman hooks the distribution adds

| Hook | Does |
|---|---|
| `90-nexora-os-release.hook` | keeps `/usr/lib/os-release`, `/etc/issue` and `/etc/lsb-release` branded when `filesystem` or `lsb-release` are updated |
| `95-nexora-boot.hook` | regenerates boot entries after kernel or initramfs changes (removed kernels drop out of the menu; the GRUB theme is copied next to `grub.cfg`) |
