# Building the ISO

## Quick start

```bash
git clone --recursive https://github.com/trail-b1az3r/distro && cd distro

# Anywhere with Docker or Podman (recommended; nothing touches your system):
./build.sh --container

# On Arch Linux or EndeavourOS:
sudo scripts/bootstrap.sh --builder     # once: archiso, tools, EndeavourOS keyring
sudo ./build.sh --profile standard
```

Output:

```
dist/Nexora-2026.09-x86_64.iso
checksums/Nexora-2026.09-x86_64.iso.sha256
checksums/Nexora-2026.09-x86_64.iso.b2sum
metadata/Nexora-2026.09-x86_64.json            build information (versions, commits, sizes)
metadata/Nexora-2026.09-x86_64.packages.txt    every package in the live system
metadata/Nexora-2026.09-x86_64.offline-repo.txt packages carried for installation
metadata/Nexora-2026.09-x86_64.aur.lock.json   the AUR commits used
```

Requirements: x86-64, about 30 GB free (60 GB with `--offline full`), 8 GB
RAM, internet access. A full build from scratch takes one to three hours,
mostly compiling AUR packages; later builds reuse `build/repo`.

## Options

| Option | Meaning |
|---|---|
| `--profile minimal\|standard\|developer\|ai` | the profile the installer preselects (and, with `--offline full`, carries) |
| `--offline minimal` (default) | the ISO carries the distribution repository (our packages + AUR builds); everything else is downloaded while installing |
| `--offline full` | the ISO carries every package any installation needs (all GPU stacks, kernels, the profile's software): installs without a network; about twice the size |
| `--clean` | start from clean work directories |
| `--debug` | fast zstd compression, keep `build/iso-work`, print every command |
| `--container` | run everything in `archlinux:base-devel` with Docker or Podman |
| `--skip-packages` | reuse `build/repo` as is |
| `--archive-date YYYY/MM/DD` | install Arch packages from that day's Arch Linux Archive snapshot |
| `--config FILE` | settings from a file ([example](../iso/build.env.example)) |
| `--dry-run` | print the build commands without running them (works on any Linux) |

## What happens

1. **Artwork** (`distrokit.build.branding`): logo, icons, wallpapers, the
   Plymouth splash, GRUB and SDDM themes and the syslinux splash, all generated
   from `distro.conf` (Pillow/NumPy/librsvg).
2. **Distribution repository** (`distrokit.build.packages`, `build/repo`):
   * the distribution's PKGBUILDs are rendered from `packages/pkgbuild/*.in`
     with a reproducible source tarball of this repository;
   * the dots' `illogical-impulse-*` meta packages are taken as they are;
   * every package named in `packages/lists/*.list`, the GPU stacks and the
     llama.cpp builds is resolved: local PKGBUILD first, then the
     Arch/EndeavourOS repositories, then the AUR, recursively, and built in
     dependency order with `makepkg` as an unprivileged user.
   AUR packages are pinned to git commits in `packages/aur.lock.json`. The
   first build writes it; commit it. `scripts/build-packages.sh --update-lock`
   refreshes the pins (review the diff: it is code you will run as root).
   Packages are built in a build chroot (`build/packages/chroot`, made with
   `pacstrap`): each build installs its dependencies there and removes them
   afterwards, so the host's packages and pacman databases are never touched
   and nothing asks for a password halfway. Source signatures are checked
   against the build's own keyring in `build/packages/gnupg`.
   Pinned commits are fetched from the AUR, or from Arch Linux's GitHub mirror
   of it (`AUR_GIT_MIRROR`, the same commits) when the AUR's git service fails;
   a commit fetched once is reused from `build/packages/aur` without the network.
3. **Offline repository** (`build/offline-repo`): see `--offline`.
4. **archiso profile** (`build/iso-profile`): archiso's `releng` profile with
   `iso/` laid over it — branded boot menus, the live session, NetworkManager
   instead of systemd-networkd, no root autologin or SSH, the package list
   (`base`, `desktop`, `browser`, `live` lists), pacman configurations, build
   information.
5. **mkarchiso**, then the ISO, checksums and metadata are moved into place.

Build the repository alone with `scripts/build-packages.sh` (`--plan` shows
the order without building).

## Reproducibility

* `SOURCE_DATE_EPOCH` defaults to the commit time, and the source tarball,
  PKGBUILDs and archiso timestamps follow it.
* `--archive-date` pins Arch Linux packages (EndeavourOS's small repository
  is not archived; its keyring and mirror list are pinned by commit and SHA-256
  in `iso/sources.conf`).
* AUR packages are pinned in `packages/aur.lock.json`, the desktop by the
  `desktop/dots` submodule commit, the fonts by commit and checksum.
* For bit-for-bit rebuilds also pin the container image by digest
  (`BUILD_IMAGE` in `iso/sources.conf`).

## Signing

With `GPGKEY` set (or `--sign KEY`), packages, the repository database and the
ISO checksums are signed. Put the public key's ID in `DISTRO_REPO_KEY_ID` so
installed systems require signatures. See [release-process.md](release-process.md).

## Testing the ISO

```bash
tests/qemu/run.sh              # every scenario, newest ISO in dist/
tests/qemu/run.sh --scenario uefi-btrfs-encrypted --keep
```

See [testing.md](testing.md). To look around manually:

```bash
qemu-system-x86_64 -enable-kvm -m 4G -smp 2 -cdrom dist/*.iso \
  -drive if=pflash,format=raw,readonly=on,file=/usr/share/edk2/x64/OVMF_CODE.4m.fd \
  -drive file=disk.qcow2,if=virtio -vga virtio
```

## Troubleshooting builds

| Problem | Fix |
|---|---|
| `the host is not Arch-based` | use `--container` |
| a build dependency cannot be installed in the chroot | the repositories changed under a pinned package; `--clean` recreates the chroot, `scripts/build-packages.sh --update-lock` refreshes the pins |
| `could not fetch PGP key …` | the keyservers were unreachable; build again later. The key verifies a package's upstream sources |
| `permission denied while trying to connect to the docker API` | `build.sh` runs Docker through `sudo` when your user cannot reach its socket; to avoid the password prompt, join the `docker` group (`sudo usermod -aG docker $USER`, then log in again) or use rootless Podman. On Arch or EndeavourOS you do not need `--container` at all |
| Docker: `failed to set up container networking … operation not supported` | the kernel was updated and the running kernel's modules are gone: reboot. Container builds use the host's network, so this only affects older checkouts |
| `Not found anywhere: X` | a package in `packages/lists` does not exist (renamed or removed upstream): fix the list |
| an AUR package fails to build | pin an older commit in `aur.lock.json` or remove it from the lists; see `build/packages/src/<pkg>` |
| `could not fetch the AUR package X` | both the AUR and its mirror failed; the message shows git's error for each. Check the network and [status.archlinux.org](https://status.archlinux.org), then build again. "Commit … is gone": run `scripts/build-packages.sh --update-lock` |
| `No space left on device` | free space or point `--build-dir` elsewhere; `--clean` removes old work directories |
| mkarchiso: `must be run as root` | `sudo ./build.sh`, or `--container` |
