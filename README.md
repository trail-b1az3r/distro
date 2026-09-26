# Nexora Linux

An EndeavourOS-based Arch Linux distribution with a polished Hyprland desktop,
real hardware detection, a GPU manager that gets NVIDIA/AMD/Intel and hybrid
laptops right, a graphical installer, and optional local AI (HyperNix, the
Hermis and OpenClaw assistants, Claude Code and local models).

The name, colours and every user-visible string come from
[`distro.conf`](distro.conf): rename the distribution by editing one file
(see [docs/customizing.md](docs/customizing.md)).

## What you get

| | |
|---|---|
| **Base** | Arch Linux + EndeavourOS repositories, `pacman` and `yay`, systemd, NetworkManager, PipeWire + WirePlumber, Bluetooth, Wayland and X11 (XWayland), Plymouth, zram |
| **Desktop** | Hyprland with the [illogical-impulse / Halcyon shell](https://github.com/trail-b1az3r/dots) (pinned), SDDM login theme, Dolphin, Konsole, Fish (bash stays available), Material You colours from the wallpaper |
| **Installer** | Graphical: UEFI and BIOS, erase / install alongside / manual partitioning, LUKS2 encryption, Btrfs (with snapshots) or ext4, swap (zram, partition, file, hibernation), separate `/home`, systemd-boot or GRUB, Secure Boot with your own keys (sbctl), profiles, GPU and AI choices. Also unattended from JSON. |
| **Hardware** | Detection of CPU, GPUs (integrated/discrete/hybrid), RAM, disks, laptop/tablet, Wi-Fi, Bluetooth, touchscreen/pen/touchpad and displays (EDID, HiDPI scale) — shown before installing, with recommendations you can override |
| **Graphics** | `sudo nexora-gpu detect \| configure \| status`: NVIDIA open/legacy/nouveau, AMD (+ROCm), Intel (incl. Arc), PRIME offload on hybrid laptops, early KMS, suspend support |
| **Surface** | Microsoft Surface detection with the optional [linux-surface](https://github.com/linux-surface/linux-surface) kernel — recommended, never forced |
| **AI (optional)** | HyperNix with a PyTorch build matching your GPU; Hermis (Hermes Agent) and/or OpenClaw; Claude Code (`claude` works immediately); a model catalogue with honest size/memory estimates; a local OpenAI-compatible model server (llama.cpp) |
| **Tools** | `nexora` CLI (system, hardware, gpu, update, install, ai, model, doctor, repair…), graphical Welcome wizard and updater, AI launcher and model manager |
| **Safety** | `nexora doctor`, `nexora repair`, `nexora reset-desktop`, `nexora repair-gpu`, rescue from the live ISO; every change is explained before it is made |

Profiles: **Minimal**, **Standard** (default), **Developer**, **AI** — each
feature can be switched individually in the installer.

## Quick start

**Use it:** download the ISO from the releases (or build it), write it to a USB
stick, boot it and follow the installer. → [docs/installation.md](docs/installation.md)

**Build the ISO:**

```bash
git clone --recursive https://github.com/trail-b1az3r/distro
cd distro
./build.sh --container                    # any Linux with Docker or Podman
# or, on Arch Linux / EndeavourOS:
sudo scripts/bootstrap.sh --builder && sudo ./build.sh --profile standard
```

Results: `dist/Nexora-YYYY.MM-x86_64.iso`, `checksums/`, `metadata/`.
→ [docs/iso-building.md](docs/iso-building.md)

**Develop:**

```bash
make test            # unit + GUI tests (no root, no Arch needed)
make lint            # ruff, shellcheck, PKGBUILD and completion checks
make installer-demo  # the installer on a simulated machine
make qemu-test       # install the newest ISO in QEMU/KVM and check it
```

## Documentation

Start with [docs/README.md](docs/README.md). Highlights:

* Users: [installation](docs/installation.md) · [desktop](docs/desktop.md) ·
  [hardware](docs/hardware.md) · [GPU](docs/gpu.md) · [Surface](docs/surface.md) ·
  [AI assistants](docs/ai.md) · [HyperNix](docs/hypernix.md) · [models](docs/models.md) ·
  [development](docs/development.md) · [packages and updates](docs/packages.md) ·
  [troubleshooting](docs/troubleshooting.md) · [recovery](docs/recovery.md)
* Builders and contributors: [ISO building](docs/iso-building.md) ·
  [customizing and rebranding](docs/customizing.md) · [architecture](docs/architecture.md) ·
  [testing](docs/testing.md) · [upstream components](docs/upstream.md) ·
  [release process](docs/release-process.md) · [contributing](CONTRIBUTING.md)

## Repository layout

```
distro.conf        name, IDs, colours, URLs: the single source of branding
build.sh           ISO build front end (see iso/build.env.example)
installer/         installer configuration schema and unattended-install examples
cli/               the `nexora` command reference (code: lib/distrokit/cli.py)
lib/distrokit/     the Python code: installer, hardware, gpu, ai, desktop, system, gui, build
iso/               archiso overlay: boot menus, live session, autoinstall, pinned build inputs
packages/          package lists, PKGBUILD templates, repository manifest, AUR lock
hardware/          detection tables (GPU families, VRAM), GPU driver stacks, Surface data
desktop/           dots submodule (upstream desktop) + overlay (distribution layer)
ai/                HyperNix, Hermis, OpenClaw, Claude Code specs; model catalogue; model server
branding/          logo and icon sources, boot/login/terminal themes (artwork is generated)
profiles/          Minimal / Standard / Developer / AI and the feature switches
scripts/           bootstrap, package builds, checks, repository publishing
tests/             unit, GUI, loop-device integration and QEMU install tests
docs/              user and developer documentation
```

## Principles

* Arch and EndeavourOS packages first, then the AUR (prebuilt into the
  distribution repository), then official upstream installers — custom code
  only where nothing exists. See [docs/upstream.md](docs/upstream.md).
* No telemetry, no background services you did not ask for, nothing that
  needs root runs without telling you what it will do.
* The desktop configuration is upstream's, pinned and deployed unchanged, plus
  a small distribution layer; your `~/.config/hypr/custom/` is never touched.

Licence: GPL-3.0-or-later ([LICENSE](LICENSE)). Components keep their own
licences (see [docs/upstream.md](docs/upstream.md)).
