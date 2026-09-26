"""``<id>-privileged``: the only root entry point of the graphical apps.

Run through pkexec (polkit asks for the administrator password). It accepts a
short allowlist of actions with validated arguments, so the GUI never runs
arbitrary commands as root.

    <id>-privileged firewall on|off
    <id>-privileged mac-randomization on|off
    <id>-privileged location on|off
    <id>-privileged coredumps on|off
    <id>-privileged snapshot [description]
    <id>-privileged snapshot-timeline on|off
    <id>-privileged install <package>...
    <id>-privileged update-system
    <id>-privileged gpu-configure
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

from .branding import load as load_branding

PKG_RE = re.compile(r"^[a-z0-9@._+-]+$")


def _run(cmd: list[str]) -> int:
    print("$ " + " ".join(cmd), flush=True)
    return subprocess.call(cmd)


def _toggle_file(path: Path, on: bool, content: str) -> None:
    if on:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    elif path.exists():
        path.unlink()


def main(argv: list[str] | None = None) -> int:
    b = load_branding()
    args = list(sys.argv[1:] if argv is None else argv)
    if os.geteuid() != 0:
        print("must run as root (through pkexec)", file=sys.stderr)
        return 1
    if not args:
        print(__doc__)
        return 2
    action, rest = args[0], args[1:]

    def onoff() -> bool:
        if len(rest) != 1 or rest[0] not in ("on", "off"):
            raise SystemExit(f"{action}: expected on|off")
        return rest[0] == "on"

    if action == "firewall":
        return _run(["systemctl", "enable" if onoff() else "disable", "--now", "nftables.service"])
    if action == "mac-randomization":
        _toggle_file(Path(f"/etc/NetworkManager/conf.d/90-{b.id}-mac.conf"), onoff(),
                     "# Random MAC while scanning; a stable per-network MAC when connected.\n"
                     "[device]\nwifi.scan-rand-mac-address=yes\n\n"
                     "[connection]\nwifi.cloned-mac-address=stable\nethernet.cloned-mac-address=stable\n")
        return _run(["nmcli", "general", "reload"])
    if action == "location":
        return _run(["systemctl", "unmask" if onoff() else "mask", "geoclue.service"])
    if action == "coredumps":
        on = onoff()
        _toggle_file(Path(f"/etc/systemd/coredump.conf.d/90-{b.id}.conf"), not on,
                     "# Crash dumps are not stored (privacy setting from the Welcome app).\n[Coredump]\nStorage=none\n")
        return 0
    if action == "snapshot":
        desc = " ".join(rest)[:80] or "Manual snapshot"
        if not re.match(r"^[\w .,:()-]*$", desc):
            raise SystemExit("snapshot: invalid description")
        return _run(["snapper", "-c", "root", "create", "-d", desc])
    if action == "snapshot-timeline":
        verb = "enable" if onoff() else "disable"
        return _run(["systemctl", verb, "--now", "snapper-timeline.timer", "snapper-cleanup.timer"])
    if action == "install":
        if not rest or not all(PKG_RE.match(p) for p in rest):
            raise SystemExit("install: invalid package name")
        return _run(["pacman", "-S", "--needed", "--noconfirm", *rest])
    if action == "update-system":
        return _run(["pacman", "-Syu", "--noconfirm"])
    if action == "gpu-configure":
        return _run([f"/usr/bin/{b.cli}", "gpu", "configure", "--yes"])
    print(f"unknown action {action!r}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
