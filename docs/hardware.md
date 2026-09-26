# Hardware

## What is detected

`nexora hardware` (and the installer's *Hardware* page) reads the kernel's
sysfs/procfs and udev; nothing is sent anywhere.

```
Hardware Detected
System            Micro-Star International Co., Ltd. GT73VR 7RF
Type              Laptop
CPU               Intel Core i7-7700HQ (4 cores / 8 threads)
GPU (integrated)  Intel HD Graphics 630
GPU (discrete)    NVIDIA GeForce GTX 1080 Mobile, 8 GB VRAM (estimated)
RAM               32 GB
Storage           1 TB NVMe SSD — Samsung SSD 980 PRO 1TB
Display           Built-in 1920 × 1080, 17.3"
Wi-Fi             Intel Wireless 8265 / 8275
Bluetooth         Intel Bluetooth wireless interface
Input             touchpad
Firmware          UEFI, Secure Boot off

Recommended Configuration
✓ Intel graphics (Mesa, ANV Vulkan, iHD VA-API)
✓ NVIDIA 580 legacy driver (Maxwell, Pascal, Volta)
✓ Wayland
✓ Hardware acceleration
✓ Hybrid graphics (PRIME render offload)
✓ CPU microcode (intel-ucode)
```

| Area | How |
|---|---|
| CPU | vendor, model, cores/threads, features (x86-64 level), microcode package |
| GPUs | PCI class 03xx devices; vendor, model from `pci.ids` (with the Arch `hwdata` database), architecture/generation from `hardware/detection/gpu-families.toml`, integrated vs discrete, the GPU driving the boot display, current driver, VRAM (reported by the driver, or estimated from `gpu-vram.tsv` and marked *estimated*) |
| Topology | single GPU, hybrid (integrated + discrete: PRIME offload), multi-GPU desktops |
| Memory | RAM and swap |
| Storage | disks, transport (NVMe, SATA, USB, virtio), SSD/HDD, partitions and free space, existing operating systems; the live USB stick is never offered as a target |
| Chassis | laptop / desktop / tablet / convertible (DMI chassis type, battery, lid) |
| Displays | connectors, EDID (name, size in mm, resolution), internal vs external, and a scale for HiDPI screens that Hyprland accepts exactly |
| Wi-Fi, Bluetooth, Ethernet | adapters and drivers, extra firmware where needed (e.g. Broadcom, Marvell) |
| Input | keyboards, touchpads, touchscreens, pens/styluses (udev properties, with a `/proc/bus/input` fallback) |
| Firmware | UEFI or BIOS, Secure Boot and Setup Mode |
| Virtualisation | QEMU/KVM, VirtualBox, VMware, Hyper-V (guest tools are installed accordingly) |

`nexora hardware --json` prints the full report; the installer saves it to
`/var/lib/nexora/hardware.json`.

## What the recommendations change

| Detected | Result |
|---|---|
| Intel / AMD CPU | `intel-ucode` / `amd-ucode`, loaded early from the initramfs |
| Any GPU | the matching driver stack (see [gpu.md](gpu.md)) |
| Hybrid graphics | PRIME render offload, `prime-run`, the integrated GPU drives the desktop |
| Laptop | power profiles, battery reporting; `thermald` on Intel laptops |
| HiDPI display | a per-display scale in `~/.config/hypr/custom/general.lua` |
| Touchscreen / pen | the shell's on-screen keyboard and touch gestures work out of the box (Surface: `iptsd`, see [surface.md](surface.md)) |
| Virtual machine | guest agents (`qemu-guest-agent`, `spice-vdagent`, `virtualbox-guest-utils`, `open-vm-tools`, Hyper-V daemons) |
| Microsoft Surface | the linux-surface kernel is recommended (not forced) |

Everything can be overridden in the installer, and later with
`nexora gpu configure --driver`, `nexora surface enable|disable`, and by editing
`~/.config/hypr/custom/`.

## External displays

Hyprland picks up displays when they are connected. Scales for displays found
during installation are written to `~/.config/hypr/custom/general.lua`; for
others, add a line such as:

```lua
hl.monitor({ output = "DP-2", mode = "preferred", position = "auto", scale = 1.5 })
```

`hyprctl monitors` lists connector names. On hybrid laptops, ports wired to
the discrete GPU work with the NVIDIA driver loaded (the GPU manager sets
`AQ_DRM_DEVICES` so the integrated GPU renders the desktop).

## Compatibility notes

* **NVIDIA Kepler and older** (GTX 600/700 series and earlier) have no NVIDIA
  driver with Wayland support; nouveau is used.
* **NVIDIA Maxwell, Pascal, Volta** (GTX 750–10 series, Titan V) use the 580
  legacy branch, built into the distribution repository.
* **Broadcom Wi-Fi** needing `broadcom-wl` is detected; the DKMS module is
  installed with kernel headers.
* **Apple Macs** with T2 chips need the linux-t2 kernel, which is not included.
* **ARM** devices are not supported (x86-64 only).
