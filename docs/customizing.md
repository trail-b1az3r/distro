# Customizing and rebranding

## Rename the distribution

Everything user-visible comes from [`distro.conf`](../distro.conf): names, IDs,
the CLI name, URLs, ISO label, live user, colours, the package repository and
the default editor/browser. To make "Aurora OS":

```sh
DISTRO_NAME="Aurora"
DISTRO_PRETTY_NAME="Aurora OS"
DISTRO_ID="aurora"                 # packages aurora-core..., /etc/aurora, aurora-gpu
DISTRO_CLI="aurora"                # the command
DISTRO_TAGLINE="..."
DISTRO_HOME_URL="https://example.org"   # and DOC/SUPPORT/BUG URLs, DISTRO_GIT_URL
ISO_LABEL_PREFIX="AURORA"
ISO_PUBLISHER="Aurora <https://example.org>"
LIVE_HOSTNAME="aurora-live"
BRAND_BG="#0B1A14"                 # background, surface, text, muted, accents...
BRAND_ACCENT="#3CCB7F"
BRAND_ACCENT_2="#2CB1E0"
DISTRO_REPO_NAME="aurora"
DISTRO_REPO_SERVER="https://github.com/you/aurora/releases/download/repo"
```

Then rebuild: `./build.sh`. The logo, icons, wallpapers, boot splash, GRUB,
SDDM and syslinux themes, fastfetch logo, os-release, pacman hooks, polkit
policy, completions, man page, the website (`site/`) and every string in the apps follow. The logo
itself is `branding/logo/logo-mark.svg.in`: a hand drawing of a sheet with a
snow-capped peak, traced to vector from `branding/logo/source/frontline-sketch.png`
by `branding/logo/source/trace-logo.py` (ink lines, pencil lines and blurred
watercolour washes, in the drawing's own colours). Replace it with your own
mark; `logo.svg.in` is the same mark with the name beside it. Fastfetch shows the
mark as Braille line art (`braille_logo` in `lib/distrokit/build/branding.py`).

The login screen is [SilentSDDM](https://github.com/uiriansan/SilentSDDM)
(`branding/sddm`, see its `UPSTREAM`): `branding/sddm/configs/theme.conf.in`
holds every option, with the `@BRAND_*@` colours; its lock screen shows the
mark, its login screen the plain backdrop. The earlier login theme, with desktop
previews and a system panel, is still installed as `<id>-classic`: choose it with
`Current=<id>-classic` in `/etc/sddm.conf.d/10-<id>.conf`.

## The rename from Nexora

The distribution was Nexora until 26.11.0.2.1. `DISTRO_LEGACY_IDS="nexora"` in
`distro.conf` keeps systems installed under that name updating: every
`frontline-*` package replaces its `nexora-*` one, the package repository is
also published as `[nexora]`, `/usr/bin/nexora` still works, and a pacman hook
(`frontline-migrate-legacy`, `lib/distrokit/system/legacy.py`) moves the rest
over once: pacman.conf's `[nexora...]` sections, `/etc/nexora`, `/var/lib/nexora`,
enabled units, the login and boot themes, and each user's `nexora*` folders
(the old paths stay as links). Nothing is deleted. `make test` checks that a
renamed configuration renders everywhere (`test_branding_rename`).

`distro.conf` is validated: IDs must be lowercase `[a-z0-9-]`, colours
`#RRGGBB`, the ISO label `A-Z0-9_`.

## Profiles and features

* [`profiles/*.toml`](../profiles): Minimal, Standard (default), Developer, AI.
  A profile inherits another, lists package lists and sets feature values.
* [`profiles/features.toml`](../profiles/features.toml): the switches the
  installer shows (label, description, group, the package lists each value
  adds). Add a feature there and it appears in the installer and in
  `frontline install`.

## Package lists

[`packages/lists/*.list`](../packages/lists): one package per line, `#`
comments, `@DISTRO_ID@` placeholders. Any package from Arch, EndeavourOS or
the AUR works; AUR packages are built into the distribution repository
automatically on the next build (and pinned in `aur.lock.json`).

After changing lists or profiles, run `python3 -m distrokit.build.manifests`:
it rewrites [`packages/manifests/`](../packages/manifests), which shows
exactly what each profile, the live ISO and each kind of hardware install, so
the change is visible in review (the tests fail while the manifests are stale).

## Drivers, models, assistants

Data files, not code:

* GPU driver stacks: `hardware/gpu/drivers.toml`; GPU generations:
  `hardware/detection/gpu-families.toml`; VRAM table `gpu-vram.tsv`.
* Surface: `hardware/surface/surface.toml`.
* Models: `ai/models/catalog.toml` (use exact file sizes from Hugging Face).
* Assistants and tools: `ai/hermis/assistant.toml`, `ai/openclaw/assistant.toml`,
  `ai/claude-code/tool.toml`, `ai/hypernix/hypernix.toml`.
* Model server: `ai/runtime/llama-server.toml`.

## The desktop

* To follow a newer dots commit: `git -C desktop/dots pull && git add desktop/dots`.
  The keybind test fails if upstream starts using a chord the distribution
  layer binds.
* The distribution layer is `desktop/overlay/` (Hyprland `init.lua.in`, Fish,
  profile.d, session start script, desktop entries, default applications).
* User-facing defaults written at install time (keyboard, display scales,
  apps) go to `~/.config/hypr/custom/`, which is the user's.

## The live ISO and boot menus

`iso/`: `profiledef.sh.in`, `grub/` (UEFI: `menu.cfg.in` holds the entries,
`grub.cfg.in` and `loopback.cfg.in` load it), `syslinux/` (BIOS), `airootfs/`
(files added to the live system). The UEFI menu's look is
`branding/grub/theme.txt.in`, shared with GRUB on installed systems; its
background, icons and highlight are drawn by `distrokit.build.branding`. Files ending in `.in` and
`@TOKENS@` in paths are rendered from `distro.conf`.
