"""Moving a system over from the distribution's former name (``DISTRO_LEGACY_IDS`` in distro.conf).

The distribution was Nexora; it is Frontline now. ``<id>-*`` packages replace the old ``<legacy>-*`` ones (pacman
asks once, at the first upgrade), and a pacman hook then runs ``<cli> migrate-legacy``, which moves everything the
old name was written into:

* pacman.conf: ``[<legacy>]``, ``[<legacy>-surface]``, ``[<legacy>-experiments...]`` become ``[<id>...]``, with the
  server addresses of the renamed releases;
* ``/etc/<legacy>``, ``/var/lib/<legacy>``, ``/var/cache/<legacy>``: moved to ``<id>``; the old path becomes a link;
* enabled units: links to ``<legacy>-*.service``/``.timer`` become links to the ``<id>-*`` units;
* the login screen (SDDM's ``Current=``), and the boot splash (Plymouth) when it was the old theme;
* every user's own folders and files named after it, in ``~/.config``, ``~/.local/share``, ``~/.local/state``,
  ``~/.cache`` and ``~`` itself: renamed, with a link left at the old name.

Everything is idempotent: a second run (every upgrade of the core package runs it) changes nothing. Nothing is
deleted: where both the old and the new path exist, the new one is kept and the old one is left where it was.
"""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

from .. import util
from ..branding import Branding, load as load_branding

# Per-user places where the old name appears as a file or folder name (nexora, nexora-msg, nexora-write, ...).
HOME_DIRS = (".config", ".local/share", ".local/state", ".cache", "")


def legacy_ids(b: Branding) -> list[str]:
    return [i for i in b.get("DISTRO_LEGACY_IDS").split() if i and i != b.id]


def rename_name(name: str, old: str, new: str) -> str | None:
    """``nexora`` -> ``frontline``, ``nexora-msg`` -> ``frontline-msg``, ``.nexora-code`` -> ``.frontline-code``;
    None for a name that is not the old one (``nexoraish`` is not)."""
    m = re.fullmatch(rf"(\.?){re.escape(old)}([-_.].*)?", name)
    if not m:
        return None
    return f"{m.group(1)}{new}{m.group(2) or ''}"


def pacman_conf(text: str, old: str, new: str) -> str:
    """Rename the old repositories' sections, and their release addresses."""
    text = re.sub(rf"(?m)^\[{re.escape(old)}((?:-[A-Za-z0-9_-]+)?)\]", rf"[{new}\1]", text)
    return re.sub(rf"(/releases/download/){re.escape(old)}-", rf"\g<1>{new}-", text)


def move(src: Path, dst: Path, log: list[str]) -> None:
    """Move ``src`` to ``dst`` and leave a link at ``src``; leave both alone when ``dst`` is already there."""
    if src.is_symlink() or not src.exists():
        return
    if dst.exists() or dst.is_symlink():
        log.append(f"kept {src} ({dst} exists)")
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.stat().st_dev == dst.parent.stat().st_dev:
        os.rename(src, dst)
    else:
        shutil.move(str(src), str(dst))
    os.symlink(dst.name if src.parent == dst.parent else dst, src)
    log.append(f"moved {src} -> {dst}")


def units(root: Path, old: str, new: str, log: list[str]) -> None:
    """Re-point enabled-unit links (``*.wants/<old>-x.timer``) at the renamed units."""
    for base in ("etc/systemd/system", "etc/systemd/user"):
        for wants in (root / base).glob("*.wants") if (root / base).is_dir() else []:
            for link in wants.iterdir():
                renamed = rename_name(link.name, old, new)
                if not renamed or not link.is_symlink():
                    continue
                kind = "user" if base.endswith("user") else "system"
                unit = Path("/usr/lib/systemd") / kind / renamed
                target = wants / renamed
                if (root / unit.relative_to("/")).exists() and not target.exists():
                    os.symlink(unit, target)
                    log.append(f"enabled {renamed} ({link.name} was)")
                if target.exists() or target.is_symlink():
                    link.unlink()


