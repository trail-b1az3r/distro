# Installation

## What you need

* A 64-bit PC (x86-64-v1 or newer), UEFI or legacy BIOS.
* 4 GB RAM (8 GB or more recommended; 16 GB+ for local AI models).
* 30 GB of disk for Minimal, 40–60 GB for Standard/Developer, 80 GB+ for the AI
  profile with models.
* A USB stick of 8 GB or more.
* An internet connection is recommended. Whether one is required depends on
  the ISO: a standard ISO carries the distribution's own packages and
  downloads the rest while installing; an ISO built with `--offline full`
  installs with no network at all. The installer tells you which one you have.

## 1. Write the ISO to a USB stick

Check the download first (the release page lists the SHA-256 sum; files over
2 GiB are split: `cat Nexora-*.iso.part-* > Nexora.iso`):

```bash
sha256sum -c Nexora-2026.09-x86_64.iso.sha256
```

Then write it. **This erases the USB stick.**

* Linux: `sudo dd if=Nexora-2026.09-x86_64.iso of=/dev/sdX bs=4M status=progress oflag=sync`
  (find `/dev/sdX` with `lsblk`; use the whole device, not a partition), or
  GNOME Disks ("Restore Disk Image"). Avoid KDE ISO Image Writer: some of its
  versions stop with "The last block was not fully written (-1 of 1,048,576
  bytes)! Aborting." on images that other writers write without trouble.
