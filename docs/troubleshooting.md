# Troubleshooting

Start with the doctor. It checks the kernel, boot loader, graphics, Vulkan,
network, audio, desktop, package manager, disk space, services, time and the
AI backend, and prints a fix for each problem:

```bash
nexora doctor              # -v for details, --report writes a support bundle (kept local)
sudo nexora repair         # repairs what the doctor found, after showing the plan
```

## Boot

| Symptom | Try |
|---|---|
| Writing the USB stick stops: "The last block was not fully written (-1 of 1,048,576 bytes)! Aborting." | That is KDE ISO Image Writer, not the image. Check the ISO's checksum and write it with `dd` or GNOME Disks ([installation](installation.md#1-write-the-iso-to-a-usb-stick)). |
| Black screen after the boot menu | Boot the **diagnostic** entry (text boot, no splash). If that works, it is graphics: see below. |
| "Please enter passphrase" does not appear | Press Esc to hide the splash; type the passphrase blind and Enter. |
| Boot menu missing after a firmware update | From the live ISO: `sudo nexora rescue` (reinstalls the boot loader). |
| Windows disappeared from the menu | systemd-boot: check the Windows boot manager is on the ESP. GRUB: `sudo nexora repair boot` (runs os-prober). |
| Kernel update and the system no longer boots | Choose another kernel (e.g. LTS) or the fallback initramfs entry in the boot menu, then `sudo nexora repair boot`. |

## Graphics

| Symptom | Try |
|---|---|
| No desktop after login, NVIDIA | `sudo nexora repair-gpu`, or `--safe` for nouveau |
| Hybrid laptop: external display dead | `nexora-gpu status`; the port may hang off the NVIDIA GPU, which needs its driver loaded |
| Screen tearing / flicker on NVIDIA | make sure `nexora-gpu status` shows the NVIDIA driver in use and `nvidia_drm.modeset=1` |
| Blurry XWayland apps on HiDPI | set the display scale in `~/.config/hypr/custom/general.lua` (XWayland apps render at 1x unless they support scaling) |
| Games: missing 32-bit drivers | multilib is on by default; `sudo nexora gpu configure` adds the `lib32-` drivers |

## Desktop

| Symptom | Try |
|---|---|
| Bar or widgets missing | `qs -c ii` in a terminal shows Quickshell's errors; `nexora reset-desktop` restores defaults (your files are backed up) |
| A keybind stopped working after editing | your files in `~/.config/hypr/custom/` load last; `hyprctl configerrors` shows mistakes |
| Wallpaper colours not applied | the shell's Python environment may still be setting up after an offline install: `nexora setup status` |

## Network, audio, Bluetooth

* Wi-Fi: `nmtui`, or the network menu in the bar. Broadcom cards need
  `broadcom-wl-dkms` (installed automatically when detected).
* Audio: `systemctl --user restart pipewire wireplumber`; `pavucontrol-qt` to
  pick the output.
* Bluetooth: `systemctl status bluetooth`; `bluetoothctl` for pairing from a
  terminal.

## Packages

| Symptom | Try |
|---|---|
| "unable to lock database" | `sudo nexora repair packages` removes a stale lock (only if no pacman is running) |
| signature / keyring errors | `sudo nexora repair packages` refreshes the keyrings first |
| "failed to synchronize … nexora" | the distribution repository could not be reached; retry later, or comment out `[nexora]` in `/etc/pacman.conf` temporarily |
| an AUR package fails to build | report it to the AUR package; the rest of the system is unaffected |

## AI

| Symptom | Try |
|---|---|
| an assistant is "not installed" after an offline install | `nexora setup resume` once online |
| OpenClaw needs a newer Node.js | the error names the package to install |
| the model server does not start | `journalctl --user -u nexora-llm`; is a model installed and set as default (`nexora model installed`)? |
| CUDA not used | `nexora ai backend`; on hybrid laptops run tools with `prime-run` |
| model too slow | pick a smaller model or a mixture-of-experts one; see `nexora model recommend` |

## Reporting a bug

Attach the output of `nexora doctor --report` (the bundle contains hardware
and configuration details but no personal files; review it first) and, for
installation problems, `/var/log/nexora/install.log`.
