# The `nexora` command

`nexora` (the name comes from `DISTRO_CLI` in `distro.conf`) is the
distribution's command-line tool. The code lives in
[`lib/distrokit/cli.py`](../lib/distrokit/cli.py); the package installs it as
`/usr/bin/nexora`, with `nexora-gpu` and `distro-gpu` as shortcuts for
`nexora gpu`. Bash and Fish completions and the man page (`man nexora`) are
generated from the same argument parser at package build time
([`build/completions.py`](../lib/distrokit/build/completions.py),
[`build/manpage.py`](../lib/distrokit/build/manpage.py)), so they always match.

Read-only commands never need root. Commands that change the system print a
plan, ask for confirmation (`-y` skips the question), and then re-run
themselves through `sudo`.

| Command | What it does |
|---|---|
| `nexora system` | Distribution, kernel, boot loader, desktop, profile, install date |
| `nexora hardware` | Detected hardware and the recommended configuration (`--json` for scripts) |
| `nexora gpu detect\|plan\|configure\|status` | The GPU manager (see [docs/gpu.md](../docs/gpu.md)) |
| `nexora surface status\|enable\|disable` | The linux-surface kernel on Microsoft Surface devices |
| `nexora update` | Packages (pacman), AUR (yay), Flatpak, desktop configuration, AI tools; `--check` lists only |
| `nexora install NAME…` | Features (`office`, `docker`, `podman`, `plasma`, `editor`, `dev`, `compilers`, `snapshots`, `firewall`), AI tools (`claude-code`, `hermis`, `openclaw`, `hypernix`) or any package |
| `nexora ai status\|install\|remove\|launch\|backend\|runtime\|update [TOOL]` | AI assistants, HyperNix, Claude Code, the local model server |
| `nexora model list\|recommend\|installed\|info\|install\|add\|remove\|default\|serve` | Local models (see [docs/models.md](../docs/models.md)) |
| `nexora doctor` | Diagnose problems; each finding comes with a fix |
| `nexora repair [auto\|packages\|boot\|all]` | Repair what the doctor found |
| `nexora repair-gpu [--safe]` | Re-detect GPUs and reinstall drivers (`--safe`: open-source drivers) |
| `nexora reset-desktop` | Restore the default desktop configuration; yours is backed up first |
| `nexora rescue` | From the live ISO: mount an installed system (unlocking it) and repair it |
| `nexora setup [status\|resume]` | Setup tasks that need the network (AI tools, models) after an offline install |
| `nexora installer [--config FILE] [--dry-run]` | Start the installer |
| `nexora iso build\|test\|info` | In a source checkout: build or test the ISO; on the live ISO: build info |
| `nexora welcome` | Open the Welcome wizard |

## Output examples

```
$ sudo nexora-gpu detect
GPU Detection
Vendor        NVIDIA
Model         GeForce GTX 1080 Mobile
Type          discrete
Architecture  pascal
VRAM          8 GB (estimated)
PCI           0000:01:00.0 [10de:1be0]
Driver now    nouveau

Plan (hybrid)
• Intel HD Graphics 630 [primary]: Intel graphics (Mesa, ANV Vulkan, iHD VA-API)
• NVIDIA GeForce GTX 1080 Mobile [offload]: NVIDIA 580 legacy driver (Maxwell, Pascal, Volta)
• Run a program on the NVIDIA GPU with: prime-run <program>
```

```
$ nexora doctor
System Doctor
✓ Kernel — linux 6.16.8
! GPU — Graphics driver not configured by the GPU manager
    fix: sudo nexora gpu configure
✓ Network — NetworkManager is running
...
```

Exit codes: 0 success, 1 failure (for `doctor`: a critical problem was
found), 2 invalid arguments or configuration, 130 interrupted.
