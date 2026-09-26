"""pacman.conf generation for the build host, the live ISO and installed systems.

Repository order: the ISO's offline repository (live only) or the
distribution's own repository first, then EndeavourOS, then Arch. Package
names do not overlap between them, so the order only matters for speed.
"""

from __future__ import annotations

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


def distro_repo_block(branding: Branding) -> str:
    server = branding.get("DISTRO_REPO_SERVER")
    if not server:
        return ""
    if branding.get("DISTRO_REPO_KEY_ID"):
        sig = "Required DatabaseOptional"
    else:
        sig = branding.get("DISTRO_REPO_SIGLEVEL_UNSIGNED", "Optional TrustAll")
    return f"[{branding.repo_name}]\nSigLevel = {sig}\nServer = {server}\n\n"


def render(kind: str, branding: Branding | None = None, *, offline_repo: str = "", archive_date: str = "",
           multilib: bool = True) -> str:
    """kind: target | live | offline | build.

    * target  - an installed system
    * live    - the live ISO (offline repository first, then online repositories)
    * offline - offline repository only (installing without network)
    * build   - the ISO build host; ``archive_date`` (YYYY/MM/DD) pins Arch
                packages to the Arch Linux Archive for reproducible builds
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
        out.append(distro_repo_block(branding))
    out.append("[endeavouros]\nSigLevel = PackageRequired\nInclude = /etc/pacman.d/endeavouros-mirrorlist\n\n")
    repos = ["core", "extra"] + (["multilib"] if multilib else [])
    for repo in repos:
        if kind == "build" and archive_date:
            out.append(f"[{repo}]\nServer = https://archive.archlinux.org/repos/{archive_date}/$repo/os/$arch\n\n")
        else:
            out.append(f"[{repo}]\nInclude = /etc/pacman.d/mirrorlist\n\n")
    return "".join(out).rstrip("\n") + "\n"