* Windows / macOS: [Rufus](https://rufus.ie) (DD mode) or [balenaEtcher](https://etcher.balena.io).
* [Ventoy](https://www.ventoy.net) works too: copy the ISO onto the Ventoy stick.

## 2. Boot it

Choose the USB stick in your firmware's boot menu (often F12, F11, F8, Esc or
Option on Macs). The boot menu offers:

| Entry | Use it when |
|---|---|
| **live** | Normal start. |
| **safe graphics** | The screen stays black or the desktop does not start (uses the firmware's display driver; the installer then runs on its own in a simple session). |
| **copied to RAM** | You want to remove the USB stick after starting (needs 8 GB RAM or more). |
| **Memory test** | You suspect faulty RAM. |

**Secure Boot:** the ISO's boot loader is not signed by Microsoft. Turn Secure
Boot off in the firmware to start the ISO. The installer can set up Secure
Boot with your own keys afterwards (see below).

The live desktop starts and opens the installer. Log out to get a text login:
user `liveuser`, no password (it has `sudo`).

## 3. The installer

Every page can be revisited until you press **Install**; nothing is written
to disk before that.

1. **Welcome / Language / Keyboard** — language, time zone (no location lookup
   is done; pick your region), keyboard layout and variant with a test field.
2. **Internet** — connect with *Network settings* if needed. *Install without
   the internet* uses only the ISO's packages (only on complete ISOs).
3. **Hardware** — what was detected (CPU, GPUs, RAM, disks, display, Wi-Fi,
   Bluetooth, input devices, firmware) and the recommended configuration. You
   can override recommendations on later pages.
4. **Disk** — see [Partitioning](#partitioning).
5. **Profile** — Minimal, Standard, Developer or AI, then individual features
   (applications, browser, office, Plasma fallback session, developer tools,
   editor, containers, Claude Code, HyperNix, assistant, GPU compute
   toolkits, snapshots, firewall).
6. **Desktop** — what the Hyprland desktop looks like and how to use it.
7. **Graphics** — the driver chosen for each GPU, with alternatives (for
   example the open-source driver instead of NVIDIA's).
8. **Kernel** — `linux` (default), `linux-lts`, `linux-zen`; on Microsoft
   Surface devices the linux-surface kernel is offered (see [surface.md](surface.md)).
9. **AI** — assistant (None, Hermis, OpenClaw or both), HyperNix, Claude Code.
10. **Model** — a local model to download now or after the first login (sizes
    and memory needs are shown; nothing large is downloaded silently). See
    [models.md](models.md).
11. **User** — name, user name, password, computer name, shell (Fish or bash),
    optional root password (without one, root login is disabled and `sudo` is
    used), automatic login.
12. **Summary** — everything that will happen, with every destructive disk
    change spelled out (ERASE / FORMAT lines). You confirm by typing or
    selecting the disk.
13. **Install** — progress and a live log. The log is kept at
    `/var/log/nexora/install.log` on the new system.

## Partitioning

| Mode | What happens |
|---|---|
| **Erase disk** | The whole disk is wiped. UEFI: 1 GiB EFI partition + root (+ swap partition, + `/home` if chosen). BIOS: 1 MiB BIOS boot partition + root. |
| **Install alongside** | Uses the largest free (unpartitioned) space; existing partitions are not touched. Shrink Windows first from Windows (Disk Management). On failure, the partitions the installer created are removed again. If the existing EFI partition is smaller than 1 GiB, an extra 1 GiB boot partition (XBOOTLDR) holds the kernels. |
| **Manual** | Choose existing partitions for `/`, `/boot` (EFI), `/home` and swap, and whether to format each. |

Options:

* **File system:** Btrfs (default: subvolumes `@`, `@home`, `@log`, `@pkg`,
  zstd compression, snapshots with Snapper, rollbacks from the boot menu with
  GRUB) or ext4.
* **Encryption:** LUKS2 for root (and `/home`, swap). The passphrase is asked
  in the boot splash. Keep it safe: it cannot be recovered.
* **Swap:** zram (compressed RAM, default), a swap partition or a swap file;
  *hibernation* reserves swap the size of your RAM and configures resume.
* **Separate /home:** keeps your files on their own partition.
* **Boot loader:** automatic (systemd-boot on UEFI, GRUB on BIOS) or GRUB on
  UEFI. Both get a *diagnostic* entry (text boot, no splash) for troubleshooting.
* **Secure Boot (sbctl):** with systemd-boot, creates your own signing keys,
  signs the boot loader and kernels, and enrols the keys (keeping Microsoft's
  so firmware option ROMs keep working) if the firmware is in *Setup Mode*.
  Otherwise the keys are created and you enrol them later with
  `sudo sbctl enroll-keys --microsoft` after putting the firmware in Setup Mode.

### Dual boot with Windows

1. In Windows, shrink the C: partition (Disk Management) to leave at least
   40 GB unallocated. Turn off *Fast Startup* (Control Panel → Power Options),
   and suspend BitLocker if you use it.
2. Install with **Install alongside**. systemd-boot finds Windows
   automatically; GRUB lists it through os-prober.

## After installation

On first login the **Welcome** wizard opens: updates, driver status, AI setup
and model download, appearance, apps, privacy, backups. Anything that needed
the internet and could not run during installation (AI tools, models, the
desktop's Python environment) is resumed automatically once you are online
(`nexora setup status` shows what is pending).

## Unattended installation

The installer runs from a JSON file with the same settings as the graphical
installer ([installer/schema.json](../installer/schema.json),
examples in [installer/examples](../installer/examples)):

```bash
sudo nexora-installer --config install.json --dry-run      # show the plan and every command
INSTALL_USER_PASSWORD=... INSTALL_DISK_PASSPHRASE=... \
  sudo -E nexora-installer --config install.json --yes-i-understand
```

Passwords can stay out of the file (`INSTALL_USER_PASSWORD`,
`INSTALL_ROOT_PASSWORD`, `INSTALL_DISK_PASSPHRASE`). Without
`--yes-i-understand` the installer asks you to type the disk name before it
erases anything.

To install many machines, boot the ISO with an extra kernel parameter (press
`e` in the UEFI menu or Tab in the BIOS menu):

* `nexora.autoinstall=label:MYSTICK:install.json` reads the file from a USB
  stick whose file system is labelled `MYSTICK`;
* `nexora.autoinstall=fw_cfg` reads it from QEMU's fw_cfg (used by the tests);
* add `nexora.autoinstall.poweroff=1` to power off afterwards.

This **erases disks without asking**; never put it on a boot entry by accident.
