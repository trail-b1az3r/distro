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
policy, completions, man page and every string in the apps follow. The logo
itself is `branding/logo/logo-mark.svg.in` (an SVG template using the
`@BRAND_*@` colours); replace it with your own mark. `make test` checks that a
renamed configuration renders everywhere (`test_branding_rename`).

`distro.conf` is validated: IDs must be lowercase `[a-z0-9-]`, colours
`#RRGGBB`, the ISO label `A-Z0-9_`.

## Profiles and features

* [`profiles/*.toml`](../profiles): Minimal, Standard (default), Developer, AI.
  A profile inherits another, lists package lists and sets feature values.
* [`profiles/features.toml`](../profiles/features.toml): the switches the
  installer shows (label, description, group, the package lists each value
  adds). Add a feature there and it appears in the installer and in
  `nexora install`.

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

`iso/`: `profiledef.sh.in`, `efiboot/` (systemd-boot), `syslinux/` (BIOS),
`airootfs/` (files added to the live system). Files ending in `.in` and
`@TOKENS@` in paths are rendered from `distro.conf`.
