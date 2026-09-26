"""Per-user installation of AI tools: HyperNix, the assistants (Hermis,
OpenClaw) and Claude Code.

Everything installs into the user's home (``~/.local``), never into system
directories, so a failed or unavailable tool can never break the OS, and no
root is needed after installation. Commands can run as another user (the
installer) or inside a target root (``arch-chroot``).
"""

from __future__ import annotations

import os
import pwd
import re
import shlex
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .. import paths, util
from ..branding import Branding, load as load_branding

TOOL_FILES = {
    "hermis": ("ai", "hermis", "assistant.toml"),
    "openclaw": ("ai", "openclaw", "assistant.toml"),
    "claude-code": ("ai", "claude-code", "tool.toml"),
}
ASSISTANTS = ("hermis", "openclaw")


@dataclass
class ToolSpec:
    id: str
    name: str
    method: str  # uv-tool | npm-user
    package: str
    version: str
    commands: list[str]
    python: str = ""
    node: str = ""
    homepage: str = ""
    license: str = ""
    description: str = ""
    upstream: str = ""
    launch: dict[str, Any] = field(default_factory=dict)

    @property
    def requirement(self) -> str:
        if not self.version:
            return self.package
        sep = "==" if self.method == "uv-tool" else "@"
        return f"{self.package}{sep}{self.version}"


def load_spec(tool_id: str) -> ToolSpec:
    if tool_id not in TOOL_FILES:
        raise KeyError(f"unknown tool {tool_id!r}")
    with paths.data(*TOOL_FILES[tool_id]).open("rb") as fh:
        raw = tomllib.load(fh)
    meta = raw.get("assistant") or raw.get("tool") or {}
    inst = raw["install"]
    return ToolSpec(
        id=meta["id"],
        name=meta["name"],
        method=inst["method"],
        package=inst["package"],
        version=inst.get("version", ""),
        commands=list(inst.get("commands", [])),
        python=inst.get("python", ""),
        node=inst.get("node", ""),
        homepage=meta.get("homepage", ""),
        license=meta.get("license", ""),
        description=meta.get("description", ""),
        upstream=meta.get("upstream", ""),
        launch=raw.get("launch", {}),
    )


def hypernix_config() -> dict[str, Any]:
    with paths.data("ai", "hypernix", "hypernix.toml").open("rb") as fh:
        return tomllib.load(fh)


# ---------------------------------------------------------------------------
# Version ranges (npm "engines" subset: comparators, spaces, ||)
# ---------------------------------------------------------------------------


def _vtuple(v: str) -> tuple[int, int, int]:
    nums = [int(x) for x in re.findall(r"\d+", v)[:3]]
    return tuple((nums + [0, 0, 0])[:3])  # type: ignore[return-value]


def satisfies(version: str, spec: str) -> bool:
    if not spec.strip():
        return True
    v = _vtuple(version)
    for alternative in spec.split("||"):
        ok = True
        for comp in alternative.split():
            m = re.match(r"^(>=|<=|>|<|=|\^|~)?v?([\d.]+)$", comp.strip())
            if not m:
                return False
            op, target = m.group(1) or "=", _vtuple(m.group(2))
            if op == "^":
                ok &= v >= target and v[0] == target[0]
            elif op == "~":
                ok &= v >= target and v[:2] == target[:2]
            else:
                ok &= {"=": v == target, ">=": v >= target, "<=": v <= target, ">": v > target, "<": v < target}[op]
        if ok:
            return True
    return False


# ---------------------------------------------------------------------------
# Running as the user
# ---------------------------------------------------------------------------


@dataclass
class UserContext:
    """Where and as whom per-user commands run."""

    user: str
    home: Path  # home as seen by the commands (inside the root)
    root: Path = Path("/")
    runner: util.Runner = field(default_factory=util.Runner)
    branding: Branding = field(default_factory=load_branding)

    @classmethod
    def current(cls, runner: util.Runner | None = None) -> "UserContext":
        pw = pwd.getpwuid(os.getuid())
        return cls(pw.pw_name, Path(pw.pw_dir), Path("/"), runner or util.Runner())

    @property
    def host_home(self) -> Path:
        """The home directory as seen from this process."""
        return self.root / str(self.home).lstrip("/")

    @property
    def bin_dir(self) -> Path:
        return self.home / ".local" / "bin"

    @property
    def data_dir(self) -> Path:
        return self.home / ".local" / "share" / self.branding.id

    def env(self) -> dict[str, str]:
        home = str(self.home)
        return {
            "HOME": home,
            "USER": self.user,
            "PATH": f"{home}/.local/bin:/usr/local/bin:/usr/bin",
            "XDG_DATA_HOME": f"{home}/.local/share",
            "XDG_CONFIG_HOME": f"{home}/.config",
            "XDG_CACHE_HOME": f"{home}/.cache",
            "UV_TOOL_BIN_DIR": f"{home}/.local/bin",
            "UV_NO_MODIFY_PATH": "1",
            "NPM_CONFIG_PREFIX": f"{home}/.local",
            "NPM_CONFIG_UPDATE_NOTIFIER": "false",
            "NPM_CONFIG_FUND": "false",
        }

    def run(self, cmd: list[str], check: bool = True, capture: bool = False) -> util.Result:
        env_args = [f"{k}={v}" for k, v in self.env().items()]
        same_user = str(self.root) == "/" and os.getuid() == pwd.getpwnam(self.user).pw_uid
        if same_user:
            return self.runner.run(cmd, check=check, capture=capture, env=self.env())
        wrapped = ["runuser", "-u", self.user, "--", "env", *env_args, *cmd]
        if str(self.root) != "/":
            wrapped = ["arch-chroot", str(self.root), *wrapped]
        return self.runner.run(wrapped, check=check, capture=capture)

    def shell(self, script: str, check: bool = True, capture: bool = False) -> util.Result:
        return self.run(["bash", "-c", script], check=check, capture=capture)


