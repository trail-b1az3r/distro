# Architecture

## Components

```
                       distro.conf  (names, IDs, colours, repository)
                            │
        ┌───────────────────┼─────────────────────────────────────────┐
        │                   │                                         │
  lib/distrokit        data files                               build pipeline
  (Python, stdlib;     profiles/  packages/lists  hardware/     build.sh → distrokit.build.{branding,
   GUIs need PySide6)  ai/  desktop/  branding/  iso/            packages, iso} → mkarchiso → dist/
        │
        ├── hardware/      sysfs/procfs/udev → HardwareReport (CPU, GPUs, topology, displays, disks, input…)
        ├── gpu/           plan (stack per GPU, hybrid, env, modules) → apply (files + packages) → status
        ├── surface.py     Surface detection, [frontline-surface] repository (built from the linux-surface fork) and kernel
        ├── boot.py        kernel command line fragments, systemd-boot entries, GRUB, boot.conf
        ├── installer/     config (+schema) → disks (partition plans) → steps (Installation) → engine
        ├── ai/            backends (GPU → PyTorch/llama.cpp), tools (uv/npm per user), models, runtime, launcher
        ├── tasks.py       per-user setup queue (tools, models) resumed after offline installs
        ├── desktop/       deploy: dots + distribution layer into a home, with manifest, backups, reset
        ├── system/        doctor, repair, update, info
        ├── cli.py         the `frontline` command
        ├── privileged.py  pkexec helper with an allowlist, for the GUIs
        ├── hooks.py       pacman hooks (boot entries, os-release)
        ├── gui/           PySide6/QML: installer, welcome, updater, AI launcher (+ DistroUi components)
        └── build/         branding, stage (package layout), packages (resolver/builder), iso, completions, manpage
```

## Principles

* **One source of truth per concern.** Names in `distro.conf`, package sets in
  `packages/lists`, driver knowledge in `hardware/gpu/drivers.toml`, AI tool
  specs in `ai/*.toml`. Code reads data; changing a version or a package
  name never needs code changes.
* **Same code everywhere.** The installer, `frontline gpu configure`, `repair`,
  and the pacman hooks call the same functions. Everything that touches a
  system takes a `root` (the installer passes `/mnt/frontline`), and every command
  goes through a `Runner`, which can record instead of run (dry runs, the
  installer's summary, the tests).
* **Detect from the kernel, not from guesses.** Hardware detection reads sysfs
  and udev with a configurable root, which is how the tests run against fake
  machines (`tests/hwfixtures.py`).
* **Explain, then act.** Destructive or privileged actions are described in
  plain words first (installer summary, repair plans, `gpu configure`), and
  the GUIs reach root only through the allowlisted helper via polkit.

## Installed layout

| Path | Package | Content |
|---|---|---|
| `/usr/lib/frontline/distrokit/` | frontline-core | the Python package |
| `/usr/share/frontline/` | core, branding, desktop | data: `distro.conf`, profiles, lists, hardware, ai, icons, dots, overlay, artwork |
| `/usr/bin/frontline`, `frontline-gpu`, `distro-gpu` | core | CLI (isolated-mode Python launchers) |
| `/usr/lib/frontline/bin/` | core, desktop | privileged helper, hook helpers, session start |
| `/usr/share/libalpm/hooks/9?-frontline-*.hook` | core | pacman hooks |
| `/usr/share/polkit-1/actions/org.frontline.privileged.policy` | core | polkit |
| `/usr/lib/systemd/user/frontline-llm.service` | core | local model server |
| `/usr/share/{plymouth,grub,sddm}/themes/frontline/` | branding | boot and login themes |
| `/etc/frontline/` | installer, GPU manager | `boot.conf`, `cmdline.d/`, `gpu.env`, `firstboot.json` |
| `/var/lib/frontline/` | installer | `install.json`, `hardware.json`, `gpu.json` |

The layout is defined once in [`lib/distrokit/build/stage.py`](../lib/distrokit/build/stage.py)
and tested.

## The installation, step by step

`Installation.steps()` (in `installer/steps.py`): preflight → mirrors →
partition → format (LUKS) → mount (Btrfs subvolumes, swap) → pacstrap (from
the ISO's offline repository and/or mirrors; missing AUR packages are built
later) → fstab → system configuration (locale, time, keyboard, hostname,
pacman.conf, mkinitcpio with systemd + sd-encrypt + plymouth, sudo, zram,
kernel parameters, SDDM) → user → graphics drivers → Surface kernel →
boot loader (+ Secure Boot) → initramfs and boot entries → desktop deploy →
services → snapshots → remaining AUR packages → per-user AI tools and models
→ install record. Failures in non-critical steps (mirrors, Surface, AUR, AI)
become warnings; a failure after creating partitions in free space removes
them again.

The GUI never runs as root: it sends the configuration to
`frontline-installer --engine` (through sudo on the live ISO, pkexec elsewhere),
which streams JSON events back.
