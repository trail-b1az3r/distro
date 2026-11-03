"""One wpa_supplicant per Wi-Fi device, run and watched by nmxd, spoken to over its control socket.

Networks are given to it over the socket (ADD_NETWORK / SET_NETWORK), never written to a file, so passwords stay in
memory. Events (CTRL-EVENT-*) come on a second, attached socket.
"""

from __future__ import annotations

import itertools
import os
import socket
import subprocess
import tempfile
import threading
import time
from pathlib import Path

RUN = Path(os.environ.get("NMX_RUN", "/run/nmx"))
CTRL_DIR = RUN / "wpa"
_counter = itertools.count()


class WpaError(Exception):
    pass


class Control:
    """A wpa_supplicant control socket (a Unix datagram socket bound at our end too)."""

    def __init__(self, iface: str, ctrl_dir: Path = CTRL_DIR):
        self.path = str(ctrl_dir / iface)
        self.local = str(RUN / f"ctrl-{os.getpid()}-{next(_counter)}")
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        try:
            os.unlink(self.local)
        except FileNotFoundError:
            pass
        self.sock.bind(self.local)
        self.sock.connect(self.path)
        self.lock = threading.Lock()

    def request(self, command: str, timeout: float = 10.0) -> str:
        with self.lock:
            self.sock.settimeout(timeout)
            self.sock.send(command.encode())
            deadline = time.monotonic() + timeout
            while True:
                data = self.sock.recv(65536).decode(errors="replace")
                # Unsolicited events (when attached) start with "<N>"; skip them while waiting for the reply.
                if data.startswith("<") and ">" in data[:4]:
                    if time.monotonic() > deadline:
                        raise TimeoutError(command)
                    continue
                return data

    def ok(self, command: str) -> None:
        reply = self.request(command).strip()
        if reply != "OK":
            raise WpaError(f"{command.split(' ')[0]}: {reply}")

    def recv_event(self, timeout: float | None) -> str | None:
        self.sock.settimeout(timeout)
        try:
            data = self.sock.recv(65536).decode(errors="replace")
        except (socket.timeout, TimeoutError):
            return None
        if data.startswith("<") and ">" in data[:4]:
            return data[data.index(">") + 1:].strip()
        return None

    def close(self) -> None:
        try:
            self.sock.close()
        finally:
            try:
                os.unlink(self.local)
            except FileNotFoundError:
                pass


def parse_scan_results(text: str) -> list[dict]:
    """SCAN_RESULTS: 'bssid / frequency / signal level / flags / ssid', tab separated."""
    out = []
    for line in text.splitlines()[1:]:
        parts = line.split("\t")
        if len(parts) < 4:
            continue
        bssid, freq, level, flags = parts[:4]
        ssid = decode_ssid(parts[4]) if len(parts) > 4 else ""
        try:
            out.append({"bssid": bssid.lower(), "freq": int(freq), "level": int(level), "flags": flags, "ssid": ssid})
        except ValueError:
            continue
    return out


def decode_ssid(text: str) -> str:
    """wpa_supplicant prints SSIDs with printf escapes (\\xNN, \\\\, \\")."""
    raw = bytearray()
    i = 0
    while i < len(text):
        c = text[i]
        if c == "\\" and i + 1 < len(text):
            n = text[i + 1]
            if n == "x" and i + 3 < len(text):
                try:
                    raw.append(int(text[i + 2:i + 4], 16))
                    i += 4
                    continue
                except ValueError:
                    pass
            raw += {"n": b"\n", "r": b"\r", "t": b"\t", "e": b"\x1b"}.get(n, n.encode())
            i += 2
            continue
        raw += c.encode()
        i += 1
    return raw.decode("utf-8", errors="replace")


def parse_status(text: str) -> dict:
    return dict(line.split("=", 1) for line in text.splitlines() if "=" in line)


