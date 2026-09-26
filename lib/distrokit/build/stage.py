"""Lay out the files of the distribution's own packages.

    python3 -m distrokit.build.stage <component> <destdir>
    python3 -m distrokit.build.stage --list

Each ``package_<id>-<component>()`` function in the PKGBUILD calls this with
``$pkgdir``, so the file layout is defined (and unit-tested) in one place.

========== ================================================================
component  contents
========== ================================================================
core       distrokit, data files, CLI, GPU tool, privileged helper, pacman
           hooks, polkit policy, completions, model-server user unit
branding   logos, icons, wallpapers, boot splash, GRUB/SDDM themes, fastfetch
desktop    the dots (pinned) and the distribution layer, shell integration
welcome    Welcome wizard and graphical updater
installer  graphical and unattended installer
ai         AI launcher and model manager
========== ================================================================

The branding component needs the generated artwork (``python3 -m
distrokit.build.branding``), which the PKGBUILD's build() runs.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

from .. import paths
from ..ai import runtime
from ..branding import Branding, load as load_branding
from . import completions

COMPONENTS = ("core", "branding", "desktop", "welcome", "installer", "ai")
IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo", ".git", ".github", ".gitmodules", "*.orig")


class Stage:
    def __init__(self, dest: Path, b: Branding, src: Path | None = None):
        self.dest = Path(dest)
        self.b = b
        self.src = Path(src or paths.DATA_ROOT)
        self.share = f"/usr/share/{b.id}"
        self.lib = f"/usr/lib/{b.id}"

    # -- primitives --------------------------------------------------------------
    def p(self, path: str) -> Path:
        return self.dest / path.lstrip("/")

    def file(self, src: Path | str, dest: str, mode: int = 0o644) -> None:
        target = self.p(dest)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(self.src / src, target)
        target.chmod(mode)

    def text(self, dest: str, content: str, mode: int = 0o644) -> None:
        target = self.p(dest)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
        target.chmod(mode)

    def template(self, src: Path | str, dest: str, mode: int = 0o644) -> None:
        self.text(dest, self.b.render((self.src / src).read_text()), mode)

    def tree(self, src: Path | str, dest: str, ignore=IGNORE) -> None:
        target = self.p(dest)
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(self.src / src, target, ignore=ignore, symlinks=True)
        for root, dirs, files in os.walk(target):
            for d in dirs:
                p = Path(root) / d
                if not p.is_symlink():
                    p.chmod(0o755)
            for f in files:
                p = Path(root) / f
                if not p.is_symlink():
                    p.chmod(0o755 if os.access(p, os.X_OK) else 0o644)

    def link(self, dest: str, target: str) -> None:
        link = self.p(dest)
        link.parent.mkdir(parents=True, exist_ok=True)
        if link.is_symlink() or link.exists():
            link.unlink()
        link.symlink_to(target)

    def python_entry(self, dest: str, module: str, func: str = "main", comment: str = "") -> None:
        """A launcher that runs distrokit in isolated mode (-I): environment
        variables and the user's site-packages cannot change what runs, which
        matters for the helpers started through sudo and pkexec."""
        self.text(dest, (
            "#!/usr/bin/python3 -I\n"
            f"# {comment or self.b.pretty_name}\n"
            "import sys\n"
            f"sys.path.insert(0, {self.lib!r})\n"
            f"from {module} import {func}\n"
            f"sys.exit({func}())\n"
        ), 0o755)

    def desktop_entry(self, name: str) -> None:
        self.template(f"desktop/overlay/applications/{name}.desktop.in",
                      f"/usr/share/applications/{self.b.id}-{name}.desktop")

    def license(self, pkg: str) -> None:
        if (self.src / "LICENSE").is_file():
            self.file("LICENSE", f"/usr/share/licenses/{pkg}/LICENSE")

    # -- components ------------------------------------------------------------------
    def core(self) -> None:
        b, share, lib = self.b, self.share, self.lib
        self.tree("lib/distrokit", f"{lib}/distrokit")
        self.file("distro.conf", f"{share}/distro.conf")
        for d in ("profiles", "hardware", "ai", "packages/lists"):
            self.tree(d, f"{share}/{d}")
        self.file("packages/editors.toml", f"{share}/packages/editors.toml")
        self.tree("branding/icons/ui", f"{share}/branding/icons/ui")

        self.python_entry(f"/usr/bin/{b.cli}", "distrokit.cli", comment=f"{b.pretty_name} system tool")
        self.link(f"/usr/bin/{b.id}-gpu", b.cli)
        self.link("/usr/bin/distro-gpu", b.cli)
        self.python_entry(f"{lib}/bin/{b.id}-privileged", "distrokit.privileged",
                          comment="Privileged actions of the graphical apps (through pkexec)")
        self.python_entry(f"{lib}/bin/{b.id}-update-boot", "distrokit.hooks", "update_boot_main",
                          comment="pacman hook: boot entries after kernel changes")
        self.python_entry(f"{lib}/bin/{b.id}-os-release", "distrokit.hooks", "os_release_main",
                          comment="pacman hook: distribution identity files")

        hooks = "/usr/share/libalpm/hooks"
        self.text(f"{hooks}/90-{b.id}-os-release.hook", (
            "[Trigger]\nType = Path\nOperation = Install\nOperation = Upgrade\n"
            "Target = usr/lib/os-release\nTarget = etc/lsb-release\nTarget = etc/issue\n"
            f"Target = {lib.lstrip('/')}/bin/{b.id}-os-release\n\n"
            f"[Action]\nDescription = Updating {b.name} identity files...\nWhen = PostTransaction\n"
            f"Exec = {lib}/bin/{b.id}-os-release\n"
        ))
        # After mkinitcpio's 90-mkinitcpio-install hook has copied the kernels.
        self.text(f"{hooks}/95-{b.id}-boot.hook", (
            "[Trigger]\nType = Path\nOperation = Install\nOperation = Upgrade\nOperation = Remove\n"
            "Target = usr/lib/modules/*/vmlinuz\nTarget = usr/lib/initcpio/*\n"
            "Target = usr/share/grub/themes/*\n\n"
            f"[Action]\nDescription = Updating {b.name} boot entries...\nWhen = PostTransaction\n"
            f"Exec = {lib}/bin/{b.id}-update-boot\n"
        ))

        self.text(f"/usr/share/polkit-1/actions/org.{b.id}.privileged.policy", polkit_policy(b, lib))
        self.text(f"/usr/lib/systemd/user/{runtime.service_name(b)}", runtime.unit_text(b))

        parser = _parser()
        self.text(f"/usr/share/bash-completion/completions/{b.cli}", completions.bash(b, parser))
        for alias in (f"{b.id}-gpu", "distro-gpu"):
            self.link(f"/usr/share/bash-completion/completions/{alias}", b.cli)
        self.text(f"/usr/share/fish/vendor_completions.d/{b.cli}.fish", completions.fish(b, parser))
        from . import manpage

        epoch = int(os.environ.get("SOURCE_DATE_EPOCH", "0")) or None
        date = __import__("time").strftime("%Y-%m", __import__("time").gmtime(epoch))
        self.text(f"/usr/share/man/man1/{b.cli}.1", manpage.render(b, parser, date))
        self.link(f"/usr/share/man/man1/{b.id}-gpu.1", f"{b.cli}.1")
        for d in ("/etc", "/var/lib", "/var/log"):
            self.p(f"{d}/{b.id}").mkdir(parents=True, exist_ok=True)
        self.license(f"{b.id}-core")

    def branding(self) -> None:
        b, share = self.b, self.share
        gen = Path("branding/generated")
        if not (self.src / gen / "wallpapers").is_dir():
            raise SystemExit("branding artwork is missing: run `python3 -m distrokit.build.branding` first")
        for d in ("logo", "wallpapers", "icons/apps"):
            self.tree(gen / d, f"{share}/branding/generated/{d}")
        for f in ("logo-256.png", "logo-96.png", "logo-wordmark.png"):
            self.file(gen / f, f"{share}/branding/generated/{f}")
        self.tree(gen / "icons" / "hicolor", "/usr/share/icons/hicolor")
        self.file(gen / "logo" / "logo-mark.svg", f"/usr/share/pixmaps/{b.id}.svg")
        self.file(gen / "logo-256.png", f"/usr/share/pixmaps/{b.id}.png")
        for wp in sorted((self.src / gen / "wallpapers").iterdir()):
            self.link(f"/usr/share/backgrounds/{b.id}/{wp.name}", f"{share}/branding/generated/wallpapers/{wp.name}")

        ply = f"/usr/share/plymouth/themes/{b.id}"
        for f in sorted((self.src / gen / "plymouth").iterdir()):
            name = {"theme.plymouth": f"{b.id}.plymouth", "theme.script": f"{b.id}.script"}.get(f.name, f.name)
            self.file(f, f"{ply}/{name}")
        self.tree(gen / "grub", f"/usr/share/grub/themes/{b.id}")
        self.tree(gen / "sddm", f"/usr/share/sddm/themes/{b.id}")
        self.file(gen / "fastfetch" / "config.jsonc", f"{share}/fastfetch.jsonc")
        self.file(gen / "fastfetch" / "logo.ansi", f"{share}/fastfetch-logo.ansi")
        # Plain `fastfetch` would otherwise show the ID_LIKE distribution's logo.
        self.file(gen / "fastfetch" / "config.jsonc", "/etc/xdg/fastfetch/config.jsonc")
        self.license(f"{b.id}-branding")

    def desktop(self) -> None:
        b, share, lib = self.b, self.share, self.lib
        self.tree("desktop/dots", f"{share}/desktop/dots")
        self.tree("desktop/overlay", f"{share}/desktop/overlay")
        self.text(f"{share}/desktop/VERSION", desktop_version(self.src) + "\n")
        self.template("desktop/overlay/fish/vendor.fish.in", f"/usr/share/fish/vendor_conf.d/{b.id}.fish")
        self.template("desktop/overlay/profile.d/profile.sh.in", f"/etc/profile.d/{b.id}.sh")
        self.template("desktop/overlay/bin/session-start.in", f"{lib}/bin/{b.id}-session-start", 0o755)
        self.file("desktop/overlay/xdg/mimeapps.list", "/etc/xdg/mimeapps.list")
        self.file("desktop/overlay/xdg/xdg-terminals.list", "/etc/xdg/xdg-terminals.list")
        self.license(f"{b.id}-desktop")

    def welcome(self) -> None:
        b = self.b
        self.python_entry(f"/usr/bin/{b.id}-welcome", "distrokit.gui.welcome_app", comment=f"Welcome to {b.name}")
        self.python_entry(f"/usr/bin/{b.id}-update", "distrokit.gui.updater_app", comment="System update")
        self.desktop_entry("welcome")
        self.desktop_entry("update")
        self.license(f"{b.id}-welcome")

    def installer(self) -> None:
        b = self.b
        self.python_entry(f"/usr/bin/{b.id}-installer", "distrokit.installer.main", comment=f"Install {b.name}")
        self.desktop_entry("installer")
        self.license(f"{b.id}-installer")

    def ai(self) -> None:
        b = self.b
        self.python_entry(f"/usr/bin/{b.id}-ai", "distrokit.gui.ai_app", comment="AI launcher and model manager")
        self.desktop_entry("ai")
        self.desktop_entry("models")
        self.license(f"{b.id}-ai")

    def run(self, component: str) -> None:
        if component not in COMPONENTS:
            raise SystemExit(f"unknown component {component!r}; choose from {', '.join(COMPONENTS)}")
        getattr(self, component)()


def _parser():
    from ..cli import build_parser

    return build_parser()


def polkit_policy(b: Branding, lib: str) -> str:
    """pkexec rule for the privileged helper: an administrator password,
    remembered briefly so one Welcome session does not ask repeatedly."""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE policyconfig PUBLIC "-//freedesktop//DTD PolicyKit Policy Configuration 1.0//EN"
 "http://www.freedesktop.org/standards/PolicyKit/1/policyconfig.dtd">
<policyconfig>
  <vendor>{b.pretty_name}</vendor>
  <vendor_url>{b.get('DISTRO_HOME_URL')}</vendor_url>
  <icon_name>{b.id}</icon_name>
  <action id="org.{b.id}.privileged">
    <description>Change system settings</description>
    <message>Authentication is required to change system settings, install updates or configure drivers.</message>
    <defaults>
      <allow_any>auth_admin</allow_any>
      <allow_inactive>auth_admin</allow_inactive>
      <allow_active>auth_admin_keep</allow_active>
    </defaults>
    <annotate key="org.freedesktop.policykit.exec.path">{lib}/bin/{b.id}-privileged</annotate>
  </action>
  <action id="org.{b.id}.installer">
    <description>Install {b.name}</description>
    <message>Authentication is required to partition disks and install {b.name}.</message>
    <defaults>
      <allow_any>auth_admin</allow_any>
      <allow_inactive>auth_admin</allow_inactive>
      <allow_active>auth_admin</allow_active>
    </defaults>
    <annotate key="org.freedesktop.policykit.exec.path">/usr/bin/{b.id}-installer</annotate>
  </action>
</policyconfig>
"""


