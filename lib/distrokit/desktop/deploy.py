"""Deploy the desktop (the dots repository plus the distribution layer) into a
user's home directory.

This follows the file-copy step of the dots' own installer
(``sdata/subcmd-install/3.files-legacy.sh``) so the result is what upstream
expects, with three differences that make it safe to run unattended and on
updates:

* it never needs a TTY, sudo or network;
* files the user changed since the last deployment are backed up before they
  are replaced, and files the user created are never deleted;
* a manifest of deployed files (``~/.local/state/<id>/desktop-manifest.json``)
  lets updates and ``reset-desktop`` know exactly what the desktop owns.

Upstream's rule stays: ``~/.config/hypr/custom`` belongs to the user and is
only created, never overwritten (except by an explicit reset, which backs it
up first).
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .. import paths, util
from ..branding import Branding, load as load_branding

MISC_EXCLUDE = {"quickshell", "fish", "hypr", "fontconfig"}
ENTRY_ANCHOR = 'require("hyprland.halcyon")'


def dots_dir() -> Path:
    return paths.data("desktop", "dots")


def overlay_dir() -> Path:
    return paths.data("desktop", "overlay")


def branding_wallpapers_dir() -> Path:
    return paths.data("branding", "wallpapers", "generated")


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


@dataclass
class UserSettings:
    """Choices made in the installer that end up in the user's own files."""

    keyboard_layout: str = "us"
    keyboard_variant: str = ""
    monitors: list[dict[str, Any]] = field(default_factory=list)  # {connector, scale}
    apps: dict[str, str] = field(default_factory=dict)  # variables.lua: terminal, browser, ...


@dataclass
class DeployReport:
    written: list[str] = field(default_factory=list)
    backed_up: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    kept: list[str] = field(default_factory=list)
    backup_dir: str = ""


