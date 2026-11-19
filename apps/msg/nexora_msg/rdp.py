"""The remote desktop viewer: another computer's desktop, shared by its rdp-express server (the nexora-rdp-express
package), over the local network or Tailscale.

The protocol is rdp-express's own (apps/rdp-express/src/link.rs). A plaintext hello (X25519 keys and nonces) is
followed by ChaCha20-Poly1305 frames. The first time, the server's one-time pairing code (`rdp-express pair`) is
mixed into the key; after that the server knows this viewer's key. The server sends JPEG rectangles of what
changed; the viewer acknowledges each frame (so a slow link gets fewer frames, not a growing delay) and sends the
pointer and keys back.
"""

from __future__ import annotations

import base64
import json
import os
import socket
import struct
import threading
from collections.abc import Callable
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from . import paths

PORT = 47801
MAX_FRAME = 64 * 1024 * 1024
BTN_LEFT, BTN_RIGHT, BTN_MIDDLE = 0x110, 0x111, 0x112


class RemoteError(RuntimeError):
    pass


def derive(shared: bytes, code: str | None, client_nonce: bytes, server_nonce: bytes) -> bytes:
    ikm = shared + (code.encode() if code else b"")
    info = b"rdp-express v1 pair" if code else b"rdp-express v1 key"
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=client_nonce + server_nonce, info=info).derive(ikm)


def identity(path: Path | None = None) -> X25519PrivateKey:
    path = path or paths.data_dir() / "remote-identity.key"
    if path.exists():
        return X25519PrivateKey.from_private_bytes(path.read_bytes())
    key = X25519PrivateKey.generate()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(key.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
                                  serialization.NoEncryption()))
    return key


class Sealer:
    def __init__(self, key: bytes, direction: bytes):
        self.aead = ChaCha20Poly1305(key)
        self.direction = direction
        self.counter = 0

    def _nonce(self) -> bytes:
        return self.direction + self.counter.to_bytes(8, "big")

    def seal(self, plain: bytes) -> bytes:
        out = self.aead.encrypt(self._nonce(), plain, None)
        self.counter += 1
        return out

    def open(self, sealed: bytes) -> bytes:
        try:
            out = self.aead.decrypt(self._nonce(), sealed, None)
        except Exception:  # noqa: BLE001 - InvalidTag
            raise RemoteError("a frame failed its check (a wrong pairing code, or tampered with)") from None
        self.counter += 1
        return out


def _read(sock: socket.socket, n: int) -> bytes:
    data = b""
    while len(data) < n:
        chunk = sock.recv(n - len(data))
        if not chunk:
            raise RemoteError("the remote computer closed the connection")
        data += chunk
    return data


def read_frame(sock: socket.socket) -> bytes:
    (length,) = struct.unpack(">I", _read(sock, 4))
    if length > MAX_FRAME:
        raise RemoteError("frame too large")
    return _read(sock, length)


def write_frame(sock: socket.socket, body: bytes) -> None:
    sock.sendall(struct.pack(">I", len(body)) + body)


def parse_frame(m: bytes) -> tuple[int, int, int, list[tuple[int, int, int, int, bytes]]]:
    """A frame message: (number, width, height, [(x, y, w, h, jpeg)])."""
    number, width, height, count = struct.unpack(">IHHH", m[1:11])
    rects, at = [], 11
    for _ in range(count):
        x, y, w, h, length = struct.unpack(">HHHHI", m[at:at + 12])
        at += 12
        rects.append((x, y, w, h, m[at:at + length]))
        at += length
    return number, width, height, rects


