"""Tailscale: the devices on your tailnet, so the iPhone's companion app and other computers' remote desktops are
found from anywhere, not just on the same Wi-Fi."""

from __future__ import annotations

import json
import shutil
import socket
import subprocess
from concurrent.futures import ThreadPoolExecutor


def available() -> bool:
    return shutil.which("tailscale") is not None


def status() -> dict:
    try:
        out = subprocess.run(["tailscale", "status", "--json"], capture_output=True, text=True, timeout=6, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return {}
    if out.returncode != 0:
        return {}
    try:
        return json.loads(out.stdout)
    except ValueError:
        return {}


def peers(data: dict | None = None) -> list[dict]:
    """Online devices on the tailnet: {name, host (its MagicDNS name, or its address), address, os}."""
    data = status() if data is None else data
    out = []
    for peer in (data.get("Peer") or {}).values():
        if not peer.get("Online"):
            continue
        ips = peer.get("TailscaleIPs") or []
        v4 = next((ip for ip in ips if "." in ip), ips[0] if ips else "")
        dns = (peer.get("DNSName") or "").rstrip(".")
        out.append({"name": peer.get("HostName") or dns.split(".")[0] or v4, "host": v4 or dns, "dns": dns,
                    "address": v4, "os": (peer.get("OS") or "").lower()})
    return sorted(out, key=lambda p: p["name"].lower())


def answers(host: str, port: int, timeout: float = 1.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def listening(port: int, os_names: tuple[str, ...] = (), data: dict | None = None) -> list[dict]:
    """The online peers (of these operating systems, if given) that answer on a port."""
    candidates = [p for p in peers(data) if not os_names or p["os"] in os_names]
    if not candidates:
        return []
    with ThreadPoolExecutor(max_workers=16) as pool:
        ok = list(pool.map(lambda p: answers(p["host"], port), candidates))
    return [p for p, yes in zip(candidates, ok) if yes]
