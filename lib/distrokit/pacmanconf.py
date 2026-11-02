"""pacman.conf generation for the build host, the live ISO and installed systems.

Repository order: the ISO's offline repository (live only) or the
distribution's own repository first, then EndeavourOS, then Arch.
"""
from __future__ import annotations

import urllib.error
import urllib.request

from .branding import Branding, load as load_branding

OPTIONS = """\
[options]
HoldPkg     = pacman glibc
Architecture = auto
Color
ILoveCandy
VerbosePkgLists
CheckSpace
ParallelDownloads = 5
SigLevel    = Required DatabaseOptional
LocalFileSigLevel = Optional
"""


def distro_repo_block(branding: Branding, enabled: bool = True) -> str:
    server = branding.get("DISTRO_REPO_SERVER")
    if not server:
        return ""
    sig = "Required DatabaseOptional" if branding.get("DISTRO_REPO_KEY_ID") else branding.get("DISTRO_REPO_SIGLEVEL_UNSIGNED", "Optional TrustAll")
    block = f"[{branding.repo_name}]\nSigLevel = {sig}\nServer = {server}\n"
    if enabled:
        return block + "\n"
    return (f"# {server} has no {branding.repo_name}.db yet, so the {branding.repo_name} repository is off.\n"
            f"# `sudo {branding.cli} repair packages` turns it on once it is published.\n"
            + "".join(f"#{line}\n" for line in block.splitlines()) + "\n")


def experiments_repo_block(branding: Branding, enabled: bool = True) -> str:
    home = branding.get("DISTRO_HOME_URL", "").rstrip("/")
    if not home:
        return ""
    server = f"{home}/releases/download/nexora-experiments"
    block = f"[nexora-experiments]\nSigLevel = Optional TrustAll\nServer = {server}\n"
    return block + ("\n" if enabled else "")


def set_experiments_repo(text: str, enabled: bool, branding: Branding | None = None) -> str:
    branding = branding or load_branding()
    lines = text.splitlines(keepends=True)
    head = "[nexora-experiments]"
    start = next((i for i, line in enumerate(lines) if line.strip() in (head, "#" + head)), None)
    if start is not None:
        end = start + 1
        while end < len(lines) and lines[end].strip() and not lines[end].lstrip("#").startswith("["):
            end += 1
        if end < len(lines) and not lines[end].strip():
            end += 1
        lines = lines[:start] + lines[end:]
    if not enabled:
        return "".join(lines)
    block = experiments_repo_block(branding, True)
    # Put the experimental source immediately before the stable Nexora source.
    at = next((i for i, line in enumerate(lines) if line.strip() == f"[{branding.repo_name}]"), None)
    if at is None:
        at = next((i for i, line in enumerate(lines) if line.strip() == "[endeavouros]"), len(lines))
    return "".join(lines[:at]) + block + "".join(lines[at:])


def distro_repo_published(branding: Branding | None = None, timeout: float = 8.0) -> bool | None:
    branding = branding or load_branding()
    server = branding.get("DISTRO_REPO_SERVER")
    if not server:
        return None
    url = f"{server.rstrip('/')}/{branding.repo_name}.db"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, method="HEAD"), timeout=timeout):
            return True
    except urllib.error.HTTPError as e:
        return False if e.code in (403, 404, 410) else None
    except (OSError, ValueError):
        return None


def distro_repo_enabled(text: str, branding: Branding | None = None) -> bool:
    branding = branding or load_branding()
    return any(line.strip() == f"[{branding.repo_name}]" for line in text.splitlines())


def set_distro_repo(text: str, enabled: bool, branding: Branding | None = None) -> str:
    branding = branding or load_branding()
    block = distro_repo_block(branding, enabled)
    if not block:
        return text
    lines = text.splitlines(keepends=True)
    head = f"[{branding.repo_name}]"
    at = next((i for i, line in enumerate(lines) if line.strip() in (head, "#" + head)), None)
    if at is None:
        at = next((i for i, line in enumerate(lines) if line.strip() == "[endeavouros]"), len(lines))
        if at == len(lines) and lines and lines[-1].strip():
            block = "\n" + block
        return "".join(lines[:at]) + block + "".join(lines[at:])
    notes = {line + "\n" for line in distro_repo_block(branding, False).splitlines() if line.startswith("# ")}
    start = at
    while start > 0 and lines[start - 1] in notes:
        start -= 1
    end = at + 1
    while end < len(lines) and lines[end].strip() and not lines[end].lstrip("#").startswith("["):
        end += 1
    if end < len(lines) and not lines[end].strip():
        end += 1
    return "".join(lines[:start]) + block + "".join(lines[end:])


def render(kind: str, branding: Branding | None = None, *, offline_repo: str = "", archive_date: str = "",
           multilib: bool = True, distro_repo: bool = True) -> str:
    branding = branding or load_branding()
    if kind not in ("target", "live", "offline", "build"):
        raise ValueError(kind)
    options = OPTIONS
    if kind in ("target", "live", "offline"):
        options = options.replace("ParallelDownloads = 5\n", "ParallelDownloads = 5\nDownloadUser = alpm\n")
    out = [f"# pacman configuration for {branding.pretty_name} ({kind}).\n# See pacman.conf(5).\n\n", options, "\n"]
    local_name = f"{branding.repo_name}-offline"
    if kind in ("live", "offline", "build") and offline_repo:
        out.append(f"[{local_name}]\nSigLevel = Optional TrustAll\nServer = file://{offline_repo}\n\n")
    if kind == "offline":
        return "".join(out)
    if kind == "target" or (kind == "live" and not offline_repo):
        out.append(distro_repo_block(branding, distro_repo))
    out.append("[endeavouros]\nSigLevel = PackageRequired\nInclude = /etc/pacman.d/endeavouros-mirrorlist\n\n")
    repos = ["core", "extra"] + (["multilib"] if multilib else [])
    for repo in repos:
        if kind == "build" and archive_date:
            out.append(f"[{repo}]\nServer = https://archive.archlinux.org/repos/{archive_date}/$repo/os/$arch\n\n")
        else:
            out.append(f"[{repo}]\nInclude = /etc/pacman.d/mirrorlist\n\n")
    return "".join(out).rstrip("\n") + "\n"
