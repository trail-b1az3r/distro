# HyperNix

[HyperNix](https://github.com/trail-b1az3r/HyperNix-pip) is installed per user
into its own virtual environment,
`~/.local/share/nexora/hypernix/venv`, with its commands (`hypernix`, `hnx`,
`hyped-pro`, `hyped-plus`, `tvtop`, `waiter`, `multilama`, `hyprslug`) linked
into `~/.local/bin`.

## GPU backends

PyTorch is installed **first**, from the wheel index matching your hardware,
and HyperNix then reuses it (the procedure HyperNix's README gives). The
backend is chosen from the GPU manager's plan:

| Backend | When | PyTorch wheels |
|---|---|---|
| `cuda` | NVIDIA Turing and newer with the NVIDIA driver | CUDA 12.8 (`cu128`) |
| `cuda_legacy` | NVIDIA Maxwell/Pascal/Volta (580 driver) | CUDA 12.6 (`cu126`) |
| `rocm` | AMD GPUs supported by ROCm, with *GPU compute toolkits* | ROCm 6.4 |
| `xpu` | Intel Arc | Intel XPU |
| `vulkan` | other GPUs | CPU PyTorch; inference through llama.cpp's Vulkan backend |
| `cpu` | no usable GPU | CPU |

```bash
nexora ai backend                    # the detected backend and why
nexora ai install hypernix --backend cpu   # override
```

Nothing is hard-coded to one vendor: the index URLs and versions live in
[`ai/hypernix/hypernix.toml`](../ai/hypernix/hypernix.toml).

## Configuration

`~/.config/nexora/ai.env` holds the environment HyperNix and the assistants
see (loaded by Fish, Bash/Zsh login shells and Hyprland):

* `HYPERNIX_NO_PATH_SETUP=1`, `HYPERNIX_AUTO_INSTALL=0` — the distribution
  manages `PATH` and dependencies;
* backend variables such as `HSA_OVERRIDE_GFX_VERSION` for consumer AMD GPUs
  that ROCm supports under a sibling's ID.

Add your own variables at the end of the file.

## Models

HyperNix model names can be used directly in the model manager
(*Add model → HyperNix model*, or `nexora model add --hypernix qwen3-8b`);
catalogue entries that HyperNix knows carry their HyperNix id. See
[models.md](models.md).

## Updating and removing

```bash
nexora ai update          # HyperNix, Hermis, OpenClaw, Claude Code
nexora ai remove hypernix # deletes the virtual environment and the links
```
