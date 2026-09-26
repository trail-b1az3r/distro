"""`<cli> system`: what this system is and how it is set up."""

from __future__ import annotations

import os
import platform as pyplatform
import time
from pathlib import Path

from .. import boot, pkg, util
from ..branding import Branding, load as load_branding


def os_release(root: Path = Path("/")) -> dict[str, str]:
    values = {}
    for candidate in (root / "etc/os-release", root / "usr/lib/os-release"):
        if candidate.exists():
            for line in candidate.read_text().splitlines():
                if "=" in line:
                    k, v = line.split("=", 1)
                    values[k] = v.strip('"')
            break
    return values


def uptime() -> str:
    try:
        seconds = float(Path("/proc/uptime").read_text().split()[0])
    except (OSError, ValueError):
        return ""
    days, rem = divmod(int(seconds), 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    parts = ([f"{days}d"] if days else []) + ([f"{hours}h"] if hours or days else []) + [f"{minutes}m"]
    return " ".join(parts)


def gather(branding: Branding | None = None) -> list[tuple[str, str]]:
    branding = branding or load_branding()
    rel = os_release()
    rec = util.read_json(branding.system_paths().install_record, {}) or {}
    installed = pkg.installed_packages()
    rows = [
        ("OS", rel.get("PRETTY_NAME", branding.pretty_name)),
        ("Based on", "EndeavourOS / Arch Linux"),
        ("Kernel", pyplatform.release()),
        ("Uptime", uptime()),
        ("Desktop", os.environ.get("XDG_CURRENT_DESKTOP") or "Hyprland"),
        ("Session", os.environ.get("XDG_SESSION_TYPE", "")),
        ("Packages", f"{len(installed)} (pacman)"),
    ]
    rc, out = util.run_quiet(["flatpak", "list", "--app", "--columns=application"]) if util.which("flatpak") else (1, "")
    if rc == 0 and out.strip():
        rows.append(("Flatpaks", str(len(out.splitlines()))))
    cfg = boot.load_config(branding=branding)
    if cfg:
        rows.append(("Boot", f"{cfg.bootloader} ({cfg.firmware.upper()})"))
    if rec:
        rows.append(("Profile", rec.get("profile", "")))
        rows.append(("Installed", time.strftime("%Y-%m-%d", time.localtime(rec.get("installed_at", 0)))))
        gpu = rec.get("gpu", {})
        for c in gpu.get("choices", []):
            rows.append(("GPU", f"{c['display_name']} — {c['label']}"))
        ai = rec.get("ai_backend", {})
        if ai:
            rows.append(("AI backend", ai.get("description", "")))
    return [(k, v) for k, v in rows if v]