class Remote:
    """One connection to a remote desktop. on_hello(info) once, on_frame(number, width, height, rects) per frame,
    on_close(reason) at the end; all from the reading thread."""

    def __init__(self, key: X25519PrivateKey | None = None, name: str | None = None,
                 on_hello: Callable[[dict], None] | None = None,
                 on_frame: Callable[[int, int, int, list], None] | None = None,
                 on_close: Callable[[str], None] | None = None):
        self.identity = key or identity()
        self.name = name or socket.gethostname()
        self.on_hello = on_hello or (lambda info: None)
        self.on_frame = on_frame or (lambda *a: None)
        self.on_close = on_close or (lambda reason: None)
        self.sock: socket.socket | None = None
        self.out: Sealer | None = None
        self.info: dict = {}
        self.server = ""
        self.wlock = threading.Lock()

    def connect(self, host: str, port: int = PORT, code: str = "") -> None:
        try:
            sock = socket.create_connection((host, port), timeout=10)
        except OSError as error:
            raise RemoteError(f"could not reach {host}: {error}") from None
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        mine = os.urandom(16)
        pub = self.identity.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        write_frame(sock, json.dumps({"hello": "rdp-express", "v": 1, "pub": base64.b64encode(pub).decode(),
                                      "nonce": base64.b64encode(mine).decode(), "name": self.name}).encode())
        hello = json.loads(read_frame(sock))
        if hello.get("error"):
            sock.close()
            raise RemoteError(hello["error"])
        if hello.get("hello") != "rdp-express-server":
            sock.close()
            raise RemoteError("that is not an rdp-express server")
        self.server = hello.get("name", host)
        code = "".join(ch for ch in code if ch.isdigit())
        if not hello.get("known") and not code:
            sock.close()
            raise RemoteError(f"{self.server} does not know this computer yet: run `rdp-express pair` there and "
                              "enter the code it shows")
        shared = self.identity.exchange(X25519PublicKey.from_public_bytes(base64.b64decode(hello["pub"])))
        key = derive(shared, None if hello.get("known") else code, mine, base64.b64decode(hello["nonce"]))
        self.out, inbound = Sealer(key, b"C2S\0"), Sealer(key, b"S2C\0")
        self.sock = sock
        self.send(b"\x10" + json.dumps({"name": self.name}).encode())
        try:
            first = inbound.open(read_frame(sock))
        except (RemoteError, OSError) as error:
            sock.close()
            self.sock = None
            raise RemoteError("the pairing code was wrong (or it ran out): ask for a new one with "
                              "`rdp-express pair`") if not hello.get("known") else error from None
        if first[:1] == b"\x03":
            sock.close()
            raise RemoteError(json.loads(first[1:]).get("error", "the remote desktop failed"))
        self.info = json.loads(first[1:])
        sock.settimeout(None)
        self.on_hello(self.info)
        threading.Thread(target=self._read_loop, args=(inbound,), daemon=True, name="remote").start()

    def _read_loop(self, inbound: Sealer) -> None:
        reason = "closed"
        try:
            while self.sock is not None:
                m = inbound.open(read_frame(self.sock))
                if m[:1] == b"\x02":
                    number, width, height, rects = parse_frame(m)
                    self.on_frame(number, width, height, rects)
                    self.send(b"\x15" + struct.pack(">I", number))
                elif m[:1] == b"\x01":
                    self.info = json.loads(m[1:])
                    self.on_hello(self.info)
                elif m[:1] == b"\x03":
                    reason = json.loads(m[1:]).get("error", reason)
                    break
        except (RemoteError, OSError, ValueError, struct.error) as error:
            reason = str(error)
        finally:
            self.close()
            self.on_close(reason)

    def send(self, plain: bytes) -> None:
        sock, out = self.sock, self.out
        if sock is None or out is None:
            return
        with self.wlock:
            try:
                write_frame(sock, out.seal(plain))
            except OSError:
                pass

    # ── input ──
    def pointer(self, x: int, y: int) -> None:
        self.send(struct.pack(">BHH", 0x11, max(0, x), max(0, y)))

    def button(self, button: int, pressed: bool) -> None:
        self.send(struct.pack(">BIB", 0x12, button, 1 if pressed else 0))

    def scroll(self, vertical: int, horizontal: int = 0) -> None:
        self.send(struct.pack(">Bhh", 0x13, vertical, horizontal))

    def key(self, evdev: int, pressed: bool) -> None:
        self.send(struct.pack(">BIB", 0x14, evdev, 1 if pressed else 0))

    def settings(self, quality: int | None = None, fps: int | None = None) -> None:
        self.send(b"\x16" + json.dumps({k: v for k, v in (("quality", quality), ("fps", fps)) if v}).encode())

    def refresh(self) -> None:
        self.send(b"\x17")

    def close(self) -> None:
        sock, self.sock = self.sock, None
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            sock.close()


def discover() -> list[dict]:
    """Computers on the tailnet with a remote desktop to share."""
    from . import tailscale
    return tailscale.listening(PORT, ("linux", "macos", "windows", "freebsd"))