class Deployer:
    def __init__(self, home: Path, branding: Branding | None = None, *, dots: Path | None = None,
                 overlay: Path | None = None, wallpapers: Path | None = None,
                 log: Callable[[str], None] | None = None, visible_home: Path | None = None):
        """``home`` is where files are written; ``visible_home`` is the path
        the user will see (differs during installation, e.g. /mnt/home/x)."""
        self.home = Path(home)
        self.visible_home = Path(visible_home or home)
        self.branding = branding or load_branding()
        self.dots = Path(dots or dots_dir())
        self.overlay = Path(overlay or overlay_dir())
        self.wallpapers = Path(wallpapers or branding_wallpapers_dir())
        self.log = log or (lambda _m: None)
        self.state = self.home / ".local" / "state" / self.branding.id
        self.manifest_path = self.state / "desktop-manifest.json"
        self.config = self.home / ".config"
        self.report = DeployReport()
        self._manifest: dict[str, str] = {}
        self._new_manifest: dict[str, str] = {}
        self._backup_root: Path | None = None
        # Deploy-time changes to the user's copy of upstream files (never to
        # upstream itself), keyed by path relative to home.
        self._transforms: dict[str, Callable[[bytes], bytes]] = {
            ".config/quickshell/ii/services/FirstRunExperience.qml": self._greeting,
        }

    # -- helpers --------------------------------------------------------------
    def _rel(self, target: Path) -> str:
        return str(target.relative_to(self.home))

    def _backup(self, target: Path) -> None:
        if self._rel(target) in self.report.backed_up:
            return
        if self._backup_root is None:
            self._backup_root = self.state / "desktop-backups" / time.strftime("%Y%m%d-%H%M%S")
            self.report.backup_dir = str(self.visible_home / self._backup_root.relative_to(self.home))
        dest = self._backup_root / self._rel(target)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target, dest)
        self.report.backed_up.append(self._rel(target))

    def _install(self, src: Path, target: Path, *, content: bytes | None = None, overwrite: bool = True) -> None:
        rel = self._rel(target)
        data = content if content is not None else src.read_bytes()
        if content is None and rel in self._transforms:
            data = self._transforms[rel](data)
        new_hash = hashlib.sha256(data).hexdigest()
        if target.is_symlink():
            target.unlink()
        if target.exists():
            if not overwrite:
                self.report.kept.append(rel)
                self._new_manifest[rel] = self._manifest.get(rel, _sha(target))
                return
            current = _sha(target)
            if current == new_hash:
                self._new_manifest[rel] = new_hash
                return
            # The user changed a file we deployed (or a file we never deployed
            # is in the way): keep a copy before replacing it. A file written
            # earlier in this same run is ours and needs no backup.
            if self._manifest.get(rel) != current and self._new_manifest.get(rel) != current:
                self._backup(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        if src is not None and src.exists() and os.access(src, os.X_OK) and content is None:
            target.chmod(0o755)
        self._new_manifest[rel] = new_hash
        self.report.written.append(rel)

    def _sync_dir(self, src: Path, dest: Path, exclude: set[str] | None = None, overwrite: bool = True) -> None:
        exclude = exclude or set()
        for path in sorted(src.rglob("*")):
            rel_parts = path.relative_to(src).parts
            if rel_parts[0] in exclude or ".git" in rel_parts:
                continue
            if path.is_dir():
                continue
            target = dest / path.relative_to(src)
            if path.is_symlink():
                link = os.readlink(path)
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.is_symlink() or target.exists():
                    if target.is_symlink() and os.readlink(target) == link:
                        continue
                    if not overwrite:
                        continue
                    if target.is_file() and not target.is_symlink():
                        self._backup(target)
                    target.unlink()
                os.symlink(link, target)
                continue
            self._install(path, target, overwrite=overwrite)

    def _prune(self) -> None:
        """Delete files we deployed last time that upstream no longer ships,
        unless the user changed them. Files the user created are untouched."""
        for rel, old_hash in self._manifest.items():
            if rel in self._new_manifest:
                continue
            target = self.home / rel
            if not target.is_file():
                continue
            if _sha(target) != old_hash:
                self._backup(target)
            target.unlink()
            self.report.removed.append(rel)

    # -- steps ----------------------------------------------------------------
    def deploy(self, settings: UserSettings | None = None, *, first: bool | None = None) -> DeployReport:
        cfg_src = self.dots / "dots" / ".config"
        if not cfg_src.is_dir():
            raise FileNotFoundError(f"desktop configuration not found at {cfg_src} (is the dots submodule checked out?)")
        self._manifest = util.read_json(self.manifest_path, {}) or {}
        first = (not self.manifest_path.exists()) if first is None else first

        # Miscellaneous app configs (kitty, foot, fuzzel, Kvantum, matugen, ...)
        for item in sorted(cfg_src.iterdir()):
            if item.name in MISC_EXCLUDE:
                continue
            if item.is_dir():
                self._sync_dir(item, self.config / item.name)
            else:
                self._install(item, self.config / item.name)
        konsole = self.dots / "dots" / ".local" / "share" / "konsole"
        if konsole.is_dir():
            self._sync_dir(konsole, self.home / ".local" / "share" / "konsole")

        # Quickshell (the bar, sidebars, overview...), Fish, fontconfig.
        self._sync_dir(cfg_src / "quickshell", self.config / "quickshell")
        self._sync_dir(cfg_src / "fish", self.config / "fish", exclude={"conf.d"})
        self._sync_dir(cfg_src / "fontconfig", self.config / "fontconfig")

        # Hyprland: upstream defaults, entry point with our layer, lock/idle.
        hypr_src = cfg_src / "hypr"
        hypr = self.config / "hypr"
        self._sync_dir(hypr_src / "hyprland", hypr / "hyprland")
        old_conf = hypr / "hyprland.conf"
        if old_conf.exists() and not old_conf.is_symlink():
            old_conf.rename(hypr / "hyprland.conf.old")  # as upstream: the Lua config replaces it
        self._install(hypr_src / "hyprland.lua", hypr / "hyprland.lua",
                      content=self.entry_point((hypr_src / "hyprland.lua").read_text()).encode())
        for name in ("hyprlock.conf", "hypridle.conf"):
            self._install(hypr_src / name, hypr / name, overwrite=True)
        hyprlock_dir = hypr_src / "hyprlock"
        if hyprlock_dir.is_dir():
            self._sync_dir(hyprlock_dir, hypr / "hyprlock")
        custom_exists = (hypr / "custom").exists()
        self._sync_dir(hypr_src / "custom", hypr / "custom", overwrite=False)
        layer_src = self.overlay / "hypr" / "init.lua.in"
        self._install(layer_src, hypr / self.branding.id / "init.lua",
                      content=self.branding.render(layer_src.read_text()).encode())

        icon = self.dots / "dots" / ".local" / "share" / "icons" / "illogical-impulse.svg"
        if icon.exists():
            self._install(icon, self.home / ".local" / "share" / "icons" / "illogical-impulse.svg")

        # Wallpapers into the folder the wallpaper picker opens; the
        # distribution's own wallpaper becomes the first-run default.
        walls = self.home / "Pictures" / "Wallpapers"
        for src_dir in (self.dots / "wallpapers", self.wallpapers):
            if src_dir.is_dir():
                for wp in sorted(src_dir.iterdir()):
                    if wp.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"):
                        self._install(wp, walls / wp.name, overwrite=False)
        self._customise_shell()

        # Upstream's own bookkeeping, so its `./setup uninstall` keeps working.
        ii = self.config / "illogical-impulse"
        ii.mkdir(parents=True, exist_ok=True)
        (ii / "installed_true").touch()
        listing = sorted(str(self.visible_home / rel) for rel in self._new_manifest)
        (ii / "installed_listfile").write_text("\n".join(listing) + "\n")

        # ydotool is a user service upstream enables for the on-screen keyboard.
        wants = self.config / "systemd" / "user" / "default.target.wants"
        wants.mkdir(parents=True, exist_ok=True)
        link = wants / "ydotool.service"
        if not link.exists() and not link.is_symlink():
            os.symlink("/usr/lib/systemd/user/ydotool.service", link)

        if settings is not None and (first or not custom_exists):
            self.write_user_settings(settings)

        self._prune()
        util.write_json(self.manifest_path, self._new_manifest)
        return self.report

    def entry_point(self, upstream: str) -> str:
        """Upstream's hyprland.lua with the distribution layer inserted after
        Halcyon and before ~/.config/hypr/custom."""
        block = (
            f"\n-- {self.branding.pretty_name} layer (see ~/.config/hypr/{self.branding.id}/init.lua) --\n"
            f'if is_file_exists(HOME .. "/.config/hypr/{self.branding.id}/init.lua") then\n'
            f'    require("{self.branding.id}.init")\n'
            "end\n"
        )
        if ENTRY_ANCHOR in upstream:
            return upstream.replace(ENTRY_ANCHOR, ENTRY_ANCHOR + "\n" + block, 1)
        marker = "-- Custom configurations --"
        if marker in upstream:
            return upstream.replace(marker, block.lstrip("\n") + "\n" + marker, 1)
        return upstream.rstrip("\n") + "\n" + block

    def _customise_shell(self) -> None:
        """The distribution's wallpaper becomes the shell's first-run default
        (in the user's copy; upstream's file is untouched)."""
        qs = self.config / "quickshell" / "ii"
        default_wp = sorted(self.wallpapers.glob("*-default.png")) if self.wallpapers.is_dir() else []
        target = qs / "assets" / "images" / "default_wallpaper.png"
        if default_wp and target.parent.is_dir():
            self._install(default_wp[0], target)

    def _greeting(self, data: bytes) -> bytes:
        text = data.decode("utf-8")
        text = re.sub(r'(property string firstRunNotifSummary: )"[^"]*"',
                      lambda m: f'{m.group(1)}"Welcome to {self.branding.pretty_name}"', text)
        return text.encode("utf-8")

    def write_user_settings(self, s: UserSettings) -> None:
        custom = self.config / "hypr" / "custom"
        custom.mkdir(parents=True, exist_ok=True)
        head = f"-- Written by the {self.branding.name} installer. This file is yours: edit it freely.\n"
        general = head + (
            "-- Keyboard layout chosen during installation.\n"
            "hl.config({\n    input = {\n"
            f'        kb_layout = "{_lua_str(s.keyboard_layout)}",\n'
            f'        kb_variant = "{_lua_str(s.keyboard_variant)}"\n'
            "    }\n})\n"
        )
        if s.monitors:
            general += "\n-- Displays found during installation, with a scale suited to their pixel density.\n"
            general += "-- `hyprctl monitors` lists names; change `scale` to taste (1, 1.25, 1.5, 2...).\n"
            for m in s.monitors:
                general += (
                    f'hl.monitor({{ output = "{_lua_str(m["connector"])}", mode = "preferred", '
                    f'position = "auto", scale = {float(m["scale"]):g} }})\n'
                )
        variables = head + "-- Default applications for the keybinds (Super+Enter, Super+E, ...).\n"
        for key in ("terminal", "fileManager", "browser", "codeEditor", "officeSoftware", "textEditor"):
            if s.apps.get(key):
                variables += f'{key} = "{_lua_str(s.apps[key])}"\n'
        for name, content in (("general.lua", general), ("variables.lua", variables)):
            target = custom / name
            if target.exists() and target.read_text().strip() and head not in target.read_text():
                upstream = self.dots / "dots" / ".config" / "hypr" / "custom" / name
                if not (upstream.exists() and upstream.read_text() == target.read_text()):
                    self._backup(target)
            target.write_text(content)
            self.report.written.append(self._rel(target))
            self._new_manifest[self._rel(target)] = hashlib.sha256(content.encode()).hexdigest()

    # -- reset ----------------------------------------------------------------
    def reset(self, settings: UserSettings | None = None) -> DeployReport:
        """Back up everything the desktop owns (and custom/), then deploy fresh."""
        manifest = util.read_json(self.manifest_path, {}) or {}
        for rel, deployed_hash in manifest.items():
            target = self.home / rel
            if target.is_file() and not target.is_symlink() and _sha(target) != deployed_hash:
                self._backup(target)
        custom = self.config / "hypr" / "custom"
        if custom.is_dir():
            for f in custom.rglob("*"):
                if f.is_file():
                    self._backup(f)
            shutil.rmtree(custom)
        if self.manifest_path.exists():
            self.manifest_path.unlink()
        backup_root = self._backup_root
        report = self.deploy(settings, first=True)
        self._backup_root = backup_root
        return report


def _lua_str(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def default_apps(installed: set[str], editor_command: str = "") -> dict[str, str]:
    """Keybind applications, only for what is actually installed."""
    apps = {"terminal": "konsole", "fileManager": "dolphin"}
    if "firefox" in installed:
        apps["browser"] = "firefox"
    if editor_command:
        apps["codeEditor"] = editor_command
    if "onlyoffice-bin" in installed:
        apps["officeSoftware"] = "onlyoffice-desktopeditors"
    if "kate" in installed:
        apps["textEditor"] = "kate"
    return apps
