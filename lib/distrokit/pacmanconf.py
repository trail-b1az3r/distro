"""pacman.conf generation for the build host, the live ISO and installed systems.

Repository order: the ISO's offline repository (live only) or the
distribution's own repository first, then EndeavourOS, then Arch. Package
names do not overlap between them, so the order only matters for speed.
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
    """The distribution repository's section. ``enabled=False`` writes it
    commented out: pacman stops every sync when one repository's database
    cannot be fetched, so a repository that is not published (yet) must not
    be switched on."""
    server = branding.get("DISTRO_REPO_SERVER")
    if not server:
        return ""
    if branding.get("DISTRO_REPO_KEY_ID"):
        sig = "Required DatabaseOptional"
    else:
        sig = branding.get("DISTRO_REPO_SIGLEVEL_UNSIGNED", "Optional TrustAll")
    block = f"[{branding.repo_name}]\nSigLevel = {sig}\nServer = {server}\n"
    if enabled:
        return block + "\n"
    return (f"# {server} has no {branding.repo_name}.db yet, so the {branding.repo_name} repository is off.\n"
            f"# `sudo {branding.cli} repair packages` turns it on once it is published.\n"
            + "".join(f"#{line}\n" for line in block.splitlines()) + "\n")


def distro_repo_published(branding: Branding | None = None, timeout: float = 8.0) -> bool | None:
    """Whether the distribution repository's database can be downloaded:
    True, False (the server answers, but there is no database), or None
    (no repository configured, or the server cannot be reached)."""
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
    """pacman.conf ``text`` with the distribution repository switched on or
    off. Added before [endeavouros] when it is not there at all."""
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
    # The section runs to the next blank line or section; the notes a
    # commented-out one carries sit right above it.
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
    """kind: target | live | offline | build.

    * target  - an installed system
    * live    - the live ISO (offline repository first, then online repositories)
    * offline - offline repository only (installing without network)
    * build   - the ISO build host; ``archive_date`` (YYYY/MM/DD) pins Arch
                packages to the Arch Linux Archive for reproducible builds

    ``distro_repo=False`` writes the distribution repository commented out
    (see :func:`distro_repo_block`).
    """
    branding = branding or load_branding()
    if kind not in ("target", "live", "offline", "build"):
        raise ValueError(kind)
    options = OPTIONS
    if kind in ("target", "live", "offline"):
        # Downloads run as the unprivileged alpm user (pacman 7). Not on the
        # build host, where containers and root-owned build trees get in the way.
        options = options.replace("ParallelDownloads = 5\n", "ParallelDownloads = 5\nDownloadUser = alpm\n")
    out = [f"# pacman configuration for {branding.pretty_name} ({kind}).\n# See pacman.conf(5).\n\n", options, "\n"]
    local_name = f"{branding.repo_name}-offline"
    if kind in ("live", "offline", "build") and offline_repo:
        out.append(f"[{local_name}]\nSigLevel = Optional TrustAll\nServer = file://{offline_repo}\n\n")
    if kind == "offline":
        return "".join(out)
    if kind == "target" or (kind == "live" and not offline_repo):
        # The build host makes these packages and the live ISO carries them in
        # its offline repository, so only installed systems use the published
        # repository (pacman stops when any configured repository is
        # unreachable, which must never block an installation).
        out.append(distro_repo_block(branding, distro_repo))
    out.append("[endeavouros]\nSigLevel = PackageRequired\nInclude = /etc/pacman.d/endeavouros-mirrorlist\n\n")
    repos = ["core", "extra"] + (["multilib"] if multilib else [])
    for repo in repos:
        if kind == "build" and archive_date:
            out.append(f"[{repo}]\nServer = https://archive.archlinux.org/repos/{archive_date}/$repo/os/$arch\n\n")
        else:
            out.append(f"[{repo}]\nInclude = /etc/pacman.d/mirrorlist\n\n")
    return "".join(out).rstrip("\n") + "\n"