def login_screen(root: Path, old: str, new: str, log: list[str]) -> None:
    conf_d = root / "etc" / "sddm.conf.d"
    if not conf_d.is_dir():
        return
    for f in sorted(conf_d.iterdir()):
        renamed = None
        m = re.fullmatch(rf"(\d+-){re.escape(old)}(.*\.conf)", f.name)
        if m:
            renamed = f"{m.group(1)}{new}{m.group(2)}"
        text = f.read_text(errors="replace")
        new_text = re.sub(rf"(?m)^Current={re.escape(old)}$", f"Current={new}", text)
        target = conf_d / renamed if renamed else f
        if renamed and target.exists():
            continue
        if new_text != text or renamed:
            util.atomic_write(target, new_text)
            if renamed:
                f.unlink()
            log.append(f"login screen: {target.name}")


def boot_splash(root: Path, old: str, new: str, runner: util.Runner, log: list[str]) -> None:
    conf = root / "etc" / "plymouth" / "plymouthd.conf"
    if not conf.is_file() or not re.search(rf"(?m)^Theme={re.escape(old)}$", conf.read_text(errors="replace")):
        return
    if not (root / "usr" / "share" / "plymouth" / "themes" / new).is_dir():
        return
    if root == Path("/") and util.which("plymouth-set-default-theme"):
        # -R rebuilds the initramfs so the new splash is the one that shows.
        runner.run(["plymouth-set-default-theme", "-R", new], check=False)
    else:
        util.atomic_write(conf, re.sub(rf"(?m)^Theme={re.escape(old)}$", f"Theme={new}", conf.read_text()))
    log.append(f"boot splash: {new}")


def homes(root: Path) -> list[Path]:
    found = [root / "root"] if (root / "root").is_dir() else []
    home = root / "home"
    if home.is_dir():
        found += [d for d in sorted(home.iterdir()) if d.is_dir() and not d.is_symlink()]
    return found


def user_files(home: Path, old: str, new: str, log: list[str]) -> None:
    for sub in HOME_DIRS:
        d = home / sub if sub else home
        if not d.is_dir():
            continue
        for entry in sorted(d.iterdir()):
            if not sub and not entry.name.startswith("."):
                continue  # in the home folder itself only its hidden files: ~/nexora may be a project of the user's
            renamed = rename_name(entry.name, old, new)
            if renamed and not entry.is_symlink():
                dst = d / renamed
                if not (dst.exists() or dst.is_symlink()):
                    os.rename(entry, dst)
                    os.symlink(renamed, entry)
                    try:
                        st = dst.lstat()
                        os.lchown(entry, st.st_uid, st.st_gid)
                    except OSError:
                        pass
                    log.append(f"moved {entry} -> {dst.name}")


def migrate(root: Path | str = "/", b: Branding | None = None, runner: util.Runner | None = None) -> list[str]:
    """Move a system over from every legacy ID to the current one. Returns what was done, one line each."""
    b = b or load_branding()
    root = Path(root)
    runner = runner or util.Runner()
    log: list[str] = []
    for old in legacy_ids(b):
        conf = root / "etc" / "pacman.conf"
        if conf.is_file():
            text = conf.read_text()
            new_text = pacman_conf(text, old, b.id)
            if new_text != text:
                shutil.copy2(conf, conf.with_name(f"pacman.conf.{old}"))
                util.atomic_write(conf, new_text)
                log.append(f"pacman.conf: [{old}...] -> [{b.id}...] (the old file is pacman.conf.{old})")
        for base in ("etc", "var/lib", "var/cache"):
            move(root / base / old, root / base / b.id, log)
        units(root, old, b.id, log)
        login_screen(root, old, b.id, log)
        boot_splash(root, old, b.id, runner, log)
        for home in homes(root):
            user_files(home, old, b.id, log)
    return log


def main(argv: list[str] | None = None) -> int:
    log = migrate()
    for line in log:
        print(line)
    return 0
