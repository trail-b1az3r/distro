# The desktop

The desktop is [Hyprland](https://hyprland.org) with the
illogical-impulse / Halcyon shell from
[trail-b1az3r/dots](https://github.com/trail-b1az3r/dots): a bar, sidebars
(AI chat, notifications, quick settings), an overview, a launcher, an
on-screen keyboard, Material You colours taken from the wallpaper and
Wayland-first apps. The dots are pinned to a commit (the `desktop/dots`
submodule) and deployed unchanged, so upstream's documentation applies.

## First steps

* **Super** opens the search/launcher; **Super + /** shows every keybind.
* **Super + Enter** terminal (Konsole), **Super + E** files (Dolphin),
  **Super + W** browser, **Super + Q** close a window.
* The Welcome wizard: **Super + F1**. The updater: **Super + Shift + U**.
  The AI launcher: **Ctrl + Super + A**.
* Wallpaper picker: **Ctrl + Super + T**; theme menu: **Ctrl + Super + Shift + T**.

The three distribution shortcuts use chords upstream leaves free; the test
suite checks this on every change, because Hyprland runs *every* action bound
to a chord.

## How the configuration is put together

`~/.config/hypr/hyprland.lua` loads, in order:

1. upstream's defaults (`~/.config/hypr/hyprland/`),
2. the Halcyon layer (`hyprland/halcyon/`),
3. the distribution layer (`~/.config/hypr/nexora/init.lua`): driver
   environment from `/etc/nexora/gpu.env`, your AI environment, `~/.local/bin`
   on `PATH`, sharp XWayland on HiDPI, first-login setup, the three shortcuts,
4. **your files in `~/.config/hypr/custom/`** — they win, and nothing ever
   overwrites them. The installer writes your keyboard layout, display scales
   and default applications there (`general.lua`, `variables.lua`); edit
   them freely.

Updates (`nexora update`, the updater) refresh everything else. A file you
changed outside `custom/` is backed up before it is replaced
(`~/.local/state/nexora/desktop-backups/<date>/`).
`nexora reset-desktop` restores the defaults after backing up yours.

## Default applications

Konsole (terminal), Dolphin (files), Firefox (browser, if installed), Okular
(PDF), Gwenview (images), Haruna/mpv (media), Ark (archives), OnlyOffice
(documents), Kate (text), and the code editor from `CODE_EDITOR` in
`distro.conf` (Code - OSS by default). Change them in
`~/.config/hypr/custom/variables.lua` (keybinds) and with the usual
`xdg-mime` / *Default Applications* settings.

## The Plasma fallback session

If you enabled *KDE Plasma fallback session*, the login screen offers
*Plasma (Wayland)* and *Plasma (X11)*: a conventional desktop for when you need
X11 or something more familiar. Choose the session at the bottom left of the
login screen.

## Shells

Terminals open Fish, configured by the dots plus the distribution's defaults
(`/usr/share/fish/vendor_conf.d/nexora.fish`): abbreviations (`up` → update,
`doctor`, `gpu`, `hw`…), `sysinfo`, zoxide, fzf and direnv integration. Bash
remains the login shell unless you chose Fish in the installer, so scripts and
`sudo -i` behave as on any Arch system.
