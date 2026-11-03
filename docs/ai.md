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

## AI autocorrect

Select text in a graphical application and press **Ctrl + Super + Shift + C**.
Nexora sends the selection to the configured local model server and replaces
it with the corrected text. This works in Firefox, Nexora Write and other
Wayland applications that support normal clipboard copy/paste.

The feature uses only the selected text; it does not record keystrokes or run
as a background keyboard hook. It refuses to operate in terminal windows and
outside a Wayland desktop session, including TTYs. Install and select a local
GGUF model first, the shortcut starts the user model service automatically when a default
model is configured. Required Wayland clipboard/typing tools are installed with
the desktop profile.

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

Nexora supports three selectable inference runners: `t1` delegates to
HyperNix T1's built-in runner; `ggml-hnx` uses HyperNix's patched llama.cpp
through `hnx runtime serve`; `legacy` uses the standard upstream
`llama-server`. Select one with `nexora model backend t1|ggml-hnx|legacy`.
The selection is stored per-user in `~/.config/nexora/ai-runtime.toml`.
T1 must already be installed and its local API running.

The local OpenAI-compatible endpoint for the standalone runners is
`http://127.0.0.1:8081/v1`. Point Hermis, OpenClaw or any compatible tool
at the endpoint reported by `nexora model serve --status`:

```bash
nexora model serve             # starts the selected runner with the default model
nexora model serve --status
nexora model backend           # show selected runner
nexora model backend t1        # HyperNix T1 built-in runner
nexora model backend ggml-hnx  # HyperNix patched llama.cpp
nexora model backend legacy    # upstream llama.cpp
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
