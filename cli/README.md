# The `frontline` command

`frontline` (the name comes from `DISTRO_CLI` in `distro.conf`) is the
distribution's command-line tool. The code lives in
[`lib/distrokit/cli.py`](../lib/distrokit/cli.py); the package installs it as
`/usr/bin/frontline`, with `frontline-gpu` and `distro-gpu` as shortcuts for
`frontline gpu`. Bash and Fish completions and the man page (`man frontline`) are
generated from the same argument parser at package build time
([`build/completions.py`](../lib/distrokit/build/completions.py),
[`build/manpage.py`](../lib/distrokit/build/manpage.py)), so they always match.

Read-only commands never need root. Commands that change the system print a
plan, ask for confirmation (`-y` skips the question), and then re-run
themselves through `sudo`.

| Command | What it does |
|---|---|
| `frontline system` | Distribution, kernel, boot loader, desktop, profile, install date |
| `frontline hardware` | Detected hardware and the recommended configuration (`--json` for scripts) |
| `frontline gpu detect\|plan\|configure\|status` | The GPU manager (see [docs/gpu.md](../docs/gpu.md)) |
| `frontline surface status\|enable\|disable` | The linux-surface kernel on Microsoft Surface devices |
| `frontline update` | Packages (pacman), AUR (yay), Flatpak, desktop configuration, AI tools; `--check` lists only |
| `frontline install NAME…` | Features (`office`, `docker`, `podman`, `plasma`, `editor`, `dev`, `compilers`, `snapshots`, `firewall`), AI tools (`claude-code`, `hermis`, `openclaw`, `hypernix`) or any package |
| `frontline ai status\|install\|remove\|launch\|backend\|runtime\|update [TOOL]` | AI assistants, HyperNix, Claude Code, the local model server |
| `frontline model list\|recommend\|installed\|info\|install\|add\|remove\|default\|serve` | Local models (see [docs/models.md](../docs/models.md)) |
| `frontline doctor` | Diagnose problems; each finding comes with a fix |
| `frontline repair [auto\|packages\|boot\|all]` | Repair what the doctor found |
| `frontline repo [status\|on\|off\|auto]` | The `[frontline]` package repository in `/etc/pacman.conf`: `off` while it is not published (pacman cannot sync with it on), `auto` to match whether it is |
| `frontline logs [status\|save\|on\|off\|send]` | Diagnostic logs: `save` keeps a bundle in `~/.local/state/frontline/logs`; sharing is off by default, `on` allows `send`, which files the logs in the repository set by `DISTRO_LOG_REPO` (with the GitHub CLI, or a pre-filled issue in the browser) |
| `frontline repair-gpu [--safe]` | Re-detect GPUs and reinstall drivers (`--safe`: open-source drivers) |
| `frontline reset-desktop` | Restore the default desktop configuration; yours is backed up first |
| `sudo logout` / `frontline logout [now\|+MIN\|HH:MM\|stop\|status]` | Log out graphical sessions like `shutdown`: in 1 minute by default (with a warning), `now`, later, or `stop` to cancel; SSH and text logins stay, `--all` for every user |
| `frontline rescue` | From the live ISO: mount an installed system (unlocking it) and repair it |
| `frontline setup [status\|resume]` | Setup tasks that need the network (AI tools, models) after an offline install |
| `frontline installer [--config FILE] [--dry-run]` | Start the installer |
| `frontline iso build\|test\|info` | In a source checkout: build or test the ISO; on the live ISO: build info |
| `frontline welcome` | Open the Welcome wizard |

## Output examples

```
$ sudo frontline-gpu detect
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
$ frontline doctor
System Doctor
✓ Kernel — linux 6.16.8
! GPU — Graphics driver not configured by the GPU manager
    fix: sudo frontline gpu configure
✓ Network — NetworkManager is running
...
```

Exit codes: 0 success, 1 failure (for `doctor`: a critical problem was
found), 2 invalid arguments or configuration, 130 interrupted.