def desktop_version(src: Path) -> str:
    """dots commit + digest of the distribution layer: the updater redeploys
    the desktop configuration when either changes."""
    shipped = src / "desktop" / "VERSION"
    if shipped.is_file():
        return shipped.read_text().strip()
    commit = "unknown"
    res = subprocess.run(["git", "-C", str(src), "ls-tree", "HEAD", "desktop/dots"], capture_output=True, text=True)
    if res.returncode == 0 and res.stdout.split():
        commit = res.stdout.split()[2]
    return f"{commit}+{tree_digest(src / 'desktop' / 'overlay')[:12]}"


def tree_digest(root: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        if p.is_file() and "__pycache__" not in p.parts:
            h.update(p.relative_to(root).as_posix().encode() + b"\0" + p.read_bytes() + b"\0")
    return h.hexdigest()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Install one component of the distribution into a staging directory.")
    p.add_argument("component", nargs="?", choices=COMPONENTS)
    p.add_argument("destdir", nargs="?")
    p.add_argument("--list", action="store_true")
    a = p.parse_args(argv)
    if a.list or not a.component:
        print("\n".join(COMPONENTS))
        return 0
    if not a.destdir:
        p.error("destdir is required")
    Stage(Path(a.destdir), load_branding()).run(a.component)
    return 0


if __name__ == "__main__":
    sys.exit(main())
