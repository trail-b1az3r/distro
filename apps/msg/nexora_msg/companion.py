"""The link to the Nexora Messages companion app on the iPhone (apps/msg/ios): its contacts, with photos, and
sending pictures (and texts) through Messages.

iOS lets no app read Messages, so the companion cannot see the conversations; what it can do is read the address
book (with permission) and fill in a message with a picture for you to send with one tap. It stays reachable in the
background by playing silence (as SideStore does).

The connection is TCP, over the USB cable (usbmuxd) or the local network (Bonjour, _nexoramsg._tcp), on port 47800,
and it is encrypted: each side has an X25519 key; the shared secret makes a ChaCha20-Poly1305 key for each
connection (with a fresh nonce from each side), and a six-digit code both sides show the first time, which you
confirm on the phone, pairs them. Frames: a 4-byte big-endian length, then JSON (the hello) or ciphertext.
"""

from __future__ import annotations

import base64
import itertools
import json
import os
import socket
import struct
import subprocess
import threading
from collections.abc import Callable
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from . import paths, usbmux

PORT = 47800
SERVICE = "_nexoramsg._tcp"
MAX_FRAME = 64 * 1024 * 1024


class CompanionError(RuntimeError):
    pass


def hkdf(secret: bytes, salt: bytes, info: bytes, length: int) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=length, salt=salt or None, info=info).derive(secret)


def pairing_code(shared: bytes) -> str:
    return f"{int.from_bytes(hkdf(shared, b'', b'nexora-msg v1 code', 4), 'big') % 1_000_000:06d}"


def session_key(shared: bytes, desktop_nonce: bytes, phone_nonce: bytes) -> bytes:
    return hkdf(shared, desktop_nonce + phone_nonce, b"nexora-msg v1 key", 32)


def nonce(direction: bytes, counter: int) -> bytes:
    return direction + counter.to_bytes(8, "big")


def identity(path: Path | None = None) -> X25519PrivateKey:
    """This computer's key, made once."""
    path = path or paths.data_dir() / "identity.key"
    if path.exists():
        return X25519PrivateKey.from_private_bytes(path.read_bytes())
    key = X25519PrivateKey.generate()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(key.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
                                  serialization.NoEncryption()))
    return key


def public_bytes(key: X25519PrivateKey) -> bytes:
    return key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


class Channel:
    """Frames, then encrypted frames once the hello is done."""

    def __init__(self, sock: socket.socket, send_dir: bytes, recv_dir: bytes):
        self.sock = sock
        self.send_dir, self.recv_dir = send_dir, recv_dir
        self.aead: ChaCha20Poly1305 | None = None
        self.sent = self.received = 0
        self.wlock = threading.Lock()

    def _read(self, n: int) -> bytes:
        data = b""
        while len(data) < n:
            chunk = self.sock.recv(n - len(data))
            if not chunk:
                raise CompanionError("the iPhone closed the connection")
            data += chunk
        return data

    def send(self, obj: dict) -> None:
        data = json.dumps(obj).encode()
        with self.wlock:
            if self.aead is not None:
                data = self.aead.encrypt(nonce(self.send_dir, self.sent), data, None)
                self.sent += 1
            self.sock.sendall(struct.pack(">I", len(data)) + data)

    def recv(self) -> dict:
        (length,) = struct.unpack(">I", self._read(4))
        if length > MAX_FRAME:
            raise CompanionError("frame too large")
        data = self._read(length)
        if self.aead is not None:
            try:
                data = self.aead.decrypt(nonce(self.recv_dir, self.received), data, None)
            except Exception:  # noqa: BLE001 - InvalidTag
                raise CompanionError("a message failed its check (wrong key, or tampered with)") from None
            self.received += 1
        return json.loads(data)