# ---------------------------------------------------------------------------
# Install / status / remove
# ---------------------------------------------------------------------------


class ToolError(RuntimeError):
    pass


def node_version(ctx: UserContext) -> str:
    if ctx.runner.dry_run:
        return "99.0.0"
    res = ctx.run(["node", "--version"], check=False, capture=True)
    return res.stdout.strip().lstrip("v") if res.ok else ""


def install_tool(spec: ToolSpec, ctx: UserContext, upgrade: bool = False) -> None:
    if spec.method == "uv-tool":
        cmd = ["uv", "tool", "install", "--force" if upgrade else "--upgrade", spec.requirement]
        if spec.python:
            cmd[3:3] = ["--python", spec.python]
        ctx.run(cmd)
    elif spec.method == "npm-user":
        have = node_version(ctx)
        if not have:
            raise ToolError(f"{spec.name} needs Node.js; install it with: sudo pacman -S nodejs npm")
        if spec.node and not satisfies(have, spec.node):
            raise ToolError(
                f"{spec.name} needs Node.js {spec.node}, but {have} is installed. "
                "Install a matching version (for example: sudo pacman -S nodejs-lts-krypton) and try again."
            )
        ctx.run(["npm", "install", "--global", "--prefix", str(ctx.home / ".local"), "--no-audit", spec.requirement])
    else:
        raise ToolError(f"unknown install method {spec.method!r}")


def remove_tool(spec: ToolSpec, ctx: UserContext) -> None:
    if spec.method == "uv-tool":
        ctx.run(["uv", "tool", "uninstall", spec.package], check=False)
    else:
        ctx.run(["npm", "uninstall", "--global", "--prefix", str(ctx.home / ".local"), spec.package], check=False)


def tool_installed(spec: ToolSpec, home: Path) -> bool:
    return all((home / ".local" / "bin" / c).exists() for c in spec.commands)


def tool_version(spec: ToolSpec, home: Path) -> str:
    exe = home / ".local" / "bin" / spec.commands[0]
    if not exe.exists():
        return ""
    rc, out = util.run_quiet([str(exe), "--version"], timeout=20)
    return out.strip().splitlines()[0] if rc == 0 and out.strip() else "installed"


# ---------------------------------------------------------------------------
# HyperNix
# ---------------------------------------------------------------------------


def hypernix_venv(ctx: UserContext) -> Path:
    return ctx.data_dir / hypernix_config()["install"]["venv"]


def install_hypernix(ctx: UserContext, torch_index: str, extra_env: dict[str, str] | None = None) -> None:
    cfg = hypernix_config()
    inst = cfg["install"]
    venv = hypernix_venv(ctx)
    py = venv / "bin" / "python"
    req = inst["package"] + (f"=={inst['version']}" if inst.get("version") else "")
    ctx.run(["uv", "venv", "--allow-existing", "--python", inst["python"], str(venv)])
    # PyTorch first, from the index matching the GPU; hypernix then reuses it.
    ctx.run(["uv", "pip", "install", "--python", str(py), "--index-url", torch_index, "torch"])
    ctx.run(["uv", "pip", "install", "--python", str(py), req])
    links = " ".join(
        f'[ -e {shlex.quote(str(venv / "bin" / c))} ] && ln -sf {shlex.quote(str(venv / "bin" / c))} {shlex.quote(str(ctx.bin_dir / c))};'
        for c in inst["commands"]
    )
    ctx.shell(f"mkdir -p {shlex.quote(str(ctx.bin_dir))}; {links} true")
    write_ai_env(ctx, {**cfg.get("env", {}), **(extra_env or {})})


def hypernix_installed(home: Path, branding: Branding) -> bool:
    return (home / ".local" / "bin" / "hypernix").exists()


def remove_hypernix(ctx: UserContext) -> None:
    cfg = hypernix_config()["install"]
    for c in cfg["commands"]:
        ctx.run(["rm", "-f", str(ctx.bin_dir / c)], check=False)
    ctx.run(["rm", "-rf", str(hypernix_venv(ctx))], check=False)


def write_ai_env(ctx: UserContext, env: dict[str, str]) -> None:
    """~/.config/<id>/ai.env: sourced by the shells and the launcher."""
    content = "# Environment for local AI tools; managed by `{} ai`.\n".format(ctx.branding.cli)
    content += "".join(f"{k}={shlex.quote(v)}\n" for k, v in sorted(env.items()))
    target = ctx.home / ".config" / ctx.branding.id / "ai.env"
    ctx.shell(f"mkdir -p {shlex.quote(str(target.parent))} && cat > {shlex.quote(str(target))} <<'EOF'\n{content}EOF")
