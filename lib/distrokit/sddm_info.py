"""System information for the login screen (SDDM theme, branding/sddm/Main.qml).

The greeter cannot run programs, so this runs before SDDM starts (<id>-sddm-info.service, pulled in by a drop-in on
sddm.service): it runs fastfetch with the distribution's own config (never a user's or Halcyon's), keeps the lines that
mean something before anyone has logged in, and writes them as a small QML file the theme loads:

    /var/lib/<id>/sddm/SystemInfo.qml    Item { host, rows: [[key, value], ...], generated }
"""
from __future__ import annotations

import json
import re
import os
import platform
import shutil
import socket
import subprocess
import time
from pathlib import Path

from .branding import load as load_branding

ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")

# Lines about a logged-in session (or nobody's): left out of the login screen.
SKIP = {"terminal", "shell", "uptime", "desktop", "wm", "de", "terminal font", "locale", "title", "colors"}


def fastfetch_rows(config: Path, timeout: float = 15.0) -> list[list[str]]:
    """``Key: value`` lines from fastfetch with ``config`` (its own keys, in its order)."""
    exe = shutil.which("fastfetch")
    if not exe or not config.is_file():
        return []
    try:
        # A tab between key and value whatever the config's separator is, so values can hold anything.
        out = subprocess.run([exe, "--config", str(config), "--logo", "none", "--pipe", "--separator", "\t"],
                             capture_output=True, text=True, timeout=timeout, check=False).stdout
    except (OSError, subprocess.TimeoutExpired):
        return []
    rows = []
    for line in out.splitlines():
        line = ANSI.sub("", line)
        key, sep, value = line.partition("\t")
        key, value = key.strip(), value.strip()
        if not sep or not key or not value or "@" in key or key.lower() in SKIP or set(key) <= {"-"}:
            continue
        rows.append([key, value])
    return rows


def fallback_rows() -> list[list[str]]:
    """Without fastfetch: what the system says about itself."""
    pretty = ""
    try:
        for line in Path("/etc/os-release").read_text().splitlines():
            if line.startswith("PRETTY_NAME="):
                pretty = line.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    rows = [["OS", pretty or platform.system()], ["Kernel", platform.release()]]
    cpu = platform.processor()
    if cpu:
        rows.append(["CPU", cpu])
    return rows


def qml(host: str, rows: list[list[str]]) -> str:
    # json.dumps gives JavaScript string literals, so nothing in the values can break out of them.
    return (
        "// Written by the login screen's system information service; do not edit.\n"
        "import QtQuick\n\n"
        "Item {\n"
        f"    readonly property string host: {json.dumps(host)}\n"
        f"    readonly property var rows: {json.dumps(rows, ensure_ascii=False)}\n"
        f"    readonly property string generated: {json.dumps(time.strftime('%Y-%m-%d %H:%M'))}\n"
        "}\n"
    )


def write(dest: Path, text: str) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(f".{dest.name}.{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.chmod(0o644)
    tmp.replace(dest)


def main(argv: list[str] | None = None) -> int:
    import argparse

    b = load_branding()
    p = argparse.ArgumentParser(description="System information for the login screen")
    p.add_argument("--config", type=Path, default=Path(f"/usr/share/{b.id}/fastfetch.jsonc"),
                   help="fastfetch config (the distribution's)")
    p.add_argument("--out", type=Path, default=Path(f"/var/lib/{b.id}/sddm/SystemInfo.qml"))
    a = p.parse_args(argv)
    rows = fastfetch_rows(a.config) or fallback_rows()
    write(a.out, qml(socket.gethostname(), rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
