# The GPU manager

```bash
sudo frontline-gpu detect      # what is there and what would be installed
sudo frontline-gpu configure   # install and configure it (asks first)
frontline-gpu status           # what is running now
```

(`frontline gpu …` and `distro-gpu …` are the same command.) The installer uses
the same code, so an installed system and a later `configure` agree.

## Driver stacks

Defined in [`hardware/gpu/drivers.toml`](../hardware/gpu/drivers.toml) and
chosen per GPU from its vendor and architecture
([`hardware/detection/gpu-families.toml`](../hardware/detection/gpu-families.toml)):

| Stack | GPUs | Notes |
|---|---|---|
| `nvidia-open` | Turing (GTX 16xx, RTX 20xx) and newer | NVIDIA's open kernel modules; prebuilt `nvidia-open` for the `linux` kernel, `nvidia-open-dkms` for other kernels; CUDA; early KMS; suspend/resume services |
| `nvidia-580xx` | Maxwell, Pascal, Volta | the last branch supporting them, from the distribution repository (built from the AUR); CUDA 12.x runtimes |
| `nouveau` | Kepler and older, or on request | open source, NVK Vulkan; fallback for any NVIDIA GPU |
| `amdgpu` | GCN 1.2 and newer (RX 400+, all RDNA, APUs) | Mesa RADV Vulkan, VA-API; ROCm with *GPU compute toolkits* on supported cards (with `HSA_OVERRIDE_GFX_VERSION` where needed) |
| `radeon` | older AMD/ATI | Mesa |
| `intel` / `intel-discrete` / `intel-legacy` | Gen 9+ / Arc / older | ANV Vulkan, iHD or i965 VA-API, oneAPI for Arc |
| `virtual` | QEMU, VirtualBox, VMware | virtio/llvmpipe |

## Hybrid laptops

On Intel + NVIDIA or AMD + NVIDIA laptops the integrated GPU drives the
screen and the NVIDIA GPU sleeps until a program asks for it:

```bash
prime-run blender          # run one program on the NVIDIA GPU
```

`configure` writes:

* `/etc/modprobe.d/frontline-gpu.conf` — driver options (e.g. NVIDIA dynamic
  power management on Turing+, video memory preservation for suspend),
* `/etc/mkinitcpio.conf.d/20-frontline-gpu.conf` — early KMS modules,
* `/etc/udev/rules.d/80-frontline-gpu.rules` — stable `/dev/dri/frontline-primary-card`
  and `frontline-offload-card` names (card numbers change between boots),
* `/etc/frontline/gpu.env` — the Hyprland environment (`AQ_DRM_DEVICES`,
  `LIBVA_DRIVER_NAME`, …),
* kernel parameters (e.g. `nvidia_drm.modeset=1`) in `/etc/frontline/cmdline.d/`,
  then regenerates the initramfs and boot entries.

## Overrides

```bash
sudo frontline-gpu configure --driver 0000:01:00.0=nouveau   # use nouveau for this GPU
sudo frontline-gpu configure --recommended                   # forget overrides
sudo frontline-gpu configure --compute                       # add CUDA / ROCm toolkits
```

The PCI address comes from `detect`. Overrides are remembered, so updates and
`repair-gpu` keep your choice.

## When graphics break

* Boot the **diagnostic** entry of the boot menu (text mode, no splash).
* `sudo frontline repair-gpu` re-detects and reinstalls the recommended drivers;
  `sudo frontline repair-gpu --safe` switches every NVIDIA GPU to nouveau.
* From the live ISO: `sudo frontline rescue` mounts the installed system and
  repairs it from outside.

See also [troubleshooting.md](troubleshooting.md#graphics).