def parse_event(line: str) -> tuple[str, dict]:
    """'CTRL-EVENT-SSID-TEMP-DISABLED id=0 ssid="x" auth_failures=1 duration=10 reason=WRONG_KEY' ->
    ('CTRL-EVENT-SSID-TEMP-DISABLED', {...}). Quoted values keep their spaces."""
    name, _, rest = line.partition(" ")
    fields: dict[str, str] = {}
    i = 0
    positional = 0
    while i < len(rest):
        while i < len(rest) and rest[i] == " ":
            i += 1
        if i >= len(rest):
            break
        j = i
        while j < len(rest) and rest[j] not in " =":
            j += 1
        if j < len(rest) and rest[j] == "=":
            key = rest[i:j]
            j += 1
            if j < len(rest) and rest[j] in "'\"":
                quote = rest[j]
                end = rest.find(quote, j + 1)
                end = len(rest) if end < 0 else end
                fields[key] = rest[j + 1:end]
                i = end + 1
            else:
                end = rest.find(" ", j)
                end = len(rest) if end < 0 else end
                fields[key] = rest[j:end]
                i = end
        else:
            fields[f"_{positional}"] = rest[i:j]
            positional += 1
            i = j
    return name, fields


class Supplicant:
    """A supervised wpa_supplicant for one interface."""

    def __init__(self, iface: str, driver: str = "nl80211,wext"):
        self.iface = iface
        self.driver = driver
        self.proc: subprocess.Popen | None = None
        self.ctrl: Control | None = None
        self.events: Control | None = None

    def config_text(self) -> str:
        return (
            f"ctrl_interface=DIR={CTRL_DIR} GROUP=root\n"
            "update_config=0\n"
            "ap_scan=1\n"
            "p2p_disabled=1\n"
            # SAE: hash-to-element and hunting-and-pecking both, for every AP generation.
            "sae_pwe=2\n"
            # Optional PMF globally; networks that require it say so themselves.
            "pmf=1\n"
            "autoscan=exponential:3:300\n"
        )

    def start(self, timeout: float = 10.0) -> None:
        self.stop()
        CTRL_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, conf = tempfile.mkstemp(prefix=f"wpa-{self.iface}-", suffix=".conf", dir=RUN)
        with os.fdopen(fd, "w") as handle:
            handle.write(self.config_text())
        try:
            os.unlink(CTRL_DIR / self.iface)
        except FileNotFoundError:
            pass
        self.proc = subprocess.Popen(
            ["wpa_supplicant", "-i", self.iface, "-D", self.driver, "-c", conf, "-s"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.monotonic() + timeout
        while not (CTRL_DIR / self.iface).exists():
            if self.proc.poll() is not None or time.monotonic() > deadline:
                raise WpaError(f"wpa_supplicant did not start on {self.iface}")
            time.sleep(0.05)
        self.ctrl = Control(self.iface)
        self.events = Control(self.iface)
        self.events.ok("ATTACH")
        os.unlink(conf)

    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def stop(self) -> None:
        for control in (self.events, self.ctrl):
            if control is not None:
                try:
                    if control is self.ctrl:
                        control.request("TERMINATE", timeout=2)
                except OSError:
                    pass
                control.close()
        self.ctrl = self.events = None
        if self.proc is not None:
            try:
                self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
            self.proc = None

    # ── requests ──
    def request(self, command: str, timeout: float = 10.0) -> str:
        if self.ctrl is None:
            raise WpaError(f"wpa_supplicant is not running on {self.iface}")
        return self.ctrl.request(command, timeout)

    def scan(self) -> None:
        reply = self.request("SCAN").strip()
        if reply not in ("OK", "FAIL-BUSY"):
            raise WpaError(f"SCAN: {reply}")

    def scan_results(self) -> list[dict]:
        return parse_scan_results(self.request("SCAN_RESULTS"))

    def status(self) -> dict:
        return parse_status(self.request("STATUS"))

    def connect(self, fields: dict[str, str]) -> int:
        self.request("REMOVE_NETWORK all")
        nid = int(self.request("ADD_NETWORK").strip())
        for key, value in fields.items():
            self.ctrl.ok(f"SET_NETWORK {nid} {key} {value}")
        self.ctrl.ok(f"SELECT_NETWORK {nid}")
        return nid

    def disconnect(self) -> None:
        self.request("DISCONNECT")
        self.request("REMOVE_NETWORK all")

    def reassociate(self) -> None:
        self.request("REASSOCIATE")
