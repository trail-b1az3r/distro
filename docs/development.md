# Development environment

Every profile has **Git, Fish, yay, OpenSSH, curl, wget, jq, zip/unzip,
p7zip, tar, rsync, htop/btop** and `base-devel` (GCC, make, binutils,
fakeroot, …).

| Feature (installer / `nexora install`) | Packages |
|---|---|
| Developer utilities (`dev`, Standard and up) | Python, pip, uv, Node.js, npm, GitHub CLI, git-lfs, ripgrep, fd, bat, eza, fzf, zoxide, tmux, direnv, starship |
| Compilers and debuggers (`compilers`, Developer and up) | GCC, Clang/LLVM, lld, LLDB, GDB, Valgrind, strace, ltrace, perf, make, CMake, Meson, Ninja, Autotools, pkgconf, Rust (rustup-free `rust`), pipx, virtualenv, ShellCheck, kernel headers |
| Code editor (`editor`) | `CODE_EDITOR` from `distro.conf`: Code - OSS (default), VSCodium, or Microsoft's Visual Studio Code |
| Containers (`podman` or `docker`) | Podman + podman-compose (rootless, sub-UIDs configured), or Docker + compose + buildx (your user joins the `docker` group) |
| Claude Code (`claude-code`) | see [ai.md](ai.md#claude-code) |

```bash
nexora install compilers editor podman
```

## Editors and licences

`packages/editors.toml` records whether each editor may be put on the ISO.
Code - OSS and VSCodium are open source and come from the distribution's
repositories (offline-capable). Microsoft's Visual Studio Code does not allow
redistribution: choosing it (`CODE_EDITOR="visual-studio-code-bin"`) installs
it from the AUR with yay during or after installation, never from the ISO.

## Fish

Terminals open Fish with the dots' configuration and the distribution's
defaults (`/usr/share/fish/vendor_conf.d/nexora.fish`):

* abbreviations: `up` (update), `doctor`, `gpu`, `hw`, `pacs`/`pacr` (search/remove), `g`/`gs`/`gc`…
* `ls`/`ll`/`la`/`lt` through eza when installed,
* `sysinfo` (fastfetch with the distribution's logo),
* zoxide (`z`), fzf key bindings, direnv hooks.

Your own settings go in `~/.config/fish/config.fish` or `~/.config/fish/conf.d/`.
Bash is still there (`bash`, and the login shell unless you chose Fish);
scripts with `#!/bin/bash` or `#!/bin/sh` are unaffected.

## Python and Node.js

Use per-project environments: `uv venv` / `uv pip`, `pipx` for CLI tools,
`npm install --prefix ~/.local -g …` for global Node tools (`~/.local/bin` is
on `PATH`). Avoid `sudo pip install`: it breaks pacman-managed Python.
