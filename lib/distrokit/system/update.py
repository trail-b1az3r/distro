"""System updates: one view over every source of updates, with pacman
remaining the tool that actually updates packages.

Sources:
  packages   Arch, EndeavourOS and distribution repositories (pacman -Syu)
  aur        AUR packages (yay -Sua)
  flatpak    Flatpak applications
  desktop    the desktop configuration shipped by <id>-desktop
  gpu        drift between the GPU configuration and the hardware
  ai         HyperNix, the AI assistants and Claude Code (per user)

Every command is printed before it runs, so nothing hides what pacman does.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

from .. import paths, pkg, util
from ..branding import Branding, load as load_branding

ARCH_NEWS = "https://archlinux.org/feeds/news/"


@dataclass
class Item:
    name: str
    current: str = ""
    new: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Source:
    id: str
    label: str
    items: list[Item] = field(default_factory=list)
    available: bool = True  # tool present / applicable
    error: str = ""
    needs_root: bool = False
    command: list[str] = field(default_factory=list)  # what `apply` runs, for display

    @property
    def count(self) -> int:
        return len(self.items)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["count"] = self.count
        return d


def _parse_updates(text: str) -> list[Item]:
    items = []
    for line in text.splitlines():
        m = re.match(r"^(\S+)\s+(\S+)\s+->\s+(\S+)", line.strip())
        if m:
            items.append(Item(*m.groups()))
    return items


def check_packages() -> Source:
    src = Source("packages", "System packages (pacman)", needs_root=True, command=["pacman", "-Syu"])
    if not util.which("checkupdates"):
        src.available, src.error = False, "checkupdates (pacman-contrib) is not installed"
        return src
    # checkupdates syncs a private copy of the databases: no root, no partial upgrades.
    rc, out = util.run_quiet(["checkupdates", "--nocolor"], timeout=180)
    if rc not in (0, 2):  # 2 = no updates
        src.error = "could not reach the package mirrors"
        return src
    src.items = _parse_updates(out)
    return src


def check_aur() -> Source:
    src = Source("aur", "AUR packages (yay)", command=["yay", "-Sua"])
    if not util.which("yay"):
        src.available, src.error = False, "yay is not installed"
        return src
    if os.geteuid() == 0:
        src.available, src.error = False, "run as your user to check AUR updates"
        return src
    rc, out = util.run_quiet(["yay", "-Qua", "--color", "never"], timeout=180)
    src.items = _parse_updates(out)
    return src


def check_flatpak() -> Source:
    src = Source("flatpak", "Flatpak applications", command=["flatpak", "update", "-y"])
    if not util.which("flatpak"):
        src.available = False
        return src
    rc, out = util.run_quiet(["flatpak", "remote-ls", "--updates", "--columns=application,version"], timeout=120)
    src.items = [Item(line.split("\t")[0], "", (line.split("\t") + [""])[1]) for line in out.splitlines() if line.strip()]
    return src


def desktop_version() -> str:
    path = paths.data("desktop", "VERSION")
    return path.read_text().strip() if path.exists() else ""


def check_desktop(home: Path | None = None, branding: Branding | None = None) -> Source:
    branding = branding or load_branding()
    home = home or Path.home()
    src = Source("desktop", "Desktop configuration", command=[branding.cli, "update", "--desktop-only"])
    state = paths.user_state_dir(branding.id, home) / "desktop-version"
    shipped = desktop_version()
    deployed = state.read_text().strip() if state.exists() else ""
    if shipped and shipped != deployed:
        src.items = [Item("desktop configuration", deployed[:12] or "(first deployment)", shipped[:12])]
    return src


def check_gpu(branding: Branding | None = None) -> Source:
    from ..gpu import apply as gpu_apply
    from ..gpu.plan import build_plan
    from ..hardware import detect

    branding = branding or load_branding()
    src = Source("gpu", "Graphics drivers", needs_root=True, command=[branding.cli, "gpu", "configure"])
    state = gpu_apply.load_state(branding=branding)
    if not state:
        return src
    report = detect()
    previous = {c["slot"]: c["stack"] for c in state["plan"]["choices"]}
    plan = build_plan(report, overrides={s: st for s, st in previous.items() if report.gpu(s)}, branding=branding)
    now = {c.slot: c.stack for c in plan.choices}
    if now != previous:
        src.items = [Item(f"GPU {slot}", previous.get(slot, "none"), stack) for slot, stack in now.items()
                     if previous.get(slot) != stack]
    installed = pkg.installed_packages()
    missing = [p for p in plan.packages if p not in installed]
    if missing:
        src.items.append(Item("missing driver packages", "", ", ".join(missing)))
    return src


def _pypi_latest(package: str) -> str:
    try:
        with urllib.request.urlopen(f"https://pypi.org/pypi/{package}/json", timeout=10) as r:
            return json.load(r)["info"]["version"]
    except (OSError, ValueError, KeyError):
        return ""


def _npm_latest(package: str) -> str:
    try:
        with urllib.request.urlopen(f"https://registry.npmjs.org/{package.replace('/', '%2F')}/latest", timeout=10) as r:
            return json.load(r)["version"]
    except (OSError, ValueError, KeyError):
        return ""


def _uv_tool_versions() -> dict[str, str]:
    rc, out = util.run_quiet(["uv", "tool", "list"], timeout=30)
    versions = {}
    for line in out.splitlines():
        m = re.match(r"^(\S+) v(\S+)", line)
        if m:
            versions[m.group(1)] = m.group(2)
    return versions


def _npm_user_versions(home: Path) -> dict[str, str]:
    root = home / ".local" / "lib" / "node_modules"
    versions = {}
    for pkg_json in list(root.glob("*/package.json")) + list(root.glob("@*/*/package.json")):
        try:
            data = json.loads(pkg_json.read_text())
            versions[data["name"]] = data["version"]
        except (OSError, ValueError, KeyError):
            pass
    return versions


def check_ai(home: Path | None = None, branding: Branding | None = None) -> Source:
    from ..ai import tools

    branding = branding or load_branding()
    home = home or Path.home()
    src = Source("ai", "AI tools", command=[branding.cli, "ai", "update"])
    if os.geteuid() == 0:
        src.available, src.error = False, "run as your user to check AI tools"
        return src
    uv_versions = _uv_tool_versions() if util.which("uv") else {}
    npm_versions = _npm_user_versions(home)
    for tool_id in (*tools.ASSISTANTS, "claude-code"):
        spec = tools.load_spec(tool_id)
        if not tools.tool_installed(spec, home):
            continue
        if spec.method == "uv-tool":
            cur, new = uv_versions.get(spec.package, ""), _pypi_latest(spec.package)
        else:
            cur, new = npm_versions.get(spec.package, ""), _npm_latest(spec.package)
        if cur and new and cur != new and not spec.version:
            src.items.append(Item(spec.name, cur, new))
    venv_py = home / ".local" / "share" / branding.id / "hypernix" / "venv" / "bin" / "python"
    if venv_py.exists():
        rc, out = util.run_quiet([str(venv_py), "-c", "import importlib.metadata as m; print(m.version('hypernix'))"])
        cur, new = out.strip(), _pypi_latest("hypernix")
        if cur and new and cur != new:
            src.items.append(Item("HyperNix", cur, new))
    return src


def check_all(branding: Branding | None = None, sources: list[str] | None = None) -> list[Source]:
    branding = branding or load_branding()
    checks: dict[str, Callable[[], Source]] = {
        "packages": check_packages,
        "aur": check_aur,
        "flatpak": check_flatpak,
        "desktop": lambda: check_desktop(branding=branding),
        "gpu": lambda: check_gpu(branding),
        "ai": lambda: check_ai(branding=branding),
    }
    result = []
    for sid, fn in checks.items():
        if sources and sid not in sources:
            continue
        try:
            result.append(fn())
        except Exception as exc:  # noqa: BLE001
            result.append(Source(sid, sid, error=str(exc)))
    return result


@dataclass
class News:
    title: str
    link: str
    published: float


def arch_news(since: float, timeout: float = 8.0) -> list[News]:
    """Arch news posts since a time. Posts often announce manual interventions,
    so the updater shows them before updating."""
    try:
        with urllib.request.urlopen(ARCH_NEWS, timeout=timeout) as r:
            root = ET.fromstring(r.read())
    except (OSError, ET.ParseError):
        return []
    items = []
    for item in root.iter("item"):
        title = item.findtext("title") or ""
        link = item.findtext("link") or ""
        pub = item.findtext("pubDate") or ""
        try:
            ts = time.mktime(time.strptime(pub[:25], "%a, %d %b %Y %H:%M:%S"))
        except ValueError:
            continue
        if ts > since:
            items.append(News(title, link, ts))
    return items


def last_update_time(root: Path = Path("/")) -> float:
    log = root / "var/log/pacman.log"
    if not log.exists():
        return 0.0
    last = 0.0
    with log.open(errors="replace") as fh:
        for line in fh:
            if "starting full system upgrade" in line:
                m = re.match(r"^\[(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})", line)
                if m:
                    last = time.mktime(time.strptime(m.group(1), "%Y-%m-%dT%H:%M:%S"))
    return last


# ---------------------------------------------------------------------------
# Applying
# ---------------------------------------------------------------------------


def apply_packages(runner: util.Runner, interactive: bool = True) -> None:
    cmd = ["pacman", "-Syu"] + ([] if interactive else ["--noconfirm"])
    if os.geteuid() != 0:
        cmd = ["sudo", *cmd]
    runner.run(cmd)


def apply_aur(runner: util.Runner, interactive: bool = True) -> None:
    runner.run(["yay", "-Sua"] + ([] if interactive else ["--noconfirm", "--answerdiff", "None", "--answerclean", "None"]))


def apply_flatpak(runner: util.Runner) -> None:
    runner.run(["flatpak", "update", "-y", "--noninteractive"])


def apply_desktop(branding: Branding | None = None, log: Callable[[str], None] = print) -> list[str]:
    from ..desktop.deploy import Deployer

    branding = branding or load_branding()
    dep = Deployer(Path.home(), branding, log=log)
    report = dep.deploy()
    state = paths.user_state_dir(branding.id) / "desktop-version"
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(desktop_version() + "\n")
    lines = [f"{len(report.written)} files updated"]
    if report.backed_up:
        lines.append(f"{len(report.backed_up)} files you changed were backed up to {report.backup_dir}")
    if report.removed:
        lines.append(f"{len(report.removed)} files no longer shipped were removed")
    return lines


def apply_ai(runner: util.Runner, branding: Branding | None = None) -> list[str]:
    from ..ai import tools

    branding = branding or load_branding()
    ctx = tools.UserContext.current(runner)
    done = []
    for tool_id in (*tools.ASSISTANTS, "claude-code"):
        spec = tools.load_spec(tool_id)
        if tools.tool_installed(spec, ctx.home):
            if spec.method == "uv-tool":
                ctx.run(["uv", "tool", "upgrade", spec.package])
            else:
                tools.install_tool(spec, ctx)
            done.append(spec.name)
    venv_py = ctx.data_dir / "hypernix" / "venv" / "bin" / "python"
    if venv_py.exists():
        ctx.run(["uv", "pip", "install", "--python", str(venv_py), "--upgrade", "hypernix"])
        done.append("HyperNix")
    return done
