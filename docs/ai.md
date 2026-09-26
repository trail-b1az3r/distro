# AI assistants, the AI launcher and Claude Code

Everything AI is **optional**, installed **per user** (in your home, without
root), and **never breaks the system**: if a tool fails to install, the rest
of the installation continues and the tool is retried after login. Nothing is
installed or downloaded without your choice.

## What you can choose

| | What it is | Installed with | Command |
|---|---|---|---|
| **Hermis** | [Hermes Agent](https://github.com/NousResearch/hermes-agent) by Nous Research (MIT): a self-improving agent that learns skills; works with local models or cloud providers | `uv tool install hermes-agent` (pinned Python, isolated) | `hermes` |
| **OpenClaw** | [OpenClaw](https://github.com/openclaw/openclaw) (MIT): a personal assistant with a local gateway, chat channels and a web dashboard | `npm install --prefix ~/.local openclaw` | `openclaw` |
| **HyperNix** | model toolkit with a GPU-matched PyTorch (see [hypernix.md](hypernix.md)) | uv virtual environment | `hypernix` |
| **Claude Code** | Anthropic's coding agent | official npm package into `~/.local` | `claude` |
| **Local model** | a GGUF model served by llama.cpp (see [models.md](models.md)) | download with size check and SHA-256 verification | `nexora model serve` |

In the installer: *AI* page → assistant **None / Hermis / OpenClaw / Both**,
HyperNix, Claude Code; *Model* page → a local model. The AI profile preselects
Hermis, HyperNix, Claude Code and GPU compute. Afterwards:

```bash
nexora install hermis            # or openclaw, hypernix, claude-code
nexora ai status                 # what is installed and configured
nexora ai remove openclaw
nexora ai update                 # update the per-user AI tools
```

## The AI launcher

**Ctrl + Super + A** (or *AI Assistant* in the app launcher) opens one window
for everything that is installed: start an assistant (the first start runs
its own setup: `hermes setup`, `openclaw onboard`), open Claude Code in a
terminal, open HyperNix, start or stop the local model server, and manage
models. Tools that are not installed show how to install them.

## Claude Code

`claude` works in every terminal immediately after installation:
`~/.local/bin` is on `PATH` for Fish, Bash/Zsh (`/etc/profile.d/nexora.sh`)
and the Hyprland session, so no shell configuration is needed. The first run
asks you to sign in. Claude Code's licence does not allow redistribution, so
it is downloaded from Anthropic's npm package at installation (or after the
first login when installing offline), never copied onto the ISO.

Node.js comes from the Arch repositories (`nodejs`, `npm`); if a tool needs a
newer Node.js than installed, the error says which package to install.

## Using local models with the assistants

The local model server speaks the OpenAI API at `http://127.0.0.1:8081/v1`
(only on this computer). Point Hermis, OpenClaw or any OpenAI-compatible tool
at it:

```bash
nexora model serve          # starts the user service with the default model
nexora model serve --status
```

Hermis and OpenClaw can equally use cloud providers; you choose during their
setup.

## Privacy

* The distribution sends no telemetry. The installer and tools contact only
  package mirrors, the Hugging Face model files you choose, PyPI/npm for the
  tools you choose, and GitHub for release checks you start.
* The local model server listens on 127.0.0.1 only.
* Assistants you configure with cloud providers send your prompts to those
  providers under their terms.

## Where things are

| Path | Content |
|---|---|
| `~/.local/bin/` | `hermes`, `openclaw`, `claude`, `hypernix` and friends |
| `~/.local/share/uv/tools/` | Hermis's environment |
| `~/.local/lib/node_modules/` | OpenClaw, Claude Code |
| `~/.local/share/nexora/hypernix/venv/` | HyperNix |
| `~/.local/share/nexora/models/` | downloaded models |
| `~/.config/nexora/models.json` | installed models and the default one |
| `~/.config/nexora/ai.env` | AI environment (backend variables), loaded by shells and Hyprland |
| `~/.local/state/nexora/setup-tasks.json` | pending/failed setup tasks (`nexora setup status`) |

Specifications of each tool (package, versions, commands, Node/Python
requirements) are data files in [`ai/`](../ai): update a version there, not in
code.
