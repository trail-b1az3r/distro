"""Optional user-session helpers for stock NetworkManager."""
from __future__ import annotations

import os
import subprocess
import time

from . import portal

INTERVAL = 30
CA_SCAN_INTERVAL = 300
SERVER_CERT_EAP = {"peap", "ttls", "tls", "fast", "teap"}


def run(args: list[str]) -> str:
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=8, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def ensure_system_ca() -> None:
    uuids = run(["nmcli", "-t", "-f", "UUID", "connection", "show"]).splitlines()
    fields = [
        "802-1x.eap", "802-1x.identity", "802-1x.ca-cert", "802-1x.ca-path",
        "802-1x.phase2-ca-cert", "802-1x.phase2-ca-path", "802-1x.system-ca-certs",
        "802-1x.domain-suffix-match"
    ]
    for uuid in uuids:
        if not uuid:
            continue
        values = run(["nmcli", "-g", ",".join(fields), "connection", "show", uuid]).splitlines()
        values += [""] * (len(fields) - len(values))
        values = ["" if value.strip() in ("", "--") else value.strip() for value in values[:8]]
        eap, identity, ca_cert, ca_path, phase2_cert, phase2_path, system_ca, domain_match = values
        methods = {method.strip().lower() for method in eap.split(";") if method.strip()}
        if not methods.intersection(SERVER_CERT_EAP):
            continue
        # Never override an explicit CA or a profile's deliberate system-CA setting.
        if any((ca_cert, ca_path, phase2_cert, phase2_path)) or system_ca.lower() in ("yes", "true", "on"):
            continue
        # Validate the server name as well as its chain. Prefer the explicit NM setting;
        # otherwise infer the realm suffix from an identity such as alice@university.edu.
        domain = domain_match
        if not domain and "@" in identity:
            candidate = identity.rsplit("@", 1)[1].strip().rstrip(".")
            if "." in candidate and any(char.isalpha() for char in candidate) and all(part and part.replace("-", "").isalnum() for part in candidate.split(".")):
                domain = candidate
        if not domain:
            continue
        try:
            result = subprocess.run(["nmcli", "connection", "modify", uuid,
                                      "802-1x.system-ca-certs", "yes",
                                      "802-1x.domain-suffix-match", domain],
                                    capture_output=True, text=True, timeout=8, check=False)
        except (OSError, subprocess.TimeoutExpired):
            continue
        if result.returncode == 0:
            print(f"nmx-nm-assist: enabled system CA trust and domain matching for 802.1X profile {uuid}", flush=True)


def open_portal_if_needed(state: str, last_url: str) -> str:
    if state not in ("portal", "limited", "unknown"):
        return ""
    kind, url = portal.probe()
    if kind != "portal" or not url or url == last_url:
        return last_url
    env = os.environ.copy()
    environment = run(["systemctl", "--user", "show-environment"])
    for line in environment.splitlines():
        key, sep, value = line.partition("=")
        if sep and key and key.replace("_", "").isalnum():
            env[key] = value
    if not (env.get("WAYLAND_DISPLAY") or env.get("DISPLAY")):
        return last_url
    try:
        subprocess.Popen(["xdg-open", url], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        return last_url
    return url


def main() -> int:
    while run(["nmcli", "-t", "-f", "RUNNING", "general"]) != "running":
        time.sleep(5)
    last_portal = ""
    last_ca_scan = 0.0
    while True:
        state = run(["nmcli", "-t", "-f", "CONNECTIVITY", "general"])
        last_portal = open_portal_if_needed(state, last_portal)
        now = time.monotonic()
        if now - last_ca_scan >= CA_SCAN_INTERVAL:
            ensure_system_ca()
            last_ca_scan = now
        time.sleep(INTERVAL)
