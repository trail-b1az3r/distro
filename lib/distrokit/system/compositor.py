"""A hyprland-plus built from source into /usr/local that hides the packaged one.

Halcyon's installer, its updater and hyprctl-lite can build hyprland-plus from source into /usr/local/bin, which
comes before /usr/bin in PATH (and its wayland-sessions entry is what the login screen starts). Once the
hyprland-plus package is installed, that copy is stale: it was linked against the libraries of its day, and when
pacman moves one of them on (aquamarine 0.15 to 0.16: libaquamarine.so.14 to .so.15) the copy cannot start, and
neither can the desktop, although the packaged Hyprland is fine.

The package's install script, ``<cli> doctor`` and ``<cli> repair hyprland`` use this to find such a copy and move
it aside (never delete it) to /usr/local/lib/hyprland-plus-retired/<time>/, so the packaged Hyprland runs.
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path

PROGRAMS = ("Hyprland", "hyprland", "hyprctl", "hyprpm", "start-hyprland")
RETIRED = "usr/local/lib/hyprland-plus-retired"
MARK = b"hyprland-plus"


def _contains(path: Path, needle: bytes, chunk: int = 1 << 20) -> bool:
    """Whether a (possibly large) file contains ``needle``, read in pieces."""
    try:
        with path.open("rb") as fh:
            tail = b""
            while block := fh.read(chunk):
                if needle in tail + block:
                    return True
                tail = block[-len(needle):]
    except OSError:
        return False
    return False


def package_installed(root: Path = Path("/")) -> bool:
    """Whether pacman has the hyprland-plus package (the AUR's or the distribution's) installed."""
    local = root / "var/lib/pacman/local"
    return any(p.is_dir() for p in local.glob("hyprland-plus-[0-9]*")) if local.is_dir() else False


def stale_local_build(root: Path = Path("/")) -> list[Path]:
    """The files of a hyprland-plus source build in /usr/local that hide the packaged hyprland-plus, or [].

    Only when the package is installed (otherwise the /usr/local build is the user's Hyprland), and only a
    hyprland-plus binary (a stock Hyprland someone built is left alone)."""
    binary = root / "usr/local/bin/Hyprland"
    if not (binary.is_file() and package_installed(root) and _contains(binary, MARK)):
        return []
    found = [root / "usr/local/bin" / name for name in PROGRAMS
             if (root / "usr/local/bin" / name).exists() or (root / "usr/local/bin" / name).is_symlink()]
    sessions = root / "usr/local/share/wayland-sessions"
    if sessions.is_dir():
        found += sorted(p for p in sessions.glob("hyprland*.desktop"))
    return found


def can_start(binary: Path, root: Path = Path("/")) -> list[str]:
    """The shared libraries ``binary`` needs that are missing (ldd's "not found"); [] when it can start or ldd
    is not there to ask."""
    from .. import util

    if str(root) != "/" or not shutil.which("ldd"):
        return []
    rc, out = util.run_quiet(["ldd", str(binary)])
    return sorted({line.split("=>")[0].strip() for line in out.splitlines() if "not found" in line})


def retire(files: list[Path], root: Path = Path("/"), stamp: str = "") -> Path:
    """Move ``files`` into /usr/local/lib/hyprland-plus-retired/<stamp>/, keeping their paths under /usr/local."""
    stamp = stamp or time.strftime("%Y%m%d-%H%M%S")
    dest = root / RETIRED / stamp
    local = root / "usr/local"
    for path in files:
        target = dest / path.relative_to(local)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), str(target))
    return dest