class Companion:
    def __init__(self, key: X25519PrivateKey | None = None, name: str | None = None,
                 on_event: Callable[[dict], None] | None = None, on_close: Callable[[str], None] | None = None):
        self.key = key or identity()
        self.name = name or socket.gethostname()
        self.on_event = on_event or (lambda e: None)
        self.on_close = on_close or (lambda reason: None)
        self.channel: Channel | None = None
        self.code = ""
        self.phone = ""
        self.paired = False
        self.ids = itertools.count(1)
        self.pending: dict[int, dict] = {}
        self.cond = threading.Condition()
        self.reader: threading.Thread | None = None

    # ── connecting ──
    def connect_usb(self, udid: str = "") -> None:
        for dev in usbmux.devices():
            if not udid or dev["udid"] == udid:
                self.start(usbmux.connect(dev["id"], PORT))
                return
        raise CompanionError("no iPhone on the cable")

    def connect_tcp(self, host: str, port: int = PORT) -> None:
        try:
            self.start(socket.create_connection((host, port), timeout=8))
        except OSError as error:
            raise CompanionError(f"could not reach the iPhone at {host}: {error}") from None

    def start(self, sock: socket.socket) -> None:
        sock.settimeout(30)
        ch = Channel(sock, b"D2P\0", b"P2D\0")
        mine = os.urandom(16)
        ch.send({"hello": "nexora-msg", "v": 1, "pub": base64.b64encode(public_bytes(self.key)).decode(),
                 "nonce": base64.b64encode(mine).decode(), "name": self.name})
        hello = ch.recv()
        if hello.get("hello") != "nexora-msg-ios":
            raise CompanionError("that is not the Nexora Messages app")
        peer = X25519PublicKey.from_public_bytes(base64.b64decode(hello["pub"]))
        shared = self.key.exchange(peer)
        self.code = pairing_code(shared)
        self.phone = hello.get("name", "iPhone")
        self.paired = bool(hello.get("paired"))
        ch.aead = ChaCha20Poly1305(session_key(shared, mine, base64.b64decode(hello["nonce"])))
        sock.settimeout(None)
        self.channel = ch
        self.reader = threading.Thread(target=self._read_loop, daemon=True, name="companion")
        self.reader.start()

    def wait_paired(self, timeout: float = 120) -> bool:
        """Until the code is confirmed on the phone (it sends {"event": "paired"})."""
        with self.cond:
            self.cond.wait_for(lambda: self.paired or self.channel is None, timeout)
        return self.paired

    def _read_loop(self) -> None:
        reason = "closed"
        try:
            while self.channel is not None:
                msg = self.channel.recv()
                if "event" in msg:
                    if msg["event"] == "paired":
                        with self.cond:
                            self.paired = True
                            self.cond.notify_all()
                    self.on_event(msg)
                elif "id" in msg:
                    with self.cond:
                        self.pending[msg["id"]] = msg
                        self.cond.notify_all()
        except (CompanionError, OSError, ValueError) as error:
            reason = str(error)
        finally:
            with self.cond:
                self.channel = None
                self.cond.notify_all()
            self.on_close(reason)

    def request(self, op: str, timeout: float = 120, **args):
        if self.channel is None:
            raise CompanionError("not connected to the iPhone")
        if not self.paired:
            raise CompanionError("confirm the pairing code on the iPhone first")
        rid = next(self.ids)
        self.channel.send({"id": rid, "op": op, **args})
        with self.cond:
            if not self.cond.wait_for(lambda: rid in self.pending or self.channel is None, timeout):
                raise CompanionError("the iPhone did not answer")
            reply = self.pending.pop(rid, None)
        if reply is None:
            raise CompanionError("the connection to the iPhone closed")
        if not reply.get("ok"):
            raise CompanionError(reply.get("error", "failed"))
        return reply.get("data")

    def close(self) -> None:
        ch, self.channel = self.channel, None
        if ch is not None:
            try:
                ch.sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            ch.sock.close()

    # ── what it does ──
    def contacts(self) -> list[dict]:
        return self.request("contacts", timeout=300) or []

    def send(self, to: list[str], text: str = "", image: Path | None = None) -> dict:
        args: dict = {"to": to, "text": text}
        if image is not None:
            args.update(image=base64.b64encode(image.read_bytes()).decode(), filename=image.name)
        return self.request("send", timeout=600, **args) or {}


def discover(timeout: float = 4) -> list[dict]:
    """Companion apps on the local network (Bonjour, through Avahi)."""
    try:
        out = subprocess.run(["avahi-browse", "-rpt", SERVICE], capture_output=True, text=True, timeout=timeout + 4,
                             check=False).stdout
    except (OSError, subprocess.TimeoutExpired):
        return []
    found = {}
    for line in out.splitlines():
        parts = line.split(";")
        if parts[0] == "=" and len(parts) >= 9:
            name, host, addr, port = parts[3], parts[6], parts[7], parts[8]
            found.setdefault(name, {"name": name.replace("\\032", " "), "host": addr or host, "port": int(port)})
    return list(found.values())
