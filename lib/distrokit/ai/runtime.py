"""The local model server (llama.cpp's llama-server) as an on-demand
systemd user service."""

from __future__ import annotations

import os
import shutil
import tomllib
import urllib.request
from pathlib import Path
from typing import Any

from .. import paths, util
from ..branding import Branding, load as load_branding
from .models import Registry


def config() -> dict[str, Any]:
    with paths.data("ai", "runtime", "llama-server.toml").open("rb") as fh:
        return tomllib.load(fh)


def service_name(branding: Branding) -> str:
    return f"{branding.id}-llm.service"


def unit_text(branding: Branding) -> str:
    """Installed system-wide to /usr/lib/systemd/user; not enabled by default."""
    return (
        "[Unit]\n"
        f"Description={branding.name} local model server (llama.cpp)\n"
        "Documentation=https://github.com/ggml-org/llama.cpp/tree/master/tools/server\n\n"
        "[Service]\n"
        f"ExecStart=/usr/bin/{branding.cli} model serve --foreground\n"
        "Restart=on-failure\n"
        "RestartSec=5\n\n"
        "[Install]\n"
        "WantedBy=default.target\n"
    )


def server_command(entry: dict[str, Any], gpu: bool = True) -> list[str]:
    cfg = config()["server"]
    exe = shutil.which("llama-server") or "llama-server"
    cmd = [exe, "-m", entry["path"], "--host", cfg["host"], "--port", str(cfg["port"]),
           "-c", str(entry.get("context") or cfg["default_context"]), "--jinja"]
    if gpu:
        cmd += ["-ngl", "999"]
    if entry.get("mmproj"):
        cmd += ["--mmproj", entry["mmproj"]]
    return cmd


def endpoint() -> str:
    cfg = config()["server"]
    return f"http://{cfg['host']}:{cfg['port']}/v1"


def is_running(timeout: float = 1.5) -> bool:
    cfg = config()["server"]
    try:
        with urllib.request.urlopen(f"http://{cfg['host']}:{cfg['port']}/health", timeout=timeout) as r:
            return r.status == 200
    except OSError:
        return False


def serve_foreground(branding: Branding | None = None) -> int:
    branding = branding or load_branding()
    reg = Registry(branding.id)
    default = reg.default()
    if not default:
        util.eprint(f"No default model. Install one with `{branding.cli} model install` first.")
        return 1
    mid, entry = default
    if "path" not in entry:
        util.eprint(f"Model {mid} is a HyperNix model without a local GGUF file; run it with `hypernix chat`.")
        return 1
    if not shutil.which("llama-server"):
        util.eprint(f"llama-server is not installed. Install it with `{branding.cli} ai runtime`.")
        return 1
    cmd = server_command(entry)
    util.eprint(f"Serving {mid} at {endpoint()}")
    os.execv(cmd[0], cmd)
    return 0  # unreachable


def start(branding: Branding | None = None) -> util.Result:
    branding = branding or load_branding()
    return util.Runner().run(["systemctl", "--user", "start", service_name(branding)], check=False, capture=True)


def stop(branding: Branding | None = None) -> util.Result:
    branding = branding or load_branding()
    return util.Runner().run(["systemctl", "--user", "stop", service_name(branding)], check=False, capture=True)


def installed_package(root: str | Path = "/") -> str:
    """Which llama.cpp build is installed, if any: the installed package's
    name, which may be a variant providing the configured one (for example
    llama.cpp-vulkan-git for llama.cpp-vulkan)."""
    from .. import pkg

    have = pkg.installed_provides(root)
    builds = [v for k, v in config()["packages"].items() if k != "default_gpu"]
    return next((have[p] for p in dict.fromkeys(builds) if p in have), "")
