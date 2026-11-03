"""The local model server (llama.cpp's llama-server) as an on-demand
systemd user service."""

from __future__ import annotations

import json
import os
import shutil
import tomllib
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .. import paths, util
from ..branding import Branding, load as load_branding
from .models import Registry


def config() -> dict[str, Any]:
    with paths.data("ai", "runtime", "llama-server.toml").open("rb") as fh:
        return tomllib.load(fh)


RUNNERS = ("t1", "ggml-hnx", "legacy")


def runner_config_path(branding: Branding | None = None) -> Path:
    branding = branding or load_branding()
    return paths.user_config_dir(branding.id) / "ai-runtime.toml"


def runner_backend(branding: Branding | None = None) -> str:
    path = runner_config_path(branding)
    try:
        with path.open("rb") as fh:
            selected = tomllib.load(fh).get("runner", {}).get("backend", "legacy")
    except (OSError, tomllib.TOMLDecodeError):
        selected = "legacy"
    return selected if selected in RUNNERS else "legacy"


def set_runner_backend(name: str, branding: Branding | None = None) -> None:
    if name not in RUNNERS:
        raise ValueError(f"runner must be one of: {', '.join(RUNNERS)}")
    path = runner_config_path(branding)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".toml.tmp")
    temporary.write_text(f'[runner]\nbackend = "{name}"\n', encoding="utf-8")
    temporary.replace(path)


def _t1_base_url() -> str:
    base = os.environ.get("T1_URL", "http://127.0.0.1:8000").rstrip("/")
    try:
        with urllib.request.urlopen(base + "/runner/status", timeout=2) as response:
            status = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, ValueError) as exc:
        raise RuntimeError("HyperNix T1 is not reachable. Start its local API first.") from exc
    model = status.get("model") or {}
    url = model.get("base_url") or status.get("base_url")
    if not status.get("loaded", bool(url)) or not url:
        raise RuntimeError("HyperNix T1 has no model loaded. Run 'hypernix-t1 built-in-runner start'.")
    url = str(url).rstrip("/")
    return url if url.endswith("/v1") else url + "/v1"


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
    if runner_backend() == "ggml-hnx":
        exe = shutil.which("hnx")
        if not exe:
            raise RuntimeError("HyperNix's hnx command is missing; install/update HyperNix first.")
        return [exe, "runtime", "serve", entry["path"], "--host", cfg["host"],
                "--port", str(cfg["port"]), "--gpu-layers", "999" if gpu else "0",
                "--context", str(entry.get("context") or cfg["default_context"])]
    exe = shutil.which("llama-server") or "llama-server"
    cmd = [exe, "-m", entry["path"], "--host", cfg["host"], "--port", str(cfg["port"]),
           "-c", str(entry.get("context") or cfg["default_context"]), "--jinja"]
    if gpu:
        cmd += ["-ngl", "999"]
    if entry.get("mmproj"):
        cmd += ["--mmproj", entry["mmproj"]]
    return cmd


def endpoint() -> str:
    if runner_backend() == "t1":
        return _t1_base_url()
    cfg = config()["server"]
    return f"http://{cfg['host']}:{cfg['port']}/v1"


def is_running(timeout: float = 1.5) -> bool:
    try:
        base = endpoint().removesuffix("/v1")
        with urllib.request.urlopen(base + "/health", timeout=timeout) as response:
            return response.status == 200
    except (OSError, RuntimeError, urllib.error.URLError):
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
    backend = runner_backend(branding)
    if backend == "t1":
        util.eprint("T1 is managed by HyperNix; start it with 'hypernix-t1 built-in-runner start'.")
        return 1
    if backend == "legacy" and not shutil.which("llama-server"):
        util.eprint(f"llama-server is not installed. Install it with `{branding.cli} ai runtime`.")
        return 1
    try:
        cmd = server_command(entry)
    except RuntimeError as exc:
        util.eprint(str(exc))
        return 1
    util.eprint(f"Serving {mid} at {endpoint()}")
    os.execv(cmd[0], cmd)
    return 0  # unreachable


def start(branding: Branding | None = None) -> util.Result:
    branding = branding or load_branding()
    if runner_backend(branding) == "t1":
        return util.Runner().run(["hypernix-t1", "built-in-runner", "start", "--no-pick"],
                                 check=False, capture=True)
    return util.Runner().run(["systemctl", "--user", "start", service_name(branding)], check=False, capture=True)


def stop(branding: Branding | None = None) -> util.Result:
    branding = branding or load_branding()
    if runner_backend(branding) == "t1":
        return util.Runner().run(["hypernix-t1", "built-in-runner", "stop"], check=False, capture=True)
    return util.Runner().run(["systemctl", "--user", "stop", service_name(branding)], check=False, capture=True)


def installed_package(root: str | Path = "/") -> str:
    """Which llama.cpp build is installed, if any: the installed package's
    name, which may be a variant providing the configured one (for example
    llama.cpp-vulkan-git for llama.cpp-vulkan)."""
    from .. import pkg

    have = pkg.installed_provides(root)
    builds = [v for k, v in config()["packages"].items() if k != "default_gpu"]
    return next((have[p] for p in dict.fromkeys(builds) if p in have), "")
