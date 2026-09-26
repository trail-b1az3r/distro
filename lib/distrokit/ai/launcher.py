"""The unified AI launcher: one place to open HyperNix, the assistants,
Claude Code and local models, whatever is installed."""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from ..branding import Branding, load as load_branding
from . import models, runtime, tools

TERMINALS = (("konsole", ["-e"]), ("kitty", ["--"]), ("foot", []), ("alacritty", ["-e"]), ("xterm", ["-e"]))


@dataclass
class Entry:
    id: str
    name: str
    description: str
    installed: bool
    configured: bool
    kind: str  # assistant | toolkit | coding | model
    install_command: str
    homepage: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _expand(path: str, home: Path) -> Path:
    return Path(path.replace("~", str(home), 1)) if path.startswith("~") else Path(path)


def entries(home: Path | None = None, branding: Branding | None = None) -> list[Entry]:
    home = home or Path.home()
    branding = branding or load_branding()
    out = [
        Entry(
            "hypernix",
            "HyperNix",
            "Chat with local models, convert and quantise to GGUF, train and monitor runs.",
            tools.hypernix_installed(home, branding),
            True,
            "toolkit",
            f"{branding.cli} ai install hypernix",
            "https://github.com/trail-b1az3r/HyperNix-pip",
        )
    ]
    for tool_id in (*tools.ASSISTANTS, "claude-code"):
        spec = tools.load_spec(tool_id)
        marker = spec.launch.get("configured_marker", "")
        out.append(
            Entry(
                tool_id,
                spec.name,
                spec.description or ("Anthropic's agentic coding tool, in your terminal." if tool_id == "claude-code" else ""),
                tools.tool_installed(spec, home),
                (not marker) or _expand(marker, home).exists(),
                "coding" if tool_id == "claude-code" else "assistant",
                f"{branding.cli} ai install {tool_id}",
                spec.homepage,
            )
        )
    reg = models.Registry(branding.id, home)
    default = reg.default()
    out.append(
        Entry(
            "local-model",
            f"Local model: {default[1].get('name', default[0])}" if default else "Local model",
            f"Chat with your default model in the terminal, or serve it at {runtime.endpoint()} for other apps.",
            bool(default),
            bool(default),
            "model",
            f"{branding.cli} model install",
        )
    )
    return out


def terminal_command(cmd: list[str], hold: bool = False) -> list[str]:
    for name, flag in TERMINALS:
        if shutil.which(name):
            inner = cmd
            if hold:
                script = " ".join(_q(c) for c in cmd) + '; echo; read -rp "Press Enter to close… " _'
                inner = ["bash", "-c", script]
            return [name, *flag, *inner]
    raise RuntimeError("no terminal emulator found")


def _q(s: str) -> str:
    import shlex

    return shlex.quote(s)


def command_for(entry_id: str, action: str = "run", home: Path | None = None,
                branding: Branding | None = None) -> tuple[list[str], bool]:
    """(command, needs terminal) for launching an entry."""
    home = home or Path.home()
    branding = branding or load_branding()
    local_bin = home / ".local" / "bin"
    if entry_id == "hypernix":
        exe = str(local_bin / "hyped-pro") if (local_bin / "hyped-pro").exists() else str(local_bin / "hypernix")
        if action == "doctor":
            return [str(local_bin / "hypernix"), "doctor"], True
        if action == "devices":
            return [str(local_bin / "hypernix"), "devices"], True
        return [exe], True
    if entry_id == "local-model":
        default = models.Registry(branding.id, home).default()
        if not default:
            return [branding.cli, "model", "install"], True
        mid, entry = default
        if action == "serve":
            return ["systemctl", "--user", "start", runtime.service_name(branding)], False
        if entry.get("path") and (local_bin / "hypernix").exists():
            return [str(local_bin / "hypernix"), "chat", "--model-dir", entry["path"]], True
        if entry.get("hypernix_id") and (local_bin / "hypernix").exists():
            return [str(local_bin / "hypernix"), "chat", "--repo-id", entry["hypernix_id"]], True
        if entry.get("path") and shutil.which("llama-cli"):
            return ["llama-cli", "-m", entry["path"], "-cnv", "-ngl", "999"], True
        return [branding.cli, "ai", "status"], True
    spec = tools.load_spec(entry_id)
    marker = spec.launch.get("configured_marker", "")
    if action == "run" and marker and not _expand(marker, home).exists() and spec.launch.get("setup"):
        action = "setup"
    cmd = list(spec.launch.get(action) or spec.launch["run"])
    cmd[0] = str(local_bin / cmd[0]) if (local_bin / cmd[0]).exists() else cmd[0]
    return cmd, bool(spec.launch.get("terminal", True))


def launch(entry_id: str, action: str = "run") -> subprocess.Popen:
    """Start an entry detached from the caller. Missing tools open an
    installer terminal instead of failing."""
    branding = load_branding()
    home = Path.home()
    ent = next((e for e in entries(home, branding) if e.id == entry_id), None)
    if ent is None:
        raise KeyError(entry_id)
    env = os.environ.copy()
    env["PATH"] = f"{home / '.local' / 'bin'}:{env.get('PATH', '')}"
    ai_env = home / ".config" / branding.id / "ai.env"
    for line in ai_env.read_text().splitlines() if ai_env.exists() else []:
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            env[k] = v.strip("'\"")
    if not ent.installed:
        cmd = terminal_command([branding.cli, *ent.install_command.split()[1:]], hold=True)
    else:
        cmd, term = command_for(entry_id, action, home, branding)
        if term:
            cmd = terminal_command(cmd, hold=action in ("setup", "doctor", "devices"))
    return subprocess.Popen(cmd, env=env, start_new_session=True, stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
