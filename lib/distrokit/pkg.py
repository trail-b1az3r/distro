"""pacman and yay helpers that work on the running system or on a mounted
target root (during installation)."""

from __future__ import annotations

import os
import pwd
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from . import util
from .boot import in_root

PACMAN_FLAGS = ["--noconfirm", "--needed"]
# --ask 4 answers "yes" to pacman's "remove conflicting package?" question, so
# replacing a driver stack happens in one transaction instead of failing.
ASK_CONFLICTS = ["--ask", "4"]


def installed_packages(root: Path | str = "/") -> dict[str, str]:
    """{name: version} from the local pacman database (no pacman call, no lock)."""
    local = Path(root) / "var" / "lib" / "pacman" / "local"
    result: dict[str, str] = {}
    if not local.is_dir():
        return result
    for entry in local.iterdir():
        desc = entry / "desc"
        if not desc.is_file():
            continue
        lines = desc.read_text(errors="replace").splitlines()
        name = version = ""
        for i, line in enumerate(lines):
            if line == "%NAME%" and i + 1 < len(lines):
                name = lines[i + 1]
            elif line == "%VERSION%" and i + 1 < len(lines):
                version = lines[i + 1]
        if name:
            result[name] = version
    return result


def is_installed(name: str, root: Path | str = "/") -> bool:
    return name in installed_packages(root)


def in_sync_db(names: list[str], root: Path | str = "/") -> dict[str, bool]:
    """Which packages the configured repositories provide (read-only)."""
    result = {}
    for name in names:
        cmd = ["pacman", "-Sp", "--print-format", "%n", name]
        if str(root) not in ("/", ""):
            cmd = ["pacman", "--sysroot", str(root), "-Sp", "--print-format", "%n", name]
        rc, _ = util.run_quiet(cmd, timeout=30)
        result[name] = rc == 0
    return result


def install(packages: list[str], runner: util.Runner, root: Path | str = "/", refresh: bool = False) -> None:
    if not packages:
        return
    sync = "-Syu" if refresh else "-S"
    in_root(runner, root, ["pacman", sync, *PACMAN_FLAGS, *ASK_CONFLICTS, *packages])


def remove(packages: list[str], runner: util.Runner, root: Path | str = "/") -> list[str]:
    present = [p for p in packages if p in installed_packages(root)]
    if present:
        in_root(runner, root, ["pacman", "-Rns", "--noconfirm", *present])
    return present


@contextmanager
def temporary_nopasswd(root: Path | str, user: str) -> Iterator[None]:
    """Let ``user`` run pacman through sudo without a password, for the
    duration of an unattended AUR build inside the installer. The drop-in is
    removed even if the build fails."""
    path = Path(root) / "etc" / "sudoers.d" / "00-installer-aur-build"
    util.atomic_write(path, f"{user} ALL=(ALL:ALL) NOPASSWD: /usr/bin/pacman\n", 0o440)
    try:
        yield
    finally:
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def aur_install(packages: list[str], runner: util.Runner, root: Path | str = "/", user: str | None = None) -> None:
    """Build and install AUR packages with yay as an unprivileged user."""
    if not packages:
        return
    user = user or os.environ.get("SUDO_USER") or ""
    if not user or user == "root":
        raise RuntimeError(
            "AUR packages must be built by a normal user. Run this command with sudo from your own account, "
            f"or install them yourself with: yay -S {' '.join(packages)}"
        )
    yay = ["yay", "-S", "--needed", "--noconfirm", "--answerdiff", "None", "--answerclean", "None",
           "--removemake", "--sudoloop", *packages]
    if str(root) in ("/", ""):
        home = pwd.getpwnam(user).pw_dir
        runner.run(["sudo", "-u", user, "-H", "env", f"HOME={home}", *yay])
    else:
        with temporary_nopasswd(root, user):
            in_root(runner, root, ["runuser", "-u", user, "--", "env", f"HOME=/home/{user}", *yay])


def install_with_fallback(repo: list[str], aur: list[str], runner: util.Runner, root: Path | str = "/",
                          user: str | None = None) -> list[str]:
    """Install repo packages with pacman; AUR packages via pacman when a
    configured repository (the distribution's own, or the ISO's offline repo)
    carries them, otherwise with yay. Returns the packages built with yay."""
    install(repo, runner, root)
    if not aur:
        return []
    if runner.dry_run:
        install(aur, runner, root)
        return []
    available = in_sync_db(aur, root)
    from_repo = [p for p in aur if available.get(p)]
    to_build = [p for p in aur if not available.get(p)]
    install(from_repo, runner, root)
    aur_install(to_build, runner, root, user)
    return to_build
