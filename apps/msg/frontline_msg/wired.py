"""The iPhone over a cable: libimobiledevice makes a local backup (incremental after the first), and the Rust store
reads its messages, pictures and contacts. This is the whole history; Bluetooth adds what arrives in between.

The phone asks "Trust This Computer?" the first time; tap Trust and enter its passcode.
"""

from __future__ import annotations

import plistlib
import re
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

from . import paths


class WiredError(RuntimeError):
    pass


def _run(args: list[str], timeout: float = 20) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
    except FileNotFoundError:
        raise WiredError(f"{args[0]} is missing: install libimobiledevice (and usbmuxd)") from None
    except subprocess.TimeoutExpired:
        raise WiredError(f"{args[0]} did not answer") from None


def available() -> bool:
    return shutil.which("idevicebackup2") is not None


def devices() -> list[dict]:
    """iPhones on the cable (and, once paired over the cable, on the same Wi-Fi: libimobiledevice's -n)."""
    out = []
    for flag, link in (("-l", "usb"), ("-n", "wifi")):
        result = _run(["idevice_id", flag], timeout=8)
        for udid in result.stdout.split():
            if any(d["udid"] == udid for d in out):
                continue
            name = _run(["ideviceinfo", "-u", udid, *(["-n"] if link == "wifi" else []), "-k", "DeviceName"]).stdout.strip()
            out.append({"udid": udid, "name": name or "iPhone", "link": link})
    return out


def pair(udid: str) -> str:
    """'' when paired; otherwise what to do on the phone."""
    if _run(["idevicepair", "-u", udid, "validate"]).returncode == 0:
        return ""
    result = _run(["idevicepair", "-u", udid, "pair"], timeout=60)
    if result.returncode == 0:
        return ""
    text = (result.stdout + result.stderr).lower()
    if "passcode" in text:
        return "Unlock the iPhone, then try again."
    if "dialog" in text or "trust" in text or "pending" in text:
        return "Tap \"Trust\" on the iPhone and enter its passcode, then try again."
    return (result.stderr or result.stdout).strip() or "pairing failed"


def encrypted(backup: Path) -> bool:
    try:
        with open(backup / "Manifest.plist", "rb") as f:
            return bool(plistlib.load(f).get("IsEncrypted"))
    except (OSError, plistlib.InvalidFileException, ValueError):
        return False


PROGRESS = re.compile(r"(\d{1,3})% Finished")


def backup(udid: str, link: str = "usb", progress: Callable[[int, str], None] | None = None) -> Path:
    """Makes (or brings up to date) the phone's backup; returns its folder."""
    progress = progress or (lambda pct, text: None)
    message = pair(udid) if link == "usb" else ""
    if message:
        raise WiredError(message)
    root = paths.backups_dir()
    target = root / udid
    if target.exists() and encrypted(target):
        raise WiredError("The iPhone makes encrypted backups (\"Encrypt local backup\" is on). Turn it off in Finder "
                         "or iTunes, or with: idevicebackup2 -i encryption off; frontline-msg reads unencrypted ones.")
    args = ["idevicebackup2", "-u", udid, *(["-n"] if link == "wifi" else []), "backup", str(root)]
    try:
        proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    except FileNotFoundError:
        raise WiredError("idevicebackup2 is missing: install libimobiledevice") from None
    tail: list[str] = []
    assert proc.stdout is not None
    for line in proc.stdout:
        line = line.strip()
        if not line:
            continue
        tail = (tail + [line])[-6:]
        match = PROGRESS.search(line)
        if match:
            progress(int(match.group(1)), "Backing up")
        elif line.startswith(("Receiving files", "Backup Successful", "Requesting backup", "Full backup mode")):
            progress(-1, line)
    if proc.wait() != 0:
        detail = " ".join(tail)
        if "encrypted" in detail.lower() or "password" in detail.lower():
            raise WiredError("The backup is encrypted; frontline-msg reads unencrypted ones.")
        raise WiredError(f"the backup failed: {detail}")
    return target
