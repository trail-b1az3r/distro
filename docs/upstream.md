# Upstream components

Order of preference for everything the distribution needs:

1. Arch Linux packages
2. EndeavourOS packages
3. AUR packages — built into the distribution repository, pinned by commit
4. official upstream installers (npm, PyPI via uv) for per-user tools
5. custom code — only where nothing suitable exists

| Component | Source | How it is used | Modified? | Licence |
|---|---|---|---|---|
| Arch Linux | archlinux.org | base system, kernel, drivers, most software | no | various |
| EndeavourOS | endeavouros.com | repository, keyring, mirror list, `eos-rankmirrors`, `yay` | no | GPL |
| archiso | Arch Linux | builds the ISO; its `releng` profile is the base of `iso/` | no (profile files are overlaid: boot menus, live session, networking) | GPL-3.0 |
| dots (illogical-impulse / Halcyon) | [trail-b1az3r/dots](https://github.com/trail-b1az3r/dots), from end-4's dots-hyprland | the desktop configuration, pinned submodule; its `illogical-impulse-*` PKGBUILDs build the desktop's dependencies | **not modified.** Deploy-time changes to the user's copy only: the first-run greeting names the distribution, and the default wallpaper is the distribution's. The distribution layer is a separate file loaded after upstream's. | GPL-3.0 |
| Google Sans Flex | [end-4/google-sans-flex](https://github.com/end-4/google-sans-flex) | packaged (pinned commit + SHA-256) instead of being fetched into each home | no | OFL-1.1 |
| Hyprland, Quickshell | hyprland.org, quickshell.org | compositor and shell (via the dots' packages) | no | BSD-3 / LGPL-3.0 |
| HyperNix | [trail-b1az3r/HyperNix-pip](https://github.com/trail-b1az3r/HyperNix-pip) | PyPI package in a per-user uv environment | no | see upstream |
| Hermes Agent ("Hermis") | [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent) | `uv tool install hermes-agent` (instead of the upstream curl-pipe-bash installer) | no | MIT |
| OpenClaw | [openclaw/openclaw](https://github.com/openclaw/openclaw) | npm package into `~/.local` | no | MIT |
| Claude Code | Anthropic | official npm package, per user, never redistributed | no | Anthropic Commercial Terms |
| llama.cpp | [ggml-org/llama.cpp](https://github.com/ggml-org/llama.cpp) | model server (AUR builds in the distribution repository) | no | MIT |
| linux-surface | [linux-surface](https://github.com/linux-surface/linux-surface) | optional kernel from its own repository, key vendored and fingerprint-checked | no | GPL-2.0 |
| Lucide icons | lucide.dev | UI icons of the distribution's apps (`branding/icons/ui`) | recoloured at runtime | ISC |
| Models | Hugging Face repositories listed in `ai/models/catalog.toml` | downloaded on request, SHA-256 verified | no | per model (shown before download) |

**Forks:** none. The distribution's own code is `lib/distrokit`, the overlay
files and the artwork (original, generated procedurally from `distro.conf`;
nothing is copied from another distribution's artwork).

**Replaced defaults** (and why):

* releng's systemd-networkd/iwd → NetworkManager (what the installed system uses);
* releng's root autologin and SSH with an empty root password → a live user
  with sudo, no SSH;
* EndeavourOS's Calamares installer → the distribution's installer (profiles,
  GPU manager, AI setup, Surface kernel, offline/online package handling);
* Hermes Agent's `curl | bash` installer → `uv tool install` (pinned Python,
  reproducible, no shell-profile edits).
